package com.haman.sleep.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import com.haman.audio.AudioCapture
import com.haman.audio.AudioRingBuffer
import com.haman.audio.SlidingWindow
import com.haman.audio.WavWriter
import com.haman.data.HamanDatabase
import com.haman.data.SessionEntity
import com.haman.data.SessionWriter
import com.haman.data.AttributionStore
import com.haman.domain.AcousticClass
import com.haman.domain.DetectionPipeline
import com.haman.domain.DetectorConfig
import com.haman.inference.YamnetClassifier
import com.haman.sleep.MainActivity
import com.haman.sleep.R
import com.haman.sleep.data.Prefs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import java.io.File
import kotlin.concurrent.thread

/**
 * Runs the whole detection chain for a night.
 *
 * Reliability, not throughput, is the hard part here. A foreground service alone is not
 * enough: without a wakelock the CPU suspends between microphone buffers and inference
 * stops while capture appears to continue, and on several OEM Android builds the
 * process is killed outright unless the user has granted a battery-optimisation
 * exemption. Both are handled here; the exemption prompt lives in the UI because only
 * the user can grant it.
 */
class MonitoringService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var captureThread: Thread? = null
    private var capture: AudioCapture? = null
    private var classifier: YamnetClassifier? = null
    private var wakeLock: PowerManager.WakeLock? = null

    @Volatile private var stopping = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> { stopSelf(); return START_NOT_STICKY }
        }
        if (captureThread != null) return START_STICKY

        startForegroundNotification()
        acquireWakeLock()
        captureThread = thread(name = "haman-capture", start = true) { runSession() }
        return START_STICKY
    }

    private fun runSession() = runBlocking {
        val db = HamanDatabase.get(applicationContext)
        val prefs = Prefs(applicationContext)
        val sampleRate = YamnetClassifier.SAMPLE_RATE

        val cap = AudioCapture(applicationContext, sampleRate)
        capture = cap
        if (!cap.start()) {
            MonitorState.update { it.copy(error = "Microphone unavailable") }
            stopSelf(); return@runBlocking
        }

        val clf = try {
            YamnetClassifier(applicationContext)
        } catch (e: Exception) {
            Log.e(TAG, "model load failed", e)
            MonitorState.update { it.copy(error = "Model failed to load: ${e.message}") }
            cap.stop(); stopSelf(); return@runBlocking
        }
        classifier = clf

        val config = loadConfig(prefs)
        val pipeline = DetectionPipeline(config, frameHopMs = HOP_MS)
        AttributionStore(db).configure(pipeline.attribution, prefs.readCalibration())

        val startedAt = System.currentTimeMillis()
        val sessionId = db.sessions().insert(
            SessionEntity(
                startedAt = startedAt,
                deviceModel = "${Build.MANUFACTURER} ${Build.MODEL}",
                appVersion = appVersion(),
                audioSource = cap.activeSource.name,
                configJson = config.toJson(),
            )
        )
        val writer = SessionWriter(db, sessionId)
        val clipsDir = File(filesDir, "clips/$sessionId")
        val keepClips = prefs.readKeepClips()

        MonitorState.update {
            it.copy(running = true, sessionId = sessionId, startedAt = startedAt,
                audioSource = cap.activeSource.name, error = null)
        }

        val window = SlidingWindow(YamnetClassifier.FRAME_SAMPLES, HOP_SAMPLES)
        val ring = AudioRingBuffer(sampleRate * RING_SECONDS)
        val floatChunk = FloatArray(sampleRate / 10)
        val counts = mutableMapOf<AcousticClass, Int>()
        var samplesRead = 0L
        var lastFlush = System.currentTimeMillis()

        cap.readLoop { pcm, n ->
            ring.write(pcm, n)
            samplesRead += n
            AudioCapture.toFloat(pcm, n, floatChunk)

            window.append(floatChunk, n) { frame ->
                // Timestamps are derived from the sample count, not the wall clock:
                // the audio stream is the only monotonic reference that stays correct
                // if the device clock shifts mid-night.
                val framePos = samplesRead
                val relMs = (framePos - YamnetClassifier.FRAME_SAMPLES) * 1000L / sampleRate
                val ts = startedAt + relMs
                val rms = AudioCapture.rmsDb(frame)

                val result = pipeline.onFrame(ts, rms) { clf.infer(frame) }

                for (event in result.events) {
                    counts[event.cls] = (counts[event.cls] ?: 0) + 1
                    val clipPath = if (keepClips) saveClip(ring, clipsDir, event.peakFrameMs,
                        startedAt, sampleRate, event.cls.name, event.startMs) else null
                    writer.addEvent(event, pipeline.embeddingFor(event.peakFrameMs), clipPath)
                    MonitorState.update {
                        it.copy(lastEventAt = event.startMs, lastEventClass = event.cls,
                            counts = counts.toMap())
                    }
                }
                result.completedEpisodes.forEach(writer::addEpisode)
                writer.addBuckets(result.completedBuckets)

                MonitorState.update {
                    it.copy(rmsDb = rms, noiseFloorDb = result.noiseFloorDb,
                        gateOpen = result.gateOpen, gateSkipRatio = pipeline.gateSkipRatio)
                }

                val now = System.currentTimeMillis()
                if (now - lastFlush >= FLUSH_INTERVAL_MS && writer.hasPending) {
                    lastFlush = now
                    scope.launch { runCatching { writer.flush() }
                        .onFailure { Log.e(TAG, "flush failed", it) } }
                }
            }
        }

        // readLoop returns when capture stops or the microphone is taken away.
        val endedAt = System.currentTimeMillis()
        val tail = pipeline.flush(endedAt)
        tail.events.forEach { writer.addEvent(it, pipeline.embeddingFor(it.peakFrameMs), null) }
        tail.completedEpisodes.forEach(writer::addEpisode)
        writer.addBuckets(tail.completedBuckets)
        runCatching { writer.flush() }.onFailure { Log.e(TAG, "final flush failed", it) }

        val status = if (stopping) SessionEntity.STATUS_COMPLETE else SessionEntity.STATUS_INTERRUPTED
        db.sessions().finish(
            id = sessionId, endedAt = endedAt, status = status,
            floor = pipeline.let { MonitorState.state.value.noiseFloorDb },
            framesSeen = pipeline.framesSeen, framesInferred = pipeline.framesInferred,
            micGapMs = MonitorState.state.value.micGapMs,
        )
        applyRetention(db, prefs)
        clf.close()
        MonitorState.update { it.copy(running = false) }
    }

    /** 2.5 s around the event, including pre-roll from before detection completed. */
    private fun saveClip(
        ring: AudioRingBuffer, dir: File, peakFrameMs: Long,
        sessionStart: Long, sampleRate: Int, cls: String, eventStartMs: Long,
    ): String? {
        val preRollMs = 750L
        val clipMs = 2500L
        val startRelMs = (peakFrameMs - sessionStart) - preRollMs
        if (startRelMs < 0) return null
        val startSample = startRelMs * sampleRate / 1000
        val count = (clipMs * sampleRate / 1000).toInt()
        val pcm = ring.read(startSample + count, count) ?: return null
        val file = File(dir, "${cls}_$eventStartMs.wav")
        return runCatching {
            WavWriter.write(file, pcm, sampleRate)
            file.absolutePath
        }.getOrNull()
    }

    private suspend fun applyRetention(db: HamanDatabase, prefs: Prefs) {
        val days = prefs.readRetentionDays()
        if (days <= 0) return
        val cutoff = System.currentTimeMillis() - days * 24L * 3600_000L
        db.events().clipsOlderThan(cutoff).forEach { runCatching { File(it).delete() } }
        db.events().clearClipsOlderThan(cutoff)
    }

    private fun loadConfig(prefs: Prefs): DetectorConfig {
        // A tuned config shipped by ml/tune_thresholds.py takes precedence over the
        // hand-set defaults; the sensitivity dial is applied on top of whichever wins.
        val base = runCatching {
            assets.open(CONFIG_ASSET).bufferedReader().use { DetectorConfig.fromJson(it.readText()) }
        }.getOrElse {
            Log.i(TAG, "no tuned config in assets, using defaults")
            DetectorConfig.DEFAULT
        }
        return base.withSensitivity(prefs.readSensitivity())
    }

    private fun appVersion(): String = runCatching {
        packageManager.getPackageInfo(packageName, 0).versionName ?: "?"
    }.getOrDefault("?")

    private fun acquireWakeLock() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "haman:monitor").apply {
            setReferenceCounted(false)
            // No timeout: the wakelock must outlive a full night. It is released in
            // onDestroy, and the foreground notification keeps it user-visible.
            acquire()
        }
    }

    private fun startForegroundNotification() {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Sleep monitoring",
                    NotificationManager.IMPORTANCE_LOW).apply {
                    description = "Shown while the microphone is being monitored"
                    setShowBadge(false)
                }
            )
        }
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val stop = PendingIntent.getService(
            this, 1, Intent(this, MonitoringService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val n: Notification = Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("Listening")
            .setContentText("Monitoring sleep sounds. Audio stays on this device.")
            .setSmallIcon(android.R.drawable.presence_audio_online)
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "Stop", stop).build())
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(NOTIF_ID, n)
        }
    }

    override fun onDestroy() {
        stopping = true
        capture?.stop()
        captureThread?.join(5_000)
        wakeLock?.let { if (it.isHeld) it.release() }
        scope.cancel()
        MonitorState.update { it.copy(running = false) }
        super.onDestroy()
    }

    companion object {
        private const val TAG = "MonitoringService"
        private const val CHANNEL_ID = "haman_monitor"
        private const val NOTIF_ID = 1001
        const val ACTION_STOP = "com.haman.sleep.STOP"
        const val CONFIG_ASSET = "detector_config.json"

        const val HOP_MS = 480L
        const val HOP_SAMPLES = 7680        // 480 ms at 16 kHz
        const val RING_SECONDS = 10
        const val FLUSH_INTERVAL_MS = 5_000L

        fun start(context: Context) {
            val i = Intent(context, MonitoringService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(i)
            else context.startService(i)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, MonitoringService::class.java))
        }
    }
}
