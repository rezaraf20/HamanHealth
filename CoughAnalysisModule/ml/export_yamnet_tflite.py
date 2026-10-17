#!/usr/bin/env python3
"""Export TF-Hub YAMNet to a TFLite model that returns scores *and* embeddings.

The bundled MediaPipe/TF-Hub .tflite variants emit classification scores only. This
project needs the 1024-d embedding as well: it is what the personalization and
speaker-attribution layers in docs/ARCHITECTURE.md §4 are built on.

Writes straight into the app's assets, which is the single source of truth: the model
the app ships is the model the evaluation harness scores against.

Input is one fixed 15600-sample frame (0.975 s @ 16 kHz) rather than a variable-length
waveform. A fixed shape lets the Android side allocate tensors once and reuse them
across ~60,000 inferences a night instead of reallocating per call, and it keeps the
phone's framing identical to the desktop harness's framing.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import tensorflow as tf
import tensorflow_hub as hub

YAMNET_URL = "https://tfhub.dev/google/yamnet/1"
FRAME_SAMPLES = 15600  # exactly one YAMNet patch
ROOT = Path(__file__).resolve().parents[1]


def build(out_path: Path) -> None:
    print("loading YAMNet from TF-Hub cache ...")
    yamnet = hub.load(YAMNET_URL)

    class Wrapped(tf.Module):
        def __init__(self, model):
            super().__init__()
            self.model = model

        @tf.function(input_signature=[tf.TensorSpec([FRAME_SAMPLES], tf.float32, name="waveform")])
        def infer(self, waveform):
            scores, embeddings, _ = self.model(waveform)
            # One patch in -> one frame out; drop the time axis so the phone gets
            # flat [521] / [1024] tensors.
            return {"scores": scores[0], "embeddings": embeddings[0]}

    wrapped = Wrapped(yamnet)
    concrete = wrapped.infer.get_concrete_function()

    converter = tf.lite.TFLiteConverter.from_concrete_functions([concrete], wrapped)
    # Builtins only, deliberately. Allowing SELECT_TF_OPS would drag the ~20 MB
    # Flex delegate into the APK; YAMNet converts without it, so this both keeps the
    # app smaller and fails loudly here if a future TF version stops converting cleanly.
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
    converter.optimizations = []  # keep float32: quantizing changes embedding geometry
    tflite_model = converter.convert()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(tflite_model)
    print(f"wrote {out_path}  ({len(tflite_model)/1e6:.2f} MB)")
    return yamnet


def verify(yamnet, out_path: Path, tolerance: float = 1e-3) -> None:
    """Confirm the exported model matches TF-Hub. If these drift, every threshold
    tuned on desktop is wrong on the phone."""
    print("\nverifying TFLite against TF-Hub ...")
    rng = np.random.default_rng(0)
    interpreter = tf.lite.Interpreter(model_content=out_path.read_bytes())
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    outs = {d["name"]: d for d in interpreter.get_output_details()}
    print("  input :", inp["shape"], inp["dtype"].__name__)
    for name, d in outs.items():
        print(f"  output: {name} {d['shape']} {d['dtype'].__name__}")

    worst_scores = worst_emb = 0.0
    for trial in range(5):
        wave = rng.standard_normal(FRAME_SAMPLES).astype(np.float32) * 0.1
        ref_scores, ref_emb, _ = yamnet(wave)
        ref_scores = ref_scores.numpy()[0]
        ref_emb = ref_emb.numpy()[0]

        interpreter.set_tensor(inp["index"], wave)
        interpreter.invoke()
        got = [interpreter.get_tensor(d["index"]) for d in interpreter.get_output_details()]
        got_scores = next(g for g in got if g.shape[-1] == 521).reshape(-1)
        got_emb = next(g for g in got if g.shape[-1] == 1024).reshape(-1)

        worst_scores = max(worst_scores, float(np.max(np.abs(ref_scores - got_scores))))
        worst_emb = max(worst_emb, float(np.max(np.abs(ref_emb - got_emb))))

    print(f"  max |dscores| = {worst_scores:.2e}")
    print(f"  max |dembed|  = {worst_emb:.2e}")
    ok = worst_scores < tolerance and worst_emb < tolerance * 100
    print("  PARITY OK" if ok else "  PARITY FAILED - do not ship this model")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=ROOT / "android/app/src/main/assets/yamnet.tflite")
    args = ap.parse_args()
    model = build(args.out)
    verify(model, args.out)
