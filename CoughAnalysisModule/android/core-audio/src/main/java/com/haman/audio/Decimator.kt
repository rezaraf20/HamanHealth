package com.haman.audio

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * 48 kHz -> 16 kHz decimation with an anti-aliasing low-pass.
 *
 * Exists for phones whose audio stack only delivers a full-band signal at the native
 * 48 kHz rate: asking those for 16 kHz can route capture through a narrowband voice path.
 * Capturing at 48 kHz and decimating ourselves sidesteps that. Stateful across chunks so
 * the filter has no seam at chunk boundaries.
 */
class Decimator3(taps: Int = 95) {
    private val h: FloatArray
    private val taps = taps
    // Doubled ring buffer: every sample is written at pos and pos+taps, so the most
    // recent `taps` samples are always contiguous and the filter needs no modulo.
    // Shifting a history array per input sample instead costs ~4.5M float copies a
    // second at 48 kHz - real CPU across an eight-hour night.
    private val ring: FloatArray
    private var pos = 0
    private var phase = 0

    init {
        require(taps % 2 == 1)
        // Windowed-sinc, cutoff 7.2 kHz at 48 kHz: keeps YAMNet's band (it uses up to
        // 7.5 kHz) while rejecting what would alias above the new 8 kHz Nyquist.
        val fc = 7200.0 / 48000.0
        val m = taps - 1
        h = FloatArray(taps) { n ->
            val x = n - m / 2.0
            val sinc = if (x == 0.0) 2 * fc else sin(2 * PI * fc * x) / (PI * x)
            val w = 0.42 - 0.5 * cos(2 * PI * n / m) + 0.08 * cos(4 * PI * n / m) // Blackman
            (sinc * w).toFloat()
        }
        val sum = h.sum()
        for (i in h.indices) h[i] /= sum
        ring = FloatArray(taps * 2)
    }

    /** @return number of 16 kHz samples written to [out] (about count / 3). */
    fun process(input: ShortArray, count: Int, out: ShortArray): Int {
        var written = 0
        for (i in 0 until count) {
            val v = input[i].toFloat()
            ring[pos] = v
            ring[pos + taps] = v
            pos = (pos + 1) % taps
            phase++
            if (phase == 3) {
                phase = 0
                // ring[pos .. pos+taps) is oldest -> newest.
                var acc = 0f
                val newest = pos + taps - 1
                for (k in 0 until taps) acc += h[k] * ring[newest - k]
                out[written++] = acc.toInt().coerceIn(-32768, 32767).toShort()
            }
        }
        return written
    }
}
