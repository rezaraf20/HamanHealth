#!/usr/bin/env python3
"""Feasibility: does a cough head trained on YAMNet embeddings beat YAMNet's own Cough output?

YAMNet's Cough score is a linear read-out of the same 1024-d embedding, trained on
AudioSet. A read-out trained on the target domain - phone-recorded coughs at nightstand
levels and room noise, with the same normalisation the app applies - may recover coughs
YAMNet scores near zero.

Training data: COUGHVID tuning split (positives, weakly labelled by frame activity) and
ESC-50 non-cough categories plus low-confidence COUGHVID clips (negatives), each placed
at random levels in room noise. Evaluation: real phone captures (tools/device_recall_test.sh),
which are held-out coughs through a different acoustic path.
"""
from __future__ import annotations
import glob, json
from pathlib import Path
import numpy as np, pandas as pd, soundfile as sf
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from frontend import (ROOT, SAMPLE_RATE, HOP_SAMPLES, FRAME_SAMPLES, frame_audio, load_interpreter,
                      normalise, reduce_scores, rms_db, run_frames)
from night_mixer import coughvid_files, load_16k, lowpass, room_noise
from analyze_capture import align
from assembler import IDX

rng = np.random.default_rng(0)
interp = load_interpreter()


def embed_clip(clip, level_db, lp=None):
    x = clip / (np.abs(clip).max() + 1e-9) * 0.5 * 10 ** (level_db / 20)
    if lp: x = lowpass(x, lp)
    pad = int(0.5 * SAMPLE_RATE)
    audio = room_noise(len(x) + 2 * pad, -62, rng); audio[pad:pad + len(x)] += x
    frames = frame_audio(audio)
    raw, emb = run_frames(*interp, normalise(frames), want_embeddings=True)
    act = np.array([rms_db(f) for f in frames])
    return emb, reduce_scores(raw)[:, IDX["COUGH"]], act


X, y = [], []
pos = coughvid_files(split_held_out=False); rng.shuffle(pos)
for f in pos[:350]:
    c = load_16k(f)
    if len(c) < FRAME_SAMPLES // 2: continue
    emb, _, act = embed_clip(c, float(rng.choice([0, -8, -15, -22, -28])), 5500 if rng.random() < .3 else None)
    keep = act >= act.max() - 12                     # weak label: the clip's active frames
    X.append(emb[keep]); y.append(np.ones(keep.sum()))

meta = pd.read_csv(ROOT / "Datasets/ESC-50-master/meta/esc50.csv")
negs = meta[meta.category != "coughing"].sample(900, random_state=0)
for fn in negs.filename:
    emb, _, act = embed_clip(load_16k(ROOT / "Datasets/ESC-50-master/audio" / fn), float(rng.uniform(-25, 0)))
    X.append(emb); y.append(np.zeros(len(emb)))
lowconf = [Path(j).with_suffix(".wav") for j in sorted(glob.glob(str(ROOT / "Datasets/COUGHVID/*.json")))
           if float(json.loads(open(j).read()).get("cough_detected", 1)) < 0.05 and Path(j).with_suffix(".wav").exists()]
rng.shuffle(lowconf)
for f in lowconf[:250]:                              # mostly speech and handling noise
    c = load_16k(f)
    if len(c) < FRAME_SAMPLES // 2: continue
    emb, _, _ = embed_clip(c, float(rng.uniform(-20, 0)))
    X.append(emb); y.append(np.zeros(len(emb)))
X = np.concatenate(X); y = np.concatenate(y)
print(f"training frames: {len(y)}  (positives {int(y.sum())})")
head = LogisticRegression(C=0.5, max_iter=3000, class_weight="balanced").fit(X, y)

# ---- evaluate on real phone captures ----
PB = ROOT / "ml/artifacts/playback"
# every capture made with tools/device_recall_test.sh
caps = {p.stem: p for p in sorted((ROOT / "results/device").glob("*.pcm"))}

print(f"\n{'capture':28}{'lvl':>6}   {'YAMNet cough >=.4':>18}   {'head >=.5':>10}   {'frame AUC yamnet/head':>22}")
for name, path in caps.items():
    cap = np.fromfile(path, dtype="<i2").astype(np.float32) / 32768
    frames = frame_audio(cap)
    raw, emb = run_frames(*interp, normalise(frames), want_embeddings=True)
    yam = reduce_scores(raw)[:, IDX["COUGH"]]; hd = head.predict_proba(emb)[:, 1]
    cursor = 0
    lab = np.zeros(len(frames))
    for lvl in ("loud", "quiet"):
        played, _ = sf.read(PB / f"playback_{lvl}.wav", dtype="float32")
        off, _ = align(cap, played, cursor); cursor = off + len(played) - SAMPLE_RATE
        by, bh = [], []
        for m in json.load(open(PB / f"playback_{lvl}.json")):
            a = off + int(m["start_s"] * SAMPLE_RATE); b = off + int(m["end_s"] * SAMPLE_RATE)
            sl = slice(max(0, (a - FRAME_SAMPLES) // HOP_SAMPLES + 1), b // HOP_SAMPLES + 1)
            by.append(yam[sl].max()); bh.append(hd[sl].max()); lab[sl] = 1
        span = slice(off // HOP_SAMPLES, (off + len(played)) // HOP_SAMPLES)
        auc_y = roc_auc_score(lab[span], yam[span]); auc_h = roc_auc_score(lab[span], hd[span])
        print(f"{name:28}{lvl:>6}   {sum(v >= .4 for v in by):>12}/12      {sum(v >= .5 for v in bh):>5}/12   "
              f"{auc_y:>12.3f} / {auc_h:.3f}")
