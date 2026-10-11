package com.haman.audio

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AudioRingBufferTest {

    private fun ramp(from: Int, n: Int) = ShortArray(n) { (from + it).toShort() }

    @Test
    fun reads_the_requested_range_across_the_wrap() {
        val ring = AudioRingBuffer(10)
        ring.write(ramp(0, 7), 7)
        ring.write(ramp(7, 7), 7) // wraps; samples 4..13 remain
        assertArrayEquals(ramp(8, 5), ring.read(13, 5))
    }

    @Test
    fun refuses_overwritten_audio() {
        val ring = AudioRingBuffer(10)
        ring.write(ramp(0, 14), 14)
        assertNull(ring.read(5, 3))
    }

    @Test
    fun refuses_audio_not_recorded_yet_instead_of_returning_old_samples() {
        val ring = AudioRingBuffer(10)
        ring.write(ramp(0, 12), 12)
        // Samples 10..13 requested but only up to 11 exist; the old code returned the
        // slots holding samples 2..3 from a buffer length earlier as if they were 12..13.
        assertNull(ring.read(14, 4))
    }
}
