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
import com.haman.domain.AcousticClass
import kotlinx.coroutines.delay

@Composable
fun HomeScreen(
    vm: MainViewModel,
    onStart: () -> Unit,
    onStop: () -> Unit,
    batteryExempt: Boolean,
    onRequestBatteryExemption: () -> Unit,
) {
    val live by vm.live.collectAsState()
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(live.running) {
        while (live.running) { now = System.currentTimeMillis(); delay(1000) }
    }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Tonight", style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.SemiBold)

        live.error?.let {
            Card(colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.errorContainer)) {
                Text(it, Modifier.padding(14.dp), color = MaterialTheme.colorScheme.onErrorContainer)
            }
        }

        // Doze and OEM battery managers are the most common reason a night ends at 2am
        // with no data. Surfaced before recording rather than after a lost night.
        if (!batteryExempt) {
            Card(colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.tertiaryContainer)) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Battery optimisation is on",
                        style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                    Text(
                        "Android may stop the recording partway through the night. " +
                        "Exempting Haman keeps it running until you stop it.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    TextButton(onClick = onRequestBatteryExemption) { Text("Allow background running") }
                }
            }
        }

        if (live.running) {
            Text(
                "Recording for ${formatDuration(now - live.startedAt)}",
                style = MaterialTheme.typography.bodyLarge,
            )
            LevelMeter(live.rmsDb, live.noiseFloorDb, live.gateOpen)
            Text(
                "Input ${live.rmsDb.toInt()} dB · floor ${live.noiseFloorDb.toInt()} dB · " +
                    "${(live.gateSkipRatio * 100).toInt()}% of frames skipped by the gate",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                "Microphone path: ${live.audioSource}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            Text(
                "Place the phone on your nightstand, screen down, plugged in. " +
                    "Audio is analysed on the device and never leaves it.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            AcousticClass.LOGGED.forEach { cls ->
                StatTile(
                    label = cls.name.lowercase().replaceFirstChar { it.uppercase() },
                    value = (live.counts[cls] ?: 0).toString(),
                    color = classColor(cls.name),
                    modifier = Modifier.weight(1f),
                )
            }
        }

        live.lastEventClass?.let {
            Text(
                "Last: ${it.name.lowercase()} at ${formatTimeSec(live.lastEventAt)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Button(
            onClick = if (live.running) onStop else onStart,
            modifier = Modifier.fillMaxWidth().height(56.dp),
            colors = if (live.running)
                ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
            else ButtonDefaults.buttonColors(),
        ) {
            Text(if (live.running) "Stop monitoring" else "Start monitoring",
                style = MaterialTheme.typography.titleMedium)
        }

        LegendRow()
    }
}
