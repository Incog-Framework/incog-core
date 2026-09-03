package com.incog.incogsecuritycore

import android.util.Base64
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * DECISION 1: the AES-256 key is loaded from build-time config and shared with
 * the backend, not generated fresh per session.
 */
@RunWith(RobolectricTestRunner::class)
class CryptoManagerKeyTest {

    private fun base64KeyOfLength(bytes: Int): String =
        Base64.encodeToString(ByteArray(bytes) { it.toByte() }, Base64.NO_WRAP)

    @Test
    fun `configured key is a 256-bit AES key`() {
        val key = CryptoManager.loadSharedKey()

        assertEquals("AES", key.algorithm)
        assertEquals(CryptoManager.AES_KEY_LENGTH_BYTES, key.encoded.size)
    }

    @Test
    fun `the same shared key is returned every call, not a fresh one`() {
        // The backend decrypts with its own copy of this key, so two calls in
        // the same build must produce identical key material.
        assertArrayEquals(
            CryptoManager.loadSharedKey().encoded,
            CryptoManager.loadSharedKey().encoded
        )
    }

    @Test
    fun `a valid 32-byte base64 key parses`() {
        val key = CryptoManager.parseSharedKey(base64KeyOfLength(32))

        assertEquals(CryptoManager.AES_KEY_LENGTH_BYTES, key.encoded.size)
    }

    @Test
    fun `a key of the wrong length is rejected`() {
        val error = runCatching { CryptoManager.parseSharedKey(base64KeyOfLength(16)) }.exceptionOrNull()

        assertTrue("Expected IllegalArgumentException", error is IllegalArgumentException)
        assertTrue(
            "Error should state the required length: ${error?.message}",
            error?.message?.contains("32 bytes") == true
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `a blank key is rejected`() {
        CryptoManager.parseSharedKey("   ")
    }

    @Test
    fun `data encrypted with the shared key decrypts with a separately loaded copy`() {
        // Mirrors the real flow: this app encrypts, the backend decrypts using
        // the same configured key value rather than a transmitted one.
        val plaintext = "evidence blob".toByteArray(Charsets.UTF_8)

        val blob = CryptoManager.encrypt(plaintext, CryptoManager.loadSharedKey())
        val recovered = CryptoManager.decrypt(blob, CryptoManager.loadSharedKey())

        assertArrayEquals(plaintext, recovered)
    }

    @Test
    fun `a different key cannot decrypt the blob`() {
        val blob = CryptoManager.encrypt("secret".toByteArray(), CryptoManager.loadSharedKey())

        val error = runCatching {
            CryptoManager.decrypt(blob, CryptoManager.parseSharedKey(base64KeyOfLength(32)))
        }.exceptionOrNull()

        assertTrue("GCM auth should fail with the wrong key", error != null)
    }
}
