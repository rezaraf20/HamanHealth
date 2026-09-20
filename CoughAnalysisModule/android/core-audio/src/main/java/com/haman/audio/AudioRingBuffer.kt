package com.haman.audio

/**
 * Rolling buffer of recent PCM, so a clip can include audio from *before* the event
 * was detected.
 *
 * Detection necessarily lags the sound: an event is only confirmed once enough frames
 * have passed to satisfy minDuration. Without pre-roll, every saved clip would start
 * mid-cough and be useless for the very thing clips exist for - checking whether a
 * detection was real.
 */
class AudioRingBuffer(private val capacity: Int) {
    private val buf = ShortArray(capacity)
    private var writeIndex = 0
    private var totalWritten = 0L

    @Synchronized
    fun write(samples: ShortArray, count: Int) {
        var i = 0
        while (i < count) {
            val take = minOf(count - i, capacity - writeIndex)
            System.arraycopy(samples, i, buf, writeIndex, take)
            writeIndex = (writeIndex + take) % capacity
            i += take
        }
        totalWritten += count
    }

    /** Absolute index of the next sample to be written. */
    @Synchronized
    fun position(): Long = totalWritten

    /**
     * Copy [count] samples ending at absolute index [endSample].
     * @return null if that range has already been overwritten.
     */
    @Synchronized
    fun read(endSample: Long, count: Int): ShortArray? {
        val start = endSample - count
        if (count > capacity || start < 0) return null
        if (totalWritten - start > capacity) return null // already overwritten
        val out = ShortArray(count)
        var startIndex = ((start % capacity) + capacity).toInt() % capacity
        var i = 0
        while (i < count) {
            val take = minOf(count - i, capacity - startIndex)
            System.arraycopy(buf, startIndex, out, i, take)
            startIndex = (startIndex + take) % capacity
            i += take
        }
        return out
    }

    @Synchronized
    fun reset() { writeIndex = 0; totalWritten = 0 }
}
