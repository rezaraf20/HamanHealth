package com.haman.audio

import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Minimal 16-bit PCM WAV writer. Clips are short and on-device only, so a container
 *  any tool can open beats a codec dependency. */
object WavWriter {
    fun write(file: File, samples: ShortArray, sampleRate: Int) {
        val dataBytes = samples.size * 2
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        header.put("RIFF".toByteArray())
        header.putInt(36 + dataBytes)
        header.put("WAVE".toByteArray())
        header.put("fmt ".toByteArray())
        header.putInt(16)            // PCM chunk size
        header.putShort(1)           // format = PCM
        header.putShort(1)           // channels = mono
        header.putInt(sampleRate)
        header.putInt(sampleRate * 2) // byte rate
        header.putShort(2)           // block align
        header.putShort(16)          // bits per sample
        header.put("data".toByteArray())
        header.putInt(dataBytes)

        val body = ByteBuffer.allocate(dataBytes).order(ByteOrder.LITTLE_ENDIAN)
        samples.forEach { body.putShort(it) }

        file.parentFile?.mkdirs()
        FileOutputStream(file).use {
            it.write(header.array())
            it.write(body.array())
        }
    }
}
