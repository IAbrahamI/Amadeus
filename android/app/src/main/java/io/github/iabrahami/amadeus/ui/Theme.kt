package io.github.iabrahami.amadeus.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.iabrahami.amadeus.R
import kotlin.math.cos
import kotlin.math.sin

/**
 * The dashboard's look on the phone (core/web/themes.js and hud.css): a dark HUD in the theme you pick on the PC.
 * Amber always means "needs you", in every theme.
 */
class HudTheme(
    val id: String, val name: String, val a: Color, val a2: Color, val a3: Color, val line: Color, val lineHi: Color,
    val text: Color, val dim: Color, val ink: Color, val void: Color, val deck: Color,
    val k: List<Color>, val rc: Color, val rc2: Color, val hi: Color,
)

private fun rgb(s: String): Color = s.split(",").map { it.trim().toInt() }.let { Color(it[0], it[1], it[2]) }
private fun hex(s: String): Color = Color(android.graphics.Color.parseColor(s))

/** The same three themes as the dashboard; an unknown id is the default. */
val THEMES = listOf(
    HudTheme("blue", "Default", rgb("95,216,255"), rgb("140,215,255"), rgb("30,88,120"), hex("#12324A"), hex("#1E5878"),
        hex("#D4E6F2"), hex("#6E8BA0"), hex("#031018"), hex("#04070C"), hex("#08101A"),
        listOf(rgb("95,216,255"), rgb("140,170,255"), rgb("79,224,166")), rgb("225,248,255"), rgb("255,255,255"), rgb("235,250,255")),
    HudTheme("purple", "Purple", rgb("182,140,255"), rgb("205,180,255"), rgb("72,40,135"), hex("#2C1E4C"), hex("#4C3684"),
        hex("#E7DFF8"), hex("#9083AA"), hex("#12082A"), hex("#07050E"), hex("#100A1C"),
        listOf(rgb("182,140,255"), rgb("255,130,215"), rgb("110,190,255")), rgb("255,150,225"), rgb("255,225,245"), rgb("245,238,255")),
    HudTheme("red", "Red", rgb("255,82,96"), rgb("255,145,150"), rgb("125,28,40"), hex("#4A1820"), hex("#7C2A36"),
        hex("#F5DCDE"), hex("#A57E84"), hex("#1A0406"), hex("#0C0405"), hex("#160A0C"),
        listOf(rgb("255,82,96"), rgb("255,150,95"), rgb("255,195,205")), rgb("255,196,110"), rgb("255,236,200"), rgb("255,240,240")),
)

fun themeFor(id: String?) = THEMES.firstOrNull { it.id == id } ?: THEMES[0]

/** The colours in use. Reading them in a composable redraws it when the theme changes on the PC. */
object C {
    var theme by mutableStateOf(THEMES[0])
    val accent get() = theme.a
    val accent2 get() = theme.a2
    val bg get() = theme.void
    val deck get() = theme.deck
    val text get() = theme.text
    val dim get() = theme.dim
    val line get() = theme.line
    val lineHi get() = theme.lineHi
    val ink get() = theme.ink
    val green get() = theme.k[2]
    /** "Needs you", in every theme. */
    val amber = Color(0xFFFFB547)
    val amberInk = Color(0xFF1E1302)
    val red = Color(0xFFFF5A5F)
    val online = Color(0xFF3ECF7A)
    // the names the rest of the app (notifications, avatar) already uses
    val soft get() = theme.text.copy(alpha = .8f)
    val muted get() = theme.dim
    val onAccent get() = theme.ink
    val no get() = red
    val ok get() = online
    val warn get() = amber
}

/** Labels and titles (Chakra Petch), body text (IBM Plex Sans) and data (JetBrains Mono), bundled with the app (SIL OFL). */
val Chakra = FontFamily(
    Font(R.font.chakra_regular, FontWeight.Normal), Font(R.font.chakra_medium, FontWeight.Medium), Font(R.font.chakra_semibold, FontWeight.SemiBold),
)
@OptIn(ExperimentalTextApi::class)  // variable fonts: stable in practice since Android 8; the API is still marked experimental
val Plex = FontFamily(listOf(400, 500, 600).map { w ->
    Font(R.font.plex_sans, FontWeight(w), variationSettings = FontVariation.Settings(FontVariation.weight(w)))
})
@OptIn(ExperimentalTextApi::class)
val Mono = FontFamily(listOf(400, 500).map { w ->
    Font(R.font.jetbrains_mono, FontWeight(w), variationSettings = FontVariation.Settings(FontVariation.weight(w)))
})
val Display = Chakra

@Composable
fun AmadeusTheme(content: @Composable () -> Unit) {
    val body = TextStyle(fontFamily = Plex)
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = C.accent, onPrimary = C.ink, background = C.bg, onBackground = C.text, surface = C.deck, onSurface = C.text,
            surfaceVariant = C.deck, onSurfaceVariant = C.dim, outline = C.line, error = C.red,
        ),
        typography = Typography().run {
            copy(bodyLarge = bodyLarge.merge(body), bodyMedium = bodyMedium.merge(body), bodySmall = bodySmall.merge(body),
                titleLarge = titleLarge.merge(body), titleMedium = titleMedium.merge(body), labelLarge = labelLarge.merge(body))
        },
    ) { CompositionLocalProvider(LocalContentColor provides C.text, content = content) }
}

/** The HUD backdrop: the theme's void, a faint grid and faint scanlines. */
fun Modifier.hud(): Modifier = background(C.bg).drawBehind {
    val grid = C.line.copy(alpha = .22f)
    val step = 28.dp.toPx()
    var x = 0f
    while (x < size.width) { drawLine(grid, Offset(x, 0f), Offset(x, size.height), 1f); x += step }
    var y = 0f
    while (y < size.height) { drawLine(grid, Offset(0f, y), Offset(size.width, y), 1f); y += step }
    val scan = Color.Black.copy(alpha = .16f)
    val s = 3.dp.toPx()
    y = 0f
    while (y < size.height) { drawLine(scan, Offset(0f, y), Offset(size.width, y), 1f); y += s }
}

/** A CRT box: only its four corner brackets, over a faint deck. Amber when it needs you. */
@Composable
fun CrtBox(modifier: Modifier = Modifier, amber: Boolean = false, fill: Boolean = true, pad: Dp = 14.dp, content: @Composable ColumnScope.() -> Unit) {
    val c = if (amber) C.amber else C.accent
    Column(modifier.fillMaxWidth()
        .then(if (fill) Modifier.background(C.deck.copy(alpha = .72f)) else Modifier)
        .drawBehind {
            val l = 14.dp.toPx()
            val w = 1.5.dp.toPx()
            val h = w / 2
            val (W, H) = size.width to size.height
            fun corner(x: Float, y: Float, dx: Float, dy: Float) {
                drawLine(c, Offset(x, y), Offset(x + dx * l, y), w, StrokeCap.Square)
                drawLine(c, Offset(x, y), Offset(x, y + dy * l), w, StrokeCap.Square)
            }
            corner(h, h, 1f, 1f); corner(W - h, h, -1f, 1f); corner(h, H - h, 1f, -1f); corner(W - h, H - h, -1f, -1f)
        }
        .padding(pad), content = content)
}

/** A small uppercase label in Chakra Petch. */
@Composable
fun Label(text: String, modifier: Modifier = Modifier, color: Color = C.dim, size: TextUnit = 11.sp, spacing: TextUnit = 2.sp) =
    Text(text.uppercase(), modifier, color = color, fontFamily = Chakra, fontWeight = FontWeight.Medium, fontSize = size, letterSpacing = spacing,
        maxLines = 1, overflow = TextOverflow.Ellipsis)

/** A section label with a rule to its right. */
@Composable
fun Rule(text: String, modifier: Modifier = Modifier, color: Color = C.dim) = Row(modifier.fillMaxWidth().padding(top = 14.dp, bottom = 8.dp),
    verticalAlignment = Alignment.CenterVertically) {
    Label(text, color = color)
    Box(Modifier.weight(1f).padding(start = 10.dp).height(1.dp).background(C.line))
}

enum class TagKind { Amber, AmberLine, Accent, Line, Red }

@Composable
fun Tag(text: String, kind: TagKind = TagKind.Accent, modifier: Modifier = Modifier) {
    val (fg, bg, border) = when (kind) {
        TagKind.Amber -> Triple(C.amberInk, C.amber, C.amber)
        TagKind.AmberLine -> Triple(C.amber, Color.Transparent, C.amber)
        TagKind.Accent -> Triple(C.ink, C.accent, C.accent)
        TagKind.Line -> Triple(C.accent, Color.Transparent, C.accent.copy(alpha = .6f))
        TagKind.Red -> Triple(C.red, Color.Transparent, C.red)
    }
    Text(text.uppercase(), modifier.background(bg).border(1.dp, border).padding(horizontal = 6.dp, vertical = 1.dp), color = fg,
        fontFamily = Chakra, fontWeight = FontWeight.SemiBold, fontSize = 10.sp, letterSpacing = 1.5.sp, maxLines = 1)
}

enum class Btn { Plain, Go, Amber, Danger }

/** A HUD button: "[ APPROVE ]". */
@Composable
fun HudButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, kind: Btn = Btn.Plain, enabled: Boolean = true) {
    val c = when (kind) { Btn.Plain -> C.dim; Btn.Go -> C.accent; Btn.Amber -> C.amber; Btn.Danger -> C.red }
    val fg = when (kind) { Btn.Plain -> C.text; else -> c }
    Box(modifier.heightIn(min = 44.dp).alpha(if (enabled) 1f else .4f)
        .background(if (kind == Btn.Go) C.accent.copy(alpha = .1f) else if (kind == Btn.Amber) C.amber.copy(alpha = .08f) else Color.Transparent)
        .border(1.dp, c.copy(alpha = if (kind == Btn.Plain) .55f else .9f))
        .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
        .padding(horizontal = 12.dp, vertical = 8.dp), contentAlignment = Alignment.Center) {
        Text("[ ${text.uppercase()} ]", color = fg, fontFamily = Chakra, fontWeight = FontWeight.SemiBold, fontSize = 12.sp, letterSpacing = 1.5.sp, maxLines = 1)
    }
}

/** The small dot-shell mark (the tray icon): a ring of dots around a centre. */
@Composable
fun DotMark(modifier: Modifier = Modifier, size: Dp = 26.dp) = Canvas(modifier.size(size)) {
    val c = C.accent
    val r = this.size.minDimension / 2
    val center = Offset(r, r)
    drawCircle(c.copy(alpha = .25f), r * .98f, center, style = Stroke(1f))
    for (i in 0 until 12) {
        val a = i / 12f * 6.2832f
        drawCircle(c.copy(alpha = if (i % 3 == 0) 1f else .6f), r * .09f, Offset(r + cos(a) * r * .72f, r + sin(a) * r * .72f))
    }
    drawCircle(c, r * .22f, center)
    drawCircle(Color.White.copy(alpha = .8f), r * .09f, center)
}

/** A blinking "_" after a title. */
@Composable
fun Cursor(color: Color = C.accent, size: TextUnit = 20.sp) {
    val t = rememberInfiniteTransition(label = "cursor")
    val a by t.animateFloat(1f, 0f, infiniteRepeatable(tween(1060, easing = { if (it < .5f) 0f else 1f }), RepeatMode.Restart), label = "blink")
    Text("_", Modifier.alpha(a), color = color, fontFamily = Chakra, fontWeight = FontWeight.SemiBold, fontSize = size)
}

/** The header of every screen: the mark (tap: Home), the title with its cursor, and the status or a control on the right. */
@Composable
fun Header(title: String, onMark: () -> Unit, modifier: Modifier = Modifier, right: @Composable RowScope.() -> Unit = {}) =
    Row(modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(44.dp).clickable(role = Role.Button, onClick = onMark).semantics { contentDescription = "Home" },
            contentAlignment = Alignment.CenterStart) { DotMark() }
        Text(title.uppercase(), Modifier.padding(start = 4.dp), color = C.text, fontFamily = Chakra, fontWeight = FontWeight.SemiBold,
            fontSize = 20.sp, letterSpacing = 4.sp, maxLines = 1)
        Cursor()
        Spacer(Modifier.weight(1f))
        right()
    }

/** "● PC ONLINE" / "● PC OFFLINE". */
@Composable
fun PcStatus(online: Boolean?, onClick: () -> Unit = {}) = Row(Modifier.clickable(onClick = onClick).padding(vertical = 8.dp),
    verticalAlignment = Alignment.CenterVertically) {
    Box(Modifier.size(7.dp).background(when (online) { true -> C.online; false -> C.red; null -> C.dim }, androidx.compose.foundation.shape.CircleShape))
    Text(when (online) { true -> " PC ONLINE"; false -> " PC OFFLINE"; null -> " CONNECTING" }, color = C.dim, fontFamily = Mono, fontSize = 11.sp, letterSpacing = 1.sp)
}

/** A segmented switch: the highlight sits on the picked side. */
@Composable
fun Seg(options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit, modifier: Modifier = Modifier) =
    Row(modifier.border(1.dp, C.line)) {
        options.forEach { (id, label) ->
            val on = id == selected
            Box(Modifier.heightIn(min = 36.dp).background(if (on) C.accent.copy(alpha = .16f) else Color.Transparent)
                .drawBehind { if (on) drawLine(C.accent, Offset(0f, size.height - 1.dp.toPx()), Offset(size.width, size.height - 1.dp.toPx()), 2.dp.toPx()) }
                .clickable(role = Role.Tab) { onSelect(id) }.padding(horizontal = 12.dp), contentAlignment = Alignment.Center) {
                Label(label, color = if (on) C.accent else C.dim, size = 11.sp)
            }
        }
    }

/** A mono text field in a thin frame. */
@Composable
fun HudField(value: String, onChange: (String) -> Unit, placeholder: String, modifier: Modifier = Modifier, maxLines: Int = 1,
             error: Boolean = false, imeAction: ImeAction = ImeAction.Default, onDone: () -> Unit = {}) =
    BasicTextField(value, onChange, modifier.border(1.dp, if (error) C.red else C.lineHi).padding(horizontal = 10.dp, vertical = 11.dp),
        maxLines = maxLines, singleLine = maxLines == 1, cursorBrush = SolidColor(C.accent),
        textStyle = TextStyle(color = C.text, fontFamily = Mono, fontSize = 14.sp),
        keyboardOptions = KeyboardOptions(imeAction = imeAction), keyboardActions = KeyboardActions(onAny = { onDone() }),
        decorationBox = { field ->
            Box { if (value.isEmpty()) Text(placeholder, color = C.dim, fontFamily = Mono, fontSize = 14.sp, maxLines = 1); field() }
        })

/** A dashed frame (the to-do "+ Add" box, the More tiles). */
fun Modifier.dashed(color: Color): Modifier = drawBehind {
    drawRect(color, style = Stroke(1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx()))))
}

/** A HUD on/off switch: two small blocks, lit when on. */
@Composable
fun HudSwitch(on: Boolean, onChange: (Boolean) -> Unit, enabled: Boolean = true) =
    Row(Modifier.alpha(if (enabled) 1f else .4f).border(1.dp, if (on) C.accent else C.lineHi).clickable(enabled = enabled, role = Role.Switch) { onChange(!on) }
        .padding(3.dp).semantics { contentDescription = if (on) "On" else "Off" }, horizontalArrangement = Arrangement.spacedBy(3.dp)) {
        Box(Modifier.size(width = 14.dp, height = 14.dp).background(if (on) C.accent.copy(alpha = .35f) else C.dim.copy(alpha = .5f)))
        Box(Modifier.size(width = 14.dp, height = 14.dp).background(if (on) C.accent else C.line))
    }

@Composable
fun Hint(text: String, modifier: Modifier = Modifier) = Text(text, modifier, color = C.dim, fontSize = 12.sp, lineHeight = 17.sp)

@Composable
fun Body(text: String, modifier: Modifier = Modifier, color: Color = C.text, size: TextUnit = 15.sp, weight: FontWeight = FontWeight.Normal, maxLines: Int = Int.MAX_VALUE) =
    Text(text, modifier, color = color, fontFamily = Plex, fontSize = size, fontWeight = weight, lineHeight = size * 1.4f, maxLines = maxLines,
        overflow = TextOverflow.Ellipsis)

@Composable
fun MonoText(text: String, modifier: Modifier = Modifier, color: Color = C.dim, size: TextUnit = 12.sp) =
    Text(text, modifier, color = color, fontFamily = Mono, fontSize = size, maxLines = 1)

/** A tappable row with a title, a line under it and something on the right ("›" by default). */
@Composable
fun HudRow(title: String, sub: String? = null, titleColor: Color = C.text, onClick: (() -> Unit)? = null,
           right: @Composable BoxScope.() -> Unit = { if (onClick != null) Text("›", color = C.dim, fontSize = 20.sp) }) =
    Row(Modifier.fillMaxWidth().heightIn(min = 58.dp).let { if (onClick != null) it.clickable(onClick = onClick) else it }
        .drawBehind { drawLine(C.line, Offset(0f, size.height), Offset(size.width, size.height), 1f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(6f, 5f))) }
        .padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Body(title, color = titleColor, size = 15.sp, weight = FontWeight.Medium)
            if (sub != null) Hint(sub)
        }
        Box(Modifier.padding(start = 10.dp), contentAlignment = Alignment.CenterEnd, content = right)
    }

@Composable
fun Gap(h: Dp) = Spacer(Modifier.height(h).width(1.dp))
