package com.haman.sleep.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.haman.data.MinuteRollupEntity
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

fun classColor(cls: String): Color = when (cls) {
    "COUGH" -> ClassColors.cough
    "SNEEZE" -> ClassColors.sneeze
    "SNORE" -> ClassColors.snore
    else -> ClassColors.neutral
}

private val timeFmt = SimpleDateFormat("HH:mm", Locale.getDefault())
private val timeSecFmt = SimpleDateFormat("HH:mm:ss", Locale.getDefault())

fun formatTime(ms: Long): String = timeFmt.format(Date(ms))
fun formatTimeSec(ms: Long): String = timeSecFmt.format(Date(ms))

fun formatDuration(ms: Long): String {
    val totalMin = ms / 60_000
    return if (totalMin < 60) "${totalMin}m" else "${totalMin / 60}h ${totalMin % 60}m"
}

/** Live input level. Maps a dBFS range onto a bar, with the noise floor marked so the
 *  gate's behaviour is visible rather than mysterious. */
@Composable
fun LevelMeter(rmsDb: Float, floorDb: Float, gateOpen: Boolean, modifier: Modifier = Modifier) {
    val minDb = -80f
    val maxDb = 0f
    fun norm(v: Float) = ((v - minDb) / (maxDb - minDb)).coerceIn(0f, 1f)
    val level = norm(rmsDb)
    val floor = norm(floorDb)
    val active = MaterialTheme.colorScheme.primary
    val idle = MaterialTheme.colorScheme.surfaceVariant
    val marker = MaterialTheme.colorScheme.onSurfaceVariant

    Canvas(modifier.fillMaxWidth().height(28.dp)) {
        drawRect(color = idle, size = size)
        drawRect(
            color = if (gateOpen) active else active.copy(alpha = 0.35f),
            size = Size(size.width * level, size.height),
        )
        // Noise-floor tick: everything to the left of this is gated away.
        drawRect(
            color = marker,
            topLeft = Offset(size.width * floor, 0f),
            size = Size(2f, size.height),
        )
    }
}

/**
 * The night at a glance, drawn from the per-minute rollup.
 *
 * This is why minute_rollup exists: an 8-hour timeline is ~480 rows regardless of how
 * eventful the night was, so the chart renders in constant time.
 */
@Composable
fun TimelineChart(
    rollups: List<MinuteRollupEntity>,
    startedAt: Long,
    endedAt: Long,
    modifier: Modifier = Modifier,
) {
    if (rollups.isEmpty()) {
        Box(modifier.fillMaxWidth().height(120.dp), contentAlignment = Alignment.Center) {
            Text("No activity recorded", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        return
    }
    val startMin = startedAt / 60_000
    val endMin = (if (endedAt > 0) endedAt else System.currentTimeMillis()) / 60_000
    val span = (endMin - startMin).coerceAtLeast(1)
    val surface = MaterialTheme.colorScheme.surfaceVariant

    Column(modifier) {
        Canvas(Modifier.fillMaxWidth().height(120.dp)) {
            drawRect(surface, size = size)
            val maxCount = rollups.maxOf { it.count }.coerceAtLeast(1)
            rollups.forEach { r ->
                if (r.count == 0) return@forEach
                val x = ((r.minuteEpoch - startMin).toFloat() / span) * size.width
                val h = (r.count.toFloat() / maxCount) * size.height * 0.9f
                drawRect(
                    color = classColor(r.cls),
                    topLeft = Offset(x, size.height - h),
                    size = Size(maxOf(2f, size.width / span), h),
                )
            }
        }
        Row(Modifier.fillMaxWidth().padding(top = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween) {
            Text(formatTime(startedAt), style = MaterialTheme.typography.labelSmall)
            Text(formatTime(if (endedAt > 0) endedAt else System.currentTimeMillis()),
                style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
fun StatTile(label: String, value: String, color: Color, modifier: Modifier = Modifier) {
    Column(
        modifier
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(horizontal = 14.dp, vertical = 12.dp)
    ) {
        Text(value, style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.SemiBold, color = color)
        Text(label, style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun LegendRow(modifier: Modifier = Modifier) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        listOf("Cough" to ClassColors.cough, "Sneeze" to ClassColors.sneeze,
            "Snore" to ClassColors.snore).forEach { (name, c) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.height(10.dp).clip(RoundedCornerShape(2.dp))
                    .background(c).padding(end = 10.dp)) { Text("    ") }
                Text("  $name", style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}
