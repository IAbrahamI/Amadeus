package io.github.iabrahami.amadeus.ui

import io.github.iabrahami.amadeus.assistantName
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.Image
import androidx.compose.ui.res.painterResource
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import io.github.iabrahami.amadeus.AmadeusApp
import io.github.iabrahami.amadeus.R
import io.github.iabrahami.amadeus.data.AmadeusApi
import io.github.iabrahami.amadeus.link.LinkService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Mode, voice, calls, this phone. */
@Composable
fun SettingsScreen(nav: Nav, onUnpaired: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val store = (ctx.applicationContext as AmadeusApp).store
    val home = load("settings") { it.home() }
    var calls by remember { mutableStateOf(store.calls) }
    var confirmPrivate by remember { mutableStateOf(false) }
    var confirmUnpair by remember { mutableStateOf(false) }
    val h = home.value.data

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        Title("Settings")
        ErrorLine(home.value.error) { home.reload() }
        Card(Modifier.padding(horizontal = 16.dp), border = C.line) {
            Section("Mode")
            Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ModeButton("Visible", "phone connected", on = true, Modifier.weight(1f)) {}
                ModeButton("Private", "nothing reachable", on = false, Modifier.weight(1f)) { confirmPrivate = true }
            }
            Hint("Private switches Tailscale off on your PC. Turn it back on there (\"make yourself visible\").", Modifier.padding(top = 8.dp))
        }

        Card(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp)) {
            Toggle("Voice input", "\"${ctx.assistantName}, …\" wakes it on the PC", h != null && h.optString("voice") != "off", enabled = h != null) { on ->
                scope.io(ctx, done = { home.reload() }) { it.voice(on) }
            }
            Toggle("Calls on this phone", "urgent mail, codes, approvals, the evening summary", calls) { on ->
                calls = on
                store.calls = on
                if (on) LinkService.start(ctx) else LinkService.stop(ctx)
            }
            val q = h?.optJSONArray("quiet_hours")
            Row(Modifier.fillMaxWidth().heightIn(min = 56.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Quiet hours")
                    Hint(if (q == null) "…" else "%02d:00–%02d:00 (codes still ring)".format(q.optInt(0), q.optInt(1)))
                }
                Hint("set on the PC")
            }
        }

        Card(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp)) {
            LinkRow("Approvals", "${h?.optJSONArray("approvals")?.length() ?: "–"}") { nav.go(Screen.Approvals) }
            LinkRow("This phone", store.host?.substringBefore('.') ?: "") {}
        }

        Spacer(Modifier.size(20.dp))
        Column(Modifier.fillMaxWidth().padding(bottom = 84.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Hint("Connected to ${store.host ?: "your PC"} · through Tailscale")
            LineButton("Unpair this phone", { confirmUnpair = true }, Modifier.padding(top = 8.dp), color = C.no)
        }
    }

    if (confirmPrivate) AlertDialog(
        onDismissRequest = { confirmPrivate = false },
        title = { Text("Go private?") },
        text = { Text("Your PC switches Tailscale off. This phone can't reach ${ctx.assistantName} until you make it visible again on the PC.") },
        confirmButton = { TextButton({ confirmPrivate = false; scope.io(ctx) { it.goPrivate() } }) { Text("Go private") } },
        dismissButton = { TextButton({ confirmPrivate = false }) { Text("Cancel") } },
    )
    if (confirmUnpair) AlertDialog(
        onDismissRequest = { confirmUnpair = false },
        title = { Text("Unpair this phone?") },
        text = { Text("This phone's key is removed here and on your PC. To use the app again, pair it with a new code.") },
        confirmButton = { TextButton({
            confirmUnpair = false
            LinkService.stop(ctx)
            scope.launch { withContext(Dispatchers.IO) { ctx.api.unpair() }; onUnpaired() }
        }) { Text("Unpair", color = C.no) } },
        dismissButton = { TextButton({ confirmUnpair = false }) { Text("Cancel") } },
    )
}

@Composable
private fun ModeButton(title: String, sub: String, on: Boolean, modifier: Modifier, onClick: () -> Unit) =
    Column(modifier.heightIn(min = 64.dp).background(if (on) C.accent.copy(alpha = .12f) else Color.Transparent, RoundedCornerShape(14.dp))
        .border(if (on) 2.dp else 1.dp, if (on) C.accent else Color(0x26FFFFFF), RoundedCornerShape(14.dp)).clickable(onClick = onClick)
        .padding(8.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Text(title, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
        Text(sub, color = if (on) C.soft else C.muted, fontSize = 12.sp)
    }

@Composable
private fun Toggle(title: String, sub: String, checked: Boolean, enabled: Boolean = true, onChange: (Boolean) -> Unit) =
    Row(Modifier.fillMaxWidth().heightIn(min = 56.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) { Text(title); Hint(sub) }
        Switch(checked, onChange, enabled = enabled, colors = SwitchDefaults.colors(checkedTrackColor = C.accent, checkedThumbColor = C.onAccent))
    }

@Composable
private fun LinkRow(title: String, value: String, onClick: () -> Unit) =
    Row(Modifier.fillMaxWidth().heightIn(min = 52.dp).clickable(onClick = onClick), verticalAlignment = Alignment.CenterVertically) {
        Text(title, modifier = Modifier.weight(1f))
        Text(value, color = C.muted)
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
    val fieldColors = OutlinedTextFieldDefaults.colors(focusedBorderColor = C.accent, unfocusedBorderColor = C.line, cursorColor = C.accent)

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

    Column(Modifier.fillMaxSize().background(glow).verticalScroll(rememberScrollState()).padding(horizontal = 28.dp, vertical = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Image(painterResource(R.drawable.amadeus_logo), "Amadeus", Modifier.size(150.dp))
        Text("AMADEUS", fontFamily = Display, fontWeight = FontWeight.SemiBold, fontSize = 30.sp, letterSpacing = 9.sp)
        Text("On your PC open the dashboard → Phone → Pair a phone, then scan the QR code.", color = C.soft,
            textAlign = TextAlign.Center, fontSize = 15.sp)
        FilledButton(if (busy) "Pairing…" else "Scan QR code", C.accent, {
            scan.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE).setPrompt("Scan the QR code on your PC")
                .setBeepEnabled(false).setOrientationLocked(false))
        }, Modifier.fillMaxWidth().padding(top = 10.dp), textColor = C.onAccent, enabled = !busy)
        error?.let { Text(it, color = C.warn, fontSize = 14.sp, textAlign = TextAlign.Center) }

        if (!typing) Text("Enter the code instead", color = C.accent, fontSize = 14.sp, modifier = Modifier.clickable { typing = true }.padding(10.dp))
        else {
            OutlinedTextField(host, { host = it.trim() }, Modifier.fillMaxWidth(), label = { Text("Your PC (Tailscale)") },
                placeholder = { Text("pc-name.tailXXXX.ts.net") }, singleLine = true,
                colors = fieldColors, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
            OutlinedTextField(code, { code = it.filter(Char::isDigit).take(6) }, Modifier.fillMaxWidth(), label = { Text("6-digit code") }, singleLine = true,
                colors = fieldColors, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 26.sp, letterSpacing = 10.sp, textAlign = TextAlign.Center))
            LineButton("Pair", { pair(host, code) }, Modifier.fillMaxWidth(), enabled = !busy && code.length == 6 && AmadeusApi.allowedHost(host))
        }
        Hint("Only works inside your private Tailscale network. The phone gets its own key; remove it any time on the PC.",
            Modifier.padding(top = 20.dp))
    }
}
