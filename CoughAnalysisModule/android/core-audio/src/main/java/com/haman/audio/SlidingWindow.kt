package com.haman.audio

/**
 * Produces overlapping analysis windows from a stream of samples.
 *
 * YAMNet consumes 0.975 s windows every 0.48 s, so consecutive windows overlap by
 * about half. The overlap is not optional: a cough lasting 300 ms could otherwise
 * straddle a window boundary and score weakly in both halves.
 */
class SlidingWindow(
    private val windowSize: Int,
    private val hopSize: Int,
) {
    private val window = FloatArray(windowSize)
    private var pos = 0
    private var primed = false

    /** Feed samples; [onWindow] fires once per completed hop. The array it receives is
     *  reused, so consumers must not retain it. */
    fun append(samples: FloatArray, count: Int, onWindow: (FloatArray) -> Unit) {
        var i = 0
        while (i < count) {
            val take = minOf(count - i, windowSize - pos)
            System.arraycopy(samples, i, window, pos, take)
            pos += take
            i += take
            if (pos == windowSize) {
                onWindow(window)
                primed = true
                // Slide by one hop, keeping the overlap.
                System.arraycopy(window, hopSize, window, 0, windowSize - hopSize)
                pos = windowSize - hopSize
            }
        }
    }

    fun reset() { pos = 0; primed = false }
}
