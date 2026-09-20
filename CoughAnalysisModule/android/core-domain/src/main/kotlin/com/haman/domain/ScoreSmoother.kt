package com.haman.domain

/**
 * Median-3 followed by an EMA, per class.
 *
 * Raw YAMNet scores are spiky frame to frame. The median kills single-frame outliers
 * (the main cause of spurious one-frame events) without the lag a longer window would
 * add; the EMA then takes the remaining jitter off. Order matters: EMA-then-median
 * would smear an outlier across three frames before removing it.
 */
class ScoreSmoother(private val alpha: Float = 0.5f) {
    private val n = AcousticClass.ALL.size
    private val h1 = FloatArray(n)
    private val h2 = FloatArray(n)
    private val ema = FloatArray(n)
    private var seen = 0

    fun smooth(raw: FloatArray, out: FloatArray = FloatArray(n)): FloatArray {
        for (i in 0 until n) {
            val med = median3(raw[i], h1[i], h2[i])
            val v = if (seen == 0) med else alpha * med + (1 - alpha) * ema[i]
            ema[i] = v
            out[i] = v
            h2[i] = h1[i]
            h1[i] = raw[i]
        }
        if (seen < 3) seen++
        return out
    }

    fun reset() {
        java.util.Arrays.fill(h1, 0f); java.util.Arrays.fill(h2, 0f)
        java.util.Arrays.fill(ema, 0f); seen = 0
    }

    private fun median3(a: Float, b: Float, c: Float): Float =
        maxOf(minOf(a, b), minOf(maxOf(a, b), c))
}
