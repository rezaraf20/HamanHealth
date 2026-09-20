package com.haman.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * These tests encode the specific failure modes the assembler exists to prevent.
 * Each one corresponds to a bullet in the EventAssembler doc comment: if one of these
 * regresses, overnight output degrades in a way clip-level accuracy would not reveal.
 */
class EventAssemblerTest {

    private val hop = 480L

    /** Drive a score profile for one class through the assembler. */
    private fun run(
        cls: AcousticClass,
        profile: List<Float>,
        config: DetectorConfig = DetectorConfig.DEFAULT,
        rmsDb: Float = -30f,
        speech: List<Float>? = null,
    ): List<DetectedEvent> {
        val asm = EventAssembler(config, hop)
        val out = mutableListOf<DetectedEvent>()
        val buf = FloatArray(AcousticClass.ALL.size)
        profile.forEachIndexed { i, p ->
            java.util.Arrays.fill(buf, 0f)
            buf[cls.ordinal] = p
            speech?.getOrNull(i)?.let { buf[AcousticClass.SPEECH.ordinal] = it }
            out += asm.process(i * hop, buf, rmsDb, gateOpen = true, noiseFloorDb = -60f)
        }
        out += asm.flush(profile.size * hop)
        return out
    }

    @Test
    fun `one cough produces exactly one event`() {
        // A cough spans ~2-3 frames and its score rises then falls.
        val events = run(AcousticClass.COUGH, listOf(0.0f, 0.1f, 0.8f, 0.6f, 0.1f, 0.0f, 0.0f))
        assertEquals(1, events.size)
        assertEquals(AcousticClass.COUGH, events[0].cls)
        assertEquals(0.8f, events[0].peakScore, 1e-4f)
    }

    @Test
    fun `mid-event dip does not split one cough into two`() {
        // Without the merge gap this dip below the off-threshold would close the event
        // and open a second one - the single most common over-counting bug.
        val events = run(AcousticClass.COUGH, listOf(0.0f, 0.7f, 0.15f, 0.7f, 0.1f, 0.0f, 0.0f))
        assertEquals(1, events.size)
    }

    @Test
    fun `single-frame spike is discarded as a transient`() {
        // One frame is 480 ms of hop but the event must last minDurationMs=300ms of
        // *sustained* score; an isolated spike is a click, not a cough.
        val events = run(AcousticClass.COUGH, listOf(0.0f, 0.9f, 0.0f, 0.0f, 0.0f))
        assertTrue("isolated spike should not emit, got $events", events.isEmpty())
    }

    @Test
    fun `score oscillating around a single threshold still yields one event`() {
        // Hysteresis test: these values straddle onThreshold 0.45 repeatedly.
        val events = run(AcousticClass.COUGH, listOf(0.0f, 0.5f, 0.4f, 0.5f, 0.42f, 0.5f, 0.0f, 0.0f))
        assertEquals(1, events.size)
    }

    @Test
    fun `refractory period suppresses immediate re-trigger`() {
        val cfg = DetectorConfig.DEFAULT.copy(
            params = DetectorConfig.defaultParams + ("COUGH" to
                ClassParams(0.45f, 0.25f, 300, 400, refractoryMs = 5_000))
        )
        val events = run(
            AcousticClass.COUGH,
            listOf(0.0f, 0.8f, 0.8f, 0.0f, 0.0f, 0.8f, 0.8f, 0.0f, 0.0f),
            config = cfg,
        )
        assertEquals("second burst falls inside the refractory window", 1, events.size)
    }

    @Test
    fun `coughs close together share a bout id and distant ones do not`() {
        val cfg = DetectorConfig.DEFAULT.copy(coughBoutGapMs = 3_000)
        val asm = EventAssembler(cfg, hop)
        val buf = FloatArray(AcousticClass.ALL.size)
        val out = mutableListOf<DetectedEvent>()

        // Two bursts ~1.9s apart (same bout), then one ~10s later (new bout).
        val profile = FloatArray(40).also { p ->
            p[1] = 0.8f; p[2] = 0.8f
            p[6] = 0.8f; p[7] = 0.8f
            p[30] = 0.8f; p[31] = 0.8f
        }
        profile.forEachIndexed { i, p ->
            java.util.Arrays.fill(buf, 0f); buf[AcousticClass.COUGH.ordinal] = p
            out += asm.process(i * hop, buf, -30f, true, -60f)
        }
        out += asm.flush(40 * hop)

        assertEquals(3, out.size)
        assertEquals(out[0].boutId, out[1].boutId)
        assertTrue("third cough should start a new bout", out[2].boutId != out[1].boutId)
    }

    @Test
    fun `sustained speech suppresses new events`() {
        val speech = List(8) { 0.9f }
        val events = run(
            AcousticClass.COUGH,
            listOf(0.0f, 0.8f, 0.8f, 0.8f, 0.0f, 0.0f, 0.0f, 0.0f),
            speech = speech,
        )
        assertTrue("talking should suppress detection, got $events", events.isEmpty())
    }

    @Test
    fun `gated frames cannot open an event`() {
        val asm = EventAssembler(DetectorConfig.DEFAULT, hop)
        val buf = FloatArray(AcousticClass.ALL.size)
        val out = mutableListOf<DetectedEvent>()
        repeat(6) { i ->
            java.util.Arrays.fill(buf, 0f)
            buf[AcousticClass.COUGH.ordinal] = 0.9f
            out += asm.process(i * hop, buf, -80f, gateOpen = false, noiseFloorDb = -60f)
        }
        assertTrue(out.isEmpty())
    }

    @Test
    fun `snr is measured against the floor at event onset`() {
        val asm = EventAssembler(DetectorConfig.DEFAULT, hop)
        val buf = FloatArray(AcousticClass.ALL.size)
        val out = mutableListOf<DetectedEvent>()
        listOf(0.0f, 0.8f, 0.8f, 0.0f, 0.0f).forEachIndexed { i, p ->
            java.util.Arrays.fill(buf, 0f); buf[AcousticClass.COUGH.ordinal] = p
            out += asm.process(i * hop, buf, rmsDb = -25f, gateOpen = true, noiseFloorDb = -65f)
        }
        out += asm.flush(5 * hop)
        assertEquals(1, out.size)
        assertEquals(40f, out[0].snrDb, 0.01f)
    }

    @Test
    fun `flush closes an event still in progress`() {
        val asm = EventAssembler(DetectorConfig.DEFAULT, hop)
        val buf = FloatArray(AcousticClass.ALL.size)
        repeat(4) { i ->
            java.util.Arrays.fill(buf, 0f); buf[AcousticClass.SNORE.ordinal] = 0.7f
            asm.process(i * hop, buf, -30f, true, -60f)
        }
        val tail = asm.flush(4 * hop)
        assertEquals("an event open at session end must not be lost", 1, tail.size)
    }
}
