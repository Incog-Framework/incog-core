package com.incog.incogsecuritycore
import java.nio.ByteBuffer

/**
 * Slices the encrypted blob into carrier-sized fragments and puts them back together.
 *
 * Every emitted fragment carries its own ordering header:
 *
 *     [ index : 2 bytes ][ total : 2 bytes ][ data : up to chunkSize bytes ]
 *
 * The header travels with the fragment, so reassembly no longer depends on
 * upload or storage order - fragments can come back shuffled, and a missing or
 * duplicated one is reported instead of silently corrupting the blob.
 */
object FragmentationManager {

    /** Bytes of ordering metadata prepended to every fragment. */
    const val FRAGMENT_HEADER_SIZE = 4

    /** Largest fragment count addressable by the 2-byte index/total fields. */
    const val MAX_FRAGMENTS = 0xFFFF

    /**
     * Slices a large encrypted binary blob into smaller payload fragments.
     *
     * @param payload The complete encrypted byte array.
     * @param chunkSize The maximum size (in bytes) of the DATA carried by each
     *   fragment. Each returned fragment is up to
     *   `chunkSize + FRAGMENT_HEADER_SIZE` bytes once the header is added.
     * @return A list of fragments [F_1, F_2, ..., F_n], each tagged with its index and the total.
     */
    fun fragmentData(payload: ByteArray, chunkSize: Int): List<ByteArray> {
        require(chunkSize > 0) { "chunkSize must be positive but was $chunkSize." }
        require(payload.isNotEmpty()) { "Cannot fragment an empty payload." }

        val total = (payload.size + chunkSize - 1) / chunkSize

        require(total <= MAX_FRAGMENTS) {
            "Payload needs $total fragments, more than the $MAX_FRAGMENTS a 2-byte index can address. " +
                "Use a larger chunkSize."
        }

        val fragments = ArrayList<ByteArray>(total)
        var offset = 0
        var index = 0

        while (offset < payload.size) {
            // Calculate how much data is left; take either the chunk size or the remainder
            val size = minOf(chunkSize, payload.size - offset)

            val fragment = ByteBuffer.allocate(FRAGMENT_HEADER_SIZE + size)
            fragment.putShort(index.toShort())
            fragment.putShort(total.toShort())
            fragment.put(payload, offset, size)

            fragments.add(fragment.array())
            offset += size
            index++
        }

        return fragments
    }

    /**
     * Reassembles payload fragments back into the original encrypted binary blob.
     *
     * Order-independent: fragments are sorted by their embedded index, so an
     * out-of-order upload still reassembles correctly. Throws
     * IllegalArgumentException if fragments are malformed, duplicated, missing,
     * or belong to different evidence packages.
     *
     * (Chirag will write the Python equivalent of this on the Backend, but we need it here for testing).
     */
    fun reassembleData(fragments: List<ByteArray>): ByteArray {
        require(fragments.isNotEmpty()) { "Cannot reassemble an empty fragment list." }

        var expectedTotal = -1
        val dataByIndex = HashMap<Int, ByteArray>(fragments.size)

        for (fragment in fragments) {
            require(fragment.size > FRAGMENT_HEADER_SIZE) {
                "Malformed fragment: ${fragment.size} bytes cannot hold a " +
                    "$FRAGMENT_HEADER_SIZE-byte header plus data."
            }

            val buffer = ByteBuffer.wrap(fragment)
            val index = buffer.short.toInt() and 0xFFFF
            val total = buffer.short.toInt() and 0xFFFF

            if (expectedTotal == -1) {
                expectedTotal = total
            }

            require(total == expectedTotal) {
                "Fragments disagree on the total count ($expectedTotal vs $total) - they are " +
                    "probably from different evidence packages."
            }

            require(index < total) {
                "Fragment index $index is out of range for a $total-fragment payload."
            }

            require(!dataByIndex.containsKey(index)) { "Duplicate fragment index $index." }

            val data = ByteArray(buffer.remaining())
            buffer.get(data)
            dataByIndex[index] = data
        }

        require(dataByIndex.size == expectedTotal) {
            val missing = (0 until expectedTotal).filterNot(dataByIndex::containsKey)
            "Incomplete payload: got ${dataByIndex.size} of $expectedTotal fragments (missing $missing)."
        }

        val totalSize = dataByIndex.values.sumOf { it.size }
        val reassembled = ByteBuffer.allocate(totalSize)

        for (index in 0 until expectedTotal) {
            reassembled.put(dataByIndex.getValue(index))
        }

        return reassembled.array()
    }
}
