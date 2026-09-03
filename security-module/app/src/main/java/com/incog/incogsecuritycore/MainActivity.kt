package com.incog.incogsecuritycore

import android.app.Activity
import android.graphics.Bitmap
import android.graphics.Color
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.Toast
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext


class MainActivity : Activity() {

    // Pixel work runs on Dispatchers.Default; results come back on Main.
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Create a simple layout programmatically
        val layout = LinearLayout(this)
        layout.orientation = LinearLayout.VERTICAL
        // Add this line to push everything down by 150 pixels!
        layout.setPadding(0, 150, 0, 0)

        val button = Button(this)
        button.text = "Run Security Pipeline"

        button.setOnClickListener {
            scope.launch { runPipelineTest() }
        }

        layout.addView(button)
        setContentView(layout)
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private suspend fun runPipelineTest() {
        // 1. Sample Evidence: Bangalore Location & Timestamp
        val locationData = """
        {
            "event": "CRITICAL_EVIDENCE",
            "landmark": "Vidhana Soudha, Bengaluru",
            "coordinates": {"lat": 12.9797, "lng": 77.5907},
            "timestamp": "2026-08-22T00:03:00+05:30",
            "accuracy_meters": 4.2
        }
    """.trimIndent()

        Log.d("IncogDemo", "--- [ORIGINAL DATA] ---")
        Log.d("IncogDemo", locationData)

        val decryptedJson = withContext(Dispatchers.Default) {
            // 2. Load the shared key (build-time config) & Encrypt
            val secretKey = CryptoManager.loadSharedKey()
            val encryptedBlob = CryptoManager.encrypt(locationData.toByteArray(Charsets.UTF_8), secretKey)
            Log.d("IncogDemo", "Encrypted Size: ${encryptedBlob.size} bytes (AES-256-GCM)")

            // 3. Create Carrier Image (500x500 green PNG) & Embed Data
            val carrierBitmap = Bitmap.createBitmap(500, 500, Bitmap.Config.ARGB_8888)
            carrierBitmap.eraseColor(Color.GREEN)
            val stegoImage = SteganographyEngine.embedData(carrierBitmap, encryptedBlob)
            Log.d("IncogDemo", "Stego Image Created successfully.")

            // ----------------------------------------------------
            // INVERSE EXTRACTION PIPELINE (Simulating Backend/Receiver)
            // ----------------------------------------------------

            // 4. Extract raw encrypted bits from the image pixels
            val extractedEncryptedBlob = SecurityExtractor.extractFromBitmap(stegoImage)

            // 5. Decrypt using the same shared AES key
            SecurityExtractor.decryptPayload(extractedEncryptedBlob, secretKey)
        }

        Log.d("IncogDemo", "--- [RECOVERED DATA] ---")
        Log.d("IncogDemo", decryptedJson)

        Toast.makeText(this, "Encryption + Decryption Verified! Check Logcat.", Toast.LENGTH_LONG).show()
    }
}
