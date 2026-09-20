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
        "framesSeen = :framesSeen, framesInferred = :framesInferred, micGapMs = :micGapMs WHERE id = :id")
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
}

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
