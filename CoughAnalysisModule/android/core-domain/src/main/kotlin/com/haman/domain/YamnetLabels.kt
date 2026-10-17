package com.haman.domain

/**
 * Maps YAMNet's 521 AudioSet scores down to the five classes this app reasons about.
 *
 * Indices are fixed by models/yamnet_class_map.csv and verified by a unit test
 * against that file, so a future model swap cannot silently shift them.
 */
object YamnetLabels {
    const val BREATHING = 36
    const val SNORING = 38
    const val SNORT = 41
    const val COUGH = 42
    const val SNEEZE = 44

    /** AudioSet splits human speech across several labels; any of them means
     *  "someone is talking", which is what the speech suppressor needs. */
    private val SPEECH_INDICES = intArrayOf(0, 1, 2, 3, 4, 65)

    const val NUM_YAMNET_CLASSES = 521

    /**
     * Reduce a raw YAMNet score vector into per-[AcousticClass] scores.
     *
     * Snoring takes max(Snoring, Snort): AudioSet labels the sharp inhale at the end
     * of a snore cycle as "Snort", and dropping it would clip real snore events.
     */
    fun reduce(raw: FloatArray, out: FloatArray = FloatArray(AcousticClass.ALL.size)): FloatArray {
        require(raw.size == NUM_YAMNET_CLASSES) {
            "expected $NUM_YAMNET_CLASSES YAMNet scores, got ${raw.size}"
        }
        out[AcousticClass.COUGH.ordinal] = raw[COUGH]
        out[AcousticClass.SNEEZE.ordinal] = raw[SNEEZE]
        out[AcousticClass.SNORE.ordinal] = maxOf(raw[SNORING], raw[SNORT])
        out[AcousticClass.BREATHING.ordinal] = raw[BREATHING]
        var speech = 0f
        for (i in SPEECH_INDICES) if (raw[i] > speech) speech = raw[i]
        out[AcousticClass.SPEECH.ordinal] = speech
        return out
    }
}
