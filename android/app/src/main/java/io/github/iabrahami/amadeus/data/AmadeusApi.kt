package io.github.iabrahami.amadeus.data

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.time.LocalDate
import java.util.concurrent.TimeUnit

/**
 * Talks to Amadeus Core on your PC — only over your Tailscale network (https://<pc>.ts.net) and only with this
 * phone's device key. Any other host is refused here, so a bug or a bad link can't send data elsewhere.
 * All calls block: use them from a background thread (Dispatchers.IO).
 */
class AmadeusApi(private val store: DeviceStore) {
    companion object {
        private val JSON = "application/json".toMediaType()
        fun allowedHost(host: String) = Regex("^[a-z0-9-]+(\\.[a-z0-9-]+)*\\.ts\\.net$").matches(host.lowercase())
        private val MOOD = Regex("\\s*\\[mood:\\s*\\w*\\]?\\s*$|\\[mood:\\s*\\w+\\]", RegexOption.IGNORE_CASE)
        fun stripMood(t: String) = MOOD.replace(t, "").trim()
    }

    class ApiError(message: String, val code: Int = 0) : Exception(message)

    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)   // the live link and its streamed answers stay open
        .build()

    private fun base(): String {
        val host = store.host ?: throw ApiError("This phone is not paired", 401)
        require(allowedHost(host)) { "Only your Tailscale address (*.ts.net) is allowed" }
        return "https://$host"
    }

    fun url(path: String) = base() + path

    fun request(path: String): Request.Builder =
        Request.Builder().url(base() + path).header("Cookie", "amadeus_dev=${store.deviceKey}")

    private fun call(path: String, body: RequestBody? = null, timeoutSec: Long = 30): String {
        val req = request(path).apply { if (body != null) post(body) }.build()
        val client = http.newBuilder().readTimeout(timeoutSec, TimeUnit.SECONDS).build()
        client.newCall(req).execute().use { r ->
            val text = r.body?.string() ?: ""
            if (!r.isSuccessful) {
                val msg = runCatching { JSONObject(text).optString("error") }.getOrNull().orEmpty()
                throw ApiError(msg.ifBlank { "Your PC answered ${r.code}" }, r.code)
            }
            return text
        }
    }

    private fun get(path: String, timeoutSec: Long = 30) = call(path, null, timeoutSec)
    private fun post(path: String, json: JSONObject = JSONObject(), timeoutSec: Long = 30) =
        call(path, json.toString().toRequestBody(JSON), timeoutSec)

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    /** Pairing: the 6-digit code from the dashboard (📱 Phone) → this phone's own key (sent back as a cookie). */
    fun pair(host: String, code: String): Result<Unit> = runCatching {
        val h = host.trim().removePrefix("https://").trimEnd('/').lowercase()
        if (!allowedHost(h)) throw ApiError("That's not a Tailscale address (…ts.net)")
        val body = JSONObject().put("code", code.trim()).put("name", "Android app").toString().toRequestBody(JSON)
        http.newCall(Request.Builder().url("https://$h/api/pair").post(body).build()).execute().use { r ->
            if (!r.isSuccessful) throw ApiError(runCatching { JSONObject(r.body?.string() ?: "{}").optString("error") }
                .getOrNull().orEmpty().ifBlank { "Pairing failed" })
            val key = r.headers("Set-Cookie").firstNotNullOfOrNull { Regex("amadeus_dev=([^;]+)").find(it)?.groupValues?.get(1) }
                ?: throw ApiError("No key received")
            store.host = h
            store.deviceKey = key
        }
    }

    fun unpair() {
        runCatching { post("/api/unpair") }
        store.unpair()
    }

    // ---------- home, approvals, its questions ----------
    fun home() = JSONObject(get("/api/app/home"))
    /** The assistant's name, avatar and voice pack (set on the PC). */
    fun identity() = JSONObject(get("/api/identity"))
    fun approvals() = JSONArray(get("/api/approvals"))
    fun decide(approvalId: String, approve: Boolean) =
        JSONObject(post("/api/approvals/$approvalId/" + if (approve) "approve" else "reject", timeoutSec = 120))
    fun events() = JSONArray(get("/api/events"))
    fun markSeen(eventId: String) { post("/api/events/$eventId/seen") }
    fun callAnswered() { post("/api/call/answered") }
    fun appActive() { post("/api/app/active") }

    // ---------- talking to the assistant (the same "Quick chat" as the small window on the PC) ----------
    /** A fresh Quick chat after a quiet break (the PC decides; it keeps a recap of the earlier ones). */
    fun quickChatId(): String = JSONObject(get("/api/quickchat")).getString("id")
    fun newQuickChat(): String = JSONObject(post("/api/quickchat/new", timeoutSec = 60)).getString("id")

    /** The last messages of a chat as (role, text) — only what you said and what it answered. */
    fun history(cid: String, last: Int = 30): List<Pair<String, String>> {
        val msgs = JSONObject(get("/api/conversations/$cid")).getJSONArray("messages")
        return (0 until msgs.length()).map { msgs.getJSONObject(it) }
            .filter { it.optString("role") in setOf("user", "assistant") && it.optString("content").isNotBlank() }
            .map { it.getString("role") to stripMood(it.getString("content")) }
            .takeLast(last)
    }

    /**
     * Sends a message and streams its answer. onText gets the answer so far (mood tags removed);
     * onApproval is called when it needs your OK for something.
     */
    fun chat(cid: String, text: String, voice: Boolean, onText: (String) -> Unit, onApproval: (JSONObject) -> Unit = {},
             onMood: (String) -> Unit = {}) {
        val body = JSONObject().put("text", text).put("voice", voice).toString().toRequestBody(JSON)
        http.newCall(request("/api/conversations/$cid/messages").post(body).build()).execute().use { r ->
            if (!r.isSuccessful) throw ApiError("Your PC answered ${r.code}", r.code)
            val src = r.body?.source() ?: return
            var event = ""
            val acc = StringBuilder()
            while (true) {
                val line = src.readUtf8Line() ?: break
                when {
                    line.startsWith("event: ") -> event = line.removePrefix("event: ")
                    line.startsWith("data: ") -> {
                        val data = line.removePrefix("data: ")
                        when (event) {
                            "token" -> {
                                acc.append(JSONArray("[$data]").optString(0))
                                Regex("\\[mood:\\s*(\\w+)\\]", RegexOption.IGNORE_CASE).find(acc)?.let { onMood(it.groupValues[1].lowercase()) }
                                onText(stripMood(acc.toString()))
                            }
                            "approval" -> onApproval(JSONObject(data))
                            "error" -> throw ApiError(JSONObject(data).optString("message", "Something went wrong"))
                            "done" -> return
                        }
                    }
                }
            }
        }
    }

    /** Speech to text on your PC (Whisper). The recording goes only to your PC. */
    fun stt(audio: ByteArray, contentType: String): String =
        JSONObject(call("/api/voice/stt", audio.toRequestBody(contentType.toMediaType()), timeoutSec = 120)).optString("text").trim()

    fun voice(on: Boolean) = JSONObject(post("/api/voice/" + if (on) "on" else "off")).optString("voice")

    // ---------- today ----------
    fun calendar(from: LocalDate, to: LocalDate) = JSONArray(get("/api/calendar?from=$from&to=$to"))
    fun todo(): List<String> = JSONObject(get("/api/todo")).getJSONArray("items").let { a -> (0 until a.length()).map { a.getString(it) } }
    fun todoDone(item: String) { post("/api/todo/done", JSONObject().put("item", item)) }

    // ---------- mail (read on your PC through Thunderbird) ----------
    fun mailStatus() = JSONObject(get("/api/mail/status", 30))
    fun mailUnread() = JSONArray(get("/api/mail/unread", 90))
    fun mailMessage(id: Long) = JSONObject(get("/api/mail/message/$id", 60))
    fun mailMarkRead(id: Long, read: Boolean) { post("/api/mail/markread", JSONObject().put("ids", JSONArray().put(id)).put("read", read)) }

    // ---------- settings ----------
    fun devices() = JSONObject(get("/api/devices", 30))
    fun goPrivate() = JSONObject(post("/api/phone/private", timeoutSec = 90))
}
