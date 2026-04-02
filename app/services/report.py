from __future__ import annotations

import json
import datetime as dt
import html as html_lib
import re
import time
from urllib.parse import urlparse

import httpx
from pathlib import Path
from typing import Dict, List, Any

import markdown

from app.config import settings
from app.services.serp import SerpClient
from app.services.edinet import EdinetClient
from app.services.jquants import JQuantsClient
from app.services.llm import LlmClient
from app.services.cache import load_cache, save_cache
from app.services.valuation import ValuationEngine
from app.services.concurrent import run_concurrent, run_concurrent_dict

# ── Activist & Engagement Radar constants ──
_KNOWN_ACTIVISTS = {
    "elliott", "valueact", "oasis management", "oasis", "strategic capital",
    "dalton investments", "asset value investors", "nippon active value",
    "オアシス", "エリオット", "ストラテジック・キャピタル", "ダルトン",
}
_ACTIVIST_PURPOSE_KEYWORDS = ["提案", "経営", "資本"]
_POISON_PILL_KEYWORDS = ["買収防衛策", "ポイズンピル", "ライツプラン", "事前警告型"]


def _safe_json(data: Dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _normalize_stock_code(stock_code: str) -> str:
    cleaned = stock_code.strip().upper().replace(".T", "")
    return cleaned


def _coerce_company_name(input_name: str | None, jquants_name: str | None) -> str:
    if input_name:
        return input_name
    return jquants_name or "Unknown Company"

def _prefer_japanese_name(name: str | None) -> str | None:
    """
    If the name contains Japanese inside parentheses, return the Japanese portion.
    Example: 'Kabushikigaisha Aru Puranna (株式会社アールプランナー)' -> '株式会社アールプランナー'
    """
    if not name:
        return name
    if "(" in name and ")" in name:
        inner = name[name.find("(") + 1 : name.rfind(")")]
        # simple heuristic: if inner has Japanese characters, prefer it
        if _contains_japanese(inner):
            return inner.strip()
    return name

def _classify_sector_stub(stock_code: str, fallback: str = "General") -> str:
    from app.services.sector_lookup import get_sector as _get_sector
    return _get_sector(stock_code) or KNOWN_CODE_SECTOR_MAP.get(stock_code) or fallback

KNOWN_CODE_NAME_JP = {
    "2983": "株式会社アールプランナー",
    "6501": "株式会社日立製作所",
    "9984": "ソフトバンクグループ株式会社",
    "3697": "株式会社SHIFT",
    "7203": "トヨタ自動車株式会社",
    "6758": "ソニーグループ株式会社",
    "6861": "株式会社キーエンス",
    "9432": "日本電信電話株式会社",
    "8306": "株式会社三菱UFJフィナンシャル・グループ",
}
KNOWN_CODE_NAME_EN = {
    "2983": "Arr Planner Co., Ltd.",
    "6501": "Hitachi, Ltd.",
    "9984": "SoftBank Group Corp.",
    "3697": "SHIFT Inc.",
    "7203": "Toyota Motor Corporation",
    "6758": "Sony Group Corporation",
    "6861": "Keyence Corporation",
    "9432": "Nippon Telegraph and Telephone Corporation",
    "8306": "Mitsubishi UFJ Financial Group, Inc.",
}
KNOWN_CODE_SECTOR_MAP = {
    "2983": "Homebuilding / Residential Real Estate",
    "6501": "Industrial Conglomerates / Electronics",
}
# Known head office overrides for companies where LLM enrichment may confuse
# parent HQ (in Japan) with foreign subsidiary HQ.
KNOWN_CODE_HEAD_OFFICE = {
    "9984": "Tokyo, Japan (Minato-ku)",
    "6501": "Tokyo, Japan (Chiyoda-ku)",
    "7203": "Toyota City, Aichi, Japan",
    "6758": "Tokyo, Japan (Minato-ku)",
}


def _serp_company_name_hint(serp_results) -> str | None:
    if not serp_results:
        return None
    # Use the first meaningful title/snippet chunk before separators like "-" or "|"
    for item in serp_results:
        title = (getattr(item, "title", None) or "").strip()
        if title:
            # drop site suffixes
            for sep in (" - ", " | ", " — "):
                if sep in title:
                    title = title.split(sep)[0].strip()
                    break
            if 2 <= len(title) <= 80:
                return title
        snippet = (getattr(item, "snippet", None) or "").strip()
        if snippet:
            for sep in (" - ", " | ", " — "):
                if sep in snippet:
                    snippet = snippet.split(sep)[0].strip()
                    break
            if 2 <= len(snippet) <= 80:
                return snippet
    return None


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


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator


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


def _format_number(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1_000_000_000:
        return f"{value/1_000_000_000:,.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value/1_000_000:,.2f}M"
    return f"{value:,.0f}"


def _format_short(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}{suffix}"


def _format_compact(value: float | None) -> str:
    if value is None:
        return "—"
    abs_val = abs(value)
    if abs_val >= 1_000_000_000_000:
        return f"{value/1_000_000_000_000:.1f}T"
    if abs_val >= 1_000_000_000:
        return f"{value/1_000_000_000:.1f}B"
    if abs_val >= 1_000_000:
        return f"{value/1_000_000:.1f}M"
    return f"{value:,.0f}"


def _format_period_label(period: str | None) -> str:
    if not period:
        return "-"
    dt_val = _parse_date(period)
    if not dt_val:
        return str(period)
    return dt_val.strftime("%b '%y")


def _series_from_rows(rows: List[Dict[str, Any]], key: str, count: int = 5, scale: float = 1.0) -> List[Dict[str, Any]]:
    series = []
    for row in list(reversed(rows[-count:])):
        value = row.get(key)
        if value is not None:
            value = float(value) / scale
        series.append({
            "label": _format_period_label(row.get("period")),
            "value": value,
        })
    return series


def _normalize_series(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    values = [abs(item["value"]) for item in series if item.get("value") is not None]
    max_val = max(values) if values else 0
    for item in series:
        val = item.get("value")
        if val is None or max_val == 0:
            item["height"] = 0
        else:
            item["height"] = max(8, int((abs(val) / max_val) * 100))
    return series


def _avg_volume(rows: List[Dict[str, Any]], window: int = 90) -> float | None:
    if not rows:
        return None
    # Use the last 90 trading days for the average
    tail = rows[-window:] if len(rows) >= window else rows
    vols = [r.get("volume") for r in tail if r.get("volume") is not None]
    return float(sum(vols) / len(vols)) if vols else None


def _format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


# === J-Quants v2 helpers for clean snapshot & history ===

def _extract_price_list(prices: Dict) -> List[Dict[str, Any]]:
    if not isinstance(prices, dict):
        return []
    data = prices.get("daily_quotes") or prices.get("data") or []
    if isinstance(data, dict):
        data = [data]
    return data


def _detect_split_multiplier(price_history: List[Dict[str, Any]]) -> float:
    """
    Detect stock split from AdjFactor (J-Quants v2 uses values < 1.0 for splits).
    Returns the multiplier to adjust historical per-share metrics.
    """
    multiplier = 1.0
    for day in price_history:
        adj = _to_float_safe(day.get("AdjFactor") or day.get("AdjustmentFactor"))
        if adj is not None and 0 < adj < 1.0:
            # Accumulate ALL split factors (multiply them together)
            # so that multiple splits (e.g. 5:1 then 2:1) are handled correctly.
            multiplier *= (1.0 / adj)
    return multiplier


def _latest_price(price_history: List[Dict[str, Any]]) -> float | None:
    if not price_history:
        return None
    last = price_history[-1]
    return _to_float_safe(
        last.get("AdjustmentClose")
        or last.get("AdjClose")
        or last.get("Close")
        or last.get("C")
    )


def _compute_clean_kpi(financials_raw: Dict, prices_raw: Dict) -> Dict[str, Any] | None:
    """
    Recompute headline KPIs using J-Quants v2 summary + price history, with split handling.
    Returns None if required fields are missing.
    """
    statements = financials_raw.get("statements") or financials_raw.get("data")
    if not statements:
        return None
    if isinstance(statements, dict):
        statements = [statements]
    
    # Sort by disclosure date (newest first)
    statements = sorted(statements, key=lambda r: r.get("DiscDate", ""), reverse=True)
    latest = statements[0]

    price_history = _extract_price_list(prices_raw)
    current_price = _latest_price(price_history)
    if current_price is None:
        return None

    split_multiplier = _detect_split_multiplier(price_history) or 1.0

    # --- Determine best EPS for P/E: prefer full-year or forecast over interim ---
    period_type = latest.get("CurPerType", "")  # "FY", "3Q", "2Q", "1Q"
    raw_eps = _to_float_safe(latest.get("EPS")) or 0
    eps_for_pe = raw_eps  # default to raw EPS

    if period_type != "FY" and raw_eps > 0:
        # Interim cumulative EPS — not suitable for P/E without adjustment.
        # 1) Prefer forecast full-year EPS (FEPS) if available
        feps = _to_float_safe(latest.get("FEPS"))
        if feps and feps > 0:
            eps_for_pe = feps
        else:
            # 2) Annualise interim EPS based on period type
            annualise_factor = {"3Q": 4/3, "2Q": 2, "1Q": 4}.get(period_type)
            if annualise_factor:
                eps_for_pe = raw_eps * annualise_factor
            else:
                # 3) Try latest FY statement
                for stmt in statements:
                    if stmt.get("CurPerType") == "FY":
                        fy_eps = _to_float_safe(stmt.get("EPS"))
                        if fy_eps and fy_eps > 0:
                            eps_for_pe = fy_eps
                        break

    net_profit = _to_float_safe(latest.get("NP")) or 0
    equity = _to_float_safe(latest.get("Eq")) or 0
    assets = _to_float_safe(latest.get("TA")) or 0

    # Operating profit and revenue for EBIT margin (use _pick_value to handle 0 correctly)
    revenue = _pick_value(latest, ["NetSales", "Revenue", "Sales", "OperatingRevenue"])
    op_profit = _pick_value(latest, ["OperatingProfit", "OperatingIncome", "OP"])
    ocf = _pick_value(latest, ["CashFlowsFromOperatingActivities", "OperatingCashFlow", "CFO"])

    raw_div = _to_float_safe(latest.get("FDivAnn"))
    if raw_div is None:
        raw_div = _to_float_safe(latest.get("DivAnn")) or 0

    # Shares: Infer from NP/EPS to match working script
    base_shares = (net_profit / raw_eps) if raw_eps not in (None, 0) else 0
    if base_shares == 0:
        # fallback to explicit field if inference fails
        base_shares = _to_float_safe(latest.get("IssuedShare") or latest.get("IssuedShares")) or 0

    if base_shares == 0:
        return None

    eps = eps_for_pe / split_multiplier if split_multiplier > 1 else eps_for_pe
    div_annual = raw_div / split_multiplier if (raw_div is not None and split_multiplier > 1) else raw_div
    current_shares = base_shares * split_multiplier

    market_cap = current_price * current_shares
    bps = (equity / current_shares) if (equity and current_shares > 0) else 0
    # Fallback: use raw BPS from J-Quants when equity is missing
    if not bps:
        bps = _to_float_safe(latest.get("BPS")) or 0
    pbr = (current_price / bps) if bps > 0 else None
    per = (current_price / eps) if eps > 0 else None
    # ROE: use net_profit / equity (consistent with _compute_financial_kpis)
    roe = (net_profit / equity) if (net_profit > 0 and equity > 0) else None
    # Annualise interim ROE so it's comparable to full-year rates
    if roe is not None and period_type != "FY":
        annualise_roe = {"1Q": 4, "2Q": 2, "3Q": 4/3}.get(period_type, 1)
        roe = roe * annualise_roe
    div_yield = (div_annual / current_price) if current_price > 0 else None
    equity_ratio = (equity / assets) if assets > 0 else None

    ebit_pct = round(op_profit / revenue * 100, 1) if (op_profit is not None and revenue and revenue > 0) else None
    ocf_pct = round(ocf / revenue * 100, 0) if (ocf is not None and revenue and revenue > 0) else None

    # EV/EBITDA: Enterprise Value / EBITDA (using OP as EBITDA proxy)
    # Annualise interim OP for EV/EBITDA
    ev_ebitda = None
    if op_profit and op_profit > 0 and market_cap:
        ann_op = op_profit
        if period_type != "FY":
            ann_factor = {"1Q": 4, "2Q": 2, "3Q": 4/3}.get(period_type, 1)
            ann_op = op_profit * ann_factor
        borrowings = _to_float_safe(latest.get("Borrowings")) or _to_float_safe(latest.get("TotalDebt")) or 0
        cash_equiv = _to_float_safe(latest.get("CashAndEquivalents")) or _to_float_safe(latest.get("CashAndDeposits")) or 0
        net_debt = borrowings - cash_equiv
        ev = market_cap + net_debt
        if ann_op > 0:
            ev_ebitda = ev / ann_op

    kpi = {
        "price": current_price,
        "market_cap_raw": market_cap,
        "pbr": pbr,
        "pb_value": pbr,  # alias for clarity in template
        "per": per,
        "roe": roe,
        "div_yield": div_yield,
        "bps": bps,
        "eps": eps,
        "dps": div_annual,
        "equity_ratio": equity_ratio,
        "ebit_pct": ebit_pct,
        "ocf_pct": ocf_pct,
        "ev_ebitda": ev_ebitda,
        "market_cap_display": None,
        "split_multiplier": split_multiplier,
    }

    if market_cap is not None:
        if market_cap < 1_000_000_000_000:
            kpi["market_cap_display"] = f"¥{market_cap/1_000_000_000:,.1f}B"
            kpi["market_cap"] = market_cap / 1_000_000_000  # numeric in billions
        else:
            kpi["market_cap_display"] = f"¥{market_cap/1_000_000_000_000:,.2f}T"
            kpi["market_cap"] = market_cap / 1_000_000_000_000  # numeric in trillions
    return kpi


def _build_clean_history(financials_raw: Dict, split_multiplier: float = 1.0) -> List[Dict[str, Any]]:
    """
    Build a clean 5-year history focused on FY and 2Q, choosing the best disclosure per period.
    Output values are numeric (roe_ratio as decimal, ocf_bil, dps) plus labels for charts.
    """
    reports = financials_raw.get("statements") or financials_raw.get("data")
    if not reports:
        return []
    if isinstance(reports, dict):
        reports = [reports]

    best_reports: Dict[str, Dict[str, Any]] = {}

    def score_report(r: Dict[str, Any]) -> int:
        score = 0
        if _to_float_safe(r.get("NP")) is not None:
            score += 2
        if _to_float_safe(r.get("CFO")) is not None:
            score += 2
        if _to_float_safe(r.get("DivAnn")) is not None:
            score += 1
        if _to_float_safe(r.get("Div2Q")) is not None:
            score += 1
        return score

    for r in reports:
        ptype = r.get("CurPerType", "")
        if ptype not in ("FY", "2Q"):
            continue
        fy_end = r.get("CurFYEn", "")
        if not fy_end:
            continue
        key = f"{fy_end}_{ptype}"
        r_score = score_report(r)
        disc_date = r.get("DiscDate", "")
        existing = best_reports.get(key)
        if not existing or r_score > existing["score"] or (r_score == existing["score"] and disc_date > existing["date"]):
            best_reports[key] = {"report": r, "score": r_score, "date": disc_date}

    clean_list = [v["report"] for v in best_reports.values()]
    clean_list.sort(key=lambda x: (x.get("CurFYEn", ""), x.get("CurPerType", "")), reverse=True)

    history: List[Dict[str, Any]] = []
    for r in clean_list:
        raw_date = r.get("DiscDate", "") or r.get("CurFYEn", "")
        display_date = _format_period_label(raw_date)
        ptype = r.get("CurPerType", "")

        cfo = _to_float_safe(r.get("CFO"))
        ocf_bil = cfo / 1_000_000_000 if cfo is not None else None
        # Annualise interim OCF so chart shows comparable annual rates
        _ocf_ann = {"1Q": 4, "2Q": 2, "3Q": 4 / 3}.get(ptype, 1)
        if ocf_bil is not None and _ocf_ann != 1:
            ocf_bil = ocf_bil * _ocf_ann

        np_val = _to_float_safe(r.get("NP"))
        eq_val = _to_float_safe(r.get("Eq"))
        roe_ratio = (np_val / eq_val) if (np_val is not None and eq_val not in (None, 0)) else None
        # Annualise interim ROE so chart/narrative show comparable annual rates
        if roe_ratio is not None and ptype in ("1Q", "2Q", "3Q"):
            roe_ratio = roe_ratio * _ocf_ann

        raw_div = None
        if ptype == "FY":
            raw_div = _to_float_safe(r.get("DivAnn"))
        elif ptype == "2Q":
            raw_div = _to_float_safe(r.get("Div2Q"))
        dps = None
        if raw_div is not None:
            dps = raw_div / split_multiplier if split_multiplier > 1 else raw_div

        # skip if completely empty
        if roe_ratio is None and ocf_bil is None and dps is None:
            continue

        history.append({
            "label": display_date,
            "type": ptype,
            "roe_ratio": roe_ratio,
            "ocf_bil": ocf_bil,
            "dps": dps,
        })

    return history


def _to_float_safe(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1].strip()
        if cleaned in {"", "-", "—"}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _coerce_percent_value(value: Any) -> float | None:
    return _to_float_safe(value)


_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def _contains_japanese(text: str | None) -> bool:
    if not text:
        return False
    return bool(_JAPANESE_RE.search(text))


def _contains_japanese_in_json(obj: Any) -> bool:
    if isinstance(obj, str):
        return _contains_japanese(obj)
    if isinstance(obj, list):
        return any(_contains_japanese_in_json(item) for item in obj)
    if isinstance(obj, dict):
        return any(_contains_japanese_in_json(value) for value in obj.values())
    return False


def _parse_yen_number(text: str) -> float | None:
    if not text:
        return None
    nums = re.findall(r"[¥$]?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)", text)
    best = None
    for n in nums:
        try:
            val = float(n.replace(",", ""))
            if best is None or val > best:
                best = val
        except Exception:
            continue
    return best


def _extract_ownership_from_text(text: str) -> Dict[str, float | None]:
    """
    Rough extraction of ownership mix from EDINET narrative tables.
    We look for 6 percentage numbers in sequence; the common order in EDINET is:
    government, financial institutions, financial instruments firms, other corporations,
    foreign, individuals/others.
    """
    empty = {"foreign": None, "institutional": None, "corporate": None, "individual": None}
    if not text:
        return empty

    # Pass 1: table-like six-number extraction
    nums = re.findall(r"(\d{1,3}(?:\.\d{1,2})?)%", text)
    values = [float(n) for n in nums]
    if len(values) >= 6:
        gov, fin_inst, fin_instr, other_corp, foreign, individual = values[:6]
        return {
            "foreign": foreign,
            "institutional": fin_inst,
            "corporate": other_corp,
            "individual": individual,
            "government": gov,
            "securities_firms": fin_instr,
        }

    # Pass 2: label-guided regex (handles noisy EDINET narrative text)
    buckets = {
        "foreign": [r"外国法人等", r"外国人", r"外国", r"FOREIGN"],
        "institutional": [r"金融機関", r"保険", r"BANK", r"INSTITUTION"],
        "corporate": [r"その他の法人", r"法人", r"CORP"],
        "individual": [r"個人", r"個人その他", r"INDIVIDUAL"],
    }
    found: Dict[str, float] = {}
    for key, patterns in buckets.items():
        for pat in patterns:
            m = re.search(pat + r".{0,30}?(\d{1,3}(?:\.\d{1,2})?)%", text, flags=re.IGNORECASE | re.DOTALL)
            if m:
                try:
                    found[key] = float(m.group(1))
                    break
                except Exception:
                    continue
    # If at least two categories found, return partial mix
    if len(found) >= 2:
        return {
            "foreign": found.get("foreign"),
            "institutional": found.get("institutional"),
            "corporate": found.get("corporate"),
            "individual": found.get("individual"),
        }
    return empty


def _classify_shareholders_to_ownership(shareholders: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Classify major shareholders into ownership categories using keyword matching.
    Returns approximate ownership mix derived from the top shareholder list.
    """
    if not shareholders:
        return {}

    # Domestic institutional: Japanese trust banks, insurance, custodians, asset managers
    # Includes English names of major Japanese custodian banks (often appear in
    # J-Quants shareholder lists as English names)
    _DOMESTIC_INST_KW = [
        "信託銀行", "信託", "生命保険", "損害保険", "火災保険",
        "アセットマネジメント", "投資顧問", "投信", "運用",
        "ファンド", "キャピタル", "年金",
        "カストディ", "マスタートラスト",
        # English names of key Japanese domestic custodian banks
        "master trust bank of japan", "custody bank of japan",
        "japan trustee", "trust & custody",
        "japan securities finance",
        # English names of major Japanese insurers
        "nippon life", "dai-ichi life", "meiji yasuda",
        "sumitomo life", "tokio marine", "mitsui sumitomo",
        "sompo", "aioi nissay",
        # English names of Japanese banks/brokers (specific enough to avoid false matches)
        "mufg", "mizuho", "smbc", "resona",
        "nomura securities", "nomura asset", "nomura trust",
        "daiwa securities", "daiwa asset",
        "nikko asset", "nikko securities",
    ]
    # Foreign entities: katakana names of foreign institutions + ASCII equivalents
    _FOREIGN_ENTITY_KW = [
        # Katakana foreign institution names (as they appear on Kabutan)
        "ストリート", "モルガン", "ゴールドマン", "サックス",
        "バークレイズ", "メロン", "バンガード", "ブラックロック",
        "フィデリティ", "インベスコ", "シュローダー", "ラザード",
        "ウェリントン", "ディメンショナル", "モクスレイ",
        "チェース", "テマセク", "ノルジェス",
        "バンク", "トラスト",  # katakana "bank"/"trust" → foreign banks
        "インターナショナル",
        # ASCII foreign institution names
        "blackrock", "vanguard", "state street", "fidelity", "jpmorgan",
        "goldman sachs", "morgan stanley", "ubs", "barclays", "hsbc",
        "aberdeen", "invesco", "schroders", "lazard", "wellington",
        "dimensional", "norges", "calpers", "gic", "temasek",
        "moxley", "bny", "citibank", "credit suisse",
    ]
    _FOREIGN_KW = ["外国", "foreign"]
    _CORPORATE_KW = [
        "株式会社", "有限会社", "合同会社", "合資会社", "合名会社",
        "corp", "inc", "ltd", "co.", "gmbh", "llc",
        "holdings", "ホールディングス", "グループ",
        "財団法人", "社団法人",
        "自社",  # treasury stock = corporate
    ]
    # Generic institutional keywords (English terms)
    _GENERIC_INST_KW = [
        "asset management", "life insurance", "investment",
        "fund", "capital", "pension", "mutual",
        "advisory", "management", "bank", "銀行", "証券",
    ]

    buckets: Dict[str, float] = {"foreign": 0.0, "institutional": 0.0, "corporate": 0.0, "individual": 0.0}

    for sh in shareholders:
        name = (sh.get("name") or "").strip()
        pct = sh.get("pct")
        if not name or not pct:
            continue
        try:
            pct = float(pct)
        except (ValueError, TypeError):
            continue
        if pct <= 0 or pct > 100:
            continue

        name_lower = name.lower()
        # 1. Domestic institutional (Japanese trust banks, insurance, custodians)
        if any(kw in name_lower for kw in _DOMESTIC_INST_KW):
            buckets["institutional"] += pct
        # 2. Foreign entities (katakana foreign names, ASCII foreign names)
        elif any(kw in name_lower for kw in _FOREIGN_ENTITY_KW):
            buckets["foreign"] += pct
        elif any(kw in name_lower for kw in _FOREIGN_KW):
            buckets["foreign"] += pct
        # 3. Corporate (Japanese company suffixes, treasury stock)
        elif any(kw in name_lower for kw in _CORPORATE_KW):
            buckets["corporate"] += pct
        # 4. Generic institutional (English keywords like "bank", "management")
        elif any(kw in name_lower for kw in _GENERIC_INST_KW):
            buckets["institutional"] += pct
        # 5. ASCII names without other matches → likely foreign
        elif name.isascii() and len(name) > 3:
            buckets["foreign"] += pct
        else:
            # Japanese names without any keywords → likely individuals
            buckets["individual"] += pct

    # Round values
    buckets = {k: round(v, 2) for k, v in buckets.items()}

    # Only return if we classified something meaningful
    if any(v > 0 for v in buckets.values()):
        return buckets
    return {}


def _extract_major_shareholders(text: str, limit: int = 6) -> List[Dict[str, Any]]:
    """
    Heuristic extraction of major shareholders from EDINET narrative text.
    Looks for patterns like 'Name 12.3%' and returns up to `limit` entries.
    """
    if not text:
        return []
    candidates = []
    for match in re.finditer(r"([\w\u3040-\u30ff\u3400-\u9fff・\-.\s]{2,40})\s*(\d{1,2}(?:\.\d{1,2})?)%", text):
        name = match.group(1).strip().strip("・,，")
        pct = match.group(2)
        try:
            pct_val = float(pct)
        except Exception:
            continue
        if 0 < pct_val <= 100 and name:
            candidates.append({"name": name, "pct": pct_val})
    # Deduplicate by name, keep largest pct
    merged = {}
    for c in candidates:
        if c["name"] not in merged or c["pct"] > merged[c["name"]]["pct"]:
            merged[c["name"]] = c
    ranked = sorted(merged.values(), key=lambda x: x["pct"], reverse=True)
    return ranked[:limit]


def _extract_shares_from_text(text: str) -> float | None:
    """
    Heuristic extraction of issued shares from EDINET narrative or SERP snippets.
    Patterns: '発行済株式総数 12,345,678株', 'shares outstanding 12,345,678'.
    """
    if not text:
        return None
    patterns = [
        r"発行済株式総数\s*[:：]?\s*([0-9,]+)株",
        r"総発行株式数\s*[:：]?\s*([0-9,]+)株",
        r"issued shares\s*[:：]?\s*([0-9,]+)",
        r"shares outstanding\s*[:：]?\s*([0-9,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except Exception:
                continue
    # fallback: pick largest yen-like number if followed by '株'
    m = re.search(r"([0-9]{1,3}(?:,[0-9]{3})+)\s*株", text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except Exception:
            return None
    return None


def _fetch_major_shareholders_web(stock_code: str, company_name: str) -> Dict[str, Any]:
    """
    Use SerpAPI to find shareholder pages, fetch HTML, and extract data via LLM.
    Uses BeautifulSoup to find the specific table section like the working Spyder script.
    """
    from bs4 import BeautifulSoup
    serp = SerpClient()
    llm = LlmClient()
    
    priority_urls = [
        f"https://kabutan.jp/stock/holder?code={stock_code}",
        f"https://kabutan.jp/stock/kabunushi?code={stock_code}",
        f"https://minkabu.jp/stock/{stock_code}/major_shareholders",
    ]
    
    try:
        query = f"{stock_code} 大株主 持株比率 株主名"
        serp_results = serp.search(query, num=5)
        for res in serp_results:
            link = res.url or ""
            if any(domain in link for domain in ["kabutan", "minkabu", "nikkei", "buffett-code"]):
                if link not in priority_urls:
                    priority_urls.insert(0, link)
    except Exception:
        pass

    snippet = ""
    HOLDER_KEYWORDS = ["株主名", "大株主", "持株比率", "保有株数", "所有株式数"]

    # Fetch all candidate URLs concurrently
    fetch_tasks = [lambda u=url: _fetch_url_text(u, max_chars=100000, strip=False) for url in priority_urls]
    fetched_htmls = run_concurrent(fetch_tasks, max_workers=min(6, len(fetch_tasks)))

    for url, html in zip(priority_urls, fetched_htmls):
        if not html:
            continue

        if not any(kw in html for kw in HOLDER_KEYWORDS):
            continue

        try:
            soup = BeautifulSoup(html, "html.parser")
            found_table = False
            for table in soup.find_all("table"):
                header_text = " ".join(th.get_text(strip=True) for th in table.find_all("th"))
                if any(kw in header_text for kw in HOLDER_KEYWORDS):
                    snippet = str(table)
                    found_table = True
                    break

            if not found_table:
                for tag in soup.find_all(["div", "section", "article"]):
                    text = tag.get_text()
                    if sum(1 for kw in HOLDER_KEYWORDS if kw in text) >= 2:
                        if len(str(tag)) < 30000:
                            snippet = str(tag)
                            found_table = True
                            break

            if snippet:
                break
        except Exception:
            continue

    if snippet:
        raw_json = llm.extract_shareholders(snippet, stock_code)
        return _safe_parse_json(raw_json)
    
    return {"report_date": "", "shareholders": []}


def _fetch_shareholders_kabutan(stock_code: str) -> List[Dict[str, Any]]:
    """Directly scrape Kabutan's holder page for major shareholder data.

    Unlike _fetch_major_shareholders_web() which goes through SerpAPI + LLM,
    this parses the well-known Kabutan HTML structure directly.
    Returns: [{"name": str, "pct": float, "shares": str|None}, ...]
    """
    from bs4 import BeautifulSoup

    urls = [
        f"https://kabutan.jp/stock/holder/?code={stock_code}",
        f"https://kabutan.jp/stock/?code={stock_code}",
    ]

    _HOLDER_HEADER_KW = ["株主名", "株主", "大株主", "氏名", "名称"]
    _HOLDER_PCT_KW = ["持株比率", "比率", "割合", "%", "％"]

    for url in urls:
        try:
            raw_html = _fetch_url_text(url, max_chars=100000, strip=False)
            if not raw_html:
                continue

            soup = BeautifulSoup(raw_html, "html.parser")

            for table in soup.find_all("table"):
                header_text = " ".join(
                    cell.get_text(strip=True)
                    for cell in table.find_all(["th", "td"])
                )
                # Require at least one holder keyword in headers
                if not any(kw in header_text for kw in _HOLDER_HEADER_KW):
                    continue
                # Should have percentage-type data
                table_text = table.get_text()
                if not re.search(r"\d{1,2}\.\d{1,2}", table_text):
                    continue

                # Identify columns
                rows = table.find_all("tr")
                name_col: int | None = None
                pct_col: int | None = None
                shares_col: int | None = None

                for row in rows[:5]:  # Scan up to 5 header rows
                    cells = row.find_all(["th", "td"])
                    for ci, cell in enumerate(cells):
                        ct = cell.get_text(strip=True)
                        if any(k in ct for k in _HOLDER_HEADER_KW) and name_col is None:
                            name_col = ci
                        elif any(k in ct for k in _HOLDER_PCT_KW) and pct_col is None:
                            pct_col = ci
                        elif any(k in ct for k in ["株式数", "保有株数", "株数"]) and shares_col is None:
                            shares_col = ci
                    if name_col is not None and pct_col is not None:
                        break

                results: List[Dict[str, Any]] = []
                for row in rows:
                    cells = row.find_all(["th", "td"])
                    if len(cells) < 2:
                        continue

                    # Extract name
                    raw_name = ""
                    if name_col is not None and name_col < len(cells):
                        raw_name = cells[name_col].get_text(strip=True)
                    else:
                        raw_name = cells[0].get_text(strip=True)

                    if not raw_name or len(raw_name) < 2 or len(raw_name) > 80:
                        continue
                    if any(k in raw_name for k in ["合計", "株主名", "計"]):
                        continue

                    # Extract percentage
                    pct_val: float | None = None
                    if pct_col is not None and pct_col < len(cells):
                        m = re.search(r"(\d{1,3}(?:\.\d{1,2})?)", cells[pct_col].get_text(strip=True))
                        if m:
                            try:
                                v = float(m.group(1))
                                if 0 < v <= 100:
                                    pct_val = v
                            except (ValueError, TypeError):
                                pass

                    # Fallback: scan cells for decimal numbers (real percentages)
                    if pct_val is None:
                        # First pass: look for numbers with decimals (e.g., 5.16)
                        for cell in cells[1:]:  # skip name column
                            ct = cell.get_text(strip=True)
                            m = re.search(r"(\d{1,2}\.\d{1,2})", ct)
                            if m:
                                try:
                                    v = float(m.group(1))
                                    if 0.01 <= v <= 99:
                                        pct_val = v
                                        break
                                except (ValueError, TypeError):
                                    continue

                    if pct_val is None:
                        continue

                    # Extract shares
                    shares_str: str | None = None
                    if shares_col is not None and shares_col < len(cells):
                        shares_str = cells[shares_col].get_text(strip=True)

                    results.append({
                        "name": raw_name,
                        "pct": pct_val,
                        "shares": shares_str,
                    })

                if len(results) >= 3:
                    # Deduplicate, sort by pct descending
                    merged: Dict[str, Dict[str, Any]] = {}
                    for item in results:
                        if item["name"] not in merged or item["pct"] > merged[item["name"]]["pct"]:
                            merged[item["name"]] = item
                    ranked = sorted(merged.values(), key=lambda x: x["pct"], reverse=True)
                    return ranked[:15]
        except Exception:
            continue
    return []


def _fetch_shareholders_edinet(edinet_docs: list) -> List[Dict[str, Any]]:
    """Extract major shareholders from EDINET annual report filings.

    Tries the most recent annual reports first (doc_type_code 120 = 有価証券報告書).
    Falls back to other filing types that may contain shareholder data.
    """
    if not edinet_docs:
        return []

    edinet = EdinetClient()
    # Prefer annual reports (120), then quarterly (140), then amendments (130)
    _ANNUAL_TYPES = {"120"}
    _FALLBACK_TYPES = {"130", "140", "150", "160"}

    # Sort docs: annual first, then fallback types
    annual_docs = [d for d in edinet_docs if d.get("doc_type_code") in _ANNUAL_TYPES]
    fallback_docs = [d for d in edinet_docs if d.get("doc_type_code") in _FALLBACK_TYPES]
    ordered_docs = annual_docs + fallback_docs

    # Also try all docs in case doc_type_code is missing/different
    if not ordered_docs:
        ordered_docs = edinet_docs[:5]
    else:
        # Add remaining docs as last resort
        seen_ids = {d.get("doc_id") for d in ordered_docs}
        for d in edinet_docs[:5]:
            if d.get("doc_id") not in seen_ids:
                ordered_docs.append(d)

    for doc in ordered_docs[:6]:
        try:
            shareholders = edinet.extract_shareholders_table(doc.get("doc_id", ""))
            if shareholders and len(shareholders) >= 3:
                return shareholders
        except Exception:
            continue
    return []


def _get_edinet_large_holders(stock_code: str) -> List[Dict[str, Any]]:
    """
    Find 大量保有報告書 (5% rule filings) ABOUT a given company.

    EDINET API facts:
    - secCode = the FILER's code (null for most investors/funds)
    - issuerEdinetCode = the TARGET company's EDINET code (always set for 大量保有)
    - ordinanceCode "060" = all 大量保有 filings

    Strategy (single-pass concurrent scan):
    1. Discover the target company's EDINET code from any of its own filings
       (where secCode matches the stock code)
    2. Collect ALL 大量保有 filings (ordinanceCode "060") across all days
    3. After scan completes, filter by issuerEdinetCode == target EDINET code
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # ── 6-hour cache ──
    cache_key = f"large_holders_{stock_code}.json"
    cache_path = Path(settings.output_dir) / "cache" / cache_key
    cached = load_cache(cache_path, max_age_seconds=6 * 3600)
    if cached:
        return cached

    sec_code = f"{stock_code}0"
    today = dt.date.today()
    target_edinet_codes: set = set()
    all_060_filings: List[Dict[str, Any]] = []
    seen_ids: set = set()
    lock = threading.Lock()

    def _scan_day(delta: int):
        check_date = (today - dt.timedelta(days=delta)).strftime("%Y-%m-%d")
        try:
            url = f"{settings.edinet_base_url}/documents.json"
            params = {
                "date": check_date,
                "type": 2,
                "Subscription-Key": settings.edinet_subscription_key or settings.edinet_api_key
            }
            resp = httpx.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return set(), []
            data = resp.json()
            codes: set = set()
            hits: List[Dict[str, Any]] = []
            for doc in data.get("results", []):
                # Discover target company's EDINET code from its own filings
                if (doc.get("secCode") or "") == sec_code:
                    ec = doc.get("edinetCode")
                    if ec:
                        codes.add(ec)

                # Collect all 大量保有 filings (ordinanceCode "060")
                if (doc.get("ordinanceCode") or "") == "060":
                    hits.append({
                        "date": (doc.get("submitDateTime") or "")[:10],
                        "filer": doc.get("filerName"),
                        "type": doc.get("docDescription") or "",
                        "doc_id": doc.get("docID"),
                        "doc_type_code": str(doc.get("docTypeCode") or ""),
                        "_issuer_edinet": doc.get("issuerEdinetCode") or "",
                    })
            return codes, hits
        except Exception:
            return set(), []

    BATCH_SIZE = 30
    for batch_start in range(0, 730, BATCH_SIZE):
        # Early exit: if we already have the EDINET code and enough matches
        with lock:
            if target_edinet_codes:
                matched = sum(
                    1 for f in all_060_filings
                    if f.get("_issuer_edinet") in target_edinet_codes
                )
                if matched >= 10:
                    break
        batch_end = min(batch_start + BATCH_SIZE, 730)
        deltas = list(range(batch_start, batch_end))

        with ThreadPoolExecutor(max_workers=min(30, len(deltas))) as pool:
            futures = {pool.submit(_scan_day, d): d for d in deltas}
            for future in as_completed(futures):
                try:
                    codes, hits = future.result()
                except Exception:
                    continue
                with lock:
                    target_edinet_codes.update(codes)
                    for hit in hits:
                        doc_id = hit.get("doc_id")
                        if doc_id and doc_id not in seen_ids:
                            seen_ids.add(doc_id)
                            all_060_filings.append(hit)

    # Filter: keep only filings where issuerEdinetCode matches our target
    filings: List[Dict[str, Any]] = []
    for f in all_060_filings:
        issuer = f.pop("_issuer_edinet", "")
        if issuer in target_edinet_codes:
            filings.append(f)
    filings.sort(key=lambda x: x.get("date", ""), reverse=True)

    result = filings[:10]
    save_cache(cache_path, result)
    return result


def _is_activist_filer(filer_name: str | None, purpose: str | None) -> bool:
    """Check if a filer is a known activist or has activist-like purpose."""
    if not filer_name:
        return False
    import unicodedata
    name_lower = unicodedata.normalize("NFKC", filer_name).lower()
    if any(act in name_lower for act in _KNOWN_ACTIVISTS):
        return True
    if purpose and any(kw in purpose for kw in _ACTIVIST_PURPOSE_KEYWORDS):
        return True
    return False


def _check_poison_pill(edinet_narrative: str) -> bool:
    """Simple keyword search for poison pill / takeover defense in narrative text."""
    if not edinet_narrative:
        return False
    return any(kw in edinet_narrative for kw in _POISON_PILL_KEYWORDS)


def _translate_filer_name(name: str) -> str:
    """Best-effort English translation of Japanese institutional investor names."""
    if not name:
        return name
    import unicodedata
    # Normalize full-width ASCII → half-width (e.g. Ｏａｓｉｓ → Oasis)
    name = unicodedata.normalize("NFKC", name)
    # If the name is now pure ASCII (already English), return as-is
    if name.isascii():
        return name.strip()
    # Strip common suffixes
    for suffix in ["株式会社", "有限会社", "合同会社", "合資会社", "保険相互会社", "相互会社"]:
        name = name.replace(suffix, "").strip()
    # Common katakana word → English (applied after full-name match)
    _KATA_WORDS = {
        "ジャパン": "Japan", "リミテッド": "Ltd.", "カンパニー": "Co.",
        "マネジメント": "Mgmt", "マネージメント": "Mgmt",
        "フィナンシャル・グループ": "Financial Group",
        "フィナンシャル": "Financial", "グループ": "Group",
        "インベストメント": "Investment", "インベストメンツ": "Investments",
        "アセット": "Asset", "キャピタル": "Capital",
        "セキュリティーズ": "Securities", "パートナーズ": "Partners",
        "ホールディングス": "Holdings", "コーポレーション": "Corp.",
        "アドバイザーズ": "Advisors", "アドバイザリー": "Advisory",
        "インターナショナル": "Intl", "グローバル": "Global",
        "ファンド": "Fund", "トラスト": "Trust", "バンク": "Bank",
        "エルエルシー": "LLC", "エルエルピー": "LLP", "エルピー": "LP", "ピーエルシー": "PLC",
        "アンド": "&", "サービシーズ": "Services", "リサーチ": "Research",
    }
    # Known institutional investor katakana → English
    _KNOWN_MAP = {
        "ブラックロック": "BlackRock",
        "キャピタル・リサーチ・アンド・マネージメント・カンパニー": "Capital Research & Management",
        "キャピタル・リサーチ": "Capital Research",
        "バンガード": "Vanguard",
        "ゴールドマン・サックス": "Goldman Sachs",
        "モルガン・スタンレー": "Morgan Stanley",
        "ステート・ストリート": "State Street",
        "フィデリティ": "Fidelity",
        "オアシス・マネジメント": "Oasis Management",
        "オアシス": "Oasis",
        "エリオット": "Elliott",
        "バリューアクト": "ValueAct",
        "ストラテジック・キャピタル": "Strategic Capital",
        "ダルトン・インベストメンツ": "Dalton Investments",
        "ニューバーガー・バーマン": "Neuberger Berman",
        "マッコーリー": "Macquarie",
        "ＪＰモルガン": "JPMorgan",
        "シティグループ": "Citigroup",
        "ＵＢＳ": "UBS",
        "ＢＮＰパリバ": "BNP Paribas",
        "クレディ・スイス": "Credit Suisse",
        "ドイツ銀行": "Deutsche Bank",
        "ノムラ": "Nomura",
    }
    for jp, en in _KNOWN_MAP.items():
        if jp in name:
            rest = name.replace(jp, "").strip(" ・　")
            for kj, ke in _KATA_WORDS.items():
                rest = rest.replace(kj, ke)
            rest = rest.replace("・", " ").strip()
            return f"{en} {rest}".strip() if rest else en
    # Known JP banks / asset managers
    _JP_MAP = {
        "三井住友トラスト・アセットマネジメント": "Sumitomo Mitsui Trust AM",
        "三井住友信託銀行": "Sumitomo Mitsui Trust Bank",
        "三井住友": "Sumitomo Mitsui",
        "三菱ＵＦＪ": "Mitsubishi UFJ",
        "三菱UFJ": "Mitsubishi UFJ",
        "みずほ": "Mizuho",
        "野村アセットマネジメント": "Nomura Asset Management",
        "野村アセット": "Nomura Asset Mgmt",
        "野村證券": "Nomura Securities",
        "野村": "Nomura",
        "大和アセットマネジメント": "Daiwa Asset Management",
        "大和アセット": "Daiwa Asset Mgmt",
        "大和証券": "Daiwa Securities",
        "大和": "Daiwa",
        "日興アセットマネジメント": "Nikko Asset Management",
        "日興アセット": "Nikko Asset Mgmt",
        "シルチェスター・インターナショナル・インベスターズ": "Silchester International Investors",
        "シルチェスター": "Silchester",
        "アセットマネジメントＯｎｅ": "Asset Management One",
        "アセットマネジメントOne": "Asset Management One",
        "りそな": "Resona",
        "日本生命保険相互会社": "Nippon Life Insurance",
        "日本生命": "Nippon Life",
        "第一生命": "Dai-ichi Life",
        "東京海上": "Tokio Marine",
    }
    for jp, en in _JP_MAP.items():
        if jp in name:
            rest = name.replace(jp, "").strip(" ・　")
            # Apply katakana word replacements on the remaining text
            for kj, ke in _KATA_WORDS.items():
                rest = rest.replace(kj, ke)
            rest = rest.replace("・", " ").strip()
            return f"{en} {rest}".strip() if rest else en
    # Apply katakana word replacements as general fallback
    result = name
    for kj, ke in _KATA_WORDS.items():
        result = result.replace(kj, ke)
    result = result.replace("・", " ").strip()
    if result != name:
        return result
    # Last resort: use _translate_short_text (LLM) if it looks Japanese
    if _contains_japanese(name):
        return _translate_short_text(name) or name
    return name


_PURPOSE_EN_MAP = {
    "純投資": "Pure investment",
    "投資一任契約": "Discretionary investment mgmt",
    "投資信託": "Investment trust mgmt",
    "経営参画": "Management participation",
    "経営への関与": "Management involvement",
    "提案": "Shareholder proposal",
    "資本政策": "Capital policy engagement",
    "重要提案行為": "Material proposal activity",
}


def _translate_purpose(purpose: str | None) -> str | None:
    """Best-effort English translation of 保有目的 (holding purpose)."""
    if not purpose:
        return None
    # Check known phrases first
    for jp, en in _PURPOSE_EN_MAP.items():
        if jp in purpose:
            return en
    if _contains_japanese(purpose):
        return _translate_short_text(purpose) or purpose
    return purpose


def _fetch_activist_radar_data(stock_code: str, edinet_docs_raw: list) -> Dict[str, Any]:
    """Build activist radar data from EDINET 大量保有報告書 filings.

    Uses _get_edinet_large_holders() to scan EDINET for actual 5%‐rule filings
    about this company (by form code 030xxx), then downloads + parses the top
    filings for stake % and purpose.  Translates names/purposes to English.

    Post-processing:
    - Deduplicate by filer (keep most-recent filing per filer)
    - For disposal filings (current < 0.5%, previous ≥ 3%), show previous
      stake with "SOLD" flag — activist exits are critical intelligence

    Returns {"filings": [...], "has_poison_pill": False}
    """
    import unicodedata

    edinet = EdinetClient()

    # Get 大量保有 filings from EDINET scan
    large_holder_filings = _get_edinet_large_holders(stock_code)

    # 24-month cutoff, sort newest-first
    cutoff = (dt.date.today() - dt.timedelta(days=730)).isoformat()
    large_holder_filings = [
        d for d in large_holder_filings
        if (d.get("date") or "") >= cutoff
    ]
    large_holder_filings.sort(key=lambda d: d.get("date") or "", reverse=True)

    # Parse top 10 in parallel (extra headroom for dedup)
    top_docs = large_holder_filings[:10]
    if not top_docs:
        return {"filings": [], "has_poison_pill": False}

    def _parse_filing(doc):
        doc_id = doc.get("doc_id") or ""
        details = edinet.extract_large_holder_details(doc_id) if doc_id else {}
        filer_jp = unicodedata.normalize("NFKC", doc.get("filer") or "")
        purpose_jp = details.get("purpose")
        filer_en = _translate_filer_name(filer_jp)
        purpose_en = _translate_purpose(purpose_jp)

        stake = details.get("stake_pct")
        prev_stake = details.get("prev_stake_pct")
        sold = False

        # Disposal detection: current stake near zero but previous was large
        if stake is not None and stake < 0.5 and prev_stake and prev_stake >= 3.0:
            stake = prev_stake  # show what they HELD before exiting
            sold = True

        return {
            "filer": filer_en or filer_jp,
            "filer_jp": filer_jp,
            "stake_pct": stake,
            "date": doc.get("date") or "",
            "purpose": purpose_en or purpose_jp,
            "is_activist": _is_activist_filer(filer_jp, purpose_jp),
            "is_sold": sold,
            "doc_id": doc_id,
        }

    parsed = run_concurrent([lambda d=d: _parse_filing(d) for d in top_docs], max_workers=10)
    all_filings = [f for f in parsed if f is not None]

    # Deduplicate: keep only the most recent filing per filer (list is
    # already sorted newest-first, so first occurrence wins)
    seen_filers: set = set()
    unique_filings: list = []
    for f in all_filings:
        key = f["filer"].lower().strip()
        if key in seen_filers:
            continue
        seen_filers.add(key)
        unique_filings.append(f)

    filings = unique_filings

    return {"filings": filings[:8], "has_poison_pill": False}


def _fetch_segment_data_web(stock_code: str) -> List[Dict[str, Any]]:
    """Best-effort scrape of kabutan.jp for segment revenue data."""
    try:
        url = f"https://kabutan.jp/stock/finance/?code={stock_code}"
        raw_html = _fetch_url_text(url, max_chars=30000, strip=False)
        if not raw_html:
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_html, "html.parser")

        # Look for tables containing segment/business-type keywords
        segment_keywords = ["セグメント", "事業別", "セグメント別", "部門別"]
        for table in soup.find_all("table"):
            header_text = table.get_text(strip=True)
            if not any(kw in header_text for kw in segment_keywords):
                continue

            rows = table.find_all("tr")
            segments = []
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                name = cells[0].get_text(strip=True)
                # Skip header-like rows
                if any(kw in name for kw in ["セグメント", "合計", "計", "消去"]):
                    continue
                if not name or len(name) > 50:
                    continue
                # Try to extract a numeric value from the second cell
                val_text = cells[1].get_text(strip=True).replace(",", "").replace("百万円", "")
                try:
                    revenue = float(val_text)
                    segments.append({"name": name, "revenue": revenue})
                except (ValueError, TypeError):
                    continue

            if segments:
                total = sum(s["revenue"] for s in segments if s["revenue"] > 0)
                if total > 0:
                    return [
                        {
                            "segment": s["name"][:40],
                            "pct": round(s["revenue"] / total * 100, 1),
                            "revenue_mm": s["revenue"],
                        }
                        for s in segments
                        if s["revenue"] > 0
                    ]
        return []
    except Exception:
        return []


def _fetch_ownership_web(stock_code: str) -> Dict[str, float | None]:
    """Best-effort scrape of kabutan.jp for ownership mix data.

    Tries multiple pages: the holder page is most likely to have 所有者別
    data, with finance and main pages as fallbacks.
    """
    from bs4 import BeautifulSoup

    _OWNERSHIP_STRONG_KW = ["所有者別", "株主構成"]
    _OWNERSHIP_WEAK_KW = ["外国人", "金融機関", "個人その他", "外国法人等"]
    _CATEGORY_MAP = {
        "政府": "government",
        "地方公共団体": "government",
        "金融機関": "institutional",
        "金融商品取引業者": "securities_firms",
        "その他の法人": "corporate",
        "外国法人等": "foreign",
        "外国人": "foreign",
        "個人その他": "individual",
        "個人": "individual",
    }

    urls = [
        f"https://kabutan.jp/stock/holder/?code={stock_code}",
        f"https://kabutan.jp/stock/finance/?code={stock_code}",
        f"https://kabutan.jp/stock/?code={stock_code}",
    ]

    for url in urls:
        try:
            raw_html = _fetch_url_text(url, max_chars=80000, strip=False)
            if not raw_html:
                continue

            soup = BeautifulSoup(raw_html, "html.parser")

            for table in soup.find_all("table"):
                table_text = table.get_text()
                # Require a strong ownership keyword, or at least 2 weak keywords
                strong_match = any(kw in table_text for kw in _OWNERSHIP_STRONG_KW)
                weak_matches = sum(1 for kw in _OWNERSHIP_WEAK_KW if kw in table_text)
                if not strong_match and weak_matches < 2:
                    continue

                result: Dict[str, float | None] = {
                    "foreign": None, "institutional": None, "corporate": None,
                    "individual": None, "government": None, "securities_firms": None,
                }
                found = False
                for row in table.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    row_text = row.get_text()
                    matched_key = None
                    for jp_label, key in _CATEGORY_MAP.items():
                        if jp_label in row_text:
                            matched_key = key
                            break
                    if not matched_key:
                        continue
                    for cell in reversed(cells):
                        cell_text = cell.get_text().strip()
                        pct_match = re.search(r"(\d{1,3}\.\d{1,2})", cell_text)
                        if pct_match:
                            val = float(pct_match.group(1))
                            if 0 < val <= 100:
                                result[matched_key] = val
                                found = True
                                break

                if found and any(v is not None and v > 0 for v in result.values()):
                    return result
        except Exception:
            continue
    return {}


def _sanitize_text(value: Any, max_len: int = 220) -> Any:
    if not isinstance(value, str):
        return value
    cleaned = " ".join(value.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def _strip_japanese_from_text(text: str) -> str:
    """Remove Japanese characters (hiragana, katakana, CJK) from narrative text.

    Preserves the surrounding English text and punctuation.  Japanese product
    names like 'FXなび' become 'FX', which is better than leaking Japanese
    into an English-only report.
    """
    if not text or not isinstance(text, str):
        return text
    # Pattern: sequences of Japanese characters (hiragana, katakana, CJK ideographs,
    # and common full-width punctuation) — possibly preceded/followed by quotes
    cleaned = re.sub(
        r"['\u2018\u2019]?[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF]+['\u2018\u2019]?",
        "",
        text,
    )
    # Clean up artifacts: double spaces, orphaned commas/parentheses
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r",\s*,", ",", cleaned)
    cleaned = re.sub(r"\s+([,.])", r"\1", cleaned)
    return cleaned.strip()


def _sanitize_narrative(narrative: Dict[str, Any]) -> Dict[str, Any]:
    def sanitize_list(items: Any, max_len: int = 500) -> Any:
        if not isinstance(items, list):
            return items
        return [_sanitize_text(item, max_len) for item in items]

    if not isinstance(narrative, dict):
        return narrative
    cleaned = dict(narrative)

    # Strip any remaining Japanese characters from narrative text fields
    for key in ("summary_text", "outlook_summary"):
        val = cleaned.get(key)
        if isinstance(val, str) and _contains_japanese(val):
            cleaned[key] = _strip_japanese_from_text(val)
    for key in ("company_bullets", "bull_case", "bear_case"):
        val = cleaned.get(key)
        if isinstance(val, list):
            cleaned[key] = [
                _strip_japanese_from_text(item) if isinstance(item, str) and _contains_japanese(item) else item
                for item in val
            ]
    # Allow generous lengths for analytical text
    for key in ("summary_text", "outlook_summary"):
        cleaned[key] = _sanitize_text(cleaned.get(key), 2000)
    cleaned["company_bullets"] = sanitize_list(cleaned.get("company_bullets"), 500)
    cleaned["bull_case"] = sanitize_list(cleaned.get("bull_case"), 600)
    cleaned["bear_case"] = sanitize_list(cleaned.get("bear_case"), 600)
    corp = cleaned.get("corporate_info")
    if isinstance(corp, dict):
        corp_clean = {
            "president": _sanitize_text(corp.get("president"), 120),
            "employees": _sanitize_text(corp.get("employees"), 60),
            "head_office": _sanitize_text(corp.get("head_office"), 140),
        }
        cleaned["corporate_info"] = corp_clean
    disclosures = cleaned.get("disclosures")
    if isinstance(disclosures, list):
        cleaned["disclosures"] = [
            {
                "date": item.get("date"),
                "title": _sanitize_text(item.get("title"), 160),
                "detail": _sanitize_text(item.get("detail"), 200),
            }
            for item in disclosures
            if isinstance(item, dict)
        ]
    return cleaned


def _translate_short_text(text: str | None) -> str | None:
    if not text or not _contains_japanese(text):
        return text
    try:
        llm = LlmClient()
        translated_raw = llm.translate_json_to_english(_safe_json({"text": text}))
        translated = _safe_parse_json(translated_raw)
        return translated.get("text") or text
    except Exception:
        return text


def _merge_jquants_edinet(jquants: Dict, edinet: Dict) -> Dict:
    """Merge J-Quants and EDINET financial data.

    J-Quants has period types (CurPerType) needed for annualization, but often
    lacks balance-sheet and cash-flow fields.  EDINET XBRL has these (CFO, CFI,
    CFF, CashAndCashEquivalents, Borrowings, CapitalExpenditures, etc.).

    Strategy: use J-Quants statements as base, then for each period find the
    matching EDINET row and copy over any fields that are missing in J-Quants.
    """
    jq_data = jquants.get("statements") or jquants.get("financials") or jquants.get("data") or []
    ed_data = edinet.get("statements") or edinet.get("financials") or edinet.get("data") or []
    if isinstance(jq_data, dict):
        jq_data = [jq_data]
    if isinstance(ed_data, dict):
        ed_data = [ed_data]
    if not jq_data:
        return edinet
    if not ed_data:
        return jquants

    # Build EDINET lookup by period end date (normalised to YYYY-MM-DD)
    def _norm_date(s):
        if not s:
            return ""
        s = s.replace("/", "-").strip()
        # Handle compact YYYYMMDD format (e.g. "20240331")
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return s[:10]

    ed_by_period: Dict[str, Dict] = {}
    for row in ed_data:
        # EDINET uses PeriodEnd; prefer CurPerEn over CurFYEn for interim matching
        period = _norm_date(
            row.get("PeriodEnd") or row.get("PeriodEndDate") or row.get("CurPerEn") or row.get("CurFYEn") or ""
        )
        if period and period not in ed_by_period:
            ed_by_period[period] = row

    merged = []
    for jq_row in jq_data:
        # J-Quants uses CurPerEn (period end) — must come BEFORE CurFYEn
        # (fiscal year end) so interim reports match the correct EDINET period
        period = _norm_date(
            jq_row.get("PeriodEnd") or jq_row.get("PeriodEndDate") or jq_row.get("CurPerEn") or jq_row.get("CurFYEn") or ""
        )
        new_row = dict(jq_row)
        ed_row = ed_by_period.pop(period, None) if period else None
        if ed_row:
            # Copy EDINET fields into J-Quants row where J-Quants is missing.
            # Also fill in empty-string values from J-Quants with EDINET data.
            for key, value in ed_row.items():
                existing = new_row.get(key)
                if existing is None or existing == "":
                    new_row[key] = value
        merged.append(new_row)

    # Append any EDINET periods not present in J-Quants (older FY data)
    for period, ed_row in ed_by_period.items():
        merged.append(ed_row)

    result = dict(jquants)
    result["statements"] = merged
    return result


def _extract_financial_rows(financials: Dict) -> List[Dict[str, Any]]:
    data = financials.get("statements") or financials.get("financials") or financials.get("data") or []
    if isinstance(data, dict):
        data = [data]

    rows: List[Dict[str, Any]] = []
    for item in data:
        period = item.get("PeriodEnd") or item.get("PeriodEndDate") or item.get("Period") or item.get("CurPerEn") or item.get("CurFYEn")
        row = {
            "period": period,
            "period_type": item.get("CurPerType", ""),  # "FY", "3Q", "2Q", "1Q"
            "revenue": _pick_value(item, [
                "NetSales", "Revenue", "Sales", "OperatingRevenue",
                "Revn",  # J-Quants v2 abbreviated
            ]),
            "operating_profit": _pick_value(item, [
                "OperatingProfit", "OperatingIncome", "OP",
                "OperatingProfitLoss",  # EDINET variant
            ]),
            "ordinary_profit": _pick_value(item, [
                "OrdinaryProfit", "OrdinaryIncome", "OrdProfit", "OdP",
                "ProfitLossBeforeIncomeTaxes",  # some IFRS filers
                "OrdinaryProfitLoss",
            ]),
            "net_income": _pick_value(item, [
                "Profit", "NetIncome", "NetIncomeLoss", "NP",
                "ProfitLossAttributableToOwnersOfParent",
                "ProfitAttributableToOwnersOfParent",
            ]),
            "eps": _pick_value(item, [
                "EarningsPerShare", "EPS",
                "BasicEarningsPerShare",
            ]),
            "dps": _pick_value(item, [
                "DividendPerShare", "DPS", "AnnualDividendPerShare",
                "DividendPerShareAnnual", "DivAnn", "FDivAnn",
            ]),
            "total_assets": _pick_value(item, ["TotalAssets", "TA"]),
            "equity": _pick_value(item, [
                "Equity", "TotalEquity", "Eq", "NetAssets",
                "EquityAttributableToOwnersOfParent",
            ]),
            "cfo": _pick_value(item, [
                "CashFlowsFromOperatingActivities", "OperatingCashFlow", "CFO",
                "NetCashProvidedByUsedInOperatingActivities",
            ]),
            "cfi": _pick_value(item, [
                "CashFlowsFromInvestingActivities", "InvestingCashFlow", "CFI",
                "NetCashProvidedByUsedInInvestingActivities",
            ]),
            "cff": _pick_value(item, [
                "CashFlowsFromFinancingActivities", "FinancingCashFlow", "CFF",
                "NetCashProvidedByUsedInFinancingActivities",
            ]),
            "capex": _pick_value(item, [
                "CapitalExpenditures", "Capex",
                "PurchaseOfPropertyPlantAndEquipment",
                "PaymentsForPropertyPlantAndEquipment",
            ]),
            "borrowings": _pick_value(item, [
                "Borrowings", "InterestBearingDebt",
                "ShortTermBorrowings", "LongTermBorrowings",
            ]),
            "cash_equiv": _pick_value(item, [
                "CashAndCashEquivalents", "CashEquivalents",
                "CashAndCashEquivalentsEndOfPeriod",
                "CashEq",  # J-Quants v2 abbreviated
            ]),
            "equity_ratio_raw": _pick_value(item, ["EquityRatio", "EqAR"]),
            "bps_raw": _pick_value(item, ["BookValuePerShare", "BPS"]),
            "shares_out": _pick_value(item, ["SharesOutstandingFY", "ShOutFY", "IssuedShares"]),
            "treasury_shares": _pick_value(item, ["TreasurySharesFY", "TrShFY"]),
        }
        # ── Derivation fallbacks for missing balance-sheet fields ──
        # Many J-Quants entries have BPS, EqAR, ShOutFY, EPS but empty TA/Eq.
        # Derive shares_out from net_income / eps if missing (unit-consistent)
        if row.get("shares_out") is None and row.get("net_income") and row.get("eps") and row["eps"] != 0:
            row["shares_out"] = abs(row["net_income"] / row["eps"])
        # Derive equity from BPS * shares_out
        if row.get("equity") is None and row.get("bps_raw") is not None and row.get("shares_out"):
            row["equity"] = row["bps_raw"] * row["shares_out"]
        # Derive total_assets from equity / equity_ratio
        if row.get("total_assets") is None and row.get("equity") and row.get("equity_ratio_raw"):
            eqr = row["equity_ratio_raw"]
            # J-Quants EqAR can be percentage (45.0) or decimal (0.45)
            if eqr > 1:
                eqr = eqr / 100.0
            if 0 < eqr <= 1:
                row["total_assets"] = row["equity"] / eqr
        # Derive borrowings from total_assets - equity if both now exist
        if row.get("borrowings") is None and row.get("total_assets") is not None and row.get("equity") is not None:
            row["borrowings"] = max(0, row["total_assets"] - row["equity"])
        # Derive cash_equiv from CashEq or fallback: if we have CFO+CFI+CFF, skip (unreliable)
        # (cash_equiv stays None if J-Quants didn't provide it — no safe derivation)
        # Derive BPS from equity / shares if missing
        if row.get("bps_raw") is None and row.get("equity") and row.get("shares_out") and row["shares_out"] > 0:
            row["bps_raw"] = row["equity"] / row["shares_out"]

        # FCF
        if row.get("cfo") is not None and row.get("capex") is not None:
            row["fcf"] = row.get("cfo") - row.get("capex")
        elif row.get("cfo") is not None and row.get("cfi") is not None:
            row["fcf"] = row.get("cfo") + row.get("cfi")
        # Net debt
        if row.get("borrowings") is not None and row.get("cash_equiv") is not None:
            row["net_debt"] = row["borrowings"] - row["cash_equiv"]
        # D/E ratio
        if row.get("borrowings") is not None and row.get("equity") and row["equity"] != 0:
            row["de_ratio"] = row["borrowings"] / row["equity"]
        # Equity ratio (prefer raw API value, fallback to computed)
        if row.get("equity_ratio_raw") is not None:
            row["equity_ratio"] = row["equity_ratio_raw"]
        elif row.get("equity") and row.get("total_assets") and row["total_assets"] != 0:
            row["equity_ratio"] = row["equity"] / row["total_assets"]
        # FCF margin
        if row.get("fcf") is not None and row.get("revenue") and row["revenue"] != 0:
            row["fcf_margin"] = row["fcf"] / row["revenue"]
        # Cash conversion (CFO / NI)
        if row.get("cfo") is not None and row.get("net_income") and row["net_income"] != 0:
            row["cash_conversion"] = row["cfo"] / row["net_income"]
        # Payout ratio (annualise EPS for interim periods since DPS is annual)
        if row.get("dps") is not None and row.get("eps") and row["eps"] != 0:
            _pr_ptype = row.get("period_type", "")
            _pr_ann = {"1Q": 4, "2Q": 2, "3Q": 4 / 3}.get(_pr_ptype, 1)
            row["payout_ratio"] = row["dps"] / (row["eps"] * _pr_ann)
        rows.append(row)

    return rows


def _compute_financial_kpis(financials: Dict) -> Dict[str, Any]:
    rows = _extract_financial_rows(financials)
    rows_sorted = sorted(rows, key=lambda r: _parse_date(r.get("period")) or dt.date.min, reverse=True)

    for row in rows_sorted:
        row["op_margin"] = _safe_ratio(row.get("operating_profit"), row.get("revenue"))
        row["net_margin"] = _safe_ratio(row.get("net_income"), row.get("revenue"))
        raw_roe = _safe_ratio(row.get("net_income"), row.get("equity"))
        # Annualise interim ROE/ROA so LLM/display show comparable annual rates
        ptype = row.get("period_type", "")
        annualise = {"1Q": 4, "2Q": 2, "3Q": 4/3}.get(ptype, 1)
        if raw_roe is not None and annualise != 1:
            raw_roe = raw_roe * annualise
        row["roe"] = raw_roe
        raw_roa = _safe_ratio(row.get("net_income"), row.get("total_assets"))
        if raw_roa is not None and annualise != 1:
            raw_roa = raw_roa * annualise
        row["roa"] = raw_roa

    # --- Use only FY (full-year) rows for display table and growth rates ---
    # Mixing interim (1Q/2Q/3Q) with FY data creates misleading comparisons
    # (e.g., 9-month revenue vs 6-month revenue shows as "54% growth").
    fy_rows_raw = [r for r in rows_sorted if r.get("period_type") == "FY"]
    # Dedup FY rows: keep the first (newest disclosure) per period date
    seen_periods = set()
    fy_rows = []
    for r in fy_rows_raw:
        p = r.get("period")
        if p and p not in seen_periods:
            seen_periods.add(p)
            fy_rows.append(r)
    # If no FY rows found (period_type not available), include the latest
    # interim report separately but label it and still use FY for growth.
    latest_interim = None
    if not fy_rows:
        # No period_type tagging — fall back to all rows
        fy_rows = rows_sorted
    elif rows_sorted and rows_sorted[0].get("period_type") != "FY":
        # Latest data is interim — include it as first row but compute growth from FY
        latest_interim = rows_sorted[0]

    summary: Dict[str, Any] = {}
    if len(fy_rows) >= 2:
        latest_fy = fy_rows[0]
        prev_fy = fy_rows[1]
        summary = {
            "latest_period": latest_fy.get("period"),
            "revenue_growth": _safe_ratio(
                latest_fy.get("revenue") - prev_fy.get("revenue") if latest_fy.get("revenue") is not None and prev_fy.get("revenue") is not None else None,
                prev_fy.get("revenue"),
            ),
            "operating_profit_growth": _safe_ratio(
                latest_fy.get("operating_profit") - prev_fy.get("operating_profit") if latest_fy.get("operating_profit") is not None and prev_fy.get("operating_profit") is not None else None,
                prev_fy.get("operating_profit"),
            ),
            "net_income_growth": _safe_ratio(
                latest_fy.get("net_income") - prev_fy.get("net_income") if latest_fy.get("net_income") is not None and prev_fy.get("net_income") is not None else None,
                prev_fy.get("net_income"),
            ),
        }

    # Build display table: optionally prepend latest interim, then FY rows
    table_rows = []
    if latest_interim:
        table_rows.append(latest_interim)
    table_rows.extend(fy_rows)
    trimmed_rows = table_rows[:8]
    display_rows = []
    for row in trimmed_rows:
        display_rows.append({
            "period": row.get("period") or "-",
            "revenue": _format_number(row.get("revenue")),
            "operating_profit": _format_number(row.get("operating_profit")),
            "ordinary_profit": _format_number(row.get("ordinary_profit")),
            "net_income": _format_number(row.get("net_income")),
            "eps": _format_number(row.get("eps")),
            "dps": _format_number(row.get("dps")),
            "op_margin": _format_pct(row.get("op_margin")),
            "net_margin": _format_pct(row.get("net_margin")),
            "roe": _format_pct(row.get("roe")),
        })

    summary_display = {}
    if summary:
        summary_display = {
            "latest_period": summary.get("latest_period"),
            "revenue_growth": _format_pct(summary.get("revenue_growth")),
            "operating_profit_growth": _format_pct(summary.get("operating_profit_growth")),
            "net_income_growth": _format_pct(summary.get("net_income_growth")),
        }

    return {
        "rows": rows_sorted,
        "display_rows": display_rows,
        "summary": summary,
        "summary_display": summary_display,
    }


def _extract_price_rows(prices: Dict) -> List[Dict[str, Any]]:
    if not prices:
        return []
    # Support both J-Quants v1/v2 and Stooq CSV formats
    data = prices.get("daily_quotes") or prices.get("data") or []
    if isinstance(data, dict):
        data = [data]

    rows: List[Dict[str, Any]] = []
    for item in data:
        # Case-insensitive key lookup for common J-Quants fields
        def get_val(keys: List[str]):
            for k in keys:
                if k in item: return item[k]
                if k.lower() in item: return item[k.lower()]
                if k.upper() in item: return item[k.upper()]
            return None

        date = get_val(["Date", "QuoteDate", "DateOfQuote"])
        close = _to_float_safe(get_val(["AdjustmentClose", "AdjClose", "Close", "C"]))
        volume = _to_float_safe(get_val(["Volume", "TradeVolume", "V", "AdjustmentVolume", "AdjVo", "Vo"]))
        
        if date and close is not None:
            rows.append({"date": date, "close": close, "volume": volume})

    rows_sorted = sorted(rows, key=lambda r: _parse_date(r.get("date")) or dt.date.min)
    return rows_sorted


def _price_on_or_before(rows: List[Dict[str, Any]], target: dt.date) -> float | None:
    for row in reversed(rows):
        row_date = _parse_date(row.get("date"))
        if row_date and row_date <= target:
            return row.get("close")
    return None


def _compute_price_kpis(prices: Dict) -> Dict[str, Any]:
    rows = _extract_price_rows(prices)
    if not rows:
        return {}

    latest = rows[-1]
    latest_date = latest.get("date")
    latest_close = latest.get("close")

    returns = {}
    if latest_date and latest_close:
        dt_latest = _parse_date(latest_date)
        if dt_latest:
            horizons = {"1m": 30, "3m": 90, "6m": 180, "12m": 365}
            for label, days in horizons.items():
                target = dt_latest - dt.timedelta(days=days)
                past_close = _price_on_or_before(rows, target)
                returns[label] = _safe_ratio(latest_close - past_close, past_close) if past_close else None

    # Calculate 52-week High/Low and Avg Volume from the available history
    closes = [row.get("close") for row in rows if row.get("close") is not None]
    avg_volume = _avg_volume(rows)
    
    return {
        "latest_date": latest_date,
        "latest_close": latest_close,
        "returns": returns,
        "range_52w_high": max(closes) if closes else None,
        "range_52w_low": min(closes) if closes else None,
        "avg_volume": avg_volume,
        "row_count": len(rows),
    }


def _compute_capital_allocation(rows: List[Dict[str, Any]], periods: int = 3) -> List[Dict[str, Any]]:
    rows_sorted = sorted(rows, key=lambda r: _parse_date(r.get("period")) or dt.date.min)
    recent = rows_sorted[-periods:] if len(rows_sorted) >= periods else rows_sorted
    result: List[Dict[str, Any]] = []
    for row in recent:
        cfo = _to_float(row.get("cfo"))
        capex = _to_float(row.get("capex"))
        cff = _to_float(row.get("cff"))
        op = _to_float(row.get("operating_profit"))
        borrowings = _to_float(row.get("borrowings"))
        cash = _to_float(row.get("cash_equiv"))
        eps = _to_float(row.get("eps"))
        dps = _to_float(row.get("dps"))

        # FCF = cfo - abs(capex), or fallback to pre-computed fcf field
        fcf = _to_float(row.get("fcf"))
        if fcf is None and cfo is not None and capex is not None:
            fcf = cfo - abs(capex)

        # Capex (absolute value)
        capex_abs = abs(capex) if capex is not None else None

        # Shareholder Returns = abs(cff) if cff < 0
        shareholder_returns = abs(cff) if cff is not None and cff < 0 else None

        # Net Debt / EBITDA (OP as proxy, annualized for interim periods)
        net_debt_ebitda = None
        if borrowings is not None and cash is not None and op is not None and op != 0:
            net_debt = borrowings - cash
            ptype_ca = row.get("period_type", "")
            ann_f = {"1Q": 4, "2Q": 2, "3Q": 4 / 3}.get(ptype_ca, 1)
            net_debt_ebitda = net_debt / (op * ann_f)

        # Payout Ratio (annualise EPS for interim periods since DPS is annual)
        payout_ratio = None
        if dps is not None and eps is not None and eps != 0:
            ptype_pr = row.get("period_type", "")
            ann_f_pr = {"1Q": 4, "2Q": 2, "3Q": 4 / 3}.get(ptype_pr, 1)
            payout_ratio = dps / (eps * ann_f_pr) * 100

        result.append({
            "period_label": _format_period_label(row.get("period")),
            "fcf": fcf,
            "capex": capex_abs,
            "shareholder_returns": shareholder_returns,
            "net_debt_ebitda": net_debt_ebitda,
            "payout_ratio": payout_ratio,
        })
    return result


def _build_capital_structure_data(
    rows_sorted: List[Dict[str, Any]],
    kpi: Dict[str, Any],
    latest: Dict[str, Any],
) -> Dict[str, Any]:
    """Build comprehensive capital structure section for the report template."""

    # --- helpers ---
    def _fl(v):
        return _to_float(v) if v is not None else None

    total_assets = _fl(latest.get("total_assets"))
    cash_equiv = _fl(latest.get("cash_equiv"))
    equity = _fl(latest.get("equity"))
    borrowings = _fl(latest.get("borrowings"))
    cfo = _fl(latest.get("cfo"))
    cfi = _fl(latest.get("cfi"))
    cff = _fl(latest.get("cff"))
    fcf = _fl(latest.get("fcf"))
    # Interim reports often lack CF data — fall back to most recent FY row
    if cfo is None and rows_sorted:
        for _cf_row in reversed(rows_sorted):
            if _fl(_cf_row.get("cfo")) is not None:
                cfo = _fl(_cf_row.get("cfo"))
                cfi = _fl(_cf_row.get("cfi"))
                cff = _fl(_cf_row.get("cff"))
                fcf = _fl(_cf_row.get("fcf"))
                break
    net_income = _fl(latest.get("net_income"))
    revenue = _fl(latest.get("revenue"))
    op = _fl(latest.get("operating_profit"))
    eps = _fl(latest.get("eps"))
    dps = _fl(latest.get("dps"))
    # Interim reports often lack DPS — fall back to most recent FY row
    if dps is None and rows_sorted:
        for _dps_row in reversed(rows_sorted):
            if _fl(_dps_row.get("dps")) is not None:
                dps = _fl(_dps_row.get("dps"))
                break
    bps_raw = _fl(latest.get("bps_raw"))
    treasury_shares = _fl(latest.get("treasury_shares"))
    shares_out = _fl(latest.get("shares_out"))
    last_price = _fl(kpi.get("price"))
    market_cap_raw = _fl(kpi.get("market_cap_raw"))
    div_yield = _fl(kpi.get("div_yield"))
    bps_kpi = _fl(kpi.get("bps"))

    # Fallback: derive borrowings from total_assets - equity if missing
    if borrowings is None and total_assets is not None and equity is not None:
        borrowings = max(0, total_assets - equity)

    # Derived
    non_cash_assets = (total_assets - cash_equiv) if total_assets is not None and cash_equiv is not None else None
    net_debt = (borrowings - cash_equiv) if borrowings is not None and cash_equiv is not None else None
    de_ratio = (borrowings / equity) if borrowings is not None and equity and equity != 0 else None
    equity_ratio = None
    raw_eq_ratio = _fl(latest.get("equity_ratio"))
    if raw_eq_ratio is not None:
        equity_ratio = raw_eq_ratio
    elif equity and total_assets and total_assets != 0:
        equity_ratio = equity / total_assets
    equity_ratio_pct = (equity_ratio * 100) if equity_ratio is not None and equity_ratio <= 1 else equity_ratio

    net_debt_ebitda = None
    if net_debt is not None and op and op != 0:
        ptype_cs = latest.get("period_type", "")
        ann_f_cs = {"1Q": 4, "2Q": 2, "3Q": 4 / 3}.get(ptype_cs, 1)
        net_debt_ebitda = net_debt / (op * ann_f_cs)

    is_net_cash = net_debt is not None and net_debt < 0

    fcf_margin = (fcf / revenue) if fcf is not None and revenue and revenue != 0 else None
    fcf_margin_pct = (fcf_margin * 100) if fcf_margin is not None else None

    fcf_yield = None
    if fcf is not None and market_cap_raw and market_cap_raw != 0:
        _fy_ptype = latest.get("period_type", "")
        _fy_ann = {"1Q": 4, "2Q": 2, "3Q": 4 / 3}.get(_fy_ptype, 1)
        fcf_yield = (fcf * _fy_ann) / market_cap_raw
    fcf_yield_pct = (fcf_yield * 100) if fcf_yield is not None else None

    cash_conversion = (cfo / net_income) if cfo is not None and net_income and net_income != 0 else None

    # Annualise EPS for interim periods since DPS is annual
    _cs_ptype = latest.get("period_type", "")
    _cs_ann = {"1Q": 4, "2Q": 2, "3Q": 4 / 3}.get(_cs_ptype, 1)
    payout_ratio = (dps / (eps * _cs_ann)) if dps is not None and eps and eps != 0 else None
    payout_ratio_pct = (payout_ratio * 100) if payout_ratio is not None else None
    div_yield_pct = (div_yield * 100) if div_yield is not None else None

    bps_val = bps_kpi or bps_raw
    treasury_value = (treasury_shares * last_price) if treasury_shares and last_price else None

    # Equity vs Debt bar percentages
    eq_bar_pct = None
    debt_bar_pct = None
    if equity is not None and borrowings is not None:
        total_cap = abs(equity) + abs(borrowings)
        if total_cap > 0:
            eq_bar_pct = round(abs(equity) / total_cap * 100, 1)
            debt_bar_pct = round(abs(borrowings) / total_cap * 100, 1)

    # Cash flow waterfall bar heights (normalised to max)
    cf_values = {"cfo": cfo, "cfi": cfi, "cff": cff, "fcf": fcf}
    cf_abs_max = max((abs(v) for v in cf_values.values() if v is not None), default=1) or 1
    cf_bars = {}
    for k, v in cf_values.items():
        if v is not None:
            cf_bars[k] = {
                "value": v,
                "display": _format_compact(v),
                "height_pct": round(abs(v) / cf_abs_max * 100, 1),
                "positive": v >= 0,
            }

    # Trend: most recent 3 periods (deduped by period date, newest first)
    _seen_periods = set()
    fy_rows = []
    for r in reversed(rows_sorted):
        p = r.get("period")
        if p and p not in _seen_periods:
            _seen_periods.add(p)
            fy_rows.append(r)
    trend_rows = fy_rows[:3] if len(fy_rows) >= 2 else []
    trend = []
    for r in trend_rows:
        r_eq = _fl(r.get("equity"))
        r_ta = _fl(r.get("total_assets"))
        r_borr = _fl(r.get("borrowings"))
        r_cash = _fl(r.get("cash_equiv"))
        # Fallback: derive borrowings from total_assets - equity if missing
        if r_borr is None and r_ta is not None and r_eq is not None:
            r_borr = r_ta - r_eq
        # Fallback: if cash is missing but we have CFO+CFI+CFF, try end-of-period balance
        # (Not reliable enough — leave as None; EDINET mapping should provide it)
        r_eq_ratio = _fl(r.get("equity_ratio"))
        if r_eq_ratio is None and r_eq and r_ta and r_ta != 0:
            r_eq_ratio = r_eq / r_ta
        r_eq_ratio_pct = (r_eq_ratio * 100) if r_eq_ratio is not None and r_eq_ratio <= 1 else r_eq_ratio
        r_net_debt = (r_borr - r_cash) if r_borr is not None and r_cash is not None else None
        r_de = (r_borr / r_eq) if r_borr is not None and r_eq and r_eq != 0 else None
        trend.append({
            "period_label": _format_period_label(r.get("period")),
            "total_assets": r_ta,
            "equity": r_eq,
            "cash_equiv": r_cash,
            "borrowings": r_borr,
            "equity_ratio_pct": r_eq_ratio_pct,
            "net_debt": r_net_debt,
            "fcf": _fl(r.get("fcf")),
            "de_ratio": r_de,
            # Pre-formatted compact display strings
            "total_assets_d": _format_compact(r_ta),
            "equity_d": _format_compact(r_eq),
            "cash_equiv_d": _format_compact(r_cash),
            "borrowings_d": _format_compact(r_borr),
            "net_debt_d": _format_compact(r_net_debt),
            "fcf_d": _format_compact(_fl(r.get("fcf"))),
            "net_debt_positive": (r_net_debt is not None and r_net_debt > 0),
        })

    # Add directional arrows vs previous period
    def _dir(cur, prv):
        if cur is None or prv is None:
            return ""
        if cur > prv:
            return "up"
        if cur < prv:
            return "down"
        return "flat"

    for i, t in enumerate(trend):
        if i == 0:
            t["ta_dir"] = ""
            t["eq_dir"] = ""
            t["cash_dir"] = ""
            t["nd_dir"] = ""
        else:
            prev = trend[i - 1]
            t["ta_dir"] = _dir(t["total_assets"], prev["total_assets"])
            t["eq_dir"] = _dir(t["equity"], prev["equity"])
            t["cash_dir"] = _dir(t["cash_equiv"], prev["cash_equiv"])
            t["nd_dir"] = _dir(t["net_debt"], prev["net_debt"])

    return {
        "asset_composition": {
            "total_assets": total_assets,
            "total_assets_d": _format_compact(total_assets),
            "cash_equiv": cash_equiv,
            "cash_equiv_d": _format_compact(cash_equiv),
            "non_cash_assets": non_cash_assets,
            "non_cash_assets_d": _format_compact(non_cash_assets),
            "equity": equity,
            "equity_d": _format_compact(equity),
            "equity_ratio_pct": equity_ratio_pct,
            "treasury_shares": treasury_shares,
            "treasury_value": treasury_value,
            "treasury_value_d": _format_compact(treasury_value),
        },
        "capital_structure": {
            "equity": equity,
            "equity_d": _format_compact(equity),
            "borrowings": borrowings,
            "borrowings_d": _format_compact(borrowings),
            "net_debt": net_debt,
            "net_debt_d": _format_compact(net_debt),
            "net_debt_abs_d": _format_compact(abs(net_debt)) if net_debt is not None else "—",
            "de_ratio": de_ratio,
            "equity_ratio_pct": equity_ratio_pct,
            "net_debt_ebitda": net_debt_ebitda,
            "is_net_cash": is_net_cash,
            "eq_bar_pct": eq_bar_pct,
            "debt_bar_pct": debt_bar_pct,
        },
        "cash_flow_quality": {
            "cfo": cfo,
            "cfo_d": _format_compact(cfo),
            "cfi": cfi,
            "cfi_d": _format_compact(cfi),
            "cff": cff,
            "cff_d": _format_compact(cff),
            "fcf": fcf,
            "fcf_d": _format_compact(fcf),
            "fcf_margin_pct": fcf_margin_pct,
            "fcf_yield_pct": fcf_yield_pct,
            "cash_conversion": cash_conversion,
            "cf_bars": cf_bars,
        },
        "per_share": {
            "bps": bps_val,
            "eps": eps,
            "dps": dps,
            "payout_ratio_pct": payout_ratio_pct,
            "div_yield_pct": div_yield_pct,
        },
        "trend": trend,
    }


def _compute_risk_metrics(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows_sorted = sorted(rows, key=lambda r: _parse_date(r.get("period")) or dt.date.min)
    if not rows_sorted:
        return []
    # Pick most recent row with actual data (skip forecast periods)
    _RISK_DATA_KEYS = ("equity", "total_assets", "revenue", "net_income", "operating_profit")
    latest = rows_sorted[-1]
    for r in reversed(rows_sorted):
        if any(r.get(k) is not None for k in _RISK_DATA_KEYS):
            latest = r
            break

    # Use FY-only rows for YoY comparison to avoid mixing cumulative periods
    fy_rows = sorted(
        [r for r in rows if r.get("period_type") == "FY"],
        key=lambda r: _parse_date(r.get("period")) or dt.date.min,
    )
    prev_fy = fy_rows[-2] if len(fy_rows) >= 2 else {}

    # Annualize flow metrics for the latest period if interim
    ptype = latest.get("period_type", "")
    ann_factor = {"1Q": 4, "2Q": 2, "3Q": 4 / 3}.get(ptype, 1)

    borrowings = _to_float(latest.get("borrowings"))
    equity = _to_float(latest.get("equity"))
    total_assets = _to_float(latest.get("total_assets"))
    op = _to_float(latest.get("operating_profit"))
    if op is not None:
        op = op * ann_factor
    cfo = _to_float(latest.get("cfo"))
    if cfo is not None:
        cfo = cfo * ann_factor
    net_income = _to_float(latest.get("net_income"))
    if net_income is not None:
        net_income = net_income * ann_factor
    # Revenue YoY uses FY rows to avoid sequential-period comparison
    latest_fy = fy_rows[-1] if fy_rows else {}
    revenue = _to_float(latest_fy.get("revenue"))
    prev_revenue = _to_float(prev_fy.get("revenue"))

    risks: List[Dict[str, Any]] = []

    # 1. D/E Ratio
    if borrowings is not None and equity is not None and equity != 0:
        de = borrowings / equity
        if de < 0.5:
            assessment = "low"
        elif de < 1.5:
            assessment = "moderate"
        else:
            assessment = "elevated"
        risks.append({
            "metric": "D/E Ratio",
            "value": f"{de:.2f}x",
            "assessment": assessment,
            "detail": f"Debt ¥{_format_compact(borrowings)} vs Equity ¥{_format_compact(equity)}",
        })

    # 2. Interest Coverage (estimated)
    if op is not None and borrowings is not None and borrowings > 0:
        est_interest = borrowings * 0.02
        coverage = op / est_interest if est_interest != 0 else None
        if coverage is not None:
            if coverage > 5:
                assessment = "low"
            elif coverage > 2:
                assessment = "moderate"
            else:
                assessment = "elevated"
            risks.append({
                "metric": "Interest Coverage (est.)",
                "value": f"{coverage:.1f}x",
                "assessment": assessment,
                "detail": f"OP ¥{_format_compact(op)} / est. interest ¥{_format_compact(est_interest)}",
            })

    # 3. CFO / Net Income (earnings quality)
    if cfo is not None and net_income is not None and net_income != 0:
        ratio = cfo / net_income
        if ratio > 0.8:
            assessment = "low"
        elif ratio > 0.4:
            assessment = "moderate"
        else:
            assessment = "elevated"
        risks.append({
            "metric": "CFO / Net Income",
            "value": f"{ratio:.2f}x",
            "assessment": assessment,
            "detail": f"Earnings quality — CFO ¥{_format_compact(cfo)} vs NI ¥{_format_compact(net_income)}",
        })

    # 4. Equity Ratio
    if equity is not None and total_assets is not None and total_assets != 0:
        eq_ratio = equity / total_assets
        if eq_ratio > 0.5:
            assessment = "low"
        elif eq_ratio > 0.3:
            assessment = "moderate"
        else:
            assessment = "elevated"
        risks.append({
            "metric": "Equity Ratio",
            "value": f"{eq_ratio * 100:.1f}%",
            "assessment": assessment,
            "detail": f"Equity ¥{_format_compact(equity)} / Assets ¥{_format_compact(total_assets)}",
        })

    # 5. Revenue YoY
    if revenue is not None and prev_revenue is not None and prev_revenue != 0:
        yoy = (revenue - prev_revenue) / prev_revenue
        if yoy > 0.05:
            assessment = "low"
        elif yoy > -0.05:
            assessment = "moderate"
        else:
            assessment = "elevated"
        risks.append({
            "metric": "Revenue YoY",
            "value": f"{yoy * 100:+.1f}%",
            "assessment": assessment,
            "detail": f"¥{_format_compact(revenue)} vs prior ¥{_format_compact(prev_revenue)}",
        })

    return risks


def _render_financial_table(financial_kpis: Dict[str, Any]) -> str:
    rows = financial_kpis.get("rows", [])
    if not rows:
        return ""

    lines = [
        "### Key Financials (JPY)",
        "| Period | Revenue | Operating Profit | Net Income | Op Margin | Net Margin | ROE |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for row in rows[:8]:
        lines.append(
            "| {period} | {rev} | {op} | {net} | {opm} | {netm} | {roe} |".format(
                period=row.get("period") or "-",
                rev=_format_number(row.get("revenue")),
                op=_format_number(row.get("operating_profit")),
                net=_format_number(row.get("net_income")),
                opm=_format_pct(row.get("op_margin")),
                netm=_format_pct(row.get("net_margin")),
                roe=_format_pct(row.get("roe")),
            )
        )

    return "\n".join(lines)


def _render_cashflow_table(financial_kpis: Dict[str, Any]) -> str:
    rows = financial_kpis.get("rows", [])
    if not rows:
        return ""
    has_cashflow = any(row.get("cfo") is not None or row.get("cfi") is not None or row.get("cff") is not None for row in rows)
    if not has_cashflow:
        return ""

    lines = [
        "### Cash Flow Snapshot (JPY)",
        "| Period | CFO | CFI | CFF | FCF (CFO+CFI) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows[:6]:
        lines.append(
            "| {period} | {cfo} | {cfi} | {cff} | {fcf} |".format(
                period=row.get("period") or "-",
                cfo=_format_number(row.get("cfo")),
                cfi=_format_number(row.get("cfi")),
                cff=_format_number(row.get("cff")),
                fcf=_format_number(row.get("fcf")),
            )
        )
    return "\n".join(lines)


def _render_price_table(price_kpis: Dict[str, Any]) -> str:
    if not price_kpis:
        return ""

    returns = price_kpis.get("returns", {})
    lines = [
        "### Market Performance",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Latest Close ({price_kpis.get('latest_date', '-')}) | {_format_number(price_kpis.get('latest_close'))} |",
        f"| 1M Return | {_format_pct(returns.get('1m'))} |",
        f"| 3M Return | {_format_pct(returns.get('3m'))} |",
        f"| 6M Return | {_format_pct(returns.get('6m'))} |",
        f"| 12M Return | {_format_pct(returns.get('12m'))} |",
        f"| 52W High | {_format_number(price_kpis.get('range_52w_high'))} |",
        f"| 52W Low | {_format_number(price_kpis.get('range_52w_low'))} |",
    ]
    return "\n".join(lines)


def _render_appendix_tables(financial_kpis: Dict[str, Any], price_kpis: Dict[str, Any]) -> str:
    tables = []
    financial_table = _render_financial_table(financial_kpis)
    price_table = _render_price_table(price_kpis)
    cashflow_table = _render_cashflow_table(financial_kpis)
    if financial_table:
        tables.append(financial_table)
    if cashflow_table:
        tables.append(cashflow_table)
    if price_table:
        tables.append(price_table)

    if not tables:
        return ""

    return "\n\n".join(["## Appendix", *tables])


def _build_v6_data_block(financial_kpis: Dict[str, Any]) -> str:
    rows = financial_kpis.get("rows", [])
    if not rows:
        return "No EDINET financial rows extracted."

    display_rows = financial_kpis.get("display_rows", [])
    latest = display_rows[0] if display_rows else {}
    latest_raw = rows[0] if rows else {}
    summary = financial_kpis.get("summary_display", {})

    lines = [
        "V6 DATA BLOCK (use these numbers; do not recompute):",
        f"Latest period: {latest.get('period')}",
        f"Revenue: {latest.get('revenue')}",
        f"Operating profit: {latest.get('operating_profit')}",
        f"Net income: {latest.get('net_income')}",
        f"Operating margin: {latest.get('op_margin')}",
        f"Net margin: {latest.get('net_margin')}",
        f"ROE: {latest.get('roe')}",
        f"Total assets: {_format_number(latest_raw.get('total_assets'))}",
        f"Equity: {_format_number(latest_raw.get('equity'))}",
    ]

    if latest_raw.get("cfo") is not None or latest_raw.get("cfi") is not None or latest_raw.get("cff") is not None:
        lines.extend([
            f"CFO: {_format_number(latest_raw.get('cfo'))}",
            f"CFI: {_format_number(latest_raw.get('cfi'))}",
            f"CFF: {_format_number(latest_raw.get('cff'))}",
            f"FCF (CFO+CFI): {_format_number(latest_raw.get('fcf'))}",
            f"Capex: {_format_number(latest_raw.get('capex'))}",
        ])

    if summary.get("latest_period"):
        lines.extend([
            f"YoY revenue growth: {summary.get('revenue_growth')}",
            f"YoY operating profit growth: {summary.get('operating_profit_growth')}",
            f"YoY net income growth: {summary.get('net_income_growth')}",
        ])

    lines.append("")
    lines.append("Net sales and operating margin trend (FY2019–FY2023 if available):")
    lines.append("| Fiscal year | Net sales | Operating margin |")
    lines.append("| --- | ---: | ---: |")
    for row in display_rows:
        lines.append(f"| {row.get('period')} | {row.get('revenue')} | {row.get('op_margin')} |")

    return "\n".join(lines)


def _build_valuation_block(valuation: Dict[str, Any]) -> str:
    if not valuation:
        return "Valuation model: not available."

    lines = [
        "VALUATION MODEL OUTPUT (use in Valuation Context section):",
        f"Last price: {valuation.get('last_price'):.0f}" if valuation.get("last_price") is not None else "Last price: N/A",
        f"Target (blend): {valuation.get('target_price'):.0f}" if valuation.get("target_price") is not None else "Target (blend): N/A",
        f"Target range: {valuation.get('target_low'):.0f}–{valuation.get('target_high'):.0f}" if valuation.get("target_low") is not None and valuation.get("target_high") is not None else "Target range: N/A",
        f"Upside vs price: {valuation.get('upside_pct'):.1f}%" if valuation.get("upside_pct") is not None else "Upside vs price: N/A",
        f"Quality score: {valuation.get('quality_score'):.0f}/100" if valuation.get("quality_score") is not None else "Quality score: N/A",
        f"Methods used: {valuation.get('method_count') or 'N/A'}",
        f"Model type: {valuation.get('model_type') or 'N/A'}",
        f"Samples: {valuation.get('samples') or 'N/A'}",
        f"R2: {valuation.get('r2'):.2f}" if valuation.get("r2") is not None else "R2: N/A",
        f"Predicted multiple: {valuation.get('predicted_multiple'):.2f}x" if valuation.get("predicted_multiple") is not None else "Predicted multiple: N/A",
        f"Actual multiple: {valuation.get('actual_multiple'):.2f}x" if valuation.get("actual_multiple") is not None else "Actual multiple: N/A",
        f"Implied price: {valuation.get('implied_price'):.0f}" if valuation.get("implied_price") is not None else "Implied price: N/A",
        f"Implied range: {valuation.get('range_low'):.0f}–{valuation.get('range_high'):.0f}" if valuation.get("range_low") is not None and valuation.get("range_high") is not None else "Implied range: N/A",
        f"Score (z): {valuation.get('score_z'):.2f}" if valuation.get("score_z") is not None else "Score (z): N/A",
        f"Peer median multiple: {valuation.get('peer_multiple'):.2f}x" if valuation.get("peer_multiple") is not None else "Peer median multiple: N/A",
        f"Peer implied price: {valuation.get('peer_price'):.0f}" if valuation.get("peer_price") is not None else "Peer implied price: N/A",
        f"Peer range: {valuation.get('peer_range_low'):.0f}–{valuation.get('peer_range_high'):.0f}" if valuation.get("peer_range_low") is not None and valuation.get("peer_range_high") is not None else "Peer range: N/A",
        f"DCF price: {valuation.get('dcf_price'):.0f}" if valuation.get("dcf_price") is not None else "DCF price: N/A",
        f"DCF range: {valuation.get('dcf_range_low'):.0f}–{valuation.get('dcf_range_high'):.0f}" if valuation.get("dcf_range_low") is not None and valuation.get("dcf_range_high") is not None else "DCF range: N/A",
        f"SOTP price: {valuation.get('sotp_price'):.0f}" if valuation.get("sotp_price") is not None else "SOTP price: N/A",
        f"SOTP range: {valuation.get('sotp_range_low'):.0f}–{valuation.get('sotp_range_high'):.0f}" if valuation.get("sotp_range_low") is not None and valuation.get("sotp_range_high") is not None else "SOTP range: N/A",
    ]

    # Per-method breakdown for richer LLM context
    method_results = valuation.get("method_results") or []
    if method_results:
        lines.append("")
        lines.append("PER-METHOD DETAIL:")
        for mr in method_results:
            if mr.get("price") is not None:
                detail_parts = [f"  {mr['name']} (weight {mr.get('weight', 0):.0%}): ¥{mr['price']:,.0f}"]
                if mr.get("range_low") is not None and mr.get("range_high") is not None:
                    detail_parts.append(f"range ¥{mr['range_low']:,.0f}–¥{mr['range_high']:,.0f}")
                if mr.get("reasoning"):
                    detail_parts.append(mr["reasoning"])
                # Key details from the method
                details = mr.get("details") or {}
                key_details = []
                for k in ("wacc", "fcf_margin", "peer_pe", "peer_pb", "peer_ev_ebitda",
                           "multiplier", "roe", "dps", "payout_ratio", "normalised_earnings"):
                    if k in details and details[k] is not None:
                        key_details.append(f"{k}={details[k]:.3f}" if isinstance(details[k], float) else f"{k}={details[k]}")
                if key_details:
                    detail_parts.append(f"[{', '.join(key_details)}]")
                lines.append(" | ".join(detail_parts))

    # Advisor reasoning
    advisor = valuation.get("advisor") or {}
    if advisor.get("reasoning"):
        lines.append("")
        lines.append(f"ADVISOR REASONING: {advisor['reasoning']}")
    if advisor.get("sector_classification"):
        lines.append(f"SECTOR CLASSIFICATION: {advisor['sector_classification']}")

    return "\n".join(lines)


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", text)
    text = re.sub(r"(?is)<head.*?>.*?</head>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_segment_revenue(text: str, max_segments: int = 8) -> List[Dict[str, Any]]:
    """Extract segment revenue data from text using multiple regex strategies.

    Handles both English and Japanese patterns found in EDINET filings,
    research reports, and web-scraped content.
    """
    if not text:
        return []
    candidates: List[Dict[str, Any]] = []

    # ── Unit normaliser (converts to millions of yen) ──
    def normalize(value: str, unit: str | None) -> float | None:
        try:
            num = float(value.replace(",", "").replace("，", "").replace("、", ""))
        except Exception:
            return None
        if num == 0:
            return None
        if not unit:
            return num
        unit_l = unit.lower().strip()
        if unit_l in ("billion", "bn", "b"):
            return num * 1_000
        if unit_l in ("million", "m", "mn"):
            return num
        if unit_l in ("trillion", "tn", "t"):
            return num * 1_000_000
        if unit_l == "兆円":
            return num * 1_000_000
        if unit_l == "億円":
            return num * 100  # 1億 = 100百万
        if unit_l == "百万円":
            return num
        if unit_l == "千円":
            return num / 1_000
        return num

    # ── Skip-list: names that are headers, totals, or noise ──
    _SKIP_NAMES = {
        "合計", "計", "消去", "調整", "全社", "小計", "総計",
        "total", "subtotal", "elimination", "adjustments", "corporate",
        "セグメント間", "配賦不能", "調整額", "連結", "のれん",
    }

    def _is_noise(name: str) -> bool:
        n = name.strip().lower()
        if len(n) < 2 or len(n) > 50:
            return True
        for skip in _SKIP_NAMES:
            if skip in n:
                return True
        if re.fullmatch(r"[\d,.\s%¥]+", n):
            return True
        return False

    # ── English patterns ──
    eng_patterns = [
        # "Segment Name Revenue: 1,234 million"
        r"([A-Za-z][A-Za-z &/\\-]{2,40})\s+(?:Revenue|Sales|Net Sales)\s*[:：]?\s*[¥￥]?([0-9,.]+)\s*(billion|bn|million|mn|m|b|trillion|tn|t)?",
        # "Segment Name: ¥1,234M"
        r"([A-Za-z][A-Za-z &/\\-]{2,40})\s*[:：]\s*[¥￥]([0-9,.]+)\s*(B|M|T|bn|mn)?",
        # "Segment Name (XX.X%)" — percentage only
        r"([A-Za-z][A-Za-z &/\\-]{2,40})\s*\(\s*([0-9.]+)\s*%\s*\)",
    ]

    # ── Japanese patterns (comprehensive) ──
    jp_patterns = [
        # Standard: "事業名 売上高 1,234百万円"
        r"([^\n,。]{2,30}?)\s*(?:の)?売上高\s*[:：]?\s*([0-9,]+)\s*(兆円|億円|百万円|千円)?",
        # IFRS-style: "事業名 売上収益 1,234百万円"
        r"([^\n,。]{2,30}?)\s*(?:の)?売上収益\s*[:：]?\s*([0-9,]+)\s*(兆円|億円|百万円|千円)?",
        # "事業名 営業収益 1,234百万円"
        r"([^\n,。]{2,30}?)\s*(?:の)?営業収益\s*[:：]?\s*([0-9,]+)\s*(兆円|億円|百万円|千円)?",
        # "事業名 外部顧客への売上高 1,234百万円"
        r"([^\n,。]{2,30}?)\s*外部顧客への売上[高収益]*\s*[:：]?\s*([0-9,]+)\s*(兆円|億円|百万円|千円)?",
        # Reversed: "売上高 1,234百万円 事業名事業"
        r"(?:売上[高収益]*|営業収益)\s*[:：]?\s*([0-9,]+)\s*(兆円|億円|百万円|千円)?\s*(?:の)?\s*([^\n,。]{2,30}?)(?:事業|セグメント)",
        # Segment-labelled: "XXX事業 1,234" or "XXXセグメント 1,234"
        r"([^\n,。]{2,20}?(?:事業|セグメント|部門))\s+([0-9,]+)\s*(兆円|億円|百万円|千円)?",
        # Pct format: "事業名 XX.X%" (segment with percentage)
        r"([^\n,。]{2,30}?(?:事業|セグメント|部門))\s*[:：]?\s*([0-9.]+)\s*[%％]",
    ]

    # ── Extract from English patterns ──
    for pat in eng_patterns[:2]:
        for match in re.finditer(pat, text, flags=re.IGNORECASE):
            name = match.group(1).strip()
            if _is_noise(name):
                continue
            value = match.group(2)
            unit = match.group(3) if match.lastindex and match.lastindex >= 3 else None
            rev = normalize(value, unit)
            if rev is not None:
                candidates.append({"name": name, "revenue": rev})

    # ── English pct-only ──
    for match in re.finditer(eng_patterns[2], text, flags=re.IGNORECASE):
        name = match.group(1).strip()
        if _is_noise(name):
            continue
        try:
            pct = float(match.group(2))
            if 0 < pct <= 100:
                candidates.append({"name": name, "revenue": 0, "pct": pct})
        except ValueError:
            pass

    # ── Extract from Japanese patterns ──
    for pi, pat in enumerate(jp_patterns):
        for match in re.finditer(pat, text):
            if pi == 4:
                # Reversed pattern: groups are (value, unit, name)
                name = match.group(3).strip()
                value = match.group(1)
                unit = match.group(2)
            elif pi == 6:
                # Pct pattern
                name = match.group(1).strip()
                if _is_noise(name):
                    continue
                try:
                    pct = float(match.group(2))
                    if 0 < pct <= 100:
                        candidates.append({"name": name, "revenue": 0, "pct": pct})
                except ValueError:
                    pass
                continue
            else:
                name = match.group(1).strip()
                value = match.group(2)
                unit = match.group(3) if match.lastindex and match.lastindex >= 3 else None
            if _is_noise(name):
                continue
            rev = normalize(value, unit)
            if rev is not None:
                candidates.append({"name": name, "revenue": rev})

    # ── Deduplicate by normalised name, keep largest revenue ──
    merged: Dict[str, Dict[str, Any]] = {}
    for item in candidates:
        key = re.sub(r"\s+", " ", item["name"]).strip().lower()
        existing = merged.get(key)
        if not existing or (item.get("revenue", 0) or 0) > (existing.get("revenue", 0) or 0):
            merged[key] = item

    segments = sorted(merged.values(), key=lambda x: x.get("revenue", 0) or 0, reverse=True)
    return segments[:max_segments]


def _fetch_url_text(url: str, max_chars: int = 12000, strip: bool = True) -> str:
    try:
        resp = httpx.get(
            url,
            timeout=20,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            },
        )
        if resp.status_code >= 400:
            return ""
        ctype = resp.headers.get("content-type", "")
        if "text" not in ctype and "html" not in ctype:
            return ""
        
        text = resp.text
        if strip:
            text = _strip_html(text)
        
        return text[:max_chars]
    except Exception:
        return ""


def _score_research_url(url: str) -> int:
    score = 0
    low = url.lower()
    for term in ("ir", "investor", "profile", "company", "about", "corporate", "overview"):
        if term in low:
            score += 2
    if any(domain in low for domain in ("hitachi.com", "co.jp", "ir.")):
        score += 3
    if low.endswith(".pdf"):
        score -= 1
    return score


def _collect_research_pages(serp_results: List, limit: int = 4) -> List[Dict[str, str]]:
    seen = set()
    candidates = []
    for item in serp_results:
        if not item.url or item.url in seen:
            continue
        seen.add(item.url)
        candidates.append(( _score_research_url(item.url), item ))
    candidates.sort(key=lambda x: x[0], reverse=True)

    top_candidates = candidates[:limit]
    if not top_candidates:
        return []

    # Fetch all URLs concurrently
    fetch_tasks = [lambda item=item: _fetch_url_text(item.url) for _, item in top_candidates]
    fetched_texts = run_concurrent(fetch_tasks, max_workers=min(10, len(fetch_tasks)))

    pages: List[Dict[str, str]] = []
    for (_, item), text in zip(top_candidates, fetched_texts):
        if not text:
            continue
        pages.append({
            "url": item.url,
            "title": item.title or item.url,
            "text": text,
        })
    return pages


def _extract_company_profile(pages: List[Dict[str, str]]) -> tuple[Dict[str, str], Dict[str, str]]:
    patterns = {
        "company_name": [
            r"Company Name[:：]\s*([^\.;]+)",
            r"Corporate Name[:：]\s*([^\.;]+)",
            r"商号[:：]\s*([^\n]+)",
            r"会社名[:：]\s*([^\n]+)",
            r"提出会社名[:：]\s*([^\n]+)",
        ],
        "representative": [
            r"Representative[:：]\s*([^\.;]+)",
            r"CEO[:：]\s*([^\.;]+)",
            r"President[:：]\s*([^\.;]+)",
            r"代表取締役[^:：]*[:：]\s*([^\n]+)",
            r"代表執行役社長[^:：]*[:：]\s*([^\n]+)",
            r"社長兼CEO[:：]\s*([^\n]+)",
        ],
        "founded": [
            r"Founded[:：]\s*([^\.;]+)",
            r"Established[:：]\s*([^\.;]+)",
            r"Founded in\s*([0-9]{4})",
            r"Established in\s*([0-9]{4})",
            r"設立[:：]\s*([^\n]+)",
            r"創業[:：]\s*([^\n]+)",
        ],
        "head_office": [
            r"Head Office[:：]\s*([^\.;]+)",
            r"Headquarters[:：]\s*([^\.;]+)",
            r"Head office\s*(?:is|:)\s*([^\.;]+)",
            r"Headquarters\s*(?:is|:)\s*([^\.;]+)",
            r"本社所在地[:：]\s*([^\n]+)",
            r"本店所在地[:：]\s*([^\n]+)",
        ],
        "employees": [
            r"Employees[:：]\s*([^\.;]+)",
            r"Number of employees[:：]\s*([^\.;]+)",
            r"従業員数[:：]\s*([^\n]+)",
            r"従業員[:：]\s*([^\n]+)",
        ],
        "listed_markets": [
            r"Listed (Market|Exchange)[:：]\s*([^\.;]+)",
            r"Listed on the\s*([^\.;]+)",
            r"Listed on\s*([^\.;]+)",
            r"上場市場[:：]\s*([^\n]+)",
            r"証券取引所[:：]\s*([^\n]+)",
        ],
        "core_businesses": [
            r"Business (Description|Activities)[:：]\s*([^\.;]+)",
            r"Core Businesses[:：]\s*([^\.;]+)",
            r"事業内容[:：]\s*([^\n]+)",
            r"主な事業[:：]\s*([^\n]+)",
            r"主要事業[:：]\s*([^\n]+)",
        ],
    }

    profile: Dict[str, str] = {}
    profile_sources: Dict[str, str] = {}

    for page in pages:
        text = page["text"]
        for field, regs in patterns.items():
            if field in profile:
                continue
            for reg in regs:
                match = re.search(reg, text, flags=re.IGNORECASE)
                if match:
                    idx = match.lastindex or 1
                    value = match.group(idx).strip()
                    profile[field] = value
                    profile_sources[field] = page["url"]
                    break
    return profile, profile_sources


def _extract_profile_from_edinet(text: str) -> Dict[str, str]:
    if not text:
        return {}
    patterns = {
        "company_name": [r"(?:商号|会社名|提出会社名)[:：]\s*([^\n]+)"],
        "representative": [r"(?:代表者|代表取締役社長|代表取締役)[:：]\s*([^\n]+)"],
        "founded": [r"(?:設立|創業)[:：]\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日?)"],
        "head_office": [r"(?:本店所在地|本社所在地|所在地)[:：]\s*([^\n]+)"],
        "employees": [r"(?:従業員数|従業員)[:：]\s*([^\n]+)"],
        "listed_markets": [r"(?:上場証券取引所|上場取引所)[:：]\s*([^\n]+)"],
        "core_businesses": [r"(?:事業内容|主要事業)[:：]\s*([^\n]+)"],
    }
    profile: Dict[str, str] = {}
    for field, regs in patterns.items():
        for reg in regs:
            match = re.search(reg, text, flags=re.IGNORECASE)
            if match:
                profile[field] = match.group(1).strip()
                break
    return profile


def _fetch_corporate_info_kabutan(stock_code: str) -> Dict[str, str]:
    """Scrape kabutan.jp company profile page for president, employees, head office.

    Kabutan has a consistent profile table on every stock page with fields like:
    代表者 (representative), 従業員数 (employees), 本社所在地 (head office),
    設立 (founded), 事業内容 (business description).
    This is the most reliable public source for Japanese company metadata.
    """
    from bs4 import BeautifulSoup

    code_clean = str(stock_code).replace(".T", "").strip()
    url = f"https://kabutan.jp/stock/?code={code_clean}"
    result: Dict[str, str] = {}

    try:
        raw_html = _fetch_url_text(url, max_chars=100000, strip=False)
        if not raw_html:
            return result

        soup = BeautifulSoup(raw_html, "html.parser")

        # Kabutan uses <table class="kobetsu_data_table"> or similar for company info
        # Look for rows with th/td pairs containing known labels
        field_map = {
            "代表者": "president",
            "代表取締役": "president",
            "社長": "president",
            "従業員数": "employees",
            "従業員": "employees",
            "本社所在地": "head_office",
            "本社住所": "head_office",
            "住所": "head_office",
            "所在地": "head_office",
            "設立": "founded",
            "設立年月日": "founded",
        }

        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"])
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(strip=True)
                value = cells[1].get_text(strip=True)
                if not label or not value:
                    continue
                for jp_key, en_key in field_map.items():
                    if jp_key in label and en_key not in result:
                        # Clean up the value
                        cleaned = re.sub(r'\s+', ' ', value).strip()
                        if cleaned and cleaned != "—" and len(cleaned) < 200:
                            result[en_key] = cleaned
                            break

        # Also try the company info div/section that kabutan uses
        # Look for specific text patterns in the full page text
        page_text = soup.get_text()
        if "president" not in result:
            m = re.search(r'代表者[名\s]*[:：]?\s*([^\n,、]{2,30})', page_text)
            if m:
                result["president"] = m.group(1).strip()
        if "employees" not in result:
            m = re.search(r'従業員[数\s]*[:：]?\s*([0-9,，]+(?:\s*人)?)', page_text)
            if m:
                result["employees"] = m.group(1).strip()
        if "head_office" not in result:
            m = re.search(r'(?:本社所在地|本社住所|所在地)[:\s：]*([^\n]{3,50})', page_text)
            if m:
                result["head_office"] = m.group(1).strip()

    except Exception as exc:
        print(f"[CORPORATE INFO] Kabutan scrape failed for {stock_code}: {exc}")

    return result


def _fetch_corporate_info_yahoo_jp(stock_code: str) -> Dict[str, str]:
    """Scrape Yahoo Finance Japan profile page for corporate info.

    Yahoo Finance Japan's profile page (finance.yahoo.co.jp/quote/XXXX.T/profile)
    reliably has: 代表者名, 本社所在地, 従業員数, 設立年月日, 業種分類, etc.
    This is the most consistent publicly-available source for Japanese company metadata.
    """
    code_clean = str(stock_code).replace(".T", "").strip()
    url = f"https://finance.yahoo.co.jp/quote/{code_clean}.T/profile"
    result: Dict[str, str] = {}

    try:
        from bs4 import BeautifulSoup
        # Yahoo requires follow_redirects (returns 500 without it)
        resp = httpx.get(
            url, timeout=20, follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            },
        )
        if resp.status_code >= 400:
            return result

        soup = BeautifulSoup(resp.text, "html.parser")

        field_map = {
            "代表者名": "president",
            "代表者": "president",
            "代表取締役": "president",
            "本社所在地": "head_office",
            "住所": "head_office",
            "従業員数": "employees",
            "設立年月日": "founded",
            "設立": "founded",
        }

        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"])
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(strip=True)
                value = cells[1].get_text(strip=True)
                if not label or not value:
                    continue
                # Skip placeholder values
                if value in ("—", "---", "−", "ー"):
                    continue
                for jp_key, en_key in field_map.items():
                    if jp_key in label and en_key not in result:
                        cleaned = re.sub(r'\s+', ' ', value).strip()
                        # Remove Yahoo-specific noise from head_office
                        cleaned = re.sub(r'Yahoo!路線情報で確認$', '', cleaned).strip()
                        if cleaned and len(cleaned) < 200:
                            result[en_key] = cleaned
                            break

        # Employee data — try page text fallback if table had only "---"
        page_text = soup.get_text()
        if "employees" not in result:
            for pat in [
                r'従業員数（連結）\s*([0-9,，]+)\s*人',
                r'従業員数（単独）\s*([0-9,，]+)\s*人',
                r'従業員数[^\d]*?([0-9,，]+)\s*人',
            ]:
                m = re.search(pat, page_text)
                if m:
                    result["employees"] = m.group(1).replace("，", ",") + "人"
                    break

    except Exception as exc:
        print(f"[CORPORATE INFO] Yahoo JP scrape failed for {stock_code}: {exc}")

    return result


def _scrape_sector_from_web(stock_code: str) -> List[str]:
    """Scrape Yahoo Finance Japan and Kabutan for sector/industry classification.

    Returns a list of Japanese sector name strings (e.g. ['電気機器', '機械'])
    that can be tried against PeerDatabase's alias system.
    """
    from bs4 import BeautifulSoup

    code_clean = str(stock_code).replace(".T", "").strip()
    sectors: List[str] = []
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }

    # ── Yahoo Finance Japan ──
    try:
        url = f"https://finance.yahoo.co.jp/quote/{code_clean}.T/profile"
        resp = httpx.get(url, timeout=20, follow_redirects=True, headers=_HEADERS)
        if resp.status_code < 400:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Method 1: table rows (th/td)
            for table in soup.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all(["th", "td"])
                    if len(cells) < 2:
                        continue
                    label = cells[0].get_text(strip=True)
                    if "業種" in label:
                        value = cells[1].get_text(strip=True)
                        if value and value not in ("—", "---", "−", "ー"):
                            sectors.append(value)
            # Method 2: definition lists (dl/dt/dd)
            if not sectors:
                for dt_tag in soup.find_all("dt"):
                    if "業種" in dt_tag.get_text(strip=True):
                        dd = dt_tag.find_next_sibling("dd")
                        if dd:
                            value = dd.get_text(strip=True)
                            if value and value not in ("—", "---"):
                                sectors.append(value)
            # Method 3: regex fallback on page text
            if not sectors:
                page_text = soup.get_text()
                m = re.search(r'業種[分類]*[:\s：]*([^\n\s,、]{2,20})', page_text)
                if m:
                    sectors.append(m.group(1).strip())
    except Exception as exc:
        print(f"[SECTOR SCRAPE] Yahoo JP failed for {stock_code}: {exc}")

    # ── Kabutan ──
    try:
        url = f"https://kabutan.jp/stock/?code={code_clean}"
        raw_html = _fetch_url_text(url, max_chars=100000, strip=False)
        if raw_html:
            soup = BeautifulSoup(raw_html, "html.parser")
            for table in soup.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all(["th", "td"])
                    if len(cells) < 2:
                        continue
                    label = cells[0].get_text(strip=True)
                    if "業種" in label:
                        value = cells[1].get_text(strip=True)
                        if value and value not in ("—", "---") and value not in sectors:
                            sectors.append(value)
            # Kabutan often shows sector in a span/div near the header
            if not sectors:
                for tag in soup.find_all(["span", "a", "div"]):
                    text = tag.get_text(strip=True)
                    if "業種" in text and len(text) < 40:
                        m = re.search(r'業種[:\s：]*(.+)', text)
                        if m:
                            value = m.group(1).strip().rstrip("）)】」")
                            if value and value not in sectors:
                                sectors.append(value)
                                break
    except Exception as exc:
        print(f"[SECTOR SCRAPE] Kabutan failed for {stock_code}: {exc}")

    # Deduplicate
    seen: set = set()
    unique: List[str] = []
    for s in sectors:
        if s and s not in seen:
            seen.add(s)
            unique.append(s)
    print(f"[SECTOR SCRAPE] {stock_code} → {unique}")
    return unique


def _find_peers_via_llm(company_name: str, stock_code: str, sector_hint: str | None) -> List[Dict[str, str]]:
    """Use the LLM to suggest peer companies listed on the TSE.

    This is the ultimate fallback when sector-based and web-scraped peer
    discovery both fail.  The LLM has broad knowledge of Japanese company
    relationships and can suggest appropriate comparables.

    Returns [{"code": "1234", "name": "Company Name"}, ...] or [].
    """
    try:
        llm = LlmClient()

        sector_ctx = f" in the {sector_hint} sector" if sector_hint else ""

        system_prompt = (
            "You are a Japanese equity analyst. Given a company, "
            "suggest 8-12 publicly listed peer companies on the Tokyo Stock Exchange "
            "suitable for comparable-company valuation analysis. "
            "Focus on companies in the same industry with similar business models. "
            "Return ONLY a JSON array of objects with 'code' (4-digit TSE stock code) "
            "and 'name' (company name). Do NOT include the target company. "
            "Example: [{\"code\": \"6501\", \"name\": \"Hitachi\"}]"
        )
        user_prompt = (
            f"Company: {company_name} (TSE: {stock_code}){sector_ctx}\n"
            f"List 8-12 TSE-listed peer companies for comparable valuation."
        )

        raw = llm._create_completion(system_prompt, user_prompt)
        if not raw:
            return []

        parsed = _safe_parse_json_array(raw)
        if not parsed:
            as_dict = _safe_parse_json(raw)
            if isinstance(as_dict, dict):
                for key in ("peers", "companies", "results", "data"):
                    if isinstance(as_dict.get(key), list):
                        parsed = as_dict[key]
                        break

        target_clean = str(stock_code).replace(".T", "").strip()
        results: List[Dict[str, str]] = []
        for item in (parsed or []):
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).strip().replace(".T", "")
            name = str(item.get("name", "")).strip()
            if re.match(r'^\d{4}$', code) and code != target_clean and name:
                results.append({"code": code, "name": name})

        print(f"[PEER LLM] {stock_code} → {len(results)} peers suggested")
        return results
    except Exception as exc:
        print(f"[PEER LLM] Failed for {stock_code}: {exc}")
        return []


def _build_profile_block(profile: Dict[str, str], profile_sources: Dict[str, str], source_id_map: Dict[str, int], fallback_source_id: int | None = None) -> str:
    labels = [
        ("company_name", "Company name"),
        ("representative", "Representative"),
        ("founded", "Founded"),
        ("head_office", "Head Office"),
        ("employees", "Employees"),
        ("listed_markets", "Listed markets"),
        ("core_businesses", "Core businesses"),
    ]
    lines = ["Company Snapshot Evidence (use when available):"]
    for key, label in labels:
        value = profile.get(key)
        src_url = profile_sources.get(key)
        src_id = source_id_map.get(src_url) if src_url else None
        if value and src_id:
            lines.append(f"- {label}: {value} [{src_id}]")
        elif value and fallback_source_id:
            lines.append(f"- {label}: {value} [{fallback_source_id}]")
        elif value:
            lines.append(f"- {label}: {value}")
        else:
            lines.append(f"- {label}: N/A")
    return "\n".join(lines)


def _fetch_peer_benchmarking(
    stock_code: str,
    sector_hint: str | None,
    target_financials: Dict | None = None,
    web_sectors: List[str] | None = None,
    company_name: str | None = None,
) -> Dict[str, Any]:
    """Fetch real peer benchmarking data using PeerDatabase + J-Quants.

    Uses a multi-source approach for sector resolution:
    1. Provided sector_hint (from company_info)
    2. peer_universe.json code→sector lookup
    3. J-Quants API
    4. Web-scraped sectors from Yahoo Finance / Kabutan (pre-fetched or live)
    5. LLM-based peer suggestion (ultimate fallback)

    Returns:
        {
            "peers": [{"ticker": str, "name": str, "mkt_cap_t": float|None,
                        "ebit_pct": float|None, "roe_pct": float|None,
                        "pb": float|None, "pe": float|None, "de": float|None,
                        "ocf_pct": float|None, "inv_days": float|None,
                        "tsr_5y_pct": float|None}, ...],
            "medians": {...},
            "is_real": True,
        }
    """
    from app.services.peer_db import PeerDatabase

    peer_db = PeerDatabase()
    jquants = JQuantsClient()

    # ── Phase 1: Build sector candidates from multiple sources ──
    sector_candidates = []
    company_name_for_llm = company_name or ""
    if sector_hint:
        sector_candidates.append(sector_hint)
    # Try peer_db's own code→sector lookup
    code_sector = peer_db.get_sector_for_code(stock_code)
    if code_sector and code_sector not in sector_candidates:
        sector_candidates.append(code_sector)
    # J-Quants API sector (always try — also gives us the company name for LLM)
    try:
        jq_info = jquants.get_company_info(stock_code)
        if jq_info:
            if jq_info.sector and jq_info.sector not in sector_candidates:
                sector_candidates.append(jq_info.sector)
            if not company_name_for_llm and jq_info.name:
                company_name_for_llm = jq_info.name
    except Exception:
        pass
    # Web-scraped sector (Yahoo Finance Japan + Kabutan) — use pre-fetched or scrape live
    try:
        scraped = web_sectors if web_sectors is not None else _scrape_sector_from_web(stock_code)
        for ws in (scraped if isinstance(scraped, list) else []):
            if ws not in sector_candidates:
                sector_candidates.append(ws)
    except Exception:
        pass

    print(f"[PEER DEBUG] sector_candidates for {stock_code}: {sector_candidates}")

    # ── Phase 2: Try each sector candidate in peer_universe.json ──
    raw_peers = []
    for sc in sector_candidates:
        raw_peers = peer_db.find_peers(stock_code, sc, n=12, prefer_prime=True)
        if raw_peers:
            print(f"[PEER DEBUG] Found {len(raw_peers)} peers using sector={sc!r}")
            break
        print(f"[PEER DEBUG] No peers for sector={sc!r}, trying next...")

    # ── Phase 3: LLM-based peer discovery (ultimate fallback) ──
    if not raw_peers:
        print(f"[PEER DEBUG] All sector candidates exhausted: {sector_candidates}")
        print(f"[PEER DEBUG] Trying LLM-based peer discovery...")
        llm_name = company_name_for_llm or stock_code
        llm_peers = _find_peers_via_llm(llm_name, stock_code, sector_hint)
        if llm_peers:
            raw_peers = llm_peers
            print(f"[PEER DEBUG] LLM suggested {len(raw_peers)} peers")
        else:
            print(f"[PEER DEBUG] LLM peer discovery also returned nothing")
            return {"peers": [], "medians": {}, "is_real": False}

    # Fetch peer metrics — J-Quants _get now handles 429 retry internally
    import time as _time

    def _get_peer_metrics(peer_info: Dict) -> Dict[str, Any]:
        code = str(peer_info.get("code", ""))
        name = peer_info.get("name", "")
        result = {
            "ticker": code, "name": name,
            "mkt_cap_t": None, "ebit_pct": None, "roe_pct": None,
            "pb": None, "pe": None, "de": None,
            "ocf_pct": None, "inv_days": None, "tsr_5y_pct": None,
        }
        try:
            fin_data = jquants.get_financials(code)
            statements = fin_data.get("statements") or fin_data.get("financials") or fin_data.get("data") or []
            equity = None
            if isinstance(statements, list) and statements:
                # Use the most recent statement
                latest = statements[-1] if isinstance(statements, list) else statements
                if isinstance(latest, dict):
                    revenue = _pick_value(latest, ["NetSales", "Revenue", "Sales", "OperatingRevenue", "Revn"])
                    op_profit = _pick_value(latest, ["OperatingProfit", "OperatingIncome", "OP"])
                    net_income = _pick_value(latest, ["Profit", "NetIncome", "ProfitLoss", "NP"])
                    equity = _pick_value(latest, ["Equity", "NetAssets", "TotalEquity", "Eq"])
                    total_assets = _pick_value(latest, ["TotalAssets", "TA"])
                    total_debt = _pick_value(latest, ["TotalLiabilities", "InterestBearingDebt"])
                    ocf = _pick_value(latest, ["OperatingCashFlow", "CashFlowsFromOperatingActivities", "CFO"])
                    inventory = _pick_value(latest, ["Inventories", "Inventory"])

                    # EBIT margin
                    if op_profit is not None and revenue and revenue > 0:
                        result["ebit_pct"] = round(op_profit / revenue * 100, 1)
                    # ROE
                    if net_income is not None and equity and equity > 0:
                        result["roe_pct"] = round(net_income / equity * 100, 1)
                    # D/E
                    if total_debt is not None and equity and equity > 0:
                        result["de"] = round(total_debt / equity, 2)
                    elif total_assets is not None and equity and equity > 0:
                        result["de"] = round((total_assets - equity) / equity, 2)
                    # OCF%
                    if ocf is not None and revenue and revenue > 0:
                        result["ocf_pct"] = round(ocf / revenue * 100, 1)
                    # Inventory days
                    if inventory is not None and revenue and revenue > 0:
                        result["inv_days"] = round(inventory / revenue * 365, 0)

            # Get market data for P/B, P/E, market cap
            try:
                _time.sleep(1.0)  # pause between financials and prices to avoid 429
                prices_data = jquants.get_prices(code)
                quotes = prices_data.get("daily_quotes") or prices_data.get("data") or []
                if quotes:
                    last_quote = quotes[-1] if isinstance(quotes, list) else quotes
                    close_price = _to_float(
                        last_quote.get("AdjustmentClose") or last_quote.get("AdjClose")
                        or last_quote.get("Close") or last_quote.get("AdjC") or last_quote.get("C")
                    )
                    if close_price:
                        # Get shares from financials first (more reliable), listed_info as fallback
                        shares_out = _to_float(latest.get("ShOutFY") or latest.get("AvgSh")) if isinstance(statements, list) and statements else None
                        if not shares_out:
                            shares_info = jquants.get_listed_info(code)
                            if shares_info:
                                shares_out = _to_float(
                                    shares_info.get("IssuedShares") or shares_info.get("NumberOfIssuedShares")
                                    or shares_info.get("ShOutFY")
                                )
                        # Market cap
                        if shares_out and close_price:
                            mkt_cap = close_price * shares_out
                            result["mkt_cap_t"] = round(mkt_cap / 1_000_000_000_000, 2)
                        # P/E
                        if isinstance(statements, list) and statements:
                            eps_val = _pick_value(statements[-1], ["EarningsPerShare", "BasicEarningsPerShare", "EPS", "DEPS"])
                            if eps_val and eps_val > 0:
                                result["pe"] = round(close_price / eps_val, 1)
                        # P/B
                        if isinstance(statements, list) and statements:
                            bps_val = _pick_value(statements[-1], ["BookValuePerShare", "BPS"])
                            # Compute BPS from equity/shares if not directly available
                            if not bps_val and equity and shares_out and shares_out > 0:
                                bps_val = equity / shares_out
                            if bps_val and bps_val > 0:
                                result["pb"] = round(close_price / bps_val, 2)
                    # 5Y TSR approximation from available price history
                    if isinstance(quotes, list) and len(quotes) >= 2:
                        first_close = _to_float(
                            quotes[0].get("AdjustmentClose") or quotes[0].get("AdjClose")
                            or quotes[0].get("Close") or quotes[0].get("AdjC") or quotes[0].get("C")
                        )
                        last_close = _to_float(
                            quotes[-1].get("AdjustmentClose") or quotes[-1].get("AdjClose")
                            or quotes[-1].get("Close") or quotes[-1].get("AdjC") or quotes[-1].get("C")
                        )
                        if first_close and last_close and first_close > 0:
                            # Annualise if data spans >60 days
                            days_span = len(quotes)
                            raw_return = (last_close - first_close) / first_close * 100
                            if days_span >= 200:
                                result["tsr_5y_pct"] = round(raw_return, 0)
            except Exception as price_exc:
                print(f"[PEER DEBUG] Price fetch failed for {code}: {price_exc}")
        except Exception as fin_exc:
            print(f"[PEER DEBUG] Financial fetch failed for {code}: {fin_exc}")
        return result

    # Fetch peer metrics sequentially with delay between peers.
    # J-Quants enforces rate limits (429) after heavy pipeline usage.
    # Use longer delays (2.5s) to stay well under rate limits after
    # the main pipeline already consumed significant API budget.
    peer_results = []
    for i, peer in enumerate(raw_peers[:6]):
        if i > 0:
            _time.sleep(3.0)  # stagger requests to stay under rate limit
        try:
            peer_results.append(_get_peer_metrics(peer))
        except Exception as exc:
            print(f"[PEER DEBUG] Peer {peer.get('code')} completely failed: {exc}")

    print(f"[PEER DEBUG] peer_results={len(peer_results)}, raw_peers={len(raw_peers[:6])}")
    for pr in peer_results:
        print(f"[PEER DEBUG]   {pr['ticker']} {pr['name'][:20]}: ebit={pr.get('ebit_pct')}, roe={pr.get('roe_pct')}, pb={pr.get('pb')}, pe={pr.get('pe')}")
    valid_peers = [p for p in peer_results if p.get("ebit_pct") is not None or p.get("roe_pct") is not None]

    # If too few valid peers, include all that have any metric
    if len(valid_peers) < 3:
        valid_peers = [p for p in peer_results if any(
            p.get(k) is not None for k in ("ebit_pct", "roe_pct", "pb", "pe")
        )]

    # Compute medians
    import numpy as np
    metrics_keys = ["ebit_pct", "roe_pct", "pb", "pe", "de", "ocf_pct", "inv_days", "tsr_5y_pct"]
    medians = {}
    for key in metrics_keys:
        vals = [p.get(key) for p in valid_peers if p.get(key) is not None]
        if vals:
            medians[key] = round(float(np.median(vals)), 1)

    return {
        "peers": valid_peers[:8],
        "medians": medians,
        "is_real": len(valid_peers) >= 1,
    }


_WEB_CACHE_TTL = 24 * 3600  # 24 hours


def _cached_web_fetch(label: str, stock_code: str, fn):
    """Wrap a web scraper with 24h file-based caching."""
    cache_path = Path(settings.output_dir) / "cache" / f"{label}_{stock_code}.json"
    cached = load_cache(cache_path, _WEB_CACHE_TTL)
    if cached is not None:
        return cached
    try:
        result = fn(stock_code)
    except Exception:
        return None
    if result is not None:
        try:
            save_cache(cache_path, result)
        except Exception:
            pass
    return result


def build_report_payload(
    stock_code: str,
    company_name: str | None = None,
    mode: str = "full",
    on_progress=None,
    on_event=None,
) -> Dict:
    """Build the full report data payload using dependency-driven parallelism.

    Instead of sequential phases (A→B→C→D→E), tasks are submitted to a
    thread-pool as soon as their specific dependencies resolve.  Two LLM
    calls (EDINET extraction + profile enrichment) now run **in parallel**
    instead of back-to-back, and all web scrapers fire at t=0 with 24h
    file-based caching.
    """
    from concurrent.futures import ThreadPoolExecutor
    import threading as _threading

    last_pct = 0
    _progress_lock = _threading.Lock()

    def progress(pct: int, step: str, message: str) -> None:
        nonlocal last_pct
        with _progress_lock:
            pct = max(pct, last_pct)
            last_pct = pct
        if on_progress:
            on_progress(pct, step, message)

    def event(event_type: str, message: str, meta: dict | None = None) -> None:
        if on_event:
            on_event(event_type, message, meta)

    stock_code = _normalize_stock_code(stock_code)
    input_company_name = None
    if company_name is not None:
        input_company_name = company_name.strip() or None
    company_name = input_company_name

    progress(5, "Starting", "Normalizing input")
    serp = SerpClient()
    edinet = EdinetClient()
    jquants = JQuantsClient()

    days_back = 365 if mode == "fast" else settings.edinet_lookback_days
    edinet_error = None
    use_prices = (not settings.edinet_only) or settings.jquants_prices_only
    preliminary_name = company_name or KNOWN_CODE_NAME_JP.get(stock_code) or stock_code

    # Pre-check EDINET financials cache (skip slow XBRL parsing if cached)
    _ed_fin_cache_key = f"edinet_fin_{stock_code}_{days_back}.json"
    _ed_fin_cache_path = Path(settings.output_dir) / "cache" / _ed_fin_cache_key
    _cached_edinet_financials = load_cache(_ed_fin_cache_path, max_age_seconds=7 * 24 * 3600)

    # ══════════════════════════════════════════════════════════════════════
    #  Dependency-driven parallel pipeline (ThreadPoolExecutor)
    #
    #  Wave 0 (t=0):  company_info, listed_info, serp, financials, prices,
    #                  5 web scrapers (cached), activist_radar        [11]
    #  Gate 1 (→company_info): edinet_docs
    #  Gate 2 (→serp):         research_pages
    #  Gate 3 (→edinet_docs):  edinet_financials, narratives, segments
    #  Gate 4 (→narratives+research): LLM extract_edinet_all ‖ LLM profile
    #  Gate 5 (→edinet_fin):   valuation, peers (background thread)
    # ══════════════════════════════════════════════════════════════════════
    progress(10, "Data Fetch", "Launching parallel data collection")

    with ThreadPoolExecutor(max_workers=14) as pool:

        # ── Wave 0: fire all zero-dependency tasks immediately ────────────

        fut_company = pool.submit(lambda: jquants.get_company_info(stock_code))
        fut_listed = pool.submit(lambda: jquants.get_listed_info(stock_code))
        fut_serp = pool.submit(
            lambda: serp.search_company_context(preliminary_name, stock_code, mode=mode)
        )

        if use_prices and (jquants.api_key or jquants.refresh_token):
            fut_financials = pool.submit(lambda: jquants.get_financials(stock_code))
            fut_prices = pool.submit(lambda: jquants.get_prices(stock_code))
        else:
            fut_financials = None
            fut_prices = None

        # Web scrapers — no dependencies, 24h file cache
        fut_kab_own = pool.submit(
            lambda: _cached_web_fetch("kabutan_own", stock_code, _fetch_ownership_web)
        )
        fut_kab_sh = pool.submit(
            lambda: _cached_web_fetch("kabutan_sh", stock_code, _fetch_shareholders_kabutan)
        )
        fut_kab_corp = pool.submit(
            lambda: _cached_web_fetch("kabutan_corp", stock_code, _fetch_corporate_info_kabutan)
        )
        fut_yahoo_corp = pool.submit(
            lambda: _cached_web_fetch("yahoo_corp", stock_code, _fetch_corporate_info_yahoo_jp)
        )
        fut_web_sec = pool.submit(
            lambda: _cached_web_fetch("web_sectors", stock_code, _scrape_sector_from_web)
        )
        fut_activist = pool.submit(lambda: _fetch_activist_radar_data(stock_code, []))

        # ── Gate 1: company_info + listed_info → resolve name → edinet ──

        try:
            company_info = fut_company.result()
        except Exception:
            company_info = None
        try:
            listed_info = fut_listed.result()
        except Exception:
            listed_info = None

        # ETF / REIT / Fund detection (flag, not error)
        _market_code = ((listed_info or {}).get("MarketCodeName") or (listed_info or {}).get("MktNm") or "").lower()
        _co_name = ((listed_info or {}).get("CompanyName") or (listed_info or {}).get("CoName") or (listed_info or {}).get("CoNameEn") or "")
        _co_name_lower = _co_name.lower()
        _is_etf = any(kw in _market_code for kw in ("etf", "etn")) or "etf" in _co_name_lower or "\uff25\uff34\uff26" in _co_name or "etn" in _co_name_lower
        _is_reit = "reit" in _market_code or "reit" in _co_name_lower or "\uff32\uff25\uff29\uff34" in _co_name or "\u6295\u8cc7\u6cd5\u4eba" in _co_name
        _is_fund = _is_etf or _is_reit
        _fund_type = "ETF" if _is_etf else ("REIT" if _is_reit else None)

        resolved_company_name = _coerce_company_name(company_name, company_info.name if company_info else None)
        if resolved_company_name == "Unknown Company":
            resolved_company_name = KNOWN_CODE_NAME_JP.get(stock_code, resolved_company_name)

        progress(15, "Data Fetch", "Fetching EDINET filings")

        def _do_fetch_edinet_docs():
            def on_match(doc):
                event(
                    "edinet",
                    f"Found EDINET filing {doc.doc_id}",
                    {
                        "doc_id": doc.doc_id,
                        "submit_date": doc.submit_date,
                        "doc_type": doc.doc_type_code or doc.doc_type,
                        "filer": doc.filer_name,
                    },
                )
            try:
                return edinet.latest_filings_for_code(
                    stock_code,
                    days_back=days_back,
                    company_name=resolved_company_name,
                    doc_type=settings.edinet_doc_type,
                    max_docs=20,
                    on_match=on_match,
                )
            except Exception as exc:
                return {"error": str(exc)}

        fut_edinet_docs = pool.submit(_do_fetch_edinet_docs)

        # ── Gate 2: serp → research_pages ─────────────────────────────

        try:
            serp_results = fut_serp.result() or []
        except Exception:
            serp_results = []

        if resolved_company_name == "Unknown Company":
            serp_name_hint = _serp_company_name_hint(serp_results)
            if serp_name_hint:
                resolved_company_name = serp_name_hint

        fut_research = pool.submit(
            lambda: _collect_research_pages(serp_results, limit=10 if mode == "full" else 4)
        )

        # ── Gate 3: edinet_docs → financials, narratives, segments ────

        edinet_docs_result = fut_edinet_docs.result()
        if isinstance(edinet_docs_result, dict) and "error" in edinet_docs_result:
            edinet_docs = []
            edinet_error = edinet_docs_result["error"]
        else:
            edinet_docs = edinet_docs_result or []

        if edinet_docs:
            progress(25, "Data Fetch", f"Found {len(edinet_docs)} EDINET filings")
        else:
            progress(25, "Data Fetch", "No EDINET filings found")

        if resolved_company_name == "Unknown Company" and edinet_docs:
            resolved_company_name = edinet_docs[0].filer_name or resolved_company_name

        def _do_edinet_financials():
            if _cached_edinet_financials:
                return _cached_edinet_financials
            try:
                def on_scan(doc, idx, total):
                    event(
                        "edinet_scan",
                        f"Scanning {doc.doc_id}",
                        {
                            "doc_id": doc.doc_id,
                            "submit_date": doc.submit_date,
                            "index": idx,
                            "total": total,
                        },
                    )
                    if total:
                        pct = 30 + int(10 * (idx / total))
                        progress(pct, "Extraction", f"Scanning EDINET XBRL {idx}/{total}")

                result = edinet.latest_financials_for_code(
                    stock_code,
                    days_back=days_back,
                    company_name=resolved_company_name,
                    docs=edinet_docs,
                    on_scan=on_scan,
                )
                if result:
                    save_cache(_ed_fin_cache_path, result)
                return result
            except Exception as exc:
                return {"_error": str(exc)}

        def _do_edinet_narratives():
            if not edinet_docs:
                return []
            docs_to_fetch = edinet_docs[:5]
            tasks = [lambda doc=doc: edinet.extract_narrative_for_doc(doc.doc_id) for doc in docs_to_fetch]
            texts = run_concurrent(tasks, max_workers=min(5, len(tasks)))
            narratives = []
            for doc, text in zip(docs_to_fetch, texts):
                if text:
                    narratives.append(f"[{doc.doc_id}]\n{text}")
                    event("edinet", f"Narrative extracted from {doc.doc_id}", {"doc_id": doc.doc_id})
            return narratives

        def _do_edinet_segments():
            if not edinet_docs:
                return []
            for doc in edinet_docs[:3]:
                try:
                    segs = edinet.extract_segments_for_doc(doc.doc_id)
                    if segs and len(segs) >= 2:
                        event("edinet", f"Segments extracted from {doc.doc_id}", {"count": len(segs)})
                        return segs
                except Exception:
                    continue
            return []

        progress(30, "Extraction", "Extracting financials, narratives & segments")
        fut_ed_fin = pool.submit(_do_edinet_financials)
        fut_narratives = pool.submit(_do_edinet_narratives)
        fut_segments = pool.submit(_do_edinet_segments)

        # ── Gate 4a: jquants financials + prices (likely done by now) ─

        try:
            jquants_financials = fut_financials.result() if fut_financials else {}
        except Exception:
            jquants_financials = {}
        jquants_financials = jquants_financials or {}

        try:
            prices = fut_prices.result() if fut_prices else {}
        except Exception:
            prices = {}
        prices = prices or {}

        # ── Gate 4b: narratives → edinet_narrative ────────────────────

        narrative_parts = fut_narratives.result() or []
        edinet_narrative = "\n\n".join(narrative_parts) if narrative_parts else ""
        edinet_profile = _extract_profile_from_edinet(edinet_narrative)

        # ── Gate 4c: research_pages → profile data ────────────────────

        research_pages = fut_research.result() or []
        profile_data, profile_sources = _extract_company_profile(research_pages)

        # Build research_context (without edinet_summary — not yet available;
        # edinet_narrative is passed separately to LLM so info is not lost)
        research_context = ""
        if research_pages:
            chunks = []
            for page in research_pages:
                excerpt = page["text"][:2000]
                chunks.append(f"Source: {page['title']} ({page['url']})\n{excerpt}")
            research_context = "\n\n".join(chunks)

        # Build merged_profile (before LLM enrichment)
        merged_profile = dict(profile_data)
        for key, value in edinet_profile.items():
            if key not in merged_profile or not merged_profile.get(key):
                merged_profile[key] = value
        _known_hq = KNOWN_CODE_HEAD_OFFICE.get(stock_code)
        if _known_hq:
            merged_profile["head_office"] = _known_hq

        # ── Fire BOTH LLM calls in parallel (biggest time saving) ─────

        progress(50, "Analysis", "Running AI analysis (parallel LLM calls)")

        def _do_llm_edinet_all():
            """Single merged LLM call for insights/risks/governance/projects/ESG."""
            if not edinet_narrative:
                return None
            _cache_doc_ids = "_".join(sorted(d.doc_id for d in edinet_docs[:3])) if edinet_docs else "none"
            _llm_cache_key = f"llm_edinet_{stock_code}_{_cache_doc_ids}.json"
            _llm_cache_path = Path(settings.output_dir) / "cache" / _llm_cache_key
            _cached_llm = load_cache(_llm_cache_path, max_age_seconds=24 * 3600)
            if _cached_llm and isinstance(_cached_llm, dict) and _cached_llm.get("insights"):
                progress(55, "Analysis", "Loaded EDINET analysis from cache")
                return _cached_llm
            try:
                llm = LlmClient()
                progress(55, "Analysis", "Running EDINET analysis (merged call)")
                combined_raw = llm.extract_edinet_all(resolved_company_name, stock_code, edinet_narrative)
                combined = _safe_parse_json(combined_raw)
                if combined:
                    save_cache(_llm_cache_path, combined)
                return combined
            except Exception:
                return None

        def _do_llm_profile():
            """LLM enrichment for missing profile fields."""
            missing_fields = [
                k for k in ("representative", "founded", "head_office",
                             "employees", "listed_markets", "core_businesses")
                if not merged_profile.get(k)
            ]
            if not missing_fields:
                return None
            try:
                llm = LlmClient()
                progress(56, "Analysis", "Synthesizing company profile (GPT)")
                enriched_raw = llm.extract_profile_from_sources(
                    resolved_company_name, stock_code, research_context, edinet_narrative
                )
                return _safe_parse_json(enriched_raw)
            except Exception:
                return None

        fut_llm_edinet = pool.submit(_do_llm_edinet_all)
        fut_llm_profile = pool.submit(_do_llm_profile)

        # ── Gate 5: edinet_financials → merge, KPIs, valuation ────────

        edinet_financials = _cached_edinet_financials or {}
        edinet_fin_result = fut_ed_fin.result()
        if isinstance(edinet_fin_result, dict) and "_error" in edinet_fin_result:
            if not edinet_financials:
                edinet_financials = {}
            if not edinet_error:
                edinet_error = edinet_fin_result["_error"]
        elif edinet_fin_result:
            edinet_financials = edinet_fin_result

        # Determine financials source
        financials_source = "jquants"
        if edinet_financials:
            financials = edinet_financials
            financials_source = "edinet"
            if resolved_company_name == "Unknown Company":
                resolved_company_name = edinet_financials.get("filer_name") or resolved_company_name
        else:
            financials = jquants_financials
            financials_source = "jquants" if jquants_financials else "edinet"

        if company_name and resolved_company_name == "Unknown Company":
            resolved_company_name = company_name

        prices_error = None
        if not prices and use_prices:
            if jquants.api_key or jquants.refresh_token:
                prices_error = "J-Quants returned empty prices"
            else:
                prices_error = "J-Quants API key missing or invalid"

        # Fallback to public CSV if J-Quants returned nothing
        try:
            if use_prices and (not prices or not _compute_price_kpis(prices).get("row_count")):
                progress(57, "Analysis", "Fallback price fetch (Stooq CSV)")
                csv_prices = jquants.get_prices_fallback_csv(stock_code, from_date=None)
                if csv_prices and _compute_price_kpis(csv_prices).get("row_count"):
                    prices = csv_prices
                    prices_error = None
        except Exception as exc:
            if not prices_error:
                prices_error = f"Fallback price error: {exc}"

        merged_financials = _merge_jquants_edinet(jquants_financials, edinet_financials) if jquants_financials and edinet_financials else (jquants_financials or financials)
        financial_kpis = _compute_financial_kpis(merged_financials)
        price_kpis = _compute_price_kpis(prices)
        price_rows_count = price_kpis.get("row_count") if price_kpis else 0

        # Pre-compute segments for valuation
        _pre_segment_candidates = _extract_segment_revenue(edinet_narrative)
        edinet_segments = fut_segments.result() or []
        if edinet_segments and len(edinet_segments) >= 2:
            valuation_segments = [
                {"name": s.get("segment", ""), "revenue": s.get("revenue_mm", 0)}
                for s in edinet_segments if s.get("revenue_mm")
            ]
        else:
            valuation_segments = _pre_segment_candidates

        # ── SPEED: Start valuation in a DEFERRED daemon thread ──────
        # Instead of waiting for valuation inside the ThreadPool (blocking
        # build_report_payload), run it as a background thread so the payload
        # can return sooner.  build_report_context() will join the valuation
        # thread WHILE the narrative LLM call runs in parallel — saving
        # 15-25s by overlapping the two biggest remaining tasks.
        has_financials = bool(financial_kpis.get("rows"))
        _valuation_result_holder: Dict[str, Any] = {}

        def _bg_valuation():
            try:
                valuation_engine = ValuationEngine()
                val = valuation_engine.estimate_for_company(
                    stock_code,
                    merged_financials,
                    prices,
                    listed_info or {},
                    segments=valuation_segments,
                    on_event=event,
                    company_name=resolved_company_name,
                    sector_hint=company_info.sector if company_info else None,
                    edinet_narrative=edinet_narrative,
                )
                if val:
                    _valuation_result_holder["data"] = {
                        "model_type": val.model_type,
                        "samples": val.samples,
                        "r2": val.r2,
                        "predicted_multiple": val.predicted_multiple,
                        "actual_multiple": val.actual_multiple,
                        "implied_price": val.implied_price,
                        "range_low": val.range_low,
                        "range_high": val.range_high,
                        "score_z": val.score_z,
                        "peer_multiple": val.peer_multiple,
                        "peer_price": val.peer_price,
                        "peer_range_low": val.peer_range_low,
                        "peer_range_high": val.peer_range_high,
                        "dcf_price": val.dcf_price,
                        "dcf_range_low": val.dcf_range_low,
                        "dcf_range_high": val.dcf_range_high,
                        "sotp_price": val.sotp_price,
                        "sotp_range_low": val.sotp_range_low,
                        "sotp_range_high": val.sotp_range_high,
                        "last_price": val.last_price,
                        "market_cap": val.market_cap,
                        "shares": val.shares,
                        "target_price": val.target_price,
                        "target_low": val.target_low,
                        "target_high": val.target_high,
                        "upside_pct": val.upside_pct,
                        "quality_score": val.quality_score,
                        "method_count": val.method_count,
                        "notes": val.notes,
                        "advisor": val.advisor,
                        "method_results": val.method_results,
                        "primary_method": val.primary_method,
                        "sector_classification": val.sector_classification,
                        "valuation_narrative": val.valuation_narrative,
                        "extended_metrics": val.extended_metrics,
                    }
            except Exception as exc:
                print(f"[VALUATION ERROR] {exc}")

        _valuation_thread = None
        if has_financials:
            progress(58, "Valuation", "Starting AI valuation (background)")
            _valuation_thread = _threading.Thread(target=_bg_valuation, daemon=True)
            _valuation_thread.start()

        # Start peers in background thread (deferred join in build_report_context)
        _peer_result_holder: Dict[str, Any] = {}
        _ed_fin_ok = isinstance(edinet_financials, dict) and "_error" not in edinet_financials and edinet_financials
        _financials_for_peers = jquants_financials or (edinet_financials if _ed_fin_ok else {})
        _peer_sector_hint = company_info.sector if company_info else None
        _peer_company_name = (company_info.name if company_info else None) or resolved_company_name or ""
        try:
            _pre_web_sectors = fut_web_sec.result()
        except Exception:
            _pre_web_sectors = None
        if not isinstance(_pre_web_sectors, list):
            _pre_web_sectors = None

        def _bg_fetch_peers():
            try:
                _peer_result_holder["data"] = _fetch_peer_benchmarking(
                    stock_code, _peer_sector_hint, _financials_for_peers,
                    web_sectors=_pre_web_sectors, company_name=_peer_company_name,
                )
            except Exception as exc:
                print(f"[PEER DEBUG] Background peer fetch failed: {exc}")
                _peer_result_holder["data"] = {}

        _peer_thread = _threading.Thread(target=_bg_fetch_peers, daemon=True)
        _peer_thread.start()

        # ── Collect LLM results ───────────────────────────────────────

        edinet_insights: Dict[str, Any] = {}
        edinet_summary = ""
        capital_projects: List[Dict[str, Any]] = []
        esg_data: Dict[str, Any] = {}

        llm_edinet_result = fut_llm_edinet.result()
        if llm_edinet_result and isinstance(llm_edinet_result, dict):
            edinet_insights = llm_edinet_result.get("insights") or {}
            edinet_summary = llm_edinet_result.get("summary") or ""
            capital_projects_raw = llm_edinet_result.get("capital_projects")
            if isinstance(capital_projects_raw, list):
                capital_projects = capital_projects_raw
            elif isinstance(capital_projects_raw, dict):
                capital_projects = capital_projects_raw.get("projects") or capital_projects_raw.get("pipeline") or []
            esg_data = llm_edinet_result.get("esg") or {}

        # Enrich profile with edinet insights (core_businesses from segments)
        if not merged_profile.get("core_businesses"):
            segments = edinet_insights.get("business_segments") if isinstance(edinet_insights, dict) else None
            if isinstance(segments, list) and segments:
                seg_names = []
                for s in segments:
                    if isinstance(s, dict):
                        name = s.get("name", "")
                        if name and name != "\u2014":
                            seg_names.append(name)
                    elif isinstance(s, str) and s and s != "\u2014":
                        seg_names.append(s)
                merged_profile["core_businesses"] = "; ".join(seg_names) or merged_profile.get("core_businesses")

        # Apply LLM profile enrichment
        llm_profile_result = fut_llm_profile.result()
        if llm_profile_result and isinstance(llm_profile_result, dict):
            missing_fields = [
                k for k in ("representative", "founded", "head_office",
                             "employees", "listed_markets", "core_businesses")
                if not merged_profile.get(k)
            ]
            for key, value in llm_profile_result.items():
                if key in missing_fields and value and value != "\u2014":
                    merged_profile[key] = value

        progress(65, "Analysis", "Data compilation complete")

        # ── Collect remaining web scraper futures ─────────────────────

        try:
            kabutan_ownership = fut_kab_own.result() or {}
        except Exception:
            kabutan_ownership = {}
        try:
            kabutan_shareholders = fut_kab_sh.result() or []
        except Exception:
            kabutan_shareholders = []
        try:
            kabutan_corporate = fut_kab_corp.result() or {}
        except Exception:
            kabutan_corporate = {}
        try:
            yahoo_corporate = fut_yahoo_corp.result() or {}
        except Exception:
            yahoo_corporate = {}

        try:
            activist_radar = fut_activist.result() or {"filings": [], "has_poison_pill": False}
        except Exception:
            activist_radar = {"filings": [], "has_poison_pill": False}
        if isinstance(activist_radar, dict):
            activist_radar["has_poison_pill"] = _check_poison_pill(edinet_narrative)

    # ── ThreadPoolExecutor exited — pool tasks complete (valuation runs in background) ──

    # ── Build sources list ────────────────────────────────────────────
    sources = []
    source_id = 1
    seen_urls = set()
    for item in serp_results[: settings.max_sources]:
        if item.url in seen_urls:
            continue
        seen_urls.add(item.url)
        sources.append({
            "id": source_id,
            "title": item.title,
            "url": item.url,
            "snippet": item.snippet,
            "date": item.date,
            "type": item.source_type,
        })
        source_id += 1

    for page in research_pages:
        if page["url"] in seen_urls:
            continue
        seen_urls.add(page["url"])
        sources.append({
            "id": source_id,
            "title": page.get("title") or page["url"],
            "url": page["url"],
            "snippet": page["text"][:240],
            "date": None,
            "type": "web",
        })
        source_id += 1

    for doc in edinet_docs:
        edinet_viewer_url = f"https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{doc.doc_id}"
        sources.append({
            "id": source_id,
            "title": f"EDINET filing: {doc.filer_name} ({doc.doc_type})",
            "url": edinet_viewer_url,
            "snippet": doc.description or "",
            "date": doc.submit_date,
            "type": "edinet",
        })
        source_id += 1

    source_id_map = {s["url"]: s["id"] for s in sources if s.get("url")}
    edinet_source_id = None
    if edinet_docs:
        edinet_viewer_url = f"https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{edinet_docs[0].doc_id}"
        edinet_source_id = source_id_map.get(edinet_viewer_url)

    # Finalize research_context with edinet_summary (now available)
    if edinet_summary:
        research_context = f"{research_context}\n\nEDINET Summary:\n{edinet_summary}" if research_context else f"EDINET Summary:\n{edinet_summary}"

    profile_block = _build_profile_block(merged_profile, profile_sources, source_id_map, fallback_source_id=edinet_source_id)

    if isinstance(edinet_insights, dict) and edinet_insights:
        # Handle both old string format and new dict format for business_segments
        raw_segments = edinet_insights.get("business_segments") or []
        segment_strs = []
        for seg in raw_segments:
            if isinstance(seg, dict):
                name = seg.get("name", "\u2014")
                pct = seg.get("pct")
                segment_strs.append(f"{name} ({pct}%)" if pct else name)
            elif isinstance(seg, str):
                segment_strs.append(seg)
        insights_lines = [
            "EDINET Insights:",
            "Business Segments: " + "; ".join(segment_strs),
            "Risk Factors: " + "; ".join(edinet_insights.get("risk_factors") or []),
            "Governance (board): " + str((edinet_insights.get("governance") or {}).get("board") or "\u2014"),
            "Governance (auditors): " + str((edinet_insights.get("governance") or {}).get("auditors") or "\u2014"),
            "Governance (ownership): " + str((edinet_insights.get("governance") or {}).get("ownership") or "\u2014"),
        ]
        research_context = f"{research_context}\n\n" + "\n".join(insights_lines)

    # Re-extract segments now that research_context is enriched with insights
    segment_candidates = _extract_segment_revenue(f"{research_context}\n{edinet_narrative}")

    appendix_tables_md = _render_appendix_tables(financial_kpis, price_kpis)

    metrics = {
        "company": {
            "name": resolved_company_name,
            "stock_code": stock_code,
            "sector": company_info.sector if company_info else None,
            "market": company_info.market if company_info else None,
        },
        "financials": financial_kpis,
        "prices": price_kpis,
    }

    data_health = {
        "sources": len(sources),
        "edinet_filings": len(edinet_docs),
        "financial_rows": len(financial_kpis.get("rows", [])),
        "price_rows": price_rows_count,
        "company_name_resolved": resolved_company_name != "Unknown Company",
        "financials_source": financials_source,
        "input_company_name": input_company_name or "",
        "resolved_company_name": resolved_company_name,
    }

    warnings = []
    if not (settings.edinet_api_key or settings.edinet_subscription_key):
        warnings.append("EDINET key missing (set EDINET_SUBSCRIPTION_KEY or EDINET_API_KEY).")
    if not settings.jquants_api_key and not settings.jquants_refresh_token:
        if not settings.edinet_only:
            warnings.append("J-Quants API credentials missing.")
    if edinet_error:
        warnings.append(f"EDINET error: {edinet_error}")
    elif not edinet_docs:
        warnings.append("No EDINET filings found for this code.")
    if not financial_kpis.get("rows"):
        warnings.append("No financial rows extracted from EDINET/J-Quants.")
    if price_rows_count == 0:
        if prices_error:
            warnings.append(f"J-Quants price error: {prices_error}")
        else:
            warnings.append("No price rows from J-Quants.")
    # Valuation warning deferred to build_report_context (valuation runs in background)

    data_health["warnings"] = warnings

    facts_summary = [
        f"Company: {resolved_company_name} ({stock_code})",
        f"Sector: {company_info.sector if company_info else 'Unknown'}",
        f"Market: {company_info.market if company_info else 'Unknown'}",
        f"Sources: {len(sources)}",
        f"EDINET filings: {len(edinet_docs)}",
        f"Financial rows: {len(financial_kpis.get('rows', []))}",
        f"Price rows: {price_rows_count}",
        f"Financials source: {financials_source}",
    ]
    if resolved_company_name == "Unknown Company":
        facts_summary.append("Company name unresolved; verify stock code or J-Quants access.")

    latest_summary = financial_kpis.get("summary", {})
    if latest_summary.get("latest_period"):
        facts_summary.append(f"Latest period: {latest_summary.get('latest_period')}")
        facts_summary.append(
            f"Revenue growth: {_format_pct(latest_summary.get('revenue_growth'))}"
        )
    fin_rows = financial_kpis.get("rows") or []
    if fin_rows:
        latest_row = fin_rows[0]
        facts_summary.append(f"Latest revenue (raw): {latest_row.get('revenue')}")
        facts_summary.append(f"Latest operating profit (raw): {latest_row.get('operating_profit')}")
        facts_summary.append(f"Latest net income (raw): {latest_row.get('net_income')}")
        facts_summary.append(f"Latest op margin: {_format_pct(latest_row.get('op_margin'))}")
        facts_summary.append(f"Latest net margin: {_format_pct(latest_row.get('net_margin'))}")
        facts_summary.append(f"Latest ROE: {_format_pct(latest_row.get('roe'))}")
        # Additional metrics for richer LLM narrative
        for extra_key in ["ocf", "operating_cash_flow", "capex", "dps", "bps",
                          "equity_ratio", "total_assets", "total_equity", "total_debt"]:
            val = latest_row.get(extra_key)
            if val is not None:
                facts_summary.append(f"Latest {extra_key}: {val}")

        # Multi-year financial history for trend analysis
        if len(fin_rows) >= 2:
            facts_summary.append("\nMulti-year financial history (newest first):")
            for i, row in enumerate(fin_rows[:6]):
                period = row.get("period", f"Period-{i}")
                rev = row.get("revenue")
                op = row.get("operating_profit")
                ni = row.get("net_income")
                opm = row.get("op_margin")
                roe = row.get("roe")
                ocf = row.get("ocf") or row.get("operating_cash_flow")
                dps = row.get("dps")
                capex = row.get("capex")
                parts = [f"  {period}:"]
                if rev is not None: parts.append(f"Rev={rev}")
                if op is not None: parts.append(f"OP={op}")
                if ni is not None: parts.append(f"NI={ni}")
                if opm is not None: parts.append(f"OPM={_format_pct(opm)}")
                if roe is not None: parts.append(f"ROE={_format_pct(roe)}")
                if ocf is not None: parts.append(f"OCF={ocf}")
                if dps is not None: parts.append(f"DPS={dps}")
                if capex is not None: parts.append(f"Capex={capex}")
                facts_summary.append(" ".join(parts))

            # Compute derived metrics for LLM
            oldest_rev = None
            for row in reversed(fin_rows[:6]):
                r = row.get("revenue")
                if r and r > 0:
                    oldest_rev = r
                    break
            latest_rev = latest_row.get("revenue")
            if oldest_rev and latest_rev and oldest_rev > 0 and len(fin_rows) >= 3:
                n_years = min(len(fin_rows), 6) - 1
                cagr = ((latest_rev / oldest_rev) ** (1.0 / n_years) - 1) if n_years > 0 else 0
                facts_summary.append(f"\nDerived: {n_years}-year revenue CAGR = {cagr*100:.1f}%")
            latest_ocf = latest_row.get("ocf") or latest_row.get("operating_cash_flow")
            latest_ni = latest_row.get("net_income")
            if latest_ocf and latest_ni and latest_ni > 0:
                facts_summary.append(f"Derived: OCF/Net Income ratio = {latest_ocf/latest_ni:.2f}x")
            latest_capex = latest_row.get("capex")
            if latest_capex and latest_rev and latest_rev > 0:
                facts_summary.append(f"Derived: Capex/Sales = {abs(latest_capex)/latest_rev*100:.1f}%")

    # Include EDINET-parsed segment data in facts for LLM accuracy
    if edinet_segments and len(edinet_segments) >= 2:
        seg_lines = ["EDINET Segment Data (parsed from filing \u2014 use these as ground truth for revenue_mix):"]
        for s in edinet_segments:
            seg_name = s.get("segment", "?")
            seg_pct = s.get("pct")
            seg_rev = s.get("revenue_mm")
            seg_profit = s.get("profit_mm")
            parts = [f"  - {seg_name}"]
            if seg_rev is not None:
                parts.append(f"\u00a5{seg_rev:,.0f}M")
            if seg_pct is not None:
                parts.append(f"({seg_pct:.1f}%)")
            if seg_profit is not None:
                parts.append(f"profit \u00a5{seg_profit:,.0f}M")
            seg_lines.append(" ".join(parts))
        facts_summary.extend(seg_lines)

    # Valuation data injected by build_report_context after background join

    progress(78, "Compilation", "Compiling payload (peers finishing in background)")
    # Final company_name: JP override if mapped
    final_company_name = KNOWN_CODE_NAME_JP.get(stock_code, resolved_company_name)

    return {
        "company_name": final_company_name,
        "company_name_en": KNOWN_CODE_NAME_EN.get(stock_code),
        "stock_code": stock_code,
        "sector": company_info.sector if company_info else None,
        "is_etf": _is_fund,
        "fund_type": _fund_type,  # "ETF" | "REIT" | None
        "sources": sources,
        "metrics_json": _safe_json(metrics),
        "metrics": metrics,
        "financials_raw": merged_financials,
        "prices_raw": prices,
        "report_mode": mode,
        "appendix_tables_md": appendix_tables_md,
        "facts_summary": "\n".join(facts_summary),
        "v6_data_block": _build_v6_data_block(financial_kpis),
        "valuation_block": "",  # injected by build_report_context after join
        "valuation_data": {},   # injected by build_report_context after join
        "_valuation_thread": _valuation_thread,
        "_valuation_result_holder": _valuation_result_holder,
        "profile_block": profile_block,
        "profile_data": merged_profile,
        "listed_info": listed_info or {},
        "segment_candidates": segment_candidates,
        "edinet_segments": edinet_segments,
        "kabutan_ownership": kabutan_ownership,
        "kabutan_shareholders": kabutan_shareholders,
        "kabutan_corporate": kabutan_corporate,
        "yahoo_corporate": yahoo_corporate,
        "peer_benchmarking": {},  # populated by build_report_context after peer join
        "_peer_thread": _peer_thread,
        "_peer_result_holder": _peer_result_holder,
        "activist_radar": activist_radar,
        "edinet_docs": [
            {
                "doc_id": d.doc_id,
                "submit_date": d.submit_date or "\u2014",
                "description": d.description,
                "doc_type": d.doc_type,
                "doc_type_code": d.doc_type_code,
            }
            for d in edinet_docs[:6]
        ],
        "research_context": research_context,
        "edinet_narrative": edinet_narrative[:20000],
        "edinet_insights": edinet_insights,
        "edinet_summary": edinet_summary,
        "capital_projects": capital_projects,
        "esg_data": esg_data,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_health": data_health,
    }


def generate_report_markdown(payload: Dict, on_progress=None) -> str:
    if on_progress:
        on_progress(80, "Drafting", "Generating report narrative")
    llm = LlmClient()
    return llm.generate_report_markdown(payload, on_progress=on_progress)


def _is_narrative_valid(narrative: Dict[str, Any]) -> bool:
    """Check if the LLM narrative has the essential fields populated."""
    if not isinstance(narrative, dict):
        return False
    # Support both new format (company_profile/business_performance) and legacy (summary_text/outlook_summary)
    has_profile = False
    for key in ("company_profile", "summary_text"):
        val = narrative.get(key)
        if val and isinstance(val, str) and len(val.strip()) >= 20:
            has_profile = True
            break
    if not has_profile:
        return False
    has_performance = False
    for key in ("business_performance", "outlook_summary"):
        val = narrative.get(key)
        if val and isinstance(val, str) and len(val.strip()) >= 20:
            has_performance = True
            break
    if not has_performance:
        return False
    for key in ("bull_case", "bear_case"):
        val = narrative.get(key)
        if not isinstance(val, list) or len(val) == 0:
            return False
    return True


def _build_fallback_narrative(payload: Dict) -> Dict[str, Any]:
    """Build a data-driven narrative when the LLM fails to generate content."""
    company_name = payload.get("company_name") or "Unknown Company"
    stock_code = payload.get("stock_code") or ""
    from app.services.sector_lookup import get_sector as _get_sector
    sector = payload.get("sector") or _get_sector(payload.get("stock_code", "")) or "General"

    metrics = payload.get("metrics", {})
    financials = metrics.get("financials", {})
    rows = financials.get("rows", [])
    fin_summary = financials.get("summary", {})
    profile = payload.get("profile_data", {})

    rows_sorted = sorted(rows, key=lambda r: _parse_date(r.get("period")) or dt.date.min)
    # Prefer latest FY row for accurate ratios; fall back to latest row
    fy_rows_narr = [r for r in rows_sorted if r.get("period_type") == "FY"]
    latest = fy_rows_narr[-1] if fy_rows_narr else (rows_sorted[-1] if rows_sorted else {})

    revenue = latest.get("revenue")
    op_profit = latest.get("operating_profit")
    net_income = latest.get("net_income")
    op_margin = latest.get("op_margin")
    roe = latest.get("roe")
    cfo = latest.get("cfo")
    equity = latest.get("equity")
    total_assets = latest.get("total_assets")
    eq_ratio = _safe_ratio(equity, total_assets)
    rev_growth = fin_summary.get("revenue_growth")
    op_growth = fin_summary.get("operating_profit_growth")

    # --- company_profile ---
    parts = [f"{company_name} ({stock_code}) operates in the {sector} sector."]
    if revenue:
        part = f"The company reported revenue of ¥{_format_number(revenue)} in the latest fiscal period"
        if op_margin:
            part += f" with an operating margin of {op_margin*100:.1f}%"
        parts.append(part + ".")
    core_biz = profile.get("core_businesses")
    if core_biz:
        parts.append(f"Core business activities include {core_biz}.")
    if roe:
        quality = "strong" if roe > 0.10 else "moderate" if roe > 0.05 else "below-average"
        parts.append(f"ROE of {roe*100:.1f}% indicates {quality} capital efficiency relative to Japanese market peers.")
    if eq_ratio:
        stance = "conservative" if eq_ratio > 0.5 else "balanced" if eq_ratio > 0.3 else "leveraged"
        parts.append(f"The company maintains a {stance} balance sheet with equity ratio of {eq_ratio*100:.0f}%.")
    company_profile = " ".join(parts)

    # --- business_performance ---
    perf_parts = []
    if rev_growth is not None and revenue:
        direction = "grew" if rev_growth > 0 else "declined"
        perf_parts.append(f"{company_name} revenue {direction} {abs(rev_growth)*100:.1f}% YoY to ¥{_format_number(revenue)}")
    if op_growth is not None and op_profit:
        direction = "expanding" if op_growth > 0 else "contracting"
        perf_parts.append(f"operating profit {direction} {abs(op_growth)*100:.1f}% to ¥{_format_number(op_profit)}")
    if roe:
        perf_parts.append(f"ROE stands at {roe*100:.1f}%")
    business_performance = ", ".join(perf_parts) + "." if perf_parts else f"{company_name} financial performance is detailed in the latest EDINET filings."
    if cfo:
        cfo_ni = ""
        if net_income and net_income > 0:
            ratio = cfo / net_income
            cfo_ni = f" ({ratio:.1f}x net income)" if ratio > 0 else ""
        business_performance += f" Operating cash flow of ¥{_format_number(cfo)}{cfo_ni} provides insight into earnings quality."

    # --- material_note ---
    material_note = f"{company_name} operates in the {sector} sector — investors should monitor industry-specific regulatory and competitive developments."

    # --- investment_thesis ---
    investment_thesis = []
    if revenue and op_margin:
        quality = "demonstrating solid profitability" if op_margin > 0.08 else "reflecting competitive industry dynamics"
        investment_thesis.append(
            f"Generated revenue of ¥{_format_number(revenue)} with {op_margin*100:.1f}% operating margin, {quality}."
        )
    if roe and roe > 0.06:
        investment_thesis.append(
            f"ROE of {roe*100:.1f}% {'exceeds' if roe > 0.08 else 'approaches'} the typical cost of equity for Japanese companies."
        )
    if cfo and cfo > 0:
        investment_thesis.append(
            f"Positive operating cash flow of ¥{_format_number(cfo)} supports operations and shareholder returns."
        )
    investment_thesis.append(f"Listed on the TSE under ticker {stock_code}, operating in the {sector} sector.")
    investment_thesis = investment_thesis[:4]

    # --- bull_case ---
    bull_case = []
    if rev_growth and rev_growth > 0:
        bull_case.append(
            f"Revenue growth of {rev_growth*100:.1f}% YoY demonstrates positive business momentum, "
            f"with top-line reaching ¥{_format_number(revenue)} in the latest period."
        )
    if roe and roe > 0.06:
        bull_case.append(
            f"ROE of {roe*100:.1f}% indicates value creation for shareholders with potential for further improvement."
        )
    if not bull_case:
        bull_case = [
            "Financial data suggests stable operations with established market presence.",
            "Listed company with public disclosure requirements enabling transparent monitoring.",
        ]

    # --- bear_case ---
    bear_case = []
    if rev_growth is not None and rev_growth < 0:
        bear_case.append(
            f"Revenue decline of {abs(rev_growth)*100:.1f}% YoY raises concerns about demand sustainability."
        )
    if op_margin and op_margin < 0.05:
        bear_case.append(
            f"Operating margin of {op_margin*100:.1f}% indicates limited pricing power or cost pressures."
        )
    if not bear_case:
        bear_case = [
            "Market and macroeconomic conditions may impact future performance.",
            "Competitive dynamics and industry-specific risks require ongoing monitoring.",
        ]

    return {
        "company_profile": company_profile,
        "business_performance": business_performance,
        "material_note": material_note,
        "investment_thesis": investment_thesis[:4],
        "bull_case": bull_case[:2],
        "bear_case": bear_case[:2],
        # Legacy compatibility
        "summary_text": company_profile,
        "company_bullets": investment_thesis[:3],
        "outlook_summary": business_performance,
        "major_shareholders": [],
        "cross_holdings": [],
        "revenue_mix": [],
        "peers": [],
        "corporate_info": {"president": "—", "employees": "—", "head_office": "—"},
        "ownership_mix": {"foreign": None, "institutional": None, "corporate": None, "individual": None},
        "disclosures": [],
        "tags": [],
    }


def generate_dashboard_narrative(payload: Dict, on_progress=None, on_event=None) -> Dict[str, Any]:
    if on_progress:
        on_progress(80, "Drafting", "Generating dashboard narrative")

    # ── SPEED: Cache narrative output (24h TTL) ───────────────────
    # The narrative LLM call is the single most expensive operation (~15-25s).
    # Cache it keyed on stock_code + mode + financial data hash so repeat
    # reports for the same company skip the LLM call entirely.
    import hashlib
    _narr_cache_key = None
    try:
        _code = payload.get("stock_code", "")
        _mode = payload.get("report_mode", "full")
        _facts = payload.get("facts_summary", "")[:2000]
        _hash = hashlib.md5(f"{_code}_{_mode}_{_facts}".encode()).hexdigest()[:12]
        _narr_cache_key = f"narrative_{_code}_{_mode}_{_hash}.json"
        _narr_cache_path = Path(settings.output_dir) / "cache" / _narr_cache_key
        cached_narrative = load_cache(_narr_cache_path, max_age_seconds=24 * 3600)
        if cached_narrative and _is_narrative_valid(cached_narrative):
            if on_progress:
                on_progress(88, "Drafting", "Loaded narrative from cache")
            if on_event:
                on_event("draft_reset", "Draft start (cached)", {"step": "Drafting"})
            return _sanitize_narrative(cached_narrative)
    except Exception:
        pass

    llm = LlmClient()

    # --- Attempt 1: streaming (for live UI feedback) ---
    narrative = {}
    raw = ""
    try:
        buffer_text = ""
        last_flush = time.monotonic()

        def handle_chunk(delta: str) -> None:
            nonlocal buffer_text, last_flush
            buffer_text += delta
            now = time.monotonic()
            if len(buffer_text) >= 240 or (now - last_flush) >= 0.8:
                if on_event:
                    on_event("draft", "Draft chunk", {"chunk": buffer_text})
                buffer_text = ""
                last_flush = now

        if on_event:
            on_event("draft_reset", "Draft start", {"step": "Drafting"})
            on_event("draft", "Draft chunk", {"chunk": "Drafting report…\n"})
            raw = llm.generate_dashboard_narrative(payload, on_progress=on_progress, on_stream=handle_chunk)
            if buffer_text:
                on_event("draft", "Draft chunk", {"chunk": buffer_text})
        else:
            raw = llm.generate_dashboard_narrative(payload, on_progress=on_progress)
        narrative = _safe_parse_json(raw)
    except Exception:
        narrative = {}

    # --- Attempt 2: non-streaming retry if narrative is incomplete ---
    if not _is_narrative_valid(narrative):
        if on_event:
            on_event("warning", "Narrative incomplete — retrying without streaming")
        try:
            raw = llm.generate_dashboard_narrative(payload, on_progress=on_progress, on_stream=None)
            narrative = _safe_parse_json(raw)
        except Exception:
            pass

    # --- Fallback: data-driven narrative from financial data ---
    if not _is_narrative_valid(narrative):
        if on_event:
            on_event("warning", "LLM narrative unavailable — using data-driven fallback")
        fallback = _build_fallback_narrative(payload)
        for key, value in fallback.items():
            if not narrative.get(key):
                narrative[key] = value
    # Only translate specific fields that might contain Japanese (shareholder names,
    # corporate info, etc.).  Do NOT re-translate summary_text, outlook_summary,
    # bull_case, or bear_case — the main LLM prompt already writes these in English
    # and re-translating destroys analytical content.
    if isinstance(narrative, dict):
        translate_fields = {}
        for key in ("major_shareholders", "cross_holdings", "corporate_info", "revenue_mix", "peers"):
            val = narrative.get(key)
            if val and _contains_japanese_in_json(val):
                translate_fields[key] = val
        if translate_fields:
            try:
                translated_raw = llm.translate_json_to_english(_safe_json(translate_fields))
                translated = _safe_parse_json(translated_raw)
                if translated:
                    for key, val in translated.items():
                        narrative[key] = val
            except Exception:
                pass
    # Merge EDINET ownership / governance insights when missing
    if isinstance(narrative, dict):
        edinet_insights = payload.get("edinet_insights") if isinstance(payload, dict) else {}
        gov = edinet_insights.get("governance") if isinstance(edinet_insights, dict) else {}
        if gov:
            corp = narrative.get("corporate_info") or {}
            # Only fill in missing fields — don't overwrite existing values with "—"
            board_val = gov.get("board") or ""
            narrative["corporate_info"] = {
                "president": corp.get("president") or (board_val if board_val and board_val != "—" else "") or "—",
                "employees": corp.get("employees") or "—",
                "head_office": corp.get("head_office") or "—",
            }
        if not narrative.get("ownership_mix") and isinstance(edinet_insights, dict):
            narrative["ownership_mix"] = payload.get("ownership_mix") or {}

    # Save to cache for future runs
    if _narr_cache_key and _is_narrative_valid(narrative):
        try:
            save_cache(Path(settings.output_dir) / "cache" / _narr_cache_key, narrative)
        except Exception:
            pass

    return _sanitize_narrative(narrative)


def render_report_html(markdown_text: str, payload: Dict) -> str:
    html_body = markdown.markdown(markdown_text, extensions=["tables", "fenced_code"])
    return html_body


def _safe_parse_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except Exception:
        pass
    # try to extract first json object
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            subset = text[start:end + 1]
            try:
                return json.loads(subset)
            except Exception:
                pass
            # Fix trailing commas (common LLM issue): ,] -> ] and ,} -> }
            fixed = re.sub(r",\s*([}\]])", r"\1", subset)
            return json.loads(fixed)
    except Exception:
        return {}
    return {}


def _safe_parse_json_array(text: str) -> List[Dict]:
    """Like _safe_parse_json but returns a list of dicts."""
    if not text:
        return []
    # Strip code fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
    except Exception:
        pass
    # Try to extract first JSON array
    try:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            subset = cleaned[start:end + 1]
            try:
                result = json.loads(subset)
                if isinstance(result, list):
                    return result
            except Exception:
                pass
            fixed = re.sub(r",\s*([}\]])", r"\1", subset)
            result = json.loads(fixed)
            if isinstance(result, list):
                return result
    except Exception:
        pass
    return []


def _clean_corporate_field(value: str, field: str) -> str:
    """Post-process a corporate info field to remove noise.

    The LLM translation sometimes crams the entire corporate profile into
    a single field (e.g. president = "Ryohei Oka Founded March 21st 1946
    Established July 1st 1996 Authorized Capital...").  This strips
    everything after the first extraneous keyword.
    """
    if not value or value == "—":
        return "—"

    if field == "president":
        # Truncate at first non-name keyword
        _CUT_PATTERNS = [
            r'(?:^|\s+)Founded\b', r'(?:^|\s+)Established\b', r'(?:^|\s+)Authorized\b',
            r'\s+Capital\b', r'\s+Shares?\s+Issued', r'\s+Paid-up\b',
            r'\s+Fiscal\s+Year', r'\s+Employees?\b', r'\s+Head\s+Office\b',
            r'設立', r'資本金', r'従業員', r'本社',
            r'\d{4}年', r'\s+\(Born\b',
        ]
        for pat in _CUT_PATTERNS:
            m = re.search(pat, value, re.IGNORECASE)
            if m:
                value = value[:m.start()].strip().rstrip(",;.、。")
                break
        # If still too long (>60 chars), likely noisy — take first sentence
        if len(value) > 60:
            value = re.split(r'[,;.\n]', value)[0].strip()
        # If empty or obviously not a name, mark invalid
        if not value or len(value) < 2:
            value = ""

    elif field == "employees":
        # Normalize: extract the main number, keep "consolidated" note
        m = re.match(r'([\d,，]+)\s*(?:人|名)?(?:\s*[\(（].*?[\)）])?\s*(?:[\(（]\s*(?:consolidated|連結)[:\s：]?\s*([\d,，]+).*?[\)）])?', value)
        if m:
            main = m.group(1).replace("，", ",")
            consolidated = m.group(2)
            if consolidated:
                value = f"{main} (consolidated: {consolidated.replace('，', ',')})"
            else:
                value = main

    elif field == "head_office":
        # Remove trailing noise like "TEL:", phone numbers, URLs
        value = re.split(r'\s*(?:TEL|FAX|Tel|Fax|電話|URL|http)', value)[0].strip()
        # Cap length
        if len(value) > 80:
            value = value[:80].rsplit(",", 1)[0].strip()

    elif field == "founded":
        # Strip trailing noise (addresses, phone numbers, etc.)
        value = re.split(r'\s*(?:TEL|FAX|Tel|Fax|電話|URL|http|本社|Head)', value)[0].strip()
        if len(value) > 60:
            value = value[:60].rsplit(" ", 1)[0].strip()

    return value.strip() or "—"


def _build_corporate_info_final(
    corporate_info: Dict[str, str],
    profile: Dict[str, str],
    payload: Dict,
) -> Dict[str, str]:
    """Build corporate info with multi-layer fallback + cleaning.

    Priority order for each field:
    1. LLM narrative corporate_info (from generate_dashboard_narrative)
    2. Profile extraction from research pages
    3. Yahoo Finance Japan scrape (most reliable public source)
    4. Kabutan.jp direct scrape
    5. "—" placeholder

    Every value is post-processed by _clean_corporate_field to strip noise.
    """
    yahoo = payload.get("yahoo_corporate") or {}
    kabutan = payload.get("kabutan_corporate") or {}

    def _pick(field: str, profile_field: str) -> str:
        # Layer 1: LLM narrative
        val = corporate_info.get(field)
        if val and val != "—":
            translated = _translate_short_text(val) or val
            cleaned = _clean_corporate_field(translated, field)
            if cleaned and cleaned != "—":
                return cleaned
        # Layer 2: Profile regex extraction
        val = profile.get(profile_field)
        if val and val != "—":
            translated = _translate_short_text(val) or val
            cleaned = _clean_corporate_field(translated, field)
            if cleaned and cleaned != "—":
                return cleaned
        # Layer 3: Yahoo Finance Japan (most reliable)
        val = yahoo.get(field)
        if val and val != "—":
            translated = _translate_short_text(val) or val
            cleaned = _clean_corporate_field(translated, field)
            if cleaned and cleaned != "—":
                return cleaned
        # Layer 4: Kabutan scrape
        val = kabutan.get(field)
        if val and val != "—":
            translated = _translate_short_text(val) or val
            cleaned = _clean_corporate_field(translated, field)
            if cleaned and cleaned != "—":
                return cleaned
        return "—"

    # Pick "founded" from scraped sources (not typically in LLM narrative)
    founded = "—"
    for src in [kabutan, yahoo, profile]:
        val = src.get("founded")
        if val and val != "—":
            translated = _translate_short_text(val) or val
            cleaned = _clean_corporate_field(translated, "founded")
            if cleaned and cleaned != "—":
                founded = cleaned
                break
    # Also try extracting from messy president field (common LLM artifact)
    # Check the already-picked president value — it was already translated by _pick()
    if founded == "—":
        # Use raw value from first available source (avoid double LLM call)
        raw_pres = corporate_info.get("president") or profile.get("representative") or ""
        # If it's already English, search directly; if Japanese, skip (founded is in English)
        if not _contains_japanese(raw_pres):
            m = re.search(r'Founded\s+(.+?)(?:\s+Established|\s+Authorized|\s+Capital|\s+Shares|\s*$)', raw_pres, re.IGNORECASE)
            if m:
                founded = m.group(1).strip().rstrip(",;.")

    return {
        "president": _pick("president", "representative"),
        "founded": founded,
        "employees": _pick("employees", "employees"),
        "head_office": _pick("head_office", "head_office"),
    }


def build_dashboard_context(payload: Dict, narrative: Dict[str, Any]) -> Dict[str, Any]:
    resolved_company_name = payload.get("company_name")
    is_etf = payload.get("is_etf", False)
    fund_type = payload.get("fund_type")
    metrics = payload.get("metrics", {})
    financials = metrics.get("financials", {})
    prices = metrics.get("prices", {})
    financials_raw = payload.get("financials_raw") or {}
    prices_raw_payload = payload.get("prices_raw") or {}
    valuation = payload.get("valuation_data", {}) or {}
    profile = payload.get("profile_data", {}) or {}
    listed_info = payload.get("listed_info", {}) or {}
    company_info = metrics.get("company", {})
    edinet_insights = payload.get("edinet_insights", {}) or {}
    edinet_summary = payload.get("edinet_summary", "") or ""
    research_context = payload.get("research_context", "") or ""

    code = payload.get("stock_code")
    
    # Determine name_jp and name_en, prioritizing known maps
    name_jp_from_map = KNOWN_CODE_NAME_JP.get(code)
    name_en_from_map = KNOWN_CODE_NAME_EN.get(code)

    if name_jp_from_map:
        name_jp = name_jp_from_map
    else:
        # Try J-Quants listed_info — field is "CoName" (abbreviated) or "CompanyName"
        _li_name = listed_info.get("CoName") or listed_info.get("CompanyName") or ""
        if _li_name and _contains_japanese(_li_name):
            name_jp = _li_name
        else:
            # Fallback: prefer Japanese name from profile, or EDINET filer_name
            name_jp = _prefer_japanese_name(
                profile.get("company_name") or _li_name or payload.get("company_name")
            )
        # Also try EDINET filer_name which is usually in Japanese
        edinet_filer = (payload.get("edinet_financials") or {}).get("filer_name")
        if edinet_filer and _contains_japanese(edinet_filer):
            name_jp = edinet_filer
        # If name_jp is missing or has no Japanese, try get_listed_info CoName from J-Quants
        if not name_jp or not _contains_japanese(name_jp):
            try:
                from app.services.jquants import JQuantsClient
                _jq = JQuantsClient()
                _li_fallback = _jq.get_listed_info(code)
                _co_name = (_li_fallback or {}).get("CoName") or ""
                if _co_name and _contains_japanese(_co_name):
                    name_jp = _co_name
            except Exception:
                pass
        # Keep Japanese name as-is — do NOT translate it

    if name_en_from_map:
        name_en = name_en_from_map
    else:
        # Fallback: prefer explicit English name fields
        # J-Quants uses "CoNameEn" (abbreviated) or "CompanyNameEnglish"
        name_en = profile.get("company_name_en") or listed_info.get("CoNameEn") or listed_info.get("CompanyNameEnglish")
        # If name_en is empty, translate name_jp to English as fallback
        if not name_en and name_jp and _contains_japanese(name_jp):
            name_en = _translate_short_text(name_jp) or name_jp
        # If name_en still contains Japanese, translate it
        if name_en and _contains_japanese(name_en):
            name_en = _translate_short_text(name_en) or name_en
        # If name_en is still empty, use the resolved company name or name_jp
        if not name_en:
            name_en = payload.get("company_name") or name_jp

    # Ensure resolved_company_name is consistent with the primary Japanese name
    metrics["company"]["name"] = name_jp # Use the determined Japanese name for primary company name in metrics

    rows = financials.get("rows", [])
    print(f"[DASH DEBUG] financials keys: {list(financials.keys())[:10]}, rows count: {len(rows)}")
    if rows:
        r0 = rows[0]
        _dash_filled = [k for k,v in r0.items() if v is not None and k not in ('period','period_type','fy_end')]
        _dash_empty = [k for k,v in r0.items() if v is None and k not in ('period','period_type','fy_end')]
        print(f"[DASH DEBUG] row[0] filled: {_dash_filled}")
        print(f"[DASH DEBUG] row[0] empty:  {_dash_empty}")
    else:
        print("[DASH DEBUG] WARNING: NO ROWS in financials!")
        print(f"[DASH DEBUG] metrics keys: {list(metrics.keys())}")
        print(f"[DASH DEBUG] financials type: {type(financials)}, content preview: {str(financials)[:200]}")
    rows_sorted = sorted(rows, key=lambda r: _parse_date(r.get("period")) or dt.date.min)
    # Pick the most recent row that actually has financial data.
    # The newest row can be a forecast period (e.g., FY end not yet reported)
    # with no actual BS/PL data — skip it for the main display.
    _DATA_KEYS = ("equity", "total_assets", "revenue", "net_income", "operating_profit")
    def _has_data(r):
        return any(r.get(k) is not None for k in _DATA_KEYS)
    latest = {}
    prev = {}
    for r in reversed(rows_sorted):
        if _has_data(r):
            if not latest:
                latest = r
            elif not prev:
                prev = r
                break
    if not latest and rows_sorted:
        latest = rows_sorted[-1]
    if not prev and len(rows_sorted) >= 2:
        prev = rows_sorted[-2]

    # Capital allocation & risk computations
    capital_allocation = _compute_capital_allocation(rows_sorted, periods=3)
    computed_risks = _compute_risk_metrics(rows_sorted)
    llm_risk_factors: List[Dict[str, Any]] = []
    if isinstance(edinet_insights, dict):
        for rf in (edinet_insights.get("risk_factors") or [])[:5]:
            if isinstance(rf, str) and rf.strip() and rf.strip() != "—":
                llm_risk_factors.append({"metric": "Disclosed Risk", "value": "—", "assessment": "moderate", "detail": rf})
    risk_dashboard = computed_risks + llm_risk_factors
    capital_projects = payload.get("capital_projects") or []
    esg_data = payload.get("esg_data") or {}

    # Core financial values
    equity = latest.get("equity")
    total_assets = latest.get("total_assets")
    net_income = latest.get("net_income")
    revenue = latest.get("revenue")
    eps = latest.get("eps")
    dps = latest.get("dps")
    roe = latest.get("roe")
    equity_ratio = _safe_ratio(equity, total_assets)

    price_rows = _extract_price_rows(prices_raw_payload or payload.get("prices") or {})
    avg_volume = _avg_volume(price_rows)
    price_kpis = prices or {}
    last_price = valuation.get("last_price") or price_kpis.get("latest_close")
    shares = valuation.get("shares")
    market_cap = valuation.get("market_cap")

    # Try to fill shares from EDINET/research text when missing
    if shares is None:
        shares = _extract_shares_from_text(payload.get("edinet_narrative") or "")
    if shares is None:
        shares = _extract_shares_from_text(payload.get("edinet_summary") or "")
    if shares is None:
        shares = _extract_shares_from_text(research_context or "")
    # Infer shares from net income and EPS if still missing (EPS is per share)
    if shares is None and net_income and eps:
        try:
            shares = net_income / eps
        except Exception:
            pass

    if market_cap is None and last_price and shares:
        market_cap = last_price * shares

    bps = None
    if equity and shares:
        bps = equity / shares

    per = None
    if eps and last_price:
        per = last_price / eps
    elif net_income and market_cap:
        per = market_cap / net_income

    pbr = None
    if bps and last_price:
        pbr = last_price / bps
    elif equity and market_cap:
        pbr = market_cap / equity

    div_yield = None
    if dps and last_price:
        div_yield = dps / last_price

    # Prefer clean v2 snapshot when raw J-Quants data available
    clean_kpi = _compute_clean_kpi(financials_raw, prices_raw_payload)
    split_multiplier = 1.0
    if clean_kpi:
        kpi = clean_kpi
        split_multiplier = clean_kpi.get("split_multiplier", 1.0) or 1.0
    else:
        # Compute EV/EBITDA for fallback path
        _fallback_ev_ebitda = None
        _op = latest.get("operating_profit")
        if _op and _op > 0 and market_cap is not None:
            _borrowings = latest.get("borrowings") or 0
            _cash = latest.get("cash_equiv") or 0
            _ev = market_cap + (_borrowings - _cash)
            _fallback_ev_ebitda = _ev / _op
        kpi = {
            "price": last_price,
            "market_cap_raw": market_cap,
            "pbr": pbr,
            "pb_value": pbr,
            "per": per,
            "roe": roe,
            "div_yield": div_yield,
            "bps": bps,
            "equity_ratio": equity_ratio,
            "ebit_pct": None,
            "ocf_pct": None,
            "ev_ebitda": _fallback_ev_ebitda,
            "market_cap_display": None,
        }
        if market_cap is not None:
            if market_cap < 1_000_000_000_000:
                kpi["market_cap_display"] = f"¥{market_cap/1_000_000_000:.1f}B"
                kpi["market_cap"] = market_cap / 1_000_000_000  # numeric in billions
            else:
                kpi["market_cap_display"] = f"¥{market_cap/1_000_000_000_000:.2f}T"
                kpi["market_cap"] = market_cap / 1_000_000_000_000  # numeric in trillions

    # Ensure avg_volume is in kpi
    if avg_volume:
        kpi["avg_volume"] = avg_volume

    # Add price_date and per-share metrics for sidebar
    kpi["price_date"] = price_kpis.get("latest_date")
    if eps is not None:
        kpi.setdefault("eps", eps)
    if dps is not None:
        kpi.setdefault("dps", dps)

    # ETF-specific: add returns data to KPI for template use
    if is_etf:
        returns = price_kpis.get("returns", {})
        kpi["return_1y"] = returns.get("12m")
        kpi["return_6m"] = returns.get("6m")
        kpi["return_3m"] = returns.get("3m")
        kpi["return_1m"] = returns.get("1m")

    # Clean 5-year history (FY & 2Q) for charts
    clean_history = _build_clean_history(financials_raw, split_multiplier)

    def _series_from_history(hist: List[Dict[str, Any]], key: str, scale: float = 1.0) -> List[Dict[str, Any]]:
        series = []
        for item in list(reversed(hist[:5])):
            val = item.get(key)
            if val is not None:
                val = val / scale
            series.append({"label": item.get("label"), "value": val})
        return series

    if clean_history:
        roe_series = _normalize_series(_series_from_history(clean_history, "roe_ratio", scale=1.0))
        ocf_series = _normalize_series(_series_from_history(clean_history, "ocf_bil", scale=1.0))
        dps_series = _normalize_series(_series_from_history(clean_history, "dps", scale=1.0))
    else:
        roe_series = _normalize_series(_series_from_rows(rows_sorted, "roe", count=5, scale=1.0))
        ocf_series = _normalize_series(_series_from_rows(rows_sorted, "cfo", count=5, scale=1_000_000_000))
        dps_series = _normalize_series(_series_from_rows(rows_sorted, "dps", count=5, scale=1.0))

    peers = narrative.get("peers") or []

    # ── Major Shareholders: multi-source pipeline ──
    # Priority order:
    #   1. Kabutan direct scrape (concurrent, already fetched)
    #   2. EDINET annual report table (most authoritative)
    #   3. Web fetch via SerpAPI + LLM
    #   4. Regex extraction from EDINET narrative text
    #   5. LLM-generated narrative data
    major_shareholders: List[Dict[str, Any]] = []

    def _format_shareholder(name: str, pct: float, change: str = "—") -> Dict[str, Any]:
        return {"name": name, "pct": pct, "change": change}

    # Layer 1: Kabutan direct scrape (already fetched in Phase C)
    kabutan_sh = payload.get("kabutan_shareholders") or []
    if kabutan_sh and len(kabutan_sh) >= 3:
        candidates = [
            _format_shareholder(s.get("name", "—"), s.get("pct", 0))
            for s in kabutan_sh if s.get("pct") is not None and s.get("pct") > 0
        ]
        if len(candidates) >= 3:
            major_shareholders = candidates

    # Layer 2: EDINET annual report shareholder table
    if not major_shareholders or len(major_shareholders) < 3:
        try:
            edinet_sh = _fetch_shareholders_edinet(payload.get("edinet_docs") or [])
            if edinet_sh and len(edinet_sh) >= 3:
                candidates = [
                    _format_shareholder(
                        s.get("name", "—"),
                        s.get("pct", 0),
                    )
                    for s in edinet_sh if s.get("pct") is not None and s.get("pct") > 0
                ]
                if len(candidates) >= 3:
                    major_shareholders = candidates
        except Exception:
            pass

    # Layer 3: Web fetch via SerpAPI + LLM (existing function)
    if not major_shareholders or len(major_shareholders) < 3:
        try:
            web_data = _fetch_major_shareholders_web(code, name_jp)
            if web_data and web_data.get("shareholders"):
                candidates = [
                    _format_shareholder(
                        s.get("name_en") or s.get("name_jp") or "—",
                        _to_float_safe(s.get("pct")) or 0,
                        s.get("change") or "—",
                    )
                    for s in web_data["shareholders"]
                    if _to_float_safe(s.get("pct")) is not None and _to_float_safe(s.get("pct")) > 0
                ]
                if len(candidates) >= 3:
                    major_shareholders = candidates
        except Exception:
            pass

    # Layer 4: Regex extraction from EDINET narrative text
    if not major_shareholders or len(major_shareholders) < 3:
        extracted = _extract_major_shareholders(payload.get("edinet_narrative") or "")
        if extracted and len(extracted) >= 3:
            candidates = [
                _format_shareholder(m["name"], m["pct"])
                for m in extracted if m.get("pct") is not None and m.get("pct") > 0
            ]
            if len(candidates) >= 3:
                major_shareholders = candidates

    # Layer 5: LLM narrative data (lowest priority)
    if not major_shareholders or len(major_shareholders) < 3:
        llm_shareholders = narrative.get("major_shareholders") or []
        if llm_shareholders:
            major_shareholders = [
                _format_shareholder(
                    s.get("name") or s.get("name_en") or "—",
                    _to_float_safe(s.get("pct")) or 0,
                    s.get("change") or "—",
                )
                for s in llm_shareholders
                if _to_float_safe(s.get("pct")) is not None and _to_float_safe(s.get("pct")) > 0
            ]

    # Sanitize: drop self-referential holders (>= 95%), limit to 10 entries
    company_name_check = payload.get("company_name") or ""
    major_shareholders = [
        mh for mh in major_shareholders
        if not (
            isinstance(mh.get("pct"), (int, float))
            and mh["pct"] >= 95
            and isinstance(mh.get("name"), str)
            and company_name_check
            and company_name_check in mh["name"]
        )
    ][:10]

    # --- Translate Japanese shareholder names + classify type ---
    _SHAREHOLDER_TYPE_BADGES = {
        "Institution": {"label": "INST", "color": "#2E59A7"},
        "Fund":        {"label": "FUND", "color": "#7C3AED"},
        "Person":      {"label": "INDV", "color": "#059669"},
        "Corporate":   {"label": "CORP", "color": "#D97706"},
        "Government":  {"label": "GOV",  "color": "#DC2626"},
        "Treasury":    {"label": "TRES", "color": "#6B7280"},
    }
    try:
        has_jp = any(_contains_japanese(mh.get("name", "")) for mh in major_shareholders)
        if has_jp and major_shareholders:
            names_for_llm = json.dumps(
                [{"original": mh.get("name", "")} for mh in major_shareholders],
                ensure_ascii=False,
            )
            llm_client = LlmClient()
            translated_raw = llm_client.translate_and_classify_shareholders(names_for_llm)
            translated_list = _safe_parse_json_array(translated_raw)
            lookup = {}
            for item in translated_list:
                orig = item.get("original", "")
                if orig:
                    lookup[orig] = {
                        "english": item.get("english", orig),
                        "type": item.get("type", "Corporate"),
                    }
            for mh in major_shareholders:
                orig_name = mh.get("name", "")
                match = lookup.get(orig_name)
                if match:
                    mh["name_jp"] = orig_name
                    mh["name"] = match["english"]
                    sh_type = match["type"]
                    mh["type"] = sh_type
                    mh["type_badge"] = _SHAREHOLDER_TYPE_BADGES.get(
                        sh_type, {"label": sh_type[:4].upper(), "color": "#6B7280"}
                    )
    except Exception:
        pass  # Graceful fallback — keep original names

    # --- Layered ownership mix pipeline (with validation) ---

    def _ownership_total(mix):
        return sum(v for v in mix.values() if v is not None and v > 0)

    def _is_plausible(mix):
        """Reject implausible ownership mixes."""
        if not mix:
            return False
        total = _ownership_total(mix)
        if total < 3:
            return False
        # Total should not vastly exceed 100% (allow small rounding errors)
        if total > 110:
            return False
        non_none = {k: v for k, v in mix.items() if v is not None and v > 0}
        # Any single category > 95% is essentially impossible for TSE stocks
        if any(v > 95 for v in non_none.values()):
            return False
        return True

    def _normalize_ownership(mix):
        """Merge 6-key format to 4-key: securities_firms→institutional, government→corporate."""
        if not mix:
            return {"foreign": None, "institutional": None, "corporate": None, "individual": None}
        inst_raw = mix.get("institutional")
        sec_raw = mix.get("securities_firms")
        corp_raw = mix.get("corporate")
        gov_raw = mix.get("government")
        # Sum sub-categories; preserve None distinction (None+None=None, 0+0=0)
        inst_parts = [v for v in (inst_raw, sec_raw) if v is not None]
        inst = round(sum(inst_parts), 2) if inst_parts else None
        corp_parts = [v for v in (corp_raw, gov_raw) if v is not None]
        corp = round(sum(corp_parts), 2) if corp_parts else None
        return {
            "foreign": mix.get("foreign"),
            "institutional": inst,
            "corporate": corp,
            "individual": mix.get("individual"),
        }

    ownership_mix: Dict[str, float | None] = {}

    # Layer 0: Kabutan web scraper (high reliability)
    kabutan_mix = payload.get("kabutan_ownership") or {}
    if kabutan_mix:
        norm = _normalize_ownership(kabutan_mix)
        if _is_plausible(norm) and _ownership_total(norm) > 50:
            ownership_mix = norm

    # Layer 1a: EDINET HTML table
    if _ownership_total(ownership_mix) < 50:
        edinet_docs = payload.get("edinet_docs") or []
        for doc in edinet_docs:
            if doc.get("doc_type_code") in ("120", "130", "140"):
                try:
                    from app.services.edinet import EdinetClient
                    raw = EdinetClient().extract_ownership_table(doc.get("doc_id", ""))
                    if raw:
                        norm = _normalize_ownership(raw)
                        if _is_plausible(norm) and _ownership_total(norm) > _ownership_total(ownership_mix):
                            ownership_mix = norm
                            break
                except Exception:
                    pass

    # Layer 1b: EDINET XBRL facts
    if _ownership_total(ownership_mix) < 50:
        edinet_docs = payload.get("edinet_docs") or []
        for doc in edinet_docs:
            if doc.get("doc_type_code") in ("120", "130", "140"):
                try:
                    from app.services.edinet import EdinetClient
                    raw = EdinetClient().extract_ownership_xbrl(doc.get("doc_id", ""))
                    if raw:
                        norm = _normalize_ownership(raw)
                        if _is_plausible(norm) and _ownership_total(norm) > _ownership_total(ownership_mix):
                            ownership_mix = norm
                            break
                except Exception:
                    pass

    # Layer 2: Classify from major shareholders (medium reliability)
    if _ownership_total(ownership_mix) < 30 and major_shareholders:
        classified = _classify_shareholders_to_ownership(major_shareholders)
        if classified and _is_plausible(classified) and _ownership_total(classified) > _ownership_total(ownership_mix):
            ownership_mix = classified

    # Layer 3: LLM narrative extraction (low reliability)
    if _ownership_total(ownership_mix) < 30:
        llm_mix = narrative.get("ownership_mix") or {}
        llm_parsed = {
            "foreign": _coerce_percent_value(llm_mix.get("foreign")),
            "institutional": _coerce_percent_value(llm_mix.get("institutional")),
            "corporate": _coerce_percent_value(llm_mix.get("corporate")),
            "individual": _coerce_percent_value(llm_mix.get("individual")),
        }
        if _is_plausible(llm_parsed) and _ownership_total(llm_parsed) > _ownership_total(ownership_mix):
            ownership_mix = llm_parsed

    # Layer 4: Direct text regex (low reliability)
    if _ownership_total(ownership_mix) < 30 and payload.get("edinet_narrative"):
        text_mix = _normalize_ownership(_extract_ownership_from_text(payload["edinet_narrative"]))
        if _is_plausible(text_mix) and _ownership_total(text_mix) > _ownership_total(ownership_mix):
            ownership_mix = text_mix

    # Post-pipeline: estimate individual remainder only when not already source-provided
    total = _ownership_total(ownership_mix)
    individual_current = ownership_mix.get("individual")
    if 15 < total < 90 and (individual_current is None or individual_current == 0):
        estimated_individual = min(100 - total, 55)
        ownership_mix["individual"] = round(estimated_individual, 1)

    # Final gate: if result still fails plausibility, return all-None
    if not _is_plausible(ownership_mix):
        ownership_mix = {"foreign": None, "institutional": None, "corporate": None, "individual": None}

    # Ensure all keys exist with consistent shape
    ownership_mix = {
        "foreign": ownership_mix.get("foreign"),
        "institutional": ownership_mix.get("institutional"),
        "corporate": ownership_mix.get("corporate"),
        "individual": ownership_mix.get("individual"),
    }

    def _to_millions(v):
        """Convert raw yen to millions for income statement display (¥MN)."""
        if v is None:
            return None
        return round(v / 1_000_000, 0)

    income_statement = []
    for row in rows_sorted[-6:]:
        income_statement.append({
            "period": _format_period_label(row.get("period")),
            "sales": _to_millions(row.get("revenue")),
            "op_profit": _to_millions(row.get("operating_profit")),
            "ord_profit": _to_millions(row.get("ordinary_profit")),
            "net_income": _to_millions(row.get("net_income")),
            "eps": row.get("eps"),
            "dps": row.get("dps"),
        })

    cross_holdings = narrative.get("cross_holdings") or []
    if isinstance(cross_holdings, list):
        cross_holdings = [
            {
                "name": item.get("name") if isinstance(item, dict) else "—",
                "ticker": item.get("ticker") if isinstance(item, dict) else "—",
                "pct_held": _coerce_percent_value(item.get("pct_held")) if isinstance(item, dict) else None,
            }
            for item in cross_holdings
        ]

    # ── Revenue mix: 6-stage fallback pipeline ──
    # Stage 0 = EDINET HTML/XBRL parsed segments (highest accuracy)
    revenue_mix = []

    def _truncate_name(name, max_len=40):
        if not isinstance(name, str):
            return "—"
        name = name.strip()
        return name[:max_len] if len(name) > max_len else name

    def _has_valid_pcts(items):
        return (isinstance(items, list) and items
                and any(isinstance(it, dict) and it.get("pct") not in (None, 0) for it in items))

    def _compute_pcts_from_revenue(items):
        """If items have revenue_mm but no pct, compute pct = revenue_mm / total × 100."""
        if not isinstance(items, list):
            return items
        revenues = [it.get("revenue_mm") for it in items if isinstance(it, dict) and it.get("revenue_mm")]
        if not revenues or len(revenues) != len([it for it in items if isinstance(it, dict)]):
            return items
        total = sum(r for r in revenues if r)
        if total <= 0:
            return items
        return [
            {**it, "pct": round(it["revenue_mm"] / total * 100, 1)} if isinstance(it, dict) and it.get("revenue_mm") else it
            for it in items
        ]

    # Stage 0: EDINET HTML/XBRL parsed segments — highest accuracy (direct from filing)
    edinet_parsed_segments = payload.get("edinet_segments") or []
    if isinstance(edinet_parsed_segments, list) and len(edinet_parsed_segments) >= 2:
        revenue_mix = [
            {
                "segment": _truncate_name(s.get("segment")),
                "pct": s.get("pct"),
                "revenue_mm": s.get("revenue_mm"),
            }
            for s in edinet_parsed_segments
            if isinstance(s, dict) and s.get("segment")
        ]

    # Stage 1: LLM narrative revenue_mix — normalize and truncate
    if not _has_valid_pcts(revenue_mix):
        llm_mix = narrative.get("revenue_mix") or []
        if isinstance(llm_mix, list) and llm_mix:
            # Cross-validate LLM output against EDINET if available
            llm_revenue_mix = [
                {
                    "segment": _truncate_name(item.get("segment")),
                    "pct": _coerce_percent_value(item.get("pct")) if isinstance(item, dict) else None,
                    "revenue_mm": _to_float(item.get("revenue_mm")) if isinstance(item, dict) else None,
                }
                for item in llm_mix
                if isinstance(item, dict)
            ]
            # If Stage 0 produced results but without valid pcts, prefer Stage 0 revenue_mm
            if revenue_mix and not _has_valid_pcts(revenue_mix) and _has_valid_pcts(llm_revenue_mix):
                revenue_mix = llm_revenue_mix
            elif not revenue_mix:
                revenue_mix = llm_revenue_mix

    # Stage 2: Compute from revenue_mm if all pcts are None
    if revenue_mix and not _has_valid_pcts(revenue_mix):
        revenue_mix = _compute_pcts_from_revenue(revenue_mix)

    # Stage 3: Segment candidates from regex extraction
    if not _has_valid_pcts(revenue_mix):
        seg_candidates = payload.get("segment_candidates") or []
        if isinstance(seg_candidates, list) and seg_candidates:
            total_rev = sum(s.get("revenue", 0) for s in seg_candidates if isinstance(s, dict) and s.get("revenue"))
            if total_rev > 0:
                revenue_mix = [
                    {
                        "segment": _truncate_name(s.get("name", "—")),
                        "pct": round(s["revenue"] / total_rev * 100, 1),
                        "revenue_mm": s.get("revenue"),
                    }
                    for s in seg_candidates
                    if isinstance(s, dict) and s.get("revenue")
                ]
            elif not revenue_mix:
                revenue_mix = [
                    {"segment": _truncate_name(s.get("name", "—")), "pct": None, "revenue_mm": s.get("revenue")}
                    for s in seg_candidates if isinstance(s, dict)
                ]

    # Stage 4: EDINET insights business_segments (handle both old string and new dict format)
    if not _has_valid_pcts(revenue_mix) and isinstance(edinet_insights, dict):
        segments = edinet_insights.get("business_segments")
        if isinstance(segments, list) and segments:
            edinet_mix = []
            for s in segments:
                if isinstance(s, dict):
                    edinet_mix.append({
                        "segment": _truncate_name(s.get("name", "—")),
                        "pct": _coerce_percent_value(s.get("pct")),
                        "revenue_mm": _to_float(s.get("revenue_mm")),
                    })
                elif isinstance(s, str) and s:
                    edinet_mix.append({"segment": _truncate_name(s), "pct": None, "revenue_mm": None})
            if edinet_mix:
                # Try to compute pcts from revenue_mm if available
                edinet_mix = _compute_pcts_from_revenue(edinet_mix)
                revenue_mix = edinet_mix

    # Stage 4.5: Web scraping fallback (only if all other sources failed)
    if not _has_valid_pcts(revenue_mix):
        try:
            web_segments = _fetch_segment_data_web(code)
            if web_segments:
                revenue_mix = web_segments
        except Exception:
            pass

    # Stage 5: Truncate & clean — ensure all segment names ≤ 40 chars
    if isinstance(revenue_mix, list):
        revenue_mix = [
            {
                "segment": _truncate_name(it.get("segment") if isinstance(it, dict) else "—"),
                "pct": it.get("pct") if isinstance(it, dict) else None,
                "revenue_mm": it.get("revenue_mm") if isinstance(it, dict) else None,
            }
            for it in revenue_mix
        ]

    # ── Peer Benchmarking: use real data from _fetch_peer_benchmarking ──
    real_peer_data = payload.get("peer_benchmarking") or {}
    real_peers = real_peer_data.get("peers") or []
    peer_medians = real_peer_data.get("medians") or {}
    is_real_peers = real_peer_data.get("is_real", False)
    print(f"[PEER DEBUG dashboard] is_real_peers={is_real_peers}, real_peers={len(real_peers)}, peer_medians_keys={list(peer_medians.keys())}")

    # Build the peers list for the simple peer table (ticker, name, mkt_cap_t)
    if is_real_peers and real_peers:
        peers = [
            {
                "ticker": p.get("ticker", "—"),
                "name": p.get("name", "—"),
                "mkt_cap_t": p.get("mkt_cap_t"),
            }
            for p in real_peers
        ]
    else:
        # Fall back to LLM narrative peers
        peers = narrative.get("peers") or []
        if isinstance(peers, list):
            peers = [
                {
                    "ticker": item.get("ticker") if isinstance(item, dict) else "—",
                    "name": item.get("name") if isinstance(item, dict) else "—",
                    "mkt_cap_t": _to_float_safe(item.get("mkt_cap_t")) if isinstance(item, dict) else None,
                }
                for item in peers
            ]

    # Build peer_matrix from real data (used for stats calculations)
    if is_real_peers and real_peers:
        peer_matrix = [
            {
                "ticker": p.get("ticker"),
                "name": p.get("name"),
                "ebit_margin": p.get("ebit_pct"),
                "roe": p.get("roe_pct"),
                "debt_equity": p.get("de"),
                "inventory_days": p.get("inv_days"),
                "mkt_cap_t": p.get("mkt_cap_t"),
                "pb": p.get("pb"),
                "pe": p.get("pe"),
                "ocf_pct": p.get("ocf_pct"),
                "tsr_5y_pct": p.get("tsr_5y_pct"),
            }
            for p in real_peers
        ]
    else:
        peer_matrix = []

    corporate_info = narrative.get("corporate_info") or {}

    disclosures = narrative.get("disclosures") or []
    if not disclosures:
        edinet_docs = payload.get("edinet_docs", []) or []
        for doc in edinet_docs[:3]:
            disclosures.append({
                "date": doc.get("submit_date") or doc.get("date"),
                "title": doc.get("description") or doc.get("doc_type") or "EDINET filing",
                "detail": "Recent corporate filing.",
            })
    
    # Append 5% filings to disclosures for visibility
    try:
        large_filings = _get_edinet_large_holders(code)
        if large_filings:
            extra_disclosures = [
                {
                    "date": f["date"],
                    "title": f"5% Rule Filing: {f['filer']}",
                    "detail": f["type"][:100],
                }
                for f in large_filings[:5]
            ]
            disclosures = extra_disclosures + disclosures
    except Exception:
        pass

    avg_volume = _avg_volume(price_rows)
    week_high = price_kpis.get("range_52w_high")
    week_low = price_kpis.get("range_52w_low")
    # Avoid blanks: if range missing but we have last_price, set tight band
    if last_price and (week_high is None or week_low is None):
        week_high = week_high or last_price
        week_low = week_low or last_price
    range_pos = None
    if last_price and week_low is not None and week_high and week_high != week_low:
        range_pos = max(0, min(100, (last_price - week_low) / (week_high - week_low) * 100))

    header_tags = narrative.get("tags") or []
    if not header_tags:
        header_tags = ["REFORM DISCLOSED"] if "reform" in (payload.get("research_context", "").lower()) else []

    # ── Sanitise header fields ─────────────────────────────────
    # Web/EDINET scraping can inject raw text (addresses, officer names,
    # business descriptions) into name or exchange fields. Clean them to
    # ensure the report header renders correctly.
    def _clean_header_name(raw: str | None, max_len: int = 80) -> str | None:
        if not raw:
            return raw
        # Strip to first line only (prevents address/bio leakage)
        text = raw.split("\n")[0].strip()
        # Remove anything after "Location:", "Representative:", etc.
        for stop in ["Location:", "所在地", "Representative:", "代表", "Established:",
                      "Capital:", "資本金", "Business Description:", "事業内容",
                      "Total number", "発行済", "Fiscal year", "決算期",
                      "Audit:", "監査", "Greeting", "Officers", "Corporate Philosophy"]:
            idx = text.find(stop)
            if idx > 0:
                text = text[:idx].rstrip(" ,;:")
        # Truncate if still too long
        if len(text) > max_len:
            text = text[:max_len].rstrip(" ,;:") + "…"
        return text.strip() or raw[:max_len]

    def _clean_exchange(raw: str | None) -> str:
        if not raw:
            return "TSE"
        text = str(raw).split("\n")[0].strip()
        # Shorten common long exchange strings
        if "Prime" in text:
            return "TSE Prime"
        if "Standard" in text:
            return "TSE Standard"
        if "Growth" in text:
            return "TSE Growth"
        if len(text) > 60:
            # Try to extract first meaningful exchange name
            parts = [p.strip() for p in text.replace(",", "·").split("·") if p.strip()]
            if parts:
                first = parts[0]
                if len(first) > 60:
                    first = first[:57] + "…"
                return first
        return text

    safe_name_jp = _clean_header_name(name_jp, 80)
    safe_name_en = _clean_header_name(name_en, 100)
    raw_exchange = company_info.get("market") or profile.get("listed_markets") or "TSE"
    safe_exchange = _clean_exchange(raw_exchange)
    if is_etf:
        safe_sector = f"Exchange-Traded Fund ({fund_type})" if fund_type else "Exchange-Traded Fund"
    else:
        safe_sector = _clean_header_name(
            company_info.get("sector") or payload.get("sector") or _classify_sector_stub(payload.get("stock_code"), "Homebuilding / Residential Real Estate"),
            60,
        )
    # Sector code (TOPIX-33 sector number) for header display
    _sector_code = listed_info.get("Sector33Code") or listed_info.get("S33Cd") or ""
    if _sector_code:
        try:
            _sector_code = str(int(str(_sector_code).strip()))
        except (ValueError, TypeError):
            _sector_code = ""

    # Detect accounting standard from DocType if AccountingStandard is missing
    acct_std = listed_info.get("AccountingStandard")
    if not acct_std:
        raw_fin = payload.get("financials_raw") or {}
        fin_data = raw_fin.get("data") or raw_fin.get("statements") or []
        if isinstance(fin_data, list):
            for _stmt in reversed(fin_data):
                doc_type = (_stmt.get("DocType") or "")
                if "IFRS" in doc_type:
                    acct_std = "IFRS"
                    break
                elif "US_GAAP" in doc_type or "USGAAP" in doc_type:
                    acct_std = "US GAAP"
                    break
                elif "JGAAP" in doc_type or "JP_GAAP" in doc_type:
                    acct_std = "Japan GAAP"
                    break
        if not acct_std:
            acct_std = "Japan GAAP"
    safe_acct = _clean_header_name(acct_std, 30)
    # Derive FY end month from the most recent CurFYEn in financial data
    # CurFYEn can be "2024-08-31" (dashed) or "20240831" (compact)
    _fy_end_str = profile.get("fiscal_year_end") or ""
    if not _fy_end_str:
        raw_fin_fy = payload.get("financials_raw") or {}
        fin_data_fy = raw_fin_fy.get("data") or raw_fin_fy.get("statements") or []
        if isinstance(fin_data_fy, list) and fin_data_fy:
            for _fy_stmt in reversed(fin_data_fy):
                _fy_en = (_fy_stmt.get("CurFYEn") or "").replace("/", "-").strip()
                if not _fy_en:
                    continue
                try:
                    # Normalise compact YYYYMMDD → YYYY-MM-DD
                    if len(_fy_en) == 8 and _fy_en.isdigit():
                        _fy_en = f"{_fy_en[:4]}-{_fy_en[4:6]}-{_fy_en[6:8]}"
                    if len(_fy_en) >= 7 and _fy_en[4] == "-":
                        _fy_month = int(_fy_en[5:7])
                        _month_names = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                                        7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}
                        _fy_end_str = f"FY End {_month_names.get(_fy_month, 'March')}"
                except (ValueError, IndexError):
                    pass
                break
        if not _fy_end_str:
            _fy_end_str = "FY End March"
    safe_fy = _clean_header_name(_fy_end_str, 30)

    return {
        "is_etf": is_etf,
        "fund_type": fund_type,
        "report_metadata": {
            "generated_at": payload.get("generated_at"),
            "source": "EDINET · TSE · IB Market Data",
            "analyst_firm": "Japan Catalyst Research",
        },
        "company_header": {
            "ticker": payload.get("stock_code"),
            "name_jp": safe_name_jp,
            "name_en": safe_name_en,
            "sector": safe_sector,
            "sector_code": _sector_code,
            "exchange": safe_exchange,
            "accounting_standard": safe_acct,
            "fiscal_year_end": safe_fy,
            "tags": header_tags,
        },
        "kpi_ribbon": kpi,
        "narrative_outlook": {
            # New format fields
            "company_profile": narrative.get("company_profile") or narrative.get("summary_text") or "",
            "business_performance": narrative.get("business_performance") or narrative.get("outlook_summary") or "",
            "material_note": narrative.get("material_note") or "",
            "investment_thesis": narrative.get("investment_thesis") or narrative.get("company_bullets") or [],
            "bull_case": narrative.get("bull_case") or [],
            "bear_case": narrative.get("bear_case") or [],
            # Legacy compatibility
            "summary_text": narrative.get("company_profile") or narrative.get("summary_text") or "",
            "company_bullets": narrative.get("investment_thesis") or narrative.get("company_bullets") or [],
            "outlook_summary": narrative.get("business_performance") or narrative.get("outlook_summary") or "",
        },
        "charts_data": {
            "roe": roe_series,
            "ocf": ocf_series,
            "dps": dps_series,
            "ownership_mix": ownership_mix,
        },
        "geographic_mix": narrative.get("geographic_mix") or {},
        "income_statement": income_statement,
        "column_1_holdings": {
            "major_shareholders": major_shareholders,
            "activist_radar": payload.get("activist_radar") or {"filings": [], "has_poison_pill": False},
            "cross_holdings": cross_holdings,
        },
        "column_2_balance": {
            "summary": {
                "total_assets": latest.get("total_assets"),
                "net_assets": latest.get("equity"),
                "borrowings": latest.get("borrowings"),
                "roa_pct": latest.get("roa"),
            },
            "cash_flow": {
                "operating": latest.get("cfo"),
                "investing": latest.get("cfi"),
                "financing": latest.get("cff"),
                "cash_equiv": latest.get("cash_equiv"),
            },
            "returns": {
                "tsr_pct": (price_kpis.get("returns", {}).get("12m") * 100) if price_kpis.get("returns", {}).get("12m") is not None else None,
                "payout_ratio_pct": narrative.get("payout_ratio_pct"),
            },
            "revenue_mix": revenue_mix,
        },
        "column_3_market": {
            "stock_info": {
                "week_52_high": week_high,
                "week_52_low": week_low,
                "avg_volume": avg_volume,
                "shares_out": shares,
                "range_position": range_pos,
            },
            "peers": peers,
            "peer_matrix": peer_matrix,
            "peer_medians": peer_medians,
            "is_real_peers": is_real_peers,
            "corporate_info": _build_corporate_info_final(corporate_info, profile, payload),
        },
        "capital_structure_section": _build_capital_structure_data(rows_sorted, kpi, latest),
        "footer_disclosures": disclosures,
        "valuation": valuation,
        "capital_allocation": capital_allocation,
        "capital_projects": capital_projects,
        "esg_data": esg_data,
        "risk_dashboard": risk_dashboard,
    }


def build_report_context(
    stock_code: str,
    company_name: str | None = None,
    mode: str = "full",
    on_progress=None,
    on_event=None,
) -> Dict:
    import threading as _ctx_threading

    payload = build_report_payload(
        stock_code,
        company_name,
        mode=mode,
        on_progress=on_progress,
        on_event=on_event,
    )

    # ── SPEED: Three-way parallel overlap ──
    # 1. Narrative LLM call (15-25s)    ↗
    # 2. Valuation model (15-60s)       → all run simultaneously
    # 3. Peer benchmarking (10-30s)     ↘
    # Previously narrative waited for valuation to finish first.
    # Now they overlap, saving 15-25s on every report.

    _peer_thread = payload.pop("_peer_thread", None)
    _peer_result_holder = payload.pop("_peer_result_holder", None)
    _valuation_thread = payload.pop("_valuation_thread", None)
    _valuation_result_holder = payload.pop("_valuation_result_holder", None)

    # Start narrative generation IMMEDIATELY (doesn't need valuation or peer data)
    _narrative_holder: Dict[str, Any] = {}

    def _bg_narrative():
        try:
            _narrative_holder["data"] = generate_dashboard_narrative(
                payload, on_progress=on_progress, on_event=on_event,
            )
        except Exception:
            _narrative_holder["data"] = {}

    _narr_thread = _ctx_threading.Thread(target=_bg_narrative, daemon=True)
    _narr_thread.start()

    # Join valuation WHILE narrative is running — poll with progress ticks
    if _valuation_thread:
        try:
            tick = 0
            while _valuation_thread.is_alive():
                _valuation_thread.join(timeout=5)
                tick += 1
                if _valuation_thread.is_alive() and on_progress:
                    # Show increasing progress: 58 → 75 over ~2 min
                    vpct = min(58 + tick, 75)
                    on_progress(vpct, "Valuation", "Computing valuation model...")
            valuation_data = (_valuation_result_holder or {}).get("data") or {}
            if valuation_data:
                payload["valuation_data"] = valuation_data
                payload["valuation_block"] = _build_valuation_block(valuation_data)
                if on_progress:
                    on_progress(76, "Valuation", "Valuation model ready")
        except Exception:
            pass

    # Add valuation warning if applicable
    if settings.ml_enabled and not payload.get("valuation_data"):
        dh = payload.get("data_health") or {}
        w = dh.get("warnings") or []
        w.append("Valuation model unavailable (insufficient J-Quants coverage).")
        dh["warnings"] = w
        payload["data_health"] = dh

    # Join peer thread while narrative still runs
    if _peer_thread:
        try:
            _peer_thread.join(timeout=120)
            peer_benchmarking = (_peer_result_holder or {}).get("data") or {}
            payload["peer_benchmarking"] = peer_benchmarking
            if peer_benchmarking.get("is_real"):
                if on_progress:
                    on_progress(79, "Peers", f"Found {len(peer_benchmarking.get('peers', []))} peers")
        except Exception:
            payload["peer_benchmarking"] = {}

    # Wait for narrative to complete
    _narr_thread.join(timeout=300)
    narrative = _narrative_holder.get("data") or {}

    dashboard = build_dashboard_context(payload, narrative)
    html_body = ""

    # ── Safety net: ensure peer benchmarking data survives into dashboard ──
    raw_pb = payload.get("peer_benchmarking") or {}
    if raw_pb.get("is_real") and raw_pb.get("peers"):
        col3 = dashboard.get("column_3_market") or {}
        if not col3.get("is_real_peers") or not col3.get("peer_matrix"):
            print(f"[PEER DEBUG] Safety net triggered — injecting peer data directly into dashboard")
            peer_matrix_inject = [
                {
                    "ticker": p.get("ticker"),
                    "name": p.get("name"),
                    "ebit_margin": p.get("ebit_pct"),
                    "roe": p.get("roe_pct"),
                    "debt_equity": p.get("de"),
                    "inventory_days": p.get("inv_days"),
                    "mkt_cap_t": p.get("mkt_cap_t"),
                    "pb": p.get("pb"),
                    "pe": p.get("pe"),
                    "ocf_pct": p.get("ocf_pct"),
                    "tsr_5y_pct": p.get("tsr_5y_pct"),
                }
                for p in raw_pb["peers"]
            ]
            col3["is_real_peers"] = True
            col3["peer_matrix"] = peer_matrix_inject
            col3["peer_medians"] = raw_pb.get("medians") or {}
            dashboard["column_3_market"] = col3

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    return {
        "company_name": payload["company_name"],
        "stock_code": payload["stock_code"],
        "generated_at": now,
        "report_body": html_body,
        "dashboard": dashboard,
        "sources": payload["sources"],
        "report_mode": payload["report_mode"],
        "data_health": payload.get("data_health", {}),
        "sector": payload.get("sector"),
        "market": payload.get("metrics", {}).get("company", {}).get("market"),
        "input_company_name": payload.get("data_health", {}).get("input_company_name"),
        "metrics": payload.get("metrics", {}),
        "research_context": payload["research_context"], # Ensure enriched context is passed
        "is_etf": payload.get("is_etf", False),
        "fund_type": payload.get("fund_type"),
    }

