package com.haman.sleep.plugin

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.ContextCompat
import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.PermissionState
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback
import com.haman.data.HamanDatabase
import com.haman.data.SessionEntity
import com.haman.domain.AcousticClass
import com.haman.domain.PlatformContract.isoUtc
import com.haman.sleep.service.MonitorState
import com.haman.sleep.service.MonitoringService
import com.haman.sleep.sync.AuthTokens
import com.haman.sleep.sync.SyncEngine
import com.haman.sleep.sync.SyncScheduler
import com.haman.sleep.sync.SyncStatus
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * The "CoughSession" Capacitor plugin: the web interface's way into the cough module.
 *
 * Implements web/src/lib/cough-session.plugin.ts, contract version [CONTRACT_VERSION].
 * The contract only grows: never remove or rename a method, argument, field or event,
 * and bump the version here and in that file together.
 *
 * Nothing here runs on, or waits for, the capture thread. Calls that have to wait (start
 * until the session row exists, stop until it is finished, syncNow until the upload
 * attempt ends) resolve from a coroutine, so the bridge thread returns at once.
 */
@CapacitorPlugin(
    name = "CoughSession",
    permissions = [
        Permission(alias = CoughSessionPlugin.MICROPHONE, strings = [Manifest.permission.RECORD_AUDIO]),
        Permission(alias = CoughSessionPlugin.NOTIFICATIONS, strings = [Manifest.permission.POST_NOTIFICATIONS]),
    ],
)
class CoughSessionPlugin : Plugin() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val db by lazy { HamanDatabase.get(context) }
    private val sync by lazy { SyncEngine.get(context) }

    override fun load() {
        scope.launch {
            reconcileInterruptedSessions()
            // Nights finished but not (fully) uploaded, including ones recorded before
            // this version; does nothing while signed out.
            SyncScheduler.enqueueAllPending(context)
        }
        scope.launch {
            MonitorState.events.collect { e ->
                notifyListeners("detectedEvent", JSObject().apply {
                    put("sessionId", e.sessionId.toString())
                    put("type", e.event.cls.name.lowercase())
                    put("timestamp", isoUtc(e.event.startMs))
                    put("confidence", e.event.peakScore.toDouble())
                })
            }
        }
        scope.launch { sync.statusUpdates.collect { notifyListeners("syncStatus", it.toJs()) } }
    }

    override fun handleOnDestroy() {
        scope.cancel()
        super.handleOnDestroy()
    }

    @PluginMethod
    fun getInfo(call: PluginCall) {
        val version = runCatching {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName
        }.getOrNull() ?: "?"
        call.resolve(JSObject().put("contractVersion", CONTRACT_VERSION).put("appVersion", version))
    }

    @PluginMethod
    fun isAvailable(call: PluginCall) {
        val mic = context.packageManager.hasSystemFeature(PackageManager.FEATURE_MICROPHONE)
        val model = runCatching { context.assets.openFd(MODEL_ASSET).use { it.length > 0 } }.getOrDefault(false)
        call.resolve(JSObject().put("available", mic && model))
    }

    @PluginMethod
    override fun requestPermissions(call: PluginCall) {
        val aliases = buildList {
            if (getPermissionState(MICROPHONE) != PermissionState.GRANTED) add(MICROPHONE)
            // Without it the foreground-service notification is hidden on Android 13+,
            // and a service the user cannot see is what the system kills first.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                getPermissionState(NOTIFICATIONS) != PermissionState.GRANTED) add(NOTIFICATIONS)
        }
        if (aliases.isEmpty()) permissionsDone(call)
        else requestPermissionForAliases(aliases.toTypedArray(), call, "permissionsDone")
    }

    @PermissionCallback
    private fun permissionsDone(call: PluginCall) {
        val granted = micGranted()
        // An overnight session needs the battery exemption, or many phones end it partway
        // through the night. The old native screens asked for it; now this is the place.
        if (granted) askBatteryExemptionOnce()
        call.resolve(JSObject().put("microphone", if (granted) "granted" else "denied"))
    }

    @PluginMethod
    fun start(call: PluginCall) {
        val sensitivity = when (call.getString("sensitivity", "medium")) {
            // Midpoints of PlatformContract.sensitivityLevel's three ranges.
            "low" -> 0.17f
            "high" -> 0.83f
            "medium" -> 0.5f
            else -> return call.reject("Unknown sensitivity")
        }
        val autoStopAt = call.getString("autoStopAt")?.let {
            runCatching { Instant.parse(it).toEpochMilli() }.getOrElse { return call.reject("autoStopAt is not a valid time") }
        } ?: 0L
        if (autoStopAt in 1..System.currentTimeMillis()) return call.reject("autoStopAt is in the past")
        if (MonitorState.state.value.running) return call.reject("A night session is already running")
        if (!micGranted()) return call.reject("Microphone permission is needed to start a night session")

        MonitorState.update { it.copy(error = null, sessionId = -1) }
        MonitoringService.start(context, sensitivity, autoStopAt)
        scope.launch {
            // The service creates the session row on its capture thread; wait for it.
            val live = withTimeoutOrNull(START_TIMEOUT_MS) {
                MonitorState.state.first { (it.running && it.sessionId > 0) || it.error != null }
            }
            when {
                live == null -> call.reject("The night session did not start")
                live.error != null -> call.reject(live.error)
                else -> call.resolve(JSObject().put("sessionId", live.sessionId.toString()))
            }
        }
    }

    @PluginMethod
    fun stop(call: PluginCall) {
        val live = MonitorState.state.value
        if (!live.running || live.sessionId <= 0) return call.reject("No night session is running")
        val sessionId = live.sessionId
        MonitoringService.stop(context)
        scope.launch {
            // Until the service has run sessions().finish(); it then queues the upload itself.
            val finished = withTimeoutOrNull(STOP_TIMEOUT_MS) {
                MonitorState.state.first { it.lastFinishedSessionId == sessionId }
            }
            if (finished == null) return@launch call.reject("The night session did not finish saving")
            val session = db.sessions().byId(sessionId) ?: return@launch call.reject("The night session was not saved")
            call.resolve(summary(session))
        }
    }

    @PluginMethod
    fun getStatus(call: PluginCall) {
        val live = MonitorState.state.value
        val state = when {
            live.running && live.stopping -> "stopping"
            live.running -> "running"
            else -> "idle"
        }
        call.resolve(JSObject().apply {
            put("state", state)
            if (live.running && live.sessionId > 0) {
                put("sessionId", live.sessionId.toString())
                put("startedAt", isoUtc(live.startedAt))
                if (live.autoStopAt > 0) put("autoStopAt", isoUtc(live.autoStopAt))
            }
            put("eventCount", if (live.running) live.counts[AcousticClass.COUGH] ?: 0 else 0)
        })
    }

    @PluginMethod
    fun listSessions(call: PluginCall) {
        val (from, to) = runCatching {
            Instant.parse(call.getString("from")).toEpochMilli() to Instant.parse(call.getString("to")).toEpochMilli()
        }.getOrElse { return call.reject("from and to must be ISO 8601 times") }
        scope.launch {
            val sessions = JSArray()
            db.sessions().finishedBetween(from, to).forEach { sessions.put(summary(it)) }
            call.resolve(JSObject().put("sessions", sessions))
        }
    }

    @PluginMethod
    fun setAuth(call: PluginCall) {
        val baseUrl = call.getString("baseUrl")
        val access = call.getString("access")
        val refresh = call.getString("refresh")
        if (baseUrl.isNullOrBlank() || access.isNullOrBlank() || refresh.isNullOrBlank()) {
            return call.reject("baseUrl, access and refresh are required")
        }
        if (!baseUrl.startsWith("https://")) return call.reject("baseUrl must use https")
        scope.launch {
            sync.setAuth(AuthTokens(baseUrl.trimEnd('/'), access, refresh))
            SyncScheduler.enqueueAllPending(context)
            sync.publishStatus()
            call.resolve()
        }
    }

    @PluginMethod
    fun clearAuth(call: PluginCall) {
        scope.launch {
            sync.clearAuth()
            SyncScheduler.cancelAll(context)
            sync.publishStatus()
            call.resolve()
        }
    }

    @PluginMethod
    fun syncNow(call: PluginCall) {
        scope.launch {
            val result = sync.syncAll()
            // Whatever is still pending gets retried in the background with backoff.
            if (result == SyncEngine.Result.RETRY) SyncScheduler.enqueueAllPending(context)
            call.resolve(sync.status().toJs())
        }
    }

    @PluginMethod
    fun getSyncStatus(call: PluginCall) {
        scope.launch { call.resolve(sync.status().toJs()) }
    }

    // ── helpers ─────────────────────────────────────────────────────────────────

    private fun micGranted() =
        ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    /** NativeSessionSummary: counted coughs and coughs per local clock hour, in order. */
    private suspend fun summary(s: SessionEntity): JSObject {
        val coughs = db.events().countedCoughTimes(s.id)
        val zone = s.timezone?.let { runCatching { ZoneId.of(it) }.getOrNull() } ?: ZoneId.systemDefault()
        val hourly = JSArray()
        coughs.groupBy { HOUR.format(Instant.ofEpochMilli(it.startedAtMs).atZone(zone)) }
            .forEach { (hour, list) -> hourly.put(JSObject().put("hour", hour).put("count", list.size)) }
        return JSObject().apply {
            put("sessionId", s.id.toString())
            put("startedAt", isoUtc(s.startedAt))
            put("endedAt", isoUtc(s.endedAt ?: s.startedAt))
            put("totalCoughs", coughs.size)
            put("hourly", hourly)
        }
    }

    /** A session left 'running' by a killed process is closed as interrupted, unless it
     *  is the one being recorded right now. Was done by the old native home screen. */
    private suspend fun reconcileInterruptedSessions() {
        val live = MonitorState.state.value
        db.sessions().running().forEach { s ->
            if (!live.running || live.sessionId != s.id) {
                db.sessions().finish(
                    id = s.id, endedAt = s.startedAt, status = SessionEntity.STATUS_INTERRUPTED,
                    floor = s.noiseFloorDb, framesSeen = s.framesSeen,
                    framesInferred = s.framesInferred, micGapMs = s.micGapMs,
                )
            }
        }
    }

    private fun askBatteryExemptionOnce() {
        val pm = context.getSystemService(PowerManager::class.java) ?: return
        if (pm.isIgnoringBatteryOptimizations(context.packageName)) return
        val prefs = context.getSharedPreferences("haman", Context.MODE_PRIVATE)
        if (prefs.getBoolean(KEY_ASKED_BATTERY, false)) return
        prefs.edit().putBoolean(KEY_ASKED_BATTERY, true).apply()
        @Suppress("BatteryLife") // an 8-hour microphone session is the feature
        val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            .setData(Uri.parse("package:${context.packageName}"))
        runCatching { activity.startActivity(intent) }
    }

    private fun SyncStatus.toJs() = JSObject().apply {
        put("signedIn", signedIn)
        put("pendingNights", pendingNights)
        lastSyncedAt?.let { put("lastSyncedAt", isoUtc(it)) }
        lastError?.let { put("lastError", it) }
    }

    companion object {
        /** Bump together with CONTRACT_VERSION in web/src/lib/cough-session.plugin.ts. */
        const val CONTRACT_VERSION = 1
        const val MICROPHONE = "microphone"
        const val NOTIFICATIONS = "notifications"
        private const val MODEL_ASSET = "yamnet.tflite"
        private const val START_TIMEOUT_MS = 15_000L
        private const val STOP_TIMEOUT_MS = 30_000L
        private const val KEY_ASKED_BATTERY = "asked_battery_exemption"
        private val HOUR = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:00")
    }
}
