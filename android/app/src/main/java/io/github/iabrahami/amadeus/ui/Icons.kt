package io.github.iabrahami.amadeus.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp

/** The stroke icons from the mockup (24×24 outlines), tinted by Icon(). */
object Ico {
    private fun stroke(name: String, vararg paths: String, width: Float = 1.8f) = ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).apply {
        paths.forEach {
            addPath(addPathNodes(it), stroke = SolidColor(Color.White), strokeLineWidth = width,
                strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round)
        }
    }.build()

    private fun circle(cx: Float, cy: Float, r: Float) = "M${cx - r},${cy}a$r,$r 0 1,0 ${2 * r},0a$r,$r 0 1,0 ${-2 * r},0"

    val mic = stroke("mic", "M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0M12 17v4m-3 0h6")
    val micOff = stroke("micOff", "M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0M12 17v4M4 4l16 16")
    val back = stroke("back", "M15 5l-7 7 7 7", width = 2f)
    val home = stroke("home", circle(12f, 12f, 8f), circle(12f, 12f, 3f))
    val today = stroke("today", "M6 5h12a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z", "M4 10h16M9 3v4m6-4v4")
    val mail = stroke("mail", "M5 5h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z", "m4 7 8 6 8-6")
    val chats = stroke("chats", "M5 18l-1 3 4-2h9a3 3 0 0 0 3-3V8a3 3 0 0 0-3-3H7a3 3 0 0 0-3 3v7")
    val more = stroke("more", circle(5f, 12f, 1.5f), circle(12f, 12f, 1.5f), circle(19f, 12f, 1.5f))
    val send = stroke("send", "M4 12l16-8-6 16-2-7-8-1Z")
    val phone = stroke("phone", "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2Z", width = 2.2f)
    val close = stroke("close", "M6 6l12 12M18 6 6 18", width = 2.2f)
}
