package io.github.iabrahami.amadeus.ui

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.iabrahami.amadeus.assistantName
import org.json.JSONObject
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private class MailData(val connected: Boolean, val accounts: List<JSONObject>, val unread: Map<String, Int>, val vip: List<String>)

/** Mail: one inbox per account (read on your PC, nothing is stored on the phone). Sorting and writing go through the assistant. */
@Composable
fun MailScreen(nav: Nav) {
    val ctx = LocalContext.current
    val data = load("mail") { api ->
        val st = api.mailStatus()
        val off = st.optJSONArray("off")?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()
        val accounts = st.optJSONArray("accounts")?.objects().orEmpty().filter { it.optString("id") !in off }
        val connected = st.optBoolean("connected") && accounts.isNotEmpty()
        val unread = if (connected) api.mailUnread().objects().groupingBy { it.optString("accountId") }.eachCount() else emptyMap()
        val vip = st.optJSONArray("vip")?.let { a -> (0 until a.length()).map { a.getString(it).lowercase() } }.orEmpty()
        MailData(connected, accounts, unread, vip)
    }
    val d = data.value.data
    var acc by rememberSaveable { mutableStateOf<String?>(null) }
    LaunchedEffect(d) { if (d != null && d.accounts.none { it.optString("id") == acc }) acc = d.accounts.firstOrNull()?.optString("id") }
    val list = load("mailList", acc) { api -> acc?.let { api.mailRecent(it).objects() } }
    Column(Modifier.fillMaxSize()) {
        Header("Mail") { d?.unread?.values?.sum()?.takeIf { it > 0 }?.let { MonoText("$it unread", color = C.accent) } }
        ErrorLine(data.value.error ?: list.value.error) { data.reload(); list.reload() }
        if (d != null && !d.connected) {
            CrtBox(Modifier.padding(16.dp)) {
                Label("No mail account yet", color = C.accent)
                Hint("Connect your accounts on the PC: dashboard → Mail → + Add account. They show up here right away.", Modifier.padding(top = 6.dp))
            }
            return@Column
        }
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            d?.accounts.orEmpty().forEach { a ->
                val id = a.optString("id"); val on = id == acc; val n = d?.unread?.get(id) ?: 0
                Row(Modifier.heightIn(min = 40.dp).border(1.dp, if (on) C.accent else C.line).background(if (on) C.accent.copy(alpha = .1f) else Color.Transparent)
                    .clickable(role = Role.Tab) { acc = id }.padding(horizontal = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Label(a.optString("name"), color = if (on) C.accent else C.text.copy(alpha = .8f), size = 11.sp, spacing = 1.sp)
                    if (n > 0) Tag("$n", TagKind.Accent, Modifier.padding(start = 6.dp))
                }
            }
            Box(Modifier.size(40.dp).border(1.dp, C.line).clickable {
                Toast.makeText(ctx, "Add an account on the PC: dashboard → Mail → + Add account", Toast.LENGTH_LONG).show()
            }.semantics { contentDescription = "Add an account" }, contentAlignment = Alignment.Center) { Text("+", color = C.accent, fontSize = 18.sp) }
        }
        LazyColumn(Modifier.weight(1f).padding(horizontal = 16.dp)) {
            val mails = list.value.data.orEmpty()
            if (!list.value.loading && list.value.error == null && mails.isEmpty() && acc != null) item { Hint("Nothing in the last 7 days.", Modifier.padding(vertical = 12.dp)) }
            if (list.value.loading && mails.isEmpty()) item { Hint("Loading…", Modifier.padding(vertical = 12.dp)) }
            items(mails, key = { it.optLong("id") }) { m -> MailRow(m, important(m, d?.vip.orEmpty())) { nav.go(Screen.MailRead(m.optLong("id"))) } }
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            HudButton("Sort my inbox", { nav.askAmadeus("sort my inbox") }, Modifier.weight(1f), Btn.Go)
            HudButton("Write a mail", { nav.askAmadeus("Write a mail to ", send = false) }, Modifier.weight(1f))
        }
    }
}

/** From someone on your important-people list (Memory page on the PC). */
private fun important(m: JSONObject, vip: List<String>): Boolean {
    val from = m.optString("from").lowercase()
    return vip.any { it.isNotBlank() && from.contains(it) }
}

@Composable
private fun MailRow(m: JSONObject, important: Boolean, onClick: () -> Unit) {
    val unread = !m.optBoolean("read", true)
    Row(Modifier.fillMaxWidth().heightIn(min = 60.dp).clickable(onClick = onClick)
        .drawBehind { drawLine(C.line, Offset(0f, size.height), Offset(size.width, size.height), 1f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(6f, 5f))) }
        .padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (unread) Box(Modifier.padding(end = 6.dp).size(6.dp).background(C.accent))
                Body(sender(m.optString("from")), Modifier.weight(1f, fill = false), size = 15.sp, weight = if (unread) FontWeight.SemiBold else FontWeight.Normal, maxLines = 1)
                if (important) Tag("Important", TagKind.Amber, Modifier.padding(start = 6.dp))
            }
            Body(m.optString("subject").ifBlank { "(no subject)" }, color = C.dim, size = 13.sp, maxLines = 1)
        }
        MonoText(shortDate(m.optString("date")), Modifier.padding(start = 8.dp), size = 11.sp)
    }
}

/** "Anna Example <anna@example.org>" → "Anna Example". */
fun sender(from: String) = from.substringBefore('<').trim().trim('"').ifBlank { from.trim('<', '>') }

fun shortDate(iso: String): String = runCatching {
    val d = OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault())
    val days = java.time.temporal.ChronoUnit.DAYS.between(d.toLocalDate(), LocalDate.now())
    d.format(DateTimeFormatter.ofPattern(when { days == 0L -> "HH:mm"; days == 1L -> "'Yesterday'"; days < 7 -> "EEE"; else -> "d MMM" }, Locale.ENGLISH))
}.getOrDefault("")

/** One mail. Opening it marks it read, like any mail app. */
@Composable
fun MailReadScreen(nav: Nav, id: Long) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val data = load("mail", id) { it.mailMessage(id) }
    val m = data.value.data
    LaunchedEffect(m) { if (m != null && !m.optBoolean("read", true)) scope.io(ctx) { it.mailMarkRead(id, true) } }
    Column(Modifier.fillMaxSize()) {
        SubHeader(nav, "Mail")
        ErrorLine(data.value.error) { data.reload() }
        if (m == null) { if (data.value.loading) Hint("Loading…", Modifier.padding(16.dp)); return@Column }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Body(m.optString("subject").ifBlank { "(no subject)" }, size = 19.sp, weight = FontWeight.SemiBold)
            MonoText(m.optString("from"), Modifier.padding(top = 6.dp))
            MonoText(shortDate(m.optString("date")))
            m.optJSONArray("attachments")?.objects()?.takeIf { it.isNotEmpty() }?.let { a ->
                Hint("Attachments: " + a.joinToString(", ") { it.optString("name") })
            }
            Box(Modifier.fillMaxWidth().padding(vertical = 12.dp).heightIn(min = 1.dp).background(C.line))
            Body(m.optString("body") + if (m.optBoolean("truncated")) "\n[…]" else "", size = 15.sp)
            Gap(16.dp)
        }
        val subject = m.optString("subject")
        Row(Modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            HudButton("Summarize", { nav.askAmadeus("Summarize email [$id] (\"$subject\") in a few sentences and tell me if I need to do anything.") }, Modifier.weight(1f))
            HudButton("Reply with ${ctx.assistantName}", { nav.askAmadeus("Draft a reply to email [$id] (\"$subject\") from ${m.optString("from")}. My points: ", send = false) },
                Modifier.weight(1f), Btn.Go)
        }
        HudButton("Mark unread", { scope.io(ctx, done = { nav.back() }) { it.mailMarkRead(id, false) } }, Modifier.fillMaxWidth().padding(16.dp))
    }
}
