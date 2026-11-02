package io.github.iabrahami.amadeus.ui

import io.github.iabrahami.amadeus.assistantName
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Your open (unread) mail, by account and folder. Read from Thunderbird on your PC; nothing is stored on the phone. */
@Composable
fun MailScreen(nav: Nav) {
    val data = load("mail") { api ->
        val accounts = api.mailStatus().optJSONArray("accounts")?.objects().orEmpty().associate { it.optString("id") to it.optString("name") }
        accounts to api.mailUnread().objects()
    }
    val (accounts, mails) = data.value.data ?: (emptyMap<String, String>() to emptyList())
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
            Column(Modifier.weight(1f)) {
                Title("Mail", if (data.value.data == null) "Loading…" else "${mails.size} open · ${accounts.size} account${if (accounts.size == 1) "" else "s"}")
            }
            LineButton("Sort my inbox", { nav.askAmadeus("sort my inbox") }, Modifier.padding(end = 16.dp, bottom = 10.dp))
        }
        Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Chip("Open", true) {}
            Chip("Codes & links", false) { nav.askAmadeus("show my verification codes and links") }
            Chip("What's important?", false) { nav.askAmadeus("which of my open mails are important?") }
        }
        ErrorLine(data.value.error) { data.reload() }
        LazyColumn(Modifier.weight(1f).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            if (!data.value.loading && data.value.error == null && mails.isEmpty()) item { Hint("No open mail.") }
            mails.groupBy { it.optString("accountId") }.forEach { (acc, inAcc) ->
                item(key = "a$acc") {
                    Text("${accounts[acc] ?: "Mail"} · ${inAcc.size}", color = C.accent, fontFamily = Display, fontWeight = FontWeight.SemiBold,
                        fontSize = 16.sp, modifier = Modifier.padding(top = 10.dp))
                }
                inAcc.groupBy { it.optString("folder").trim('/') }.forEach { (folder, inFolder) ->
                    item(key = "f$acc$folder") {
                        Text("${folder.ifBlank { "Inbox" }.uppercase()} (${inFolder.size})", color = C.muted, fontSize = 12.sp, letterSpacing = 1.sp,
                            modifier = Modifier.padding(top = 4.dp))
                    }
                    items(inFolder, key = { "m" + it.optLong("id") }) { m ->
                        MailRow(m) { nav.go(Screen.MailRead(m.optLong("id"))) }
                    }
                }
            }
            item { Spacer(Modifier.size(8.dp)) }
        }
        Row(Modifier.padding(start = 16.dp, top = 16.dp, bottom = 16.dp, end = 86.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            FilledButton("Ask about a mail", C.accent, { nav.askAmadeus("About my mail: ", send = false) }, Modifier.weight(1f), textColor = C.onAccent)
        }
    }
}

@Composable
private fun MailRow(m: JSONObject, onClick: () -> Unit) =
    Row(Modifier.fillMaxWidth().background(C.card, RoundedCornerShape(14.dp)).clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp)) {
        Column(Modifier.weight(1f)) {
            Text(sender(m.optString("from")), fontWeight = FontWeight.SemiBold, maxLines = 1)
            Text(m.optString("subject").ifBlank { "(no subject)" }, color = C.soft, fontSize = 14.sp, maxLines = 2)
        }
        Text(shortDate(m.optString("date")), color = C.muted, fontSize = 12.sp)
    }

@Composable
fun Chip(text: String, on: Boolean, onClick: () -> Unit) =
    Text(text, fontSize = 13.sp, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal, color = if (on) C.onAccent else C.text,
        modifier = Modifier.background(if (on) C.accent else C.card, RoundedCornerShape(16.dp)).clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp))

/** "Anna Example <anna@example.org>" → "Anna Example". */
fun sender(from: String) = from.substringBefore('<').trim().trim('"').ifBlank { from.trim('<', '>') }

fun shortDate(iso: String): String = runCatching {
    val d = OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault())
    d.format(DateTimeFormatter.ofPattern(if (d.toLocalDate() == java.time.LocalDate.now()) "HH:mm" else "d MMM"))
}.getOrDefault("")

/** One mail. Opening it marks it read in Thunderbird, like any mail app. */
@Composable
fun MailReadScreen(nav: Nav, id: Long) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val data = load("mail", id) { it.mailMessage(id) }
    val m = data.value.data
    LaunchedEffect(m) { if (m != null && !m.optBoolean("read", true)) scope.io(ctx) { it.mailMarkRead(id, true) } }
    Column(Modifier.fillMaxSize()) {
        BackHeader(nav, "Mail")
        ErrorLine(data.value.error) { data.reload() }
        if (m == null) { if (data.value.loading) Centered("Loading…"); return@Column }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Text(m.optString("subject").ifBlank { "(no subject)" }, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
            Text("From ${m.optString("from")}", color = C.muted, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
            Text(shortDate(m.optString("date")), color = C.muted, fontSize = 13.sp)
            m.optJSONArray("attachments")?.objects()?.takeIf { it.isNotEmpty() }?.let { a ->
                Text("Attachments: " + a.joinToString(", ") { it.optString("name") }, color = C.muted, fontSize = 13.sp)
            }
            Text(m.optString("body") + if (m.optBoolean("truncated")) "\n[…]" else "", fontSize = 15.sp, lineHeight = 22.sp,
                modifier = Modifier.padding(vertical = 14.dp))
        }
        val subject = m.optString("subject")
        Row(Modifier.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            LineButton("Summarize", { nav.askAmadeus("Summarize email [$id] (\"$subject\") in a few sentences and tell me if I need to do anything.") }, Modifier.weight(1f))
            FilledButton("Reply with ${LocalContext.current.assistantName}", C.accent, { nav.askAmadeus("Draft a reply to email [$id] (\"$subject\") from ${m.optString("from")}. My points: ", send = false) },
                Modifier.weight(1f), textColor = C.onAccent)
        }
        LineButton("Mark unread", { scope.io(ctx, done = { nav.back() }) { it.mailMarkRead(id, false) } }, Modifier.padding(start = 16.dp, end = 86.dp, bottom = 12.dp).fillMaxWidth())
    }
}
