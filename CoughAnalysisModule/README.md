# Cough Analysis Module

A module of **HamanHealth** that listens overnight and logs **coughs, sneezes and
snoring** to a local database on the phone.

Everything runs on the device. No audio is uploaded.

Android first (Kotlin + Jetpack Compose), structured so the detection core can move to
iOS later without a rewrite.

| | |
|---|---|
| **Design and rationale** | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| **Build, test, re-tune** | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| **Original model benchmark** | [docs/BENCHMARK.md](docs/BENCHMARK.md) |
| **Licences and attribution** | [THIRD_PARTY.md](THIRD_PARTY.md) |

**Just want to try it?** Install the ready-made APK: see [INSTALL.md](../INSTALL.md) at the
repository root.

---

## Quick start

Requires macOS on Apple Silicon and a phone with USB debugging enabled.

```bash
./tools/setup_env.sh     # JDKs + Android SDK under $HOME, no sudo (~4 GB)
./tools/build.sh         # run the test suite and build the APK
./tools/install.sh       # install on the connected phone
./tools/release_apk.sh   # build the installable release APK into the repository root
```

To prepare the phone: Settings → About phone → tap **Build number** seven times, then
Settings → System → Developer options → enable **USB debugging**, connect by USB and
accept the prompt.

On first launch the app asks for microphone and notification permission and offers to
exempt itself from battery optimisation. **Accept the battery exemption** — without it
Android usually kills the recording partway through the night.

On each new phone, run **Settings → Run microphone diagnostics** once. It listens to a
few coughs on every microphone route the phone offers and keeps the one where they are
recognised best. Which route works best differs between phones, and choosing wrong is
the main reason detection works on one model and fails on another.

---

## How it works

```
mic ─► noise gate ─► gain normalisation ─► YAMNet (TFLite) ─► smoothing ─► event assembly ─► SQLite
                          │
                          └─► 1024-d embedding ─► speaker attribution
```

YAMNet is the backbone: ~15 MB on device, it scores AudioSet's `Cough`, `Sneeze`,
`Snoring`, `Snort` and `Breathing` directly, and emits a per-frame embedding that the
personalisation layer uses. The noise gate skips inference on quiet frames — about
two-thirds of a night, and most of the battery cost.

The hard part is not classification. Eight hours of audio is ~60,000 inferences of
which nearly all are negative, so the metric that decides whether this is usable is
**false alarms per hour**, not F1. A detector at 95% clip precision can still invent 40
coughs a night, and a log nobody trusts is worse than no log.

### Storage

Raw frames are never stored. Three tiers instead:

| Table | What it holds |
|---|---|
| `sessions` | one row per night |
| `events` | each cough, sneeze and individual snore |
| `snore_episodes` | continuous runs of snoring, aggregated |
| `minute_rollup` | per-minute × class counters, so the timeline chart reads ~480 rows instead of scanning everything |
| `labels` | your "me / someone else / not real" verdicts, which train attribution |

Optional 2.5-second audio clips are saved per event, on-device only, with a retention
window. They exist so a false positive can be checked and corrected.

---

## Measured performance

**Real coughs, held out from tuning** — 200 COUGHVID recordings (crowdsourced from
users' own phones) placed in room noise at different levels, through the full on-device
chain ([`ml/diagnose_recall.py`](ml/diagnose_recall.py)):

| Condition | Recall before fixes | Recall now |
|---|---|---|
| Near (phone held close) | 72% | **87%** |
| Bedside (−15 dB) | 54% | **88%** |
| Far / low-sensitivity mic (−28 dB) | 24% | **88%** |
| Band-limited voice path | 26% | **76%** |

**On a real phone** — 12 held-out coughs played from a laptop speaker to a Galaxy S23
([`tools/device_recall_test.sh`](tools/device_recall_test.sh)):

| Build | Loud | Quiet (−20 dB) |
|---|---|---|
| Before | 1/12 | 0/12 |
| Now (CAMCORDER route) | 6/12 | 3–4/12 |

Laptop speakers are thin below ~200 Hz, so this rig understates real coughs; use it to
compare builds, routes and phones rather than as an absolute figure. The remaining
misses are coughs the model itself scores near zero — see
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the proposed next step.

**False alarms** — 4 hours of synthetic nights (real coughs and 24 kinds of household
distractor sound mixed into room noise), after tuning:

| Class | Precision | Recall | False alarms/hour |
|---|---|---|---|
| Cough | 0.975 | 0.817 | 0.75 |
| Sneeze | 0.857 | 0.250 | 0.25 |
| Snore | 0.989 | 0.972 | 0.50 |

Synthetic nights are a tuning target, not a measurement of a real bedroom, and the
sneeze row rests on 24 events. Sneeze recall is genuinely weak — ESC-50 provides only
40 sneeze clips.

---

## Accuracy, calibration, and telling people apart

**Calibration.** The noise floor is tracked continuously as a rolling 10th percentile,
so a fan switching on at 2 AM adapts instead of deafening the detector. Sensitivity is
one slider mapped onto operating points from the threshold sweep, because a raw 0–1
threshold is not a question anyone can answer.

**Rejecting other people's coughs.** This is an open research problem and no setting
solves it. Three layers, increasing in cost: a proximity prior from level and spectral
tilt (no setup, valid while the phone stays put); prototype matching on YAMNet
embeddings; and a logistic head trained on events labelled "me" or "someone else".
Expect roughly **75–85%** after ~50 labels in a two-adult bedroom, not 99%. Attribution
is stored *beside* each event and never used to delete one.

**What this is not.** It logs acoustic events. It is not a medical device and does not
screen for sleep apnoea, COVID, or any condition — apnoea in particular needs
respiratory-effort and oximetry signals a phone microphone does not have.

---

## Layout

```
android/
  app/              Compose UI, foreground service, permissions
  core-domain/      pure Kotlin, no Android imports — the part that ports to iOS
  core-audio/       AudioRecord capture, ring buffer, WAV clips
  core-inference/   TFLite YAMNet wrapper
  core-data/        Room schema, DAOs, export
ml/                 model export, synthetic nights, threshold tuning
scripts/            the original clip-level benchmark
tools/              environment setup, build, install
Datasets/           COUGHVID and ESC-50 (not in git — see docs/DEVELOPMENT.md)
```

`core-domain` is plain Kotlin/JVM with **zero Android dependencies**. It holds the
smoother, event assembler, episode aggregator, attribution scorer and data models —
everything that defines behaviour. Porting to iOS means writing SwiftUI screens, an
`AVAudioEngine` capture shim and a TFLite shim; the detection logic, thresholds and
schema come along unchanged.

---

## Tests

```
58 JVM tests      ./tools/build.sh
 8 device tests   cd android && ./gradlew :app:connectedDebugAndroidTest
```

The device tests are not optional extras. TFLite tensor shapes and the real SQLite
database can only fail on a phone, and two crashes shipped past the JVM suite because
of it. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
