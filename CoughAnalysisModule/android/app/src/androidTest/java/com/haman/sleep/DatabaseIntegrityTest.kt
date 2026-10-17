package com.haman.sleep

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.haman.data.EventEntity
import com.haman.data.HamanDatabase
import com.haman.data.PlatformPayload
import com.haman.data.SessionEntity
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Opens the real database.
 *
 * The app shipped with `execSQL("PRAGMA journal_mode=WAL")` in the Room open callback,
 * which throws because that pragma returns a row. It crashed on first database access -
 * app startup - and no JVM test touched SQLite, so nothing caught it. These tests open
 * the database and assert the pragmas actually took effect rather than assuming.
 */
@RunWith(AndroidJUnit4::class)
class DatabaseIntegrityTest {

    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun database_opens_without_throwing() {
        runBlocking {
            val db = HamanDatabase.get(context)
            // Forces the connection open so the Room callbacks actually run.
            db.sessions().running()
        }
    }

    @Test
    fun wal_and_foreign_keys_are_actually_enabled() {
        val db = HamanDatabase.get(context)
        db.openHelper.writableDatabase.query("PRAGMA journal_mode").use { c ->
            assertTrue(c.moveToFirst())
            assertEquals("wal", c.getString(0).lowercase())
        }
        db.openHelper.writableDatabase.query("PRAGMA foreign_keys").use { c ->
            assertTrue(c.moveToFirst())
            assertEquals("Room should enable foreign keys itself", 1, c.getInt(0))
        }
    }

    @Test
    fun a_session_and_its_events_round_trip(): Unit = runBlocking {
        val db = HamanDatabase.get(context)
        val id = db.sessions().insert(
            SessionEntity(
                startedAt = 1_000L, deviceModel = "test", appVersion = "test",
                audioSource = "VOICE_RECOGNITION", configJson = "{}",
            )
        )
        db.events().insertAll(
            listOf(
                EventEntity(sessionId = id, cls = "COUGH", startedAtMs = 1_100,
                    endedAtMs = 1_700, peakScore = 0.8f, meanScore = 0.7f,
                    peakDb = -30f, snrDb = 25f),
                EventEntity(sessionId = id, cls = "SNORE", startedAtMs = 2_000,
                    endedAtMs = 3_000, peakScore = 0.6f, meanScore = 0.5f,
                    peakDb = -35f, snrDb = 20f),
            )
        )
        assertEquals(2, db.events().countFor(id))
        assertEquals(2, db.events().forExport(id).size)

        // Cascade delete must take the events with it, or clearing a night leaves orphans.
        db.sessions().delete(id)
        assertEquals(0, db.events().countFor(id))
    }

    @Test
    fun platform_payload_reads_the_v2_columns(): Unit = runBlocking {
        val db = HamanDatabase.get(context)
        val id = db.sessions().insert(
            SessionEntity(
                startedAt = 1_760_043_600_000L, endedAt = 1_760_072_400_000L,
                deviceModel = "test", appVersion = "test", audioSource = "VOICE_RECOGNITION",
                configJson = "{}", status = SessionEntity.STATUS_COMPLETE,
                timezone = "Europe/Amsterdam", sensitivity = 0.5f,
            )
        )
        db.events().insertAll(
            listOf(
                EventEntity(sessionId = id, cls = "COUGH", startedAtMs = 1_760_048_103_120L,
                    endedAtMs = 1_760_048_104_560L, peakScore = 0.9f, meanScore = 0.7f,
                    peakDb = -21f, snrDb = 38f, boutId = 1, peakFrameMs = 1_760_048_103_600L,
                    clipPath = "/x.wav"),
                // Individual snores stay on the phone.
                EventEntity(sessionId = id, cls = "SNORE", startedAtMs = 1_760_050_000_000L,
                    endedAtMs = 1_760_050_001_000L, peakScore = 0.6f, meanScore = 0.5f,
                    peakDb = -35f, snrDb = 20f),
            )
        )
        val p = PlatformPayload.build(db, id, "install-1")!!
        assertEquals("install-1:$id", p.deviceSessionId)
        assertEquals("Europe/Amsterdam", p.timezone)
        assertEquals("medium", p.sensitivity)
        assertEquals(1, p.events.size)
        with(p.events.single()) {
            assertEquals("cough", eventType)
            assertEquals("2025-10-09T22:15:03.120Z", timestamp)
            assertEquals("2025-10-09T22:15:03.600Z", peakAt)
            assertTrue(hasDeviceClip)
        }
        db.sessions().delete(id)
    }
}
