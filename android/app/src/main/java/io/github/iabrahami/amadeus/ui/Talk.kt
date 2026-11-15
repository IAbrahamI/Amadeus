package io.github.iabrahami.amadeus.ui

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.widget.Toast
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.iabrahami.amadeus.AmadeusApp
import io.github.iabrahami.amadeus.data.AmadeusApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import kotlin.coroutines.resume

/**
 * Today's chat with the assistant, the same one as the small window and the dashboard on the PC (one chat per day).
 * Home and Chat both show it; it lives as long as the app does. Answers are read aloud on the phone by the VOICE
 * setting: SPOKEN (when you talked to it, the default), ON (every answer) or OFF.
 */
class Talk(private val ctx: Context) {
    private val app get() = ctx.applicationContext as AmadeusApp
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    val lines = mutableStateListOf<AmadeusApi.Line>()
    var cid by mutableStateOf<String?>(null); private set
    var busy by mutableStateOf(false); private set
    var online by mutableStateOf<Boolean?>(null); private set
    var voiceMode by mutableStateOf(app.store.voiceMode)
    private val voice = Speaker(ctx)

    fun setVoice(mode: String) { voiceMode = mode; app.store.voiceMode = mode; if (mode == "off") voice.stop() }

    /** Loads today's chat (again): on start and whenever you come back to the app. */
    fun refresh() = scope.launch {
        if (busy) return@launch
        try {
            val (id, h) = withContext(Dispatchers.IO) { val id = app.api.quickChatId(); id to app.api.history(id) }
            cid = id
            lines.clear(); lines.addAll(h)
            online = true
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            online = false
        }
    }

    /** Sends what you said; spoken = you said it (speech to text). */
    fun send(text: String, spoken: Boolean = false, onDone: () -> Unit = {}) {
        val id = cid ?: return Toast.makeText(ctx, "Not connected to your PC yet", Toast.LENGTH_SHORT).show()
        if (text.isBlank() || busy) return
        val aloud = voiceMode == "always" || (voiceMode == "voice" && spoken)
        voice.stop()
        val now = System.currentTimeMillis() / 1000.0
        lines.add(AmadeusApi.Line(true, text, now))
        lines.add(AmadeusApi.Line(false, "…", now))
        busy = true
        CoreLink.mode = "think"
        var own = false
        var answer = ""
        scope.launch {
            try {
                withContext(Dispatchers.IO) {
                    app.api.chat(id, text, spoken, aloud, object : AmadeusApi.Stream {
                        override fun text(soFar: String) {
                            answer = soFar
                            scope.launch {
                                if (lines.isNotEmpty()) lines[lines.lastIndex] = lines.last().copy(text = soFar.ifBlank { "…" })
                                if (!aloud) { CoreLink.mode = "speak"; CoreLink.talk() }
                            }
                        }
                        override fun tool() { scope.launch { if (!voice.playing) CoreLink.mode = "think" } }
                        override fun approval(a: JSONObject) {
                            scope.launch { if (lines.isNotEmpty()) lines[lines.lastIndex] = lines.last().copy(text = "I need your OK first: " + plain(a.optString("summary"))) }
                        }
                        override fun mood(m: String) { AvatarState.mood = m }
                        override fun say(line: String) { if (aloud) { own = true; voice.say { app.api.tts(line, speech = true, limit = 2000) } } }
                        override fun sayLine(id: String) { if (aloud) voice.say { app.api.voiceLine(id) } }
                    })
                }
                online = true
                if (aloud && !own && answer.isNotBlank()) voice.say { app.api.tts(answer, speech = true, limit = 600) }  // the server makes it speakable and short
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (lines.isNotEmpty() && !lines.last().mine) lines[lines.lastIndex] = lines.last().copy(text = "That didn't work: ${e.message ?: "your PC didn't answer"}")
                if (e !is AmadeusApi.ApiError) online = false
            } finally {
                busy = false
                if (!voice.busy) CoreLink.mode = "idle"
                onDone()
            }
        }
    }

    // ---------- listening: tap the core (or the mic) and talk; it sends when you stop, or tap again ----------
    var listening by mutableStateOf(false); private set
    private val recorder = Recorder(ctx)
    private var watch: Job? = null

    /** Starts listening. auto = it ends by itself once you stop talking (tap); otherwise you end it (hold). */
    fun listen(auto: Boolean): Boolean {
        if (listening || busy) return false
        voice.stop()
        if (runCatching { recorder.start() }.isFailure) { Toast.makeText(ctx, "The microphone isn't available", Toast.LENGTH_SHORT).show(); return false }
        listening = true
        CoreLink.mode = "listen"
        if (auto) watch = scope.launch {
            var spoke = false; var quietSince = 0L; val start = System.currentTimeMillis()
            while (listening) {
                delay(120)
                val now = System.currentTimeMillis()
                if (recorder.level() > 2200) { spoke = true; quietSince = 0L } else if (quietSince == 0L) quietSince = now
                when {
                    spoke && quietSince > 0 && now - quietSince > 1300 -> { endListen(); break }   // you stopped talking
                    !spoke && now - start > 7000 -> { endListen(send = false); Toast.makeText(ctx, "I didn't hear anything", Toast.LENGTH_SHORT).show(); break }
                    now - start > 45_000 -> { endListen(); break }
                }
            }
        }
        return true
    }

    /** Stops listening; send = turn it into text on your PC and ask. */
    fun endListen(send: Boolean = true) {
        if (!listening) return
        watch?.cancel(); watch = null
        listening = false
        val audio = recorder.stop()
        if (!send || audio == null) {
            CoreLink.mode = "idle"
            if (send) Toast.makeText(ctx, "I didn't catch that", Toast.LENGTH_SHORT).show()
            return
        }
        CoreLink.mode = "think"
        scope.launch {
            val text = try { withContext(Dispatchers.IO) { app.api.stt(audio, "audio/ogg") } } catch (e: CancellationException) { throw e } catch (e: Exception) {
                Toast.makeText(ctx, e.message ?: "Couldn't reach your PC", Toast.LENGTH_LONG).show(); ""
            }
            if (text.isNotBlank()) send(text, spoken = true)
            else { CoreLink.mode = "idle"; Toast.makeText(ctx, "I didn't catch that", Toast.LENGTH_SHORT).show() }
        }
    }

    fun release() { endListen(send = false); voice.stop() }
}

/** Plays its spoken lines one after another (WAV from the PC), with a short breath in between. The core speaks along. */
class Speaker(private val ctx: Context) {
    private val queue = Channel<suspend () -> ByteArray?>(Channel.UNLIMITED)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var player: MediaPlayer? = null
    var playing = false; private set
    private var pending = 0
    val busy get() = playing || pending > 0
    private var gen = 0

    init {
        scope.launch {
            for (job in queue) {
                val g = gen
                val audio = try { withContext(Dispatchers.IO) { job() } } catch (e: CancellationException) { throw e } catch (e: Exception) {
                    Toast.makeText(ctx, "I couldn't speak that: ${e.message}", Toast.LENGTH_SHORT).show(); null
                }
                pending--
                if (audio == null || audio.isEmpty() || g != gen) { if (!busy) CoreLink.mode = "idle"; continue }
                play(audio)
                if (!busy) CoreLink.mode = "idle"
            }
        }
    }

    fun say(fetch: suspend () -> ByteArray?) { pending++; queue.trySend(fetch) }

    private var finish: (() -> Unit)? = null

    /** Stops what it says now and drops what was waiting. */
    fun stop() {
        gen++
        finish?.invoke()
    }

    private suspend fun play(audio: ByteArray) {
        val f = File(ctx.cacheDir, "say.wav").apply { writeBytes(audio) }
        playing = true
        CoreLink.mode = "speak"
        suspendCancellableCoroutine { cont ->
            val p = MediaPlayer()
            player = p
            fun done() {
                finish = null
                if (player === p) { p.runCatching { stop(); release() }; player = null }
                if (cont.isActive) cont.resume(Unit)
            }
            finish = ::done
            runCatching {
                p.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                p.setDataSource(f.path)
                p.setOnCompletionListener { done() }
                p.setOnErrorListener { _, _, _ -> done(); true }
                p.prepare()
                p.start()
            }.onFailure { done() }
            cont.invokeOnCancellation { p.runCatching { release() } }
        }
        // a voice pulse on the core while it plays is drawn by the speak mode; a short breath before the next line
        playing = false
        kotlinx.coroutines.delay(350)
        f.delete()
    }
}
