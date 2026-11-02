package io.github.iabrahami.amadeus.link

import io.github.iabrahami.amadeus.assistantName
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.app.Person
import android.graphics.drawable.Icon
import android.os.Build
import io.github.iabrahami.amadeus.R
import io.github.iabrahami.amadeus.ui.CallActivity
import io.github.iabrahami.amadeus.ui.MainActivity
import org.json.JSONObject

/**
 * Its calls on the phone as real incoming calls, and the quiet "connected" status of the live link.
 */
object Notifications {
    const val CALLS = "her_calls"
    const val NEWS = "her_news"
    const val LINK = "link"
    const val STATUS_ID = 1

    fun createChannels(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        listOf("calls", "status").forEach { nm.deleteNotificationChannel(it) }   // channels of earlier versions
        nm.createNotificationChannel(NotificationChannel(CALLS, "Amadeus calls", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "When something important comes in: codes, urgent mail, reminders, the evening summary"
            setSound(null, null)  // Ringer plays its ringtone
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 400, 300, 400)
        })
        nm.createNotificationChannel(NotificationChannel(NEWS, "Amadeus notifications", NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "Approvals, questions from your work team, finished jobs"
        })
        // Android needs a notification for the live link; this channel is off, so you never see it
        nm.createNotificationChannel(NotificationChannel(LINK, "Live link (hidden)", NotificationManager.IMPORTANCE_NONE).apply {
            description = "Keeps the connection to your PC open. Hidden: the app shows the connection itself."
        })
    }

    private fun openApp(ctx: Context) = PendingIntent.getActivity(
        ctx, 0, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun link(ctx: Context): Notification =
        Notification.Builder(ctx, LINK)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(ctx.assistantName)
            .setContentText("Connected to your PC")
            .setContentIntent(openApp(ctx))
            .build()

    /** Not important enough for a call: a normal notification. On the lock screen it only says "Amadeus". */
    fun note(ctx: Context, ev: JSONObject) {
        val public = Notification.Builder(ctx, NEWS).setSmallIcon(R.drawable.ic_notify).setContentTitle(ctx.assistantName)
            .setContentText("Something for you").build()
        val n = Notification.Builder(ctx, NEWS)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(ev.optString("title", ctx.assistantName))
            .setContentText(ev.optString("body"))
            .setStyle(Notification.BigTextStyle().bigText(ev.optString("body")))
            .setContentIntent(openApp(ctx))
            .setVisibility(Notification.VISIBILITY_PRIVATE)
            .setPublicVersion(public)
            .setColor(0xFFE8A33A.toInt())
            .setAutoCancel(true)
            .build()
        ctx.getSystemService(NotificationManager::class.java).notify(ev.optString("id").hashCode(), n)
    }

    /**
     * Its call: a real incoming-call notification (Android's call style, "Amadeus" with Answer / Later), full screen
     * over the lock screen when allowed. The ringtone is played by Ringer, so it rings like a phone call.
     */
    fun call(ctx: Context, ev: JSONObject) {
        val id = ev.optString("id")
        fun screen(answer: Boolean) = PendingIntent.getActivity(ctx, (id + answer).hashCode(),
            Intent(ctx, CallActivity::class.java).putExtra("event", ev.toString()).putExtra("answer", answer)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val later = PendingIntent.getBroadcast(ctx, (id + "later").hashCode(),
            Intent(ctx, CallActionReceiver::class.java).putExtra("event", ev.toString()),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val b = Notification.Builder(ctx, CALLS)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(ctx.assistantName)
            .setContentText("Incoming call")      // like a normal call: why it's calling is in the app, after you unlock
            .setCategory(Notification.CATEGORY_CALL)
            .setContentIntent(screen(false))
            .setFullScreenIntent(screen(false), true)
            .setOngoing(true)
            .setColor(0xFFE8A33A.toInt())
            .setColorized(true)
        if (Build.VERSION.SDK_INT >= 31) {
            val caller = Person.Builder().setName(ctx.assistantName).setImportant(true)
                .setIcon(Icon.createWithResource(ctx, R.drawable.amadeus_logo)).build()
            b.setStyle(Notification.CallStyle.forIncomingCall(caller, later, screen(true)))
        } else {
            b.addAction(Notification.Action.Builder(null, "Later", later).build())
                .addAction(Notification.Action.Builder(null, "Answer", screen(true)).build())
        }
        ctx.getSystemService(NotificationManager::class.java).notify(id.hashCode(), b.build())
    }

    /** Android 14+: full-screen calls need your OK once (Settings → Apps → Amadeus → Full screen notifications). */
    fun canRingFullScreen(ctx: Context) =
        Build.VERSION.SDK_INT < 34 || ctx.getSystemService(NotificationManager::class.java).canUseFullScreenIntent()

    fun cancel(ctx: Context, eventId: String) =
        ctx.getSystemService(NotificationManager::class.java).cancel(eventId.hashCode())
}
