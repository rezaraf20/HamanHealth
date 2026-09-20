package com.haman.domain

/**
 * Turns a stream of per-frame scores into discrete events.
 *
 * This is the piece that separates "classifies clips well" from "usable overnight".
 * A per-frame threshold on an 8-hour stream produces a mess: one cough spans 2-3
 * frames and its score dips mid-event, so naive thresholding emits three events for
 * one cough and thousands of single-frame false alarms per night.
 *
 * Four mechanisms, each targeting a specific failure:
 *  - **hysteresis**  — a score oscillating around one threshold fragments an event
 *  - **merge gap**   — a real event's score dips mid-way; brief dips must not split it
 *  - **min duration**— single-frame spikes are transients, not events
 *  - **refractory**  — an event's own tail/echo must not immediately re-trigger it
 */
class EventAssembler(
    private var config: DetectorConfig,
    private val frameHopMs: Long = 480L,
) {
    private class ClassState {
        var active = false
        var startMs = 0L
        var lastAboveMs = 0L
        var peakScore = 0f
        var peakFrameMs = 0L
        var peakDb = -160f
        var scoreSum = 0.0
        var frames = 0
        var refractoryUntilMs = Long.MIN_VALUE
        var floorAtStartDb = -90f

        fun reset() {
            active = false; peakScore = 0f; peakDb = -160f; scoreSum = 0.0; frames = 0
        }
    }

    private val states = Array(AcousticClass.ALL.size) { ClassState() }
    private var lastCoughEndMs = Long.MIN_VALUE
    private var currentBoutId = 0L

    fun updateConfig(newConfig: DetectorConfig) { config = newConfig }

    /**
     * Feed one frame of smoothed scores.
     *
     * @param gateOpen false when the frame was below the noise gate. Gated frames
     *   still advance time (so active events can close naturally) but cannot open one.
     * @return events that closed on this frame, if any.
     */
    fun process(
        timestampMs: Long,
        smoothed: FloatArray,
        rmsDb: Float,
        gateOpen: Boolean,
        noiseFloorDb: Float,
    ): List<DetectedEvent> {
        var emitted: MutableList<DetectedEvent>? = null

        // Sustained talking suppresses new events. People talking, a TV or a radio are
        // the dominant false-positive source, and none of them are sleep events. The
        // threshold is high so that the speech-like fringe of a real cough does not
        // suppress the cough itself.
        val speechActive = smoothed[AcousticClass.SPEECH.ordinal] >= config.speechSuppressionThreshold

        for (cls in AcousticClass.LOGGED) {
            val st = states[cls.ordinal]
            val p = smoothed[cls.ordinal]
            val params = config.paramsFor(cls)

            if (st.active) {
                if (p >= params.offThreshold) {
                    st.lastAboveMs = timestampMs
                    if (p > st.peakScore) { st.peakScore = p; st.peakFrameMs = timestampMs }
                    if (rmsDb > st.peakDb) st.peakDb = rmsDb
                    st.scoreSum += p
                    st.frames++
                }
                // Close on a trailing gap, or on hitting the hard duration ceiling.
                // The ceiling matters when the off-threshold is low enough that room
                // noise alone sustains the event.
                val gapClosed = timestampMs - st.lastAboveMs >= params.mergeGapMs
                val tooLong = timestampMs - st.startMs >= params.maxDurationMs
                if (gapClosed || tooLong) {
                    val ev = close(cls, st, params, timestampMs)
                    if (ev != null) {
                        if (emitted == null) emitted = mutableListOf()
                        emitted.add(ev)
                    }
                }
            } else {
                val ready = timestampMs >= st.refractoryUntilMs
                if (ready && gateOpen && !speechActive && p >= params.onThreshold) {
                    st.reset()
                    st.active = true
                    st.startMs = timestampMs
                    st.lastAboveMs = timestampMs
                    st.peakScore = p
                    st.peakFrameMs = timestampMs
                    st.peakDb = rmsDb
                    st.scoreSum = p.toDouble()
                    st.frames = 1
                    st.floorAtStartDb = noiseFloorDb
                }
            }
        }
        return emitted ?: emptyList()
    }

    /** Close anything still open — called when a session ends so a final event
     *  in progress is not silently lost. */
    fun flush(atMs: Long): List<DetectedEvent> {
        val out = mutableListOf<DetectedEvent>()
        for (cls in AcousticClass.LOGGED) {
            val st = states[cls.ordinal]
            if (st.active) close(cls, st, config.paramsFor(cls), atMs)?.let(out::add)
        }
        return out
    }

    private fun close(
        cls: AcousticClass,
        st: ClassState,
        params: ClassParams,
        nowMs: Long,
    ): DetectedEvent? {
        st.active = false
        // The event runs to the end of the last frame that was above threshold, not
        // to now — now is already inside the trailing silence. Clamped to the ceiling.
        val endMs = minOf(st.lastAboveMs + frameHopMs, st.startMs + params.maxDurationMs)
        val duration = endMs - st.startMs
        if (duration < params.minDurationMs) return null // transient, discard

        st.refractoryUntilMs = nowMs + params.refractoryMs

        var boutId: Long? = null
        if (cls == AcousticClass.COUGH) {
            if (st.startMs - lastCoughEndMs > config.coughBoutGapMs) currentBoutId++
            boutId = currentBoutId
            lastCoughEndMs = endMs
        }

        return DetectedEvent(
            cls = cls,
            startMs = st.startMs,
            endMs = endMs,
            peakScore = st.peakScore,
            meanScore = if (st.frames > 0) (st.scoreSum / st.frames).toFloat() else st.peakScore,
            peakDb = st.peakDb,
            snrDb = st.peakDb - st.floorAtStartDb,
            peakFrameMs = st.peakFrameMs,
            boutId = boutId,
        )
    }

    fun reset() {
        states.forEach { it.reset(); it.refractoryUntilMs = Long.MIN_VALUE }
        lastCoughEndMs = Long.MIN_VALUE
        currentBoutId = 0L
    }
}
