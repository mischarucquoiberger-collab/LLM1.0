"""ETA prediction v6 — total-duration-centric with progress-to-time mapping.

With parallel pipeline execution, individual stage durations are unreliable
(a stage may take 0.1s or 180s depending on what runs in parallel).

Instead, this uses two primary signals:
1. Historical total run duration — median of past runs by mode
2. Elapsed extrapolation — using a progress-to-time mapping that correctly
   accounts for Drafting being the bulk of the work

The progress-to-time map converts reported progress % (which is stage-based)
into estimated time fraction (what % of total time has passed).  This is the
key to accurate ETA: at 70% progress, we know we're only ~50% done time-wise
because Drafting (60-90% progress) takes most of the remaining time.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path
from typing import Dict, List

from app.config import settings

# ── Stage definitions (must match backend progress calls) ──

STAGE_ORDER = [
    "Starting", "Company Info", "Data Fetch", "Extraction",
    "Analysis", "Valuation", "Peers", "Drafting", "Rendering", "Complete",
]

# Progress % at end of each stage — for progress bar interpolation.
STAGE_ENDS = {
    "Starting": 5, "Company Info": 10, "Data Fetch": 25, "Extraction": 35,
    "Analysis": 45, "Valuation": 55, "Peers": 60, "Drafting": 90,
    "Rendering": 100, "Complete": 100,
}

# ── Progress-to-time mapping ──
# Maps (progress %, time fraction) — calibrated for parallel pipeline.
# Key insight: stages 25-60% (Extraction/Analysis/Valuation/Peers) often
# complete in seconds due to parallelism, while Drafting (60-90%) takes
# the majority of total time.
_PROGRESS_TIME = [
    (0,   0.00),
    (5,   0.02),   # Starting — instant
    (10,  0.05),   # Company Info — fast
    (25,  0.18),   # Data Fetch — moderate
    (35,  0.22),   # Extraction — often overlaps
    (45,  0.25),   # Analysis — often overlaps
    (55,  0.55),   # Valuation — significant J-Quants work
    (60,  0.70),   # Peers — more J-Quants work
    (90,  0.90),   # Drafting — fast with cache, slow without
    (100, 1.00),   # Rendering + done
]

# Baseline total run durations (seconds) when no history exists.
TOTAL_BASELINE = {"fast": 50, "full": 90}

LOCK = threading.Lock()

# ── Per-job ETA state ──
_JOB_ETA_STATE: Dict[str, dict] = {}

# ── Historical data (persisted across server restarts) ──
_HISTORY_PATH = Path(settings.output_dir) / "eta_history.json"
_HISTORY: Dict[str, list] = {}
_MAX_HISTORY = 15


def _load_history():
    global _HISTORY
    if _HISTORY_PATH.exists():
        try:
            _HISTORY = json.loads(_HISTORY_PATH.read_text())
        except Exception:
            _HISTORY = {}


def _save_history():
    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_PATH.write_text(json.dumps(_HISTORY, indent=2))
    except Exception:
        pass


_load_history()


def _progress_to_time_frac(pct: float) -> float:
    """Convert progress % to estimated time fraction (piecewise linear)."""
    pct = max(0.0, min(pct, 100.0))
    for i in range(len(_PROGRESS_TIME) - 1):
        p0, t0 = _PROGRESS_TIME[i]
        p1, t1 = _PROGRESS_TIME[i + 1]
        if p0 <= pct <= p1:
            if p1 == p0:
                return t0
            return t0 + (pct - p0) / (p1 - p0) * (t1 - t0)
    return 1.0


def _get_expected_total(mode: str = "full") -> float:
    """Best estimate for total run duration: historical median or baseline."""
    key = f"_total_{mode}"
    hist = _HISTORY.get(key)
    if hist and len(hist) >= 2:
        s = sorted(hist)
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
    return float(TOTAL_BASELINE.get(mode, 200))


def _raw_eta(job) -> float | None:
    """Compute raw ETA using total-duration + elapsed extrapolation."""
    step = getattr(job, "step", None)
    if not step or step == "Complete":
        return 0.0

    try:
        mode = getattr(job, "mode", "full") or "full"
        expected_total = _get_expected_total(mode)

        # Total elapsed time since job started
        total_elapsed = 0.0
        started = getattr(job, "started_at", None)
        if started:
            try:
                total_elapsed = max(
                    (dt.datetime.now() - dt.datetime.fromisoformat(started)).total_seconds(), 0
                )
            except Exception:
                pass

        # Current progress — use stage position as floor
        progress = getattr(job, "progress", 0) or 0
        if step in STAGE_ORDER:
            idx = STAGE_ORDER.index(step)
            prev = STAGE_ORDER[idx - 1] if idx > 0 else None
            floor_pct = STAGE_ENDS.get(prev, 0) if prev else 0
            progress = max(progress, floor_pct)

        # Convert progress to time fraction (the key correction)
        time_frac = _progress_to_time_frac(progress)
        time_frac = max(0.01, min(time_frac, 0.99))

        # Signal 1: expected_total minus elapsed
        hist_eta = max(expected_total - total_elapsed, 0)

        # Signal 2: elapsed extrapolation using time fraction
        elapsed_eta = None
        if total_elapsed > 5 and time_frac > 0.03:
            elapsed_eta = total_elapsed / time_frac * (1 - time_frac)

        # Blend: trust elapsed extrapolation more as we progress further
        if elapsed_eta is not None:
            w = min(0.85, time_frac * 1.6)
            raw = (1 - w) * hist_eta + w * elapsed_eta
        else:
            raw = hist_eta

        return max(3.0, min(raw, 300.0))

    except Exception:
        return None


def predict_eta(job) -> float | None:
    """ETA with smooth monotonic countdown.

    Per-job state ensures the displayed ETA ticks down steadily.
    Downward corrections are fast; upward corrections are limited.
    """
    raw = _raw_eta(job)
    if raw is None:
        return None

    job_id = getattr(job, "job_id", None)
    if not job_id:
        return round(raw)

    now = time.time()

    with LOCK:
        state = _JOB_ETA_STATE.get(job_id)

        if state is None:
            _JOB_ETA_STATE[job_id] = {"eta": raw, "ts": now, "step": job.step}
            return round(raw)

        prev_eta = state["eta"]
        prev_ts = state["ts"]
        elapsed_since = now - prev_ts

        # Where countdown should be if ticking at 1s/s
        expected = max(prev_eta - elapsed_since, 0)

        stage_changed = job.step != state["step"]

        if raw <= expected:
            # Ahead of schedule — drop quickly (users love seeing ETA shrink)
            smoothed = 0.3 * expected + 0.7 * raw
        elif stage_changed:
            # Stage transition — allow moderate upward correction
            smoothed = expected + min(raw - expected, 8.0)
        else:
            # Behind within same stage — tiny increase only
            smoothed = expected + min(raw - expected, 2.0)

        smoothed = max(2.0, min(smoothed, 300.0))

        state["eta"] = smoothed
        state["ts"] = now
        state["step"] = job.step

        return round(smoothed)


def interpolate_progress(job) -> int:
    """Smooth progress interpolation within the current stage.

    Uses total elapsed vs expected total to estimate how far through
    the current stage we are, producing a smooth-moving progress bar.
    """
    base_progress = getattr(job, "progress", 0) or 0
    step = getattr(job, "step", None)

    if not step or step not in STAGE_ORDER or step == "Complete":
        return base_progress

    try:
        idx = STAGE_ORDER.index(step)
        prev = STAGE_ORDER[idx - 1] if idx > 0 else None
        start_pct = STAGE_ENDS.get(prev, 0) if prev else 0
        end_pct = STAGE_ENDS.get(step, start_pct + 5)

        if not job.stage_started_at:
            return max(base_progress, start_pct)

        # Total elapsed from job start
        mode = getattr(job, "mode", "full") or "full"
        expected_total = _get_expected_total(mode)

        total_elapsed = 0.0
        started = getattr(job, "started_at", None)
        if started:
            try:
                total_elapsed = max(
                    (dt.datetime.now() - dt.datetime.fromisoformat(started)).total_seconds(), 0
                )
            except Exception:
                pass

        # Expected time window for this stage (from progress-to-time map)
        t_start = _progress_to_time_frac(start_pct)
        t_end = _progress_to_time_frac(end_pct)
        expected_stage_secs = max((t_end - t_start) * expected_total, 1.0)

        # Elapsed within this stage
        start_ts = dt.datetime.fromisoformat(job.stage_started_at)
        stage_elapsed = max((dt.datetime.now() - start_ts).total_seconds(), 0)

        if stage_elapsed < 0.3:
            frac = 0.02
        elif stage_elapsed >= expected_stage_secs:
            # Overrun: asymptotically approach 95%
            overshoot = stage_elapsed / expected_stage_secs
            frac = 0.90 + 0.05 * (1 - 1.0 / max(overshoot, 1.0))
            frac = min(frac, 0.95)
        else:
            frac = min(stage_elapsed / expected_stage_secs, 0.90)

        # Ease-out: fast start, decelerates near end
        eased = 1 - (1 - frac) ** 2.5

        interpolated = int(start_pct + eased * (end_pct - start_pct))
        return max(base_progress, interpolated)

    except Exception:
        return base_progress


def cleanup_job(job_id: str):
    """Remove per-job ETA state when job completes."""
    with LOCK:
        _JOB_ETA_STATE.pop(job_id, None)


def record_job(job):
    """Record completed job data for future ETA predictions."""
    job_id = getattr(job, "job_id", None)
    if job_id:
        cleanup_job(job_id)

    # Record total run duration (primary signal for future ETAs)
    started = getattr(job, "started_at", None)
    finished = getattr(job, "finished_at", None)
    mode = getattr(job, "mode", "full") or "full"

    if started and finished:
        try:
            total_duration = (
                dt.datetime.fromisoformat(finished) - dt.datetime.fromisoformat(started)
            ).total_seconds()
            if total_duration > 5:
                key = f"_total_{mode}"
                with LOCK:
                    if key not in _HISTORY:
                        _HISTORY[key] = []
                    _HISTORY[key].append(round(total_duration, 1))
                    if len(_HISTORY[key]) > _MAX_HISTORY:
                        _HISTORY[key] = _HISTORY[key][-_MAX_HISTORY:]
        except Exception:
            pass

    # Also record individual stage durations (backward compat + diagnostics)
    stage_history = getattr(job, "stage_history", []) or []
    with LOCK:
        for entry in stage_history:
            stage = entry.get("stage")
            duration = float(entry.get("duration") or 0)
            if not stage or duration <= 0:
                continue
            if stage not in _HISTORY:
                _HISTORY[stage] = []
            _HISTORY[stage].append(round(duration, 1))
            if len(_HISTORY[stage]) > _MAX_HISTORY:
                _HISTORY[stage] = _HISTORY[stage][-_MAX_HISTORY:]
        _save_history()
