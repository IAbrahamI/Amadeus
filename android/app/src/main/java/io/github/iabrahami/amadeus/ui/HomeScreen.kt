package io.github.iabrahami.amadeus.ui

import io.github.iabrahami.amadeus.assistantName
import android.Manifest
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.runtime.DisposableEffect
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import io.github.iabrahami.amadeus.link.Notifications
import android.content.pm.PackageManager
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.res.painterResource
import androidx.core.content.ContextCompat
import io.github.iabrahami.amadeus.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.time.LocalTime

private data class Bubble(val mine: Boolean, val text: String)

/** Talking to the assistant: status, its face, what needs your OK, and the "Quick chat" you also have on the PC. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun HomeScreen(nav: Nav) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val home = load("home") { it.home() }
    val chat = remember { mutableStateListOf<Bubble>() }
    var cid by remember { mutableStateOf<String?>(null) }
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var recording by remember { mutableStateOf(false) }
    val recorder = remember { Recorder(ctx) }
    val list = rememberLazyListState()

    // the Quick chat: a fresh one after a quiet break (it keeps a recap of the earlier ones); checked whenever you come back
    var opened by remember { mutableIntStateOf(0) }
    var newChat by remember { mutableStateOf(false) }
    val owner0 = androidx.lifecycle.compose.LocalLifecycleOwner.current
    DisposableEffect(owner0) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) opened++ }
        owner0.lifecycle.addObserver(obs)
        onDispose { owner0.lifecycle.removeObserver(obs) }
    }
    LaunchedEffect(opened, newChat) {
        val fresh = newChat
        runCatching {
            withContext(Dispatchers.IO) {
                val id = if (fresh) ctx.api.newQuickChat() else ctx.api.quickChatId()
                id to ctx.api.history(id)
            }
        }.onSuccess { (id, h) ->
            if (id != cid || fresh) { cid = id; chat.clear(); chat.addAll(h.map { Bubble(it.first == "user", it.second) }) }
        }
        newChat = false
    }
    LaunchedEffect(chat.size, chat.lastOrNull()?.text?.length) { if (chat.isNotEmpty()) list.scrollToItem(chat.lastIndex) }

    fun send(text: String, voice: Boolean = false) {
        val id = cid ?: return Toast.makeText(ctx, "Not connected to your PC yet", Toast.LENGTH_SHORT).show()
        if (text.isBlank() || busy) return
        chat.add(Bubble(true, text))
        chat.add(Bubble(false, "…"))
        busy = true
        scope.io(ctx, done = { busy = false; home.reload() }) { api ->
            AvatarState.talking = true
            try {
                api.chat(id, text, voice, onText = { t -> scope.launch { chat[chat.lastIndex] = Bubble(false, t.ifBlank { "…" }) } },
                    onMood = { AvatarState.mood = it })
            } finally {
                AvatarState.talking = false
            }
        }
    }

    LaunchedEffect(nav.ask.value, cid) {
        val a = nav.ask.value ?: return@LaunchedEffect
        if (cid == null) return@LaunchedEffect
        nav.ask.value = null
        if (a.send) send(a.text) else input = a.text
    }

    val micPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (!ok) Toast.makeText(ctx, "Allow the microphone to talk to ${ctx.assistantName}", Toast.LENGTH_LONG).show()
    }

    val h = home.value.data
    val keyboard = WindowInsets.isImeVisible
    Column(Modifier.fillMaxSize().background(glow)) {
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 16.dp, top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(if (home.value.error == null) C.online else C.no))
            Text(if (home.value.error == null) "  Connected to your PC" else "  Can't reach your PC", color = C.soft, fontSize = 13.sp,
                modifier = Modifier.weight(1f).clickable { home.reload() })
            if (chat.isNotEmpty()) Text("New chat", color = C.accent, fontSize = 13.sp,
                modifier = Modifier.clickable(enabled = !busy) { newChat = true }.padding(horizontal = 10.dp, vertical = 12.dp))
            val voiceOn = h?.optString("voice") != "off"
            Box(Modifier.size(44.dp).clip(CircleShape).border(1.dp, C.line, CircleShape).background(C.card)
                .clickable { scope.io(ctx, done = { home.reload() }) { it.voice(!voiceOn) } }, contentAlignment = Alignment.Center) {
                Icon(if (voiceOn) Ico.mic else Ico.micOff, if (voiceOn) "Voice input on the PC is on" else "Voice input on the PC is off",
                    Modifier.size(20.dp), tint = if (voiceOn) C.accent else C.muted)
            }
        }

        // Android 14+: its calls only ring full screen (like a phone call) after you allow it once
        var fullScreenOk by remember { mutableStateOf(Notifications.canRingFullScreen(ctx)) }
        val owner = androidx.lifecycle.compose.LocalLifecycleOwner.current
        DisposableEffect(owner) {
            val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) fullScreenOk = Notifications.canRingFullScreen(ctx) }
            owner.lifecycle.addObserver(obs)
            onDispose { owner.lifecycle.removeObserver(obs) }
        }
        if (!fullScreenOk && Build.VERSION.SDK_INT >= 34) {
            Card(Modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp).clickable {
                ctx.startActivity(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:${ctx.packageName}")))
            }, border = C.accent) {
                Text("Let ${LocalContext.current.assistantName} call you like a phone call", fontWeight = FontWeight.SemiBold)
                Text("Tap, then allow \"Full screen notifications\" for the Amadeus app.", color = C.soft, fontSize = 13.sp)
            }
        }

        // The avatar: head and shoulders, its mood, its mouth moving while it answers.
        // While you type (keyboard open) it steps back to a small picture, so the chat and what you write stay visible.
        if (keyboard) Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.Bottom) {
            AvatarSmall(height = 72.dp)
            Text("AMADEUS", fontFamily = Display, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, letterSpacing = 5.sp,
                modifier = Modifier.padding(start = 10.dp, bottom = 10.dp))
        } else Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            AvatarPortrait(Modifier.padding(top = 4.dp), height = if (chat.size > 4) 200.dp else 270.dp)
            Text(greeting(h), color = C.text, fontSize = 14.sp, lineHeight = 20.sp,
                modifier = Modifier.offset(y = (-6).dp).widthIn(max = 330.dp)
                    .background(C.bg.copy(alpha = .85f), RoundedCornerShape(14.dp))
                    .border(1.dp, C.line, RoundedCornerShape(14.dp)).padding(horizontal = 14.dp, vertical = 8.dp))
        }

        val approvals = h?.optJSONArray("approvals")
        if (keyboard) Unit
        else if (approvals != null && approvals.length() > 0) {
            val a = approvals.getJSONObject(0)
            Card(Modifier.padding(start = 16.dp, end = 16.dp, top = 10.dp), border = C.line) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(if (approvals.length() == 1) "1 approval waiting" else "${approvals.length()} approvals waiting",
                        fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    Text("See all", color = C.accent, fontSize = 13.sp, modifier = Modifier.clickable { nav.go(Screen.Approvals) }.padding(6.dp))
                }
                Text(plain(a.optString("summary")), color = C.soft, fontSize = 14.sp, modifier = Modifier.padding(vertical = 8.dp), maxLines = 3)
                ApproveRow(a.getString("id")) { home.reload() }
            }
        }

        LazyColumn(Modifier.weight(1f).fillMaxWidth().padding(horizontal = 16.dp), state = list,
            verticalArrangement = Arrangement.spacedBy(8.dp, Alignment.Bottom)) {
            item { Spacer(Modifier.height(8.dp)) }
            items(chat) { b ->
                Box(Modifier.fillMaxWidth(), contentAlignment = if (b.mine) Alignment.CenterEnd else Alignment.CenterStart) {
                    Text(md(b.text), fontSize = 14.sp, lineHeight = 20.sp, color = C.text,
                        modifier = Modifier.widthIn(max = 300.dp)
                            .background(if (b.mine) Color(0xFF4A3312) else Color(0x12FFFFFF),
                                if (b.mine) RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp) else RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp))
                            .padding(horizontal = 12.dp, vertical = 8.dp))
                }
            }
        }

        // the message box, like Claude's: a rounded card that grows with what you write, mic and send below the text
        Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)
            .background(Color(0xFF1C1A1F), RoundedCornerShape(24.dp))
            .border(1.dp, if (recording) C.no else C.line, RoundedCornerShape(24.dp))
            .padding(start = 18.dp, end = 10.dp, top = 14.dp, bottom = 10.dp)) {
            BasicTextField(input, { input = it }, Modifier.fillMaxWidth().heightIn(min = 24.dp), maxLines = 6,
                textStyle = TextStyle(color = C.text, fontSize = 16.sp, lineHeight = 22.sp), cursorBrush = SolidColor(C.accent),
                decorationBox = { field ->
                    Box {
                        if (input.isEmpty()) Text(if (recording) "Listening…" else "Ask ${LocalContext.current.assistantName}…", color = C.muted, fontSize = 16.sp)
                        field()
                    }
                })
            Row(Modifier.fillMaxWidth().padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Spacer(Modifier.weight(1f))
                val typing = input.isNotBlank()
                // hold to talk
                Box(Modifier.size(44.dp).clip(CircleShape).background(if (recording) C.no else C.card)
                    .pointerInput(cid, busy) {
                        detectTapGestures(onPress = {
                            if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                                micPermission.launch(Manifest.permission.RECORD_AUDIO); return@detectTapGestures
                            }
                            if (busy) return@detectTapGestures
                            runCatching { recorder.start(); recording = true }
                            tryAwaitRelease()
                            recording = false
                            val audio = recorder.stop() ?: return@detectTapGestures
                            scope.io(ctx) { api ->
                                val text = api.stt(audio, "audio/ogg")
                                scope.launch { if (text.isNotBlank()) send(text, voice = true) else Toast.makeText(ctx, "I didn't catch that", Toast.LENGTH_SHORT).show() }
                            }
                        })
                    }, contentAlignment = Alignment.Center) {
                    Icon(Ico.mic, "Hold to talk", Modifier.size(22.dp), tint = if (recording) Color.White else C.soft)
                }
                Spacer(Modifier.size(8.dp))
                Box(Modifier.size(44.dp).clip(CircleShape).background(if (typing && !busy) C.accent else C.accent.copy(alpha = .3f))
                    .clickable(enabled = typing && !busy) { send(input.trim()); input = "" }, contentAlignment = Alignment.Center) {
                    Icon(Ico.send, "Send", Modifier.size(20.dp), tint = C.onAccent)
                }
            }
        }
    }
}

private fun greeting(h: JSONObject?): String {
    if (h == null) return "Connecting to your PC…"
    val hour = LocalTime.now().hour
    val hello = when { hour < 11 -> "Good morning."; hour < 18 -> "Hi."; else -> "Good evening." }
    val parts = mutableListOf<String>()
    val ok = h.optJSONArray("approvals")?.length() ?: 0
    if (ok > 0) parts += if (ok == 1) "one thing needs your OK" else "$ok things need your OK"
    val now = LocalTime.now().toString().take(5)
    val next = h.optJSONArray("today")?.let { t -> (0 until t.length()).map { t.getJSONObject(it) } }
        ?.firstOrNull { !it.optBoolean("all_day") && it.optString("start").takeLast(5) >= now }
    if (next != null) parts += "${next.optString("title")} at ${next.optString("start").takeLast(5)}"
    return if (parts.isEmpty()) "$hello Nothing needs you right now." else "$hello " + parts.joinToString(", ").replaceFirstChar { it.uppercase() } + "."
}

/** Its answers use a little Markdown: **bold** shows bold, the other marks are dropped. */
fun md(s: String) = buildAnnotatedString {
    val text = s.replace(Regex("(?m)^#+\\s*"), "").replace(Regex("(?m)^\\s*[-*]\\s+"), "• ").replace("`", "")
    var bold = false
    text.split("**").forEach { part ->
        if (bold) withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(part) } else append(part)
        bold = !bold
    }
}

/** Markdown bold and similar marks removed for plain text on the phone. */
fun plain(s: String) = s.replace(Regex("[*_`#>]"), "").trim()

@Composable
fun ApproveRow(approvalId: String, onDone: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FilledButton("Approve", C.ok, { busy = true; scope.io(ctx, done = { busy = false; onDone() }) { it.decide(approvalId, true) } }, Modifier.weight(1f), enabled = !busy)
        FilledButton("Reject", C.no, { busy = true; scope.io(ctx, done = { busy = false; onDone() }) { it.decide(approvalId, false) } }, Modifier.weight(1f), enabled = !busy)
    }
}
