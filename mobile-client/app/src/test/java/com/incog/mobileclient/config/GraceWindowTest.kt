package com.incog.mobileclient.config

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The grace window bounds. These matter because the value reaches the alert path: too large and a
 * real emergency waits, negative and [android.os.Handler.postDelayed] would fire instantly while
 * logging a hold that never happened.
 */
class GraceWindowTest {

    @Test
    fun `clamp keeps an in-range hold unchanged`() {
        assertEquals(10, IncogConfig.clampGraceSeconds(10))
        assertEquals(1, IncogConfig.clampGraceSeconds(1))
        assertEquals(IncogConfig.MAX_GRACE_SECONDS, IncogConfig.clampGraceSeconds(IncogConfig.MAX_GRACE_SECONDS))
    }

    @Test
    fun `clamp allows zero, meaning alert immediately`() {
        assertEquals(0, IncogConfig.clampGraceSeconds(0))
    }

    @Test
    fun `clamp floors a negative hold at zero so the alert is never deferred indefinitely`() {
        assertEquals(0, IncogConfig.clampGraceSeconds(-1))
        assertEquals(0, IncogConfig.clampGraceSeconds(Int.MIN_VALUE))
    }

    @Test
    fun `clamp caps an oversized hold so a real emergency cannot be delayed past the maximum`() {
        assertEquals(IncogConfig.MAX_GRACE_SECONDS, IncogConfig.clampGraceSeconds(600))
        assertEquals(IncogConfig.MAX_GRACE_SECONDS, IncogConfig.clampGraceSeconds(Int.MAX_VALUE))
    }

    @Test
    fun `millis converts seconds and applies the same bounds`() {
        assertEquals(10_000L, IncogConfig.graceMillis(10))
        assertEquals(0L, IncogConfig.graceMillis(0))
        assertEquals(0L, IncogConfig.graceMillis(-5))
        assertEquals(IncogConfig.MAX_GRACE_SECONDS * 1000L, IncogConfig.graceMillis(Int.MAX_VALUE))
    }

    @Test
    fun `the default hold is within bounds and non-zero`() {
        // A zero default would silently ship the old no-window behaviour.
        assertEquals(DEFAULT_GRACE_SECONDS, IncogConfig.clampGraceSeconds(DEFAULT_GRACE_SECONDS))
        assertEquals(true, DEFAULT_GRACE_SECONDS > 0)
    }
}
