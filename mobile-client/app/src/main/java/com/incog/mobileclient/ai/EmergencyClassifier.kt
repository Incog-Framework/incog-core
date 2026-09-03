package com.incog.mobileclient.ai

import android.content.Context
import com.incog.mobileclient.handoff.SensorPacket
import org.tensorflow.lite.Interpreter
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Phase 5 + 6 on-device — runs Lipika's `emergency_model.tflite` locally and applies the decision
 * threshold. This is the runtime bridge that closes the on-device AI gap (Decision 2).
 *
 * Normalization is baked into the model (a Keras Normalization layer), so it takes RAW feature
 * values. Feature order, classification cutoff, and decision threshold mirror xai-engine:
 *   - phase5/tflite_predict.py  (confidence >= 0.5 -> "Emergency")
 *   - phase6/decision_engine.py (EmergencyStatus = Emergency AND confidence >= 0.80)
 *
 * Create once per session and [close] it on teardown.
 */
class EmergencyClassifier(context: Context) {

    private val interpreter: Interpreter = Interpreter(loadModel(context))

    /** Returns null when the packet has no accelerometer history yet to build features from. */
    fun classify(packet: SensorPacket): AiResult? {
        val features = FeatureExtractor.fromSensorPacket(packet) ?: return null

        val input = arrayOf(features.toModelInput())   // shape [1][5]
        val output = arrayOf(FloatArray(1))            // shape [1][1]
        interpreter.run(input, output)
        val confidence = output[0][0].toDouble()

        val prediction = if (confidence >= CLASSIFICATION_THRESHOLD) "Emergency" else "Normal"
        val emergencyStatus = confidence >= DECISION_THRESHOLD

        return AiResult(
            sessionId = packet.sessionId,
            timestampMs = packet.timestampMs,
            prediction = prediction,
            confidence = confidence,
            emergencyStatus = emergencyStatus,
            decisionThreshold = DECISION_THRESHOLD,
            features = features
        )
    }

    fun close() = interpreter.close()

    /** Reads the model asset fully into a direct buffer (avoids needing noCompress on the asset). */
    private fun loadModel(context: Context): ByteBuffer {
        val bytes = context.assets.open(MODEL_ASSET).use { it.readBytes() }
        return ByteBuffer.allocateDirect(bytes.size).apply {
            order(ByteOrder.nativeOrder())
            put(bytes)
            rewind()
        }
    }

    companion object {
        private const val MODEL_ASSET = "emergency_model.tflite"
        private const val CLASSIFICATION_THRESHOLD = 0.5  // phase5: Emergency vs Normal
        private const val DECISION_THRESHOLD = 0.8         // phase6: confirm emergency
    }
}
