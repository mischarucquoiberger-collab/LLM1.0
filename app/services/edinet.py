from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Dict, Any
import datetime as dt
import httpx
import io
import re
import threading
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from app.config import settings
from app.services.cache import load_cache, save_cache

_shared_http_client: httpx.Client | None = None

def _get_http_client() -> httpx.Client:
    """Module-level pooled HTTP client — reuses TCP connections across all EDINET requests."""
    global _shared_http_client
    if _shared_http_client is None:
        _shared_http_client = httpx.Client(
            timeout=30,
            limits=httpx.Limits(max_connections=15, max_keepalive_connections=8),
            follow_redirects=True,
        )
    return _shared_http_client

try:  # optional, improves iXBRL parsing
    from lxml import etree  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    etree = None


_NUM_CLEAN_RE = re.compile(r"[,\s]")


def _safe_localname(tag: Any) -> str:
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def _normalize_number(text: str | None) -> float | None:
    if text is None:
        return None
    t = str(text).strip()
    if not t:
        return None
    neg = False
    if t.startswith(("△", "▲")):
        neg = True
        t = t[1:].strip()
    if t.startswith("(") and t.endswith(")"):
        neg = True
        t = t[1:-1].strip()
    t = t.replace("－", "-")
    t = _NUM_CLEAN_RE.sub("", t)
    if not re.fullmatch(r"[-+]?\d+(\.\d+)?", t):
        return None
    try:
        value = float(t)
    except Exception:
        return None
    if neg:
        value = -abs(value)
    return value


def _apply_scale(value: float, attrs: Dict[str, str]) -> float:
    scale = attrs.get("scale")
    if not scale:
        return value
    try:
        return value * (10 ** int(scale))
    except Exception:
        return value


def _get_ix_name(attrs: Dict[str, str]) -> str:
    for key in ("name", "data-xbrl-name", "data-name", "xbrl:name"):
        v = attrs.get(key)
        if v:
            return v
    for key, v in attrs.items():
        if "name" in key.lower() and v:
            return v
    return ""


def _sniff_ixbrl(data: bytes) -> bool:
    head = data[:2_000_000].lower()
    return b"ix:nonfraction" in head or b"ix:fraction" in head or b"ix:nonnumeric" in head


def _parse_root(data: bytes, ixbrl: bool):
    if etree is not None:
        parser = etree.HTMLParser(recover=True) if ixbrl else etree.XMLParser(recover=True, huge_tree=True)
        try:
            return etree.fromstring(data, parser)
        except Exception:
            return None
    if ixbrl:
        return None
    try:
        return ET.fromstring(data)
    except Exception:
        return None

@dataclass
class EdinetDocument:
    doc_id: str
    filer_name: str
    doc_type: str
    doc_type_code: str | None
    submit_date: str
    sec_code: str | None
    description: str | None
    xbrl_flag: str | None


class EdinetClient:
    def __init__(self) -> None:
        self.api_key = settings.edinet_api_key
        self.subscription_key = settings.edinet_subscription_key
        self.base_url = settings.edinet_base_url.strip()

    def _auth_params(self) -> Dict[str, str]:
        if self.subscription_key:
            return {"Subscription-Key": self.subscription_key}
        if self.api_key:
            return {"api_key": self.api_key}
        return {}

    def list_documents(self, date: str | None = None, doc_type: int | None = None) -> List[EdinetDocument]:
        if not (self.api_key or self.subscription_key):
            return []

        date_str = date or dt.date.today().isoformat()
        url = f"{self.base_url}/documents.json"
        doc_type_value = doc_type if doc_type is not None else settings.edinet_doc_type
        params = {"date": date_str, "type": doc_type_value, **self._auth_params()}

        response = _get_http_client().get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", [])

        if settings.edinet_require_xbrl:
            filtered = []
            for r in results:
                flag = r.get("xbrlFlag")
                if flag is None:
                    filtered.append(r)
                elif str(flag) == "1":
                    filtered.append(r)
            results = filtered

        docs: List[EdinetDocument] = []
        for item in results:
            docs.append(
                EdinetDocument(
                    doc_id=item.get("docID", ""),
                    filer_name=item.get("filerName", ""),
                    doc_type=item.get("docType", ""),
                    doc_type_code=str(item.get("docTypeCode") or "") if item.get("docTypeCode") is not None else None,
                    submit_date=item.get("submitDateTime", ""),
                    sec_code=item.get("secCode"),
                    description=item.get("docDescription"),
                    xbrl_flag=str(item.get("xbrlFlag")) if item.get("xbrlFlag") is not None else None,
                )
            )
        return docs

    def _match_sec_code(self, stock_code: str, sec_code: str | None) -> bool:
        if not sec_code:
            return False
        # Normalize both codes — strip whitespace, uppercase
        sec_clean = sec_code.strip().upper()
        code_clean = stock_code.strip().upper().replace(".T", "")
        # Direct match (handles alphanumeric codes like 157A)
        if sec_clean == code_clean or sec_clean.startswith(code_clean):
            return True
        # Digits-only comparison for legacy numeric codes
        digits = "".join(ch for ch in sec_clean if ch.isdigit())
        cleaned = "".join(ch for ch in code_clean if ch.isdigit())
        if not cleaned:
            return False
        if digits.startswith(cleaned):
            return True
        if len(cleaned) == 4 and digits.startswith(f"{cleaned}0"):
            return True
        if len(digits) >= 4 and digits[:4] == cleaned:
            return True
        return False

    def _preferred_doctype_rank(self, doc_type_code: str | None) -> int:
        if not doc_type_code:
            return 999
        try:
            code = int(doc_type_code)
        except Exception:
            return 999
        pref = [int(x) for x in settings.edinet_preferred_doctypes.split(",") if x.strip().isdigit()]
        if code in pref:
            return pref.index(code)
        return 999

    def _score_instance_candidate(self, name: str, data: bytes) -> int:
        t = data.lower()
        contextref = t.count(b"contextref=")
        context_tag = t.count(b"<context") + t.count(b"<xbrli:context")
        ix_nonfraction = t.count(b"ix:nonfraction")
        ix_fraction = t.count(b"ix:fraction")
        size_kb = max(len(data) // 1024, 1)
        bonus = 0
        lname = name.lower()
        if lname.endswith(".xbrl"):
            bonus += 3000
        if "ixbrl" in lname:
            bonus += 2000
        if "publicdoc" in lname:
            bonus += 500
        return (
            contextref * 3500
            + ix_nonfraction * 9000
            + ix_fraction * 2500
            + context_tag * 1200
            + size_kb
            + bonus
        )

    def _select_best_instances(self, zip_bytes: bytes) -> list[tuple[int, str, bytes]]:
        if not zip_bytes:
            return []
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile as exc:
            raise RuntimeError("EDINET XBRL payload is not a valid zip file.") from exc
        with zf:
            candidates = []
            for name in zf.namelist():
                lname = name.lower()
                if not (lname.endswith(".xbrl") or lname.endswith(".xml") or lname.endswith(".xhtml") or lname.endswith(".html") or lname.endswith(".htm")):
                    continue
                try:
                    data = zf.read(name)
                except Exception:
                    continue
                score = self._score_instance_candidate(name, data[:2_000_000])
                candidates.append((score, name, data))
            if not candidates:
                return []

            # Prefer true XBRL instance files when available.
            xbrl_candidates = [c for c in candidates if c[1].lower().endswith(".xbrl")]
            if xbrl_candidates:
                candidates = xbrl_candidates
            else:
                xml_candidates = [c for c in candidates if c[1].lower().endswith(".xml")]
                if xml_candidates:
                    candidates = xml_candidates

            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates

    def latest_filings_for_code(
        self,
        stock_code: str,
        days_back: int = 30,
        company_name: str | None = None,
        max_docs: int = 10,
        doc_type: int | None = None,
        on_match=None,
    ) -> List[EdinetDocument]:
        if not (self.api_key or self.subscription_key):
            return []

        today = dt.date.today()

        primary_doc_type = doc_type if doc_type is not None else settings.edinet_doc_type
        cache_key = f"edinet_docs_{stock_code}_{days_back}_{primary_doc_type}.json"
        cache_path = Path(settings.output_dir) / "cache" / cache_key
        cached = load_cache(cache_path, max_age_seconds=6 * 3600)
        if cached and isinstance(cached.get("docs"), list):
            try:
                return [EdinetDocument(**item) for item in cached["docs"]]
            except Exception:
                pass

        doc_types_to_try = [primary_doc_type]
        for fallback in (1, 2):
            if fallback not in doc_types_to_try:
                doc_types_to_try.append(fallback)

        docs: List[EdinetDocument] = []

        from concurrent.futures import ThreadPoolExecutor, as_completed

        for doc_type_value in doc_types_to_try:
            docs.clear()

            # --- concurrent day scanning ---
            lock = threading.Lock()
            found_count = 0
            first_found_delta: int | None = None
            scan_window = min(days_back, 730)
            BATCH_SIZE = 40

            def _scan_day(delta: int) -> List[EdinetDocument]:
                date = (today - dt.timedelta(days=delta)).isoformat()
                try:
                    return self.list_documents(date, doc_type=doc_type_value)
                except Exception:
                    return []

            for batch_start in range(0, days_back, BATCH_SIZE):
                # Check early-termination conditions before launching batch
                with lock:
                    if found_count >= max_docs:
                        break
                    if first_found_delta is not None and batch_start - first_found_delta >= scan_window:
                        break

                batch_end = min(batch_start + BATCH_SIZE, days_back)
                deltas = list(range(batch_start, batch_end))

                with ThreadPoolExecutor(max_workers=min(30, len(deltas))) as pool:
                    future_to_delta = {pool.submit(_scan_day, d): d for d in deltas}
                    for future in as_completed(future_to_delta):
                        delta = future_to_delta[future]
                        try:
                            day_docs = future.result()
                        except Exception:
                            continue
                        for doc in day_docs:
                            matched = False
                            if self._match_sec_code(stock_code, doc.sec_code):
                                matched = True
                            elif company_name and company_name != "Unknown Company":
                                if company_name.lower() in (doc.filer_name or "").lower():
                                    matched = True
                            if matched:
                                with lock:
                                    docs.append(doc)
                                    found_count += 1
                                    if first_found_delta is None or delta < first_found_delta:
                                        first_found_delta = delta
                                if on_match:
                                    try:
                                        on_match(doc)
                                    except Exception:
                                        pass

            if docs:
                break

        docs.sort(key=lambda d: d.submit_date or "", reverse=True)
        if len(docs) > max_docs:
            docs = docs[:max_docs]
        try:
            save_cache(cache_path, {"docs": [asdict(doc) for doc in docs]})
        except Exception:
            pass
        return docs

    def download_xbrl_zip(self, doc_id: str) -> bytes:
        if not (self.api_key or self.subscription_key):
            return b""
        url = f"{self.base_url}/documents/{doc_id}"
        params = {"type": 1, **self._auth_params()}
        response = _get_http_client().get(url, params=params, timeout=60)
        response.raise_for_status()
        return response.content

    def _select_honbun_html(self, zip_bytes: bytes) -> bytes | None:
        if not zip_bytes:
            return None
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            htmls = [n for n in zf.namelist() if n.lower().endswith((".htm", ".html", ".xhtml"))]
            if not htmls:
                return None

            def score(name: str) -> int:
                low = name.lower()
                s = 0
                if "honbun" in low:
                    s += 10
                if "publicdoc" in low:
                    s += 5
                if "ixbrl" in low:
                    s += 3
                return s

            htmls.sort(key=score, reverse=True)
            for name in htmls:
                try:
                    return zf.read(name)
                except Exception:
                    continue
        return None

    def _extract_ixbrl_text(self, html_bytes: bytes, max_chars: int = 50000) -> str:
        if etree is None:
            return ""
        root = etree.fromstring(html_bytes, etree.HTMLParser(recover=True))
        etree.strip_elements(root, "script", "style", "noscript", "head", with_tail=False)

        lines = []
        for t in root.itertext():
            s = str(t).replace("\u3000", " ").strip()
            if not s:
                continue
            if "{" in s and "}" in s and ":" in s:
                continue
            lines.append(s)
        text = "\n".join(lines)
        return text[:max_chars]

    def extract_narrative_for_doc(self, doc_id: str) -> str:
        try:
            zip_bytes = self.download_xbrl_zip(doc_id)
        except Exception:
            return ""
        html_bytes = self._select_honbun_html(zip_bytes)
        if not html_bytes:
            return ""
        return self._extract_ixbrl_text(html_bytes)

    def extract_ownership_table(self, doc_id: str) -> Dict[str, float | None]:
        """Parse 所有者別状況 table from annual report HTML."""
        try:
            zip_bytes = self.download_xbrl_zip(doc_id)
        except Exception:
            return {}
        html_bytes = self._select_honbun_html(zip_bytes)
        if not html_bytes:
            return {}
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return {}
        soup = BeautifulSoup(html_bytes, "html.parser")

        # Category mapping: Japanese label → our key
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
        _CATEGORY_KEYWORDS = list(_CATEGORY_MAP.keys())

        # Find the table near the 所有者別 section
        target_table = None
        for table in soup.find_all("table"):
            preceding_text = ""
            for sibling in table.previous_siblings:
                text = getattr(sibling, "get_text", lambda: str(sibling))()
                preceding_text = text + preceding_text
                if len(preceding_text) > 2000:
                    break
            table_text = table.get_text()
            combined = preceding_text + table_text
            if "所有者別" not in combined:
                continue
            # Require at least one category keyword in table text to avoid false positives
            if not any(kw in table_text for kw in _CATEGORY_KEYWORDS):
                continue
            # Check this table actually has percentage data
            if re.search(r"\d{1,3}\.\d{1,2}", table_text):
                target_table = table
                break

        if not target_table:
            return {}

        result: Dict[str, float | None] = {
            "foreign": None, "institutional": None, "corporate": None,
            "individual": None, "government": None, "securities_firms": None,
        }

        rows = target_table.find_all("tr")

        # Identify percentage column by scanning header row for ratio keywords
        pct_col_idx: int | None = None
        _PCT_HEADER_KW = ["比率", "割合", "%", "％"]
        for row in rows:
            cells = row.find_all(["th", "td"])
            for ci, cell in enumerate(cells):
                cell_text = cell.get_text(strip=True)
                if any(kw in cell_text for kw in _PCT_HEADER_KW):
                    pct_col_idx = ci
                    break
            if pct_col_idx is not None:
                break

        for row in rows:
            cells = row.find_all(["td", "th"])
            row_text = row.get_text()
            # Try to match a category from the row text
            matched_key = None
            for jp_label, key in _CATEGORY_MAP.items():
                if jp_label in row_text:
                    matched_key = key
                    break
            if not matched_key:
                continue

            # Strategy A: use identified percentage column
            if pct_col_idx is not None and pct_col_idx < len(cells):
                cell_text = cells[pct_col_idx].get_text().strip()
                pct_match = re.search(r"(\d{1,3}\.\d{1,2})", cell_text)
                if pct_match:
                    val = float(pct_match.group(1))
                    if 0 < val <= 100:
                        result[matched_key] = val
                        continue

            # Strategy B: scan cells in reverse, prefer numbers with decimals
            for cell in reversed(cells):
                cell_text = cell.get_text().strip()
                pct_match = re.search(r"(\d{1,3}\.\d{1,2})", cell_text)
                if pct_match:
                    val = float(pct_match.group(1))
                    if 0 < val <= 100:
                        result[matched_key] = val
                        break

        # Only return if we found meaningful data
        if any(v is not None and v > 0 for v in result.values()):
            return result
        return {}

    def extract_ownership_xbrl(self, doc_id: str) -> Dict[str, float | None]:
        """Extract ownership mix from XBRL facts (iXBRL or plain XBRL).

        Looks for element names containing both a category keyword and a ratio
        keyword, following the same pattern as ``_extract_segments_from_xbrl``.
        """
        try:
            zip_bytes = self.download_xbrl_zip(doc_id)
        except Exception:
            return {}

        candidates = self._select_best_instances(zip_bytes)
        if not candidates:
            return {}

        # Map XBRL element name fragments → our category keys
        _XBRL_CATEGORY_MAP = {
            "governmentandlocalgovernments": "government",
            "financialinstitutions": "institutional",
            "securitiescompanies": "securities_firms",
            "othercorporations": "corporate",
            "foreigncorporationsetc": "foreign",
            "foreigncorporations": "foreign",
            "individualsandothers": "individual",
        }
        _RATIO_KW = ("ratio", "percentage", "proportion")

        result: Dict[str, float | None] = {
            "foreign": None, "institutional": None, "corporate": None,
            "individual": None, "government": None, "securities_firms": None,
        }

        try_limit = max(settings.edinet_instance_try_limit, 1)
        for _, _, xml_bytes in candidates[:try_limit]:
            ixbrl = _sniff_ixbrl(xml_bytes)
            if ixbrl and etree is None:
                continue
            root = _parse_root(xml_bytes, ixbrl)
            if root is None:
                continue

            facts_found = False
            if ixbrl:
                for elem in root.iter():
                    ln = _safe_localname(elem.tag).lower()
                    if ln not in ("nonfraction", "fraction"):
                        continue
                    name = _get_ix_name(elem.attrib).lower()
                    if not name:
                        continue
                    # Must contain both a category keyword AND a ratio keyword
                    matched_cat = None
                    for frag, cat_key in _XBRL_CATEGORY_MAP.items():
                        if frag in name:
                            matched_cat = cat_key
                            break
                    if not matched_cat:
                        continue
                    if not any(rk in name for rk in _RATIO_KW):
                        continue
                    raw = elem.attrib.get("value")
                    if raw is None:
                        raw = "".join(elem.itertext()).strip()
                    value = _normalize_number(raw)
                    if value is None:
                        continue
                    value = _apply_scale(value, elem.attrib)
                    if 0 <= value <= 100:
                        result[matched_cat] = value
                        facts_found = True
            else:
                for elem in root.iter():
                    name = _safe_localname(elem.tag).lower()
                    if not name:
                        continue
                    matched_cat = None
                    for frag, cat_key in _XBRL_CATEGORY_MAP.items():
                        if frag in name:
                            matched_cat = cat_key
                            break
                    if not matched_cat:
                        continue
                    if not any(rk in name for rk in _RATIO_KW):
                        continue
                    raw = (elem.text or "").strip()
                    value = _normalize_number(raw)
                    if value is None:
                        continue
                    value = _apply_scale(value, elem.attrib)
                    if 0 <= value <= 100:
                        result[matched_cat] = value
                        facts_found = True

            if facts_found:
                break

        if any(v is not None and v > 0 for v in result.values()):
            # Heuristic: if all values are tiny decimals (e.g. 0.253 = 25.3%), scale up
            non_none = [v for v in result.values() if v is not None and v > 0]
            if non_none and all(v < 1.5 for v in non_none) and sum(non_none) < 5:
                result = {k: (round(v * 100, 2) if v is not None else None) for k, v in result.items()}
            return result
        return {}

    def extract_shareholders_table(self, doc_id: str) -> List[Dict[str, Any]]:
        """Extract major shareholders (大株主) table from an annual report filing.

        Downloads the filing HTML via EDINET API and parses the standardized
        大株主の状況 section.  Returns a list of dicts:
            [{"name": str, "name_jp": str, "pct": float, "shares": str|None}, ...]
        """
        try:
            zip_bytes = self.download_xbrl_zip(doc_id)
        except Exception:
            return []
        html_bytes = self._select_honbun_html(zip_bytes)
        if not html_bytes:
            return []
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html_bytes, "html.parser")

        # ── Strategy 1: Locate the 大株主 section ──
        # Annual reports have a standardised section header "大株主の状況"
        _SECTION_KW = ["大株主の状況", "大株主", "主要株主", "主要な株主"]
        _EXCLUDE_KW = ["大株主の異動", "自己株式", "ストック"]

        target_table = None
        # Walk all text nodes to find the section header, then grab the next table
        for tag in soup.find_all(["p", "div", "span", "h1", "h2", "h3", "h4", "h5", "h6", "b", "strong"]):
            tag_text = tag.get_text(strip=True)
            if not any(kw in tag_text for kw in _SECTION_KW):
                continue
            if any(kw in tag_text for kw in _EXCLUDE_KW):
                continue
            # Found a section header — find the next table
            sibling = tag.find_next("table")
            if sibling:
                # Verify the table has realistic shareholder data
                table_text = sibling.get_text()
                # Needs names + percentages
                if re.search(r"\d{1,2}\.\d{1,2}", table_text):
                    target_table = sibling
                    break

        # ── Strategy 2: Scan all tables for shareholder-like content ──
        if not target_table:
            for table in soup.find_all("table"):
                header_text = " ".join(
                    th.get_text(strip=True) for th in table.find_all("th")
                )
                table_text = table.get_text()
                combined = header_text + " " + table_text
                # Require shareholder keywords in the header/table
                if not any(kw in combined for kw in ["株主名", "大株主", "所有株式数", "持株比率"]):
                    continue
                # Require percentage patterns
                if not re.search(r"\d{1,3}(?:\.\d{1,2})?", table_text):
                    continue
                # Reject tiny tables (< 3 data rows)
                data_rows = [r for r in table.find_all("tr") if r.find("td")]
                if len(data_rows) < 3:
                    continue
                target_table = table
                break

        if not target_table:
            return []

        # ── Parse the table ──
        results: List[Dict[str, Any]] = []
        rows = target_table.find_all("tr")

        # Identify column indices from header row
        name_col: int | None = None
        shares_col: int | None = None
        pct_col: int | None = None

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

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            # Try to extract name
            raw_name = ""
            if name_col is not None and name_col < len(cells):
                raw_name = cells[name_col].get_text(strip=True)
            else:
                # Fallback: first cell
                raw_name = cells[0].get_text(strip=True)

            # Skip header-like rows
            if not raw_name or any(k in raw_name for k in [
                "氏名", "株主名", "名称", "合計", "計",
                "自己名義", "他人名義", "所有者", "発行済",
            ]):
                continue
            # Skip if name is too short or too long
            if len(raw_name) < 2 or len(raw_name) > 60:
                continue

            # Try to extract percentage
            pct_val: float | None = None
            if pct_col is not None and pct_col < len(cells):
                pct_text = cells[pct_col].get_text(strip=True)
                m = re.search(r"(\d{1,3}(?:\.\d{1,2})?)", pct_text)
                if m:
                    try:
                        v = float(m.group(1))
                        if 0 < v <= 100:
                            pct_val = v
                    except ValueError:
                        pass

            # Fallback: scan all cells for a percentage
            if pct_val is None:
                for cell in reversed(cells):
                    ct = cell.get_text(strip=True)
                    m = re.search(r"(\d{1,3}(?:\.\d{1,2})?)", ct)
                    if m:
                        try:
                            v = float(m.group(1))
                            if 0.1 <= v <= 99:
                                pct_val = v
                                break
                        except ValueError:
                            continue

            if pct_val is None:
                continue

            # Extract shares count if available
            shares_str: str | None = None
            if shares_col is not None and shares_col < len(cells):
                shares_str = cells[shares_col].get_text(strip=True)

            results.append({
                "name": raw_name,
                "name_jp": raw_name,
                "pct": pct_val,
                "shares": shares_str,
            })

        # Deduplicate by name, keep highest pct
        merged: Dict[str, Dict[str, Any]] = {}
        for item in results:
            key = item["name"]
            if key not in merged or item["pct"] > merged[key]["pct"]:
                merged[key] = item
        ranked = sorted(merged.values(), key=lambda x: x["pct"], reverse=True)
        return ranked[:20]

    def extract_large_holder_details(self, doc_id: str) -> Dict[str, Any]:
        """Extract stake % and purpose from a 大量保有報告書 filing.

        Returns {"stake_pct": float|None, "prev_stake_pct": float|None,
                 "purpose": str|None}.

        Group filings list each entity's individual stake in ② sections,
        followed by the GROUP total in a （２） section.  We take the LAST
        match of 「上記提出者の株券等保有割合」 which is always the total.

        Also extracts 「直前の報告書に記載された株券等保有割合」 (the previous
        stake from the prior filing) — essential for disposal reports where
        the current stake dropped to near-zero.
        """
        import unicodedata

        result: Dict[str, Any] = {"stake_pct": None, "prev_stake_pct": None, "purpose": None}
        try:
            zip_bytes = self.download_xbrl_zip(doc_id)
        except Exception:
            return result
        html_bytes = self._select_honbun_html(zip_bytes)
        if not html_bytes:
            return result
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return result

        soup = BeautifulSoup(html_bytes, "html.parser")
        text = soup.get_text()
        # Normalize full-width chars → half-width for consistent matching
        text = unicodedata.normalize("NFKC", text)

        # ── Current stake % ──
        # Group filings: take the LAST match (= group total).
        _STAKE_PAT = r"上記提出者の株券等保有割合[（(％%）)T/U+V×\d\s・]*?\n*(\d{1,3}\.\d{1,2})"
        all_stakes = re.findall(_STAKE_PAT, text, re.DOTALL)
        if all_stakes:
            try:
                v = float(all_stakes[-1])  # last = group total
                if 0 <= v <= 100:
                    result["stake_pct"] = v
            except ValueError:
                pass

        # Fallback: broader patterns if the specific one didn't match
        if result["stake_pct"] is None:
            _FALLBACK_PATTERNS = [
                r"保有割合[（(％%）)T/U+V×\d\s・]*?\n*(\d{1,3}\.\d{1,2})",
                r"変更後[のの]?割合.{0,60}?(\d{1,3}\.\d{1,2})",
                r"所有割合.{0,60}?(\d{1,3}\.\d{1,2})",
            ]
            for pat in _FALLBACK_PATTERNS:
                matches = re.findall(pat, text, re.DOTALL)
                if matches:
                    try:
                        v = float(matches[-1])
                        if 0 <= v <= 100:
                            result["stake_pct"] = v
                            break
                    except ValueError:
                        continue

        # ── Previous stake % ──
        # 「直前の報告書に記載された株券等保有割合（％）5.19」
        _PREV_PAT = r"直前の報告書に記載された[^\d]{0,30}?保有割合[（(％%）)\s]*\n*(\d{1,3}\.\d{1,2})"
        prev_matches = re.findall(_PREV_PAT, text, re.DOTALL)
        if prev_matches:
            try:
                pv = float(prev_matches[-1])  # last = group total
                if 0 < pv <= 100:
                    result["prev_stake_pct"] = pv
            except ValueError:
                pass

        # ── Purpose ──
        # Find the LAST 保有目的 section (group-level purpose in group filings)
        _PURPOSE_PATTERNS = [
            r"保有(?:の)?目的[】\])\s:：]*\n*([\u3000-\u9FFFa-zA-Z\w].{4,200}?)(?:\n\n|。)",
            r"保有(?:の)?目的[】\])\s:：]*(.{5,200}?)(?:\n\n|。|$)",
        ]
        for pat in _PURPOSE_PATTERNS:
            matches = re.findall(pat, text, re.DOTALL)
            if matches:
                raw = matches[-1].strip()  # last = group-level purpose
                raw = re.sub(r"[\[\]{}【】]", "", raw)
                raw = re.sub(r"\s+", "", raw).strip()
                if len(raw) >= 3:
                    result["purpose"] = raw
                    break

        return result

    def _extract_xbrl_metrics(self, xbrl_bytes: bytes) -> List[Dict[str, Any]]:
        if not xbrl_bytes:
            return []
        candidates = self._select_best_instances(xbrl_bytes)
        if not candidates:
            return []

        target_map = {
            "NetSales": [
                "netsales",
                "sales",
                "revenue",
                "operatingrevenue",
                "netrevenue",
                "revenuefromcontractswithcustomers",
                "turnover",
                "revenuefromcontractswithcustomersincludingassessedtax",
                "operatingrevenues",
                "operatingrevenuestotal",
                "revenueifrs",
                "revenues",
                "salesifrs",
            ],
            "OperatingProfit": [
                "operatingprofit",
                "operatingincome",
                "operatingprofitloss",
                "profitlossfromoperatingactivities",
                "operatingprofitlossifrs",
            ],
            "Profit": [
                "profitloss",
                "netincome",
                "netincomeloss",
                "profit",
                "profitattributabletoownersofparent",
                "profitlossattributabletoownersofparent",
                "profitlossattributabletoownersofparentcompany",
                "profitattributabletoownersofparent",
                "profitlossattributabletoownersofparentifrs",
                "profitlossifrs",
            ],
            "EarningsPerShare": [
                "earningspershare", "eps", "basicearningspershare",
                "basicearningslosspershare", "earningslosspershare",
            ],
            "IssuedShares": [
                "numberofsharesissuedandoutstanding",
                "numberofissuedshares",
                "issuedshares",
                "totalnumberofissuedshares",
                "sharesoutstanding",
                "totalsharesissued",
            ],
            "TotalAssets": ["totalassets", "assets", "assets_total", "totalassetsifrs"],
            "Equity": [
                "equity",
                "totalequity",
                "netassets",
                "shareholdersequity",
                "ownersequity",
                "owners_equity",
                "equityattributabletoownersofparent",
                "owners' equity",
                "equityattributabletoownersofparentifrs",
            ],
            "CashFlowsFromOperatingActivities": [
                "cashflowsfromoperatingactivities",
                "netcashprovidedbyusedinoperatingactivities",
                "netcashprovidedbyusedinoperatingactivitiesifrs",
            ],
            "CashFlowsFromInvestingActivities": [
                "cashflowsfrominvestingactivities",
                "netcashprovidedbyusedininvestingactivities",
                "netcashprovidedbyusedininvestingactivitiesifrs",
            ],
            "CashFlowsFromFinancingActivities": [
                "cashflowsfromfinancingactivities",
                "netcashprovidedbyusedinfinancingactivities",
                "netcashprovidedbyusedinfinancingactivitiesifrs",
            ],
            "CapitalExpenditures": [
                "capitalexpenditures",
                "capitalexpendituresoverviewofcapitalexpendituresetc",
                "purchaseofpropertyplantandequipment",
                "purchaseofpropertyplantandequipmentinvcf",
                "paymentsforpropertyplantandequipment",
                "acquisitionsofpropertyplantandequipment",
            ],
            "CashAndCashEquivalents": [
                "cashandcashequivalents",
                "cashequivalents",
                "cashandcashequivalentsendofperiod",
                "cashanddeposits",
                "cashcashequivalentsandshortterminvestments",
                "cashandcashequivalentsatendofperiod",
                "cashandcashequivalentsatendofyear",
                "increasedecreaseincashandcashequivalents",
            ],
            "Borrowings": [
                "interestbearingdebt",
                "borrowings",
                "shorttermborrowings",
                "longtermborrowings",
                "shorttermloans",
                "shorttermloanspayable",
                "longtermloans",
                "longtermloanspayable",
                "currentportionoflongtermloanspayable",
                "bondspayable",
                "commercialpaper",
            ],
        }
        try_limit = max(settings.edinet_instance_try_limit, 1)
        for _, _, xml_bytes in candidates[:try_limit]:
            ixbrl = _sniff_ixbrl(xml_bytes)
            if ixbrl and etree is None:
                raise RuntimeError("lxml is required to parse iXBRL files. Install it and restart.")

            root = _parse_root(xml_bytes, ixbrl)
            if root is None:
                continue

            # Build context -> period end date map
            context_dates: Dict[str, str] = {}
            for ctx in root.iter():
                if _safe_localname(ctx.tag).lower() != "context":
                    continue
                ctx_id = ctx.attrib.get("id") or ctx.attrib.get("ID")
                if not ctx_id:
                    continue
                found = None
                for child in ctx.iter():
                    ln = _safe_localname(child.tag).lower()
                    if ln in ("enddate", "instant"):
                        found = (child.text or "").strip()
                        break
                if found:
                    context_dates[ctx_id] = found

            if not context_dates:
                continue

            facts: List[Dict[str, Any]] = []
            if ixbrl:
                for elem in root.iter():
                    ln = _safe_localname(elem.tag).lower()
                    if ln not in ("nonfraction", "fraction"):
                        continue
                    ctx = elem.attrib.get("contextRef") or elem.attrib.get("contextref")
                    if not ctx:
                        continue
                    name = _get_ix_name(elem.attrib)
                    raw = elem.attrib.get("value")
                    if raw is None:
                        raw = "".join(elem.itertext()).strip()
                    value = _normalize_number(raw)
                    if value is None:
                        continue
                    value = _apply_scale(value, elem.attrib)
                    facts.append({"name": name, "value": value, "contextRef": ctx})
            else:
                for elem in root.iter():
                    ctx = elem.attrib.get("contextRef")
                    if not ctx:
                        continue
                    raw = (elem.text or "").strip()
                    value = _normalize_number(raw)
                    if value is None:
                        continue
                    value = _apply_scale(value, elem.attrib)
                    name = _safe_localname(elem.tag)
                    facts.append({"name": name, "value": value, "contextRef": ctx})

            if not facts:
                continue

            # Filter out dimensional/segment contexts (e.g. _ReportableSegmentsMember)
            facts = [f for f in facts if "Member" not in (f.get("contextRef") or "")]

            if not facts:
                continue

            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for fact in facts:
                ctx = fact.get("contextRef")
                period = context_dates.get(ctx)
                if not period:
                    continue
                grouped.setdefault(period, []).append(fact)

            _SUMMARY_SUFFIX = "summaryofbusinessresults"

            def pick_metric(items: List[Dict[str, Any]], aliases: List[str]) -> float | None:
                alias_set = set(aliases)
                matches = []
                for item in items:
                    name = (item.get("name") or "").lower()
                    if not name:
                        continue
                    if name.endswith(_SUMMARY_SUFFIX):
                        name = name[: -len(_SUMMARY_SUFFIX)]
                    if name in alias_set:
                        matches.append(float(item.get("value")))
                if not matches:
                    return None
                return max(matches, key=lambda x: abs(x))

            rows: List[Dict[str, Any]] = []
            for period, items in grouped.items():
                row = {"PeriodEnd": period}
                for canonical, aliases in target_map.items():
                    value = pick_metric(items, aliases)
                    if value is not None:
                        row[canonical] = value
                if len(row.keys()) > 1:
                    rows.append(row)

            if rows:
                rows.sort(key=lambda r: r.get("PeriodEnd", ""), reverse=True)
                return rows

        return []

    # ------------------------------------------------------------------
    # Segment extraction — parse structured segment data from filings
    # ------------------------------------------------------------------

    def _extract_segment_tables_html(self, html_bytes: bytes) -> List[Dict[str, Any]]:
        """Parse セグメント情報 tables from the EDINET HTML filing.

        Japanese annual reports contain a standardised section with segment
        revenues and profits.  We look for the table that contains
        '外部顧客への売上高' (sales to external customers) or similar
        headers, then extract each row as a segment.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        if not html_bytes:
            return []
        soup = BeautifulSoup(html_bytes, "html.parser")

        # ── Strategy 1: find the segment information table ──
        # In EDINET filings the segment table usually follows a heading
        # containing 'セグメント情報' and has columns like:
        #   segment_name | 外部顧客への売上高 | セグメント間 | 計 | セグメント利益
        _SECTION_KW = [
            "セグメント情報",
            "報告セグメント",
            "セグメント別",
            "事業セグメント",
        ]
        _REVENUE_HEADER_KW = [
            "外部顧客への売上高",
            "外部顧客に対する売上高",
            "外部顧客への営業収益",
            "外部顧客売上高",
            "売上高",
            "売上収益",
            "営業収益",
        ]
        _PROFIT_HEADER_KW = [
            "セグメント利益",
            "セグメント損益",
            "営業利益",
            "利益",
        ]
        _SKIP_ROW_KW = [
            "合計", "計", "消去", "調整", "全社", "セグメント間", "配賦不能",
            "調整額", "のれん", "減価償却", "その他の項目",
        ]

        best_segments: List[Dict[str, Any]] = []

        for table in soup.find_all("table"):
            # Check if this table or its surroundings mention segment info
            table_text = table.get_text()
            # Look at preceding content too
            preceding = ""
            for sib in table.previous_siblings:
                txt = getattr(sib, "get_text", lambda: str(sib))()
                preceding = txt + preceding
                if len(preceding) > 600:
                    break
            combined = preceding + table_text

            if not any(kw in combined for kw in _SECTION_KW):
                continue

            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # ── Identify header row and column indices ──
            revenue_col = None
            profit_col = None
            header_row_idx = None
            for ri, row in enumerate(rows):
                cells = row.find_all(["th", "td"])
                for ci, cell in enumerate(cells):
                    cell_text = cell.get_text(strip=True)
                    if revenue_col is None:
                        for kw in _REVENUE_HEADER_KW:
                            if kw in cell_text:
                                revenue_col = ci
                                header_row_idx = ri
                                break
                    if profit_col is None:
                        for kw in _PROFIT_HEADER_KW:
                            if kw in cell_text and "率" not in cell_text:
                                profit_col = ci
                                break
                if revenue_col is not None:
                    break

            if revenue_col is None:
                continue

            # ── Extract data rows ──
            segments: List[Dict[str, Any]] = []
            for ri, row in enumerate(rows):
                if ri <= (header_row_idx or 0):
                    continue
                cells = row.find_all(["th", "td"])
                if len(cells) < 2:
                    continue

                # Segment name is typically first cell
                name = cells[0].get_text(strip=True)
                if not name or len(name) > 60:
                    continue
                # Skip totals, adjustments, elimination rows
                if any(kw in name for kw in _SKIP_ROW_KW):
                    continue
                # Skip if name looks like a sub-header (all alpha or all kanji with no numbers)
                if name in ("", "—", "―", "－"):
                    continue

                # Extract revenue
                rev_val = None
                if revenue_col < len(cells):
                    raw = cells[revenue_col].get_text(strip=True)
                    rev_val = _normalize_number(raw)

                # Extract profit
                profit_val = None
                if profit_col is not None and profit_col < len(cells):
                    raw = cells[profit_col].get_text(strip=True)
                    profit_val = _normalize_number(raw)

                if rev_val is not None:
                    seg = {"name": name.strip()[:40], "revenue": rev_val}
                    if profit_val is not None:
                        seg["profit"] = profit_val
                    segments.append(seg)

            # Keep the table that yielded the most segments with real data
            if len(segments) > len(best_segments):
                best_segments = segments

        if not best_segments:
            # ── Strategy 2: find ANY table with segment-like rows ──
            # Some filings use simpler tables with just segment names + revenue
            for table in soup.find_all("table"):
                table_text = table.get_text()
                # Must mention 事業 (business) or セグメント (segment)
                if not re.search(r"(?:事業|セグメント|部門)", table_text):
                    continue
                rows = table.find_all("tr")
                segments = []
                for row in rows:
                    cells = row.find_all(["th", "td"])
                    if len(cells) < 2:
                        continue
                    name = cells[0].get_text(strip=True)
                    if not name or len(name) > 60:
                        continue
                    if any(kw in name for kw in _SKIP_ROW_KW):
                        continue
                    # Try each subsequent cell for a number
                    for cell in cells[1:]:
                        val = _normalize_number(cell.get_text(strip=True))
                        if val is not None and val > 0:
                            segments.append({"name": name[:40], "revenue": val})
                            break
                if len(segments) >= 2 and len(segments) > len(best_segments):
                    best_segments = segments

        if not best_segments:
            return []

        # ── Convert to standard format with percentages ──
        total_rev = sum(s["revenue"] for s in best_segments if s.get("revenue", 0) > 0)
        result = []
        for s in best_segments:
            rev = s.get("revenue", 0)
            if rev <= 0:
                continue
            entry: Dict[str, Any] = {
                "segment": s["name"],
                "pct": round(rev / total_rev * 100, 1) if total_rev > 0 else None,
                "revenue_mm": rev,
            }
            if "profit" in s:
                entry["profit_mm"] = s["profit"]
            result.append(entry)

        # Sort by revenue descending
        result.sort(key=lambda x: x.get("revenue_mm", 0) or 0, reverse=True)
        return result[:10]

    def _extract_segments_from_xbrl(self, xbrl_bytes: bytes) -> List[Dict[str, Any]]:
        """Extract segment data from XBRL facts using dimension/context analysis.

        XBRL contexts carry segment dimensions. We look for facts whose
        context includes a segment axis/dimension and map the segment
        identifier to its revenue and profit amounts.
        """
        candidates = self._select_best_instances(xbrl_bytes)
        if not candidates:
            return []

        # Segment-level XBRL aliases
        _SEG_REVENUE_ALIASES = [
            "netsales", "sales", "revenue", "operatingrevenue",
            "revenuesfromexternalcustomers", "externalsalesamount",
            "revenuefromcontractswithcustomers",
        ]
        _SEG_PROFIT_ALIASES = [
            "segmentprofitloss", "segmentprofit", "operatingprofit",
            "operatingincome", "profitloss",
        ]

        try_limit = max(settings.edinet_instance_try_limit, 1)
        for _, _, xml_bytes in candidates[:try_limit]:
            ixbrl = _sniff_ixbrl(xml_bytes)
            if ixbrl and etree is None:
                continue
            root = _parse_root(xml_bytes, ixbrl)
            if root is None:
                continue

            # Build context -> (period, segment_label) map
            # Segment contexts have <segment> child with <explicitMember> or xbrldi:explicitMember
            context_info: Dict[str, Dict[str, str]] = {}
            for ctx in root.iter():
                if _safe_localname(ctx.tag).lower() != "context":
                    continue
                ctx_id = ctx.attrib.get("id") or ctx.attrib.get("ID")
                if not ctx_id:
                    continue
                period_end = None
                segment_label = None
                for child in ctx.iter():
                    ln = _safe_localname(child.tag).lower()
                    if ln in ("enddate", "instant"):
                        period_end = (child.text or "").strip()
                    if ln in ("explicitmember", "typedmember"):
                        # The text content is the segment member identifier
                        member_text = (child.text or "").strip()
                        if member_text:
                            # Extract meaningful part (e.g. "ReportableSegments_Segment1Member" -> "Segment1")
                            segment_label = member_text
                if period_end and segment_label:
                    context_info[ctx_id] = {"period": period_end, "segment": segment_label}

            if not context_info:
                continue

            # Collect facts tied to segment contexts
            seg_facts: Dict[str, Dict[str, float]] = {}
            all_facts: List[Dict[str, Any]] = []
            if ixbrl:
                for elem in root.iter():
                    ln = _safe_localname(elem.tag).lower()
                    if ln not in ("nonfraction", "fraction"):
                        continue
                    ctx = elem.attrib.get("contextRef") or elem.attrib.get("contextref")
                    if not ctx or ctx not in context_info:
                        continue
                    name = _get_ix_name(elem.attrib)
                    raw = elem.attrib.get("value")
                    if raw is None:
                        raw = "".join(elem.itertext()).strip()
                    value = _normalize_number(raw)
                    if value is None:
                        continue
                    value = _apply_scale(value, elem.attrib)
                    all_facts.append({"name": name, "value": value, "ctx": ctx})
            else:
                for elem in root.iter():
                    ctx = elem.attrib.get("contextRef")
                    if not ctx or ctx not in context_info:
                        continue
                    raw = (elem.text or "").strip()
                    value = _normalize_number(raw)
                    if value is None:
                        continue
                    value = _apply_scale(value, elem.attrib)
                    name = _safe_localname(elem.tag)
                    all_facts.append({"name": name, "value": value, "ctx": ctx})

            if not all_facts:
                continue

            # Group by (period, segment) and pick revenue + profit
            from collections import defaultdict
            grouped: Dict[str, Dict[str, List]] = defaultdict(lambda: defaultdict(list))
            for fact in all_facts:
                info = context_info[fact["ctx"]]
                key = (info["period"], info["segment"])
                grouped[key]["facts"].append(fact)

            # Pick latest period
            all_periods = set(context_info[c]["period"] for c in context_info)
            latest_period = max(all_periods) if all_periods else None
            if not latest_period:
                continue

            segments: Dict[str, Dict[str, float | None]] = {}
            for (period, seg_label), data in grouped.items():
                if period != latest_period:
                    continue
                facts_list = data.get("facts", [])
                rev = None
                profit = None
                for fact in facts_list:
                    name_lower = (fact["name"] or "").lower()
                    if rev is None:
                        for alias in _SEG_REVENUE_ALIASES:
                            if alias in name_lower:
                                rev = fact["value"]
                                break
                    if profit is None:
                        for alias in _SEG_PROFIT_ALIASES:
                            if alias in name_lower:
                                profit = fact["value"]
                                break
                if rev is not None:
                    segments[seg_label] = {"revenue": rev, "profit": profit}

            if not segments:
                continue

            # Convert to standard format
            total_rev = sum(s["revenue"] for s in segments.values() if s.get("revenue", 0) > 0)
            result = []
            for seg_label, data in segments.items():
                rev = data.get("revenue", 0)
                if rev <= 0:
                    continue
                # Clean the segment label
                clean_name = seg_label.split("_")[-1] if "_" in seg_label else seg_label
                clean_name = clean_name.replace("Member", "").replace("Segment", "Seg ")
                entry: Dict[str, Any] = {
                    "segment": clean_name[:40],
                    "pct": round(rev / total_rev * 100, 1) if total_rev > 0 else None,
                    "revenue_mm": rev,
                }
                if data.get("profit") is not None:
                    entry["profit_mm"] = data["profit"]
                result.append(entry)

            result.sort(key=lambda x: x.get("revenue_mm", 0) or 0, reverse=True)
            if result:
                return result[:10]

        return []

    def extract_segments_for_doc(self, doc_id: str) -> List[Dict[str, Any]]:
        """Extract segment data from an EDINET filing.

        Tries multiple strategies in order of accuracy:
        1. HTML table parsing (most reliable — reads actual 'セグメント情報' tables)
        2. XBRL dimension-based extraction (structured data from XBRL tags)

        Returns list of dicts: [{segment, pct, revenue_mm, profit_mm?}, ...]
        """
        try:
            zip_bytes = self.download_xbrl_zip(doc_id)
        except Exception:
            return []

        # Strategy 1: HTML table parsing (highest accuracy)
        html_segments = []
        html_bytes = self._select_honbun_html(zip_bytes)
        if html_bytes:
            html_segments = self._extract_segment_tables_html(html_bytes)
            if html_segments and len(html_segments) >= 2:
                return html_segments

        # Strategy 2: XBRL structured extraction
        xbrl_segments = self._extract_segments_from_xbrl(zip_bytes)
        if xbrl_segments and len(xbrl_segments) >= 2:
            return xbrl_segments

        # Strategy 1 with even 1 segment is better than nothing
        if html_segments:
            return html_segments

        return []

    def latest_financials_for_code(
        self,
        stock_code: str,
        days_back: int = 120,
        company_name: str | None = None,
        docs: List[EdinetDocument] | None = None,
        on_scan=None,
    ) -> Dict[str, Any]:
        if docs is None:
            docs = self.latest_filings_for_code(
                stock_code,
                days_back=days_back,
                company_name=company_name,
                max_docs=80,
                doc_type=settings.edinet_doc_type,
            )

        def sort_key(doc: EdinetDocument):
            rank = self._preferred_doctype_rank(doc.doc_type_code)
            return (rank, doc.submit_date or "")

        ordered = sorted(docs, key=sort_key)
        last_error: str | None = None
        total = len(ordered)

        rows_by_period: Dict[str, Dict[str, Any]] = {}
        used_docs: List[str] = []
        filer_name: str | None = None
        max_periods = 8

        for idx, doc in enumerate(ordered, start=1):
            if on_scan:
                try:
                    on_scan(doc, idx, total)
                except Exception:
                    pass
            try:
                zip_bytes = self.download_xbrl_zip(doc.doc_id)
                rows = self._extract_xbrl_metrics(zip_bytes)
                if rows:
                    if not filer_name:
                        filer_name = doc.filer_name
                    used_docs.append(doc.doc_id)
                    for row in rows:
                        period = row.get("PeriodEnd")
                        if not period:
                            continue
                        existing = rows_by_period.get(period, {})
                        merged = dict(existing)
                        for key, value in row.items():
                            if value is not None or key not in merged:
                                merged[key] = value
                        rows_by_period[period] = merged
                if len(rows_by_period) >= max_periods:
                    break
            except Exception as exc:
                last_error = (
                    "Failed to extract EDINET financials. "
                    "Ensure lxml is installed and EDINET documents are accessible. "
                    f"Details: {exc}"
                )
                continue

        if rows_by_period:
            return {
                "statements": list(rows_by_period.values()),
                "doc_id": used_docs[0] if used_docs else None,
                "doc_ids": used_docs,
                "filer_name": filer_name,
            }

        if last_error:
            raise RuntimeError(last_error)
        raise RuntimeError("EDINET financials were not found in the XBRL files. Check EDINET docType and lookback settings.")
