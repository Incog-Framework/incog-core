package com.incog.mobileclient.config

import android.content.Context

/**
 * The owner-configurable concealed codes, typed on the calculator then "=".
 *
 * Defaults intentionally match the historical hardcoded values so the app (and the calculator
 * unit tests, which construct the ViewModel with no args) still behave before first-run setup
 * writes real, owner-only values. In normal use these are overwritten during setup — shipping the
 * defaults would mean anyone who read the repo knows the codes.
 */
data class SecretCodes(
    /** Opens the system Accessibility settings so the owner can enable the Sentinel Engine. */
    val unlock: String = "271828",
    /** Stops an active Ghost State session (cancels a false trigger). */
    val standDown: String = "314159",
    /** Opens this app's concealed setup screen. */
    val settings: String = "191919",
)

/** Everything the owner configures once, persisted across launches. */
data class IncogSettings(
    val contactName: String = "",
    val contactPhone: String = "",
    val codes: SecretCodes = SecretCodes(),
    /** False until the owner completes first-run setup; drives whether setup is shown on launch. */
    val setupComplete: Boolean = false,
)

/**
 * Thin SharedPreferences wrapper for [IncogSettings]. Kept deliberately boring and synchronous —
 * the payload is a handful of short strings read once at launch and on save.
 *
 * Note: this stores the emergency contact and the access codes in the app's private prefs. That is
 * adequate for the MVP; a hardened build would encrypt them at rest (e.g. EncryptedSharedPreferences)
 * so a rooted device can't read the trusted contact — tracked as a follow-up.
 */
class IncogConfig(context: Context) {

    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun load(): IncogSettings = IncogSettings(
        contactName = prefs.getString(KEY_CONTACT_NAME, "").orEmpty(),
        contactPhone = prefs.getString(KEY_CONTACT_PHONE, "").orEmpty(),
        codes = SecretCodes(
            unlock = prefs.getString(KEY_UNLOCK, DEFAULT.unlock).orEmpty().ifBlank { DEFAULT.unlock },
            standDown = prefs.getString(KEY_STANDDOWN, DEFAULT.standDown).orEmpty().ifBlank { DEFAULT.standDown },
            settings = prefs.getString(KEY_SETTINGS, DEFAULT.settings).orEmpty().ifBlank { DEFAULT.settings },
        ),
        setupComplete = prefs.getBoolean(KEY_SETUP_COMPLETE, false),
    )

    /** Persists the settings and marks setup complete. */
    fun save(settings: IncogSettings) {
        prefs.edit()
            .putString(KEY_CONTACT_NAME, settings.contactName.trim())
            .putString(KEY_CONTACT_PHONE, settings.contactPhone.trim())
            .putString(KEY_UNLOCK, settings.codes.unlock.trim())
            .putString(KEY_STANDDOWN, settings.codes.standDown.trim())
            .putString(KEY_SETTINGS, settings.codes.settings.trim())
            .putBoolean(KEY_SETUP_COMPLETE, true)
            .apply()
    }

    private companion object {
        const val PREFS_NAME = "incog_config"
        const val KEY_CONTACT_NAME = "contact_name"
        const val KEY_CONTACT_PHONE = "contact_phone"
        const val KEY_UNLOCK = "code_unlock"
        const val KEY_STANDDOWN = "code_standdown"
        const val KEY_SETTINGS = "code_settings"
        const val KEY_SETUP_COMPLETE = "setup_complete"
        val DEFAULT = SecretCodes()
    }
}
