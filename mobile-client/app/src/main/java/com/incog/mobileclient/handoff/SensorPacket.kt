package com.incog.mobileclient.handoff

import com.incog.mobileclient.sensors.LocationReading
import com.incog.mobileclient.sensors.Vec3Reading

/**
 * Phase 3 output — the Aarush -> Lipika handoff contract (Phase 3 -> Phase 4).
 *
 * A snapshot of the live Ghost State session that Lipika's `xai-engine` sensor-fusion /
 * feature-extraction step consumes. The raw accelerometer/gyroscope arrays plus the live audio
 * memory stream are the actual inputs to her pipeline; this packet bundles the latest values and
 * the rolling sample arrays, tagged with the SensorSessionID.
 *
 * NOTE: keep this shape stable — `xai-engine` depends on it. Schema changes are a cross-team
 * conversation, not a unilateral edit. (See mobile-client/CLAUDE.md.)
 */
data class SensorPacket(
    val sessionId: String,
    val timestampMs: Long,
    val latestAccel: Vec3Reading?,
    val latestGyro: Vec3Reading?,
    val latestLocation: LocationReading?,
    val accelSamples: List<Vec3Reading>,
    val gyroSamples: List<Vec3Reading>,
    /** Rolling RMS of the live mic buffer — a cheap audio-energy signal. */
    val audioRmsEnergy: Double,
    /** Milliseconds of audio currently held in the in-memory circular buffer. */
    val audioBufferedMs: Long
)
