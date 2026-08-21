package com.incog.incogsecuritycore

import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

object CryptoManager {
    private const val AES_GCM_NO_PADDING = "AES/GCM/NoPadding"
    private const val GCM_IV_LENGTH = 12 // 12 bytes / 96 bits standard for GCM
    private const val GCM_TAG_LENGTH = 128 // 128-bit authentication tag

    /**
     * Generates a random 256-bit AES secret key.
     */
    fun generate256BitKey(): SecretKey {
        val keyGen = KeyGenerator.getInstance("AES")
        keyGen.init(256, SecureRandom())
        return keyGen.generateKey()
    }

    /**
     * Encrypts plain byte array data using AES-256-GCM.
     * Appends the generated 12-byte IV to the beginning of the ciphertext.
     */
    fun encrypt(rawData: ByteArray, key: SecretKey): ByteArray {
        // 1. Generate a random Initialization Vector (IV)
        val iv = ByteArray(GCM_IV_LENGTH)
        SecureRandom().nextBytes(iv)

        // 2. Set up the Cipher
        val cipher = Cipher.getInstance(AES_GCM_NO_PADDING)
        val parameterSpec = GCMParameterSpec(GCM_TAG_LENGTH, iv)
        cipher.init(Cipher.ENCRYPT_MODE, key, parameterSpec)

        // 3. Encrypt the data
        val cipherText = cipher.doFinal(rawData)

        // 4. Return Single Encrypted Binary Blob: [ 12-byte IV ] + [ Ciphertext + Auth Tag ]
        return iv + cipherText
    }

    /**
     * Decrypts an encrypted binary blob produced by encrypt().
     */
    fun decrypt(encryptedBlob: ByteArray, key: SecretKey): ByteArray {
        require(encryptedBlob.size > GCM_IV_LENGTH) { "Invalid payload length." }

        // 1. Extract the IV from the front of the blob
        val iv = encryptedBlob.copyOfRange(0, GCM_IV_LENGTH)

        // 2. Extract the actual encrypted data
        val cipherText = encryptedBlob.copyOfRange(GCM_IV_LENGTH, encryptedBlob.size)

        // 3. Set up the Cipher for decryption
        val cipher = Cipher.getInstance(AES_GCM_NO_PADDING)
        val parameterSpec = GCMParameterSpec(GCM_TAG_LENGTH, iv)
        cipher.init(Cipher.DECRYPT_MODE, key, parameterSpec)

        // 4. Decrypt and return original bytes
        return cipher.doFinal(cipherText)
    }
}