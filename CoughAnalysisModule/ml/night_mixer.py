#!/usr/bin/env python3
"""Synthesise nights with exact ground truth, then cache their model scores.

Clip-level metrics (eval_esc50.py) cannot predict overnight behaviour: what matters is
how many false events accumulate over 8 hours of mostly-silence, and that depends on
the event assembler, not the classifier. Real annotated night recordings do not exist
here, so nights are built from ESC-50 events mixed into room noise at known times.

Scores are computed once and cached to .npz so threshold sweeps are pure numpy and
cost nothing - retuning does not mean re-running the model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf

from frontend import (ROOT, SAMPLE_RATE, frame_audio, load_interpreter,
                      reduce_scores, rms_db, run_frames, HOP_SAMPLES, FRAME_SAMPLES)

TARGET = {"coughing": "COUGH", "sneezing": "SNEEZE", "snoring": "SNORE"}

# Categories that plausibly occur in or near a bedroom at night. Chosen deliberately to
# include the confusions eval_esc50.py surfaced (breathing, drinking, insects) rather
# than easy negatives, so the tuned thresholds are tested against the hard cases.
DISTRACTORS = [
    "breathing", "drinking_sipping", "insects", "clock_tick", "clock_alarm",
    "door_wood_knock", "mouse_click", "keyboard_typing", "wind", "rain",
    "toilet_flush", "water_drops", "footsteps", "laughing", "crying_baby",
    "vacuum_cleaner", "washing_machine", "car_horn", "siren", "crickets",
]


def load_16k(path: Path) -> np.ndarray:
    import librosa
    a, sr = sf.read(path, dtype="float32", always_2d=False)
    if a.ndim > 1:
        a = a.mean(axis=1)
    if sr != SAMPLE_RATE:
        a = librosa.resample(a, orig_sr=sr, target_sr=SAMPLE_RATE)
    return a


def trim(a: np.ndarray, thresh_db: float = -45.0) -> np.ndarray:
    """ESC-50 clips are 5 s with the event somewhere inside; keep the active part so
    placement timing means something."""
    win = 512
    if len(a) < win * 2:
        return a
    frames = len(a) // win
    e = np.array([rms_db(a[i * win:(i + 1) * win]) for i in range(frames)])
    active = np.where(e > thresh_db)[0]
    if len(active) == 0:
        return a
    return a[active[0] * win: min(len(a), (active[-1] + 1) * win)]


def attenuate(a: np.ndarray, distance_m: float, rng) -> np.ndarray:
    """Crude but directionally correct distance model.

    Two effects that matter for the proximity prior: inverse-square level loss, and
    high-frequency roll-off, since air and bedding absorb treble faster than bass. A
    convolutional room impulse response would be better but needs data we do not have.
    """
    gain = 1.0 / max(distance_m, 0.3) ** 1.0
    out = a * gain
    if distance_m > 1.0:
        # One-pole lowpass; stronger with distance.
        alpha = np.clip(0.45 / distance_m, 0.05, 0.45)
        y = np.zeros_like(out)
        acc = 0.0
        for i in range(len(out)):
            acc = alpha * out[i] + (1 - alpha) * acc
            y[i] = acc
        out = y * 1.6
    return out.astype(np.float32)


def room_noise(n: int, level_db: float, rng) -> np.ndarray:
    """Brown-ish noise: a bedroom floor is low-frequency dominated (traffic, HVAC)."""
    white = rng.standard_normal(n).astype(np.float32)
    brown = np.cumsum(white)
    brown -= brown.mean()
    brown /= (np.abs(brown).max() + 1e-9)
    target = 10 ** (level_db / 20.0)
    rms = np.sqrt(np.mean(brown ** 2)) + 1e-9
    return (brown * (target / rms)).astype(np.float32)


def build_night(meta, audio_dir, minutes, seed, floor_db):
    rng = np.random.default_rng(seed)
    n = int(minutes * 60 * SAMPLE_RATE)
    night = room_noise(n, floor_db, rng)
    truth = []

    pool = {}
    for cat in list(TARGET) + DISTRACTORS:
        files = meta[meta.category == cat].filename.tolist()
        if files:
            pool[cat] = files

    def place(cat, cls, t_s, distance):
        files = pool.get(cat)
        if not files:
            return
        clip = trim(load_16k(audio_dir / rng.choice(files)))
        clip = attenuate(clip, distance, rng)
        start = int(t_s * SAMPLE_RATE)
        end = min(n, start + len(clip))
        if end <= start:
            return
        night[start:end] += clip[: end - start]
        if cls:
            truth.append({
                "cls": cls,
                "start_ms": int(t_s * 1000),
                "end_ms": int((end / SAMPLE_RATE) * 1000),
                "distance_m": float(distance),
            })

    dur_s = minutes * 60

    # Coughs: mostly near (the phone's owner), some far (a partner across the bed).
    for _ in range(max(1, int(dur_s / 3600 * 10))):
        place("coughing", "COUGH", rng.uniform(0, dur_s - 3),
              rng.choice([0.5, 0.7, 1.0, 2.5, 3.0], p=[0.3, 0.25, 0.2, 0.15, 0.1]))

    for _ in range(max(1, int(dur_s / 3600 * 2))):
        place("sneezing", "SNEEZE", rng.uniform(0, dur_s - 3),
              rng.choice([0.5, 0.8, 2.5], p=[0.5, 0.3, 0.2]))

    # Snoring arrives in episodes, not uniformly: a run of breaths every few seconds.
    n_episodes = max(1, int(dur_s / 3600 * 3))
    for _ in range(n_episodes):
        ep_start = rng.uniform(0, max(1.0, dur_s - 400))
        ep_len = rng.uniform(120, 360)
        t = ep_start
        while t < min(ep_start + ep_len, dur_s - 3):
            place("snoring", "SNORE", t, rng.choice([0.6, 0.9]))
            t += rng.uniform(3.0, 6.0)

    # Distractors: the false-positive pressure the thresholds must survive.
    for _ in range(max(1, int(dur_s / 3600 * 40))):
        place(str(rng.choice(DISTRACTORS)), None, rng.uniform(0, dur_s - 3),
              rng.uniform(0.8, 3.0))

    peak = np.abs(night).max()
    if peak > 0.98:
        night *= 0.98 / peak
    return night, sorted(truth, key=lambda x: x["start_ms"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nights", type=int, default=6)
    ap.add_argument("--minutes", type=int, default=30)
    ap.add_argument("--floor-db", type=float, default=-62.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=ROOT / "ml/artifacts/nights.npz")
    args = ap.parse_args()

    meta = pd.read_csv(ROOT / "Datasets/ESC-50-master/meta/esc50.csv")
    audio_dir = ROOT / "Datasets/ESC-50-master/audio"
    interp, in_idx, sc_idx, em_idx = load_interpreter()

    all_scores, all_rms, all_truth, night_index = [], [], [], []
    for i in range(args.nights):
        print(f"night {i + 1}/{args.nights}: mixing {args.minutes} min ...")
        night, truth = build_night(meta, audio_dir, args.minutes, args.seed + i, args.floor_db)
        frames = frame_audio(night)
        print(f"  {len(frames)} frames, {len(truth)} ground-truth events; scoring ...")
        raw, _ = run_frames(interp, in_idx, sc_idx, em_idx, frames)
        red = reduce_scores(raw)
        rms = np.array([rms_db(f) for f in frames], dtype=np.float32)

        all_scores.append(red)
        all_rms.append(rms)
        all_truth.append(json.dumps(truth))
        night_index.append(len(frames))
        del night, frames, raw

    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.out,
        scores=np.concatenate(all_scores),
        rms=np.concatenate(all_rms),
        lengths=np.array(night_index),
        truth=np.array(all_truth, dtype=object),
        minutes=args.minutes,
        allow_pickle=True,
    )
    total_h = args.nights * args.minutes / 60
    print(f"\nwrote {args.out}  ({total_h:.1f} hours of scored night audio)")


if __name__ == "__main__":
    main()
