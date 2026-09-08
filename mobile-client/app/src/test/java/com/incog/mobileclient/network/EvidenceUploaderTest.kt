package com.incog.mobileclient.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EvidenceUploaderTest {

    private fun body(contactName: String, contactPhone: String, smsSent: Boolean?) =
        EvidenceUploader.buildBody(
            deviceId = "dev-1",
            latitude = 12.9459,
            longitude = 77.5999,
            encryptedEvidenceBase64 = "BLOB",
            isStealthActive = true,
            contactName = contactName,
            contactPhone = contactPhone,
            contactSmsSent = smsSent
        )

    @Test
    fun `core fields are always present`() {
        val b = body("Aarush", "+919876543210", true)
        assertEquals("dev-1", b["device_id"])
        assertEquals(12.9459, b["latitude"])
        assertEquals(77.5999, b["longitude"])
        assertEquals(true, b["is_stealth_active"])
        assertEquals("BLOB", b["encrypted_evidence"])
    }

    @Test
    fun `contact fields are sent, even when blank`() {
        val withContact = body("Aarush", "+919876543210", true)
        assertEquals("Aarush", withContact["contact_name"])
        assertEquals("+919876543210", withContact["contact_phone"])

        val blank = body("", "", null)
        assertEquals("", blank["contact_name"])
        assertEquals("", blank["contact_phone"])
    }

    @Test
    fun `contact_sms_sent is a real boolean when set`() {
        assertEquals(true, body("A", "+911234567", true)["contact_sms_sent"])
        assertEquals(false, body("A", "+911234567", false)["contact_sms_sent"])
        // Guard against regressing to the string "true"/"false".
        assertTrue(body("A", "+911234567", true)["contact_sms_sent"] is Boolean)
    }

    @Test
    fun `contact_sms_sent is OMITTED when null (never sent as false)`() {
        val b = body("A", "", null)
        assertFalse(b.containsKey("contact_sms_sent"))
    }
}
