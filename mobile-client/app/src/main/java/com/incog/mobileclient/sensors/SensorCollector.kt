package com.incog.mobileclient.sensors

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager

/**
 * Phase 3 — collects live accelerometer + gyroscope readings during Ghost State.
 *
 * Keeps the latest sample of each plus a bounded rolling history (the raw arrays Lipika's
 * feature-extraction step consumes). Readings are delivered on the main looper by default;
 * history access is synchronized so the service's snapshot logger can read safely.
 */
class SensorCollector(context: Context) : SensorEventListener {

    private val sensorManager =
        context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroscope = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

    private val accelHistory = ArrayDeque<Vec3Reading>()
    private val gyroHistory = ArrayDeque<Vec3Reading>()

    @Volatile
    var latestAccel: Vec3Reading? = null
        private set

    @Volatile
    var latestGyro: Vec3Reading? = null
        private set

    fun start() {
        accelerometer?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }
        gyroscope?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }
    }

    fun stop() {
        sensorManager.unregisterListener(this)
        synchronized(accelHistory) { accelHistory.clear() }
        synchronized(gyroHistory) { gyroHistory.clear() }
        latestAccel = null
        latestGyro = null
    }

    val accelSampleCount: Int get() = synchronized(accelHistory) { accelHistory.size }
    val gyroSampleCount: Int get() = synchronized(gyroHistory) { gyroHistory.size }

    /** Snapshot copies of the rolling history — for the handoff to Lipika's Phase 4. */
    fun accelSamples(): List<Vec3Reading> = synchronized(accelHistory) { accelHistory.toList() }
    fun gyroSamples(): List<Vec3Reading> = synchronized(gyroHistory) { gyroHistory.toList() }

    override fun onSensorChanged(event: SensorEvent) {
        val reading = Vec3Reading(
            timestampMs = System.currentTimeMillis(),
            x = event.values[0],
            y = event.values[1],
            z = event.values[2]
        )
        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                latestAccel = reading
                addBounded(accelHistory, reading)
            }
            Sensor.TYPE_GYROSCOPE -> {
                latestGyro = reading
                addBounded(gyroHistory, reading)
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) { /* not needed */ }

    private fun addBounded(history: ArrayDeque<Vec3Reading>, reading: Vec3Reading) {
        synchronized(history) {
            history.addLast(reading)
            while (history.size > MAX_SAMPLES) history.removeFirst()
        }
    }

    companion object {
        /** ~ a few seconds of history at SENSOR_DELAY_GAME (~50 Hz). */
        private const val MAX_SAMPLES = 1000
    }
}
