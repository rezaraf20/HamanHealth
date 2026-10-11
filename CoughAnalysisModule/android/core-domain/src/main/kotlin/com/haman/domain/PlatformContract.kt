package com.haman.domain

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

/**
 * The upload contract with the HamanHealth platform backend:
 * `POST /api/sessions/sync` (backend/app/schemas.py, SessionUploadRequest).
 *
 * Field names here are the backend's, so this file is the single place to look when
 * either side changes. The backend accepts the same night any number of times and
 * merges on [PlatformEvent.deviceEventId], so the phone can re-send after a failed
 * request or after the user labels events the next morning.
 *
 * What is deliberately NOT here: embeddings and audio. Embeddings are a device-local
 * personalisation detail. Audio clips go through a separate, consent-gated endpoint
 * (`POST /api/sessions/{id}/events/{device_event_id}/clip`), never inside this payload.
 *
 * Timestamps are ISO 8601 in UTC with milliseconds ([isoUtc]); the backend rejects
 * timestamps without a zone.
 */
@Serializable
data class PlatformSessionUpload(
    @SerialName("device_session_id") val deviceSessionId: String,
    @SerialName("started_at") val startedAt: String,
    @SerialName("ended_at") val endedAt: String? = null,
    /** running | complete | interrupted */
    val status: String,
    val timezone: String? = null,
    /** low | medium | high — the exact thresholds are in [detectorConfig]. */
    val sensitivity: String? = null,
    @SerialName("device_model") val deviceModel: String,
    @SerialName("app_version") val appVersion: String,
    @SerialName("audio_source") val audioSource: String,
    @SerialName("noise_floor_db") val noiseFloorDb: Float,
    @SerialName("mic_gap_ms") val micGapMs: Long,
    @SerialName("frames_seen") val framesSeen: Long,
    @SerialName("frames_inferred") val framesInferred: Long,
    @SerialName("detector_config") val detectorConfig: JsonElement? = null,
    val events: List<PlatformEvent>,
    @SerialName("snore_episodes") val snoreEpisodes: List<PlatformSnoreEpisode>,
)

@Serializable
data class PlatformEvent(
    @SerialName("device_event_id") val deviceEventId: String,
    /** cough | sneeze | snore */
    @SerialName("event_type") val eventType: String,
    /** Event start. */
    val timestamp: String,
    @SerialName("ended_at") val endedAt: String,
    @SerialName("peak_at") val peakAt: String? = null,
    /** Peak model score, 0-1. */
    val confidence: Float,
    @SerialName("mean_score") val meanScore: Float,
    /** Magnitude: loudest frame in dBFS. Comparable within one device and mic route only. */
    @SerialName("peak_db") val peakDb: Float,
    @SerialName("snr_db") val snrDb: Float,
    @SerialName("bout_id") val boutId: Long? = null,
    /** Model's attribution guess: subject | other | unknown. */
    @SerialName("subject_label") val subjectLabel: String,
    @SerialName("subject_confidence") val subjectConfidence: Float,
    /** The user's verdict: subject | other | not_an_event, or null if not labelled. */
    @SerialName("user_label") val userLabel: String? = null,
    @SerialName("has_device_clip") val hasDeviceClip: Boolean,
)

@Serializable
data class PlatformSnoreEpisode(
    @SerialName("started_at") val startedAt: String,
    @SerialName("ended_at") val endedAt: String,
    @SerialName("snore_count") val snoreCount: Int,
    @SerialName("mean_intensity_db") val meanIntensityDb: Float,
)

object PlatformContract {
    /** Each saved clip starts this long before the event's peak frame. The server
     *  uses it to place the clip (and measurements taken from it) on the timeline. */
    const val CLIP_PRE_ROLL_MS = 750L

    /** Individual snores are not uploaded: hundreds a night, and the episode is what a
     *  report needs. They stay on the phone. */
    val UPLOADED_CLASSES = setOf(AcousticClass.COUGH, AcousticClass.SNEEZE)

    private val json = Json { explicitNulls = false; encodeDefaults = false }
    private val lenient = Json { ignoreUnknownKeys = true; isLenient = true }

    fun encode(upload: PlatformSessionUpload): String = json.encodeToString(upload)

    /** The stored detector config as a JSON object rather than a string inside JSON. */
    fun parseConfig(configJson: String): JsonElement? =
        runCatching { lenient.parseToJsonElement(configJson) }.getOrNull()

    /** Room stores enum names (COUGH, NOT_AN_EVENT); the API uses lowercase. */
    fun wireName(enumName: String): String = enumName.lowercase()

    /** Maps the 0-1 sensitivity dial onto the platform's three named levels. */
    fun sensitivityLevel(dial: Float?): String? = when {
        dial == null -> null
        dial < 1f / 3 -> "low"
        dial < 2f / 3 -> "medium"
        else -> "high"
    }

    /**
     * Epoch milliseconds → "2026-10-09T22:15:03.120Z".
     *
     * Written out instead of using java.time because this module must stay plain
     * Kotlin for the iOS port (docs/ARCHITECTURE.md §7).
     */
    fun isoUtc(epochMs: Long): String {
        val days = epochMs.floorDiv(86_400_000L)
        val msOfDay = epochMs.mod(86_400_000L)
        // Civil-from-days (H. Hinnant), proleptic Gregorian.
        val z = days + 719_468
        val era = z.floorDiv(146_097L)
        val doe = z - era * 146_097
        val yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365
        val doy = doe - (365 * yoe + yoe / 4 - yoe / 100)
        val mp = (5 * doy + 2) / 153
        val d = doy - (153 * mp + 2) / 5 + 1
        val m = if (mp < 10) mp + 3 else mp - 9
        val y = yoe + era * 400 + if (m <= 2) 1 else 0

        val h = msOfDay / 3_600_000
        val min = msOfDay / 60_000 % 60
        val s = msOfDay / 1000 % 60
        val ms = msOfDay % 1000
        fun pad(v: Long, n: Int) = v.toString().padStart(n, '0')
        return "${pad(y, 4)}-${pad(m, 2)}-${pad(d, 2)}T${pad(h, 2)}:${pad(min, 2)}:${pad(s, 2)}.${pad(ms, 3)}Z"
    }
}
