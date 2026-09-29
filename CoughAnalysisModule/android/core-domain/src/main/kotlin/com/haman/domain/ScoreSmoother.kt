package com.haman.domain

/**
 * Exponential moving average, per class.
 *
 * This used to be a median-3 followed by the EMA. The median was removed on evidence:
 * on real coughs it discarded 14-35% of detections YAMNet had actually made. A cough is
 * short, a strong one is often seen confidently by only one or two overlapping windows,
 * and a median over three frames erases exactly that peak (results/recall_diagnosis.json).
 *
 * Transient rejection now rests on minDurationMs and the hysteresis thresholds, and the
 * thresholds were re-tuned with this smoother in place, so the false-alarm budget still
 * holds. Mirrors assembler.smooth in ml/.
 */
class ScoreSmoother(
    private val alpha: Float = 0.5f,
    /** max(raw, ema): instant attack, smoothed release. See DetectorConfig.attackRelease. */
    private val attackRelease: Boolean = true,
) {
    private val n = AcousticClass.ALL.size
    private val ema = FloatArray(n)
    private var seen = false

    fun smooth(raw: FloatArray, out: FloatArray = FloatArray(n)): FloatArray {
        for (i in 0 until n) {
            var v = if (!seen) raw[i] else alpha * raw[i] + (1 - alpha) * ema[i]
            if (attackRelease && raw[i] > v) v = raw[i]
            ema[i] = v
            out[i] = v
        }
        seen = true
        return out
    }

    fun reset() {
        java.util.Arrays.fill(ema, 0f)
        seen = false
    }
}
