package com.haman.sleep.sync

import com.haman.sleep.sync.PlatformApi.ClipResult
import com.haman.sleep.sync.PlatformApi.Outcome
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * The upload client against every response in ANDROID_APP_TASK.md §4.3 (clips), §4.2
 * (nights), §4.4 (consent) and the 401 → refresh → retry rule of §4.1.
 */
class PlatformApiTest {
    @get:Rule val tmp = TemporaryFolder()
    private lateinit var server: MockWebServer
    private lateinit var store: MemoryTokens
    private lateinit var api: PlatformApi
    private lateinit var clip: File

    private class MemoryTokens(var tokens: AuthTokens?) : PlatformApi.Tokens {
        override fun read() = tokens
        override fun write(tokens: AuthTokens) { this.tokens = tokens }
    }

    @Before fun setUp() {
        server = MockWebServer().apply { start() }
        store = MemoryTokens(AuthTokens(server.url("/api").toString(), "access-1", "refresh-1"))
        val http = OkHttpClient.Builder().readTimeout(1, TimeUnit.SECONDS).build()
        api = PlatformApi(store, http)
        clip = tmp.newFile("COUGH_1.wav").apply { writeBytes(ByteArray(44) + ByteArray(1000)) }
    }

    @After fun tearDown() { server.shutdown() }

    private fun respond(code: Int, body: String = "{}") =
        server.enqueue(MockResponse().setResponseCode(code).setBody(body))

    // ── §4.2 night ──────────────────────────────────────────────────────────────

    @Test fun night_201_returns_server_id_and_sends_bearer_json() {
        respond(201, """{"id": 4, "device_session_id": "i:1", "event_count": 2}""")
        assertEquals(Outcome.Ok(4L), api.syncNight("""{"device_session_id":"i:1"}"""))
        val req = server.takeRequest()
        assertEquals("/api/sessions/sync", req.path)
        assertEquals("POST", req.method)
        assertEquals("Bearer access-1", req.getHeader("Authorization"))
        assertTrue(req.getHeader("Content-Type")!!.startsWith("application/json"))
        assertEquals("""{"device_session_id":"i:1"}""", req.body.readUtf8())
    }

    @Test fun night_422_is_rejected_with_body_kept() {
        respond(422, """{"detail":"bad"}""")
        val r = api.syncNight("{}")
        assertTrue(r is Outcome.Rejected && r.code == 422 && r.body.contains("bad"))
    }

    @Test fun night_500_is_transient() {
        respond(500)
        assertTrue(api.syncNight("{}") is Outcome.Transient)
    }

    // ── §4.1 tokens ─────────────────────────────────────────────────────────────

    @Test fun on_401_refreshes_once_stores_new_tokens_and_retries() {
        respond(401)
        respond(200, """{"access":"access-2","refresh":"refresh-2","token_type":"bearer"}""")
        respond(201, """{"id": 7}""")
        assertEquals(Outcome.Ok(7L), api.syncNight("{}"))

        assertEquals("Bearer access-1", server.takeRequest().getHeader("Authorization"))
        val refresh = server.takeRequest()
        assertEquals("/api/auth/refresh", refresh.path)
        assertEquals("""{"refresh":"refresh-1"}""", refresh.body.readUtf8())
        assertEquals("Bearer access-2", server.takeRequest().getHeader("Authorization"))
        assertEquals("access-2", store.tokens!!.access)
        assertEquals("refresh-2", store.tokens!!.refresh)
    }

    @Test fun refresh_rejected_means_signed_out() {
        respond(401)
        respond(401, """{"detail":"Invalid or expired refresh token"}""")
        assertEquals(Outcome.SignedOut, api.syncNight("{}"))
        assertEquals(2, server.requestCount) // no third attempt
    }

    @Test fun still_401_after_refresh_means_signed_out_without_looping() {
        respond(401)
        respond(200, """{"access":"access-2","refresh":"refresh-2"}""")
        respond(401)
        assertEquals(Outcome.SignedOut, api.syncNight("{}"))
        assertEquals(3, server.requestCount)
    }

    @Test fun no_tokens_means_signed_out_without_a_request() {
        store.tokens = null
        assertEquals(Outcome.SignedOut, api.syncNight("{}"))
        assertEquals(0, server.requestCount)
    }

    // ── §4.3 clips: one test per row of the table ───────────────────────────────

    @Test fun clip_201_stored_as_multipart_file_part() {
        respond(201, """{"clip_anon_id":"1a6d"}""")
        assertEquals(Outcome.Ok(ClipResult.STORED), api.uploadClip(4, 12, clip))
        val req = server.takeRequest()
        assertEquals("/api/sessions/4/events/12/clip", req.path)
        assertTrue(req.getHeader("Content-Type")!!.startsWith("multipart/form-data"))
        val body = req.body.readUtf8()
        assertTrue(body.contains("""name="file"; filename="COUGH_1.wav""""))
        assertTrue(body.contains("Content-Type: audio/wav"))
        assertTrue("clip_started_at must not be sent", !body.contains("clip_started_at"))
    }

    @Test fun clip_401_refreshes_and_retries() {
        respond(401)
        respond(200, """{"access":"access-2","refresh":"refresh-2"}""")
        respond(201, """{"clip_anon_id":"x"}""")
        assertEquals(Outcome.Ok(ClipResult.STORED), api.uploadClip(4, 12, clip))
        assertEquals(3, server.requestCount)
    }

    @Test fun clip_403_clips_switched_off() {
        respond(403)
        assertEquals(Outcome.Ok(ClipResult.CLIPS_OFF), api.uploadClip(4, 12, clip))
    }

    @Test fun clip_404_night_unknown() {
        respond(404)
        assertEquals(Outcome.Ok(ClipResult.UNKNOWN_NIGHT), api.uploadClip(4, 12, clip))
    }

    @Test fun clip_409_limit_reached() {
        respond(409)
        assertEquals(Outcome.Ok(ClipResult.LIMIT_REACHED), api.uploadClip(4, 12, clip))
    }

    @Test fun clip_422_file_rejected() {
        respond(422)
        assertEquals(Outcome.Ok(ClipResult.FILE_REJECTED), api.uploadClip(4, 12, clip))
    }

    @Test fun clip_503_clips_disabled_is_retried_later() {
        respond(503)
        assertTrue(api.uploadClip(4, 12, clip) is Outcome.Transient)
    }

    @Test fun clip_5xx_is_transient() {
        respond(502)
        assertTrue(api.uploadClip(4, 12, clip) is Outcome.Transient)
    }

    @Test fun clip_timeout_is_transient() {
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        assertTrue(api.uploadClip(4, 12, clip) is Outcome.Transient)
    }

    @Test fun no_network_is_transient() {
        server.shutdown()
        assertTrue(api.uploadClip(4, 12, clip) is Outcome.Transient)
        assertTrue(api.syncNight("{}") is Outcome.Transient)
    }

    // ── §4.4 consent ────────────────────────────────────────────────────────────

    @Test fun consent_reads_audio_clips_flag() {
        respond(200, """{"coughTracking":true,"audioClips":false}""")
        assertEquals(Outcome.Ok(false), api.audioClipsEnabled())
        assertEquals("/api/consent", server.takeRequest().path)
        respond(200, """{"audioClips":true}""")
        assertEquals(Outcome.Ok(true), api.audioClipsEnabled())
    }

    @Test fun base_url_with_trailing_slash_is_not_doubled() {
        store.tokens = store.tokens!!.copy(baseUrl = server.url("/api/").toString())
        respond(201, """{"id": 1}""")
        api.syncNight("{}")
        assertEquals("/api/sessions/sync", server.takeRequest().path)
    }
}
