package com.incog.mobileclient.ghost

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import androidx.core.app.NotificationCompat
import com.incog.mobileclient.ai.EmergencyClassifier
import com.incog.mobileclient.handoff.SensorPacket
import com.incog.mobileclient.sensors.AudioBufferCollector
import com.incog.mobileclient.sensors.LocationCollector
import com.incog.mobileclient.sensors.SensorCollector
import java.util.UUID

/**
 * Phase 2 — Ghost State.
 *
 * A foreground [Service] started when the Sentinel Engine detects the DDU trigger. It runs the
 * covert session with no visible UI of its own (the calculator stays exactly as it was). Android
 * forces a persistent notification for any foreground service, AND always attributes it to the
 * posting app ("Calculator") — the app name in the notification header cannot be spoofed. So the
 * most discreet option is a plain, boring notification consistent with the Calculator decoy,
 * hidden from the lock screen (VISIBILITY_SECRET), silent, and at the bottom of the shade
 * (IMPORTANCE_MIN).
 *
 * Lifecycle:
 *  - DDU trigger -> [start]. First trigger begins a session (new [currentSessionId]); a repeat
 *    trigger while already running just re-posts the notification (in case it was dismissed).
 *  - [ACTION_STOP] -> ends the session and returns to Phase 0. Reachable in-app via the calculator
 *    stand-down code (same process, so the non-exported service can be stopped this way).
 *
 * Phase 3 will start sensor + audio collectors from [startSession] and upgrade the
 * foreground-service type to microphone|location. For now it uses the permission-free `dataSync`
 * type so Phase 2 runs without runtime-permission prompts beyond notifications.
 */
class GhostStateService : Service() {

    private var sensorCollector: SensorCollector? = null
    private var locationCollector: LocationCollector? = null
    private var audioCollector: AudioBufferCollector? = null

    // Phase 4-6 on-device AI (Decision 2). Fires the Phase 7 handoff once per session.
    private var classifier: EmergencyClassifier? = null
    private var emergencyHandled = false

    private val handler = Handler(Looper.getMainLooper())
    private val snapshotRunnable = object : Runnable {
        override fun run() {
            logSnapshot()
            handler.postDelayed(this, SNAPSHOT_INTERVAL_MS)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSession()
            return START_NOT_STICKY
        }
        if (!isRunning) {
            startSession()
        } else {
            // Repeat trigger: re-post the notification in case the user swiped it away.
            enterForeground()
            Log.i(TAG, "Ghost State already active — refreshed. SessionID=$currentSessionId")
        }
        return START_STICKY
    }

    private fun startSession() {
        val sessionId = "SESS-" + UUID.randomUUID().toString().take(8).uppercase()
        currentSessionId = sessionId
        isRunning = true
        enterForeground()

        // Accelerometer + gyroscope need no runtime permission.
        sensorCollector = SensorCollector(this).apply { start() }

        // Mic + GPS require permission granted at setup; skip gracefully if not (the FGS type is
        // also chosen from granted permissions in currentForegroundType()).
        val micStarted = if (hasPermission(Manifest.permission.RECORD_AUDIO)) {
            AudioBufferCollector().let { if (it.start()) { audioCollector = it; true } else false }
        } else false
        val gpsStarted = if (hasLocationPermission()) {
            LocationCollector(this).also { it.start(); locationCollector = it }; true
        } else false

        emergencyHandled = false
        classifier = try {
            EmergencyClassifier(this)
        } catch (t: Throwable) {
            Log.e(TAG, "Failed to load emergency model — AI disabled this session.", t)
            null
        }

        startSnapshotLogging()
        Log.i(TAG, "Ghost State ACTIVATED — SessionID=$sessionId (mic=$micStarted, gps=$gpsStarted, ai=${classifier != null})")
    }

    private fun stopSession() {
        Log.i(TAG, "Ghost State DEACTIVATED — SessionID=$currentSessionId")
        stopSnapshotLogging()
        sensorCollector?.stop(); sensorCollector = null
        locationCollector?.stop(); locationCollector = null
        audioCollector?.stop(); audioCollector = null
        classifier?.close(); classifier = null
        emergencyHandled = false
        isRunning = false
        currentSessionId = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun enterForeground() {
        val notification = buildNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, currentForegroundType())
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    /** FGS type derived from whichever sensitive permissions are granted (falls back to dataSync). */
    private fun currentForegroundType(): Int {
        var type = 0
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
            hasPermission(Manifest.permission.RECORD_AUDIO)
        ) {
            type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && hasLocationPermission()) {
            type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
        }
        return if (type == 0) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else type
    }

    private fun hasPermission(permission: String): Boolean =
        checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    private fun hasLocationPermission(): Boolean =
        hasPermission(Manifest.permission.ACCESS_FINE_LOCATION) ||
            hasPermission(Manifest.permission.ACCESS_COARSE_LOCATION)

    private fun startSnapshotLogging() {
        handler.postDelayed(snapshotRunnable, SNAPSHOT_INTERVAL_MS)
    }

    private fun stopSnapshotLogging() {
        handler.removeCallbacks(snapshotRunnable)
    }

    /** Builds the Phase 3 -> Phase 4 handoff packet (the Aarush -> Lipika contract). */
    private fun buildSensorPacket(): SensorPacket? {
        val sessionId = currentSessionId ?: return null
        val sensors = sensorCollector
        return SensorPacket(
            sessionId = sessionId,
            timestampMs = System.currentTimeMillis(),
            latestAccel = sensors?.latestAccel,
            latestGyro = sensors?.latestGyro,
            latestLocation = locationCollector?.latest,
            accelSamples = sensors?.accelSamples() ?: emptyList(),
            gyroSamples = sensors?.gyroSamples() ?: emptyList(),
            audioRmsEnergy = audioCollector?.lastRmsEnergy ?: 0.0,
            audioBufferedMs = audioCollector?.bufferedMs ?: 0L
        )
    }

    private fun logSnapshot() {
        val packet = buildSensorPacket() ?: return
        Log.i(
            TAG,
            "snapshot accel=${packet.latestAccel} gyro=${packet.latestGyro} " +
                "loc=${packet.latestLocation} audioRms=${"%.1f".format(packet.audioRmsEnergy)} " +
                "audioMs=${packet.audioBufferedMs} accelN=${packet.accelSamples.size} " +
                "gyroN=${packet.gyroSamples.size}"
        )
        runInference(packet)
    }

    /** Phase 5-6: on-device inference on each snapshot. Fires the Phase 7 handoff once per session. */
    private fun runInference(packet: SensorPacket) {
        val result = classifier?.classify(packet) ?: return
        Log.i(
            TAG,
            "AI prediction=${result.prediction} confidence=${"%.4f".format(result.confidence)} " +
                "emergency=${result.emergencyStatus} features=${result.features}"
        )
        if (result.emergencyStatus && !emergencyHandled) {
            emergencyHandled = true
            Log.w(
                TAG,
                "EMERGENCY CONFIRMED (confidence ${"%.4f".format(result.confidence)} >= " +
                    "${result.decisionThreshold}) — Phase 7 handoff point. SessionID=${result.sessionId}"
            )
            // TODO(integration, Decision 1): hand off to the security pipeline once Gagan's module
            // is merged into the app — SecurityOrchestrator.processEmergencyTrigger(
            //   sessionId, timestamp, gps, featureVector, aiResult, audioBytes, carrierImages).
            // For now the confirmed emergency is logged only.
        }
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "General",
            NotificationManager.IMPORTANCE_MIN
        ).apply {
            setShowBadge(false)
            setSound(null, null)
            enableVibration(false)
            enableLights(false)
            lockscreenVisibility = Notification.VISIBILITY_SECRET
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(com.incog.mobileclient.R.drawable.ic_calc_notification)
            .setContentTitle("Calculator")
            .setContentText("Running")
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_SECRET)
            .setOngoing(true)
            .setShowWhen(false)
            .setSilent(true)
            // Deliberately no content intent — tapping does nothing (avoids revealing the app).
            .build()

    companion object {
        private const val TAG = "GhostState"
        private const val CHANNEL_ID = "general_background"
        private const val NOTIFICATION_ID = 1001
        private const val SNAPSHOT_INTERVAL_MS = 2000L

        const val ACTION_STOP = "com.incog.mobileclient.ghost.action.STOP"

        /** True while a covert session is active. */
        @Volatile
        var isRunning: Boolean = false
            private set

        /** The active SensorSessionID, or null when no session is running. */
        @Volatile
        var currentSessionId: String? = null
            private set

        /** Start (or refresh) Ghost State from an always-alive component (e.g. the Sentinel Engine). */
        fun start(context: Context) {
            context.startForegroundService(Intent(context, GhostStateService::class.java))
        }

        /** Stop Ghost State (in-process only — the service is not exported). */
        fun stop(context: Context) {
            context.startService(
                Intent(context, GhostStateService::class.java).setAction(ACTION_STOP)
            )
        }
    }
}
