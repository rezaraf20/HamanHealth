package com.haman.sleep.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.haman.data.SessionEntity
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val dayFmt = SimpleDateFormat("EEE d MMM", Locale.getDefault())

@Composable
fun HistoryScreen(vm: MainViewModel, onOpen: (Long) -> Unit) {
    val sessions by vm.sessions.collectAsState()

    if (sessions.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("No nights recorded yet", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        return
    }

    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        contentPadding = PaddingValues(vertical = 20.dp),
    ) {
        item {
            Text("History", style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.SemiBold)
        }
        items(sessions, key = { it.id }) { s -> SessionCard(s) { onOpen(s.id) } }
    }
}

@Composable
private fun SessionCard(s: SessionEntity, onClick: () -> Unit) {
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(dayFmt.format(Date(s.startedAt)),
                    style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                val dur = (s.endedAt ?: s.startedAt) - s.startedAt
                Text(formatDuration(dur), style = MaterialTheme.typography.bodyMedium)
            }
            Text("${formatTime(s.startedAt)} – ${s.endedAt?.let { formatTime(it) } ?: "…"}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)

            if (s.status == SessionEntity.STATUS_INTERRUPTED) {
                // Never hide a short night: an interrupted session and a quiet one look
                // identical in the data, and conflating them makes the log untrustworthy.
                Text("Interrupted — the service was stopped before you ended it",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.error)
            }
            if (s.framesSeen > 0) {
                val skipped = 100 - (s.framesInferred * 100 / s.framesSeen)
                Text("$skipped% of frames gated · mic ${s.audioSource}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
