package com.haman.data

import com.haman.domain.AcousticClass
import com.haman.domain.AttributionEngine
import com.haman.domain.AttributionFeatures
import com.haman.domain.DetectedEvent
import com.haman.domain.EmbeddingCodec
import com.haman.domain.LogisticHead
import com.haman.domain.ProximityCalibration
import com.haman.domain.PrototypeAttributor
import com.haman.domain.SubjectLabel

/**
 * Rebuilds the attribution model from whatever labels the user has given so far.
 *
 * Two regimes, because the right estimator depends on how much data exists: below
 * [LogisticHead.MIN_LABELS] a 1027-feature regression would just memorise the training
 * set, so a nearest-prototype rule generalises better. Above it, the regression can
 * also use the proximity features the prototype ignores.
 */
class AttributionStore(private val db: HamanDatabase) {

    suspend fun configure(engine: AttributionEngine, calibration: ProximityCalibration?) {
        engine.calibration = calibration

        val labelled = db.events().labelledWithEmbeddings()
        if (labelled.isEmpty()) {
            engine.prototypes = null
            engine.head = null
            return
        }

        val owner = mutableListOf<FloatArray>()
        val other = mutableListOf<FloatArray>()
        val features = mutableListOf<FloatArray>()
        val targets = mutableListOf<Int>()

        for (row in labelled) {
            val bytes = row.embedding ?: continue
            val scale = row.embeddingScale ?: continue
            val embedding = EmbeddingCodec.decode(bytes, scale)
            val isOwner = row.userLabel == SubjectLabel.SUBJECT.name

            if (isOwner) owner.add(embedding) else other.add(embedding)
            features.add(AttributionFeatures.build(row.toDomain(), embedding, calibration))
            targets.add(if (isOwner) 1 else 0)
        }

        engine.prototypes = PrototypeAttributor.build(owner, other)
        engine.head = if (features.size >= LogisticHead.MIN_LABELS) {
            LogisticHead.train(features, targets.toIntArray())
        } else null
    }

    /** How many usable attribution labels exist, for the calibration screen. */
    suspend fun labelCount(): Int = db.events().labelledWithEmbeddings().size

    private fun LabelledEvent.toDomain() = DetectedEvent(
        cls = AcousticClass.valueOf(cls),
        startMs = startedAtMs,
        endMs = endedAtMs,
        peakScore = peakScore,
        meanScore = meanScore,
        peakDb = peakDb,
        snrDb = snrDb,
        peakFrameMs = startedAtMs,
        boutId = boutId,
    )
}
