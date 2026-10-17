package com.haman.sleep.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.haman.data.HamanDatabase
import java.util.concurrent.TimeUnit

/** Uploads one night and its clips; WorkManager runs it when there is a network and
 *  retries it with backoff, also after the app was closed or the phone restarted. */
class UploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val sessionId = inputData.getLong(KEY_SESSION_ID, -1)
        if (sessionId < 0) return Result.failure()
        return when (SyncEngine.get(applicationContext).syncSession(sessionId)) {
            SyncEngine.Result.RETRY -> Result.retry()
            // Signed out: nothing to do until the next setAuth enqueues it again.
            SyncEngine.Result.SIGNED_OUT, SyncEngine.Result.DONE -> Result.success()
        }
    }

    companion object {
        const val KEY_SESSION_ID = "session_id"
    }
}

/** Where uploads get queued (ANDROID_APP_TASK.md §4.5). */
object SyncScheduler {
    private const val TAG = "haman-upload"

    /** A night just finished or changed: upload it, after any upload of it already queued. */
    fun enqueueSession(context: Context, sessionId: Long) =
        enqueue(context, sessionId, ExistingWorkPolicy.APPEND_OR_REPLACE)

    /** App start and setAuth: every night with something left to upload. */
    suspend fun enqueueAllPending(context: Context) {
        HamanDatabase.get(context).sessions().pendingUpload()
            .forEach { enqueue(context, it, ExistingWorkPolicy.KEEP) }
    }

    /** Sign-out: stop uploading. Local data and upload state stay. */
    fun cancelAll(context: Context) {
        WorkManager.getInstance(context).cancelAllWorkByTag(TAG)
    }

    private fun enqueue(context: Context, sessionId: Long, policy: ExistingWorkPolicy) {
        val request = OneTimeWorkRequestBuilder<UploadWorker>()
            .setInputData(workDataOf(UploadWorker.KEY_SESSION_ID to sessionId))
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .addTag(TAG)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork("upload-session-$sessionId", policy, request)
    }
}
