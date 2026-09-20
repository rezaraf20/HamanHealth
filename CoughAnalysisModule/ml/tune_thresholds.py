#!/usr/bin/env python3
"""Choose detection parameters against night-shaped audio, then emit the app's config.

The objective is not F1. It is: maximise recall subject to a false-alarm budget. A
sleep log is read once in the morning and trusted or not, and phantom events destroy
that trust far faster than missed ones - but a detector that finds a third of the real
events is also useless, which is where the default parameters landed.

Writes detector_config.json in the exact shape DetectorConfig.fromJson expects, so it
drops straight into the app's assets.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from assembler import DEFAULT_PARAMS, assemble_prepared, match, prepare
from eval_night import evaluate, load_nights, print_report
from frontend import HOP_MS, LOGGED, ROOT

# Below this, ambient room noise sustains an event indefinitely.
MIN_OFF_THRESHOLD = 0.12


def sweep_class(preps, truths, cls, budget, grid):
    """Best parameters for one class under the FA/hour budget."""
    hours = sum(len(p["sm"]) for p in preps) * HOP_MS / 3_600_000
    best = None
    frontier = []

    for on in grid["on"]:
        for ratio in grid["off_ratio"]:
            # Floor the off-threshold. The unconstrained sweep chose 0.04, which room
            # noise alone exceeds, so every event ran to its ceiling.
            off = round(max(on * ratio, MIN_OFF_THRESHOLD), 3)
            if off >= on:
                continue
            for min_dur in grid["min_dur"]:
                for merge_gap in grid["merge_gap"]:
                    params = {cls: dict(on=on, off=off, min_dur=min_dur,
                                        merge_gap=merge_gap,
                                        refractory=DEFAULT_PARAMS[cls]["refractory"],
                                        max_dur=DEFAULT_PARAMS[cls]["max_dur"])}
                    tp = fp = fn = n_true = 0
                    for prep, truth in zip(preps, truths):
                        pred = assemble_prepared(prep, params)
                        r = match(pred, truth)[cls]
                        tp += r["tp"]; fp += r["fp"]; fn += r["fn"]; n_true += r["n_true"]
                    if n_true == 0:
                        continue
                    recall = tp / n_true
                    fa_h = fp / hours
                    prec = tp / (tp + fp) if (tp + fp) else 0.0
                    row = dict(on=on, off=off, min_dur=min_dur, merge_gap=merge_gap,
                               recall=recall, precision=prec, fa_per_hour=fa_h)
                    frontier.append(row)
                    if fa_h <= budget:
                        # Tie-break on precision: among equally sensitive settings,
                        # prefer the one that cries wolf less.
                        key = (recall, prec)
                        if best is None or key > (best["recall"], best["precision"]):
                            best = row
    return best, frontier


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nights", type=Path, default=ROOT / "ml/artifacts/nights.npz")
    ap.add_argument("--budget", type=float, default=1.0, help="max false alarms per hour")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "android/app/src/main/assets/detector_config.json")
    ap.add_argument("--report", type=Path, default=ROOT / "results/threshold_tuning.json")
    args = ap.parse_args()

    nights, _ = load_nights(args.nights)
    print(f"preparing {len(nights)} nights ...")
    preps = [prepare(s, r) for s, r, _ in nights]
    truths = [t for _, _, t in nights]

    grid = dict(
        on=[round(x, 2) for x in np.arange(0.10, 0.65, 0.05)],
        off_ratio=[0.4, 0.55, 0.7],
        min_dur=[600, 960],
        merge_gap=[720, 1200, 1500, 2000],
    )

    tuned, report = {}, {}
    for cls in LOGGED:
        print(f"sweeping {cls} ({len(grid['on']) * 3 * 2 * 4} combinations) ...")
        best, frontier = sweep_class(preps, truths, cls, args.budget, grid)
        if best is None:
            print(f"  no setting met the budget; keeping defaults for {cls}")
            best = dict(**{k: DEFAULT_PARAMS[cls][k] for k in ("on", "off", "min_dur", "merge_gap")},
                        recall=0.0, precision=0.0, fa_per_hour=0.0)
        tuned[cls] = best
        report[cls] = dict(best=best, frontier=sorted(
            frontier, key=lambda r: -r["recall"])[:20])
        print(f"  on={best['on']} off={best['off']} min_dur={best['min_dur']} "
              f"merge_gap={best['merge_gap']} -> recall={best['recall']:.3f} "
              f"prec={best['precision']:.3f} FA/h={best['fa_per_hour']:.2f}")

    # Emit in DetectorConfig's on-the-wire shape.
    params_json = {}
    for cls in LOGGED:
        b = tuned[cls]
        params_json[cls] = dict(
            onThreshold=float(b["on"]), offThreshold=float(b["off"]),
            minDurationMs=int(b["min_dur"]), mergeGapMs=int(b["merge_gap"]),
            refractoryMs=int(DEFAULT_PARAMS[cls]["refractory"]),
            maxDurationMs=int(DEFAULT_PARAMS[cls]["max_dur"]),
        )
    # Context classes are not events; carry the defaults through unchanged.
    params_json["BREATHING"] = dict(onThreshold=0.50, offThreshold=0.30, minDurationMs=960,
                                    mergeGapMs=1440, refractoryMs=500, maxDurationMs=15000)
    params_json["SPEECH"] = dict(onThreshold=0.60, offThreshold=0.40, minDurationMs=960,
                                 mergeGapMs=1440, refractoryMs=300, maxDurationMs=30000)

    config = dict(
        params=params_json, gateMarginDb=6.0, speechSuppressionThreshold=0.55,
        coughSneezeExclusionThreshold=0.20, coughBoutGapMs=3000,
        snoreEpisodeGapMs=60000, emaAlpha=0.5,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(config, indent=2))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(
        dict(budget_fa_per_hour=args.budget, grid=grid, results=report), indent=2))

    print(f"\nwrote {args.out}")
    tuned_params = {c: dict(on=tuned[c]["on"], off=tuned[c]["off"],
                            min_dur=tuned[c]["min_dur"], merge_gap=tuned[c]["merge_gap"],
                            refractory=DEFAULT_PARAMS[c]["refractory"],
                            max_dur=DEFAULT_PARAMS[c]["max_dur"]) for c in LOGGED}
    print_report(evaluate(nights, DEFAULT_PARAMS), "BEFORE (defaults)")
    print_report(evaluate(nights, tuned_params), "AFTER (tuned)")


if __name__ == "__main__":
    main()
