package com.haman.sleep.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import com.haman.sleep.data.Prefs
import com.haman.sleep.service.MonitorState

/** State for the native Diagnostics screen, the one native screen left: everything else
 *  is the web interface (MainActivity). */
class MainViewModel(app: Application) : AndroidViewModel(app) {
    val prefs = Prefs(app)
    val live = MonitorState.state
}
