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
 *
 * DO NOT RETRY on a 400 or 503 response: per the backend contract those mean the evidence was
 * rejected but the SOS signal is already stored and contacts already alerted — retrying files a
 * duplicate and re-alerts everyone. This method makes a single attempt by design; only the caller
 * may retry, and only on a network failure or a non-503 5xx.
 *
 * Timeout is 60s: the backend is on a free tier that cold-starts, so the first request after idle
 * can take ~30s+ to wake. (Warming it by opening /map first avoids this.)
 */
object EvidenceUploader {
    private const val TAG = "EvidenceUploader"
    private const val TIMEOUT_MS = 60_000

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
                connectTimeout = TIMEOUT_MS
                readTimeout = TIMEOUT_MS
                setRequestProperty("Content-Type", "application/json")
                setRequestProperty("X-Incog-Key", BuildConfig.AGENT_KEY)
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
