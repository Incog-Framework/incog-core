package com.incog.mobileclient.sentinel

import android.accessibilityservice.AccessibilityService
import android.util.Log
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import com.incog.mobileclient.ghost.GhostStateService

/**
 * Phase 1 — the Sentinel Engine.
 *
 * A background [AccessibilityService] that intercepts hardware volume-key events (even when the
 * calculator is not in the foreground and the screen is locked) and watches for the covert
 * trigger pattern: Volume Down -> Volume Down -> Volume Up ("DDU"), pressed in quick succession.
 *
 * On a match it emits a [TriggerEvent] on [SentinelBus] (the Phase 1 -> Phase 2 seam).
 *
 * Volume handling: the service is fully passive — it observes volume key events but never consumes
 * them, so normal volume control keeps working exactly as usual (crucial for a believable decoy).
 * The tradeoff is that performing the DDU gesture briefly nudges the volume and shows the system
 * volume popup; this is harmless during a real emergency and far less suspicious than volume
 * buttons that behave incorrectly. (Consuming events to hide the popup is possible but reliably
 * breaks normal volume behaviour on real hardware, so it is intentionally not done here.)
 */
class SentinelAccessibilityService : AccessibilityService() {

    private data class Press(val keyCode: Int, val timeMs: Long)

    private val recentPresses = ArrayDeque<Press>()

    override fun onServiceConnected() {
        super.onServiceConnected()
        Log.i(TAG, "Sentinel Engine connected — listening for DDU trigger.")
    }

    override fun onKeyEvent(event: KeyEvent): Boolean {
        val code = event.keyCode
        if (code != KeyEvent.KEYCODE_VOLUME_DOWN && code != KeyEvent.KEYCODE_VOLUME_UP) {
            return false
        }

        // Count one discrete press on the initial key-down (ignore auto-repeat from holding).
        if (event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0) {
            registerPress(code, event.eventTime)
        }

        // Always pass the event through untouched — never break normal volume behaviour.
        return false
    }

    private fun registerPress(keyCode: Int, now: Long) {
        // Drop presses that are too old to be part of the current pattern attempt.
        while (recentPresses.isNotEmpty() && now - recentPresses.first().timeMs > PATTERN_WINDOW_MS) {
            recentPresses.removeFirst()
        }
        recentPresses.addLast(Press(keyCode, now))
        while (recentPresses.size > PATTERN_LENGTH) {
            recentPresses.removeFirst()
        }
        checkForTrigger(now)
    }

    private fun checkForTrigger(now: Long) {
        if (recentPresses.size < PATTERN_LENGTH) return

        val pattern = recentPresses.map { it.keyCode }
        if (pattern == DDU_PATTERN) {
            recentPresses.clear()
            val event = TriggerEvent(
                trigger = true,
                timestamp = now,
                triggerType = "DDU"
            )
            Log.i(TAG, "DDU trigger detected -> emitting $event")
            SentinelBus.emit(event)

            // Phase 1 -> Phase 2: launch (or refresh) Ghost State. Starting the foreground service
            // directly from the always-alive accessibility service is reliable even when no
            // Activity is running (app backgrounded / screen locked). The service itself decides
            // whether to begin a new session or just re-post its notification if already active.
            GhostStateService.start(this)
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Not used — the Sentinel Engine only cares about key events, but this override is required.
    }

    override fun onInterrupt() {
        // Required override; nothing to clean up on interrupt.
    }

    companion object {
        private const val TAG = "SentinelEngine"

        /** All three presses of the trigger must land within this window (ms). */
        private const val PATTERN_WINDOW_MS = 2000L

        private const val PATTERN_LENGTH = 3

        /** Down -> Down -> Up. */
        private val DDU_PATTERN = listOf(
            KeyEvent.KEYCODE_VOLUME_DOWN,
            KeyEvent.KEYCODE_VOLUME_DOWN,
            KeyEvent.KEYCODE_VOLUME_UP
        )
    }
}
