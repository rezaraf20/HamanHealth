package com.haman.data

import java.io.File

/**
 * CSV and JSON export.
 *
 * This module is meant to become part of a larger application, so the export format is
 * the contract: stable column names, epoch-millisecond timestamps, one row per event.
 * Embeddings and clip paths are deliberately excluded - they are device-local and
 * privacy-sensitive, and nothing downstream should depend on them.
 */
object Exporter {

    private const val HEADER =
        "session_id,event_id,class,started_at_ms,ended_at_ms,duration_ms," +
        "peak_score,mean_score,peak_db,snr_db,bout_id,subject_label,subject_confidence,user_label"

    suspend fun exportSessionCsv(db: HamanDatabase, sessionId: Long, out: File): File {
        val rows = db.events().forExport(sessionId)
        out.parentFile?.mkdirs()
        out.bufferedWriter().use { w ->
            w.appendLine(HEADER)
            rows.forEach { e ->
                w.appendLine(
                    listOf(
                        e.sessionId, e.id, e.cls, e.startedAtMs, e.endedAtMs,
                        e.endedAtMs - e.startedAtMs, e.peakScore, e.meanScore,
                        e.peakDb, e.snrDb, e.boutId ?: "",
                        e.subjectLabel, e.subjectConfidence, e.userLabel ?: "",
                    ).joinToString(",")
                )
            }
        }
        return out
    }

    suspend fun exportSessionJson(db: HamanDatabase, sessionId: Long, out: File): File {
        val session = db.sessions().byId(sessionId)
        val rows = db.events().forExport(sessionId)
        val episodes = db.episodes().totalSnoreMs(sessionId)
        out.parentFile?.mkdirs()
        out.bufferedWriter().use { w ->
            w.appendLine("{")
            w.appendLine("""  "session_id": $sessionId,""")
            w.appendLine("""  "started_at": ${session?.startedAt ?: 0},""")
            w.appendLine("""  "ended_at": ${session?.endedAt ?: 0},""")
            w.appendLine("""  "device_model": "${session?.deviceModel.orEmpty()}",""")
            w.appendLine("""  "audio_source": "${session?.audioSource.orEmpty()}",""")
            w.appendLine("""  "noise_floor_db": ${session?.noiseFloorDb ?: 0f},""")
            w.appendLine("""  "mic_gap_ms": ${session?.micGapMs ?: 0},""")
            w.appendLine("""  "total_snore_ms": $episodes,""")
            w.appendLine("""  "events": [""")
            rows.forEachIndexed { i, e ->
                val comma = if (i == rows.lastIndex) "" else ","
                w.appendLine(
                    """    {"id": ${e.id}, "class": "${e.cls}", "start_ms": ${e.startedAtMs}, """ +
                    """"end_ms": ${e.endedAtMs}, "peak_score": ${e.peakScore}, """ +
                    """"peak_db": ${e.peakDb}, "snr_db": ${e.snrDb}, """ +
                    """"bout_id": ${e.boutId ?: "null"}, "subject": "${e.subjectLabel}", """ +
                    """"subject_confidence": ${e.subjectConfidence}, """ +
                    """"user_label": ${e.userLabel?.let { "\"$it\"" } ?: "null"}}$comma"""
                )
            }
            w.appendLine("  ]")
            w.appendLine("}")
        }
        return out
    }
}
