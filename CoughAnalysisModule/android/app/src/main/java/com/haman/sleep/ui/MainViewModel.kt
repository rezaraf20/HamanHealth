package com.haman.sleep.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.haman.data.EventSummary
import com.haman.data.Exporter
import com.haman.data.HamanDatabase
import com.haman.data.LabelEntity
import com.haman.data.MinuteRollupEntity
import com.haman.data.SessionEntity
import com.haman.data.SnoreEpisodeEntity
import com.haman.sleep.data.Prefs
import com.haman.sleep.service.MonitorState
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.io.File

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val db = HamanDatabase.get(app)
    val prefs = Prefs(app)

    val live = MonitorState.state

    val sessions = db.sessions().observeAll()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val attributionLabelCount = db.labels().observeAttributionLabelCount()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), 0)

    init {
        // A session left 'running' means the process died mid-night - a killed service,
        // a crash, a reboot. Reconciling at startup keeps the history honest instead of
        // showing a night that has been recording for three days.
        viewModelScope.launch {
            db.sessions().running().forEach { s ->
                if (!MonitorState.state.value.running || MonitorState.state.value.sessionId != s.id) {
                    db.sessions().finish(
                        id = s.id, endedAt = s.startedAt, status = SessionEntity.STATUS_INTERRUPTED,
                        floor = s.noiseFloorDb, framesSeen = s.framesSeen,
                        framesInferred = s.framesInferred, micGapMs = s.micGapMs,
                    )
                }
            }
        }
    }

    fun events(sessionId: Long): Flow<List<EventSummary>> = db.events().observeSummaries(sessionId)
    fun rollups(sessionId: Long): Flow<List<MinuteRollupEntity>> = db.rollups().observeFor(sessionId)
    fun episodes(sessionId: Long): Flow<List<SnoreEpisodeEntity>> = db.episodes().observeFor(sessionId)

    fun label(eventId: Long, label: String) = viewModelScope.launch {
        db.labels().upsert(LabelEntity(eventId = eventId, userLabel = label,
            labeledAt = System.currentTimeMillis()))
    }

    fun clearLabel(eventId: Long) = viewModelScope.launch { db.labels().clearFor(eventId) }

    fun deleteSession(id: Long) = viewModelScope.launch {
        File(getApplication<Application>().filesDir, "clips/$id").deleteRecursively()
        db.sessions().delete(id)
    }

    fun export(sessionId: Long, onDone: (File?) -> Unit) = viewModelScope.launch {
        val dir = File(getApplication<Application>().getExternalFilesDir(null), "exports")
        val result = runCatching {
            Exporter.exportSessionCsv(db, sessionId, File(dir, "haman_session_$sessionId.csv"))
            Exporter.exportSessionJson(db, sessionId, File(dir, "haman_session_$sessionId.json"))
        }.getOrNull()
        onDone(result)
    }
}
