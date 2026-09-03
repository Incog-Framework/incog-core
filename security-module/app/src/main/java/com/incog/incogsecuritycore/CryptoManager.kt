package com.incog.incogsecuritycore

import android.util.Base64
import android.util.Log
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

object CryptoManager {
    private const val TAG = "CryptoManager"
    private const val AES_GCM_NO_PADDING = "AES/GCM/NoPadding"
    private const val GCM_IV_LENGTH = 12 // 12 bytes / 96 bits standard for GCM
    private const val GCM_TAG_LENGTH = 128 // 128-bit authentication tag

    /** AES-256 means a 32-byte key. */
    const val AES_KEY_LENGTH_BYTES = 32

    /**
     * Loads the AES-256 key shared with the backend (team DECISION 1).
     *
     * The key is injected at build time from local.properties or the
     * INCOG_EVIDENCE_KEY_BASE64 environment variable - see app/build.gradle.kts.
     * It is deliberately NOT a fresh per-session key: the backend loads the
     * same value from its own config so it can decrypt what we upload.
     */
    fun loadSharedKey(): SecretKey =
        parseSharedKey(
            base64Key = BuildConfig.EVIDENCE_KEY_BASE64,
            isPlaceholder = BuildConfig.EVIDENCE_KEY_IS_PLACEHOLDER
        )

    /**
     * Parses a Base64-encoded 256-bit key. Exposed separately from
     * [loadSharedKey] so tests can supply a key without a rebuild.
     */
    @JvmOverloads
    fun parseSharedKey(base64Key: String, isPlaceholder: Boolean = false): SecretKey {
        require(base64Key.isNotBlank()) {
            "Shared evidence key is not configured. Set incog.evidenceKeyBase64 in " +
                "local.properties or INCOG_EVIDENCE_KEY_BASE64 in the environment."
        }

        if (isPlaceholder) {
            Log.w(
                TAG,
                "Using the PLACEHOLDER evidence key. Evidence encrypted with it will NOT " +
                    "decrypt on the backend - set the real shared key before shipping."
            )
        }

        val keyBytes = try {
            Base64.decode(base64Key, Base64.NO_WRAP)
        } catch (error: IllegalArgumentException) {
            throw IllegalArgumentException("Shared evidence key is not valid Base64.", error)
        }

        require(keyBytes.size == AES_KEY_LENGTH_BYTES) {
            "Shared evidence key must be $AES_KEY_LENGTH_BYTES bytes (AES-256) but was " +
                "${keyBytes.size} bytes."
        }

        return SecretKeySpec(keyBytes, "AES")
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