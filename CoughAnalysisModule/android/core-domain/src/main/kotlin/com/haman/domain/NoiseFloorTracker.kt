package com.haman.domain

/**
 * Rolling estimate of the room's noise floor, as a low percentile of recent frame levels.
 *
 * A fixed threshold cannot work: a bedroom with a fan sits 20 dB above a silent one,
 * and the fan may switch on at 2 AM. Tracking a percentile (not a mean) keeps the
 * estimate on the *quiet* part of the distribution, so the occasional cough does not
 * drag the floor upward and desensitise the gate.
 */
class NoiseFloorTracker(
    private val windowFrames: Int = 125, // ~60 s at a 480 ms hop
    private val percentile: Float = 0.10f,
) {
    private val buf = FloatArray(windowFrames)
    private val scratch = FloatArray(windowFrames)
    private var count = 0
    private var idx = 0

    /** Until the window has filled, report a permissive floor so startup does not
     *  gate away real audio. */
    var floorDb: Float = -90f
        private set

    val isWarmedUp: Boolean get() = count >= windowFrames / 4

    fun update(rmsDb: Float): Float {
        buf[idx] = rmsDb
        idx = (idx + 1) % windowFrames
        if (count < windowFrames) count++

        System.arraycopy(buf, 0, scratch, 0, count)
        java.util.Arrays.sort(scratch, 0, count)
        val k = ((count - 1) * percentile).toInt().coerceIn(0, count - 1)
        floorDb = scratch[k]
        return floorDb
    }

    fun reset() {
        count = 0; idx = 0; floorDb = -90f
    }
}
