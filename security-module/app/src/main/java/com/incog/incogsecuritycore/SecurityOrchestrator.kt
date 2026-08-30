package com.incog.incogsecuritycore
import android.graphics.Bitmap
import android.util.Base64
import android.util.Log
import javax.crypto.SecretKey

/**
 * Output of a completed Phase 7 -> Phase 10 run. The encryption key is
 * returned alongside the stego images because it is not persisted anywhere
 * else yet - in production it belongs in the Android Keystore, wrapped for
 * transport, or handed off to Chirag's backend out of band.
 */
data class PipelineResult(
    val stegoImages: List<Bitmap>,
    val secretKey: SecretKey
)

object SecurityOrchestrator {
    private const val TAG = "SecurityOrchestrator"
    private const val FRAGMENT_CHUNK_SIZE = 256

    /**
     * Runs the Phase 7 -> Phase 10 pipeline against a real emergency handoff
     * from Lipika's decision engine (sessionId/gps/featureVector/aiResult)
     * plus the flushed audio buffer for that session.
     *
     * Returns null and discards silently when aiResult.emergencyStatus is
     * false, per the Phase 6 -> Phase 7 handoff rule.
     */
    fun processEmergencyTrigger(
        sessionId: String,
        timestamp: Long,
        gps: GPSData,
        featureVector: FeatureVector,
        aiResult: AIResult,
        audioBytes: ByteArray,
        carrierImages: List<Bitmap>
    ): PipelineResult? {
        if (!aiResult.emergencyStatus) {
            Log.d(TAG, "AI result did not flag an emergency; discarding silently.")
            return null
        }

        require(carrierImages.isNotEmpty()) { "At least one carrier image is required." }

        Log.d(TAG, "--- INCOG SECURITY PIPELINE STARTED ---")

        // PHASE 7: Unified Evidence Packaging
        Log.d(TAG, "Executing Phase 7: Packaging Evidence...")
        val evidence = EvidencePackage(
            sessionId = sessionId,
            timestamp = timestamp,
            gps = gps,
            audioBase64 = Base64.encodeToString(audioBytes, Base64.NO_WRAP),
            featureVector = featureVector,
            aiResult = aiResult
        )
        val rawPayload = evidence.toByteArray()

        // PHASE 8: Authenticated Encryption
        Log.d(TAG, "Executing Phase 8: AES-256-GCM Encryption...")
        val secretKey = CryptoManager.generate256BitKey()
        // Note: In a production app, this key would be securely stored in the Android Keystore.
        val encryptedBlob = CryptoManager.encrypt(rawPayload, secretKey)

        // PHASE 9: Data Fragmentation
        Log.d(TAG, "Executing Phase 9: Slicing Encrypted Blob...")
        val fragments = FragmentationManager.fragmentData(encryptedBlob, FRAGMENT_CHUNK_SIZE)
        Log.d(TAG, "Payload sliced into ${fragments.size} fragments.")

        // PHASE 10: LSB Steganography
        Log.d(TAG, "Executing Phase 10: Embedding into Carrier Images...")
        val stegoImages = mutableListOf<Bitmap>()

        for ((index, fragment) in fragments.withIndex()) {
            // Cycle through the built-in carrier pool instead of reusing one image per fragment.
            val carrierImage = carrierImages[index % carrierImages.size]
            val stegoImage = SteganographyEngine.embedData(carrierImage, fragment)
            stegoImages.add(stegoImage)
            Log.d(TAG, "Fragment ${index + 1} embedded successfully.")
        }

        Log.d(TAG, "--- INCOG SECURITY PIPELINE COMPLETE ---")

        // Final Output: Ready for Network Payload Hand-off to Chirag (Phase 11)
        return PipelineResult(stegoImages, secretKey)
    }
}
