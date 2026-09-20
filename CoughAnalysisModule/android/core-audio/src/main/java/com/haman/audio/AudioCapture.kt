package com.haman.audio

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.util.Log
import kotlin.math.log10
import kotlin.math.sqrt

/**
 * Microphone capture tuned for level-faithful analysis.
 *
 * The audio *source* matters more than it looks. MediaRecorder.AudioSource.MIC applies
 * automatic gain control, which amplifies a quiet distant cough until it looks like a
 * near one - destroying the level evidence the proximity prior in the attribution layer
 * depends on. UNPROCESSED is requested when the device advertises it, falling back to
 * VOICE_RECOGNITION (AGC off on most devices) and only then to MIC. Which one was
 * actually used is reported so it can be recorded with the session; results are not
 * comparable across sources.
 */
class AudioCapture(
    private val context: Context,
    private val sampleRate: Int = 16000,
) {
    enum class Source { UNPROCESSED, VOICE_RECOGNITION, MIC }

    private var record: AudioRecord? = null
    @Volatile private var running = false

    var activeSource: Source = Source.MIC
        private set

    /** True when the device confirms it can deliver an unprocessed signal path. */
    fun supportsUnprocessed(): Boolean {
        val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        return am.getProperty(AudioManager.PROPERTY_SUPPORT_AUDIO_SOURCE_UNPROCESSED) == "true"
    }

    @SuppressLint("MissingPermission") // caller holds RECORD_AUDIO; enforced by the service
    fun start(): Boolean {
        val minBuf = AudioRecord.getMinBufferSize(
            sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBuf <= 0) {
            Log.e(TAG, "getMinBufferSize failed: $minBuf")
            return false
        }
        // A generous buffer: this thread must survive being descheduled while the
        // device is dozing without dropping audio.
        val bufferSize = maxOf(minBuf * 4, sampleRate) // >= 1 s

        val candidates = buildList {
            if (supportsUnprocessed()) add(Source.UNPROCESSED to MediaRecorder.AudioSource.UNPROCESSED)
            add(Source.VOICE_RECOGNITION to MediaRecorder.AudioSource.VOICE_RECOGNITION)
            add(Source.MIC to MediaRecorder.AudioSource.MIC)
        }

        for ((label, source) in candidates) {
            val r = try {
                AudioRecord(source, sampleRate, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, bufferSize)
            } catch (e: Exception) {
                Log.w(TAG, "source $label unavailable", e); null
            }
            if (r != null && r.state == AudioRecord.STATE_INITIALIZED) {
                record = r
                activeSource = label
                r.startRecording()
                running = true
                Log.i(TAG, "capture started on $label at $sampleRate Hz")
                return true
            }
            r?.release()
        }
        Log.e(TAG, "no usable audio source")
        return false
    }

    /**
     * Blocking read loop. Runs on a dedicated thread owned by the caller.
     * @param onAudio receives raw PCM plus the running absolute sample position.
     */
    fun readLoop(onAudio: (ShortArray, Int) -> Unit) {
        val r = record ?: return
        val chunk = ShortArray(sampleRate / 10) // 100 ms
        while (running) {
            val n = r.read(chunk, 0, chunk.size)
            if (n > 0) {
                onAudio(chunk, n)
            } else if (n == AudioRecord.ERROR_INVALID_OPERATION || n == AudioRecord.ERROR_DEAD_OBJECT) {
                // The mic was taken - a phone call, or another app with priority.
                // Surfacing this rather than spinning is what lets the service log an
                // explicit gap instead of silently losing hours.
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

        /** Convert 16-bit PCM to normalised floats in [-1, 1]. */
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
