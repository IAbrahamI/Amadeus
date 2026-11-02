package io.github.iabrahami.amadeus.link

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import io.github.iabrahami.amadeus.AmadeusApp

/** After the phone restarts: reconnect to Amadeus if this phone is paired and calls are on. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val store = (ctx.applicationContext as AmadeusApp).store
        if (intent.action == Intent.ACTION_BOOT_COMPLETED && store.paired && store.calls) LinkService.start(ctx)
    }
}
