package io.github.iabrahami.amadeus.ui

import io.github.iabrahami.amadeus.assistantName
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONArray
import org.json.JSONObject
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale

fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }

/** Everything waiting for your OK. Nothing changes until you approve. */
@Composable
fun ApprovalsScreen(nav: Nav) {
    val data = load("approvals") { it.approvals().objects() }
    val approvals = data.value.data.orEmpty()
    Column(Modifier.fillMaxSize()) {
        BackHeader(nav, "Approvals", trailing = {
            val n = approvals.size
            if (n > 0) Text("$n", color = C.onAccent, fontWeight = FontWeight.SemiBold, fontSize = 13.sp,
                modifier = Modifier.background(C.accent, RoundedCornerShape(12.dp)).padding(horizontal = 10.dp, vertical = 2.dp))
        })
        Hint("Nothing changes until you approve it.", Modifier.padding(start = 16.dp, bottom = 12.dp))
        ErrorLine(data.value.error) { data.reload() }
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (!data.value.loading && approvals.isEmpty()) Hint("All clear. Nothing is waiting for you.")
            approvals.forEach { a ->
                Card(border = C.line) {
                    Text(toolLabel(a.optString("tool")), color = C.accent, fontSize = 13.sp)
                    Text(plain(a.optString("summary")), fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(vertical = 8.dp))
                    ApproveRow(a.getString("id")) { data.reload() }
                }
            }
            Spacer(Modifier.size(84.dp))
        }
    }
}

private fun toolLabel(tool: String) = when {
    tool.startsWith("calendar") -> "Calendar"
    tool.startsWith("mail") -> "Mail"
    tool.startsWith("todo") -> "ToDo"
    tool.startsWith("note") -> "Notes"
    tool.startsWith("send_to_work") || tool.startsWith("continue_project") || tool.startsWith("start_work") -> "Work (Claude Code)"
    else -> tool.replace('_', ' ').replaceFirstChar { it.uppercase() }
}

/** Your day: the week, the calendar, your ToDo (ToDo.md in Obsidian), and "plan my day" with the assistant. */
@Composable
fun TodayScreen(nav: Nav) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val today = remember { LocalDate.now() }
    var day by remember { mutableStateOf(today) }
    val monday = today.with(DayOfWeek.MONDAY)
    val cal = load("cal", monday) { it.calendar(monday, monday.plusDays(7)).objects() }
    val todo = load("todo") { it.todo() }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        Title("Today", day.format(DateTimeFormatter.ofPattern("EEEE d MMMM", Locale.ENGLISH)))
        Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            (0..6).map { monday.plusDays(it.toLong()) }.forEach { d ->
                val on = d == day
                Column(Modifier.weight(1f).heightIn(min = 52.dp).background(if (on) C.accent else Color.Transparent, RoundedCornerShape(12.dp))
                    .clickable { day = d }.padding(vertical = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(d.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.ENGLISH).take(2), fontSize = 12.sp, color = if (on) C.onAccent else C.muted)
                    Text("${d.dayOfMonth}", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = if (on) C.onAccent else C.text)
                }
            }
        }
        ErrorLine(cal.value.error ?: todo.value.error) { cal.reload(); todo.reload() }

        Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Section("Schedule")
            val items = cal.value.data.orEmpty().filter { o ->
                val s = LocalDate.parse(o.optString("occ_start").take(10))
                val e = LocalDate.parse(o.optString("occ_end").take(10))
                if (o.optInt("all_day") == 1) !day.isBefore(s) && day.isBefore(e) else !day.isBefore(s) && !day.isAfter(e)
            }
            if (!cal.value.loading && items.isEmpty()) Hint("Nothing in your calendar.")
            items.forEach { o ->
                val allDay = o.optInt("all_day") == 1
                Row(verticalAlignment = Alignment.Top) {
                    Text(if (allDay) "all day" else o.optString("occ_start").drop(11).take(5), color = C.muted, fontSize = 13.sp,
                        modifier = Modifier.width(56.dp).padding(top = 10.dp))
                    Column(Modifier.weight(1f).background(C.card, RoundedCornerShape(12.dp)).padding(horizontal = 12.dp, vertical = 10.dp)) {
                        Text(o.optString("title"), fontWeight = FontWeight.SemiBold)
                        val sub = listOfNotNull(
                            if (!allDay) "until " + o.optString("occ_end").drop(11).take(5) else null,
                            o.optString("location").ifBlank { null },
                            if (o.optString("repeat").isNotBlank()) "repeats" else null,
                        ).joinToString(" · ")
                        if (sub.isNotBlank()) Text(sub, color = C.muted, fontSize = 12.sp)
                    }
                }
            }

            Spacer(Modifier.size(8.dp))
            Section("ToDo")
            if (!todo.value.loading && todo.value.data.isNullOrEmpty()) Hint("Your ToDo is empty.")
            todo.value.data.orEmpty().forEach { item ->
                Row(Modifier.fillMaxWidth().heightIn(min = 44.dp), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(false, { scope.io(ctx, done = { todo.reload() }) { it.todoDone(item) } },
                        colors = CheckboxDefaults.colors(uncheckedColor = C.accent))
                    Text(item, fontSize = 14.sp)
                }
            }
        }
        LineButton("Plan my day with ${LocalContext.current.assistantName}", { nav.askAmadeus("plan my day") }, Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 84.dp))
    }
}

@Composable
fun Centered(text: String) = Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
    Text(text, color = C.muted, textAlign = TextAlign.Center, modifier = Modifier.padding(24.dp))
}
