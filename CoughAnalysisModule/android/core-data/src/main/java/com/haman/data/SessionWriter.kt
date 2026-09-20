package com.haman.data

import com.haman.domain.AcousticClass
import com.haman.domain.DetectedEvent
import com.haman.domain.EmbeddingCodec
import com.haman.domain.MinuteBucket
import com.haman.domain.SnoreEpisode

/**
 * Buffers a session's output and writes it in periodic transactions.
 *
 * Committing per event would mean thousands of separate transactions across a night on
 * a CPU that is otherwise idle - one of the few places in this app where the storage
 * layer, not the model, is the battery cost.
 */
class SessionWriter(
    private val db: HamanDatabase,
    private val sessionId: Long,
) {
    private val events = mutableListOf<EventEntity>()
    private val episodes = mutableListOf<SnoreEpisodeEntity>()
    private val rollups = mutableListOf<MinuteRollupEntity>()

    var totalEvents: Int = 0
        private set

    @Synchronized
    fun addEvent(event: DetectedEvent, embedding: FloatArray?, clipPath: String?) {
        val q = embedding?.let { EmbeddingCodec.encode(it) }
        events.add(
            EventEntity(
                sessionId = sessionId,
                cls = event.cls.name,
                startedAtMs = event.startMs,
                endedAtMs = event.endMs,
                peakScore = event.peakScore,
                meanScore = event.meanScore,
                peakDb = event.peakDb,
                snrDb = event.snrDb,
                boutId = event.boutId,
                subjectLabel = event.subject.name,
                subjectConfidence = event.subjectConfidence,
                clipPath = clipPath,
                embedding = q?.bytes,
                embeddingScale = q?.scale,
            )
        )
        totalEvents++
    }

    @Synchronized
    fun addEpisode(ep: SnoreEpisode) {
        episodes.add(
            SnoreEpisodeEntity(
                sessionId = sessionId,
                startMs = ep.startMs,
                endMs = ep.endMs,
                snoreCount = ep.snoreCount,
                meanIntensityDb = ep.meanIntensityDb,
                snoresPerHour = ep.snoresPerHour,
            )
        )
    }

    @Synchronized
    fun addBuckets(buckets: List<MinuteBucket>) {
        buckets.forEach {
            rollups.add(
                MinuteRollupEntity(
                    sessionId = sessionId,
                    minuteEpoch = it.minuteEpoch,
                    cls = it.cls.name,
                    count = it.count,
                    maxScore = it.maxScore,
                    meanDb = it.meanDb,
                )
            )
        }
    }

    @Synchronized
    private fun drain(): Triple<List<EventEntity>, List<SnoreEpisodeEntity>, List<MinuteRollupEntity>> {
        val e = events.toList(); val s = episodes.toList(); val r = rollups.toList()
        events.clear(); episodes.clear(); rollups.clear()
        return Triple(e, s, r)
    }

    val hasPending: Boolean
        @Synchronized get() = events.isNotEmpty() || episodes.isNotEmpty() || rollups.isNotEmpty()

    suspend fun flush() {
        val (e, s, r) = drain()
        if (e.isEmpty() && s.isEmpty() && r.isEmpty()) return
        db.batch().writeBatch(e, s, r, db.events(), db.episodes(), db.rollups())
    }
}
