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
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.incog.mobileclient.config.Contact
import com.incog.mobileclient.config.IncogConfig
import com.incog.mobileclient.config.IncogSettings
import com.incog.mobileclient.config.SecretCodes

/**
 * Owner-only setup, shown automatically on first run and reachable later via the concealed settings
 * code. Configures the trusted contacts (all are texted on an emergency) and the concealed codes so
 * nothing ships hardcoded.
 */
private class ContactRow(name: String, phone: String) {
    var name by mutableStateOf(name)
    var phone by mutableStateOf(phone)
}

@Composable
fun SetupScreen(
    initial: IncogSettings,
    isFirstRun: Boolean,
    onSave: (IncogSettings) -> Unit,
    modifier: Modifier = Modifier,
    onCancel: (() -> Unit)? = null,
) {
    val rows = remember {
        mutableStateListOf<ContactRow>().apply {
            val start = initial.contacts.ifEmpty { listOf(Contact()) }
            start.forEach { add(ContactRow(it.name, it.phone)) }
        }
    }
    var unlockCode by remember { mutableStateOf(initial.codes.unlock) }
    var standDownCode by remember { mutableStateOf(initial.codes.standDown) }
    var settingsCode by remember { mutableStateOf(initial.codes.settings) }
    var error by remember { mutableStateOf<String?>(null) }
    val focusManager = LocalFocusManager.current

    Column(
        modifier = modifier
            .fillMaxSize()
            .imePadding()
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
            text = "Add the people to alert in an emergency and choose your private codes. Every " +
                "contact below is texted your location when a trigger fires.",
            style = MaterialTheme.typography.bodyMedium,
        )

        SectionLabel("Trusted contacts")
        rows.forEachIndexed { index, row ->
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("Contact ${index + 1}", style = MaterialTheme.typography.titleSmall)
                    if (rows.size > 1) {
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = { rows.removeAt(index) }) { Text("Remove") }
                    }
                }
                OutlinedTextField(
                    value = row.name,
                    onValueChange = { row.name = it },
                    label = { Text("Name (optional)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = row.phone,
                    onValueChange = { row.phone = it },
                    label = { Text("Phone number") },
                    supportingText = { Text("With country code, e.g. +919876543210") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
        if (rows.size < IncogConfig.MAX_CONTACTS) {
            OutlinedButton(onClick = { rows.add(ContactRow("", "")) }) {
                Text("+ Add another contact")
            }
        }

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
                    val contacts = rows.map { Contact(it.name.trim(), it.phone.trim()) }
                    val validation = validate(contacts, unlockCode, standDownCode, settingsCode)
                    if (validation != null) {
                        error = validation
                    } else {
                        onSave(
                            IncogSettings(
                                contacts = contacts.filter { it.phone.isNotBlank() },
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
            imeAction = androidx.compose.ui.text.input.ImeAction.Done,
        ),
        keyboardActions = KeyboardActions(onDone = { focusManager.clearFocus() }),
        modifier = Modifier.fillMaxWidth(),
    )
}

/** Returns an error message, or null if everything is valid. Package-visible for unit testing. */
internal fun validate(
    contacts: List<Contact>,
    unlock: String,
    standDown: String,
    settings: String,
): String? {
    val phones = contacts.map { it.phone.trim() }.filter { it.isNotEmpty() }
    if (phones.isEmpty()) {
        return "Add at least one contact with a phone number."
    }
    if (phones.any { !it.matches(PHONE_REGEX) }) {
        return "Each phone number must be 7–15 digits, with an optional leading +."
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
