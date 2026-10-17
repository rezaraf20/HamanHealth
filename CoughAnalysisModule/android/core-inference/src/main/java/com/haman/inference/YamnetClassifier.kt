package com.haman.inference

import android.content.Context
import com.haman.domain.FrameInference
import org.tensorflow.lite.Interpreter
import java.io.Closeable
import java.io.FileInputStream
import java.nio.MappedByteBuffer
import java.nio.channels.FileChannel

/**
 * YAMNet on device.
 *
 * The model is the one ml/export_yamnet_tflite.py produces: a fixed 15600-sample input
 * (exactly one patch) returning both the 521 AudioSet scores and the 1024-d embedding.
 * The export verifies numerical parity with TF-Hub to ~1e-6, which is what lets
 * thresholds tuned on the desktop hold on the phone.
 */
class YamnetClassifier(
    context: Context,
    modelAsset: String = MODEL_ASSET,
    numThreads: Int = 2,
) : Closeable {

    private val interpreter: Interpreter
    private val scoresIndex: Int
    private val embeddingIndex: Int

    // Reused across every frame. At ~60,000 inferences a night, allocating these per
    // call would be a meaningful GC load on a device that is otherwise idle.
    //
    // All three are RANK 1, matching the exported model. ml/export_yamnet_tflite.py
    // returns scores[0] and embeddings[0], so the tensors are [15600], [521] and
    // [1024] - not [1, 15600] etc. Wrapping them in Array(1){...} makes TFLite throw
    // "Cannot copy from a TensorFlowLite tensor with shape [521] to a Java object with
    // shape [1, 521]" at the first inference. ModelInferenceTest guards this.
    private val input = FloatArray(FRAME_SAMPLES)
    private val scores = FloatArray(NUM_CLASSES)
    private val embedding = FloatArray(EMBEDDING_DIM)
    private val outputs = HashMap<Int, Any>()

    init {
        val options = Interpreter.Options().apply {
            setNumThreads(numThreads)
            // XNNPACK is on by default and is the fastest safe path here; NNAPI is
            // deprecated and its per-device behaviour is not worth the variance.
        }
        interpreter = Interpreter(loadModel(context, modelAsset), options)

        // Resolve outputs by shape rather than by index: the converter does not
        // guarantee output ordering, and silently swapping scores with the embedding
        // would produce plausible-looking nonsense.
        var si = -1
        var ei = -1
        for (i in 0 until interpreter.outputTensorCount) {
            when (interpreter.getOutputTensor(i).shape().last()) {
                NUM_CLASSES -> si = i
                EMBEDDING_DIM -> ei = i
            }
        }
        require(si >= 0 && ei >= 0) {
            "model does not expose both a [$NUM_CLASSES] score tensor and a [$EMBEDDING_DIM] embedding tensor"
        }
        scoresIndex = si
        embeddingIndex = ei
        outputs[scoresIndex] = scores
        outputs[embeddingIndex] = embedding
    }

    /**
     * @param frame exactly [FRAME_SAMPLES] mono samples in [-1, 1] at 16 kHz.
     * @return scores and embedding. Both arrays are freshly copied, because the caller
     *   caches embeddings past the lifetime of this call.
     */
    fun infer(frame: FloatArray): FrameInference {
        require(frame.size == FRAME_SAMPLES) {
            "expected $FRAME_SAMPLES samples, got ${frame.size}"
        }
        System.arraycopy(frame, 0, input, 0, FRAME_SAMPLES)
        interpreter.runForMultipleInputsOutputs(arrayOf<Any>(input), outputs)
        return FrameInference(scores.copyOf(), embedding.copyOf())
    }

    override fun close() = interpreter.close()

    private fun loadModel(context: Context, asset: String): MappedByteBuffer =
        context.assets.openFd(asset).use { fd ->
            FileInputStream(fd.fileDescriptor).use { fis ->
                // Memory-mapped, so the 15 MB of weights are never copied onto the heap.
                // Requires the .tflite to be stored uncompressed (see app/build.gradle.kts).
                fis.channel.map(FileChannel.MapMode.READ_ONLY, fd.startOffset, fd.declaredLength)
            }
        }

    companion object {
        const val MODEL_ASSET = "yamnet.tflite"
        const val FRAME_SAMPLES = 15600
        const val NUM_CLASSES = 521
        const val EMBEDDING_DIM = 1024
        const val SAMPLE_RATE = 16000
    }
}
