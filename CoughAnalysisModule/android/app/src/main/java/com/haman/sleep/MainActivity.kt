package com.haman.sleep

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.haman.sleep.service.MonitoringService
import com.haman.sleep.ui.*

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { HamanTheme { HamanApp() } }
    }
}

private data class Tab(val route: String, val label: String)

private val TABS = listOf(
    Tab("home", "Tonight"),
    Tab("history", "History"),
    Tab("settings", "Settings"),
)

@Composable
private fun HamanApp() {
    val context = LocalContext.current
    val vm: MainViewModel = viewModel()
    val nav = rememberNavController()

    var micGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    var batteryExempt by remember { mutableStateOf(isBatteryExempt(context)) }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { result ->
        micGranted = result[Manifest.permission.RECORD_AUDIO] ?: micGranted
        if (micGranted) MonitoringService.start(context)
    }

    val batteryLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { batteryExempt = isBatteryExempt(context) }

    fun requestAndStart() {
        val needed = buildList {
            add(Manifest.permission.RECORD_AUDIO)
            // Without POST_NOTIFICATIONS on API 33+ the foreground-service notification
            // is suppressed, and a foreground service the user cannot see is exactly
            // what the platform kills first.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                add(Manifest.permission.POST_NOTIFICATIONS)
            }
        }.filter {
            ContextCompat.checkSelfPermission(context, it) != PackageManager.PERMISSION_GRANTED
        }
        if (needed.isEmpty()) MonitoringService.start(context)
        else permissionLauncher.launch(needed.toTypedArray())
    }

    val backStack by nav.currentBackStackEntryAsState()
    val currentRoute = backStack?.destination?.route

    Scaffold(
        bottomBar = {
            if (currentRoute in TABS.map { it.route }) {
                NavigationBar {
                    TABS.forEach { tab ->
                        NavigationBarItem(
                            selected = currentRoute == tab.route,
                            onClick = {
                                nav.navigate(tab.route) {
                                    popUpTo("home"); launchSingleTop = true
                                }
                            },
                            icon = {},
                            label = { Text(tab.label) },
                        )
                    }
                }
            }
        }
    ) { pad ->
        NavHost(nav, startDestination = "home", modifier = Modifier.padding(pad)) {
            composable("home") {
                HomeScreen(
                    vm = vm,
                    onStart = { requestAndStart() },
                    onStop = { MonitoringService.stop(context) },
                    batteryExempt = batteryExempt,
                    onRequestBatteryExemption = {
                        batteryLauncher.launch(batteryExemptionIntent(context.packageName))
                    },
                )
            }
            composable("history") {
                HistoryScreen(vm) { id -> nav.navigate("session/$id") }
            }
            composable("settings") { SettingsScreen(vm) }
            composable("session/{id}") { entry ->
                val id = entry.arguments?.getString("id")?.toLongOrNull() ?: return@composable
                SessionDetailScreen(vm, id) { nav.popBackStack() }
            }
        }
    }
}

private fun isBatteryExempt(context: android.content.Context): Boolean {
    val pm = context.getSystemService(PowerManager::class.java) ?: return true
    return pm.isIgnoringBatteryOptimizations(context.packageName)
}

@Suppress("BatteryLife") // sideloaded sleep monitor: an 8-hour session is the feature
private fun batteryExemptionIntent(packageName: String) =
    Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
        .setData(Uri.parse("package:$packageName"))
