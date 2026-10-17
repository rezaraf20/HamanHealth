package com.haman.sleep

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.haman.sleep.ui.DiagnosticsScreen
import com.haman.sleep.ui.HamanTheme
import com.haman.sleep.ui.MainViewModel

/**
 * Microphone diagnostics: tests every microphone route on this phone and keeps the one
 * where coughs are recognised best. Native because it has no web equivalent yet; opened
 * by long-pressing the app icon (res/xml/shortcuts.xml).
 */
class DiagnosticsActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            HamanTheme {
                val vm: MainViewModel = viewModel()
                var micGranted by remember {
                    mutableStateOf(
                        ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
                            PackageManager.PERMISSION_GRANTED
                    )
                }
                val askMic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
                    micGranted = it
                }
                DiagnosticsScreen(
                    vm = vm,
                    micGranted = micGranted,
                    onRequestMic = { askMic.launch(Manifest.permission.RECORD_AUDIO) },
                    onBack = { finish() },
                )
            }
        }
    }
}
