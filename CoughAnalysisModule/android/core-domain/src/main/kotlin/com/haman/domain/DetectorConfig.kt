package com.haman.domain

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Event-assembly parameters for one class.
 *
 * Two thresholds, not one: with a single threshold a score hovering near it flickers
 * across frames and turns one cough into four events. [onThreshold] starts an event,
 * the lower [offThreshold] sustains it (Schmitt-trigger hysteresis).
 */
@Serializable
data class ClassParams(
    val onThreshold: Float,
    val offThreshold: Float,
    /** Events shorter than this are discarded as transients. */
    val minDurationMs: Long,
    /** Silence shorter than this does not end the event — it bridges it. */
    val mergeGapMs: Long,
    /** After an event closes, ignore new onsets this long to avoid re-triggering
     *  on the event's own tail or echo. */
    val refractoryMs: Long,
    /**
     * Hard ceiling on a single event.
     *
     * Without it a low off-threshold keeps an event open indefinitely: on-device this
     * produced a 9.6-second "cough", because once opened, ambient room noise never fell
     * back under an off-threshold of 0.04. Physiology bounds these sounds, so the
     * detector should too. Defaulted so tuned configs written before this field existed
     * still deserialise.
     */
    val maxDurationMs: Long = 3_000,
)

@Serializable
data class DetectorConfig(
    val params: Map<String, ClassParams> = defaultParams,
    /** Inference is skipped when a frame is below (noise floor + this margin).
     *  The single biggest battery lever: it skips roughly 60% of frames. */
    val gateMarginDb: Float = 6f,
    /** Frames whose SPEECH score exceeds this suppress event emission — talking,
     *  TV and radio are the dominant daytime false-positive source. */
    val speechSuppressionThreshold: Float = 0.55f,
    /**
     * Cough and sneeze are acoustically entangled: measured on ESC-50, sneeze clips
     * reach 1.00 on YAMNet's Cough output (results/esc50_yamnet.json). Without
     * arbitration a single sneeze opens both a cough event and a sneeze event and is
     * counted twice. Above this score the weaker of the two is suppressed for that
     * frame, so the louder interpretation wins instead of both.
     */
    val coughSneezeExclusionThreshold: Float = 0.20f,
    /** Coughs starting within this of the previous cough share a bout id. */
    val coughBoutGapMs: Long = 3_000,
    /** Snore events separated by less than this belong to one episode. */
    val snoreEpisodeGapMs: Long = 60_000,
    /** Median filter + EMA weight applied to raw scores before assembly. */
    val emaAlpha: Float = 0.5f,
) {
    fun paramsFor(c: AcousticClass): ClassParams =
        params[c.name] ?: defaultParams.getValue(c.name)

    /**
     * Maps one user-facing "sensitivity" dial onto every threshold.
     *
     * Exposing raw 0-1 thresholds would be asking the user a question they cannot
     * answer. "Fewer misses vs fewer false alarms" is a decision they can make.
     * 0.0 = conservative (high precision), 0.5 = tuned default, 1.0 = sensitive.
     */
    fun withSensitivity(s: Float): DetectorConfig {
        val t = s.coerceIn(0f, 1f)
        val shift = (0.5f - t) * 0.30f // ±0.15 around the tuned operating point
        return copy(params = params.mapValues { (_, p) ->
            p.copy(
                onThreshold = (p.onThreshold + shift).coerceIn(0.05f, 0.95f),
                offThreshold = (p.offThreshold + shift * 0.6f).coerceIn(0.02f, 0.90f),
            )
        })
    }

    /**
     * Clamp timing parameters that are inert at this frame hop.
     *
     * Both mistakes are silent and cost accuracy rather than raising an error, so they
     * are caught here instead of in review: a minDuration at or below one hop can never
     * reject a single-frame spike (one frame already spans a whole hop), and a mergeGap
     * at or below one hop can never bridge a dipped frame. Tuned configs coming from
     * ml/tune_thresholds.py go through this on load.
     */
    fun validatedFor(frameHopMs: Long): DetectorConfig = copy(
        params = params.mapValues { (_, p) ->
            p.copy(
                minDurationMs = maxOf(p.minDurationMs, frameHopMs + 1),
                mergeGapMs = maxOf(p.mergeGapMs, frameHopMs + 1),
                // A ceiling below the floor would discard every event.
                maxDurationMs = maxOf(p.maxDurationMs, p.minDurationMs + frameHopMs),
            )
        }
    )

    fun toJson(): String = Json.encodeToString(this)

    companion object {
        /** Starting points from docs/ARCHITECTURE.md §2; replaced by the values
         *  ml/tune_thresholds.py writes into assets/detector_config.json. */
        // IMPORTANT: minDurationMs and mergeGapMs are quantised by the frame hop
        // (480 ms). A value at or below one hop is inert - see validatedFor().
        //   minDurationMs in (hop, 2*hop]  => requires 2 frames above threshold
        //   mergeGapMs    in (hop, 2*hop]  => bridges exactly one dipped frame
        val defaultParams: Map<String, ClassParams> = mapOf(
            "COUGH" to ClassParams(0.45f, 0.25f, 600, 720, 250, maxDurationMs = 3_000),
            "SNEEZE" to ClassParams(0.40f, 0.22f, 600, 960, 500, maxDurationMs = 3_000),
            // Wider gap: one snore is a whole breath cycle and the quiet part of the
            // cycle must not split it. Still well under the 3-8 s between snores, so
            // separate snores stay separate events.
            "SNORE" to ClassParams(0.35f, 0.20f, 800, 1500, 500, maxDurationMs = 6_000),
            "BREATHING" to ClassParams(0.50f, 0.30f, 960, 1440, 500, maxDurationMs = 15_000),
            "SPEECH" to ClassParams(0.60f, 0.40f, 960, 1440, 300, maxDurationMs = 30_000),
        )

        val DEFAULT = DetectorConfig()

        private val lenient = Json { ignoreUnknownKeys = true; isLenient = true }
        fun fromJson(json: String): DetectorConfig = lenient.decodeFromString(json)
    }
}
