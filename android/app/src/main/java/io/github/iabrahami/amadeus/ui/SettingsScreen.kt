package io.github.iabrahami.amadeus.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import io.github.iabrahami.amadeus.AmadeusApp
import io.github.iabrahami.amadeus.BuildConfig
import io.github.iabrahami.amadeus.assistantName
import io.github.iabrahami.amadeus.data.AmadeusApi
import io.github.iabrahami.amadeus.link.LinkService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** More: the other pages, the theme (the PC's), spoken answers, calls, and this phone. */
@Composable
fun MoreScreen(nav: Nav, counts: Counts, onUnpaired: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val app = ctx.applicationContext as AmadeusApp
    val store = app.store
    val home = load("settings") { it.home() }
    var calls by remember { mutableStateOf(store.calls) }
    var avatar by remember { mutableStateOf(store.showAvatar) }
    var voiceMode by remember { mutableStateOf(store.voiceMode) }
    var confirmPrivate by remember { mutableStateOf(false) }
    var confirmUnpair by remember { mutableStateOf(false) }
    val h = home.value.data
    val name = ctx.assistantName

    Column(Modifier.fillMaxSize()) {
        Header("More", onMark = { nav.tab(Screen.Home) }) { PcStatus(if (h == null && home.value.loading) null else home.value.error == null) { home.reload() } }
        ErrorLine(home.value.error) { home.reload() }
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Tile("Approvals", "Waiting for your OK", Modifier.weight(1f), badge = counts.approvals.takeIf { it > 0 }) { nav.go(Screen.Approvals) }
                Tile("Projects", "Claude Code runs", Modifier.weight(1f)) { nav.go(Screen.Projects) }
            }
            Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Tile("Your day", "Brief and plan", Modifier.weight(1f)) { nav.go(Screen.YourDay) }
                Tile("Memory", "What $name knows", Modifier.weight(1f)) { nav.go(Screen.Memory) }
            }

            Rule("Theme · from your PC")
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                THEMES.forEach { t ->
                    val on = C.theme.id == t.id
                    Column(Modifier.weight(1f).border(1.dp, if (on) t.a else C.line).clickable(role = Role.RadioButton) {
                        C.theme = t; store.theme = t.id
                        scope.io(ctx) { it.setTheme(t.id) }
                    }.semantics { contentDescription = "${t.name} theme" + if (on) ", selected" else "" }.padding(8.dp)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                            Box(Modifier.size(14.dp).background(t.a)); Box(Modifier.size(14.dp).background(t.k[1])); Box(Modifier.size(14.dp).background(t.k[2]))
                        }
                        Label(t.name, Modifier.padding(top = 6.dp), color = if (on) t.a else C.dim, size = 10.sp)
                    }
                }
            }
            Hint("The phone follows the dashboard. Changing it here changes it on the PC too.", Modifier.padding(top = 6.dp))

            Rule("Voice · spoken answers")
            Seg(listOf("always" to "On", "voice" to "Spoken", "off" to "Off"), voiceMode, { voiceMode = it; store.voiceMode = it })
            Hint(when (voiceMode) {
                "always" -> "Reads every answer aloud on this phone."
                "off" -> "Answers stay text only."
                else -> "Speaks only when you asked by voice (hold the mic)."
            }, Modifier.padding(top = 6.dp))

            Rule("This phone")
            HudRow("Calls", "Ring like a phone call for urgent things, while you're away from the PC") {
                HudSwitch(calls, { on -> calls = on; store.calls = on; if (on) LinkService.start(ctx) else LinkService.stop(ctx) })
            }
            val q = h?.optJSONArray("quiet_hours")
            HudRow("Quiet hours", if (q == null) "…" else "%02d:00 – %02d:00, only codes still ring. Set on the PC.".format(q.optInt(0), q.optInt(1)))
            HudRow("Wake word on the PC", "\"$name, …\" starts listening on the PC") {
                HudSwitch(h != null && h.optString("voice") != "off", { on -> scope.io(ctx, done = { home.reload() }) { it.voice(on) } }, enabled = h != null)
            }
            if (store.avatarSet.isNotBlank()) HudRow("Avatar on Home", "Show your own sprites instead of the core") {
                HudSwitch(avatar, { on -> avatar = on; store.showAvatar = on })
            }
            HudRow("Go private", "Switch the PC off the network for now", onClick = { confirmPrivate = true })
            HudRow("Unpair this phone", "Removes this phone's key", titleColor = C.red, onClick = { confirmUnpair = true })
            Hint("Connected to ${store.host ?: "your PC"} through Tailscale · app ${BuildConfig.VERSION_NAME}", Modifier.padding(vertical = 16.dp))
        }
    }

    if (confirmPrivate) AlertDialog(
        onDismissRequest = { confirmPrivate = false }, containerColor = C.deck,
        title = { Label("Go private?", color = C.text, size = 14.sp) },
        text = { Body("Your PC switches Tailscale off. This phone can't reach $name until you make it visible again on the PC.", size = 14.sp) },
        confirmButton = { TextButton({ confirmPrivate = false; scope.io(ctx) { it.goPrivate() } }) { Label("Go private", color = C.accent) } },
        dismissButton = { TextButton({ confirmPrivate = false }) { Label("Cancel") } },
    )
    if (confirmUnpair) AlertDialog(
        onDismissRequest = { confirmUnpair = false }, containerColor = C.deck,
        title = { Label("Unpair this phone?", color = C.text, size = 14.sp) },
        text = { Body("This phone's key is removed here and on your PC. To use the app again, pair it with a new code.", size = 14.sp) },
        confirmButton = { TextButton({
            confirmUnpair = false
            LinkService.stop(ctx)
            scope.launch { withContext(Dispatchers.IO) { ctx.api.unpair() }; onUnpaired() }
        }) { Label("Unpair", color = C.red) } },
        dismissButton = { TextButton({ confirmUnpair = false }) { Label("Cancel") } },
    )
}

@Composable
private fun Tile(title: String, sub: String, modifier: Modifier, badge: Int? = null, onClick: () -> Unit) =
    Column(modifier.heightIn(min = 70.dp).dashed(C.lineHi).clickable(role = Role.Button, onClick = onClick).padding(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label(title, Modifier.weight(1f), color = C.text, size = 12.sp)
            if (badge != null) Tag("$badge", TagKind.Amber)
        }
        Hint(sub, Modifier.padding(top = 4.dp))
    }

/** First start: scan the QR code in the dashboard (Phone → Pair a phone) and you're done. Typing the code still works. */
@Composable
fun PairScreen(onPaired: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var host by remember { mutableStateOf((ctx.applicationContext as AmadeusApp).store.host ?: "") }
    var code by remember { mutableStateOf("") }
    var typing by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun pair(h: String, c: String) {
        busy = true; error = null
        scope.launch {
            val r = withContext(Dispatchers.IO) { ctx.api.pair(h, c) }
            busy = false
            r.onSuccess { onPaired() }.onFailure { error = it.message ?: "Pairing failed. Is Tailscale on, on both devices?" }
        }
    }

    // The QR code is https://<your pc>.ts.net/pair#code=123456
    val scan = rememberLauncherForActivityResult(ScanContract()) { result ->
        val text = result.contents ?: return@rememberLauncherForActivityResult
        val m = Regex("^https://([^/#?]+)/pair#code=(\\d{6})$").find(text.trim())
        if (m == null) { error = "That's not an Amadeus pairing code. Make a new one on the PC: dashboard → Phone → Pair a phone."; return@rememberLauncherForActivityResult }
        host = m.groupValues[1]; code = m.groupValues[2]
        pair(host, code)
    }

    Column(Modifier.fillMaxSize().hud().verticalScroll(rememberScrollState()).padding(horizontal = 28.dp, vertical = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        LiveCore(Modifier.size(220.dp), mode = if (busy) "think" else "idle")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("AMADEUS", fontFamily = Chakra, fontWeight = FontWeight.SemiBold, fontSize = 28.sp, letterSpacing = 9.sp, color = C.text)
            Cursor(size = 28.sp)
        }
        Body("On your PC open the dashboard → Phone → Pair a phone, then scan the QR code.", color = C.dim, size = 15.sp)
        HudButton(if (busy) "Pairing…" else "Scan QR code", {
            scan.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE).setPrompt("Scan the QR code on your PC")
                .setBeepEnabled(false).setOrientationLocked(false))
        }, Modifier.fillMaxWidth().padding(top = 10.dp), Btn.Go, enabled = !busy)
        error?.let { Text(it, color = C.amber, fontFamily = Mono, fontSize = 13.sp, textAlign = TextAlign.Center) }

        if (!typing) Label("Enter the code instead", Modifier.clickable { typing = true }.padding(12.dp), color = C.accent)
        else {
            Label("Your PC (Tailscale)", Modifier.fillMaxWidth())
            HudField(host, { host = it.trim() }, "pc-name.tailXXXX.ts.net", Modifier.fillMaxWidth())
            Label("6-digit code", Modifier.fillMaxWidth())
            androidx.compose.foundation.text.BasicTextField(code, { code = it.filter(Char::isDigit).take(6) },
                Modifier.fillMaxWidth().border(1.dp, C.lineHi).padding(12.dp), singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                cursorBrush = androidx.compose.ui.graphics.SolidColor(C.accent),
                textStyle = androidx.compose.ui.text.TextStyle(color = C.text, fontFamily = Mono, fontSize = 26.sp, letterSpacing = 10.sp, textAlign = TextAlign.Center))
            HudButton("Pair", { pair(host, code) }, Modifier.fillMaxWidth(), Btn.Go, enabled = !busy && code.length == 6 && AmadeusApi.allowedHost(host))
        }
        Hint("Only works inside your private Tailscale network. The phone gets its own key; remove it any time on the PC.", Modifier.padding(top = 20.dp))
    }
}
