package com.haman.audio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * The decimator exists to rescue full-band audio on phones that only deliver it at
 * 48 kHz. A bad one would either lose the band it is meant to keep or fold energy above
 * 8 kHz back down as false high-frequency content - recreating the problem it solves.
 */
class DecimatorTest {
    private fun tone(freq: Double, seconds: Double = 1.0, amp: Double = 10000.0) =
        ShortArray((48000 * seconds).toInt()) { (amp * sin(2 * PI * freq * it / 48000)).toInt().toShort() }

    private fun rms(x: ShortArray, from: Int) =
        sqrt(x.drop(from).sumOf { it.toDouble() * it } / (x.size - from))

    private fun decimate(input: ShortArray): ShortArray {
        val out = ShortArray(input.size / 3 + 4)
        val n = Decimator3().process(input, input.size, out)
        return out.copyOf(n)
    }

    @Test
    fun `output rate is one third`() {
        assertEquals(16000, decimate(tone(1000.0)).size)
    }

    @Test
    fun `passband is preserved`() {
        for (f in listOf(500.0, 3000.0, 6000.0)) {
            val out = decimate(tone(f))
            val ratio = rms(out, 200) / (10000.0 / sqrt(2.0))
            assertTrue("$f Hz should pass ~unity, got $ratio", ratio in 0.9..1.1)
        }
    }

    @Test
    fun `energy above the new nyquist is rejected rather than aliased`() {
        // 12 kHz would alias to 4 kHz after naive decimation.
        val out = decimate(tone(12000.0))
        val ratio = rms(out, 200) / (10000.0 / sqrt(2.0))
        assertTrue("12 kHz leaked through at $ratio", ratio < 0.01)
    }

    @Test
    fun `chunked processing matches one-shot processing`() {
        val x = tone(2500.0)
        val oneShot = decimate(x)
        val d = Decimator3()
        val out = ShortArray(x.size / 3 + 16)
        var w = 0
        var i = 0
        val chunk = ShortArray(4799) // deliberately not a multiple of 3
        val buf = ShortArray(chunk.size / 3 + 4)
        while (i < x.size) {
            val n = minOf(chunk.size, x.size - i)
            System.arraycopy(x, i, chunk, 0, n)
            val m = d.process(chunk, n, buf)
            System.arraycopy(buf, 0, out, w, m)
            w += m; i += n
        }
        assertEquals(oneShot.size, w)
        for (k in oneShot.indices) assertEquals("sample $k", oneShot[k], out[k])
    }
}
