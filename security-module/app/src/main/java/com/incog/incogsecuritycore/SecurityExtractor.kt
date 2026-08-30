package com.incog.incogsecuritycore

import android.graphics.Bitmap
import java.nio.ByteBuffer
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

object SecurityExtractor {

    private const val AES_GCM_NO_PADDING = "AES/GCM/NoPadding"
    private const val GCM_IV_LENGTH = 12
    private const val GCM_TAG_LENGTH = 128

    /**
     * Extracts raw embedded bytes from the LSBs of a Bitmap.
     */
    fun extractFromBitmap(bitmap: Bitmap): ByteArray {
        val width = bitmap.width
        val height = bitmap.height
        val totalPixels = width * height

        // 1. Extract first 32 bits to determine payload size (4 bytes)
        var lengthBits = 0
        var bitIndex = 0

        for (i in 0 until 32) {
            val x = i % width
            val y = i / width
            val pixel = bitmap.getPixel(x, y)
            val lsb = pixel and 1
            lengthBits = (lengthBits shl 1) or lsb
            bitIndex++
        }

        val payloadSize = lengthBits
        val extractedBytes = ByteArray(payloadSize)

        // 2. Extract payload bytes bit-by-bit
        var currentByte = 0
        var byteBitCounter = 0
        var byteIndex = 0

        while (byteIndex < payloadSize && bitIndex < totalPixels) {
            val x = bitIndex % width
            val y = bitIndex / width
            val pixel = bitmap.getPixel(x, y)
            val lsb = pixel and 1

            currentByte = (currentByte shl 1) or lsb
            byteBitCounter++

            if (byteBitCounter == 8) {
                extractedBytes[byteIndex] = currentByte.toByte()
                currentByte = 0
                byteBitCounter = 0
                byteIndex++
            }
            bitIndex++
        }

        return extractedBytes
    }

    /**
     * Decrypts AES-256-GCM ciphertext (IV prepended).
     */
    fun decryptPayload(encryptedData: ByteArray, secretKey: SecretKey): String {
        val buffer = ByteBuffer.wrap(encryptedData)
        val iv = ByteArray(GCM_IV_LENGTH)
        buffer.get(iv)

        val cipherText = ByteArray(buffer.remaining())
        buffer.get(cipherText)

        val cipher = Cipher.getInstance(AES_GCM_NO_PADDING)
        val spec = GCMParameterSpec(GCM_TAG_LENGTH, iv)
        cipher.init(Cipher.DECRYPT_MODE, secretKey, spec)

        val decryptedBytes = cipher.doFinal(cipherText)
        return String(decryptedBytes, Charsets.UTF_8)
    }
}