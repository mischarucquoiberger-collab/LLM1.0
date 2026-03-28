"""TSE sector lookup from local CSV data."""
import csv
from pathlib import Path
from functools import lru_cache

_DATA = Path(__file__).resolve().parent.parent / "data" / "sector_map.csv"


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    mapping = {}
    with open(_DATA, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row["code"].strip()
            mapping[code] = {
                "name_en": row["name_en"],
                "sector_33": row["sector_33"],
                "sector_17": row["sector_17"],
            }
    return mapping


def get_sector(stock_code: str) -> str | None:
    """Return 33-sector name for a stock code, or None if not found."""
    code = stock_code.strip().replace(".T", "")
    entry = _load().get(code)
    if entry:
        return entry["sector_33"] or entry["sector_17"] or None
    # Fallback: try the peer universe database
    try:
        from app.services.peer_db import PeerDatabase
        db = PeerDatabase()
        return db.get_sector_for_code(code)
    except Exception:
        return None


def get_sector_detail(stock_code: str) -> dict | None:
    """Return full sector detail dict, or None."""
    code = stock_code.strip().replace(".T", "")
    return _load().get(code)
