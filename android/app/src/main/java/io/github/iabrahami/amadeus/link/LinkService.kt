package io.github.iabrahami.amadeus.link

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.lifecycle.LifecycleService
import io.github.iabrahami.amadeus.AmadeusApp
import io.github.iabrahami.amadeus.data.AmadeusApi
import io.github.iabrahami.amadeus.data.DeviceStore
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import org.json.JSONObject

/**
 * The live link: one quiet connection to your PC over Tailscale (/api/stream, server-sent events). When Amadeus
 * would call you on the PC, the event arrives here and becomes a call on the phone. No Google push involved.
 * Reconnects by itself (PC asleep, private mode, no network) with growing pauses, so the battery isn't drained.
 */
class LinkService : LifecycleService() {
    private var source: EventSource? = null
    private var backoff = 5_000L
    private val main = Handler(Looper.getMainLooper())
    private lateinit var api: AmadeusApi
    private lateinit var store: DeviceStore
    private lateinit var app: AmadeusApp

    override fun onCreate() {
        super.onCreate()
        app = application as AmadeusApp
        api = app.api
        store = app.store
        startForeground(Notifications.STATUS_ID, Notifications.link(this),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        if (!store.paired || !store.calls) { stopSelf(); return START_NOT_STICKY }
        if (source == null) connect()
        return START_STICKY
    }

    private fun connect() {
        val req = runCatching { api.request("/api/stream").header("Accept", "text/event-stream").build() }.getOrNull()
            ?: return stopSelf()
        source = EventSources.createFactory(api.http).newEventSource(req, object : EventSourceListener() {
            override fun onOpen(eventSource: EventSource, response: Response) {
                backoff = 5_000L
            }

            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                val d = JSONObject(data)
                when (type) {
                    "amadeus" -> when {
                        store.alreadyShown(d.optString("id")) -> {}
                        app.inApp -> app.update()                                    // you're in the app: it just refreshes
                        d.optBoolean("call") -> Calls.incoming(this@LinkService, d)  // important: it calls
                        else -> Notifications.note(this@LinkService, d)              // approvals, questions, jobs: a notification
                    }
                    "gone" -> { Calls.gone(this@LinkService, d.optString("id")); app.update() }   // handled elsewhere
                    "answered" -> Calls.hangUp(this@LinkService)                     // you picked up on the PC
                }
            }

            override fun onClosed(eventSource: EventSource) = retry("Your PC closed the connection")

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                if (response?.code == 401) {
                    source = null
                    main.post { stopSelf() }
                    return
                }
                retry("PC off or in private mode")
            }
        })
    }

    @Suppress("UNUSED_PARAMETER")
    private fun retry(why: String) {
        source = null
        main.postDelayed({ if (source == null && store.paired && store.calls) connect() }, backoff)
        backoff = (backoff * 2).coerceAtMost(15 * 60_000L)
    }


    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        source?.cancel()
        source = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent): IBinder? = super.onBind(intent)

    companion object {
        fun start(ctx: Context) = ctx.startForegroundService(Intent(ctx, LinkService::class.java))
        fun stop(ctx: Context) = ctx.stopService(Intent(ctx, LinkService::class.java))
    }
}
