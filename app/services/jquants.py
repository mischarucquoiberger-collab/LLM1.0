from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import httpx

from app.config import settings
from app.services.sector_lookup import get_sector


@dataclass
class JQuantsCompany:
    name: str
    sector: str | None = None
    market: str | None = None


class JQuantsClient:
    def __init__(self) -> None:
        self.api_key = settings.jquants_api_key
        self.base_url = settings.jquants_base_url.strip()
        self.mode = settings.jquants_mode
        self.refresh_token = settings.jquants_refresh_token
        self.api_key_header = settings.jquants_api_key_header

    def _candidate_codes(self, stock_code: str) -> list[str]:
        cleaned = stock_code.strip().upper().replace(".T", "")
        candidates = [cleaned]
        # Pure numeric 4-digit codes get a 5-digit variant (trailing 0)
        if cleaned.isdigit() and len(cleaned) == 4:
            candidates.append(f"{cleaned}0")
        # Alphanumeric codes (e.g. 157A, 247A) — new JPX format
        # Also try without trailing letter for legacy API compatibility
        if len(cleaned) >= 3 and any(c.isalpha() for c in cleaned):
            digits_only = "".join(c for c in cleaned if c.isdigit())
            if digits_only and digits_only != cleaned:
                candidates.append(digits_only)
        candidates.append(f"{cleaned}.T")
        return list(dict.fromkeys([c for c in candidates if c]))

    def _headers(self) -> Dict[str, str]:
        if self.mode == "api_key":
            return {self.api_key_header: self.api_key}
        if self.mode == "token" and self.refresh_token:
            token = self._get_id_token()
            return {"Authorization": f"Bearer {token}"}
        return {}

    def _get_id_token(self, refresh_token: str | None = None) -> str:
        token_source = refresh_token or self.refresh_token
        if not token_source:
            return ""
        url = f"{self.base_url}/v1/token/auth_refresh"
        response = httpx.post(url, json={"refreshToken": token_source}, timeout=30)
        response.raise_for_status()
        return response.json().get("idToken", "")

    def _get(self, endpoint: str, params: Dict) -> Dict:
        """
        Robust GET with dual-mode auth and dual host fallback:
        1) Primary host from settings (api.jpx-jquants.com by default).
        2) If DNS fails, retry with api.jquants.com.
        3) Auth: API-key header first; on 401/403, retry with Bearer token.
        4) Auto-retry on 429 (rate limit) with exponential backoff.
        """
        import time as _time

        def do_request(base_url: str, headers: Dict) -> httpx.Response:
            url = f"{base_url}{endpoint}"
            return httpx.get(url, params=params, headers=headers, timeout=30)

        headers_primary = self._headers()

        def try_hosts(headers):
            bases = [self.base_url]
            if "jpx-jquants" in self.base_url:
                bases.append(self.base_url.replace("jpx-jquants", "jquants"))
            last_exc = None
            for base in bases:
                try:
                    resp = do_request(base, headers)
                    resp.raise_for_status()
                    return resp
                except httpx.HTTPStatusError as exc:
                    last_exc = exc
                    status = exc.response.status_code
                    if status in (401, 403):
                        raise exc
                    if status == 429:
                        raise exc  # bubble up for retry handling
                    continue
                except httpx.RequestError as req_err:
                    last_exc = req_err
                    continue
            raise last_exc or httpx.RequestError("All host attempts failed")

        def _try_with_rate_limit_retry(headers, max_retries=2):
            for attempt in range(max_retries):
                try:
                    return try_hosts(headers)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429:
                        retry_after = exc.response.headers.get("Retry-After")
                        wait = min(float(retry_after) if retry_after else 1.0, 2.0)
                        _time.sleep(wait)
                        continue
                    raise
            # final attempt without catching
            return try_hosts(headers)

        # Attempt 1: primary headers (API key or bearer if mode=token)
        try:
            response = _try_with_rate_limit_retry(headers_primary)
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status not in (401, 403):
                raise

        # Attempt 2: bearer token via refresh token (or api_key as refresh token)
        try_refresh = self.refresh_token or self.api_key
        if try_refresh:
            try:
                id_token = self._get_id_token(refresh_token=try_refresh)
                if id_token:
                    headers_fallback = {"Authorization": f"Bearer {id_token}"}
                    response = _try_with_rate_limit_retry(headers_fallback)
                    return response.json()
            except Exception:
                pass

        # Final raise to surface the original problem
        response = _try_with_rate_limit_retry(headers_primary)
        response.raise_for_status()
        return response.json()

    def get_company_info(self, stock_code: str) -> JQuantsCompany | None:
        if not self.api_key and not self.refresh_token:
            return None

        for code in self._candidate_codes(stock_code):
            params = {"code": code}
            payload = self._get(settings.jquants_company_endpoint, params)
            info = payload.get("info") or payload.get("data") or []
            if isinstance(info, list) and info:
                item = info[0]
                return JQuantsCompany(
                    name=item.get("CompanyName") or item.get("CoNameEn") or item.get("CoName") or "",
                    sector=item.get("Sector33CodeName") or item.get("S33Nm") or item.get("Sector17CodeName") or item.get("S17Nm") or get_sector(code),
                    market=item.get("MarketCodeName") or item.get("MktNm"),
                )
        return None

    def get_listed_info(self, stock_code: str) -> Dict | None:
        if not self.api_key and not self.refresh_token:
            return None

        for code in self._candidate_codes(stock_code):
            params = {"code": code}
            payload = self._get(settings.jquants_company_endpoint, params)
            info = payload.get("info") or payload.get("data") or []
            if isinstance(info, list) and info:
                return info[0]
        return None

    def get_financials(self, stock_code: str) -> Dict:
        if not self.api_key and not self.refresh_token:
            return {}

        for code in self._candidate_codes(stock_code):
            params = {"code": code, "limit": 60}
            payload = self._get(settings.jquants_financials_endpoint, params)
            data = payload.get("statements") or payload.get("financials") or payload.get("data")
            if data:
                return payload
        return {}

    def get_prices(self, stock_code: str, from_date: str | None = None) -> Dict:
        if not self.api_key and not self.refresh_token:
            return {}

        import datetime as dt
        # default: pull last 365 days to ensure 52-week range coverage
        if from_date is None:
            default_from = (dt.date.today() - dt.timedelta(days=365)).strftime("%Y%m%d")
        else:
            # ensure YYYYMMDD format if it was passed as ISO
            try:
                d = dt.date.fromisoformat(from_date)
                default_from = d.strftime("%Y%m%d")
            except ValueError:
                default_from = from_date.replace("-", "")

        to_date = dt.date.today().strftime("%Y%m%d")

        endpoints = [settings.jquants_prices_endpoint]
        # v2 fallback if present
        if settings.jquants_prices_endpoint != "/v2/equities/bars/daily":
            endpoints.append("/v2/equities/bars/daily")

        for code in self._candidate_codes(stock_code):
            for ep in endpoints:
                params = {"code": code, "from": default_from, "to": to_date, "limit": 300}
                try:
                    payload = self._get(ep, params)
                except Exception:
                    continue
                data = payload.get("daily_quotes") or payload.get("data")
                if data:
                    return payload
        return {}

    def get_prices_fallback_csv(self, stock_code: str, from_date: str | None = None) -> Dict:
        """
        Lightweight, dependency-free fallback using Stooq daily CSV (public).
        Symbol format: {code}.jp (Tokyo). Returns dict with daily_quotes list.
        """
        import datetime as dt
        symbol = f"{stock_code.strip().upper().replace('.T','')}.jp"
        url = f"https://stooq.pl/q/d/l/?s={symbol}&i=d"
        try:
            resp = httpx.get(url, timeout=12)
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()
            if len(lines) <= 1:
                return {}
            header = lines[0].split(",")
            idx_map = {name: i for i, name in enumerate(header)}
            rows = []
            for line in lines[1:]:
                parts = line.split(",")
                date = parts[idx_map.get("Data", 0)]
                if from_date:
                    try:
                        if dt.date.fromisoformat(date) < dt.date.fromisoformat(from_date):
                            continue
                    except Exception:
                        pass
                def pick(key):
                    try:
                        return float(parts[idx_map[key]])
                    except Exception:
                        return None
                rows.append({
                    "Date": date,
                    "Close": pick("Zamkniecie"),
                    "Open": pick("Otwarcie"),
                    "High": pick("Najwyzszy"),
                    "Low": pick("Najnizszy"),
                    "Volume": pick("Wolumen"),
                })
            return {"daily_quotes": rows}
        except Exception:
            return {}
