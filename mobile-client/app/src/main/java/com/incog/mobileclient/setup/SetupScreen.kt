package com.incog.mobileclient.setup

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.incog.mobileclient.alert.ContactAlerter
import com.incog.mobileclient.config.Contact
import com.incog.mobileclient.config.DEFAULT_GRACE_SECONDS
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
    var ownerName by remember { mutableStateOf(initial.ownerName) }
    var unlockCode by remember { mutableStateOf(initial.codes.unlock) }
    var standDownCode by remember { mutableStateOf(initial.codes.standDown) }
    var settingsCode by remember { mutableStateOf(initial.codes.settings) }
    var captureMode by remember { mutableStateOf(initial.captureMode) }
    var hapticCues by remember { mutableStateOf(initial.hapticCues) }
    var graceSecondsText by remember { mutableStateOf(initial.graceSeconds.toString()) }
    var error by remember { mutableStateOf<String?>(null) }
    val focusManager = LocalFocusManager.current

    val context = LocalContext.current
    var smsGranted by remember { mutableStateOf(ContactAlerter.hasSmsPermission(context)) }
    var testResult by remember { mutableStateOf<String?>(null) }
    val smsPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> smsGranted = granted }

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

        SectionLabel("Your details")
        OutlinedTextField(
            value = ownerName,
            onValueChange = { ownerName = it },
            label = { Text("Your name") },
            supportingText = { Text("Shown to your contacts: \"<name> may be in danger\"") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
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

        // SMS permission is the usual reason alerts don't send on a fresh (sideloaded) install.
        // Surface its status here so a user can grant it and confirm delivery with a test text,
        // instead of the alert failing silently in a real emergency.
        if (!smsGranted) {
            Text(
                "⚠ SMS permission is OFF — emergency texts will NOT be sent. Grant it below.",
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium,
            )
            Button(onClick = { smsPermissionLauncher.launch(Manifest.permission.SEND_SMS) }) {
                Text("Grant SMS permission")
            }
            Text(
                "If nothing happens, enable it manually: Settings → Apps → Calculator → " +
                    "Permissions → SMS → Allow.",
                style = MaterialTheme.typography.bodySmall,
            )
        } else {
            OutlinedButton(
                onClick = {
                    val contacts = rows.map { Contact(it.name.trim(), it.phone.trim()) }
                        .filter { it.phone.isNotBlank() }
                    testResult = if (contacts.isEmpty()) {
                        "Add a contact with a phone number first."
                    } else {
                        val sent = ContactAlerter.sendTest(context, contacts, ownerName.trim())
                            .count { it.smsSent }
                        "Test alert sent to $sent/${contacts.size} contact(s). Check their phone(s)."
                    }
                },
            ) { Text("Send test alert") }
            if (testResult != null) {
                Text(testResult!!, style = MaterialTheme.typography.bodySmall)
            }
        }

        // A silent trigger means an accidental one is invisible, so a false alarm can run all the
        // way to texting contacts unnoticed. These two settings are the owner's defence: feel that
        // a session started, and get a window to cancel before anyone is contacted.
        SectionLabel("False-alarm safeguards")
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text("Vibrate on trigger", style = MaterialTheme.typography.bodyLarge)
                Text(
                    "One short buzz when a session starts, and another when it stops — so you " +
                        "notice an accidental trigger even with the phone in your pocket. Turn off " +
                        "only if the trigger must be completely imperceptible.",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Switch(checked = hapticCues, onCheckedChange = { hapticCues = it })
        }
        OutlinedTextField(
            value = graceSecondsText,
            onValueChange = { graceSecondsText = it.filter(Char::isDigit).take(2) },
            label = { Text("Alert delay (seconds)") },
            supportingText = {
                Text(
                    "Once an emergency is detected, your contacts are texted after this delay — " +
                        "type your stand-down code within it to cancel a false alarm. The alert " +
                        "always sends if you do nothing. 0 texts immediately; max " +
                        "${IncogConfig.MAX_GRACE_SECONDS}.",
                )
            },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth(),
        )

        SectionLabel("Concealed codes (digits only, typed on the calculator then =)")
        CodeField("Unlock code — opens Accessibility settings", unlockCode) { unlockCode = it }
        CodeField("Stand-down code — stops an active session", standDownCode) { standDownCode = it }
        CodeField("Settings code — reopens this screen", settingsCode) { settingsCode = it }

        SectionLabel("Developer")
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text("Capture mode", style = MaterialTheme.typography.bodyLarge)
                Text(
                    "Save each session's sensor stream to a file for model-training captures. " +
                        "Leave off for normal use.",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Switch(checked = captureMode, onCheckedChange = { captureMode = it })
        }

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
                                ownerName = ownerName.trim(),
                                contacts = contacts.filter { it.phone.isNotBlank() },
                                codes = SecretCodes(
                                    unlock = unlockCode.trim(),
                                    standDown = standDownCode.trim(),
                                    settings = settingsCode.trim(),
                                ),
                                setupComplete = true,
                                captureMode = captureMode,
                                hapticCues = hapticCues,
                                graceSeconds = IncogConfig.clampGraceSeconds(
                                    graceSecondsText.toIntOrNull() ?: DEFAULT_GRACE_SECONDS
                                ),
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
