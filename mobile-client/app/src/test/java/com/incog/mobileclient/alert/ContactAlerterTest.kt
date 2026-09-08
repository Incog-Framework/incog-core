package com.incog.mobileclient.alert

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Covers the pure logic. The actual SmsManager send + SEND_SMS permission path needs the Android
 * framework, so it's verified on-device (see the PR's verification steps), not here.
 */
class ContactAlerterTest {

    @Test
    fun `shouldAttempt is false for a blank number`() {
        assertFalse(ContactAlerter.shouldAttempt(""))
        assertFalse(ContactAlerter.shouldAttempt("   "))
        assertTrue(ContactAlerter.shouldAttempt("+919876543210"))
    }

    @Test
    fun `message carries the emergency marker, coordinates and a maps link`() {
        val msg = ContactAlerter.buildMessage("Aarush", 12.9459, 77.5999)
        assertTrue(msg.contains("INCOG EMERGENCY"))
        assertTrue(msg.contains("Aarush"))
        assertTrue(msg.contains("12.945900"))
        assertTrue(msg.contains("77.599900"))
        assertTrue(msg.contains("https://maps.google.com/?q=12.9459,77.5999"))
    }

    @Test
    fun `redact keeps only the last three digits`() {
        assertEquals("***069", ContactAlerter.redact("+917259644069"))
        assertEquals("***", ContactAlerter.redact("12"))
    }
}
