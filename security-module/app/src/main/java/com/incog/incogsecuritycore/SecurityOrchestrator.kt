package com.incog.incogsecuritycore
import android.graphics.Bitmap
import android.util.Base64
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Output of a completed Phase 7 -> Phase 10 run.
 *
 * [encryptedBlob] is the AES-256-GCM payload the app uploads directly to the
 * backend over TLS (team DECISION 1). [stegoImages] are the same blob hidden
 * in carrier images for on-device at-rest storage only - they are not the
 * network transport.
 *
 * The AES key is deliberately absent: it is the shared key both sides load
 * from their own config, not a per-session secret to hand around.
 */
data class PipelineResult(
    val sessionId: String,
    val encryptedBlob: ByteArray,
    val stegoImages: List<Bitmap>
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is PipelineResult) return false

        return sessionId == other.sessionId &&
            encryptedBlob.contentEquals(other.encryptedBlob) &&
            stegoImages == other.stegoImages
    }

    override fun hashCode(): Int {
        var result = sessionId.hashCode()
        result = 31 * result + encryptedBlob.contentHashCode()
        result = 31 * result + stegoImages.hashCode()
        return result
    }
}

object SecurityOrchestrator {
    private const val TAG = "SecurityOrchestrator"

    /** Data bytes per fragment, before FragmentationManager adds its 4-byte header. */
    const val FRAGMENT_CHUNK_SIZE = 256

    /**
     * PHASE 7 + 8: packages the evidence and encrypts it with the shared key.
     *
     * The returned blob is what gets uploaded to the backend over TLS. Returns
     * null and discards silently when aiResult.emergencyStatus is false, per
     * the Phase 6 -> Phase 7 handoff rule.
     */
    suspend fun packageAndEncrypt(
        sessionId: String,
        timestamp: Long,
        gps: GPSData,
        featureVector: FeatureVector,
        aiResult: AIResult,
        audioBytes: ByteArray
    ): ByteArray? = withContext(Dispatchers.Default) {
        if (!aiResult.emergencyStatus) {
            Log.d(TAG, "AI result did not flag an emergency; discarding silently.")
            return@withContext null
        }

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

        // PHASE 8: Authenticated Encryption with the key shared with the backend.
        Log.d(TAG, "Executing Phase 8: AES-256-GCM Encryption...")
        CryptoManager.encrypt(rawPayload, CryptoManager.loadSharedKey())
    }

    /**
     * PHASE 9 + 10: fragments an encrypted blob and hides the fragments in
     * carrier images for at-rest storage on the device.
     *
     * Fragments are spread across the carrier pool in order; each one carries
     * its own index/total header, so the images can be read back in any order.
     */
    suspend fun hideAtRest(
        encryptedBlob: ByteArray,
        carrierImages: List<Bitmap>,
        chunkSize: Int = FRAGMENT_CHUNK_SIZE
    ): List<Bitmap> = withContext(Dispatchers.Default) {
        require(carrierImages.isNotEmpty()) { "At least one carrier image is required." }

        // Fail fast with an actionable message rather than letting the first
        // oversized fragment blow up mid-embed.
        val smallestCapacity = carrierImages.minOf { SteganographyEngine.maxPayloadBytes(it) }
        val fragmentSize = chunkSize + FragmentationManager.FRAGMENT_HEADER_SIZE

        require(fragmentSize <= smallestCapacity) {
            "Smallest carrier image holds $smallestCapacity payload bytes but each fragment is " +
                "up to $fragmentSize bytes. Use larger carriers or a smaller chunkSize."
        }

        // PHASE 9: Data Fragmentation
        Log.d(TAG, "Executing Phase 9: Slicing Encrypted Blob...")
        val fragments = FragmentationManager.fragmentData(encryptedBlob, chunkSize)
        Log.d(TAG, "Payload sliced into ${fragments.size} fragments.")

        // PHASE 10: LSB Steganography
        Log.d(TAG, "Executing Phase 10: Embedding into Carrier Images...")
        fragments.mapIndexed { index, fragment ->
            // Cycle through the built-in carrier pool instead of reusing one image per fragment.
            val stegoImage = SteganographyEngine.embedData(carrierImages[index % carrierImages.size], fragment)
            Log.d(TAG, "Fragment ${index + 1} embedded successfully.")
            stegoImage
        }
    }

    /**
     * Runs the full Phase 7 -> Phase 10 pipeline against a real emergency
     * handoff from Lipika's decision engine (sessionId/gps/featureVector/aiResult)
     * plus the flushed audio buffer for that session.
     *
     * Returns null and discards silently when aiResult.emergencyStatus is false.
     *
     * @param embedAtRest set false to skip Phase 9/10 when the app only needs
     *   the encrypted blob to upload.
     */
    suspend fun processEmergencyTrigger(
        sessionId: String,
        timestamp: Long,
        gps: GPSData,
        featureVector: FeatureVector,
        aiResult: AIResult,
        audioBytes: ByteArray,
        carrierImages: List<Bitmap> = emptyList(),
        embedAtRest: Boolean = true
    ): PipelineResult? {
        Log.d(TAG, "--- INCOG SECURITY PIPELINE STARTED ---")

        val encryptedBlob = packageAndEncrypt(
            sessionId = sessionId,
            timestamp = timestamp,
            gps = gps,
            featureVector = featureVector,
            aiResult = aiResult,
            audioBytes = audioBytes
        ) ?: return null

        val stegoImages = if (embedAtRest) {
            hideAtRest(encryptedBlob, carrierImages)
        } else {
            emptyList()
        }

        Log.d(TAG, "--- INCOG SECURITY PIPELINE COMPLETE ---")

        // Final Output: encryptedBlob goes to Chirag's backend over TLS;
        // stegoImages stay on the device as the hidden at-rest copy.
        return PipelineResult(sessionId, encryptedBlob, stegoImages)
    }
}
