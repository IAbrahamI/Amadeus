package io.github.iabrahami.amadeus.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.LocalContentColor
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** The look from the mockup: near-black with an amber glow, warm off-white text. */
object C {
    val bg = Color(0xFF0B0B10)
    val glow = Color(0xFF2A1D0C)
    val accent = Color(0xFFE8A33A)
    val onAccent = Color(0xFF1B1205)
    val text = Color(0xFFF3EFE6)
    val soft = Color(0xFFC9C2B4)
    val muted = Color(0xFFA39C8E)
    val card = Color(0x0DFFFFFF)
    val line = Color(0x4DE8A33A)
    val ok = Color(0xFF1F9D55)
    val no = Color(0xFFB33A3A)
    val warn = Color(0xFFE0A96D)
    val agent = Color(0xFF6E96F0)
    val online = Color(0xFF3ECF7A)
}

/** Display type (headings, the assistant's name): a tight, wide-spaced sans; body: the system sans. */
val Display = FontFamily.SansSerif

/** Light text on the dark background everywhere (also in places without a Material surface). */
@Composable
fun AmadeusTheme(content: @Composable () -> Unit) = MaterialTheme(
    colorScheme = darkColorScheme(
        primary = C.accent, onPrimary = C.onAccent, background = C.bg, onBackground = C.text,
        surface = C.bg, onSurface = C.text, surfaceVariant = Color(0xFF17161C), onSurfaceVariant = C.soft,
        outline = C.line, error = C.no,
    ),
) { CompositionLocalProvider(LocalContentColor provides C.text, content = content) }

@Composable
fun Title(text: String, sub: String? = null, color: Color = C.text) = Column(Modifier.padding(start = 20.dp, end = 20.dp, top = 22.dp, bottom = 8.dp)) {
    if (sub != null) Text(sub, color = C.muted, fontSize = 13.sp)
    Text(text, color = color, style = TextStyle(fontFamily = Display, fontWeight = FontWeight.SemiBold, fontSize = 30.sp))
}

@Composable
fun Section(text: String, color: Color = C.text) =
    Text(text, color = color, style = TextStyle(fontFamily = Display, fontWeight = FontWeight.SemiBold, fontSize = 17.sp))

@Composable
fun Card(modifier: Modifier = Modifier, border: Color? = null, fill: Color = C.card, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(18.dp)
    Column(
        modifier.fillMaxWidth().background(fill, shape)
            .let { if (border != null) it.border(1.dp, border, shape) else it }
            .padding(14.dp),
        content = content,
    )
}

@Composable
fun FilledButton(text: String, color: Color, onClick: () -> Unit, modifier: Modifier = Modifier, textColor: Color = Color.White, enabled: Boolean = true) =
    Button(onClick, modifier.heightIn(min = 46.dp), enabled = enabled, shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(containerColor = color, contentColor = textColor)) { Text(text, fontWeight = FontWeight.SemiBold) }

@Composable
fun LineButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, color: Color = C.accent, enabled: Boolean = true) =
    OutlinedButton(onClick, modifier.heightIn(min = 46.dp), enabled = enabled, shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, color.copy(alpha = .55f)),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = C.text)) { Text(text, fontWeight = FontWeight.Medium) }

@Composable
fun Hint(text: String, modifier: Modifier = Modifier) = Text(text, modifier, color = C.muted, fontSize = 12.sp)
