package io.github.iabrahami.amadeus.link

import android.content.Context
import io.github.iabrahami.amadeus.AmadeusApp
import kotlinx.coroutines.flow.MutableStateFlow
import org.json.JSONObject

/**
 * The call that is ringing right now, shared by the live link, the notification and the call screen.
 * Answering or declining on one device ends the call on the other (the PC window checks /api/call, the phone gets
 * "answered" / "gone" through the live link).
 */
object Calls {
    /** Events of the current call (id → event). Empty: nothing is ringing. */
    val ringing = MutableStateFlow<Map<String, JSONObject>>(emptyMap())

    fun incoming(ctx: Context, ev: JSONObject) {
        ringing.value = ringing.value + (ev.optString("id") to ev)
        Notifications.call(ctx, ev)
        Ringer.start(ctx)
    }

    /** One event was handled elsewhere (dashboard, PC window). */
    fun gone(ctx: Context, id: String) {
        Notifications.cancel(ctx, id)   // also a normal notification for it
        if (id !in ringing.value) return
        ringing.value = ringing.value - id
        if (ringing.value.isEmpty()) Ringer.stop()
    }

    /** Picked up or declined on this phone, or answered on the PC: the call ends here. */
    fun hangUp(ctx: Context, vararg ids: String) {
        Ringer.stop()
        (ids.toSet().ifEmpty { ringing.value.keys }).forEach { Notifications.cancel(ctx, it) }
        ringing.value.keys.forEach { Notifications.cancel(ctx, it) }
        ringing.value = emptyMap()
    }

    /** You answered on the phone: tell the PC (its window stops ringing). Call from a background thread. */
    fun answerOnPc(app: AmadeusApp) = runCatching { app.api.callAnswered() }

    /** "Later" on the phone: the PC stops ringing too; approvals keep waiting for you on the dashboard. */
    fun declineOnPc(app: AmadeusApp, eventJson: String) {
        app.api.callAnswered()
        val ev = JSONObject(eventJson)
        if (!(ev.optString("kind") == "approval" && ev.optString("status") == "pending")) app.api.markSeen(ev.optString("id"))
    }
}
