package io.github.iabrahami.amadeus.link

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.net.Uri
import android.os.Handler
import android.os.Looper
import io.github.iabrahami.amadeus.AmadeusApp

/**
 * The phone's own ringtone, played as a real ringtone: it follows your ring volume
 * and silent mode. Stops when you answer or decline (on the phone or the PC), or after a minute (missed call).
 */
object Ringer {
    private var player: MediaPlayer? = null
    private val main = Handler(Looper.getMainLooper())
    var ringing: Boolean = false
        private set

    fun start(ctx: Context) = main.post {
        if (player != null) return@post
        val app = ctx.applicationContext as AmadeusApp
        ringing = true
        player = runCatching {
            MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                setDataSource(app, android.media.RingtoneManager.getDefaultUri(android.media.RingtoneManager.TYPE_RINGTONE))
                isLooping = true
                setOnPreparedListener { if (ringing) it.start() }
                setOnErrorListener { _, _, _ -> stop(); true }
                prepareAsync()
            }
        }.getOrNull()
        main.postDelayed({ stop() }, 60_000)
    }

    fun stop() = main.post {
        ringing = false
        main.removeCallbacksAndMessages(null)
        player?.runCatching { stop() }
        player?.release()
        player = null
    }
}
