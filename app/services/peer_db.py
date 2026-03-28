"""Local peer universe database built from TSE listed-company data.

Provides sector-aware peer lookup so valuation methods can find real
comparable companies rather than falling back to generic sector medians.

The database is a pre-processed JSON file containing 3,700+ companies
grouped by their 33-sector TSE classification.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "peer_universe.json"

_SECTOR_ALIAS_MAP = {
    # Map common sector strings to exact 33-sector names in the database
    "bank": "Banks",
    "banks": "Banks",
    "insurance": "Insurance",
    "real estate": "Real Estate",
    "technology": "Information & Communication",
    "it": "Information & Communication",
    "software": "Information & Communication",
    "information": "Information & Communication",
    "retail": "Retail Trade",
    "wholesale": "Wholesale Trade",
    "trading": "Wholesale Trade",
    "pharma": "Pharmaceutical",
    "pharmaceutical": "Pharmaceutical",
    "drug": "Pharmaceutical",
    "utility": "Electric Power and Gas",
    "electric power": "Electric Power and Gas",
    "gas": "Electric Power and Gas",
    "auto": "Transportation Equipment",
    "automobile": "Transportation Equipment",
    "automotive": "Transportation Equipment",
    "food": "Foods",
    "foods": "Foods",
    "beverage": "Foods",
    "construction": "Construction",
    "chemical": "Chemicals",
    "chemicals": "Chemicals",
    "machinery": "Machinery",
    "electronics": "Electric Appliances",
    "electric appliances": "Electric Appliances",
    "telecom": "Information & Communication",
    "transport": "Land Transportation",
    "logistics": "Warehousing and Harbor Transportation Service",
    "services": "Services",
    "steel": "Iron and Steel",
    "iron": "Iron and Steel",
    "mining": "Mining",
    "oil": "Oil and Coal Products",
    "energy": "Oil and Coal Products",
    "textiles": "Textiles and Apparels",
    "apparel": "Textiles and Apparels",
    "precision": "Precision Instruments",
    "glass": "Glass and Ceramics Products",
    "ceramics": "Glass and Ceramics Products",
    "paper": "Pulp and Paper",
    "rubber": "Rubber Products",
    "nonferrous": "Nonferrous Metals",
    "metal products": "Metal Products",
    "marine": "Marine Transportation",
    "shipping": "Marine Transportation",
    "air": "Air Transportation",
    "airline": "Air Transportation",
    "securities": "Securities and Commodities Futures",
    "other financing": "Other Financing Business",
    "financing": "Other Financing Business",
    "fishery": "Fishery, Agriculture and Forestry",
    "agriculture": "Fishery, Agriculture and Forestry",
    # ── TSE 33-sector Japanese names (J-Quants returns these) ──
    "水産・農林業": "Fishery, Agriculture and Forestry",
    "鉱業": "Mining",
    "建設業": "Construction",
    "食料品": "Foods",
    "繊維製品": "Textiles and Apparels",
    "パルプ・紙": "Pulp and Paper",
    "化学": "Chemicals",
    "医薬品": "Pharmaceutical",
    "石油・石炭製品": "Oil and Coal Products",
    "ゴム製品": "Rubber Products",
    "ガラス・土石製品": "Glass and Ceramics Products",
    "鉄鋼": "Iron and Steel",
    "非鉄金属": "Nonferrous Metals",
    "金属製品": "Metal Products",
    "機械": "Machinery",
    "電気機器": "Electric Appliances",
    "輸送用機器": "Transportation Equipment",
    "精密機器": "Precision Instruments",
    "その他製品": "Other Products",
    "電気・ガス業": "Electric Power and Gas",
    "陸運業": "Land Transportation",
    "海運業": "Marine Transportation",
    "空運業": "Air Transportation",
    "倉庫・運輸関連業": "Warehousing and Harbor Transportation Service",
    "情報・通信業": "Information & Communication",
    "情報･通信業": "Information & Communication",  # half-width dot variant
    "卸売業": "Wholesale Trade",
    "小売業": "Retail Trade",
    "銀行業": "Banks",
    "証券、商品先物取引業": "Securities and Commodities Futures",
    "証券･商品先物取引業": "Securities and Commodities Futures",
    "保険業": "Insurance",
    "その他金融業": "Other Financing Business",
    "不動産業": "Real Estate",
    "サービス業": "Services",
    # ── Short-form Japanese variants (Yahoo Finance / Kabutan drop particles) ──
    "輸送機器": "Transportation Equipment",
    "情報通信": "Information & Communication",
    "情報通信業": "Information & Communication",
    "電気ガス業": "Electric Power and Gas",
    "証券業": "Securities and Commodities Futures",
    "その他 金融業": "Other Financing Business",
    "倉庫運輸関連": "Warehousing and Harbor Transportation Service",
    "水産農林業": "Fishery, Agriculture and Forestry",
    "石油石炭製品": "Oil and Coal Products",
    "ガラス土石製品": "Glass and Ceramics Products",
    "パルプ紙": "Pulp and Paper",
    # ── English variants from J-Quants / LLM output ──
    "electric appliance": "Electric Appliances",
    "transportation equipment": "Transportation Equipment",
    "other products": "Other Products",
    "land transportation": "Land Transportation",
    "warehousing": "Warehousing and Harbor Transportation Service",
    "communication": "Information & Communication",
    "semiconductors": "Electric Appliances",
    "semiconductor": "Electric Appliances",
    "consumer electronics": "Electric Appliances",
    "medical devices": "Precision Instruments",
    "medical": "Pharmaceutical",
    "healthcare": "Pharmaceutical",
    "finance": "Other Financing Business",
    "financial": "Other Financing Business",
    "property": "Real Estate",
    "media": "Information & Communication",
    "internet": "Information & Communication",
    "gaming": "Information & Communication",
}


class PeerDatabase:
    """In-memory peer lookup from pre-processed TSE universe data."""

    def __init__(self) -> None:
        self._db: Dict[str, Any] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not _DB_PATH.exists():
            logger.warning("Peer universe file not found: %s", _DB_PATH)
            return
        try:
            self._db = json.loads(_DB_PATH.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to load peer universe", exc_info=True)

    def _resolve_sector(self, sector_hint: str) -> str | None:
        """Map a sector hint string to an exact 33-sector name."""
        if not sector_hint:
            return None
        self._ensure_loaded()
        peers = self._db.get("peers", {})
        if not peers:
            return None

        # Exact match
        if sector_hint in peers:
            return sector_hint

        # Case-insensitive exact match
        hint_lower = sector_hint.lower()
        for key in peers:
            if key.lower() == hint_lower:
                return key

        # Normalize Unicode variants (full-width ・ vs half-width ･, etc.)
        import unicodedata
        hint_norm = unicodedata.normalize("NFKC", sector_hint)
        if hint_norm != sector_hint and hint_norm in peers:
            return hint_norm
        for key in peers:
            if unicodedata.normalize("NFKC", key) == hint_norm:
                return key

        # Alias lookup (check both directions: alias⊂hint AND hint⊂alias)
        hint_norm_lower = unicodedata.normalize("NFKC", hint_lower)
        for alias, canonical in _SECTOR_ALIAS_MAP.items():
            alias_lower = alias if alias == alias.lower() else alias.lower()
            alias_norm = unicodedata.normalize("NFKC", alias_lower)
            if (alias_lower in hint_lower or hint_lower in alias_lower
                    or alias_norm in hint_norm_lower or hint_norm_lower in alias_norm):
                if canonical in peers:
                    return canonical

        # Substring match (both directions)
        for key in peers:
            if key.lower() in hint_lower or hint_lower in key.lower():
                return key

        return None

    def find_peers(
        self,
        stock_code: str,
        sector_hint: str,
        n: int = 20,
        prefer_prime: bool = True,
    ) -> List[Dict[str, str]]:
        """Find up to n same-sector peer companies.

        Args:
            stock_code: The target company's code (excluded from results).
            sector_hint: Sector name or keyword to match.
            n: Maximum number of peers to return.
            prefer_prime: If True, prioritise Prime Market companies.

        Returns:
            List of dicts with keys: code, name, sector33, sector17, market, size.
        """
        self._ensure_loaded()
        sector = self._resolve_sector(sector_hint)
        if not sector:
            return []

        all_peers = self._db.get("peers", {}).get(sector, [])
        # Exclude the target company
        code_clean = str(stock_code).replace(".T", "").strip()
        candidates = [p for p in all_peers if str(p.get("code", "")) != code_clean]

        if not candidates:
            return []

        if prefer_prime:
            # Sort: Prime Market first, then by size (TOPIX Core30 > Large70 > Mid400 > Small)
            def _rank(p):
                market = p.get("market", "")
                size = p.get("size", "")
                m_score = 0 if "Prime" in market else (1 if "Standard" in market else 2)
                s_score = 0
                if "Core" in size:
                    s_score = 0
                elif "Large" in size:
                    s_score = 1
                elif "Mid" in size:
                    s_score = 2
                elif "Small 1" in size:
                    s_score = 3
                elif "Small 2" in size:
                    s_score = 4
                else:
                    s_score = 5
                return (m_score, s_score)
            candidates.sort(key=_rank)
        else:
            random.shuffle(candidates)

        return candidates[:n]

    def get_sector_for_code(self, stock_code: str) -> str | None:
        """Look up the 33-sector name for a given stock code."""
        self._ensure_loaded()
        code_clean = str(stock_code).replace(".T", "").strip()
        for sector, peers in self._db.get("peers", {}).items():
            for p in peers:
                if str(p.get("code", "")) == code_clean:
                    return sector
        return None

    def get_company_info(self, stock_code: str) -> Dict[str, str] | None:
        """Look up full company info for a given stock code."""
        self._ensure_loaded()
        code_clean = str(stock_code).replace(".T", "").strip()
        for sector, peers in self._db.get("peers", {}).items():
            for p in peers:
                if str(p.get("code", "")) == code_clean:
                    return p
        return None
