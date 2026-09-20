package com.haman.data

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Storage schema. See docs/ARCHITECTURE.md §3 for why there are three tiers rather
 * than one events table: raw frames are never persisted, discrete events and
 * aggregated episodes serve different questions, and the minute rollup exists so the
 * timeline UI reads hundreds of rows instead of tens of thousands.
 */

@Entity(tableName = "sessions")
data class SessionEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val startedAt: Long,
    val endedAt: Long? = null,
    val deviceModel: String,
    val appVersion: String,
    /** Which microphone path was granted. Levels are not comparable across sources,
     *  so analysis must be able to see this. */
    val audioSource: String,
    val noiseFloorDb: Float = -90f,
    val configJson: String,
    val status: String = STATUS_RUNNING,
    val framesSeen: Long = 0,
    val framesInferred: Long = 0,
    /** Milliseconds the microphone was unavailable (phone call, another app). Logged
     *  explicitly so a short night is distinguishable from a quiet one. */
    val micGapMs: Long = 0,
) {
    companion object {
        const val STATUS_RUNNING = "running"
        const val STATUS_COMPLETE = "complete"
        const val STATUS_INTERRUPTED = "interrupted"
    }
}

@Entity(
    tableName = "events",
    foreignKeys = [ForeignKey(
        entity = SessionEntity::class,
        parentColumns = ["id"], childColumns = ["sessionId"],
        onDelete = ForeignKey.CASCADE,
    )],
    indices = [Index("sessionId", "startedAtMs"), Index("cls", "startedAtMs")],
)
data class EventEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val sessionId: Long,
    val cls: String,
    val startedAtMs: Long,
    val endedAtMs: Long,
    val peakScore: Float,
    val meanScore: Float,
    val peakDb: Float,
    val snrDb: Float,
    val boutId: Long? = null,
    /** Attribution is stored beside the event, never used to filter it out. */
    val subjectLabel: String = "UNKNOWN",
    val subjectConfidence: Float = 0f,
    val clipPath: String? = null,
    /** int8-quantised embedding; see EmbeddingCodec. Prunable without losing the event. */
    val embedding: ByteArray? = null,
    val embeddingScale: Float? = null,
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is EventEntity) return false
        return id == other.id && sessionId == other.sessionId && cls == other.cls &&
            startedAtMs == other.startedAtMs && endedAtMs == other.endedAtMs &&
            peakScore == other.peakScore && meanScore == other.meanScore &&
            peakDb == other.peakDb && snrDb == other.snrDb && boutId == other.boutId &&
            subjectLabel == other.subjectLabel && subjectConfidence == other.subjectConfidence &&
            clipPath == other.clipPath && embeddingScale == other.embeddingScale &&
            (embedding?.contentEquals(other.embedding) ?: (other.embedding == null))
    }

    override fun hashCode(): Int {
        var r = id.hashCode()
        r = 31 * r + cls.hashCode()
        r = 31 * r + startedAtMs.hashCode()
        r = 31 * r + (embedding?.contentHashCode() ?: 0)
        return r
    }
}

@Entity(
    tableName = "snore_episodes",
    foreignKeys = [ForeignKey(
        entity = SessionEntity::class,
        parentColumns = ["id"], childColumns = ["sessionId"],
        onDelete = ForeignKey.CASCADE,
    )],
    indices = [Index("sessionId", "startMs")],
)
data class SnoreEpisodeEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val sessionId: Long,
    val startMs: Long,
    val endMs: Long,
    val snoreCount: Int,
    val meanIntensityDb: Float,
    val snoresPerHour: Float,
)

/** Composite primary key: one row per (session, minute, class), written once when the
 *  minute closes and never updated. */
@Entity(
    tableName = "minute_rollup",
    primaryKeys = ["sessionId", "minuteEpoch", "cls"],
    foreignKeys = [ForeignKey(
        entity = SessionEntity::class,
        parentColumns = ["id"], childColumns = ["sessionId"],
        onDelete = ForeignKey.CASCADE,
    )],
)
data class MinuteRollupEntity(
    val sessionId: Long,
    val minuteEpoch: Long,
    val cls: String,
    val count: Int,
    val maxScore: Float,
    val meanDb: Float,
)

/** User verdicts that train the attribution layer. Kept separate from events so a
 *  label survives re-detection and can be audited. */
@Entity(
    tableName = "labels",
    foreignKeys = [ForeignKey(
        entity = EventEntity::class,
        parentColumns = ["id"], childColumns = ["eventId"],
        onDelete = ForeignKey.CASCADE,
    )],
    indices = [Index(value = ["eventId"], unique = true)],
)
data class LabelEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val eventId: Long,
    /** SUBJECT / OTHER / NOT_AN_EVENT — the third is what makes false positives
     *  correctable rather than just visible. */
    val userLabel: String,
    val labeledAt: Long,
)
