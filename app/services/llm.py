from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from app.config import settings


@dataclass
class LlmSection:
    title: str
    body: str


class LlmClient:
    def __init__(self) -> None:
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model

        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - import-time fallback
            raise RuntimeError("OpenAI client is not installed. Add openai to requirements.") from exc

        self._client = OpenAI(api_key=self.api_key)

    def _create_completion(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        if not response.choices:
            return ""
        return response.choices[0].message.content or ""

    def _create_completion_stream(self, system_prompt: str, user_prompt: str, on_chunk=None) -> str:
        stream = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            stream=True,
        )
        content = ""
        for event in stream:
            try:
                delta = event.choices[0].delta.content
            except Exception:
                delta = None
            if delta:
                content += delta
                if on_chunk:
                    on_chunk(delta)
        return content

    def generate_report_markdown(self, prompt_payload: Dict, on_progress=None) -> str:
        if not self.api_key:
            return "## Executive Summary\n\nAPI key missing. Provide OPENAI_API_KEY to generate content."

        system_prompt = (
            "You are a senior sell-side equity research analyst. Write in English with analytical rigor. "
            "Use citations like [1] that map to the provided sources. Do NOT invent facts. "
            "If information is missing, explicitly say it is not available. "
            "Keep claims grounded in the provided data and sources only. "
            "If the company name or sector is unresolved, do not infer it from memory. "
            "ALL output MUST be in English. Translate any Japanese text (product names, app names, "
            "brands, proper nouns) to English or romaji. Never output Japanese characters."
        )

        report_mode = prompt_payload.get("report_mode", "full")
        appendix_tables = prompt_payload.get("appendix_tables_md", "")
        facts_summary = prompt_payload.get("facts_summary", "")

        unresolved_note = ""
        if prompt_payload.get("company_name") == "Unknown Company":
            unresolved_note = (
                "IMPORTANT: The company name is unresolved. Do NOT guess the company identity. "
                "Refer to the company only as 'Unknown Company'.\n\n"
            )

        report_date = prompt_payload.get("generated_at") or ""
        v6_data_block = prompt_payload.get("v6_data_block", "")
        valuation_block = prompt_payload.get("valuation_block", "")
        profile_block = prompt_payload.get("profile_block", "")
        research_context = prompt_payload.get("research_context", "")
        edinet_narrative = prompt_payload.get("edinet_narrative", "")

        template = f"""
Write the report in the exact V6 section order and headings below. Keep the headings verbatim.
If data is missing, write "N/A" (do not use phrases like "Not disclosed in provided sources").
If a field is "N/A" in the profile block but evidence exists in the research context or EDINET
extract, use that evidence and cite it.
Use citations [id] at the end of each paragraph or bullet list that relies on sources.
Do NOT add a References or Appendix section (they are appended separately).

TITLE LINE:
"{{company}} ({{code}}) — Company Overview & Analytical Framework"
SUBTITLE LINE:
"No Rating / No Target Price • {{date}}"

SECTIONS (use this exact order):
1. Company Snapshot
2. Executive Summary
3. Investment Framework (Key Debates)
4. Business Overview
5. Industry Context and Company Exposure
6. Sources of Competitive Advantage (Descriptive)
7. Financial Snapshot
8. Net sales and operating margin trend (FY2021–FY2025)  (table)
9. Cash Flow and Working-Capital Dynamics
10. Peer Benchmarking (High-Level Anchoring)
11. Governance and Management
12. Why Now (12–24 Month Set-Up)
13. Scenario Framework (Illustrative)
14. Valuation Context (No Rating / No Target Price)
15. Key Monitoring Indicators
16. Risks (Prioritized)
17. Conclusion (Non-Recommendation)
18. Disclosures

Formatting requirements:
- Company Snapshot: bullet list of fields (Company name, Representative, Founded, Head Office, Employees,
  Listed markets, Securities code, Core businesses).
- Executive Summary: 1-2 paragraphs + 3-5 bullets.
- Investment Framework: bullets.
- Financial Snapshot: bullets using EDINET numbers if available.
- Net sales and operating margin trend: Markdown table with Fiscal year, Net sales, Operating margin.
- Scenario Framework: table with Scenario, Operating margin, Inventory days, Narrative.
- Risks (Prioritized): short paragraph then a small risk matrix table with Risk | Impact | Time horizon | Mechanism.

IMPORTANT: Use V6 DATA BLOCK for numbers and tables. Do NOT recompute or invent.
If cash flow numbers are provided, use them in the Cash Flow and Working-Capital Dynamics section.
If valuation model output is provided, summarize it in the Valuation Context section as:
- ML multiple-based implied price & range
- Peer-multiple implied price & range
- DCF implied price & range
 - SOTP proxy implied price & range (if available; otherwise explain data gap)
These are non-recommendation outputs; do not issue a rating or target price.
"""

        parts = [
            template,
            f"Report mode: {report_mode}. If mode is fast, keep sections concise but still analytical.\n\n",
            unresolved_note,
            f"Company: {prompt_payload.get('company_name')} ({prompt_payload.get('stock_code')})\n",
            f"Sector: {prompt_payload.get('sector') or 'Unknown'}\n",
            f"Date: {report_date}\n\n",
            "Facts Summary:\n",
            f"{facts_summary}\n\n",
            "V6 DATA BLOCK:\n",
            f"{v6_data_block}\n\n",
            "VALUATION MODEL OUTPUT:\n",
            f"{valuation_block}\n\n",
            "COMPANY PROFILE EXTRACTS:\n",
            f"{profile_block}\n\n",
            "RESEARCH CONTEXT EXTRACTS (may include Japanese):\n",
            f"{research_context}\n\n",
            "EDINET NARRATIVE EXTRACT (Japanese, use for Business Overview, Risks, Governance):\n",
            f"{edinet_narrative}\n\n",
            "Sources (cite as [id]):\n",
            "\n".join([f"[{s['id']}] {s['title']} - {s['url']}" for s in prompt_payload.get("sources", [])]),
            "\n\n",
            "Key Metrics (JSON):\n",
            prompt_payload.get("metrics_json", "{}"),
            "\n\n",
        ]

        if appendix_tables:
            parts.append(
                "Appendix tables (already rendered; do not repeat, but reference them when relevant):\n"
                + appendix_tables
            )

        base_context = "".join(parts)

        if report_mode == "full":
            outline_prompt = (
                "Create a concise outline that follows the exact V6 section order. "
                "Use the exact headings and include 2-4 bullets each. "
                "Only include bullets you can support with the given facts or sources."
            )
            if on_progress:
                on_progress(84, "Drafting", "Building analytical outline")
            outline = self._create_completion(system_prompt, f"{outline_prompt}\n\n{base_context}")
            if on_progress:
                on_progress(88, "Drafting", "Writing full report draft")
            draft_prompt = f"Use the following outline to write the full V6-style report:\n\n{outline}\n\n{base_context}"
            return self._create_completion(system_prompt, draft_prompt)

        if on_progress:
            on_progress(85, "Drafting", "Writing report draft")
        return self._create_completion(system_prompt, base_context)

    def generate_dashboard_narrative(self, prompt_payload: Dict, on_progress=None, on_stream=None) -> str:
        if not self.api_key:
            if on_stream:
                on_stream("OpenAI API key missing. Draft streaming unavailable.\n")
            return "{}"

        target_model = self.model

        system_prompt = (
            "You are a senior sell-side equity research analyst at a top-tier Japanese investment bank "
            "(Nomura, Daiwa, SMBC Nikko calibre).  You write initiating-coverage research notes.\n\n"
            "CRITICAL LENGTH REQUIREMENTS — your output will be REJECTED if too short:\n"
            "- summary_text: MINIMUM 3 full sentences (50+ words). Describe business model, market position, "
            "key products/services, geographic scope, and competitive advantages.\n"
            "- company_bullets: EXACTLY 3 bullets, each 1-2 full sentences (20+ words each). "
            "Each must be substantive with named products, strategies, or market positions.\n"
            "- outlook_summary: MINIMUM 8 sentences (120+ words). This is the MOST IMPORTANT section. "
            "It must be a dense analytical paragraph covering: (1) latest revenue & operating income with "
            "exact yen figures and YoY growth rates, (2) margin trend over time, (3) ROE level and trajectory "
            "vs prior years, (4) operating cash flow vs net income ratio and earnings quality implications, "
            "(5) capex levels and investment intensity, (6) dividend changes/policy, (7) management's named "
            "medium-term strategy and key initiatives, (8) key execution risks or headwinds.\n"
            "- bull_case: EXACTLY 3 bullets, each 2-3 full sentences (30+ words each) with specific metrics.\n"
            "- bear_case: EXACTLY 3 bullets, each 2-3 full sentences (30+ words each) with specific metrics.\n\n"
            "WRITING RULES:\n"
            "1. Be SPECIFIC — name products, brands, geographies, flagship projects, strategy names. "
            "Never write generic statements like 'the company has strong fundamentals'. Instead write: "
            "'Toyota's hybrid powertrain dominance (50%+ global HEV share) provides a durable margin advantage "
            "as electrification transitions unfold unevenly across geographies.'\n"
            "2. Use REAL NUMBERS from the data — quote revenue in ¥B format, margins as %, ROE, OCF, capex, "
            "YoY changes, 5-year CAGRs. Compute derived metrics: OCF/net income ratio, capex/sales %, "
            "debt/equity, payout ratio, revenue CAGR from multi-year data if available.\n"
            "3. Reference MULTI-YEAR TRENDS when data is provided — do not just cite the latest period. "
            "Say 'ROE improved from 5.2% to 8.0% over five years' rather than just 'ROE is 8.0%'.\n"
            "4. For the outlook, write in a flowing analytical style — connect financial metrics to business "
            "implications. Example: 'Operating cash flow surged 148% to ¥599B, significantly outpacing "
            "net income and suggesting high-quality earnings, though capex remains elevated at ¥322B "
            "indicating continued growth investment.'\n"
            "5. ALL output text MUST be in English. Translate every Japanese word, product name, "
            "app name, brand name, and proper noun to English or romaji. Never output Japanese "
            "characters (hiragana, katakana, kanji) in any field. For example: 'FXなび' → 'FX Navi', "
            "'株たす' → 'Kabu Tasu', 'トウシカ' → 'Toushika'.\n"
            "6. Use citations [id] when supported by sources.\n"
            "7. Return STRICT JSON only.  No markdown fences.\n"
            "8. If information is genuinely unknown, use '—'.  Do NOT invent facts.\n"
            "9. revenue_mix percentages MUST sum to ~100%. Segment names must be short (2-5 words), "
            "NOT paragraph descriptions. Include revenue_mm (revenue in millions of yen) when available.\n"
            "10. If the Facts Summary contains 'EDINET Segment Data' with parsed segment names, revenues, "
            "and percentages, use those as GROUND TRUTH for revenue_mix. Copy the segment names and "
            "percentages exactly — do NOT invent different segments or change the numbers. "
            "You may translate Japanese segment names to short English equivalents.\n"
            "11. For ownership_mix: ONLY provide values if the data explicitly contains 所有者別状況 "
            "(ownership by holder type) percentages. Typical ranges: Foreign 10-35%, Institutional "
            "15-40%, Corporate 10-30%, Individual 15-40%. If no ownership data found, return ALL "
            "null values. Do NOT guess. Values must sum to ~100%.\n"
        )

        report_date = prompt_payload.get("generated_at") or ""
        facts_summary = prompt_payload.get("facts_summary", "")
        profile_block = prompt_payload.get("profile_block", "")
        research_context = prompt_payload.get("research_context", "")
        edinet_narrative = prompt_payload.get("edinet_narrative", "")
        valuation_block = prompt_payload.get("valuation_block", "")

        schema = """
Return JSON with EXACTLY this structure. READ THE LENGTH REQUIREMENTS — every narrative field has a MINIMUM word count:
{
  "summary_text": "<COMPANY DESCRIPTION — MINIMUM 50 words, 3 sentences. Describe: (a) what the company does and its core business model, (b) its market position and scale (e.g. 'Japan's largest...', '#2 player in...'), (c) key products/services/brands/assets, (d) geographic scope. Write as if briefing an institutional investor. EXAMPLE: 'Mitsui Fudosan is Japan's largest comprehensive real estate developer, managing a diverse portfolio that includes premium office buildings, retail centers, and residential developments. The company is a market leader in large-scale urban redevelopment projects and maintains a significant global presence across North America, Europe, and Asia.'>",

  "company_bullets": [
    "<BULLET 1 — MINIMUM 20 words. Specific market position with named flagship products/projects/brands. EXAMPLE: 'Holds a dominant market position in Japan through iconic flagship developments such as Tokyo Midtown, Nihonbashi, and the LaLaport retail chain.'>",
    "<BULLET 2 — MINIMUM 20 words. Business model strength or diversification with specifics. EXAMPLE: 'Maintains a highly diversified and resilient business mix spanning office leasing, residential sales, logistics, and luxury hospitality.'>",
    "<BULLET 3 — MINIMUM 20 words. Strategic edge, competitive moat, or operational advantage. EXAMPLE: 'Leverages strong brand equity and an integrated value chain that encompasses development, management, and real estate brokerage services.'>"
  ],

  "outlook_summary": "<DENSE ANALYTICAL PARAGRAPH — MINIMUM 120 words, 8+ sentences. This is the most important section. Weave together ALL of these elements in a flowing narrative: (1) latest revenue and operating income with exact ¥B figures and YoY growth %, (2) operating margin level and trend vs prior years, (3) ROE level and multi-year trajectory with basis point changes, (4) operating cash flow amount and ratio to net income — what this implies about earnings quality, (5) capex amount and % of sales — what this implies about investment intensity, (6) dividend per share changes and payout ratio context, (7) management's named medium-term plan/strategy and 2-3 key strategic initiatives, (8) 1-2 specific execution risks. Connect metrics to business implications. EXAMPLE QUALITY: 'Mitsui Fudosan demonstrates strong operational momentum with revenue growing 10.2% YoY to ¥2,625B in FY2025 and operating income expanding 9.7% to ¥373B, while ROE improved 50bps to 8.0%. Operating cash flow surged 148% to ¥599B, significantly outpacing net income and suggesting high-quality earnings, though capex remains elevated at ¥322B indicating continued growth investment. The dividend cut from ¥84 to ¥31 in FY2025 is notable despite steady 40%+ payout ratios, likely reflecting normalization after a one-time special dividend. Management's \"& INNOVATION 2030\" strategy positions the company as an \"industrial developer\" focused on ESG integration, TCFD/RE100 commitments, and value-added real estate beyond traditional landlord models, though execution risk remains on these ambitious transformation goals.'>",

  "bull_case": [
    "<BULL 1 — MINIMUM 30 words, 2-3 sentences. Growth or profitability thesis with multi-year trends and specific numbers. EXAMPLE: 'Consistent top-line growth with 5-year revenue CAGR of 5.5% and improving operating margins (14.2% in FY2025 vs 10.2% in FY2021) demonstrate pricing power and operational leverage in Japan's recovering real estate market'>",
    "<BULL 2 — MINIMUM 30 words, 2-3 sentences. Cash flow, balance sheet, or capital return thesis with metrics>",
    "<BULL 3 — MINIMUM 30 words, 2-3 sentences. Strategic positioning, ROE improvement, or management quality thesis>"
  ],

  "bear_case": [
    "<BEAR 1 — MINIMUM 30 words, 2-3 sentences. Valuation risk with specific multiples and comparison. EXAMPLE: 'PER of 20.8x represents stretched valuation relative to 8.0% ROE, implying market has priced in significant multiple expansion with limited margin of safety'>",
    "<BEAR 2 — MINIMUM 30 words, 2-3 sentences. Operational or financial risk with metrics>",
    "<BEAR 3 — MINIMUM 30 words, 2-3 sentences. Structural, competitive, or macro risk>"
  ],

  "major_shareholders": [{"name":"<English name>", "pct":0, "change":"NEW|↑|↓|—"}],
  "cross_holdings": [{"name":"", "ticker":"", "pct_held":0}],
  "revenue_mix": [{"segment":"short name 2-5 words", "pct":0, "revenue_mm":0}],
  "peers": [{"ticker":"<TSE code>", "name":"<English name>", "mkt_cap_t":0}],
  "corporate_info": {"president":"<English name>", "employees":"<number>", "head_office":"<city, prefecture>"},
  "ownership_mix": {"foreign": null, "institutional": null, "corporate": null, "individual": null},
  "disclosures": [{"date":"YYYY-MM-DD", "title":"", "detail":""}],
  "tags": ["REFORM DISCLOSED"]
}
"""

        user_prompt = (
            f"Date: {report_date}\n\n"
            "Facts Summary:\n"
            f"{facts_summary}\n\n"
            "Company Profile Extracts:\n"
            f"{profile_block}\n\n"
            "Valuation Model Output:\n"
            f"{valuation_block}\n\n"
            "Research Context & Mandatory Research Points:\n"
            f"{research_context}\n\n"
            "EDINET Narrative Extract:\n"
            f"{edinet_narrative}\n\n"
            "EDINET Insights (JSON):\n"
            f"{prompt_payload.get('edinet_insights', {})}\n\n"
            "Sources (cite as [id]):\n"
            + "\n".join([f"[{s['id']}] {s['title']} - {s['url']}" for s in prompt_payload.get("sources", [])])
            + "\n\n"
            + schema
        )

        if on_progress:
            on_progress(84, "Drafting", "Synthesizing institutional-grade narrative")

        response = self._client.chat.completions.create(
            model=target_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.25,
            stream=on_stream is not None,
        )

        if on_stream:
            content = ""
            for event in response:
                try:
                    delta = event.choices[0].delta.content
                    if delta:
                        content += delta
                        on_stream(delta)
                except (IndexError, AttributeError, TypeError):
                    continue
            if not content.strip():
                raise RuntimeError("LLM streaming returned empty response for dashboard narrative")
            return content
        else:
            if not response.choices:
                return ""
            return response.choices[0].message.content or ""

    def translate_json_to_english(self, json_text: str) -> str:
        if not self.api_key:
            return json_text
        system_prompt = (
            "Translate all string values in the JSON to English. "
            "Preserve keys, numbers, punctuation, and JSON structure exactly. "
            "Use romaji for Japanese names, and you may keep the original Japanese in parentheses if short. "
            "Return STRICT JSON only."
        )
        user_prompt = f"JSON to translate:\n{json_text}"
        return self._create_completion(system_prompt, user_prompt)

    def translate_and_classify_shareholders(self, shareholders_json: str) -> str:
        if not self.api_key:
            return shareholders_json
        system_prompt = (
            "You are a Japanese financial data specialist. "
            "Translate Japanese shareholder names to clear English and classify each shareholder type.\n\n"
            "Classification rules:\n"
            "- 信託銀行(信託口), マスタートラスト, カストディ, custody, trust bank (trust account) → Institution\n"
            "- 投資信託, ファンド, fund, asset management, investment trust → Fund\n"
            "- Individual/personal names (Japanese or romaji) → Person\n"
            "- 株式会社, Co., Ltd., Corp., Inc., corporate entities → Corporate\n"
            "- 財務大臣, government, ministry, 政府 → Government\n"
            "- 自社, treasury stock, 自己株式 → Treasury\n\n"
            "Return STRICT JSON array only, no markdown fences. "
            "Each element: {\"original\": \"<original name>\", \"english\": \"<English name>\", \"type\": \"Institution|Fund|Person|Corporate|Government|Treasury\"}"
        )
        user_prompt = f"Translate and classify these shareholder names:\n{shareholders_json}"
        return self._create_completion(system_prompt, user_prompt)

    def extract_profile_from_sources(self, company_name: str, stock_code: str, research_context: str, edinet_narrative: str) -> str:
        if not self.api_key:
            return "{}"
        system_prompt = (
            "Extract a concise company profile from the provided sources. "
            "All output must be in English. Translate any Japanese text. "
            "Return STRICT JSON only, no code fences. "
            "If a field is unknown, use an em dash '—'. Do not invent facts."
        )
        schema = """
Return JSON with this exact structure:
{
  "company_name": "",
  "representative": "",
  "founded": "",
  "head_office": "",
  "employees": "",
  "listed_markets": "",
  "core_businesses": "",
  "sector": "",
  "market": ""
}
"""
        user_prompt = (
            f"Company: {company_name} ({stock_code})\n\n"
            "Research Context:\n"
            f"{research_context}\n\n"
            "EDINET Narrative:\n"
            f"{edinet_narrative}\n\n"
            f"{schema}"
        )
        return self._create_completion(system_prompt, user_prompt)

    def extract_edinet_insights(self, company_name: str, stock_code: str, edinet_text: str) -> str:
        if not self.api_key:
            return "{}"
        system_prompt = (
            "Extract key EDINET insights in English. "
            "Translate any Japanese text. "
            "Return STRICT JSON only, no code fences. "
            "If a field is unknown, use an em dash '—'. Do not invent facts.\n\n"
            "IMPORTANT for business_segments:\n"
            "- Look for the セグメント情報 (segment information) section in the filing.\n"
            "- Look for tables showing 報告セグメント (reporting segments) with columns like:\n"
            "  外部顧客への売上高 (sales to external customers), セグメント利益 (segment profit).\n"
            "- Also check 事業の内容 (description of business) for segment names and descriptions.\n"
            "- Each segment name MUST be short (2-5 words), NOT a paragraph description.\n"
            "- Include revenue in millions of yen (revenue_mm) when available in the filing.\n"
            "- Percentages must sum to approximately 100%.\n"
            "- If exact percentages are not stated, compute them from revenue amounts.\n"
            "- Include profit_mm (segment profit in millions of yen) when available.\n"
            "- Do NOT confuse total consolidated figures with segment figures."
        )
        schema = """
Return JSON with this exact structure:
{
  "business_segments": [
    {"name": "short name 2-5 words", "pct": 65.2, "revenue_mm": 12345, "profit_mm": 1234},
    {"name": "short name 2-5 words", "pct": 34.8, "revenue_mm": 6789, "profit_mm": 678}
  ],
  "risk_factors": ["..."],
  "governance": {
    "board": "",
    "auditors": "",
    "ownership": ""
  }
}
"""
        user_prompt = (
            f"Company: {company_name} ({stock_code})\n\n"
            "EDINET text:\n"
            f"{edinet_text}\n\n"
            f"{schema}"
        )
        return self._create_completion(system_prompt, user_prompt)

    def extract_capital_projects(self, company_name: str, stock_code: str, edinet_text: str) -> str:
        if not self.api_key:
            return "[]"
        system_prompt = (
            "Extract capital investment and project pipeline information from the EDINET filing. "
            "Look for sections related to: 設備投資, 事業計画, 開発計画, 資本的支出, 投資計画, "
            "主要な設備の新設, 重要な設備の新設・拡充. "
            "Translate all Japanese text to English. "
            "Return STRICT JSON only, no code fences. "
            "If no project information is found, return an empty array []."
        )
        schema = """
Return a JSON array with this structure:
[
  {
    "project_name": "Name or description of the project",
    "type": "Office|Logistics|R&D|Factory|IT|Residential|Other",
    "timeline": "e.g. FY2025-FY2027 or Ongoing",
    "amount_mm": 1500,
    "description": "One sentence summary of the project purpose"
  }
]
Rules:
- amount_mm is the investment amount in millions of yen. Use null if not disclosed.
- type must be one of: Office, Logistics, R&D, Factory, IT, Residential, Other
- Maximum 10 projects
- Only include projects with concrete details (name, amount, or timeline)
"""
        user_prompt = (
            f"Company: {company_name} ({stock_code})\n\n"
            "EDINET text:\n"
            f"{edinet_text}\n\n"
            f"{schema}"
        )
        return self._create_completion(system_prompt, user_prompt)

    def extract_esg_data(self, company_name: str, stock_code: str, edinet_text: str) -> str:
        if not self.api_key:
            return "{}"
        system_prompt = (
            "Extract ESG (Environmental, Social, Governance) information from the EDINET filing. "
            "Look for sections related to: サステナビリティ, ESG, 環境, TCFD, 人的資本, "
            "ガバナンス, CO2, 気候変動, 多様性, ダイバーシティ, 人権, コンプライアンス. "
            "Translate all Japanese text to English. "
            "Return STRICT JSON only, no code fences. "
            "If no ESG information is found, return an empty object {}."
        )
        schema = """
Return JSON with this exact structure:
{
  "environmental": ["Concrete environmental initiative or metric (1 sentence each)"],
  "social": ["Concrete social/HR initiative or metric (1 sentence each)"],
  "governance": ["Concrete governance structure or policy (1 sentence each)"],
  "certifications": ["ISO 14001", "TCFD supporter", etc.]
}
Rules:
- Each array should have 1-5 items maximum
- Only include items with concrete details from the filing
- Use empty arrays [] for categories with no information
- Certifications should be short labels, not sentences
"""
        user_prompt = (
            f"Company: {company_name} ({stock_code})\n\n"
            "EDINET text:\n"
            f"{edinet_text}\n\n"
            f"{schema}"
        )
        return self._create_completion(system_prompt, user_prompt)

    def summarize_edinet(self, edinet_text: str) -> str:
        if not self.api_key:
            return ""
        system_prompt = (
            "Summarize the EDINET filing excerpt into 2-3 English sentences. "
            "Translate any Japanese. Focus on business activities, recent changes, and governance signals. "
            "Return plain text only."
        )
        return self._create_completion(system_prompt, edinet_text[:4000])

    def extract_shareholders(self, html_snippet: str, ticker: str) -> str:
        if not self.api_key:
            return "{}"
        
        prompt = f"""You are a Japanese financial data specialist.

Below is HTML from a Japanese stock website for ticker {ticker}.
Your job:
1. Find the major shareholders (大株主) table
2. Extract ALL shareholders listed (not just top 5 — get all of them, up to 20)
3. Translate every Japanese company/person name into clear English
   - 野村証券 → Nomura Securities Co., Ltd.
   - 三井住友信託銀行 → Sumitomo Mitsui Trust Bank
   - 日本マスタートラスト信託銀行 → Japan Master Trust Bank
   - 個人名 (individual names) → keep romanized (e.g. 梢 政樹 → Kozue Masaki)
4. Identify the report date (e.g. "Dec 2024" or "2024年12月末")

Return ONLY a valid JSON object (no markdown fences, no extra text):
{{
  "report_date": "Dec 2024",
  "shareholders": [
    {{
      "rank": 1,
      "name_en": "Kozue Masaki (Individual)",
      "name_jp": "梢 政樹",
      "shares": "940,000",
      "pct": "17.41",
      "change": ""
    }},
    {{
      "rank": 2,
      "name_en": "TreeTop Co., Ltd.",
      "name_jp": "ＴｒｅｅＴｏｐ株式会社",
      "shares": "800,000",
      "pct": "14.82",
      "change": "↓"
    }}
  ]
}}

Rules for "change" field:
- "NEW" if marked as newly appearing
- "↑"  if ownership increased
- "↓"  if ownership decreased
- "—"  if no change indicated

HTML:
{html_snippet}"""

        return self._create_completion("You are a Japanese financial data specialist.", prompt)

    def infer_ownership_and_peers(self, company_name: str, stock_code: str, context: str) -> str:
        if not self.api_key:
            return "{}"
        system_prompt = (
            "Infer ownership mix and key peers from the provided context. "
            "Return STRICT JSON only. "
            "If unknown, use null. "
            "Do not invent exact numbers; prefer approximate percentages only if clearly stated."
        )
        schema = """
Return JSON:
{
  "ownership_mix": {"foreign": null, "institutional": null, "corporate": null, "individual": null},
  "peers": [{"ticker": "", "name": "", "mkt_cap_t": null}]
}
"""
        user_prompt = (
            f"Company: {company_name} ({stock_code})\n\n"
            "Context:\n"
            f"{context}\n\n"
            f"{schema}"
        )
        return self._create_completion(system_prompt, user_prompt)
