package com.haman.sleep.service

import com.haman.domain.AcousticClass
import kotlinx.coroutines.flow.MutableStateFlow
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
        val error: String? = null,
    )

    private val _state = MutableStateFlow(Live())
    val state: StateFlow<Live> = _state.asStateFlow()

    internal fun update(block: (Live) -> Live) { _state.value = block(_state.value) }
    internal fun reset() { _state.value = Live() }
}
