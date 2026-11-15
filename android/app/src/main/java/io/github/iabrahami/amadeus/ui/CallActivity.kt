package io.github.iabrahami.amadeus.ui

import androidx.compose.ui.platform.LocalContext
import io.github.iabrahami.amadeus.assistantName
import android.content.ClipData
import android.content.ClipboardManager
import android.app.KeyguardManager
import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.iabrahami.amadeus.AmadeusApp
import androidx.lifecycle.lifecycleScope
import io.github.iabrahami.amadeus.link.Calls
import kotlinx.coroutines.launch
import org.json.JSONObject
import kotlin.concurrent.thread

/** Its call on the phone: full screen, its ringtone, the reason, and Answer / Later. */
class CallActivity : ComponentActivity() {
    private lateinit var ev: JSONObject

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        ev = runCatching { JSONObject(intent.getStringExtra("event") ?: "{}") }.getOrDefault(JSONObject())
        // the call ended elsewhere (answered on the PC, handled on the dashboard): close
        lifecycleScope.launch {
            Calls.ringing.collect { if (ev.optString("id") !in it) finish() }
        }
        val km = getSystemService(KeyguardManager::class.java)
        setContent {
            var locked by remember { mutableStateOf(km.isKeyguardLocked) }
            AmadeusTheme { CallScreen(ev, locked) { a -> if (a == "later") later() else unlockThen { locked = false; act(a) } } }
        }
        if (intent.getBooleanExtra("answer", false)) unlockThenAnswer()   // "Answer" right in the call notification
    }

    /**
     * Answering on the lock screen asks for your fingerprint / face right away, so answering and unlocking are one
     * step. Cancel it and the call keeps ringing.
     */
    private fun unlockThenAnswer() = unlockThen { answer() }

    private fun unlockThen(then: () -> Unit) {
        val km = getSystemService(KeyguardManager::class.java)
        if (!km.isKeyguardLocked) return then()
        km.requestDismissKeyguard(this, object : KeyguardManager.KeyguardDismissCallback() {
            override fun onDismissSucceeded() = then()
        })
    }

    /** What you picked in the bubble (after unlocking). */
    private fun act(a: String) {
        val app = application as AmadeusApp
        val e = ev
        when (a) {
            "talk" -> answer()
            "adjust" -> answer(openApprovals = true)
            "gotit", "snooze", "approve", "reject" -> {
                Calls.hangUp(this)
                thread {
                    runCatching {
                        when (a) {
                            "approve", "reject" -> app.api.decide(e.optString("ref"), a == "approve")
                            "snooze" -> {
                                val mail = Regex("^mail:(\\d+)$").find(e.optString("ref"))?.groupValues?.get(1)
                                app.api.addReminder(e.optString("title") + (mail?.let { " [mail:$it]" } ?: ""), "in 10 minutes")
                            }
                        }
                    }.onFailure { err -> runOnUiThread { Toast.makeText(app, err.message ?: "Couldn't reach your PC", Toast.LENGTH_LONG).show() } }
                    runCatching { Calls.declineOnPc(app, e.toString()) }
                }
                if (a == "snooze") Toast.makeText(this, "Again in 10 minutes", Toast.LENGTH_SHORT).show()
                finish()
            }
        }
    }

    /** Picked up: the PC stops ringing, and you're in the app. */
    private fun answer(openApprovals: Boolean = false) {
        Calls.hangUp(this)
        val app = application as AmadeusApp
        val e = ev
        thread {
            Calls.answerOnPc(app)
            if (!(e.optString("kind") == "approval" && e.optString("status") == "pending")) runCatching { app.api.markSeen(e.optString("id")) }
        }
        // a reminder about a mail opens that mail
        val mail = Regex("^mail:(\\d+)$").find(e.optString("ref"))?.groupValues?.get(1)?.toLongOrNull()
        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .apply { if (mail != null) putExtra("mail", mail); if (openApprovals) putExtra("approvals", true) })
        finish()
    }

    private fun later() {
        Calls.hangUp(this)
        val app = application as AmadeusApp
        val e = ev.toString()
        thread { runCatching { Calls.declineOnPc(app, e) } }
        finish()
    }
}

/**
 * Full screen, the core with its heartbeat, and why it calls in an amber bubble with what you can do about it right
 * there. On the lock screen the bubble only says to unlock: what it's about shows after you unlock.
 */
@Composable
private fun CallScreen(ev: JSONObject, locked: Boolean, act: (String) -> Unit) {
    val name = LocalContext.current.assistantName
    val kind = ev.optString("kind")
    Column(Modifier.fillMaxSize().hud().padding(horizontal = 20.dp, vertical = 40.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Tag("Incoming · " + if (kind == "mail_code") "urgent" else kindLabel(kind), TagKind.Amber)
        Text(name.uppercase(), Modifier.padding(top = 14.dp), color = C.text, fontFamily = Chakra, fontWeight = FontWeight.SemiBold, fontSize = 30.sp, letterSpacing = 8.sp)
        Label("Calling from your PC", Modifier.padding(top = 4.dp), color = C.accent, spacing = 3.sp)
        LiveCore(Modifier.weight(1f).fillMaxWidth(), mode = "think")
        Column(Modifier.fillMaxWidth().background(C.deck).border(1.dp, C.amber).padding(14.dp)) {
            Label(kindLabel(kind), color = C.amber)
            if (locked) Body("Unlock to see what it's about.", Modifier.padding(top = 4.dp), size = 16.sp, weight = FontWeight.SemiBold)
            else {
                Body(ev.optString("title"), Modifier.padding(top = 4.dp), size = 16.sp, weight = FontWeight.SemiBold, maxLines = 3)
                ev.optString("body").takeIf { it.isNotBlank() }?.let { Hint(it.take(240)) }
            }
            Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                when {
                    kind == "approval" -> {
                        HudButton("Reject", { act("reject") }, Modifier.weight(1f))
                        HudButton("Adjust", { act("adjust") }, Modifier.weight(1f), Btn.Amber)
                        HudButton("Approve", { act("approve") }, Modifier.weight(1f), Btn.Go)
                    }
                    kind == "reminder" || kind == "calendar" -> {
                        HudButton("Got it", { act("gotit") }, Modifier.weight(1f), Btn.Go)
                        HudButton("Snooze 10 min", { act("snooze") }, Modifier.weight(1f))
                    }
                    else -> HudButton("Got it", { act("gotit") }, Modifier.weight(1f), Btn.Go)
                }
            }
        }
        Row(Modifier.padding(top = 24.dp), horizontalArrangement = Arrangement.spacedBy(72.dp)) {
            RoundAction(Ico.close, "Later", C.dim) { act("later") }
            RoundAction(Ico.mic, "Talk", C.accent) { act("talk") }
        }
    }
}

private fun kindLabel(kind: String) = when (kind) {
    "mail_code" -> "Code"; "mail" -> "Mail"; "message" -> "Message"; "reminder" -> "Reminder"; "calendar" -> "Calendar"
    "digest" -> "Your day"; "approval" -> "Approval"; "test" -> "Test call"; else -> kind.replace('_', ' ')
}

@Composable
private fun RoundAction(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, color: Color, onClick: () -> Unit) =
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(Modifier.size(64.dp).background(color.copy(alpha = .1f)).border(1.dp, color).clickable(role = androidx.compose.ui.semantics.Role.Button, onClick = onClick),
            contentAlignment = Alignment.Center) {
            Icon(icon, label, Modifier.size(26.dp), tint = color)
        }
        Label(label, color = color)
    }
