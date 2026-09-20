# Cough detection project instructions

- Use Python 3.12 and the project `.venv`.
- Datasets live under `Datasets/`; do not modify or commit dataset files.
- COUGHVID labels are automated `cough_detected` confidence scores, not definitive ground truth.
- ESC-50 is an environmental-sound benchmark; only its `coughing` class is positive for cough detection.
- Keep model adapters and evaluation code in `scripts/`, and write generated reports to `results/`.
- Report accuracy together with precision, recall, F1, ROC-AUC/average precision, latency, throughput, and memory where applicable.
- Do not claim medical diagnostic performance from these datasets or models.
- Preserve model and dataset licenses and cite their sources in documentation.

## Android application (added alongside the benchmark)

- The app lives in `android/`; the model-prep and validation harness in `ml/`. The
  original clip benchmark stays in `scripts/` and is unchanged.
- `android/core-domain` is pure Kotlin/JVM and must never gain an Android dependency.
  It is the module that moves to iOS via Kotlin Multiplatform; adding an Android import
  there silently forfeits that.
- Detection logic exists in Kotlin (`core-domain`) and Python (`ml/assembler.py`).
  Any change to one must be made in the other, and `ml/parity_fixture.py` regenerated,
  or `AssemblerParityTest` will fail — which is the intent.
- Report event-level metrics with **false alarms per hour**, not just F1. Clip-level
  accuracy does not predict overnight behaviour.
- Thresholds shipped in `android/app/src/main/assets/detector_config.json` are produced
  by `ml/tune_thresholds.py`. Do not hand-edit them; re-run the sweep.
- Synthetic night audio is a tuning and regression target, not a measurement of
  real-world accuracy. Say so whenever quoting those numbers.
- Audio and embeddings stay on the device. Export formats deliberately exclude both.
- The existing rule against diagnostic claims applies to the app: it logs acoustic
  events and is not a sleep-apnoea or disease screener.
