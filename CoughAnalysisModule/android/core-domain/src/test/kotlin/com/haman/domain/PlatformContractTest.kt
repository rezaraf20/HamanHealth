package com.haman.domain

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import java.io.File
import java.time.Instant
import java.time.format.DateTimeFormatter
import kotlin.random.Random

class PlatformContractTest {

    private val reference = DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSS'Z'")
        .withZone(java.time.ZoneOffset.UTC)

    @Test
    fun isoUtc_matches_java_time_everywhere() {
        val fixed = listOf(0L, -1L, 1_760_049_303_120L, 951_782_400_000L /* 2000-02-29 */,
            4_102_444_799_999L /* 2099-12-31T23:59:59.999 */, -62_135_596_800_000L /* year 1 */)
        val rnd = Random(42)
        (fixed + List(20_000) { rnd.nextLong(-2_000_000_000_000L, 5_000_000_000_000L) }).forEach { ms ->
            assertEquals("at $ms", reference.format(Instant.ofEpochMilli(ms)), PlatformContract.isoUtc(ms))
        }
    }

    @Test
    fun field_names_match_the_backend_schema() {
        val json = Json.parseToJsonElement(PlatformContract.encode(sample())).jsonObject
        // backend/app/schemas.py: SessionUploadRequest
        assertEquals(
            setOf("device_session_id", "started_at", "ended_at", "status", "timezone", "sensitivity",
                "device_model", "app_version", "audio_source", "noise_floor_db", "mic_gap_ms",
                "frames_seen", "frames_inferred", "detector_config", "events", "snore_episodes"),
            json.keys,
        )
        // CoughEventIn
        assertEquals(
            setOf("device_event_id", "event_type", "timestamp", "ended_at", "peak_at", "confidence",
                "mean_score", "peak_db", "snr_db", "bout_id", "subject_label", "subject_confidence",
                "user_label", "has_device_clip"),
            (json["events"]!!.jsonArray[0] as JsonObject).keys,
        )
        // SnoreEpisodeIn
        assertEquals(
            setOf("started_at", "ended_at", "snore_count", "mean_intensity_db"),
            (json["snore_episodes"]!!.jsonArray[0] as JsonObject).keys,
        )
        // The config travels as an object, not as a string with escaped JSON in it.
        assertEquals(true, json["detector_config"] is JsonObject)
    }

    @Test
    fun unlabelled_event_omits_user_label_instead_of_sending_null() {
        val json = PlatformContract.encode(sample().copy(events = listOf(sample().events[1])))
        assertFalse(json.contains("user_label"))
    }

    @Test
    fun sensitivity_levels() {
        assertEquals(null, PlatformContract.sensitivityLevel(null))
        assertEquals("low", PlatformContract.sensitivityLevel(0.1f))
        assertEquals("medium", PlatformContract.sensitivityLevel(0.5f))
        assertEquals("high", PlatformContract.sensitivityLevel(0.9f))
    }

    /** Also written to build/ so the backend can be tested against exactly this output. */
    @Test
    fun write_sample_for_backend_check() {
        File("build/platform-contract-sample.json").apply { parentFile.mkdirs() }
            .writeText(PlatformContract.encode(sample()))
    }

    private fun sample(): PlatformSessionUpload {
        val start = 1_760_043_600_000L // 2025-10-09T21:00:00Z
        return PlatformSessionUpload(
            deviceSessionId = "3f0c5c1e-6a4e-4b8e-9a51-1d0b0b7c2d11:17",
            startedAt = PlatformContract.isoUtc(start),
            endedAt = PlatformContract.isoUtc(start + 8 * 3_600_000L),
            status = "complete",
            timezone = "Europe/Amsterdam",
            sensitivity = PlatformContract.sensitivityLevel(0.5f),
            deviceModel = "samsung SM-S911B",
            appVersion = "0.2.0",
            audioSource = "CAMCORDER@48k",
            noiseFloorDb = -62.5f,
            micGapMs = 0,
            framesSeen = 60_000,
            framesInferred = 21_000,
            detectorConfig = PlatformContract.parseConfig(DetectorConfig.DEFAULT.toJson()),
            events = listOf(
                PlatformEvent("1", "cough", PlatformContract.isoUtc(start + 4_503_120),
                    PlatformContract.isoUtc(start + 4_504_560), PlatformContract.isoUtc(start + 4_503_600),
                    0.91f, 0.7f, -21.5f, 38f, 1, "subject", 0.8f, "not_an_event", true),
                PlatformEvent("2", "sneeze", PlatformContract.isoUtc(start + 9_000_000),
                    PlatformContract.isoUtc(start + 9_000_960), null,
                    0.7f, 0.6f, -30f, 25f, null, "unknown", 0f, null, false),
            ),
            snoreEpisodes = listOf(
                PlatformSnoreEpisode(PlatformContract.isoUtc(start + 10_800_000),
                    PlatformContract.isoUtc(start + 12_600_000), 400, -40f),
            ),
        )
    }
}
