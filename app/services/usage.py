from __future__ import annotations

import datetime as dt
from typing import Dict, Any

import httpx

from app.config import settings


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


def fetch_serp_usage() -> Dict[str, Any]:
    if settings.serp_provider.lower() != "serpapi":
        return {
            "status": "unsupported",
            "message": f"SERP provider '{settings.serp_provider}' usage not supported yet.",
        }
    if not settings.serp_api_key:
        return {"status": "unavailable", "message": "SERP_API_KEY missing."}

    url = "https://serpapi.com/account.json"
    response = httpx.get(url, params={"api_key": settings.serp_api_key}, timeout=20)
    if response.status_code != 200:
        return {"status": "error", "message": response.text}

    payload = response.json()
    return {
        "status": "ok",
        "plan_searches_left": payload.get("plan_searches_left"),
        "total_searches_left": payload.get("total_searches_left"),
        "this_month_usage": payload.get("this_month_usage"),
        "searches_per_month": payload.get("searches_per_month"),
        "account_rate_limit_per_hour": payload.get("account_rate_limit_per_hour"),
    }


def fetch_openai_costs() -> Dict[str, Any]:
    api_key = settings.openai_admin_key or settings.openai_api_key
    if not api_key:
        return {"status": "unavailable", "message": "OPENAI_API_KEY missing."}

    lookback_days = max(settings.usage_lookback_days, 1)
    start_time = int((dt.datetime.utcnow() - dt.timedelta(days=lookback_days)).timestamp())

    url = "https://api.openai.com/v1/organization/costs"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "start_time": start_time,
        "bucket_width": "1d",
        "limit": lookback_days,
    }

    response = httpx.get(url, headers=headers, params=params, timeout=20)
    if response.status_code != 200:
        return {
            "status": "error",
            "message": response.text,
        }

    payload = response.json()
    total_cost = 0.0
    currency = "USD"
    for bucket in payload.get("data", []):
        for result in bucket.get("results", []):
            amount = result.get("amount", {})
            value = _to_float(amount.get("value"))
            if value is not None:
                total_cost += value
            currency = amount.get("currency", currency)

    return {
        "status": "ok",
        "cost_last_period": round(total_cost, 2),
        "currency": currency,
        "lookback_days": lookback_days,
        "note": "OpenAI does not expose remaining credits via API. This is spend to date in the lookback window.",
    }


def usage_snapshot() -> Dict[str, Any]:
    return {
        "serp": fetch_serp_usage(),
        "openai": fetch_openai_costs(),
        "edinet": {
            "status": "not_implemented",
            "message": "EDINET usage endpoint is not implemented in this MVP.",
        },
        "jquants": {
            "status": "not_implemented",
            "message": "J-Quants usage endpoint is not implemented in this MVP.",
        },
    }
