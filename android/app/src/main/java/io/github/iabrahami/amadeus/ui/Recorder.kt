package io.github.iabrahami.amadeus.ui

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import java.io.File

/** Hold-to-talk: records a short voice message (Ogg/Opus) that goes only to your PC for speech-to-text. */
class Recorder(private val ctx: Context) {
    private var rec: MediaRecorder? = null
    private var file: File? = null

    fun start() {
        val f = File.createTempFile("ask", ".ogg", ctx.cacheDir)
        @Suppress("DEPRECATION")
        val r = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) MediaRecorder(ctx) else MediaRecorder()
        r.setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
        r.setOutputFormat(MediaRecorder.OutputFormat.OGG)
        r.setAudioEncoder(MediaRecorder.AudioEncoder.OPUS)
        r.setAudioSamplingRate(16000)
        r.setAudioChannels(1)
        r.setAudioEncodingBitRate(32000)
        r.setOutputFile(f.absolutePath)
        r.prepare()
        r.start()
        rec = r
        file = f
    }

    /** The recording, or null if it was too short. The file is deleted right away. */
    fun stop(): ByteArray? {
        val r = rec ?: return null
        val f = file
        rec = null
        file = null
        val ok = runCatching { r.stop() }.isSuccess
        r.release()
        val bytes = if (ok && f != null && f.length() > 2000) f.readBytes() else null
        f?.delete()
        return bytes
    }
}
