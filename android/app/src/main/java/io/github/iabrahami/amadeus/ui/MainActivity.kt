package io.github.iabrahami.amadeus.ui

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import io.github.iabrahami.amadeus.AmadeusApp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import io.github.iabrahami.amadeus.link.LinkService

/** The app: pairing on first start, then Amadeus. */
class MainActivity : ComponentActivity() {
    private var paired by mutableStateOf(false)
    /** A mail to open right away (its reminder about it was answered). */
    private var openMail by mutableStateOf<Long?>(null)
    /** Approvals to open right away (Adjust in a call). */
    private var openApprovals by mutableStateOf(false)
    private val notifyPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        hideSystemButtons()
        val store = (application as AmadeusApp).store
        paired = store.paired
        setContent {
            AmadeusTheme {
                if (paired) AmadeusAppUi(onUnpaired = { paired = false }, openMail = openMail, mailOpened = { openMail = null },
                    openApprovals = openApprovals, approvalsOpened = { openApprovals = false })
                else PairScreen(onPaired = { paired = true; connected() })
            }
        }
        intent?.getLongExtra("mail", -1L)?.takeIf { it > 0 }?.let { openMail = it }
        if (intent?.getBooleanExtra("approvals", false) == true) openApprovals = true
        if (paired) connected()
        // while you're in the app, tell the PC every 30 s: its window then stays quiet (you see everything here)
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.RESUMED) {
                while (true) {
                    if (paired) withContext(Dispatchers.IO) { runCatching { (application as AmadeusApp).api.appActive() } }
                    delay(30_000)
                }
            }
        }
    }

    /**
     * While the app is open, Android's own buttons (back, home, recent apps) are hidden, so they don't sit under the
     * app's menu. Swiping up from the bottom edge shows them for a moment, on top of the app, without moving it.
     */
    private fun hideSystemButtons() {
        WindowCompat.getInsetsController(window, window.decorView).apply {
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            hide(WindowInsetsCompat.Type.navigationBars())
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemButtons()  // back from another app or a dialog: hidden again
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        intent.getLongExtra("mail", -1L).takeIf { it > 0 }?.let { openMail = it }
        if (intent.getBooleanExtra("approvals", false)) openApprovals = true
    }

    /** Paired: ask once for notifications (its calls) and open the live link. */
    private fun connected() {
        if (Build.VERSION.SDK_INT >= 33) notifyPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        if ((application as AmadeusApp).store.calls) LinkService.start(this)
    }
}
