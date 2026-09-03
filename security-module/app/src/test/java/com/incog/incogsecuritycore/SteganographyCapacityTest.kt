package com.incog.incogsecuritycore

import android.graphics.Bitmap
import android.graphics.Color
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Phase 10 capacity guards: embedding used to stop silently once it ran out of
 * pixels, and extraction used to return a half-filled array, so an oversized
 * fragment produced a stego image that could never be decrypted.
 */
@RunWith(RobolectricTestRunner::class)
class SteganographyCapacityTest {

    private fun carrier(width: Int, height: Int): Bitmap =
        Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888).apply { eraseColor(Color.GRAY) }

    @Test
    fun `capacity is one bit per pixel minus the length prefix`() {
        // 64x64 = 4096 pixels = 512 bytes, minus the 4-byte length prefix.
        assertEquals(508, SteganographyEngine.maxPayloadBytes(carrier(64, 64)))
    }

    @Test
    fun `a payload at exactly the carrier capacity round-trips`() {
        val image = carrier(64, 64)
        val payload = ByteArray(SteganographyEngine.maxPayloadBytes(image)) { it.toByte() }

        val stego = SteganographyEngine.embedData(image, payload)

        assertArrayEquals(payload, SecurityExtractor.extractFromBitmap(stego))
    }

    @Test
    fun `embedding a fragment larger than the carrier is rejected`() {
        val image = carrier(64, 64)
        val tooBig = ByteArray(SteganographyEngine.maxPayloadBytes(image) + 1)

        val error = runCatching { SteganographyEngine.embedData(image, tooBig) }.exceptionOrNull()

        assertTrue("Expected IllegalArgumentException", error is IllegalArgumentException)
        assertTrue(
            "Error should explain the shortfall: ${error?.message}",
            error?.message?.contains("Carrier image holds") == true
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `extracting from an image too small for the length prefix is rejected`() {
        // 4x4 = 16 pixels, fewer than the 32 bits of length prefix.
        SecurityExtractor.extractFromBitmap(carrier(4, 4))
    }

    @Test
    fun `extracting an image declaring more payload than it carries is rejected`() {
        // A plain unmodified image: its LSBs decode to a nonsense length far
        // larger than the pixels available.
        val notACarrier = Bitmap.createBitmap(64, 64, Bitmap.Config.ARGB_8888).apply {
            eraseColor(Color.WHITE) // 0xFFFFFFFF -> every LSB is 1
        }

        val error = runCatching { SecurityExtractor.extractFromBitmap(notACarrier) }.exceptionOrNull()

        assertTrue("Expected IllegalArgumentException, got $error", error is IllegalArgumentException)
    }

    @Test
    fun `embedding only disturbs the least significant bit`() {
        val image = carrier(64, 64)
        val payload = ByteArray(32) { 0xFF.toByte() }

        val stego = SteganographyEngine.embedData(image, payload)

        val originalPixels = IntArray(image.width * image.height)
        image.getPixels(originalPixels, 0, image.width, 0, 0, image.width, image.height)

        val stegoPixels = IntArray(stego.width * stego.height)
        stego.getPixels(stegoPixels, 0, stego.width, 0, 0, stego.width, stego.height)

        for (index in originalPixels.indices) {
            assertEquals(
                "pixel $index changed beyond its LSB",
                originalPixels[index] and 0xFFFFFFFE.toInt(),
                stegoPixels[index] and 0xFFFFFFFE.toInt()
            )
        }
    }

    @Test
    fun `stego image differs from the carrier`() {
        val image = carrier(64, 64)
        val stego = SteganographyEngine.embedData(image, ByteArray(64) { 0xFF.toByte() })

        val originalPixels = IntArray(image.width * image.height)
        image.getPixels(originalPixels, 0, image.width, 0, 0, image.width, image.height)

        val stegoPixels = IntArray(stego.width * stego.height)
        stego.getPixels(stegoPixels, 0, stego.width, 0, 0, stego.width, stego.height)

        assertNotEquals(
            "Embedding should have modified some LSBs",
            originalPixels.toList(),
            stegoPixels.toList()
        )
    }
}
