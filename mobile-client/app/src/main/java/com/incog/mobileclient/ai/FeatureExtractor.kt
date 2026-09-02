package com.incog.mobileclient.ai

import com.incog.mobileclient.handoff.SensorPacket
import kotlin.math.round
import kotlin.math.sqrt

/**
 * Phase 4 (on-device port) — turns a [SensorPacket] into the 5-feature vector.
 *
 * Ported to match Lipika's Python source of truth EXACTLY:
 *   - xai-engine/phase4/feature_extraction.py  (acceleration_magnitude, peak_and_variance, possible_fall)
 *   - xai-engine/phase4/sensor_packet_adapter.py (SensorPacket -> features mapping)
 *
 * Any change here must stay in lockstep with those files (tracked in issue #5). Gyroscope samples
 * are intentionally unused — the trained model's 5 features never included gyro.
 */
object FeatureExtractor {

    private const val FALL_ACCELERATION_THRESHOLD = 15.0
    // 16-bit PCM full-scale amplitude: rescales audioRmsEnergy (raw PCM RMS, 0..32767) into the
    // [0,1] range the model's AudioEnergy feature was trained on. Same constant as the adapter.
    // NOTE (issue #5): this mapping is unvalidated against real audio — confirm on-device.
    private const val AUDIO_RMS_FULL_SCALE = 32768.0

    /** Returns null if the packet has no accelerometer history yet (nothing to compute). */
    fun fromSensorPacket(packet: SensorPacket): FeatureVector? {
        val samples = packet.accelSamples
        if (samples.isEmpty()) return null

        val magnitudes = DoubleArray(samples.size) { i ->
            val s = samples[i]
            sqrt(s.x.toDouble() * s.x + s.y.toDouble() * s.y + s.z.toDouble() * s.z)
        }

        val peak = magnitudes.max()
        val variance = sampleVariance(magnitudes)
        val audioEnergy = (packet.audioRmsEnergy / AUDIO_RMS_FULL_SCALE).coerceAtMost(1.0)
        val gpsVelocity = packet.latestLocation?.speedMps?.toDouble() ?: 0.0

        return FeatureVector(
            peakAcceleration = round4(peak),
            motionVariance = round4(variance),
            audioEnergy = round4(audioEnergy),
            gpsVelocity = round4(gpsVelocity),
            possibleFall = peak > FALL_ACCELERATION_THRESHOLD
        )
    }

    /** Sample variance (ddof=1); 0.0 for fewer than 2 samples — matches peak_and_variance(). */
    private fun sampleVariance(values: DoubleArray): Double {
        if (values.size < 2) return 0.0
        val mean = values.average()
        var sumSq = 0.0
        for (v in values) {
            val d = v - mean
            sumSq += d * d
        }
        return sumSq / (values.size - 1)
    }

    /** Matches the Python `round(x, 4)` applied before the feature vector is fed to the model. */
    private fun round4(v: Double): Double = round(v * 10000.0) / 10000.0
}
