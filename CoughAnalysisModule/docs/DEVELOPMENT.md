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

## Why detection varies between phones

Low recall on some phones (A31, P30 Lite) and misses even on flagships were traced with
`ml/diagnose_recall.py` (real COUGHVID coughs through the full chain) and
`tools/device_recall_test.sh` (real coughs played to a real phone). Findings, in order of
impact:

1. **YAMNet is strongly level-sensitive.** The median cough score fell from 0.97 to 0.57
   when input was 13 dB quieter — roughly flagship mic vs budget mic. Fixed by
   `InputNormalizer`: each window's peak is boosted to −6 dBFS (boost-only, capped at
   +30 dB) before inference. Far-field recall 25% → 80%. Level evidence (gate, peakDb,
   attribution) still uses the un-normalised signal.
2. **The microphone route matters more than any threshold.** Same coughs, Galaxy S23:

   | Route | Received peak | Noise floor | Median cough score (quiet) |
   |---|---|---|---|
   | VOICE_RECOGNITION | −29.5 dB | −78.9 dB | 0.34 |
   | UNPROCESSED | −47.0 dB | −78.7 dB | 0.09 |
   | CAMCORDER | −30.4 dB | −68.4 dB | 0.57 |

   VOICE_RECOGNITION's noise suppression damages coughs; UNPROCESSED has no mic
   pre-gain; CAMCORDER keeps the cough intact. The default order is now CAMCORDER →
   VOICE_RECOGNITION → MIC → UNPROCESSED, and **Settings → Run microphone diagnostics**
   scores each route with the model while the user coughs and keeps the best one for
   that phone. Some phones also band-limit certain routes to ~4 kHz; the live stream is
   checked for that and the home screen warns if it happens.
3. **Median smoothing erased real coughs.** A cough seen confidently by one or two
   windows lost its peak in a median-3. Replaced with attack-release smoothing
   (`max(raw, ema)`), which keeps a peak on the frame it occurs and smooths only the
   decay.
4. **Timestamp jitter on the phone.** Frames were stamped from a sample count updated
   per 100 ms chunk, so durations wobbled around the tuned `minDurationMs` (exactly three
   hops) and borderline coughs that pass offline were dropped on-device. Frames are now
   stamped `k × 480 ms`, identical to the tuning harness. The parity test could not see
   this — its fixture uses exact timestamps — which is why device replays exist.
5. Smaller: speech suppression now needs *sustained* speech (4 of 5 frames), since a
   voiced cough can score high on Speech for one frame; and a sneeze must beat a cough by
   0.15 to win, since coughs are far more common at night.

The tuning nights were also rebuilt: ESC-50's cough clips are loud, clean bouts and
over-stated recall, so nights now use real COUGHVID coughs across 0 to −28 dB, and
COUGHVID is split so reported recall is measured on a held-out 20%.

### What limits recall now, and the proposed next step

With the fixes above, the phone and the Python replay produce identical events from the
same audio, so the pipeline behaves on-device exactly as tuned. The remaining misses are
coughs YAMNet's own `Cough` output scores near zero on that phone's audio — no threshold
can recover those without flooding false alarms.

The candidate fix is a small cough-specific read-out trained on YAMNet's 1024-d
embeddings (which the app already computes every frame; applying it is one dot product).
`ml/exp_cough_head.py` is the feasibility check. On the S23 captures it lifted quiet
coughs from 3/12 to 8/12 on CAMCORDER and from 4/12 to 10/12 on VOICE_RECOGNITION, and
improved frame-level AUC on 7 of 10 captures. Not shipped yet, for two reasons:

- its false-alarm cost over full nights has not been measured;
- its training negatives currently include ESC-50, which is **CC BY-NC**. A shipped model
  trained on that data is a more direct derivative than tuned thresholds; decide on the
  licensing, or train the negatives on permissively licensed audio instead.

### Testing a new phone

```bash
./tools/install.sh                                   # debug build on the phone
./tools/device_recall_test.sh a31                    # default route
./tools/device_recall_test.sh a31_cam CAMCORDER@16k  # force a route
.venv/bin/python ml/analyze_capture.py results/device/a31.pcm --dir ml/artifacts/playback
```

Place the phone next to the Mac speaker. The test plays 24 held-out coughs, scores what
the phone logged, and pulls the raw capture; `analyze_capture.py` then shows per cough
how loud it arrived, how much high-frequency content survived, whether the gate opened
and what the model scored — i.e. where on that phone each cough is lost. Raw captures
are only written by debug builds, and only while `files/debug_raw` exists on the phone.

Laptop speakers are thin below ~200 Hz, so absolute numbers from this test understate
real coughs somewhat. Use it to compare routes, builds and phones against each other.

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
