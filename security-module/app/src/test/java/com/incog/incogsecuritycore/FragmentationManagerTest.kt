package com.incog.incogsecuritycore

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Phase 9 fragmentation: fragments carry an index/total header so reassembly
 * survives out-of-order delivery and reports missing/duplicated pieces
 * instead of silently producing a corrupt blob.
 */
class FragmentationManagerTest {

    private val payload = ByteArray(1000) { (it % 251).toByte() }

    @Test
    fun `fragments carry an index-and-total header`() {
        val fragments = FragmentationManager.fragmentData(payload, chunkSize = 256)

        assertEquals("1000 bytes at 256 per fragment", 4, fragments.size)

        fragments.forEachIndexed { expectedIndex, fragment ->
            val index = ((fragment[0].toInt() and 0xFF) shl 8) or (fragment[1].toInt() and 0xFF)
            val total = ((fragment[2].toInt() and 0xFF) shl 8) or (fragment[3].toInt() and 0xFF)

            assertEquals("fragment index", expectedIndex, index)
            assertEquals("fragment total", fragments.size, total)
        }
    }

    @Test
    fun `header adds only its fixed overhead to each fragment`() {
        val fragments = FragmentationManager.fragmentData(payload, chunkSize = 256)

        assertEquals(256 + FragmentationManager.FRAGMENT_HEADER_SIZE, fragments[0].size)
        // 1000 = 3 * 256 + 232 for the final fragment
        assertEquals(232 + FragmentationManager.FRAGMENT_HEADER_SIZE, fragments.last().size)
    }

    @Test
    fun `in-order fragments reassemble to the original payload`() {
        val fragments = FragmentationManager.fragmentData(payload, chunkSize = 256)

        assertArrayEquals(payload, FragmentationManager.reassembleData(fragments))
    }

    @Test
    fun `shuffled fragments reassemble to the original payload`() {
        val fragments = FragmentationManager.fragmentData(payload, chunkSize = 128)

        assertArrayEquals(payload, FragmentationManager.reassembleData(fragments.shuffled()))
        assertArrayEquals(payload, FragmentationManager.reassembleData(fragments.reversed()))
    }

    @Test
    fun `a missing fragment is reported instead of silently corrupting the blob`() {
        val fragments = FragmentationManager.fragmentData(payload, chunkSize = 256)
        val incomplete = fragments.filterIndexed { index, _ -> index != 1 }

        val error = runCatching { FragmentationManager.reassembleData(incomplete) }.exceptionOrNull()

        assertTrue("Expected IllegalArgumentException", error is IllegalArgumentException)
        assertTrue(
            "Error should name the missing fragment: ${error?.message}",
            error?.message?.contains("missing [1]") == true
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun `duplicate fragments are rejected`() {
        val fragments = FragmentationManager.fragmentData(payload, chunkSize = 256)

        FragmentationManager.reassembleData(fragments + fragments[0])
    }

    @Test(expected = IllegalArgumentException::class)
    fun `fragments from different payloads are rejected`() {
        val first = FragmentationManager.fragmentData(payload, chunkSize = 256)
        val second = FragmentationManager.fragmentData(ByteArray(100), chunkSize = 256)

        FragmentationManager.reassembleData(listOf(first[0], second[0]))
    }

    @Test(expected = IllegalArgumentException::class)
    fun `header-only fragment is rejected as malformed`() {
        FragmentationManager.reassembleData(listOf(ByteArray(FragmentationManager.FRAGMENT_HEADER_SIZE)))
    }

    @Test(expected = IllegalArgumentException::class)
    fun `empty fragment list is rejected`() {
        FragmentationManager.reassembleData(emptyList())
    }

    @Test(expected = IllegalArgumentException::class)
    fun `non-positive chunk size is rejected`() {
        FragmentationManager.fragmentData(payload, chunkSize = 0)
    }

    @Test
    fun `single fragment payload round-trips`() {
        val small = ByteArray(10) { it.toByte() }
        val fragments = FragmentationManager.fragmentData(small, chunkSize = 256)

        assertEquals(1, fragments.size)
        assertArrayEquals(small, FragmentationManager.reassembleData(fragments))
    }
}
