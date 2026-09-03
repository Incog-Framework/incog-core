package com.incog.incogsecuritycore

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Lipika's decision-engine + XAI handoff (xai-engine/data/xai_output.json).
 * Field names/casing mirror that JSON exactly so this stays drop-in
 * compatible if a file/JSON bridge to xai-engine is ever added later.
 */
@Serializable
data class AIResult(
    @SerialName("SessionID") val sessionId: String? = null,
    @SerialName("TimestampMs") val timestampMs: Long? = null,
    @SerialName("Prediction") val prediction: String,
    @SerialName("Confidence") val confidence: Double,
    @SerialName("EmergencyStatus") val emergencyStatus: Boolean,
    @SerialName("DecisionThreshold") val decisionThreshold: Double,
    @SerialName("SHAP") val shap: Map<String, Double>,
    @SerialName("LIME") val lime: Map<String, Double>
)
