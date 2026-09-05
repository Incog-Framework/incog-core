package com.incog.mobileclient.sensors

import android.annotation.SuppressLint
import android.content.Context
import android.location.Location
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
            latest = location.toReading()
        }
    }

    private fun Location.toReading() = LocationReading(
        timestampMs = System.currentTimeMillis(),
        latitude = latitude,
        longitude = longitude,
        speedMps = speed,
        accuracyM = accuracy
    )

    @SuppressLint("MissingPermission")
    fun start() {
        // Seed immediately with the fused provider's cached last-known fix. A live streaming fix can
        // take a few seconds to arrive, and an emergency can be confirmed on the very first snapshot
        // (~2s in) — without this seed that upload carries no location and defaults to 0,0, which for
        // a safety alert is worse than useless (it points responders to the wrong place). Only seed
        // if a live fix hasn't already landed, so a fresh streaming update always wins.
        client.lastLocation.addOnSuccessListener { location ->
            if (location != null && latest == null) {
                latest = location.toReading()
            }
        }
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
