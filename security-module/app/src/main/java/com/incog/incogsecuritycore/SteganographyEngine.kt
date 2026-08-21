package com.incog.incogsecuritycore

import android.graphics.Bitmap
import java.nio.ByteBuffer

object SteganographyEngine {
    /**
     * Embeds a byte array (payload fragment) into the Least Significant Bits (LSB)
     * of a carrier image (Bitmap) using bitwise image manipulation.
     *
     * @param carrierImage The original local PNG image carrier.
     * @param payloadFragment The sliced encrypted binary chunk.
     * @return A new Stego Image (Bitmap) containing the hidden data.
     */
    fun embedData(carrierImage: Bitmap, payloadFragment: ByteArray): Bitmap {
        // Create a mutable copy of the carrier image to manipulate pixels
        val stegoImage = carrierImage.copy(Bitmap.Config.ARGB_8888, true)

        val width = stegoImage.width
        val height = stegoImage.height

        // 1. Prepend a 4-byte length prefix so the extractor knows how much to read
        val lengthPrefix = ByteBuffer.allocate(4).putInt(payloadFragment.size).array()
        val completePayload = lengthPrefix + payloadFragment

        var bitIndex = 0
        val totalBits = completePayload.size * 8

        // 2. Iterate through pixels to embed data (1 bit per pixel to match extraction)
        for (y in 0 until height) {
            for (x in 0 until width) {
                if (bitIndex >= totalBits) {
                    return stegoImage // All data embedded safely
                }

                // Calculate which bit of the payload we need to embed right now
                val bytePos = bitIndex / 8
                val bitPosInByte = 7 - (bitIndex % 8)
                val bitToEmbed = (completePayload[bytePos].toInt() shr bitPosInByte) and 1

                val pixel = stegoImage.getPixel(x, y)

                // Clear the LSB of the pixel (0xFFFFFFFE) and insert our data bit
                val newPixel = (pixel and 0xFFFFFFFE.toInt()) or bitToEmbed

                // Write the modified pixel back to the image
                stegoImage.setPixel(x, y, newPixel)

                bitIndex++
            }
        }

        return stegoImage
    }
}