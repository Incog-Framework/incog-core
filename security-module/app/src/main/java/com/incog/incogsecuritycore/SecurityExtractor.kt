package com.incog.incogsecuritycore

import android.graphics.Bitmap
import javax.crypto.SecretKey

object SecurityExtractor {

    /** Bits used by the length prefix SteganographyEngine writes ahead of the payload. */
    private const val LENGTH_PREFIX_BITS = SteganographyEngine.LENGTH_PREFIX_SIZE * 8

    /**
     * Extracts raw embedded bytes from the LSBs of a Bitmap.
     *
     * CPU-bound and O(width * height): call it off the main thread.
     *
     * @throws IllegalArgumentException if the image is too small to hold the
     *   length prefix, or declares a payload larger than it can actually carry
     *   (a truncated or non-carrier image), instead of returning a
     *   half-populated byte array.
     */
    fun extractFromBitmap(bitmap: Bitmap): ByteArray {
        val width = bitmap.width
        val height = bitmap.height

        // Read every pixel in one pass instead of a getPixel() call per pixel.
        val pixels = IntArray(width * height)
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height)

        require(pixels.size >= LENGTH_PREFIX_BITS) {
            "Stego image has only ${pixels.size} pixels, too few to hold the " +
                "$LENGTH_PREFIX_BITS-bit length prefix."
        }

        // 1. Extract first 32 bits to determine payload size (4 bytes)
        var payloadSize = 0
        for (i in 0 until LENGTH_PREFIX_BITS) {
            payloadSize = (payloadSize shl 1) or (pixels[i] and 1)
        }

        require(payloadSize >= 0) {
            "Stego image declares a negative payload size ($payloadSize); it is not a valid carrier."
        }

        // Long arithmetic: a corrupt prefix can declare a size whose bit count
        // would overflow Int and wrap into a passing comparison.
        val requiredBits = LENGTH_PREFIX_BITS + payloadSize.toLong() * 8

        require(requiredBits <= pixels.size.toLong()) {
            "Stego image declares a $payloadSize-byte payload needing $requiredBits bits, but the " +
                "image only carries ${pixels.size}. The image is truncated or is not a carrier."
        }

        // 2. Extract payload bytes bit-by-bit from the pixel buffer
        val extractedBytes = ByteArray(payloadSize)
        var bitIndex = LENGTH_PREFIX_BITS

        for (byteIndex in 0 until payloadSize) {
            var currentByte = 0

            for (bitPosInByte in 0 until 8) {
                currentByte = (currentByte shl 1) or (pixels[bitIndex] and 1)
                bitIndex++
            }

            extractedBytes[byteIndex] = currentByte.toByte()
        }

        return extractedBytes
    }

    /**
     * Decrypts AES-256-GCM ciphertext (IV prepended) into a UTF-8 string.
     * Delegates to [CryptoManager] so both directions share one implementation.
     */
    fun decryptPayload(encryptedData: ByteArray, secretKey: SecretKey): String =
        String(CryptoManager.decrypt(encryptedData, secretKey), Charsets.UTF_8)
}
