package com.haman.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

/** One row per class with its count, for a session summary. */
data class ClassCount(val cls: String, val count: Int)

/** A user-labelled event with its embedding, for training attribution. */
data class LabelledEvent(
    val id: Long,
    val cls: String,
    val startedAtMs: Long,
    val endedAtMs: Long,
    val peakScore: Float,
    val meanScore: Float,
    val peakDb: Float,
    val snrDb: Float,
    val boutId: Long?,
    val embedding: ByteArray?,
    val embeddingScale: Float?,
    val userLabel: String,
)

/** Flat row for CSV/JSON export. Excludes embeddings and clip paths on purpose. */
data class ExportRow(
    val id: Long,
    val sessionId: Long,
    val cls: String,
    val startedAtMs: Long,
    val endedAtMs: Long,
    val peakScore: Float,
    val meanScore: Float,
    val peakDb: Float,
    val snrDb: Float,
    val boutId: Long?,
    val subjectLabel: String,
    val subjectConfidence: Float,
    val userLabel: String?,
)

/** One event as the platform backend needs it. No embedding, no clip path. */
data class UploadRow(
    val id: Long,
    val cls: String,
    val startedAtMs: Long,
    val endedAtMs: Long,
    val peakFrameMs: Long?,
    val peakScore: Float,
    val meanScore: Float,
    val peakDb: Float,
    val snrDb: Float,
    val boutId: Long?,
    val subjectLabel: String,
    val subjectConfidence: Float,
    val userLabel: String?,
    val hasClip: Boolean,
)

/** Enough of an event to render and label it, without loading the embedding blob. */
data class EventSummary(
    val id: Long,
    val cls: String,
    val startedAtMs: Long,
    val endedAtMs: Long,
    val peakScore: Float,
    val peakDb: Float,
    val subjectLabel: String,
    val subjectConfidence: Float,
    val clipPath: String?,
    val userLabel: String?,
)

@Dao
interface SessionDao {
    @Insert suspend fun insert(session: SessionEntity): Long

    @Query("UPDATE sessions SET endedAt = :endedAt, status = :status, noiseFloorDb = :floor, " +
        "framesSeen = :framesSeen, framesInferred = :framesInferred, micGapMs = :micGapMs, " +
        "uploadDirty = 1 WHERE id = :id")
    suspend fun finish(id: Long, endedAt: Long, status: String, floor: Float,
                       framesSeen: Long, framesInferred: Long, micGapMs: Long)

    @Query("SELECT * FROM sessions ORDER BY startedAt DESC")
    fun observeAll(): Flow<List<SessionEntity>>

    @Query("SELECT * FROM sessions WHERE id = :id")
    suspend fun byId(id: Long): SessionEntity?

    /** Sessions left 'running' by a crash or a kill. Reconciled at startup so the UI
     *  never shows a night that has been recording for three days. */
    @Query("SELECT * FROM sessions WHERE status = 'running'")
    suspend fun running(): List<SessionEntity>

    @Query("DELETE FROM sessions WHERE id = :id")
    suspend fun delete(id: Long)

    /** Finished nights that started in [fromMs, toMs), newest first. */
    @Query("SELECT * FROM sessions WHERE status != 'running' AND startedAt >= :fromMs " +
        "AND startedAt < :toMs ORDER BY startedAt DESC")
    suspend fun finishedBetween(fromMs: Long, toMs: Long): List<SessionEntity>

    // ── Platform upload ──────────────────────────────────────────────────────────

    /** Finished nights with anything still to upload: the night itself (never sent, or
     *  changed since) or a clip of an uploaded event class. Nights the server rejected
     *  as malformed are excluded; retrying them cannot succeed. */
    @Query(PENDING_UPLOAD + " ORDER BY s.startedAt ASC")
    suspend fun pendingUpload(): List<Long>

    @Query("SELECT COUNT(*) FROM (" + PENDING_UPLOAD + ")")
    suspend fun countPendingUpload(): Int

    @Query("UPDATE sessions SET serverSessionId = :serverId, lastUploadedAt = :at, " +
        "uploadDirty = 0 WHERE id = :id")
    suspend fun markUploaded(id: Long, serverId: Long, at: Long)

    @Query("UPDATE sessions SET uploadError = :error WHERE id = :id")
    suspend fun markUploadRejected(id: Long, error: String)

    @Query("UPDATE sessions SET uploadDirty = 1 WHERE id = :id")
    suspend fun markChanged(id: Long)

    companion object {
        const val PENDING_UPLOAD =
            "SELECT s.id FROM sessions s WHERE s.status != 'running' AND s.uploadError IS NULL " +
            "AND (s.serverSessionId IS NULL OR s.uploadDirty = 1 OR EXISTS (" +
            "SELECT 1 FROM events e WHERE e.sessionId = s.id AND e.clipPath IS NOT NULL " +
            "AND e.clipUpload IS NULL AND e.cls IN ('COUGH', 'SNEEZE')))"
    }
}

/** An event whose clip still has to be uploaded. */
data class PendingClip(val id: Long, val clipPath: String)

/** The cough events of a night, for the summary the web layer shows. */
data class CoughTime(val startedAtMs: Long)

@Dao
interface EventDao {
    @Insert suspend fun insertAll(events: List<EventEntity>): List<Long>

    @Query("SELECT COUNT(*) FROM events WHERE sessionId = :sessionId")
    suspend fun countFor(sessionId: Long): Int

    @Query("SELECT cls, COUNT(*) as count FROM events WHERE sessionId = :sessionId GROUP BY cls")
    fun observeCounts(sessionId: Long): Flow<List<ClassCount>>

    @Query(
        "SELECT e.id, e.cls, e.startedAtMs, e.endedAtMs, e.peakScore, e.peakDb, " +
        "e.subjectLabel, e.subjectConfidence, e.clipPath, l.userLabel " +
        "FROM events e LEFT JOIN labels l ON l.eventId = e.id " +
        "WHERE e.sessionId = :sessionId ORDER BY e.startedAtMs ASC"
    )
    fun observeSummaries(sessionId: Long): Flow<List<EventSummary>>

    @Query("SELECT * FROM events WHERE id = :id")
    suspend fun byId(id: Long): EventEntity?

    /** Training set for the attribution head: only events the user has labelled, and
     *  only those that still carry an embedding. Returns the *user's* verdict, not the
     *  model's earlier guess - training on your own predictions learns nothing. */
    @Query(
        "SELECT e.id, e.cls, e.startedAtMs, e.endedAtMs, e.peakScore, e.meanScore, " +
        "e.peakDb, e.snrDb, e.boutId, e.embedding, e.embeddingScale, l.userLabel " +
        "FROM events e JOIN labels l ON l.eventId = e.id " +
        "WHERE l.userLabel IN ('SUBJECT','OTHER') AND e.embedding IS NOT NULL"
    )
    suspend fun labelledWithEmbeddings(): List<LabelledEvent>

    @Query(
        "SELECT e.id, e.sessionId, e.cls, e.startedAtMs, e.endedAtMs, e.peakScore, " +
        "e.meanScore, e.peakDb, e.snrDb, e.boutId, e.subjectLabel, e.subjectConfidence, " +
        "l.userLabel FROM events e LEFT JOIN labels l ON l.eventId = e.id " +
        "WHERE e.sessionId = :sessionId ORDER BY e.startedAtMs ASC"
    )
    suspend fun forExport(sessionId: Long): List<ExportRow>

    @Query(
        "SELECT e.id, e.cls, e.startedAtMs, e.endedAtMs, e.peakFrameMs, e.peakScore, " +
        "e.meanScore, e.peakDb, e.snrDb, e.boutId, e.subjectLabel, e.subjectConfidence, " +
        "l.userLabel, (e.clipPath IS NOT NULL) AS hasClip " +
        "FROM events e LEFT JOIN labels l ON l.eventId = e.id " +
        "WHERE e.sessionId = :sessionId AND e.cls IN (:classes) ORDER BY e.startedAtMs ASC"
    )
    suspend fun forUpload(sessionId: Long, classes: List<String>): List<UploadRow>

    /** Clips of a night still to upload, for the given (uploaded) event classes. */
    @Query("SELECT id, clipPath FROM events WHERE sessionId = :sessionId AND clipPath IS NOT NULL " +
        "AND clipUpload IS NULL AND cls IN (:classes) ORDER BY startedAtMs ASC")
    suspend fun pendingClips(sessionId: Long, classes: List<String>): List<PendingClip>

    @Query("UPDATE events SET clipUpload = :state WHERE id = :id")
    suspend fun setClipUpload(id: Long, state: String)

    @Query("UPDATE events SET clipUpload = :state WHERE sessionId = :sessionId AND clipPath IS NOT NULL " +
        "AND clipUpload IS NULL AND cls IN (:classes)")
    suspend fun setPendingClipsUpload(sessionId: Long, classes: List<String>, state: String)

    /** Coughs that count for the user (not rejected by them), same rule as the server. */
    @Query("SELECT e.startedAtMs FROM events e LEFT JOIN labels l ON l.eventId = e.id " +
        "WHERE e.sessionId = :sessionId AND e.cls = 'COUGH' " +
        "AND (l.userLabel IS NULL OR l.userLabel = 'SUBJECT') ORDER BY e.startedAtMs ASC")
    suspend fun countedCoughTimes(sessionId: Long): List<CoughTime>

    @Query("SELECT clipPath FROM events WHERE clipPath IS NOT NULL AND startedAtMs < :before")
    suspend fun clipsOlderThan(before: Long): List<String>

    /** Retention: drop audio and embeddings past the window but keep the events. */
    @Query("UPDATE events SET clipPath = NULL WHERE startedAtMs < :before")
    suspend fun clearClipsOlderThan(before: Long)

    @Query("UPDATE events SET embedding = NULL, embeddingScale = NULL WHERE startedAtMs < :before")
    suspend fun clearEmbeddingsOlderThan(before: Long)
}

@Dao
interface EpisodeDao {
    @Insert suspend fun insertAll(episodes: List<SnoreEpisodeEntity>)

    @Query("SELECT * FROM snore_episodes WHERE sessionId = :sessionId ORDER BY startMs ASC")
    fun observeFor(sessionId: Long): Flow<List<SnoreEpisodeEntity>>

    @Query("SELECT * FROM snore_episodes WHERE sessionId = :sessionId ORDER BY startMs ASC")
    suspend fun forSession(sessionId: Long): List<SnoreEpisodeEntity>

    @Query("SELECT COALESCE(SUM(endMs - startMs), 0) FROM snore_episodes WHERE sessionId = :sessionId")
    suspend fun totalSnoreMs(sessionId: Long): Long
}

@Dao
interface RollupDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(rows: List<MinuteRollupEntity>)

    @Query("SELECT * FROM minute_rollup WHERE sessionId = :sessionId ORDER BY minuteEpoch ASC")
    fun observeFor(sessionId: Long): Flow<List<MinuteRollupEntity>>
}

@Dao
interface LabelDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(label: LabelEntity)

    @Query("SELECT COUNT(*) FROM labels WHERE userLabel IN ('SUBJECT','OTHER')")
    fun observeAttributionLabelCount(): Flow<Int>

    @Query("DELETE FROM labels WHERE eventId = :eventId")
    suspend fun clearFor(eventId: Long)
}

/** Batched writes. Per-event commits on a sleeping CPU are a measurable battery cost,
 *  so the recorder accumulates and calls this every few seconds. */
@Dao
abstract class BatchDao {
    @Transaction
    open suspend fun writeBatch(
        events: List<EventEntity>,
        episodes: List<SnoreEpisodeEntity>,
        rollups: List<MinuteRollupEntity>,
        eventDao: EventDao,
        episodeDao: EpisodeDao,
        rollupDao: RollupDao,
    ) {
        if (events.isNotEmpty()) eventDao.insertAll(events)
        if (episodes.isNotEmpty()) episodeDao.insertAll(episodes)
        if (rollups.isNotEmpty()) rollupDao.insertAll(rollups)
    }
}
