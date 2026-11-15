package io.github.iabrahami.amadeus.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.github.iabrahami.amadeus.AmadeusApp
import io.github.iabrahami.amadeus.assistantName
import io.github.iabrahami.amadeus.data.AmadeusApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import androidx.compose.ui.text.withStyle
import org.json.JSONArray
import org.json.JSONObject

/** Where you are. The five tabs at the bottom: Today, Chat, Home (in the middle), Mail, More; the rest opens on top of a tab. */
sealed class Screen(val tab: Int) {
    data object Today : Screen(0)
    data object Chat : Screen(1)
    data object Home : Screen(2)
    data object Mail : Screen(3)
    data object More : Screen(4)
    data object Approvals : Screen(4)
    data object Projects : Screen(4)
    data object YourDay : Screen(4)
    data object Memory : Screen(4)
    data class MailRead(val id: Long) : Screen(3)
}

/** Something to say to the assistant from another screen ("Plan my day", "Sort my inbox"); send = false only fills the box. */
data class Ask(val text: String, val send: Boolean = true)

class Nav {
    val stack = mutableStateListOf<Screen>(Screen.Home)
    val ask: MutableState<Ask?> = mutableStateOf(null)
    /** Today's switch: "day" or "reminders". */
    var todayTab by mutableStateOf("day")
    val top get() = stack.last()
    fun go(s: Screen) { if (s != top) stack.add(s) }
    fun tab(s: Screen) { stack.clear(); stack.add(Screen.Home); if (s != Screen.Home) stack.add(s) }
    fun back(): Boolean = if (stack.size > 1) { stack.removeAt(stack.lastIndex); true } else false
    fun askAmadeus(text: String, send: Boolean = true) { ask.value = Ask(text, send); tab(Screen.Chat) }
}

/** The counts on the tabs and on Home: approvals waiting, open to-dos, unread mail. */
class Counts {
    var approvals by mutableIntStateOf(0)
    var todos by mutableIntStateOf(0)
    var mail by mutableStateOf<Int?>(null)
}

val Context.api: AmadeusApi get() = (applicationContext as AmadeusApp).api

/** Result of loading something from your PC. */
data class Load<T>(val data: T? = null, val error: String? = null, val loading: Boolean = true)

class Loader<T>(private val state: MutableState<Load<T>>, val reload: () -> Unit) {
    val value: Load<T> get() = state.value
}

/** Loads in the background (and again on reload(), and when something new arrives from your PC); keeps the old data while reloading. */
@Composable
fun <T> load(vararg keys: Any?, block: (AmadeusApi) -> T): Loader<T> {
    val api = LocalContext.current.api
    val state = remember(*keys) { mutableStateOf(Load<T>()) }
    var tick by remember(*keys) { mutableIntStateOf(0) }
    val app = LocalContext.current.applicationContext as AmadeusApp
    LaunchedEffect(*keys) { app.updates.collect { tick++ } }
    LaunchedEffect(*keys, tick) {
        state.value = state.value.copy(loading = true)
        state.value = try {
            Load(withContext(Dispatchers.IO) { block(api) }, null, false)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Load(state.value.data, e.message ?: "Couldn't reach your PC", false)
        }
    }
    return Loader(state) { tick++ }
}

/** Runs a PC call in the background; a failure becomes a short message on screen. */
fun CoroutineScope.io(ctx: Context, done: () -> Unit = {}, block: (AmadeusApi) -> Unit) = launch {
    try {
        withContext(Dispatchers.IO) { block(ctx.api) }
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Toast.makeText(ctx, e.message ?: "Couldn't reach your PC", Toast.LENGTH_LONG).show()
    }
    done()
}

fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }

@Composable
fun AmadeusAppUi(onUnpaired: () -> Unit, openMail: Long? = null, mailOpened: () -> Unit = {}, openApprovals: Boolean = false, approvalsOpened: () -> Unit = {}) {
    val ctx = LocalContext.current
    val nav = remember { Nav() }
    val talk = remember { Talk(ctx) }
    val counts = remember { Counts() }
    DisposableEffect(Unit) { onDispose { talk.release() } }
    LaunchedEffect(openMail) { if (openMail != null) { nav.tab(Screen.Mail); nav.go(Screen.MailRead(openMail)); mailOpened() } }
    LaunchedEffect(openApprovals) { if (openApprovals) { nav.tab(Screen.More); nav.go(Screen.Approvals); approvalsOpened() } }
    BackHandler(enabled = nav.stack.size > 1) { nav.back() }

    // today's chat and the counts: on start, whenever you come back, and when something new arrives from your PC
    val owner = LocalLifecycleOwner.current
    var resumed by remember { mutableIntStateOf(0) }
    DisposableEffect(owner) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) resumed++ }
        owner.lifecycle.addObserver(obs)
        onDispose { owner.lifecycle.removeObserver(obs) }
    }
    LaunchedEffect(resumed) { talk.refresh() }
    val home = load("counts", resumed, talk.busy) { api -> api.home() to runCatching { api.todo().size }.getOrNull() }
    LaunchedEffect(home.value.data) {
        val (h, todos) = home.value.data ?: return@LaunchedEffect
        counts.approvals = h.optJSONArray("approvals")?.length() ?: 0
        if (todos != null) counts.todos = todos
    }
    val unread = load("unread", resumed) { api -> if (api.mailStatus().optBoolean("connected")) api.mailUnread().length() else null }
    LaunchedEffect(unread.value.data, unread.value.loading) { if (!unread.value.loading) counts.mail = unread.value.data }

    Column(Modifier.fillMaxSize().hud().statusBarsPadding().navigationBarsPadding()) {
        Box(Modifier.weight(1f).fillMaxWidth().windowInsetsPadding(WindowInsets.ime)) {
            when (val s = nav.top) {
                Screen.Home -> HomeScreen(nav, talk, counts, home.value.data?.first, home.value.error == null && home.value.data != null)
                Screen.Chat -> ChatScreen(nav, talk)
                Screen.Today -> TodayScreen(nav)
                Screen.Mail -> MailScreen(nav)
                is Screen.MailRead -> MailReadScreen(nav, s.id)
                Screen.More -> MoreScreen(nav, counts, onUnpaired)
                Screen.Approvals -> ApprovalsScreen(nav) { home.reload() }
                Screen.Projects -> ProjectsScreen(nav)
                Screen.YourDay -> YourDayScreen(nav)
                Screen.Memory -> MemoryScreen(nav)
            }
        }
        BottomNav(nav, counts)
    }
}

@Composable
private fun BottomNav(nav: Nav, counts: Counts) {
    val tabs = listOf(Triple(Screen.Today, Ico.today, "Today"), Triple(Screen.Chat, Ico.chats, "Chat"), Triple(Screen.Home, Ico.home, "Home"),
        Triple(Screen.Mail, Ico.mail, "Mail"), Triple(Screen.More, Ico.more, "More"))
    Row(Modifier.fillMaxWidth().background(C.bg.copy(alpha = .94f))
        .drawBehind { drawLine(C.line, Offset(0f, 0f), Offset(size.width, 0f), 1.dp.toPx()) }) {
        tabs.forEach { (screen, icon, label) ->
            val on = nav.top.tab == screen.tab
            val badge = when (screen) { Screen.Home -> counts.approvals.takeIf { it > 0 }; Screen.Mail -> counts.mail?.takeIf { it > 0 }; else -> null }
            Column(Modifier.weight(1f).heightIn(min = 58.dp).clickable(role = Role.Tab) { nav.tab(screen) }
                .semantics { contentDescription = label + (badge?.let { ", $it" } ?: "") }
                .drawBehind { if (on) drawLine(C.accent, Offset(size.width * .3f, 1.dp.toPx()), Offset(size.width * .7f, 1.dp.toPx()), 2.dp.toPx()) },
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                Box {
                    Icon(icon, null, Modifier.size(22.dp), tint = if (on) C.accent else C.dim)
                    if (badge != null) Text(if (badge > 99) "99+" else "$badge", Modifier.align(Alignment.TopEnd).offset(x = 12.dp, y = (-6).dp)
                        .background(if (screen == Screen.Home) C.amber else C.accent).padding(horizontal = 3.dp),
                        color = if (screen == Screen.Home) C.amberInk else C.ink, fontFamily = Mono, fontWeight = FontWeight.Medium, fontSize = 10.sp)
                }
                Label(label, Modifier.padding(top = 4.dp), color = if (on) C.accent else C.dim, size = 10.sp, spacing = 1.5.sp)
            }
        }
    }
}

/**
 * The ask bar, as on the PC: the VOICE tag (SPOKEN / ON / OFF, tap to change), a mono text field, and the mic (hold to
 * talk). What you say goes to today's chat.
 */
@Composable
fun AskBar(talk: Talk, nav: Nav) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var input by remember { mutableStateOf("") }
    var recording by remember { mutableStateOf(false) }
    val recorder = remember { Recorder(ctx) }
    LaunchedEffect(nav.ask.value, talk.cid) {
        val a = nav.ask.value ?: return@LaunchedEffect
        if (talk.cid == null) return@LaunchedEffect
        nav.ask.value = null
        if (a.send) talk.send(a.text) else input = a.text
    }
    val micPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (!ok) Toast.makeText(ctx, "Allow the microphone to talk to ${ctx.assistantName}", Toast.LENGTH_LONG).show()
    }
    fun submit() { if (input.isNotBlank() && !talk.busy) { talk.send(input.trim()); input = "" } }
    val (vLabel, vColor) = when (talk.voiceMode) { "always" -> "ON" to C.accent; "off" -> "OFF" to C.dim; else -> "SPOKEN" to C.accent }
    Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp).heightIn(min = 50.dp)
        .background(C.deck.copy(alpha = .9f)).border(1.dp, if (recording) C.red else C.lineHi)
        .padding(start = 6.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Row(Modifier.heightIn(min = 44.dp).clickable(role = Role.Button) {
            talk.setVoice(when (talk.voiceMode) { "voice" -> "always"; "always" -> "off"; else -> "voice" })
        }.semantics { contentDescription = "Spoken answers: $vLabel. Tap to change." }.padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Row(Modifier.border(1.dp, vColor.copy(alpha = .7f)).padding(horizontal = 6.dp, vertical = 3.dp)) {
                Text("VOICE ", color = vColor, fontFamily = Chakra, fontWeight = FontWeight.SemiBold, fontSize = 10.sp, letterSpacing = 1.5.sp)
                Text(vLabel, color = C.text.copy(alpha = if (talk.voiceMode == "off") .5f else .9f), fontFamily = Chakra, fontSize = 10.sp, letterSpacing = 1.5.sp)
            }
        }
        BasicTextField(input, { input = it }, Modifier.weight(1f).padding(horizontal = 8.dp), maxLines = 4,
            textStyle = TextStyle(color = C.text, fontFamily = Mono, fontSize = 14.sp, lineHeight = 20.sp), cursorBrush = SolidColor(C.accent),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send), keyboardActions = KeyboardActions(onSend = { submit() }),
            decorationBox = { f ->
                Box {
                    if (input.isEmpty()) Text(if (recording) "Listening…" else if (talk.busy) "Thinking…" else "Ask ${ctx.assistantName}…", color = C.dim, fontFamily = Mono, fontSize = 14.sp)
                    f()
                }
            })
        Box(Modifier.width(1.dp).height(28.dp).background(C.line))
        val typing = input.isNotBlank()
        Box(Modifier.size(46.dp).semantics { contentDescription = if (typing) "Send" else "Hold to talk" }
            .pointerInput(typing, talk.busy, talk.cid) {
                detectTapGestures(onTap = { if (typing) submit() }, onPress = {
                    if (typing) return@detectTapGestures
                    if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                        micPermission.launch(Manifest.permission.RECORD_AUDIO); return@detectTapGestures
                    }
                    if (talk.busy) return@detectTapGestures
                    runCatching { recorder.start(); recording = true; CoreLink.mode = "listen" }
                    tryAwaitRelease()
                    recording = false
                    if (CoreLink.mode == "listen") CoreLink.mode = "idle"
                    val audio = recorder.stop() ?: return@detectTapGestures
                    CoreLink.mode = "think"
                    scope.io(ctx, done = { if (!talk.busy) CoreLink.mode = "idle" }) { api ->
                        val text = api.stt(audio, "audio/ogg")
                        scope.launch { if (text.isNotBlank()) talk.send(text, spoken = true) else Toast.makeText(ctx, "I didn't catch that", Toast.LENGTH_SHORT).show() }
                    }
                })
            }, contentAlignment = Alignment.Center) {
            Icon(if (typing) Ico.send else Ico.mic, null, Modifier.size(20.dp), tint = if (recording) C.red else C.accent)
        }
    }
}

@Composable
fun ErrorLine(text: String?, retry: (() -> Unit)? = null) {
    if (text == null) return
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(text, color = C.amber, fontFamily = Mono, fontSize = 12.sp, modifier = Modifier.weight(1f))
        if (retry != null) Label("Retry", Modifier.clickable { retry() }.padding(10.dp), color = C.accent)
    }
}

/** A sub-screen's header: the mark goes back, the title says where you are. */
@Composable
fun SubHeader(nav: Nav, title: String, right: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit = {}) =
    Header(title, onMark = { if (!nav.back()) nav.tab(Screen.Home) }, right = right)

/** Its answers use a little Markdown: **bold** shows bold, the other marks are dropped. */
fun md(s: String) = androidx.compose.ui.text.buildAnnotatedString {
    val text = s.replace(Regex("(?m)^#+\\s*"), "").replace(Regex("(?m)^\\s*[-*]\\s+"), "• ").replace("`", "")
    var bold = false
    text.split("**").forEach { part ->
        if (bold) withStyle(androidx.compose.ui.text.SpanStyle(fontWeight = FontWeight.SemiBold, color = C.text)) { append(part) } else append(part)
        bold = !bold
    }
}

/** Markdown marks removed for plain text on the phone. */
fun plain(s: String) = s.replace(Regex("[*_`#>]"), "").trim()
