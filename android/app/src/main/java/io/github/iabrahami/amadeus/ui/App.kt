package io.github.iabrahami.amadeus.ui

import io.github.iabrahami.amadeus.assistantName
import android.content.Context
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.clickable
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.iabrahami.amadeus.AmadeusApp
import io.github.iabrahami.amadeus.data.AmadeusApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Where you are in the app. The four main places have a tab at the bottom; the rest open on top of them. */
sealed class Screen(val tab: Int) {
    data object Home : Screen(0)
    data object Today : Screen(1)
    data object Mail : Screen(2)
    data object Settings : Screen(3)
    data object Approvals : Screen(0)
    data class MailRead(val id: Long) : Screen(2)
}

/** Something to say to the assistant from another screen ("Plan my day", "Sort my inbox"); send = false only fills the box. */
data class Ask(val text: String, val send: Boolean = true)

class Nav {
    val stack = mutableStateListOf<Screen>(Screen.Home)
    val ask: MutableState<Ask?> = mutableStateOf(null)
    val top get() = stack.last()
    fun go(s: Screen) { if (s != top) stack.add(s) }
    fun tab(s: Screen) { stack.clear(); stack.add(Screen.Home); if (s != Screen.Home) stack.add(s) }
    fun back(): Boolean = if (stack.size > 1) { stack.removeAt(stack.lastIndex); true } else false
    fun askAmadeus(text: String, send: Boolean = true) { ask.value = Ask(text, send); tab(Screen.Home) }
}

val Context.api: AmadeusApi get() = (applicationContext as AmadeusApp).api

/** Result of loading something from your PC. */
data class Load<T>(val data: T? = null, val error: String? = null, val loading: Boolean = true)

class Loader<T>(private val state: MutableState<Load<T>>, val reload: () -> Unit) {
    val value: Load<T> get() = state.value
}

/** Loads in the background (and again on reload()); keeps the old data while reloading. */
@Composable
fun <T> load(vararg keys: Any?, block: (AmadeusApi) -> T): Loader<T> {
    val api = LocalContext.current.api
    val state = remember(*keys) { mutableStateOf(Load<T>()) }
    var tick by remember(*keys) { mutableIntStateOf(0) }
    val app = LocalContext.current.applicationContext as AmadeusApp
    LaunchedEffect(*keys) { app.updates.collect { tick++ } }   // something new from your PC while you're in the app
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

val glow = Brush.radialGradient(listOf(C.glow, C.bg), radius = 1400f)

@Composable
fun AmadeusAppUi(onUnpaired: () -> Unit, openMail: Long? = null, mailOpened: () -> Unit = {}) {
    val nav = remember { Nav() }
    LaunchedEffect(openMail) { if (openMail != null) { nav.tab(Screen.Mail); nav.go(Screen.MailRead(openMail)); mailOpened() } }
    BackHandler(enabled = nav.stack.size > 1) { nav.back() }
    Column(Modifier.fillMaxSize().background(C.bg).statusBarsPadding().navigationBarsPadding()) {
        Box(Modifier.weight(1f).fillMaxWidth().windowInsetsPadding(WindowInsets.ime)) {
            when (val s = nav.top) {
                Screen.Home -> HomeScreen(nav)
                Screen.Approvals -> ApprovalsScreen(nav)
                Screen.Today -> TodayScreen(nav)
                Screen.Mail -> MailScreen(nav)
                is Screen.MailRead -> MailReadScreen(nav, s.id)
                Screen.Settings -> SettingsScreen(nav, onUnpaired)
            }
            // the avatar stays with you on every other screen: small, bottom right, standing on the menu bar (tap: back to the main screen)
            if (nav.top != Screen.Home) AvatarSmall(Modifier.align(Alignment.BottomEnd).padding(end = 10.dp)
                .clickable { nav.tab(Screen.Home) })
        }
        BottomNav(nav)
    }
}

@Composable
private fun BottomNav(nav: Nav) {
    val tabs = listOf(Triple(Screen.Home, Ico.home, LocalContext.current.assistantName), Triple(Screen.Today, Ico.today, "Today"),
        Triple(Screen.Mail, Ico.mail, "Mail"), Triple(Screen.Settings, Ico.more, "More"))
    Row(Modifier.fillMaxWidth().background(Color(0xE608080C)).border(0.5.dp, C.line.copy(alpha = .3f))
        .padding(top = 6.dp, bottom = 8.dp)) {
        tabs.forEach { (screen, icon, label) ->
            val on = nav.top.tab == screen.tab
            Column(Modifier.weight(1f).heightIn(min = 48.dp).clickable { nav.tab(screen) },
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                Icon(icon, label, Modifier.size(22.dp), tint = if (on) C.accent else C.muted)
                Text(label, fontSize = 11.sp, color = if (on) C.accent else C.muted)
            }
        }
    }
}

@Composable
fun BackHeader(nav: Nav, title: String, sub: String? = null, color: Color = C.text, trailing: @Composable () -> Unit = {}) =
    Row(Modifier.fillMaxWidth().padding(start = 8.dp, end = 16.dp, top = 12.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = { nav.back() }, modifier = Modifier.size(48.dp)) { Icon(Ico.back, "Back", tint = C.text) }
        Column(Modifier.weight(1f)) {
            Text(title, color = color, fontSize = 28.sp, fontFamily = Display, fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold)
            if (sub != null) Text(sub, color = C.muted, fontSize = 13.sp)
        }
        trailing()
    }

@Composable
fun ErrorLine(text: String?, retry: (() -> Unit)? = null) {
    if (text == null) return
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(text, color = C.warn, fontSize = 13.sp, modifier = Modifier.weight(1f))
        if (retry != null) Text("Retry", color = C.accent, fontSize = 13.sp, modifier = Modifier.clickable { retry() }.padding(8.dp))
    }
}
