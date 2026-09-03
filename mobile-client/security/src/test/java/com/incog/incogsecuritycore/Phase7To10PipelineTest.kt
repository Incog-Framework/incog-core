package com.incog.incogsecuritycore

import android.graphics.Bitmap
import android.graphics.Color
import android.util.Base64
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File
import java.io.FileOutputStream

/**
 * Local sanity check for the Phase 7 -> Phase 10 round trip: simulates an
 * incoming SensorPacket-derived feature vector plus Lipika's AI/XAI result,
 * runs it through packaging -> AES-256-GCM -> fragmentation -> LSB stego,
 * then reverses the whole thing and confirms the original evidence comes
 * back out unchanged. Runs on the JVM via Robolectric, no emulator needed.
 */
@RunWith(RobolectricTestRunner::class)
class Phase7To10PipelineTest {

    private fun carrierBitmap(color: Int): Bitmap {
        val bitmap = Bitmap.createBitmap(64, 64, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(color)
        return bitmap
    }

    // Mirrors xai-engine/data/xai_output.json exactly (SHAP/LIME values,
    // sessionId, thresholds) - see xai-engine/phase6/decision_engine.py and
    // xai-engine/xai/xai_pipeline.py for the source of truth.
    private val sampleAiResult = AIResult(
        sessionId = "SESS-9021",
        timestampMs = 1734900000000L,
        prediction = "Emergency",
        confidence = 0.9999,
        emergencyStatus = true,
        decisionThreshold = 0.8,
        shap = mapOf(
            "PeakAcceleration" to 0.143158,
            "MotionVariance" to 0.113331,
            "AudioEnergy" to 0.026651,
            "GPSVelocity" to 0.053793,
            "PossibleFall" to 0.063062
        ),
        lime = mapOf(
            "MotionVariance > 25.20" to 0.295421,
            "PeakAcceleration > 20.62" to 0.264128,
            "0.11 < AudioEnergy <= 0.40" to -0.214919,
            "0.50 < PossibleFall <= 1.00" to 0.197703,
            "0.00 < GPSVelocity <= 0.20" to 0.190662
        )
    )

    private val sampleFeatureVector = FeatureVector(
        peakAcceleration = 18.2,
        motionVariance = 4.1,
        audioEnergy = 0.82,
        gpsVelocity = 0.0,
        possibleFall = true
    )

    private val sampleGps = GPSData(lat = 12.9716, lng = 77.5946)

    // Placeholder for the real captured audio buffer: raw PCM capture/flush
    // lives in mobile-client's AudioBufferCollector, which this module does
    // not integrate with yet, so this stands in for a flushed audio file.
    private val sampleAudioBytes = ByteArray(512) { it.toByte() }

    private suspend fun runPipeline(
        aiResult: AIResult = sampleAiResult,
        sessionId: String = "SESS-9021",
        carrierImages: List<Bitmap> = listOf(
            carrierBitmap(Color.GREEN),
            carrierBitmap(Color.BLUE),
            carrierBitmap(Color.RED)
        ),
        embedAtRest: Boolean = true
    ): PipelineResult? = SecurityOrchestrator.processEmergencyTrigger(
        sessionId = sessionId,
        timestamp = 1734900000L,
        gps = sampleGps,
        featureVector = sampleFeatureVector,
        aiResult = aiResult,
        audioBytes = sampleAudioBytes,
        carrierImages = carrierImages,
        embedAtRest = embedAtRest
    )

    private fun assertRecoveredEvidenceMatches(evidence: EvidencePackage, sessionId: String) {
        assertEquals(sessionId, evidence.sessionId)
        assertEquals(sampleGps, evidence.gps)
        assertEquals(sampleFeatureVector, evidence.featureVector)
        assertEquals(sampleAiResult, evidence.aiResult)
        assertEquals(Base64.encodeToString(sampleAudioBytes, Base64.NO_WRAP), evidence.audioBase64)
    }

    @Test
    fun `emergency trigger produces stego images that round-trip back to the original evidence`() = runBlocking {
        val result = runPipeline()

        assertNotNull("Emergency trigger should produce a pipeline result", result)
        val stegoImages = result!!.stegoImages
        assertTrue("Expected at least one stego image", stegoImages.isNotEmpty())

        // Reverse Phase 10 -> Phase 7: extract every fragment, reassemble,
        // decrypt, and confirm we recover the exact evidence package.
        val fragments = stegoImages.map { SecurityExtractor.extractFromBitmap(it) }
        val reassembled = FragmentationManager.reassembleData(fragments)
        val decrypted = CryptoManager.decrypt(reassembled, CryptoManager.loadSharedKey())

        assertRecoveredEvidenceMatches(EvidencePackage.fromByteArray(decrypted), "SESS-9021")

        writeStegoImagesForInspection(stegoImages)
    }

    /**
     * DECISION 1: the blob the app uploads over TLS must decrypt on its own
     * with the shared config key - no stego, no per-session key handoff.
     */
    @Test
    fun `exposed encrypted blob decrypts directly with the shared config key`() = runBlocking {
        val result = runPipeline()
        assertNotNull(result)

        val decrypted = CryptoManager.decrypt(result!!.encryptedBlob, CryptoManager.loadSharedKey())

        assertRecoveredEvidenceMatches(EvidencePackage.fromByteArray(decrypted), "SESS-9021")
    }

    /**
     * Stego images and the uploadable blob are the same evidence, so a device
     * that only uploads never has to pay for the pixel work.
     */
    @Test
    fun `blob is still produced when at-rest embedding is skipped`() = runBlocking {
        val result = runPipeline(carrierImages = emptyList(), embedAtRest = false)

        assertNotNull(result)
        assertTrue("No stego images expected", result!!.stegoImages.isEmpty())
        assertTrue("Blob should still be produced", result.encryptedBlob.isNotEmpty())

        val decrypted = CryptoManager.decrypt(result.encryptedBlob, CryptoManager.loadSharedKey())
        assertRecoveredEvidenceMatches(EvidencePackage.fromByteArray(decrypted), "SESS-9021")
    }

    /**
     * Out-of-order upload/storage must still reassemble, now that fragments
     * carry their own index/total header.
     */
    @Test
    fun `shuffled stego images still reassemble into the original evidence`() = runBlocking {
        val result = runPipeline(sessionId = "SESS-9023")
        assertNotNull(result)

        val shuffledFragments = result!!.stegoImages
            .map { SecurityExtractor.extractFromBitmap(it) }
            .reversed()

        val reassembled = FragmentationManager.reassembleData(shuffledFragments)
        val decrypted = CryptoManager.decrypt(reassembled, CryptoManager.loadSharedKey())

        assertRecoveredEvidenceMatches(EvidencePackage.fromByteArray(decrypted), "SESS-9023")
    }

    @Test
    fun `non-emergency AI result is discarded silently`() = runBlocking {
        val nonEmergency = sampleAiResult.copy(
            prediction = "Normal",
            confidence = 0.12,
            emergencyStatus = false
        )

        val result = runPipeline(aiResult = nonEmergency, sessionId = "SESS-9022")

        assertNull("Non-emergency AI result must not produce a pipeline result", result)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `carrier pool too small for the chunk size is rejected up front`() {
        runBlocking {
            // 16x16 = 256 pixels = 32 payload bytes, far below a 256-byte fragment.
            SecurityOrchestrator.hideAtRest(
                encryptedBlob = ByteArray(1024) { it.toByte() },
                carrierImages = listOf(
                    Bitmap.createBitmap(16, 16, Bitmap.Config.ARGB_8888)
                )
            )
        }
    }

    private fun writeStegoImagesForInspection(stegoImages: List<Bitmap>) {
        val outDir = File("build/test-results/stego")
        outDir.mkdirs()
        stegoImages.forEachIndexed { index, bitmap ->
            FileOutputStream(File(outDir, "stego_fragment_$index.png")).use { stream ->
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream)
            }
        }
    }
}
