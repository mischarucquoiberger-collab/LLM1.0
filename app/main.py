from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, asdict, field
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from starlette.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio
import json
import logging
import threading
import uuid
import datetime as dt

from app.config import settings
from app.services.report import build_report_context
from app.services.pdf import render_pdf_from_html
from app.services.usage import usage_snapshot
from app.services.diagnostics import diagnostics_snapshot
from app.services import eta  # ETA model

app = FastAPI(title="LLM Research Report MVP")

# Pre-build EDINET 大量保有 index in background on startup (makes first query instant)
@app.on_event("startup")
async def _warm_edinet_index():
    from app.services.chat import warm_060_index
    warm_060_index()

# Pre-train ML valuation model in background — only if cache already
# exists (refresh before expiry).  Avoid cold-start training on startup
# because the bulk J-Quants fetches compete with per-report peer lookups
# for rate-limit budget, slowing down actual reports.
@app.on_event("startup")
async def _warm_valuation_model():
    from app.services.valuation import ValuationEngine
    eng = ValuationEngine()
    meta, _ = eng._load_cached_model()
    if meta:
        # Model exists but might expire soon — refresh in background
        eng.train_model_background()

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

static_path = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@dataclass
class JobStatus:
    job_id: str
    status: str = "queued"
    progress: int = 0
    step: str = "Queued"
    message: str = "Waiting to start."
    error: str | None = None
    html_file: str | None = None
    pdf_file: str | None = None
    company_name: str | None = None
    stock_code: str | None = None
    input_company_name: str | None = None
    resolved_company_name: str | None = None
    source_count: int = 0
    sources: list[dict] = field(default_factory=list)
    edinet_count: int = 0
    financial_rows: int = 0
    price_rows: int = 0
    financials_source: str | None = None
    warnings: list[str] | None = None
    created_at: str = field(default_factory=lambda: dt.datetime.now().isoformat(timespec="seconds"))
    started_at: str | None = None
    finished_at: str | None = None
    events: list[dict] = field(default_factory=list)
    edinet_scanned: int = 0
    edinet_total: int = 0
    edinet_current: str | None = None
    stage_history: list[dict] = field(default_factory=list)
    stage_started_at: str | None = None
    mode: str = "full"


JOBS: dict[str, JobStatus] = {}
JOBS_LOCK = threading.Lock()
_background_tasks: set = set()  # prevent GC of fire-and-forget tasks


def _update_job(job_id: str, **updates) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        for key, value in updates.items():
            setattr(job, key, value)


def _append_event(job_id: str, event_type: str, message: str, meta: dict | None = None) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        entry = {
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "type": event_type,
            "message": message,
            "meta": meta or {},
        }
        job.events.append(entry)
        if len(job.events) > 200:
            job.events = job.events[-200:]


def _build_report_files(stock_code: str, company_name: str | None, mode: str, job_id: str) -> JobStatus:
    stage_history: list[dict] = []
    stage_state = {"current": None, "start": None}

    def on_progress(pct: int, step: str, message: str) -> None:
        prev_step = None
        prev_msg = None
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                prev_step = job.step
                prev_msg = job.message
        now = dt.datetime.now()
        # Track stage timing
        if stage_state["current"] != step:
            if stage_state["current"] is not None and stage_state["start"] is not None:
                duration = (now - stage_state["start"]).total_seconds()
                stage_history.append({
                    "stage": stage_state["current"],
                    "duration": duration,
                    "started_at": stage_state["start"].isoformat(timespec="seconds"),
                    "ended_at": now.isoformat(timespec="seconds"),
                    "mode": mode,
                })
            stage_state["current"] = step
            stage_state["start"] = now
            # Push stage_history to job so predict_eta() can see completed stages mid-run
            _update_job(job_id, stage_started_at=now.isoformat(timespec="seconds"),
                        stage_history=list(stage_history))

        _update_job(job_id, progress=pct, step=step, message=message)
        if step != prev_step or message != prev_msg:
            _append_event(job_id, "stage", f"{step} — {message}")

    def on_event(event_type: str, message: str, meta: dict | None = None) -> None:
        if event_type == "edinet_scan" and meta:
            _update_job(
                job_id,
                edinet_scanned=int(meta.get("index") or 0),
                edinet_total=int(meta.get("total") or 0),
                edinet_current=meta.get("doc_id"),
            )
        if event_type == "edinet" and meta:
            doc_id = meta.get("doc_id")
            if doc_id:
                with JOBS_LOCK:
                    job = JOBS.get(job_id)
                    if job:
                        seen = {ev.get("meta", {}).get("doc_id") for ev in job.events if ev.get("type") == "edinet"}
                        if doc_id not in seen:
                            job.edinet_count = (job.edinet_count or 0) + 1
        _append_event(job_id, event_type, message, meta)

    if company_name is not None:
        company_name = company_name.strip() or None

    context = build_report_context(
        stock_code,
        company_name,
        mode=mode,
        on_progress=on_progress,
        on_event=on_event,
    )

    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build a filesystem-safe slug using stock_code + job_id (avoids Unicode issues)
    slug = f"{context['stock_code']}_{job_id[:8]}"
    html_path = output_dir / f"report_{slug}.html"
    pdf_path = output_dir / f"report_{slug}.pdf"

    try:
        html_content = TEMPLATES.get_template("report.html").render({
            "request": None,
            **context,
        })
    except Exception as exc:
        # Template rendering failed — write a minimal error report so the user
        # still gets *something* viewable rather than a 500 on every access.
        from html import escape as _esc
        html_content = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>Report Error — {_esc(str(context.get('stock_code', '')))}</title></head>"
            "<body style='font-family:sans-serif;padding:40px'>"
            f"<h1>Report generation partially failed</h1>"
            f"<p>Company: {_esc(str(context.get('company_name', 'Unknown')))} ({_esc(str(context.get('stock_code', '')))})</p>"
            f"<p>Error during template rendering: <code>{_esc(str(exc))}</code></p>"
            "<p>The data was collected successfully but the dashboard template could not render. "
            "This is usually caused by missing or unexpected data in the pipeline output.</p>"
            "</body></html>"
        )
        _update_job(job_id, error=f"Template render error: {exc}")

    html_path.write_text(html_content, encoding="utf-8")

    pdf_error = None
    if settings.report_output.lower() == "pdf":
        try:
            _update_job(job_id, progress=94, step="Rendering", message="Rendering PDF output")
            render_pdf_from_html(html_path, pdf_path)
            _update_job(job_id, progress=98, step="Rendering", message="Finalizing PDF")
        except Exception as exc:
            pdf_error = str(exc)

    with JOBS_LOCK:
        status = JOBS.get(job_id)
        if status is None:
            return None
        data_health = context.get("data_health", {})
        status.company_name = context.get("company_name")
        status.stock_code = context.get("stock_code")
        status.resolved_company_name = context.get("company_name")
        status.source_count = int(data_health.get("sources", 0) or 0)
        status.sources = context.get("sources", [])
        status.edinet_count = int(data_health.get("edinet_filings", 0) or 0)
        status.financial_rows = int(data_health.get("financial_rows", 0) or 0)
        status.price_rows = int(data_health.get("price_rows", 0) or 0)
        status.financials_source = data_health.get("financials_source")
        status.warnings = data_health.get("warnings")
        status.html_file = html_path.name
        if settings.report_output.lower() == "pdf" and pdf_path.exists():
            status.pdf_file = pdf_path.name
        if pdf_error and not status.pdf_file:
            status.error = pdf_error
        status.stage_history = stage_history
        return status


async def _run_job(job_id: str, stock_code: str, company_name: str | None, mode: str) -> None:
    _update_job(
        job_id,
        status="running",
        progress=2,
        step="Starting",
        message="Starting data collection",
        started_at=dt.datetime.now().isoformat(timespec="seconds"),
    )
    _append_event(job_id, "stage", "Starting — Starting data collection")
    try:
        await asyncio.to_thread(_build_report_files, stock_code, company_name, mode, job_id)
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                return
            has_error = job.error
            has_html = bool(job.html_file)
        if has_error and has_html:
            _update_job(
                job_id,
                status="warning",
                progress=100,
                step="Complete",
                message="HTML ready. PDF failed. See error for details.",
                finished_at=dt.datetime.now().isoformat(timespec="seconds"),
            )
        elif has_error:
            _update_job(
                job_id,
                status="error",
                progress=100,
                step="Error",
                message="Report generated with errors",
                finished_at=dt.datetime.now().isoformat(timespec="seconds"),
            )
        else:
            _update_job(
                job_id,
                status="complete",
                progress=100,
                step="Complete",
                message="Report ready",
                finished_at=dt.datetime.now().isoformat(timespec="seconds"),
            )
        # Train ETA models from this run if we have stage history
        try:
            with JOBS_LOCK:
                j = JOBS.get(job_id)
            if j:
                eta.record_job(j)
        except Exception:
            pass
    except Exception as exc:
        _update_job(
            job_id,
            status="error",
            progress=100,
            step="Error",
            message="Failed to generate report",
            error=str(exc),
            finished_at=dt.datetime.now().isoformat(timespec="seconds"),
        )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return FileResponse(str(BASE_DIR / "templates" / "index.html"))











@app.post("/start")
async def start(
    stock_code: str = Form(...),
    company_name: str = Form(""),
    mode: str = Form("full"),
):
    import re as _re
    # Input validation / sanitization
    stock_code = _re.sub(r"[^0-9A-Za-z.]", "", stock_code.strip())[:10]
    if not stock_code:
        raise HTTPException(status_code=400, detail="Invalid stock code.")
    company_name = _re.sub(r"[<>&\"']", "", company_name.strip())[:100]
    if mode not in ("full", "fast"):
        mode = "full"
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = JobStatus(
            job_id=job_id,
            stock_code=stock_code,
            input_company_name=company_name,
            mode=mode,
        )

    task = asyncio.create_task(_run_job(job_id, stock_code, company_name or None, mode))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return JSONResponse(
        {
            "job_id": job_id,
            "received": {
                "stock_code": stock_code,
                "company_name": company_name,
                "mode": mode,
            },
        }
    )


@app.get("/status/{job_id}")
async def status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        data = asdict(job)
    # ETA calculations outside lock to avoid blocking worker thread
    try:
        eta_seconds = eta.predict_eta(job)
        if eta_seconds is not None:
            data["eta_seconds"] = int(eta_seconds)
        data["interpolated_progress"] = eta.interpolate_progress(job)
    except Exception:
        pass
    # Build completed dict {stage: seconds} for frontend ETA learning
    if data.get("stage_history"):
        data["completed"] = {
            s["stage"]: round(s["duration"], 1)
            for s in data["stage_history"]
            if "stage" in s and "duration" in s
        }
    # Strip events from polling response — they can contain control chars
    # and are large (use /stream/{job_id} for live events instead)
    data.pop("events", None)
    # Sanitize error field (tracebacks can contain tabs/newlines)
    if data.get("error") and isinstance(data["error"], str):
        data["error"] = data["error"].replace("\t", "  ").replace("\n", " | ")
    return JSONResponse(data)


@app.get("/usage")
async def usage():
    data = await asyncio.to_thread(usage_snapshot)
    return JSONResponse(data)


@app.get("/diagnostics")
async def diagnostics(code: str = "6501", days: int = 120):
    data = await asyncio.to_thread(diagnostics_snapshot, code=code, days=days)
    return JSONResponse(data)


@app.get("/download")
async def download(file: str, inline: bool = False):
    output_dir = Path(settings.output_dir).resolve()
    target = (output_dir / file).resolve()
    # Path-traversal guard: target must live inside output_dir
    try:
        target.relative_to(output_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file path.")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    media_type = "application/pdf" if target.suffix == ".pdf" else "text/html"
    headers = {}
    if inline:
        headers["Content-Disposition"] = "inline"
    else:
        # Use ASCII-safe filename for Content-Disposition
        safe_name = target.name.encode("ascii", "replace").decode("ascii")
        headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    return FileResponse(path=str(target), media_type=media_type, headers=headers)


@app.get("/view/{job_id}")
async def view_report(job_id: str):
    """Serve report HTML directly by job ID — resilient alternative to /download."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if not job.html_file:
        raise HTTPException(
            status_code=202,
            detail="Report is still being generated. Please try again shortly.",
        )
    output_dir = Path(settings.output_dir).resolve()
    target = (output_dir / job.html_file).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="Report file not found on disk.")
    return FileResponse(path=str(target), media_type="text/html", headers={"Content-Disposition": "inline"})


@app.get("/stream/{job_id}")
async def stream_events(job_id: str):
    """Server-Sent Events endpoint for live report progress streaming."""
    async def event_generator():
        last_index = 0
        while True:
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if not job:
                    not_found = True
                else:
                    not_found = False
                    events = job.events[last_index:]
                    last_index = len(job.events)
                    is_done = job.status in ("complete", "warning", "error")
            if not_found:
                yield f"event: error\ndata: Job not found\n\n"
                return
            for ev in events:
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if is_done:
                yield f"event: done\ndata: {{}}\n\n"
                return
            await asyncio.sleep(0.3)
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a completed job and its output files (idempotent)."""
    job = None
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job and job.status == "running":
            raise HTTPException(status_code=409, detail="Cannot delete a running job.")
        JOBS.pop(job_id, None)

    # Clean cached report text
    _report_text_cache.pop(job_id, None)
    if job and job.html_file:
        _report_text_cache.pop(job.html_file, None)

    # Try to clean up files on disk (even if job wasn't in memory)
    output_dir = Path(settings.output_dir).resolve()
    deleted_files = []
    file_candidates = []
    if job:
        file_candidates = [job.html_file, job.pdf_file]
    else:
        # Job not in memory (server restarted) — try common file patterns
        for ext in ("html", "pdf"):
            file_candidates.append(f"{job_id}.{ext}")

    for fname in file_candidates:
        if not fname:
            continue
        fpath = (output_dir / fname).resolve()
        try:
            fpath.relative_to(output_dir)
        except ValueError:
            continue
        if fpath.exists():
            await asyncio.to_thread(fpath.unlink)
            deleted_files.append(fname)
    return JSONResponse({"deleted": True, "job_id": job_id, "files_removed": deleted_files})


# ── Director network endpoint ──────────────────────────────

@app.get("/api/directors/{ticker}")
async def api_directors(ticker: str, name: str = ""):
    """Generate or return cached director network data for a company."""
    from app.services.directors import get_director_network
    import traceback

    company_name = name or ticker
    try:
        data = await asyncio.to_thread(get_director_network, ticker, company_name)
        return JSONResponse(data)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


# ── Live quote endpoint (for polling live prices) ────────

@app.get("/api/quote/{code}")
async def api_quote(code: str):
    """Return a live Yahoo Finance quote for a TSE stock code."""
    from app.services.chat import _fetch_yahoo_quote
    quote = await asyncio.to_thread(_fetch_yahoo_quote, code)
    if not quote:
        raise HTTPException(status_code=404, detail="No quote data available")
    return JSONResponse(quote)


# ── Price history endpoint (for chart sparklines) ────────

@app.get("/api/price-history/{code}")
async def api_price_history(code: str, days: int = 90, interval: str = "1d"):
    """Return price history for chart rendering.

    For short ranges (1D, 5D) pass interval=5m or interval=15m to get
    intraday data from Yahoo Finance.  Longer ranges use daily closes
    from J-Quants / Stooq as before.
    """
    from app.services.jquants import JQuantsClient
    import logging, datetime as _dt
    logger = logging.getLogger(__name__)

    def _fetch():
        # Try Yahoo Finance first (works for all intervals and has deeper history)
        yahoo_data = _fetch_yahoo_chart(code, days, interval, logger)
        if yahoo_data:
            # Yahoo's coarse range buckets (e.g. "6mo" for 92-day YTD) may
            # return more data than the requested window.  Trim daily data
            # to only include dates within the requested calendar-day span.
            if interval == "1d" and days > 0:
                cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
                yahoo_data = [p for p in yahoo_data if (p.get("date") or "") >= cutoff]
            return yahoo_data

        # Fallback to J-Quants / Stooq for daily data
        if interval != "1d":
            return []
        client = JQuantsClient()
        quotes = []
        from_date = (_dt.date.today() - _dt.timedelta(days=min(days + 30, 2000))).isoformat()
        try:
            data = client.get_prices(code, from_date=from_date)
            quotes = data.get("daily_quotes") or data.get("data") or []
        except Exception as e:
            logger.debug(f"J-Quants price fetch failed for {code}: {e}")

        if not quotes:
            try:
                data = client.get_prices_fallback_csv(code, from_date=from_date)
                quotes = data.get("daily_quotes") or []
            except Exception as e:
                logger.debug(f"Stooq fallback failed for {code}: {e}")

        if not quotes:
            return []

        recent = quotes[-days:]
        compact = []
        for q in recent:
            close = q.get("Close") or q.get("AdjustmentClose") or q.get("AdjC") or q.get("C")
            if close is not None:
                compact.append({
                    "date": q.get("Date", ""),
                    "close": close,
                })
        return compact

    result = await asyncio.to_thread(_fetch)
    return JSONResponse(result)


def _fetch_yahoo_chart(code: str, days: int, interval: str, logger) -> list:
    """Fetch price data from Yahoo Finance chart API (intraday or daily)."""
    import datetime as _dt
    from app.services.chat import _get_yahoo_client

    symbol = f"{code.strip()}.T"
    # Map days to Yahoo range strings
    if days <= 1:
        yf_range = "1d"
    elif days <= 5:
        yf_range = "5d"
    elif days <= 30:
        yf_range = "1mo"
    elif days <= 90:
        yf_range = "3mo"
    elif days <= 180:
        yf_range = "6mo"
    elif days <= 365:
        yf_range = "1y"
    elif days <= 730:
        yf_range = "2y"
    else:
        yf_range = "5y"

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval={interval}&range={yf_range}"
    )
    try:
        resp = _get_yahoo_client().get(url, timeout=12)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug(f"Yahoo chart failed for {code}: {e}")
        return []

    results = data.get("chart", {}).get("result", [])
    if not results:
        return []

    timestamps = results[0].get("timestamp", [])
    quotes = results[0].get("indicators", {}).get("quote", [{}])[0]
    closes = quotes.get("close", [])
    opens = quotes.get("open", [])
    highs = quotes.get("high", [])
    lows = quotes.get("low", [])

    is_intraday = interval != "1d" and interval != "1wk" and interval != "1mo"

    compact = []
    for i, ts in enumerate(timestamps):
        close = closes[i] if i < len(closes) else None
        if close is None:
            continue
        t = _dt.datetime.fromtimestamp(ts)
        date_str = t.strftime("%Y-%m-%d %H:%M") if is_intraday else t.strftime("%Y-%m-%d")
        entry = {"date": date_str, "close": round(close, 1)}
        if is_intraday:
            entry["open"] = round(opens[i], 1) if i < len(opens) and opens[i] is not None else None
            entry["high"] = round(highs[i], 1) if i < len(highs) and highs[i] is not None else None
            entry["low"] = round(lows[i], 1) if i < len(lows) and lows[i] is not None else None
        compact.append(entry)
    return compact


# ── Report text cache (avoids re-parsing HTML per question) ──
_report_text_cache: dict[str, str] = {}
_REPORT_CACHE_MAX = 50


def _strip_html_to_text(html: str) -> str:
    """Strip HTML to clean text for the AI companion context."""
    import re
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<svg[^>]*>[\s\S]*?</svg>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    for ent, ch in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " "), ("&#x27;", "'"), ("&quot;", '"')]:
        text = text.replace(ent, ch)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > 50_000:
        text = text[:50_000] + "\n\n[Report truncated for context window]"
    return text


def _extract_report_text(job: JobStatus) -> str:
    """Extract clean text from a JobStatus object's report HTML."""
    if job.job_id in _report_text_cache:
        return _report_text_cache[job.job_id]
    if not job.html_file:
        return ""
    output_dir = Path(settings.output_dir).resolve()
    html_path = output_dir / job.html_file
    if not html_path.exists():
        return ""
    text = _strip_html_to_text(html_path.read_text(encoding="utf-8"))
    if len(_report_text_cache) >= _REPORT_CACHE_MAX:
        try:
            _report_text_cache.pop(next(iter(_report_text_cache)))
        except StopIteration:
            pass
    _report_text_cache[job.job_id] = text
    return text


def _extract_report_text_from_file(filename: str) -> str:
    """Extract clean text from an HTML report file by name (fallback for old reports)."""
    if filename in _report_text_cache:
        return _report_text_cache[filename]
    output_dir = Path(settings.output_dir).resolve()
    target = (output_dir / filename).resolve()
    try:
        target.relative_to(output_dir)
    except ValueError:
        return ""
    if not target.exists():
        return ""
    text = _strip_html_to_text(target.read_text(encoding="utf-8"))
    if len(_report_text_cache) >= _REPORT_CACHE_MAX:
        try:
            _report_text_cache.pop(next(iter(_report_text_cache)))
        except StopIteration:
            pass
    _report_text_cache[filename] = text
    return text


# ── Report companion chat endpoint ────────────────────────

@app.post("/api/report-chat")
async def api_report_chat(request: Request):
    """Report-context AI assistant. Works with both live jobs and old reports on disk."""
    from app.services.chat import stream_report_chat

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    report_text = None
    sources = []
    company = body.get("company", "")

    # Strategy 1: job_id → look up in-memory JOBS (just-generated reports)
    job_id = body.get("job_id")
    if job_id:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if job and job.status in ("complete", "warning"):
            report_text = _extract_report_text(job)
            sources = job.sources or []
            company = company or job.company_name or job.stock_code or ""

    # Strategy 2: file → read HTML directly from disk (previous reports)
    if not report_text:
        file_name = body.get("file")
        if file_name:
            report_text = _extract_report_text_from_file(file_name)
            sources = body.get("sources") or []

    if not report_text:
        raise HTTPException(status_code=404, detail="Report not found")

    async def event_generator():
        try:
            async for event_str in stream_report_chat(report_text, sources, messages, company):
                yield event_str
        except Exception as e:
            logging.getLogger("api").error(f"Report chat stream error: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Chat / Query endpoint ─────────────────────────────────

@app.post("/api/chat")
async def api_chat(request: Request):
    """Claude-powered query endpoint with tool use. Streams SSE events."""
    from app.services.chat import stream_chat_response

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    messages = body.get("messages", [])
    mode = body.get("mode", "stream")  # "stream" or "instant"

    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    async def event_generator():
        try:
            async for event_str in stream_chat_response(messages, mode=mode):
                yield event_str
        except Exception as e:
            logging.getLogger("api").error(f"Chat stream error: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Text-to-Speech (edge-tts) ────────────────────────────

@app.post("/api/tts")
async def api_tts(request: Request):
    """Stream natural-sounding TTS audio (MP3) via Microsoft Edge neural voices."""
    import edge_tts
    import re
    import logging

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")
    if len(text) > 2000:
        text = text[:2000]

    voice = body.get("voice", "en-US-AvaNeural")
    rate = body.get("rate", "+5%")

    # Validate voice (allow known edge-tts neural voice pattern)
    if not re.match(r"^[a-zA-Z]{2}-[a-zA-Z]{2}-\w+$", voice):
        voice = "en-US-AvaNeural"
    # Validate rate (e.g. "+5%", "-10%", "+0%")
    if not re.match(r"^[+-]\d{1,3}%$", rate):
        rate = "+5%"

    async def audio_stream():
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        except Exception as e:
            logging.getLogger("tts").warning(f"TTS stream error: {e}")

    return StreamingResponse(
        audio_stream(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
    )


# ── Catch-all for client-side routing (React Router) ──────────
# Must be LAST so it doesn't shadow API/static routes.
@app.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_catch_all(request: Request, full_path: str):
    # Skip API, static, and file-download paths
    if full_path.startswith(("api/", "static/", "start", "status/", "stream/", "jobs/", "download")):
        raise HTTPException(status_code=404)
    return FileResponse(str(BASE_DIR / "templates" / "index.html"))
