package com.incog.incogsecuritycore

import android.graphics.Bitmap
import java.nio.ByteBuffer

object SteganographyEngine {

    /** 4-byte big-endian length prefix written ahead of every payload. */
    const val LENGTH_PREFIX_SIZE = 4

    /**
     * How many payload bytes a carrier can actually hold: one bit per pixel,
     * minus the space taken by the length prefix.
     */
    fun maxPayloadBytes(carrierImage: Bitmap): Int =
        (carrierImage.width * carrierImage.height) / 8 - LENGTH_PREFIX_SIZE

    /**
     * Embeds a byte array (payload fragment) into the Least Significant Bits (LSB)
     * of a carrier image (Bitmap) using bitwise image manipulation.
     *
     * CPU-bound and O(width * height): call it off the main thread.
     * SecurityOrchestrator already runs it on Dispatchers.Default.
     *
     * @param carrierImage The original local PNG image carrier.
     * @param payloadFragment The sliced encrypted binary chunk.
     * @return A new Stego Image (Bitmap) containing the hidden data.
     * @throws IllegalArgumentException if the fragment does not fit in the carrier.
     */
    fun embedData(carrierImage: Bitmap, payloadFragment: ByteArray): Bitmap {
        val width = carrierImage.width
        val height = carrierImage.height

        // Read every pixel in one pass instead of a getPixel() call per pixel.
        val pixels = IntArray(width * height)
        carrierImage.getPixels(pixels, 0, width, 0, 0, width, height)

        // 1. Prepend a 4-byte length prefix so the extractor knows how much to read
        val lengthPrefix = ByteBuffer.allocate(LENGTH_PREFIX_SIZE).putInt(payloadFragment.size).array()
        val completePayload = lengthPrefix + payloadFragment

        val totalBits = completePayload.size * 8

        // 2. Capacity guard. Without this the embed loop simply stopped when it
        //    ran out of pixels, producing a truncated stego image that could
        //    never be decrypted - a silent data-loss bug.
        require(totalBits <= pixels.size) {
            "Carrier image holds ${pixels.size} bits (${width}x$height) but this fragment needs " +
                "$totalBits bits (${payloadFragment.size} payload bytes + $LENGTH_PREFIX_SIZE-byte " +
                "length prefix). Use a larger carrier or a smaller fragment size."
        }

        // 3. Write one payload bit into the LSB of each pixel.
        for (bitIndex in 0 until totalBits) {
            val bytePos = bitIndex / 8
            val bitPosInByte = 7 - (bitIndex % 8)
            val bitToEmbed = (completePayload[bytePos].toInt() shr bitPosInByte) and 1

            // Clear the LSB of the pixel (0xFFFFFFFE) and insert our data bit
            pixels[bitIndex] = (pixels[bitIndex] and 0xFFFFFFFE.toInt()) or bitToEmbed
        }

        // 4. Write every pixel back in one pass.
        val stegoImage = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        stegoImage.setPixels(pixels, 0, width, 0, 0, width, height)

        return stegoImage
    }
}
