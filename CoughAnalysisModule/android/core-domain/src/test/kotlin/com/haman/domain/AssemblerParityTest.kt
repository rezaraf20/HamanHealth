package com.haman.domain

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Replays a fixture produced by ml/parity_fixture.py and asserts this assembler agrees
 * with the Python one used to tune thresholds.
 *
 * The two implementations are the same algorithm written twice. If they drift, every
 * threshold in assets/detector_config.json silently stops describing what the phone
 * actually does - and nothing else in the test suite would notice.
 */
class AssemblerParityTest {

    @Serializable
    private data class Fixture(
        val hop_ms: Long,
        val classes: List<String>,
        val params: Map<String, PyParams>,
        val scores: List<List<Float>>,
        val rms_db: List<Float>,
        val expected_events: List<PyEvent>,
    )

    @Serializable
    private data class PyParams(
        val on: Float, val off: Float,
        val min_dur: Long, val merge_gap: Long, val refractory: Long,
        // Must be mapped explicitly: ignoreUnknownKeys would silently substitute
        // ClassParams' 3000 ms default for snore's 6000 ms and change the event count.
        val max_dur: Long,
    )

    @Serializable
    private data class PyEvent(
        val cls: String, val start_ms: Long, val end_ms: Long,
        val peak_score: Float, val peak_frame_ms: Long,
    )

    private fun loadFixture(): Fixture {
        val stream = javaClass.classLoader!!.getResourceAsStream("parity_fixture.json")
            ?: error("parity_fixture.json missing; regenerate with ml/parity_fixture.py")
        val text = stream.bufferedReader().use { it.readText() }
        return Json { ignoreUnknownKeys = true }.decodeFromString(text)
    }

    @Test
    fun `kotlin assembler reproduces the python reference exactly`() {
        val f = loadFixture()
        assertEquals("fixture class order must match AcousticClass",
            AcousticClass.ALL.map { it.name }, f.classes)

        val config = DetectorConfig.DEFAULT.copy(
            params = f.params.mapValues { (_, p) ->
                ClassParams(p.on, p.off, p.min_dur, p.merge_gap, p.refractory, p.max_dur)
            } + DetectorConfig.defaultParams.filterKeys { it !in f.params }
        )

        // Drive the full pipeline, so the noise gate, smoother and cough/sneeze
        // exclusion are all exercised - not just the state machine.
        val pipeline = DetectionPipeline(config, frameHopMs = f.hop_ms)
        val produced = mutableListOf<DetectedEvent>()
        f.scores.forEachIndexed { i, row ->
            val raw = FloatArray(YamnetLabels.NUM_YAMNET_CLASSES)
            raw[YamnetLabels.COUGH] = row[AcousticClass.COUGH.ordinal]
            raw[YamnetLabels.SNEEZE] = row[AcousticClass.SNEEZE.ordinal]
            raw[YamnetLabels.SNORING] = row[AcousticClass.SNORE.ordinal]
            raw[YamnetLabels.BREATHING] = row[AcousticClass.BREATHING.ordinal]
            raw[0] = row[AcousticClass.SPEECH.ordinal]
            produced += pipeline.onFrame(i * f.hop_ms, f.rms_db[i]) {
                FrameInference(raw, null)
            }.events
        }
        produced += pipeline.flush(f.scores.size * f.hop_ms).events

        val expected = f.expected_events.sortedWith(compareBy({ it.start_ms }, { it.cls }))
        val actual = produced.sortedWith(compareBy({ it.startMs }, { it.cls.name }))

        assertEquals(
            "event count differs — Kotlin and Python assemblers have diverged\n" +
                "expected: ${expected.map { "${it.cls}@${it.start_ms}" }}\n" +
                "actual:   ${actual.map { "${it.cls.name}@${it.startMs}" }}",
            expected.size, actual.size,
        )

        expected.zip(actual).forEach { (e, a) ->
            assertEquals("class at ${e.start_ms}", e.cls, a.cls.name)
            assertEquals("start of ${e.cls}", e.start_ms, a.startMs)
            assertEquals("end of ${e.cls}@${e.start_ms}", e.end_ms, a.endMs)
            assertEquals("peak frame of ${e.cls}@${e.start_ms}", e.peak_frame_ms, a.peakFrameMs)
            assertEquals("peak score of ${e.cls}@${e.start_ms}",
                e.peak_score.toDouble(), a.peakScore.toDouble(), 1e-4)
        }
    }

    @Test
    fun `fixture actually contains events`() {
        // A fixture of pure silence would pass the parity test while proving nothing.
        assertTrue(loadFixture().expected_events.isNotEmpty())
    }
}
