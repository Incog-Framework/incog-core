package com.incog.mobileclient.setup

import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.incog.mobileclient.config.IncogSettings
import com.incog.mobileclient.config.SecretCodes

/**
 * Owner-only setup, shown automatically on first run and reachable later via the concealed settings
 * code. Configures the emergency contact and the three concealed codes so nothing ships hardcoded.
 *
 * Reached only by the owner (first run, or the settings code), so labels are plain rather than
 * disguised — a future stealth pass could cover this screen as "Calculator preferences" if desired.
 */
@Composable
fun SetupScreen(
    initial: IncogSettings,
    isFirstRun: Boolean,
    onSave: (IncogSettings) -> Unit,
    modifier: Modifier = Modifier,
    onCancel: (() -> Unit)? = null,
) {
    var contactName by remember { mutableStateOf(initial.contactName) }
    var contactPhone by remember { mutableStateOf(initial.contactPhone) }
    var unlockCode by remember { mutableStateOf(initial.codes.unlock) }
    var standDownCode by remember { mutableStateOf(initial.codes.standDown) }
    var settingsCode by remember { mutableStateOf(initial.codes.settings) }
    var error by remember { mutableStateOf<String?>(null) }
    val focusManager = LocalFocusManager.current

    Column(
        modifier = modifier
            .fillMaxSize()
            // imePadding shrinks the viewport to sit above the keyboard, so the scroll range covers
            // the lower fields and the focused one is auto-scrolled into view instead of being hidden.
            .imePadding()
            // Tapping empty space dismisses the keyboard (drags still scroll — tap != drag).
            .pointerInput(Unit) { detectTapGestures(onTap = { focusManager.clearFocus() }) }
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            text = if (isFirstRun) "Set up Incog" else "Incog settings",
            style = MaterialTheme.typography.headlineSmall,
        )
        Text(
            text = "Configure your trusted contact and your private codes. Choose codes only you " +
                "know — they replace the defaults.",
            style = MaterialTheme.typography.bodyMedium,
        )

        SectionLabel("Trusted contact")
        OutlinedTextField(
            value = contactName,
            onValueChange = { contactName = it },
            label = { Text("Name (optional)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = contactPhone,
            onValueChange = { contactPhone = it },
            label = { Text("Phone number") },
            supportingText = { Text("With country code, e.g. +919876543210") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
            modifier = Modifier.fillMaxWidth(),
        )

        SectionLabel("Concealed codes (digits only, typed on the calculator then =)")
        CodeField("Unlock code — opens Accessibility settings", unlockCode) { unlockCode = it }
        CodeField("Stand-down code — stops an active session", standDownCode) { standDownCode = it }
        CodeField("Settings code — reopens this screen", settingsCode) { settingsCode = it }

        if (error != null) {
            Text(
                text = error!!,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium,
            )
        }

        Spacer(Modifier.height(4.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            if (onCancel != null) {
                OutlinedButton(onClick = onCancel, modifier = Modifier.weight(1f)) { Text("Cancel") }
            }
            Button(
                onClick = {
                    val validation = validate(contactPhone, unlockCode, standDownCode, settingsCode)
                    if (validation != null) {
                        error = validation
                    } else {
                        onSave(
                            IncogSettings(
                                contactName = contactName.trim(),
                                contactPhone = contactPhone.trim(),
                                codes = SecretCodes(
                                    unlock = unlockCode.trim(),
                                    standDown = standDownCode.trim(),
                                    settings = settingsCode.trim(),
                                ),
                                setupComplete = true,
                            )
                        )
                    }
                },
                modifier = Modifier.weight(1f),
            ) {
                Text(if (isFirstRun) "Finish setup" else "Save")
            }
        }
    }
}

@Composable
private fun SectionLabel(text: String) {
    Spacer(Modifier.height(8.dp))
    Text(text = text, style = MaterialTheme.typography.titleSmall)
}

@Composable
private fun CodeField(label: String, value: String, onChange: (String) -> Unit) {
    val focusManager = LocalFocusManager.current
    OutlinedTextField(
        value = value,
        // Digits only: the codes are entered on the calculator keypad, which produces digits.
        onValueChange = { input -> onChange(input.filter(Char::isDigit)) },
        label = { Text(label) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(
            keyboardType = KeyboardType.NumberPassword,
            imeAction = ImeAction.Done,
        ),
        keyboardActions = KeyboardActions(onDone = { focusManager.clearFocus() }),
        modifier = Modifier.fillMaxWidth(),
    )
}

/** Returns an error message, or null if everything is valid. Package-visible for unit testing. */
internal fun validate(
    phone: String,
    unlock: String,
    standDown: String,
    settings: String,
): String? {
    if (!phone.trim().matches(PHONE_REGEX)) {
        return "Enter a valid phone number (7–15 digits, optional leading +)."
    }
    val codes = listOf(unlock.trim(), standDown.trim(), settings.trim())
    if (codes.any { !it.matches(CODE_REGEX) }) {
        // A leading zero can't be typed on the calculator (leading zeros collapse), so it's barred.
        return "Each code must be 4–12 digits and cannot start with 0."
    }
    if (codes.toSet().size != codes.size) {
        return "The three codes must all be different."
    }
    return null
}

private val PHONE_REGEX = Regex("^\\+?[0-9]{7,15}$")
private val CODE_REGEX = Regex("^[1-9][0-9]{3,11}$")
