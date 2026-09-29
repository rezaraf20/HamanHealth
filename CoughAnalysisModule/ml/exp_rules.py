#!/usr/bin/env python3
"""Measure candidate rule changes on three sources at once.

  device  - a real phone capture (debug dump) of known coughs played from a speaker
  heldout - held-out COUGHVID coughs at bedside / far levels (never used for tuning)
  nights  - synthetic nights: recall and false alarms per hour

Thresholds are held fixed at the shipped config so differences are due to the rules.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import soundfile as sf

import assembler as A
from assembler import prepare, assemble_prepared, match
from analyze_capture import align
import diagnose_recall as D
from eval_night import load_nights
from frontend import (ROOT, SAMPLE_RATE, HOP_SAMPLES, FRAME_SAMPLES, frame_audio,
                      load_interpreter, normalise, reduce_scores, rms_db, run_frames, HOP_MS)
from night_mixer import coughvid_files

CONFIGS = {
    "current":                dict(),
    "speech sustained 4/5":   dict(speech_sustain=4),
    "speech off":             dict(speech_sustain=99),
    "attack_release":         dict(smoothing="attack_release"),
    "sneeze margin .15":      dict(sneeze_margin=0.15),
    "sustain+margin":         dict(speech_sustain=4, sneeze_margin=0.15),
    "all three":              dict(speech_sustain=4, sneeze_margin=0.15, smoothing="attack_release"),
}


def score(frames, interp):
    return reduce_scores(run_frames(*interp, normalise(frames))[0])


def device_set(pcm_path, d, interp):
    cap = np.fromfile(pcm_path, dtype="<i2").astype(np.float32) / 32768
    frames = frame_audio(cap)
    sc = score(frames, interp)
    rms = np.array([rms_db(f) for f in frames], dtype=np.float32)
    gts, cursor = [], 0
    for lvl in ("loud", "quiet"):
        played, _ = sf.read(d / f"playback_{lvl}.wav", dtype="float32")
        off, _ = align(cap, played, cursor)
        cursor = off + len(played) - SAMPLE_RATE
        for m in json.load(open(d / f"playback_{lvl}.json")):
            gts.append(dict(cls="COUGH", lvl=lvl,
                            start_ms=int((off / SAMPLE_RATE + m["start_s"]) * 1000),
                            end_ms=int((off / SAMPLE_RATE + m["end_s"]) * 1000)))
    return sc, rms, gts


def heldout_set(interp, n, rng):
    files = coughvid_files(split_held_out=True)
    rng.shuffle(files)
    out = []
    for wav in files[:n]:
        clip = D.load_16k(wav)
        if len(clip) < FRAME_SAMPLES:
            continue
        clip = clip / (np.abs(clip).max() + 1e-9) * 0.5
        for vname in ("bedside", "far"):
            v = D.VARIANTS[vname]
            x = clip * 10 ** (v["gain_db"] / 20)
            n_pre = int(D.PREFIX_S * SAMPLE_RATE)
            audio = D.brown(n_pre + len(x) + SAMPLE_RATE, -62, rng)
            audio[n_pre:n_pre + len(x)] += x
            frames = frame_audio(audio)
            sc = score(frames, interp)
            rms = np.array([rms_db(f) for f in frames], dtype=np.float32)
            gt = [dict(cls="COUGH", start_ms=int(n_pre / SAMPLE_RATE * 1000),
                       end_ms=int((n_pre + len(x)) / SAMPLE_RATE * 1000))]
            out.append((vname, sc, rms, gt))
    return out


def run_cfg(params, cfg, dev, held, nights):
    r = {}
    sc, rms, gts = dev
    ev = assemble_prepared(prepare(sc, rms, cfg), params)
    for lvl in ("loud", "quiet"):
        g = [x for x in gts if x["lvl"] == lvl]
        r[f"dev_{lvl}"] = match(ev, g)["COUGH"]["tp"] / len(g)
    non_cough = sum(1 for e in ev if e.cls != "COUGH")
    r["dev_other_events"] = non_cough
    for vname in ("bedside", "far"):
        items = [x for x in held if x[0] == vname]
        hits = sum(match(assemble_prepared(prepare(s, rr, cfg), params), gt)["COUGH"]["tp"]
                   for _, s, rr, gt in items)
        r[f"held_{vname}"] = hits / len(items)
    tot = {c: dict(tp=0, fp=0, n_true=0) for c in ("COUGH", "SNEEZE", "SNORE")}
    hours = 0
    for s, rr, truth in nights:
        m = match(assemble_prepared(prepare(s, rr, cfg), params), truth)
        for c in tot:
            for k in tot[c]:
                tot[c][k] += m[c][k]
        hours += len(s) * HOP_MS / 3.6e6
    for c in tot:
        r[f"night_{c}_recall"] = tot[c]["tp"] / max(tot[c]["n_true"], 1)
        r[f"night_{c}_fah"] = tot[c]["fp"] / hours
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcm", required=True); ap.add_argument("--dir", required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--shipped", action="store_true", help="evaluate only the shipped config + rules")
    ap.add_argument("--config", action="append", default=[],
                    help="evaluate these config files (thresholds + rules) instead")
    a = ap.parse_args()
    interp = load_interpreter()
    params = D.load_params()
    cfg_files = a.config
    dev = device_set(a.pcm, Path(a.dir), interp)
    held = heldout_set(interp, a.n, np.random.default_rng(5))
    nights, _ = load_nights(ROOT / "ml/artifacts/nights.npz", normalised=True)
    print(f"device coughs: {len(dev[2])}, held-out clips: {len(held)}, nights: {len(nights)}")
    hdr = ("config", "dev loud", "dev quiet", "held bed", "held far",
           "N cough", "cough FA/h", "sneeze FA/h", "snore FA/h")
    print("\n" + f"{hdr[0]:24}" + "".join(f"{h:>11}" for h in hdr[1:]))
    print("-" * 112)
    results = {}
    configs = {k: (params, v) for k, v in CONFIGS.items()}
    if a.shipped:
        configs = {"shipped (tuned)": (params, D.load_rules())}
    if cfg_files:
        configs = {Path(f).stem: (D.load_params(f), D.load_rules(f)) for f in cfg_files}
    for name, (prm, cfg) in configs.items():
        print(f"  {name}: rules={cfg} cough={prm['COUGH']}")
    for name, (prm, cfg) in configs.items():
        r = run_cfg(prm, cfg, dev, held, nights)
        results[name] = r
        print(f"{name:24}" + "".join(f"{v:>10.0%} " for v in (r["dev_loud"], r["dev_quiet"],
              r["held_bedside"], r["held_far"], r["night_COUGH_recall"]))
              + "".join(f"{v:>11.2f}" for v in (r["night_COUGH_fah"], r["night_SNEEZE_fah"], r["night_SNORE_fah"])))
    (ROOT / "results/rule_experiments.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
