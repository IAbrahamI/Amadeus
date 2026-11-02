package io.github.iabrahami.amadeus

import android.app.Activity
import android.app.Application
import android.os.Bundle
import io.github.iabrahami.amadeus.data.AmadeusApi
import io.github.iabrahami.amadeus.data.DeviceStore
import io.github.iabrahami.amadeus.link.Notifications
import io.github.iabrahami.amadeus.ui.CallActivity
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/** App start: notification channels and the one connection to your PC. Also knows whether you're in the app right now. */
class AmadeusApp : Application() {
    lateinit var store: DeviceStore
    lateinit var api: AmadeusApi

    /** Open screens of the app (the call screen doesn't count): > 0 means you're in the app, so it doesn't ring. */
    private var visible = 0
    val inApp: Boolean get() = visible > 0

    /** Something new arrived from your PC while you're in the app: the screens refresh themselves. */
    private val _updates = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val updates = _updates.asSharedFlow()
    fun update() { _updates.tryEmit(Unit) }

    /** The assistant's name, avatar and ringtone as set on the PC (kept, so the app shows them even offline). */
    fun refreshIdentity() {
        if (!store.paired) return
        Thread {
            runCatching {
                val id = api.identity()
                store.assistantName = id.optString("name", "Amadeus").ifBlank { "Amadeus" }
                store.avatarSet = id.optString("avatar", "")
                store.ringtone = id.optJSONObject("voice")?.optString("ringtone", "") ?: ""
                update()
            }
        }.start()
    }

    override fun onCreate() {
        super.onCreate()
        store = DeviceStore(this)
        api = AmadeusApi(store)
        Notifications.createChannels(this)
        refreshIdentity()
        registerActivityLifecycleCallbacks(object : ActivityLifecycleCallbacks {
            override fun onActivityStarted(a: Activity) { if (a !is CallActivity) visible++ }
            override fun onActivityStopped(a: Activity) { if (a !is CallActivity) visible = (visible - 1).coerceAtLeast(0) }
            override fun onActivityCreated(a: Activity, b: Bundle?) {}
            override fun onActivityResumed(a: Activity) {}
            override fun onActivityPaused(a: Activity) {}
            override fun onActivitySaveInstanceState(a: Activity, b: Bundle) {}
            override fun onActivityDestroyed(a: Activity) {}
        })
    }
}

/** The assistant's name, as set on the PC (config "assistant_name"). */
val android.content.Context.assistantName: String get() = (applicationContext as AmadeusApp).store.assistantName
