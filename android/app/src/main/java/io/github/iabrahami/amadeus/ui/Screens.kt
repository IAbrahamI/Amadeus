package io.github.iabrahami.amadeus.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.iabrahami.amadeus.assistantName
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.time.DayOfWeek
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.TextStyle
import java.util.Locale

// ---------- Today: the day (calendar, reminders, to-dos) and the Reminders tab ----------

@Composable
fun TodayScreen(nav: Nav) {
    Column(Modifier.fillMaxSize()) {
        Header("Today", onMark = { nav.tab(Screen.Home) }) {
            Seg(listOf("day" to "Day", "reminders" to "Reminders"), nav.todayTab, { nav.todayTab = it })
        }
        if (nav.todayTab == "reminders") RemindersView(nav) else DayView(nav)
    }
}

/** A reminder: its text (without the mail marker), the mail it's about, how it repeats, and its next time. */
class Reminder(o: JSONObject) {
    val id: String = o.optString("id")
    private val raw: String = o.optString("text")
    val text = raw.replace(Regex("\\s*\\[mail:\\d+\\]"), "").trim()
    val mail: Long? = Regex("\\[mail:(\\d+)\\]").find(raw)?.groupValues?.get(1)?.toLongOrNull()
    val schedule: String = o.optString("schedule")
    val next: LocalDateTime? = o.optDouble("next_run", 0.0).takeIf { it > 0 }
        ?.let { LocalDateTime.ofInstant(Instant.ofEpochMilli((it * 1000).toLong()), ZoneId.systemDefault()) }
    private val parts = schedule.split(" ")
    val time: String = parts.lastOrNull()?.takeIf { it.matches(Regex("\\d{1,2}:\\d{2}")) } ?: next?.toLocalTime()?.toString()?.take(5) ?: ""
    /** "Once", "Daily", "Weekdays", "Weekly · Mon". */
    val repeat: String? = when (parts.firstOrNull()) {
        "daily" -> "Daily"; "weekdays" -> "Weekdays"
        "weekly" -> "Weekly · " + parts.getOrNull(1).orEmpty().replaceFirstChar { it.uppercase() }
        else -> null
    }

    /** Does it ring on this day? */
    fun on(day: LocalDate): Boolean {
        val from = next?.toLocalDate() ?: return false
        if (day.isBefore(from)) return false
        return when (parts.firstOrNull()) {
            "daily" -> true
            "weekdays" -> day.dayOfWeek.value <= 5
            "weekly" -> day.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.ENGLISH).lowercase().startsWith(parts.getOrNull(1).orEmpty().take(3))
            else -> day == from
        }
    }
}

private class Item(val time: String, val title: String, val sub: String, val color: Color, val reminder: Boolean, val onClick: (() -> Unit)? = null)

@Composable
private fun DayView(nav: Nav) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val today = remember { LocalDate.now() }
    var day by remember { mutableStateOf(today) }
    val monday = today.with(DayOfWeek.MONDAY)
    val cal = load("cal", monday) { it.calendar(monday, monday.plusDays(7)).objects() }
    val rem = load("rem") { it.reminders().objects().map(::Reminder) }
    val todo = load("todo") { it.todo() }
    val events = cal.value.data.orEmpty()
    val reminders = rem.value.data.orEmpty()
    fun eventsOn(d: LocalDate) = events.filter { o ->
        val s = LocalDate.parse(o.optString("occ_start").take(10)); val e = LocalDate.parse(o.optString("occ_end").take(10))
        if (o.optInt("all_day") == 1) !d.isBefore(s) && d.isBefore(e) else !d.isBefore(s) && !d.isAfter(e)
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        // the week
        Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            (0..6).map { monday.plusDays(it.toLong()) }.forEach { d ->
                val on = d == day
                val busy = eventsOn(d).isNotEmpty() || reminders.any { it.on(d) }
                Column(Modifier.weight(1f).heightIn(min = 58.dp).border(1.dp, if (on) C.accent else Color.Transparent)
                    .background(if (on) C.accent.copy(alpha = .08f) else Color.Transparent).clickable(role = Role.Tab) { day = d }.padding(vertical = 6.dp),
                    horizontalAlignment = Alignment.CenterHorizontally) {
                    Label(d.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.ENGLISH), color = if (on || d == today) C.accent else C.dim, size = 10.sp, spacing = 1.sp)
                    Text("${d.dayOfMonth}", color = if (on) C.text else C.text.copy(alpha = .8f), fontFamily = Mono, fontSize = 17.sp)
                    Box(Modifier.size(4.dp).background(if (busy) C.accent else Color.Transparent))
                }
            }
        }
        ErrorLine(cal.value.error ?: rem.value.error ?: todo.value.error) { cal.reload(); rem.reload(); todo.reload() }

        Rule("Calendar" + if (day == today) "" else " · " + day.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.ENGLISH) + " ${day.dayOfMonth}")
        val name = ctx.assistantName
        val items = eventsOn(day).map { o ->
            val allDay = o.optInt("all_day") == 1
            val sub = listOfNotNull(
                if (o.optString("created_by") == "amadeus") "Planned by $name" else null,
                o.optString("location").ifBlank { null },
                if (!allDay) "until " + o.optString("occ_end").drop(11).take(5) else null,
                if (o.optString("repeat").isNotBlank()) "repeats" else null,
            ).joinToString(" · ")
            Item(if (allDay) "all day" else o.optString("occ_start").drop(11).take(5), o.optString("title"), sub,
                if (o.optString("created_by") == "amadeus") C.green else C.accent, false)
        } + reminders.filter { it.on(day) }.map { r ->
            Item(r.time, r.text, listOfNotNull("Reminder", r.repeat, if (r.mail != null) "about a mail" else null).joinToString(" · "), C.accent, true,
                r.mail?.let { m -> { nav.tab(Screen.Mail); nav.go(Screen.MailRead(m)) } })
        }
        val sorted = items.sortedBy { if (it.time == "all day") "" else it.time }
        val now = LocalTime.now().toString().take(5)
        var nowShown = day != today
        if (!cal.value.loading && !rem.value.loading && sorted.isEmpty()) Hint("Nothing planned.", Modifier.padding(vertical = 6.dp))
        sorted.forEach { it ->
            if (!nowShown && it.time != "all day" && it.time > now) { NowLine(now); nowShown = true }
            TimelineRow(it)
        }
        if (!nowShown && sorted.isNotEmpty()) NowLine(now)

        Rule("To-dos · ToDo.md")
        var adding by remember { mutableStateOf(false) }
        var newItem by remember { mutableStateOf("") }
        fun addTodo() {
            val t = newItem.trim(); if (t.isEmpty()) return
            newItem = ""; adding = false
            scope.io(ctx, done = { todo.reload() }) { it.todoAdd(t) }
        }
        if (!adding) Row(Modifier.fillMaxWidth().heightIn(min = 46.dp).dashed(C.lineHi).clickable { adding = true }.padding(horizontal = 12.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text("+ ", color = C.accent, fontFamily = Mono, fontSize = 14.sp); MonoText("Add a to-do", size = 13.sp)
        } else Row(verticalAlignment = Alignment.CenterVertically) {
            HudField(newItem, { newItem = it }, "What needs doing?", Modifier.weight(1f), imeAction = ImeAction.Done, onDone = ::addTodo)
            HudButton("Add", ::addTodo, Modifier.padding(start = 8.dp), Btn.Go, enabled = newItem.isNotBlank())
        }
        if (!todo.value.loading && todo.value.data.isNullOrEmpty()) Hint("Your to-do list is empty.", Modifier.padding(vertical = 8.dp))
        todo.value.data.orEmpty().forEach { item ->
            var ticked by remember(item) { mutableStateOf(false) }
            Row(Modifier.fillMaxWidth().heightIn(min = 48.dp).clickable(enabled = !ticked, role = Role.Checkbox) {
                ticked = true
                scope.io(ctx, done = { todo.reload() }) { it.todoDone(item) }
            }.semantics { contentDescription = "$item, tap to mark done" }, verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(18.dp).border(1.5.dp, C.accent).background(if (ticked) C.accent else Color.Transparent))
                Body(item, Modifier.padding(start = 12.dp), size = 15.sp, color = if (ticked) C.dim else C.text)
            }
        }
        HudButton("Plan my day with $name", { nav.askAmadeus("plan my day") }, Modifier.fillMaxWidth().padding(top = 16.dp, bottom = 20.dp), Btn.Go)
    }
}

@Composable
private fun TimelineRow(it: Item) = Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min).let { m -> it.onClick?.let { m.clickable(onClick = it) } ?: m }
    .padding(vertical = 6.dp)) {
    MonoText(it.time, Modifier.width(56.dp).padding(top = 2.dp))
    Box(Modifier.width(2.dp).fillMaxHeight().drawBehind {
        if (it.reminder) drawLine(it.color, Offset(size.width / 2, 0f), Offset(size.width / 2, size.height), size.width,
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx())))
        else drawRect(it.color)
    })
    Column(Modifier.weight(1f).padding(start = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (it.reminder) Text("🔔 ", fontSize = 11.sp)
            Body(it.title, size = 15.sp, weight = FontWeight.Medium)
        }
        if (it.sub.isNotBlank()) Hint(it.sub)
    }
}

@Composable
private fun NowLine(now: String) = Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
    Box(Modifier.weight(1f).height(1.dp).background(C.red))
    Text(" NOW $now", color = C.red, fontFamily = Mono, fontSize = 10.sp)
}

@Composable
private fun RemindersView(nav: Nav) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val rem = load("rem") { it.reminders().objects().map(::Reminder) }
    var text by remember { mutableStateOf("") }
    var whenText by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    fun add() {
        if (text.isBlank() || whenText.isBlank() || busy) return
        busy = true; error = null
        scope.launch {
            val r = withContext(Dispatchers.IO) { runCatching { ctx.api.addReminder(text.trim(), whenText.trim()) } }
            busy = false
            r.onSuccess { text = ""; whenText = ""; rem.reload() }.onFailure { error = it.message ?: "Couldn't reach your PC" }
        }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        Rule("New reminder")
        CrtBox(pad = 12.dp) {
            HudField(text, { text = it; error = null }, "Remind me to…", Modifier.fillMaxWidth(), imeAction = ImeAction.Next)
            Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                HudField(whenText, { whenText = it; error = null }, "Every weekday 18:00", Modifier.weight(1f), error = error != null,
                    imeAction = ImeAction.Done, onDone = ::add)
                HudButton(if (busy) "…" else "Add", ::add, Modifier.padding(start = 8.dp), Btn.Go, enabled = text.isNotBlank() && whenText.isNotBlank() && !busy)
            }
            if (error != null) Text(error!!, Modifier.padding(top = 8.dp), color = C.red, fontFamily = Mono, fontSize = 12.sp)
            Hint("Plain words work: \"tomorrow 9\", \"every Monday 18:00\", \"in 10 minutes\". Or just ask in the chat.", Modifier.padding(top = 8.dp))
        }
        Rule("Coming up")
        ErrorLine(rem.value.error) { rem.reload() }
        val list = rem.value.data.orEmpty().sortedBy { it.next }
        if (!rem.value.loading && list.isEmpty()) Hint("No reminders. Add one above, or ask in the chat.")
        list.forEach { r -> ReminderRow(r, nav) { scope.io(ctx, done = { rem.reload() }) { it.deleteReminder(r.id) } } }
        Gap(20.dp)
    }
}

@Composable
private fun ReminderRow(r: Reminder, nav: Nav, remove: () -> Unit) {
    val today = LocalDate.now()
    val d = r.next?.toLocalDate()
    val dayLabel = when (d) { null -> ""; today -> "Today"; today.plusDays(1) -> "Tomorrow"
        else -> d.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.ENGLISH) + " ${d.dayOfMonth}" }
    Row(Modifier.fillMaxWidth().heightIn(min = 60.dp).let { m -> r.mail?.let { id -> m.clickable { nav.tab(Screen.Mail); nav.go(Screen.MailRead(id)) } } ?: m }
        .drawBehind { drawLine(C.line, Offset(0f, size.height), Offset(size.width, size.height), 1f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(6f, 5f))) }
        .padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.width(76.dp)) {
            MonoText(r.next?.toLocalTime()?.toString()?.take(5) ?: r.time, color = C.accent, size = 13.sp)
            Label(dayLabel, size = 9.sp, spacing = 1.sp)
        }
        Column(Modifier.weight(1f)) {
            Body(r.text, size = 15.sp, weight = FontWeight.Medium, maxLines = 2)
            Row(Modifier.padding(top = 3.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                when {
                    r.mail != null -> Tag("✉ About a mail", TagKind.Line)
                    r.repeat != null -> Tag("↻ " + r.repeat, TagKind.Line)
                    else -> Hint("Once")
                }
                if (r.mail != null && r.repeat != null) Tag("↻ " + r.repeat, TagKind.Line)
            }
        }
        HudButton("Remove", remove, Modifier.padding(start = 8.dp))
    }
}

// ---------- Approvals ----------

/** Everything waiting for your OK: reject, adjust (say what should be different) or approve. Nothing runs before you approve. */
@Composable
fun ApprovalsScreen(nav: Nav, changed: () -> Unit) {
    val data = load("approvals") { it.approvals().objects() }
    val approvals = data.value.data.orEmpty()
    Column(Modifier.fillMaxSize()) {
        SubHeader(nav, "Approvals") { if (approvals.isNotEmpty()) Tag("${approvals.size} waiting", TagKind.Amber) }
        ErrorLine(data.value.error) { data.reload() }
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            if (!data.value.loading && approvals.isEmpty()) Hint("All clear. Nothing is waiting for you.", Modifier.padding(top = 8.dp))
            approvals.forEach { a -> key(a.optString("id") + a.optInt("revised")) { ApprovalCard(a) { data.reload(); changed() } } }
            Hint("Nothing runs before you approve it.", Modifier.padding(bottom = 20.dp))
        }
    }
}

@Composable
fun ApprovalCard(a: JSONObject, done: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val id = a.optString("id")
    var busy by remember { mutableStateOf(false) }
    var adjusting by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    CrtBox(amber = true) {
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Tag(toolLabel(a.optString("tool")), TagKind.Amber)
            if (a.optInt("revised") > 0) Tag("Revised", TagKind.AmberLine)
        }
        Text(md(a.optString("summary")), Modifier.padding(top = 10.dp), color = C.text.copy(alpha = .9f), fontFamily = Plex, fontSize = 15.sp, lineHeight = 21.sp)
        a.optString("feedback").takeIf { it.isNotBlank() && it != "null" }?.let {
            Text("Changed: $it", Modifier.padding(top = 6.dp), color = C.amber, fontFamily = Mono, fontSize = 12.sp)
        }
        if (adjusting) {
            HudField(note, { note = it; error = null }, "What should be different?", Modifier.fillMaxWidth().padding(top = 10.dp), maxLines = 4)
            Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                HudButton("Cancel", { adjusting = false; note = "" }, Modifier.weight(1f), enabled = !busy)
                HudButton(if (busy) "Redrafting…" else "Send", {
                    busy = true; error = null
                    scope.launch {
                        val r = withContext(Dispatchers.IO) { runCatching { ctx.api.revise(id, note.trim()) } }
                        busy = false
                        val err = r.exceptionOrNull()?.message ?: r.getOrNull()?.optString("error")?.ifBlank { null }
                        if (err != null) error = err else { adjusting = false; note = ""; done() }
                    }
                }, Modifier.weight(1f), Btn.Amber, enabled = note.isNotBlank() && !busy)
            }
        } else Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            HudButton("Reject", { busy = true; scope.io(ctx, done = { busy = false; done() }) { it.decide(id, false) } }, Modifier.weight(1f), enabled = !busy)
            HudButton("Adjust", { adjusting = true }, Modifier.weight(1f), Btn.Amber, enabled = !busy)
            HudButton("Approve", { busy = true; scope.io(ctx, done = { busy = false; done() }) { it.decide(id, true) } }, Modifier.weight(1f), Btn.Go, enabled = !busy)
        }
        if (error != null) Text(error!!, Modifier.padding(top = 8.dp), color = C.red, fontFamily = Mono, fontSize = 12.sp)
    }
}

fun toolLabel(tool: String) = when {
    tool.startsWith("calendar") -> "Calendar"
    tool.startsWith("mail") -> "Mail"
    tool.startsWith("todo") -> "To-do"
    tool.startsWith("note") -> "Notes"
    tool.contains("reminder") -> "Reminder"
    tool.startsWith("send_to_work") || tool.startsWith("continue_project") || tool.startsWith("start_work") -> "Work"
    tool.startsWith("brief") -> "Your day"
    tool == "suggest_improvement" -> "Improvement"
    tool == "learn_from_web" -> "Learning"
    else -> tool.replace('_', ' ')
}

// ---------- More's pages: Projects, Your day, Memory ----------

@Composable
fun ProjectsScreen(nav: Nav) {
    val data = load("projects") { it.projects().objects() }
    Column(Modifier.fillMaxSize()) {
        SubHeader(nav, "Projects")
        ErrorLine(data.value.error) { data.reload() }
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Hint("Claude Code runs on your PC. Ask in the chat to start or continue one.")
            if (!data.value.loading && data.value.data.isNullOrEmpty()) Hint("No projects yet.", Modifier.padding(top = 12.dp))
            data.value.data.orEmpty().forEach { p ->
                val state = p.optString("state")
                HudRow(p.optString("name"), "${p.optInt("files")} files · " + ago(p.optDouble("updated", 0.0)),
                    onClick = { nav.askAmadeus("How is the project ${p.optString("name")} going?", send = false) }) {
                    when (state) {
                        "needs" -> Tag("Needs you", TagKind.Amber)
                        "active" -> Tag("Working", TagKind.Accent)
                        "done" -> Tag("Done", TagKind.Line)
                        else -> Label("Idle")
                    }
                }
            }
            Gap(20.dp)
        }
    }
}

private fun ago(epoch: Double): String {
    if (epoch <= 0) return ""
    val t = LocalDateTime.ofInstant(Instant.ofEpochMilli((epoch * 1000).toLong()), ZoneId.systemDefault())
    return if (t.toLocalDate() == LocalDate.now()) "today " + t.toLocalTime().toString().take(5)
    else "${t.dayOfMonth} " + t.month.getDisplayName(TextStyle.SHORT, Locale.ENGLISH)
}

@Composable
fun YourDayScreen(nav: Nav) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val data = load("yourday") { it.day().optJSONArray("reports")?.objects().orEmpty() }
    var busy by remember { mutableStateOf(false) }
    val label = mapOf("morning" to "Morning brief", "now" to "So far today", "evening" to "Evening summary")
    Column(Modifier.fillMaxSize()) {
        SubHeader(nav, "Your day")
        ErrorLine(data.value.error) { data.reload() }
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            if (!data.value.loading && data.value.data.isNullOrEmpty()) Hint("No brief yet today.")
            data.value.data.orEmpty().forEach { r ->
                Rule(label[r.optString("kind")] ?: r.optString("kind"))
                Text(md(r.optString("text")), color = C.text.copy(alpha = .9f), fontFamily = Plex, fontSize = 15.sp, lineHeight = 21.sp)
            }
            Row(Modifier.padding(vertical = 18.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                HudButton(if (busy) "Summarizing…" else "Summarize so far", {
                    busy = true; scope.io(ctx, done = { busy = false; data.reload() }) { it.daySoFar() }
                }, Modifier.weight(1f), enabled = !busy)
                HudButton("Plan my day", { nav.askAmadeus("plan my day") }, Modifier.weight(1f), Btn.Go)
            }
            Hint("What goes into the briefs and when: ask in the chat (\"add the weather to my morning brief\").", Modifier.padding(bottom = 20.dp))
        }
    }
}

@Composable
fun MemoryScreen(nav: Nav) {
    val name = LocalContext.current.assistantName
    val data = load("memory") { it.memory().optString("text") }
    Column(Modifier.fillMaxSize()) {
        SubHeader(nav, "Memory")
        ErrorLine(data.value.error) { data.reload() }
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Hint("What $name knows about you and your work, kept on your PC.")
            if (data.value.loading && data.value.data == null) Hint("Loading…", Modifier.padding(top = 12.dp))
            data.value.data?.let { Text(md(it), Modifier.padding(top = 12.dp, bottom = 20.dp), color = C.text.copy(alpha = .9f), fontFamily = Plex, fontSize = 14.sp, lineHeight = 20.sp) }
        }
    }
}
