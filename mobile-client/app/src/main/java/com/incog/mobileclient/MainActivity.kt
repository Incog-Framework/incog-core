package com.incog.mobileclient

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.incog.mobileclient.calculator.CalculatorScreen
import com.incog.mobileclient.config.IncogConfig
import com.incog.mobileclient.setup.SetupScreen
import com.incog.mobileclient.ui.theme.CalculatorTheme

class MainActivity : ComponentActivity() {

    // Registered as a field so it's ready before the activity is started (required by the API).
    private val requestPermissions =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { /* no-op */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        // One-time setup: request the runtime permissions Ghost State needs. Without them the OS
        // suppresses the FGS notification (POST_NOTIFICATIONS) and blocks mic/GPS capture.
        requestSetupPermissions()

        val config = IncogConfig(this)
        setContent {
            CalculatorTheme {
                var settings by remember { mutableStateOf(config.load()) }
                // Show setup automatically until the owner has completed first-run configuration,
                // and on demand when they type the concealed settings code on the calculator.
                var showSetup by remember { mutableStateOf(!settings.setupComplete) }

                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    if (showSetup) {
                        SetupScreen(
                            modifier = Modifier.padding(innerPadding),
                            initial = settings,
                            isFirstRun = !settings.setupComplete,
                            onSave = { updated ->
                                config.save(updated)
                                settings = config.load()
                                showSetup = false
                            },
                            // No way to back out of first-run setup; afterwards, Cancel returns to the calc.
                            onCancel = if (settings.setupComplete) ({ showSetup = false }) else null,
                        )
                    } else {
                        CalculatorScreen(
                            modifier = Modifier.padding(innerPadding),
                            codes = settings.codes,
                            onOpenSettings = { showSetup = true },
                        )
                    }
                }
            }
        }
    }

    private fun requestSetupPermissions() {
        val needed = buildList {
            add(Manifest.permission.RECORD_AUDIO)
            add(Manifest.permission.ACCESS_FINE_LOCATION)
            add(Manifest.permission.ACCESS_COARSE_LOCATION)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                add(Manifest.permission.POST_NOTIFICATIONS)
            }
        }.filter {
            checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
        }
        if (needed.isNotEmpty()) {
            requestPermissions.launch(needed.toTypedArray())
        }
    }
}
