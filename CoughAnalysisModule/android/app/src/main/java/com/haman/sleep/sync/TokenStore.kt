package com.haman.sleep.sync

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** The login the background upload uses: handed over by the web layer via setAuth. */
@Serializable
data class AuthTokens(val baseUrl: String, val access: String, val refresh: String)

/**
 * Stores [AuthTokens] encrypted with an AES-GCM key that lives in the Android Keystore
 * (it never leaves the secure hardware and is not part of any backup). Only the
 * ciphertext reaches SharedPreferences. Tokens are never logged.
 *
 * Not EncryptedSharedPreferences: that library is deprecated, and this is all of it
 * that is needed here.
 */
class TokenStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("haman_auth", Context.MODE_PRIVATE)

    @Synchronized
    fun read(): AuthTokens? {
        val blob = prefs.getString(KEY_BLOB, null) ?: return null
        return runCatching {
            val bytes = Base64.decode(blob, Base64.NO_WRAP)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, IV_BYTES))
            val plain = cipher.doFinal(bytes, IV_BYTES, bytes.size - IV_BYTES)
            Json.decodeFromString<AuthTokens>(plain.decodeToString())
        }.getOrElse {
            // Key gone (e.g. device restored from backup) or data damaged: signed out.
            prefs.edit().remove(KEY_BLOB).apply()
            null
        }
    }

    @Synchronized
    fun write(tokens: AuthTokens) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val ct = cipher.doFinal(Json.encodeToString(AuthTokens.serializer(), tokens).encodeToByteArray())
        prefs.edit().putString(KEY_BLOB, Base64.encodeToString(cipher.iv + ct, Base64.NO_WRAP)).commit()
    }

    @Synchronized
    fun clear() { prefs.edit().remove(KEY_BLOB).commit() }

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (ks.getEntry(ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE).apply {
            init(
                KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build()
            )
        }.generateKey()
    }

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val ALIAS = "haman_auth_tokens"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
        const val KEY_BLOB = "tokens"
    }
}
