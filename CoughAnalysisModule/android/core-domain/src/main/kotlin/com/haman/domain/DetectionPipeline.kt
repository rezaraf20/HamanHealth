package com.haman.domain

/** One frame's model output. Defined here rather than imported from the inference
 *  module so this package stays free of Android and TFLite types. */
class FrameInference(val scores: FloatArray, val embedding: FloatArray?)

data class FrameResult(
    val timestampMs: Long,
    val gateOpen: Boolean,
    val inferenceRan: Boolean,
    val noiseFloorDb: Float,
    val rmsDb: Float,
    val smoothed: FloatArray,
    val events: List<DetectedEvent>,
    val completedEpisodes: List<SnoreEpisode>,
    val completedBuckets: List<MinuteBucket>,
)

/**
 * The whole detection chain, from one frame of audio to persisted-shaped output.
 *
 * Deliberately pure: it has no threads, no I/O and no Android types, so the desktop
 * evaluation harness and the phone run *identical* logic. That is the only reason
 * thresholds tuned in ml/ can be trusted on device.
 */
class DetectionPipeline(
    config: DetectorConfig = DetectorConfig.DEFAULT,
    private val frameHopMs: Long = 480L,
) {
    // Validated on the way in: parameters below one frame hop are silently inert.
    var config: DetectorConfig = config.validatedFor(frameHopMs)
        private set

    private val noiseFloor = NoiseFloorTracker()
    private var smoother = ScoreSmoother(config.emaAlpha)
    private val assembler = EventAssembler(this.config, frameHopMs)
    private val rollup = MinuteRollupAccumulator()
    private var snoreEpisodes = SnoreEpisodeAggregator(config.snoreEpisodeGapMs)
    val attribution = AttributionEngine()

    private val reduced = FloatArray(AcousticClass.ALL.size)
    private val smoothed = FloatArray(AcousticClass.ALL.size)

    /** Recent embeddings, so an event closing several frames after its peak can still
     *  retrieve the embedding of the peak frame. ~30 s at a 480 ms hop. */
    private val embeddingCache = ArrayDeque<Pair<Long, FloatArray>>()
    private val embeddingCacheSize = 64

    var framesSeen: Long = 0; private set
    var framesInferred: Long = 0; private set

    /** Fraction of frames the noise gate skipped — the headline battery statistic. */
    val gateSkipRatio: Float
        get() = if (framesSeen == 0L) 0f else 1f - (framesInferred.toFloat() / framesSeen)

    fun updateConfig(newConfig: DetectorConfig) {
        config = newConfig.validatedFor(frameHopMs)
        assembler.updateConfig(config)
        smoother = ScoreSmoother(config.emaAlpha)
        snoreEpisodes = SnoreEpisodeAggregator(config.snoreEpisodeGapMs)
    }

    /**
     * @param infer invoked only when the gate is open. Passing it as a lambda (rather
     *   than passing scores in) keeps the gating decision inside the domain, so the
     *   caller cannot accidentally pay for inference on a silent frame.
     */
    fun onFrame(timestampMs: Long, rmsDb: Float, infer: () -> FrameInference): FrameResult {
        framesSeen++
        val floor = noiseFloor.update(rmsDb)

        // Before the floor estimate has settled, stay open rather than risk gating away
        // the first minute of the night.
        val gateOpen = !noiseFloor.isWarmedUp || rmsDb > floor + config.gateMarginDb

        var embedding: FloatArray? = null
        if (gateOpen) {
            framesInferred++
            val out = infer()
            YamnetLabels.reduce(out.scores, reduced)
            embedding = out.embedding
        } else {
            // A gated frame is genuinely "nothing happening" — zero scores let any
            // in-progress event close naturally instead of hanging open.
            java.util.Arrays.fill(reduced, 0f)
        }

        if (embedding != null) {
            embeddingCache.addLast(timestampMs to embedding)
            while (embeddingCache.size > embeddingCacheSize) embeddingCache.removeFirst()
        }

        smoother.smooth(reduced, smoothed)
        applyCoughSneezeExclusion(smoothed)
        rollup.addFrame(timestampMs, rmsDb, smoothed)

        val raw = assembler.process(timestampMs, smoothed, rmsDb, gateOpen, floor)
        val events = ArrayList<DetectedEvent>(raw.size)
        val episodes = mutableListOf<SnoreEpisode>()

        for (e in raw) {
            val emb = embeddingFor(e.peakFrameMs)
            val (label, conf) = attribution.attribute(e, emb)
            val attributed = e.copy(subject = label, subjectConfidence = conf)
            events.add(attributed)
            rollup.addEvent(attributed)
            if (attributed.cls == AcousticClass.SNORE) {
                snoreEpisodes.add(attributed)?.let(episodes::add)
            }
        }

        return FrameResult(
            timestampMs = timestampMs,
            gateOpen = gateOpen,
            inferenceRan = gateOpen,
            noiseFloorDb = floor,
            rmsDb = rmsDb,
            smoothed = smoothed.copyOf(),
            events = events,
            completedEpisodes = episodes,
            completedBuckets = rollup.drainCompleted(timestampMs),
        )
    }


    /**
     * Winner-take-all between cough and sneeze.
     *
     * These two share most of their acoustic signature and YAMNet scores them together;
     * suppressing the weaker one keeps one physical event from being logged as two.
     * Applied after smoothing so the decision is made on stable scores rather than on
     * a single noisy frame.
     */
    private fun applyCoughSneezeExclusion(scores: FloatArray) {
        val c = AcousticClass.COUGH.ordinal
        val s = AcousticClass.SNEEZE.ordinal
        // Arbitrate from the point either class could OPEN an event, not from a fixed
        // absolute level. With a tuned cough on-threshold of 0.10 and an exclusion
        // threshold of 0.20, coughs scoring 0.10-0.20 opened an event that was never
        // arbitrated — on-device this logged one sneeze as a sneeze AND a cough at the
        // same millisecond.
        val t = minOf(
            config.coughSneezeExclusionThreshold,
            config.paramsFor(AcousticClass.COUGH).onThreshold,
            config.paramsFor(AcousticClass.SNEEZE).onThreshold,
        )
        if (scores[c] >= t && scores[s] >= t) {
            if (scores[c] >= scores[s]) scores[s] = 0f else scores[c] = 0f
        }
    }

    /** Embedding of the peak frame, or the closest cached frame within one hop. */
    fun embeddingFor(timestampMs: Long): FloatArray? {
        for ((ts, emb) in embeddingCache) if (ts == timestampMs) return emb
        return embeddingCache.minByOrNull { kotlin.math.abs(it.first - timestampMs) }
            ?.takeIf { kotlin.math.abs(it.first - timestampMs) <= frameHopMs }
            ?.second
    }

    /** End of session: close anything still open so nothing is silently dropped. */
    fun flush(atMs: Long): FrameResult {
        val tail = assembler.flush(atMs)
        val episodes = mutableListOf<SnoreEpisode>()
        val events = tail.map { e ->
            val (label, conf) = attribution.attribute(e, embeddingFor(e.peakFrameMs))
            e.copy(subject = label, subjectConfidence = conf).also {
                rollup.addEvent(it)
                if (it.cls == AcousticClass.SNORE) snoreEpisodes.add(it)?.let(episodes::add)
            }
        }
        snoreEpisodes.flush()?.let(episodes::add)
        return FrameResult(
            timestampMs = atMs, gateOpen = false, inferenceRan = false,
            noiseFloorDb = noiseFloor.floorDb, rmsDb = -160f,
            smoothed = FloatArray(AcousticClass.ALL.size),
            events = events, completedEpisodes = episodes,
            completedBuckets = rollup.drainAll(),
        )
    }
}
