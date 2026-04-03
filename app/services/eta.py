"""ETA prediction v7 — Kalman-filter pace tracking with stage-aware blending.

Replaces the v6 static progress-to-time mapping with a 1D Kalman filter
that tracks the live "seconds per progress-percent" pace.  This adapts
in real-time as stages complete faster or slower than expected.

Three layers:
1. PaceKalman     — 1D Kalman filter on observed pace (s/%)
2. StageAwareETA  — blends Kalman estimate with historical priors
3. DisplayDamper  — smooth monotonic countdown with proportional corrections

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
    "Analysis", "Valuation", "Peers", "Drafting", "Rendering", "Complete",
]

STAGE_ENDS = {
    "Starting": 5, "Company Info": 10, "Data Fetch": 25, "Extraction": 35,
    "Analysis": 45, "Valuation": 55, "Peers": 60, "Drafting": 90,
    "Rendering": 100, "Complete": 100,
}

# ── Progress-to-time mapping (used for historical fallback + interpolation) ──
_PROGRESS_TIME = [
    (0,   0.00),
    (5,   0.02),
    (10,  0.05),
    (25,  0.18),
    (35,  0.22),
    (45,  0.25),
    (55,  0.55),
    (60,  0.70),
    (90,  0.90),
    (100, 1.00),
]

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


# ── Layer 1: 1D Kalman Filter on Pace ──

class PaceKalman:
    """1D Kalman filter tracking 'seconds per progress-percent'.

    State: x = pace (s/%)
    Simple constant-velocity model (pace assumed roughly constant between updates).
    Adapts quickly to actual run speed via Kalman gain.
    """

    def __init__(self, initial_pace: float, process_noise: float = 0.5,
                 measurement_noise: float = 2.0):
        self.x = initial_pace
        self.P = 10.0           # initial uncertainty (high = trust measurements early)
        self.Q = process_noise  # how much pace can change between updates
        self.R = measurement_noise  # how noisy each measurement is

    def update(self, measured_pace: float) -> float:
        # Predict step (constant model: pace stays the same)
        P_pred = self.P + self.Q

        # Update step
        K = P_pred / (P_pred + self.R)  # Kalman gain
        self.x = self.x + K * (measured_pace - self.x)
        self.P = (1 - K) * P_pred

        return self.x

    @property
    def pace(self) -> float:
        return max(self.x, 0.01)

    @property
    def confidence(self) -> float:
        """0..1, higher = more confident."""
        return max(0.0, 1.0 - self.P / (self.P + 5.0))


# ── Layer 2: Stage-Aware ETA Computation ──

class StageAwareETA:
    """Combines Kalman-filtered pace with historical priors.

    For early observations (<3), blends heavily with historical.
    Once the Kalman filter has enough data, trusts live pace.
    """

    def __init__(self, mode: str = "full"):
        self.mode = mode
        hist_total = _get_expected_total(mode)
        initial_pace = hist_total / 100.0  # seconds per percent

        self.kalman = PaceKalman(
            initial_pace=initial_pace,
            process_noise=0.3,
            measurement_noise=1.5,
        )
        self.last_progress = 0.0
        self.last_time = None
        self.last_progress_time = None  # when progress last changed
        self.update_count = 0
        self.job_start_time = None

    def update(self, progress: float, current_time: float, step: str) -> float:
        """Feed new observation, return raw ETA in seconds."""
        if self.last_time is None:
            self.last_time = current_time
            self.last_progress = progress
            self.last_progress_time = current_time
            self.job_start_time = current_time
            return self._historical_eta(progress)

        dp = progress - self.last_progress
        dt_sec = current_time - self.last_time

        # Track when progress last changed (for stall detection)
        if dp > 0.5:
            self.last_progress_time = current_time

        # Only update Kalman when we have meaningful progress delta
        if dp > 0.5 and dt_sec > 0.1:
            measured_pace = dt_sec / dp
            measured_pace = max(0.05, min(measured_pace, 30.0))
            self.kalman.update(measured_pace)
            self.update_count += 1
            self.last_progress = progress
            self.last_time = current_time

        remaining_pct = max(100.0 - progress, 0.0)

        # Stall detection: if no progress for >3s, the Kalman pace is
        # likely too optimistic. Blend in an elapsed-based correction.
        stall_secs = current_time - (self.last_progress_time or current_time)
        stall_boost = 0.0
        if stall_secs > 3.0 and remaining_pct > 1:
            # The longer we stall, the more we should distrust the fast pace
            # Inject the stall duration as additional time remaining
            stall_boost = stall_secs * 0.5  # half of stall time as buffer

        # For very early run, blend with historical
        if self.update_count < 3:
            kalman_eta = remaining_pct * self.kalman.pace
            hist_eta = self._historical_eta(progress)
            w = self.update_count / 3.0
            raw = (1 - w) * hist_eta + w * kalman_eta
        else:
            kalman_eta = remaining_pct * self.kalman.pace
            hist_eta = self._historical_eta(progress)
            raw = 0.1 * hist_eta + 0.9 * kalman_eta

        # Apply stall correction: ensure ETA is at least the stall boost
        raw = max(raw, stall_boost)

        # Also use total-elapsed sanity check: if we've used X% of expected
        # time but only made Y% progress, adjust upward
        if self.job_start_time:
            total_elapsed = current_time - self.job_start_time
            time_frac = _progress_to_time_frac(progress)
            if time_frac > 0.05 and total_elapsed > 5:
                elapsed_projection = total_elapsed / time_frac * (1 - time_frac)
                # Take the max of Kalman estimate and elapsed projection,
                # weighted toward whichever is larger (pessimistic = safer)
                raw = max(raw, elapsed_projection * 0.4)

        return max(2.0, min(raw, 600.0))

    def _historical_eta(self, progress: float) -> float:
        """Fallback: total_expected * (1 - time_fraction)."""
        total = _get_expected_total(self.mode)
        time_frac = _progress_to_time_frac(progress)
        return total * (1.0 - time_frac)


# ── Layer 3: Display Damper ──

class DisplayDamper:
    """Smooth ETA for display with proportional corrections.

    Ticks down naturally at ~1s/s.
    Downward corrections: fast (users love seeing ETA shrink).
    Upward corrections: proportional, not fixed-cap (handles big stalls).
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

        if raw_eta <= expected:
            # Ahead of schedule — fast drop (60% toward raw each update)
            result = 0.4 * expected + 0.6 * raw_eta
        elif stage_changed:
            # Stage boundary — allow larger proportional correction
            delta = raw_eta - expected
            result = expected + min(delta, max(delta * 0.5, 8.0))
        else:
            # Behind within same stage — proportional but bounded
            delta = raw_eta - expected
            correction = min(delta * 0.25, max(expected * 0.25, 4.0))
            result = expected + correction

        # Floor: if raw says work remains (>3s), don't show 1s
        if raw_eta > 3.0:
            result = max(result, 3.0)

        result = max(1.0, min(result, 600.0))
        self.displayed_eta = result
        return round(result)


# ── Public API ──

def predict_eta(job) -> float | None:
    """ETA with Kalman-filtered pace tracking + smooth display damping."""
    step = getattr(job, "step", None)
    if not step or step == "Complete":
        return 0

    job_id = getattr(job, "job_id", None)
    if not job_id:
        return None

    now = time.time()
    mode = getattr(job, "mode", "full") or "full"

    # Current progress — use stage position as floor
    progress = getattr(job, "progress", 0) or 0
    if step in STAGE_ORDER:
        idx = STAGE_ORDER.index(step)
        prev = STAGE_ORDER[idx - 1] if idx > 0 else None
        floor_pct = STAGE_ENDS.get(prev, 0) if prev else 0
        progress = max(progress, floor_pct)

    with LOCK:
        state = _JOB_ETA_STATE.get(job_id)

        if state is None:
            estimator = StageAwareETA(mode=mode)
            damper = DisplayDamper()
            _JOB_ETA_STATE[job_id] = {
                "estimator": estimator,
                "damper": damper,
                "step": step,
            }
            state = _JOB_ETA_STATE[job_id]

        raw = state["estimator"].update(progress, now, step)
        stage_changed = step != state["step"]
        state["step"] = step
        return state["damper"].smooth(raw, now, stage_changed)


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

        mode = getattr(job, "mode", "full") or "full"
        expected_total = _get_expected_total(mode)

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
            if not stage or duration <= 0:
                continue
            if stage not in _HISTORY:
                _HISTORY[stage] = []
            _HISTORY[stage].append(round(duration, 1))
            if len(_HISTORY[stage]) > _MAX_HISTORY:
                _HISTORY[stage] = _HISTORY[stage][-_MAX_HISTORY:]
        _save_history()
