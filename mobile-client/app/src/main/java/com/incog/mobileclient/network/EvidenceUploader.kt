package com.incog.mobileclient.network

import android.util.Log
import com.incog.mobileclient.BuildConfig
import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL

/**
 * Phase 11 client seam — POSTs an SOS signal + AES-256-GCM encrypted evidence to Chirag's backend
 * (`POST /api/v1/sos`). The evidence blob is produced by the security pipeline (Gagan) and matches
 * the backend's `evidence_crypto.py` byte-for-byte.
 *
 * Backend URL + agent key come from BuildConfig (injected from local.properties/env — team
 * DECISION 1). Blocking network call — invoke off the main thread.
 */
object EvidenceUploader {
    private const val TAG = "EvidenceUploader"

    fun upload(
        deviceId: String,
        latitude: Double,
        longitude: Double,
        encryptedEvidenceBase64: String,
        isStealthActive: Boolean = true
    ): Boolean {
        val body = JSONObject()
            .put("device_id", deviceId)
            .put("latitude", latitude)
            .put("longitude", longitude)
            .put("is_stealth_active", isStealthActive)
            .put("encrypted_evidence", encryptedEvidenceBase64)
            .toString()

        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(BuildConfig.BACKEND_SOS_URL).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = 10_000
                readTimeout = 15_000
                setRequestProperty("Content-Type", "application/json")
                setRequestProperty("X-Agent-Key", BuildConfig.AGENT_KEY)
            }
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val ok = code in 200..299
            if (ok) {
                Log.i(TAG, "SOS uploaded (HTTP $code).")
            } else {
                val err = conn.errorStream?.bufferedReader()?.use(BufferedReader::readText)
                Log.e(TAG, "SOS upload failed (HTTP $code): $err")
            }
            ok
        } catch (t: Throwable) {
            Log.e(TAG, "SOS upload error.", t)
            false
        } finally {
            conn?.disconnect()
        }
    }
}
