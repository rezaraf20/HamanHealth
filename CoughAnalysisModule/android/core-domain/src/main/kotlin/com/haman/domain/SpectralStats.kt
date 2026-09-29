package com.haman.domain

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.sin

/**
 * Band energies of a captured signal, used to tell a full-band microphone path from a
 * band-limited one.
 *
 * Some phones route certain audio sources through voice processing that cuts everything
 * above ~4 kHz. Much of a cough's energy lives above that, and on band-limited input
 * recall fell to 26-43% versus 72% full-band (results/recall_diagnosis.json). The fix is
 * choosing a different source; this is how the source probe tells them apart.
 *
 * Welch-averaged power spectrum with a Hann window; no dependencies so it stays in the
 * portable module.
 */
object SpectralStats {
    const val LOW_BAND_LO = 300f
    const val LOW_BAND_HI = 3400f
    const val HIGH_BAND_LO = 4200f
    const val HIGH_BAND_HI = 7400f

    /** A path whose high band sits this far below its low band is treated as band-limited.
     *  Full-band capture of room noise lands around -10 to -30 dB; a telephony low-pass
     *  leaves little but quantisation noise and lands far below this. */
    const val BAND_LIMITED_BELOW_DB = -45f

    data class Bands(val lowDb: Float, val highDb: Float) {
        val highMinusLowDb: Float get() = highDb - lowDb
        val looksBandLimited: Boolean get() = highMinusLowDb < BAND_LIMITED_BELOW_DB
    }

    fun bands(x: FloatArray, sampleRate: Int, fftSize: Int = 1024): Bands {
        require(fftSize and (fftSize - 1) == 0) { "fftSize must be a power of two" }
        val power = DoubleArray(fftSize / 2 + 1)
        val window = DoubleArray(fftSize) { 0.5 - 0.5 * cos(2 * PI * it / (fftSize - 1)) }
        val re = DoubleArray(fftSize)
        val im = DoubleArray(fftSize)
        var segments = 0
        var start = 0
        while (start + fftSize <= x.size) {
            for (i in 0 until fftSize) { re[i] = x[start + i] * window[i]; im[i] = 0.0 }
            fft(re, im)
            for (k in power.indices) power[k] += re[k] * re[k] + im[k] * im[k]
            segments++
            start += fftSize / 2
        }
        if (segments == 0) return Bands(-160f, -160f)
        val binHz = sampleRate.toFloat() / fftSize
        fun bandDb(lo: Float, hi: Float): Float {
            var sum = 0.0
            var n = 0
            for (k in power.indices) {
                val f = k * binHz
                if (f in lo..hi) { sum += power[k] / segments; n++ }
            }
            val mean = if (n > 0) sum / n else 0.0
            return if (mean <= 1e-20) -160f else (10 * log10(mean)).toFloat()
        }
        return Bands(bandDb(LOW_BAND_LO, LOW_BAND_HI), bandDb(HIGH_BAND_LO, HIGH_BAND_HI))
    }

    /** In-place iterative radix-2 FFT. */
    internal fun fft(re: DoubleArray, im: DoubleArray) {
        val n = re.size
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) { j = j xor bit; bit = bit shr 1 }
            j = j xor bit
            if (i < j) {
                var t = re[i]; re[i] = re[j]; re[j] = t
                t = im[i]; im[i] = im[j]; im[j] = t
            }
        }
        var len = 2
        while (len <= n) {
            val ang = -2 * PI / len
            val wr = cos(ang); val wi = sin(ang)
            var i = 0
            while (i < n) {
                var cr = 1.0; var ci = 0.0
                for (k in 0 until len / 2) {
                    val ur = re[i + k]; val ui = im[i + k]
                    val vr = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci
                    val vi = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr
                    re[i + k] = ur + vr; im[i + k] = ui + vi
                    re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi
                    val nr = cr * wr - ci * wi
                    ci = cr * wi + ci * wr
                    cr = nr
                }
                i += len
            }
            len = len shl 1
        }
    }
}
