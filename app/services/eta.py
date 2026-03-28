"""ETA prediction v4 — stage-aware pace tracking.

Core insight: early stages are fast and inflate progress %, making naive
pace extrapolation (elapsed / progress) always underestimate.  Instead, we
track the actual duration of each completed stage, compute a pace factor
(how fast this run is relative to baseline), and apply it to remaining stages.

Algorithm:
1. Build expected durations from baselines (or historical averages if available)
2. For completed stages, compare actual vs expected → derive a pace factor
3. For remaining stages, scale expected durations by the pace factor
4. For the current stage, estimate remaining from its expected duration minus elapsed
5. Sum everything for the raw ETA
6. Smooth the output so the countdown never jumps wildly

Stages (aligned with backend progress calls):
  Starting → Company Info → Data Fetch → Extraction → Analysis
  → Valuation → Peers → Drafting → Rendering → Complete
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
    "Starting",
    "Company Info",
    "Data Fetch",
    "Extraction",
    "Analysis",
    "Valuation",
    "Peers",
    "Drafting",
    "Rendering",
    "Complete",
]

# Baseline durations in seconds — calibrated from observed runs.
# These are the "prior" before any data from the current run.
STAGE_BASELINES = {
    "Starting":       3,
    "Company Info":    6,
    "Data Fetch":     30,
    "Extraction":     15,
    "Analysis":       20,
    "Valuation":      25,
    "Peers":          15,
    "Drafting":      100,
    "Rendering":      25,
    "Complete":        0,
}

TOTAL_BASELINE = sum(STAGE_BASELINES.values())  # ~239s

# Progress % at end of each stage — proportional to baseline duration
STAGE_ENDS = {
    "Starting":       5,
    "Company Info":   12,
    "Data Fetch":     25,
    "Extraction":     35,
    "Analysis":       45,
    "Valuation":      55,
    "Peers":          60,
    "Drafting":       90,
    "Rendering":     100,
    "Complete":      100,
}

LOCK = threading.Lock()

# ── Per-job ETA state ──
_JOB_ETA_STATE: Dict[str, dict] = {}

# ── Historical stage durations (persisted across server restarts) ──
_HISTORY_PATH = Path(settings.output_dir) / "eta_history.json"
_HISTORY: Dict[str, List[float]] = {}
_MAX_HISTORY = 10  # keep last N durations per stage


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
        _HISTORY_PATH.write_text(json.dumps(_HISTORY))
    except Exception:
        pass


_load_history()


def _expected_duration(stage: str) -> float:
    """Best estimate for a stage's duration: historical median or baseline."""
    hist = _HISTORY.get(stage)
    if hist and len(hist) >= 2:
        s = sorted(hist)
        mid = len(s) // 2
        median = s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
        # Blend: 70% historical median + 30% baseline (prevents runaway drift)
        return 0.7 * median + 0.3 * STAGE_BASELINES.get(stage, 15)
    return float(STAGE_BASELINES.get(stage, 15))


def _compute_pace_factor(stage_history: list) -> float:
    """Compute how fast this run is relative to expected durations.

    Returns a multiplier: 1.0 = on pace, 1.5 = 50% slower, 0.8 = 20% faster.
    Uses only stages with meaningful duration (>1s) to avoid noise.
    """
    if not stage_history:
        return 1.0

    ratios = []
    for entry in stage_history:
        stage = entry.get("stage", "")
        actual = float(entry.get("duration", 0))
        expected = _expected_duration(stage)
        if actual > 1 and expected > 1:
            ratios.append(actual / expected)

    if not ratios:
        return 1.0

    # Use median ratio (robust to outliers)
    ratios.sort()
    mid = len(ratios) // 2
    median = ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2

    # Clamp to reasonable range (0.3x to 3.0x)
    return max(0.3, min(median, 3.0))


def _raw_eta(job) -> float | None:
    """Compute raw ETA (remaining seconds) using stage-aware pace tracking."""
    step = getattr(job, "step", None)
    if not step or step == "Complete":
        return 0.0

    try:
        stage_history = getattr(job, "stage_history", []) or []

        # 1. Pace factor from completed stages
        pace = _compute_pace_factor(stage_history)

        # 2. Elapsed time in current stage
        elapsed_in_stage = 0.0
        if job.stage_started_at:
            try:
                start_ts = dt.datetime.fromisoformat(job.stage_started_at)
                elapsed_in_stage = max((dt.datetime.now() - start_ts).total_seconds(), 0)
            except Exception:
                pass

        # 3. Expected remaining for current stage
        expected_current = _expected_duration(step) * pace
        if elapsed_in_stage >= expected_current:
            # Overrun: estimate proportionally more time needed
            # The longer we've overrun, the less confident we are — add 30% of overrun
            remaining_current = max(elapsed_in_stage * 0.3, 3.0)
        else:
            remaining_current = expected_current - elapsed_in_stage

        # 4. Sum of future stages (scaled by pace)
        if step in STAGE_ORDER:
            idx = STAGE_ORDER.index(step)
            future_stages = STAGE_ORDER[idx + 1:]
        else:
            future_stages = []

        future_sum = sum(_expected_duration(s) * pace for s in future_stages
                         if s != "Complete")

        # 5. Cross-check against total elapsed time
        total_elapsed = 0.0
        started = getattr(job, "started_at", None)
        if started:
            try:
                total_elapsed = max(
                    (dt.datetime.now() - dt.datetime.fromisoformat(started)).total_seconds(),
                    0,
                )
            except Exception:
                pass

        raw = remaining_current + future_sum

        # When pace factor has little data (≤2 completed stages), the ETA
        # relies mostly on baselines.  If a significant stage (baseline >5s)
        # is overrunning, that's a signal this run is slower — bump future estimates.
        stage_baseline = STAGE_BASELINES.get(step, 0)
        if (len(stage_history) <= 2
                and elapsed_in_stage > expected_current
                and stage_baseline > 5):
            # How much slower is this stage vs expected? Use that as ad-hoc pace.
            adhoc_pace = elapsed_in_stage / (_expected_duration(step) or 15)
            adhoc_pace = max(1.0, min(adhoc_pace, 3.0))  # only bump up, never down
            # Re-compute future with the ad-hoc pace instead of the weak pace factor
            future_sum = sum(_expected_duration(s) * adhoc_pace for s in future_stages
                             if s != "Complete")
            raw = remaining_current + future_sum

        # Sanity: if we're in Drafting or later, ETA shouldn't be less than
        # what Drafting alone would take
        if step == "Drafting" and raw < 15:
            raw = max(raw, 15)

        return max(2.0, min(raw, 600.0))

    except Exception:
        return None


def predict_eta(job) -> float | None:
    """ETA with smooth monotonic countdown.

    Uses per-job state so the displayed ETA ticks down steadily.
    Server corrections are absorbed gradually — never jumps up wildly.
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

        # Where the countdown should be if ticking at 1s/s
        expected = max(prev_eta - elapsed_since, 0)

        stage_changed = job.step != state["step"]

        if raw <= expected:
            # Ahead of schedule — let it drop faster
            smoothed = 0.4 * expected + 0.6 * raw
        elif stage_changed:
            # Stage transition — allow moderate correction (up to 15s increase)
            smoothed = expected + min(raw - expected, 15.0)
        else:
            # Behind schedule within same stage — limit increase to 5s
            smoothed = expected + min(raw - expected, 5.0)

        smoothed = max(2.0, min(smoothed, 600.0))

        state["eta"] = smoothed
        state["ts"] = now
        state["step"] = job.step

        return round(smoothed)


def interpolate_progress(job) -> int:
    """Smooth progress interpolation within the current stage.

    Uses elapsed time vs expected duration with an ease-out curve
    so the progress bar always appears to be moving.
    """
    base_progress = getattr(job, "progress", 0) or 0
    step = getattr(job, "step", None)

    if not step or step not in STAGE_ORDER or step == "Complete":
        return base_progress

    try:
        idx = STAGE_ORDER.index(step)
        prev_stage = STAGE_ORDER[idx - 1] if idx > 0 else None
        start_pct = STAGE_ENDS.get(prev_stage, 0) if prev_stage else 0
        end_pct = STAGE_ENDS.get(step, start_pct + 5)

        if not job.stage_started_at:
            return max(base_progress, start_pct)

        # Use pace-adjusted expected duration for this stage
        stage_history = getattr(job, "stage_history", []) or []
        pace = _compute_pace_factor(stage_history)
        expected = _expected_duration(step) * pace

        start_ts = dt.datetime.fromisoformat(job.stage_started_at)
        elapsed = max((dt.datetime.now() - start_ts).total_seconds(), 0)

        if elapsed >= expected and expected > 0:
            # Overrun: creep toward 95% asymptotically
            overshoot = elapsed / expected
            frac = 0.90 + 0.05 * (1 - 1.0 / max(overshoot, 1.0))
            frac = min(frac, 0.95)
        else:
            frac = min(elapsed / max(expected, 1.0), 0.90)

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
    """Record completed stage durations for future ETA predictions."""
    job_id = getattr(job, "job_id", None)
    if job_id:
        cleanup_job(job_id)

    stage_history = getattr(job, "stage_history", []) or []
    if not stage_history:
        return

    with LOCK:
        for entry in stage_history:
            stage = entry.get("stage")
            duration = float(entry.get("duration") or 0)
            if not stage or duration <= 0:
                continue
            if stage not in _HISTORY:
                _HISTORY[stage] = []
            _HISTORY[stage].append(round(duration, 1))
            # Keep only recent history
            if len(_HISTORY[stage]) > _MAX_HISTORY:
                _HISTORY[stage] = _HISTORY[stage][-_MAX_HISTORY:]
        _save_history()
