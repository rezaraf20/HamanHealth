package com.haman.sleep.data

import android.content.Context
import com.haman.domain.ProximityCalibration

/**
 * A handful of scalar settings, read synchronously from the capture thread.
 *
 * SharedPreferences rather than DataStore on purpose: these are read once at session
 * start from inside the capture loop, and DataStore's Flow API would mean suspending
 * plumbing through the service for no benefit at this size.
 */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("haman", Context.MODE_PRIVATE)

    fun readSensitivity(): Float = sp.getFloat(KEY_SENSITIVITY, 0.5f)
    fun writeSensitivity(v: Float) = sp.edit().putFloat(KEY_SENSITIVITY, v).apply()

    fun readKeepClips(): Boolean = sp.getBoolean(KEY_KEEP_CLIPS, true)
    fun writeKeepClips(v: Boolean) = sp.edit().putBoolean(KEY_KEEP_CLIPS, v).apply()

    fun readRetentionDays(): Int = sp.getInt(KEY_RETENTION_DAYS, 14)
    fun writeRetentionDays(v: Int) = sp.edit().putInt(KEY_RETENTION_DAYS, v).apply()

    fun readCalibration(): ProximityCalibration? {
        val n = sp.getInt(KEY_CAL_COUNT, 0)
        if (n < ProximityCalibration.MIN_SAMPLES) return null
        return ProximityCalibration(
            meanDb = sp.getFloat(KEY_CAL_MEAN, -30f),
            sdDb = sp.getFloat(KEY_CAL_SD, 5f),
            sampleCount = n,
        )
    }

    fun writeCalibration(c: ProximityCalibration?) {
        if (c == null) { sp.edit().remove(KEY_CAL_COUNT).apply(); return }
        sp.edit()
            .putFloat(KEY_CAL_MEAN, c.meanDb)
            .putFloat(KEY_CAL_SD, c.sdDb)
            .putInt(KEY_CAL_COUNT, c.sampleCount)
            .apply()
    }

    private companion object {
        const val KEY_SENSITIVITY = "sensitivity"
        const val KEY_KEEP_CLIPS = "keep_clips"
        const val KEY_RETENTION_DAYS = "retention_days"
        const val KEY_CAL_MEAN = "cal_mean_db"
        const val KEY_CAL_SD = "cal_sd_db"
        const val KEY_CAL_COUNT = "cal_count"
    }
}
