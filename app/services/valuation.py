"""Smart AI-driven valuation engine.

Uses an LLM advisor to identify the company's sector profile and select the
most appropriate valuation methodology, then runs all applicable models and
produces a weighted blend.

Valuation methods implemented:
  1. DCF (Discounted Cash Flow) — FCF-based multi-stage projection with bull/bear scenarios
  2. DDM (Dividend Discount Model) — Gordon Growth + H-model hybrid
  3. EV/EBITDA relative — sector-peer enterprise-value multiples
  4. P/E peer relative — earnings-based peer median (with own-multiple & discount-to-peers)
  5. P/B peer relative — book-value-based peer median (with own-multiple & discount-to-peers)
  6. NAV (Net Asset Value) — balance-sheet-based adjusted book value
  7. EPV (Earnings Power Value) — normalised earnings capitalisation
  8. SOTP (Sum-of-the-Parts) — segment-revenue-weighted multiple
  9. Residual Income — excess-return-on-equity capitalisation
 10. ML Ridge regression — cross-sectional multiple prediction
 11. EV/Revenue (P/S) — revenue-based relative valuation
 12. Graham Number — classic Ben Graham intrinsic value formula
 13. Reverse DCF — binary search for market-implied growth rate
 14. Dividend Yield Model — price implied by sector median yield

The LLM advisor examines the company's financials, sector, and narrative
context to assign per-method relevance weights (0–1).  Methods that receive
weight 0 are skipped entirely, saving compute.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
import joblib

from app.config import settings
from app.services.jquants import JQuantsClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if cleaned in {"", "-", "nan", "NaN"}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _pick_value(item: Dict[str, Any], keys: List[str]) -> float | None:
    for key in keys:
        if key in item:
            value = _to_float(item.get(key))
            if value is not None:
                return value
    return None


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _ratio(n: float | None, d: float | None) -> float | None:
    if n is None or d in (None, 0):
        return None
    return n / d


def _median(values: List[float]) -> float | None:
    values = [v for v in values if v is not None]
    if not values:
        return None
    arr = sorted(values)
    mid = len(arr) // 2
    if len(arr) % 2:
        return float(arr[mid])
    return float((arr[mid - 1] + arr[mid]) / 2)


def _percentile(values: List[float], pct: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), pct))


def _clip(v: float, lo: float, hi: float) -> float:
    return float(np.clip(v, lo, hi))


def _fallback_range(value: float) -> Tuple[float, float]:
    return value * 0.85, value * 1.15


def _net_debt(latest: Dict[str, Any]) -> float:
    """Compute net debt: prefer interest-bearing debt - cash, fall back to total liabilities."""
    borrowings = latest.get("borrowings")
    cash = latest.get("cash_equiv") or 0
    if borrowings is not None:
        return max(borrowings - cash, 0)
    # Fallback: total liabilities (less accurate — includes AP, deferred tax, etc.)
    ta = latest.get("total_assets", 0) or 0
    eq = latest.get("equity", 0) or 0
    return max(ta - eq, 0)


def _compute_capm(
    prices: Dict[str, Any],
    risk_free_rate: float = 0.009,
    equity_risk_premium: float = 0.06,
) -> Dict[str, float]:
    """Compute CAPM beta proxy and cost of equity from daily price data."""
    data = prices.get("daily_quotes") or prices.get("data") or []
    if isinstance(data, dict):
        data = [data]
    closes = []
    for q in data:
        c = _to_float(q.get("AdjustmentClose") or q.get("AdjClose") or q.get("Close") or q.get("C"))
        if c is not None and c > 0:
            closes.append(c)
    if len(closes) < 30:
        return {}
    arr = np.array(closes, dtype=float)
    daily_returns = np.diff(arr) / arr[:-1]
    annualised_vol = float(np.std(daily_returns) * np.sqrt(252))
    # Beta proxy: (stock_vol / TOPIX_vol) × assumed correlation
    topix_vol = 0.16
    correlation = 0.70
    beta = (annualised_vol / topix_vol) * correlation
    beta = _clip(beta, 0.3, 2.5)
    cost_of_equity = risk_free_rate + beta * equity_risk_premium
    return {
        "beta": round(beta, 3),
        "risk_free_rate": risk_free_rate,
        "equity_risk_premium": equity_risk_premium,
        "cost_of_equity": round(cost_of_equity, 4),
        "annualised_vol": round(annualised_vol, 4),
    }


# ---------------------------------------------------------------------------
# Japanese sector median multiples (absolute fallback when no peers)
# ---------------------------------------------------------------------------

_SECTOR_MEDIANS = {
    "default":      {"pe": 15.0, "pb": 1.2, "ev_ebitda": 9.0,  "ps": 0.8,  "div_yield": 0.025},
    "bank":         {"pe": 10.0, "pb": 0.5, "ev_ebitda": None, "ps": 1.5,  "div_yield": 0.035},
    "insurance":    {"pe": 12.0, "pb": 0.8, "ev_ebitda": None, "ps": 0.6,  "div_yield": 0.030},
    "real estate":  {"pe": 14.0, "pb": 1.0, "ev_ebitda": 18.0, "ps": 2.0,  "div_yield": 0.030},
    "technology":   {"pe": 25.0, "pb": 3.0, "ev_ebitda": 15.0, "ps": 3.0,  "div_yield": 0.010},
    "retail":       {"pe": 18.0, "pb": 1.5, "ev_ebitda": 10.0, "ps": 0.5,  "div_yield": 0.020},
    "pharma":       {"pe": 20.0, "pb": 2.0, "ev_ebitda": 12.0, "ps": 2.5,  "div_yield": 0.020},
    "utility":      {"pe": 12.0, "pb": 0.8, "ev_ebitda": 7.0,  "ps": 0.6,  "div_yield": 0.035},
    "auto":         {"pe": 11.0, "pb": 0.8, "ev_ebitda": 6.5,  "ps": 0.4,  "div_yield": 0.032},
    "food":         {"pe": 20.0, "pb": 1.8, "ev_ebitda": 11.0, "ps": 1.0,  "div_yield": 0.020},
    "construction": {"pe": 10.0, "pb": 0.8, "ev_ebitda": 6.0,  "ps": 0.4,  "div_yield": 0.030},
    "chemical":     {"pe": 12.0, "pb": 1.0, "ev_ebitda": 7.0,  "ps": 0.6,  "div_yield": 0.025},
    "machinery":    {"pe": 15.0, "pb": 1.3, "ev_ebitda": 8.0,  "ps": 0.8,  "div_yield": 0.025},
    "electronics":  {"pe": 18.0, "pb": 1.5, "ev_ebitda": 10.0, "ps": 1.2,  "div_yield": 0.020},
    "telecom":      {"pe": 13.0, "pb": 1.5, "ev_ebitda": 6.0,  "ps": 1.5,  "div_yield": 0.035},
    "transport":    {"pe": 12.0, "pb": 1.0, "ev_ebitda": 7.0,  "ps": 0.5,  "div_yield": 0.025},
}


def _get_sector_medians(sector: str) -> dict:
    sector_l = (sector or "").lower()
    for key, vals in _SECTOR_MEDIANS.items():
        if key != "default" and key in sector_l:
            return vals
    return _SECTOR_MEDIANS["default"]


# ---------------------------------------------------------------------------
# Financial row extraction
# ---------------------------------------------------------------------------

def _extract_financial_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = payload.get("statements") or payload.get("financials") or payload.get("data") or []
    if isinstance(data, dict):
        data = [data]
    rows: List[Dict[str, Any]] = []
    for item in data:
        period = item.get("PeriodEnd") or item.get("PeriodEndDate") or item.get("CurPerEn") or item.get("Period")
        period_type = item.get("TypeOfCurrentPeriod") or item.get("CurPerType") or ""
        row = {
            "period": period,
            "period_type": period_type,
            "revenue": _pick_value(item, [
                "NetSales", "Revenue", "Sales", "OperatingRevenue", "Revn",
            ]),
            "operating_profit": _pick_value(item, [
                "OperatingProfit", "OperatingIncome", "OP", "OperatingProfitLoss",
            ]),
            "net_income": _pick_value(item, [
                "Profit", "NetIncome", "NetIncomeLoss", "NP",
                "ProfitLossAttributableToOwnersOfParent",
                "ProfitAttributableToOwnersOfParent",
            ]),
            "equity": _pick_value(item, [
                "Equity", "TotalEquity", "Eq", "NetAssets",
                "EquityAttributableToOwnersOfParent",
            ]),
            "total_assets": _pick_value(item, ["TotalAssets", "TA"]),
            "cfo": _pick_value(item, [
                "CashFlowsFromOperatingActivities", "CFO",
                "NetCashProvidedByUsedInOperatingActivities",
            ]),
            "cfi": _pick_value(item, [
                "CashFlowsFromInvestingActivities", "CFI",
                "NetCashProvidedByUsedInInvestingActivities",
            ]),
            "cff": _pick_value(item, [
                "CashFlowsFromFinancingActivities", "CFF",
                "NetCashProvidedByUsedInFinancingActivities",
            ]),
            "capex": _pick_value(item, [
                "CapitalExpenditures",
                "PurchaseOfPropertyPlantAndEquipment",
                "PaymentsForPropertyPlantAndEquipment",
                "PurchaseOfTangibleFixedAssets",
            ]),
            "ebitda": _pick_value(item, ["EBITDA"]),
            "eps": _pick_value(item, ["EarningsPerShare", "EPS", "BasicEarningsPerShare"]),
            "issued_shares": _pick_value(item, [
                "IssuedShares", "NumberOfSharesIssuedAndOutstanding",
                "ShOutFY",
                "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock",
            ]),
            "treasury_shares": _pick_value(item, [
                "TreasuryShares", "TrShFY",
                "NumberOfTreasurySharesAtTheEndOfFiscalYear",
            ]),
            "avg_shares": _pick_value(item, [
                "AverageNumberOfShares", "AvgSh",
            ]),
            "dividends": _pick_value(item, [
                "DividendPerShareAnnual", "DivAnn", "FDivAnn",
                "DividendPerShare", "DPS", "AnnualDividendPerShare",
            ]),
            "borrowings": _pick_value(item, [
                "InterestBearingDebt", "Borrowings",
                "ShortTermBorrowings", "LongTermBorrowings",
            ]),
            "cash_equiv": _pick_value(item, [
                "CashAndCashEquivalents", "CashEquivalents",
                "CashAndCashEquivalentsEndOfPeriod", "CashEq",
            ]),
        }
        if row.get("cfo") is not None and row.get("capex") is not None:
            row["fcf"] = row["cfo"] - row["capex"]
        elif row.get("cfo") is not None and row.get("cfi") is not None:
            row["fcf"] = row["cfo"] + row["cfi"]
        # Synthetic EBITDA if not available — estimate D&A from cash flow data
        if row.get("ebitda") is None and row.get("operating_profit") is not None:
            da_estimate = 0
            if row.get("cfo") is not None and row.get("net_income") is not None:
                non_cash = row["cfo"] - row["net_income"]
                if non_cash > 0:
                    # Conservative: use 50% of non-cash as D&A proxy
                    # (non-cash includes deferred taxes, SBC, impairments, etc.)
                    da_estimate = non_cash * 0.5
                    # Cap D&A at 30% of revenue to avoid extreme outliers
                    rev = row.get("revenue")
                    if rev and rev > 0:
                        da_estimate = min(da_estimate, rev * 0.30)
            row["ebitda"] = row["operating_profit"] + da_estimate
        rows.append(row)
    rows.sort(key=lambda r: _parse_date(r.get("period")) or dt.date.min, reverse=True)
    return rows


def _annualize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of *row* with flow metrics annualized for interim periods.

    Balance-sheet items (equity, total_assets, borrowings, cash_equiv) are
    point-in-time and left unchanged.  Flow items (revenue, operating_profit,
    net_income, ebitda, cfo, cfi, cff, capex, fcf) are scaled to a full-year
    equivalent when the row represents a 1Q/2Q/3Q cumulative period.
    """
    ptype = (row.get("period_type") or "").upper()
    factor_map = {"1Q": 4, "2Q": 2, "3Q": 4 / 3}
    factor = factor_map.get(ptype)
    if not factor:
        return row  # FY or unknown — no change
    out = dict(row)
    for key in ("revenue", "operating_profit", "net_income", "ebitda",
                "cfo", "cfi", "cff", "capex", "fcf"):
        val = out.get(key)
        if val is not None:
            out[key] = val * factor
    return out


def _extract_latest_metrics(rows):
    if not rows:
        return None, None
    return rows[0], (rows[1] if len(rows) > 1 else None)


def _extract_shares(info: Dict[str, Any]) -> float | None:
    for key in (
        "TotalNumberOfIssuedShares",
        "TotalNumberOfIssuedSharesAtTheEndOfFiscalYearIncludingTreasuryStock",
        "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock",
        "NumberOfIssuedAndOutstandingShares",
        "SharesOutstanding",
        "SharesOutstandingAtEndOfFiscalYear",
    ):
        if key in info:
            value = _to_float(info.get(key))
            if value is not None:
                return value
    return None


def _extract_market_cap(info: Dict[str, Any]) -> float | None:
    for key in ("MarketCapitalization", "MarketCap", "market_cap"):
        if key in info:
            value = _to_float(info.get(key))
            if value is not None:
                return value
    return None


def _latest_price_from_quotes(prices: Dict[str, Any]) -> float | None:
    data = prices.get("daily_quotes") or prices.get("data") or []
    if isinstance(data, dict):
        data = [data]
    if not data:
        return None
    last = data[-1]
    return _to_float(
        last.get("AdjustmentClose") or last.get("AdjClose")
        or last.get("Close") or last.get("C")
    )


def _build_feature_vector(latest, prev):
    rev = latest.get("revenue")
    op = latest.get("operating_profit")
    ni = latest.get("net_income")
    eq = latest.get("equity")
    assets = latest.get("total_assets")
    fcf = latest.get("fcf")
    features = {
        "op_margin": _ratio(op, rev),
        "net_margin": _ratio(ni, rev),
        "roe": _ratio(ni, eq),
        "roa": _ratio(ni, assets),
        "leverage": _ratio(assets, eq),
        "fcf_margin": _ratio(fcf, rev) if fcf is not None else None,
    }
    if prev:
        prev_rev, prev_op, prev_ni = prev.get("revenue"), prev.get("operating_profit"), prev.get("net_income")
        features["rev_growth"] = _ratio(rev - prev_rev if rev is not None and prev_rev is not None else None, prev_rev)
        features["op_growth"] = _ratio(op - prev_op if op is not None and prev_op is not None else None, prev_op)
        features["ni_growth"] = _ratio(ni - prev_ni if ni is not None and prev_ni is not None else None, prev_ni)
    else:
        features["rev_growth"] = features["op_growth"] = features["ni_growth"] = None
    return features


def _features_to_array(features, columns):
    return [float(features.get(c)) if features.get(c) is not None else np.nan for c in columns]


# ---------------------------------------------------------------------------
# LLM valuation advisor — identifies sector & picks method weights
# ---------------------------------------------------------------------------

_ADVISOR_SYSTEM = """You are a senior equity research analyst specialising in Japanese equities.
Given a company's financial profile, determine the most appropriate valuation
methodology.  Return STRICT JSON only (no markdown fences).

Consider these valuation methods and when each is most appropriate:
- dcf:  Stable positive FCF, predictable growth (industrials, tech, consumer staples)
- ddm:  Reliable dividend payer, mature company, payout ratio >20%
- ev_ebitda: Capital-intensive, leveraged, or comparing across capital structures
- pe_peer: Profitable company with sector peers available
- pb_peer: Asset-heavy (banks, real estate, insurance, holding companies)
- nav: Real estate, investment trusts, holding companies with tangible assets
- epv: Stable earnings, low-growth mature business (utilities, telecoms)
- sotp: Diversified conglomerates with distinct business segments
- residual_income: High ROE vs cost-of-equity spread, banks/financials
- ml_ridge: Always included as cross-check (ML regression model)
- ev_revenue: Revenue-based for low-margin or loss-making companies, high-growth firms
- graham: Graham Number (pure fundamental, no peers needed) — positive earnings & equity
- reverse_dcf: Diagnostic — shows market-implied growth rate (keep weight low ~0.1-0.2)
- div_yield_model: Dividend yield vs sector average — for dividend-paying stocks

Return JSON:
{
  "sector_classification": "<specific sector like 'Homebuilding', 'Electric Utilities', 'Diversified Electronics'>",
  "company_profile": "<1 sentence describing the business model>",
  "primary_method": "<method_key>",
  "method_weights": {
    "dcf": 0.0-1.0,
    "ddm": 0.0-1.0,
    "ev_ebitda": 0.0-1.0,
    "pe_peer": 0.0-1.0,
    "pb_peer": 0.0-1.0,
    "nav": 0.0-1.0,
    "epv": 0.0-1.0,
    "sotp": 0.0-1.0,
    "residual_income": 0.0-1.0,
    "ml_ridge": 0.3,
    "ev_revenue": 0.0-1.0,
    "graham": 0.0-1.0,
    "reverse_dcf": 0.0-0.2,
    "div_yield_model": 0.0-1.0
  },
  "wacc_estimate": 0.05-0.12,
  "terminal_growth": 0.005-0.025,
  "reasoning": "<2-3 sentences explaining why these methods were chosen>"
}

Rules:
- Weights should sum to roughly 2.0-4.0 (multiple methods usually apply)
- Set weight to 0.0 for methods that are clearly inappropriate
- primary_method should have weight >= 0.5
- ml_ridge is always at least 0.2 (serves as cross-check)
- Be specific about sector_classification for Japanese companies
"""


def _ask_valuation_advisor(
    company_name: str,
    stock_code: str,
    sector_hint: str | None,
    latest: Dict[str, Any],
    prev: Dict[str, Any] | None,
    has_dividends: bool,
    has_segments: bool,
    edinet_narrative_snippet: str = "",
) -> Dict[str, Any]:
    """Call LLM to get smart method selection and WACC estimate."""
    try:
        from app.services.llm import LlmClient
        llm = LlmClient()
        if not llm.api_key:
            return _default_advisor_result(sector_hint, has_dividends, latest)
    except Exception:
        return _default_advisor_result(sector_hint, has_dividends, latest)

    rev = latest.get("revenue")
    op = latest.get("operating_profit")
    ni = latest.get("net_income")
    eq = latest.get("equity")
    assets = latest.get("total_assets")
    fcf = latest.get("fcf")
    cfo = latest.get("cfo")
    ebitda = latest.get("ebitda")

    def _fmt(v):
        if v is None:
            return "N/A"
        if abs(v) >= 1e9:
            return f"¥{v/1e9:.1f}B"
        if abs(v) >= 1e6:
            return f"¥{v/1e6:.0f}M"
        return f"¥{v:,.0f}"

    rev_growth = None
    if prev and prev.get("revenue") and rev:
        rev_growth = (rev - prev["revenue"]) / prev["revenue"]

    op_margin = _ratio(op, rev)
    roe_val = _ratio(ni, eq)

    lines = [
        f"Company: {company_name} ({stock_code})",
        f"Sector hint: {sector_hint or 'Unknown'}",
        f"Revenue: {_fmt(rev)}",
    ]
    if op_margin is not None:
        lines.append(f"Operating profit: {_fmt(op)}, margin: {op_margin*100:.1f}%")
    else:
        lines.append(f"Operating profit: {_fmt(op)}")
    lines.append(f"Net income: {_fmt(ni)}")
    lines.append(f"EBITDA: {_fmt(ebitda)}")
    lines.append(f"Equity: {_fmt(eq)}")
    lines.append(f"Total assets: {_fmt(assets)}")
    lines.append(f"FCF: {_fmt(fcf)}")
    lines.append(f"CFO: {_fmt(cfo)}")
    if rev_growth is not None:
        lines.append(f"Revenue growth: {rev_growth*100:.1f}%")
    if roe_val is not None:
        lines.append(f"ROE: {roe_val*100:.1f}%")
    lines.append(f"Has dividends: {'Yes' if has_dividends else 'No'}")
    lines.append(f"Has business segments: {'Yes' if has_segments else 'No'}")
    profile_text = "\n".join(lines) + "\n"
    if edinet_narrative_snippet:
        profile_text += f"\nEDINET excerpt (business description):\n{edinet_narrative_snippet[:1500]}\n"

    try:
        raw = llm._create_completion(_ADVISOR_SYSTEM, profile_text)
        # Parse JSON
        if not raw:
            return _default_advisor_result(sector_hint, has_dividends, latest)
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return _default_advisor_result(sector_hint, has_dividends, latest)
        result = json.loads(text[start:end + 1])
        # Validate structure
        weights = result.get("method_weights", {})
        if not isinstance(weights, dict) or not weights:
            return _default_advisor_result(sector_hint, has_dividends, latest)
        # Ensure ml_ridge always present
        if "ml_ridge" not in weights:
            weights["ml_ridge"] = 0.3
        result["method_weights"] = weights
        return result
    except Exception:
        logger.debug("Valuation advisor LLM call failed", exc_info=True)
        return _default_advisor_result(sector_hint, has_dividends, latest)


def _default_advisor_result(sector_hint, has_dividends, latest):
    """Deterministic fallback when LLM is unavailable."""
    ni = latest.get("net_income") if latest else None
    eq = latest.get("equity") if latest else None
    fcf = latest.get("fcf") if latest else None
    rev = latest.get("revenue") if latest else None
    weights = {
        "dcf": 0.6 if fcf and fcf > 0 else 0.2,
        "ddm": 0.4 if has_dividends else 0.0,
        "ev_ebitda": 0.4,
        "pe_peer": 0.5 if ni and ni > 0 else 0.1,
        "pb_peer": 0.3,
        "nav": 0.3,
        "epv": 0.3 if ni and ni > 0 else 0.0,
        "sotp": 0.0,
        "residual_income": 0.3 if ni and eq and ni > 0 and eq > 0 else 0.0,
        "ml_ridge": 0.3,
        "ev_revenue": 0.3 if rev and rev > 0 else 0.0,
        "graham": 0.2 if ni and ni > 0 and eq and eq > 0 else 0.0,
        "reverse_dcf": 0.15 if fcf and fcf > 0 else 0.0,
        "div_yield_model": 0.3 if has_dividends else 0.0,
    }
    sector_lower = (sector_hint or "").lower()
    if any(kw in sector_lower for kw in ("bank", "insurance", "financ")):
        weights["pb_peer"] = 0.7
        weights["residual_income"] = 0.5
        weights["nav"] = 0.4
        weights["dcf"] = 0.1
    elif any(kw in sector_lower for kw in ("real estate", "reit", "property")):
        weights["nav"] = 0.7
        weights["pb_peer"] = 0.5
        weights["dcf"] = 0.3
    elif any(kw in sector_lower for kw in ("utility", "electric power", "gas")):
        weights["epv"] = 0.6
        weights["ddm"] = 0.5
        weights["dcf"] = 0.5
    primary = max(weights, key=weights.get)
    return {
        "sector_classification": sector_hint or "General",
        "company_profile": "Sector-based default classification",
        "primary_method": primary,
        "method_weights": weights,
        "wacc_estimate": 0.08,
        "terminal_growth": 0.015,
        "reasoning": "Fallback: LLM unavailable, using sector-heuristic weights.",
    }


# ---------------------------------------------------------------------------
# Individual valuation methods
# ---------------------------------------------------------------------------

@dataclass
class MethodResult:
    """Output of a single valuation method."""
    name: str           # e.g. "DCF (2-Stage FCF)"
    key: str            # e.g. "dcf"
    price: float | None
    range_low: float | None
    range_high: float | None
    weight: float       # advisor-assigned weight
    details: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""


def _method_dcf(rows, shares, wacc, terminal_growth, years=7) -> MethodResult:
    """Two-stage DCF: explicit FCF projection + terminal value."""
    if not rows or not shares or shares <= 0:
        return MethodResult("DCF (2-Stage FCF)", "dcf", None, None, None, 0.0,
                            reasoning="Insufficient data for DCF.")
    latest = rows[0]
    revenue = latest.get("revenue")
    fcf = latest.get("fcf")
    if revenue is None or fcf is None or revenue <= 0:
        return MethodResult("DCF (2-Stage FCF)", "dcf", None, None, None, 0.0,
                            reasoning="Missing revenue or FCF.")
    if fcf <= 0:
        return MethodResult("DCF (2-Stage FCF)", "dcf", None, None, None, 0.0,
                            reasoning="Negative or zero FCF; DCF not applicable.")
    # Revenue growth from history — use CAGR for stability
    cagr_3y = None
    cagr_5y = None
    if len(rows) >= 3 and rows[2].get("revenue") and rows[2]["revenue"] > 0 and revenue > 0:
        cagr_3y = (revenue / rows[2]["revenue"]) ** (1 / 3) - 1
    if len(rows) >= 5 and rows[4].get("revenue") and rows[4]["revenue"] > 0 and revenue > 0:
        cagr_5y = (revenue / rows[4]["revenue"]) ** (1 / 5) - 1
    if cagr_3y is not None and cagr_5y is not None:
        g = cagr_3y * 0.6 + cagr_5y * 0.4  # weighted blend
    elif cagr_3y is not None:
        g = cagr_3y
    elif cagr_5y is not None:
        g = cagr_5y
    else:
        # Fallback to YoY arithmetic mean
        growth_rates = []
        for i in range(min(4, len(rows) - 1)):
            r0, r1 = rows[i].get("revenue"), rows[i + 1].get("revenue")
            if r0 is not None and r1 is not None and r1 != 0:
                growth_rates.append((r0 - r1) / r1)
        g = float(np.mean(growth_rates)) if growth_rates else 0.03
    g = _clip(g, -0.10, 0.25)
    # Fade growth toward terminal in second stage
    g_stage2 = (g + terminal_growth) / 2
    fcf_margin = _clip(fcf / revenue, -0.05, 0.25)
    # Stage 1: years 1-5 at g
    pv = 0.0
    rev = revenue
    stage1_years = min(years, 5)
    for yr in range(1, stage1_years + 1):
        rev *= (1 + g)
        pv += (rev * fcf_margin) / ((1 + wacc) ** yr)
    # Stage 2: remaining years at faded growth
    for yr in range(stage1_years + 1, years + 1):
        rev *= (1 + g_stage2)
        pv += (rev * fcf_margin) / ((1 + wacc) ** yr)
    # Terminal value
    terminal_fcf = rev * fcf_margin * (1 + terminal_growth)
    if wacc <= terminal_growth:
        return MethodResult("DCF (2-Stage FCF)", "dcf", None, None, None, 0.0,
                            reasoning="WACC <= terminal growth; DCF diverges.")
    tv = terminal_fcf / (wacc - terminal_growth)
    tv *= 0.95  # 5% margin-of-safety discount on terminal value
    pv_terminal = tv / ((1 + wacc) ** years)
    equity_val = pv + pv_terminal
    price = equity_val / shares
    # Bull/Bear scenario analysis
    def _dcf_scenario(w, g_adj, m_adj):
        p, r = 0.0, revenue
        g_s = _clip(g + g_adj, -0.10, 0.30)
        g2_s = (g_s + terminal_growth) / 2
        m_s = _clip(fcf_margin + m_adj, 0.01, 0.30)
        for yr in range(1, stage1_years + 1):
            r *= (1 + g_s)
            p += (r * m_s) / ((1 + w) ** yr)
        for yr in range(stage1_years + 1, years + 1):
            r *= (1 + g2_s)
            p += (r * m_s) / ((1 + w) ** yr)
        tf = r * m_s * (1 + terminal_growth)
        if w <= terminal_growth:
            return None
        t = tf / (w - terminal_growth)
        t *= 0.95
        return (p + t / ((1 + w) ** years)) / shares
    dcf_base = price
    dcf_bull = _dcf_scenario(wacc, +0.02, min(0.01, 0.30 - fcf_margin))
    dcf_bear = _dcf_scenario(wacc, max(-0.02, -0.05 - g), max(-0.01, 0.01 - fcf_margin))
    low = dcf_bear if dcf_bear is not None else price * 0.80
    high = dcf_bull if dcf_bull is not None else price * 1.20
    return MethodResult(
        "DCF (2-Stage FCF)", "dcf", price, low, high, 0.0,
        details={"wacc": wacc, "growth_stage1": g, "growth_stage2": g_stage2,
                 "terminal_growth": terminal_growth, "fcf_margin": fcf_margin,
                 "projection_years": years, "pv_fcf": pv, "pv_terminal": pv_terminal,
                 "dcf_base": dcf_base, "dcf_bull": dcf_bull, "dcf_bear": dcf_bear},
        reasoning=(f"Two-stage FCF model: {g*100:.1f}% growth fading to {terminal_growth*100:.1f}%, "
                  f"WACC {wacc*100:.1f}%, FCF margin {fcf_margin*100:.1f}%. "
                  f"Bull ¥{dcf_bull:,.0f} / Bear ¥{low:,.0f}.") if dcf_bull else
                  (f"Two-stage FCF model: {g*100:.1f}% growth fading to {terminal_growth*100:.1f}%, "
                  f"WACC {wacc*100:.1f}%, FCF margin {fcf_margin*100:.1f}%."),
    )


def _method_ddm(latest, shares, price, wacc, terminal_growth) -> MethodResult:
    """Dividend Discount Model (Gordon Growth + H-model for fading growth)."""
    if not latest or not shares or shares <= 0:
        return MethodResult("DDM (Gordon Growth)", "ddm", None, None, None, 0.0,
                            reasoning="Insufficient data for DDM.")
    dps = latest.get("dividends")
    if dps is None or dps <= 0:
        return MethodResult("DDM (Gordon Growth)", "ddm", None, None, None, 0.0,
                            reasoning="No positive dividends; DDM not applicable.")
    ni = latest.get("net_income")
    eq = latest.get("equity")
    roe = _ratio(ni, eq)
    payout = dps * shares / ni if ni and ni > 0 else 0.5
    payout = _clip(payout, 0.05, 0.95)
    # Sustainable growth = ROE * (1 - payout)
    g_sustainable = (roe or 0.06) * (1 - payout)
    g_sustainable = _clip(g_sustainable, 0.0, 0.10)
    # H-model: high growth fading to terminal over H years
    H = 5
    g_high = g_sustainable
    g_term = terminal_growth
    if wacc <= g_term:
        return MethodResult("DDM (Gordon Growth)", "ddm", None, None, None, 0.0,
                            reasoning="Required return <= terminal growth.")
    # Gordon base
    gordon = dps * (1 + g_term) / (wacc - g_term)
    # H-model premium
    h_premium = dps * H * (g_high - g_term) / (wacc - g_term)
    ddm_price = gordon + h_premium
    # Range: +/- 0.5% cost of equity
    low_w, high_w = wacc + 0.005, max(wacc - 0.005, g_term + 0.002)
    low = dps * (1 + g_term) / (low_w - g_term) + dps * H * (g_high - g_term) / (low_w - g_term)
    high = dps * (1 + g_term) / (high_w - g_term) + dps * H * (g_high - g_term) / (high_w - g_term)
    return MethodResult(
        "DDM (H-Model)", "ddm", ddm_price, low, high, 0.0,
        details={"dps": dps, "payout_ratio": payout, "g_sustainable": g_sustainable,
                 "g_terminal": g_term, "h_years": H, "gordon_value": gordon,
                 "h_premium": h_premium},
        reasoning=f"H-model DDM: DPS ¥{dps:.1f}, payout {payout*100:.0f}%, "
                  f"sustainable growth {g_sustainable*100:.1f}% fading to {g_term*100:.1f}%.",
    )


def _method_ev_ebitda(latest, shares, price, peer_samples, sector, market_cap) -> MethodResult:
    """EV/EBITDA relative valuation using sector peers."""
    if not latest or not shares or shares <= 0:
        return MethodResult("EV/EBITDA Relative", "ev_ebitda", None, None, None, 0.0,
                            reasoning="Insufficient data.")
    ebitda = latest.get("ebitda")
    if not ebitda or ebitda <= 0:
        return MethodResult("EV/EBITDA Relative", "ev_ebitda", None, None, None, 0.0,
                            reasoning="No positive EBITDA.")
    debt = _net_debt(latest)
    ev = (market_cap or (price * shares if price else 0)) + debt
    actual_ev_ebitda = ev / ebitda if ebitda else None
    # Peer EV/EBITDA — use real EV/EBITDA multiples from training set
    ev_peers = [s.get("multiple_value") for s in peer_samples
                if s.get("multiple_type") == "EV/EBITDA" and s.get("sector") == sector]
    if len(ev_peers) < 3:
        ev_peers = [s.get("multiple_value") for s in peer_samples if s.get("multiple_type") == "EV/EBITDA"]
    # Filter outliers: keep 2x-25x range
    ev_peers = [x for x in ev_peers if x is not None and 2.0 <= x <= 25.0]
    if not ev_peers:
        # Fall back to P/E * 0.65 proxy only when no EV/EBITDA data exists
        pe_peers_fallback = [s.get("multiple_value") for s in peer_samples
                    if s.get("multiple_type") == "P/E" and s.get("sector") == sector]
        if len(pe_peers_fallback) < 3:
            pe_peers_fallback = [s.get("multiple_value") for s in peer_samples if s.get("multiple_type") == "P/E"]
        if not pe_peers_fallback:
            # Final fallback: use sector median EV/EBITDA
            sector_meds = _get_sector_medians(sector)
            fallback_evebitda = sector_meds.get("ev_ebitda")
            if fallback_evebitda and ebitda and ebitda > 0:
                implied_ev = fallback_evebitda * ebitda
                implied_equity = implied_ev - debt
                implied_price = max(implied_equity / shares, 0) if shares else None
                low = max(((fallback_evebitda * 0.75 * ebitda) - debt) / shares, 0) if shares else None
                high = max(((fallback_evebitda * 1.25 * ebitda) - debt) / shares, 0) if shares else None
                return MethodResult(
                    "EV/EBITDA Relative", "ev_ebitda", implied_price, low, high, 0.0,
                    details={"ebitda": ebitda, "net_debt": debt, "peer_ev_ebitda": fallback_evebitda,
                             "implied_ev": implied_ev, "source": "sector_median"},
                    reasoning=f"Sector median EV/EBITDA {fallback_evebitda:.1f}x (no peer data; using market benchmark).",
                )
            return MethodResult("EV/EBITDA Relative", "ev_ebitda", None, None, None, 0.0,
                                reasoning="No peer data available for EV/EBITDA comparison.")
        # Use sector median EV/EBITDA instead of arbitrary P/E conversion
        sector_meds = _get_sector_medians(sector)
        fallback_evebitda = sector_meds.get("ev_ebitda")
        if fallback_evebitda:
            ev_peers = [fallback_evebitda]
        else:
            return MethodResult("EV/EBITDA Relative", "ev_ebitda", None, None, None, 0.0,
                                reasoning="No EV/EBITDA peer data; P/E peers cannot substitute.")
    peer_ev_ebitda_raw = _median(ev_peers)
    if not peer_ev_ebitda_raw:
        return MethodResult("EV/EBITDA Relative", "ev_ebitda", None, None, None, 0.0,
                            reasoning="Could not estimate peer EV/EBITDA.")
    # Anchor to company's own actual EV/EBITDA when available and reasonable
    peer_ev_ebitda = peer_ev_ebitda_raw
    blend_note = ""
    if actual_ev_ebitda is not None and 1.0 < actual_ev_ebitda < 50.0:
        peer_ev_ebitda = peer_ev_ebitda_raw * 0.60 + actual_ev_ebitda * 0.40
        blend_note = f" (blended: 60% peer {peer_ev_ebitda_raw:.1f}x + 40% actual {actual_ev_ebitda:.1f}x)"
    implied_ev = peer_ev_ebitda * ebitda
    implied_equity = implied_ev - debt
    implied_price = max(implied_equity / shares, 0) if shares else None
    p25 = _percentile(ev_peers, 25) if ev_peers else None
    p75 = _percentile(ev_peers, 75) if ev_peers else None
    low = max(((p25 * ebitda) - debt) / shares, 0) if p25 and shares else None
    high = max(((p75 * ebitda) - debt) / shares, 0) if p75 and shares else None
    return MethodResult(
        "EV/EBITDA Relative", "ev_ebitda", implied_price, low, high, 0.0,
        details={"ebitda": ebitda, "net_debt": debt, "actual_ev_ebitda": actual_ev_ebitda,
                 "peer_ev_ebitda": peer_ev_ebitda, "peer_ev_ebitda_raw": peer_ev_ebitda_raw,
                 "implied_ev": implied_ev},
        reasoning=f"EV/EBITDA ~{peer_ev_ebitda:.1f}x{blend_note} applied to EBITDA of ¥{ebitda/1e6:.0f}M, "
                  f"net debt ¥{debt/1e6:.0f}M.",
    )


def _method_pe_peer(latest, shares, peer_samples, sector, current_price=None) -> MethodResult:
    """P/E peer-relative valuation."""
    if not latest or not shares or shares <= 0:
        return MethodResult("P/E Peer Relative", "pe_peer", None, None, None, 0.0)
    ni = latest.get("net_income")
    if not ni or ni <= 0:
        return MethodResult("P/E Peer Relative", "pe_peer", None, None, None, 0.0,
                            reasoning="No positive earnings for P/E.")
    same = [s.get("multiple_value") for s in peer_samples
            if s.get("multiple_type") == "P/E" and s.get("sector") == sector]
    if len(same) < 5:
        same = [s.get("multiple_value") for s in peer_samples if s.get("multiple_type") == "P/E"]
    peer_pe = _median(same) if same else None
    # Compute own P/E and discount-to-peers
    own_pe = None
    discount_to_peers = None
    if current_price and current_price > 0 and ni > 0:
        own_pe = (current_price * shares) / ni
        if peer_pe and peer_pe > 0:
            discount_to_peers = own_pe / peer_pe - 1
    if not peer_pe:
        sector_meds = _get_sector_medians(sector)
        fallback_pe = sector_meds.get("pe")
        if fallback_pe:
            price = (fallback_pe * ni) / shares
            low = (fallback_pe * 0.75 * ni) / shares
            high = (fallback_pe * 1.25 * ni) / shares
            details = {"peer_pe": fallback_pe, "net_income": ni, "peer_count": 0, "source": "sector_median"}
            if own_pe is not None:
                details["own_pe"] = round(own_pe, 2)
                details["discount_to_peers"] = round((own_pe / fallback_pe - 1), 4) if fallback_pe else None
            return MethodResult(
                "P/E Peer Relative", "pe_peer", price, low, high, 0.0,
                details=details,
                reasoning=f"Sector median P/E {fallback_pe:.1f}x (no peer data; using market benchmark).",
            )
        return MethodResult("P/E Peer Relative", "pe_peer", None, None, None, 0.0,
                            reasoning="No P/E peers available.")
    price = (peer_pe * ni) / shares
    low = (_percentile(same, 25) * ni / shares) if same else None
    high = (_percentile(same, 75) * ni / shares) if same else None
    details = {"peer_pe": peer_pe, "net_income": ni, "peer_count": len(same)}
    if own_pe is not None:
        details["own_pe"] = round(own_pe, 2)
    if discount_to_peers is not None:
        details["discount_to_peers"] = round(discount_to_peers, 4)
    return MethodResult(
        "P/E Peer Relative", "pe_peer", price, low, high, 0.0,
        details=details,
        reasoning=f"Sector median P/E {peer_pe:.1f}x applied to NI ¥{ni/1e6:.0f}M"
                  f"{f', own P/E {own_pe:.1f}x ({discount_to_peers:+.0%} vs peers)' if own_pe is not None and discount_to_peers is not None else ''}.",
    )


def _method_pb_peer(latest, shares, peer_samples, sector, current_price=None) -> MethodResult:
    """P/B peer-relative valuation."""
    if not latest or not shares or shares <= 0:
        return MethodResult("P/B Peer Relative", "pb_peer", None, None, None, 0.0)
    eq = latest.get("equity")
    if not eq or eq <= 0:
        return MethodResult("P/B Peer Relative", "pb_peer", None, None, None, 0.0,
                            reasoning="No positive equity for P/B.")
    same = [s.get("multiple_value") for s in peer_samples
            if s.get("multiple_type") == "P/B" and s.get("sector") == sector]
    if len(same) < 5:
        same = [s.get("multiple_value") for s in peer_samples if s.get("multiple_type") == "P/B"]
    peer_pb = _median(same) if same else None
    # Compute own P/B and discount-to-peers
    own_pb = None
    discount_to_peers = None
    if current_price and current_price > 0 and eq > 0:
        own_pb = (current_price * shares) / eq
        if peer_pb and peer_pb > 0:
            discount_to_peers = own_pb / peer_pb - 1
    if not peer_pb:
        sector_meds = _get_sector_medians(sector)
        fallback_pb = sector_meds.get("pb")
        if fallback_pb:
            price = (fallback_pb * eq) / shares
            low = (fallback_pb * 0.75 * eq) / shares
            high = (fallback_pb * 1.25 * eq) / shares
            details = {"peer_pb": fallback_pb, "equity": eq, "peer_count": 0, "source": "sector_median"}
            if own_pb is not None:
                details["own_pb"] = round(own_pb, 2)
                details["discount_to_peers"] = round((own_pb / fallback_pb - 1), 4) if fallback_pb else None
            return MethodResult(
                "P/B Peer Relative", "pb_peer", price, low, high, 0.0,
                details=details,
                reasoning=f"Sector median P/B {fallback_pb:.2f}x (no peer data; using market benchmark).",
            )
        return MethodResult("P/B Peer Relative", "pb_peer", None, None, None, 0.0,
                            reasoning="No P/B peers available.")
    price = (peer_pb * eq) / shares
    low = (_percentile(same, 25) * eq / shares) if same else None
    high = (_percentile(same, 75) * eq / shares) if same else None
    details = {"peer_pb": peer_pb, "equity": eq, "peer_count": len(same)}
    if own_pb is not None:
        details["own_pb"] = round(own_pb, 2)
    if discount_to_peers is not None:
        details["discount_to_peers"] = round(discount_to_peers, 4)
    return MethodResult(
        "P/B Peer Relative", "pb_peer", price, low, high, 0.0,
        details=details,
        reasoning=f"Sector median P/B {peer_pb:.2f}x applied to equity ¥{eq/1e6:.0f}M"
                  f"{f', own P/B {own_pb:.2f}x ({discount_to_peers:+.0%} vs peers)' if own_pb is not None and discount_to_peers is not None else ''}.",
    )


def _method_nav(latest, shares) -> MethodResult:
    """Net Asset Value — adjusted book value with liquidation-to-going-concern spectrum."""
    if not latest or not shares or shares <= 0:
        return MethodResult("NAV (Net Asset Value)", "nav", None, None, None, 0.0)
    eq = latest.get("equity")
    assets = latest.get("total_assets")
    if not eq or eq <= 0 or not assets:
        return MethodResult("NAV (Net Asset Value)", "nav", None, None, None, 0.0,
                            reasoning="Missing balance sheet data for NAV.")
    nav_base = eq / shares
    ni = latest.get("net_income")
    roe = _ratio(ni, eq)
    tangible_ratio = min(1.0, eq / assets) if assets > 0 else 0.5

    # Liquidation-to-going-concern spectrum based on ROE
    if roe is not None and roe > 0.15:
        # High ROE: strong going-concern premium, 1.3-1.6x book
        # Interpolate within range based on how far above 15%
        excess = min(roe - 0.15, 0.15)  # cap excess at 15pp
        multiplier = 1.3 + (excess / 0.15) * 0.3  # 1.3 to 1.6
        label = "going-concern premium (high ROE)"
    elif roe is not None and roe >= 0.08:
        # Moderate ROE: going-concern premium, 1.0-1.3x book
        frac = (roe - 0.08) / 0.07  # 0 at 8%, 1 at 15%
        multiplier = 1.0 + frac * 0.3
        label = "going-concern premium"
    elif roe is not None and roe >= 0.02:
        # Low ROE: slight discount, 0.85-1.0x book
        frac = (roe - 0.02) / 0.06  # 0 at 2%, 1 at 8%
        multiplier = 0.85 + frac * 0.15
        label = "marginal returns discount"
    else:
        # Very low / negative ROE: liquidation discount, 0.60-0.80x book
        # Adjust for tangible asset ratio (higher tangible = less discount)
        multiplier = 0.60 + tangible_ratio * 0.20  # 0.60 to 0.80
        label = "liquidation discount"

    nav_price = nav_base * multiplier
    # Range: ±0.20 around multiplier
    range_lo = nav_base * max(0.40, multiplier - 0.20)
    range_hi = nav_base * min(2.0, multiplier + 0.20)

    return MethodResult(
        "NAV (Net Asset Value)", "nav", nav_price, range_lo, range_hi, 0.0,
        details={"equity": eq, "bps": nav_base, "roe": roe, "tangible_ratio": tangible_ratio,
                 "multiplier": multiplier, "adjustment": multiplier - 1.0},
        reasoning=f"Book value ¥{nav_base:.0f}/share × {multiplier:.2f} ({label}), "
                  f"ROE {roe*100:.1f}%" if roe else f"Book value ¥{nav_base:.0f}/share × {multiplier:.2f} ({label}).",
    )


def _method_epv(latest, shares, wacc) -> MethodResult:
    """Earnings Power Value — normalised earnings capitalised at WACC."""
    if not latest or not shares or shares <= 0 or not wacc:
        return MethodResult("EPV (Earnings Power)", "epv", None, None, None, 0.0)
    ni = latest.get("net_income")
    if not ni or ni <= 0:
        return MethodResult("EPV (Earnings Power)", "epv", None, None, None, 0.0,
                            reasoning="No positive earnings for EPV.")
    # Normalise: use average of operating profit and net income to smooth
    op = latest.get("operating_profit") or ni
    normalised = (op * 0.7 + ni) / 1.7  # blend
    normalised = max(normalised, ni * 0.5)
    epv_equity = normalised / wacc
    epv_price = epv_equity / shares
    # Range: +/- 1% WACC
    low = (normalised / (wacc + 0.01)) / shares
    high = (normalised / max(wacc - 0.01, 0.03)) / shares
    return MethodResult(
        "EPV (Earnings Power)", "epv", epv_price, low, high, 0.0,
        details={"normalised_earnings": normalised, "wacc": wacc,
                 "epv_total": epv_equity},
        reasoning=f"Normalised earnings ¥{normalised/1e6:.0f}M capitalised at {wacc*100:.1f}% WACC.",
    )


def _method_sotp(segments, shares, peer_samples, sector) -> MethodResult:
    """Sum-of-the-Parts using segment revenues and sector P/S multiples."""
    if not segments or not shares or shares <= 0:
        return MethodResult("SOTP (Sum-of-Parts)", "sotp", None, None, None, 0.0,
                            reasoning="No segment data available for SOTP.")
    ps_vals = [s.get("multiple_value") for s in peer_samples
               if s.get("multiple_type") == "P/S" and s.get("sector") == sector]
    if len(ps_vals) < 5:
        ps_vals = [s.get("multiple_value") for s in peer_samples if s.get("multiple_type") == "P/S"]
    ps_median = _median(ps_vals)
    if not ps_median:
        return MethodResult("SOTP (Sum-of-Parts)", "sotp", None, None, None, 0.0,
                            reasoning="No P/S peer data for SOTP.")
    total = sum(seg.get("revenue", 0) * ps_median for seg in segments if seg.get("revenue"))
    price = total / shares
    p25 = _percentile(ps_vals, 25) or ps_median * 0.8
    p75 = _percentile(ps_vals, 75) or ps_median * 1.2
    low = sum(seg.get("revenue", 0) * p25 for seg in segments if seg.get("revenue")) / shares
    high = sum(seg.get("revenue", 0) * p75 for seg in segments if seg.get("revenue")) / shares
    seg_details = [{"name": s.get("name", "?"), "revenue": s.get("revenue")} for s in segments]
    return MethodResult(
        "SOTP (Sum-of-Parts)", "sotp", price, low, high, 0.0,
        details={"segments": seg_details, "ps_multiple": ps_median, "total_ev": total},
        reasoning=f"Aggregated {len(segments)} segments at P/S {ps_median:.2f}x.",
    )


def _method_residual_income(latest, rows, shares, wacc, capm=None) -> MethodResult:
    """Residual Income Model — capitalised excess ROE spread."""
    if not latest or not shares or shares <= 0:
        return MethodResult("Residual Income", "residual_income", None, None, None, 0.0)
    eq = latest.get("equity")
    ni = latest.get("net_income")
    if not eq or eq <= 0 or not ni:
        return MethodResult("Residual Income", "residual_income", None, None, None, 0.0,
                            reasoning="Missing equity or earnings.")
    roe = ni / eq
    bps = eq / shares
    # Residual income = (ROE - CoE) * BPS
    # Use CAPM cost of equity when available (more accurate than WACC)
    coe = (capm or {}).get("cost_of_equity") or wacc
    ri = (roe - coe) * bps
    # Capitalise RI as perpetuity (conservative: no growth)
    if coe <= 0:
        return MethodResult("Residual Income", "residual_income", None, None, None, 0.0)
    ri_value = bps + ri / coe
    # Fade RI to zero over time (more conservative)
    fade_factor = 0.7  # assume 70% of excess persists
    ri_faded = bps + (ri * fade_factor) / coe
    low = bps + (ri * 0.4) / coe  # pessimistic: 40% persistence
    high = bps + ri / coe  # full persistence
    return MethodResult(
        "Residual Income", "residual_income", ri_faded, low, high, 0.0,
        details={"roe": roe, "coe": coe, "bps": bps, "ri_per_share": ri,
                 "fade_factor": fade_factor},
        reasoning=f"ROE {roe*100:.1f}% vs CoE {coe*100:.1f}%: "
                  f"{'positive' if ri > 0 else 'negative'} spread of {(roe-coe)*100:.1f}pp, "
                  f"BPS ¥{bps:.0f}.",
    )


# ---------------------------------------------------------------------------
# EV/Revenue (Price-to-Sales Relative)
# ---------------------------------------------------------------------------

def _method_ev_revenue(latest, shares, peer_samples, sector, market_cap) -> MethodResult:
    """EV/Revenue relative valuation using P/S multiples."""
    if not latest or not shares or shares <= 0:
        return MethodResult("EV/Revenue (P/S)", "ev_revenue", None, None, None, 0.0,
                            reasoning="Insufficient data.")
    revenue = latest.get("revenue")
    if not revenue or revenue <= 0:
        return MethodResult("EV/Revenue (P/S)", "ev_revenue", None, None, None, 0.0,
                            reasoning="No positive revenue.")
    debt = _net_debt(latest)
    # Peer P/S multiples
    ps_peers = [s.get("multiple_value") for s in peer_samples
                if s.get("multiple_type") == "P/S" and s.get("sector") == sector]
    if len(ps_peers) < 3:
        ps_peers = [s.get("multiple_value") for s in peer_samples if s.get("multiple_type") == "P/S"]
    ps_peers = [x for x in ps_peers if x is not None and 0.1 <= x <= 20.0]
    if ps_peers:
        peer_ps = _median(ps_peers)
        p25 = _percentile(ps_peers, 25)
        p75 = _percentile(ps_peers, 75)
    else:
        sector_meds = _get_sector_medians(sector)
        peer_ps = sector_meds.get("ps", 0.8)
        p25 = peer_ps * 0.75
        p75 = peer_ps * 1.25
    implied_ev = peer_ps * revenue
    price = max((implied_ev - debt) / shares, 0)
    low = max(((p25 * revenue) - debt) / shares, 0) if p25 else None
    high = max(((p75 * revenue) - debt) / shares, 0) if p75 else None
    return MethodResult(
        "EV/Revenue (P/S)", "ev_revenue", max(price, 0), low, high, 0.0,
        details={"revenue": revenue, "net_debt": debt, "peer_ps": peer_ps,
                 "implied_ev": implied_ev, "peer_count": len(ps_peers)},
        reasoning=f"P/S {peer_ps:.2f}x applied to revenue ¥{revenue/1e6:.0f}M, net debt ¥{debt/1e6:.0f}M.",
    )


# ---------------------------------------------------------------------------
# Graham Number
# ---------------------------------------------------------------------------

def _method_graham(latest, shares) -> MethodResult:
    """Graham Number — classic Ben Graham formula: sqrt(22.5 × EPS × BPS)."""
    if not latest or not shares or shares <= 0:
        return MethodResult("Graham Number", "graham", None, None, None, 0.0,
                            reasoning="Insufficient data.")
    ni = latest.get("net_income")
    eq = latest.get("equity")
    if not ni or ni <= 0 or not eq or eq <= 0:
        return MethodResult("Graham Number", "graham", None, None, None, 0.0,
                            reasoning="Requires positive earnings and equity.")
    eps = ni / shares
    bps = eq / shares
    graham = (22.5 * eps * bps) ** 0.5
    low = graham * 0.85
    high = graham * 1.15
    return MethodResult(
        "Graham Number", "graham", graham, low, high, 0.0,
        details={"eps": eps, "bps": bps, "formula": "sqrt(22.5 × EPS × BPS)"},
        reasoning=f"Graham = √(22.5 × ¥{eps:.1f} × ¥{bps:.0f}) = ¥{graham:,.0f}.",
    )


# ---------------------------------------------------------------------------
# Reverse DCF (Implied Growth)
# ---------------------------------------------------------------------------

def _method_reverse_dcf(latest, rows, shares, price, wacc, terminal_growth) -> MethodResult:
    """Reverse DCF — binary search for market-implied growth rate."""
    if not latest or not shares or shares <= 0 or not price or price <= 0:
        return MethodResult("Reverse DCF", "reverse_dcf", None, None, None, 0.0,
                            reasoning="Insufficient data for reverse DCF.")
    revenue = latest.get("revenue")
    fcf = latest.get("fcf")
    if not revenue or revenue <= 0 or not fcf or fcf <= 0:
        return MethodResult("Reverse DCF", "reverse_dcf", None, None, None, 0.0,
                            reasoning="Missing positive revenue or FCF.")
    market_cap = price * shares
    fcf_margin = fcf / revenue
    # Binary search for implied growth
    def _dcf_value(g):
        pv = 0.0
        rev = revenue
        g2 = (g + terminal_growth) / 2
        for yr in range(1, 6):
            rev *= (1 + g)
            pv += (rev * fcf_margin) / ((1 + wacc) ** yr)
        for yr in range(6, 8):
            rev *= (1 + g2)
            pv += (rev * fcf_margin) / ((1 + wacc) ** yr)
        tf = rev * fcf_margin * (1 + terminal_growth)
        if wacc <= terminal_growth:
            return pv
        tv = tf / (wacc - terminal_growth) * 0.95
        return pv + tv / ((1 + wacc) ** 7)

    lo_g, hi_g = -0.10, 0.40
    implied_growth = None
    for _ in range(60):
        mid_g = (lo_g + hi_g) / 2
        val = _dcf_value(mid_g)
        if val < market_cap:
            lo_g = mid_g
        else:
            hi_g = mid_g
        if abs(hi_g - lo_g) < 0.0001:
            implied_growth = mid_g
            break
    if implied_growth is None:
        implied_growth = (lo_g + hi_g) / 2
    # Actual 3Y CAGR
    actual_cagr = None
    if len(rows) >= 3 and rows[2].get("revenue") and rows[2]["revenue"] > 0 and revenue > 0:
        actual_cagr = (revenue / rows[2]["revenue"]) ** (1 / 3) - 1
    if actual_cagr is not None:
        diff = implied_growth - actual_cagr
        if diff > 0.03:
            assessment = "Market implies higher growth vs historical"
        elif diff < -0.03:
            assessment = "Market implies lower growth vs historical"
        else:
            assessment = "Market-implied growth aligned with historical"
    else:
        assessment = "Historical CAGR unavailable for comparison"
    return MethodResult(
        "Reverse DCF", "reverse_dcf", price, price * 0.90, price * 1.10, 0.0,
        details={"implied_growth_rate": round(implied_growth, 4),
                 "actual_growth_3y_cagr": round(actual_cagr, 4) if actual_cagr is not None else None,
                 "assessment": assessment},
        reasoning=f"Implied growth {implied_growth*100:.1f}% vs "
                  f"{'actual ' + f'{actual_cagr*100:.1f}%' if actual_cagr is not None else 'N/A'}. "
                  f"{assessment}.",
    )


# ---------------------------------------------------------------------------
# Dividend Yield Model
# ---------------------------------------------------------------------------

def _method_dividend_yield(latest, shares, sector) -> MethodResult:
    """Dividend Yield Model — price = DPS / sector median yield."""
    if not latest or not shares or shares <= 0:
        return MethodResult("Dividend Yield Model", "div_yield_model", None, None, None, 0.0,
                            reasoning="Insufficient data.")
    dps = latest.get("dividends")
    if not dps or dps <= 0:
        return MethodResult("Dividend Yield Model", "div_yield_model", None, None, None, 0.0,
                            reasoning="No positive dividends; model not applicable.")
    sector_meds = _get_sector_medians(sector)
    target_yield = sector_meds.get("div_yield", 0.025)
    if target_yield <= 0:
        target_yield = 0.025
    price = dps / target_yield
    low = dps / (target_yield + 0.005)
    high = dps / max(target_yield - 0.005, 0.005)
    return MethodResult(
        "Dividend Yield Model", "div_yield_model", price, low, high, 0.0,
        details={"dps": dps, "sector_median_yield": target_yield},
        reasoning=f"DPS ¥{dps:.1f} / sector yield {target_yield*100:.1f}% = ¥{price:,.0f}.",
    )


# ---------------------------------------------------------------------------
# ML Ridge regression (existing approach, refactored)
# ---------------------------------------------------------------------------

def _method_ml_ridge(latest, prev, shares, model, meta) -> MethodResult:
    """ML cross-sectional multiple prediction using Ridge regression."""
    if not latest or not shares or shares <= 0 or model is None or not meta:
        return MethodResult("ML Ridge (Cross-Sectional)", "ml_ridge", None, None, None, 0.0,
                            reasoning="ML model not available.")
    columns = meta.get("columns", [])
    if not columns:
        return MethodResult("ML Ridge (Cross-Sectional)", "ml_ridge", None, None, None, 0.0)
    features = _build_feature_vector(latest, prev)
    row = _features_to_array(features, columns)
    # Impute NaN with training set medians instead of rejecting
    if any(np.isnan(row)):
        medians = meta.get("feature_medians", [0.0] * len(columns))
        for i in range(len(row)):
            if np.isnan(row[i]):
                row[i] = medians[i] if i < len(medians) else 0.0
    # Determine base metric
    ni = latest.get("net_income")
    eq = latest.get("equity")
    rev = latest.get("revenue")
    base_metric, model_type = None, None
    if ni and ni > 0:
        base_metric, model_type = ni, "P/E"
    elif eq and eq > 0:
        base_metric, model_type = eq, "P/B"
    elif rev and rev > 0:
        base_metric, model_type = rev, "P/S"
    if not base_metric:
        return MethodResult("ML Ridge (Cross-Sectional)", "ml_ridge", None, None, None, 0.0)
    predicted = float(model.predict(np.asarray([row], dtype=float))[0])
    resid_std = float(meta.get("resid_std") or 0.0)
    price = (predicted * base_metric) / shares
    low = max((predicted - resid_std) * base_metric / shares, 0) if resid_std else None
    high = (predicted + resid_std) * base_metric / shares if resid_std else None
    return MethodResult(
        f"ML Ridge ({model_type})", "ml_ridge", price, low, high, 0.0,
        details={"predicted_multiple": predicted, "model_type": model_type,
                 "base_metric": base_metric, "r2": meta.get("r2"),
                 "samples": meta.get("samples")},
        reasoning=f"Ridge regression predicts {model_type} multiple of {predicted:.2f}x "
                  f"(R²={meta.get('r2', 0):.2f}, n={meta.get('samples', 0)}).",
    )


# ---------------------------------------------------------------------------
# Valuation result
# ---------------------------------------------------------------------------

@dataclass
class ValuationResult:
    model_type: str
    samples: int
    r2: float | None
    predicted_multiple: float | None
    actual_multiple: float | None
    implied_price: float | None
    range_low: float | None
    range_high: float | None
    score_z: float | None
    peer_multiple: float | None
    peer_price: float | None
    peer_range_low: float | None
    peer_range_high: float | None
    dcf_price: float | None
    dcf_range_low: float | None
    dcf_range_high: float | None
    sotp_price: float | None
    sotp_range_low: float | None
    sotp_range_high: float | None
    last_price: float | None
    market_cap: float | None
    shares: float | None
    target_price: float | None
    target_low: float | None
    target_high: float | None
    upside_pct: float | None
    quality_score: float | None
    method_count: int
    notes: List[str]
    # --- New v2 fields ---
    advisor: Dict[str, Any] = field(default_factory=dict)
    method_results: List[Dict[str, Any]] = field(default_factory=list)
    primary_method: str = ""
    sector_classification: str = ""
    valuation_narrative: str = ""
    extended_metrics: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Blending
# ---------------------------------------------------------------------------

def _blend_methods_v2(
    results: List[MethodResult],
) -> Tuple[float | None, float | None, float | None, int]:
    """Weighted blend of all methods that produced a price."""
    # Exclude methods with price=0 (non-results from negative equity after debt)
    available = [r for r in results if r.price is not None and r.price > 0 and r.weight > 0]
    if not available:
        return None, None, None, 0
    total_w = sum(r.weight for r in available)
    if total_w <= 0:
        return None, None, None, 0
    blended = sum(r.price * r.weight for r in available) / total_w
    lows = [r.range_low for r in available if r.range_low is not None]
    highs = [r.range_high for r in available if r.range_high is not None]
    bl = sum((r.range_low or r.price * 0.85) * r.weight for r in available) / total_w
    bh = sum((r.range_high or r.price * 1.15) * r.weight for r in available) / total_w
    return blended, bl, bh, len(available)


def _quality_score(method_count, sample_count, row_count):
    base = 25 + method_count * 12
    if sample_count >= 300:
        base += 10
    if row_count >= 3:
        base += 10
    if row_count >= 5:
        base += 5
    return float(min(100, max(0, base)))


def _quality_score_v2(method_results, sample_count, row_count, latest_period=None, extended_metrics=None):
    """Improved quality score considering method agreement, data recency, and depth."""
    active = [r for r in method_results if r.price is not None and r.weight > 0]
    active_count = len(active)

    # Base: 20 + 10 per active method, capped at 60
    base = min(60, 20 + active_count * 10)

    # Data recency: +0-15 based on how recent the latest period is
    recency_bonus = 0
    if latest_period:
        period_date = _parse_date(latest_period)
        if period_date:
            months_ago = max(0, (dt.date.today() - period_date).days / 30.0)
            if months_ago <= 6:
                recency_bonus = 15
            elif months_ago <= 12:
                recency_bonus = 10
            elif months_ago <= 18:
                recency_bonus = 5

    # Method agreement: +0-15 based on coefficient of variation
    agreement_bonus = 0
    prices = [r.price for r in active if r.price is not None]
    if len(prices) >= 2:
        mean_p = float(np.mean(prices))
        std_p = float(np.std(prices))
        if mean_p > 0:
            cv = std_p / mean_p
            if cv < 0.10:
                agreement_bonus = 15
            elif cv < 0.20:
                agreement_bonus = 10
            elif cv < 0.30:
                agreement_bonus = 5
            elif cv > 0.50:
                agreement_bonus = -10  # methods wildly disagree
            elif cv > 0.40:
                agreement_bonus = -5

    # Peer data quality: +0-10
    peer_bonus = 0
    if sample_count >= 300:
        peer_bonus = 10
    elif sample_count >= 100:
        peer_bonus = 5

    # Historical depth: +0-10
    depth_bonus = 0
    if row_count >= 5:
        depth_bonus = 10
    elif row_count >= 3:
        depth_bonus = 5

    # Data completeness bonus: +0-5 from extended metrics
    completeness_bonus = 0
    if extended_metrics:
        expected_keys = ["beta", "roic", "earnings_yield", "fcf_yield", "ev_revenue", "debt_equity", "cost_of_equity"]
        filled = sum(1 for k in expected_keys if extended_metrics.get(k) is not None)
        fill_pct = filled / len(expected_keys)
        if fill_pct >= 0.80:
            completeness_bonus = 5
        elif fill_pct >= 0.50:
            completeness_bonus = 3

    total = base + recency_bonus + agreement_bonus + peer_bonus + depth_bonus + completeness_bonus
    return float(min(100, max(0, total)))


# ---------------------------------------------------------------------------
# ML training (kept from original)
# ---------------------------------------------------------------------------

class ValuationEngine:
    def __init__(self) -> None:
        self.jquants = JQuantsClient()
        self.cache_dir = Path(settings.output_dir) / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _load_cached_model(self) -> Tuple[dict | None, dict | None]:
        meta_path = self.cache_dir / "valuation_meta.json"
        model_path = self.cache_dir / "valuation_model.joblib"
        if not meta_path.exists() or not model_path.exists():
            return None, None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            trained_at = dt.datetime.fromisoformat(meta.get("trained_at"))
            if (dt.datetime.now() - trained_at).days > settings.ml_cache_days:
                return None, None
            model = joblib.load(model_path)
            return meta, model
        except Exception:
            return None, None

    def _save_cached_model(self, meta, model):
        meta_path = self.cache_dir / "valuation_meta.json"
        model_path = self.cache_dir / "valuation_model.joblib"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        joblib.dump(model, model_path)

    def _list_universe(self, max_tickers):
        if not (self.jquants.api_key or self.jquants.refresh_token):
            return []
        try:
            payload = self.jquants._get(settings.jquants_company_endpoint, params={})
        except Exception:
            return []
        info = payload.get("info") or payload.get("data") or []
        return info[:max_tickers] if isinstance(info, list) else []

    def _fetch_latest_price(self, code):
        try:
            prices = self.jquants.get_prices(code)
        except Exception:
            return None
        return _latest_price_from_quotes(prices)

    def _load_ticker_cache(self, code: str):
        """Load cached ticker data (financials + price) with 24h TTL."""
        cache_path = self.cache_dir / f"ticker_{code}.json"
        if not cache_path.exists():
            return None
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_at = dt.datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
            if (dt.datetime.now() - cached_at).total_seconds() > 24 * 3600:
                return None
            return data
        except Exception:
            return None

    def _save_ticker_cache(self, code: str, data: dict):
        """Save ticker data to cache."""
        data["cached_at"] = dt.datetime.now().isoformat(timespec="seconds")
        cache_path = self.cache_dir / f"ticker_{code}.json"
        try:
            cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _build_training_set(self, max_tickers, on_event=None):
        import time as _time
        columns = [
            "op_margin", "net_margin", "roe", "roa", "leverage",
            "fcf_margin", "rev_growth", "op_growth", "ni_growth",
        ]
        X, y, multiples, peer_samples = [], [], [], []
        universe = self._list_universe(max_tickers)

        # Throttle: enforce ~1 req/s to stay under J-Quants rate limit
        _last_api_call = [0.0]

        def _throttled_api(fn, *args, **kwargs):
            elapsed = _time.monotonic() - _last_api_call[0]
            if elapsed < 1.0:
                _time.sleep(1.0 - elapsed)
            _last_api_call[0] = _time.monotonic()
            return fn(*args, **kwargs)

        def _process_ticker(info):
            code = info.get("Code") or info.get("code")
            if not code:
                return None

            # Check per-ticker cache first
            cached = self._load_ticker_cache(code)
            if cached and cached.get("result"):
                return cached["result"]
            if cached and cached.get("skip"):
                return None

            try:
                fin_payload = _throttled_api(self.jquants.get_financials, code)
            except Exception:
                return None  # transient API error — don't cache
            rows = _extract_financial_rows(fin_payload)
            latest, prev = _extract_latest_metrics(rows)
            if not latest:
                self._save_ticker_cache(code, {"skip": True})
                return None
            latest = _annualize_row(latest)
            if prev:
                prev = _annualize_row(prev)
            features = _build_feature_vector(latest, prev)
            row = _features_to_array(features, columns)
            if any(np.isnan(row)):
                self._save_ticker_cache(code, {"skip": True})
                return None
            try:
                price = _throttled_api(self._fetch_latest_price, code)
            except Exception:
                price = None
            if price is None or price <= 0:
                return None  # price fetch failed — don't cache, may be transient
            shares = _extract_shares(info) or 0.0
            mcap = _extract_market_cap(info)
            if mcap is None and shares:
                mcap = shares * price
            if mcap is None or mcap <= 0:
                self._save_ticker_cache(code, {"skip": True})
                return None
            eq = latest.get("equity")
            ni = latest.get("net_income")
            rev = latest.get("revenue")
            mt = None
            if eq and eq > 0:
                mult = mcap / eq; mt = "P/B"
            elif ni and ni > 0:
                mult = mcap / ni; mt = "P/E"
            elif rev and rev > 0:
                mult = mcap / rev; mt = "P/S"
            else:
                self._save_ticker_cache(code, {"skip": True})
                return None
            sector = info.get("Sector33CodeName") or info.get("Sector17CodeName") or "Unknown"
            # Compute EV/EBITDA for this peer
            ebitda_val = latest.get("ebitda")
            ev_ebitda_mult = None
            if ebitda_val and ebitda_val > 0:
                debt = _net_debt(latest)
                peer_ev = mcap + debt
                ev_ebitda_mult = peer_ev / ebitda_val
            result = {"row": [float(v) for v in row], "multiple": float(mult), "code": code,
                    "sector": sector, "multiple_type": mt,
                    "ev_ebitda": float(ev_ebitda_mult) if ev_ebitda_mult is not None else None}
            self._save_ticker_cache(code, {"result": result})
            return result

        # Process sequentially to stay under J-Quants rate limits.
        # Early-exit once we have enough usable samples (2× min to be safe).
        enough = settings.ml_min_samples * 2
        for idx, info in enumerate(universe):
            if on_event and idx % 10 == 0 and idx > 0:
                on_event("valuation", f"Sampling {idx}/{len(universe)} tickers", {})
            try:
                result = _process_ticker(info)
            except Exception:
                continue
            if result is None:
                continue
            X.append(result["row"])
            y.append(result["multiple"])
            multiples.append(result["multiple"])
            peer_samples.append({
                "code": result["code"], "sector": result["sector"],
                "multiple_type": result["multiple_type"],
                "multiple_value": result["multiple"],
            })
            if result.get("ev_ebitda") is not None:
                peer_samples.append({
                    "code": result["code"], "sector": result["sector"],
                    "multiple_type": "EV/EBITDA",
                    "multiple_value": result["ev_ebitda"],
                })
            # Early exit once we have enough samples
            if len(y) >= enough:
                break
        self._peer_samples = peer_samples
        return X, y, columns, multiples

    def train_model(self, on_event=None):
        """Return cached model if available. Never train inline during report generation.

        Use ``train_model_background()`` (e.g. on server startup) to populate
        the cache.  This keeps report generation fast by avoiding the 150s+
        J-Quants rate-limit penalty.
        """
        meta_cached, model_cached = self._load_cached_model()
        if meta_cached and model_cached:
            return meta_cached, model_cached
        # No cached model — don't block the report; return None so ML method
        # is skipped (the LLM advisor will assign weight 0).
        return None, None

    def _train_model_sync(self, on_event=None):
        """Actually train the model (slow, ~60-120s due to J-Quants rate limits)."""
        X, y, columns, _ = self._build_training_set(settings.ml_max_tickers, on_event=on_event)
        if len(y) < settings.ml_min_samples:
            return None, None
        model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        X_arr = np.asarray(X, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        model.fit(X_arr, y_arr)
        preds = model.predict(X_arr)
        ss_tot = float(np.sum((y_arr - y_arr.mean()) ** 2))
        ss_res = float(np.sum((y_arr - preds) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
        resid_std = float(np.std(y_arr - preds))
        feature_medians = [float(np.nanmedian(X_arr[:, i])) for i in range(X_arr.shape[1])]
        meta = {
            "trained_at": dt.datetime.now().isoformat(timespec="seconds"),
            "columns": columns,
            "samples": len(y),
            "r2": r2,
            "resid_std": resid_std,
            "feature_medians": feature_medians,
            "peer_samples": getattr(self, "_peer_samples", []),
        }
        self._save_cached_model(meta, model)
        return meta, model

    def train_model_background(self):
        """Start model training in a background daemon thread.

        Call once at server startup.  The trained model is cached for
        ``settings.ml_cache_days`` days.  Subsequent ``train_model()`` calls
        return the cached result instantly.
        """
        meta, model = self._load_cached_model()
        if meta and model:
            return  # already cached
        t = threading.Thread(target=self._train_model_sync, daemon=True)
        t.start()

    # -------------------------------------------------------------------
    # Targeted sector-peer fetching from local universe
    # -------------------------------------------------------------------

    def _fetch_targeted_peer_multiples(
        self,
        stock_code: str,
        sector: str,
        on_event=None,
        max_peers: int = 8,
    ) -> List[Dict[str, Any]]:
        """Fetch real P/E, P/B, EV/EBITDA multiples for same-sector peers.

        Uses the local peer universe database to identify sector peers,
        then fetches their financials from J-Quants to compute actual
        multiples.  Results are cached for 7 days.
        """
        from app.services.peer_db import PeerDatabase

        # Check cache first
        cache_key = f"sector_peers_{sector.replace(' ', '_')}_{max_peers}.json"
        cache_path = self.cache_dir / cache_key
        try:
            if cache_path.exists():
                import json as _json
                cached = _json.loads(cache_path.read_text(encoding="utf-8"))
                cached_at = dt.datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
                if (dt.datetime.now() - cached_at).days <= 7:
                    return cached.get("peer_samples", [])
        except Exception:
            pass

        if not (self.jquants.api_key or self.jquants.refresh_token):
            return []

        db = PeerDatabase()
        peers = db.find_peers(stock_code, sector, n=max_peers, prefer_prime=True)
        if not peers:
            return []

        if on_event:
            on_event("valuation", f"Fetching {len(peers)} sector peer multiples", {})

        import time as _time

        peer_samples: List[Dict[str, Any]] = []

        for pidx, peer_info in enumerate(peers):
            code = peer_info["code"]
            try:
                _time.sleep(1.0)  # throttle to avoid 429
                fin = self.jquants.get_financials(code)
            except Exception:
                continue
            rows = _extract_financial_rows(fin)
            if not rows:
                continue
            raw_latest = rows[0]
            latest = _annualize_row(raw_latest)
            _time.sleep(1.0)
            p = self._fetch_latest_price(code)
            if not p or p <= 0:
                continue
            # Derive shares from NI/EPS (avoids extra company_info API call)
            ni_raw = raw_latest.get("net_income")
            eps_val = raw_latest.get("eps")
            if eps_val is None:
                stmts = fin.get("statements") or fin.get("data") or []
                if isinstance(stmts, list) and stmts:
                    eps_val = _to_float(stmts[0].get("EarningsPerShare") or stmts[0].get("EPS"))
            shares = None
            if ni_raw and eps_val and eps_val > 0:
                shares = abs(ni_raw / eps_val)
            # Fallback: equity / BPS
            if not shares or shares <= 0:
                eq = latest.get("equity")
                stmts = fin.get("statements") or fin.get("data") or []
                bps_val = None
                if isinstance(stmts, list) and stmts:
                    bps_val = _to_float(stmts[0].get("BPS") or stmts[0].get("BookValuePerShare"))
                if eq and bps_val and bps_val > 0:
                    shares = eq / bps_val
            if not shares or shares <= 0:
                continue
            mcap = shares * p
            if mcap <= 0:
                continue

            ni = latest.get("net_income")
            eq = latest.get("equity")
            rev = latest.get("revenue")
            ebitda = latest.get("ebitda")
            peer_sector = peer_info.get("sector33", sector)

            if ni and ni > 0:
                pe = mcap / ni
                if 1.0 < pe < 100.0:
                    peer_samples.append({"code": code, "sector": peer_sector,
                                    "multiple_type": "P/E", "multiple_value": pe})
            if eq and eq > 0:
                pb = mcap / eq
                if 0.1 < pb < 20.0:
                    peer_samples.append({"code": code, "sector": peer_sector,
                                    "multiple_type": "P/B", "multiple_value": pb})
            if rev and rev > 0:
                ps = mcap / rev
                if 0.05 < ps < 30.0:
                    peer_samples.append({"code": code, "sector": peer_sector,
                                    "multiple_type": "P/S", "multiple_value": ps})
            if ebitda and ebitda > 0 and eq:
                debt = _net_debt(latest)
                ev = mcap + debt
                ev_ebitda = ev / ebitda
                if 1.0 < ev_ebitda < 50.0:
                    peer_samples.append({"code": code, "sector": peer_sector,
                                    "multiple_type": "EV/EBITDA", "multiple_value": ev_ebitda})
            # Early exit once we have enough peer data points
            if len(peer_samples) >= 20:
                break

        # Cache results
        if peer_samples:
            try:
                import json as _json
                cache_path.write_text(
                    _json.dumps({
                        "cached_at": dt.datetime.now().isoformat(timespec="seconds"),
                        "sector": sector,
                        "peer_count": len(peers),
                        "peer_samples": peer_samples,
                    }, ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
            except Exception:
                pass

        return peer_samples

    # -------------------------------------------------------------------
    # Main entry point — AI-driven valuation
    # -------------------------------------------------------------------

    def estimate_for_company(
        self,
        stock_code: str,
        financials: Dict[str, Any],
        prices: Dict[str, Any],
        listed_info: Dict[str, Any] | None,
        segments: List[Dict[str, Any]] | None = None,
        on_event=None,
        company_name: str = "",
        sector_hint: str | None = None,
        edinet_narrative: str = "",
    ) -> ValuationResult | None:
        # --- Train ML model (best-effort; may return None if J-Quants unavailable) ---
        try:
            meta, model = self.train_model(on_event=on_event)
        except Exception:
            meta, model = None, None

        rows = _extract_financial_rows(financials)
        latest, prev = _extract_latest_metrics(rows)
        # Annualize flow metrics so valuation methods use full-year equivalents
        if latest:
            latest = _annualize_row(latest)
        if prev:
            prev = _annualize_row(prev)
        # Build FY-equivalent rows list for methods that need historical series
        # (e.g. DCF CAGR, Residual Income). Prepend annualized latest, then FY-only.
        fy_rows = [r for r in rows if (r.get("period_type") or "").upper() == "FY"]
        if latest:
            ann_rows = [latest] + fy_rows
        else:
            ann_rows = fy_rows
        if not latest:
            return None

        price = _latest_price_from_quotes(prices) if prices else None
        if price is not None and price <= 0:
            price = None

        info = listed_info or {}
        shares = None
        market_cap = _extract_market_cap(info)

        # Priority 1: derive shares from NI / EPS — keeps units consistent
        # (J-Quants financials are in raw yen; EPS is in yen/share,
        #  so NI/EPS gives shares as number-of-shares)
        if rows:
            raw_latest = rows[0]  # non-annualized
            ni_raw = raw_latest.get("net_income")
            eps_val = raw_latest.get("eps") if "eps" in raw_latest else None
            if eps_val is None:
                stmts = financials.get("statements") or financials.get("data") or []
                if isinstance(stmts, list) and stmts:
                    eps_val = _to_float(stmts[0].get("EarningsPerShare") or stmts[0].get("EPS"))
            if eps_val is None and prev:
                eps_val = prev.get("eps")
                prev_raw = rows[1] if len(rows) > 1 else None
                if prev_raw:
                    ni_raw = prev_raw.get("net_income")
            if ni_raw and eps_val and eps_val > 0:
                shares = abs(ni_raw / eps_val)

        # Priority 2: derive shares from Equity / BPS — also unit-consistent
        if (not shares or shares <= 0) and latest:
            eq = latest.get("equity")
            bps_val = None
            # Look for BPS in raw financial statements
            stmts = financials.get("statements") or financials.get("data") or []
            if isinstance(stmts, list) and stmts:
                bps_val = _to_float(stmts[0].get("BPS") or stmts[0].get("BookValuePerShare"))
            if eq and bps_val and bps_val > 0:
                shares = eq / bps_val

        # Priority 3: market_cap / price from listed_info
        if (not shares or shares <= 0) and market_cap and price:
            shares = market_cap / price

        # Priority 4: _extract_shares from listed_info (may have correct units)
        if not shares or shares <= 0:
            shares = _extract_shares(info)

        if market_cap is None and shares and price:
            market_cap = shares * price

        if not shares or shares <= 0:
            # Last resort: use equity / 1000 approximation
            eq = latest.get("equity") if latest else None
            if eq and eq > 0:
                shares = eq / 1000
            else:
                return None

        peer_samples = (meta.get("peer_samples") or []) if meta else []
        from app.services.sector_lookup import get_sector as _get_sector
        sector = sector_hint or info.get("Sector33CodeName") or info.get("Sector17CodeName") or _get_sector(stock_code) or "General"

        # --- Targeted peer fetching from local universe when ML peer data is sparse ---
        if len(peer_samples) < 10:
            try:
                targeted = self._fetch_targeted_peer_multiples(stock_code, sector, on_event)
                if targeted:
                    peer_samples = peer_samples + targeted
                    if on_event:
                        on_event("valuation", f"Added {len(targeted)} sector peer multiples", {})
            except Exception:
                pass

        # --- Check for dividends ---
        has_dividends = False
        for r in rows[:3]:
            if r.get("dividends") and r["dividends"] > 0:
                has_dividends = True
                break

        # --- LLM Advisor: pick methods & WACC ---
        if on_event:
            on_event("valuation", "AI advisor selecting valuation methods", {})
        advisor = _ask_valuation_advisor(
            company_name=company_name,
            stock_code=stock_code,
            sector_hint=sector,
            latest=latest,
            prev=prev,
            has_dividends=has_dividends,
            has_segments=bool(segments),
            edinet_narrative_snippet=edinet_narrative[:2000] if edinet_narrative else "",
        )
        weights = advisor.get("method_weights", {})
        wacc = advisor.get("wacc_estimate", settings.dcf_wacc)
        terminal_growth = advisor.get("terminal_growth", settings.dcf_terminal_growth)

        # Enforce minimum weights so key methods always run (they can
        # still produce price=None if underlying data is missing).
        _MIN_WEIGHTS = {"nav": 0.3, "pe_peer": 0.2, "pb_peer": 0.2, "ev_ebitda": 0.2, "epv": 0.2, "ev_revenue": 0.15, "graham": 0.15}
        for mkey, mmin in _MIN_WEIGHTS.items():
            if weights.get(mkey, 0) < mmin:
                weights[mkey] = mmin

        # --- Compute CAPM beta ---
        capm = _compute_capm(prices) if prices else {}

        # --- Run all methods with weight > 0 ---
        method_results: List[MethodResult] = []

        if weights.get("dcf", 0) > 0:
            r = _method_dcf(ann_rows, shares, wacc, terminal_growth)
            r.weight = weights["dcf"]
            method_results.append(r)

        if weights.get("ddm", 0) > 0:
            r = _method_ddm(latest, shares, price, wacc, terminal_growth)
            r.weight = weights["ddm"]
            method_results.append(r)

        if weights.get("ev_ebitda", 0) > 0:
            r = _method_ev_ebitda(latest, shares, price, peer_samples, sector, market_cap)
            r.weight = weights["ev_ebitda"]
            method_results.append(r)

        if weights.get("pe_peer", 0) > 0:
            r = _method_pe_peer(latest, shares, peer_samples, sector, current_price=price)
            r.weight = weights["pe_peer"]
            method_results.append(r)

        if weights.get("pb_peer", 0) > 0:
            r = _method_pb_peer(latest, shares, peer_samples, sector, current_price=price)
            r.weight = weights["pb_peer"]
            method_results.append(r)

        if weights.get("nav", 0) > 0:
            r = _method_nav(latest, shares)
            r.weight = weights["nav"]
            method_results.append(r)

        if weights.get("epv", 0) > 0:
            r = _method_epv(latest, shares, wacc)
            r.weight = weights["epv"]
            method_results.append(r)

        if weights.get("sotp", 0) > 0:
            r = _method_sotp(segments, shares, peer_samples, sector)
            r.weight = weights["sotp"]
            method_results.append(r)

        if weights.get("residual_income", 0) > 0:
            r = _method_residual_income(latest, ann_rows, shares, wacc, capm=capm)
            r.weight = weights["residual_income"]
            method_results.append(r)

        if weights.get("ml_ridge", 0) > 0:
            r = _method_ml_ridge(latest, prev, shares, model, meta)
            r.weight = weights["ml_ridge"]
            method_results.append(r)

        if weights.get("ev_revenue", 0) > 0:
            r = _method_ev_revenue(latest, shares, peer_samples, sector, market_cap)
            r.weight = weights["ev_revenue"]
            method_results.append(r)

        if weights.get("graham", 0) > 0:
            r = _method_graham(latest, shares)
            r.weight = weights["graham"]
            method_results.append(r)

        if weights.get("reverse_dcf", 0) > 0:
            r = _method_reverse_dcf(latest, rows, shares, price, wacc, terminal_growth)
            r.weight = weights["reverse_dcf"]
            method_results.append(r)

        if weights.get("div_yield_model", 0) > 0:
            r = _method_dividend_yield(latest, shares, sector)
            r.weight = weights["div_yield_model"]
            method_results.append(r)

        # --- Compute extended financial metrics ---
        extended_metrics: Dict[str, Any] = {}
        if capm:
            extended_metrics["beta"] = capm.get("beta")
            extended_metrics["cost_of_equity"] = capm.get("cost_of_equity")
            extended_metrics["risk_free_rate"] = capm.get("risk_free_rate")
            extended_metrics["equity_risk_premium"] = capm.get("equity_risk_premium")
            extended_metrics["annualised_vol"] = capm.get("annualised_vol")
        # ROIC: NOPAT / invested capital
        op_val = latest.get("operating_profit")
        eq_val = latest.get("equity")
        debt_val = _net_debt(latest) if latest else None
        if op_val and eq_val and debt_val is not None and (eq_val + debt_val) > 0:
            nopat = op_val * 0.70
            extended_metrics["roic"] = round(nopat / (eq_val + debt_val), 4)
        ni_val = latest.get("net_income")
        fcf_val = latest.get("fcf")
        if ni_val and market_cap and market_cap > 0:
            extended_metrics["earnings_yield"] = round(ni_val / market_cap, 4)
        if fcf_val and market_cap and market_cap > 0:
            extended_metrics["fcf_yield"] = round(fcf_val / market_cap, 4)
        rev_val = latest.get("revenue")
        if rev_val and rev_val > 0 and market_cap and debt_val is not None:
            extended_metrics["ev_revenue"] = round((market_cap + debt_val) / rev_val, 2)
        if eq_val and eq_val > 0 and debt_val is not None:
            extended_metrics["debt_equity"] = round(debt_val / eq_val, 2)
        # Implied growth from reverse DCF
        for mr in method_results:
            if mr.key == "reverse_dcf" and mr.details.get("implied_growth_rate") is not None:
                extended_metrics["implied_growth"] = mr.details["implied_growth_rate"]
                break

        # --- Blend ---
        target_price, target_low, target_high, method_count = _blend_methods_v2(method_results)

        upside_pct = None
        if price and target_price:
            upside_pct = (target_price / price - 1) * 100

        latest_period = latest.get("period") if latest else None
        quality = _quality_score_v2(method_results, int((meta or {}).get("samples", 0)), len(rows), latest_period, extended_metrics=extended_metrics)

        # --- Build legacy-compatible fields ---
        def _find(key):
            for mr in method_results:
                if mr.key == key and mr.price is not None:
                    return mr
            return None

        dcf_r = _find("dcf")
        pe_r = _find("pe_peer")
        pb_r = _find("pb_peer")
        ml_r = _find("ml_ridge")
        sotp_r = _find("sotp")

        # Model type from ML or best available
        model_type = None
        if ml_r and ml_r.details.get("model_type"):
            model_type = ml_r.details["model_type"]
        elif pe_r:
            model_type = "P/E"
        elif pb_r:
            model_type = "P/B"

        # Peer from best peer method
        peer_r = pe_r or pb_r
        peer_multiple = peer_r.details.get("peer_pe") or peer_r.details.get("peer_pb") if peer_r else None

        # Build narrative
        active = [r for r in method_results if r.price is not None and r.weight > 0]
        narrative_parts = []
        if advisor.get("reasoning"):
            narrative_parts.append(f"AI Advisor: {advisor['reasoning']}")
        for mr in sorted(active, key=lambda x: x.weight, reverse=True):
            narrative_parts.append(
                f"{mr.name} (weight {mr.weight:.0%}): ¥{mr.price:,.0f} "
                f"[¥{mr.range_low:,.0f}–¥{mr.range_high:,.0f}] — {mr.reasoning}"
                if mr.range_low and mr.range_high else
                f"{mr.name} (weight {mr.weight:.0%}): ¥{mr.price:,.0f} — {mr.reasoning}"
            )

        notes = [
            f"Primary method: {advisor.get('primary_method', 'N/A')}",
            f"Sector: {advisor.get('sector_classification', 'N/A')}",
            f"Methods used: {method_count}",
            f"WACC: {wacc*100:.1f}%",
        ]

        return ValuationResult(
            model_type=model_type,
            samples=int((meta or {}).get("samples", 0)),
            r2=(meta or {}).get("r2"),
            predicted_multiple=ml_r.details.get("predicted_multiple") if ml_r else None,
            actual_multiple=None,  # computed downstream if needed
            implied_price=ml_r.price if ml_r else None,
            range_low=ml_r.range_low if ml_r else None,
            range_high=ml_r.range_high if ml_r else None,
            score_z=None,
            peer_multiple=peer_multiple,
            peer_price=peer_r.price if peer_r else None,
            peer_range_low=peer_r.range_low if peer_r else None,
            peer_range_high=peer_r.range_high if peer_r else None,
            dcf_price=dcf_r.price if dcf_r else None,
            dcf_range_low=dcf_r.range_low if dcf_r else None,
            dcf_range_high=dcf_r.range_high if dcf_r else None,
            sotp_price=sotp_r.price if sotp_r else None,
            sotp_range_low=sotp_r.range_low if sotp_r else None,
            sotp_range_high=sotp_r.range_high if sotp_r else None,
            last_price=price,
            market_cap=market_cap,
            shares=shares,
            target_price=target_price,
            target_low=target_low,
            target_high=target_high,
            upside_pct=upside_pct,
            quality_score=quality,
            method_count=method_count,
            notes=notes,
            advisor=advisor,
            method_results=[
                {
                    "name": mr.name,
                    "key": mr.key,
                    "price": mr.price,
                    "range_low": mr.range_low,
                    "range_high": mr.range_high,
                    "weight": mr.weight,
                    "reasoning": mr.reasoning,
                    "details": mr.details,
                }
                for mr in method_results
            ],
            primary_method=advisor.get("primary_method", ""),
            sector_classification=advisor.get("sector_classification", ""),
            valuation_narrative="\n".join(narrative_parts),
            extended_metrics=extended_metrics,
        )
