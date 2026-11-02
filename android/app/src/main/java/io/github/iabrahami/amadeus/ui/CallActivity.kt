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
        setContent { AmadeusTheme { CallScreen(answer = { unlockThenAnswer() }, later = { later() }) } }
        if (intent.getBooleanExtra("answer", false)) unlockThenAnswer()   // "Answer" right in the call notification
    }

    /**
     * Answering on the lock screen asks for your fingerprint / face right away, so answering and unlocking are one
     * step. Cancel it and the call keeps ringing.
     */
    private fun unlockThenAnswer() {
        val km = getSystemService(KeyguardManager::class.java)
        if (!km.isKeyguardLocked) return answer()
        km.requestDismissKeyguard(this, object : KeyguardManager.KeyguardDismissCallback() {
            override fun onDismissSucceeded() = answer()
        })
    }

    /** Picked up: the PC stops ringing, and you're in the app. */
    private fun answer() {
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
            .apply { if (mail != null) putExtra("mail", mail) })
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

/** Like a normal phone call: who's calling, nothing about why (that's in the app, after you unlock). */
@Composable
private fun CallScreen(answer: () -> Unit, later: () -> Unit) {
    Column(Modifier.fillMaxSize().background(Brush.radialGradient(listOf(Color(0xFF33230E), C.bg), radius = 1500f))
        .padding(horizontal = 24.dp, vertical = 72.dp), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.SpaceBetween) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Box(Modifier.size(190.dp).shadow(40.dp, CircleShape, spotColor = C.accent, ambientColor = C.accent).clip(CircleShape)
                .background(C.bg).border(2.dp, C.accent.copy(alpha = .7f), CircleShape), contentAlignment = Alignment.Center) {
                androidx.compose.foundation.Image(androidx.compose.ui.res.painterResource(io.github.iabrahami.amadeus.R.drawable.amadeus_logo),
                    LocalContext.current.assistantName, Modifier.size(140.dp))
            }
            Text(LocalContext.current.assistantName.uppercase(), fontFamily = Display, fontWeight = FontWeight.SemiBold, fontSize = 32.sp, letterSpacing = 10.sp,
                modifier = Modifier.padding(top = 12.dp))
            Text("Incoming call…", color = C.soft, fontSize = 15.sp)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(96.dp)) {
            RoundAction(Ico.close, "Later", C.no, later)
            RoundAction(Ico.phone, "Answer", C.ok, answer)
        }
    }
}

@Composable
private fun RoundAction(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, color: Color, onClick: () -> Unit) =
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(Modifier.size(72.dp).clip(CircleShape).background(color).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
            Icon(icon, label, Modifier.size(28.dp), tint = Color.White)
        }
        Text(label, color = C.soft, fontSize = 13.sp)
    }
