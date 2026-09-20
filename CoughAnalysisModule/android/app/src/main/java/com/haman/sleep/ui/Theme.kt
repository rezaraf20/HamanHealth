package com.haman.sleep.ui

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

// A deliberately dim palette: this screen gets opened in a dark bedroom at 3am.
private val DarkColors = darkColorScheme(
    primary = Color(0xFF8AB4F8),
    secondary = Color(0xFF7FD1AE),
    tertiary = Color(0xFFF2B8B5),
    background = Color(0xFF0E1116),
    surface = Color(0xFF161A21),
)

private val LightColors = lightColorScheme(
    primary = Color(0xFF2E5AAC),
    secondary = Color(0xFF2A7F62),
    tertiary = Color(0xFFB3261E),
)

@Composable
fun HamanTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val context = LocalContext.current
    val scheme = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        dark -> DarkColors
        else -> LightColors
    }
    MaterialTheme(colorScheme = scheme, content = content)
}

/** Stable colour per event class, used by both the timeline and the event list so the
 *  same sound always reads the same way. */
object ClassColors {
    val cough = Color(0xFFE2725B)
    val sneeze = Color(0xFFE6B450)
    val snore = Color(0xFF6C9BD1)
    val neutral = Color(0xFF9AA0A6)
}
