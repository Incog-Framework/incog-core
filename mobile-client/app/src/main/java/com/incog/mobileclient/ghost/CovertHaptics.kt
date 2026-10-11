package com.incog.mobileclient.ghost

import android.content.Context
import android.media.AudioAttributes
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log

/**
 * The one perceptible signal Ghost State gives the owner: a single short tick when a session arms,
 * and another when it stands down. It exists because the DDU trigger is otherwise completely
 * silent — an accidental activation (a volume press through a pocket) was previously undetectable
 * by the owner, so a false alarm could run all the way to texting their contacts without them ever
 * knowing a session had started.
 *
 * Deliberately NOT routed through the Ghost State notification, for two reasons:
 *  1. The notification channel is [android.app.NotificationManager.IMPORTANCE_MIN], and a MIN
 *     channel cannot vibrate at all. Vibration needs IMPORTANCE_DEFAULT, which would also make the
 *     notification audible, badged and heads-up — destroying the Calculator disguise.
 *  2. Channel settings are immutable after creation, so flipping `enableVibration(true)` would be
 *     silently ignored on every device that already has the channel (i.e. every existing install).
 *
 * Firing the vibrator directly keeps the channel exactly as covert as it was and gives full control
 * over the pattern. The pattern matters: one ~60 ms tick is indistinguishable from any ordinary
 * notification buzz, so it stays deniable to a bystander. A longer or repeating pattern would read
 * as "something is happening" and is exactly what this must not do.
 */
internal object CovertHaptics {

    /**
     * A single short tick. Short enough to be deniable, long enough to feel through a pocket on the
     * test hardware (OnePlus 11R), where 60 ms at default amplitude was reported as too faint.
     */
    private const val TICK_MS = 120L

    /**
     * Full strength. [VibrationEffect.DEFAULT_AMPLITUDE] defers to the system's vibration-intensity
     * setting, which on the test device made the cue barely perceptible — not good enough for a cue
     * whose entire job is to be noticed through a pocket.
     */
    private const val MAX_AMPLITUDE = 255

    /**
     * USAGE_ALARM so the cue survives silent mode and Do Not Disturb — a safety cue the owner cannot
     * feel is worthless, and DND suppresses notification-usage vibrations.
     */
    private val ATTRIBUTES: AudioAttributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_ALARM)
        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
        .build()

    /**
     * Fires the tick. Never throws and never blocks the caller: this sits on the emergency path, so
     * a missing or failing vibrator must not be able to break arming, standing down, or alerting.
     */
    fun tick(context: Context) {
        try {
            val vibrator = vibrator(context) ?: return
            if (!vibrator.hasVibrator()) return
            @Suppress("DEPRECATION") // The VibrationAttributes overload is API 33+; this covers 26+.
            vibrator.vibrate(strongTick(vibrator), ATTRIBUTES)
        } catch (t: Throwable) {
            Log.w(TAG, "Haptic cue failed — continuing without it.", t)
        }
    }

    /**
     * The strongest single tick the hardware can give, still one tick (a pattern would stop reading
     * as an ordinary notification buzz, which is what keeps this deniable).
     *
     * Not every motor supports amplitude control; where it doesn't, [VibrationEffect.createOneShot]
     * ignores the amplitude entirely, so fall back to the predefined heavy click, which the platform
     * maps to the strongest crisp effect that device has.
     */
    private fun strongTick(vibrator: Vibrator): VibrationEffect = when {
        vibrator.hasAmplitudeControl() -> VibrationEffect.createOneShot(TICK_MS, MAX_AMPLITUDE)
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q ->
            VibrationEffect.createPredefined(VibrationEffect.EFFECT_HEAVY_CLICK)
        else -> VibrationEffect.createOneShot(TICK_MS, VibrationEffect.DEFAULT_AMPLITUDE)
    }

    private fun vibrator(context: Context): Vibrator? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            context.getSystemService(VibratorManager::class.java)?.defaultVibrator
        } else {
            context.getSystemService(Vibrator::class.java)
        }

    private const val TAG = "CovertHaptics"
}
