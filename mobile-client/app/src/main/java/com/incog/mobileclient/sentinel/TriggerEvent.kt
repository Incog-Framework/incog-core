package com.incog.mobileclient.sentinel

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * Phase 1 output — emitted when the Sentinel Engine detects the hidden trigger pattern.
 *
 * Mirrors the Trigger Event Object in the workflow spec:
 * `{ "trigger": true, "timestamp": ..., "triggerType": "DDU" }`
 */
data class TriggerEvent(
    val trigger: Boolean,
    val timestamp: Long,
    val triggerType: String
)

/**
 * Phase 1 -> Phase 2 seam.
 *
 * The AccessibilityService and the rest of the app share one process, so a process-wide
 * hot flow is the simplest reliable channel. Phase 2 (GhostState) will collect from here to
 * start the covert session. `extraBufferCapacity = 1` lets [emit] succeed without a live
 * collector so a trigger is never silently dropped between detection and collection.
 */
object SentinelBus {
    private val _triggers = MutableSharedFlow<TriggerEvent>(extraBufferCapacity = 1)
    val triggers: SharedFlow<TriggerEvent> = _triggers.asSharedFlow()

    fun emit(event: TriggerEvent) {
        _triggers.tryEmit(event)
    }
}
