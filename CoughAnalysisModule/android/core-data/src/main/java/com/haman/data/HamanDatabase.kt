package com.haman.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [
        SessionEntity::class,
        EventEntity::class,
        SnoreEpisodeEntity::class,
        MinuteRollupEntity::class,
        LabelEntity::class,
    ],
    version = 1,
    exportSchema = true,
)
abstract class HamanDatabase : RoomDatabase() {
    abstract fun sessions(): SessionDao
    abstract fun events(): EventDao
    abstract fun episodes(): EpisodeDao
    abstract fun rollups(): RollupDao
    abstract fun labels(): LabelDao
    abstract fun batch(): BatchDao

    companion object {
        @Volatile private var instance: HamanDatabase? = null

        fun get(context: Context): HamanDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext, HamanDatabase::class.java, "haman.db"
            )
                // WAL keeps the long-running writer from blocking UI reads.
                //
                // Set through the builder, NOT via execSQL("PRAGMA journal_mode=WAL").
                // That pragma RETURNS the resulting mode as a row, and execSQL rejects
                // any statement that returns data - it throws "Queries can be performed
                // using SQLiteDatabase query or rawQuery methods only" on the very first
                // database access, which is app startup. Assignment-only pragmas such as
                // synchronous below return nothing and are fine with execSQL.
                .setJournalMode(RoomDatabase.JournalMode.WRITE_AHEAD_LOGGING)
                // Foreign keys are deliberately not set here. Room enables them itself
                // when the schema declares any, and RoomDatabase.Callback has no
                // onConfigure hook - the only place SQLite reliably accepts the change.
                // DatabaseIntegrityTest asserts they really are on.
                .addCallback(object : RoomDatabase.Callback() {
                    override fun onOpen(db: SupportSQLiteDatabase) {
                        // NORMAL sync avoids an fsync per batch across a whole night.
                        // Safe under WAL: a crash can lose the last commits but cannot
                        // corrupt the database.
                        db.execSQL("PRAGMA synchronous=NORMAL")
                    }
                })
                .build().also { instance = it }
        }
    }
}
