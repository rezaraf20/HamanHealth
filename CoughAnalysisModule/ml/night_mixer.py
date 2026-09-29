#!/usr/bin/env python3
"""Synthesise nights with exact ground truth, then cache their model scores.

Clip-level metrics cannot predict overnight behaviour: what matters is how many false
events accumulate over hours of mostly-silence, which depends on the event assembler,
not the classifier. Annotated real nights do not exist here, so nights are built from
real recordings mixed into room noise at known times.

Coughs come mainly from COUGHVID - real users' own phones - rather than ESC-50. The
first version used ESC-50 only; its cough clips are clean, loud, multi-cough bouts, and
thresholds tuned on them missed most real single coughs on budget phones. Placed
events span a wide level range (0 to -28 dB) because level is the dominant factor in
YAMNet's recall (results/recall_diagnosis.json).

COUGHVID is split deterministically: split 0 is held out for diagnose_recall.py so the
reported recall is not measured on tuning data.

Scores are cached twice - with and without input normalisation - so the effect of
normalisation on false alarms can be measured on identical audio.
"""
from __future__ import annotations

import argparse
import json
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf

from frontend import (ROOT, SAMPLE_RATE, frame_audio, load_interpreter, normalise,
                      reduce_scores, rms_db, run_frames)

DISTRACTORS = [
    "breathing", "drinking_sipping", "insects", "clock_tick", "clock_alarm",
    "door_wood_knock", "mouse_click", "keyboard_typing", "wind", "rain",
    "toilet_flush", "water_drops", "footsteps", "laughing", "crying_baby",
    "vacuum_cleaner", "washing_machine", "car_horn", "siren", "crickets",
    "dog", "cat", "door_wood_creaks", "sneezing_decoy",
]
# Placement levels relative to a -6 dBFS-peak source, and their probabilities.
# Skewed quiet on purpose: a nightstand phone rarely hears a cough at full scale.
LEVELS_DB = [0, -8, -15, -22, -28]
LEVEL_P = [0.15, 0.2, 0.3, 0.2, 0.15]


def coughvid_split(name: str) -> int:
    return zlib.crc32(name.encode()) % 5


def coughvid_files(split_held_out: bool, min_conf: float = 0.9):
    root = ROOT / "Datasets/COUGHVID"
    out = []
    for js in sorted(root.glob("*.json")):
        wav = js.with_suffix(".wav")
        if not wav.exists():
            continue
        if (coughvid_split(wav.name) == 0) != split_held_out:
            continue
        if float(json.loads(js.read_text()).get("cough_detected", 0)) >= min_conf:
            out.append(wav)
    return out


def load_16k(path: Path) -> np.ndarray:
    import librosa
    a, sr = sf.read(path, dtype="float32", always_2d=False)
    if a.ndim > 1:
        a = a.mean(axis=1)
    if sr != SAMPLE_RATE:
        a = librosa.resample(a, orig_sr=sr, target_sr=SAMPLE_RATE)
    return a


def trim(a: np.ndarray, rel_db: float = -30.0) -> np.ndarray:
    """Keep the active part, relative to the clip's own peak."""
    win = 512
    frames = len(a) // win
    if frames < 2:
        return a
    e = np.array([rms_db(a[i * win:(i + 1) * win]) for i in range(frames)])
    active = np.where(e > e.max() + rel_db)[0]
    if len(active) == 0:
        return a
    return a[active[0] * win: min(len(a), (active[-1] + 1) * win)]


def lowpass(a, cutoff):
    from scipy.signal import butter, sosfilt
    return sosfilt(butter(4, cutoff, fs=SAMPLE_RATE, output="sos"), a).astype(np.float32)


def room_noise(n, level_db, rng):
    b = np.cumsum(rng.standard_normal(n)).astype(np.float32)
    b -= b.mean()
    b /= np.sqrt(np.mean(b ** 2)) + 1e-9
    return b * 10 ** (level_db / 20)


def build_night(meta, audio_dir, cv_files, minutes, seed, floor_db):
    rng = np.random.default_rng(seed)
    n = int(minutes * 60 * SAMPLE_RATE)
    night = room_noise(n, floor_db, rng)
    truth = []
    dur_s = minutes * 60

    def esc(cat):
        files = meta[meta.category == cat].filename.tolist()
        return audio_dir / rng.choice(files) if files else None

    def place(path, cls, t_s, level_db):
        if path is None:
            return
        clip = trim(load_16k(path))
        clip = clip / (np.abs(clip).max() + 1e-9) * 0.5          # peak -6 dBFS
        clip = clip * 10 ** (level_db / 20)
        if level_db <= -20:
            clip = lowpass(clip, 5500)                             # distance roll-off
        start = int(t_s * SAMPLE_RATE)
        end = min(n, start + len(clip))
        if end <= start:
            return
        night[start:end] += clip[: end - start]
        if cls:
            truth.append(dict(cls=cls, start_ms=int(t_s * 1000),
                              end_ms=int(end / SAMPLE_RATE * 1000), level_db=float(level_db)))

    level = lambda: float(rng.choice(LEVELS_DB, p=LEVEL_P))

    for _ in range(int(dur_s / 3600 * 30)):
        src = rng.choice(cv_files) if rng.random() < 0.7 else esc("coughing")
        place(src, "COUGH", rng.uniform(0, dur_s - 12), level())

    for _ in range(max(1, int(dur_s / 3600 * 6))):
        place(esc("sneezing"), "SNEEZE", rng.uniform(0, dur_s - 4), level())

    for _ in range(max(1, int(dur_s / 3600 * 3))):
        ep_start = rng.uniform(0, max(1.0, dur_s - 400))
        ep_level = float(rng.choice([0, -8, -15]))
        t = ep_start
        while t < min(ep_start + rng.uniform(120, 360), dur_s - 4):
            place(esc("snoring"), "SNORE", t, ep_level)
            t += rng.uniform(3.0, 6.0)

    for _ in range(int(dur_s / 3600 * 40)):
        cat = str(rng.choice([d for d in DISTRACTORS if d != "sneezing_decoy"]))
        place(esc(cat), None, rng.uniform(0, dur_s - 5), float(rng.uniform(-25, -3)))

    peak = np.abs(night).max()
    if peak > 0.98:
        night *= 0.98 / peak
    return night, sorted(truth, key=lambda x: x["start_ms"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nights", type=int, default=6)
    ap.add_argument("--minutes", type=int, default=30)
    ap.add_argument("--floor-db", type=float, default=-62.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=ROOT / "ml/artifacts/nights.npz")
    args = ap.parse_args()

    meta = pd.read_csv(ROOT / "Datasets/ESC-50-master/meta/esc50.csv")
    audio_dir = ROOT / "Datasets/ESC-50-master/audio"
    cv_files = coughvid_files(split_held_out=False)
    print(f"{len(cv_files)} COUGHVID tuning recordings (held-out split excluded)")
    interp = load_interpreter()

    S, SN, R, T, L = [], [], [], [], []
    for i in range(args.nights):
        print(f"night {i + 1}/{args.nights} ...")
        night, truth = build_night(meta, audio_dir, cv_files, args.minutes,
                                   args.seed + i, args.floor_db)
        frames = frame_audio(night)
        raw, _ = run_frames(*interp, frames)
        raw_n, _ = run_frames(*interp, normalise(frames))
        S.append(reduce_scores(raw)); SN.append(reduce_scores(raw_n))
        R.append(np.array([rms_db(f) for f in frames], dtype=np.float32))
        T.append(json.dumps(truth)); L.append(len(frames))
        print(f"  {len(frames)} frames, {len(truth)} events "
              f"({sum(t['cls']=='COUGH' for t in truth)} coughs)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, scores=np.concatenate(S), scores_norm=np.concatenate(SN),
                        rms=np.concatenate(R), lengths=np.array(L),
                        truth=np.array(T, dtype=object), minutes=args.minutes)
    print(f"wrote {args.out} ({args.nights * args.minutes / 60:.1f} h)")


if __name__ == "__main__":
    main()
