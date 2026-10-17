#!/usr/bin/env python3
"""Print compact, reproducible summaries of the local audio datasets."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd


def profile_coughvid(root: Path) -> None:
    scores = []
    for metadata_path in sorted(root.glob("*.json")):
        with metadata_path.open() as handle:
            metadata = json.load(handle)
        scores.append(float(metadata.get("cough_detected", 0.0)))
    print(f"COUGHVID records: {len(scores)}")
    if scores:
        print(f"  score min/mean/max: {min(scores):.4f}/{sum(scores)/len(scores):.4f}/{max(scores):.4f}")
        print(f"  score >= 0.5: {sum(score >= 0.5 for score in scores)}")


def profile_esc50(root: Path) -> None:
    metadata = pd.read_csv(root / "meta" / "esc50.csv")
    counts = Counter(metadata["category"])
    print(f"ESC-50 records: {len(metadata)}")
    print(f"  classes: {metadata['category'].nunique()}")
    print(f"  coughing records: {counts.get('coughing', 0)}")
    print(f"  folds: {dict(sorted(metadata['fold'].value_counts().to_dict().items()))}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", type=Path, default=Path("Datasets"))
    args = parser.parse_args()
    coughvid_root = args.datasets / "COUGHVID"
    if not coughvid_root.exists():
        coughvid_root = args.datasets / "public_dataset"
    profile_coughvid(coughvid_root)
    profile_esc50(args.datasets / "ESC-50-master")


if __name__ == "__main__":
    main()
