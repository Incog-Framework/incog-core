package com.incog.mobileclient.sensors

/** A single 3-axis sensor sample (accelerometer or gyroscope), device time-stamped. */
data class Vec3Reading(
    val timestampMs: Long,
    val x: Float,
    val y: Float,
    val z: Float
)

/** A single location fix. */
data class LocationReading(
    val timestampMs: Long,
    val latitude: Double,
    val longitude: Double,
    val speedMps: Float,
    val accuracyM: Float
)
