# Development

## Environment

`./tools/setup_env.sh` installs everything under `$HOME`, without sudo:

| | |
|---|---|
| JDK 17 | Gradle toolchain |
| JDK 21 | runs Gradle itself |
| Android SDK | platform 37.2, build-tools 37.0.0, platform-tools |
| Gradle 9.7.1 / AGP 9.4.1 | via the wrapper |

Homebrew is deliberately not used — installing it needs sudo. Android Studio is
optional; the whole build works from the CLI.

Because the JDKs live in `~/Library/Java` (where Gradle's macOS auto-detection does not
look), their paths are written into `android/gradle.properties` as
`org.gradle.java.installations.paths`. Re-run `setup_env.sh` if they move.

## Python side

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install --no-deps -e ./models/audiokit
.venv/bin/python -m pip install --no-deps -e ./models/coughkit
```

`models/audiokit` and `models/coughkit` are third-party clones with their own git
history and are not tracked here. They are only needed to re-run the original
clip benchmark in `scripts/` — the Android app and the tuning harness do not use them.

## Datasets

Not in git (~31 GB). The harness expects:

```
Datasets/ESC-50-master/     ESC-50, from github.com/karolpiczak/ESC-50
Datasets/COUGHVID/          COUGHVID .wav + .json pairs
```

ESC-50 is what matters for this module — it contains `coughing`, `sneezing`, `snoring`
and `breathing` at 40 clips each, plus 46 other categories that serve as realistic
bedroom false-positive sources. COUGHVID is only used by the original benchmark.

## Build and test

```bash
./tools/build.sh                                  # JVM tests + debug APK
./tools/install.sh                                # install on a connected phone
cd android && ./gradlew :app:connectedDebugAndroidTest   # on-device tests
```

Gradle uninstalls the app after a connected-test run, so re-run `./tools/install.sh`
afterwards.

### Why there are on-device tests

Two crashes shipped past a green JVM suite, because neither failure is reachable
without a real device:

- `execSQL("PRAGMA journal_mode=WAL")` throws, because that pragma **returns a row** and
  `execSQL` rejects any statement that returns data. It fired on the first database
  access — app startup — so the app died before drawing anything.
- The exported model returns rank-1 tensors `[521]` / `[1024]`, but the Kotlin wrapper
  allocated `Array(1){FloatArray(521)}`, i.e. `[1, 521]`. The UI looked healthy while
  the capture thread was dead.

`app/src/androidTest/` now covers model loading, tensor shapes, non-degenerate
embeddings, stale-buffer detection, database open, WAL and foreign keys actually being
on, and cascade delete.

## Re-tuning the detector

Thresholds in `android/app/src/main/assets/detector_config.json` are generated, not
hand-written. To regenerate:

```bash
.venv/bin/python ml/night_mixer.py --nights 6 --minutes 30   # synthesise + score nights
.venv/bin/python ml/tune_thresholds.py --budget 1.0          # sweep -> detector_config.json
.venv/bin/python ml/parity_fixture.py                        # refresh the Kotlin test fixture
./tools/build.sh                                             # rebuild with the new config
```

The objective is **maximise recall subject to a false-alarm budget**, not F1.

`--budget` is false alarms per hour per class. Lower it if the log feels untrustworthy;
raise it if too much is being missed.

## The detection logic exists twice

`android/core-domain` (Kotlin) runs on the phone. `ml/assembler.py` is the same
algorithm in Python, used to tune thresholds over hours of audio in seconds.

Duplication is a real cost, accepted because the alternative — tuning against logic
that differs from what ships — is worse and fails silently.

`ml/parity_fixture.py` freezes a slice of real scores plus the Python output;
`AssemblerParityTest` replays it in Kotlin and asserts identical events. **Any change to
one implementation must be made in the other and the fixture regenerated**, or that test
fails. It has already caught three genuine divergences:

1. `np.percentile` interpolates between samples; the Kotlin noise floor indexes into a
   sorted window without interpolating.
2. On the phone a gated frame runs no inference, so **zeros** enter the smoother and
   drag down following frames. Smoothing raw scores and masking afterwards gives
   different events.
3. A per-class duration ceiling that silently fell back to a default on one side.

## Parameter invariants

These fail silently rather than loudly, so `DetectorConfig.validatedFor()` enforces
them and `ConfigValidationTest` guards them:

- `minDurationMs` and `mergeGapMs` must exceed one frame hop (480 ms). One frame already
  spans a whole hop, so a smaller `minDuration` can never reject a single-frame spike
  and a smaller `mergeGap` can never bridge a dipped frame.
- `maxDurationMs` must exceed `minDurationMs`. It is a hard ceiling on a single event:
  with a low off-threshold, ambient room noise alone can keep an event open forever —
  the first on-device run produced a 9.6-second "cough".
- Cough/sneeze arbitration uses `min(exclusionThreshold, on_cough, on_sneeze)`, not a
  fixed value. A fixed 0.20 against a tuned cough on-threshold of 0.10 left a band where
  a cough event opened unarbitrated, and one sneeze was logged as both a sneeze and a
  cough at the same millisecond.

## Inspecting a recorded night

```bash
adb shell "run-as com.haman.sleep cat databases/haman.db" > haman.db
sqlite3 haman.db "select cls, count(*) from events group by cls;"
```

Or use **Export** in the session screen, which writes CSV and JSON to the app's external
files directory. The export format is the integration contract: stable column names,
epoch-millisecond timestamps, one row per event. Embeddings and clip paths are
deliberately excluded — they are device-local and privacy-sensitive.
