#!/usr/bin/env python3
"""Event-level metrics over synthetic nights, with false alarms per hour as the headline.

FA/hour is the number that decides whether this product is usable. A detector at 95%
clip precision can still emit 40 phantom coughs a night, and a log nobody trusts is
worse than no log. Target: under 1 false alarm per hour per class.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from assembler import DEFAULT_PARAMS, DEFAULTS, assemble, match
from frontend import HOP_MS, LOGGED, ROOT


def load_nights(path: Path):
    d = np.load(path, allow_pickle=True)
    scores, rms, lengths = d["scores"], d["rms"], d["lengths"]
    truths = [json.loads(t) for t in d["truth"]]
    nights, off = [], 0
    for n, ln in enumerate(lengths):
        nights.append((scores[off:off + ln], rms[off:off + ln], truths[n]))
        off += ln
    return nights, float(d["minutes"])


def evaluate(nights, params, cfg=None, verbose=False):
    totals = {c: dict(tp=0, fp=0, fn=0, n_pred=0, n_true=0) for c in LOGGED}
    hours = 0.0
    for scores, rms, truth in nights:
        pred = assemble(scores, rms, params, cfg)
        res = match(pred, truth)
        for c in LOGGED:
            for k in totals[c]:
                totals[c][k] += res[c][k]
        hours += len(scores) * HOP_MS / 3_600_000

    report = {"hours": hours, "per_class": {}}
    for c in LOGGED:
        t = totals[c]
        prec = t["tp"] / t["n_pred"] if t["n_pred"] else 0.0
        rec = t["tp"] / t["n_true"] if t["n_true"] else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        report["per_class"][c] = dict(
            precision=prec, recall=rec, f1=f1,
            fa_per_hour=t["fp"] / hours if hours else 0.0,
            misses_per_hour=t["fn"] / hours if hours else 0.0,
            **t,
        )
    return report


def print_report(r, title="event-level"):
    print(f"\n{title} over {r['hours']:.1f} hours")
    print(f"{'class':8} {'prec':>6} {'recall':>7} {'F1':>6} {'FA/h':>7} {'miss/h':>7} "
          f"{'TP':>5} {'FP':>5} {'FN':>5}")
    print("-" * 70)
    for c, m in r["per_class"].items():
        print(f"{c:8} {m['precision']:6.3f} {m['recall']:7.3f} {m['f1']:6.3f} "
              f"{m['fa_per_hour']:7.2f} {m['misses_per_hour']:7.2f} "
              f"{m['tp']:5d} {m['fp']:5d} {m['fn']:5d}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--nights", type=Path, default=ROOT / "ml/artifacts/nights.npz")
    ap.add_argument("--config", type=Path, default=None,
                    help="tuned detector_config.json; defaults to the built-in parameters")
    args = ap.parse_args()

    nights, minutes = load_nights(args.nights)
    params = DEFAULT_PARAMS
    if args.config and args.config.exists():
        cfg = json.loads(args.config.read_text())
        params = {k: dict(on=v["onThreshold"], off=v["offThreshold"],
                          min_dur=v["minDurationMs"], merge_gap=v["mergeGapMs"], max_dur=v.get("maxDurationMs", 3000),
                          refractory=v["refractoryMs"])
                  for k, v in cfg["params"].items() if k in LOGGED}
    print_report(evaluate(nights, params), "default parameters" if not args.config else "tuned")
