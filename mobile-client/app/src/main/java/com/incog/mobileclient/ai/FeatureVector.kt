package com.incog.mobileclient.ai

/**
 * The 5-feature vector Lipika's emergency model consumes. Order and units mirror
 * xai-engine (`tflite_feature_order.json`, `phase4/feature_extraction.py`).
 */
data class FeatureVector(
    val peakAcceleration: Double,
    val motionVariance: Double,
    val audioEnergy: Double,
    val gpsVelocity: Double,
    val possibleFall: Boolean
) {
    /**
     * Model input order: [PeakAcceleration, MotionVariance, AudioEnergy, GPSVelocity, PossibleFall].
     * Normalization is baked into the .tflite (a Keras Normalization layer), so these are RAW
     * values. PossibleFall is encoded 1.0/0.0 (matches `astype(float32)` of the Python bool).
     */
    fun toModelInput(): FloatArray = floatArrayOf(
        peakAcceleration.toFloat(),
        motionVariance.toFloat(),
        audioEnergy.toFloat(),
        gpsVelocity.toFloat(),
        if (possibleFall) 1f else 0f
    )
}
