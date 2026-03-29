from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict
import httpx

from app.config import settings
from app.services.concurrent import run_concurrent

_shared_http_client: httpx.Client | None = None

def _get_http_client() -> httpx.Client:
    global _shared_http_client
    if _shared_http_client is None:
        _shared_http_client = httpx.Client(
            timeout=30,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            follow_redirects=True,
        )
    return _shared_http_client


@dataclass
class SerpResult:
    title: str
    url: str
    snippet: str
    date: str | None = None
    source_type: str = "web"


class SerpClient:
    def __init__(self) -> None:
        # Normalize provider; if mis-set, default to serpapi
        provider_raw = (settings.serp_provider or "").lower()
        if provider_raw not in ("serpapi", "serper"):
            provider_raw = "serpapi"
        self.provider = provider_raw

        # If api_key missing but provider env looks like a key, treat provider env as key
        if settings.serp_api_key:
            self.api_key = settings.serp_api_key
        else:
            self.api_key = settings.serp_provider if settings.serp_provider and provider_raw == "serpapi" else ""
        self.base_url = settings.serp_base_url

    def _request(self, params: Dict, json_body: Dict | None = None) -> Dict:
        if self.provider == "serper":
            headers = {
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
            }
            response = _get_http_client().post(self.base_url, json=json_body or params, headers=headers)
        else:
            response = _get_http_client().get(self.base_url, params=params)
        response.raise_for_status()
        return response.json()

    def search(self, query: str, num: int = 5, news: bool = False) -> List[SerpResult]:
        if not self.api_key:
            return []

        if self.provider == "serper":
            payload = {"q": query, "num": num}
            if news:
                payload["type"] = "news"
            data = self._request(payload, json_body=payload)
            items = data.get("news", []) if news else data.get("organic", [])
            results = []
            for item in items:
                results.append(
                    SerpResult(
                        title=item.get("title", ""),
                        url=item.get("link", ""),
                        snippet=item.get("snippet", ""),
                        date=item.get("date"),
                        source_type="news" if news else "web",
                    )
                )
            return results

        params = {
            "q": query,
            "api_key": self.api_key,
            "engine": "google",
            "num": num,
        }
        if news:
            params["tbm"] = "nws"
        data = self._request(params)
        items_key = "news_results" if news else "organic_results"
        items = data.get(items_key, [])
        results = []
        for item in items:
            results.append(
                SerpResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    date=item.get("date"),
                    source_type="news" if news else "web",
                )
            )
        return results

    def search_company_context(self, company_name: str, stock_code: str, mode: str = "full") -> List[SerpResult]:
        name = company_name if company_name and company_name != "Unknown Company" else stock_code
        base_name = company_name if company_name and company_name != "Unknown Company" else ""
        if mode == "fast":
            queries = [
                f"{name} investor relations",
                f"{name} business segments",
            ]
            news_queries = [f"{name} earnings"]
        else:
            queries = [
                f"{name} investor relations",
                f"{name} IR site",
                f"{name} business segments",
                f"{name} sector overview",
                f"{name} competitors",
                f"{name} company profile",
                f"{name} corporate profile",
                f"{name} integrated report",
                f"{name} annual report",
                f"{name} company overview",
                f"{name} 会社概要",
                f"{name} 会社情報",
                f"{name} 代表取締役",
                f"{name} 本社所在地",
                f"{name} 従業員数",
                f"{name} 沿革",
                f"{name} 事業セグメント",
            ]
            news_queries = [
                f"{name} earnings",
                f"{name} outlook",
                f"{name} news",
            ]

        if base_name and stock_code:
            queries.append(f"{base_name} {stock_code} Tokyo Stock Exchange")

        results: List[SerpResult] = []
        per_query = 2 if mode == "fast" else 3

        # Build all search tasks and run them concurrently
        tasks: list = []
        for query in queries:
            tasks.append(lambda q=query: self.search(q, num=per_query, news=False))
        if settings.serp_news:
            for query in news_queries:
                tasks.append(lambda q=query: self.search(q, num=per_query, news=True))

        batch_results = run_concurrent(tasks, max_workers=8)
        for batch in batch_results:
            if batch:
                results.extend(batch)

        blacklist_domains = ["law.cornell.edu", "irs.gov", "sec.gov"]
        blacklist_terms = ["u.s. code", "limitations on assessment", "form 4810"]
        filtered = []
        for r in results:
            if not r.url:
                continue
            url_low = r.url.lower()
            if any(bad in url_low for bad in blacklist_domains):
                continue
            text_blob = f"{r.title} {r.snippet}".lower()
            if any(term in text_blob for term in blacklist_terms):
                continue
            filtered.append(r)

        return filtered
