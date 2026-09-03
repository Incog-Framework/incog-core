package com.incog.mobileclient.ai

/**
 * Phase 5 + 6 output, produced entirely on-device.
 *
 * Mirrors the fields of the security module's `AIResult` (the Phase 6 -> Phase 7 handoff) MINUS
 * SHAP/LIME, which cannot run on-device and move server-side/async per Decision 2. The backend
 * attaches the explanation log post-hoc.
 */
data class AiResult(
    val sessionId: String,
    val timestampMs: Long,
    val prediction: String,       // "Emergency" | "Normal"
    val confidence: Double,       // sigmoid probability from the model
    val emergencyStatus: Boolean, // confidence >= decisionThreshold
    val decisionThreshold: Double,
    val features: FeatureVector
)
