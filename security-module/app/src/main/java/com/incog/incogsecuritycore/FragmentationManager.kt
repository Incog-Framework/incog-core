package com.incog.incogsecuritycore
import java.nio.ByteBuffer

object FragmentationManager {

    /**
     * Slices a large encrypted binary blob into smaller payload fragments.
     *
     * @param payload The complete encrypted byte array.
     * @param chunkSize The maximum size (in bytes) of each fragment.
     * @return A list of byte arrays representing the payload fragments [F_1, F_2, ..., F_n].
     */
    fun fragmentData(payload: ByteArray, chunkSize: Int): List<ByteArray> {
        val fragments = mutableListOf<ByteArray>()
        var offset = 0

        while (offset < payload.size) {
            // Calculate how much data is left; take either the chunk size or the remainder
            val size = minOf(chunkSize, payload.size - offset)
            val chunk = payload.copyOfRange(offset, offset + size)
            fragments.add(chunk)
            offset += size
        }

        return fragments
    }

    /**
     * Reassembles payload fragments back into the original encrypted binary blob.
     * (Chirag will write the Python equivalent of this on the Backend, but we need it here for testing).
     */
    fun reassembleData(fragments: List<ByteArray>): ByteArray {
        var totalSize = 0
        for (fragment in fragments) {
            totalSize += fragment.size
        }

        val reassembled = ByteBuffer.allocate(totalSize)
        for (fragment in fragments) {
            reassembled.put(fragment)
        }

        return reassembled.array()
    }
}