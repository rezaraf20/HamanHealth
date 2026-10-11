package com.haman.data

import com.haman.domain.AcousticClass
import com.haman.domain.PlatformContract
import com.haman.domain.PlatformContract.isoUtc
import com.haman.domain.PlatformContract.wireName
import com.haman.domain.PlatformEvent
import com.haman.domain.PlatformSessionUpload
import com.haman.domain.PlatformSnoreEpisode

/**
 * Builds the platform upload for one night from the local database.
 *
 * Sending is left to the host app (the Capacitor plugin in the platform), which owns
 * the login token and the network policy. This only answers "what exactly do we send",
 * so that answer lives next to the schema it reads from.
 */
object PlatformPayload {

    /**
     * @param installId random id generated once per app install and kept in app
     *   storage. Room ids restart at 1 after a reinstall, so the id alone would merge a
     *   new night into an old one on the server; prefixing the install id prevents that.
     * @return null if the session does not exist.
     */
    suspend fun build(db: HamanDatabase, sessionId: Long, installId: String): PlatformSessionUpload? {
        val s = db.sessions().byId(sessionId) ?: return null
        val events = db.events().forUpload(sessionId, PlatformContract.UPLOADED_CLASSES.map { it.name })
        val episodes = db.episodes().forSession(sessionId)

        return PlatformSessionUpload(
            deviceSessionId = deviceSessionId(installId, s.id),
            startedAt = isoUtc(s.startedAt),
            endedAt = s.endedAt?.let(::isoUtc),
            status = s.status,
            timezone = s.timezone,
            sensitivity = PlatformContract.sensitivityLevel(s.sensitivity),
            deviceModel = s.deviceModel,
            appVersion = s.appVersion,
            audioSource = s.audioSource,
            noiseFloorDb = s.noiseFloorDb,
            micGapMs = s.micGapMs,
            framesSeen = s.framesSeen,
            framesInferred = s.framesInferred,
            detectorConfig = PlatformContract.parseConfig(s.configJson),
            events = events.map { e ->
                PlatformEvent(
                    deviceEventId = e.id.toString(),
                    eventType = wireName(e.cls),
                    timestamp = isoUtc(e.startedAtMs),
                    endedAt = isoUtc(e.endedAtMs),
                    peakAt = e.peakFrameMs?.let(::isoUtc),
                    confidence = e.peakScore,
                    meanScore = e.meanScore,
                    peakDb = e.peakDb,
                    snrDb = e.snrDb,
                    boutId = if (e.cls == AcousticClass.COUGH.name) e.boutId else null,
                    subjectLabel = wireName(e.subjectLabel),
                    subjectConfidence = e.subjectConfidence,
                    userLabel = e.userLabel?.let(::wireName),
                    hasDeviceClip = e.hasClip,
                )
            },
            snoreEpisodes = episodes.map { ep ->
                PlatformSnoreEpisode(
                    startedAt = isoUtc(ep.startMs),
                    endedAt = isoUtc(ep.endMs),
                    snoreCount = ep.snoreCount,
                    meanIntensityDb = ep.meanIntensityDb,
                )
            },
        )
    }

    suspend fun buildJson(db: HamanDatabase, sessionId: Long, installId: String): String? =
        build(db, sessionId, installId)?.let(PlatformContract::encode)

    fun deviceSessionId(installId: String, sessionId: Long): String = "$installId:$sessionId"
}
