package com.haman.sleep

import androidx.room.Room
import androidx.room.testing.MigrationTestHelper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.haman.data.EventEntity
import com.haman.data.HamanDatabase
import com.haman.data.PlatformPayload
import com.haman.data.SessionEntity
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
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

    // ── Schema v2 → v3 (upload state) ────────────────────────────────────────────
    // Keeps every night, event and label, and marks existing nights for upload. Uses
    // its own database file, never the app's real one.

    private val dbName = "migration-test.db"

    @get:Rule
    val helper = MigrationTestHelper(InstrumentationRegistry.getInstrumentation(), HamanDatabase::class.java)

    @Test
    fun v2_to_v3_keeps_sessions_events_and_labels(): Unit = runBlocking {
        helper.createDatabase(dbName, 2).use { db ->
            db.execSQL(
                "INSERT INTO sessions (id, startedAt, endedAt, deviceModel, appVersion, audioSource, " +
                "noiseFloorDb, configJson, status, framesSeen, framesInferred, micGapMs, timezone, sensitivity) " +
                "VALUES (7, 1760043600000, 1760072400000, 'SM-S911B', '0.2.0', 'CAMCORDER@48k', " +
                "-62.5, '{}', 'complete', 60000, 21000, 0, 'Europe/Amsterdam', 0.5)"
            )
            db.execSQL(
                "INSERT INTO events (id, sessionId, cls, startedAtMs, endedAtMs, peakScore, meanScore, " +
                "peakDb, snrDb, boutId, subjectLabel, subjectConfidence, clipPath, peakFrameMs) " +
                "VALUES (70, 7, 'COUGH', 1760048103120, 1760048104560, 0.9, 0.7, -21.0, 38.0, 1, " +
                "'SUBJECT', 0.8, '/data/clip.wav', 1760048103600)"
            )
            db.execSQL("INSERT INTO labels (id, eventId, userLabel, labeledAt) VALUES (1, 70, 'OTHER', 1760080000000)")
        }

        helper.runMigrationsAndValidate(dbName, 3, true, HamanDatabase.MIGRATION_2_3).close()

        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val room = Room.databaseBuilder(context, HamanDatabase::class.java, dbName)
            .addMigrations(HamanDatabase.MIGRATION_2_3).build()
        try {
            val s = room.sessions().byId(7)!!
            assertEquals("Europe/Amsterdam", s.timezone)
            assertEquals(60000L, s.framesSeen)
            // New upload state: not uploaded yet, marked for upload.
            assertNull(s.serverSessionId)
            assertTrue(s.uploadDirty)
            assertNull(s.uploadError)
            assertEquals(listOf(7L), room.sessions().pendingUpload())

            val e = room.events().byId(70)!!
            assertEquals("/data/clip.wav", e.clipPath)
            assertEquals(1760048103600L, e.peakFrameMs)
            assertNull(e.clipUpload)
            assertEquals(listOf(70L), room.events().pendingClips(7, listOf("COUGH", "SNEEZE")).map { it.id })

            // The label survived, and it still keeps the cough out of the user's count.
            assertEquals("OTHER", room.events().forExport(7).single().userLabel)
            assertEquals(0, room.events().countedCoughTimes(7).size)
        } finally {
            room.close()
            context.deleteDatabase(dbName)
        }
    }
}
