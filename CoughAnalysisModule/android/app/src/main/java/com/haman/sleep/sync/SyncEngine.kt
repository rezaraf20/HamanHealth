package com.haman.sleep.sync

import android.content.Context
import com.haman.data.EventEntity
import com.haman.data.HamanDatabase
import com.haman.data.PlatformPayload
import com.haman.domain.PlatformContract
import com.haman.sleep.data.Prefs
import com.haman.sleep.sync.PlatformApi.ClipResult
import com.haman.sleep.sync.PlatformApi.Outcome
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File

/** What the web layer sees about uploading (cough-session.plugin.ts NativeSyncStatus). */
data class SyncStatus(
    val signedIn: Boolean,
    val pendingNights: Int,
    val lastSyncedAt: Long?,
    val lastError: String?,
)

/**
 * Uploads finished nights and their clips (backend/docs/ANDROID_APP_TASK.md §4).
 *
 * Per night: the night first (POST /sessions/sync, which keeps the server id), then,
 * if the user has clips on, each pending clip in turn. Every step's result is written to
 * Room immediately, so a restart continues where it stopped and nothing is sent twice.
 * Local data is never deleted or changed by an upload, only its upload state.
 *
 * One process-wide lock serialises everything: the worker and syncNow() never upload the
 * same night at the same time.
 */
class SyncEngine private constructor(context: Context) {
    private val app = context.applicationContext
    private val db = HamanDatabase.get(app)
    private val prefs = Prefs(app)
    private val tokenStore = TokenStore(app)
    private val state = app.getSharedPreferences("haman_sync", Context.MODE_PRIVATE)
    private val api = PlatformApi(object : PlatformApi.Tokens {
        override fun read() = tokenStore.read()
        override fun write(tokens: AuthTokens) = tokenStore.write(tokens)
    })
    private val lock = Mutex()

    enum class Result { DONE, RETRY, SIGNED_OUT }

    private val _status = MutableSharedFlow<SyncStatus>(extraBufferCapacity = 8, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    /** Emits after every upload attempt and when the pending count may have changed. */
    val statusUpdates: SharedFlow<SyncStatus> = _status

    val isSignedIn: Boolean get() = tokenStore.read() != null

    fun setAuth(tokens: AuthTokens) { tokenStore.write(tokens); clearError() }

    fun clearAuth() { tokenStore.clear() }

    suspend fun status(): SyncStatus = SyncStatus(
        signedIn = isSignedIn,
        pendingNights = db.sessions().countPendingUpload(),
        lastSyncedAt = state.getLong(KEY_LAST_SYNCED, 0).takeIf { it > 0 },
        lastError = state.getString(KEY_LAST_ERROR, null),
    )

    suspend fun publishStatus() { _status.tryEmit(status()) }

    /** Every pending night, oldest first. */
    suspend fun syncAll(): Result = lock.withLock {
        var result = Result.DONE
        for (id in db.sessions().pendingUpload()) {
            when (syncLocked(id)) {
                Result.SIGNED_OUT -> { result = Result.SIGNED_OUT; break }
                Result.RETRY -> result = Result.RETRY
                Result.DONE -> Unit
            }
        }
        result
    }.also { publishStatus() }

    suspend fun syncSession(sessionId: Long): Result =
        lock.withLock { syncLocked(sessionId) }.also { publishStatus() }

    private suspend fun syncLocked(sessionId: Long): Result {
        if (!isSignedIn) return Result.SIGNED_OUT
        val session = db.sessions().byId(sessionId) ?: return Result.DONE
        if (session.status == "running" || session.uploadError != null) return Result.DONE

        // 1. The night.
        var serverId = session.serverSessionId
        if (serverId == null || session.uploadDirty) {
            serverId = when (val r = uploadNight(sessionId)) {
                is Outcome.Ok -> r.value
                else -> return failed(r)
            }
        }

        // 2. Its clips, if the user has them on.
        val classes = PlatformContract.UPLOADED_CLASSES.map { it.name }
        val pending = db.events().pendingClips(sessionId, classes)
        if (pending.isNotEmpty()) {
            when (val consent = api.audioClipsEnabled()) {
                is Outcome.Ok -> if (!consent.value) {
                    db.events().setPendingClipsUpload(sessionId, classes, EventEntity.CLIP_SKIPPED)
                    return succeeded()
                }
                else -> return failed(consent)
            }
            var nightResent = false
            for (clip in pending) {
                val file = File(clip.clipPath)
                if (!file.exists()) {
                    // Local retention removed it: nothing to send, not an error.
                    db.events().setClipUpload(clip.id, EventEntity.CLIP_SKIPPED)
                    continue
                }
                var r = api.uploadClip(serverId!!, clip.id, file)
                if (r is Outcome.Ok && r.value == ClipResult.UNKNOWN_NIGHT && !nightResent) {
                    // The server lost or never got the night: send it again, retry once.
                    nightResent = true
                    serverId = when (val n = uploadNight(sessionId)) {
                        is Outcome.Ok -> n.value
                        else -> return failed(n)
                    }
                    r = api.uploadClip(serverId, clip.id, file)
                }
                when {
                    r !is Outcome.Ok -> return failed(r)
                    r.value == ClipResult.STORED -> db.events().setClipUpload(clip.id, EventEntity.CLIP_UPLOADED)
                    r.value == ClipResult.FILE_REJECTED -> db.events().setClipUpload(clip.id, EventEntity.CLIP_FAILED)
                    r.value == ClipResult.CLIPS_OFF || r.value == ClipResult.LIMIT_REACHED -> {
                        db.events().setPendingClipsUpload(sessionId, classes, EventEntity.CLIP_SKIPPED)
                        break
                    }
                    // Still unknown after re-sending the night: try again later.
                    r.value == ClipResult.UNKNOWN_NIGHT -> return failed(Outcome.Transient("clip: night unknown to server"))
                }
            }
        }
        return succeeded()
    }

    private suspend fun uploadNight(sessionId: Long): Outcome<Long> {
        val json = PlatformPayload.buildJson(db, sessionId, prefs.installId())
            ?: return Outcome.Rejected(0, "session $sessionId not found")
        return api.syncNight(json).also {
            when (it) {
                is Outcome.Ok -> db.sessions().markUploaded(sessionId, it.value, System.currentTimeMillis())
                // 422: the payload broke the contract. A bug; keep the body, never retry.
                is Outcome.Rejected -> db.sessions().markUploadRejected(sessionId, "HTTP ${it.code}: ${it.body}")
                else -> Unit
            }
        }
    }

    private fun succeeded(): Result {
        state.edit().putLong(KEY_LAST_SYNCED, System.currentTimeMillis()).remove(KEY_LAST_ERROR).apply()
        return Result.DONE
    }

    private fun failed(outcome: Outcome<*>): Result = when (outcome) {
        is Outcome.SignedOut -> { setError("Sign in again to upload"); Result.SIGNED_OUT }
        is Outcome.Transient -> { setError("Upload will retry: ${outcome.reason}"); Result.RETRY }
        is Outcome.Rejected -> { setError("Upload rejected (HTTP ${outcome.code})"); Result.DONE }
        is Outcome.Ok -> Result.DONE
    }

    private fun setError(message: String) { state.edit().putString(KEY_LAST_ERROR, message).apply() }
    private fun clearError() { state.edit().remove(KEY_LAST_ERROR).apply() }

    companion object {
        private const val KEY_LAST_SYNCED = "last_synced_at"
        private const val KEY_LAST_ERROR = "last_error"

        @Volatile private var instance: SyncEngine? = null
        fun get(context: Context): SyncEngine = instance ?: synchronized(this) {
            instance ?: SyncEngine(context).also { instance = it }
        }
    }
}
