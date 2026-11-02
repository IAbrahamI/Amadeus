package io.github.iabrahami.amadeus.ui

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Rect
import android.util.LruCache
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.requiredWidth
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlin.math.ceil
import kotlin.math.sqrt
import io.github.iabrahami.amadeus.assistantName

/**
 * The avatar: the same sprite set as on the PC, if you added one there (config "avatar"; loaded from your PC, kept in
 * memory only), otherwise the default agent icon. The mood comes from the answers ([mood: happy]); while it answers,
 * the mouth moves (frames 1–3).
 */
object AvatarState {
    var mood by mutableStateOf("normal")
    var talking by mutableStateOf(false)

    private val MOODS = mapOf("normal" to "normal", "happy" to "happy", "thinking" to "sided_thinking", "surprised" to "sided_surprised",
        "worried" to "sided_worried", "sad" to "sad", "annoyed" to "annoyed", "blush" to "blush", "wink" to "winking")
    fun sprite(mood: String, frame: Int) = "${MOODS[mood] ?: "normal"}$frame"

    private val cache = object : LruCache<String, ImageBitmap>(12) {}

    /** One sprite, scaled down to phone size. Null while the PC can't be reached. */
    suspend fun load(ctx: Context, key: String): ImageBitmap? {
        cache.get(key)?.let { return it }
        val set = (ctx.applicationContext as io.github.iabrahami.amadeus.AmadeusApp).store.avatarSet
        if (set.isBlank()) return null  // no sprites: the default icon is shown
        return withContext(Dispatchers.IO) {
            runCatching {
                ctx.api.http.newCall(ctx.api.request("/avatar/$set/${set}_$key.png").build()).execute().use { r ->
                    if (!r.isSuccessful) return@use null
                    val bytes = r.body?.bytes() ?: return@use null
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = 2 })
                        ?.let { completeHead(it) }?.asImageBitmap()
                }
            }.getOrNull()?.also { cache.put(key, it) }
        }
    }
}

/**
 * Sprites cut flat at the top of the head (same fix as on the PC, avatar.js): fit a circle to the head outline
 * in the top rows, then draw the missing crown above it from the mirrored top hair rows, with a thin dark outline.
 */
private fun completeHead(im: Bitmap): Bitmap {
    val w = im.width
    val h = im.height
    val pad = 20      // rows added above the sprite (40 on the full-size sprite)
    val probe = 30    // how far down the head outline is measured (60 on the full-size sprite)
    val out = Bitmap.createBitmap(w, h + pad, Bitmap.Config.ARGB_8888)
    val c = Canvas(out)
    c.drawBitmap(im, 0f, pad.toFloat(), null)
    fun span(y: Int): Pair<Int, Int> {
        var a = -1
        var b = -1
        for (x in 0 until w) if ((im.getPixel(x, y) ushr 24) > 128) { if (a < 0) a = x; b = x }
        return a to b
    }
    val (a0, b0) = span(0)
    val (a1, b1) = span(probe)
    if (a0 < 0 || a1 < 0 || b0 - a0 < 10) return out
    val cx = (a0 + b0) / 2f
    val h0 = (b0 - a0) / 2f
    val h1 = (b1 - a1) / 2f
    val yc = (h1 * h1 - h0 * h0 + probe * probe) / (2f * probe)
    val r = sqrt(h0 * h0 + yc * yc)
    val top = yc - r                       // negative: rows missing above the image
    if (!(top < -1 && top > -pad)) return out
    val cyc = pad + yc
    val depth = ceil(-top).toInt() + 2
    val circle = Path().apply { addCircle(cx, cyc, r, Path.Direction.CW) }
    c.save()
    c.clipPath(circle)
    c.clipOutRect(0f, pad.toFloat(), w.toFloat(), (h + pad).toFloat())
    c.translate(0f, pad.toFloat())
    c.scale(1f, -1f)                       // mirror the top hair rows upward
    val src = Rect((a0 - 2).coerceAtLeast(0), 0, (b0 + 2).coerceAtMost(w), (depth + 2).coerceAtMost(h))
    c.drawBitmap(im, src, src, null)
    c.restore()
    c.save()
    c.clipRect(0f, 0f, w.toFloat(), pad + 1f)
    c.drawArc(cx - r + .75f, cyc - r + .75f, cx + r - .75f, cyc + r - .75f, 180f, 180f, false,
        Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = 1.5f; color = 0xE6461C0E.toInt() })
    c.restore()
    return out
}

/** The current frame: mouth moving while it talks, otherwise the calm frame of the mood. */
@Composable
private fun avatarFrame(): ImageBitmap? {
    val ctx = LocalContext.current
    var frame by androidx.compose.runtime.remember { mutableIntStateOf(1) }
    LaunchedEffect(AvatarState.talking) {
        if (!AvatarState.talking) { frame = 1; return@LaunchedEffect }
        val seq = intArrayOf(2, 3, 2, 1, 3, 2, 1, 2)
        var i = 0
        while (true) { frame = seq[i++ % seq.size]; delay(130) }
    }
    val key = AvatarState.sprite(AvatarState.mood, frame)
    val calm = AvatarState.sprite(AvatarState.mood, 1)
    var shown by androidx.compose.runtime.remember { mutableStateOf<ImageBitmap?>(null) }
    val img = produceState<ImageBitmap?>(null, key) { value = AvatarState.load(ctx, key) ?: AvatarState.load(ctx, calm) }.value
    if (img != null) shown = img
    return shown
}

/** Fades the bottom edge out, so where the picture is cut (at the chest) has no hard line. */
private fun Modifier.fadeBottom(from: Float) = graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }
    .drawWithContent {
        drawContent()
        drawRect(Brush.verticalGradient(from to Color.Black, 1f to Color.Transparent), blendMode = BlendMode.DstIn)
    }

/** The portrait for the main screen: down to the shoulders, gently breathing, no frame. */
@Composable
fun AvatarPortrait(modifier: Modifier = Modifier, height: Dp = 300.dp) {
    val img = avatarFrame() ?: return DefaultAgent(modifier, height)
    val breath by rememberInfiniteTransition(label = "breath").animateFloat(1f, 1.012f,
        infiniteRepeatable(tween(2600, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "breath")
    // the sprite is 909×1660 with the completed crown; the top ~63% is head and shoulders
    val width = height / 0.63f * (909f / 1660f)
    Box(modifier.size(width, height).clipToBounds().fadeBottom(.86f), contentAlignment = Alignment.TopCenter) {
        Image(img, LocalContext.current.assistantName, Modifier.requiredWidth(width).graphicsLayer {
            scaleX = breath; scaleY = breath; transformOrigin = androidx.compose.ui.graphics.TransformOrigin(.5f, 1f)
        }, contentScale = ContentScale.FillWidth, alignment = Alignment.TopCenter)
    }
}

/** The avatar alone, small (other screens, bottom right, standing on the menu bar): head and shoulders, no background. */
@Composable
fun AvatarSmall(modifier: Modifier = Modifier, height: Dp = 96.dp) {
    val img = avatarFrame() ?: return DefaultAgent(modifier, height * 0.8f)
    val width = height / 0.63f * (909f / 1660f)
    Box(modifier.size(width, height).clipToBounds().fadeBottom(.86f), contentAlignment = Alignment.TopCenter) {
        Image(img, LocalContext.current.assistantName, Modifier.requiredWidth(width), contentScale = ContentScale.FillWidth, alignment = Alignment.TopCenter)
    }
}

/** The default agent icon, when no sprite set was added on the PC. */
@Composable
private fun DefaultAgent(modifier: Modifier, height: Dp) {
    androidx.compose.foundation.Image(androidx.compose.ui.res.painterResource(io.github.iabrahami.amadeus.R.drawable.agent_default),
        LocalContext.current.assistantName, modifier.size(height * (400f / 440f), height), contentScale = ContentScale.Fit)
}
