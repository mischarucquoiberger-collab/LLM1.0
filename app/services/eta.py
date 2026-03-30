"""ETA prediction v5 — adaptive pace with elapsed crosscheck.

Two-signal approach for accurate ETA:
1. Stage-based: uses baseline durations scaled by observed pace factor
2. Elapsed-based: uses total_elapsed / progress_fraction as a crosscheck

Blends both signals — early on trusts stage baselines more, later trusts
elapsed extrapolation more as it becomes statistically reliable.

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

# Baseline durations in seconds — calibrated from observed single runs (2026-03).
# Total ~250s (~4:10) — realistic for a typical fast-mode report.
STAGE_BASELINES = {
    "Starting":       2,
    "Company Info":    5,
    "Data Fetch":     25,
    "Extraction":     15,
    "Analysis":       18,
    "Valuation":      22,
    "Peers":          15,
    "Drafting":      110,
    "Rendering":      20,
    "Complete":        0,
}

TOTAL_BASELINE = sum(STAGE_BASELINES.values())  # ~232s

# Stages that are meaningful for pace estimation.
# Starting & Company Info are always fast (CPU-bound) and shouldn't influence
# pace prediction for API-bound stages like Drafting.
_PACE_RELEVANT_STAGES = {"Data Fetch", "Extraction", "Analysis", "Valuation", "Peers", "Drafting", "Rendering"}

# Progress % at end of each stage — proportional to baseline duration
STAGE_ENDS = {
    "Starting":       5,
    "Company Info":   10,
    "Data Fetch":     25,
    "Extraction":     35,
    "Analysis":       45,
    "Valuation":      55,
    "Peers":          60,
    "Drafting":       90,
    "Rendering":     100,
    "Complete":      100,
}

# Weight of each stage for pace calculation — heavier stages
# are more informative about overall run speed.
_STAGE_WEIGHT = {s: max(STAGE_BASELINES.get(s, 5), 3) for s in STAGE_ORDER}

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
        return 0.7 * median + 0.3 * STAGE_BASELINES.get(stage, 10)
    return float(STAGE_BASELINES.get(stage, 10))


def _compute_pace_factor(stage_history: list) -> float:
    """Compute how fast this run is relative to expected durations.

    Returns a multiplier: 1.0 = on pace, 1.5 = 50% slower, 0.5 = 50% faster.
    Only uses API-bound stages (Data Fetch+) — Starting/Company Info are always
    fast and would bias the estimate low.
    """
    if not stage_history:
        return 1.0

    weighted_ratios = []
    for entry in stage_history:
        stage = entry.get("stage", "")
        # Skip CPU-bound stages that don't predict API-bound stage speed
        if stage not in _PACE_RELEVANT_STAGES:
            continue
        actual = float(entry.get("duration", 0))
        expected = _expected_duration(stage)
        if actual > 0.5 and expected > 0.5:
            weight = _STAGE_WEIGHT.get(stage, 3)
            ratio = actual / expected
            weighted_ratios.append((ratio, weight))

    if not weighted_ratios:
        return 1.0

    # Weighted median
    weighted_ratios.sort(key=lambda x: x[0])
    total_weight = sum(w for _, w in weighted_ratios)
    cumulative = 0
    for ratio, weight in weighted_ratios:
        cumulative += weight
        if cumulative >= total_weight / 2:
            return max(0.3, min(ratio, 3.0))

    return 1.0


def _raw_eta(job) -> float | None:
    """Compute raw ETA (remaining seconds) using dual-signal approach."""
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
            remaining_current = max(elapsed_in_stage * 0.2, 2.0)
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

        stage_eta = remaining_current + future_sum

        # 5. Elapsed-based crosscheck using weighted stage position
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

        # Compute weighted fraction done (using baseline weights, not progress %)
        # This is more accurate than progress % because it accounts for heavy stages
        completed_baseline = sum(
            STAGE_BASELINES.get(e.get("stage", ""), 0) for e in stage_history
        )
        # Add partial current stage
        current_baseline = STAGE_BASELINES.get(step, 10)
        if current_baseline > 0 and elapsed_in_stage > 0:
            current_frac = min(elapsed_in_stage / (current_baseline * max(pace, 0.3)), 0.95)
            completed_baseline += current_baseline * current_frac

        weight_done = completed_baseline / max(TOTAL_BASELINE, 1)
        weight_done = max(0.01, min(weight_done, 0.99))

        elapsed_eta = None
        if total_elapsed > 8 and weight_done > 0.05:
            elapsed_eta = total_elapsed / weight_done * (1 - weight_done)

        # 6. Blend: only use elapsed crosscheck after enough progress
        # At early stages, trust baselines; after Extraction+, blend more
        n_relevant_completed = sum(
            1 for e in stage_history if e.get("stage") in _PACE_RELEVANT_STAGES
        )
        raw = stage_eta
        if elapsed_eta is not None and n_relevant_completed >= 1:
            # After 1+ relevant stage, start blending
            elapsed_weight = min(0.7, n_relevant_completed * 0.2)
            raw = (1 - elapsed_weight) * stage_eta + elapsed_weight * elapsed_eta

        # Hard cap: ETA should never exceed 5 minutes for a single report
        return max(2.0, min(raw, 300.0))

    except Exception:
        return None


def predict_eta(job) -> float | None:
    """ETA with smooth monotonic countdown.

    Uses per-job state so the displayed ETA ticks down steadily.
    Server corrections are absorbed gradually — never jumps up wildly,
    but corrections downward happen quickly.
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
            # Ahead of schedule — drop fast (users love seeing ETA shrink)
            smoothed = 0.3 * expected + 0.7 * raw
        elif stage_changed:
            # Stage transition — allow moderate correction (up to 10s increase)
            smoothed = expected + min(raw - expected, 10.0)
        else:
            # Behind schedule within same stage — limit increase to 3s
            smoothed = expected + min(raw - expected, 3.0)

        smoothed = max(2.0, min(smoothed, 300.0))

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
