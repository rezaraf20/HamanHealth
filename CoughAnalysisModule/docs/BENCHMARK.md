# Clip-level model benchmark (original exploration)

This is the work the module grew out of: a clip-level comparison of CoughKit and YAMNet
on COUGHVID and ESC-50, kept unchanged in `scripts/`.

Its headline result (CoughKit F1 0.96 vs YAMNet 0.85 on COUGHVID) is **not** why YAMNet
was chosen to run on the phone. See [ARCHITECTURE.md](ARCHITECTURE.md) section 1 for why
that comparison should not drive the on-device model decision.

# Cough Detection Model Exploration

This project compares two zero-shot cough scorers against the local COUGHVID and ESC-50 datasets:

- **CoughKit**: a bundled XGBoost cough classifier from [bagustris/coughkit](https://github.com/bagustris/coughkit).
- **YAMNet**: TensorFlow Hub's AudioSet-pretrained general audio event model.

The comparison measures classification metrics, per-file latency, throughput relative to audio duration, model-load time, and process RSS change. It is an engineering benchmark, not a medical validation study.

## Setup

The project uses Python 3.12 because the current CoughKit release requires Python 3.11+. On this Apple Silicon machine:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install --no-deps -e ./models/audiokit
.venv/bin/python -m pip install --no-deps -e ./models/coughkit
```

CoughKit's XGBoost wheel needs OpenMP. On this machine, launch CoughKit benchmarks with the copy bundled in scikit-learn:

```bash
DYLD_LIBRARY_PATH="$PWD/.venv/lib/python3.12/site-packages/sklearn/.dylibs" .venv/bin/python scripts/benchmark.py --dataset esc50 --model coughkit --limit 20
```

If that copy is unavailable, install `libomp` through the machine's package manager and rerun.

## Explore the data

```bash
.venv/bin/python scripts/profile_datasets.py
```

COUGHVID's `cough_detected` value is an automated confidence score. The benchmark accepts either `Datasets/COUGHVID` or the original `Datasets/public_dataset` layout and turns the score into a temporary label using `--coughvid-threshold`; this is weak supervision, not ground truth. ESC-50 uses its `coughing` category as the positive class and all other categories as negatives.

## Run model benchmarks

Warm YAMNet's TensorFlow Hub cache:

```bash
.venv/bin/python scripts/download_yamnet.py
```

Start with a small smoke benchmark:

```bash
.venv/bin/python scripts/benchmark.py --dataset esc50 --model both --limit 20
```

Full runs write JSON to `results/`:

```bash
.venv/bin/python scripts/benchmark.py --dataset esc50 --model both --output results/esc50.json
.venv/bin/python scripts/benchmark.py --dataset coughvid --model both --output results/coughvid.json
```

The benchmark uses a 0.5 model-score threshold for predictions. For product decisions, also inspect ROC-AUC, average precision, threshold curves, false-positive cost, cold-start versus warm latency, and performance on recordings from users and devices not represented in training data.

## Data and model provenance

- COUGHVID: Orlandic, Teijeiro, and Atienza, *The COUGHVID crowdsourcing dataset*, Scientific Data 2021. See the CoughKit README for the source citation and license details.
- ESC-50: Piczak, *ESC: Dataset for Environmental Sound Classification*, ACM Multimedia 2015. The local dataset is CC BY-NC.
- YAMNet: TensorFlow Models / AudioSet model, loaded from TensorFlow Hub at runtime.
- CoughKit source is cloned under `models/coughkit/`; its model artifacts are part of that repository.
