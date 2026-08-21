package com.incog.incogsecuritycore

import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

@Serializable
data class GPSData(
    val lat: Double,
    val lng: Double
)

@Serializable
data class FeatureVector(
    val peakAcceleration: Double,
    val motionVariance: Double,
    val audioEnergy: Double,
    val gpsVelocity: Double,
    val possibleFall: Boolean
)

@Serializable
data class EvidencePackage(
    val sessionId: String,
    val timestamp: Long,
    val gps: GPSData,
    val audioBase64: String, // Compressed audio buffer converted to Base64
    val featureVector: FeatureVector
) {
    /**
     * Serializes the evidence package instance into a UTF-8 JSON byte array
     * ready for encryption.
     */
    fun toByteArray(): ByteArray {
        val jsonString = Json.encodeToString(this)
        return jsonString.toByteArray(Charsets.UTF_8)
    }

    companion object {
        fun fromByteArray(bytes: ByteArray): EvidencePackage {
            val jsonString = String(bytes, Charsets.UTF_8)
            return Json.decodeFromString(jsonString)
        }
    }
}