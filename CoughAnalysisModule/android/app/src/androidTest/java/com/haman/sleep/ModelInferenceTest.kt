package com.haman.sleep

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.haman.domain.AcousticClass
import com.haman.domain.YamnetLabels
import com.haman.inference.YamnetClassifier
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.abs
import kotlin.math.sin

/**
 * Exercises the real TFLite interpreter against the real asset.
 *
 * None of this is reachable from a JVM unit test: the tensor shapes, the asset being
 * stored uncompressed so it can be memory-mapped, and the output-by-shape resolution
 * all only fail on device. A rank mismatch here ([521] vs [1, 521]) crashed the capture
 * thread on the first frame while the UI looked perfectly healthy.
 */
@RunWith(AndroidJUnit4::class)
class ModelInferenceTest {

    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun model_loads_and_returns_correctly_shaped_outputs() {
        YamnetClassifier(context).use { clf ->
            val frame = FloatArray(YamnetClassifier.FRAME_SAMPLES)
            val out = clf.infer(frame)
            assertEquals(YamnetClassifier.NUM_CLASSES, out.scores.size)
            assertEquals(YamnetClassifier.EMBEDDING_DIM, out.embedding!!.size)
        }
    }

    @Test
    fun scores_are_probabilities_and_the_embedding_is_not_degenerate() {
        YamnetClassifier(context).use { clf ->
            // A 440 Hz tone: arbitrary but deterministic, and definitely not silence.
            val frame = FloatArray(YamnetClassifier.FRAME_SAMPLES) { i ->
                (0.25 * sin(2.0 * Math.PI * 440.0 * i / YamnetClassifier.SAMPLE_RATE)).toFloat()
            }
            val out = clf.infer(frame)

            assertTrue("scores must lie in [0,1]", out.scores.all { it in 0f..1.0001f })
            assertTrue("at least one class should respond", out.scores.any { it > 0.01f })

            val emb = out.embedding!!
            assertTrue("embedding must not be all zeros", emb.any { abs(it) > 1e-6f })
        }
    }

    @Test
    fun different_inputs_produce_different_outputs() {
        // Guards against the interpreter silently returning a stale buffer, which the
        // reused output arrays would otherwise make invisible.
        YamnetClassifier(context).use { clf ->
            val silence = clf.infer(FloatArray(YamnetClassifier.FRAME_SAMPLES))
            val tone = clf.infer(FloatArray(YamnetClassifier.FRAME_SAMPLES) { i ->
                (0.3 * sin(2.0 * Math.PI * 1000.0 * i / YamnetClassifier.SAMPLE_RATE)).toFloat()
            })
            val delta = silence.scores.indices.maxOf { abs(silence.scores[it] - tone.scores[it]) }
            assertTrue("outputs did not change with input (stale buffer?)", delta > 0.01f)
        }
    }

    @Test
    fun reduce_accepts_the_real_model_output_width() {
        YamnetClassifier(context).use { clf ->
            val out = clf.infer(FloatArray(YamnetClassifier.FRAME_SAMPLES))
            val reduced = YamnetLabels.reduce(out.scores)
            assertEquals(AcousticClass.ALL.size, reduced.size)
        }
    }

    @Test
    fun the_tuned_config_asset_is_present_and_parses() {
        val json = context.assets.open("detector_config.json").bufferedReader().use { it.readText() }
        val cfg = com.haman.domain.DetectorConfig.fromJson(json)
        assertTrue(cfg.paramsFor(AcousticClass.COUGH).onThreshold > 0f)
    }
}
