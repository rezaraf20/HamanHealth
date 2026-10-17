# Third-party components and attribution

## Shipped in the app

**YAMNet** — `android/app/src/main/assets/yamnet.tflite`

Converted from the TensorFlow Hub model at `https://tfhub.dev/google/yamnet/1` by
[`ml/export_yamnet_tflite.py`](ml/export_yamnet_tflite.py). The conversion changes only
the input/output signature (a fixed 15600-sample frame returning scores *and* the 1024-d
embedding); the weights are unmodified and numerical parity with the original is verified
to ~1e-6 as part of the export.

- Source: TensorFlow Model Garden / AudioSet
- Licence: **Apache License 2.0**
- Paper: Gemmeke et al., *Audio Set: An ontology and human-labeled dataset for audio
  events*, ICASSP 2017

**TensorFlow Lite** runtime (`org.tensorflow:tensorflow-lite`) — Apache License 2.0.

**AndroidX / Jetpack Compose / Room / Kotlin coroutines & serialization** — Apache
License 2.0.

## Used for development only, not shipped

**ESC-50** — `Datasets/ESC-50-master/`

Used to evaluate clip-level accuracy and to synthesise night audio for threshold tuning.
Not redistributed here.

- Piczak, *ESC: Dataset for Environmental Sound Classification*, ACM Multimedia 2015
- Licence: **CC BY-NC 3.0** — non-commercial use only

**COUGHVID** — `Datasets/COUGHVID/`

Used only by the original clip benchmark in `scripts/`. Not redistributed here.

- Orlandic, Teijeiro & Atienza, *The COUGHVID crowdsourcing dataset, a corpus for the
  study of large-scale cough analysis algorithms*, Scientific Data 2021

Note: COUGHVID's `cough_detected` field is an automated confidence score, not a
human-verified ground-truth label.

**CoughKit** — `models/coughkit/`, **audiokit** — `models/audiokit/`

Third-party clones kept out of this repository's history. Used only as a comparison
baseline in the original benchmark; not used by the Android app.

- Source: https://github.com/bagustris/coughkit
- See that repository for its own licence and model provenance.

## Note on the non-commercial dataset licence

ESC-50 is CC BY-NC. It is used here to *evaluate and tune* the detector; no ESC-50 audio
is redistributed and none is embedded in the app. If this module is ever used
commercially, re-verify that the tuning provenance is acceptable, or re-tune against
audio with suitable licensing.
