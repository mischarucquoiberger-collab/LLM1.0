"""PDF rendering via Playwright with persistent browser pool.

Keeps a warm Chromium instance across calls so subsequent renders skip
the 3-5s cold-start penalty.  The browser is lazily launched on first
use and cleaned up on process exit.
"""
from __future__ import annotations

import atexit
import threading
from pathlib import Path

_lock = threading.Lock()
_playwright_ctx = None
_browser = None


def _get_browser():
    """Return a reusable Chromium browser instance (lazy init, thread-safe)."""
    global _playwright_ctx, _browser
    with _lock:
        if _browser is not None:
            try:
                # Quick liveness check — if browser crashed, relaunch
                _browser.contexts  # noqa: B018
                return _browser
            except Exception:
                _browser = None
                _playwright_ctx = None

        from playwright.sync_api import sync_playwright
        _playwright_ctx = sync_playwright().start()
        _browser = _playwright_ctx.chromium.launch()
        return _browser


def _cleanup():
    """Clean up browser on process exit."""
    global _browser, _playwright_ctx
    try:
        if _browser:
            _browser.close()
    except Exception:
        pass
    try:
        if _playwright_ctx:
            _playwright_ctx.stop()
    except Exception:
        pass
    _browser = None
    _playwright_ctx = None


atexit.register(_cleanup)


def render_pdf_from_html(html_path: Path, pdf_path: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401 — verify installed
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Playwright is required for PDF rendering. Install playwright and run 'playwright install'."
        ) from exc

    html_path = html_path.resolve()
    pdf_path = pdf_path.resolve()
    if not html_path.exists():
        raise FileNotFoundError(f"HTML file not found at {html_path}")

    browser = _get_browser()
    page = browser.new_page()
    try:
        page.goto(html_path.as_uri(), wait_until="networkidle")
        page.pdf(path=str(pdf_path), format="A4", print_background=True)
    finally:
        page.close()
