package com.haman.domain

/** The event vocabulary. Only COUGH, SNEEZE and SNORE are logged as events;
 *  BREATHING and SPEECH are carried as context (speech in particular is a useful
 *  suppressor — people talking is not people sleeping). */
enum class AcousticClass {
    COUGH, SNEEZE, SNORE, BREATHING, SPEECH;

    val isLoggedEvent: Boolean get() = this == COUGH || this == SNEEZE || this == SNORE

    companion object {
        val ALL: List<AcousticClass> = entries
        val LOGGED: List<AcousticClass> = entries.filter { it.isLoggedEvent }
    }
}

/**
 * One analysis frame: 0.96 s of audio reduced to per-class scores plus level.
 *
 * Scores are held in a FloatArray indexed by [AcousticClass.ordinal] rather than
 * named fields because this allocates once per frame and is touched ~60,000 times
 * a night; a map per frame would be a real allocation cost on a sleeping CPU.
 */
class FrameScores(
    val timestampMs: Long,
    val scores: FloatArray,
    /** RMS level of the frame in dBFS (negative; 0 dB is full scale). */
    val rmsDb: Float,
) {
    operator fun get(c: AcousticClass): Float = scores[c.ordinal]

    companion object {
        fun of(timestampMs: Long, rmsDb: Float, vararg pairs: Pair<AcousticClass, Float>): FrameScores {
            val a = FloatArray(AcousticClass.ALL.size)
            pairs.forEach { (c, v) -> a[c.ordinal] = v }
            return FrameScores(timestampMs, a, rmsDb)
        }
    }
}

/**
 * A detected acoustic event.
 *
 * Deliberately holds no embedding array: keeping this a pure scalar data class makes
 * it comparable, loggable and testable. The embedding for [peakFrameMs] is looked up
 * separately from the pipeline's frame cache when the event is persisted.
 */
data class DetectedEvent(
    val cls: AcousticClass,
    val startMs: Long,
    val endMs: Long,
    val peakScore: Float,
    val meanScore: Float,
    val peakDb: Float,
    val snrDb: Float,
    /** Timestamp of the single strongest frame — the anchor for clip extraction. */
    val peakFrameMs: Long,
    /** Groups coughs that belong to one coughing fit. Null for other classes. */
    val boutId: Long? = null,
    val subject: SubjectLabel = SubjectLabel.UNKNOWN,
    val subjectConfidence: Float = 0f,
) {
    val durationMs: Long get() = endMs - startMs
}

/**
 * A run of continuous snoring.
 *
 * Snoring fires on every breath, which would mean hundreds of near-identical rows a
 * night. The episode is the unit a human actually cares about ("you snored from
 * 01:12 to 02:40"); individual snore events remain in the events table underneath.
 */
data class SnoreEpisode(
    val startMs: Long,
    val endMs: Long,
    val snoreCount: Int,
    val meanIntensityDb: Float,
) {
    val durationMs: Long get() = endMs - startMs
    val snoresPerHour: Float
        get() = if (durationMs <= 0) 0f else snoreCount * 3_600_000f / durationMs
}

/** Per-minute × class counters. Drawing an 8-hour timeline reads ~480 of these
 *  instead of scanning every event. */
data class MinuteBucket(
    val minuteEpoch: Long,
    val cls: AcousticClass,
    val count: Int,
    val maxScore: Float,
    val meanDb: Float,
)

enum class SubjectLabel { SUBJECT, OTHER, UNKNOWN }
