#!/usr/bin/env python3
"""Build the playback sequences used by tools/device_recall_test.sh.

Twelve real coughs from the HELD-OUT COUGHVID split (never used for tuning), each
separated by 6 s of silence, at a loud and a quiet level. Played from a speaker next to
the phone, they give a controlled, repeatable recall test through a real phone's actual
microphone path - the one thing no desktop simulation reproduces.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import soundfile as sf
from frontend import ROOT
from night_mixer import coughvid_files, load_16k, trim

OUT = ROOT / "ml/artifacts/playback"


def main(n: int = 12, seed: int = 11):
    rng = np.random.default_rng(seed)
    files = coughvid_files(split_held_out=True)
    rng.shuffle(files)
    clips = []
    for f in files:
        c = trim(load_16k(f))
        if 0.6 < len(c) / 16000 < 4.5:
            clips.append((f.name, c / (np.abs(c).max() + 1e-9) * 0.8))
        if len(clips) == n:
            break
    OUT.mkdir(parents=True, exist_ok=True)
    gap = np.zeros(6 * 16000, dtype=np.float32)
    for name, gain_db in (("loud", 0), ("quiet", -20)):
        parts, marks, t = [np.zeros(3 * 16000, dtype=np.float32)], [], 3.0
        for fname, c in clips:
            x = (c * 10 ** (gain_db / 20)).astype(np.float32)
            marks.append(dict(file=fname, start_s=round(t, 3), end_s=round(t + len(x) / 16000, 3)))
            parts += [x, gap]
            t += len(x) / 16000 + 6.0
        sf.write(OUT / f"playback_{name}.wav", np.concatenate(parts), 16000)
        (OUT / f"playback_{name}.json").write_text(json.dumps(marks, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
