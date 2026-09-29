package com.haman.audio

import com.haman.audio.AudioCapture.Route
import com.haman.audio.AudioCapture.Source
import com.haman.domain.SpectralStats
import org.junit.Assert.assertEquals
import org.junit.Test

class AudioSourceProbeTest {
    private val fullBand = SpectralStats.Bands(lowDb = -50f, highDb = -65f)
    private val narrow = SpectralStats.Bands(lowDb = -50f, highDb = -110f)

    private fun r(src: Source, cough: Float?, bands: SpectralStats.Bands = fullBand, opened: Boolean = true) =
        AudioSourceProbe.Result(Route(src, 16000), opened, -40f, bands, cough)

    @Test
    fun `the route where coughs score highest wins`() {
        val pick = AudioSourceProbe.choose(listOf(
            r(Source.CAMCORDER, 0.55f), r(Source.VOICE_RECOGNITION, 0.85f), r(Source.MIC, 0.40f)))
        assertEquals(Source.VOICE_RECOGNITION, pick!!.source)
    }

    @Test
    fun `near-ties go to the earlier route in the default order`() {
        val pick = AudioSourceProbe.choose(listOf(
            r(Source.VOICE_RECOGNITION, 0.80f), r(Source.CAMCORDER, 0.78f)))
        assertEquals(Source.CAMCORDER, pick!!.source)
    }

    @Test
    fun `a band-limited route loses to a full-band one that also heard the coughs`() {
        val pick = AudioSourceProbe.choose(listOf(
            r(Source.VOICE_RECOGNITION, 0.90f, narrow), r(Source.CAMCORDER, 0.60f)))
        assertEquals(Source.CAMCORDER, pick!!.source)
    }

    @Test
    fun `without usable coughs the first full-band route in default order is used`() {
        val pick = AudioSourceProbe.choose(listOf(
            r(Source.CAMCORDER, 0.05f, narrow), r(Source.VOICE_RECOGNITION, 0.10f), r(Source.MIC, 0.02f)))
        assertEquals(Source.VOICE_RECOGNITION, pick!!.source)
    }

    @Test
    fun `routes that failed to open are ignored`() {
        val pick = AudioSourceProbe.choose(listOf(
            r(Source.CAMCORDER, 0.95f, opened = false), r(Source.MIC, 0.50f)))
        assertEquals(Source.MIC, pick!!.source)
    }
}
