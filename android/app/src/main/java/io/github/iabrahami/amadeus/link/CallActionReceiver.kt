package io.github.iabrahami.amadeus.link

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import io.github.iabrahami.amadeus.AmadeusApp
import kotlin.concurrent.thread

/** "Later" on its call (in the notification or the call screen): stop ringing here and on the PC. */
class CallActionReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val ev = intent.getStringExtra("event") ?: return
        Calls.hangUp(ctx, ev)
        val pending = goAsync()
        thread {
            runCatching { Calls.declineOnPc(ctx.applicationContext as AmadeusApp, ev) }
            pending.finish()
        }
    }
}
