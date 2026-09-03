package com.incog.mobileclient.sensors

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import kotlin.math.sqrt

/**
 * Phase 3 — streams microphone PCM into a fixed-size in-memory circular buffer during Ghost State.
 *
 * Nothing is written to disk (the workflow keeps audio as a "live memory stream" until Phase 7
 * flushes it to a file). The buffer holds the most recent [BUFFER_SECONDS] seconds; older audio is
 * overwritten. [lastRmsEnergy] is exposed as a lightweight signal for verification/logging.
 *
 * The caller verifies RECORD_AUDIO before [start]; hence the MissingPermission suppression.
 */
class AudioBufferCollector {

    private var audioRecord: AudioRecord? = null
    private var readThread: Thread? = null
    @Volatile private var running = false

    private val ringCapacityBytes = SAMPLE_RATE * BYTES_PER_SAMPLE * BUFFER_SECONDS
    private val ring = ByteArray(ringCapacityBytes)
    private var writePos = 0
    @Volatile private var bytesBuffered = 0

    @Volatile
    var lastRmsEnergy: Double = 0.0
        private set

    val bufferedMs: Long
        get() = (bytesBuffered.toLong() * 1000L) / (SAMPLE_RATE * BYTES_PER_SAMPLE)

    /**
     * Snapshot the buffered PCM in chronological order (oldest sample first). This is the flushed
     * audio handed to the security pipeline as evidence. Empty if nothing has been captured yet.
     */
    fun snapshotPcm(): ByteArray = synchronized(ring) {
        if (bytesBuffered == 0) return@synchronized ByteArray(0)
        val out = ByteArray(bytesBuffered)
        if (bytesBuffered < ringCapacityBytes) {
            // Not wrapped yet: chronological data is ring[0 until bytesBuffered).
            System.arraycopy(ring, 0, out, 0, bytesBuffered)
        } else {
            // Full & wrapped: the oldest byte is at writePos.
            val tail = ringCapacityBytes - writePos
            System.arraycopy(ring, writePos, out, 0, tail)
            System.arraycopy(ring, 0, out, tail, writePos)
        }
        out
    }

    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBuffer <= 0) {
            Log.w(TAG, "AudioRecord min buffer unavailable ($minBuffer) — mic capture skipped.")
            return false
        }
        val record = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            minBuffer * 2
        )
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            Log.w(TAG, "AudioRecord failed to initialize — mic capture skipped.")
            record.release()
            return false
        }
        audioRecord = record
        record.startRecording()
        running = true
        readThread = Thread { readLoop(minBuffer) }.apply { start() }
        return true
    }

    private fun readLoop(chunkSize: Int) {
        val chunk = ByteArray(chunkSize)
        while (running) {
            val read = audioRecord?.read(chunk, 0, chunk.size) ?: -1
            if (read > 0) {
                writeToRing(chunk, read)
                lastRmsEnergy = computeRms(chunk, read)
            }
        }
    }

    private fun writeToRing(data: ByteArray, length: Int) {
        synchronized(ring) {
            for (i in 0 until length) {
                ring[writePos] = data[i]
                writePos = (writePos + 1) % ringCapacityBytes
            }
            bytesBuffered = minOf(bytesBuffered + length, ringCapacityBytes)
        }
    }

    private fun computeRms(data: ByteArray, length: Int): Double {
        var sumSquares = 0.0
        var count = 0
        var i = 0
        while (i + 1 < length) {
            // little-endian 16-bit PCM
            val sample = (data[i].toInt() and 0xFF) or (data[i + 1].toInt() shl 8)
            sumSquares += (sample * sample).toDouble()
            count++
            i += 2
        }
        if (count == 0) return 0.0
        return sqrt(sumSquares / count)
    }

    fun stop() {
        running = false
        readThread?.join(300)
        readThread = null
        audioRecord?.apply {
            try {
                stop()
            } catch (_: IllegalStateException) {
                // already stopped
            }
            release()
        }
        audioRecord = null
        synchronized(ring) {
            writePos = 0
            bytesBuffered = 0
        }
        lastRmsEnergy = 0.0
    }

    companion object {
        private const val TAG = "AudioBuffer"
        const val SAMPLE_RATE = 16000
        private const val BYTES_PER_SAMPLE = 2
        private const val BUFFER_SECONDS = 30
    }
}
