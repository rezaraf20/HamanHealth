package com.haman.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NoiseFloorTrackerTest {
    @Test
    fun `floor tracks the quiet part of the distribution not the mean`() {
        val t = NoiseFloorTracker(windowFrames = 100, percentile = 0.10f)
        // 90 quiet frames at -60 dB, 10 loud events at -20 dB.
        repeat(90) { t.update(-60f) }
        repeat(10) { t.update(-20f) }
        assertEquals("loud events must not drag the floor up", -60f, t.floorDb, 0.5f)
    }

    @Test
    fun `floor adapts when the room gets noisier`() {
        val t = NoiseFloorTracker(windowFrames = 50, percentile = 0.10f)
        repeat(50) { t.update(-70f) }
        assertEquals(-70f, t.floorDb, 0.5f)
        repeat(50) { t.update(-45f) } // a fan switches on
        assertEquals(-45f, t.floorDb, 0.5f)
    }
}

class ScoreSmootherTest {
    @Test
    fun `median kills an isolated single-frame outlier`() {
        val s = ScoreSmoother(alpha = 1.0f) // EMA disabled, isolating the median
        val n = AcousticClass.ALL.size
        fun frame(v: Float) = FloatArray(n).also { it[AcousticClass.COUGH.ordinal] = v }

        s.smooth(frame(0.0f))
        s.smooth(frame(0.0f))
        val spike = s.smooth(frame(1.0f))
        assertTrue(
            "a lone spike must be suppressed, got ${spike[AcousticClass.COUGH.ordinal]}",
            spike[AcousticClass.COUGH.ordinal] < 0.5f,
        )
    }

    @Test
    fun `a sustained signal passes through`() {
        val s = ScoreSmoother(alpha = 1.0f)
        val n = AcousticClass.ALL.size
        fun frame(v: Float) = FloatArray(n).also { it[AcousticClass.COUGH.ordinal] = v }
        repeat(4) { s.smooth(frame(0.9f)) }
        val out = s.smooth(frame(0.9f))
        assertEquals(0.9f, out[AcousticClass.COUGH.ordinal], 0.05f)
    }
}

class YamnetLabelsTest {
    @Test
    fun `reduce maps the documented AudioSet indices`() {
        val raw = FloatArray(YamnetLabels.NUM_YAMNET_CLASSES)
        raw[YamnetLabels.COUGH] = 0.7f
        raw[YamnetLabels.SNEEZE] = 0.6f
        raw[YamnetLabels.SNORING] = 0.5f
        raw[YamnetLabels.BREATHING] = 0.4f
        raw[0] = 0.3f // Speech
        val out = YamnetLabels.reduce(raw)
        assertEquals(0.7f, out[AcousticClass.COUGH.ordinal], 1e-6f)
        assertEquals(0.6f, out[AcousticClass.SNEEZE.ordinal], 1e-6f)
        assertEquals(0.5f, out[AcousticClass.SNORE.ordinal], 1e-6f)
        assertEquals(0.4f, out[AcousticClass.BREATHING.ordinal], 1e-6f)
        assertEquals(0.3f, out[AcousticClass.SPEECH.ordinal], 1e-6f)
    }

    @Test
    fun `snore takes the max of Snoring and Snort`() {
        // AudioSet labels the sharp inhale ending a snore cycle as Snort; ignoring it
        // would clip real snore events short.
        val raw = FloatArray(YamnetLabels.NUM_YAMNET_CLASSES)
        raw[YamnetLabels.SNORING] = 0.2f
        raw[YamnetLabels.SNORT] = 0.8f
        assertEquals(0.8f, YamnetLabels.reduce(raw)[AcousticClass.SNORE.ordinal], 1e-6f)
    }

    /** Guards the hard-coded indices against a class-map change. */
    @Test
    fun `indices match the shipped yamnet class map`() {
        val csv = java.io.File("../../models/yamnet_class_map.csv")
        if (!csv.exists()) return // dataset not present in this checkout
        val names = csv.readLines().drop(1).map { line ->
            // display_name is the last field and may be quoted
            line.substringAfterLast(',').trim().trim('"')
        }
        assertEquals("Cough", names[YamnetLabels.COUGH])
        assertEquals("Sneeze", names[YamnetLabels.SNEEZE])
        assertEquals("Snoring", names[YamnetLabels.SNORING])
        assertEquals("Snort", names[YamnetLabels.SNORT])
        assertEquals("Breathing", names[YamnetLabels.BREATHING])
        assertEquals("Speech", names[0])
    }
}

class AggregatorTest {
    private fun snore(start: Long, end: Long, db: Float = -30f) = DetectedEvent(
        cls = AcousticClass.SNORE, startMs = start, endMs = end,
        peakScore = 0.8f, meanScore = 0.7f, peakDb = db, snrDb = 20f, peakFrameMs = start,
    )

    @Test
    fun `consecutive snores form one episode`() {
        val agg = SnoreEpisodeAggregator(gapMs = 60_000)
        var completed: SnoreEpisode? = null
        for (i in 0 until 10) {
            completed = agg.add(snore(i * 5_000L, i * 5_000L + 2_000L)) ?: completed
        }
        assertNull("no gap, so nothing should have closed yet", completed)
        val ep = agg.flush()
        assertNotNull(ep)
        assertEquals(10, ep!!.snoreCount)
    }

    @Test
    fun `a long quiet gap starts a new episode`() {
        val agg = SnoreEpisodeAggregator(gapMs = 60_000)
        agg.add(snore(0, 2_000))
        agg.add(snore(5_000, 7_000))
        val closed = agg.add(snore(300_000, 302_000)) // 5 min later
        assertNotNull("gap should have closed the first episode", closed)
        assertEquals(2, closed!!.snoreCount)
    }

    @Test
    fun `snores per hour is computed from episode duration`() {
        val ep = SnoreEpisode(startMs = 0, endMs = 3_600_000, snoreCount = 300, meanIntensityDb = -30f)
        assertEquals(300f, ep.snoresPerHour, 0.1f)
    }

    @Test
    fun `minute rollup buckets events by minute and only drains completed minutes`() {
        val acc = MinuteRollupAccumulator()
        val smoothed = FloatArray(AcousticClass.ALL.size)
        acc.addFrame(30_000, -50f, smoothed)
        acc.addEvent(DetectedEvent(AcousticClass.COUGH, 30_000, 30_500, 0.8f, 0.7f, -30f, 20f, 30_000))
        assertTrue("current minute must stay open", acc.drainCompleted(35_000).isEmpty())

        acc.addFrame(90_000, -50f, smoothed)
        val drained = acc.drainCompleted(90_000)
        assertEquals(1, drained.size)
        assertEquals(AcousticClass.COUGH, drained[0].cls)
        assertEquals(1, drained[0].count)
        assertEquals(0L, drained[0].minuteEpoch)
    }
}

class AttributionTest {
    private fun event(peakDb: Float) = DetectedEvent(
        cls = AcousticClass.COUGH, startMs = 0, endMs = 500,
        peakScore = 0.8f, meanScore = 0.7f, peakDb = peakDb, snrDb = 25f, peakFrameMs = 0,
    )

    @Test
    fun `with no calibration and no labels the verdict is UNKNOWN`() {
        val (label, conf) = AttributionEngine().attribute(event(-30f), null)
        assertEquals(SubjectLabel.UNKNOWN, label)
        assertEquals(0f, conf, 1e-6f)
    }

    @Test
    fun `proximity prior is one-sided - louder than calibrated is not penalised`() {
        val cal = ProximityCalibration(meanDb = -30f, sdDb = 5f, sampleCount = 5)
        assertEquals(0.9f, cal.probabilityOwner(-20f), 1e-3f)  // louder: still the owner
        assertTrue(cal.probabilityOwner(-50f) < 0.2f)          // much quieter: probably not
    }

    @Test
    fun `a distant quiet cough is attributed to someone else`() {
        val engine = AttributionEngine(
            calibration = ProximityCalibration(meanDb = -28f, sdDb = 4f, sampleCount = 5)
        )
        val (label, _) = engine.attribute(event(-55f), null)
        assertEquals(SubjectLabel.OTHER, label)
    }

    @Test
    fun `calibration refuses to build from too few samples and floors the sd`() {
        assertNull(ProximityCalibration.from(listOf(-30f, -31f)))
        val cal = ProximityCalibration.from(List(5) { -30f })!!
        assertTrue("sd must be floored or every later event is rejected", cal.sdDb >= 3f)
    }

    @Test
    fun `prototype attributor separates two embedding clusters`() {
        val owner = List(5) { i -> FloatArray(16) { j -> if (j < 8) 1f + i * 0.01f else 0f } }
        val other = List(5) { i -> FloatArray(16) { j -> if (j >= 8) 1f + i * 0.01f else 0f } }
        val proto = PrototypeAttributor.build(owner, other)!!
        assertTrue(proto.probabilityOwner(owner[0]) > 0.9f)
        assertTrue(proto.probabilityOwner(other[0]) < 0.1f)
    }

    @Test
    fun `logistic head refuses to train on a single class`() {
        val feats = List(10) { FloatArray(4) { 0.5f } }
        assertNull(LogisticHead.train(feats, IntArray(10) { 1 }))
    }

    @Test
    fun `logistic head learns a separable split`() {
        val feats = mutableListOf<FloatArray>()
        val labels = mutableListOf<Int>()
        repeat(40) { i ->
            feats.add(floatArrayOf(1f, 0f, i * 0.01f, 0f)); labels.add(1)
            feats.add(floatArrayOf(0f, 1f, i * 0.01f, 0f)); labels.add(0)
        }
        val head = LogisticHead.train(feats, labels.toIntArray(), epochs = 500, lr = 0.5f, l2 = 0.0f)!!
        assertTrue(head.probabilityOwner(floatArrayOf(1f, 0f, 0.2f, 0f)) > 0.6f)
        assertTrue(head.probabilityOwner(floatArrayOf(0f, 1f, 0.2f, 0f)) < 0.4f)
    }
}

class DetectorConfigTest {
    @Test
    fun `sensitivity slider moves thresholds in the expected direction`() {
        val base = DetectorConfig.DEFAULT.paramsFor(AcousticClass.COUGH).onThreshold
        val sensitive = DetectorConfig.DEFAULT.withSensitivity(1.0f).paramsFor(AcousticClass.COUGH).onThreshold
        val strict = DetectorConfig.DEFAULT.withSensitivity(0.0f).paramsFor(AcousticClass.COUGH).onThreshold
        assertTrue("higher sensitivity must lower the threshold", sensitive < base)
        assertTrue("lower sensitivity must raise the threshold", strict > base)
    }

    @Test
    fun `config survives a json round trip`() {
        val cfg = DetectorConfig.DEFAULT.withSensitivity(0.8f)
        assertEquals(cfg, DetectorConfig.fromJson(cfg.toJson()))
    }
}

class ConfigValidationTest {
    /** The two bugs this guard exists to prevent, both of which fail silently. */
    @Test
    fun `timing parameters at or below one frame hop are raised`() {
        val inert = DetectorConfig.DEFAULT.copy(
            params = mapOf("COUGH" to ClassParams(0.45f, 0.25f, 300, 400, 250))
        )
        val fixed = inert.validatedFor(480L).paramsFor(AcousticClass.COUGH)
        assertTrue("minDuration must exceed one hop to reject a 1-frame spike", fixed.minDurationMs > 480)
        assertTrue("mergeGap must exceed one hop to bridge a dipped frame", fixed.mergeGapMs > 480)
    }

    @Test
    fun `already valid parameters are left alone`() {
        val p = DetectorConfig.DEFAULT.validatedFor(480L).paramsFor(AcousticClass.SNORE)
        assertEquals(800L, p.minDurationMs)
        assertEquals(1500L, p.mergeGapMs)
    }
}

class CoughSneezeExclusionTest {
    /**
     * Guards against double-counting. Measured on ESC-50, sneeze clips reach 1.00 on
     * YAMNet's Cough output, so without arbitration one sneeze becomes two events.
     */
    private fun pipelineWith(coughScore: Float, sneezeScore: Float): List<DetectedEvent> {
        val pipeline = DetectionPipeline(DetectorConfig.DEFAULT, frameHopMs = 480L)
        val raw = FloatArray(YamnetLabels.NUM_YAMNET_CLASSES)
        val events = mutableListOf<DetectedEvent>()
        // Warm the noise floor with quiet frames so the gate is open for the loud ones.
        repeat(40) { i ->
            events += pipeline.onFrame(i * 480L, -70f) {
                FrameInference(FloatArray(YamnetLabels.NUM_YAMNET_CLASSES), null)
            }.events
        }
        raw[YamnetLabels.COUGH] = coughScore
        raw[YamnetLabels.SNEEZE] = sneezeScore
        repeat(6) { i ->
            events += pipeline.onFrame((40 + i) * 480L, -25f) { FrameInference(raw, null) }.events
        }
        repeat(10) { i ->
            events += pipeline.onFrame((46 + i) * 480L, -70f) {
                FrameInference(FloatArray(YamnetLabels.NUM_YAMNET_CLASSES), null)
            }.events
        }
        events += pipeline.flush(60 * 480L).events
        return events
    }

    @Test
    fun `a sneeze that also scores high on cough is logged once, as a sneeze`() {
        val events = pipelineWith(coughScore = 0.80f, sneezeScore = 0.95f)
        assertEquals("one physical event must produce one row, got $events", 1, events.size)
        assertEquals(AcousticClass.SNEEZE, events[0].cls)
    }

    @Test
    fun `a cough that bleeds into the sneeze score is logged once, as a cough`() {
        val events = pipelineWith(coughScore = 0.95f, sneezeScore = 0.55f)
        assertEquals(1, events.size)
        assertEquals(AcousticClass.COUGH, events[0].cls)
    }
}

class ShippedConfigTest {
    /**
     * Parses the actual file that goes into the APK.
     *
     * A malformed or renamed field would not fail the build - the service catches the
     * exception and silently falls back to defaults, so the app would ship running
     * untuned thresholds while appearing to work. This turns that into a build failure.
     */
    @Test
    fun `the tuned config shipped in assets parses and is sane`() {
        val f = java.io.File("../app/src/main/assets/detector_config.json")
        if (!f.exists()) return // config not generated in this checkout
        val cfg = DetectorConfig.fromJson(f.readText()).validatedFor(480L)

        AcousticClass.LOGGED.forEach { cls ->
            val p = cfg.paramsFor(cls)
            assertTrue("$cls onThreshold out of range: ${p.onThreshold}",
                p.onThreshold in 0.01f..0.99f)
            assertTrue("$cls offThreshold must sit below onThreshold",
                p.offThreshold < p.onThreshold)
            assertTrue("$cls minDuration must exceed one frame hop", p.minDurationMs > 480)
            assertTrue("$cls mergeGap must exceed one frame hop", p.mergeGapMs > 480)
        }
        // A config that parsed but kept every default would mean the sweep silently
        // did nothing; the tuned snore threshold differs from the built-in default.
        assertTrue("tuned config looks identical to the defaults - did the sweep run?",
            cfg.params != DetectorConfig.defaultParams)
    }
}

class DurationCeilingTest {
    /**
     * On-device, a tuned off-threshold of 0.04 produced a 9.6-second "cough": once
     * opened, ambient room noise never fell back below it. Physiology bounds these
     * sounds, so the detector must too.
     */
    @Test
    fun `an event that never falls below the off-threshold is capped`() {
        val cfg = DetectorConfig.DEFAULT.copy(
            params = DetectorConfig.defaultParams + ("COUGH" to
                ClassParams(0.45f, 0.04f, 600, 720, 250, maxDurationMs = 3_000))
        )
        val asm = EventAssembler(cfg, 480L)
        val buf = FloatArray(AcousticClass.ALL.size)
        val out = mutableListOf<DetectedEvent>()
        // 40 frames (19 s) of sustained above-off-threshold score.
        repeat(40) { i ->
            java.util.Arrays.fill(buf, 0f)
            buf[AcousticClass.COUGH.ordinal] = if (i == 0) 0.9f else 0.2f
            out += asm.process(i * 480L, buf, -30f, true, -60f)
        }
        out += asm.flush(40 * 480L)
        assertTrue("expected at least one event", out.isNotEmpty())
        out.forEach {
            assertTrue("event ran to ${it.durationMs} ms, ceiling is 3000", it.durationMs <= 3_000)
        }
    }

    @Test
    fun `the ceiling cannot be set below the floor`() {
        val p = DetectorConfig.DEFAULT.copy(
            params = mapOf("COUGH" to ClassParams(0.45f, 0.25f, 600, 720, 250, maxDurationMs = 100))
        ).validatedFor(480L).paramsFor(AcousticClass.COUGH)
        assertTrue("a ceiling under the floor would discard every event",
            p.maxDurationMs > p.minDurationMs)
    }
}

class ExclusionBandTest {
    /**
     * With a tuned cough on-threshold of 0.10 and a fixed exclusion threshold of 0.20,
     * coughs scoring 0.10-0.20 opened an event that was never arbitrated. On-device this
     * logged one sneeze as both a sneeze and a cough at the same millisecond.
     */
    @Test
    fun `arbitration covers the band below the fixed exclusion threshold`() {
        val cfg = DetectorConfig.DEFAULT.copy(
            params = DetectorConfig.defaultParams +
                ("COUGH" to ClassParams(0.10f, 0.04f, 600, 720, 250, maxDurationMs = 3_000)) +
                ("SNEEZE" to ClassParams(0.20f, 0.11f, 600, 960, 500, maxDurationMs = 3_000)),
            coughSneezeExclusionThreshold = 0.20f,
        )
        val pipeline = DetectionPipeline(cfg, frameHopMs = 480L)
        val events = mutableListOf<DetectedEvent>()
        val silence = FloatArray(YamnetLabels.NUM_YAMNET_CLASSES)
        repeat(40) { i ->
            events += pipeline.onFrame(i * 480L, -70f) { FrameInference(silence, null) }.events
        }
        // A sneeze whose cough score sits inside the previously unarbitrated band.
        val raw = FloatArray(YamnetLabels.NUM_YAMNET_CLASSES)
        raw[YamnetLabels.SNEEZE] = 0.39f
        raw[YamnetLabels.COUGH] = 0.18f
        repeat(6) { i -> events += pipeline.onFrame((40 + i) * 480L, -25f) { FrameInference(raw, null) }.events }
        repeat(12) { i ->
            events += pipeline.onFrame((46 + i) * 480L, -70f) { FrameInference(silence, null) }.events
        }
        events += pipeline.flush(60 * 480L).events

        val coincident = events.filter { it.cls == AcousticClass.COUGH }
            .any { c -> events.any { it.cls == AcousticClass.SNEEZE && it.startMs == c.startMs } }
        assertTrue("one sound was logged as both a cough and a sneeze: $events", !coincident)
        assertEquals("expected a single sneeze", 1, events.size)
        assertEquals(AcousticClass.SNEEZE, events[0].cls)
    }
}
