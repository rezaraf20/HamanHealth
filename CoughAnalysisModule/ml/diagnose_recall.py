#!/usr/bin/env python3
"""Where do real coughs get lost?

Runs real cough recordings through the exact on-device chain and records the first
stage that drops each one:

  model   - YAMNet never scored the cough above the on-threshold
  gate    - it did, but only on frames the noise gate skipped
  smooth  - it survived the gate but median+EMA smoothing pulled it under
  speech  - the speech suppressor blocked the onset
  assembly- the score crossed the threshold but no event came out (min duration etc.)
  detected

COUGHVID is used because its recordings come from thousands of different users'
phones and browsers - the device variety the app actually meets - unlike ESC-50's
curated clips. Each clip is embedded after 20 s of room noise so the noise floor and
gate behave as they would mid-night, rather than sitting in their warm-up state.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from assembler import (IDX, DEFAULTS, apply_exclusion, assemble_prepared,
                       exclusion_threshold, prepare, validate_params)
from frontend import (ROOT, SAMPLE_RATE, HOP_SAMPLES, FRAME_SAMPLES, frame_audio,
                      load_interpreter, normalise, reduce_scores, run_frames)

PREFIX_S = 20.0


def load_16k(path: Path) -> np.ndarray:
    import librosa
    a, sr = sf.read(path, dtype="float32", always_2d=False)
    if a.ndim > 1:
        a = a.mean(axis=1)
    if sr != SAMPLE_RATE:
        a = librosa.resample(a, orig_sr=sr, target_sr=SAMPLE_RATE)
    return a


def brown(n, level_db, rng):
    b = np.cumsum(rng.standard_normal(n)).astype(np.float32)
    b -= b.mean()
    b /= np.sqrt(np.mean(b ** 2)) + 1e-9
    return b * 10 ** (level_db / 20)


def lowpass(a, cutoff_hz):
    from scipy.signal import butter, sosfilt
    sos = butter(8, cutoff_hz, btype="low", fs=SAMPLE_RATE, output="sos")
    return sosfilt(sos, a).astype(np.float32)


VARIANTS = {
    # as recorded: phone held close, which is how COUGHVID was collected
    "near":        dict(gain_db=0,   lp=None),
    # nightstand distance: ~15 dB quieter
    "bedside":     dict(gain_db=-15, lp=None),
    # quieter still, e.g. a low-sensitivity budget mic or a phone across the bed
    "far":         dict(gain_db=-28, lp=None),
    # voice-processing path that band-limits to telephony bandwidth
    "narrowband":  dict(gain_db=-15, lp=3800),
}


SHIPPED_CONFIG = ROOT / "android/app/src/main/assets/detector_config.json"


def load_params(path=None):
    cfg = json.loads(Path(path or SHIPPED_CONFIG).read_text())
    params = {k: dict(on=v["onThreshold"], off=v["offThreshold"], min_dur=v["minDurationMs"],
                      merge_gap=v["mergeGapMs"], refractory=v["refractoryMs"],
                      max_dur=v.get("maxDurationMs", 3000))
              for k, v in cfg["params"].items() if k in ("COUGH", "SNEEZE", "SNORE")}
    return params


def load_rules(path=None):
    """Pipeline rules as shipped, in the assembler's cfg vocabulary."""
    cfg = json.loads(Path(path or SHIPPED_CONFIG).read_text())
    return dict(smoothing="attack_release" if cfg.get("attackRelease") else "ema",
                speech_sustain=cfg.get("speechSustainFrames", 1),
                speech_window=cfg.get("speechWindowFrames", 5),
                sneeze_margin=cfg.get("sneezeMargin", 0.0))


def classify(scores, rms, clip_lo, clip_hi, params):
    """First stage at which the cough is lost."""
    on = params["COUGH"]["on"]
    prep = prepare(scores, rms)
    c = IDX["COUGH"]
    sl = slice(clip_lo, clip_hi)

    raw_max = float(scores[sl, c].max())
    if raw_max < on:
        return "model", raw_max

    gated_raw = np.where(prep["gate"][sl], scores[sl, c], 0.0)
    if gated_raw.max() < on:
        return "gate", raw_max

    sm = apply_exclusion(prep["sm"], exclusion_threshold(params, prep["cfg"]), prep["cfg"]["sneeze_margin"])
    if sm[sl, c].max() < on:
        return "smooth", raw_max

    crossing = (sm[sl, c] >= on) & prep["gate"][sl]
    if crossing.any() and prep["speech"][sl][crossing].all():
        return "speech", raw_max

    events = assemble_prepared(prep, params)
    t_lo, t_hi = clip_lo * 480, clip_hi * 480 + 975
    if any(e.cls == "COUGH" and e.end_ms >= t_lo and e.start_ms <= t_hi for e in events):
        return "detected", raw_max
    return "assembly", raw_max


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--min-conf", type=float, default=0.9)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--out", type=Path, default=ROOT / "results/recall_diagnosis.json")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    # Held-out split only: these recordings never touched threshold tuning.
    from night_mixer import coughvid_files
    files = coughvid_files(split_held_out=True, min_conf=args.min_conf)
    rng.shuffle(files)
    files = files[: args.n]
    print(f"{len(files)} held-out COUGHVID recordings with cough_detected >= {args.min_conf}")

    params = load_params()
    print("cough params:", params["COUGH"])
    interp = load_interpreter()

    results = {v: [] for v in VARIANTS}
    for k, wav in enumerate(files, 1):
        clip = load_16k(wav)
        if len(clip) < FRAME_SAMPLES:
            continue
        peak = np.abs(clip).max() + 1e-9
        clip = clip / peak * 0.5  # normalise the recording itself; variants then set level
        for name, v in VARIANTS.items():
            x = clip * 10 ** (v["gain_db"] / 20)
            if v["lp"]:
                x = lowpass(x, v["lp"])
            n_pre = int(PREFIX_S * SAMPLE_RATE)
            audio = brown(n_pre + len(x) + SAMPLE_RATE, -62, rng)
            audio[n_pre:n_pre + len(x)] += x
            frames = frame_audio(audio)
            raw, _ = run_frames(*interp, normalise(frames))
            red = reduce_scores(raw)
            rms = np.array([20 * np.log10(np.sqrt(np.mean(f.astype(np.float64) ** 2)) + 1e-12)
                            for f in frames], dtype=np.float32)
            lo = max(0, n_pre // HOP_SAMPLES - 1)
            hi = min(len(frames), (n_pre + len(x)) // HOP_SAMPLES + 1)
            stage, raw_max = classify(red, rms, lo, hi, params)
            results[name].append(dict(file=wav.name, stage=stage, raw_max=raw_max))
        if k % 25 == 0:
            print(f"  {k}/{len(files)}")

    stages = ["detected", "model", "gate", "smooth", "speech", "assembly"]
    print(f"\n{'variant':12}" + "".join(f"{s:>10}" for s in stages) + f"{'median raw':>12}")
    print("-" * 84)
    summary = {}
    for name, rows in results.items():
        n = len(rows)
        counts = {s: sum(r["stage"] == s for r in rows) for s in stages}
        med = float(np.median([r["raw_max"] for r in rows]))
        summary[name] = dict(n=n, counts=counts, median_raw_cough=med)
        print(f"{name:12}" + "".join(f"{100*counts[s]/n:9.0f}%" for s in stages) + f"{med:12.2f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(params=params["COUGH"], summary=summary,
                                        rows=results), indent=1))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
