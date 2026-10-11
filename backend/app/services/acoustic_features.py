"""
Per-event measurements calculated from the event's audio clip.

Why on the server, from the clip: the phone's own numbers (start/end, peak_db) are
tied to the detector's 0.48 s analysis frames and to the phone's mic gain. With the
clip stored, every measurement here can be improved and re-run over all past events
(`python -m app.jobs.compute_features`) without a new app release. Each version of the
method writes its own row in cough_event_features; bump METHOD when results change.

acoustic-v1, all on a 20 ms window / 10 ms hop envelope:
  acoustic_start_at / _end_at  first/last moment the sound is within 20 dB of its
                               loudest point (and at least 6 dB above background), searched
                               around the detector's start/end — 10 ms resolution
  peak_dbfs                    loudest sample, dB relative to full scale
  rms_dbfs                     average level over the sound
  noise_floor_dbfs             background level of the clip (10th percentile of the envelope)
  prominence_db                loudest envelope point minus background: a magnitude that
                               does not depend on the phone's mic gain
  crest_factor_db              peak minus RMS: how sharp / explosive the sound is
  spectral_centroid_hz         "brightness" of the sound
  low_freq_ratio               share of energy below 1 kHz
  zero_crossing_rate           sign changes per second (noisy vs. tonal)
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import io
import wave

import numpy as np

METHOD = "acoustic-v1"

_WIN_S = 0.020
_HOP_S = 0.010
_FLOOR = 1e-10            # avoids log(0) on digital silence
_SEARCH_MARGIN_S = 0.48   # detector boundaries are one frame hop coarse
_DROP_FROM_PEAK_DB = 20.0
_MIN_ABOVE_NOISE_DB = 6.0


@dataclass
class Features:
    acoustic_start_at: datetime | None
    acoustic_end_at: datetime | None
    acoustic_duration_ms: int | None
    peak_dbfs: float
    rms_dbfs: float
    noise_floor_dbfs: float
    prominence_db: float
    crest_factor_db: float
    spectral_centroid_hz: float
    low_freq_ratio: float
    zero_crossing_rate: float

    def as_columns(self) -> dict:
        return asdict(self)


def _db(x: float) -> float:
    return float(10 * np.log10(max(x, _FLOOR)))


def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return pcm.astype(np.float64) / 32768.0, rate


def compute(
    wav_bytes: bytes,
    clip_started_at: datetime,
    event_start: datetime,
    event_end: datetime | None,
) -> Features | None:
    """None when the event does not overlap the clip (nothing to measure)."""
    x, rate = read_wav(wav_bytes)
    n = len(x)
    win, hop = int(_WIN_S * rate), int(_HOP_S * rate)
    if n < win:
        return None

    def idx(t: datetime) -> int:
        return int(round((t - clip_started_at).total_seconds() * rate))

    end = event_end or event_start
    # Search a little beyond the detector's boundaries, which are frame-quantised.
    margin = int(_SEARCH_MARGIN_S * rate)
    lo, hi = max(0, idx(event_start) - margin // 2), min(n, idx(end) + margin)
    if hi - lo < win:
        return None

    # Envelope over the whole clip: frame k covers [k*hop, k*hop + win).
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    env_db = 10 * np.log10(np.maximum((frames ** 2).mean(axis=1), _FLOOR))
    noise_floor = float(np.percentile(env_db, 10))

    k_lo = lo // hop
    k_hi = min(len(env_db), max(k_lo + 1, (hi - win) // hop + 1))
    if k_lo >= k_hi:
        return None
    seg_env = env_db[k_lo:k_hi]
    k_peak = int(np.argmax(seg_env))
    peak_env = float(seg_env[k_peak])
    threshold = max(peak_env - _DROP_FROM_PEAK_DB, noise_floor + _MIN_ABOVE_NOISE_DB)

    # Walk outwards from the loudest frame while the sound stays above the threshold.
    above = seg_env >= threshold
    a = b = k_peak
    if above[k_peak]:
        while a > 0 and above[a - 1]:
            a -= 1
        while b < len(seg_env) - 1 and above[b + 1]:
            b += 1
        s0 = (k_lo + a) * hop
        s1 = min(n, (k_lo + b) * hop + win)
        start_at = clip_started_at + timedelta(seconds=s0 / rate)
        end_at = clip_started_at + timedelta(seconds=s1 / rate)
        duration_ms = int(round((s1 - s0) * 1000 / rate))
    else:
        # Sound never clears the background by 6 dB: measure the detector's window.
        s0, s1 = lo, hi
        start_at = end_at = None
        duration_ms = None

    sound = x[s0:s1]
    peak = float(np.max(np.abs(sound)))
    rms_power = float(np.mean(sound ** 2))

    spectrum = np.abs(np.fft.rfft(sound * np.hanning(len(sound)))) ** 2
    freqs = np.fft.rfftfreq(len(sound), 1 / rate)
    total = float(spectrum.sum())
    centroid = float((freqs * spectrum).sum() / total) if total > 0 else 0.0
    low_ratio = float(spectrum[freqs < 1000].sum() / total) if total > 0 else 0.0
    zc = int(np.count_nonzero(np.diff(np.signbit(sound))))

    return Features(
        acoustic_start_at=start_at,
        acoustic_end_at=end_at,
        acoustic_duration_ms=duration_ms,
        peak_dbfs=round(_db(peak ** 2), 2),
        rms_dbfs=round(_db(rms_power), 2),
        noise_floor_dbfs=round(noise_floor, 2),
        prominence_db=round(peak_env - noise_floor, 2),
        crest_factor_db=round(_db(peak ** 2) - _db(rms_power), 2),
        spectral_centroid_hz=round(centroid, 1),
        low_freq_ratio=round(low_ratio, 4),
        zero_crossing_rate=round(zc * rate / max(1, len(sound)), 1),
    )
