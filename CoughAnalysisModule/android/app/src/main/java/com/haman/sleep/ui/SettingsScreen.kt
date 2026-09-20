package com.haman.sleep.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@Composable
fun SettingsScreen(vm: MainViewModel) {
    var sensitivity by remember { mutableFloatStateOf(vm.prefs.readSensitivity()) }
    var keepClips by remember { mutableStateOf(vm.prefs.readKeepClips()) }
    var retention by remember { mutableIntStateOf(vm.prefs.readRetentionDays()) }
    val labelCount by vm.attributionLabelCount.collectAsState()

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        Text("Settings", style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.SemiBold)

        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("Sensitivity", style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold)
            Text(
                // One dial instead of raw thresholds: "fewer misses vs fewer false
                // alarms" is a decision the user can actually make.
                when {
                    sensitivity < 0.34f -> "Conservative — fewer false alarms, will miss quiet events"
                    sensitivity < 0.67f -> "Balanced — the tuned default"
                    else -> "Sensitive — catches more, expect more false alarms"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Slider(
                value = sensitivity,
                onValueChange = { sensitivity = it },
                onValueChangeFinished = { vm.prefs.writeSensitivity(sensitivity) },
            )
            Text("Takes effect on the next session.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }

        HorizontalDivider()

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Keep audio clips", style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold)
                Text(
                    "Saves 2.5 seconds per detected event so you can check it and label " +
                        "it. Stored only on this phone. Turning this off makes " +
                        "personalisation impossible.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Switch(checked = keepClips, onCheckedChange = {
                keepClips = it; vm.prefs.writeKeepClips(it)
            })
        }

        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("Delete clips after $retention days",
                style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Slider(
                value = retention.toFloat(),
                onValueChange = { retention = it.toInt() },
                onValueChangeFinished = { vm.prefs.writeRetentionDays(retention) },
                valueRange = 1f..60f,
            )
            Text("Events and counts are kept forever; only the audio is deleted.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }

        HorizontalDivider()

        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("Personalisation", style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold)
            Text(
                "$labelCount labelled events. Label events as \"Me\" or \"Someone else\" " +
                    "in a session to teach the app your acoustic signature. " +
                    "Around 30 labels are needed before the stronger model kicks in.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            LinearProgressIndicator(
                progress = { (labelCount / 30f).coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth(),
            )
        }

        HorizontalDivider()

        Text(
            "Haman logs acoustic events during sleep. It is not a medical device and " +
                "does not screen for sleep apnoea or any other condition. All audio " +
                "is processed on this device and never uploaded.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
