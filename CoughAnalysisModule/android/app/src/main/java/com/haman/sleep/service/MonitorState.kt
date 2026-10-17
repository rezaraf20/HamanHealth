package com.haman.sleep.service

import com.haman.domain.AcousticClass
import com.haman.domain.DetectedEvent
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Live state published by the monitoring service.
 *
 * A process-wide object rather than a bound service: there is exactly one recording at
 * a time, the UI is frequently not running at all (the whole point is that the phone
 * sits on a nightstand with the screen off), and binding adds lifecycle complexity
 * with nothing to show for it.
 */
object MonitorState {
    data class Live(
        val running: Boolean = false,
        val sessionId: Long = -1,
        val startedAt: Long = 0,
        val rmsDb: Float = -160f,
        val noiseFloorDb: Float = -90f,
        val gateOpen: Boolean = false,
        val gateSkipRatio: Float = 0f,
        val audioSource: String = "",
        val counts: Map<AcousticClass, Int> = emptyMap(),
        val lastEventAt: Long = 0,
        val lastEventClass: AcousticClass? = null,
        val micGapMs: Long = 0,
        /** null until enough loud audio has been heard to judge. */
        val bandLimited: Boolean? = null,
        val error: String? = null,
        /** Epoch ms at which the service ends the session by itself; 0 = never. */
        val autoStopAt: Long = 0,
        /** Stop requested, final events and the session row still being written. */
        val stopping: Boolean = false,
        /** The last session whose row has been finalised (sessions().finish() returned). */
        val lastFinishedSessionId: Long = -1,
    )

    private val _state = MutableStateFlow(Live())
    val state: StateFlow<Live> = _state.asStateFlow()

    /** One entry per detected event (cough, sneeze, snore), for live listeners such as
     *  the web interface. Unlike [state], nothing is conflated: two coughs in quick
     *  succession are two emissions. tryEmit with DROP_OLDEST never suspends, so the
     *  capture loop can never be held up by a slow or absent listener. */
    data class LiveEvent(val sessionId: Long, val event: DetectedEvent)

    private val _events = MutableSharedFlow<LiveEvent>(
        extraBufferCapacity = 64, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val events: SharedFlow<LiveEvent> = _events

    internal fun emit(sessionId: Long, event: DetectedEvent) { _events.tryEmit(LiveEvent(sessionId, event)) }

    @Synchronized
    internal fun update(block: (Live) -> Live) { _state.value = block(_state.value) }
    internal fun reset() { _state.value = Live() }
}
