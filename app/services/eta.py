"""ETA prediction v8 — Per-stage duration tracking with adaptive blending.

Core insight: stages have wildly different speeds. Data Fetch takes ~15s,
Drafting (LLM call) takes ~45s, Rendering takes ~5s. A single global
pace estimate will always be wrong.

Algorithm:
  ETA = time_remaining_in_current_stage + sum(expected_duration for future stages)

Per-stage expected duration uses:
  1. Historical median from previous runs (best — adapts over time)
  2. Realistic defaults (fallback for first few runs)

Current stage remaining uses:
  - max(0, expected_duration - elapsed_in_stage)
  - With stall detection: if stage takes >2x expected, extend proportionally

Historical data is persisted across server restarts in eta_history.json.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path
from typing import Dict

from app.config import settings

# ── Stage definitions (must match backend progress calls) ──

STAGE_ORDER = [
    "Starting", "Company Info", "Data Fetch", "Extraction",
    "Analysis", "Valuation", "Compilation", "Peers", "Drafting", "Rendering", "Complete",
]

STAGE_ENDS = {
    "Starting": 5, "Company Info": 10, "Data Fetch": 25, "Extraction": 35,
    "Analysis": 55, "Valuation": 65, "Compilation": 78, "Peers": 80,
    "Drafting": 92, "Rendering": 100, "Complete": 100,
}

# Realistic default durations per stage (seconds) — used when no history exists.
# These reflect typical observed timings for a full report.
STAGE_DEFAULTS = {
    "Starting": 1,
    "Company Info": 13,
    "Data Fetch": 18,
    "Extraction": 2,
    "Analysis": 5,
    "Valuation": 3,
    "Compilation": 5,
    "Peers": 20,          # Often includes background task completion waits
    "Drafting": 30,       # LLM narrative generation — can be fast if cached
    "Rendering": 6,
    "Complete": 0,
}

# Fast mode has shorter durations
STAGE_DEFAULTS_FAST = {
    "Starting": 1,
    "Company Info": 8,
    "Data Fetch": 10,
    "Extraction": 1,
    "Analysis": 3,
    "Valuation": 2,
    "Compilation": 3,
    "Peers": 10,
    "Drafting": 18,
    "Rendering": 4,
    "Complete": 0,
}

TOTAL_BASELINE = {"fast": 50, "full": 90}

LOCK = threading.Lock()

# ── Per-job ETA state ──
_JOB_ETA_STATE: Dict[str, dict] = {}

# ── Historical data (persisted across server restarts) ──
_HISTORY_PATH = Path(settings.output_dir) / "eta_history.json"
_HISTORY: Dict[str, list] = {}
_MAX_HISTORY = 20


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


def _median(values: list) -> float:
    """Compute median of a list of numbers."""
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _get_stage_expected(stage: str, mode: str = "full") -> float:
    """Expected duration for a stage: historical median or default."""
    hist = _HISTORY.get(stage)
    if hist and len(hist) >= 2:
        return _median(hist)
    defaults = STAGE_DEFAULTS_FAST if mode == "fast" else STAGE_DEFAULTS
    return float(defaults.get(stage, 5))


def _get_expected_total(mode: str = "full") -> float:
    """Best estimate for total run duration: historical median or baseline."""
    key = f"_total_{mode}"
    hist = _HISTORY.get(key)
    if hist and len(hist) >= 2:
        return _median(hist)
    return float(TOTAL_BASELINE.get(mode, 90))


# ── Progress-to-time mapping (kept for interpolate_progress) ──
_PROGRESS_TIME = [
    (0,   0.00),
    (5,   0.01),   # Starting — instant
    (10,  0.14),   # Company Info — ~13s
    (25,  0.32),   # Data Fetch — ~18s
    (35,  0.34),   # Extraction — ~2s
    (55,  0.39),   # Analysis — ~5s
    (65,  0.42),   # Valuation — ~3s
    (78,  0.47),   # Compilation — ~5s
    (80,  0.67),   # Peers — ~20s
    (92,  0.94),   # Drafting — ~30s
    (100, 1.00),   # Rendering — ~6s
]


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


# ── Core ETA Estimator ──

class StageETA:
    """Per-stage ETA estimator.

    ETA = time_remaining_in_current_stage + sum(expected_duration for future stages)
    """

    def __init__(self, mode: str = "full"):
        self.mode = mode
        self.current_stage = None
        self.stage_start_time = None
        self.job_start_time = None

    def update(self, progress: float, current_time: float, step: str) -> float:
        """Feed new observation, return raw ETA in seconds."""
        if self.job_start_time is None:
            self.job_start_time = current_time

        # Detect stage change
        if step != self.current_stage:
            self.current_stage = step
            self.stage_start_time = current_time

        if step not in STAGE_ORDER or step == "Complete":
            return 0.0

        stage_idx = STAGE_ORDER.index(step)
        stage_elapsed = current_time - (self.stage_start_time or current_time)
        stage_expected = _get_stage_expected(step, self.mode)

        # Time remaining in current stage
        if stage_elapsed < stage_expected:
            current_remaining = stage_expected - stage_elapsed
        else:
            # Stage is taking longer than expected.
            # Use a logarithmic decay: the longer we overshoot, the less
            # confident we are about when it'll finish. Add a proportional
            # buffer that shrinks slowly.
            import math
            overshoot = stage_elapsed - stage_expected
            # Estimate remaining = base_buffer * decay_factor
            # At 2x overshoot: ~40% of expected remaining
            # At 5x overshoot: ~25% of expected remaining
            # At 10x: ~15%
            decay = 1.0 / (1.0 + math.log1p(overshoot / max(stage_expected, 1.0)))
            current_remaining = max(3.0, stage_expected * decay)

        # Sum expected durations for all future stages
        future_remaining = 0.0
        for future_idx in range(stage_idx + 1, len(STAGE_ORDER)):
            future_stage = STAGE_ORDER[future_idx]
            if future_stage == "Complete":
                continue
            future_remaining += _get_stage_expected(future_stage, self.mode)

        raw = current_remaining + future_remaining

        # Sanity: use total elapsed as a cross-check
        if self.job_start_time:
            total_elapsed = current_time - self.job_start_time
            total_expected = _get_expected_total(self.mode)
            if total_elapsed > 5 and total_expected > 0:
                elapsed_frac = total_elapsed / total_expected
                if elapsed_frac > 0.1:
                    # Elapsed-based projection
                    elapsed_projection = total_expected - total_elapsed
                    # Blend: 70% stage-based, 30% elapsed-based
                    if elapsed_projection > 0:
                        raw = 0.7 * raw + 0.3 * elapsed_projection

        return max(2.0, min(raw, 600.0))


# ── Display Damper ──

class DisplayDamper:
    """Smooth ETA for display with proportional corrections.

    Ticks down naturally at ~1s/s.
    Downward corrections: fast (users love seeing ETA shrink).
    Upward corrections: proportional, not fixed-cap (handles big stalls).
    Stage changes: allow larger jumps (new info available).
    """

    def __init__(self):
        self.displayed_eta = None
        self.last_ts = None

    def smooth(self, raw_eta: float, now: float, stage_changed: bool) -> float:
        if self.displayed_eta is None:
            self.displayed_eta = raw_eta
            self.last_ts = now
            return round(raw_eta)

        elapsed = now - self.last_ts
        self.last_ts = now

        # Where the countdown would be if ticking at 1s/s
        expected = max(self.displayed_eta - elapsed, 0)

        if stage_changed:
            # Stage boundary — trust the new estimate more (70% new, 30% current)
            result = 0.3 * expected + 0.7 * raw_eta
        elif raw_eta <= expected:
            # Ahead of schedule — fast drop (60% toward raw each update)
            result = 0.4 * expected + 0.6 * raw_eta
        else:
            # Behind within same stage — proportional correction
            delta = raw_eta - expected
            correction = min(delta * 0.3, max(expected * 0.3, 5.0))
            result = expected + correction

        # Floor: if raw says work remains (>3s), don't show 1s
        if raw_eta > 3.0:
            result = max(result, 3.0)

        result = max(1.0, min(result, 600.0))
        self.displayed_eta = result
        return round(result)


# ── Public API ──

def predict_eta(job) -> float | None:
    """ETA with per-stage duration tracking + smooth display damping."""
    step = getattr(job, "step", None)
    if not step or step == "Complete":
        return 0

    job_id = getattr(job, "job_id", None)
    if not job_id:
        return None

    now = time.time()
    mode = getattr(job, "mode", "full") or "full"

    with LOCK:
        state = _JOB_ETA_STATE.get(job_id)

        if state is None:
            estimator = StageETA(mode=mode)
            damper = DisplayDamper()
            _JOB_ETA_STATE[job_id] = {
                "estimator": estimator,
                "damper": damper,
                "step": step,
            }
            state = _JOB_ETA_STATE[job_id]

        # Current progress — use stage position as floor
        progress = getattr(job, "progress", 0) or 0
        if step in STAGE_ORDER:
            idx = STAGE_ORDER.index(step)
            prev = STAGE_ORDER[idx - 1] if idx > 0 else None
            floor_pct = STAGE_ENDS.get(prev, 0) if prev else 0
            progress = max(progress, floor_pct)

        raw = state["estimator"].update(progress, now, step)
        stage_changed = step != state["step"]
        state["step"] = step
        return state["damper"].smooth(raw, now, stage_changed)


def interpolate_progress(job) -> int:
    """Smooth progress interpolation within the current stage.

    Uses per-stage expected durations to estimate how far through
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

        mode = getattr(job, "mode", "full") or "full"
        expected_stage_secs = max(_get_stage_expected(step, mode), 1.0)

        # Elapsed within this stage
        start_ts = dt.datetime.fromisoformat(job.stage_started_at)
        stage_elapsed = max((dt.datetime.now() - start_ts).total_seconds(), 0)

        if stage_elapsed < 0.3:
            frac = 0.02
        elif stage_elapsed >= expected_stage_secs:
            overshoot = stage_elapsed / expected_stage_secs
            frac = 0.90 + 0.05 * (1 - 1.0 / max(overshoot, 1.0))
            frac = min(frac, 0.95)
        else:
            frac = min(stage_elapsed / expected_stage_secs, 0.90)

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

    stage_history = getattr(job, "stage_history", []) or []
    with LOCK:
        for entry in stage_history:
            stage = entry.get("stage")
            duration = float(entry.get("duration") or 0)
            if not stage or duration < 0.5:
                continue
            if stage not in _HISTORY:
                _HISTORY[stage] = []
            _HISTORY[stage].append(round(duration, 1))
            if len(_HISTORY[stage]) > _MAX_HISTORY:
                _HISTORY[stage] = _HISTORY[stage][-_MAX_HISTORY:]
        _save_history()
