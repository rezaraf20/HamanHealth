package com.haman.audio

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import kotlin.math.log10
import kotlin.math.sqrt

/**
 * Microphone capture that always delivers 16 kHz mono PCM to the pipeline, from
 * whichever source and native rate gives the most faithful signal on this phone.
 *
 * Which Android audio source is best is device-specific, and choosing wrong fails
 * silently. MIC applies automatic gain control; VOICE_RECOGNITION is AGC-free on most
 * phones but on some it is routed through narrowband voice processing that cuts
 * everything above ~4 kHz - where much of a cough lives. The app worked on Samsung
 * flagships and missed most coughs on budget phones, consistent with exactly that.
 * [AudioSourceProbe] measures each route, and the chosen [Route] is passed in here.
 */
class AudioCapture(private val context: Context) {

    enum class Source(val androidSource: Int) {
        UNPROCESSED(MediaRecorder.AudioSource.UNPROCESSED),
        VOICE_RECOGNITION(MediaRecorder.AudioSource.VOICE_RECOGNITION),
        CAMCORDER(MediaRecorder.AudioSource.CAMCORDER),
        MIC(MediaRecorder.AudioSource.MIC),
    }

    /** A source plus the rate it is captured at. At 48 kHz the stream is decimated to
     *  16 kHz internally, for phones that only deliver full band at their native rate. */
    data class Route(val source: Source, val captureRate: Int) {
        override fun toString() = "${source.name}@${captureRate / 1000}k"

        companion object {
            fun parse(s: String?): Route? = runCatching {
                val (src, rate) = s!!.split("@")
                Route(Source.valueOf(src), rate.removeSuffix("k").toInt() * 1000)
            }.getOrNull()
        }
    }

    private var record: AudioRecord? = null
    private var decimator: Decimator3? = null
    @Volatile private var running = false

    var activeRoute: Route = Route(Source.MIC, OUTPUT_RATE)
        private set

    fun supportsUnprocessed(): Boolean {
        val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        return am.getProperty(AudioManager.PROPERTY_SUPPORT_AUDIO_SOURCE_UNPROCESSED) == "true"
    }

    /** Order tried when no cough-test result is stored. See [DEFAULT_ORDER]. */
    fun defaultRoutes(): List<Route> =
        DEFAULT_ORDER.map { Route(it, OUTPUT_RATE) }

    @SuppressLint("MissingPermission") // caller holds RECORD_AUDIO; enforced by the service
    fun start(preferred: Route? = null): Boolean {
        val candidates = buildList {
            preferred?.let(::add)
            defaultRoutes().filter { it != preferred }.forEach(::add)
        }
        for (route in candidates) {
            val r = open(route) ?: continue
            record = r
            activeRoute = route
            decimator = if (route.captureRate == 48000) Decimator3() else null
            r.startRecording()
            running = true
            Log.i(TAG, "capture started on $route")
            return true
        }
        Log.e(TAG, "no usable audio route")
        return false
    }

    /**
     * Blocking read loop on the caller's thread. Always delivers 16 kHz samples,
     * decimating when capturing at 48 kHz.
     */
    fun readLoop(onAudio: (ShortArray, Int) -> Unit) {
        val r = record ?: return
        val dec = decimator
        val chunk = ShortArray(activeRoute.captureRate / 10) // 100 ms
        val out = ShortArray(OUTPUT_RATE / 10 + 4)
        while (running) {
            val n = r.read(chunk, 0, chunk.size)
            if (n > 0) {
                if (dec != null) {
                    val m = dec.process(chunk, n, out)
                    if (m > 0) onAudio(out, m)
                } else {
                    onAudio(chunk, n)
                }
            } else if (n == AudioRecord.ERROR_INVALID_OPERATION || n == AudioRecord.ERROR_DEAD_OBJECT) {
                // The mic was taken (a call, another app). Surfacing this lets the
                // service log an explicit gap instead of silently losing hours.
                Log.w(TAG, "read failed ($n); microphone lost")
                running = false
            }
        }
    }

    fun stop() {
        running = false
        record?.let {
            runCatching { if (it.recordingState == AudioRecord.RECORDSTATE_RECORDING) it.stop() }
            it.release()
        }
        record = null
    }

    val isRunning: Boolean get() = running

    companion object {
        private const val TAG = "AudioCapture"
        const val OUTPUT_RATE = 16000

        /**
         * Measured, not assumed (see AudioSourceProbe for the numbers): on a Galaxy S23
         * CAMCORDER kept coughs intact where VOICE_RECOGNITION's noise suppression
         * damaged them, and UNPROCESSED arrived ~18 dB too quiet. Phones differ, which
         * is what the diagnostics cough test is for; this is only the fallback.
         */
        val DEFAULT_ORDER = listOf(
            Source.CAMCORDER, Source.VOICE_RECOGNITION, Source.MIC, Source.UNPROCESSED,
        )

        @SuppressLint("MissingPermission")
        internal fun open(route: Route): AudioRecord? {
            val minBuf = AudioRecord.getMinBufferSize(
                route.captureRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            if (minBuf <= 0) return null
            // >= 1 s of buffer: the thread must survive being descheduled while the
            // device dozes without dropping audio.
            val size = maxOf(minBuf * 4, route.captureRate * 2)
            val r = try {
                AudioRecord(route.source.androidSource, route.captureRate,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, size)
            } catch (e: Exception) {
                Log.w(TAG, "route $route unavailable", e); return null
            }
            if (r.state != AudioRecord.STATE_INITIALIZED) { r.release(); return null }
            return r
        }

        fun toFloat(src: ShortArray, count: Int, dst: FloatArray) {
            for (i in 0 until count) dst[i] = src[i] / 32768f
        }

        /** Frame level in dBFS. Floored at -160 so digital silence stays finite. */
        fun rmsDb(samples: FloatArray, count: Int = samples.size): Float {
            var sum = 0.0
            for (i in 0 until count) sum += (samples[i] * samples[i]).toDouble()
            val rms = sqrt(sum / count)
            if (rms < 1e-8) return -160f
            return (20.0 * log10(rms)).toFloat()
        }
    }
}
