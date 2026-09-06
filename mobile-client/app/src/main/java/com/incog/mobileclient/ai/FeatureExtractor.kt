package com.incog.mobileclient.ai

import com.incog.mobileclient.handoff.SensorPacket
import kotlin.math.log10
import kotlin.math.max
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

    // AudioEnergy is a dB-scaled loudness in [0,1], NOT a linear ratio. The old audioRms/32768
    // linear scale left even a shout at ~0.18 (verified on-device), so audio was a dead feature;
    // Lipika refit this against real RAVDESS speech. These three constants MUST match
    // xai-engine/data/model_contract.json (checked by phase4/test_contract_sync.py) and must only
    // change in lockstep with a retrain — see audioEnergyDb().
    private const val AUDIO_RMS_FULL_SCALE = 32768.0  // 16-bit PCM full scale (0 dB reference)
    private const val AUDIO_FLOOR_DB = -32.0          // maps to 0.0 (quiet)
    private const val AUDIO_CEIL_DB = -20.0           // maps to 1.0 (loud/distress)

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
        val audioEnergy = audioEnergyDb(packet.audioRmsEnergy)
        val gpsVelocity = packet.latestLocation?.speedMps?.toDouble() ?: 0.0

        return FeatureVector(
            peakAcceleration = round4(peak),
            motionVariance = round4(variance),
            audioEnergy = round4(audioEnergy),
            gpsVelocity = round4(gpsVelocity),
            possibleFall = peak > FALL_ACCELERATION_THRESHOLD
        )
    }

    /**
     * Maps raw PCM RMS to a dB-based loudness in [0,1]. Mirrors the contract formula exactly:
     * clamp((20*log10(max(rms,1)/AUDIO_RMS_FULL_SCALE) - AUDIO_FLOOR_DB)/(AUDIO_CEIL_DB - AUDIO_FLOOR_DB), 0, 1).
     */
    private fun audioEnergyDb(rms: Double): Double {
        val db = 20.0 * log10(max(rms, 1.0) / AUDIO_RMS_FULL_SCALE)
        val normalized = (db - AUDIO_FLOOR_DB) / (AUDIO_CEIL_DB - AUDIO_FLOOR_DB)
        return normalized.coerceIn(0.0, 1.0)
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
