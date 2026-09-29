package com.haman.audio

import android.content.Context
import android.util.Log
import com.haman.domain.SpectralStats

/**
 * Finds the microphone route on which *this* phone hears coughs best.
 *
 * Which Android audio source works best is device-specific and fails silently. Measured
 * on a Galaxy S23 with the same coughs played to each route (quiet level):
 *
 *   route              received peak   noise floor   median cough score
 *   VOICE_RECOGNITION     -29.5 dB       -78.9 dB          0.34
 *   UNPROCESSED           -47.0 dB       -78.7 dB          0.09
 *   CAMCORDER             -30.4 dB       -68.4 dB          0.57
 *
 * "Least processed" is not "best": UNPROCESSED applies no mic pre-gain, so coughs arrive
 * ~18 dB quieter against the same floor. VOICE_RECOGNITION suppresses noise and damages
 * coughs with it. CAMCORDER keeps room noise and the cough intact, and YAMNet copes with
 * noise far better than with processing. Bandwidth alone can't rank these, so the probe
 * scores each route with the model itself while the user coughs, and uses bandwidth only
 * as a secondary check.
 */
class AudioSourceProbe(private val context: Context) {

    data class Result(
        val route: AudioCapture.Route,
        val opened: Boolean,
        val rmsDb: Float = -160f,
        val bands: SpectralStats.Bands? = null,
        /** Mean of the two highest per-frame cough scores; null if no scorer was given. */
        val coughScore: Float? = null,
    ) {
        val inconclusive: Boolean get() = bands == null || bands.lowDb < MIN_LOW_BAND_DB
        val fullBand: Boolean get() = !inconclusive && !bands!!.looksBandLimited
    }

    /**
     * Blocking; run off the main thread.
     * @param scorer takes ~[secondsEach] of 16 kHz audio and returns a cough score. The
     *   app supplies it (this module cannot depend on the inference module).
     */
    fun probe(
        routes: List<AudioCapture.Route> = candidateRoutes(context),
        secondsEach: Float = 6f,
        scorer: ((FloatArray) -> Float)? = null,
        onProgress: (index: Int, total: Int, route: AudioCapture.Route?) -> Unit = { _, _, _ -> },
    ): List<Result> {
        val results = routes.mapIndexed { i, route ->
            onProgress(i, routes.size, route)
            measure(route, secondsEach, scorer)
        }
        onProgress(routes.size, routes.size, null)
        return results
    }

    private fun measure(route: AudioCapture.Route, seconds: Float, scorer: ((FloatArray) -> Float)?): Result {
        val rec = AudioCapture.open(route) ?: return Result(route, opened = false)
        return try {
            val total = (route.captureRate * seconds).toInt()
            val pcm = ShortArray(total)
            rec.startRecording()
            // Discard the first 300 ms: many HALs ramp gain or deliver a start-up click.
            val skip = ShortArray(route.captureRate * 3 / 10)
            var got = 0
            while (got < skip.size) { val n = rec.read(skip, got, skip.size - got); if (n <= 0) break; got += n }
            got = 0
            while (got < total) { val n = rec.read(pcm, got, total - got); if (n <= 0) break; got += n }
            rec.stop()

            val at16: ShortArray = if (route.captureRate == 48000) {
                val out = ShortArray(got / 3 + 4)
                out.copyOf(Decimator3().process(pcm, got, out))
            } else pcm.copyOf(got)
            val f = FloatArray(at16.size)
            AudioCapture.toFloat(at16, at16.size, f)
            Result(route, opened = true,
                rmsDb = AudioCapture.rmsDb(f),
                bands = SpectralStats.bands(f, AudioCapture.OUTPUT_RATE),
                coughScore = scorer?.invoke(f))
        } catch (e: Exception) {
            Log.w("AudioSourceProbe", "probe failed for $route", e)
            Result(route, opened = false)
        } finally {
            rec.release()
        }
    }

    companion object {
        const val MIN_LOW_BAND_DB = -95f
        /** Below this best score the user probably didn't cough; fall back to defaults. */
        const val MIN_USABLE_COUGH_SCORE = 0.3f
        /** Scores within this of the best are treated as ties, broken by default order. */
        const val TIE_MARGIN = 0.05f

        /** Every source at 16 kHz - including UNPROCESSED even when the phone doesn't
         *  advertise it, since on the S23 it opens anyway. */
        fun candidateRoutes(context: Context): List<AudioCapture.Route> =
            AudioCapture.Source.entries.map { AudioCapture.Route(it, AudioCapture.OUTPUT_RATE) }
                .sortedBy { AudioCapture.DEFAULT_ORDER.indexOf(it.source) }

        fun choose(results: List<Result>): AudioCapture.Route? {
            val opened = results.filter { it.opened }
            if (opened.isEmpty()) return null
            val rank = { r: Result -> AudioCapture.DEFAULT_ORDER.indexOf(r.route.source) }

            val scored = opened.filter { (it.coughScore ?: 0f) >= MIN_USABLE_COUGH_SCORE }
            if (scored.isNotEmpty()) {
                // Prefer full-band routes; a band-limited route only wins if nothing else heard it.
                val pool = scored.filter { !it.inconclusive && it.fullBand }.ifEmpty { scored }
                val best = pool.maxOf { it.coughScore!! }
                return pool.filter { it.coughScore!! >= best - TIE_MARGIN }.minBy(rank).route
            }
            // No usable coughs: the first full-band route in default order.
            return opened.filter { it.fullBand }.minByOrNull(rank)?.route
                ?: opened.minBy(rank).route
        }
    }
}
