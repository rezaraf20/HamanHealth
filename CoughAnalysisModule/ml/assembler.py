#!/usr/bin/env python3
"""Python mirror of core-domain's detection chain.

This duplicates Kotlin, which is a real cost - but the alternative is tuning thresholds
against logic that differs from what ships, which is worse and fails silently. The
duplication is deliberately mechanical: every function here has a named counterpart,
and parity_fixture.py generates a fixture the Kotlin test suite replays to prove the
two still agree.

  NoiseFloorTracker  <- NoiseFloorTracker.kt
  smooth             <- ScoreSmoother.kt
  exclusion          <- DetectionPipeline.applyCoughSneezeExclusion
  assemble           <- EventAssembler.kt
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from frontend import CLASSES, HOP_MS, LOGGED

IDX = {c: i for i, c in enumerate(CLASSES)}

DEFAULT_PARAMS = {
    "COUGH":  dict(on=0.45, off=0.25, min_dur=600, merge_gap=720, refractory=250, max_dur=3000),
    "SNEEZE": dict(on=0.40, off=0.22, min_dur=600, merge_gap=960, refractory=500, max_dur=3000),
    "SNORE":  dict(on=0.35, off=0.20, min_dur=800, merge_gap=1500, refractory=500, max_dur=6000),
}

DEFAULTS = dict(
    gate_margin_db=6.0,
    speech_suppression=0.55,
    # Speech must be present in this many of the last `speech_window` frames to suppress
    # an onset. 1 reproduces the original single-frame rule, which blocked real voiced
    # coughs on-device (a cough can score 0.95 on Speech for one frame; talking is sustained).
    speech_sustain=4,
    speech_window=5,
    cough_sneeze_exclusion=0.20,
    # Sneeze must beat cough by this margin to win arbitration. Coughs are far more common
    # at night than sneezes, so a near-tie is more likely a cough.
    sneeze_margin=0.15,
    ema_alpha=0.5,
    # "ema": plain EMA. "attack_release": max(raw, ema) - an envelope follower that keeps a
    # peak intact on the frame it happens and only smooths the decay.
    smoothing="attack_release",
    cough_bout_gap_ms=3000,
)


@dataclass
class Event:
    cls: str
    start_ms: int
    end_ms: int
    peak_score: float
    mean_score: float
    peak_db: float
    snr_db: float
    peak_frame_ms: int


def noise_floor(rms: np.ndarray, window: int = 125, pct: float = 0.10) -> np.ndarray:
    """Rolling 10th-percentile floor. Mirrors NoiseFloorTracker.

    Uses the same integer index into the sorted window that Kotlin uses, NOT
    np.percentile: numpy interpolates between neighbouring samples and Kotlin does not,
    and that small difference moves enough frames across the gate threshold to change
    the event count. Caught by AssemblerParityTest.
    """
    out = np.empty(len(rms), dtype=np.float32)
    for i in range(len(rms)):
        lo = max(0, i - window + 1)
        w = np.sort(rms[lo:i + 1])
        k = int((len(w) - 1) * pct)
        out[i] = w[k]
    return out


def smooth(raw: np.ndarray, alpha: float, mode: str = "ema") -> np.ndarray:
    """EMA per class. Mirrors ScoreSmoother.

    There used to be a median-3 in front of this. It was removed because on real coughs
    it discarded 14-35% of detections YAMNet had actually made (a cough is short, and a
    median over three frames erases a peak that only one or two frames see). Single-frame
    spikes are rejected by minDurationMs instead, which does it without that cost.
    """
    n, k = raw.shape
    out = np.zeros_like(raw)
    ema = np.zeros(k, dtype=np.float32)
    for i in range(n):
        ema = raw[i] if i == 0 else alpha * raw[i] + (1 - alpha) * ema
        if mode == "attack_release":
            ema = np.maximum(raw[i], ema)
        out[i] = ema
    return out


def exclusion_threshold(params: dict, cfg: dict) -> float:
    """Arbitrate from the point either class could open an event.

    A fixed absolute threshold leaves a band below it where one class can open an
    unarbitrated event; mirrors the min() in DetectionPipeline.applyCoughSneezeExclusion.
    Classes absent from a partial sweep fall back to their defaults.
    """
    on_c = params.get("COUGH", DEFAULT_PARAMS["COUGH"])["on"]
    on_s = params.get("SNEEZE", DEFAULT_PARAMS["SNEEZE"])["on"]
    return min(cfg["cough_sneeze_exclusion"], on_c, on_s)


def apply_exclusion(sm: np.ndarray, thresh: float, margin: float = 0.0) -> np.ndarray:
    """Winner-take-all between cough and sneeze. Mirrors applyCoughSneezeExclusion."""
    out = sm.copy()
    c, s = IDX["COUGH"], IDX["SNEEZE"]
    both = (out[:, c] >= thresh) & (out[:, s] >= thresh)
    sneeze_wins = both & (out[:, s] >= out[:, c] + margin)
    cough_wins = both & ~sneeze_wins
    out[cough_wins, s] = 0.0
    out[sneeze_wins, c] = 0.0
    return out


def validate_params(params: dict, hop_ms: int = HOP_MS) -> dict:
    """Mirrors DetectorConfig.validatedFor: timings at or below one hop are inert."""
    out = {}
    for cls, p in params.items():
        q = dict(p)
        q["min_dur"] = max(q["min_dur"], hop_ms + 1)
        q["merge_gap"] = max(q["merge_gap"], hop_ms + 1)
        q.setdefault("max_dur", DEFAULT_PARAMS.get(cls, {}).get("max_dur", 3000))
        q["max_dur"] = max(q["max_dur"], q["min_dur"] + hop_ms)
        out[cls] = q
    return out


def prepare(scores: np.ndarray, rms: np.ndarray, cfg: dict = None) -> dict:
    """Everything that does not depend on the per-class thresholds.

    Split out so a threshold sweep does not recompute the noise floor and the smoother
    for every candidate - they are the expensive part and are threshold-independent.
    """
    cfg = {**DEFAULTS, **(cfg or {})}
    floor = noise_floor(rms)

    # NoiseFloorTracker.isWarmedUp is count >= windowFrames/4, and count is i+1,
    # so the floor is trusted from i = 30 onward. Before that the gate stays open
    # rather than risk gating away the start of a session.
    warm_frames = 125 // 4
    gate = np.array([((i + 1) < warm_frames) or (rms[i] > floor[i] + cfg["gate_margin_db"])
                     for i in range(len(rms))])

    # Order matters, and getting it wrong is invisible: on the phone a gated frame
    # never runs inference, so DetectionPipeline feeds ZEROS into the smoother, and
    # those zeros drag down the following frames' smoothed scores. Smoothing the raw
    # scores and masking afterwards produces different events. Caught by
    # AssemblerParityTest.
    gated = scores.copy()
    gated[~gate] = 0.0

    # Exclusion is applied per-candidate in assemble_prepared, not here: its threshold
    # depends on the on-thresholds being swept. SPEECH is unaffected by it, so the
    # speech mask can still be precomputed.
    sm = smooth(gated, cfg["ema_alpha"], cfg["smoothing"])
    flags = (sm[:, IDX["SPEECH"]] >= cfg["speech_suppression"]).astype(np.int32)
    w = cfg["speech_window"]
    csum = np.concatenate([[0], np.cumsum(flags)])
    recent = np.array([csum[i + 1] - csum[max(0, i + 1 - w)] for i in range(len(flags))])
    speech = recent >= cfg["speech_sustain"]
    return dict(sm=sm, floor=floor, rms=rms, gate=gate, speech=speech, cfg=cfg)


def assemble(
    scores: np.ndarray,
    rms: np.ndarray,
    params: dict,
    cfg: dict = None,
    hop_ms: int = HOP_MS,
    t0: int = 0,
) -> list[Event]:
    """Hysteresis state machine. Mirrors EventAssembler.process/close."""
    return assemble_prepared(prepare(scores, rms, cfg), params, hop_ms, t0)


def assemble_prepared(prep: dict, params: dict, hop_ms: int = HOP_MS, t0: int = 0) -> list[Event]:
    cfg = prep["cfg"]
    params = validate_params(params, hop_ms)
    sm = apply_exclusion(prep["sm"], exclusion_threshold(params, cfg), cfg["sneeze_margin"])
    floor, rms = prep["floor"], prep["rms"]
    gate_arr, speech_arr = prep["gate"], prep["speech"]

    events: list[Event] = []
    state = {c: dict(active=False, refractory_until=-1) for c in params}

    for i in range(len(sm)):
        ts = t0 + i * hop_ms
        gate_open = bool(gate_arr[i])
        speech_active = bool(speech_arr[i])

        for cls, p in params.items():
            st = state[cls]
            v = sm[i, IDX[cls]]  # already zeroed upstream when gated

            if st["active"]:
                if v >= p["off"]:
                    st["last_above"] = ts
                    if v > st["peak"]:
                        st["peak"] = float(v)
                        st["peak_frame"] = ts
                    st["peak_db"] = max(st["peak_db"], float(rms[i]))
                    st["sum"] += float(v)
                    st["n"] += 1
                gap_closed = ts - st["last_above"] >= p["merge_gap"]
                too_long = ts - st["start"] >= p["max_dur"]
                if gap_closed or too_long:
                    end_ms = min(st["last_above"] + hop_ms, st["start"] + p["max_dur"])
                    if end_ms - st["start"] >= p["min_dur"]:
                        events.append(Event(
                            cls=cls, start_ms=st["start"], end_ms=end_ms,
                            peak_score=st["peak"],
                            mean_score=st["sum"] / max(st["n"], 1),
                            peak_db=st["peak_db"],
                            snr_db=st["peak_db"] - st["floor_at_start"],
                            peak_frame_ms=st["peak_frame"],
                        ))
                        st["refractory_until"] = ts + p["refractory"]
                    st["active"] = False
            else:
                if (ts >= st["refractory_until"] and gate_open
                        and not speech_active and v >= p["on"]):
                    st.update(active=True, start=ts, last_above=ts, peak=float(v),
                              peak_frame=ts, peak_db=float(rms[i]), sum=float(v), n=1,
                              floor_at_start=float(floor[i]))

    # flush
    end_ts = t0 + len(sm) * hop_ms
    for cls, st in state.items():
        if st["active"]:
            p = params[cls]
            end_ms = min(st["last_above"] + hop_ms, st["start"] + p["max_dur"])
            if end_ms - st["start"] >= p["min_dur"]:
                events.append(Event(
                    cls=cls, start_ms=st["start"], end_ms=end_ms, peak_score=st["peak"],
                    mean_score=st["sum"] / max(st["n"], 1), peak_db=st["peak_db"],
                    snr_db=st["peak_db"] - st["floor_at_start"], peak_frame_ms=st["peak_frame"],
                ))
    return sorted(events, key=lambda e: e.start_ms)


def match(pred: list[Event], truth: list[dict], tolerance_ms: int = 1500):
    """Overlap-based scoring, per class.

    Recall  = fraction of ground-truth regions touched by at least one prediction.
    FP      = predictions that touch no ground-truth region of their class.

    One-to-one matching was replaced because a real cough recording often holds a bout
    of several coughs in one ground-truth region; one-to-one scoring counted every cough
    after the first as a false alarm and so tuned the detector to under-report bouts.
    """
    results = {}
    for cls in LOGGED:
        p = [e for e in pred if e.cls == cls]
        t = [g for g in truth if g["cls"] == cls]
        hit = set()
        tp_pred = 0
        for e in p:
            touched = [j for j, g in enumerate(t)
                       if e.end_ms >= g["start_ms"] - tolerance_ms
                       and e.start_ms <= g["end_ms"] + tolerance_ms]
            if touched:
                tp_pred += 1
                hit.update(touched)
        results[cls] = dict(tp=len(hit), fp=len(p) - tp_pred, fn=len(t) - len(hit),
                            tp_pred=tp_pred, n_pred=len(p), n_true=len(t))
    return results
