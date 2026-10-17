package com.haman.sleep

import android.os.Bundle
import com.getcapacitor.BridgeActivity
import com.haman.sleep.plugin.CoughSessionPlugin

/**
 * The app: a Capacitor WebView showing the web interface, loaded live from server.url
 * in web/capacitor.config.json (https://app.hamanhealth.com). The cough module is
 * reachable from it as the "CoughSession" plugin.
 *
 * The microphone diagnostics, which have no web equivalent yet, are [DiagnosticsActivity]
 * (long-press the app icon).
 */
class MainActivity : BridgeActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        // Must be registered before super.onCreate builds the bridge.
        registerPlugin(CoughSessionPlugin::class.java)
        super.onCreate(savedInstanceState)
    }
}
