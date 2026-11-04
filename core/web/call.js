// Desktop "incoming call" (the phone page). Lists what needs you: approvals, reminders, work results, jobs.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (path, opts = {}) => {
  const r = await fetch(path, { ...opts, headers: { "content-type": "application/json" } });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
};
// the KDE window has a native bridge; the phone app just navigates (and never closes itself)
const native = (msg) => {
  if (window.PHONE) { if (msg.startsWith("open:")) location.href = "/index.html" + (msg.slice(5).replace(/^\//, "") || ""); return; }
  try { window.webkit.messageHandlers.amadeus.postMessage(msg); } catch { window.close(); }
};
const ICON = { digest: "📬", message: "💭", mail: "✉️", mail_code: "🔑", calendar: "📅", approval: "✅", reminder: "⏰", work: "🛠️", job: "📋", job_failed: "⚠️" };
const STAY = new URLSearchParams(location.search).has("stay") || window.PHONE;  // small window or phone app: no ringing, no auto-close
let events = [], answered = false;

function line(e) {
  return { digest: "Here's your day.", message: `Urgent message from ${e.title}.`, mail: `You've got mail: ${e.title}.`, mail_code: e.ref ? "Your code just arrived." : "A mail wants you to confirm your address.", calendar: `Coming up: ${e.title}.`, approval: `This needs your approval: ${e.title}`, reminder: `Reminder: ${e.title}`,
    work: `The work agents finished. ${e.title}`, job: e.title,
    job_failed: `Something went wrong: ${e.title}. You should take a look.` }[e.kind] || e.title;
}
function mood(e) { return e.kind === "job_failed" ? "worried" : e.kind === "approval" ? "normal" : "happy"; }

function say(text, m) {
  Avatar.setMood(m); Avatar.subtitle(text, Math.max(4000, text.length * 70));
  if ($("#log") && answered) bubble("amadeus", text);  // whatever it says also stays readable in the conversation

  const t = setInterval(Avatar.talk, 150); setTimeout(() => clearInterval(t), Math.min(6000, text.length * 55));
}

function render() {
  $("#count").textContent = events.length === 1 ? "1 update" : `${events.length} updates`;
  const open = events.filter((e) => !e.done);
  $("#list").innerHTML = (events.length > 1 ? `<div class="listhead"><span>${open.length} update${open.length === 1 ? "" : "s"}</span>
      <button type="button" id="clearAll" title="Dismiss everything except approvals that still wait">Clear all</button></div>` : "") +
    events.map((e) => {
      const pending = e.kind === "approval" && e.status === "pending";
      const acts = e.done ? "" : pending
        ? `<button class="green" data-ok="${e.id}">Approve</button><button class="red" data-no="${e.id}">Reject</button><button data-open="${e.id}">Open</button>`
        : e.kind === "message" ? `<button class="green" data-open="${e.id}">Reply</button>`
        : e.kind === "mail_code" ? (e.ref ? `<button class="green" data-copy="${e.id}">Copy code</button>` : "") + `<button data-open="${e.id}">Open mail</button>`
        : (e.conversation_id || e.kind === "mail" || e.ref === "day") ? `<button data-open="${e.id}">Open</button>`
        : e.kind === "reminder" && /^mail:/.test(e.ref || "") ? `<button data-open="${e.id}">Open mail</button>` : "";
      return `<div class="ev ${e.done ? "done" : ""}" data-ev="${e.id}">
        <div class="t">${(ICON[e.kind] || "•")} ${esc(e.title)}</div>${e.body ? `<div class="b">${esc(e.body)}</div>` : ""}
        <div class="a">${acts}</div>${e.done ? "" : `<button class="x" data-seen="${e.id}" title="Dismiss">✕</button>`}</div>`;
    }).join("");
  document.querySelectorAll("[data-ok],[data-no]").forEach((b) => b.onclick = () => decide(b.dataset.ok || b.dataset.no, !!b.dataset.ok));
  document.querySelectorAll("[data-seen]").forEach((b) => b.onclick = () => seen(b.dataset.seen));
  document.querySelectorAll("[data-open]").forEach((b) => b.onclick = () => openEvent(b.dataset.open));
  document.querySelectorAll("[data-copy]").forEach((b) => b.onclick = () => copyCode(b));
  const ca = $("#clearAll"); if (ca) ca.onclick = clearAll;
}
async function clearAll() {  // approvals that still wait stay on the Approvals page; they just leave this list
  for (const e of events.filter((x) => !x.done)) { await api(`/api/events/${e.id}/seen`, { method: "POST" }); e.done = true; }
  events = []; render(); maybeFinish();
}

// A handled item turns green (approved / ok) or red (rejected / failed), then slides away.
function dismiss(id, cls, label) {
  const e = events.find((x) => x.id === id); if (e) e.done = true;
  const card = document.querySelector(`.ev[data-ev="${id}"]`);
  if (!card) { events = events.filter((x) => x.id !== id); render(); return maybeFinish(); }
  card.classList.add(cls);
  card.querySelector(".a").innerHTML = `<span class="tag">${label}</span>`;
  setTimeout(() => card.classList.add("leaving"), 900);
  setTimeout(() => { events = events.filter((x) => x.id !== id); render(); maybeFinish(); }, 1300);
}
async function decide(id, ok) {
  const e = events.find((x) => x.id === id);
  document.querySelectorAll(`.ev[data-ev="${id}"] button`).forEach((b) => (b.disabled = true));
  const r = await api(`/api/approvals/${e.ref}/${ok ? "approve" : "reject"}`, { method: "POST" });
  await api(`/api/events/${id}/seen`, { method: "POST" });
  const failed = r.status === "failed" || r.error;
  say(ok ? (failed ? "I tried, but it failed. Check the chat." : "Done.") : "Fine, I won't do it.", ok && !failed ? "happy" : "normal");
  if (e.conversation_id) followUp(e.conversation_id);
  dismiss(id, ok && !failed ? "ok" : "bad", ok ? (failed ? "✗ Failed" : "✓ Approved") : "✗ Rejected");
}
// after a decision it often continues (e.g. a corrected proposal): show that it's working and then the answer
async function followUp(cid) {
  const wait = bubble("note typing", `${NAME()} is working on it`);
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    const d = await api(`/api/conversations/${cid}`);
    if (!d.busy) {
      wait.remove();
      const last = [...d.messages].reverse().find((m) => m.role === "assistant" && m.content.trim());
      if (last && last.created > Date.now() / 1000 - 300) bubble("amadeus", stripMood(last.content).trim());
      refresh();
      return;
    }
  }
  wait.remove();
}
async function seen(id) {
  await api(`/api/events/${id}/seen`, { method: "POST" });
  dismiss(id, "ok", "✓ OK");
}
async function copyCode(b) {
  const e = events.find((x) => x.id === b.dataset.copy);
  try { await navigator.clipboard.writeText(e.ref); }
  catch { const t = document.createElement("textarea"); t.value = e.ref; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); }
  b.textContent = "Copied ✓";
  setTimeout(() => seen(e.id), 1500);
}
async function openEvent(id) {
  const e = events.find((x) => x.id === id);
  if (e.kind !== "approval") await api(`/api/events/${id}/seen`, { method: "POST" });
  if (e.kind === "reminder" && /^mail:\d+$/.test(e.ref || "")) return native("open:/#mail=" + e.ref.slice(5));
  if (e.ref === "day") return native("open:/#day");  // morning brief / evening summary: "Your day" on the dashboard
  native("open:" + (e.conversation_id ? `/#chat=${e.conversation_id}` : e.kind === "approval" ? "/#approvals" : (e.kind === "mail" || e.kind === "mail_code") ? "/#mail=unread" : e.kind === "message" ? "/#messages" : "/"));
}
// Once you've picked up, the window stays open (to keep talking) until you hang up or close it.
function maybeFinish() { if (!STAY && !answered && events.every((e) => e.done)) setTimeout(() => native("close"), 2500); }

// hanging up marks everything as seen except approvals that still wait for you (they stay on the dashboard)
async function hangUp() {
  for (const e of events) if (!e.done && !(e.kind === "approval" && e.status === "pending")) await api(`/api/events/${e.id}/seen`, { method: "POST" });
  native("close");
}

async function refresh() {
  const fresh = await api("/api/events");
  let added = false;
  const before = events.length;  // items handled elsewhere (e.g. on the dashboard) disappear here too
  events = events.filter((x) => x.done || fresh.some((f) => f.id === x.id));
  if (events.length !== before) { render(); maybeFinish(); }
  for (const e of fresh) if (!events.some((x) => x.id === e.id)) { events.push(e); added = true; if (answered) say(line(e), mood(e)); }
  if (added || !events.length) render();
}

// The ringtone: a soft two-tone ring made right here.
function makeRing() {
  let ctx = null, timer = null;
  const beep = () => {
    const t = ctx.currentTime;
    [[660, 0], [880, 0.18]].forEach(([f, d]) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = f; o.connect(g); g.connect(ctx.destination);
      g.gain.setValueAtTime(0.0001, t + d); g.gain.exponentialRampToValueAtTime(0.15, t + d + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + d + 0.16); o.start(t + d); o.stop(t + d + 0.18);
    });
  };
  return {
    play: () => { ctx = ctx || new AudioContext(); beep(); timer = setInterval(beep, 1600); return Promise.resolve(); },
    stop: () => { clearInterval(timer); timer = null; },
  };
}

// quick chat: a short conversation with the assistant right in the small window (it goes into today's chat)
const stripMood = (t) => t.replace(/\s*\[mood:\s*\w*\]?\s*$/i, "").replace(/\[mood:\s*\w+\]/gi, "");
async function quickChatId() {  // today's chat (one per day)
  return (await api("/api/quickchat")).id;
}
function bubble(cls, text) {
  const d = document.createElement("div"); d.className = "m " + cls;
  if (cls === "amadeus") { d.classList.add("md"); d.innerHTML = window.md(text); } else d.textContent = text;
  $("#log").appendChild(d); $("#log").scrollTop = $("#log").scrollHeight; return d;
}
// The small window always opens empty; what you say here still goes into today's chat (the dashboard shows the whole day).
async function loadHistory() { $("#log").innerHTML = ""; }
// While it talks, the words are only in the speech bubble at the top; when it's done they move into the conversation.
async function ask(text, voice = false) {
  bubble("user", text);
  const wait = bubble("note typing", `${NAME()} is thinking`);
  Avatar.setMood("thinking");
  const cid = await quickChatId();
  const r = await fetch(`/api/conversations/${cid}/messages`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, voice }) });
  const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "", acc = "", note = "", reply = null;
  for (;;) {
    const { value, done } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true }); let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      const ev = chunk.match(/^event: (.*)$/m)?.[1], data = JSON.parse(chunk.match(/^data: (.*)$/m)?.[1] || "{}");
      if (ev === "token") {
        acc += data; Avatar.talk();
        const shown = stripMood(acc).trim();
        if (shown) {  // the reply appears in the conversation as it is written
          if (!reply) { wait.remove(); reply = bubble("amadeus", ""); }
          reply.innerHTML = window.md(shown); $("#log").scrollTop = $("#log").scrollHeight;
        }
        const mm = acc.match(/\[mood:\s*(\w+)\]/i); if (mm) Avatar.setMood(mm[1].toLowerCase());
      }
      if (ev === "approval") { note = "This needs your approval: see above."; refresh(); }
      if (ev === "error") note = "⚠️ " + data.message;
    }
  }
  wait.remove();
  if (!reply && stripMood(acc).trim()) bubble("amadeus", stripMood(acc).trim());
  if (note) bubble("note", note);
}

async function answer() {
  answered = true;
  loadHistory().catch(() => {});
  $("#ringing").hidden = true; $("#talk").hidden = false;
  if (await Avatar.init(api)) Avatar.show(true);
  else $("#avatarPanel .stage").innerHTML = `<img class="avatar-default" src="/agent.svg" alt="">`;  // no sprites: the default agent
  const first = events[0];
  $("#askInput").focus();
  if (!first) return say("Nothing new right now.", "normal");
  say(events.length > 1 ? `${line(first)} …and ${events.length - 1} more.` : line(first), mood(first));
}

(async () => {
  // buttons work even if loading the events fails
  $("#decline").onclick = hangUp;
  if (window.Voice) {
    Voice.onSpeak = (sentence) => Avatar.subtitle(sentence, Math.max(2500, sentence.length * 75));  // subtitle = what it is saying right now
  }
  $("#ask").onsubmit = (e) => { e.preventDefault(); const t = $("#askInput").value.trim(); if (!t) return; $("#askInput").value = ""; ask(t).catch((err) => bubble("note", "⚠️ " + err.message)); };
  let timeout;
  const ring = makeRing();
  const stopRing = () => ring.stop();
  $("#accept").onclick = () => { stopRing(); clearTimeout(timeout); api("/api/call/answered", { method: "POST" }).catch(() => {}); answer(); };
  // picked up on the phone: stop ringing here and close
  const ringStart = Date.now() / 1000;
  setInterval(async () => {
    if (answered || STAY) return;
    const c = await api("/api/call").catch(() => null);
    if (c && c.by === "phone" && c.at > ringStart - 5) { stopRing(); clearTimeout(timeout); native("close"); }
  }, 2000);
  $("#decline").onclick = () => { stopRing(); hangUp(); };
  if (window.Voice) {
    const mic = $("#askMic");
    // click once to start recording, click again to send
    mic.addEventListener("click", (e) => {
      e.preventDefault();
      if (Voice.recording) { Voice.release(); mic.classList.remove("rec"); mic.title = "Click to talk"; }
      else { Voice.listen(); mic.classList.add("rec"); mic.title = "Recording… click again to send"; }
    });
    Voice.onBusy = (b) => { mic.classList.toggle("busy", b); if (b) mic.classList.remove("rec"); };
    // Wake word: the listener records your whole request ("<name>, …") and sends it here as text; this only shows it
    let wakeNote = null;
    window.amadeusWake = async (d) => {
      if (!answered) { stopRing(); clearTimeout(timeout); await answer(); }
      if (d.stage === "listening") {
        if (!wakeNote) wakeNote = bubble("note typing", "Listening… (talk normally, I'll wait until you're done)");
        document.body.classList.add("listening"); mic.classList.add("rec");
        return;
      }
      if (wakeNote) { wakeNote.remove(); wakeNote = null; }
      document.body.classList.remove("listening"); mic.classList.remove("rec");
      if (d.stage === "text" && d.text) ask(d.text, true).catch((err) => bubble("note", "⚠️ " + err.message));
      else if (d.stage === "cancel" && !d.quiet) bubble("note", `I didn't catch a request. Say "${NAME()}" and what you need.`);
    };
    Voice.onHint = (msg) => bubble("note", msg);
    Voice.onText = (text) => { if (!answered) { stopRing(); clearTimeout(timeout); answer(); } ask(text, true).catch((err) => bubble("note", "⚠️ " + err.message)); };
  }
  // everything was handled elsewhere (phone, dashboard): stop ringing and close right away
  let loaded = false;
  setInterval(() => { if (loaded && !answered && !STAY && !events.some((e) => !e.done)) { stopRing(); native("close"); } }, 1000);
  try { await refresh(); loaded = true; } catch (err) { console.error("loading events failed: " + err.message); $("#count").textContent = "Couldn't load the updates: " + err.message; }
  setInterval(() => refresh().catch(() => {}), 5000);
  if (STAY) return answer();
  if (!events.length && !$("#count").textContent.startsWith("Couldn't")) return native("close");
  ring.play().catch((e) => console.warn("ring: play() refused:", e.name, e.message));  // rings even when spoken answers are off
  timeout = setTimeout(() => native("close"), 120000);  // missed call after 2 minutes: the events stay for the next one
  $("#accept").focus();
})();

// ---------- phone app: install + notifications for its calls ----------
if (window.PHONE && "serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").then(async (reg) => {
    const btn = document.getElementById("phoneNotify");
    const key = (await (await fetch("/api/push/key")).json()).key;
    if (!key || !("PushManager" in window)) return;
    const urlB64 = (s) => Uint8Array.from(atob((s + "===".slice((s.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
    const subscribe = async () => {
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64(key) });
      await fetch("/api/push/subscribe", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(sub) });
      btn.hidden = true;
    };
    const existing = await reg.pushManager.getSubscription();
    if (existing && Notification.permission === "granted") {
      fetch("/api/push/subscribe", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(existing) });
    } else {
      btn.hidden = false;
      btn.onclick = async () => { if (await Notification.requestPermission() === "granted") subscribe().catch((e) => alert("Notifications failed: " + e.message)); };
    }
  }).catch((e) => console.warn("service worker:", e));
}

