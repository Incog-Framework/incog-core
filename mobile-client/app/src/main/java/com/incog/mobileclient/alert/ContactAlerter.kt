package com.incog.mobileclient.alert

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.telephony.SmsManager
import android.util.Log
import androidx.core.content.ContextCompat

/**
 * Sends the emergency SMS to the user's trusted contact directly from the device — the PRIMARY
 * alert path (the backend alert is redundancy). Device-sent SMS is the only free path that actually
 * reaches an arbitrary number (the backend's Twilio trial can't send free-form messages), it uses
 * the cellular network so it works with no data connection, and it arrives from the user's own
 * number.
 *
 * [send] never throws and returns true only if the message was actually handed to the radio, so an
 * SMS failure can never take down the Ghost State session or the evidence upload.
 */
object ContactAlerter {
    private const val TAG = "ContactAlerter"

    /** Pure/testable: true only if there is a number worth attempting an SMS to. */
    fun shouldAttempt(contactPhone: String): Boolean = contactPhone.isNotBlank()

    /**
     * Pure/testable SMS body. Carries that it's an Incog emergency, who it's from, the coordinates,
     * and a tappable Google Maps link. Kept compact but it will exceed one 160-char SMS segment once
     * the link is included — hence multipart in [send].
     */
    fun buildMessage(senderLabel: String, latitude: Double, longitude: Double): String {
        val mapsUrl = "https://maps.google.com/?q=$latitude,$longitude"
        return "INCOG EMERGENCY\n" +
            "$senderLabel may be in danger.\n" +
            "Location: ${"%.6f".format(latitude)}, ${"%.6f".format(longitude)}\n" +
            "Map: $mapsUrl"
    }

    /** Redacts a phone number to its last 3 digits for logging (it's PII, and not the app owner's). */
    fun redact(contactPhone: String): String {
        val t = contactPhone.trim()
        return if (t.length <= 3) "***" else "***${t.takeLast(3)}"
    }

    /**
     * Sends the emergency SMS. Returns true only if the send was handed to the radio. Never throws;
     * returns false on a blank number, a missing SEND_SMS grant, or any exception.
     */
    fun send(
        context: Context,
        contactPhone: String,
        senderLabel: String,
        latitude: Double,
        longitude: Double
    ): Boolean {
        if (!shouldAttempt(contactPhone)) return false

        if (ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            Log.w(TAG, "SEND_SMS not granted — cannot text ${redact(contactPhone)}.")
            return false
        }

        return try {
            // getSystemService(SmsManager) — the API 31+ replacement for the deprecated getDefault().
            val sms = context.getSystemService(SmsManager::class.java)
            val message = buildMessage(senderLabel, latitude, longitude)
            // Multipart: a single sendTextMessage() truncates at 160 chars and would cut the Maps link.
            val parts = sms.divideMessage(message)
            sms.sendMultipartTextMessage(contactPhone, null, parts, null, null)
            Log.i(TAG, "Emergency SMS handed to radio for ${redact(contactPhone)} (${parts.size} parts).")
            true
        } catch (t: Throwable) {
            Log.e(TAG, "Failed to send emergency SMS to ${redact(contactPhone)}.", t)
            false
        }
    }
}
