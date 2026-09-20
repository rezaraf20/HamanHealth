#!/usr/bin/env python3
"""Benchmark YAMNet and CoughKit as cough scorers on local datasets."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

import librosa
import numpy as np
import pandas as pd
import psutil
import soundfile as sf
from sklearn.metrics import accuracy_score, average_precision_score, f1_score, precision_score, recall_score, roc_auc_score


YAMNET_URL = "https://tfhub.dev/google/yamnet/1"
YAMNET_CLASS_MAP_URL = "https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv"


def load_coughkit():
    """Load the editable CoughKit package."""
    from coughkit import classify_cough, load_cough_classifier, load_scaler

    return classify_cough, load_cough_classifier(), load_scaler()


def load_yamnet():
    import tensorflow_hub as hub

    class_map_path = Path(__file__).resolve().parents[1] / "models/yamnet_class_map.csv"
    if not class_map_path.exists():
        class_map_path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(YAMNET_CLASS_MAP_URL) as source, class_map_path.open("wb") as target:
            target.write(source.read())
    class_map = pd.read_csv(class_map_path)
    labels = class_map["display_name"].astype(str).tolist()
    cough_ids = [index for index, label in enumerate(labels) if "cough" in label.casefold()]
    if not cough_ids:
        raise RuntimeError("YAMNet class map contains no cough label")
    return hub.load(YAMNET_URL), cough_ids, labels


@dataclass
class Record:
    path: Path
    label: int
    source_score: float | None
    duration_seconds: float


def records_for(dataset: str, root: Path, coughvid_threshold: float) -> list[Record]:
    records = []
    if dataset == "coughvid":
        coughvid_root = root / "COUGHVID"
        if not coughvid_root.exists():
            coughvid_root = root / "public_dataset"
        for metadata_path in sorted(coughvid_root.glob("*.json")):
            audio_path = metadata_path.with_suffix(".wav")
            if not audio_path.exists():
                continue
            with metadata_path.open() as handle:
                score = float(json.load(handle).get("cough_detected", 0.0))
            records.append(Record(audio_path, int(score >= coughvid_threshold), score, sf.info(audio_path).duration))
    else:
        metadata = pd.read_csv(root / "ESC-50-master/meta/esc50.csv")
        for row in metadata.itertuples():
            audio_path = root / "ESC-50-master/audio" / row.filename
            records.append(Record(audio_path, int(row.category == "coughing"), None, sf.info(audio_path).duration))
    return records


def score_file(model_name: str, path: Path, state) -> float:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if model_name == "coughkit":
        classify_cough, model, scaler = state
        return float(classify_cough(audio, sample_rate, model, scaler))
    yamnet, cough_ids, _ = state
    audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)
    scores, _, _ = yamnet(audio)
    return float(np.max(scores.numpy()[:, cough_ids]))


def evaluate(model_name: str, records: list[Record], limit: int | None) -> dict:
    selected = records[:limit] if limit else records
    process = psutil.Process()
    before_memory = process.memory_info().rss
    load_start = time.perf_counter()
    state = load_coughkit() if model_name == "coughkit" else load_yamnet()
    load_seconds = time.perf_counter() - load_start
    scores, elapsed, durations = [], [], []
    for record in selected:
        start = time.perf_counter()
        scores.append(score_file(model_name, record.path, state))
        elapsed.append(time.perf_counter() - start)
        durations.append(record.duration_seconds)
    labels = np.array([record.label for record in selected])
    predictions = (np.array(scores) >= 0.5).astype(int)
    metrics = {"model": model_name, "records": len(selected), "load_seconds": load_seconds,
               "peak_rss_delta_mb": (process.memory_info().rss - before_memory) / 1e6,
               "mean_latency_ms": statistics.mean(elapsed) * 1000,
               "p50_latency_ms": float(np.percentile(elapsed, 50) * 1000),
               "p95_latency_ms": float(np.percentile(elapsed, 95) * 1000),
               "audio_seconds_per_wall_second": sum(durations) / max(sum(elapsed), 1e-9),
               "accuracy": accuracy_score(labels, predictions),
               "precision": precision_score(labels, predictions, zero_division=0),
               "recall": recall_score(labels, predictions, zero_division=0),
               "f1": f1_score(labels, predictions, zero_division=0)}
    if len(np.unique(labels)) == 2:
        metrics["roc_auc"] = roc_auc_score(labels, scores)
        metrics["average_precision"] = average_precision_score(labels, scores)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=["coughvid", "esc50"], required=True)
    parser.add_argument("--model", choices=["coughkit", "yamnet", "both"], default="both")
    parser.add_argument("--datasets", type=Path, default=Path("Datasets"))
    parser.add_argument("--limit", type=int, help="Evaluate only the first N sorted records")
    parser.add_argument("--coughvid-threshold", type=float, default=0.5)
    parser.add_argument("--output", type=Path, default=Path("results/benchmark.json"))
    args = parser.parse_args()
    records = records_for(args.dataset, args.datasets, args.coughvid_threshold)
    models = ["coughkit", "yamnet"] if args.model == "both" else [args.model]
    results = [evaluate(model, records, args.limit) for model in models]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"dataset": args.dataset, "coughvid_threshold": args.coughvid_threshold, "results": results}, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
