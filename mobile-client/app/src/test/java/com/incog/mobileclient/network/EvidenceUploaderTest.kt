package com.incog.mobileclient.network

import com.incog.mobileclient.alert.ContactSms
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EvidenceUploaderTest {

    private fun body(contacts: List<ContactSms>) =
        EvidenceUploader.buildBody(
            deviceId = "dev-1",
            latitude = 12.9459,
            longitude = 77.5999,
            encryptedEvidenceBase64 = "BLOB",
            isStealthActive = true,
            contacts = contacts
        )

    @Test
    fun `core fields are always present`() {
        val b = body(listOf(ContactSms("Aarush", "+919876543210", true)))
        assertEquals("dev-1", b["device_id"])
        assertEquals(12.9459, b["latitude"])
        assertEquals(77.5999, b["longitude"])
        assertEquals(true, b["is_stealth_active"])
        assertEquals("BLOB", b["encrypted_evidence"])
    }

    @Test
    fun `no contacts - single fields blank, sms flag and array omitted`() {
        val b = body(emptyList())
        assertEquals("", b["contact_name"])
        assertEquals("", b["contact_phone"])
        assertFalse(b.containsKey("contact_sms_sent")) // null=didn't try, never sent as false
        assertFalse(b.containsKey("contacts"))
    }

    @Test
    fun `first contact is mirrored into the legacy single fields`() {
        val b = body(
            listOf(
                ContactSms("Aarush", "+919876543210", true),
                ContactSms("Mom", "+911111111111", false),
            )
        )
        assertEquals("Aarush", b["contact_name"])
        assertEquals("+919876543210", b["contact_phone"])
        assertEquals(true, b["contact_sms_sent"])
        assertTrue(b["contact_sms_sent"] is Boolean) // a real JSON boolean, not "true"
    }

    @Test
    fun `contacts array carries every contact with its sms result`() {
        @Suppress("UNCHECKED_CAST")
        val arr = body(
            listOf(
                ContactSms("Aarush", "+919876543210", true),
                ContactSms("Mom", "+911111111111", false),
            )
        )["contacts"] as List<Map<String, Any?>>

        assertEquals(2, arr.size)
        assertEquals("Aarush", arr[0]["name"]); assertEquals("+919876543210", arr[0]["phone"]); assertEquals(true, arr[0]["sms_sent"])
        assertEquals("Mom", arr[1]["name"]); assertEquals("+911111111111", arr[1]["phone"]); assertEquals(false, arr[1]["sms_sent"])
    }
}
