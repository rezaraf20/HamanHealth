# Haman — Sleep Acoustic Event Monitor

A module that listens overnight, detects **coughs, sneezes and snoring**, and logs
them to a local database. Android first, structured so the detection core moves to
iOS later without a rewrite.

---

## 1. The problem this actually is

The existing benchmark in `results/benchmark.json` scores **clips**: given a 5-second
file, is there a cough in it. The product is a different problem: given **8 continuous
hours**, emit a timestamped list of events.

That difference drives every decision below.

| Clip classification | Overnight monitoring |
|---|---|
| Balanced-ish classes | ~99.99% of frames are negative |
| Metric: F1 / ROC-AUC | Metric: **false alarms per hour** |
| Model runs once | Model runs ~60,000 times per night |
| Plugged in | Battery must survive 8h |
| One speaker, deliberate | Two sleepers, incidental, distant |

A detector at 95% precision on clips can still produce 50 false coughs a night. So the
headline metric for this project is **FA/hour, with a target under 1**, measured on
synthetic night audio — not F1 on COUGHVID.

### Why not CoughKit, despite it winning the benchmark

`results/benchmark.json` gives CoughKit F1 0.959 / ROC-AUC 0.992 vs YAMNet's 0.850 /
0.865. That comparison should not be used to pick the on-device model:

1. **Probable train/test contamination.** CoughKit is a COUGHVID-era cough classifier
   being evaluated on COUGHVID. The number is close to self-evaluation.
2. **Weak labels.** `cough_detected` is itself an automated confidence score, not
   ground truth. The benchmark thresholds it at 0.5 and calls it a label.
3. **Wrong domain.** COUGHVID is people deliberately coughing into a handset. The
   target domain is incidental sounds 1–2 m away, through bedding, at night.
4. **Wrong label set.** CoughKit does cough only. Snoring and sneezing are half the product.
5. **Wrong runtime.** XGBoost over librosa features means reimplementing librosa's
   mel/MFCC pipeline in Kotlin bit-exactly. That is a large, bug-prone effort.

**YAMNet is the backbone**: ~4 MB TFLite, runs ~500x realtime, natively has
`Snoring`(38), `Snort`(41), `Cough`(42), `Sneeze`(44), `Breathing`(36), `Speech`(0),
and — the important part — emits a **1024-d embedding per frame** that the
personalization layer is built on.

CoughKit stays useful as a **second opinion in offline evaluation**, not on the phone.

---

## 2. Pipeline

```
 Mic ─ AudioRecord 16 kHz mono PCM16, UNPROCESSED source
  │
  ├─► Ring buffer (rolling 10 s)  ──────────────┐  (pre-roll, so a clip includes
  │                                             │   the event's onset)
  ▼                                             │
 Frame slicer  0.96 s window / 0.48 s hop       │
  │                                             │
  ▼                                             │
 Noise gate   adaptive floor, p10 over 60 s     │   skips inference in true silence
  │           (only gates BELOW floor+6 dB)     │   → ~60% of frames, big battery win
  ▼                                             │
 YAMNet TFLite ──► 521 scores + 1024-d embedding│
  │                                             │
  ▼                                             │
 Class reducer  → {cough, sneeze, snore, breathing, speech, other}
  │
  ▼
 Temporal smoother   median-3 + EMA, per class
  │
  ▼
 Event assembler   hysteresis (on/off thresholds), min duration,
  │                merge gap, refractory period, bout grouping
  ▼
 Attribution    proximity prior (+ personalized head once labels exist)
  │
  ▼
 Writer  ──► Room/SQLite  (batched transaction every 5 s)  ◄── clip from ring buffer
```

**Cough and sneeze are arbitrated, not scored independently.** Measured on ESC-50,
sneeze clips reach 1.00 on YAMNet's `Cough` output, so without arbitration one sneeze is
logged as both. The winner-take-all threshold is
`min(exclusionThreshold, onThreshold_cough, onThreshold_sneeze)` — not a fixed absolute
value. A fixed 0.20 against a tuned cough on-threshold of 0.10 left a band where a cough
event could open without ever being arbitrated, which on-device logged one sound as both
a cough and a sneeze at the same millisecond.

### Why hysteresis and not a single threshold
A single threshold makes an event flicker on/off across frames and produces 5 events
where there is 1. Onset uses a high threshold, offset a lower one. Cough is a burst;
snoring is periodic and needs a long merge gap so one breath cycle doesn't become
two events.

Per-class assembly parameters (initial values, tuned in §5):

| Class | On | Off | Min dur | Merge gap | Refractory | Max dur |
|---|---|---|---|---|---|---|
| Cough | 0.45 | 0.25 | 0.60 s | 0.72 s | 0.25 s | 3 s |
| Sneeze | 0.40 | 0.22 | 0.60 s | 0.96 s | 0.50 s | 3 s |
| Snore | 0.35 | 0.20 | 0.80 s | 1.50 s | 0.50 s | 6 s |

**Max duration is a hard ceiling, and it is load-bearing.** A low off-threshold means
an event, once opened, may never fall back below it — ambient room noise alone sustains
it. The first on-device run produced a 9.6-second "cough" for exactly this reason.
Physiology bounds these sounds, so the detector does too. The tuning sweep also floors
the off-threshold at 0.12 (`ml/tune_thresholds.py`), because settings below that scored
well only by emitting one enormous event that overlapped the ground truth.

**These timings are quantised by the 0.48 s frame hop**, which is easy to get wrong and
fails silently. A `minDuration` at or below one hop can never reject a single-frame
spike, because one frame already spans a whole hop; a `mergeGap` at or below one hop can
never bridge a dipped frame. Both must exceed 0.48 s to do anything at all.
`DetectorConfig.validatedFor()` enforces this on every config, including tuned ones
loaded from `ml/`.

### The microphone source matters more than it looks
`MediaRecorder.AudioSource.MIC` applies automatic gain control and noise suppression.
AGC destroys absolute level, and level is what the proximity prior (§4) runs on — a
quiet distant cough gets amplified to look like a near one. The capture layer requests
`UNPROCESSED` when `PROPERTY_SUPPORT_AUDIO_SOURCE_UNPROCESSED` is true, else
`VOICE_RECOGNITION` (AGC off on most devices), and records which one it got in the
session row so analysis can account for it.

---

## 3. Storage — "efficient" means not storing frames

Naive logging writes one row per frame: 60,000 rows per night, and snoring alone can
fire on every breath — ~500 snore events a night, which is both useless to read and
expensive to query.

Three tiers instead:

```
sessions        one row per night
  └─ events          discrete: each cough, sneeze, individual snore
  └─ snore_episodes  aggregate: continuous snoring runs (start, end, count, intensity)
  └─ minute_rollup   per-minute × class counters — powers the timeline chart
```

`minute_rollup` is the key to a responsive UI: drawing an 8-hour timeline reads 480
rows, not 60,000. Raw frames are never persisted.

```sql
sessions(id, started_at, ended_at, device_model, app_version,
         audio_source, noise_floor_db, config_json, status)

events(id, session_id, class, started_at_ms, ended_at_ms,
       peak_score, mean_score, peak_db, snr_db, bout_id,
       subject_label, subject_confidence, clip_path, embedding BLOB)
  INDEX (session_id, started_at_ms), (class, started_at_ms)

snore_episodes(id, session_id, start_ms, end_ms, snore_count,
               mean_intensity_db, snores_per_hour)

minute_rollup(session_id, minute_epoch, class, count, max_score, mean_db)
  PRIMARY KEY (session_id, minute_epoch, class)

labels(event_id, user_label, labeled_at)   -- feeds personalization
```

Write path: WAL mode, events buffered and flushed in **one transaction every 5 s**.
Per-event commits at 3 AM on a sleeping CPU are a measurable battery cost.

Embeddings are int8-quantized with a per-vector scale: 1 KB instead of 4 KB, ~500 KB
per night, and prunable independently of the events.

Audio clips: 2 s (0.75 s pre-roll + event + tail) at 16 kHz, on-device only, in
app-private storage, auto-deleted after a configurable retention window. They exist so
a false positive can be *audited* and *labeled* — which is the only path to §4.

---

## 4. Rejecting other people's coughs

This is the hardest requirement and deserves a straight answer: **speaker
identification on non-speech sounds is an open research problem.** There is no
configuration that makes it solved. Three layers, in increasing cost and accuracy:

**Layer 1 — proximity prior (ships first, no enrollment).**
The phone sits on one person's nightstand. A partner's cough is quieter, more
reverberant, and spectrally duller (air absorbs high frequencies with distance).
Features: peak dB, direct-to-reverberant ratio, spectral tilt. Cheap, no setup, and
effective *as long as the phone stays put* — which is why the level calibration in §5
exists and why moving the phone invalidates it.

**Layer 2 — embedding prototype (enrollment).**
User records a handful of coughs at setup; store the YAMNet embeddings; score cosine
similarity at runtime. Caveat worth internalizing: YAMNet embeddings are trained to
separate *event types*, not *people*. They carry some timbre, so this helps, but alone
it will not reliably separate two adults.

**Layer 3 — personalized head (the one that actually works).**
The review UI lets the user mark logged events **mine / not mine / unsure**. Those
labels train an on-device logistic regression over `[embedding(1024) ‖ proximity
features]`. This learns *this* person, *this* partner, *this* room, *this* phone
position — which is why it beats any general-purpose model.

Realistic expectation: **~75–85%** subject accuracy in a two-adult bedroom after
~50 labels. Not 99%. The DB therefore stores `subject_label` **alongside** the event
rather than filtering on it, so attribution can be revised or retrained later without
losing the event itself. Never discard an event because of a low attribution score.

---

## 5. Calibration

1. **Noise floor** — 30 s of room ambience at session start sets the gate. Re-estimated
   continuously as a rolling 10th percentile, so a fan switching on mid-night adapts.
2. **Sensitivity** — one user-facing slider, mapped to precision/recall operating points
   taken from the threshold sweep in §6. Not a raw 0–1 threshold: "fewer misses /
   fewer false alarms" is the decision the user can actually make.
3. **Level reference** — optional: cough 5× from your normal sleeping position. Sets
   the expected near-field dB band for Layer 1.
4. **Mic path** — logged per session (§2) so results stay comparable across devices.

---

## 6. Validation — where the existing Python work pays off

ESC-50 is already in `Datasets/` and contains exactly the four relevant categories:
**coughing, sneezing, snoring, breathing** — 40 clips each — plus 46 categories of
natural negatives that are realistic bedroom false-positive sources (clock alarm,
door knock, vacuum, washing machine, wind, rain).

The harness in `ml/`:

- `export_yamnet_tflite.py` — TF-Hub YAMNet → `.tflite`, verified numerically against
  the TF-Hub original so phone and desktop agree.
- `night_mixer.py` — **synthetic nights**: mixes ESC-50 events into hours of low-level
  room noise at varied SNR and simulated distance (level + lowpass + reverb),
  producing audio *with exact ground-truth timestamps*.
- `eval_night.py` — runs the **same event-assembly logic as the app** over synthetic
  nights and reports event-level precision/recall, onset timing error, and **FA/hour**.
- `tune_thresholds.py` — sweeps the §2 parameters, emits `detector_config.json`, which
  is shipped in the app's assets.

This is the part that makes the numbers trustworthy: the app and the evaluation run
the same parameters, and the parameters are chosen against night-shaped audio rather
than clips.

---

## 7. Module layout and the iOS path

```
Haman/
├── android/
│   ├── app/              Compose UI, DI, Android entry points
│   ├── core-domain/      ◄── PURE Kotlin. No Android imports. The part that ports.
│   ├── core-audio/       AudioRecord capture, ring buffer
│   ├── core-inference/   TFLite YAMNet wrapper
│   └── core-data/        Room, DAOs, export
├── ml/                   model export + night-shaped validation harness
├── scripts/              existing clip benchmark (kept)
└── Datasets/             unchanged
```

`core-domain` holds the smoother, the event assembler, the episode aggregator, the
attribution scorer, the config schema and the data models — everything that defines
*behavior* — and is enforced to have **zero Android dependencies**. It is a plain
Kotlin/JVM module today and becomes a Kotlin Multiplatform module by changing its
Gradle plugin.

The iOS port is then bounded to: SwiftUI screens, an `AVAudioEngine` capture shim, and
a TFLite (or Core ML) inference shim — three adapters behind interfaces that already
exist. The detection behavior, the thresholds, and the schema come along unchanged.
That is the whole reason for the module split.

---

## 8. Known risks

| Risk | Mitigation |
|---|---|
| **Doze / OEM battery killers** (Xiaomi, Samsung, OnePlus) silently kill the service — the #1 practical failure mode | Foreground service + partial wakelock + battery-optimization exemption prompt + watchdog that logs restarts so gaps are visible rather than silent |
| Fan / AC hum classified as snoring | Adaptive floor; snore requires periodicity, not just a score |
| Bedding rustle classified as cough | Hysteresis + min duration; tuned against ESC-50 negatives |
| Phone moved mid-night breaks proximity prior | Detect level-distribution shift, flag the session |
| Mic seized by a phone call | Detect, pause, log an explicit gap — never silently lose time |
| Clip storage privacy | On-device only, app-private, retention window, one-tap purge |

## 9. Scope boundary

This logs acoustic events during sleep. It is **not** a medical device and does not
screen for sleep apnea, COVID, or any condition. Apnea specifically requires
respiratory-effort and oximetry signals a phone microphone does not have. The
`instructions/PROJECT.md` rule against diagnostic claims carries over unchanged.
