from __future__ import annotations

import datetime as dt
import socket
from typing import Dict, Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.services.jquants import JQuantsClient
from app.services.edinet import EdinetClient


def _dns_lookup(host: str) -> Dict[str, Any]:
    try:
        ip = socket.gethostbyname(host)
        return {"ok": True, "ip": ip}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def edinet_check(code: str, days: int) -> Dict[str, Any]:
    if not (settings.edinet_api_key or settings.edinet_subscription_key):
        return {"ok": False, "error": "EDINET key missing (EDINET_SUBSCRIPTION_KEY or EDINET_API_KEY)."}

    base = settings.edinet_base_url.rstrip("/")
    host = urlparse(base).hostname or ""
    dns = _dns_lookup(host) if host else {"ok": False, "error": "No host"}
    auth_mode = "subscription" if settings.edinet_subscription_key else ("api_key" if settings.edinet_api_key else "none")

    url = f"{base}/documents.json"
    params = {
        "date": dt.date.today().isoformat(),
        "type": settings.edinet_doc_type,
        **({"Subscription-Key": settings.edinet_subscription_key} if settings.edinet_subscription_key else {}),
        **({"api_key": settings.edinet_api_key} if settings.edinet_api_key else {}),
    }

    match_info: Dict[str, Any] = {}
    try:
        client = EdinetClient()
        matches = client.latest_filings_for_code(code, days_back=days, max_docs=5)
        match_info = {
            "match_code": code,
            "match_days": days,
            "match_count": len(matches),
            "match_samples": [
                {
                    "docID": doc.doc_id,
                    "docTypeCode": doc.doc_type_code,
                    "submitDate": doc.submit_date,
                    "filerName": doc.filer_name,
                }
                for doc in matches
            ],
        }
    except Exception as exc:
        match_info = {"match_code": code, "match_days": days, "match_error": str(exc)}

    try:
        response = httpx.get(url, params=params, timeout=20)
        status = response.status_code
        payload = response.json()
        results = payload.get("results", [])
        sample = [
            {
                "docID": item.get("docID"),
                "filerName": item.get("filerName"),
                "secCode": item.get("secCode"),
            }
            for item in results[:3]
        ]
        return {
            "ok": True,
            "status": status,
            "doc_type": settings.edinet_doc_type,
            "results_count": len(results),
            "sample": sample,
            "dns": dns,
            "base_url": base,
            "auth_mode": auth_mode,
            **match_info,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "dns": dns, "auth_mode": auth_mode, **match_info}


def jquants_check(code: str = "6501") -> Dict[str, Any]:
    base = settings.jquants_base_url.rstrip("/")
    host = urlparse(base).hostname or ""
    dns = _dns_lookup(host) if host else {"ok": False, "error": "No host"}

    if not settings.jquants_api_key and not settings.jquants_refresh_token:
        return {"ok": False, "error": "J-Quants credentials missing.", "dns": dns}

    client = JQuantsClient()
    try:
        info = client.get_company_info(code)
        return {
            "ok": True,
            "dns": dns,
            "company": info.name if info else None,
            "sector": info.sector if info else None,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "dns": dns}


def diagnostics_snapshot(code: str = "6501", days: int = 120) -> Dict[str, Any]:
    return {
        "edinet": edinet_check(code=code, days=days),
        "jquants": jquants_check(),
        "config": {
            "edinet_base_url": settings.edinet_base_url,
            "jquants_base_url": settings.jquants_base_url,
            "edinet_doc_type": settings.edinet_doc_type,
        },
    }
