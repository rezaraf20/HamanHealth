package com.haman.domain

import kotlin.math.abs
import kotlin.math.pow

/**
 * Per-window gain normalisation applied to the model's input, and ONLY to its input.
 *
 * YAMNet is strongly level-sensitive. On real COUGHVID coughs the median cough score
 * falls from 0.97 to 0.57 when the signal is 13 dB quieter - roughly the gap between a
 * flagship phone's microphone and a budget one's - and recall on quiet coughs collapsed
 * from 72% to 24% (results/recall_diagnosis.json). Boosting each window's peak to a
 * fixed target made recall close to level-invariant (far-field 25% -> 80%) for a false
 * alarm cost of ~0.25/hour.
 *
 * Boost-only and capped: loud audio passes through untouched, and a near-silent window
 * is not amplified without limit. The noise gate, peakDb, SNR and the proximity prior
 * all keep using the UN-normalised level - that is the evidence of distance, and
 * normalising it away would blind the attribution layer.
 *
 * Mirrors frontend.normalise in ml/.
 */
object InputNormalizer {
    const val TARGET_PEAK = 0.5f           // -6 dBFS
    const val MAX_GAIN_DB = 30f
    private val MAX_GAIN = 10f.pow(MAX_GAIN_DB / 20f)

    /**
     * @param out receives the normalised samples; may be the same array as [frame].
     * @return the gain applied (>= 1).
     */
    fun normalize(frame: FloatArray, out: FloatArray): Float {
        var peak = 0f
        for (x in frame) { val a = abs(x); if (a > peak) peak = a }
        val gain = (TARGET_PEAK / (peak + 1e-9f)).coerceIn(1f, MAX_GAIN)
        for (i in frame.indices) out[i] = frame[i] * gain
        return gain
    }
}
