#!/usr/bin/env python3
"""Shared audio frontend, mirroring the Kotlin pipeline exactly.

Every constant here has a counterpart in core-domain. If the two drift, thresholds
tuned on this machine stop meaning anything on the phone, and the failure is silent -
so the framing, the class reduction and the smoothing all live in one place and are
copied into Kotlin rather than reinvented there.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# The model the app ships IS the model the harness evaluates. Keeping a second copy
# under ml/artifacts invites the two drifting apart after a re-export, which would
# silently invalidate every tuned threshold.
MODEL = ROOT / "android/app/src/main/assets/yamnet.tflite"

SAMPLE_RATE = 16000
FRAME_SAMPLES = 15600      # YamnetClassifier.FRAME_SAMPLES
HOP_SAMPLES = 7680         # 480 ms; MonitoringService.HOP_SAMPLES
HOP_MS = 480

# YamnetLabels.kt
IDX_BREATHING, IDX_SNORING, IDX_SNORT, IDX_COUGH, IDX_SNEEZE = 36, 38, 41, 42, 44
SPEECH_INDICES = [0, 1, 2, 3, 4, 65]

CLASSES = ["COUGH", "SNEEZE", "SNORE", "BREATHING", "SPEECH"]
LOGGED = ["COUGH", "SNEEZE", "SNORE"]


def load_interpreter(model_path: Path = MODEL):
    import tensorflow as tf

    interp = tf.lite.Interpreter(model_path=str(model_path), num_threads=4)
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    outs = interp.get_output_details()
    # Resolve by shape, exactly as YamnetClassifier does - output order is not guaranteed.
    scores_idx = next(o["index"] for o in outs if o["shape"][-1] == 521)
    emb_idx = next(o["index"] for o in outs if o["shape"][-1] == 1024)
    return interp, inp["index"], scores_idx, emb_idx


def frame_audio(audio: np.ndarray) -> np.ndarray:
    """Overlapping analysis windows, matching SlidingWindow."""
    if len(audio) < FRAME_SAMPLES:
        audio = np.pad(audio, (0, FRAME_SAMPLES - len(audio)))
    starts = range(0, len(audio) - FRAME_SAMPLES + 1, HOP_SAMPLES)
    return np.stack([audio[s:s + FRAME_SAMPLES] for s in starts])


def reduce_scores(raw: np.ndarray) -> np.ndarray:
    """521 AudioSet scores -> the 5 classes. Mirrors YamnetLabels.reduce."""
    out = np.zeros((raw.shape[0], len(CLASSES)), dtype=np.float32)
    out[:, 0] = raw[:, IDX_COUGH]
    out[:, 1] = raw[:, IDX_SNEEZE]
    out[:, 2] = np.maximum(raw[:, IDX_SNORING], raw[:, IDX_SNORT])
    out[:, 3] = raw[:, IDX_BREATHING]
    out[:, 4] = raw[:, SPEECH_INDICES].max(axis=1)
    return out


def rms_db(frame: np.ndarray) -> float:
    r = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))
    return -160.0 if r < 1e-8 else float(20.0 * np.log10(r))


def run_frames(interp, in_idx, sc_idx, em_idx, frames, want_embeddings=False):
    scores = np.zeros((len(frames), 521), dtype=np.float32)
    embs = np.zeros((len(frames), 1024), dtype=np.float32) if want_embeddings else None
    for i, f in enumerate(frames):
        interp.set_tensor(in_idx, f.astype(np.float32))
        interp.invoke()
        scores[i] = interp.get_tensor(sc_idx).reshape(-1)
        if want_embeddings:
            embs[i] = interp.get_tensor(em_idx).reshape(-1)
    return scores, embs


def median3_ema(raw: np.ndarray, alpha: float = 0.5) -> np.ndarray:
    """Mirrors ScoreSmoother: median-3 then EMA, per class."""
    n, k = raw.shape
    out = np.zeros_like(raw)
    h1 = np.zeros(k, dtype=np.float32)
    h2 = np.zeros(k, dtype=np.float32)
    ema = np.zeros(k, dtype=np.float32)
    for i in range(n):
        med = np.median(np.stack([raw[i], h1, h2]), axis=0)
        ema = med if i == 0 else alpha * med + (1 - alpha) * ema
        out[i] = ema
        h2, h1 = h1, raw[i].copy()
    return out
