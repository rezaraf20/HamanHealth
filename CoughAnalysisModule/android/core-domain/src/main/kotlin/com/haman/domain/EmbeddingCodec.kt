package com.haman.domain

import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * int8 quantisation for stored embeddings.
 *
 * A raw 1024-d float embedding is 4 KB; at ~500 events a night that is 2 MB/night of
 * data whose only job is to feed the attribution layer. Symmetric int8 with a
 * per-vector scale cuts it to 1 KB with cosine similarity essentially unchanged, which
 * is all §4 depends on. Lives in core-domain so the evaluation harness quantises
 * identically - otherwise on-device and offline attribution would silently diverge.
 */
object EmbeddingCodec {
    fun encode(v: FloatArray): Quantized {
        var maxAbs = 0f
        for (x in v) { val a = abs(x); if (a > maxAbs) maxAbs = a }
        if (maxAbs < 1e-8f) return Quantized(ByteArray(v.size), 1f)
        val scale = maxAbs / 127f
        val out = ByteArray(v.size)
        for (i in v.indices) out[i] = (v[i] / scale).roundToInt().coerceIn(-127, 127).toByte()
        return Quantized(out, scale)
    }

    fun decode(q: ByteArray, scale: Float): FloatArray {
        val out = FloatArray(q.size)
        for (i in q.indices) out[i] = q[i] * scale
        return out
    }

    data class Quantized(val bytes: ByteArray, val scale: Float) {
        override fun equals(other: Any?): Boolean =
            other is Quantized && scale == other.scale && bytes.contentEquals(other.bytes)
        override fun hashCode(): Int = 31 * bytes.contentHashCode() + scale.hashCode()
    }
}
