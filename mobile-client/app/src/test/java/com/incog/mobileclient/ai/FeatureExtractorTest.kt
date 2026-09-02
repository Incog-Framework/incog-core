package com.incog.mobileclient.ai

import com.incog.mobileclient.handoff.SensorPacket
import com.incog.mobileclient.sensors.LocationReading
import com.incog.mobileclient.sensors.Vec3Reading
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins the on-device feature extraction to Lipika's Python source of truth
 * (xai-engine/phase4/{feature_extraction,sensor_packet_adapter}.py). If any of these change,
 * the Kotlin port and the Python must be reconciled (issue #5).
 */
class FeatureExtractorTest {

    private fun accel(x: Float, y: Float, z: Float) = Vec3Reading(0L, x, y, z)

    private fun packet(
        accel: List<Vec3Reading>,
        audioRms: Double = 0.0,
        speed: Float? = null
    ) = SensorPacket(
        sessionId = "SESS-TEST",
        timestampMs = 1_700_000_000_000L,
        latestAccel = accel.lastOrNull(),
        latestGyro = null,
        latestLocation = speed?.let { LocationReading(0L, 12.97, 77.59, it, 5f) },
        accelSamples = accel,
        gyroSamples = emptyList(),
        audioRmsEnergy = audioRms,
        audioBufferedMs = 0L
    )

    @Test
    fun `empty accel history yields null`() {
        assertNull(FeatureExtractor.fromSensorPacket(packet(emptyList())))
    }

    @Test
    fun `peak is max magnitude, single sample variance is zero`() {
        // magnitude of (3,4,0) = 5.0
        val f = FeatureExtractor.fromSensorPacket(packet(listOf(accel(3f, 4f, 0f))))!!
        assertEquals(5.0, f.peakAcceleration, 1e-6)
        assertEquals(0.0, f.motionVariance, 1e-6) // <2 samples -> 0.0
        assertFalse(f.possibleFall)               // 5.0 !> 15
    }

    @Test
    fun `sample variance uses ddof=1`() {
        // magnitudes 3,4,0 -> [3,4] wait: use (3,0,0)=3 and (5,0,0)=5 -> mags [3,5], mean 4,
        // sample variance ddof=1 = ((3-4)^2 + (5-4)^2)/(2-1) = 2.0
        val f = FeatureExtractor.fromSensorPacket(
            packet(listOf(accel(3f, 0f, 0f), accel(5f, 0f, 0f)))
        )!!
        assertEquals(5.0, f.peakAcceleration, 1e-6) // max(3, 5)
        assertEquals(2.0, f.motionVariance, 1e-6)   // ((3-4)^2 + (5-4)^2) / (2-1)
    }

    @Test
    fun `possibleFall triggers above threshold of 15`() {
        // magnitude of (16,0,0) = 16 > 15
        val f = FeatureExtractor.fromSensorPacket(packet(listOf(accel(16f, 0f, 0f))))!!
        assertTrue(f.possibleFall)
    }

    @Test
    fun `audio energy is rescaled by PCM16 full scale and clamped to 1`() {
        val f = FeatureExtractor.fromSensorPacket(packet(listOf(accel(1f, 0f, 0f)), audioRms = 16384.0))!!
        assertEquals(0.5, f.audioEnergy, 1e-4) // 16384 / 32768
        val clamped = FeatureExtractor.fromSensorPacket(packet(listOf(accel(1f, 0f, 0f)), audioRms = 99999.0))!!
        assertEquals(1.0, clamped.audioEnergy, 1e-9) // coerced to 1.0
    }

    @Test
    fun `gps velocity falls back to zero without a fix`() {
        val noFix = FeatureExtractor.fromSensorPacket(packet(listOf(accel(1f, 0f, 0f))))!!
        assertEquals(0.0, noFix.gpsVelocity, 1e-9)
        val withFix = FeatureExtractor.fromSensorPacket(packet(listOf(accel(1f, 0f, 0f)), speed = 2.5f))!!
        assertEquals(2.5, withFix.gpsVelocity, 1e-4)
    }
}
