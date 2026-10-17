#!/usr/bin/env python3
"""Can YAMNet actually hear these three sounds?

ESC-50 contains exactly the classes this product needs - coughing, sneezing, snoring,
breathing - at 40 clips each, plus 46 other categories that double as realistic
bedroom false-positive sources (clock alarm, door knock, vacuum, washing machine).

This is clip-level, which is NOT the number that predicts overnight behaviour (see
eval_night.py for that). It answers the prior question: is the backbone capable at all.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf
from sklearn.metrics import average_precision_score, roc_auc_score

from frontend import (CLASSES, LOGGED, ROOT, SAMPLE_RATE, frame_audio,
                      load_interpreter, reduce_scores, run_frames)

# ESC-50 category -> our class
POSITIVE = {"coughing": "COUGH", "sneezing": "SNEEZE", "snoring": "SNORE"}


def load_16k(path: Path) -> np.ndarray:
    import librosa
    audio, sr = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SAMPLE_RATE:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=SAMPLE_RATE)
    return audio


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="clips per category (0 = all)")
    ap.add_argument("--out", type=Path, default=ROOT / "results/esc50_yamnet.json")
    args = ap.parse_args()

    meta = pd.read_csv(ROOT / "Datasets/ESC-50-master/meta/esc50.csv")
    audio_dir = ROOT / "Datasets/ESC-50-master/audio"
    if args.limit:
        meta = meta.groupby("category", group_keys=False).head(args.limit)

    interp, in_idx, sc_idx, em_idx = load_interpreter()

    rows = []
    for n, row in enumerate(meta.itertuples(), 1):
        audio = load_16k(audio_dir / row.filename)
        frames = frame_audio(audio)
        raw, _ = run_frames(interp, in_idx, sc_idx, em_idx, frames)
        red = reduce_scores(raw)
        # Clip-level score = max over frames, matching how the benchmark scored clips.
        peak = red.max(axis=0)
        rows.append({"category": row.category, **{c: float(peak[i]) for i, c in enumerate(CLASSES)}})
        if n % 200 == 0:
            print(f"  {n}/{len(meta)} clips")

    df = pd.DataFrame(rows)
    report = {"clips": len(df), "per_class": {}}

    print(f"\n{'class':8} {'ROC-AUC':>8} {'AP':>8} {'median+':>8} {'p95-':>8}  top false positives")
    print("-" * 92)
    for cat, cls in POSITIVE.items():
        y = (df["category"] == cat).astype(int).values
        s = df[cls].values
        auc = roc_auc_score(y, s)
        ap_score = average_precision_score(y, s)
        med_pos = float(np.median(s[y == 1]))
        p95_neg = float(np.percentile(s[y == 0], 95))

        neg = df[df["category"] != cat].groupby("category")[cls].max().sort_values(ascending=False)
        worst = ", ".join(f"{k}({v:.2f})" for k, v in neg.head(3).items())

        report["per_class"][cls] = {
            "esc50_category": cat, "roc_auc": float(auc), "average_precision": float(ap_score),
            "median_positive_score": med_pos, "p95_negative_score": p95_neg,
            "top_false_positive_categories": {k: float(v) for k, v in neg.head(5).items()},
        }
        print(f"{cls:8} {auc:8.3f} {ap_score:8.3f} {med_pos:8.2f} {p95_neg:8.2f}  {worst}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
