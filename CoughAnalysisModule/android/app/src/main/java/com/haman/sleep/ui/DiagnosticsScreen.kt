package com.haman.sleep.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.haman.audio.AudioCapture
import com.haman.audio.AudioSourceProbe
import com.haman.domain.AcousticClass
import com.haman.domain.InputNormalizer
import com.haman.domain.YamnetLabels
import com.haman.inference.YamnetClassifier
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Measures this phone's microphone routes and model speed, and picks the best route.
 *
 * Exists because detection quality turned out to be device-specific in ways that fail
 * silently: the same build caught coughs on Samsung flagships and missed most of them on
 * budget phones. The report is plain text so it can be copied off any phone and compared.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DiagnosticsScreen(vm: MainViewModel, micGranted: Boolean, onRequestMic: () -> Unit, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val live by vm.live.collectAsState()
    var running by remember { mutableStateOf(false) }
    var progress by remember { mutableFloatStateOf(0f) }
    var currentRoute by remember { mutableStateOf<String?>(null) }
    var results by remember { mutableStateOf<List<AudioSourceProbe.Result>>(emptyList()) }
    var latencyMs by remember { mutableStateOf<Float?>(null) }
    var chosen by remember { mutableStateOf(vm.prefs.readAudioRoute()) }
    var copied by remember { mutableStateOf(false) }

    fun run() = scope.launch {
        running = true; copied = false; progress = 0f
        results = withContext(Dispatchers.IO) {
            YamnetClassifier(context).use { clf ->
                AudioSourceProbe(context).probe(
                    secondsEach = 6f,
                    scorer = { audio -> coughScore(clf, audio) },
                ) { i, n, route ->
                    progress = i / n.toFloat()
                    currentRoute = route?.let { "Route ${i + 1} of $n (${it.source.name.lowercase()})" }
                }
            }
        }
        currentRoute = null
        latencyMs = withContext(Dispatchers.Default) { benchmarkModel(context) }
        AudioSourceProbe.choose(results)?.let {
            chosen = it.toString()
            vm.prefs.writeAudioRoute(chosen)
        }
        running = false
    }

    Scaffold(topBar = {
        TopAppBar(title = { Text("Microphone diagnostics") },
            navigationIcon = { TextButton(onClick = onBack) { Text("Back") } })
    }) { pad ->
        Column(
            Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(
                "Phones offer several microphone routes, and which one hears coughs best " +
                    "differs from phone to phone - on some, the default route's noise " +
                    "suppression erases most coughs. This test listens to your coughs on " +
                    "each route and keeps the one where they are recognised best.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer)) {
                Text(
                    "Put the phone where it will sit at night. When each route starts, " +
                        "cough 2-3 times at a normal strength. About 25 seconds in total.",
                    Modifier.padding(14.dp), style = MaterialTheme.typography.bodySmall,
                )
            }

            when {
                live.running -> Text("Stop monitoring first — the microphone is in use.",
                    color = MaterialTheme.colorScheme.error)
                !micGranted -> Button(onClick = onRequestMic) { Text("Allow microphone") }
                else -> Button(onClick = { run() }, enabled = !running,
                    modifier = Modifier.fillMaxWidth()) {
                    Text(if (running) "Testing…" else "Start cough test")
                }
            }
            if (running) {
                currentRoute?.let {
                    Text("$it — cough now", style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary)
                }
                LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth())
            }

            if (results.isNotEmpty()) {
                Text("Routes", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                results.forEach { r ->
                    val verdict = when {
                        !r.opened -> "unavailable"
                        r.inconclusive -> "too quiet to judge"
                        r.fullBand -> "full band"
                        else -> "BAND-LIMITED"
                    }
                    val cough = r.coughScore?.let { "cough ${"%.2f".format(it)}  " } ?: ""
                    Text("${r.route.toString().padEnd(22)} $cough$verdict",
                        fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall,
                        color = if (r.opened && !r.inconclusive && !r.fullBand)
                            MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface)
                }
            }

            Text("Selected route: ${chosen ?: "default order"}",
                style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            if (chosen != null) {
                TextButton(onClick = { vm.prefs.writeAudioRoute(null); chosen = null }) {
                    Text("Reset to default order")
                }
            }
            latencyMs?.let {
                Text("Model inference: ${"%.1f".format(it)} ms per frame " +
                        "(budget 480 ms; ${"%.0f".format(100 * it / 480)}% of real time)",
                    style = MaterialTheme.typography.bodySmall)
            }

            if (results.isNotEmpty()) {
                OutlinedButton(onClick = {
                    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    cm.setPrimaryClip(ClipData.newPlainText("Haman diagnostics", report(results, chosen, latencyMs, context)))
                    copied = true
                }) { Text(if (copied) "Copied" else "Copy report") }
            }
        }
    }
}

/** Mean of the two highest per-frame cough scores in [audio], on normalised frames -
 *  exactly what the monitoring pipeline would see. */
private fun coughScore(clf: YamnetClassifier, audio: FloatArray): Float {
    val scores = mutableListOf<Float>()
    val norm = FloatArray(YamnetClassifier.FRAME_SAMPLES)
    val frame = FloatArray(YamnetClassifier.FRAME_SAMPLES)
    var start = 0
    while (start + YamnetClassifier.FRAME_SAMPLES <= audio.size) {
        System.arraycopy(audio, start, frame, 0, frame.size)
        InputNormalizer.normalize(frame, norm)
        scores += YamnetLabels.reduce(clf.infer(norm).scores)[AcousticClass.COUGH.ordinal]
        start += 7680
    }
    return scores.sortedDescending().take(2).average().toFloat()
}

private fun benchmarkModel(context: Context): Float = YamnetClassifier(context).use { clf ->
    val frame = FloatArray(YamnetClassifier.FRAME_SAMPLES) { ((it * 7919) % 200 - 100) / 1000f }
    repeat(3) { clf.infer(frame) } // warm-up
    val times = (0 until 15).map {
        val t0 = System.nanoTime(); clf.infer(frame); (System.nanoTime() - t0) / 1e6f
    }
    times.sorted()[times.size / 2]
}

private fun report(results: List<AudioSourceProbe.Result>, chosen: String?, latency: Float?, context: Context): String =
    buildString {
        appendLine("Haman microphone diagnostics")
        appendLine("device: ${Build.MANUFACTURER} ${Build.MODEL} (Android ${Build.VERSION.RELEASE}, API ${Build.VERSION.SDK_INT})")
        appendLine("abi: ${Build.SUPPORTED_ABIS.joinToString()}")
        appendLine("unprocessed supported: ${AudioCapture(context).supportsUnprocessed()}")
        appendLine("model latency: ${latency?.let { "%.1f ms".format(it) } ?: "n/a"}")
        appendLine("selected: ${chosen ?: "default"}")
        results.forEach { r ->
            append("${r.route}: ")
            if (!r.opened) appendLine("unavailable")
            else appendLine("cough ${r.coughScore?.let { "%.2f".format(it) } ?: "n/a"}, rms ${"%.1f".format(r.rmsDb)} dB, low ${"%.1f".format(r.bands?.lowDb)} dB, " +
                "high ${"%.1f".format(r.bands?.highDb)} dB, " +
                (if (r.inconclusive) "inconclusive" else if (r.fullBand) "full-band" else "BAND-LIMITED"))
        }
    }
