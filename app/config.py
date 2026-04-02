from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1")
    openai_admin_key: str = os.getenv("OPENAI_ADMIN_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_narrative_model: str = os.getenv("ANTHROPIC_NARRATIVE_MODEL", "claude-sonnet-4-6")

    serp_provider: str = os.getenv("SERP_PROVIDER", "serpapi")
    serp_api_key: str = os.getenv("SERP_API_KEY", "")
    serp_base_url: str = os.getenv("SERP_BASE_URL", "https://serpapi.com/search")
    serp_news: bool = os.getenv("SERP_NEWS", "true").lower() == "true"

    edinet_api_key: str = os.getenv("EDINET_API_KEY", "")
    edinet_subscription_key: str = os.getenv("EDINET_SUBSCRIPTION_KEY", "")
    edinet_base_url: str = os.getenv("EDINET_BASE_URL", "https://api.edinet-fsa.go.jp/api/v2")
    edinet_lookback_days: int = int(os.getenv("EDINET_LOOKBACK_DAYS", "1200"))
    edinet_doc_type: int = int(os.getenv("EDINET_DOC_TYPE", "2"))
    edinet_require_xbrl: bool = os.getenv("EDINET_REQUIRE_XBRL", "true").lower() == "true"
    edinet_preferred_doctypes: str = os.getenv("EDINET_PREFERRED_DOCTYPES", "120,130,140,160,110")
    edinet_only: bool = os.getenv("EDINET_ONLY", "false").lower() == "true"
    edinet_instance_try_limit: int = int(os.getenv("EDINET_INSTANCE_TRY_LIMIT", "6"))

    jquants_api_key: str = os.getenv("JQUANTS_API_KEY", "")
    jquants_base_url: str = os.getenv("JQUANTS_BASE_URL", "https://api.jpx-jquants.com")
    jquants_mode: str = os.getenv("JQUANTS_MODE", "api_key")  # api_key or token
    jquants_refresh_token: str = os.getenv("JQUANTS_REFRESH_TOKEN", "")
    jquants_api_key_header: str = os.getenv("JQUANTS_API_KEY_HEADER", "X-API-KEY")
    jquants_prices_only: bool = os.getenv("JQUANTS_PRICES_ONLY", "true").lower() == "true"

    jquants_financials_endpoint: str = os.getenv("JQUANTS_FINANCIALS_ENDPOINT", "/v1/fins/statements")
    jquants_prices_endpoint: str = os.getenv("JQUANTS_PRICES_ENDPOINT", "/v1/prices/daily_quotes")
    jquants_company_endpoint: str = os.getenv("JQUANTS_COMPANY_ENDPOINT", "/v1/listed/info")

    report_output: str = os.getenv("REPORT_OUTPUT", "pdf")  # pdf or html
    output_dir: str = os.getenv("OUTPUT_DIR", "output")
    max_sources: int = int(os.getenv("MAX_SOURCES", "8"))
    mock_mode: bool = os.getenv("MOCK_MODE", "false").lower() == "true"
    usage_lookback_days: int = int(os.getenv("USAGE_LOOKBACK_DAYS", "30"))

    ml_enabled: bool = os.getenv("ML_ENABLED", "true").lower() == "true"
    ml_max_tickers: int = int(os.getenv("ML_MAX_TICKERS", "50"))
    ml_cache_days: int = int(os.getenv("ML_CACHE_DAYS", "7"))
    ml_min_samples: int = int(os.getenv("ML_MIN_SAMPLES", "15"))

    dcf_wacc: float = float(os.getenv("DCF_WACC", "0.08"))
    dcf_terminal_growth: float = float(os.getenv("DCF_TERMINAL_GROWTH", "0.015"))
    dcf_years: int = int(os.getenv("DCF_YEARS", "5"))


settings = Settings()
