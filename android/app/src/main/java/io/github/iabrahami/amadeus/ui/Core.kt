package io.github.iabrahami.amadeus.ui

import android.graphics.Bitmap
import android.graphics.Paint
import android.graphics.PorterDuff
import android.graphics.PorterDuffXfermode
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.provider.Settings
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.currentStateAsState
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.random.Random

/**
 * What the core shows, shared by every screen: idle, listen (you talk), think (a heartbeat while it works on an answer)
 * and speak (its answer comes in, or it's read aloud). talk() is one pulse of its voice.
 */
object CoreLink {
    var mode by mutableStateOf("idle")
    internal var talkAt = 0L
    fun talk() { talkAt = System.nanoTime() }
}

/**
 * The core: the same living sphere of memories as the mini core on the PC (core/web/core.js, its 2D renderer and the
 * "mini" network: 20 topics of 30 memories, 560 loose points, 700 points of dust). Drawn only while it's on screen
 * and the app is in front.
 */
@Composable
fun LiveCore(modifier: Modifier = Modifier, mode: String = CoreLink.mode) {
    val ctx = LocalContext.current
    val reduce = remember { runCatching { Settings.Global.getFloat(ctx.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }.getOrDefault(false) }
    val net = remember { Net.build() }
    val sim = remember { Sim(net, reduce) }
    var frame by remember { mutableLongStateOf(0L) }
    val resumed = LocalLifecycleOwner.current.lifecycle.currentStateAsState().value.isAtLeast(Lifecycle.State.RESUMED)
    LaunchedEffect(resumed) {
        if (!resumed) return@LaunchedEffect
        var last = 0L
        while (true) withFrameNanos { now ->
            if (now - last >= 30_000_000L) {  // about 30 frames a second: smooth, and light on the battery
                sim.step(if (last == 0L) .016f else min(.05f, (now - last) / 1e9f), now)
                last = now
                frame = now
            }
        }
    }
    sim.mode = mode
    Canvas(modifier.semantics { contentDescription = "The core: $mode" }) {
        frame  // redraw on every frame
        val theme = C.theme
        val R = min(size.width, size.height) * .30f
        drawIntoCanvas { sim.draw(it.nativeCanvas, size.width / 2, size.height / 2, R, theme) }
    }
}

private class Node(val x: Float, val y: Float, val z: Float, val kind: Int, val size: Float, val ph: Float) {
    var lit = 0f
    var sx = 0f; var sy = 0f; var sz = 0f
}

private class Dust(val x: Float, val y: Float, val z: Float, val ph: Float) { var sx = 0f; var sy = 0f; var sz = 0f }

private class Net(val nodes: List<Node>, val edges: IntArray, val adj: List<IntArray>, val dust: List<Dust>, val core: Int) {
    companion object {
        fun build(nc: Int = 20, per: Int = 30, free: Int = 560, nDust: Int = 700): Net {
            val rnd = Random(7)
            fun r1() = rnd.nextFloat() * 2 - 1
            val nodes = ArrayList<Node>()
            fun add(x: Float, y: Float, z: Float, kind: Int, size: Float): Int { nodes += Node(x, y, z, kind, size, rnd.nextFloat() * 6.28f); return nodes.size - 1 }
            val core = add(0f, 0f, 0f, -1, 1.9f)
            val clusters = ArrayList<IntArray>()
            for (ci in 0 until nc) {  // topics: a hub and its memories, at different depths
                val u = 1 - (ci + .5f) / nc * 2
                val a = ci * 2.39996f + rnd.nextFloat() * .5f
                val s = sqrt(1 - u * u)
                val depth = .3f + rnd.nextFloat() * .45f
                val dx = s * cos(a) * depth; val dy = u * depth; val dz = s * sin(a) * depth
                clusters += IntArray(per) { j ->
                    var ox = 0f; var oy = 0f; var oz = 0f
                    if (j > 0) do { ox = r1() * .16f; oy = r1() * .16f; oz = r1() * .16f } while (hypot(hypot(dx + ox, dy + oy), dz + oz) > .9f)
                    add(dx + ox, dy + oy, dz + oz, ci % 3, if (j > 0) .55f + rnd.nextFloat() * .6f else 1.6f)
                }
            }
            for (i in 0 until free) {  // loose neurons, denser towards the middle
                val r = .9f * sqrt(rnd.nextFloat()); val u = r1(); val a = rnd.nextFloat() * 6.283f; val s = sqrt(1 - u * u)
                add(s * cos(a) * r, u * r, s * sin(a) * r, i % 3, .3f + rnd.nextFloat() * .3f)
            }
            val adj = List(nodes.size) { HashSet<Int>() }
            val edges = ArrayList<Int>()
            fun link(a: Int, b: Int) { if (a == b || b in adj[a]) return; edges += a; edges += b; adj[a] += b; adj[b] += a }
            fun d2(i: Int, j: Int) = (nodes[i].x - nodes[j].x).pow(2) + (nodes[i].y - nodes[j].y).pow(2) + (nodes[i].z - nodes[j].z).pow(2)
            // nearest neighbours through a grid, so building stays fast
            val g = 16
            fun cell(v: Float) = (((v + 1) / 2 * g).toInt()).coerceIn(0, g - 1)
            val grid = HashMap<Int, MutableList<Int>>()
            nodes.forEachIndexed { i, n -> if (i != core) grid.getOrPut(cell(n.x) + g * (cell(n.y) + g * cell(n.z))) { ArrayList() } += i }
            fun near(i: Int, k: Int, skip: (Int) -> Boolean): List<Int> {
                val n = nodes[i]; val cx = cell(n.x); val cy = cell(n.y); val cz = cell(n.z)
                val found = ArrayList<Int>()
                var r = 1
                while (found.size < k + 4 && r < 4) {
                    found.clear()
                    for (x in cx - r..cx + r) for (y in cy - r..cy + r) for (z in cz - r..cz + r) {
                        if (x < 0 || y < 0 || z < 0 || x >= g || y >= g || z >= g) continue
                        grid[x + g * (y + g * z)]?.forEach { j -> if (j != i && !skip(j)) found += j }
                    }
                    r++
                }
                return found.sortedBy { d2(i, it) }.take(k)
            }
            clusters.forEach { mine ->
                val hub = mine[0]; val inCl = mine.toHashSet()
                mine.forEachIndexed { j, n -> if (j == 0) return@forEachIndexed; if (j < 7) link(n, hub); near(n, 2) { it !in inCl || it == hub }.forEach { link(n, it) } }
                link(hub, core)
            }
            clusters.forEach { mine -> clusters.filter { it !== mine }.minByOrNull { d2(it[0], mine[0]) }?.let { link(mine[0], it[0]) } }
            for (i in 1 + nc * per until nodes.size) near(i, 3) { false }.forEach { link(i, it) }
            val dust = List(nDust) { i ->
                val y = 1 - i / (nDust - 1f) * 2; val r = sqrt(1 - y * y); val th = i * 2.39996323f
                Dust(cos(th) * r, y, sin(th) * r, rnd.nextFloat() * 6.28f)
            }
            return Net(nodes, edges.toIntArray(), adj.map { it.toIntArray() }, dust, core)
        }
    }
}

private class Pulse(var a: Int, var b: Int, var u: Float, val spd: Float, var hops: Int)

/** The motion, and the 2D drawing of core.js (flatRenderer + halo), with the same numbers. */
private class Sim(val net: Net, val reduce: Boolean) {
    var mode = "idle"
    private var amp = 0f; private var ampT = 0f; private var thinkGlow = 0f; private var rot = 0f; private var hbT = 0f
    private var a1 = Float.NaN; private var a2 = 0f; private var spin = false; private var spinS = 0f; private var spinS0 = 0f
    private var t = 0f; private var hb = 0f; private var idle = 0f; private var breathe = 1f
    private var lastTalk = 0L
    private val pulses = ArrayList<Pulse>()
    private val rnd = Random(11)

    fun step(dt: Float, now: Long) {
        t += dt
        if (CoreLink.talkAt != lastTalk) { lastTalk = CoreLink.talkAt; amp = max(amp, .5f + rnd.nextFloat() * .4f) }
        if (mode == "speak") {
            ampT -= dt
            if (ampT <= 0) { ampT = .07f + rnd.nextFloat() * .16f; amp = max(amp, .45f + rnd.nextFloat() * .55f) }
            amp *= .02f.pow(dt)
        } else amp *= .01f.pow(dt)
        if (mode == "listen") amp = max(amp, .12f + .1f * sin(t * 9).pow(2))
        val thinking = mode == "think"
        thinkGlow += ((if (thinking) 1f else 0f) - thinkGlow) * (1 - .02f.pow(dt))
        rot += dt * (if (reduce) .03f else .14f + amp * .25f)
        hbT = if (thinking) hbT + dt else if (thinkGlow < .02f) 0f else hbT + dt
        val beat = if (hbT < .2f) sin(hbT / .2f * PI.toFloat() / 2).pow(2) else exp(-(hbT - .2f) / .55f)
        hb = if (reduce) 0f else (if (thinking) 1f else thinkGlow) * beat
        // the arc pairs: a slow drift; while thinking they counter-turn and every second meeting is the beat
        val n1 = rot * .9f; val n2 = -rot * .7f + 1.57f
        fun wrap(d0: Float): Float { var d = (d0 + PI.toFloat() / 2) % PI.toFloat(); if (d < 0) d += PI.toFloat(); return d - PI.toFloat() / 2 }
        if (a1.isNaN()) { a1 = n1; a2 = n2 }
        if (thinking && !reduce) {
            if (!spin) { spin = true; spinS = a1 + wrap(a2 - a1) / 2; spinS0 = spinS }
            val rel = 2 * (spinS - spinS0); val mi = (rel / PI).roundToInt(); val on = mi % 2 == 0
            val sep = abs(rel - mi * PI.toFloat()); val near = if (on) min(1f, sep / .5f) else 1f; val ease = near * near * (3 - 2 * near)
            spinS += dt * 1.9f * (.25f + .75f * ease)
            val rel2 = 2 * (spinS - spinS0); val sep2 = abs(rel2 - (rel2 / PI).roundToInt() * PI.toFloat())
            if (on && sep2 < sep && sep2 < .06f && hbT > .5f) hbT = 0f
        } else spin = false
        val ka = 1 - (if (spin) .004f else .06f).pow(dt)
        a1 += wrap((if (spin) spinS else n1) - a1) * ka
        a2 += wrap((if (spin) 2 * spinS0 - spinS else n2) - a2) * ka
        idle = (if (reduce) .1f else .55f) * (1 - min(1f, amp * 1.2f)) * (.7f + .3f * sin(t * .8f))
        breathe = (1 + sin(t * 1.1f) * .012f) * (1 + hb * .03f)
        // signals run along the links only while it really talks with you, not while it thinks
        val working = mode != "idle" && !thinking
        val rate = if (!working) 0f else (if (reduce) .5f else 4f) + amp * 16
        if (rnd.nextFloat() < rate * dt) {
            val e = rnd.nextInt(net.edges.size / 2) * 2; val flip = rnd.nextBoolean()
            pulses += Pulse(net.edges[e + if (flip) 1 else 0], net.edges[e + if (flip) 0 else 1], 0f, 1.1f + rnd.nextFloat() * 1.2f, 2 + rnd.nextInt(3))
        }
        val fade = .3f.pow(dt)
        for (n in net.nodes) n.lit = if (n.lit > .002f) n.lit * fade else 0f
        val it = pulses.listIterator()
        while (it.hasNext()) {
            val q = it.next(); q.u += dt * q.spd * (1 + amp)
            if (q.u < 1) continue
            net.nodes[q.b].lit = max(net.nodes[q.b].lit, .35f)
            val nx = net.adj[q.b].filter { n -> n != q.a }
            if (--q.hops > 0 && working && nx.isNotEmpty() && pulses.size < 240) { q.a = q.b; q.b = nx[rnd.nextInt(nx.size)]; q.u = 0f } else it.remove()
        }
    }

    // ---------- drawing ----------
    private var spritesFor: HudTheme? = null
    private lateinit var glow: List<Bitmap>; private lateinit var amberS: Bitmap; private lateinit var whiteS: Bitmap
    private fun sprite(c: Color): Bitmap {
        val b = Bitmap.createBitmap(64, 64, Bitmap.Config.ARGB_8888)
        val p = Paint().apply {
            shader = RadialGradient(32f, 32f, 32f, intArrayOf(c.toArgb(), c.copy(alpha = .55f).toArgb(), c.copy(alpha = .12f).toArgb(), c.copy(alpha = 0f).toArgb()),
                floatArrayOf(0f, .18f, .5f, 1f), Shader.TileMode.CLAMP)
        }
        android.graphics.Canvas(b).drawRect(0f, 0f, 64f, 64f, p)
        return b
    }
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val add = Paint(Paint.FILTER_BITMAP_FLAG).apply { xfermode = PorterDuffXfermode(PorterDuff.Mode.ADD) }
    private val rect = RectF()
    private val lineBuf = Array(4) { FloatArray(net.edges.size * 2) }
    private val lineN = IntArray(4)
    private val litBuf = FloatArray(net.edges.size * 2)
    private val dustBuf = FloatArray(net.dust.size * 2)
    private val ringBuf = FloatArray(130 * 4)

    private fun argb(c: Color, a: Float) = c.copy(alpha = a.coerceIn(0f, 1f)).toArgb()

    fun draw(cv: android.graphics.Canvas, cx: Float, cy: Float, R: Float, th: HudTheme) {
        if (spritesFor !== th) { glow = th.k.map(::sprite); amberS = sprite(th.rc); whiteS = sprite(th.hi); spritesFor = th }
        val small = R < 110
        halo(cv, cx, cy, R, th, small)
        val cosY = cos(rot); val sinY = sin(rot); val cosX = cos(.38f); val sinX = sin(.38f)
        fun proj(x0: Float, y0: Float, z0: Float, sc: Float, set: (Float, Float, Float) -> Unit) {
            val x = x0 * cosY + z0 * sinY; var z = -x0 * sinY + z0 * cosY; var y = y0
            val y2 = y * cosX - z * sinX; z = y * sinX + z * cosX; y = y2
            val f = 3.2f / (3.2f - z); set(cx + x * sc * f, cy + y * sc * f, z)
        }
        for (p in net.dust) {
            val w = amp * (.07f * sin(p.y * 7 + t * 11 + p.ph) + .06f * sin(p.x * 5 - t * 7)) + idle * (.07f * sin(p.y * 5 + t * 2.4f + p.ph * .4f) + .06f * sin(p.x * 4 - t * 1.7f))
            proj(p.x, p.y, p.z, R * breathe * (1 + w)) { a, b, c -> p.sx = a; p.sy = b; p.sz = c }
        }
        for (n in net.nodes) {
            val sw = 1 + amp * .07f * sin(t * 9 + n.ph) + idle * .04f * sin(t * 1.9f + n.ph)
            proj((n.x + sin(t * .5f + n.ph) * .025f) * sw, (n.y + cos(t * .6f + n.ph) * .025f) * sw, (n.z + sin(t * .4f + n.ph * 2) * .025f) * sw, R * breathe) { a, b, c -> n.sx = a; n.sy = b; n.sz = c }
        }
        dots(cv, false, th, small)
        // links: four depth buckets in one draw each; lit ones in the recall colour
        lineN.fill(0); var litN = 0
        val e = net.edges; val nodes = net.nodes
        var k = 0
        while (k < e.size) {
            val a = nodes[e[k]]; val b = nodes[e[k + 1]]; k += 2
            val buf: FloatArray; val idx: Int
            if (max(a.lit, b.lit) > .05f) { buf = litBuf; idx = litN; litN += 4 }
            else { val bk = min(3, (((a.sz + b.sz) / 2 + 1) * 2).toInt().coerceAtLeast(0)); buf = lineBuf[bk]; idx = lineN[bk]; lineN[bk] += 4 }
            buf[idx] = a.sx; buf[idx + 1] = a.sy; buf[idx + 2] = b.sx; buf[idx + 3] = b.sy
        }
        paint.style = Paint.Style.STROKE; paint.strokeWidth = if (small) .6f else 1f
        for (i in 0..3) { paint.color = argb(th.a2, .03f + (i + .5f) / 4 * .11f + amp * .06f); cv.drawLines(lineBuf[i], 0, lineN[i], paint) }
        if (litN > 0) { paint.color = argb(th.rc, .4f); cv.drawLines(litBuf, 0, litN, paint) }
        paint.style = Paint.Style.FILL
        for (q in pulses) {
            val a = nodes[q.a]; val b = nodes[q.b]; val z = if (small) 8f else 16f
            val x = a.sx + (b.sx - a.sx) * q.u; val y = a.sy + (b.sy - a.sy) * q.u
            rect.set(x - z / 2, y - z / 2, x + z / 2, y + z / 2); add.alpha = 255; cv.drawBitmap(whiteS, null, rect, add)
        }
        for ((i, n) in nodes.withIndex()) {
            val d = (n.sz + 1) / 2; val base = (if (small) 1f else 2.1f) * n.size * (.6f + d * .7f)
            val gs = base * (9 + n.lit * 7 + amp * 3) * (1 + hb * .45f)
            add.alpha = (min(1f, .25f + d * .55f + n.lit * .4f + hb * .25f) * 255).toInt()
            rect.set(n.sx - gs / 2, n.sy - gs / 2, n.sx + gs / 2, n.sy + gs / 2)
            cv.drawBitmap(if (n.lit > .15f) amberS else if (i == net.core) whiteS else glow[n.kind.coerceIn(0, 2)], null, rect, add)
            paint.color = if (n.lit > .15f) argb(th.rc2, .7f + n.lit * .3f) else argb(th.hi, .35f + d * .6f)
            cv.drawCircle(n.sx, n.sy, base * (.55f + n.lit * .3f), paint)
        }
        dots(cv, true, th, small)
    }

    private fun dots(cv: android.graphics.Canvas, front: Boolean, th: HudTheme, small: Boolean) {
        // two brightness steps per side are enough at phone size
        for (step in 0..1) {
            var n = 0
            for (p in net.dust) {
                if ((p.sz >= 0) != front) continue
                val d = (p.sz + 1) / 2
                if ((d > .5f) != (step == 1)) continue
                dustBuf[n++] = p.sx; dustBuf[n++] = p.sy
            }
            val d = if (step == 1) .75f else .25f
            paint.color = argb(th.a, if (front) .05f + d * .32f + amp * .15f * d else .05f + d * .22f)
            paint.strokeWidth = (if (small) .7f else 1f) + d * (if (small) .5f else .9f)
            paint.strokeCap = Paint.Cap.SQUARE
            cv.drawPoints(dustBuf, 0, n, paint)
        }
    }

    private fun halo(cv: android.graphics.Canvas, cx: Float, cy: Float, R: Float, th: HudTheme, small: Boolean) {
        val gR = R * (1.25f + hb * .14f)
        paint.style = Paint.Style.FILL
        paint.shader = if (hb > .01f) RadialGradient(cx, cy, gR, intArrayOf(argb(th.rc, .10f + hb * .5f), argb(th.a, .10f + amp * .2f + hb * .28f), argb(th.a3, .08f + amp * .08f + hb * .1f), argb(th.a3, 0f)),
            floatArrayOf(0f, .24f, .5f, 1f), Shader.TileMode.CLAMP)
        else RadialGradient(cx, cy, gR, intArrayOf(argb(th.a, .10f + amp * .22f + thinkGlow * .08f), argb(th.a3, .08f + amp * .08f), argb(th.a3, 0f)),
            floatArrayOf(0f, .5f, 1f), Shader.TileMode.CLAMP)
        cv.drawCircle(cx, cy, gR, paint)
        paint.shader = null
        val ringA = .35f + amp * .4f + hb * .4f; val hs = 1 + hb * .09f
        paint.style = Paint.Style.STROKE; paint.strokeCap = Paint.Cap.BUTT
        // fine tick ring
        val r1 = R * 1.2f * hs; val ticks = if (small) 48 else 120
        var n = 0
        for (i in 0 until ticks) {
            val a = i.toFloat() / ticks * 6.283f - rot * .4f; val l = if (i % 10 == 0) 7f else 3f
            ringBuf[n++] = cx + cos(a) * r1; ringBuf[n++] = cy + sin(a) * r1; ringBuf[n++] = cx + cos(a) * (r1 + l); ringBuf[n++] = cy + sin(a) * (r1 + l)
        }
        paint.color = argb(th.a, ringA * .7f); paint.strokeWidth = 1f; cv.drawLines(ringBuf, 0, n, paint)
        // the voice ring
        val r2 = R * 1.1f * hs; val bars = if (small) 48 else 96
        n = 0
        for (i in 0 until bars) {
            val a = i.toFloat() / bars * 6.283f
            val v = amp * (.5f + .5f * sin(i * .9f + t * 13)) * (.6f + .4f * sin(i * .23f - t * 4)) + idle * (.5f + .5f * sin(i * .37f + t * 2.8f)) * (.6f + .4f * sin(i * .13f - t * 1.4f)) + hb * (.9f + .5f * sin(i * .5f)) + .02f
            val l = v * R * .16f
            ringBuf[n++] = cx + cos(a) * r2; ringBuf[n++] = cy + sin(a) * r2; ringBuf[n++] = cx + cos(a) * (r2 + l); ringBuf[n++] = cy + sin(a) * (r2 + l)
        }
        paint.color = argb(th.a, .25f + idle * .35f + amp * .6f); paint.strokeWidth = if (small) 1.4f else 2f; cv.drawLines(ringBuf, 0, n, paint)
        // the arc pairs (thinking: they meet on the beat)
        fun pair(r: Float, a: Float, h1: Float, h2: Float) {
            val deg = (180 / PI).toFloat()
            rect.set(cx - r, cy - r, cx + r, cy + r)
            cv.drawArc(rect, (a - h1) * deg, 2 * h1 * deg, false, paint)
            cv.drawArc(rect, (a + PI.toFloat() - h2) * deg, 2 * h2 * deg, false, paint)
        }
        paint.color = if (thinkGlow > .1f) argb(th.rc, .32f + thinkGlow * .22f + hb * .12f) else argb(th.a, ringA)
        paint.strokeWidth = (if (small) 1.5f else 2.5f) * (1 + hb * .8f)
        pair(R * 1.34f * hs, a1, .62f, .40f)
        paint.color = if (thinkGlow > .1f) argb(th.rc, .22f + thinkGlow * .16f + hb * .1f) else argb(th.a, ringA * .6f)
        paint.strokeWidth = (if (small) 1f else 1.6f) * (1 + hb * .8f)
        pair(R * 1.42f * hs, a2, .50f, .30f)
        paint.style = Paint.Style.FILL
    }
}
