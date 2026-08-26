package com.incog.incogsecuritycore

import android.graphics.Bitmap
import android.graphics.Color
import android.util.Base64
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
    // lives in mobile-client's AudioBufferCollector, which isn't in this
    // repo yet, so this stands in for a flushed/compressed audio file.
    private val sampleAudioBytes = ByteArray(512) { it.toByte() }

    @Test
    fun `emergency trigger produces stego images that round-trip back to the original evidence`() {
        val carriers = listOf(
            carrierBitmap(Color.GREEN),
            carrierBitmap(Color.BLUE),
            carrierBitmap(Color.RED)
        )

        val result = SecurityOrchestrator.processEmergencyTrigger(
            sessionId = "SESS-9021",
            timestamp = 1734900000L,
            gps = sampleGps,
            featureVector = sampleFeatureVector,
            aiResult = sampleAiResult,
            audioBytes = sampleAudioBytes,
            carrierImages = carriers
        )

        assertNotNull("Emergency trigger should produce a pipeline result", result)
        val stegoImages = result!!.stegoImages
        assertTrue("Expected at least one stego image", stegoImages.isNotEmpty())

        // Reverse Phase 10 -> Phase 7: extract every fragment, reassemble,
        // decrypt, and confirm we recover the exact evidence package.
        val fragments = stegoImages.map { SecurityExtractor.extractFromBitmap(it) }
        val reassembled = FragmentationManager.reassembleData(fragments)
        val decrypted = CryptoManager.decrypt(reassembled, result.secretKey)
        val recovered = EvidencePackage.fromByteArray(decrypted)

        assertEquals("SESS-9021", recovered.sessionId)
        assertEquals(sampleGps, recovered.gps)
        assertEquals(sampleFeatureVector, recovered.featureVector)
        assertEquals(sampleAiResult, recovered.aiResult)
        assertEquals(Base64.encodeToString(sampleAudioBytes, Base64.NO_WRAP), recovered.audioBase64)

        writeStegoImagesForInspection(stegoImages)
    }

    @Test
    fun `non-emergency AI result is discarded silently`() {
        val nonEmergency = sampleAiResult.copy(
            prediction = "Normal",
            confidence = 0.12,
            emergencyStatus = false
        )

        val result = SecurityOrchestrator.processEmergencyTrigger(
            sessionId = "SESS-9022",
            timestamp = 1734900000L,
            gps = sampleGps,
            featureVector = sampleFeatureVector,
            aiResult = nonEmergency,
            audioBytes = sampleAudioBytes,
            carrierImages = listOf(carrierBitmap(Color.GREEN))
        )

        assertNull("Non-emergency AI result must not produce a pipeline result", result)
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
