package io.github.iabrahami.amadeus.ui

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.github.iabrahami.amadeus.AmadeusApp
import io.github.iabrahami.amadeus.assistantName
import io.github.iabrahami.amadeus.data.AmadeusApi
import io.github.iabrahami.amadeus.link.Notifications
import org.json.JSONObject
import java.time.Instant
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Home: what waits for you (approvals, to-dos, mail), the next event, the live core, today's chat faded above the ask
 * bar. While you type, the core steps back so the chat stays readable.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun HomeScreen(nav: Nav, talk: Talk, counts: Counts, home: JSONObject?, online: Boolean) {
    val ctx = LocalContext.current
    val store = (ctx.applicationContext as AmadeusApp).store
    val keyboard = WindowInsets.isImeVisible
    Column(Modifier.fillMaxSize()) {
        Header(ctx.assistantName) { PcStatus(if (home == null && talk.online == null) null else online || talk.online == true) { talk.refresh() } }
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            WaitChip("Approvals", counts.approvals, amber = counts.approvals > 0, Modifier.weight(1f)) { nav.go(Screen.Approvals) }
            WaitChip("To-dos", counts.todos, amber = counts.todos > 0, Modifier.weight(1f)) { nav.todayTab = "day"; nav.tab(Screen.Today) }
            WaitChip("Mail", counts.mail, amber = false, Modifier.weight(1f)) { nav.tab(Screen.Mail) }
        }
        next(home)?.let { (title, time) ->
            Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 10.dp).clickable { nav.todayTab = "day"; nav.tab(Screen.Today) },
                verticalAlignment = Alignment.CenterVertically) {
                Label("Next", color = C.dim); Label(" · ", color = C.dim)
                Body(title, Modifier.weight(1f), size = 14.sp, weight = FontWeight.Medium, maxLines = 1)
                MonoText(time)
            }
        }
        FullScreenCallsHint()
        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (!keyboard) {
                if (store.showAvatar && store.avatarSet.isNotBlank()) AvatarPortrait(Modifier.align(Alignment.Center), height = 300.dp)
                else LiveCore(Modifier.fillMaxSize().padding(bottom = 40.dp).talkTo(talk)
                    .semantics { contentDescription = if (talk.listening) "Listening. Tap to send." else "Tap to talk to ${ctx.assistantName}" })
                if (talk.listening) Label("Listening · tap to send", Modifier.align(Alignment.TopCenter).padding(top = 8.dp), color = C.accent)
            }
            Ghost(talk.lines, Modifier.align(Alignment.BottomCenter).fillMaxWidth().let { if (keyboard) it.fillMaxSize() else it.heightIn(max = 170.dp) })
        }
        AskBar(talk, nav)
    }
}

@Composable
private fun WaitChip(label: String, n: Int?, amber: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val c = if (amber) C.amber else C.line
    Column(modifier.heightIn(min = 54.dp).clickable(role = Role.Button, onClick = onClick)
        .semantics(mergeDescendants = true) { contentDescription = "$label: ${n ?: "–"}" }
        .drawWithContent { drawContent(); drawLine(c, androidx.compose.ui.geometry.Offset(1f, 0f), androidx.compose.ui.geometry.Offset(1f, size.height), 2.dp.toPx()) }
        .padding(start = 10.dp, top = 4.dp, bottom = 4.dp)) {
        Label(label, color = if (amber) C.amber else C.dim, size = 10.sp)
        Text(n?.toString() ?: "–", color = if (amber) C.amber else C.text.copy(alpha = .8f), fontFamily = Mono, fontSize = 22.sp)
    }
}

/** The next timed event today: (title, "15:00"). */
private fun next(h: JSONObject?): Pair<String, String>? {
    val now = LocalTime.now().toString().take(5)
    return h?.optJSONArray("today")?.objects()?.firstOrNull { !it.optBoolean("all_day") && it.optString("start").takeLast(5) >= now }
        ?.let { it.optString("title") to it.optString("start").takeLast(5) }
}

/** Today's chat, faded towards the top, like the ghost log on the dashboard. Tap: the Chat tab. */
@Composable
private fun Ghost(lines: List<AmadeusApi.Line>, modifier: Modifier) {
    val list = rememberLazyListState()
    val last = lines.takeLast(12)
    LaunchedEffect(lines.size, lines.lastOrNull()?.text?.length) { if (last.isNotEmpty()) list.scrollToItem(last.lastIndex) }
    LazyColumn(modifier.padding(horizontal = 16.dp)
        .graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen)
        .drawWithContent {
            drawContent()
            drawRect(Brush.verticalGradient(0f to Color.Transparent, .55f to Color.Black, 1f to Color.Black), blendMode = BlendMode.DstIn)
        }, state = list, verticalArrangement = Arrangement.spacedBy(8.dp, Alignment.Bottom)) {
        itemsIndexed(last) { _, l -> ChatLine(l, compact = true) }
    }
}

/** One line of the chat: the time, who said it, and the text (yours in mono, its answer in the body font). */
@Composable
fun ChatLine(l: AmadeusApi.Line, compact: Boolean = false) {
    val name = LocalContext.current.assistantName
    Row(Modifier.fillMaxWidth()) {
        MonoText(clock(l.at), Modifier.width(48.dp).padding(top = 2.dp), size = 11.sp)
        Column(Modifier.weight(1f)) {
            Label(if (l.mine) "You" else name, color = if (l.mine) C.dim else C.accent, size = 10.sp)
            if (l.mine) Text(l.text, color = C.dim, fontFamily = Mono, fontSize = 13.sp, lineHeight = 19.sp,
                maxLines = if (compact) 2 else Int.MAX_VALUE, overflow = TextOverflow.Ellipsis)
            else Text(md(l.text), color = C.text, fontFamily = Plex, fontSize = 15.sp, lineHeight = 21.sp,
                maxLines = if (compact) 3 else Int.MAX_VALUE, overflow = TextOverflow.Ellipsis)
        }
    }
}

fun clock(epoch: Double): String = if (epoch <= 0) "" else
    Instant.ofEpochMilli((epoch * 1000).toLong()).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("HH:mm"))

/** Android 14+: its calls only ring full screen (like a phone call) after you allow it once. */
@Composable
private fun FullScreenCallsHint() {
    val ctx = LocalContext.current
    var ok by remember { mutableStateOf(Notifications.canRingFullScreen(ctx)) }
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) ok = Notifications.canRingFullScreen(ctx) }
        owner.lifecycle.addObserver(obs)
        onDispose { owner.lifecycle.removeObserver(obs) }
    }
    if (ok || Build.VERSION.SDK_INT < 34) return
    CrtBox(Modifier.padding(start = 16.dp, end = 16.dp, top = 10.dp).clickable {
        ctx.startActivity(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:${ctx.packageName}")))
    }, amber = true, pad = 12.dp) {
        Label("Calls need one permission", color = C.amber)
        Hint("Tap, then allow \"Full screen notifications\" so ${ctx.assistantName} can call you like a phone call.")
    }
}

/** Chat: today's conversation (Now) and the earlier days (History), with the ask bar. */
@Composable
fun ChatScreen(nav: Nav, talk: Talk) {
    var tab by remember { mutableStateOf("now") }
    var open by remember { mutableStateOf<Pair<String, String>?>(null) }
    val days = load("days") { it.dayChats() }
    val earlier = days.value.data.orEmpty().filter { it.first != talk.cid }
    Column(Modifier.fillMaxSize()) {
        Header("Chat") { PcStatus(talk.online) { talk.refresh() } }
        CrtBox(Modifier.weight(1f).padding(horizontal = 12.dp), fill = false, pad = 10.dp) {
            Row(Modifier.fillMaxWidth().padding(bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                TabLabel("Now", tab == "now") { tab = "now"; open = null }
                TabLabel("History", tab == "history", count = earlier.size) { tab = "history" }
            }
            Box(Modifier.fillMaxWidth().heightIn(min = 1.dp).background(C.line))
            when {
                tab == "now" -> Transcript(talk.lines, "Nothing yet today. Ask below, or hold the mic and talk.")
                open != null -> {
                    val (id, title) = open!!
                    val msgs = load("day", id) { it.history(id, last = 200) }
                    Row(Modifier.fillMaxWidth().clickable { open = null }.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("‹ ", color = C.accent, fontSize = 18.sp); Label(title, color = C.accent)
                    }
                    ErrorLine(msgs.value.error) { msgs.reload() }
                    Transcript(msgs.value.data.orEmpty(), if (msgs.value.loading) "Loading…" else "Nothing said that day.")
                }
                else -> {
                    ErrorLine(days.value.error) { days.reload() }
                    LazyColumn(Modifier.fillMaxSize()) {
                        if (!days.value.loading && earlier.isEmpty()) item { Hint("No earlier days yet.", Modifier.padding(vertical = 12.dp)) }
                        itemsIndexed(earlier) { _, d -> HudRow(d.second, onClick = { open = d }) }
                    }
                }
            }
        }
        AskBar(talk, nav)
    }
}

@Composable
private fun TabLabel(text: String, on: Boolean, count: Int? = null, onClick: () -> Unit) =
    Row(Modifier.heightIn(min = 40.dp).clickable(role = Role.Tab, onClick = onClick)
        .drawWithContent { drawContent(); if (on) drawLine(C.accent, androidx.compose.ui.geometry.Offset(0f, size.height - 1), androidx.compose.ui.geometry.Offset(size.width, size.height - 1), 2.dp.toPx()) }
        .padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Label(text, color = if (on) C.accent else C.dim, size = 11.sp)
        if (count != null && count > 0) MonoText(" $count", size = 10.sp)
    }

@Composable
private fun Transcript(lines: List<AmadeusApi.Line>, empty: String) {
    val list = rememberLazyListState()
    LaunchedEffect(lines.size, lines.lastOrNull()?.text?.length) { if (lines.isNotEmpty()) list.scrollToItem(lines.lastIndex) }
    if (lines.isEmpty()) Hint(empty, Modifier.padding(vertical = 14.dp))
    LazyColumn(Modifier.fillMaxSize(), state = list, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { Box(Modifier.heightIn(min = 4.dp)) }
        itemsIndexed(lines) { _, l -> ChatLine(l) }
    }
}
