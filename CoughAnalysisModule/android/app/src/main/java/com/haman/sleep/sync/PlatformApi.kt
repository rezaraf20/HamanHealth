package com.haman.sleep.sync

import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * HTTP client for the platform upload (backend/docs/ANDROID_APP_TASK.md §4).
 *
 * Plain Kotlin + OkHttp, no Android classes, so every response the server can give is
 * covered by JVM tests against MockWebServer. Paths are relative to the baseUrl the web
 * layer passes in setAuth (it already ends in /api); no host is hard-coded here.
 *
 * A 401 is answered once with POST /auth/refresh and a retry. If the refresh fails too,
 * the call returns [Outcome.SignedOut] and the caller waits for the next setAuth.
 */
class PlatformApi(
    private val tokens: Tokens,
    private val http: OkHttpClient = defaultClient(),
) {
    /** Where the current login comes from and where a refreshed one goes. */
    interface Tokens {
        fun read(): AuthTokens?
        fun write(tokens: AuthTokens)
    }

    sealed interface Outcome<out T> {
        data class Ok<T>(val value: T) : Outcome<T>
        /** No login, or the refresh token was rejected too. */
        data object SignedOut : Outcome<Nothing>
        /** The server refused this request for good (4xx other than 401). */
        data class Rejected(val code: Int, val body: String) : Outcome<Nothing>
        /** Network down, timeout, 5xx: try again later. */
        data class Transient(val reason: String) : Outcome<Nothing>
    }

    enum class ClipResult {
        /** 201: stored (or already stored). */
        STORED,
        /** 403: the user switched clips off. */
        CLIPS_OFF,
        /** 404: the server does not know the night or event; upload the night again. */
        UNKNOWN_NIGHT,
        /** 409: this night's clip limit is reached. */
        LIMIT_REACHED,
        /** 422: the file was rejected. */
        FILE_REJECTED,
    }

    /** POST /sessions/sync. Returns the server's session id. */
    fun syncNight(payloadJson: String): Outcome<Long> =
        call({ base -> Request.Builder().url("$base/sessions/sync").post(payloadJson.toRequestBody(JSON)) }) { r ->
            when (r.code) {
                200, 201 -> Outcome.Ok(json.parseToJsonElement(r.body.string()).let {
                    (it as JsonObject)["id"]!!.jsonPrimitive.long
                })
                else -> rejectedOrTransient(r)
            }
        }

    /** POST /sessions/{serverSessionId}/events/{deviceEventId}/clip, multipart "file". */
    fun uploadClip(serverSessionId: Long, deviceEventId: Long, wav: File): Outcome<ClipResult> =
        call({ base ->
            val body: RequestBody = MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("file", wav.name, wav.asRequestBody(WAV))
                .build()
            Request.Builder().url("$base/sessions/$serverSessionId/events/$deviceEventId/clip").post(body)
        }) { r ->
            when (r.code) {
                200, 201 -> Outcome.Ok(ClipResult.STORED)
                403 -> Outcome.Ok(ClipResult.CLIPS_OFF)
                404 -> Outcome.Ok(ClipResult.UNKNOWN_NIGHT)
                409 -> Outcome.Ok(ClipResult.LIMIT_REACHED)
                422 -> Outcome.Ok(ClipResult.FILE_REJECTED)
                // 503 = clips disabled on the server for now; 5xx = server trouble.
                else -> if (r.code >= 500) Outcome.Transient("HTTP ${r.code}") else rejectedOrTransient(r)
            }
        }

    /** GET /consent → audioClips (true when absent: the server's default). */
    fun audioClipsEnabled(): Outcome<Boolean> =
        call({ base -> Request.Builder().url("$base/consent").get() }) { r ->
            when (r.code) {
                200 -> Outcome.Ok(
                    (json.parseToJsonElement(r.body.string()) as JsonObject)["audioClips"]
                        ?.jsonPrimitive?.boolean ?: true
                )
                else -> rejectedOrTransient(r)
            }
        }

    /** Sends the request with the current access token; on 401 refreshes once and retries. */
    private fun <T> call(
        build: (baseUrl: String) -> Request.Builder,
        handle: (Response) -> Outcome<T>,
    ): Outcome<T> {
        var auth = tokens.read() ?: return Outcome.SignedOut
        var refreshed = false
        while (true) {
            val request = build(auth.baseUrl.trimEnd('/'))
                .header("Authorization", "Bearer ${auth.access}")
                .build()
            try {
                http.newCall(request).execute().use { r ->
                    if (r.code != 401) return handle(r)
                }
            } catch (e: IOException) {
                return Outcome.Transient(e.message ?: e.javaClass.simpleName)
            }
            if (refreshed) return Outcome.SignedOut
            auth = when (val next = refresh(auth)) {
                is Outcome.Ok -> next.value
                is Outcome.Transient -> return next
                else -> return Outcome.SignedOut
            }
            refreshed = true
        }
    }

    /** POST /auth/refresh {"refresh"} → new pair, stored for the next calls. */
    private fun refresh(auth: AuthTokens): Outcome<AuthTokens> {
        val request = Request.Builder()
            .url("${auth.baseUrl.trimEnd('/')}/auth/refresh")
            .post("""{"refresh":${json.encodeToString(String.serializer(), auth.refresh)}}""".toRequestBody(JSON))
            .build()
        return try {
            http.newCall(request).execute().use { r ->
                when {
                    r.code == 200 -> {
                        val body = json.parseToJsonElement(r.body.string()) as JsonObject
                        val next = auth.copy(
                            access = body["access"]!!.jsonPrimitive.content,
                            refresh = body["refresh"]?.jsonPrimitive?.content ?: auth.refresh,
                        )
                        tokens.write(next)
                        Outcome.Ok(next)
                    }
                    r.code >= 500 -> Outcome.Transient("refresh: HTTP ${r.code}")
                    else -> Outcome.SignedOut
                }
            }
        } catch (e: IOException) {
            Outcome.Transient(e.message ?: e.javaClass.simpleName)
        }
    }

    private fun rejectedOrTransient(r: Response): Outcome<Nothing> =
        if (r.code >= 500 || r.code == 408 || r.code == 429) Outcome.Transient("HTTP ${r.code}")
        else Outcome.Rejected(r.code, r.body.string().take(2000))

    companion object {
        private val JSON = "application/json".toMediaType()
        private val WAV = "audio/wav".toMediaType()
        private val json = Json { ignoreUnknownKeys = true }

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .build()
    }
}
