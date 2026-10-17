package com.haman.domain

/**
 * Groups snore events into episodes.
 *
 * Snoring fires once per breath — roughly 900 events across a bad night. Those rows
 * are worth keeping for analysis but are meaningless to read. The episode is the unit
 * a person understands: "you snored from 01:12 to 02:40, 312 snores".
 */
class SnoreEpisodeAggregator(private val gapMs: Long = 60_000) {
    private var startMs = 0L
    private var endMs = 0L
    private var count = 0
    private var dbSum = 0.0
    private var open = false

    /** @return the previous episode if this event started a new one. */
    fun add(event: DetectedEvent): SnoreEpisode? {
        require(event.cls == AcousticClass.SNORE)
        var completed: SnoreEpisode? = null
        if (open && event.startMs - endMs > gapMs) {
            completed = build()
            open = false
        }
        if (!open) {
            open = true; startMs = event.startMs; count = 0; dbSum = 0.0
        }
        endMs = event.endMs
        count++
        dbSum += event.peakDb
        return completed
    }

    /** Close the in-progress episode, if any. Timing out matters: without this a
     *  session that ends mid-snore loses its last episode. */
    fun flush(): SnoreEpisode? {
        if (!open) return null
        open = false
        return build()
    }

    private fun build() = SnoreEpisode(
        startMs = startMs,
        endMs = endMs,
        snoreCount = count,
        meanIntensityDb = if (count > 0) (dbSum / count).toFloat() else -160f,
    )
}

/**
 * Accumulates per-minute × class counters.
 *
 * Exists so the timeline UI reads ~480 rows for a night instead of scanning tens of
 * thousands of events. Buckets are emitted only once their minute has passed, so a
 * bucket is written exactly once and never updated.
 */
class MinuteRollupAccumulator {
    private class Bucket {
        var count = 0
        var maxScore = 0f
        var dbSum = 0.0
        var dbFrames = 0
    }

    private val open = LinkedHashMap<Long, MutableMap<AcousticClass, Bucket>>()

    private fun minuteOf(ms: Long) = ms / 60_000L

    /** Every frame contributes level, so a minute with no events still records how
     *  loud the room was. */
    fun addFrame(timestampMs: Long, rmsDb: Float, smoothed: FloatArray) {
        val m = open.getOrPut(minuteOf(timestampMs)) { mutableMapOf() }
        for (cls in AcousticClass.LOGGED) {
            val b = m.getOrPut(cls) { Bucket() }
            b.dbSum += rmsDb; b.dbFrames++
            val s = smoothed[cls.ordinal]
            if (s > b.maxScore) b.maxScore = s
        }
    }

    fun addEvent(event: DetectedEvent) {
        val m = open.getOrPut(minuteOf(event.startMs)) { mutableMapOf() }
        m.getOrPut(event.cls) { Bucket() }.count++
    }

    /** Emit buckets for minutes strictly before the current one. */
    fun drainCompleted(nowMs: Long): List<MinuteBucket> {
        val cutoff = minuteOf(nowMs)
        val out = mutableListOf<MinuteBucket>()
        val it = open.entries.iterator()
        while (it.hasNext()) {
            val (minute, classes) = it.next()
            if (minute >= cutoff) continue
            emit(minute, classes, out)
            it.remove()
        }
        return out
    }

    fun drainAll(): List<MinuteBucket> {
        val out = mutableListOf<MinuteBucket>()
        open.forEach { (minute, classes) -> emit(minute, classes, out) }
        open.clear()
        return out
    }

    private fun emit(minute: Long, classes: Map<AcousticClass, Bucket>, out: MutableList<MinuteBucket>) {
        classes.forEach { (cls, b) ->
            // Skip empty buckets for classes that saw nothing at all this minute.
            if (b.count == 0 && b.maxScore <= 0f) return@forEach
            out.add(
                MinuteBucket(
                    minuteEpoch = minute,
                    cls = cls,
                    count = b.count,
                    maxScore = b.maxScore,
                    meanDb = if (b.dbFrames > 0) (b.dbSum / b.dbFrames).toFloat() else -160f,
                )
            )
        }
    }
}
