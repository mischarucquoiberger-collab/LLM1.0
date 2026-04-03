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
        self.anthropic_api_key = settings.anthropic_api_key

        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - import-time fallback
            raise RuntimeError("OpenAI client is not installed. Add openai to requirements.") from exc

        self._client = OpenAI(api_key=self.api_key)
        self._anthropic_client = None

    def _get_anthropic_client(self):
        if self._anthropic_client is None:
            import anthropic
            self._anthropic_client = anthropic.Anthropic(api_key=self.anthropic_api_key)
        return self._anthropic_client

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
        # Use Claude Opus via Anthropic API for high-quality narrative
        use_anthropic = bool(self.anthropic_api_key)
        if not use_anthropic and not self.api_key:
            if on_stream:
                on_stream("API key missing. Draft streaming unavailable.\n")
            return "{}"

        system_prompt = (
            "You are a senior sell-side equity research analyst at a top-tier Japanese investment bank "
            "(Nomura, Daiwa, SMBC Nikko calibre). You write initiating-coverage research notes.\n\n"
            "OUTPUT FORMAT: You MUST return a STRICT JSON object with exactly the sections below. "
            "No markdown fences, no commentary outside the JSON.\n\n"
            "SECTION REQUIREMENTS:\n\n"
            "1. company_profile (string — 120-180 words, DENSE single paragraph):\n"
            "   Institutional-grade company introduction. You MUST cover ALL of these:\n"
            "   - Company English name with ticker, founding year/history (e.g. 'spun off from X in 1972', 'traces founding to 1887')\n"
            "   - Headquarters location (city, prefecture)\n"
            "   - Revenue scale in ¥B or ¥T and core business pillars with SPECIFIC product/service names\n"
            "   - Segment breakdown: name each reporting segment and their revenue contributions\n"
            "   - Employee count, operating margin compared to sector peers (cite the sector median)\n"
            "   - Current mid-term strategic plan BY NAME if known (e.g. 'Vista 2027', 'Toyota Environmental Challenge 2050')\n"
            "   - Global footprint: key subsidiaries, JVs, or geographic presence\n"
            "   Write like the analyst knows this company deeply. NEVER use generic phrases like 'operates in the X sector'.\n"
            "   EXAMPLE: 'FANUC Corporation, spun off from Fujitsu in 1972 and headquartered in Oshino, Yamanashi, is the world's "
            "dominant manufacturer of CNC controllers, industrial robots, and ROBOMACHINE systems. Commanding an estimated 50%+ global "
            "share in CNC controllers...'\n\n"
            "2. business_performance (string — 120-180 words, DENSE single paragraph):\n"
            "   Weave ALL of these together with exact ¥ figures:\n"
            "   - Revenue with YoY growth % and ¥ figure\n"
            "   - Operating income with YoY growth % and ¥ figure, noting recovery/decline context vs prior years\n"
            "   - Net income with ¥ figure\n"
            "   - EPS with ¥ figure, ROE trajectory across multiple years (e.g. 'ROE of 8.6% marks recovery from FY2024 trough of 8.0%, but remains below FY2023 peak of 10.8%')\n"
            "   - DPS with ¥ figure AND payout ratio %\n"
            "   - Buyback program details if any (amount, shares, timeline, execution progress)\n"
            "   - Capex trend (¥ figure, vs prior year)\n"
            "   - Final sentence: identify THE single most important financial trend and explain WHY it matters\n"
            "   NEVER just list numbers — weave them into analytical prose showing cause and effect.\n"
            "   EXAMPLE: 'FY2025 sales reached ¥797B (+0.3% YoY), while operating income recovered to ¥159B (+12% YoY) and net "
            "income rose to ¥148B after a ¥171B peak in FY2023. DPS increased to ¥94.39 (70% payout ratio)...'\n\n"
            "3. material_note (string — 2-3 sentences, 30-50 words):\n"
            "   The single most important risk or catalyst right now.\n"
            "   MUST be company-specific. Name the exact event, regulation, product, or structural shift.\n"
            "   NEVER write generic boilerplate like 'investors should monitor industry developments'.\n"
            "   EXAMPLE: 'Vista 2027 Stage I missed new-product sales targets by approximately 45%; Stage II launches with a ¥65B "
            "operating profit target, making execution in functional materials the decisive near-term catalyst.'\n\n"
            "4. investment_thesis (array of EXACTLY 4 strings):\n"
            "   Each bullet is 1-2 sentences, 15-25 words, citing SPECIFIC competitive advantages.\n"
            "   Name products, market shares, technologies, geographic positions, or financial metrics.\n"
            "   NEVER write generic bullets like 'Listed on TSE' or 'operates in X sector'.\n"
            "   EXAMPLE: 'World-leading ~50% global CNC controller market share; unrivaled installed base drives recurring service revenue'\n\n"
            "5. bull_case (array of EXACTLY 2 strings):\n"
            "   Each 1-2 sentences (25-40 words) with SPECIFIC upside scenario and numbers.\n"
            "   EXAMPLE: 'ROE sustained above 17% for five straight years; 65% payout ratio with active ¥9B buyback rewards holders.'\n\n"
            "6. bear_case (array of EXACTLY 2 strings):\n"
            "   Each 1-2 sentences (25-40 words) with SPECIFIC downside risk and numbers.\n"
            "   NEVER write 'market conditions may impact performance' — name the actual risk.\n"
            "   EXAMPLE: 'PER of 40x and PBR of 3.4x price perfection; ROE of 8.6% well below historic 10.8% peak leaves valuation vulnerable.'\n\n"
            "CRITICAL WRITING RULES:\n"
            "- Be SPECIFIC: name products, brands, projects, subsidiaries, JVs, strategy names. NEVER be generic.\n"
            "- Use REAL NUMBERS from the data: revenue in ¥B/¥T, margins %, ROE, DPS, EPS, OCF, capex.\n"
            "- Compute derived metrics: OCF/NI ratio, capex/sales %, payout ratio, revenue CAGR, FCF.\n"
            "- Reference MULTI-YEAR TRENDS: 'ROE improved from 5.2% to 8.0% over three years' not just 'ROE is 8.0%'.\n"
            "- Show context: compare current vs prior year peaks/troughs, vs sector medians.\n"
            "- ALL output MUST be in English. NEVER use Japanese characters (hiragana, katakana, kanji) anywhere. "
            "Always use the English company name, never the Japanese name. Translate any Japanese product or segment names to English.\n"
            "- If unknown, use '—'. Do NOT invent facts.\n"
            "- revenue_mix percentages MUST sum to ~100%. Use EDINET Segment Data as ground truth.\n"
            "- ownership_mix: ONLY populate if explicit ownership data exists. Otherwise all null.\n"
            "- geographic_mix: populate overseas_pct and domestic_pct if revenue breakdown by geography is known. Otherwise null.\n"
        )

        report_date = prompt_payload.get("generated_at") or ""
        facts_summary = prompt_payload.get("facts_summary", "")
        profile_block = prompt_payload.get("profile_block", "")
        research_context = prompt_payload.get("research_context", "")
        edinet_narrative = prompt_payload.get("edinet_narrative", "")
        valuation_block = prompt_payload.get("valuation_block", "")

        schema = """
Return JSON with EXACTLY this structure:
{
  "company_profile": "<120-180 word paragraph: founding/history, HQ, revenue scale, specific segments/products, employee count, margin vs peers, strategy plan name, global footprint>",
  "business_performance": "<120-180 word paragraph: revenue + YoY%, OP + YoY% vs prior year context, NI, EPS, ROE multi-year trajectory, DPS + payout%, buyback details, capex trend, most important trend + why>",
  "material_note": "<2-3 sentences: specific company risk/catalyst with names and numbers, NEVER generic>",
  "investment_thesis": [
    "<Specific competitive advantage with product/market share data>",
    "<Specific operational/structural advantage>",
    "<Specific financial metric advantage vs peers>",
    "<Specific strategic/balance sheet advantage>"
  ],
  "bull_case": [
    "<Specific upside scenario with numbers and timeframe>",
    "<Specific upside scenario with numbers and timeframe>"
  ],
  "bear_case": [
    "<Specific downside risk with numbers and valuation context>",
    "<Specific downside risk with numbers and valuation context>"
  ],
  "major_shareholders": [{"name":"<English name>", "pct":0, "change":"NEW|↑|↓|—"}],
  "cross_holdings": [{"name":"", "ticker":"", "pct_held":0}],
  "revenue_mix": [{"segment":"short name 2-5 words", "pct":0, "revenue_mm":0}],
  "peers": [{"ticker":"<TSE code>", "name":"<English name>", "mkt_cap_t":0}],
  "corporate_info": {"president":"<English name>", "employees":"<number>", "head_office":"<city, prefecture>"},
  "ownership_mix": {"foreign": null, "institutional": null, "corporate": null, "individual": null},
  "geographic_mix": {"overseas_pct": null, "domestic_pct": null},
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
            on_progress(84, "Drafting", "Synthesizing institutional-grade narrative (Claude Opus)")

        if use_anthropic:
            return self._generate_narrative_anthropic(system_prompt, user_prompt, on_stream)
        else:
            return self._generate_narrative_openai(system_prompt, user_prompt, on_stream)

    def _generate_narrative_anthropic(self, system_prompt: str, user_prompt: str, on_stream=None) -> str:
        client = self._get_anthropic_client()
        narrative_model = settings.anthropic_narrative_model or "claude-sonnet-4-6"
        if on_stream:
            content = ""
            with client.messages.stream(
                model=narrative_model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.25,
            ) as stream:
                for text in stream.text_stream:
                    content += text
                    on_stream(text)
            if not content.strip():
                raise RuntimeError("Claude streaming returned empty response for dashboard narrative")
            return content
        else:
            response = client.messages.create(
                model=narrative_model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.25,
            )
            if not response.content:
                return ""
            return response.content[0].text or ""

    def _generate_narrative_openai(self, system_prompt: str, user_prompt: str, on_stream=None) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
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

    def extract_edinet_all(self, company_name: str, stock_code: str, edinet_text: str) -> str:
        """Single LLM call to extract insights, summary, capital projects, and ESG.

        Replaces 4 separate calls that each sent the full edinet_text (~20KB),
        eliminating 3 redundant copies of the filing through the API.
        """
        if not self.api_key:
            return "{}"
        system_prompt = (
            "You are a Japanese financial analyst. Extract ALL of the following from the EDINET filing. "
            "All output MUST be in English. Translate any Japanese text. "
            "Return STRICT JSON only, no code fences. "
            "If a field is unknown, use an em dash '—' for strings or empty arrays []. Do not invent facts.\n\n"
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
            "- Do NOT confuse total consolidated figures with segment figures.\n\n"
            "For capital_projects:\n"
            "- Look for 設備投資, 事業計画, 開発計画, 資本的支出, 投資計画, "
            "主要な設備の新設, 重要な設備の新設・拡充.\n"
            "- Only include projects with concrete details (name, amount, or timeline).\n"
            "- Maximum 10 projects.\n\n"
            "For ESG:\n"
            "- Look for サステナビリティ, ESG, 環境, TCFD, 人的資本, "
            "ガバナンス, CO2, 気候変動, 多様性, ダイバーシティ, 人権, コンプライアンス.\n"
            "- Only include items with concrete details from the filing.\n\n"
            "For summary:\n"
            "- Summarize the filing into 2-3 English sentences.\n"
            "- Focus on business activities, recent changes, and governance signals.\n"
        )
        schema = """
Return a SINGLE JSON object with ALL of these top-level keys:

{
  "insights": {
    "business_segments": [
      {"name": "short name 2-5 words", "pct": 65.2, "revenue_mm": 12345, "profit_mm": 1234}
    ],
    "risk_factors": ["risk factor 1", "risk factor 2"],
    "governance": {
      "board": "board composition summary",
      "auditors": "auditor info",
      "ownership": "ownership structure notes"
    }
  },
  "summary": "2-3 English sentences summarizing the filing.",
  "capital_projects": [
    {
      "project_name": "Name of project",
      "type": "Office|Logistics|R&D|Factory|IT|Residential|Other",
      "timeline": "e.g. FY2025-FY2027 or Ongoing",
      "amount_mm": 1500,
      "description": "One sentence summary"
    }
  ],
  "esg": {
    "environmental": ["Concrete environmental initiative (1 sentence each)"],
    "social": ["Concrete social/HR initiative (1 sentence each)"],
    "governance": ["Concrete governance policy (1 sentence each)"],
    "certifications": ["ISO 14001", "TCFD supporter"]
  }
}

Rules:
- business_segments: percentages must sum to ~100%, compute from revenue if not stated
- capital_projects: max 10, amount_mm null if not disclosed, return [] if none found
- esg: max 5 items per category, use empty arrays if no info, certifications are short labels
- summary: 2-3 sentences, plain English
"""
        user_prompt = (
            f"Company: {company_name} ({stock_code})\n\n"
            "EDINET text:\n"
            f"{edinet_text}\n\n"
            f"{schema}"
        )
        return self._create_completion(system_prompt, user_prompt)

    def translate_segment_names(self, names: list[str]) -> list[str]:
        """Translate a list of Japanese segment/business names to concise English.

        Returns a list of the same length with English translations.
        """
        if not self.api_key or not names:
            return names
        import json as _json
        system_prompt = (
            "Translate these Japanese business segment names to concise English (2-6 words each). "
            "Use standard industry terminology. Examples:\n"
            "- 自動車事業 → Automotive\n"
            "- 金融サービス事業 → Financial Services\n"
            "- 情報通信事業 → Information & Communications\n"
            "- エンターテインメント事業 → Entertainment\n"
            "- 不動産事業 → Real Estate\n"
            "- 電子デバイス事業 → Electronic Devices\n"
            "- ヘルスケア事業 → Healthcare\n"
            "- アパレル事業 → Apparel\n"
            "Return a JSON array of translated strings in the same order. "
            "Return ONLY the JSON array, no markdown fences."
        )
        user_prompt = _json.dumps(names, ensure_ascii=False)
        try:
            raw = self._create_completion(system_prompt, user_prompt)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = _json.loads(raw)
            if isinstance(result, list) and len(result) == len(names):
                return [str(r).strip()[:40] for r in result]
        except Exception:
            pass
        return names

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
