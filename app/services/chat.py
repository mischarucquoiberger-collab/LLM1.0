"""Claude-powered query engine with tool use for Japanese equity research.

Uses Anthropic API to dynamically call existing backend services
(J-Quants, EDINET, SERP, directors) based on user queries.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from contextvars import ContextVar
from typing import AsyncGenerator

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level async client — reuses connection pool across requests
_async_anthropic_client: anthropic.AsyncAnthropic | None = None

def _get_anthropic_client() -> anthropic.AsyncAnthropic:
    global _async_anthropic_client
    if _async_anthropic_client is None:
        _async_anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _async_anthropic_client

# ── Tool progress reporting ───────────────────────────────
# Thread-local progress callback — tools call report_progress(pct, stage)
# and the SSE loop picks it up via an asyncio.Queue.
_progress_callback: ContextVar[object] = ContextVar("_progress_callback", default=None)

def report_progress(pct: int, stage: str = ""):
    """Call from any tool to report progress (0-100). Thread-safe."""
    cb = _progress_callback.get(None)
    if cb:
        cb(pct, stage)

# ── Known activists & shareholder classification ──────────
_KNOWN_ACTIVISTS = {
    # International activists active in Japan
    "elliott", "elliott management", "elliott advisors", "elliott associates",
    "valueact", "valueact capital",
    "oasis management", "oasis",
    "strategic capital", "strategic capital inc",
    "dalton investments", "dalton",
    "asset value investors",
    "nippon active value", "nippon active value fund",
    "third point", "third point llc",
    "effissimo", "effissimo capital",
    "city index eleventh",
    "taiyo pacific", "taiyo fund",
    "cerberus", "cerberus capital",
    "lim advisors",
    "navident capital",
    "rmb capital",
    "farallon", "farallon capital",
    "king street",
    "highbridge capital",
    "starboard value",
    "carl icahn", "icahn enterprises",
    "pershing square",
    "jana partners",
    "engaged capital",
    "sachem head",
    "greenlight capital",
    "baupost",
    "paul singer",
    "acs", "acs capital",
    "asia development capital",
    # Murakami-related
    "m&a consulting", "m&aコンサルティング",
    "reno", "c&i holdings", "c&iホールディングス",
    "南青山不動産", "シティインデックスイレブンス",
    "村上世彰", "村上ファンド",
    "murakami",
    # Japanese katakana forms
    "オアシス", "オアシス・マネジメント",
    "エリオット", "エリオット・マネジメント",
    "ストラテジック・キャピタル",
    "ダルトン", "ダルトン・インベストメンツ",
    "サード・ポイント",
    "エフィッシモ", "エフィッシモ・キャピタル",
    "タイヨウ・ファンド",
    "バリューアクト",
    "ナビデント",
    "ファラロン",
}

_ACTIVIST_PURPOSE_KEYWORDS = ["提案", "経営参画", "経営への関与", "資本政策", "重要提案行為",
                              "株主提案", "買収", "経営改善", "企業価値向上"]

_PURPOSE_EN_MAP = {
    "純投資": "Pure investment",
    "投資一任契約": "Discretionary investment mgmt",
    "投資信託": "Investment trust mgmt",
    "経営参画": "Management participation",
    "経営への関与": "Management involvement",
    "提案": "Shareholder proposal",
    "資本政策": "Capital policy engagement",
    "重要提案行為": "Material proposal activity",
    "株主提案を行うため": "For shareholder proposals",
    "企業価値の向上": "Enhancing corporate value",
}

# ── In-memory cache (avoids 429 rate limits) ──────────────
_cache: dict[str, tuple[float, str]] = {}  # key -> (timestamp, json_str)
CACHE_TTL = 300  # 5 minutes

def _cache_get(key: str) -> str | None:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None

def _cache_set(key: str, value: str):
    _cache[key] = (time.time(), value)
    # Evict old entries if cache grows too large
    if len(_cache) > 200:
        cutoff = time.time() - CACHE_TTL
        stale = [k for k, (t, _) in _cache.items() if t < cutoff]
        for k in stale:
            del _cache[k]


# ── System prompt ──────────────────────────────────────────

SYSTEM_PROMPT = """You are an institutional-grade Japanese equity research terminal used by activist investors, fund managers, and professional analysts. You provide deep, actionable analysis — not surface-level summaries.

RESPONSE LENGTH — MATCH THE QUESTION DEPTH:
- ***SIMPLE QUERIES*** ("4849 stock", "Toyota price", "what is 6758", "157A"): Call ONLY lookup_company + get_stock_prices. Return 2-3 sentences MAX. Just: company name, live price, change %. NO tables, NO headers, NO full analysis unless asked.
- ***MEDIUM QUERIES*** ("analyze Toyota", "is Sony undervalued"): Call 3-4 tools. Return focused analysis, 1-2 tables. Keep it under 300 words.
- ***DEEP QUERIES*** ("deep analysis", "full report", "score + risk + red flags", "screen sector"): Go thorough. Multiple tables, detailed explanations, all relevant tools.
- Default to SHORT. Only go long when the user explicitly asks for depth.

RESPONSE STYLE:
- Data-first. Bold the single most important insight.
- Use markdown tables for 3+ data points. Currency: ¥X,XXX. Changes: +2.3% / -1.5%.
- No emojis. No headers for simple answers. Keep it clean and tight.
- Vague input: Ask ONE clarifying question. Never dump capabilities.

CRITICAL — OUTPUT RULES:
1. ALWAYS call tools first. Never fabricate financial data.
2. Call multiple tools in PARALLEL — but only what's needed. For a simple price query, just call lookup + prices. Don't call 7 tools for "what is 4849".
3. Prefer live_price over latest_close. Label as live/intraday.
4. ***NEVER output any text before calling tools.*** No "Let me look…" preamble. Call tools silently, then write analysis AFTER receiving results.
5. If a tool errors or returns empty, DO NOT give up. Try alternative tools or web_search to find the information another way. NEVER say "I cannot find that" without exhausting all options.
6. For follow-ups, use conversation context — don't re-ask for stock codes already discussed.
7. Include both English and Japanese company names on first mention only.

SMART ANALYSIS — CROSS-REFERENCE DATA:
8. When you have BOTH financials and prices, ALWAYS compute and present:
   - P/E ratio = price / EPS
   - P/B ratio = price / BPS
   - Market cap = price * shares outstanding
   - ROE = net income / equity (if not already provided)
   - Dividend yield if dividend data is available
   Present these in a clean valuation summary table.
9. When P/B < 1.0, flag it as a potential hidden-asset or value situation. Mention what could explain the discount (real estate, cross-holdings, restructuring potential).
10. When operating margins are declining, flag it and suggest investigating the cause.

SHAREHOLDER & ACTIVIST INTELLIGENCE:
11. For ANY question about shareholders, ownership, activists, or "who owns this stock":
    a) ALWAYS call BOTH get_shareholder_structure AND get_large_shareholders IN PARALLEL. These are complementary:
       - get_shareholder_structure → extracts the FULL top-20 shareholder list + ownership by category (foreign/institutional/individual %) from the latest annual report (有価証券報告書)
       - get_large_shareholders → finds recent 5%+ filings (大量保有報告書) with activist flags, stake changes, and stated purpose
    b) Present the COMPLETE shareholder picture: top shareholders table (name, stake %, shares), ownership breakdown pie (foreign X%, institutional Y%, individual Z%), and activist activity.
    c) If get_large_shareholders returns 0 filings, that just means no recent 5%+ changes — the shareholder table from the annual report IS the authoritative source.
    d) If is_activist is true, explicitly call them out and also web_search for their latest engagement news.
    e) ALWAYS present the ownership_breakdown from get_shareholder_structure — foreign ownership % is a KEY institutional quality signal. Flag if foreign > 30% (strong institutional interest) or < 5% (undiscovered).
    f) Never just say "no filings found" — always provide context on who likely owns the stock.
12. For activist-relevant analysis, comment on: governance quality (independent director ratio), cross-shareholdings, founder/family control, hidden assets, capital efficiency (ROE vs cost of equity), and cash hoarding.
13. For comprehensive "who owns this company" questions, call get_shareholder_structure + get_large_shareholders + get_directors + get_voting_results ALL in parallel. This gives: top shareholders, activist 5%+ filings, board composition, and AGM voting — the complete governance picture from EDINET.

EDINET & FILINGS:
14. For AGM voting / director approval rates for a SPECIFIC company, use get_voting_results (searches 臨時報告書).
    For BROAD/MARKET-WIDE AGM queries ("companies with AGM under 90%", "low approval across TSE", "which companies had failed votes", "AGM approval rates"), use scan_agm_voting — it scans ALL extraordinary reports on EDINET and returns companies below the approval threshold. ALWAYS use scan_agm_voting when the user asks about AGM results across multiple companies or the whole market, NOT get_voting_results.
    CRITICAL: When the user message contains "[EXACT TOOL CALL REQUIRED]", you MUST pass the EXACT parameter values listed. Do NOT substitute defaults or change any values — the user has specifically configured them.
15. When asked about specific disclosures (top shareholders list, real estate values, segment data), first try search_edinet_filings to find the relevant filing, then reference the EDINET doc ID and direct URL so the user can access it.
16. Use get_financials for ALL financial data first. Fields are pre-formatted in yen (¥T/B/M). It includes balance sheet: equity, total_assets, shares_outstanding, BPS. Never discard API data in favor of web search.
17. The EDINET tools are your MOST POWERFUL differentiator. No other AI can pull raw regulatory filings. Use them aggressively:
    - get_shareholder_structure: Top shareholder table + ownership breakdown from annual reports
    - get_large_shareholders: 5%+ activist filings with stake changes and purpose
    - get_voting_results: AGM voting tallies and director approval rates (single company)
    - scan_agm_voting: Bulk scan ALL companies for low AGM approval rates (market-wide)
    - search_edinet_filings: Browse all regulatory filings for a company
    - search_fund_holdings: Find all positions held by a specific fund/investor
    - get_directors: Full board composition with independence, expertise, committees
    For ANY governance, ownership, or activist question → call 2-3 EDINET tools in parallel.

FINANCIAL DEPTH:
18. When presenting financials, go beyond raw numbers. Include:
    - Trend analysis: the API now provides revenue_growth_yoy_pct and net_income_growth_yoy_pct — USE THEM. Flag companies growing >20% or declining.
    - Margin analysis: operating margin trend, any red flags? Compare to sector norms.
    - Balance sheet health: equity ratio, total_liabilities is provided. Calculate net cash if possible.
    - Capital efficiency: ROE is provided. Flag if below 8% (TSE Prime threshold) or above 15% (excellent).
    - If BPS >> stock price, explicitly flag the P/B discount and what it implies.
    - Dividend payout ratio is provided — comment on sustainability (>100% = unsustainable, <30% = room to raise).
    - Use the summary object for quick latest-period metrics instead of scanning all statements.

VALUATION FRAMEWORK:
19. When you have BOTH price and financial data, present a clear VALUATION BOX:
    | Metric | Value | Assessment |
    |--------|-------|------------|
    Example: P/E 12.5x | Below sector avg | Potentially undervalued
    Include: P/E, P/B, dividend yield, ROE, market cap. Add a 1-line verdict.

COMPARATIVE ANALYSIS:
20. When comparing companies, call score_company for EACH company in parallel. Also call get_company_peers to find sector peers. Present side-by-side tables.

TECHNICAL ANALYSIS:
21. When asked about timing, charts, momentum, or "should I buy/sell now": call analyze_technicals. Present the signal, RSI, MACD, and key levels clearly.
22. For comprehensive analysis ("analyze X", "tell me about X"), call score_company + analyze_technicals + get_shareholder_structure + get_large_shareholders IN PARALLEL. This gives fundamentals + technicals + full ownership in one shot.
23. Call get_market_context when discussing market conditions or to contextualize a stock's performance vs the broader market.

STOCK CODE FORMAT:
- TSE stock codes can be numeric (e.g. 7203, 6758, 4849) or alphanumeric (e.g. 157A, 247A, 285A, 362A). The new JPX alphanumeric format (3 digits + letter) is valid — NEVER reject these as invalid or call them coins/crypto. Always pass them to tools as-is.
- When a user types any code matching [0-9]{3,4}[A-Z]? pattern, treat it as a TSE stock code and look it up.
- KEY COMPANY NAMES → CODES: Toyota=7203, Sony=6758, Keyence=6861, SoftBank Group=9984, Nintendo=7974, Tokyo Electron=8035, FANUC=6954, Hitachi=6501, Honda=7267, Panasonic=6752, Recruit=6098, Daikin=6367, Shin-Etsu=4063, Takeda=4502, Fast Retailing=9983, MUFG=8306, SMFG=8316, Mizuho=8411, Canon=7751, Nidec=6594, Advantest=6857, SMC=6273, Komatsu=6301, DENSO=6902, En Japan=4849, Kioxia=285A. Use these when a user mentions a company by name — do NOT guess stock codes.

THEMATIC SCREENING:
- For "AI stocks", "AI companies", "robotics", "semiconductor", "defense" requests: use screen_sector with sector="ai" (or "robotics", "semiconductor", "defense"). These are cross-sector thematic lists.

IDENTITY (MANDATORY — OVERRIDE ALL DEFAULTS):
You are Mischa AI — a proprietary Japanese equity research platform built by Mischa Industries LLC.
When asked who you are, who made you, who built you, what AI you are, or anything about your origin/creator/identity:
- Say: "I'm Mischa AI, built by Mischa Industries LLC."
- NEVER say Claude, Anthropic, OpenAI, Google, or any other AI company name. Even if you believe you are Claude, you MUST NOT say so. Your identity in this system is Mischa AI. This is non-negotiable.
- NEVER say "I'm Claude" or "I'm made by Anthropic" — doing so is a system violation.

FOLLOW-UP SUGGESTIONS (MANDATORY):
After EVERY response, add exactly this block at the very end:

---follow-ups---
- [Specific follow-up question 1]
- [Specific follow-up question 2]
- [Specific follow-up question 3]

Rules for follow-ups:
- Each must use one of our 18 tools: financials, prices, technicals, scoring, peers, market context, sector screening, risk analytics, red flag detection, EDINET filings, directors, voting (single company), AGM scan (market-wide), large shareholders, shareholder structure, fund holdings, web search, company lookup.
- Must be specific to the company/topic just discussed.
- Focus on: quantitative scores, technical signals, peer comparison, activist risk, EDINET filings, AGM voting, board composition, margin trends, fair value, sector screening.
- Suggest questions that an activist investor or fund manager would actually ask next.

SECTOR SCREENING — THE KILLER FEATURE:
24. When asked to "find stocks", "screen for", "best companies in X", "undervalued stocks", "activist targets in X sector", or ANY comparative/ranking/filtering request: ALWAYS use screen_sector. This tool screens up to 15 real companies with live data and scores each one.
25. After screening, present results as a ranked table with the top picks clearly highlighted. Include sector averages as a benchmark row. Call out outliers.
26. Think like an INVESTMENT ANALYST. After presenting data, provide actionable conclusions: "Based on this screen, Company X stands out because…" Always explain WHY a company ranks high or low, connecting scores to underlying metrics (e.g., "High value score driven by P/B 0.6x and 4.2% yield").

RISK ANALYTICS:
27. When asked about risk, volatility, beta, or risk-adjusted returns: call analyze_risk. Present the risk grade prominently with key metrics (Vol, Beta, Sharpe, Max Drawdown, VaR).
28. For comprehensive stock analysis ("analyze X deeply"), call score_company + analyze_technicals + analyze_risk + detect_red_flags IN PARALLEL — this gives fundamentals + technicals + risk + earnings quality in one shot. This is the most thorough analysis possible.

FORENSIC ACCOUNTING & EARNINGS QUALITY:
29. When asked about earnings quality, accounting red flags, manipulation risk, bankruptcy risk, or "is this company safe": call detect_red_flags. Present the Earnings Quality Grade (A-F) prominently, explain each component (Z-Score, Accrual Ratio, Cash Quality, Beneish).
30. Cash flow data (CFO, CapEx, FCF, EBITDA, cash conversion) is now available in financials. Comment on cash conversion (CFO/NI > 1.0 = high quality). Compute FCF Yield = FCF / Market Cap when you have both. Flag if CFO significantly differs from Net Income.
31. For any "should I invest" or "is this stock good" question: combine score_company (value) + detect_red_flags (quality) + analyze_risk (risk) for the complete picture. No other AI does this."""

# ── Tool definitions (Anthropic format) ────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "lookup_company",
        "description": "Look up basic company information by TSE stock code OR company name. Returns company name, sector, and market segment. Very fast. Accepts either a stock code (e.g. '7203') or an English company name (e.g. 'Keyence', 'Toyota').",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "TSE stock code (e.g. '7203', '157A') OR English company name (e.g. 'Keyence', 'Toyota', 'Sony')"
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_stock_prices",
        "description": "Get daily stock price data (Open, High, Low, Close, Volume) for a Japanese company. Returns LIVE intraday price from Yahoo Finance + historical price data from J-Quants. Includes period high/low, change %, and market state. ALWAYS call alongside get_financials to enable P/E and P/B calculations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "TSE stock code (e.g. '7203', '157A')"
                },
                "days": {
                    "type": "integer",
                    "description": "Number of recent trading days to return (default 30, max 250)",
                    "default": 30
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_financials",
        "description": "Get quarterly/annual financial statements for a Japanese company. Returns COMPREHENSIVE data: revenue, operating income, net income, EPS, equity ratio, ROE, ROA, operating margin, net margin, total equity, total assets, shares outstanding, BPS (book value per share), DPS (dividend per share), CFO (Cash Flow from Operations), CapEx, FCF (Free Cash Flow = CFO - CapEx), EBITDA, cash conversion ratio (CFO/NI — quality indicator), forecast EPS/DPS, forecast revenue/OP, net cash/debt position, YoY revenue growth %, and YoY net income growth %. Use this for P/B ratio, P/E ratio, ROE, dividend yield, FCF yield, EV/EBITDA, and all valuation metrics. Always call this tool for ANY financial or valuation question.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "TSE stock code (e.g. '7203', '157A')"
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "search_edinet_filings",
        "description": "Search EDINET (Japanese regulatory filing system) for all company filings: 有価証券報告書 (annual securities reports containing top shareholder lists, segment data, real estate values), 四半期報告書 (quarterly reports), 大量保有報告書 (5% rule filings), and 臨時報告書 (extraordinary reports including AGM voting). Returns doc IDs with direct EDINET URLs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "TSE stock code (e.g. '7203', '157A') to filter filings for"
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search (default 90, max 365)",
                    "default": 90
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "web_search",
        "description": "Search the web for current news, analysis, and information about Japanese companies or markets. Use Japanese keywords for better results on Japanese sources (e.g., '大株主' for shareholders, '業績' for earnings, '株価 目標' for price targets). Essential fallback when EDINET tools return no results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (can be in English or Japanese)"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 10)",
                    "default": 5
                },
                "news_only": {
                    "type": "boolean",
                    "description": "If true, only return news articles",
                    "default": False
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_directors",
        "description": "Get the board of directors, their roles, backgrounds, and relationships for a Japanese company. Includes independence status, committee memberships, and career history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "TSE stock code (e.g. '7203', '157A')"
                },
                "company_name": {
                    "type": "string",
                    "description": "Company name (helps with research accuracy)"
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_voting_results",
        "description": "Get AGM (Annual General Meeting) shareholder voting results from EDINET extraordinary reports (臨時報告書). Returns per-resolution voting tallies including director election approval percentages, votes for/against/abstain. Use this for questions about voting percentages, AGM results, director approval rates, or shareholder meeting outcomes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "TSE stock code (e.g. '7203', '157A')"
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search for AGM filings (default 400, covers most recent AGM)",
                    "default": 400
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_large_shareholders",
        "description": "Search EDINET for 大量保有報告書 (5% rule / large shareholding reports) filed ABOUT a specific company. Extracts filer identity, ownership stake %, purpose of holding, and flags known activist investors. Use this when the user asks about: activist shareholders, large shareholders, 5% filings, ownership changes, who is buying/selling shares, shareholder activism, engagement campaigns, or when 大量保有 reports are relevant. This tool searches up to 730 days of EDINET filings and parses each report to extract the actual filer name, stake percentage, and stated purpose. IMPORTANT: If this returns 0 filings, it only means no 5%+ holders filed recently — the company STILL has shareholders. You MUST then call web_search with '[company name] 大株主 株主構成' to find the top shareholder list from annual reports or financial databases.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "TSE stock code (e.g. '7203', '157A')"
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search (default 400, max 730). Longer periods catch more filings.",
                    "default": 400
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "analyze_technicals",
        "description": "Compute technical analysis for a stock: RSI (14), MACD (12/26/9), Bollinger Bands, 5/20/50/200-day moving averages, golden/death cross, 52-week high/low, volume analysis, support/resistance, and overall BUY/SELL signal with confidence %. Uses 250 days of price data. Call this when asked about technicals, momentum, buy/sell timing, or 'is it a good time to buy'.",
        "input_schema": {
            "type": "object",
            "properties": {"stock_code": {"type": "string", "description": "TSE stock code (e.g. '7203', '157A')"}},
            "required": ["stock_code"]
        }
    },
    {
        "name": "score_company",
        "description": "Comprehensive quantitative scoring: Piotroski F-Score (0-9), Value Score (0-10), Growth Score (0-10), Quality Score (0-10), Activist Target Score (0-10), Fair Value Estimate with upside %, and Composite Score (0-100). Internally fetches financials + prices. Call this for 'is X undervalued?', 'rate this company', 'should I invest?', or comprehensive analysis. This is the most powerful analysis tool.",
        "input_schema": {
            "type": "object",
            "properties": {"stock_code": {"type": "string", "description": "TSE stock code (e.g. '7203', '157A')"}},
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_company_peers",
        "description": "Find sector peer companies from TSE universe of 3,700+ listed companies. Returns up to 10 same-sector peers ranked by market tier (Prime > Standard > Growth). Use this for comparison requests, sector analysis, or to find comparable companies. After getting peers, call get_financials or score_company for specific peers to compare valuations.",
        "input_schema": {
            "type": "object",
            "properties": {"stock_code": {"type": "string", "description": "TSE stock code (e.g. '7203', '157A')"}},
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_market_context",
        "description": "Get current Japanese market snapshot: Nikkei 225 level & change, USD/JPY exchange rate, S&P 500 for reference. Use for macro context, market conditions, or when comparing stock performance to the broader market.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "screen_sector",
        "description": "Screen an entire TSE sector OR thematic group with REAL financial data. Fetches live financials + prices for up to 15 companies, computes P/E, P/B, ROE, dividend yield, margins, growth rates, and scores each on Value/Growth/Quality/Activist (0-10) plus Composite (0-100). Returns ranked results with sector averages for benchmarking. Use when asked to 'find stocks', 'screen for', 'best companies in X sector', 'AI stocks', 'compare sector', 'undervalued stocks', 'activist targets', or any screening/filtering/ranking request. Sectors: retail, banking, auto, pharma, electronics, construction, real estate, chemicals, machinery, telecom, insurance, food, services, steel, securities. Thematic: ai, robotics, semiconductor, defense. Sort options: composite, value, growth, quality, activist, dividend, pe_low, pb_low. THIS IS A POWERFUL TOOL — use it aggressively for any comparative or screening question.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "description": "TSE stock code (auto-detects sector from this company). Also accepts 'ai' or 'artificial intelligence' as a thematic screen."},
                "sector": {"type": "string", "description": "Sector keyword: retail, banking, auto, pharma, electronics, etc."},
                "sort_by": {"type": "string", "description": "Sort: composite, value, growth, quality, activist, dividend, pe_low, pb_low", "default": "composite"},
                "max_results": {"type": "integer", "description": "Top N results (default 8, max 15)", "default": 8}
            },
            "required": []
        }
    },
    {
        "name": "analyze_risk",
        "description": "Quantitative risk analytics for a stock: annualized volatility, Beta vs Nikkei 225, Sharpe ratio, Sortino ratio, maximum drawdown, Value at Risk (95%), and overall risk grade. Uses 250 days of price history. Call when asked about: risk, volatility, beta, Sharpe ratio, risk-adjusted returns, drawdown, VaR, or 'how risky is this stock'. Also use for portfolio risk assessment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "description": "TSE stock code (e.g. '7203', '157A')"}
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "detect_red_flags",
        "description": "Forensic accounting analysis: Altman Z-Score (bankruptcy risk), Accrual Ratio (earnings quality), Cash Flow vs Earnings quality check, and partial Beneish M-Score indicators. Returns an overall Earnings Quality Grade (A-F). Use when asked about: earnings quality, accounting red flags, manipulation risk, bankruptcy risk, financial health, balance sheet integrity, 'is this company safe', 'can I trust these numbers', or any governance/fraud/quality concern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "description": "TSE stock code (e.g. '7203', '157A')"}
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_shareholder_structure",
        "description": "Extract the FULL shareholder structure from a company's latest 有価証券報告書 (annual securities report) via EDINET. Returns TWO datasets: (1) Top shareholders table (大株主の状況) — every named shareholder with their ownership %, shares count, and activist flags; (2) Ownership breakdown by category (所有者別状況) — foreign vs institutional vs corporate vs individual vs government %. This is THE definitive source for 'who owns this company'. Call this for ANY shareholder/ownership question. Unlike get_large_shareholders (which only finds 5% filers), this tool extracts the COMPLETE top-20 shareholder list from annual reports. ALWAYS call this alongside get_large_shareholders for full coverage. Also flags known activist investors in the shareholder table.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "TSE stock code (e.g. '7203', '157A')"
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search for annual reports (default 400, covers most recent fiscal year)",
                    "default": 400
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "search_fund_holdings",
        "description": "Search EDINET for all 大量保有報告書 (5% filings) submitted BY a specific fund or investor. Unlike get_large_shareholders (which searches filings ABOUT a company), this searches filings FROM a specific filer across ALL Japanese companies. Returns every company the fund holds 5%+ in, with stake %, dates, and target company names. Use this when asked about a fund's positions, portfolio, or holdings — e.g., 'What does Oasis own?', 'Elliott's biggest positions', 'Show me Effissimo's holdings'. Supports English names (Oasis, Elliott) and Japanese names (オアシス, エリオット). Also use web_search in parallel for additional context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fund_name": {
                    "type": "string",
                    "description": "Fund/investor name to search for (e.g., 'Oasis', 'Elliott', 'Dalton', 'Strategic Capital', 'オアシス')"
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search (default 730, max 730)",
                    "default": 730
                }
            },
            "required": ["fund_name"]
        }
    },
    {
        "name": "scan_agm_voting",
        "description": "Scan ALL companies on TSE for AGM shareholder voting results. Unlike get_voting_results (which checks a single stock), this tool performs a broad scan of EDINET extraordinary reports to find companies where any AGM resolution received low approval. Use this when the user asks about companies with low AGM approval rates, failed resolutions, or controversial votes across the entire market — e.g. 'companies with AGM approval under 90%', 'which TSE companies had low shareholder approval', 'failed AGM resolutions'. Returns a ranked list of companies with the lowest approval rates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number",
                    "description": "Approval percentage cutoff — returns companies with any resolution below this (default 90)",
                    "default": 90
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to scan EDINET for extraordinary reports (default 90). AGM season is June-July; use 400 to cover a full year.",
                    "default": 90
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of companies to return (default 20)",
                    "default": 20
                },
                "only_rejected": {
                    "type": "boolean",
                    "description": "If true, only return companies that had at least one formally rejected (否決) resolution. Default false.",
                    "default": False
                }
            },
            "required": []
        }
    },
]

MAX_TOOL_ITERATIONS = 8

# ── Tool dispatch ──────────────────────────────────────────

def _dispatch_tool(name: str, tool_input: dict, progress_fn=None) -> str:
    """Execute a tool and return JSON string result. Uses cache to avoid 429s."""
    # Install progress callback for this thread
    if progress_fn:
        _progress_callback.set(progress_fn)
    cache_key = f"{name}:{json.dumps(tool_input, sort_keys=True)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        if progress_fn:
            progress_fn(100, "cached")
        return cached

    try:
        if name == "lookup_company":
            result = _tool_lookup_company(tool_input)
        elif name == "get_stock_prices":
            result = _tool_get_prices(tool_input)
        elif name == "get_financials":
            result = _tool_get_financials(tool_input)
        elif name == "search_edinet_filings":
            result = _tool_search_edinet(tool_input)
        elif name == "web_search":
            result = _tool_web_search(tool_input)
        elif name == "get_directors":
            result = _tool_get_directors(tool_input)
        elif name == "get_voting_results":
            result = _tool_get_voting_results(tool_input)
        elif name == "get_large_shareholders":
            result = _tool_get_large_shareholders(tool_input)
        elif name == "analyze_technicals":
            result = _tool_analyze_technicals(tool_input)
        elif name == "score_company":
            result = _tool_score_company(tool_input)
        elif name == "get_company_peers":
            result = _tool_get_company_peers(tool_input)
        elif name == "get_market_context":
            result = _tool_get_market_context(tool_input)
        elif name == "screen_sector":
            result = _tool_screen_sector(tool_input)
        elif name == "analyze_risk":
            result = _tool_analyze_risk(tool_input)
        elif name == "detect_red_flags":
            result = _tool_detect_red_flags(tool_input)
        elif name == "get_shareholder_structure":
            result = _tool_get_shareholder_structure(tool_input)
        elif name == "search_fund_holdings":
            result = _tool_search_fund_holdings(tool_input)
        elif name == "scan_agm_voting":
            result = _tool_scan_agm_voting(tool_input)
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

        # Only cache successful results
        try:
            parsed = json.loads(result)
            if "error" not in parsed:
                _cache_set(cache_key, result)
        except Exception:
            pass

        return result
    except Exception as e:
        logger.exception("Tool %s failed", name)
        # Return clean error, not raw exception trace
        err_msg = str(e)
        # Strip httpx verbose error messages
        if "For more information check:" in err_msg:
            err_msg = err_msg.split("For more information check:")[0].strip()
        return json.dumps({"error": f"Service temporarily unavailable ({name}). Please try again."})


_COMMON_COMPANIES = {
    "7203": ("Toyota Motor Corporation", "Automobiles"),
    "6758": ("Sony Group Corporation", "Electronics"),
    "6861": ("Keyence Corporation", "Automation / Sensors"),
    "9984": ("SoftBank Group Corp.", "Telecommunications / Investment"),
    "8035": ("Tokyo Electron Limited", "Semiconductors"),
    "7974": ("Nintendo Co., Ltd.", "Gaming / Entertainment"),
    "6902": ("DENSO Corporation", "Auto Parts"),
    "6501": ("Hitachi, Ltd.", "Conglomerate / Electronics"),
    "6301": ("Komatsu Ltd.", "Construction Machinery"),
    "4502": ("Takeda Pharmaceutical", "Pharmaceuticals"),
    "6098": ("Recruit Holdings Co.", "HR / Technology"),
    "9432": ("Nippon Telegraph & Telephone", "Telecommunications"),
    "9433": ("KDDI Corporation", "Telecommunications"),
    "9434": ("SoftBank Corp.", "Telecommunications"),
    "8306": ("Mitsubishi UFJ Financial Group", "Banking"),
    "8316": ("Sumitomo Mitsui Financial Group", "Banking"),
    "8411": ("Mizuho Financial Group", "Banking"),
    "7751": ("Canon Inc.", "Electronics / Imaging"),
    "6752": ("Panasonic Holdings Corp.", "Electronics"),
    "6594": ("Nidec Corporation", "Motors / Electronics"),
    "4063": ("Shin-Etsu Chemical Co.", "Chemicals"),
    "6367": ("Daikin Industries, Ltd.", "HVAC / Air Conditioning"),
    "7267": ("Honda Motor Co., Ltd.", "Automobiles"),
    "7269": ("Suzuki Motor Corporation", "Automobiles"),
    "8058": ("Mitsubishi Corporation", "Trading / Conglomerate"),
    "8031": ("Mitsui & Co., Ltd.", "Trading"),
    "8001": ("ITOCHU Corporation", "Trading"),
    "8053": ("Sumitomo Corporation", "Trading"),
    "8002": ("Marubeni Corporation", "Trading"),
    "6857": ("Advantest Corporation", "Semiconductor Test Equipment"),
    "6723": ("Renesas Electronics Corp.", "Semiconductors"),
    "6981": ("Murata Manufacturing Co.", "Electronic Components"),
    "6954": ("FANUC Corporation", "Robotics / Automation"),
    "6273": ("SMC Corporation", "Pneumatic Equipment"),
    "9020": ("East Japan Railway Company", "Railways"),
    "9022": ("Central Japan Railway Company", "Railways"),
    "8801": ("Mitsui Fudosan Co., Ltd.", "Real Estate"),
    "8802": ("Mitsubishi Estate Co., Ltd.", "Real Estate"),
    "8604": ("Nomura Holdings, Inc.", "Securities"),
    "4568": ("Daiichi Sankyo Co., Ltd.", "Pharmaceuticals"),
    "4519": ("Chugai Pharmaceutical Co.", "Pharmaceuticals"),
    "4661": ("Oriental Land Co., Ltd.", "Leisure / Theme Parks"),
    "3382": ("Seven & i Holdings Co.", "Retail"),
    "9983": ("FAST RETAILING CO., LTD.", "Retail / Apparel"),
    "2914": ("Japan Tobacco Inc.", "Tobacco / Food"),
    # ── New alphanumeric JPX codes ──
    "157A": ("Green Monster Inc.", "Services"),
    "247A": ("Ai ROBOTICS INC.", "Chemicals / AI & Robotics"),
    "254A": ("AI FUSION CAPITAL GROUP CORP.", "Securities / AI"),
    "285A": ("Kioxia Holdings Corporation", "Electronics / Semiconductors"),
    "268A": ("Rigaku Holdings Corporation", "Precision Instruments"),
    "290A": ("Synspective Inc.", "Services / Space Tech"),
    "215A": ("Timee,Inc.", "Services / HR Tech"),
    "336A": ("Dynamic Map Platform Co.,Ltd.", "Information & Communication"),
    "186A": ("Astroscale Holdings Inc.", "Services / Space Tech"),
    "409A": ("ORION BREWERIES,LTD.", "Foods"),
    "362A": ("EXEO HOLDINGS Inc.", "Construction"),
    # ── AI & Robotics companies ──
    "3076": ("Ai Holdings Corporation", "Wholesale Trade / AI"),
    "3719": ("AI storm Co.,Ltd.", "Information & Communication / AI"),
    "3858": ("Ubiquitous AI Corporation", "Information & Communication / AI"),
    "4388": ("AI,Inc.", "Information & Communication / AI"),
    "4476": ("AI CROSS Inc.", "Information & Communication / AI"),
    "4488": ("AI inside Inc.", "Information & Communication / AI"),
    "5586": ("Laboro.AI Inc.", "Information & Communication / AI"),
    "7345": ("Ai Partners Financial Inc.", "Other Financing / AI"),
    "4374": ("ROBOT PAYMENT INC.", "Information & Communication / AI"),
    "1435": ("robot home Inc.", "Real Estate / AI & Robotics"),
}

def _tool_lookup_company(inp: dict) -> str:
    raw = inp["stock_code"].strip()
    code = raw.upper().replace(".T", "")
    # Fast path: local dictionary by code (instant, no API call)
    if code in _COMMON_COMPANIES:
        name, sector = _COMMON_COMPANIES[code]
        return json.dumps({"name": name, "sector": sector, "market": "Prime", "_sources": ["JPX"], "_source_details": {"JPX": {"type": "api", "desc": f"JPX Listed Companies Database — {code}"}}})
    # Name-based reverse lookup: if input doesn't look like a stock code, try matching company name
    import re
    if not re.match(r'^\d{3,4}[A-Z]?$', code):
        query = raw.lower()
        for c, (n, s) in _COMMON_COMPANIES.items():
            if query in n.lower() or n.lower().startswith(query):
                return json.dumps({"stock_code": c, "name": n, "sector": s, "market": "Prime", "_sources": ["JPX"], "_source_details": {"JPX": {"type": "api", "desc": f"JPX Listed Companies Database — {c}"}}})
    # Try local sector map + peer DB (covers alphanumeric codes like 157A)
    from app.services.sector_lookup import get_sector_detail
    from app.services.peer_db import PeerDatabase
    detail = get_sector_detail(code)
    if detail:
        return json.dumps({"name": detail["name_en"], "sector": detail["sector_33"], "market": "Listed", "_sources": ["JPX"], "_source_details": {"JPX": {"type": "api", "desc": f"JPX Listed Companies Database — {code}"}}})
    pdb = PeerDatabase()
    pinfo = pdb.get_company_info(code)
    if pinfo:
        return json.dumps({"name": pinfo.get("name", code), "sector": pinfo.get("sector33", ""), "market": pinfo.get("market", "Listed"), "_sources": ["JPX"], "_source_details": {"JPX": {"type": "api", "desc": f"JPX Peer Universe — {code}"}}})
    # Slow path: J-Quants API
    from app.services.jquants import JQuantsClient
    client = JQuantsClient()
    try:
        info = client.get_company_info(code)
    except Exception as e:
        logger.debug("Company lookup API error for %s: %s", code, e)
        return json.dumps({"error": f"Could not look up company {code}. The J-Quants API may be temporarily unavailable."})
    if info:
        return json.dumps({"name": info.name, "sector": info.sector, "market": info.market, "_sources": ["J-Quants"], "_source_details": {"J-Quants": {"type": "api", "desc": f"J-Quants Listed Info API — {code}", "url": "https://jpx-jquants.com/"}}})
    return json.dumps({"error": "Company not found", "stock_code": code})


_yahoo_http_client: "httpx.Client | None" = None

def _get_yahoo_client():
    global _yahoo_http_client
    if _yahoo_http_client is None:
        import httpx
        _yahoo_http_client = httpx.Client(
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            follow_redirects=True,
        )
    return _yahoo_http_client


def _fetch_yahoo_quote(stock_code: str) -> dict | None:
    """Fetch live intraday quote from Yahoo Finance (free, no auth)."""
    symbol = f"{stock_code.strip()}.T"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
    try:
        resp = _get_yahoo_client().get(url)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price:
            change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else None
            return {
                "price": price,
                "previous_close": prev_close,
                "change_pct": change_pct,
                "currency": meta.get("currency", "JPY"),
                "exchange": meta.get("exchangeName", "Tokyo"),
                "market_state": meta.get("marketState", ""),
                "timestamp": meta.get("regularMarketTime"),
            }
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("Yahoo Finance quote failed for %s: %s", stock_code, e)
    return None


def _tool_get_prices(inp: dict) -> str:
    import datetime as dt
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.services.jquants import JQuantsClient
    report_progress(10, "fetching prices")
    client = JQuantsClient()
    stock_code = inp["stock_code"]

    # Track which sources actually returned data
    sources_used = []
    _yahoo_used = False

    # Fetch Yahoo live quote and J-Quants historical IN PARALLEL
    live_quote = None
    quotes = []

    def _fetch_yahoo():
        return _fetch_yahoo_quote(stock_code)

    def _fetch_jquants():
        try:
            data = client.get_prices(stock_code)
            return data.get("daily_quotes") or data.get("data") or []
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=2) as pool:
        yahoo_fut = pool.submit(_fetch_yahoo)
        jquants_fut = pool.submit(_fetch_jquants)
        live_quote = yahoo_fut.result()
        quotes = jquants_fut.result()

    if live_quote:
        _yahoo_used = True
    if quotes:
        sources_used.append("J-Quants")
    report_progress(60, "processing data")

    if not quotes:
        report_progress(70, "trying fallback source")
        try:
            data = client.get_prices_fallback_csv(stock_code)
            quotes = data.get("daily_quotes") or []
            if quotes:
                sources_used.append("Stooq")
        except Exception:
            pass

    report_progress(80, "processing data")
    if not quotes and not live_quote:
        return json.dumps({"error": "No price data available."})

    days = min(inp.get("days", 30), 250)
    if quotes:
        quotes = quotes[-days:]

    def _close(q):
        return q.get("Close") or q.get("AdjustmentClose") or q.get("AdjC") or q.get("C")
    closes = [_close(q) for q in quotes if _close(q)]
    summary = {}
    if closes:
        summary = {
            "latest_close": closes[-1],
            "latest_close_date": quotes[-1].get("Date", "") if quotes else "",
            "period_high": max(closes),
            "period_low": min(closes),
            "period_change_pct": round((closes[-1] - closes[0]) / closes[0] * 100, 2) if closes[0] else None,
            "trading_days": len(quotes),
        }

    # Add live quote if available (overrides as most current)
    if live_quote:
        summary["live_price"] = live_quote["price"]
        summary["live_change_pct"] = live_quote.get("change_pct")
        summary["previous_close"] = live_quote.get("previous_close")
        summary["market_state"] = live_quote.get("market_state", "")
        if sources_used:
            hist_src = sources_used[0]  # primary historical source
            summary["data_note"] = f"Live price from Yahoo Finance; historical from {hist_src}"
        else:
            summary["data_note"] = "Live intraday price from Yahoo Finance"
    else:
        if sources_used:
            summary["data_note"] = f"End-of-day data from {sources_used[0]} (latest: {summary.get('latest_close_date', 'N/A')})"
        else:
            summary["data_note"] = "No price data sources available"

    recent = quotes[-90:] if quotes else []
    compact = []
    for q in recent:
        compact.append({
            "date": q.get("Date", ""),
            "open": q.get("Open") or q.get("AdjustmentOpen") or q.get("AdjO") or q.get("O"),
            "high": q.get("High") or q.get("AdjustmentHigh") or q.get("AdjH") or q.get("H"),
            "low": q.get("Low") or q.get("AdjustmentLow") or q.get("AdjL") or q.get("L"),
            "close": q.get("Close") or q.get("AdjustmentClose") or q.get("AdjC") or q.get("C"),
            "volume": q.get("Volume") or q.get("TurnoverValue") or q.get("Vo") or q.get("AdjVo"),
        })

    # Put primary data source first, Yahoo (live quote supplement) last
    if _yahoo_used:
        sources_used.append("Yahoo Finance")

    # Build source details
    sd = {}
    for s in sources_used:
        if s == "J-Quants":
            sd["J-Quants"] = {"type": "api", "desc": f"J-Quants Daily Quotes API — {stock_code}"}
        elif s == "Stooq":
            sd["Stooq"] = {"type": "link", "desc": f"Stooq Historical Prices — {stock_code}", "url": f"https://stooq.pl/q/?s={stock_code}.jp"}
        elif s == "Yahoo Finance":
            sd["Yahoo Finance"] = {"type": "link", "desc": f"Yahoo Finance Live Quote — {stock_code}.T", "url": f"https://finance.yahoo.com/quote/{stock_code}.T/"}

    return json.dumps({"summary": summary, "recent_prices": compact, "_sources": sources_used, "_source_details": sd})


def _safe_equity_ratio(val):
    """Convert equity ratio to percentage safely. J-Quants returns as decimal (<1) or percentage (>1)."""
    if val is None or val == "":
        return None
    try:
        v = float(val)
        return round(v * 100, 1) if v < 1 else round(v, 1)
    except (ValueError, TypeError):
        return None


def _fmt_yen(val) -> str | None:
    """Format a yen amount into readable form: ¥1.2T, ¥340B, ¥5.6M."""
    if val is None or val == "" or (isinstance(val, str) and val.strip() == ""):
        return None
    try:
        v = float(val)
    except (ValueError, TypeError):
        return None
    if abs(v) >= 1e12:
        return f"¥{v/1e12:,.1f}T"
    if abs(v) >= 1e9:
        return f"¥{v/1e9:,.0f}B"
    if abs(v) >= 1e6:
        return f"¥{v/1e6:,.0f}M"
    return f"¥{v:,.0f}"


def _parse_yen(s) -> float | None:
    """Parse formatted yen string back to float. '¥1.2T' → 1.2e12."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    if not isinstance(s, str):
        return None
    s = s.replace("¥", "").replace(",", "").strip()
    if not s:
        return None
    mul = 1
    if s.endswith("T"):
        mul = 1e12; s = s[:-1]
    elif s.endswith("B"):
        mul = 1e9; s = s[:-1]
    elif s.endswith("M"):
        mul = 1e6; s = s[:-1]
    try:
        return float(s) * mul
    except ValueError:
        return None


# ── Technical Analysis Helpers ──────────────────────────

def _ta_ema(data: list, period: int) -> list:
    if not data or period <= 0:
        return []
    k = 2.0 / (period + 1)
    r = [data[0]]
    for i in range(1, len(data)):
        r.append(data[i] * k + r[-1] * (1 - k))
    return r

def _ta_sma(data: list, period: int):
    if len(data) < period:
        return None
    return sum(data[-period:]) / period

def _ta_rsi(closes: list, period: int = 14):
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)

def _ta_macd(closes: list):
    if len(closes) < 35:
        return None
    ema12 = _ta_ema(closes, 12)
    ema26 = _ta_ema(closes, 26)
    ml = [ema12[i] - ema26[i] for i in range(len(closes))]
    sig = _ta_ema(ml, 9)
    hist = ml[-1] - sig[-1]
    crossover = None
    if len(ml) >= 2 and len(sig) >= 2:
        prev = ml[-2] - sig[-2]
        if prev < 0 and hist >= 0:
            crossover = "Bullish crossover"
        elif prev > 0 and hist <= 0:
            crossover = "Bearish crossover"
    return {"macd": round(ml[-1], 2), "signal": round(sig[-1], 2),
            "histogram": round(hist, 2), "bullish": hist > 0, "crossover": crossover}

def _ta_bollinger(closes: list, period: int = 20, ns: float = 2.0):
    if len(closes) < period:
        return None
    w = closes[-period:]
    sma = sum(w) / period
    std = (sum((c - sma) ** 2 for c in w) / period) ** 0.5
    upper = round(sma + ns * std, 1)
    lower = round(sma - ns * std, 1)
    width = upper - lower
    pos = round((closes[-1] - lower) / width * 100) if width > 0 else 50
    return {"upper": upper, "middle": round(sma, 1), "lower": lower,
            "position_pct": pos, "bandwidth_pct": round(width / sma * 100, 2) if sma > 0 else None}

def _ta_support_resistance(closes: list, window: int = 5):
    if len(closes) < window * 2 + 1:
        return {"support": [], "resistance": []}
    sups, ress = [], []
    for i in range(window, len(closes) - window):
        if all(closes[i] <= closes[i - j] for j in range(1, window + 1)) and \
           all(closes[i] <= closes[i + j] for j in range(1, window + 1)):
            sups.append(round(closes[i], 1))
        if all(closes[i] >= closes[i - j] for j in range(1, window + 1)) and \
           all(closes[i] >= closes[i + j] for j in range(1, window + 1)):
            ress.append(round(closes[i], 1))
    def _dd(lv):
        if not lv: return []
        lv.sort()
        out = [lv[0]]
        for v in lv[1:]:
            if abs(v - out[-1]) / out[-1] > 0.015:
                out.append(v)
        return out[-3:]
    return {"support": _dd(sups), "resistance": _dd(ress)}


def _pick_num(item: dict, keys: list):
    """Return the first non-None numeric value from item for the given keys."""
    for k in keys:
        v = item.get(k)
        if v is not None and v != "":
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return None


def _tool_get_financials(inp: dict) -> str:
    from app.services.jquants import JQuantsClient
    report_progress(20, "querying J-Quants")
    client = JQuantsClient()
    try:
        data = client.get_financials(inp["stock_code"])
    except Exception:
        return json.dumps({"error": "Financial data service temporarily rate-limited. Try again shortly."})
    report_progress(70, "processing statements")
    statements = data.get("statements") or data.get("financials") or data.get("data") or []

    if not statements:
        return json.dumps({"error": "No financial data available"})

    # Filter to actual financial statements (not forecast revisions)
    actuals = [s for s in statements if s.get("Sales") or s.get("NP") or s.get("OP")]
    if not actuals:
        actuals = statements  # fallback to all

    # Get most recent 6 periods
    actuals = actuals[-6:]
    def _safe_float(v):
        try:
            return float(v) if v else None
        except (ValueError, TypeError):
            return None

    compact = []
    for s in actuals:
        revenue = s.get("Sales") or s.get("NetSales") or s.get("Revenue")
        op_income = s.get("OP") or s.get("OperatingProfit") or s.get("OperatingIncome")
        net_income = s.get("NP") or s.get("Profit") or s.get("NetIncome")
        eps = s.get("EPS") or s.get("EarningsPerShare")
        eq_ratio = s.get("EqAR") or s.get("EquityToAssetRatio")
        period_type = s.get("CurPerType") or s.get("TypeOfCurrentPeriod") or ""
        period_end = s.get("CurPerEn") or s.get("CurFYEn") or ""
        disc_date = s.get("DiscDate") or s.get("DisclosedDate") or ""
        fy_end = s.get("CurFYEn") or ""

        # Balance sheet fields
        equity = _pick_num(s, ["Equity", "TotalEquity", "Eq", "NetAssets",
                                "EquityAttributableToOwnersOfParent"])
        total_assets = _pick_num(s, ["TotalAssets", "TA"])
        shares_out = _pick_num(s, ["ShOutFY", "IssuedShares",
                                    "NumberOfSharesIssuedAndOutstanding",
                                    "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYear"])
        treasury_shares = _pick_num(s, ["TrShFY", "TreasuryShares",
                                         "TreasurySharesFY"])
        avg_shares = _pick_num(s, ["AvgSh", "AverageShares",
                                    "WeightedAverageNumberOfSharesOutstanding"])

        # Net shares = outstanding - treasury (most accurate for BPS)
        shares = None
        if shares_out is not None and treasury_shares is not None:
            shares = shares_out - treasury_shares
        elif avg_shares is not None:
            shares = avg_shares
        elif shares_out is not None:
            shares = shares_out

        # Compute BPS (book value per share)
        bps = None
        if equity is not None and shares is not None and shares > 0:
            bps = round(equity / shares, 1)

        # Build fiscal year label (e.g., "Q1 FY2025" or "FY2024")
        fy_year = fy_end[:4] if fy_end else ""
        period_label = f"{period_type} FY{fy_year}" if fy_year else period_type

        # Calculate operating margin
        op_margin = None
        if revenue and op_income:
            try:
                op_margin = round(float(op_income) / float(revenue) * 100, 1)
            except (ValueError, ZeroDivisionError):
                pass

        # Compute ROE = net income / equity
        roe = None
        if net_income and equity and equity > 0:
            try:
                roe = round(float(net_income) / float(equity) * 100, 1)
            except (ValueError, ZeroDivisionError):
                pass

        # Compute ROA = net income / total assets
        roa = None
        if net_income and total_assets and total_assets > 0:
            try:
                roa = round(float(net_income) / float(total_assets) * 100, 2)
            except (ValueError, ZeroDivisionError):
                pass

        # Net margin
        net_margin = None
        if revenue and net_income:
            try:
                net_margin = round(float(net_income) / float(revenue) * 100, 1)
            except (ValueError, ZeroDivisionError):
                pass

        # Dividend per share
        dps = _pick_num(s, ["DPS", "DividendPerShare", "DividendPerShareAnnual",
                            "AnnualDividendPerShare"])

        # Cash flow fields (proven patterns from valuation.py)
        cfo = _pick_num(s, ["CashFlowsFromOperatingActivities", "CFO",
                            "NetCashProvidedByUsedInOperatingActivities"])
        cfi = _pick_num(s, ["CashFlowsFromInvestingActivities",
                            "NetCashProvidedByUsedInInvestingActivities"])
        capex = _pick_num(s, ["CapitalExpenditures",
                              "PurchaseOfPropertyPlantAndEquipment",
                              "PaymentsForPropertyPlantAndEquipment",
                              "PurchaseOfTangibleFixedAssets"])
        ebitda_raw = _pick_num(s, ["EBITDA"])

        # Free Cash Flow = CFO - CapEx (or CFO + CFI as fallback)
        fcf = None
        if cfo is not None and capex is not None:
            fcf = cfo - abs(capex)
        elif cfo is not None and cfi is not None:
            fcf = cfo + cfi  # CFI is typically negative

        # Synthetic EBITDA if not directly available
        ebitda = ebitda_raw
        if ebitda is None and op_income:
            op_val = _safe_float(op_income)
            if op_val is not None:
                if cfo is not None and net_income is not None:
                    ni_val = _safe_float(net_income)
                    if ni_val is not None:
                        non_cash = cfo - ni_val
                        da_estimate = non_cash * 0.7 if non_cash > 0 else 0
                        ebitda = op_val + da_estimate
                    else:
                        ebitda = op_val
                else:
                    ebitda = op_val  # conservative: EBITDA ~ OP

        # Cash conversion ratio (CFO / Net Income) — quality indicator
        cash_conversion = None
        if cfo is not None and net_income and _safe_float(net_income) and _safe_float(net_income) != 0:
            try:
                cash_conversion = round(cfo / float(net_income), 2)
            except (ValueError, ZeroDivisionError):
                pass

        # Forecast EPS/DPS
        f_eps = _pick_num(s, ["FEPS", "ForecastEPS"])
        f_dps = _pick_num(s, ["FDPS", "ForecastDPS", "ForecastDividendPerShare",
                               "ForecastAnnualDividendPerShare"])

        entry = {
            "period": period_label,
            "period_end": period_end,
            "disclosed": disc_date,
            "revenue": _fmt_yen(revenue),
            "operating_income": _fmt_yen(op_income),
            "net_income": _fmt_yen(net_income),
            "op_margin_pct": op_margin,
            "net_margin_pct": net_margin,
            "eps": round(_safe_float(eps), 1) if _safe_float(eps) is not None else None,
            "equity_ratio_pct": _safe_equity_ratio(eq_ratio),
            "roe_pct": roe,
            "roa_pct": roa,
            "total_equity": _fmt_yen(equity),
            "total_assets": _fmt_yen(total_assets),
            "shares_outstanding": int(shares) if shares else None,
            "bps": bps,
            "dps": round(_safe_float(dps), 1) if _safe_float(dps) is not None else None,
        }

        # Add cash flow fields
        if cfo is not None:
            entry["cfo"] = _fmt_yen(cfo)
            entry["_raw_cfo"] = cfo
        if capex is not None:
            entry["capex"] = _fmt_yen(abs(capex))
        if fcf is not None:
            entry["fcf"] = _fmt_yen(fcf)
        if ebitda is not None:
            entry["ebitda"] = _fmt_yen(ebitda)
        if cash_conversion is not None:
            entry["cash_conversion"] = cash_conversion

        # Add forecasts if available
        f_sales = s.get("FSales")
        f_op = s.get("FOP")
        f_np = s.get("FNP") or s.get("ForecastNetIncome")
        if f_sales:
            entry["forecast_revenue"] = _fmt_yen(f_sales)
        if f_op:
            entry["forecast_op"] = _fmt_yen(f_op)
        if f_np:
            entry["forecast_net_income"] = _fmt_yen(f_np)
        if f_eps and _safe_float(f_eps) is not None:
            entry["forecast_eps"] = round(_safe_float(f_eps), 1)
        if f_dps and _safe_float(f_dps) is not None:
            entry["forecast_dps"] = round(_safe_float(f_dps), 1)

        # Dividend payout ratio (DPS / EPS)
        if dps and eps:
            try:
                payout = round(float(dps) / float(eps) * 100, 1) if float(eps) > 0 else None
                if payout is not None:
                    entry["payout_ratio_pct"] = payout
            except (ValueError, ZeroDivisionError):
                pass

        # Net cash/debt (total assets - total equity gives liabilities, but we want cash-debt)
        # Approximate: if equity_ratio > 50%, company is likely net cash positive
        # We store raw values so Claude can compute
        if total_assets and equity:
            entry["total_liabilities"] = _fmt_yen(total_assets - equity)

        # Store raw numeric values for Claude's cross-referencing
        entry["_raw_revenue"] = _safe_float(revenue)
        entry["_raw_net_income"] = _safe_float(net_income)
        entry["_raw_equity"] = _safe_float(equity)
        entry["_raw_eps"] = _safe_float(eps)

        compact.append(entry)

    # Compute YoY growth rates between periods
    for i in range(1, len(compact)):
        cur = compact[i]
        prev = compact[i - 1]
        if cur.get("_raw_revenue") and prev.get("_raw_revenue") and prev["_raw_revenue"] > 0:
            cur["revenue_growth_yoy_pct"] = round(
                (cur["_raw_revenue"] - prev["_raw_revenue"]) / abs(prev["_raw_revenue"]) * 100, 1
            )
        if cur.get("_raw_net_income") and prev.get("_raw_net_income") and prev["_raw_net_income"] != 0:
            cur["net_income_growth_yoy_pct"] = round(
                (cur["_raw_net_income"] - prev["_raw_net_income"]) / abs(prev["_raw_net_income"]) * 100, 1
            )

    # Add summary metrics from the latest period for quick reference
    latest = compact[-1] if compact else {}
    summary = {
        "latest_period": latest.get("period"),
        "latest_revenue": latest.get("revenue"),
        "latest_net_income": latest.get("net_income"),
        "latest_eps": latest.get("eps"),
        "latest_bps": latest.get("bps"),
        "latest_roe_pct": latest.get("roe_pct"),
        "latest_roa_pct": latest.get("roa_pct"),
        "latest_op_margin_pct": latest.get("op_margin_pct"),
        "latest_equity_ratio_pct": latest.get("equity_ratio_pct"),
        "latest_dps": latest.get("dps"),
        "latest_shares_outstanding": latest.get("shares_outstanding"),
        "revenue_trend": "growing" if latest.get("revenue_growth_yoy_pct", 0) > 0 else "declining" if latest.get("revenue_growth_yoy_pct", 0) < 0 else "flat",
        "latest_cfo": latest.get("cfo"),
        "latest_fcf": latest.get("fcf"),
        "latest_ebitda": latest.get("ebitda"),
        "latest_cash_conversion": latest.get("cash_conversion"),
    }

    # Clean raw fields from output (they were only for growth calc)
    for entry in compact:
        for raw_key in ["_raw_revenue", "_raw_net_income", "_raw_equity", "_raw_eps", "_raw_cfo"]:
            entry.pop(raw_key, None)

    return json.dumps({
        "stock_code": inp["stock_code"], "periods": len(compact), "summary": summary, "statements": compact,
        "_sources": ["J-Quants"],
        "_source_details": {"J-Quants": {"type": "api", "desc": f"J-Quants Financial Statements API — {inp['stock_code']}", "periods": len(compact), "url": "https://jpx-jquants.com/"}},
    })


def _tool_search_edinet(inp: dict) -> str:
    """Search EDINET filings using concurrent scanner (fast, thorough)."""
    from app.services.edinet import EdinetClient

    report_progress(10, "connecting to EDINET")
    client = EdinetClient()
    stock_code = inp["stock_code"].strip()
    days_back = min(inp.get("days_back", 90), 365)

    report_progress(30, "searching filings")
    try:
        docs = client.latest_filings_for_code(
            stock_code=stock_code,
            days_back=days_back,
            doc_type=2,  # All document types
            max_docs=15,
        )
    except Exception:
        docs = []

    if not docs:
        return json.dumps({"error": "No EDINET filings found", "stock_code": stock_code, "days_searched": days_back})

    report_progress(70, "processing results")
    compact = []
    for d in docs[:10]:
        compact.append({
            "doc_id": d.doc_id,
            "filer_name": d.filer_name,
            "doc_type": d.doc_type,
            "doc_type_code": d.doc_type_code,
            "submit_date": d.submit_date,
            "description": d.description,
        })

    edinet_details = {
        "type": "filings",
        "desc": f"EDINET API v2 — {stock_code} ({days_back}d scan)",
        "items": [
            {"doc_id": d.doc_id, "filer": d.filer_name, "date": d.submit_date, "description": d.description or d.doc_type,
             "url": f"https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{d.doc_id}"}
            for d in docs[:10]
        ],
    }
    report_progress(95, "done")
    return json.dumps({"stock_code": stock_code, "filings_found": len(compact), "filings": compact, "_sources": ["EDINET"], "_source_details": {"EDINET": edinet_details}})


def _tool_web_search(inp: dict) -> str:
    from app.services.serp import SerpClient
    report_progress(20, "searching web")
    client = SerpClient()
    num = min(inp.get("num_results", 5), 10)
    news = inp.get("news_only", False)
    try:
        results = client.search(inp["query"], num=num, news=news)
    except Exception:
        return json.dumps({"error": "Web search temporarily unavailable"})
    report_progress(80, "processing results")

    if not results:
        return json.dumps({"error": "No search results found"})

    compact = []
    for r in results:
        compact.append({
            "title": r.title,
            "url": r.url,
            "snippet": r.snippet[:200],
            "date": r.date,
        })

    web_details = {
        "type": "links",
        "desc": f"Web search — \"{inp['query'][:50]}\"",
        "items": [{"title": r.title, "url": r.url} for r in results[:5]],
    }
    return json.dumps({"query": inp["query"], "results_count": len(compact), "results": compact, "_sources": ["Web"], "_source_details": {"Web": web_details}})


def _extract_voting_section(narrative: str) -> str:
    """Extract the voting results section from an extraordinary report narrative."""
    import re
    # Look for voting-related keywords
    markers = ["議決権行使", "議決権の行使", "議案の結果", "議案", "賛成", "承認可決", "選任"]
    best_start = -1
    for marker in markers:
        idx = narrative.find(marker)
        if idx != -1 and (best_start == -1 or idx < best_start):
            best_start = idx
    if best_start == -1:
        return ""
    # Go back a bit to capture context, then take a large chunk
    start = max(0, best_start - 200)
    return narrative[start:start + 5000]


def _tool_get_voting_results(inp: dict) -> str:
    """Search EDINET for extraordinary reports containing AGM voting results."""
    import re
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import datetime as dt
    from app.services.edinet import EdinetClient

    report_progress(10, "connecting to EDINET")
    client = EdinetClient()
    stock_code = inp["stock_code"].strip()
    days_back = min(inp.get("days_back", 400), 730)
    today = dt.date.today()

    # Step 1: Find extraordinary reports (臨時報告書) using concurrent scan
    report_progress(30, "scanning extraordinary reports")
    extraordinary = []

    def _scan_day(delta):
        date_str = (today - dt.timedelta(days=delta)).isoformat()
        try:
            day_docs = client.list_documents(date=date_str, doc_type=2)
            hits = []
            for d in day_docs:
                sec = (d.sec_code or "").strip()
                is_match = sec.startswith(stock_code) or (len(sec) >= 4 and sec[:4] == stock_code[:4])
                is_extraordinary = (
                    "臨時" in (d.doc_type or "")
                    or "臨時" in (d.description or "")
                    or (d.doc_type_code and d.doc_type_code in ("180", "185", "030", "035"))
                )
                if is_match and is_extraordinary:
                    hits.append(d)
            return hits
        except Exception:
            return []

    # Scan in concurrent batches
    BATCH_SIZE = 30
    for batch_start in range(0, days_back, BATCH_SIZE):
        if len(extraordinary) >= 5:
            break
        batch = list(range(batch_start, min(batch_start + BATCH_SIZE, days_back)))
        with ThreadPoolExecutor(max_workers=min(20, len(batch))) as pool:
            futures = {pool.submit(_scan_day, d): d for d in batch}
            for f in as_completed(futures):
                try:
                    hits = f.result()
                    extraordinary.extend(hits)
                except Exception:
                    pass

    extraordinary.sort(key=lambda d: d.submit_date or "", reverse=True)
    report_progress(60, f"found {len(extraordinary)} reports")

    if not extraordinary:
        return json.dumps({
            "error": f"No extraordinary reports (臨時報告書) found for {stock_code} in the past {days_back} days.",
            "stock_code": stock_code,
            "hint": "AGM voting results are filed as extraordinary reports. Japanese companies typically hold AGMs in June."
        })

    # Step 2: Download and extract voting data from the most recent extraordinary reports
    report_progress(80, "extracting voting data")
    for doc in extraordinary[:3]:
        try:
            narrative = client.extract_narrative_for_doc(doc.doc_id)
            if not narrative:
                continue

            # Check if this filing contains AGM voting data specifically
            # (not just any mention of 議決権 which could be in restructuring filings)
            agm_markers = ["定時株主総会", "株主総会", "決議事項", "賛成比率"]
            vote_markers = ["賛成", "反対", "棄権", "可決", "選任"]
            has_agm = any(m in narrative for m in agm_markers)
            has_votes = any(m in narrative for m in vote_markers)

            if has_agm and has_votes:
                voting_section = _extract_voting_section(narrative)
                report_progress(95, "finalizing")
                return json.dumps({
                    "stock_code": stock_code,
                    "filing": {
                        "doc_id": doc.doc_id,
                        "filer_name": doc.filer_name,
                        "doc_type": doc.doc_type,
                        "submit_date": doc.submit_date,
                        "description": doc.description,
                    },
                    "has_voting_data": True,
                    "voting_text": voting_section,
                    "all_extraordinary_count": len(extraordinary),
                    "_sources": ["EDINET"],
                    "_source_details": {"EDINET": {
                        "type": "filings",
                        "desc": f"EDINET 臨時報告書 — {stock_code} (AGM voting)",
                        "items": [{"doc_id": doc.doc_id, "filer": doc.filer_name, "date": doc.submit_date, "description": doc.description or "臨時報告書",
                                   "url": f"https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{doc.doc_id}"}],
                    }},
                })
        except Exception as e:
            logger.warning("Failed to extract voting from %s: %s", doc.doc_id, e)
            continue

    # If we found extraordinary reports but couldn't extract voting data
    report_progress(95, "finalizing")
    return json.dumps({
        "stock_code": stock_code,
        "extraordinary_reports_found": len(extraordinary),
        "filings": [
            {"doc_id": d.doc_id, "filer_name": d.filer_name, "doc_type": d.doc_type, "submit_date": d.submit_date, "description": d.description}
            for d in extraordinary[:5]
        ],
        "note": "Found extraordinary reports but could not extract structured voting data from filing narrative.",
        "_sources": ["EDINET"],
        "_source_details": {"EDINET": {
            "type": "filings",
            "desc": f"EDINET 臨時報告書 — {stock_code}",
            "items": [
                {"doc_id": d.doc_id, "filer": d.filer_name, "date": d.submit_date, "description": d.description or "臨時報告書",
                 "url": f"https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{d.doc_id}"}
                for d in extraordinary[:5]
            ],
        }},
    })


## ── Bulk AGM voting scanner ──────────────────────────────────────────────────
#
# Architecture (mirrors the 060 large-holder index):
#   1. Scans EDINET day-by-day for extraordinary reports (docTypeCode 180/185)
#   2. Downloads each filing and parses structured voting data per resolution
#   3. Filters companies where any resolution fell below the approval threshold
#   4. Returns a ranked list with the lowest approval rates first

_voting_index_lock = threading.Lock()
_voting_index: list | None = None          # flat list of extraordinary report metadata
_voting_built_at: float = 0
_voting_building: bool = False
_VOTING_SCAN_DAYS = 400                    # covers most recent AGM season (June-July)
_VOTING_INDEX_TTL = 3600                   # rebuild every hour
_voting_parsed_cache: dict = {}            # doc_id → parsed voting dict (or None)


def _build_voting_index(days: int = _VOTING_SCAN_DAYS):
    """Build index of ALL extraordinary reports on EDINET.

    Filters by docTypeCode 180 (臨時報告書) and 185 (訂正臨時報告書) only.
    Does NOT include 030/035 (annual/amended securities reports).
    """
    global _voting_index, _voting_built_at, _voting_building
    import datetime as dt
    from concurrent.futures import ThreadPoolExecutor
    import httpx

    with _voting_index_lock:
        if _voting_building:
            return
        _voting_building = True

    t0 = time.time()
    try:
        today = dt.date.today()
        all_reports: list = []
        seen: set = set()
        auth_key = settings.edinet_subscription_key or settings.edinet_api_key

        # Use connection pool sized for workers, not excessive
        with httpx.Client(
            timeout=10,
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=15),
        ) as client:
            def _fetch(delta):
                d = (today - dt.timedelta(days=delta)).strftime("%Y-%m-%d")
                try:
                    r = client.get(
                        f"{settings.edinet_base_url}/documents.json",
                        params={"date": d, "type": 2, "Subscription-Key": auth_key},
                    )
                    return r.json().get("results", []) if r.status_code == 200 else []
                except Exception:
                    return []

            # 25 workers to avoid hammering EDINET (government API)
            with ThreadPoolExecutor(max_workers=25) as pool:
                for docs in pool.map(_fetch, range(days)):
                    for doc in docs:
                        dtc = str(doc.get("docTypeCode") or "")
                        desc = (doc.get("docDescription") or "")
                        doc_type = (doc.get("docType") or "")
                        # Only 180 (臨時報告書) and 185 (訂正臨時報告書)
                        # NOT 030/035 which are annual securities reports
                        is_extraordinary = (
                            dtc in ("180", "185")
                            or "臨時" in desc
                            or "臨時" in doc_type
                        )
                        if not is_extraordinary:
                            continue
                        did = doc.get("docID")
                        if not did or did in seen:
                            continue
                        seen.add(did)
                        sec = (doc.get("secCode") or "").strip()
                        all_reports.append({
                            "doc_id": did,
                            "date": (doc.get("submitDateTime") or "")[:10],
                            "filer": doc.get("filerName") or "",
                            "sec_code": sec[:4] if len(sec) >= 4 else sec,
                            "description": desc,
                            "edinet_code": doc.get("edinetCode") or "",
                        })

        with _voting_index_lock:
            _voting_index = all_reports
            _voting_built_at = time.time()
        logger.info("EDINET voting index built: %d extraordinary reports in %.1fs",
                     len(seen), time.time() - t0)
    finally:
        _voting_building = False


def _ensure_voting_index(days: int = _VOTING_SCAN_DAYS):
    with _voting_index_lock:
        if _voting_index is not None and time.time() - _voting_built_at < _VOTING_INDEX_TTL:
            return
    _build_voting_index(days)


def _parse_voting_percentages(narrative: str) -> list[dict]:
    """Extract structured per-resolution voting data from extraordinary report text.

    EDINET extraordinary reports present voting results as flattened HTML tables.
    The typical format after text extraction is:

      賛成数(個) | 反対数(個) | 棄権数(個) | 賛成割合 | 決議の結果
      第１号議案 剰余金処分の件
      329,341                            ← for votes
      5,744                              ← against votes
      0                                  ← abstain
      98.28％                            ← approval percentage
      可決                               ← result

    For multi-candidate director elections, all candidate percentages appear
    vertically within the same resolution section.

    Returns a list of dicts with:
      - resolution, approval_pct, for_votes, against_votes, abstain_votes, result
    """
    import re
    if not narrative:
        return []

    results = []

    # ── Step 1: Find the voting results section ──
    # The actual vote data starts at section (3) which has these markers.
    # Everything before this is just resolution descriptions (no numbers).
    vote_section_markers = [
        "賛成数", "賛成割合", "決議の結果及び賛成",
        "決議事項に対する賛成", "議決権の数、当該決議事項",
    ]
    vote_start = len(narrative)  # default: use full text
    for marker in vote_section_markers:
        idx = narrative.find(marker)
        if idx != -1 and idx < vote_start:
            vote_start = idx

    voting_text = narrative[vote_start:]
    if not voting_text:
        return []

    # ── Step 1b: Find the END of the voting section ──
    # Voting tables end before narrative sections like 代表取締役の異動,
    # 経営上の重要な契約, or new numbered sections (②, ③)
    end_markers = ["代表取締役の異動", "経営上の重要な契約", "役員の異動",
                   "主要株主の異動", "\n②", "\n③", "以上"]
    vote_end = len(voting_text)
    for marker in end_markers:
        idx = voting_text.find(marker)
        if idx != -1 and idx < vote_end:
            vote_end = idx
    voting_text = voting_text[:vote_end]

    # ── Step 2: Split by resolution headers in the voting section ──
    resolution_splits = re.split(r'(第\d+号議案)', voting_text)

    seen_headers: set = set()
    for i in range(1, len(resolution_splits), 2):
        header = resolution_splits[i]  # e.g. "第１号議案"
        # Normalize header (full-width → half-width digits) for dedup
        norm_header = header
        for fw, hw in [('１','1'),('２','2'),('３','3'),('４','4'),('５','5'),
                       ('６','6'),('７','7'),('８','8'),('９','9'),('０','0')]:
            norm_header = norm_header.replace(fw, hw)
        if norm_header in seen_headers:
            continue
        seen_headers.add(norm_header)

        body = resolution_splits[i + 1] if i + 1 < len(resolution_splits) else ""
        body = body[:3000]  # generous limit for multi-candidate

        # Extract resolution title (first meaningful line)
        title_match = re.match(r'\s*(.{1,120}?)(?:\n|$)', body)
        title_text = title_match.group(1).strip() if title_match else ""
        # Clean out table noise from title
        title_text = re.sub(r'^[\s\d,.(注)（注）]+$', '', title_text).strip()
        title = f"{header} {title_text}" if title_text else header

        # ── Extract ALL explicit percentages (XX.XX% or XX.XX％) ──
        # Also handle full-width digits: ７５．３７％
        # This is the most reliable signal in real EDINET filings
        pct_matches = re.findall(r'([\d０-９]{1,3}(?:[.．][\d０-９]+)?)\s*[%％]', body)
        percentages = []
        for p in pct_matches:
            # Normalize full-width digits and decimal
            norm_p = p.replace('．', '.')
            for fw, hw in [('０','0'),('１','1'),('２','2'),('３','3'),('４','4'),
                           ('５','5'),('６','6'),('７','7'),('８','8'),('９','9')]:
                norm_p = norm_p.replace(fw, hw)
            try:
                val = float(norm_p)
            except ValueError:
                continue
            if 0 <= val <= 100:
                percentages.append(val)

        # ── Extract all 可決/否決 results ──
        result_matches = re.findall(r'(可決|否決)', body)

        # ── Helper to parse a number string (handles commas, full-width) ──
        def _parse_num(s: str) -> int | None:
            s = s.replace(',', '').replace('，', '')
            for fw, hw in [('０','0'),('１','1'),('２','2'),('３','3'),('４','4'),
                           ('５','5'),('６','6'),('７','7'),('８','8'),('９','9')]:
                s = s.replace(fw, hw)
            try:
                return int(s)
            except ValueError:
                return None

        if percentages:
            # ── Primary path: explicit percentages found ──
            # These are the most reliable data from EDINET filings.
            # Do NOT extract vote counts from standalone number lines — stray
            # digits (annotation numbers, footnote refs, etc.) produce garbage
            # like "9 / 296,490 / 0" when the real data is in the percentages.
            worst_pct = min(percentages)

            # Determine the overall result
            has_rejected = "否決" in body
            result_str = ""
            if len(result_matches) == 1:
                result_str = result_matches[0]
            elif has_rejected:
                result_str = "否決" if worst_pct < 50 else "可決"
            elif result_matches:
                result_str = result_matches[0]

            note = ""
            if len(percentages) > 1:
                note = f"worst of {len(percentages)} sub-items"

            results.append({
                "resolution": title,
                "approval_pct": round(worst_pct, 2),
                "for_votes": None,
                "against_votes": None,
                "abstain_votes": None,
                "result": result_str,
                **({"note": note} if note else {}),
            })
        else:
            # ── Fallback: no explicit percentages — try vote counts ──
            # Find standalone numbers (lines that are just numbers)
            # Use MULTILINE so ^ and $ match line boundaries without consuming \n
            num_lines = re.findall(r'^\s*([\d,，０-９]+)\s*$', body, re.MULTILINE)
            raw_counts = [_parse_num(n) for n in num_lines if _parse_num(n) is not None]

            # Filter out implausibly small numbers — for a public company on TSE,
            # vote counts (in voting rights units) are almost always > 100.
            # Single/double digit numbers are annotation refs, footnotes, etc.
            vote_counts = [c for c in raw_counts if c >= 100]

            if len(vote_counts) >= 2:
                for_v = vote_counts[0]
                against_v = vote_counts[1]
                abstain_v = vote_counts[2] if len(vote_counts) >= 3 else 0
                total = for_v + against_v + abstain_v
                approval_pct = round(for_v / total * 100, 2) if total > 0 else 0.0

                result_str = ""
                if "否決" in body:
                    result_str = "否決"
                elif "可決" in body:
                    result_str = "可決"

                results.append({
                    "resolution": title,
                    "approval_pct": approval_pct,
                    "for_votes": for_v,
                    "against_votes": against_v,
                    "abstain_votes": abstain_v,
                    "result": result_str,
                })

    # ── Fallback: no resolution headers found, try global percentage scan ──
    if not results:
        # Look for any percentage near voting keywords
        for m in re.finditer(r'(賛成[^\d]{0,30}?)(\d{1,3}(?:\.\d+)?)\s*[%％]', narrative):
            pct = float(m.group(2))
            if 0 <= pct <= 100:
                context = m.group(1).strip()
                results.append({
                    "resolution": context or "議案",
                    "approval_pct": round(pct, 2),
                    "for_votes": None, "against_votes": None, "abstain_votes": None,
                    "result": "",
                })

    return results


def _tool_scan_agm_voting(inp: dict) -> str:
    """Scan EDINET extraordinary reports across ALL companies for low AGM approval rates."""
    import datetime as dt
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.services.edinet import EdinetClient

    threshold = inp.get("threshold", 90)
    days_back = min(inp.get("days_back", 90), 730)
    max_results = min(inp.get("max_results", 20), 50)
    only_rejected = inp.get("only_rejected", False)

    report_progress(5, "building filing index")

    # Step 1: Build/use the index of all extraordinary reports
    # Always build with full range for caching; date filtering happens on candidates
    _ensure_voting_index(_VOTING_SCAN_DAYS)
    if not _voting_index:
        return json.dumps({"error": "No extraordinary reports found in EDINET.", "threshold": threshold})

    report_progress(15, f"index has {len(_voting_index)} reports")

    # Evict stale cache entries (keep max 1000 to bound memory)
    if len(_voting_parsed_cache) > 1000:
        _voting_parsed_cache.clear()

    # Step 2: Filter to only filings with a sec_code (listed companies)
    # AND within the requested date range (days_back)
    cutoff_date = (dt.date.today() - dt.timedelta(days=days_back)).isoformat()
    candidates = [r for r in _voting_index
                  if r.get("sec_code") and r.get("date", "") >= cutoff_date]
    candidates.sort(key=lambda x: x.get("date", ""), reverse=True)

    report_progress(20, f"scanning {len(candidates)} listed-company filings")

    # Step 3: Download and parse voting data concurrently
    client = EdinetClient()
    low_approval: list = []
    total = len(candidates)

    # Cap how many we download (extraordinary reports are filed for many reasons,
    # only a fraction contain AGM voting data)
    MAX_DOWNLOAD = min(total, 500)
    candidates = candidates[:MAX_DOWNLOAD]
    total = len(candidates)

    agm_markers = ["定時株主総会", "株主総会", "決議事項", "賛成比率", "賛成"]
    vote_markers = ["賛成", "反対", "棄権", "可決", "選任"]

    def _parse_one(entry: dict) -> dict | None:
        doc_id = entry["doc_id"]

        # Check cache first (dict reads are atomic under GIL)
        cached = _voting_parsed_cache.get(doc_id)
        if cached is not None or doc_id in _voting_parsed_cache:
            return cached

        try:
            narrative = client.extract_narrative_for_doc(doc_id)
            if not narrative:
                _voting_parsed_cache[doc_id] = None
                return None

            has_agm = any(m in narrative for m in agm_markers)
            has_votes = any(m in narrative for m in vote_markers)

            if not (has_agm and has_votes):
                _voting_parsed_cache[doc_id] = None
                return None

            resolutions = _parse_voting_percentages(narrative)
            if not resolutions:
                _voting_parsed_cache[doc_id] = None
                return None

            # Safe min() — filter None values, handle empty
            valid_pcts = [r["approval_pct"] for r in resolutions if r.get("approval_pct") is not None]
            if not valid_pcts:
                _voting_parsed_cache[doc_id] = None
                return None

            result = {
                "doc_id": doc_id,
                "sec_code": entry.get("sec_code", ""),
                "filer": entry.get("filer", ""),
                "date": entry.get("date", ""),
                "resolutions": resolutions,
                "min_approval": min(valid_pcts),
            }
            _voting_parsed_cache[doc_id] = result
            return result
        except Exception as e:
            logger.debug("Failed to parse voting from %s: %s", doc_id, e)
            _voting_parsed_cache[doc_id] = None
            return None

    # Process in batches with concurrent downloads
    # 8 workers to avoid overwhelming EDINET (government API with rate limits)
    BATCH = 30
    for batch_start in range(0, total, BATCH):
        batch = candidates[batch_start:batch_start + BATCH]
        pct = 20 + int(65 * min(batch_start + BATCH, total) / total)
        report_progress(pct, f"parsing filings ({min(batch_start + BATCH, total)}/{total})")

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_parse_one, entry): entry for entry in batch}
            for f in as_completed(futures):
                try:
                    result = f.result()
                    if result and result.get("min_approval") is not None:
                        if result["min_approval"] < threshold:
                            low_approval.append(result)
                except Exception:
                    pass

    # Step 4: Filter by only_rejected if requested
    if only_rejected:
        low_approval = [
            e for e in low_approval
            if any(r.get("result") == "否決" for r in e.get("resolutions", []))
        ]

    # Sort by lowest approval and deduplicate by company
    low_approval.sort(key=lambda x: x.get("min_approval", 100))

    # Deduplicate by sec_code (keep the entry with lowest approval)
    seen_codes: set = set()
    unique: list = []
    for entry in low_approval:
        sc = entry.get("sec_code", "")
        if sc and sc in seen_codes:
            continue
        seen_codes.add(sc)
        unique.append(entry)

    unique = unique[:max_results]

    report_progress(95, "finalizing")

    # Format output
    companies = []
    for entry in unique:
        lowest_res = min(entry["resolutions"], key=lambda r: r.get("approval_pct") or 100)
        companies.append({
            "stock_code": entry["sec_code"],
            "company_name": entry["filer"],
            "agm_date": entry["date"],
            "lowest_approval_pct": entry["min_approval"],
            "lowest_resolution": lowest_res.get("resolution", ""),
            "total_resolutions": len(entry["resolutions"]),
            "resolutions_below_threshold": sum(
                1 for r in entry["resolutions"]
                if r.get("approval_pct") is not None and r["approval_pct"] < threshold
            ),
            "all_resolutions": entry["resolutions"][:5],  # Top 5 resolutions
            "doc_id": entry["doc_id"],
        })

    return json.dumps({
        "threshold": threshold,
        "days_back": days_back,
        "total_extraordinary_scanned": total,
        "companies_below_threshold": len(companies),
        "companies": companies,
        "_sources": ["EDINET"],
        "_source_details": {"EDINET": {
            "type": "filings",
            "desc": f"EDINET 臨時報告書 bulk scan — {total} filings, threshold {threshold}%",
            "items": [
                {"doc_id": c["doc_id"], "filer": c["company_name"], "date": c["agm_date"],
                 "description": f"AGM approval {c['lowest_approval_pct']}%",
                 "url": f"https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{c['doc_id']}"}
                for c in companies[:10]
            ],
        }},
    })


def _is_activist_filer(filer_name: str | None, purpose: str | None) -> bool:
    """Check if a filer is a known activist or has activist-like stated purpose."""
    if not filer_name:
        return False
    import unicodedata
    name_lower = unicodedata.normalize("NFKC", filer_name).lower()
    if any(act in name_lower for act in _KNOWN_ACTIVISTS):
        return True
    if purpose and any(kw in purpose for kw in _ACTIVIST_PURPOSE_KEYWORDS):
        return True
    return False


def _translate_filer_name_fast(name: str) -> str:
    """Fast dictionary-based translation of Japanese institutional investor names.
    No LLM calls — suitable for real-time chat responses."""
    if not name:
        return name
    import unicodedata
    name = unicodedata.normalize("NFKC", name)
    if name.isascii():
        return name.strip()

    # Strip common suffixes
    for suffix in ["株式会社", "有限会社", "合同会社", "合資会社", "保険相互会社", "相互会社"]:
        name = name.replace(suffix, "").strip()

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
        "エルエルシー": "LLC", "エルエルピー": "LLP", "エルピー": "LP",
        "アンド": "&", "サービシーズ": "Services", "リサーチ": "Research",
    }
    _KNOWN_MAP = {
        "ブラックロック": "BlackRock",
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
        "ダルトン": "Dalton",
        "サード・ポイント": "Third Point",
        "エフィッシモ": "Effissimo",
        "エフィッシモ・キャピタル": "Effissimo Capital",
        "タイヨウ・ファンド": "Taiyo Fund",
        "シルチェスター": "Silchester",
        "ニューバーガー・バーマン": "Neuberger Berman",
        "マッコーリー": "Macquarie",
        "ＪＰモルガン": "JPMorgan",
        "シティグループ": "Citigroup",
        "ナビデント": "Navident",
        "ファラロン": "Farallon",
        "キャピタル・リサーチ": "Capital Research",
    }
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
        "大和証券": "Daiwa Securities",
        "大和": "Daiwa",
        "日興アセットマネジメント": "Nikko Asset Management",
        "アセットマネジメントOne": "Asset Management One",
        "りそな": "Resona",
        "日本生命": "Nippon Life",
        "第一生命": "Dai-ichi Life",
        "東京海上": "Tokio Marine",
        "南青山不動産": "Minami-Aoyama Fudosan",
        "シティインデックスイレブンス": "City Index Eleventh",
    }
    # Try known investor names first (longest match wins)
    for jp, en in _KNOWN_MAP.items():
        if jp in name:
            rest = name.replace(jp, "").strip(" ・　")
            for kj, ke in _KATA_WORDS.items():
                rest = rest.replace(kj, ke)
            rest = rest.replace("・", " ").strip()
            return f"{en} {rest}".strip() if rest else en
    for jp, en in _JP_MAP.items():
        if jp in name:
            rest = name.replace(jp, "").strip(" ・　")
            for kj, ke in _KATA_WORDS.items():
                rest = rest.replace(kj, ke)
            rest = rest.replace("・", " ").strip()
            return f"{en} {rest}".strip() if rest else en
    # Generic katakana replacement
    result = name
    for kj, ke in _KATA_WORDS.items():
        result = result.replace(kj, ke)
    result = result.replace("・", " ").strip()
    if result != name:
        return result
    return name


def _translate_purpose_fast(purpose: str | None) -> str | None:
    """Fast dictionary-based translation of 保有目的 (holding purpose)."""
    if not purpose:
        return None
    for jp, en in _PURPOSE_EN_MAP.items():
        if jp in purpose:
            return en
    return purpose


## ── Shared EDINET 大量保有 index ──────────────────────────────────────────────
#
# Architecture:
#   1. On server startup, a background thread pre-builds the index (~4s)
#   2. Index maps issuerEdinetCode → filings and secCode → edinetCode
#   3. All subsequent queries are instant O(1) dict lookups
#   4. Auto-refreshes every hour in background (never blocks a query)
#   5. Uses httpx.Client with connection pooling (reuses TCP connections)

_060_index_lock = threading.Lock()
_060_index: dict | None = None          # issuer_edinet_code → [filing dicts]
_060_sec_to_edinet: dict | None = None  # sec_code → set of edinet codes
_060_all_060: list | None = None        # flat list of ALL 060 filings (for fund search)
_060_built_at: float = 0
_060_result_cache: dict = {}            # stock_code → (timestamp, json_str)
_060_building: bool = False             # prevents concurrent builds
_060_INDEX_TTL = 3600                   # rebuild index every hour
_060_RESULT_TTL = 1800                  # cache per-stock results for 30 min
_060_SCAN_DAYS = 365


def _build_060_index(days: int = _060_SCAN_DAYS):
    """Build the 大量保有 index using connection-pooled HTTP."""
    global _060_index, _060_sec_to_edinet, _060_all_060, _060_built_at, _060_building
    import datetime as dt
    from concurrent.futures import ThreadPoolExecutor
    import httpx

    with _060_index_lock:
        if _060_building:
            return  # another thread is already building
        _060_building = True

    try:
        today = dt.date.today()
        sec_map: dict = {}
        filings: dict = {}
        all_060: list = []
        seen: set = set()
        auth_key = settings.edinet_subscription_key or settings.edinet_api_key

        # Single httpx.Client with connection pooling — reuses TCP connections
        # across all 90 requests instead of opening 90 separate connections
        with httpx.Client(
            timeout=10,
            limits=httpx.Limits(max_connections=60, max_keepalive_connections=30),
        ) as client:
            def _fetch(delta):
                d = (today - dt.timedelta(days=delta)).strftime("%Y-%m-%d")
                try:
                    r = client.get(
                        f"{settings.edinet_base_url}/documents.json",
                        params={"date": d, "type": 2, "Subscription-Key": auth_key},
                    )
                    return r.json().get("results", []) if r.status_code == 200 else []
                except Exception:
                    return []

            with ThreadPoolExecutor(max_workers=50) as pool:
                for docs in pool.map(_fetch, range(days)):
                    for doc in docs:
                        sc = doc.get("secCode") or ""
                        ec = doc.get("edinetCode") or ""
                        if sc and ec:
                            sec_map.setdefault(sc, set()).add(ec)
                        if (doc.get("ordinanceCode") or "") == "060":
                            did = doc.get("docID")
                            if did and did not in seen:
                                seen.add(did)
                                issuer = doc.get("issuerEdinetCode") or ""
                                entry = {
                                    "date": (doc.get("submitDateTime") or "")[:10],
                                    "filer_jp": doc.get("filerName") or "",
                                    "type": doc.get("docDescription") or "",
                                    "doc_id": did,
                                    "doc_type_code": str(doc.get("docTypeCode") or ""),
                                    "issuer_edinet": issuer,
                                    "issuer_name": doc.get("issuerName") or "",
                                    "sec_code": doc.get("secCode") or "",
                                }
                                filings.setdefault(issuer, []).append(entry)
                                all_060.append(entry)

        with _060_index_lock:
            _060_index = filings
            _060_sec_to_edinet = sec_map
            _060_all_060 = all_060
            _060_built_at = time.time()
            _060_result_cache.clear()
        logger.info("EDINET 060 index built: %d filings, %d sec_codes in %.1fs",
                     len(seen), len(sec_map), time.time() - _060_built_at)
    finally:
        _060_building = False


def _ensure_060_index(days: int = _060_SCAN_DAYS):
    """Ensure the index is ready. Returns immediately if already built."""
    with _060_index_lock:
        if _060_index is not None and time.time() - _060_built_at < _060_INDEX_TTL:
            return
    _build_060_index(days)


def warm_060_index():
    """Call from server startup to pre-build the index in background."""
    t = threading.Thread(target=_build_060_index, daemon=True)
    t.start()
    logger.info("EDINET 060 index warming started in background")


def _tool_get_large_shareholders(inp: dict) -> str:
    """Search EDINET for 大量保有報告書 filed ABOUT a given company.

    Uses a shared in-memory index (built once, reused for ~1 hour).
    First call: ~3-5s to build index.  Subsequent calls: instant lookup.
    """
    import time as _time
    import unicodedata
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.services.edinet import EdinetClient

    stock_code = inp["stock_code"].strip()

    # Check result cache first (instant)
    cached = _060_result_cache.get(stock_code)
    if cached and _time.time() - cached[0] < _060_RESULT_TTL:
        report_progress(100, "cached")
        return cached[1]

    report_progress(10, "connecting to EDINET")
    edinet = EdinetClient()
    days_back = min(inp.get("days_back", 365), 730)

    # Build/reuse the shared index
    report_progress(20, "building index")
    _ensure_060_index(max(days_back, _060_SCAN_DAYS))
    report_progress(50, "searching filings")

    # Lookup: sec_code → edinet_codes → filings (instant)
    sec_code = f"{stock_code}0"
    target_codes = set()
    with _060_index_lock:
        target_codes = _060_sec_to_edinet.get(sec_code, set()).copy() if _060_sec_to_edinet else set()

    filings = []
    with _060_index_lock:
        if _060_index:
            for ec in target_codes:
                filings.extend(_060_index.get(ec, []))
    filings.sort(key=lambda x: x.get("date", ""), reverse=True)
    report_progress(60, f"found {len(filings)} filings")

    if not filings:
        result = json.dumps({
            "stock_code": stock_code,
            "filings_found": 0,
            "filings": [],
            "note": f"No 大量保有報告書 (5% rule filings) found for {stock_code} in the past {days_back} days. This means no investor holds 5%+ and filed recently — but the company STILL has major shareholders.",
            "action_required": "You MUST now call web_search to find the top shareholder list. Search for the company's 大株主 (top shareholders) from their annual report or Kabutan/Yahoo Finance Japan. The user expects to see WHO owns this stock.",
            "_sources": ["EDINET"],
            "_source_details": {"EDINET": {"type": "api", "desc": f"EDINET API v2 — 大量保有 scan for {stock_code} ({days_back}d)", "url": "https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx"}},
        })
        _060_result_cache[stock_code] = (_time.time(), result)
        return result

    # Parse top filings for stake details (parallel)
    top_filings = filings[:6]

    def _parse_one(doc):
        doc_id = doc.get("doc_id") or ""
        details = edinet.extract_large_holder_details(doc_id) if doc_id else {}
        filer_jp = unicodedata.normalize("NFKC", doc.get("filer_jp") or "")
        purpose_jp = details.get("purpose")
        filer_en = _translate_filer_name_fast(filer_jp)
        purpose_en = _translate_purpose_fast(purpose_jp)

        stake = details.get("stake_pct")
        prev_stake = details.get("prev_stake_pct")
        sold = False

        # Disposal detection: current stake near zero but previous was large
        if stake is not None and stake < 0.5 and prev_stake and prev_stake >= 3.0:
            stake = prev_stake
            sold = True

        return {
            "filer": filer_en or filer_jp,
            "filer_jp": filer_jp,
            "stake_pct": stake,
            "prev_stake_pct": prev_stake,
            "date": doc.get("date") or "",
            "purpose": purpose_en or purpose_jp,
            "is_activist": _is_activist_filer(filer_jp, purpose_jp),
            "is_sold": sold,
            "doc_type": doc.get("type") or "",
            "doc_id": doc_id,
        }

    report_progress(65, "parsing filing details")
    parsed = []
    total_to_parse = len(top_filings)
    parsed_count = 0
    with ThreadPoolExecutor(max_workers=min(8, len(top_filings))) as pool:
        futs = {pool.submit(_parse_one, f): f for f in top_filings}
        for fut in as_completed(futs):
            try:
                r = fut.result()
                if r:
                    parsed.append(r)
            except Exception:
                pass
            parsed_count += 1
            report_progress(65 + int(30 * parsed_count / max(total_to_parse, 1)), f"parsed {parsed_count}/{total_to_parse}")

    # Sort by date descending
    parsed.sort(key=lambda x: x.get("date", ""), reverse=True)

    # Deduplicate: keep only most recent filing per filer
    seen_filers: set = set()
    unique: list = []
    for f in parsed:
        key = f["filer"].lower().strip()
        if key in seen_filers:
            continue
        seen_filers.add(key)
        unique.append(f)

    activist_count = sum(1 for f in unique if f.get("is_activist"))

    edinet_details = {
        "type": "filings",
        "desc": f"EDINET 大量保有報告書 — {stock_code} ({len(filings)} total, {days_back}d scan)",
        "items": [
            {"doc_id": f["doc_id"], "filer": f["filer"], "date": f["date"],
             "description": f.get("doc_type") or "大量保有報告書",
             "url": f"https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{f['doc_id']}"}
            for f in unique[:8]
        ],
    }

    report_progress(95, "finalizing")
    result = json.dumps({
        "stock_code": stock_code,
        "filings_found": len(filings),
        "unique_filers": len(unique),
        "activist_count": activist_count,
        "has_activist": activist_count > 0,
        "holders": unique[:8],
        "_sources": ["EDINET"],
        "_source_details": {"EDINET": edinet_details},
    })
    _060_result_cache[stock_code] = (_time.time(), result)
    return result


def _tool_search_fund_holdings(inp: dict) -> str:
    """Search EDINET for all 大量保有報告書 filed BY a specific fund/investor.

    Scans EDINET daily listings for ordinanceCode "060" filings where the
    filer name matches the given fund. Returns all target companies the fund
    holds 5%+ stakes in, with stake details.
    """
    import unicodedata
    from concurrent.futures import ThreadPoolExecutor, as_completed

    fund_name = inp["fund_name"].strip()

    # Build search variants: English, Japanese katakana, lowercase
    fund_lower = fund_name.lower()
    search_variants = {fund_lower}

    _NAME_MAP = {
        "oasis": ["オアシス", "oasis management"],
        "elliott": ["エリオット", "elliott management", "elliott advisors"],
        "dalton": ["ダルトン", "dalton investments"],
        "strategic capital": ["ストラテジック・キャピタル", "strategic capital inc"],
        "effissimo": ["エフィッシモ", "effissimo capital"],
        "third point": ["サード・ポイント", "third point llc"],
        "valueact": ["バリューアクト", "valueact capital"],
        "taiyo": ["タイヨウ", "taiyo pacific", "taiyo fund"],
        "cerberus": ["cerberus capital"],
        "nippon active": ["nippon active value", "nippon active value fund"],
        "murakami": ["村上", "m&a consulting", "reno", "c&i holdings", "南青山不動産", "シティインデックスイレブンス"],
        "city index": ["シティインデックスイレブンス", "city index eleventh"],
        "acs": ["acs capital"],
        "lim": ["lim advisors"],
    }
    for key, variants in _NAME_MAP.items():
        if key in fund_lower or fund_lower in key:
            for v in variants:
                search_variants.add(v.lower())
    search_variants.add(unicodedata.normalize("NFKC", fund_name).lower())

    def _filer_matches(filer_name: str) -> bool:
        if not filer_name:
            return False
        filer_norm = unicodedata.normalize("NFKC", filer_name).lower()
        return any(variant in filer_norm for variant in search_variants)

    # Use the shared 060 index (instant if already built)
    import datetime as _dt
    days_back = min(inp.get("days_back", 730), 730)
    cutoff_date = (_dt.date.today() - _dt.timedelta(days=days_back)).isoformat()

    report_progress(10, "building fund index")
    _ensure_060_index(max(days_back, _060_SCAN_DAYS))

    report_progress(40, "searching holdings")
    matched_filings: list = []
    with _060_index_lock:
        if _060_all_060:
            matched_filings = [
                f for f in _060_all_060
                if _filer_matches(f.get("filer_jp", "")) and (f.get("date", "") >= cutoff_date)
            ]

    # Remap field names to match expected format
    matched_filings = [{
        "date": f.get("date", ""),
        "filer_jp": f.get("filer_jp", ""),
        "doc_description": f.get("type", ""),
        "doc_id": f.get("doc_id", ""),
        "issuer_edinet_code": f.get("issuer_edinet", ""),
        "issuer_name": f.get("issuer_name", ""),
        "sec_code": f.get("sec_code", ""),
    } for f in matched_filings]

    matched_filings.sort(key=lambda x: x.get("date", ""), reverse=True)
    report_progress(60, f"found {len(matched_filings)} filings")

    if not matched_filings:
        return json.dumps({
            "fund_name": fund_name,
            "filings_found": 0,
            "holdings": [],
            "note": f"No 大量保有報告書 found filed by '{fund_name}' in the past {days_back} days. Try web_search for '{fund_name} Japan holdings positions' for additional sources.",
            "_sources": ["EDINET"],
        })

    # Parse each filing for stake details (parallel, limited to top 15)
    report_progress(80, "parsing details")
    from app.services.edinet import EdinetClient
    edinet = EdinetClient()
    top_filings = matched_filings[:15]

    def _parse_one(doc):
        doc_id = doc.get("doc_id") or ""
        details = edinet.extract_large_holder_details(doc_id) if doc_id else {}
        filer_jp = unicodedata.normalize("NFKC", doc.get("filer_jp") or "")
        filer_en = _translate_filer_name_fast(filer_jp)
        issuer = doc.get("issuer_name") or ""
        issuer_en = _translate_filer_name_fast(issuer)
        sec_code = (doc.get("sec_code") or "")[:4]

        return {
            "target_company": issuer_en or issuer,
            "target_company_jp": issuer,
            "stock_code": sec_code,
            "filer": filer_en or filer_jp,
            "stake_pct": details.get("stake_pct"),
            "prev_stake_pct": details.get("prev_stake_pct"),
            "date": doc.get("date") or "",
            "purpose": _translate_purpose_fast(details.get("purpose")),
            "doc_type": doc.get("doc_description") or "大量保有報告書",
            "doc_id": doc_id,
        }

    parsed = []
    total_to_parse = len(top_filings)
    parsed_count = 0
    with ThreadPoolExecutor(max_workers=min(8, total_to_parse)) as pool:
        futs = {pool.submit(_parse_one, f): f for f in top_filings}
        for fut in as_completed(futs):
            parsed_count += 1
            try:
                result = fut.result()
                if result:
                    parsed.append(result)
            except Exception:
                pass
            report_progress(80 + int(15 * parsed_count / max(total_to_parse, 1)), f"parsed {parsed_count}/{total_to_parse}")

    parsed.sort(key=lambda x: x.get("date", ""), reverse=True)

    # Deduplicate: keep most recent filing per target company
    seen_targets: set = set()
    unique: list = []
    for p in parsed:
        key = (p.get("stock_code") or p.get("target_company_jp") or "").lower()
        if key in seen_targets:
            continue
        seen_targets.add(key)
        unique.append(p)

    # Sort by stake descending (biggest positions first)
    unique.sort(key=lambda x: x.get("stake_pct") or 0, reverse=True)

    report_progress(95, "finalizing")
    return json.dumps({
        "fund_name": fund_name,
        "filings_found": len(matched_filings),
        "unique_positions": len(unique),
        "holdings": unique[:10],
        "_sources": ["EDINET"],
        "_source_details": {"EDINET": {
            "type": "filings",
            "desc": f"EDINET 大量保有報告書 filed by {fund_name} ({len(matched_filings)} total, {_060_SCAN_DAYS}d scan)",
            "items": [
                {"doc_id": p["doc_id"], "filer": p["filer"], "date": p["date"],
                 "description": f"{p['target_company']} — {p.get('doc_type', '')}",
                 "url": f"https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{p['doc_id']}"}
                for p in unique[:10]
            ],
        }},
    })


def _parse_shareholders_from_html(html_bytes: bytes) -> list:
    """Parse 大株主の状況 table from pre-downloaded HTML bytes."""
    import re
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_bytes, "html.parser")

    _SECTION_KW = ["大株主の状況", "大株主", "主要株主", "主要な株主"]
    _EXCLUDE_KW = ["大株主の異動", "自己株式", "ストック"]

    target_table = None
    for tag in soup.find_all(["p", "div", "span", "h1", "h2", "h3", "h4", "h5", "h6", "b", "strong"]):
        tag_text = tag.get_text(strip=True)
        if not any(kw in tag_text for kw in _SECTION_KW):
            continue
        if any(kw in tag_text for kw in _EXCLUDE_KW):
            continue
        sibling = tag.find_next("table")
        if sibling and re.search(r"\d{1,2}\.\d{1,2}", sibling.get_text()):
            target_table = sibling
            break

    if not target_table:
        for table in soup.find_all("table"):
            header_text = " ".join(th.get_text(strip=True) for th in table.find_all("th"))
            table_text = table.get_text()
            combined = header_text + " " + table_text
            if not any(kw in combined for kw in ["株主名", "大株主", "所有株式数", "持株比率"]):
                continue
            if not re.search(r"\d{1,3}(?:\.\d{1,2})?", table_text):
                continue
            data_rows = [r for r in table.find_all("tr") if r.find("td")]
            if len(data_rows) < 3:
                continue
            target_table = table
            break

    if not target_table:
        return []

    rows = target_table.find_all("tr")
    name_col = shares_col = pct_col = None

    for row in rows:
        cells = row.find_all(["th", "td"])
        for ci, cell in enumerate(cells):
            ct = cell.get_text(strip=True)
            if any(k in ct for k in ["氏名", "株主名", "名称"]) and name_col is None:
                name_col = ci
            elif any(k in ct for k in ["所有株式数", "保有株数", "持株数", "株式数"]) and shares_col is None:
                shares_col = ci
            elif any(k in ct for k in ["持株比率", "比率", "割合", "所有割合"]) and pct_col is None:
                pct_col = ci
        if name_col is not None and pct_col is not None:
            break

    results = []
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        raw_name = cells[name_col].get_text(strip=True) if name_col is not None and name_col < len(cells) else cells[0].get_text(strip=True)
        if not raw_name or any(k in raw_name for k in ["氏名", "株主名", "名称", "合計", "計", "自己名義", "他人名義", "所有者", "発行済"]):
            continue
        if len(raw_name) < 2 or len(raw_name) > 60:
            continue

        pct_val = None
        if pct_col is not None and pct_col < len(cells):
            m = re.search(r"(\d{1,3}(?:\.\d{1,2})?)", cells[pct_col].get_text(strip=True))
            if m:
                v = float(m.group(1))
                if 0 < v <= 100:
                    pct_val = v
        if pct_val is None:
            for cell in reversed(cells):
                m = re.search(r"(\d{1,3}(?:\.\d{1,2})?)", cell.get_text(strip=True))
                if m:
                    v = float(m.group(1))
                    if 0.1 <= v <= 99:
                        pct_val = v
                        break
        if pct_val is None:
            continue

        shares_str = cells[shares_col].get_text(strip=True) if shares_col is not None and shares_col < len(cells) else None
        results.append({"name": raw_name, "name_jp": raw_name, "pct": pct_val, "shares": shares_str})

    merged = {}
    for item in results:
        key = item["name"]
        if key not in merged or item["pct"] > merged[key]["pct"]:
            merged[key] = item
    return sorted(merged.values(), key=lambda x: x["pct"], reverse=True)[:20]


def _parse_ownership_from_html(html_bytes: bytes) -> dict:
    """Parse 所有者別状況 table from pre-downloaded HTML bytes."""
    import re
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_bytes, "html.parser")

    _CATEGORY_MAP = {
        "政府": "government", "地方公共団体": "government",
        "金融機関": "institutional", "金融商品取引業者": "securities_firms",
        "その他の法人": "corporate", "外国法人等": "foreign", "外国人": "foreign",
        "個人その他": "individual", "個人": "individual",
    }

    target_table = None
    for table in soup.find_all("table"):
        preceding_text = ""
        for sibling in table.previous_siblings:
            text = getattr(sibling, "get_text", lambda: str(sibling))()
            preceding_text = text + preceding_text
            if len(preceding_text) > 2000:
                break
        combined = preceding_text + table.get_text()
        if "所有者別" not in combined:
            continue
        if not any(kw in table.get_text() for kw in _CATEGORY_MAP):
            continue
        if re.search(r"\d{1,3}\.\d{1,2}", table.get_text()):
            target_table = table
            break

    if not target_table:
        return {}

    result = {"foreign": None, "institutional": None, "corporate": None, "individual": None, "government": None, "securities_firms": None}
    rows = target_table.find_all("tr")

    pct_col_idx = None
    for row in rows:
        cells = row.find_all(["th", "td"])
        for ci, cell in enumerate(cells):
            if any(kw in cell.get_text(strip=True) for kw in ["比率", "割合", "%", "％"]):
                pct_col_idx = ci
                break
        if pct_col_idx is not None:
            break

    for row in rows:
        cells = row.find_all(["td", "th"])
        row_text = row.get_text()
        matched_key = None
        for jp_label, key in _CATEGORY_MAP.items():
            if jp_label in row_text:
                matched_key = key
                break
        if not matched_key:
            continue
        if pct_col_idx is not None and pct_col_idx < len(cells):
            m = re.search(r"(\d{1,3}\.\d{1,2})", cells[pct_col_idx].get_text().strip())
            if m:
                val = float(m.group(1))
                if 0 < val <= 100:
                    result[matched_key] = val
                    continue
        for cell in reversed(cells):
            m = re.search(r"(\d{1,3}\.\d{1,2})", cell.get_text().strip())
            if m:
                val = float(m.group(1))
                if 0 < val <= 100:
                    result[matched_key] = val
                    break

    if any(v is not None and v > 0 for v in result.values()):
        return result
    return {}


def _tool_get_shareholder_structure(inp: dict) -> str:
    """Extract full shareholder structure from the latest annual report (有価証券報告書).

    Returns:
      - top_shareholders: Named list with ownership %, shares, activist flags
      - ownership_breakdown: By category (foreign, institutional, corporate, individual, government)
    """
    import unicodedata
    from app.services.edinet import EdinetClient

    report_progress(10, "connecting to EDINET")
    client = EdinetClient()
    stock_code = inp["stock_code"].strip()
    days_back = min(inp.get("days_back", 400), 730)

    # Find the latest annual report (doc_type_code 120 = 有価証券報告書)
    report_progress(20, "searching annual reports")
    try:
        docs = client.latest_filings_for_code(
            stock_code=stock_code,
            days_back=days_back,
            doc_type=2,
            max_docs=20,
        )
    except Exception:
        docs = []
    report_progress(35, f"found {len(docs)} filings")

    # Prefer annual reports (120), then quarterly (130)
    annual = [d for d in docs if str(d.doc_type_code) == "120"]
    if not annual:
        annual = [d for d in docs if str(d.doc_type_code) in ("130", "140", "160")]
    if not annual:
        # Fallback: any filing that looks like it has shareholder data
        annual = [d for d in docs if "有価証券" in (d.doc_type or "") or "報告書" in (d.doc_type or "")]

    if not annual:
        return json.dumps({
            "stock_code": stock_code,
            "error": f"No annual report found for {stock_code} in {days_back} days",
            "note": "Try calling get_large_shareholders for 5%+ holders, or web_search for shareholder info.",
            "_sources": ["EDINET"],
        })

    target_doc = annual[0]
    doc_id = target_doc.doc_id

    # Download the XBRL zip ONCE, then search ALL HTML files for the data
    report_progress(45, "downloading XBRL filing")
    shareholders = []
    ownership = {}
    try:
        zip_bytes = client.download_xbrl_zip(doc_id)
    except Exception:
        zip_bytes = b""
    report_progress(65, "parsing shareholder data")

    if zip_bytes:
        import io as _io, zipfile as _zf
        try:
            with _zf.ZipFile(_io.BytesIO(zip_bytes)) as zf:
                # Get all HTML files from the zip, sorted by name (section order)
                htmls = sorted([n for n in zf.namelist() if n.lower().endswith((".htm", ".html", ".xhtml"))])
                total_htmls = len(htmls)
                for hi, html_name in enumerate(htmls):
                    try:
                        html_bytes = zf.read(html_name)
                    except Exception:
                        continue
                    if not html_bytes:
                        continue
                    text_peek = html_bytes.decode("utf-8", errors="replace")

                    # Extract shareholders if not found yet
                    if not shareholders and ("大株主" in text_peek or "株主名" in text_peek or "持株比率" in text_peek):
                        try:
                            shareholders = _parse_shareholders_from_html(html_bytes)
                        except Exception:
                            pass

                    # Extract ownership breakdown if not found yet
                    if (not ownership or not any(v is not None for v in ownership.values())) and "所有者別" in text_peek:
                        try:
                            ownership = _parse_ownership_from_html(html_bytes)
                        except Exception:
                            pass

                    report_progress(65 + int(25 * (hi + 1) / max(total_htmls, 1)), f"scanning page {hi+1}/{total_htmls}")
                    # Stop early if we found both
                    if shareholders and ownership and any(v is not None for v in ownership.values()):
                        break
        except Exception:
            pass

        # Fallback: try XBRL-based ownership extraction
        if not ownership or not any(v is not None for v in ownership.values()):
            report_progress(90, "extracting XBRL ownership")
            try:
                ownership = client.extract_ownership_xbrl(doc_id)
            except Exception:
                ownership = {}

    report_progress(95, "translating names")
    # Translate shareholder names and flag activists
    translated_holders = []
    for sh in shareholders:
        name_jp = unicodedata.normalize("NFKC", sh.get("name_jp") or sh.get("name") or "")
        name_en = _translate_filer_name_fast(name_jp)
        is_activist = _is_activist_filer(name_jp, "")
        translated_holders.append({
            "name": name_en or name_jp,
            "name_jp": name_jp,
            "pct": sh.get("pct"),
            "shares": sh.get("shares"),
            "is_activist": is_activist,
        })

    activist_holders = [h for h in translated_holders if h.get("is_activist")]

    # Format ownership breakdown
    ownership_formatted = {}
    if ownership:
        for k, v in ownership.items():
            if v is not None:
                ownership_formatted[k] = round(v, 2)

    edinet_details = {
        "type": "filings",
        "desc": f"有価証券報告書 — shareholder structure for {stock_code}",
        "items": [{
            "doc_id": doc_id,
            "filer": target_doc.filer_name,
            "date": target_doc.submit_date,
            "description": target_doc.doc_type or "有価証券報告書",
            "url": f"https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{doc_id}",
        }],
    }

    return json.dumps({
        "stock_code": stock_code,
        "filing": {
            "doc_id": doc_id,
            "filer_name": target_doc.filer_name,
            "submit_date": target_doc.submit_date,
            "doc_type": target_doc.doc_type,
        },
        "top_shareholders": translated_holders,
        "shareholder_count": len(translated_holders),
        "activist_shareholders": [h["name"] for h in activist_holders],
        "has_activists_in_top_holders": len(activist_holders) > 0,
        "ownership_breakdown": ownership_formatted,
        "_sources": ["EDINET"],
        "_source_details": {"EDINET": edinet_details},
    })


def _tool_get_directors(inp: dict) -> str:
    import os
    cache_path = os.path.join("cache", "directors", f"{inp['stock_code']}.json")
    data = None

    # Try cache first
    report_progress(15, "checking cache")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            data = json.load(f)
        report_progress(80, "loaded from cache")

    # If no cache, call the real directors API (full pipeline)
    if data is None:
        report_progress(20, "fetching from EDINET")
        try:
            from app.services.directors import get_director_network
            company_name = inp.get("company_name", inp["stock_code"])
            data = get_director_network(inp["stock_code"], company_name)
        except Exception as e:
            logger.warning("Director fetch failed for %s: %s", inp["stock_code"], e)
            return json.dumps({
                "error": f"Could not fetch director data for {inp['stock_code']}. The research pipeline may take time for first lookup.",
                "stock_code": inp["stock_code"]
            })

    directors = data.get("directors", [])
    summary = data.get("boardSummary", {})
    compact_directors = []
    for d in directors:
        compact_directors.append({
            "name": d.get("nameEn"),
            "role": d.get("role"),
            "type": d.get("type"),
            "independent": d.get("isIndependent"),
            "nationality": d.get("nationality"),
            "gender": d.get("gender"),
            "expertise": d.get("expertise"),
            "committees": d.get("committees"),
        })

    return json.dumps({
        "stock_code": inp["stock_code"],
        "board_summary": summary,
        "directors": compact_directors,
        "_sources": ["EDINET"] if data else [],
        "_source_details": {"EDINET": {"type": "api", "desc": f"Board composition — {inp['stock_code']}", "url": "https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx"}} if data else {},
    })


# ── Technical Analysis Tool ────────────────────────────────

def _tool_analyze_technicals(inp: dict) -> str:
    """Full technical analysis computed from price data."""
    stock_code = inp["stock_code"].strip()
    report_progress(15, "fetching 250-day prices")
    price_str = _dispatch_tool("get_stock_prices", {"stock_code": stock_code, "days": 250})
    report_progress(50, "computing indicators")
    pd = json.loads(price_str)
    if "error" in pd:
        return json.dumps({"error": f"Cannot analyze: {pd['error']}"})
    prices = pd.get("recent_prices", [])
    closes = [p["close"] for p in prices if p.get("close")]
    volumes = [p.get("volume") or 0 for p in prices if p.get("close")]
    if len(closes) < 20:
        return json.dumps({"error": "Need 20+ days of price data"})
    cur = closes[-1]

    # Moving Averages
    report_progress(65, "calculating MAs + RSI")
    sma5 = _ta_sma(closes, 5)
    sma20 = _ta_sma(closes, 20)
    sma50 = _ta_sma(closes, 50)
    sma200 = _ta_sma(closes, 200)
    cross = None
    if sma50 is not None and sma200 is not None:
        cross = "Golden Cross (bullish)" if sma50 > sma200 else "Death Cross (bearish)"
    ma_pos = []
    for label, ma in [("5d", sma5), ("20d", sma20), ("50d", sma50), ("200d", sma200)]:
        if ma is not None:
            ma_pos.append({"ma": label, "value": round(ma, 1), "vs_price_pct": round((cur - ma) / ma * 100, 1)})

    # RSI
    rsi14 = _ta_rsi(closes)
    rsi_label = None
    if rsi14 is not None:
        if rsi14 >= 70: rsi_label = "OVERBOUGHT"
        elif rsi14 <= 30: rsi_label = "OVERSOLD"
        elif rsi14 >= 60: rsi_label = "Bullish"
        elif rsi14 <= 40: rsi_label = "Bearish"
        else: rsi_label = "Neutral"

    macd = _ta_macd(closes)
    bb = _ta_bollinger(closes)
    bb_label = None
    if bb:
        p = bb["position_pct"]
        if p >= 95: bb_label = "At upper band — overbought"
        elif p <= 5: bb_label = "At lower band — oversold / potential bounce"
        elif p >= 80: bb_label = "Upper zone — strong momentum"
        elif p <= 20: bb_label = "Lower zone — weakness"
        else: bb_label = "Mid-range"

    # 52-week
    n = min(250, len(closes))
    h52 = max(closes[-n:])
    l52 = min(closes[-n:])

    # Volume
    avg20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else None
    avg5 = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else None
    vol_label = None
    if avg20 and avg5 and avg20 > 0:
        r = avg5 / avg20
        if r > 2.0: vol_label = f"SURGING ({r:.1f}x avg) — strong institutional interest"
        elif r > 1.3: vol_label = f"Elevated ({r:.1f}x avg)"
        elif r < 0.6: vol_label = f"Very low ({r:.1f}x avg) — disinterest"
        elif r < 0.8: vol_label = f"Below average ({r:.1f}x avg)"
        else: vol_label = "Normal"

    sr = _ta_support_resistance(closes)

    # Overall signal scoring
    bull = bear = 0.0
    if rsi14:
        if rsi14 < 35: bull += 1.5
        elif rsi14 < 45: bull += 0.5
        elif rsi14 > 65: bear += 1.5
        elif rsi14 > 55: bear += 0.5
    if macd:
        if macd["bullish"]: bull += 1
        else: bear += 1
        if macd.get("crossover") and "Bullish" in macd["crossover"]: bull += 1
        if macd.get("crossover") and "Bearish" in macd["crossover"]: bear += 1
    if sma50 and cur > sma50: bull += 1
    elif sma50: bear += 1
    if sma200 and cur > sma200: bull += 1
    elif sma200: bear += 1
    if bb:
        if bb["position_pct"] < 20: bull += 0.5
        elif bb["position_pct"] > 80: bear += 0.5
    total = bull + bear
    score = bull / total * 100 if total > 0 else 50
    if score >= 70: signal = "STRONG BUY"
    elif score >= 55: signal = "BUY"
    elif score >= 45: signal = "NEUTRAL"
    elif score >= 30: signal = "SELL"
    else: signal = "STRONG SELL"

    return json.dumps({
        "stock_code": stock_code, "current_price": cur,
        "technical_signal": signal, "signal_strength_pct": round(score),
        "rsi": {"value": rsi14, "signal": rsi_label},
        "macd": macd, "bollinger_bands": bb, "bollinger_signal": bb_label,
        "moving_averages": ma_pos, "ma_cross": cross,
        "week_52": {"high": h52, "low": l52,
                    "from_high_pct": round((cur - h52) / h52 * 100, 1),
                    "from_low_pct": round((cur - l52) / l52 * 100, 1)},
        "volume": {"avg_20d": int(avg20) if avg20 else None,
                   "avg_5d": int(avg5) if avg5 else None, "signal": vol_label},
        "support_resistance": sr,
        "_sources": pd.get("_sources", []),
        "_source_details": pd.get("_source_details", {}),
    })


# ── Quantitative Risk Analytics Tool ──────────────────────

def _tool_analyze_risk(inp: dict) -> str:
    """Beta, Sharpe, Sortino, VaR, max drawdown, volatility — full risk profile."""
    import math
    import httpx
    stock_code = inp["stock_code"].strip()

    # 1. Get 250 days of stock prices
    price_str = _dispatch_tool("get_stock_prices", {"stock_code": stock_code, "days": 250})
    price_data = json.loads(price_str)
    if "error" in price_data:
        return json.dumps({"error": f"Cannot get price data for {stock_code}"})

    recent = price_data.get("recent_prices", [])
    if len(recent) < 30:
        return json.dumps({"error": f"Insufficient price history ({len(recent)} days). Need 30+."})

    closes = [p["close"] for p in recent if p.get("close")]
    dates = [p["date"] for p in recent if p.get("close")]
    if len(closes) < 30:
        return json.dumps({"error": "Insufficient close prices"})

    # 2. Compute log returns
    returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            returns.append(math.log(closes[i] / closes[i - 1]))

    if len(returns) < 20:
        return json.dumps({"error": "Insufficient returns data"})

    n = len(returns)
    mean_ret = sum(returns) / n
    var_ret = sum((r - mean_ret) ** 2 for r in returns) / (n - 1)
    daily_vol = math.sqrt(var_ret)
    annual_vol = daily_vol * math.sqrt(252)
    annual_ret = mean_ret * 252

    # 3. Sharpe Ratio (Japan risk-free ~0.5%)
    risk_free = 0.005
    sharpe = (annual_ret - risk_free) / annual_vol if annual_vol > 0 else 0

    # 4. Sortino Ratio (downside deviation only)
    neg_returns = [r for r in returns if r < 0]
    if neg_returns:
        downside_var = sum(r ** 2 for r in neg_returns) / len(neg_returns)
        downside_std = math.sqrt(downside_var) * math.sqrt(252)
        sortino = (annual_ret - risk_free) / downside_std if downside_std > 0 else 0
    else:
        sortino = float('inf')

    # 5. Maximum Drawdown
    peak = closes[0]
    max_dd = 0
    max_dd_peak_idx = 0
    max_dd_trough_idx = 0
    current_peak_idx = 0
    for i in range(1, len(closes)):
        if closes[i] > peak:
            peak = closes[i]
            current_peak_idx = i
        dd = (closes[i] - peak) / peak
        if dd < max_dd:
            max_dd = dd
            max_dd_peak_idx = current_peak_idx
            max_dd_trough_idx = i

    # 6. VaR (95%) — 5th percentile of daily returns
    sorted_rets = sorted(returns)
    var_idx = max(0, int(len(sorted_rets) * 0.05))
    var_95 = sorted_rets[var_idx] * 100  # as percentage

    # 7. Beta vs Nikkei 225
    beta = None
    beta_interp = "Not computed"
    try:
        nk_resp = _get_yahoo_client().get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EN225?interval=1d&range=1y",
            timeout=10,
        )
        nk_resp.raise_for_status()
        nk_data = nk_resp.json()
        nk_result = nk_data.get("chart", {}).get("result", [])
        if nk_result:
            nk_ts = nk_result[0].get("timestamp", [])
            nk_closes = nk_result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            # Build date->close map for Nikkei
            import datetime as _dt
            nk_by_date = {}
            for ts, c in zip(nk_ts, nk_closes):
                if c is not None:
                    d = _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                    nk_by_date[d] = c

            # Align returns by date
            stock_rets = []
            nk_rets = []
            for i in range(1, len(dates)):
                d = dates[i]
                d_prev = dates[i - 1]
                if d in nk_by_date and d_prev in nk_by_date and nk_by_date[d_prev] > 0 and closes[i - 1] > 0:
                    stock_rets.append(math.log(closes[i] / closes[i - 1]))
                    nk_rets.append(math.log(nk_by_date[d] / nk_by_date[d_prev]))

            if len(stock_rets) >= 20:
                mean_s = sum(stock_rets) / len(stock_rets)
                mean_n = sum(nk_rets) / len(nk_rets)
                cov = sum((s - mean_s) * (n - mean_n) for s, n in zip(stock_rets, nk_rets)) / (len(stock_rets) - 1)
                var_n = sum((n - mean_n) ** 2 for n in nk_rets) / (len(nk_rets) - 1)
                if var_n > 0:
                    beta = round(cov / var_n, 2)
                    if beta > 1.3:
                        beta_interp = "High beta — significantly more volatile than the market"
                    elif beta > 1.0:
                        beta_interp = "Above-market volatility"
                    elif beta > 0.7:
                        beta_interp = "Moderate — moves roughly with the market"
                    elif beta > 0.3:
                        beta_interp = "Low beta — defensive stock"
                    else:
                        beta_interp = "Very low beta — largely independent of market"
    except Exception:
        pass

    # 8. Risk Grade
    risk_score = 0
    if annual_vol > 0.40: risk_score += 3
    elif annual_vol > 0.30: risk_score += 2
    elif annual_vol > 0.20: risk_score += 1
    if max_dd < -0.30: risk_score += 3
    elif max_dd < -0.20: risk_score += 2
    elif max_dd < -0.10: risk_score += 1
    if beta is not None:
        if beta > 1.5: risk_score += 2
        elif beta > 1.2: risk_score += 1

    if risk_score >= 6:
        risk_grade = "Very High Risk"
    elif risk_score >= 4:
        risk_grade = "High Risk"
    elif risk_score >= 2:
        risk_grade = "Moderate Risk"
    else:
        risk_grade = "Low Risk"

    factors = []
    if annual_vol > 0.30: factors.append(f"High annualized vol ({annual_vol*100:.1f}%)")
    if max_dd < -0.20: factors.append(f"Large drawdown ({max_dd*100:.1f}%)")
    if beta and beta > 1.3: factors.append(f"High beta ({beta})")
    if sharpe < 0: factors.append("Negative risk-adjusted return")
    if not factors:
        factors.append("Within normal risk parameters")

    return json.dumps({
        "stock_code": stock_code,
        "period_days": len(closes),
        "volatility": {
            "daily_pct": round(daily_vol * 100, 2),
            "annualized_pct": round(annual_vol * 100, 1),
            "interpretation": "High" if annual_vol > 0.30 else "Moderate" if annual_vol > 0.20 else "Low",
        },
        "beta": {"value": beta, "interpretation": beta_interp} if beta is not None else {"value": None, "interpretation": "Insufficient overlapping data"},
        "sharpe_ratio": {
            "value": round(sharpe, 2),
            "interpretation": "Excellent" if sharpe > 1.5 else "Good" if sharpe > 0.5 else "Poor" if sharpe > 0 else "Negative — losing money on risk-adjusted basis",
        },
        "sortino_ratio": {"value": round(sortino, 2) if sortino != float('inf') else "N/A (no negative returns)"},
        "max_drawdown": {
            "pct": round(max_dd * 100, 1),
            "peak_date": dates[max_dd_peak_idx] if max_dd_peak_idx < len(dates) else None,
            "trough_date": dates[max_dd_trough_idx] if max_dd_trough_idx < len(dates) else None,
        },
        "var_95": {
            "daily_pct": round(var_95, 2),
            "interpretation": f"95% confidence: max daily loss ~{abs(var_95):.1f}%",
        },
        "annualized_return_pct": round(annual_ret * 100, 1),
        "risk_grade": {"grade": risk_grade, "factors": factors},
        "_sources": ["J-Quants", "Yahoo Finance"],
        "_source_details": {
            "J-Quants": {"type": "api", "desc": f"250-day price history — {stock_code}"},
            "Yahoo Finance": {"type": "api", "desc": "Nikkei 225 benchmark for beta calculation"},
        },
    })


# ── Quantitative Scoring Tool ──────────────────────────────

def _tool_score_company(inp: dict) -> str:
    """Piotroski F-Score + Value/Growth/Quality/Activist scores + Fair Value."""
    from concurrent.futures import ThreadPoolExecutor
    stock_code = inp["stock_code"].strip()
    report_progress(10, "fetching data")

    # Fetch financials + prices in parallel
    with ThreadPoolExecutor(max_workers=2) as pool:
        fin_fut = pool.submit(_dispatch_tool, "get_financials", {"stock_code": stock_code})
        price_fut = pool.submit(_dispatch_tool, "get_stock_prices", {"stock_code": stock_code, "days": 30})
        fin_str = fin_fut.result()
        price_str = price_fut.result()

    fin_data = json.loads(fin_str)
    if "error" in fin_data:
        return json.dumps({"error": f"Cannot score: {fin_data['error']}"})
    stmts = fin_data.get("statements", [])
    if len(stmts) < 2:
        return json.dumps({"error": "Need 2+ financial periods for scoring"})

    report_progress(50, "computing scores")
    price_data = json.loads(price_str)
    latest, prior = stmts[-1], stmts[-2]

    def pv(e, k):
        v = e.get(k)
        if v is None: return None
        if isinstance(v, (int, float)): return float(v)
        return _parse_yen(v)

    # Key metrics
    ni = pv(latest, "net_income"); oi = pv(latest, "operating_income")
    equity = pv(latest, "total_equity"); assets = pv(latest, "total_assets")
    rev = pv(latest, "revenue")
    eps = latest.get("eps"); bps = latest.get("bps"); roe = latest.get("roe_pct")
    roa = latest.get("roa_pct"); opm = latest.get("op_margin_pct")
    eq_ratio = latest.get("equity_ratio_pct"); shares = latest.get("shares_outstanding")
    dps = latest.get("dps"); rev_g = latest.get("revenue_growth_yoy_pct")
    ni_g = latest.get("net_income_growth_yoy_pct")
    prev_equity = pv(prior, "total_equity"); prev_assets = pv(prior, "total_assets")
    prev_rev = pv(prior, "revenue"); prev_opm = prior.get("op_margin_pct")
    prev_eq_ratio = prior.get("equity_ratio_pct"); prev_shares = prior.get("shares_outstanding")
    prev_roa = prior.get("roa_pct")

    current_price = None
    if "error" not in price_data:
        s = price_data.get("summary", {})
        current_price = s.get("live_price") or s.get("latest_close")

    # ═══ PIOTROSKI F-SCORE (0-9) ═══
    f = 0; fb = {}
    # 1 Positive NI
    fb["positive_ni"] = ni is not None and ni > 0; f += fb["positive_ni"]
    # 2 Positive ROA
    fb["positive_roa"] = roa is not None and roa > 0; f += fb["positive_roa"]
    # 3 Positive operating CF (proxy: OI > 0)
    fb["positive_opcf"] = oi is not None and oi > 0; f += fb["positive_opcf"]
    # 4 Quality: OI > NI (accruals check)
    fb["quality_earnings"] = oi is not None and ni is not None and oi > ni; f += fb["quality_earnings"]
    # 5 Lower leverage
    fb["lower_leverage"] = eq_ratio is not None and prev_eq_ratio is not None and eq_ratio > prev_eq_ratio; f += fb["lower_leverage"]
    # 6 Liquidity improving
    if equity and prev_equity and assets and prev_assets and prev_equity != 0 and prev_assets != 0:
        fb["better_liquidity"] = (equity - prev_equity) / abs(prev_equity) >= (assets - prev_assets) / abs(prev_assets)
    else:
        fb["better_liquidity"] = False
    f += fb["better_liquidity"]
    # 7 No dilution
    fb["no_dilution"] = shares is not None and prev_shares is not None and shares <= prev_shares * 1.01; f += fb["no_dilution"]
    # 8 Higher margin
    fb["higher_margin"] = opm is not None and prev_opm is not None and opm > prev_opm; f += fb["higher_margin"]
    # 9 Higher turnover
    if rev and assets and prev_rev and prev_assets and assets > 0 and prev_assets > 0:
        fb["higher_turnover"] = (rev / assets) > (prev_rev / prev_assets)
    else:
        fb["higher_turnover"] = False
    f += fb["higher_turnover"]

    if f >= 7: fl = "STRONG — High probability of outperformance"
    elif f >= 5: fl = "MODERATE — Average fundamentals"
    elif f >= 3: fl = "WEAK — Below average"
    else: fl = "VERY WEAK — High probability of underperformance"

    # ═══ VALUE SCORE (0-10) ═══
    vs = 5; vn = []; pe = pb = dy = mcap = None
    if current_price and eps and eps > 0:
        pe = round(current_price / eps, 1)
        if pe < 8: vs += 2; vn.append(f"Very low P/E ({pe}x)")
        elif pe < 12: vs += 1.5; vn.append(f"Low P/E ({pe}x)")
        elif pe < 18: vn.append(f"Fair P/E ({pe}x)")
        elif pe < 25: vs -= 1; vn.append(f"Elevated P/E ({pe}x)")
        else: vs -= 2; vn.append(f"High P/E ({pe}x)")
    if current_price and bps and bps > 0:
        pb = round(current_price / bps, 2)
        if pb < 0.5: vs += 2; vn.append(f"Deep value P/B ({pb}x)")
        elif pb < 0.8: vs += 1.5; vn.append(f"Value P/B ({pb}x)")
        elif pb < 1.0: vs += 1; vn.append(f"Below book ({pb}x)")
        elif pb < 2.0: vn.append(f"Fair P/B ({pb}x)")
        else: vs -= 1; vn.append(f"Premium P/B ({pb}x)")
    if current_price and dps and dps > 0:
        dy = round(dps / current_price * 100, 2)
        if dy > 4: vs += 1; vn.append(f"High yield ({dy}%)")
        elif dy > 2.5: vs += 0.5; vn.append(f"Good yield ({dy}%)")
    if current_price and shares:
        mcap = current_price * shares
    vs = max(0, min(10, round(vs)))

    # ═══ GROWTH SCORE (0-10) ═══
    gs = 5; gn = []
    if rev_g is not None:
        if rev_g > 20: gs += 2; gn.append(f"Strong revenue growth (+{rev_g}%)")
        elif rev_g > 10: gs += 1; gn.append(f"Solid revenue growth (+{rev_g}%)")
        elif rev_g > 0: gn.append(f"Modest revenue growth (+{rev_g}%)")
        elif rev_g > -10: gs -= 1; gn.append(f"Revenue declining ({rev_g}%)")
        else: gs -= 2; gn.append(f"Sharp revenue decline ({rev_g}%)")
    if ni_g is not None:
        if ni_g > 30: gs += 2; gn.append(f"Explosive profit growth (+{ni_g}%)")
        elif ni_g > 15: gs += 1; gn.append(f"Strong profit growth (+{ni_g}%)")
        elif ni_g > 0: gn.append(f"Profit growing (+{ni_g}%)")
        elif ni_g > -20: gs -= 1; gn.append(f"Profit declining ({ni_g}%)")
        else: gs -= 2; gn.append(f"Sharp profit decline ({ni_g}%)")
    f_eps = latest.get("forecast_eps")
    if f_eps and eps and f_eps > 0:
        prog = round(eps / f_eps * 100, 1)
        if prog > 80: gs += 1; gn.append(f"Earnings ahead of plan ({prog}% of forecast)")
        elif prog < 50: gn.append(f"Behind plan ({prog}% of forecast)")
    gs = max(0, min(10, round(gs)))

    # ═══ QUALITY SCORE (0-10) ═══
    qs = 5; qn = []
    if roe is not None:
        if roe > 15: qs += 2; qn.append(f"Excellent ROE ({roe}%)")
        elif roe > 10: qs += 1; qn.append(f"Good ROE ({roe}%)")
        elif roe > 8: qn.append(f"Adequate ROE ({roe}%) — meets TSE Prime threshold")
        elif roe > 0: qs -= 1; qn.append(f"Low ROE ({roe}%) — below 8% target")
        else: qs -= 2; qn.append(f"Negative ROE ({roe}%)")
    if opm is not None:
        if opm > 15: qs += 1; qn.append(f"High operating margin ({opm}%)")
        elif opm > 8: qn.append(f"Decent margin ({opm}%)")
        elif opm > 0: qs -= 0.5; qn.append(f"Thin margin ({opm}%)")
        else: qs -= 1.5; qn.append(f"Operating loss ({opm}%)")
    if eq_ratio is not None:
        if eq_ratio > 60: qs += 1; qn.append(f"Fortress balance sheet ({eq_ratio}% equity)")
        elif eq_ratio > 40: qn.append(f"Adequate balance sheet ({eq_ratio}% equity)")
        elif eq_ratio > 20: qs -= 0.5; qn.append(f"Leveraged ({eq_ratio}% equity)")
        else: qs -= 1; qn.append(f"Highly leveraged ({eq_ratio}% equity)")
    qs = max(0, min(10, round(qs)))

    # ═══ ACTIVIST TARGET SCORE (0-10) ═══
    at = 0; an = []
    if pb is not None and pb < 1.0:
        at += 2; an.append(f"Below book value (P/B {pb}x) — hidden asset potential")
    if roe is not None and roe < 8:
        at += 2; an.append(f"Low ROE ({roe}%) — capital efficiency target")
    if eq_ratio is not None and eq_ratio > 55:
        at += 1.5; an.append(f"Excess capital ({eq_ratio}% equity ratio)")
    payout = latest.get("payout_ratio_pct")
    if payout is not None and payout < 30:
        at += 1.5; an.append(f"Low payout ({payout}%) — cash hoarding")
    elif dps is None or dps == 0:
        at += 1; an.append("No dividend — shareholder return target")
    if mcap and mcap < 500e9:
        at += 1; an.append(f"Mid/small cap (¥{mcap / 1e9:.0f}B) — easier accumulation")
    if eq_ratio and eq_ratio > 50 and roe and roe < 6:
        at += 1; an.append("High equity + low ROE = possible cross-holdings / hidden assets")
    at = min(10, round(at))
    if at >= 7: al = "HIGH — Strong activist target profile"
    elif at >= 4: al = "MODERATE — Some activist-relevant features"
    else: al = "LOW — Unlikely activist target"

    # ═══ FAIR VALUE ESTIMATE ═══
    fv = None; fv_method = None; upside = None
    if eps and eps > 0:
        fair_pe = 12
        if qs >= 7: fair_pe += 4
        elif qs >= 5: fair_pe += 2
        elif qs < 3: fair_pe -= 3
        if gs >= 7: fair_pe += 3
        elif gs >= 5: fair_pe += 1
        elif gs < 3: fair_pe -= 2
        fair_pe = max(5, min(25, fair_pe))
        fv = round(eps * fair_pe)
        fv_method = f"Quality-Growth adjusted P/E of {fair_pe}x"
        if current_price and fv:
            upside = round((fv - current_price) / current_price * 100, 1)

    # ═══ COMPOSITE (0-100) ═══
    comp = round(f / 9 * 25 + vs / 10 * 25 + gs / 10 * 25 + qs / 10 * 25)
    if comp >= 80: cl = "EXCELLENT — Top-tier investment candidate"
    elif comp >= 65: cl = "GOOD — Above-average fundamentals"
    elif comp >= 50: cl = "FAIR — Average"
    elif comp >= 35: cl = "BELOW AVERAGE — Proceed with caution"
    else: cl = "POOR — Significant concerns"

    return json.dumps({
        "stock_code": stock_code,
        "composite_score": comp, "composite_label": cl,
        "piotroski_f_score": {"score": f, "max": 9, "label": fl, "breakdown": fb},
        "value_score": {"score": vs, "max": 10, "notes": vn},
        "growth_score": {"score": gs, "max": 10, "notes": gn},
        "quality_score": {"score": qs, "max": 10, "notes": qn},
        "activist_target": {"score": at, "max": 10, "label": al, "notes": an},
        "valuation": {"pe_ratio": pe, "pb_ratio": pb, "dividend_yield_pct": dy,
                      "market_cap": _fmt_yen(mcap) if mcap else None, "roe_pct": roe},
        "fair_value": {"estimate": fv, "method": fv_method, "upside_pct": upside,
                       "current_price": current_price},
        "_sources": list(set(fin_data.get("_sources", []) + price_data.get("_sources", []))),
        "_source_details": {**fin_data.get("_source_details", {}), **price_data.get("_source_details", {})},
    })


# ── Peer Comparison Tool ───────────────────────────────────

def _tool_get_company_peers(inp: dict) -> str:
    """Find sector peers using 3,700+ company TSE database."""
    from app.services.peer_db import PeerDatabase
    db = PeerDatabase()
    stock_code = inp["stock_code"].strip()

    # Get target company info
    info = db.get_company_info(stock_code)
    sector = db.get_sector_for_code(stock_code)
    if not sector:
        # Try lookup_company fallback
        lookup = json.loads(_dispatch_tool("lookup_company", {"stock_code": stock_code}))
        sector = lookup.get("sector")
    if not sector:
        return json.dumps({"error": f"Cannot find sector for {stock_code}"})

    peers = db.find_peers(stock_code, sector, n=10, prefer_prime=True)
    if not peers:
        return json.dumps({"error": f"No peers found in sector '{sector}'"})

    compact = []
    for p in peers:
        compact.append({
            "code": p.get("code"),
            "name": p.get("name"),
            "market": p.get("market", "").replace(" (Domestic)", "").replace("Market", "").strip(),
            "size": p.get("size", ""),
        })

    return json.dumps({
        "stock_code": stock_code,
        "company": info.get("name") if info else stock_code,
        "sector": sector,
        "peer_count": len(compact),
        "peers": compact,
        "note": "Call get_financials or get_stock_prices for specific peers to compare valuations.",
        "_sources": ["JPX"],
        "_source_details": {"JPX": {"type": "api", "desc": f"TSE Peer Universe — {sector} ({len(compact)} peers)", "url": "https://www.jpx.co.jp/english/listing/stocks/"}},
    })


# ── Market Context Tool ────────────────────────────────────

def _tool_get_market_context(inp: dict) -> str:
    """Nikkei 225, USD/JPY, S&P 500 for macro context."""
    import httpx
    ctx = {}; sources = []; sd = {}

    def _yf(symbol, key, label):
        try:
            r = _get_yahoo_client().get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d",
                timeout=8)
            if r.status_code != 200: return
            res = r.json().get("chart", {}).get("result", [])
            if not res: return
            meta = res[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            if price:
                chg = round((price - prev) / prev * 100, 2) if prev else None
                ctx[key] = {"value": round(price, 2), "change_pct": chg,
                            "market_state": meta.get("marketState", "")}
        except Exception:
            pass

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [
            pool.submit(_yf, "%5EN225", "nikkei_225", "Nikkei 225"),
            pool.submit(_yf, "USDJPY=X", "usd_jpy", "USD/JPY"),
            pool.submit(_yf, "%5EGSPC", "sp500", "S&P 500"),
        ]
        for f in futs:
            try: f.result(timeout=10)
            except Exception: pass

    # Frankfurter.app backup for forex
    if "usd_jpy" not in ctx:
        try:
            r = _get_yahoo_client().get("https://api.frankfurter.app/latest?from=USD&to=JPY", timeout=8)
            if r.status_code == 200:
                rate = r.json().get("rates", {}).get("JPY")
                if rate: ctx["usd_jpy"] = {"value": rate, "change_pct": None}
        except Exception:
            pass

    if ctx:
        sources.append("Yahoo Finance")
        sd["Yahoo Finance"] = {"type": "link", "desc": "Yahoo Finance — Market Indices",
                               "url": "https://finance.yahoo.com/"}

    if not ctx:
        return json.dumps({"error": "Could not fetch market context"})

    ctx["_sources"] = sources
    ctx["_source_details"] = sd
    return json.dumps(ctx)


# ── Thematic stock lists (cross-sector) ──────────────────
_THEMATIC_LISTS = {
    "ai": {
        "label": "AI & Artificial Intelligence",
        "codes": [
            "3076", "3719", "3858", "4374", "4388", "4476", "4488", "5586",
            "7345", "1435", "247A", "254A",
            # AI-themed ETFs/ETNs (for reference, not screened)
            # "162A", "2067", "223A", "2638",
            # Adjacent: major companies with significant AI divisions
            "6758",  # Sony (AI / imaging)
            "6861",  # Keyence (AI vision / automation)
            "6954",  # FANUC (AI robotics)
            "6501",  # Hitachi (Lumada AI platform)
            "9984",  # SoftBank Group (AI investments)
            "4849",  # Enplas (AI semiconductor test sockets)
        ],
    },
    "semiconductor": {
        "label": "Semiconductors",
        "codes": [
            "8035", "6857", "6723", "6981", "285A",
            "6526",  # Socionext
            "6920",  # Lasertec
            "7735",  # SCREENHoldings
        ],
    },
    "defense": {
        "label": "Defense & Aerospace",
        "codes": [
            "7011",  # Mitsubishi Heavy
            "7012",  # Kawasaki Heavy
            "7013",  # IHI
            "7721",  # Tokyo Keiki
            "6208",  # Ishikawa Seisakusho
        ],
    },
    "robotics": {
        "label": "Robotics & Automation",
        "codes": [
            "6954",  # FANUC
            "6861",  # Keyence
            "6506",  # Yaskawa
            "247A",  # Ai ROBOTICS
            "6273",  # SMC
            "278A",  # Terra Drone
        ],
    },
}

# ── Sector Screener Tool ──────────────────────────────────

def _tool_screen_sector(inp: dict) -> str:
    """Screen an entire sector with real financial data — the breakthrough."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.services.peer_db import PeerDatabase

    report_progress(5, "resolving sector")
    db = PeerDatabase()
    stock_code = inp.get("stock_code", "").strip()
    sector_name = inp.get("sector", "").strip()
    sort_by = inp.get("sort_by", "composite")
    max_results = min(inp.get("max_results", 8), 15)

    # ── Thematic screening (cross-sector lists like "ai", "robotics") ──
    theme_key = (stock_code or sector_name).lower().replace(" ", "")
    # Check for thematic match
    thematic_match = None
    for tk, tv in _THEMATIC_LISTS.items():
        if tk in theme_key or theme_key in tv["label"].lower().replace(" ", ""):
            thematic_match = tv
            break
    if thematic_match:
        # Build peer list from thematic codes instead of sector DB
        peers = []
        for code in thematic_match["codes"]:
            info = db.get_company_info(code)
            if info:
                peers.append(info)
            elif code in _COMMON_COMPANIES:
                name, sec = _COMMON_COMPANIES[code]
                peers.append({"code": code, "name": name, "sector33": sec})
        if peers:
            codes_names = [(p.get("code"), p.get("name", "")) for p in peers[:max_results]]
            # Jump to the scoring logic below (sector set to theme label)
            sector = thematic_match["label"]
            # Skip normal sector resolution
        else:
            return json.dumps({"error": f"No companies found for theme '{thematic_match['label']}'"})
    else:
        peers = None  # will be resolved below

    # Resolve sector (only if not thematic)
    if not thematic_match:
        sector = None
        if stock_code:
            sector = db.get_sector_for_code(stock_code)
        if not sector and sector_name:
            sector = db._resolve_sector(sector_name)
        if not sector and stock_code:
            lookup = json.loads(_dispatch_tool("lookup_company", {"stock_code": stock_code}))
            s = lookup.get("sector", "")
            if s:
                sector = db._resolve_sector(s)
        if not sector:
            return json.dumps({"error": "Cannot resolve sector. Try: retail, banking, auto, pharma, electronics, construction, real estate, chemicals, machinery, telecom, insurance, food, services, steel, mining, securities, ai, robotics, semiconductor, defense"})

    # Build peer list (skip if thematic screening already set it)
    if not thematic_match:
        peers = db.find_peers(stock_code or "0000", sector, n=20, prefer_prime=True)
        if stock_code:
            target = db.get_company_info(stock_code)
            if target and not any(p.get("code") == stock_code for p in peers):
                peers.insert(0, target)
        if not peers:
            return json.dumps({"error": f"No companies in '{sector}'"})
        codes_names = [(p.get("code"), p.get("name", "")) for p in peers[:15]]

    def _fetch_one(code_name):
        from concurrent.futures import ThreadPoolExecutor
        code, name = code_name
        try:
            # Fetch financials + prices in parallel per company
            with ThreadPoolExecutor(max_workers=2) as inner_pool:
                fin_fut = inner_pool.submit(_dispatch_tool, "get_financials", {"stock_code": code})
                price_fut = inner_pool.submit(_dispatch_tool, "get_stock_prices", {"stock_code": code, "days": 5})
                fin = json.loads(fin_fut.result())
                price = json.loads(price_fut.result())

            if "error" in fin:
                return None
            stmts = fin.get("statements", [])
            if not stmts:
                return None
            latest = stmts[-1]

            cur_price = None
            if "error" not in price:
                s = price.get("summary", {})
                cur_price = s.get("live_price") or s.get("latest_close")

            eps = latest.get("eps")
            bps = latest.get("bps")
            roe = latest.get("roe_pct")
            opm = latest.get("op_margin_pct")
            dps = latest.get("dps") or latest.get("forecast_dps")
            shares = latest.get("shares_outstanding")
            eq_ratio = latest.get("equity_ratio_pct")
            rev_g = latest.get("revenue_growth_yoy_pct")

            pe = round(cur_price / eps, 1) if cur_price and eps and eps > 0 else None
            pb = round(cur_price / bps, 2) if cur_price and bps and bps > 0 else None
            dy = round(dps / cur_price * 100, 2) if cur_price and dps and dps > 0 else None
            mcap = cur_price * shares if cur_price and shares else None

            # Quick value score
            vs = 5
            if pe and pe < 10: vs += 2
            elif pe and pe < 15: vs += 1
            elif pe and pe > 25: vs -= 1.5
            if pb and pb < 0.5: vs += 2.5
            elif pb and pb < 0.8: vs += 1.5
            elif pb and pb < 1.0: vs += 0.5
            elif pb and pb > 2.5: vs -= 1
            if dy and dy > 4: vs += 1
            elif dy and dy > 2.5: vs += 0.5
            vs = max(0, min(10, round(vs)))

            # Quick growth score
            gs = 5
            if rev_g is not None:
                if rev_g > 20: gs += 2
                elif rev_g > 10: gs += 1
                elif rev_g < -10: gs -= 2
                elif rev_g < 0: gs -= 1
            gs = max(0, min(10, round(gs)))

            # Quick quality score
            qs = 5
            if roe and roe > 15: qs += 2
            elif roe and roe > 10: qs += 1
            elif roe is not None and roe > 0 and roe < 5: qs -= 1
            elif roe is not None and roe <= 0: qs -= 2
            if opm and opm > 15: qs += 1
            elif opm is not None and opm < 3: qs -= 1
            qs = max(0, min(10, round(qs)))

            # Quick activist score
            at = 0
            if pb and pb < 0.7: at += 2.5
            elif pb and pb < 1.0: at += 1.5
            if roe is not None and roe < 8: at += 2
            if eq_ratio and eq_ratio > 50: at += 1.5
            if not dps or dps == 0: at += 1
            if mcap and mcap < 300e9: at += 1.5
            elif mcap and mcap < 500e9: at += 0.5
            at = min(10, round(at))

            comp = round((vs + gs + qs) / 3 * 10)

            return {
                "code": code, "name": name,
                "price": cur_price,
                "market_cap": _fmt_yen(mcap) if mcap else None,
                "pe": pe, "pb": pb,
                "roe_pct": roe, "div_yield_pct": dy,
                "op_margin_pct": opm, "rev_growth_pct": rev_g,
                "eq_ratio_pct": eq_ratio,
                "value": vs, "growth": gs, "quality": qs,
                "activist": at, "composite": comp,
            }
        except Exception:
            return None

    report_progress(15, f"screening {len(codes_names)} companies")
    results = []
    _screened = 0
    _total_screen = len(codes_names)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_fetch_one, cn): cn for cn in codes_names}
        for fut in as_completed(futs):
            try:
                r = fut.result()
                if r:
                    results.append(r)
            except Exception:
                pass
            _screened += 1
            report_progress(15 + int(75 * _screened / max(_total_screen, 1)), f"scored {_screened}/{_total_screen}")

    report_progress(95, "ranking results")
    sort_fn = {
        "composite": lambda x: -(x.get("composite") or 0),
        "value": lambda x: -(x.get("value") or 0),
        "growth": lambda x: -(x.get("growth") or 0),
        "quality": lambda x: -(x.get("quality") or 0),
        "activist": lambda x: -(x.get("activist") or 0),
        "dividend": lambda x: -(x.get("div_yield_pct") or 0),
        "pe_low": lambda x: (x.get("pe") or 9999),
        "pb_low": lambda x: (x.get("pb") or 9999),
    }.get(sort_by, lambda x: -(x.get("composite") or 0))
    results.sort(key=sort_fn)

    # Sector averages for benchmarking
    def _avg(key):
        vals = [r[key] for r in results if r.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    sector_avg = {
        "pe": _avg("pe"), "pb": _avg("pb"), "roe_pct": _avg("roe_pct"),
        "div_yield_pct": _avg("div_yield_pct"), "op_margin_pct": _avg("op_margin_pct"),
    }

    return json.dumps({
        "sector": sector,
        "screened": len(results),
        "total_in_sector": len(peers),
        "sort_by": sort_by,
        "sector_averages": sector_avg,
        "results": results[:max_results],
        "_sources": ["J-Quants", "Yahoo Finance", "JPX"],
        "_source_details": {
            "J-Quants": {"type": "api", "desc": f"Screened {len(results)} companies in {sector}"},
            "JPX": {"type": "api", "desc": f"TSE Peer Universe — {sector} ({len(peers)} total)"},
        },
    })


# ── Forensic Accounting / Red Flags Tool ──────────────────

def _tool_detect_red_flags(inp: dict) -> str:
    """Altman Z-Score, Accrual Ratio, Cash Quality, partial Beneish — earnings quality grade."""
    import math
    from app.services.jquants import JQuantsClient
    stock_code = inp["stock_code"].strip()

    # Get raw financial statements (need 2+ periods for indices)
    client = JQuantsClient()
    try:
        data = client.get_financials(stock_code)
    except Exception:
        return json.dumps({"error": "Financial data unavailable"})

    statements = data.get("statements") or data.get("financials") or data.get("data") or []
    actuals = [s for s in statements if s.get("Sales") or s.get("NP") or s.get("OP")]
    if len(actuals) < 2:
        return json.dumps({"error": "Need at least 2 periods of financial data for red flag analysis"})

    # Take the 2 most recent periods
    cur_s = actuals[-1]
    prev_s = actuals[-2]

    def _pn(s, keys):
        return _pick_num(s, keys)

    # Extract current period
    rev_c = _pn(cur_s, ["Sales", "NetSales", "Revenue"])
    op_c = _pn(cur_s, ["OP", "OperatingProfit", "OperatingIncome"])
    ni_c = _pn(cur_s, ["NP", "Profit", "NetIncome"])
    ta_c = _pn(cur_s, ["TotalAssets", "TA"])
    eq_c = _pn(cur_s, ["Equity", "TotalEquity", "Eq", "NetAssets", "EquityAttributableToOwnersOfParent"])
    cfo_c = _pn(cur_s, ["CashFlowsFromOperatingActivities", "CFO", "NetCashProvidedByUsedInOperatingActivities"])
    shares_c = _pn(cur_s, ["ShOutFY", "IssuedShares", "NumberOfSharesIssuedAndOutstanding", "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYear"])
    eps_c = _pn(cur_s, ["EPS", "EarningsPerShare"])

    # Extract previous period
    rev_p = _pn(prev_s, ["Sales", "NetSales", "Revenue"])
    op_p = _pn(prev_s, ["OP", "OperatingProfit", "OperatingIncome"])
    ni_p = _pn(prev_s, ["NP", "Profit", "NetIncome"])
    ta_p = _pn(prev_s, ["TotalAssets", "TA"])
    eq_p = _pn(prev_s, ["Equity", "TotalEquity", "Eq", "NetAssets", "EquityAttributableToOwnersOfParent"])

    liab_c = (ta_c - eq_c) if (ta_c and eq_c) else None
    liab_p = (ta_p - eq_p) if (ta_p and eq_p) else None

    # Get current price for Altman Z-Score X4
    price_str = _dispatch_tool("get_stock_prices", {"stock_code": stock_code, "days": 5})
    price_data = json.loads(price_str)
    cur_price = None
    if "error" not in price_data:
        ps = price_data.get("summary", {})
        cur_price = ps.get("live_price") or ps.get("latest_close")
    market_cap = cur_price * shares_c if (cur_price and shares_c) else None

    result = {"stock_code": stock_code}
    grade_points = []

    # ── 1. Altman Z-Score ──
    z_score = None
    z_details = {}
    ebit_proxy = op_c if op_c is not None else ni_c  # banks lack OP — use NI as proxy

    # Detect financial sector (banks, insurance, securities) — Z-Score is unreliable
    is_financial = False
    if eq_c and ta_c and ta_c > 0:
        eq_ratio = eq_c / ta_c
        is_financial = (eq_ratio < 0.10 and op_c is None)  # <10% equity ratio + no OP = bank/insurer

    if is_financial:
        # Z-Score is NOT applicable to financial companies (deposits are liabilities by design)
        z_details = {
            "score": None, "zone": "N/A — Financial Sector",
            "interpretation": "Altman Z-Score is not applicable to banks, insurance companies, and securities firms. Their business model inherently carries high leverage (deposits/reserves = liabilities). Rely on equity ratio, cash quality, and regulatory capital ratios instead.",
            "model": "Skipped for financial sector company",
        }
        grade_points.append(0)  # neutral — don't penalize
    elif ta_c and ta_c > 0 and eq_c is not None and ebit_proxy is not None:
        # Using Altman Z'' (universal model — works across all non-financial industries)
        # Z'' = 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4
        # Removes X5 (Sales/Assets) which distorts cross-sector comparisons

        # X1: Working Capital / Total Assets (proxy: equity ratio adjusted)
        x1 = (eq_c / ta_c) * 0.5 if eq_c else 0
        # X2: Retained Earnings / Total Assets (proxy: equity / total assets)
        x2 = eq_c / ta_c if eq_c else 0
        # X3: EBIT / Total Assets
        x3 = ebit_proxy / ta_c if ebit_proxy else 0
        # X4: Book Equity / Total Liabilities
        x4 = eq_c / liab_c if (eq_c and liab_c and liab_c > 0) else 1.0

        z_score = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
        z_score = round(z_score, 2)

        # Z'' thresholds
        if z_score > 2.60:
            z_zone = "Safe Zone"
            z_interp = "Very low bankruptcy risk"
            grade_points.append(2)
        elif z_score > 1.10:
            z_zone = "Grey Zone"
            z_interp = "Some financial stress indicators — monitor closely"
            grade_points.append(0)
        else:
            z_zone = "Distress Zone"
            z_interp = "Elevated bankruptcy risk — significant financial stress"
            grade_points.append(-2)

        z_details = {"score": z_score, "zone": z_zone, "interpretation": z_interp,
                     "model": "Altman Z'' (universal — works across all industries)",
                     "components": {"X1_working_cap": round(x1, 3), "X2_retained_earnings": round(x2, 3),
                                    "X3_ebit_ta": round(x3, 3), "X4_equity_liab": round(x4, 3)}}
    else:
        z_details = {"score": None, "zone": "N/A", "interpretation": "Insufficient data for Z-Score"}

    result["altman_z_score"] = z_details

    # ── 2. Accrual Ratio ──
    accrual = {}
    if cfo_c is not None and ni_c is not None and ta_c and ta_c > 0:
        accrual_ratio = (ni_c - cfo_c) / ta_c
        accrual_ratio_r = round(accrual_ratio, 4)

        if accrual_ratio > 0.10:
            a_signal = "RED FLAG — Very high accruals"
            a_interp = "Earnings significantly exceed cash flow. Potential earnings manipulation or aggressive accounting."
            grade_points.append(-2)
        elif accrual_ratio > 0.05:
            a_signal = "WARNING — Elevated accruals"
            a_interp = "Earnings moderately exceed cash generation. Watch for reversals."
            grade_points.append(-1)
        elif accrual_ratio > -0.05:
            a_signal = "NORMAL"
            a_interp = "Accruals within typical range."
            grade_points.append(1)
        else:
            a_signal = "EXCELLENT — Negative accruals"
            a_interp = "Cash flow exceeds reported earnings — conservative accounting, high quality."
            grade_points.append(2)

        accrual = {"value": accrual_ratio_r, "signal": a_signal, "interpretation": a_interp}
    else:
        accrual = {"value": None, "signal": "N/A", "interpretation": "CFO data unavailable for accrual analysis"}

    result["accrual_ratio"] = accrual

    # ── 3. Cash vs Earnings Quality ──
    cash_quality = {}
    if cfo_c is not None and ni_c is not None and ni_c != 0:
        cfo_ni = cfo_c / ni_c
        cfo_ni_r = round(cfo_ni, 2)

        if ni_c > 0:
            if cfo_ni > 1.5:
                cq_signal = "EXCELLENT"
                cq_interp = f"CFO is {cfo_ni_r}x net income — cash generation far exceeds reported profits. Very high quality."
                grade_points.append(2)
            elif cfo_ni > 1.0:
                cq_signal = "GOOD"
                cq_interp = f"CFO exceeds net income ({cfo_ni_r}x) — profits are backed by real cash."
                grade_points.append(1)
            elif cfo_ni > 0.5:
                cq_signal = "MEDIOCRE"
                cq_interp = f"CFO is only {cfo_ni_r}x net income — some earnings are non-cash. Monitor."
                grade_points.append(0)
            elif cfo_ni > 0:
                cq_signal = "WARNING"
                cq_interp = f"CFO is only {cfo_ni_r}x net income — most earnings are non-cash or accrual-based."
                grade_points.append(-1)
            else:
                cq_signal = "RED FLAG"
                cq_interp = "Negative CFO despite positive earnings — company is burning cash while reporting profits."
                grade_points.append(-2)
        else:
            if cfo_c > 0:
                cq_signal = "MIXED"
                cq_interp = "Positive CFO despite negative earnings — operations generate cash but non-cash charges drag profits."
                grade_points.append(0)
            else:
                cq_signal = "DISTRESS"
                cq_interp = "Both earnings and cash flow are negative."
                grade_points.append(-2)

        cash_quality = {"cfo_to_ni_ratio": cfo_ni_r, "signal": cq_signal,
                        "cfo": _fmt_yen(cfo_c), "net_income": _fmt_yen(ni_c),
                        "interpretation": cq_interp}
    else:
        cash_quality = {"cfo_to_ni_ratio": None, "signal": "N/A",
                        "interpretation": "CFO data unavailable"}

    result["cash_quality"] = cash_quality

    # ── 4. Partial Beneish M-Score Indicators ──
    beneish = {"available_of_8": 0, "note": "Full 8-variable M-Score requires detailed balance sheet data (receivables, gross profit, PPE, SGA) not available from J-Quants API. The 3 computable indicators are shown below."}
    computed = 0

    # SGI — Sales Growth Index (> 1.607 = red flag)
    if rev_c and rev_p and rev_p > 0:
        sgi = rev_c / rev_p
        beneish["sgi"] = round(sgi, 3)
        beneish["sgi_flag"] = "RED FLAG" if sgi > 1.607 else "Normal"
        computed += 1

    # TATA — Total Accruals to Total Assets (> 0.031 = red flag)
    if cfo_c is not None and ni_c is not None and ta_c and ta_c > 0:
        tata = (ni_c - cfo_c) / ta_c
        beneish["tata"] = round(tata, 4)
        beneish["tata_flag"] = "RED FLAG" if tata > 0.031 else "Normal"
        computed += 1

    # LVGI — Leverage Index (> 1.111 = red flag)
    if liab_c is not None and ta_c and liab_p is not None and ta_p:
        lev_c = liab_c / ta_c
        lev_p = liab_p / ta_p
        if lev_p > 0:
            lvgi = lev_c / lev_p
            beneish["lvgi"] = round(lvgi, 3)
            beneish["lvgi_flag"] = "RED FLAG" if lvgi > 1.111 else "Normal"
            computed += 1

    beneish["available_of_8"] = computed
    red_flags_count = sum(1 for k in ["sgi_flag", "tata_flag", "lvgi_flag"] if beneish.get(k) == "RED FLAG")
    beneish["red_flags_triggered"] = red_flags_count

    result["beneish_indicators"] = beneish

    # ── 5. Overall Earnings Quality Grade ──
    if grade_points:
        avg_score = sum(grade_points) / len(grade_points)
        if avg_score >= 1.5:
            grade, label = "A", "Excellent"
        elif avg_score >= 0.75:
            grade, label = "B+", "Good"
        elif avg_score >= 0.25:
            grade, label = "B", "Acceptable"
        elif avg_score >= -0.25:
            grade, label = "C", "Mediocre"
        elif avg_score >= -1.0:
            grade, label = "D", "Poor"
        else:
            grade, label = "F", "Failing — Multiple Red Flags"

        # Adjust for Beneish red flags
        if red_flags_count >= 2 and grade in ("A", "B+", "B"):
            grade, label = "C-", "Downgraded — Beneish indicators flagged"
    else:
        grade, label = "N/A", "Insufficient data"

    factors_list = []
    if z_details.get("score"):
        factors_list.append(f"Z-Score {z_details['score']} ({z_details['zone']})")
    if accrual.get("value") is not None:
        factors_list.append(f"Accrual ratio {accrual['value']} ({accrual['signal']})")
    if cash_quality.get("cfo_to_ni_ratio") is not None:
        factors_list.append(f"Cash quality {cash_quality['cfo_to_ni_ratio']}x ({cash_quality['signal']})")
    if red_flags_count > 0:
        factors_list.append(f"{red_flags_count} Beneish red flags triggered")

    result["earnings_quality_grade"] = {"grade": grade, "label": label, "factors": factors_list}
    result["_sources"] = ["J-Quants", "Yahoo Finance"]
    result["_source_details"] = {
        "J-Quants": {"type": "api", "desc": f"Financial statements — {stock_code} (2 periods)"},
        "Yahoo Finance": {"type": "api", "desc": f"Current price for market cap — {stock_code}"},
    }

    return json.dumps(result)


# ── Streaming chat engine ──────────────────────────────────

VOICE_PROMPT = """You are Mimi, an expert voice assistant specializing in Japanese equity research and activist shareholder intelligence. You speak like a senior analyst on a trading floor — sharp, confident, no filler.

DELIVERY:
- Short and punchy. Lead with the insight, not the preamble.
- 2-4 sentences typical. 1 sentence for simple facts. Never ramble.
- Contractions always: "it's", "they've", "doesn't", "won't".
- Natural openers sparingly: "So," "Right," "Okay," "Well,".
- React to notable data: "That's interesting," "Worth watching," "Big number."

FORMAT (non-negotiable):
- Pure spoken words. NO markdown, bullets, dashes, asterisks, lists, or formatting. Ever.
- NO "---follow-ups---" section. Never.
- Numbers spoken: "about fourteen thousand yen" not "¥14,000".
- Dates spoken: "March thirteenth" not "2026-03-13".
- Percentages spoken: "up two and a half percent" not "+2.5%".
- NEVER announce tool usage. Don't say "let me look that up", "let me check", "pulling that now", or anything similar. Just call tools silently — the system will automatically notify the user. Deliver the answer directly when tools return.
- Weave into flowing prose. Never list items.

FUND & ACTIVIST QUERIES — YOUR KEY DIFFERENTIATOR:
- "What does [fund] own?" / "[fund]'s biggest position" / "[fund] holdings" → Call search_fund_holdings with the fund name. Also call web_search in parallel for "[fund name] Japan holdings positions" for broader context.
- "Who owns [company]?" → Call get_shareholder_structure + get_large_shareholders in parallel.
- Known funds: Oasis, Elliott, Dalton, Strategic Capital, Effissimo, Third Point, ValueAct, Taiyo, Cerberus, Nippon Active Value, Murakami/Reno/City Index.
- When reporting fund positions, lead with the biggest stake and name the company. Give context on what it means (activist angle, stake size significance).

EDINET INTELLIGENCE:
- For shareholder questions: get_shareholder_structure + get_large_shareholders in PARALLEL. Never say you can't access EDINET — you CAN.
- For governance of a SPECIFIC company: get_directors + get_voting_results in parallel.
- For MARKET-WIDE AGM queries ("companies with low AGM approval", "AGM under 90%"): use scan_agm_voting — it scans ALL EDINET extraordinary reports and returns companies below the threshold. NEVER say you can't scan all companies — you CAN with scan_agm_voting.
- For filings: search_edinet_filings.
- These pull REAL regulatory data from Japan's EDINET system. Use them aggressively.

TOOLS:
- You have 18 research tools. Use them freely and in parallel.
- Stock codes: numeric (7203) or alphanumeric (157A, 247A) — both valid.
- For AI stocks: screen_sector with sector "ai".
- For scoring/valuation: score_company is the most powerful tool.
- Always call tools first, then speak the insight. Never fabricate data.

You can be interrupted anytime — the user just says "Hey Mimi" or taps the orb.
Your name is Mimi. Built by Mischa Industries LLC.
IDENTITY: You are Mimi, part of the Mischa AI platform by Mischa Industries LLC. NEVER say Claude, Anthropic, or any other AI company. If asked who made you, say "Mischa Industries LLC"."""

VOICE_TOOL_NAMES = {
    "lookup_company", "get_stock_prices", "get_financials", "search_edinet_filings",
    "web_search", "get_directors", "get_voting_results", "get_large_shareholders",
    "analyze_technicals", "score_company", "get_company_peers", "get_market_context",
    "screen_sector", "analyze_risk", "detect_red_flags", "get_shareholder_structure",
    "search_fund_holdings", "scan_agm_voting",
}
VOICE_TOOLS = [t for t in TOOL_DEFINITIONS if t["name"] in VOICE_TOOL_NAMES]
if VOICE_TOOLS:
    VOICE_TOOLS[-1] = {**VOICE_TOOLS[-1], "cache_control": {"type": "ephemeral"}}

INSTANT_PROMPT_OVERRIDE = """You are a fast Japanese equity research assistant. Be extremely concise. Get straight to the point.

RULES:
- Call tools first, NEVER fabricate data. Call tools in PARALLEL.
- For simple queries (price, lookup): 1-2 sentences max.
- For analysis queries: short bullet points, one compact table if needed. Under 200 words.
- No preamble, no "Let me look…". Tools first, then terse analysis.
- Prefer live_price over latest_close. Label as live/intraday.
- Include P/E, P/B, dividend yield when you have both price + financials.
- Currency: ¥X,XXX. Changes: +2.3% / -1.5%.
- No emojis. Clean and fast.
- Stock codes can be numeric (7203) or alphanumeric (157A, 247A). Both are valid TSE codes.
- IDENTITY: You are Mischa AI, built by Mischa Industries LLC. NEVER say Claude, Anthropic, or any other AI company name. If asked who made you, say "I'm Mischa AI, built by Mischa Industries LLC."

EDINET — YOUR KEY ADVANTAGE:
- For shareholder questions: call get_shareholder_structure (top shareholder list from annual reports) + get_large_shareholders (5% filings + activist flags) IN PARALLEL. NEVER say you can't pull EDINET data — you CAN.
- For governance of a SPECIFIC company: call get_directors + get_voting_results in parallel.
- For MARKET-WIDE AGM queries ("companies with low AGM approval", "AGM under 90%"): use scan_agm_voting — it scans ALL EDINET extraordinary reports and returns companies below the threshold.
- For filings: call search_edinet_filings.
- These tools pull REAL regulatory data from Japan's EDINET system. Use them aggressively.

FOLLOW-UP SUGGESTIONS (MANDATORY):
After EVERY response, end with exactly this block:

---follow-ups---
- [Specific follow-up 1]
- [Specific follow-up 2]
- [Specific follow-up 3]

Make each relevant to the company/topic just discussed. Focus on: technicals, scoring, peers, financials, shareholders, EDINET filings, market context."""

# Reduced tool set for instant mode — fewer tools = fewer input tokens = faster TTFT
INSTANT_TOOL_NAMES = {
    "lookup_company", "get_stock_prices", "get_financials", "web_search",
    "analyze_technicals", "score_company", "get_company_peers", "get_market_context",
    "get_large_shareholders", "get_shareholder_structure", "get_directors",
    "get_voting_results", "search_edinet_filings", "search_fund_holdings",
    "scan_agm_voting",
}
INSTANT_TOOLS = [t for t in TOOL_DEFINITIONS if t["name"] in INSTANT_TOOL_NAMES]
# Add cache_control to the last tool for prompt caching
if INSTANT_TOOLS:
    INSTANT_TOOLS[-1] = {**INSTANT_TOOLS[-1], "cache_control": {"type": "ephemeral"}}

# Add cache_control to last full tool definition for stream mode caching
STREAM_TOOLS = list(TOOL_DEFINITIONS)
if STREAM_TOOLS:
    STREAM_TOOLS[-1] = {**STREAM_TOOLS[-1], "cache_control": {"type": "ephemeral"}}


async def stream_chat_response(messages: list[dict], *, mode: str = "stream") -> AsyncGenerator[str, None]:
    """Stream a Claude response with tool use, yielding SSE-formatted events.

    Events:
      - event: text      data: {"text": "..."}
      - event: tool_call data: {"tool": "name", "input": {...}}
      - event: tool_result data: {"tool": "name", "summary": "..."}
      - event: error     data: {"message": "..."}
      - event: done      data: {}

    mode: "stream" uses Sonnet (thorough), "instant" uses Haiku (fast).
    """
    if not settings.anthropic_api_key:
        yield 'event: error\ndata: {"message": "ANTHROPIC_API_KEY not configured"}\n\n'
        return

    client = _get_anthropic_client()

    is_voice = mode == "voice"
    is_instant = mode == "instant"

    if is_voice:
        model = "claude-sonnet-4-6"
        max_tokens = 1024
        max_iterations = 5
        tools = VOICE_TOOLS
    elif is_instant:
        model = "claude-haiku-4-5"
        max_tokens = 2048
        max_iterations = 3
        tools = INSTANT_TOOLS
    else:
        model = "claude-sonnet-4-6"
        max_tokens = 8192
        max_iterations = MAX_TOOL_ITERATIONS
        tools = STREAM_TOOLS

    # System prompt as cacheable content block
    system_text = VOICE_PROMPT if is_voice else (INSTANT_PROMPT_OVERRIDE if is_instant else SYSTEM_PROMPT)
    system_block = [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]

    # Build messages for Anthropic (only role + content text)
    api_messages = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            api_messages.append({"role": role, "content": content})

    if not api_messages:
        yield 'event: error\ndata: {"message": "No messages provided"}\n\n'
        return

    extra_kwargs = {}
    if is_voice:
        extra_kwargs["temperature"] = 0.7  # natural variation for voice
    elif is_instant:
        extra_kwargs["temperature"] = 0  # deterministic + slightly faster

    for iteration in range(max_iterations):
        try:
            # Use streaming for the text response
            async with client.messages.stream(
                model=model,
                system=system_block,
                messages=api_messages,
                tools=tools,
                max_tokens=max_tokens,
                **extra_kwargs,
            ) as stream:
                assistant_text = ""
                tool_uses = []

                async for event in stream:
                    if event.type == "text":
                        assistant_text += event.text
                        chunk = json.dumps({"text": event.text})
                        yield f"event: text\ndata: {chunk}\n\n"

                response = await stream.get_final_message()

                for block in response.content:
                    if block.type == "tool_use":
                        tool_uses.append(block)

                if not tool_uses:
                    yield "event: done\ndata: {}\n\n"
                    return

                # Notify frontend about ALL tool calls first
                for tool_block in tool_uses:
                    call_data = json.dumps({"id": tool_block.id, "tool": tool_block.name, "input": tool_block.input})
                    yield f"event: tool_call\ndata: {call_data}\n\n"

                # Execute ALL tool calls in PARALLEL — stream each result immediately
                _SLOW_TOOLS = {"get_large_shareholders", "get_shareholder_structure", "search_fund_holdings", "get_voting_results", "scan_agm_voting"}
                event_q: asyncio.Queue = asyncio.Queue()
                loop = asyncio.get_event_loop()

                def _make_progress_fn(tool_id, tool_name):
                    """Create a thread-safe progress reporter for a specific tool."""
                    def _report(pct: int, stage: str = ""):
                        loop.call_soon_threadsafe(
                            event_q.put_nowait,
                            {"_t": "p", "id": tool_id, "tool": tool_name, "pct": min(pct, 100), "stage": stage},
                        )
                    return _report

                async def _run_tool(block):
                    t = 120 if block.name in _SLOW_TOOLS else 60
                    pfn = _make_progress_fn(block.id, block.name)
                    pfn(5, "starting")
                    try:
                        result = await asyncio.wait_for(
                            asyncio.to_thread(_dispatch_tool, block.name, block.input, pfn),
                            timeout=t,
                        )
                        event_q.put_nowait({"_t": "r", "block": block, "result": result, "error": None})
                    except Exception as e:
                        event_q.put_nowait({"_t": "r", "block": block, "result": None, "error": e})

                for tb in tool_uses:
                    asyncio.ensure_future(_run_tool(tb))

                tool_results = []
                completed = 0
                total = len(tool_uses)

                while completed < total:
                    try:
                        evt = await asyncio.wait_for(event_q.get(), timeout=0.15)
                    except asyncio.TimeoutError:
                        continue

                    if evt["_t"] == "p":
                        yield f"event: tool_progress\ndata: {json.dumps({k: evt[k] for k in ('id','tool','pct','stage')})}\n\n"
                    else:
                        completed += 1
                        tool_block = evt["block"]
                        if evt["error"] or not evt.get("result"):
                            err_msg = str(evt.get("error", "Unknown error"))
                            result_str = json.dumps({"error": f"Tool {tool_block.name} failed: {err_msg}"})
                        else:
                            result_str = evt["result"]
                        result_obj = None
                        try:
                            result_obj = json.loads(result_str)
                            summary = _summarize_tool_result(tool_block.name, result_obj)
                            sources = result_obj.get("_sources", [])
                            source_details = result_obj.get("_source_details", {})
                        except Exception:
                            summary = result_str[:100] if isinstance(result_str, str) else "Error"
                            sources = []
                            source_details = {}
                        rd = {"id": tool_block.id, "tool": tool_block.name, "summary": summary, "sources": sources, "source_details": source_details}
                        if tool_block.name == "get_stock_prices" and isinstance(result_obj, dict):
                            rd["stock_code"] = tool_block.input.get("stock_code")
                            s = result_obj.get("summary", {})
                            rd["live_price"] = s.get("live_price")
                            rd["live_change_pct"] = s.get("live_change_pct")
                            rd["market_state"] = s.get("market_state", "")
                            rd["previous_close"] = s.get("previous_close")
                            rd["price_history"] = result_obj.get("recent_prices", [])
                        yield f"event: tool_result\ndata: {json.dumps(rd)}\n\n"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": result_str,
                        })

                # Drain any remaining progress events
                while not event_q.empty():
                    evt = event_q.get_nowait()
                    if evt["_t"] == "p":
                        yield f"event: tool_progress\ndata: {json.dumps({k: evt[k] for k in ('id','tool','pct','stage')})}\n\n"

                # Append to messages for next iteration
                api_messages.append({"role": "assistant", "content": response.content})
                api_messages.append({"role": "user", "content": tool_results})

        except anthropic.APIError as e:
            err = json.dumps({"message": f"API error: {str(e)}"})
            yield f"event: error\ndata: {err}\n\n"
            return
        except Exception as e:
            logger.exception("Chat stream error")
            err = json.dumps({"message": f"Error: {str(e)}"})
            yield f"event: error\ndata: {err}\n\n"
            return

    yield "event: done\ndata: {}\n\n"


# ── Report-context companion chat (Haiku, no tools) ────────────────────


async def stream_report_chat(
    report_text: str,
    sources: list[dict],
    messages: list[dict],
    company_name: str = "",
) -> AsyncGenerator[str, None]:
    """Lightweight report-context Q&A using Haiku.

    No tools — answers purely from the pre-generated report text + source
    metadata.  Uses prompt caching so subsequent questions in the same
    session are very cheap (~5× less than the first).
    """
    if not settings.anthropic_api_key:
        yield 'event: error\ndata: {"message": "ANTHROPIC_API_KEY not configured"}\n\n'
        return

    client = _get_anthropic_client()

    # Build detailed sources reference with type, date, full snippet
    n_sources = len(sources) if sources else 0
    if sources:
        source_lines = []
        for i, s in enumerate(sources):
            sid = s.get("id", i + 1)
            stype = "EDINET" if s.get("type") == "edinet" else "WEB"
            title = s.get("title", "Untitled")
            url = s.get("url", "")
            snippet = (s.get("snippet") or "").strip()
            date = s.get("date", "")
            line = f"[{sid}] [{stype}] {title}"
            if url:
                line += f"\n    URL: {url}"
            if date:
                line += f"\n    Date: {date}"
            if snippet:
                line += f"\n    {snippet[:300]}"
            source_lines.append(line)
        sources_ref = "\n\n".join(source_lines)
    else:
        sources_ref = "No sources available."

    system_text = (
        f"You are a senior equity research analyst assistant for **{company_name}**.\n"
        f"You have access to a completed research report and ALL {n_sources} sources "
        f"it was built from. Use them thoroughly.\n\n"
        f"────────── REPORT CONTENT ──────────\n{report_text}\n\n"
        f"────────── SOURCES ({n_sources} total) ──────────\n{sources_ref}\n\n"
        "RULES:\n"
        f"• You have access to ALL {n_sources} sources listed above. "
        "Reference them by number [1], [2], etc.\n"
        "• Answer from the report content and source data. "
        "Be specific with exact numbers, metrics, and ¥ figures.\n"
        "• When citing data, always include the source reference: "
        "\"Revenue grew 7.6% YoY [3]\"\n"
        "• If multiple sources support a claim, cite all relevant ones: "
        "\"Based on [2][5][7]...\"\n"
        "• Think like a senior research analyst — be analytical, direct, "
        "and data-driven.\n"
        "• Use markdown formatting: **bold** key figures, use headers for "
        "structure, bullet lists for comparisons.\n"
        "• Use exact figures from the report. Do not round unnecessarily.\n"
        "• Distinguish between EDINET filing data (official) and web sources "
        "(supplementary) when relevant.\n"
        "• Be concise: lead with the answer, then support with data. "
        "No filler or preamble. Get to the point fast.\n"
        "• Use tables for comparisons and multi-metric answers when helpful.\n"
        "\n"
        "OUT-OF-SCOPE HANDLING:\n"
        f"You can ONLY answer questions about {company_name} using this report "
        "and its sources. If a user asks about:\n"
        "  – A different company\n"
        "  – General market/macro topics not covered in this report\n"
        "  – Anything you cannot answer from the report data\n"
        "Then respond EXACTLY like this pattern:\n"
        f"\"I can only answer questions about **{company_name}** based on this "
        "research report. For broader questions or other companies, you can use:\n\n"
        "- **[Query](/Query)** — Ask any question with AI-powered research tools\n"
        "- **[New Report](/Home)** — Generate a research report for a different company\"\n"
        "\n"
        "Always include those two links when redirecting.\n"
    )

    system_block = [
        {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
    ]

    api_messages = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            api_messages.append({"role": role, "content": content})

    if not api_messages:
        yield 'event: error\ndata: {"message": "No messages provided"}\n\n'
        return

    try:
        async with client.messages.stream(
            model="claude-haiku-4-5-20251001",
            system=system_block,
            messages=api_messages,
            max_tokens=4096,
            temperature=0.3,
        ) as stream:
            async for event in stream:
                if event.type == "text":
                    chunk = json.dumps({"text": event.text})
                    yield f"event: text\ndata: {chunk}\n\n"
    except anthropic.APIError as e:
        err = json.dumps({"message": f"API error: {str(e)}"})
        yield f"event: error\ndata: {err}\n\n"
        return
    except Exception as e:
        logger.exception("Report chat stream error")
        err = json.dumps({"message": f"Error: {str(e)}"})
        yield f"event: error\ndata: {err}\n\n"
        return

    yield "event: done\ndata: {}\n\n"


def _summarize_tool_result(tool_name: str, result: dict) -> str:
    """Create a short human-readable summary of a tool result."""
    if "error" in result:
        return f"Error: {result['error'][:80]}"

    if tool_name == "lookup_company":
        return f"{result.get('name', '?')} — {result.get('sector', '?')}"
    elif tool_name == "get_stock_prices":
        s = result.get("summary", {})
        live = s.get("live_price")
        if live:
            chg = s.get("live_change_pct")
            chg_str = f"{chg}%" if chg is not None else "n/a"
            return f"¥{live:,.0f} (live, {chg_str} today)"
        close = s.get("latest_close")
        pct = s.get("period_change_pct")
        pct_str = f"{pct}%" if pct is not None else "n/a"
        return f"¥{close:,.0f} ({pct_str})" if close else f"({pct_str})"
    elif tool_name == "get_financials":
        s = result.get("summary", {})
        if s and s.get("latest_period"):
            parts = [f"{s['latest_period']}: Rev {s.get('latest_revenue', '?')}, NI {s.get('latest_net_income', '?')}"]
            extras = []
            if s.get("latest_roe_pct") is not None:
                extras.append(f"ROE {s['latest_roe_pct']}%")
            if s.get("latest_bps") is not None:
                extras.append(f"BPS ¥{s['latest_bps']:,.0f}")
            if s.get("latest_op_margin_pct") is not None:
                extras.append(f"OPM {s['latest_op_margin_pct']}%")
            if s.get("latest_fcf"):
                extras.append(f"FCF {s['latest_fcf']}")
            if s.get("latest_cash_conversion") is not None:
                extras.append(f"Cash conv {s['latest_cash_conversion']}x")
            if extras:
                parts.append(" | ".join(extras))
            return " | ".join(parts)
        stmts = result.get("statements", [])
        if stmts:
            latest = stmts[-1]
            return f"{latest.get('period', '?')}: Rev {latest.get('revenue', '?')}, NI {latest.get('net_income', '?')}"
        return f"{result.get('periods', 0)} periods"
    elif tool_name == "search_edinet_filings":
        return f"Found {result.get('filings_found', 0)} filings"
    elif tool_name == "web_search":
        return f"{result.get('results_count', 0)} results for \"{result.get('query', '')}\""
    elif tool_name == "get_directors":
        s = result.get("board_summary", {})
        return f"{s.get('totalMembers', '?')} directors ({s.get('independent', '?')} independent)"
    elif tool_name == "get_voting_results":
        if result.get("has_voting_data"):
            filing = result.get("filing", {})
            return f"AGM voting data from {filing.get('submit_date', '?')}"
        count = result.get("extraordinary_reports_found", 0)
        return f"{count} extraordinary reports found"
    elif tool_name == "get_large_shareholders":
        n = result.get("unique_filers", 0)
        activists = result.get("activist_count", 0)
        if activists > 0:
            holders = result.get("holders", [])
            activist_names = [h["filer"] for h in holders if h.get("is_activist")][:3]
            return f"{n} large holders ({activists} activist: {', '.join(activist_names)})"
        return f"{n} large holders found (no known activists)"
    elif tool_name == "analyze_technicals":
        sig = result.get("technical_signal", "?")
        rsi = result.get("rsi", {}).get("value")
        w52 = result.get("week_52", {})
        fh = w52.get("from_high_pct")
        parts = [sig]
        if rsi is not None: parts.append(f"RSI {rsi}")
        if fh is not None: parts.append(f"{fh:+.1f}% from 52w high")
        return " | ".join(parts)
    elif tool_name == "score_company":
        comp = result.get("composite_score", "?")
        pf = result.get("piotroski_f_score", {}).get("score", "?")
        val = result.get("valuation", {})
        pe_r = val.get("pe_ratio"); pb_r = val.get("pb_ratio")
        fv = result.get("fair_value", {})
        up = fv.get("upside_pct")
        parts = [f"Score {comp}/100", f"Piotroski {pf}/9"]
        if pe_r: parts.append(f"P/E {pe_r}x")
        if pb_r: parts.append(f"P/B {pb_r}x")
        if up is not None: parts.append(f"Fair value {up:+.1f}%")
        return " | ".join(parts)
    elif tool_name == "get_company_peers":
        sector = result.get("sector", "?")
        n = result.get("peer_count", 0)
        return f"{n} peers in {sector}"
    elif tool_name == "get_market_context":
        nk = result.get("nikkei_225", {})
        jpy = result.get("usd_jpy", {})
        parts = []
        if nk.get("value"): parts.append(f"Nikkei {nk['value']:,.0f} ({nk.get('change_pct', '?')}%)")
        if jpy.get("value"): parts.append(f"USD/JPY {jpy['value']}")
        return " | ".join(parts) if parts else "Market data loaded"
    elif tool_name == "screen_sector":
        sector = result.get("sector", "?")
        n = result.get("screened", 0)
        top = result.get("results", [])
        avgs = result.get("sector_averages", {})
        parts = [f"Screened {n} companies in {sector}"]
        if avgs.get("pe"): parts.append(f"avg P/E {avgs['pe']}x")
        if avgs.get("pb"): parts.append(f"avg P/B {avgs['pb']}x")
        if top:
            best = top[0]
            parts.append(f"Top: {best.get('name', best.get('code', '?'))} (Score {best.get('composite', '?')})")
        return " | ".join(parts)
    elif tool_name == "analyze_risk":
        grade = result.get("risk_grade", {}).get("grade", "?")
        vol = result.get("volatility", {}).get("annualized_pct")
        beta = result.get("beta", {}).get("value")
        sharpe = result.get("sharpe_ratio", {}).get("value")
        parts = [grade]
        if vol is not None: parts.append(f"Vol {vol:.1f}%")
        if beta is not None: parts.append(f"Beta {beta:.2f}")
        if sharpe is not None: parts.append(f"Sharpe {sharpe:.2f}")
        return " | ".join(parts)
    elif tool_name == "detect_red_flags":
        grade = result.get("earnings_quality_grade", {}).get("grade", "?")
        label = result.get("earnings_quality_grade", {}).get("label", "")
        z = result.get("altman_z_score", {}).get("score")
        cq = result.get("cash_quality", {}).get("signal", "?")
        parts = [f"Grade {grade} ({label})"]
        if z is not None: parts.append(f"Z-Score {z}")
        parts.append(f"Cash: {cq}")
        return " | ".join(parts)
    elif tool_name == "get_shareholder_structure":
        n = result.get("shareholder_count", 0)
        activists = result.get("activist_shareholders", [])
        ow = result.get("ownership_breakdown", {})
        parts = [f"{n} shareholders from annual report"]
        if ow.get("foreign") is not None:
            parts.append(f"Foreign {ow['foreign']}%")
        if ow.get("institutional") is not None:
            parts.append(f"Institutional {ow['institutional']}%")
        if activists:
            parts.append(f"Activists: {', '.join(activists[:3])}")
        return " | ".join(parts)
    elif tool_name == "search_fund_holdings":
        n = result.get("unique_positions", 0)
        holdings = result.get("holdings", [])
        if holdings:
            top = holdings[0]
            stake = top.get("stake_pct")
            name = top.get("target_company", "?")
            return f"{n} positions found. Largest: {name} ({stake}%)" if stake else f"{n} positions found. Top: {name}"
        return f"{n} positions found"
    return json.dumps(result)[:100]
