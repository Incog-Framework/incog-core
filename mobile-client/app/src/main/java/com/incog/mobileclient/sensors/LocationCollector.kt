package com.incog.mobileclient.sensors

import android.annotation.SuppressLint
import android.content.Context
import android.os.Looper
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority

/**
 * Phase 3 — collects live GPS fixes during Ghost State via the fused location provider.
 *
 * The caller (GhostStateService) is responsible for verifying the location permission before
 * calling [start]; hence the MissingPermission suppression here.
 */
class LocationCollector(context: Context) {

    private val client = LocationServices.getFusedLocationProviderClient(context)

    @Volatile
    var latest: LocationReading? = null
        private set

    private val request =
        LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, UPDATE_INTERVAL_MS)
            .setMinUpdateIntervalMillis(MIN_UPDATE_INTERVAL_MS)
            .build()

    private val callback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            val location = result.lastLocation ?: return
            latest = LocationReading(
                timestampMs = System.currentTimeMillis(),
                latitude = location.latitude,
                longitude = location.longitude,
                speedMps = location.speed,
                accuracyM = location.accuracy
            )
        }
    }

    @SuppressLint("MissingPermission")
    fun start() {
        client.requestLocationUpdates(request, callback, Looper.getMainLooper())
    }

    fun stop() {
        client.removeLocationUpdates(callback)
        latest = null
    }

    companion object {
        private const val UPDATE_INTERVAL_MS = 2000L
        private const val MIN_UPDATE_INTERVAL_MS = 1000L
    }
}
