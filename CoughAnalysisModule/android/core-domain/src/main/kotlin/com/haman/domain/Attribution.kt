package com.haman.domain

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.sqrt

/**
 * Deciding whether an event came from the phone's owner or from someone else in the room.
 *
 * Read docs/ARCHITECTURE.md §4 before changing anything here. The short version: this
 * is an open research problem, there is no setting that makes it exact, and the honest
 * output is a probability plus an UNKNOWN band rather than a hard verdict. Events are
 * never discarded on the strength of this — attribution is stored *beside* the event so
 * it can be revised or retrained later.
 */

/** Distribution of peak level for events known to come from the owner, learned during
 *  the "cough 5x from where you sleep" calibration step. */
data class ProximityCalibration(
    val meanDb: Float,
    val sdDb: Float,
    val sampleCount: Int,
) {
    companion object {
        const val MIN_SAMPLES = 3
        fun from(peakDbs: List<Float>): ProximityCalibration? {
            if (peakDbs.size < MIN_SAMPLES) return null
            val mean = peakDbs.average().toFloat()
            val varr = peakDbs.sumOf { val d = it - mean; (d * d).toDouble() } / peakDbs.size
            // Floor the sd: a user who coughs 5x identically would otherwise produce a
            // near-zero sd and reject every real event thereafter.
            val sd = maxOf(sqrt(varr).toFloat(), 3f)
            return ProximityCalibration(mean, sd, peakDbs.size)
        }
    }

    /**
     * P(owner | level), one-sided on purpose.
     *
     * Distance only ever makes a sound quieter, so a level at or above the calibrated
     * mean is not evidence against the owner — only unexpectedly *quiet* events are.
     */
    fun probabilityOwner(peakDb: Float): Float {
        if (peakDb >= meanDb) return 0.9f
        val z = (peakDb - meanDb) / sdDb
        return (0.9f * exp(-0.5f * z * z)).coerceIn(0.02f, 0.9f)
    }
}

/** L2-normalised mean embedding per label. Robust from ~10 labels, where a
 *  1024-dimensional logistic regression would simply memorise the training set. */
class PrototypeAttributor(
    private val ownerPrototype: FloatArray,
    private val otherPrototype: FloatArray?,
) {
    fun probabilityOwner(embedding: FloatArray): Float {
        val e = l2normalize(embedding)
        val simOwner = dot(e, ownerPrototype)
        val simOther = otherPrototype?.let { dot(e, it) } ?: 0f
        // Temperature-scaled softmax over two cosine similarities. 8f keeps the output
        // from saturating to 0/1 on what are typically similarities in the 0.5-0.9 band.
        val t = 8f
        val a = exp((simOwner * t).toDouble())
        val b = exp((simOther * t).toDouble())
        return (a / (a + b)).toFloat()
    }

    companion object {
        fun build(owner: List<FloatArray>, other: List<FloatArray>): PrototypeAttributor? {
            if (owner.isEmpty()) return null
            return PrototypeAttributor(
                ownerPrototype = centroid(owner),
                otherPrototype = if (other.isEmpty()) null else centroid(other),
            )
        }

        private fun centroid(vs: List<FloatArray>): FloatArray {
            val acc = FloatArray(vs[0].size)
            vs.forEach { v -> val n = l2normalize(v); for (i in acc.indices) acc[i] += n[i] }
            return l2normalize(acc)
        }
    }
}

/**
 * Logistic regression over [embedding ‖ proximity features], trained on device.
 *
 * Only used once enough labels exist ([MIN_LABELS]); below that the prototype
 * attributor generalises better. Strong L2 because 1027 features against ~50 examples
 * would otherwise fit noise perfectly.
 */
class LogisticHead(val weights: FloatArray, val bias: Float) {
    fun probabilityOwner(features: FloatArray): Float {
        var z = bias
        for (i in weights.indices) z += weights[i] * features[i]
        return (1f / (1f + exp(-z.toDouble()))).toFloat()
    }

    companion object {
        const val MIN_LABELS = 30

        fun train(
            features: List<FloatArray>,
            labels: IntArray, // 1 = owner, 0 = other
            epochs: Int = 200,
            lr: Float = 0.05f,
            l2: Float = 0.01f,
        ): LogisticHead? {
            if (features.isEmpty() || features.size != labels.size) return null
            if (labels.none { it == 1 } || labels.none { it == 0 }) return null // single-class
            val d = features[0].size
            val w = FloatArray(d)
            var b = 0f
            val n = features.size
            repeat(epochs) {
                val gw = FloatArray(d)
                var gb = 0f
                for (i in 0 until n) {
                    val x = features[i]
                    var z = b
                    for (j in 0 until d) z += w[j] * x[j]
                    val p = 1f / (1f + exp(-z.toDouble())).toFloat()
                    val err = p - labels[i]
                    for (j in 0 until d) gw[j] += err * x[j]
                    gb += err
                }
                for (j in 0 until d) w[j] -= lr * (gw[j] / n + l2 * w[j])
                b -= lr * (gb / n)
            }
            return LogisticHead(w, b)
        }
    }
}

/** Builds the feature vector both the prototype and the logistic head consume. */
object AttributionFeatures {
    fun build(event: DetectedEvent, embedding: FloatArray, cal: ProximityCalibration?): FloatArray {
        val e = l2normalize(embedding)
        val out = FloatArray(e.size + 3)
        System.arraycopy(e, 0, out, 0, e.size)
        // Scaled to roughly unit range so no single hand-built feature dominates the
        // 1024 embedding dimensions during gradient descent.
        out[e.size] = if (cal != null) ((event.peakDb - cal.meanDb) / cal.sdDb).coerceIn(-4f, 4f) else 0f
        out[e.size + 1] = (event.snrDb / 30f).coerceIn(-2f, 4f)
        out[e.size + 2] = (event.durationMs / 1000f).coerceIn(0f, 5f)
        return out
    }
}

/**
 * Combines whichever evidence is available into a single verdict.
 *
 * The UNKNOWN band is load-bearing: forcing a binary answer on weak evidence produces
 * confident-looking mistakes, and a user who sees those stops trusting the whole log.
 */
class AttributionEngine(
    var calibration: ProximityCalibration? = null,
    var prototypes: PrototypeAttributor? = null,
    var head: LogisticHead? = null,
    private val ownerThreshold: Float = 0.65f,
    private val otherThreshold: Float = 0.35f,
) {
    fun attribute(event: DetectedEvent, embedding: FloatArray?): Pair<SubjectLabel, Float> {
        val evidence = mutableListOf<Float>()

        calibration?.let { evidence.add(it.probabilityOwner(event.peakDb)) }

        if (embedding != null) {
            val h = head
            if (h != null) {
                evidence.add(h.probabilityOwner(AttributionFeatures.build(event, embedding, calibration)))
            } else {
                prototypes?.let { evidence.add(it.probabilityOwner(embedding)) }
            }
        }

        if (evidence.isEmpty()) return SubjectLabel.UNKNOWN to 0f

        // Average in log-odds space so two weak-but-agreeing signals reinforce, which
        // averaging raw probabilities would not do.
        val p = combineLogOdds(evidence)
        val label = when {
            p >= ownerThreshold -> SubjectLabel.SUBJECT
            p <= otherThreshold -> SubjectLabel.OTHER
            else -> SubjectLabel.UNKNOWN
        }
        return label to p
    }

    private fun combineLogOdds(ps: List<Float>): Float {
        var sum = 0.0
        ps.forEach { raw ->
            val p = raw.coerceIn(0.01f, 0.99f)
            sum += ln((p / (1 - p)).toDouble())
        }
        val avg = sum / ps.size
        return (1.0 / (1.0 + exp(-avg))).toFloat()
    }
}

internal fun l2normalize(v: FloatArray): FloatArray {
    var s = 0.0
    for (x in v) s += (x * x).toDouble()
    val n = sqrt(s).toFloat()
    if (n < 1e-8f || abs(n - 1f) < 1e-6f) return v.copyOf()
    val out = FloatArray(v.size)
    for (i in v.indices) out[i] = v[i] / n
    return out
}

internal fun dot(a: FloatArray, b: FloatArray): Float {
    var s = 0f
    val n = minOf(a.size, b.size)
    for (i in 0 until n) s += a[i] * b[i]
    return s
}
