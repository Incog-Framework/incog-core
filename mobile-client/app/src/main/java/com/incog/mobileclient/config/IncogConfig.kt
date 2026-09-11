package com.incog.mobileclient.config

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

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

/** One trusted contact the app alerts on an emergency. */
data class Contact(
    val name: String = "",
    val phone: String = "",
)

/** Everything the owner configures once, persisted across launches. */
data class IncogSettings(
    /** The app owner's own name, shown to contacts in the alert ("<name> may be in danger"). */
    val ownerName: String = "",
    /** The user's trusted contacts (0..[IncogConfig.MAX_CONTACTS]); all are texted on an emergency. */
    val contacts: List<Contact> = emptyList(),
    val codes: SecretCodes = SecretCodes(),
    /** False until the owner completes first-run setup; drives whether setup is shown on launch. */
    val setupComplete: Boolean = false,
    /**
     * Developer/data-collection mode: when true, each Ghost State session writes its SensorPacket
     * stream to a JSON file on disk (for model-training captures). OFF by default — the production
     * app deliberately persists nothing; this is opt-in tooling, not a shipping feature.
     */
    val captureMode: Boolean = false,
)

/**
 * Thin SharedPreferences wrapper for [IncogSettings]. Kept deliberately boring and synchronous —
 * the payload is a handful of short strings read once at launch and on save.
 *
 * Contacts are stored as a count plus indexed keys (`contact_name_0`, `contact_phone_0`, …) so no
 * JSON/serialization dependency is needed. A legacy single-contact install (old `contact_name` /
 * `contact_phone` keys) is migrated to a one-element list on read.
 *
 * Stored in EncryptedSharedPreferences (values + keys encrypted via a hardware-Keystore master key),
 * so the trusted contacts and access codes are unreadable even on a rooted device or from a backup.
 * A pre-encryption plaintext install is migrated into the encrypted store once, then wiped.
 */
class IncogConfig(context: Context) {

    private val prefs: SharedPreferences = createSecurePrefs(context).also { migrateFromLegacy(context, it) }

    fun load(): IncogSettings = IncogSettings(
        ownerName = prefs.getString(KEY_OWNER_NAME, "").orEmpty(),
        contacts = loadContacts(),
        codes = SecretCodes(
            unlock = prefs.getString(KEY_UNLOCK, DEFAULT.unlock).orEmpty().ifBlank { DEFAULT.unlock },
            standDown = prefs.getString(KEY_STANDDOWN, DEFAULT.standDown).orEmpty().ifBlank { DEFAULT.standDown },
            settings = prefs.getString(KEY_SETTINGS, DEFAULT.settings).orEmpty().ifBlank { DEFAULT.settings },
        ),
        setupComplete = prefs.getBoolean(KEY_SETUP_COMPLETE, false),
        captureMode = prefs.getBoolean(KEY_CAPTURE_MODE, false),
    )

    private fun loadContacts(): List<Contact> {
        if (!prefs.contains(KEY_CONTACT_COUNT)) {
            // Legacy migration: a single-contact install stored contact_name / contact_phone.
            val legacyPhone = prefs.getString(LEGACY_KEY_PHONE, "").orEmpty()
            if (legacyPhone.isNotBlank()) {
                return listOf(Contact(prefs.getString(LEGACY_KEY_NAME, "").orEmpty(), legacyPhone))
            }
            return emptyList()
        }
        val count = prefs.getInt(KEY_CONTACT_COUNT, 0)
        return (0 until count).map { i ->
            Contact(
                name = prefs.getString("$KEY_CONTACT_NAME_PREFIX$i", "").orEmpty(),
                phone = prefs.getString("$KEY_CONTACT_PHONE_PREFIX$i", "").orEmpty(),
            )
        }
    }

    /** Persists the settings and marks setup complete. */
    fun save(settings: IncogSettings) {
        // Keep only contacts with a non-blank phone, capped at MAX_CONTACTS.
        val contacts = settings.contacts
            .map { Contact(it.name.trim(), it.phone.trim()) }
            .filter { it.phone.isNotBlank() }
            .take(MAX_CONTACTS)

        val editor = prefs.edit()
            .putString(KEY_OWNER_NAME, settings.ownerName.trim())
            .putString(KEY_UNLOCK, settings.codes.unlock.trim())
            .putString(KEY_STANDDOWN, settings.codes.standDown.trim())
            .putString(KEY_SETTINGS, settings.codes.settings.trim())
            .putBoolean(KEY_SETUP_COMPLETE, true)
            .putBoolean(KEY_CAPTURE_MODE, settings.captureMode)
            // Drop the legacy single-contact keys now that we own an indexed list.
            .remove(LEGACY_KEY_NAME)
            .remove(LEGACY_KEY_PHONE)

        // Clear any previously-stored contact slots before writing the current set.
        val previous = prefs.getInt(KEY_CONTACT_COUNT, 0)
        for (i in 0 until maxOf(previous, MAX_CONTACTS)) {
            editor.remove("$KEY_CONTACT_NAME_PREFIX$i").remove("$KEY_CONTACT_PHONE_PREFIX$i")
        }
        editor.putInt(KEY_CONTACT_COUNT, contacts.size)
        contacts.forEachIndexed { i, c ->
            editor.putString("$KEY_CONTACT_NAME_PREFIX$i", c.name)
            editor.putString("$KEY_CONTACT_PHONE_PREFIX$i", c.phone)
        }
        editor.apply()
    }

    /** Encrypted prefs backed by a hardware-Keystore master key; falls back to plaintext on failure. */
    private fun createSecurePrefs(context: Context): SharedPreferences = try {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            PREFS_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    } catch (t: Throwable) {
        // Encrypted store unavailable (e.g. a corrupted keystore) — fall back to plaintext so the app
        // still functions rather than crashing on launch. Rare; logged for diagnosis.
        Log.e(TAG, "EncryptedSharedPreferences unavailable — falling back to plaintext prefs.", t)
        context.getSharedPreferences(FALLBACK_PREFS_NAME, Context.MODE_PRIVATE)
    }

    /**
     * One-time migration: copy a pre-encryption plaintext config (the old "incog_config" file) into
     * the encrypted store and wipe it, so existing installs keep their setup after upgrading. No-op
     * once the encrypted store is populated, or on a fresh install.
     */
    private fun migrateFromLegacy(context: Context, secure: SharedPreferences) {
        if (secure.contains(KEY_SETUP_COMPLETE)) return
        val legacy = context.getSharedPreferences(LEGACY_PREFS_NAME, Context.MODE_PRIVATE)
        if (legacy.all.isEmpty()) return
        val editor = secure.edit()
        for ((k, v) in legacy.all) when (v) {
            is String -> editor.putString(k, v)
            is Boolean -> editor.putBoolean(k, v)
            is Int -> editor.putInt(k, v)
            is Long -> editor.putLong(k, v)
            is Float -> editor.putFloat(k, v)
            else -> {}
        }
        editor.apply()
        legacy.edit().clear().apply()
        Log.i(TAG, "Migrated ${legacy.all.size} legacy config entries into the encrypted store.")
    }

    companion object {
        /** Upper bound on trusted contacts, to keep the SMS fan-out and the payload sane. */
        const val MAX_CONTACTS = 5

        private const val TAG = "IncogConfig"
        private const val PREFS_NAME = "incog_config_secure"
        private const val LEGACY_PREFS_NAME = "incog_config"
        private const val FALLBACK_PREFS_NAME = "incog_config_plain"
        private const val KEY_OWNER_NAME = "owner_name"
        private const val KEY_CONTACT_COUNT = "contact_count"
        private const val KEY_CONTACT_NAME_PREFIX = "contact_name_"
        private const val KEY_CONTACT_PHONE_PREFIX = "contact_phone_"
        private const val LEGACY_KEY_NAME = "contact_name"
        private const val LEGACY_KEY_PHONE = "contact_phone"
        private const val KEY_UNLOCK = "code_unlock"
        private const val KEY_STANDDOWN = "code_standdown"
        private const val KEY_SETTINGS = "code_settings"
        private const val KEY_SETUP_COMPLETE = "setup_complete"
        private const val KEY_CAPTURE_MODE = "capture_mode"
        private val DEFAULT = SecretCodes()
    }
}
