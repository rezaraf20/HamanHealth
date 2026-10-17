#!/usr/bin/env python3
"""Replay a phone's raw capture (debug dump) against the known playback schedule.

For each played cough: how loud it arrived, how much high-frequency content survived
the phone's audio path, whether the gate opened, and what YAMNet scored it - i.e. where
on a real device each cough is lost. Alignment is by envelope cross-correlation, so it
does not depend on the phone's and the Mac's clocks agreeing.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve, welch

from frontend import (frame_audio, load_interpreter, reduce_scores, run_frames, normalise,
                      rms_db, HOP_SAMPLES, FRAME_SAMPLES, SAMPLE_RATE)
from assembler import prepare, assemble_prepared, IDX
import diagnose_recall as D


def env(x, hop=160):
    n = len(x) // hop
    return np.abs(x[: n * hop]).reshape(n, hop).mean(axis=1)


def align(capture, played, search_from=0):
    """Offset (samples) of `played` inside `capture`, by envelope correlation."""
    ec, ep = env(capture[search_from:]), env(played)
    ec = (ec - ec.mean()) / (ec.std() + 1e-9); ep = (ep - ep.mean()) / (ep.std() + 1e-9)
    corr = fftconvolve(ec, ep[::-1], mode="valid")
    k = int(np.argmax(corr))
    return search_from + k * 160, float(corr[k] / len(ep))


def bands(x):
    f, p = welch(x, fs=SAMPLE_RATE, nperseg=1024)
    lo = p[(f >= 300) & (f <= 3400)].mean(); hi = p[(f >= 4200) & (f <= 7400)].mean()
    return 10 * np.log10(lo + 1e-20), 10 * np.log10(hi + 1e-20)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pcm"); ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    d = Path(args.dir)
    cap = np.fromfile(args.pcm, dtype="<i2").astype(np.float32) / 32768
    print(f"capture: {len(cap)/SAMPLE_RATE:.0f} s")

    frames = frame_audio(cap)
    interp = load_interpreter()
    raw_n = reduce_scores(run_frames(*interp, normalise(frames))[0])
    raw_u = reduce_scores(run_frames(*interp, frames)[0])
    rms = np.array([rms_db(f) for f in frames], dtype=np.float32)
    prep = prepare(raw_n, rms)
    params = D.load_params()
    events = assemble_prepared(prep, params)

    cursor = 0
    for lvl in ("loud", "quiet"):
        played, _ = sf.read(d / f"playback_{lvl}.wav", dtype="float32")
        marks = json.load(open(d / f"playback_{lvl}.json"))
        off, q = align(cap, played, cursor)
        cursor = off + len(played) - SAMPLE_RATE
        print(f"\n== {lvl}: aligned at {off/SAMPLE_RATE:.2f} s (match {q:.2f}) ==")
        print(f"{'#':>2} {'played pk':>9} {'recv pk':>8} {'floor':>6} {'gate':>5} "
              f"{'cough(norm)':>11} {'cough(raw)':>10} {'sneeze':>6} {'speech':>6} "
              f"{'hi-lo play':>10} {'hi-lo recv':>10} {'detected':>8}")
        for i, m in enumerate(marks):
            a = off + int(m["start_s"] * SAMPLE_RATE); b = off + int(m["end_s"] * SAMPLE_RATE)
            pa, pb = int(m["start_s"] * SAMPLE_RATE), int(m["end_s"] * SAMPLE_RATE)
            f_lo = max(0, (a - FRAME_SAMPLES) // HOP_SAMPLES + 1); f_hi = min(len(frames), b // HOP_SAMPLES + 1)
            sl = slice(f_lo, f_hi)
            rec_pk = 20 * np.log10(np.abs(cap[a:b]).max() + 1e-9)
            ply_pk = 20 * np.log10(np.abs(played[pa:pb]).max() + 1e-9)
            lo_p, hi_p = bands(played[pa:pb]); lo_r, hi_r = bands(cap[a:b])
            t_lo, t_hi = a / SAMPLE_RATE * 1000, b / SAMPLE_RATE * 1000
            det = any(e.cls == "COUGH" and e.end_ms >= t_lo - 1500 and e.start_ms <= t_hi + 1500 for e in events)
            print(f"{i:2d} {ply_pk:8.1f}  {rec_pk:7.1f} {prep['floor'][sl].min():6.1f} "
                  f"{prep['gate'][sl].sum():2d}/{f_hi-f_lo:<2d} "
                  f"{raw_n[sl, IDX['COUGH']].max():11.2f} {raw_u[sl, IDX['COUGH']].max():10.2f} "
                  f"{raw_n[sl, IDX['SNEEZE']].max():6.2f} {raw_n[sl, IDX['SPEECH']].max():6.2f} "
                  f"{hi_p - lo_p:10.1f} {hi_r - lo_r:10.1f} {'yes' if det else '-':>8}")


if __name__ == "__main__":
    main()
