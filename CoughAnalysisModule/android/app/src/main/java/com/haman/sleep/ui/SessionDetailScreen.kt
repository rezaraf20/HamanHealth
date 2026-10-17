package com.haman.sleep.ui

import android.media.MediaPlayer
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.haman.data.EventSummary
import com.haman.data.SessionEntity
import java.io.File

/**
 * One night in detail, and the only place labels can be given.
 *
 * The labelling affordance is the product's feedback loop: it is what turns a generic
 * model into one calibrated to this room and these two people (architecture §4). So it
 * is one tap per event, inline, rather than buried behind a dialog.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SessionDetailScreen(vm: MainViewModel, sessionId: Long, onBack: () -> Unit) {
    val sessions by vm.sessions.collectAsState()
    val session = sessions.firstOrNull { it.id == sessionId }
    val events by vm.events(sessionId).collectAsState(initial = emptyList())
    val rollups by vm.rollups(sessionId).collectAsState(initial = emptyList())
    val episodes by vm.episodes(sessionId).collectAsState(initial = emptyList())
    var exportMsg by remember { mutableStateOf<String?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(session?.let { formatTime(it.startedAt) } ?: "Session") },
                navigationIcon = { TextButton(onClick = onBack) { Text("Back") } },
                actions = {
                    TextButton(onClick = {
                        vm.export(sessionId) { f ->
                            exportMsg = if (f != null) "Exported to Files/Android/data" else "Export failed"
                        }
                    }) { Text("Export") }
                },
            )
        }
    ) { pad ->
        LazyColumn(
            Modifier.fillMaxSize().padding(pad).padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            contentPadding = PaddingValues(vertical = 16.dp),
        ) {
            exportMsg?.let { item { Text(it, style = MaterialTheme.typography.labelMedium) } }

            item {
                TimelineChart(rollups, session?.startedAt ?: 0L, session?.endedAt ?: 0L)
            }
            item { LegendRow() }

            item {
                val byClass = events.groupingBy { it.cls }.eachCount()
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    listOf("COUGH", "SNEEZE", "SNORE").forEach { c ->
                        StatTile(
                            label = c.lowercase().replaceFirstChar { it.uppercase() },
                            value = (byClass[c] ?: 0).toString(),
                            color = classColor(c),
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
            }

            if (episodes.isNotEmpty()) {
                item {
                    Text("Snoring episodes", style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold)
                }
                items(episodes, key = { "ep${it.id}" }) { ep ->
                    ListItem(
                        headlineContent = {
                            Text("${formatTime(ep.startMs)} – ${formatTime(ep.endMs)}")
                        },
                        supportingContent = {
                            Text("${ep.snoreCount} snores · ${formatDuration(ep.endMs - ep.startMs)} · " +
                                "${ep.snoresPerHour.toInt()}/h")
                        },
                    )
                }
            }

            item {
                Text("Events (${events.size})", style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold)
            }
            if (events.isEmpty()) {
                item {
                    Text("Nothing detected during this session.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            items(events, key = { it.id }) { e ->
                EventRow(e, onLabel = { vm.label(e.id, it) }, onClear = { vm.clearLabel(e.id) })
            }
        }
    }
}

@Composable
private fun EventRow(e: EventSummary, onLabel: (String) -> Unit, onClear: () -> Unit) {
    var player by remember { mutableStateOf<MediaPlayer?>(null) }
    DisposableEffect(Unit) { onDispose { player?.release() } }

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically) {
                Column {
                    Text(e.cls.lowercase().replaceFirstChar { it.uppercase() },
                        style = MaterialTheme.typography.titleSmall,
                        color = classColor(e.cls), fontWeight = FontWeight.SemiBold)
                    Text(formatTimeSec(e.startedAtMs),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text("score ${"%.2f".format(e.peakScore)}",
                        style = MaterialTheme.typography.labelSmall)
                    Text("${e.peakDb.toInt()} dB", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }

            // The model's own guess, shown with its confidence so a weak call reads as weak.
            if (e.subjectLabel != "UNKNOWN") {
                Text(
                    "attributed: ${e.subjectLabel.lowercase()} (${(e.subjectConfidence * 100).toInt()}%)",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            e.clipPath?.let { path ->
                TextButton(onClick = {
                    runCatching {
                        player?.release()
                        player = MediaPlayer().apply {
                            setDataSource(path); prepare(); start()
                        }
                    }
                }, enabled = File(path).exists()) { Text("Play 2.5s clip") }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                LabelChip("Me", e.userLabel == "SUBJECT") { onLabel("SUBJECT") }
                LabelChip("Someone else", e.userLabel == "OTHER") { onLabel("OTHER") }
                LabelChip("Not a real event", e.userLabel == "NOT_AN_EVENT") { onLabel("NOT_AN_EVENT") }
            }
            if (e.userLabel != null) {
                TextButton(onClick = onClear) { Text("Clear label") }
            }
        }
    }
}

@Composable
private fun LabelChip(text: String, selected: Boolean, onClick: () -> Unit) {
    FilterChip(selected = selected, onClick = onClick, label = { Text(text) })
}
