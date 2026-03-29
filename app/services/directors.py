"""
Director network data generation with SERP + web scrape research pipeline.

Four-phase approach:
  1. SERP Research  — parallel searches for board composition, governance, LinkedIn
  2. Web Scrape     — fetch the official company executives page for ground truth
  3. Director Deep-Dive — individual LinkedIn/career searches per director
  4. GPT Synthesis  — feed ALL verified research into GPT to build structured JSON

The web scrape step is critical for accuracy — SERP snippets mix current/former directors.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import httpx

_shared_http_client: httpx.Client | None = None

def _get_http_client() -> httpx.Client:
    global _shared_http_client
    if _shared_http_client is None:
        _shared_http_client = httpx.Client(
            timeout=15,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
        )
    return _shared_http_client

from app.config import settings
from app.services.serp import SerpClient
from app.services.concurrent import run_concurrent

logger = logging.getLogger(__name__)

CACHE_DIR = Path("cache/directors")
CACHE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_text(text: str) -> str:
    """Strip control characters that break JSON serialization."""
    return _CONTROL_CHARS.sub("", text)


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars."""
    return text[:max_chars] if len(text) > max_chars else text


def get_director_network(ticker: str, company_name: str) -> dict:
    """Return director network data, using cache if available."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{ticker}.json"

    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < CACHE_MAX_AGE:
            return json.loads(cache_file.read_text(encoding="utf-8"))

    data = _research_and_generate(ticker, company_name)
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


# ── Phase 1: SERP Research ─────────────────────────────────

def _phase1_company_research(serp: SerpClient, ticker: str, company_name: str) -> tuple[str, list[str]]:
    """Run parallel searches for board composition, governance data, and LinkedIn.

    Returns (research_text, candidate_page_urls).
    """
    queries = [
        # Official site searches
        f"{company_name} official site board of directors executives",
        f"{company_name} corporate governance directors members",
        f"{company_name} investor relations board composition",
        # General English searches
        f"{company_name} current board of directors 2025",
        f"{company_name} board composition independent directors",
        f"{company_name} annual report directors committee",
        # LinkedIn
        f"site:linkedin.com {company_name} board director",
        f"site:linkedin.com {company_name} CEO president",
        # Social media discovery (batch — catches prominent directors)
        f"site:x.com {company_name} CEO chairman director board",
        f"site:twitter.com {company_name} CEO chairman director board",
        f"site:instagram.com {company_name} CEO chairman director",
        f"site:en.wikipedia.org {company_name} director CEO chairman",
        # Japanese searches
        f"{company_name} 取締役 役員一覧 現在",
        f"{company_name} コーポレートガバナンス報告書 2025",
        f"{company_name} 有価証券報告書 役員",
        f"{company_name} 社外取締役 独立役員",
    ]

    tasks = [lambda q=q: serp.search(q, num=5, news=False) for q in queries]
    # News about recent board changes
    news_queries = [
        f"{company_name} board director appointment 2025",
    ]
    tasks.extend([lambda q=q: serp.search(q, num=3, news=True) for q in news_queries])

    results = run_concurrent(tasks, max_workers=10)

    seen_urls = set()
    snippets = []
    candidate_pages = []

    for batch in results:
        if not batch:
            continue
        for r in batch:
            if r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            entry = f"[{r.source_type.upper()}] {r.title}\nURL: {r.url}\n{r.snippet}"
            if r.date:
                entry += f"\n(Date: {r.date})"
            snippets.append(entry)

            # Identify candidate official pages for Phase 2 scraping
            url_lower = r.url.lower()
            title_lower = r.title.lower()
            is_official = any(kw in url_lower or kw in title_lower for kw in [
                "executive", "director", "officer", "governance", "profile",
                "management", "board", "役員", "取締役", "ガバナンス",
            ])
            is_company_site = not any(d in url_lower for d in [
                "linkedin.com", "wikipedia.org", "marketscreener.com",
                "globaldata.com", "bloomberg.com", "reuters.com",
                "sec.gov", "irbank.net", "buffett-code.com",
            ])
            if is_official and is_company_site:
                candidate_pages.append(r.url)

    research_text = _sanitize_text("\n\n".join(snippets[:50]))
    logger.info("Phase 1: collected %d results, %d candidate pages", len(snippets), len(candidate_pages))
    return research_text, candidate_pages[:5]


# ── Phase 2: Web Scrape Official Page ──────────────────────

def _fetch_page(url: str) -> str | None:
    """Fetch a URL and extract text content, or return None on failure."""
    try:
        resp = _get_http_client().get(url, headers={
            "Accept": "text/html,application/xhtml+xml",
        })
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get("content-type", "")
        if "html" not in content_type and "text" not in content_type:
            return None
        text = resp.text
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        has_keywords = any(kw in text.lower() for kw in [
            "director", "chairman", "president", "executive", "board",
            "取締役", "代表取締役", "社長", "会長", "執行役", "監査",
        ])
        return text[:8000] if has_keywords else None
    except Exception as exc:
        logger.debug("Failed to fetch %s: %s", url, exc)
        return None


def _phase2_scrape_official_pages(candidate_urls: list[str], company_name: str,
                                   ticker: str = "") -> str:
    """Fetch candidate official executive pages and extract text content.

    Uses irbank.net as a fallback when no official company pages could be scraped
    (e.g. when the company website blocks bots, like sony.com).
    """
    # Filter out URLs that likely contain past/historical/non-current data
    # or belong to subsidiary companies (e.g. sonypictures.com, sonymusic.com)
    skip_url_patterns = [
        "/past", "/history", "/archive", "/2024", "/2023", "/2022", "/2021",
        "/biograph", "/pressroom", "/newsroom", "/press-release", "/news/",
    ]
    # Subsidiary domains: these are separate companies, not the parent
    skip_domains = [
        "sonypictures.com", "sonymusic.com", "sonyinteractive.com",
        "toyotafinancial.com", "lexus.com",
        "indeed.com", "glassdoor.com",
    ]
    filtered_urls = []
    for url in (candidate_urls or []):
        url_lower = url.lower()
        if any(pat in url_lower for pat in skip_url_patterns):
            logger.debug("Skipping historical/non-current URL: %s", url)
            continue
        if any(dom in url_lower for dom in skip_domains):
            logger.debug("Skipping subsidiary domain: %s", url)
            continue
        filtered_urls.append(url)

    # First try the candidate official pages (limit to 3 best)
    pages = []
    if filtered_urls:
        urls_to_try = filtered_urls[:3]
        tasks = [lambda u=u: _fetch_page(u) for u in urls_to_try]
        results = run_concurrent(tasks, max_workers=5)
        for i, text in enumerate(results):
            if text:
                pages.append(f"=== OFFICIAL PAGE: {urls_to_try[i]} ===\n{text}")

    # Always try irbank.net — structured officer data for all TSE companies
    if ticker:
        irbank_url = f"https://irbank.net/{ticker}/officer"
        irbank_text = _fetch_page(irbank_url)
        if irbank_text:
            is_primary = len(pages) == 0
            label = ("IRBANK OFFICER DATA (PRIMARY SOURCE — no official page available)"
                     if is_primary else
                     "IRBANK OFFICER DATA (CROSS-REFERENCE)")
            irbank_entry = (
                f"=== {label} ===\n"
                f"WARNING: This lists BOTH 取締役 (directors) AND 執行役 (executive officers). "
                f"ONLY include people explicitly labeled 取締役.\n{irbank_text}"
            )
            # If irbank is the PRIMARY source (no official pages), put it FIRST
            # Otherwise append as supplementary (official pages are better)
            if is_primary:
                pages.insert(0, irbank_entry)
            else:
                pages.append(irbank_entry)
            if is_primary:
                logger.info("No official pages scraped — using irbank as primary source")

    combined = _sanitize_text("\n\n".join(pages))
    logger.info("Phase 2: scraped %d pages successfully", len(pages))
    return combined


# ── Phase 3: Director Deep-Dive + LinkedIn ─────────────────

def _match_name_to_result(director_names: list[str], text_blob: str,
                           existing_map: dict[str, str]) -> str | None:
    """Match a SERP result to a director name using first+last name matching."""
    text_blob = text_blob.lower()
    best_match = None
    best_score = 0
    for name in director_names:
        if name in existing_map:
            continue
        parts = name.lower().split()
        if len(parts) < 2:
            continue
        first = parts[0]
        last = parts[-1]
        if first in text_blob and last in text_blob:
            score = len(name)
            if score > best_score:
                best_score = score
                best_match = name
    return best_match


def _phase3_director_research(serp: SerpClient, director_names: list[str],
                              company_name: str) -> tuple[str, dict, dict]:
    """Search each director for career details, LinkedIn, and Wikipedia.

    Returns (research_text, linkedin_map, social_map).
    social_map: {director_name: {"wikipedia": url}}

    NOTE: Twitter/X and Instagram searches were removed because they produce
    almost entirely false positives for Japanese corporate directors (matching
    random people with the same name). Wikipedia and LinkedIn are kept because
    they can be validated against the company context.
    """
    # Extract company keyword for validation (first significant word)
    company_key = company_name.lower().split()[0].rstrip(".,")

    tasks = []
    for name in director_names[:14]:
        # Career + board
        tasks.append(lambda n=name: serp.search(
            f'"{n}" director board career', num=3, news=False
        ))
        # LinkedIn
        tasks.append(lambda n=name: serp.search(
            f'site:linkedin.com/in/ "{n}"', num=2, news=False
        ))
        # Wikipedia
        tasks.append(lambda n=name: serp.search(
            f'site:en.wikipedia.org "{n}"', num=1, news=False
        ))

    results = run_concurrent(tasks, max_workers=12)

    seen_urls = set()
    snippets = []
    linkedin_map: dict[str, str] = {}
    wikipedia_map: dict[str, str] = {}

    for batch in results:
        if not batch:
            continue
        for r in batch:
            if r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            text_blob = r.title + " " + r.snippet

            # LinkedIn matching — strict: name must appear in URL slug + company context
            if "linkedin.com/in/" in r.url:
                match = _match_name_to_result(director_names, text_blob, linkedin_map)
                if match:
                    # Extract the URL slug (e.g. "yasuyuki-imai-76709196")
                    url_slug = r.url.lower().split("/in/")[-1].split("?")[0].split("/")[0]
                    parts = match.lower().split()
                    last_name = parts[-1] if parts else ""
                    # REQUIRE: last name must appear in the URL slug
                    if last_name and last_name in url_slug:
                        # Also require company context in title/snippet
                        blob_lower = text_blob.lower()
                        if (company_key in blob_lower
                                or "director" in blob_lower
                                or "board" in blob_lower
                                or "chairman" in blob_lower
                                or "president" in blob_lower
                                or "取締役" in blob_lower):
                            linkedin_map[match] = r.url

            # Wikipedia matching — require BOTH first+last name in URL (person, not company)
            elif "wikipedia.org/" in r.url:
                match = _match_name_to_result(director_names, text_blob, wikipedia_map)
                if match:
                    url_path = r.url.lower().split("/wiki/")[-1] if "/wiki/" in r.url.lower() else ""
                    parts = match.lower().split()
                    first_name = parts[0] if len(parts) >= 2 else ""
                    last_name = parts[-1] if parts else ""
                    # Skip disambiguation/surname/list pages
                    skip_patterns = ["(surname)", "(disambiguation)", "list_of", "category:"]
                    # REQUIRE: both first AND last name in URL path (prevents matching company pages)
                    if (first_name and last_name
                            and first_name in url_path and last_name in url_path
                            and not any(s in url_path for s in skip_patterns)):
                        # Also require snippet to mention company, business role, or Japan context
                        snippet_lower = text_blob.lower()
                        business_terms = [company_key, "director", "board", "chairman",
                                          "president", "ceo", "minister", "governor",
                                          "executive", "corporate", "japan", "politician",
                                          "mayor", "lawyer", "businessperson"]
                        if any(term in snippet_lower for term in business_terms):
                            wikipedia_map[match] = r.url

            snippets.append(f"{r.title}\nURL: {r.url}\n{r.snippet}")

    # Build combined social_map (Wikipedia only)
    social_map: dict[str, dict[str, str]] = {}
    for name in director_names:
        if name in wikipedia_map:
            social_map[name] = {"wikipedia": wikipedia_map[name]}

    research_text = _sanitize_text("\n".join(snippets[:80]))
    logger.info(
        "Phase 3: %d results, %d LinkedIn, %d Wikipedia",
        len(snippets), len(linkedin_map), len(wikipedia_map),
    )
    return research_text, linkedin_map, social_map


# ── Phase 4: GPT Synthesis ─────────────────────────────────

def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3].rstrip()
    elif "```" in raw:
        raw = raw[: raw.rfind("```")].rstrip()
    return raw


def _extract_directors_from_irbank(irbank_text: str) -> list[str]:
    """Programmatically extract board director names from irbank officer data.

    Returns names that have 取締役, 代表取締役, or 代表執行役 as their role.
    代表執行役 are included because in 指名委員会等設置会社 (committee-based
    governance) companies like Sony, the CEO/COO are listed as 代表執行役
    but are almost always also board members.
    Excludes plain 執行役, 監査役, and other non-director officers.
    Only extracts from the MOST RECENT year section.
    """
    if not irbank_text:
        return []

    # Find the actual officer name list: "役員一覧 YYYY年M月 Name 取締役..."
    # irbank pages have multiple 役員一覧 occurrences (nav, headers, tables).
    # The one directly followed by a year is the actual name list.
    list_match = re.search(r"役員一覧\s+(\d{4})年(\d+)月", irbank_text)
    if not list_match:
        return []

    latest_year = int(list_match.group(1))
    text_from_list = irbank_text[list_match.start():]

    # Get the section between the latest year and the previous year
    start = list_match.end() - list_match.start()
    next_year_match = re.search(f"{latest_year - 1}年", text_from_list[start:])
    end = start + next_year_match.start() if next_year_match else start + 3000
    section = text_from_list[:end]

    # Extract name-role pairs: "Name 取締役" or "Name 代表取締役XXX"
    matches = re.findall(
        r'([A-Za-z\u3000-\u9fff\u30a0-\u30ff\u4e00-\u9fff（）()\.\s]+?)\s+(代表取締役\S*|取締役|代表執行役\S*)',
        section
    )

    seen = set()
    names = []
    for raw_name, role in matches:
        name = raw_name.strip()
        # Remove prefix artifacts (株, 万株, 月, etc.)
        name = re.sub(r'^[万株月名\d%,\.]+\s*', '', name).strip()
        # Remove parenthetical readings
        name = re.sub(r'[（(].*?[）)]', '', name).strip()
        # Skip if too short or is a label
        if len(name) < 2 or name in ('役員一覧', '報酬', '役員'):
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)

    logger.info("Extracted %d directors from irbank: %s", len(names), names)
    return names


def _extract_names_from_gpt(client, company_name: str, ticker: str,
                            research: str, official_page: str,
                            irbank_names: list[str] | None = None) -> list[str]:
    """Extract director names from research + official page scrape.

    When irbank names are available, they are used as the ground truth and
    GPT only transliterates them to English. When an official page is available,
    it's used as the primary source. SERP data is supplementary.
    """
    # If we have irbank names, use GPT only to transliterate to English
    if irbank_names and len(irbank_names) >= 4:
        names_str = "\n".join(f"  {i+1}. {n}" for i, n in enumerate(irbank_names))
        user_content = (
            f"These are the CURRENT board directors of {company_name} (TSE: {ticker}) "
            f"from official records. Transliterate ALL names to English (romaji). "
            f"For names already in English, keep them as-is.\n\n"
            f"DIRECTORS:\n{names_str}\n\n"
            f"Return a JSON array of the English names. Preserve the exact count."
        )
    elif official_page:
        user_content = (
            f"Extract ALL CURRENT board directors of {company_name} (TSE: {ticker}).\n\n"
            f"=== OFFICIAL COMPANY PAGE (USE THIS AS YOUR PRIMARY SOURCE) ===\n"
            f"{_truncate(official_page, 5000)}\n\n"
            f"INSTRUCTIONS:\n"
            f"- Extract ONLY people listed under 'Board of Directors' / 'Member of the Board' / '取締役' headings\n"
            f"- People listed under 'Operating Officers' / '執行役員' / 'Fellows' / 'Senior Fellows' are NOT directors\n"
            f"- Include Audit & Supervisory Committee members who are also directors\n"
        )
    else:
        user_content = (
            f"Extract ALL CURRENT board directors of {company_name} (TSE: {ticker}). "
            f"STRICTLY only people with 'Director' or '取締役' in their title. "
            f"EXCLUDE: Operating Officers, Executive Officers, Fellows, Advisors.\n\n"
            f"RESEARCH:\n{_truncate(research, 4000)}"
        )

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": (
                "You extract or transliterate names of CURRENT board directors. "
                "Return ONLY a JSON array of full names in ENGLISH. No markdown, no explanation."
            )},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=2000,
        timeout=60,
    )
    if not response.choices:
        return []
    raw = _strip_code_fences(response.choices[0].message.content)
    try:
        names = json.loads(raw)
        if isinstance(names, list):
            # Require at least 4 chars (e.g. "Koji") to avoid junk matches
            return [n for n in names if isinstance(n, str) and len(n) >= 4]
    except json.JSONDecodeError:
        logger.warning("Failed to parse director names from GPT: %s", raw[:200])
    return []


def _synthesize_network(client, company_name: str, ticker: str,
                        serp_research: str, official_page: str,
                        director_research: str, linkedin_map: dict,
                        social_map: dict | None = None,
                        director_names: list[str] | None = None) -> dict:
    """Final GPT call: synthesize all research into structured JSON."""

    linkedin_section = ""
    if linkedin_map:
        lines = [f"  {name}: {url}" for name, url in linkedin_map.items()]
        linkedin_section = "\n=== LINKEDIN PROFILES FOUND ===\n" + "\n".join(lines) + "\n"

    social_section = ""
    if social_map:
        lines = []
        for name, profiles in social_map.items():
            parts = [f"{platform}: {url}" for platform, url in profiles.items()]
            lines.append(f"  {name}: {', '.join(parts)}")
        social_section = "\n=== SOCIAL MEDIA & WEB PROFILES FOUND ===\n" + "\n".join(lines) + "\n"

    official_section = ""
    if official_page:
        official_section = f"\n=== OFFICIAL COMPANY EXECUTIVES PAGE (PRIMARY SOURCE — TRUST THIS MOST) ===\n{_truncate(official_page, 5000)}\n"

    director_names_section = ""
    if director_names:
        names_list = "\n".join(f"  {i+1}. {n}" for i, n in enumerate(director_names))
        director_names_section = (
            f"\n=== VERIFIED DIRECTOR NAMES (FROM OFFICIAL RECORDS — USE THESE EXACTLY) ===\n"
            f"These {len(director_names)} directors were extracted from official filings. "
            f"You MUST include ALL of them and ONLY them in your output.\n"
            f"{names_list}\n"
        )

    system_prompt = (
        "You are a Japanese equity research analyst. You build accurate director network datasets. "
        "You have been given real research data including an OFFICIAL COMPANY PAGE. "
        "The official page is the most reliable source — if it lists 10 directors, you should have ~10 directors. "
        "CRITICAL ACCURACY RULES: "
        "1) Only include people who are CURRENT board directors (取締役). "
        "2) Do NOT include operating officers, executive officers, fellows, or advisors — ONLY board directors. "
        "3) If someone has 'Operating Officer' or '執行役員' as their ONLY title, they are NOT a director. "
        "4) A person must have 'Director' or '取締役' in their title to be included. "
        "5) Do NOT include former directors who have already left the board. "
        "ALL text MUST be in English. Return ONLY valid JSON."
    )

    user_prompt = f"""Build a director correlation network for {company_name} (TSE: {ticker}).
{director_names_section}{official_section}
=== SERP RESEARCH ===
{_truncate(serp_research, 5000)}

=== DIRECTOR PROFILES ===
{_truncate(director_research, 4000)}
{linkedin_section}{social_section}
Based on the research (prioritizing the OFFICIAL PAGE), return JSON:
{{
  "company": "{company_name}",
  "ticker": "{ticker}",
  "boardSummary": {{
    "totalMembers": 10,
    "independent": 6,
    "internal": 4,
    "women": 2,
    "foreignNationals": 3,
    "avgTenure": 3.5,
    "committees": ["Nomination", "Compensation", "Audit"],
    "insight": "2-3 sentence investor-focused summary of this board's governance quality, independence, diversity, and any notable strengths or concerns."
  }},
  "directors": [
    {{
      "id": "snake_case_id",
      "nameEn": "Full Name in English (REQUIRED, must be romaji/English)",
      "nameJp": "日本語名 or null",
      "role": "Exact title from official page (English)",
      "company": "Primary company (English)",
      "type": "internal or external",
      "isIndependent": true or false,
      "gender": "male or female",
      "nationality": "Japanese or other nationality",
      "boardSeats": 1,
      "university": "University (English) or null",
      "universityJp": null,
      "career": [{{ "company": "Name", "role": "Role", "years": "YYYY-YYYY" }}],
      "otherBoards": ["Company Name"],
      "committees": ["Nomination", "Compensation", "Audit"],
      "joinYear": 2020,
      "leaveYear": null,
      "bio": "2-3 sentence bio: who they are, their expertise, why they matter to this company",
      "expertise": ["Finance", "Technology", "International Business"],
      "keiretsuFlag": null,
      "linkedinUrl": "exact URL from research or null",
      "socialProfiles": {{
        "wikipedia": "exact wikipedia.org URL from research or null"
      }}
    }}
  ],
  "connections": [
    {{ "source": "id1", "target": "id2", "type": "board_overlap", "weight": 3, "detail": "Description", "startYear": 2020 }}
  ],
  "clusters": [
    {{ "id": "id", "label": "Name (English)", "members": ["id1","id2","id3"], "color": "rgba(R,G,B,0.06)", "borderColor": "rgba(R,G,B,0.15)" }}
  ],
  "companyColors": {{ "{company_name}": "#e11d48" }}
}}

CRITICAL RULES:
- ONLY include CURRENT board directors — check titles against the official page
- Do NOT include operating officers, fellows, or former directors
- If the official page shows 10 directors, you should have approximately 10
- nameEn MUST be English — never Japanese characters
- Do NOT miss anyone from the official page — include ALL directors listed there

DATA RICHNESS — THIS IS FOR INVESTORS:
- career: include AT LEAST 2-3 career entries per director from research. Include their most notable positions.
- committees: list ALL committees they serve on at {company_name} (Nomination, Compensation, Audit, etc.)
- expertise: assign 2-4 expertise tags based on their career (Finance, Technology, Healthcare, Legal, etc.)
- bio: write 2-3 informative sentences, not just their title — explain their background and why they matter
- otherBoards: list all other public company boards they sit on
- gender: "male" or "female" based on name/research
- nationality: best guess from name and career history

CONNECTIONS — GENERATE GENEROUSLY:
- Include ALL reasonable connections between directors
- committee: directors who serve on the same committee are connected
- board_overlap: directors who serve together on this board
- former_employer: directors who previously worked at the same company
- university: directors who attended the same university
- advisor: directors with advisory relationships
- social: directors who are known to interact on social media, share public platforms, or have a visible social connection (e.g. both active on Twitter/X, appear in same social circles, mutual public endorsements)
- AIM for 15-25 connections for a 10-person board — look for shared backgrounds, shared committees, shared employers, shared social/public presence

CLUSTERS — 3-5 meaningful groups:
- Executive Leadership (internal directors)
- Audit & Supervisory Committee
- Independent Directors
- Industry/Background groups (e.g. "Finance Background", "Tech Background")

companyColors: "#e11d48" for {company_name}, unique hex colors for other companies
linkedinUrl: use EXACT URL from research, never fabricate — set null if not found
socialProfiles: use EXACT URLs from the SOCIAL MEDIA section above, NEVER fabricate — set null for platforms not found
Connection types: board_overlap, former_employer, university, committee, advisor, social"""

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=12000,
        timeout=120,
    )

    if not response.choices:
        return {}
    raw = _strip_code_fences(response.choices[0].message.content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("GPT returned invalid JSON in synthesis: %s\nRaw: %s", exc, raw[:500])
        raise ValueError(f"GPT returned invalid JSON: {exc}")

    if "directors" not in data or len(data["directors"]) < 3:
        raise ValueError(f"GPT returned only {len(data.get('directors', []))} directors")
    data.setdefault("connections", [])
    data.setdefault("clusters", [])
    data.setdefault("companyColors", {company_name: "#e11d48"})

    # Merge LinkedIn URLs GPT may have missed — require BOTH first+last name match
    for d in data["directors"]:
        name_en = d.get("nameEn", "").lower()
        name_parts = name_en.split()
        if len(name_parts) < 2:
            continue

        if not d.get("linkedinUrl"):
            for serp_name, url in linkedin_map.items():
                serp_lower = serp_name.lower()
                if serp_lower == name_en or (
                    name_parts[0] in serp_lower and name_parts[-1] in serp_lower
                ):
                    d["linkedinUrl"] = url
                    break

        # Merge social profiles from SERP that GPT missed
        if social_map:
            social = d.get("socialProfiles") or {}
            for serp_name, profiles in social_map.items():
                serp_lower = serp_name.lower()
                if serp_lower == name_en or (
                    name_parts[0] in serp_lower and name_parts[-1] in serp_lower
                ):
                    for platform, url in profiles.items():
                        if not social.get(platform):
                            social[platform] = url
                    break
            # Clean nulls
            social = {k: v for k, v in social.items() if v}
            d["socialProfiles"] = social if social else None

    # Deduplicate director IDs (GPT sometimes generates duplicates)
    seen_ids = set()
    unique_directors = []
    for d in data["directors"]:
        if d["id"] not in seen_ids:
            seen_ids.add(d["id"])
            unique_directors.append(d)
        else:
            logger.warning("Duplicate director ID removed: %s", d["id"])
    data["directors"] = unique_directors

    # Validate cross-references
    director_ids = {d["id"] for d in data["directors"]}
    data["connections"] = [
        c for c in data["connections"]
        if c.get("source") in director_ids and c.get("target") in director_ids
    ]
    for cluster in data["clusters"]:
        cluster["members"] = [m for m in cluster.get("members", []) if m in director_ids]
    data["clusters"] = [c for c in data["clusters"] if len(c.get("members", [])) >= 2]

    return data


# ── Main Pipeline ──────────────────────────────────────────

def _research_and_generate(ticker: str, company_name: str) -> dict:
    """Full 4-phase research pipeline."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    serp = SerpClient()

    # Phase 1: SERP research
    logger.info("=== Phase 1: SERP research for %s (%s) ===", company_name, ticker)
    serp_research, candidate_pages = _phase1_company_research(serp, ticker, company_name)

    if not serp_research.strip():
        logger.warning("No SERP results — using GPT-only fallback")
        return _fallback_gpt_only(client, ticker, company_name)

    # Phase 2: Scrape official pages + irbank.net for ground truth
    logger.info("=== Phase 2: Scraping %d official pages + irbank ===", len(candidate_pages))
    official_page = _phase2_scrape_official_pages(candidate_pages, company_name, ticker)

    # Extract director names — try irbank structured extraction first
    logger.info("=== Extracting director names ===")
    irbank_names = _extract_directors_from_irbank(official_page)
    director_names = _extract_names_from_gpt(
        client, company_name, ticker, serp_research, official_page, irbank_names
    )
    logger.info("Found %d directors (irbank: %d): %s", len(director_names), len(irbank_names), director_names)

    if not director_names:
        logger.warning("No director names extracted — synthesis will rely on raw research only")

    # Phase 3: Deep-dive + LinkedIn + social profiles (skip if no names found)
    director_research = ""
    linkedin_map: dict[str, str] = {}
    social_map: dict[str, dict[str, str]] = {}
    if director_names:
        logger.info("=== Phase 3: Deep-dive for %d directors ===", len(director_names))
        director_research, linkedin_map, social_map = _phase3_director_research(serp, director_names, company_name)

    # Phase 4: GPT synthesis
    logger.info("=== Phase 4: GPT synthesis ===")
    data = _synthesize_network(
        client, company_name, ticker,
        serp_research, official_page, director_research, linkedin_map, social_map,
        director_names,
    )

    social_count = sum(1 for d in data.get("directors", []) if d.get("socialProfiles"))
    logger.info(
        "Result: %d directors, %d connections, %d clusters, %d LinkedIn, %d with social profiles",
        len(data.get("directors", [])),
        len(data.get("connections", [])),
        len(data.get("clusters", [])),
        sum(1 for d in data.get("directors", []) if d.get("linkedinUrl")),
        social_count,
    )
    return data


def _fallback_gpt_only(client, ticker: str, company_name: str) -> dict:
    """Fallback when SERP returns nothing."""
    logger.warning("GPT-only fallback for %s", company_name)

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": (
                "You are a Japanese equity research analyst. Generate a director network "
                "based on your knowledge. Only include CURRENT board directors, not operating "
                "officers or fellows. ALL text in English. Return ONLY valid JSON."
            )},
            {"role": "user", "content": f"""Generate director network for {company_name} (TSE: {ticker}).

JSON structure:
{{
  "company": "{company_name}", "ticker": "{ticker}",
  "directors": [{{
    "id": "snake_id", "nameEn": "English Name", "nameJp": null,
    "role": "Title", "company": "{company_name}", "type": "internal/external",
    "isIndependent": false, "boardSeats": 1, "university": null, "universityJp": null,
    "career": [], "otherBoards": [], "committees": [],
    "joinYear": 2020, "leaveYear": null, "bio": "Bio", "keiretsuFlag": null, "linkedinUrl": null
  }}],
  "connections": [{{ "source":"id1","target":"id2","type":"board_overlap","weight":3,"detail":"Desc","startYear":2020 }}],
  "clusters": [{{ "id":"id","label":"Name","members":["id1"],"color":"rgba(0,0,0,0.06)","borderColor":"rgba(0,0,0,0.15)" }}],
  "companyColors": {{ "{company_name}": "#e11d48" }}
}}

8-14 CURRENT directors only. 10-20 connections. 3-5 clusters.
Connection types: board_overlap, former_employer, university, committee, advisor"""},
        ],
        temperature=0.15,
        max_tokens=8000,
        timeout=120,
    )

    if not response.choices:
        return {}
    raw = _strip_code_fences(response.choices[0].message.content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("GPT fallback returned invalid JSON: %s\nRaw: %s", exc, raw[:500])
        raise ValueError(f"GPT returned invalid JSON: {exc}")

    if "directors" not in data or len(data["directors"]) < 3:
        raise ValueError("Fallback returned insufficient data")
    data.setdefault("connections", [])
    data.setdefault("clusters", [])
    data.setdefault("companyColors", {company_name: "#e11d48"})
    return data
