// The mini core (mini.html, shown by the desktop app): a transparent window with only the core. It speaks in
// comic-style bubbles that fade a few seconds later (the history is in the dashboard's Chat), and it "calls" you for
// reminders, urgent mail and approvals: the core beats like a heart, the ring plays on every beat, and the actions
// are right in an amber bubble. Clicking the core opens the dashboard.
const $ = (s) => document.querySelector(s);
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
};
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const noEmoji = (t) => String(t || "").replace(/[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}️‍⃣]\s?/gu, "");
const stripMood = (t) => noEmoji((t || "").replace(/\s*\[mood:\s*\w*\]?\s*$/i, "").replace(/\[mood:\s*\w+\]/gi, ""));
const plain = (t) => stripMood(t).replace(/```[\s\S]*?```/g, " ").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/[*_`#>|~]/g, "").replace(/\s+/g, " ").trim();
const native = (msg) => { try { (window.amadeusBridge || window.webkit.messageHandlers.amadeus).postMessage(msg); } catch {} };
const CALL = new URLSearchParams(location.search).has("call");  // opened for a call: it closes again afterwards

// ---------- the core ----------
const core = Core.start($("#corewrap"), { points: "mini" });
const placeCore = () => { const r = $("#corewrap").getBoundingClientRect(); core.target(r.width / 2, r.height / 2, Math.min(r.width, r.height) / 2 / 1.5); };
new ResizeObserver(placeCore).observe($("#corewrap")); placeCore();
let mode = "idle";
const setMode = (m) => { mode = m; core.mode(m); };
// the sphere: a click opens the dashboard, holding it talks to her (she listens while you hold, it sends when you let
// go). The outer edge of the disc moves the window (the app starts that before the page sees the press).
const HOLD = 350;
let hold = null;
const onCore = (e) => {
  const r = $("#corewrap").getBoundingClientRect(), R = Math.min(r.width, r.height) / 2 / 1.5 * 1.15;
  return Math.hypot(e.clientX - (r.x + r.width / 2), e.clientY - (r.y + r.height / 2)) <= R;
};
$("#corewrap").addEventListener("mousedown", (e) => {
  if (e.button !== 0 || !onCore(e)) return;
  const h = hold = { talking: false };
  h.t = setTimeout(() => {
    if (!window.Voice || hold !== h) return;
    h.talking = true; $("#mini").classList.add("holding"); Voice.listen(); listening(true);
  }, HOLD);
});
addEventListener("mouseup", () => {
  const h = hold; hold = null;
  if (!h) return;
  clearTimeout(h.t);
  if (h.talking) { $("#mini").classList.remove("holding"); Voice.release(); }
  else native("dash:/#home");  // a click
});
$("#corewrap").addEventListener("mousemove", (e) => { $("#corewrap").style.cursor = onCore(e) ? "pointer" : ""; });
// tell the window where the buttons are, so a press there isn't taken as moving the window
function zones() {
  const z = [...document.querySelectorAll(".ctl" + (SEPARATE ? "" : ", .bubble.show"))].map((e) => {
    const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height].map(Math.round); });
  native("zones:" + JSON.stringify(z));
}
new MutationObserver(() => setTimeout(zones, 400)).observe($("#bubbles"), { childList: true, subtree: true, attributes: true });
// Her bubble is its own window, so the core never moves or resizes for it (bubble.html). What's in #bubbles here is
// copied there as it changes, and a click there presses the same button here. Without KDE's window scripts it stays
// in this window, which is then taller.
const SEPARATE = innerHeight < 470;
if (SEPARATE) {
  document.body.classList.add("separate");
  let sent = "";
  const copy = () => { const h = $("#bubbles").innerHTML; if (h !== sent) { sent = h; native("bubble:" + h); } };
  new MutationObserver(copy).observe($("#bubbles"), { childList: true, subtree: true, attributes: true, characterData: true });
  window.amadeusBubbleReady = () => { sent = null; copy(); };
  window.amadeusBubbleClick = (a) => { const b = $(`#bubbles [data-a="${a}"]`); if (b) b.click(); };
}
addEventListener("resize", () => { shape(); zones(); });
setTimeout(zones, 300);
// the app tells us when the bottom of this window is off the screen (the core is at the bottom)
window.amadeusPillTop = (on) => { document.body.classList.toggle("pilltop", on); shape(); setTimeout(zones, 50); };
native("pill?");
(function firstStart(tries) {  // nothing to talk with yet: the dashboard walks you through it (the core may still be starting)
  api("/api/setup").then((s) => { if (s.needed) native("dash:/#home"); }).catch(() => { if (tries > 0) setTimeout(() => firstStart(tries - 1), 1000); });
})(30);
$("#cls").onclick = () => { stopAll(); native("close"); };

// ---------- bubbles: only what is being said right now ----------
let shapeT = 0;
function shape() {  // tell the window where something is drawn, so clicks elsewhere go to the desktop below
  clearTimeout(shapeT);
  shapeT = setTimeout(() => {
    const rects = [$("#disc"), $("#ctl"), ...(SEPARATE ? [] : document.querySelectorAll(".bubble.show"))].map((e) => { const r = e.getBoundingClientRect(); return [r.x - 4, r.y - 14, r.width + 8, r.height + 28].map(Math.round); });
    native("shape:" + JSON.stringify(rects));
  }, 60);
}
function bubble(kind, who, html, keep) {
  if (kind !== "user") document.querySelectorAll(".bubble:not(.user)").forEach(drop);  // one at a time
  const b = document.createElement("div");
  b.className = "bubble " + kind;
  b.innerHTML = (who ? `<span class="who">${esc(who)}</span>` : "") + `<div class="tx">${html}</div>`;
  $("#bubbles").appendChild(b);
  requestAnimationFrame(() => { b.classList.add("show"); shape(); });
  if (!keep) fadeLater(b, kind === "user" ? 3500 : 4000);
  return b;
}
function fadeLater(b, ms) { clearTimeout(b.fade); b.fade = setTimeout(() => drop(b), ms); }
function drop(b) { if (!b || !b.isConnected) return; b.classList.remove("show"); clearTimeout(b.fade); setTimeout(() => { b.remove(); shape(); maybeHide(); }, 350); }
const NAME_UP = () => (window.NAME ? NAME() : "Amadeus").toUpperCase();

// ---------- the VOICE tag: ON (default here), SPOKEN (only when you talked), OFF ----------
const VM = { always: ["ON", "Reads every answer aloud"], voice: ["SPOKEN", "Speaks only when you asked by voice"], off: ["OFF", "Answers stay text only"] };
let speakMode = "always", hasVoice = true;
function setVoiceTag() {
  const t = $("#vTag");
  t.classList.toggle("voice", hasVoice && speakMode === "always"); t.classList.toggle("off", !hasVoice || speakMode === "off");
  t.title = hasVoice ? `Spoken answers: ${VM[speakMode][1]} (click to change)` : "No voice installed: pick one under Settings → Voice";
}
api("/api/voice/replies?for=mini").then((d) => { speakMode = VM[d.mode] ? d.mode : "always"; hasVoice = !!d.voice; setVoiceTag(); }).catch(setVoiceTag);
$("#vTag").onclick = () => {
  if (Aloud.active) return Aloud.stop();  // while she speaks the tag says STOP
  if (!hasVoice) return;
  speakMode = { always: "voice", voice: "off", off: "always" }[speakMode]; setVoiceTag();
  post("/api/voice/replies", { mode: speakMode, for: "mini" });
};
let busy = false;
const Aloud = makeAloud({  // speak.js
  busy: () => busy, talk: () => core.talk(), strip: stripMood,
  speaking: (on) => { native("speaking:" + (on ? 1 : 0)); $("#vTag").classList.toggle("speaking", on); if (on) setMode("speak"); },
  idle: () => { if (!busy && !ringing) setMode("idle"); },
  failed: (e) => { if (/text-to-speech|voice/i.test(e.message)) { hasVoice = false; setVoiceTag(); } },
});

// ---------- talking with her: the answer types into a bubble, spoken sentence by sentence ----------
async function ask(text, spoken) {
  if (!text || busy) return;
  busy = true; setMode("think");  // what you said isn't shown here (the dashboard's Chat has it)
  const aloud = hasVoice && (speakMode === "always" || (speakMode === "voice" && spoken));
  if (aloud) Aloud.start(); else Aloud.stop();
  let acc = "", b = null, own = false;
  const render = (n) => { if (!b) b = bubble("amadeus", NAME_UP(), "", true); const tx = b.querySelector(".tx"); tx.textContent = plain(acc).slice(0, n === Infinity ? undefined : n) || "…"; tx.scrollTop = tx.scrollHeight; shape(); };  // the newest words stay in view
  if (aloud) Aloud.reveal = (n) => render(n);
  try {
    const cid = (await api("/api/quickchat")).id;  // today's chat: the dashboard shows the whole conversation
    const r = await fetch(`/api/conversations/${cid}/messages`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, voice: !!spoken, speak: aloud }) });
    const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = chunk.match(/^event: (.*)$/m)?.[1], data = JSON.parse(chunk.match(/^data: (.*)$/m)?.[1] || "{}");
        if (ev === "say" && aloud && Aloud.active) { own = true; acc = data; Aloud.own(data); }  // the bubble shows what she says
        if (ev === "token" && !own) { acc += data; if (aloud && Aloud.active) Aloud.feed(acc, false); else { setMode("speak"); core.talk(); render(Infinity); } }
        if (ev === "tool") setMode("think");
        if (ev === "approval") { if (Aloud.active) Aloud.stop(); acc = ""; refresh(); }
        if (ev === "say_line" && aloud) quick(data);
        if (ev === "error") acc += "\nThat didn't work: " + data.message;
      }
    }
  } catch (e) { acc = "That didn't work: " + e.message; }
  busy = false;
  const finish = () => { if (b) { render(Infinity); fadeLater(b, 4000); } if (!ringing) setMode("idle"); };
  if (Aloud.active) { Aloud.done = finish; Aloud.feed(acc, true); if (!Aloud.playing && !Aloud.queue.length) Aloud.end(); }
  else finish();
}
// a short line of her own (after a call): shown in a bubble and, with voice, spoken
function say(text) {
  const b = bubble("amadeus", NAME_UP(), esc(text), true);
  if (hasVoice && speakMode !== "off") {
    Aloud.start(); Aloud.reveal = null; Aloud.done = () => fadeLater(b, 4000); Aloud.feed(text, true);
  } else fadeLater(b, 4000);
}

// ---------- voice: the mic, Ctrl + Space, the wake word ----------
let listenB = null;
function listening(on) {
  if (on) { Aloud.stop(); stopRing(); setMode("listen"); if (!listenB || !listenB.isConnected) listenB = bubble("listen", "", "LISTENING", true); }
  else { drop(listenB); listenB = null; if (!busy && !ringing) setMode("idle"); }
}
if (window.Voice) {
  Voice.onBusy = (b) => { if (b && listenB) listenB.querySelector(".tx").textContent = "…"; };
  Voice.onHint = (msg) => { listening(false); bubble("amadeus", NAME_UP(), esc(msg)); };
  Voice.onText = (text) => { listening(false); if (adjusting) return adjustWith(text); ask(text, true); };
  new MutationObserver(() => listening(document.body.classList.contains("listening"))).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  window.amadeusWake = (d) => {  // the wake word
    const on = d.stage === "listening";
    document.body.classList.toggle("listening", on);
    if (on) return;
    if (d.stage === "text" && d.text) Voice.onText(d.text);
    else if (d.stage === "cancel" && !d.quiet) bubble("amadeus", NAME_UP(), esc(`I didn't catch a request. Say "${NAME()}" and what you need.`));
  };
}

// ---------- calls: the heartbeat rings, the actions are in the bubble ----------
// The ring: a soft two-tone beep on every heartbeat.
let ctx = null, ringing = null, ringTimer = 0;
function beep() {
  ctx = ctx || new AudioContext();
  const t = ctx.currentTime;
  [[660, 0], [880, .18]].forEach(([f, d]) => {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = f; o.connect(g); g.connect(ctx.destination);
    g.gain.setValueAtTime(.0001, t + d); g.gain.exponentialRampToValueAtTime(.15, t + d + .02);
    g.gain.exponentialRampToValueAtTime(.0001, t + d + .16); o.start(t + d); o.stop(t + d + .18);
  });
}
core.onBeat = () => { if (ringing) beep(); };
const queue = [], handled = new Set(), snoozed = {};
function line(e) {
  return { digest: "Here's your day.", message: `Urgent message from ${e.title}.`, mail: `You've got mail: ${e.title}.`, mail_code: e.ref ? "Your code just arrived." : "A mail wants you to confirm your address.",
    calendar: `Coming up: ${e.title}.`, approval: `This needs your OK: ${e.title}`, reminder: `Reminder: ${e.title}`, work: `The work run finished: ${e.title}`, job: e.title,
    job_failed: `Something went wrong: ${e.title}.` }[e.kind] || e.title;
}
let seenAtStart = null;
async function refresh() {
  let fresh, rule; try { [fresh, rule] = await Promise.all([api("/api/events"), api("/api/ringable")]); } catch { return; }
  const now = Date.now();
  // quiet hours, or you're in the phone app: only the urgent kinds ring; the rest waits on the dashboard
  const may = (e) => !rule.phone && (!rule.quiet || rule.urgent.includes(e.kind));
  if (seenAtStart === null && !CALL) { seenAtStart = true; fresh.forEach((e) => handled.add(e.id)); }  // opened by you: old ones don't ring
  for (const e of fresh) {
    if (handled.has(e.id) || queue.some((q) => q.id === e.id) || snoozed[e.id] > now || (ringing && ringing.id === e.id)) continue;
    if (may(e)) queue.push(e); else handled.add(e.id);
  }
  for (let i = queue.length - 1; i >= 0; i--) if (!fresh.some((f) => f.id === queue[i].id)) queue.splice(i, 1);  // handled elsewhere
  if (ringing && !fresh.some((f) => f.id === ringing.id)) endCall(null);  // answered on the dashboard or the phone
  if (!ringing && queue.length && !busy && !listenB) ring(queue.pop());  // the newest first: what just came in beats what's been waiting
}
function ring(e) {
  ringing = e; native("calling:1"); $("#mini").classList.add("ringing"); Aloud.stop(); setMode("think");  // the heartbeat; the ring plays on each beat
  const acts = e.kind === "approval" && e.status === "pending"
    ? '<button data-a="reject">Reject</button><button class="adj" data-a="adjust">Adjust</button><button class="go" data-a="approve">Approve</button>'
    : e.kind === "reminder" ? '<button class="go" data-a="ok">Got it</button><button data-a="snooze">Snooze 10 min</button>'
    : e.kind === "mail_code" && e.ref ? '<button class="go" data-a="copy">Copy code</button><button data-a="ok">Got it</button>'
    : '<button class="go" data-a="ok">Got it</button><button data-a="open">Open</button>';
  const b = bubble("call", "INCOMING", `${esc(line(e))}${e.body ? `<br><small>${esc(e.body.slice(0, 160))}</small>` : ""}<div class="acts">${acts}</div>`, true);
  b.dataset.ev = e.id;
  clearTimeout(ringTimer);
  ringTimer = setTimeout(() => { if (ringing === e) { endCall(null); say("It's waiting for you on the dashboard."); } }, 30000);  // nobody answered
}
// a short word in her voice when you answer a call, nothing more (voices.py makes these once)
let linePlaying = false;
function quick(kind) {
  if (!hasVoice || speakMode === "off") return;
  linePlaying = true;
  const done = () => { linePlaying = false; maybeHide(); }, a = new Audio(`/api/voice/line/${kind}`);
  a.onended = a.onerror = done;
  a.play().catch(done);
}
function stopRing() { clearTimeout(ringTimer); }
function endCall(reply) {
  stopRing();
  const b = document.querySelector(`.bubble.call[data-ev="${ringing && ringing.id}"]`); drop(b);
  if (ringing) handled.add(ringing.id);
  ringing = null; native("calling:0"); $("#mini").classList.remove("ringing"); if (!busy) setMode("idle");
  if (reply) say(reply);
  setTimeout(refresh, 600);
}
let adjusting = null;
async function adjustWith(note) {  // Adjust: what should be different, then the same redraft as on the dashboard
  const e = adjusting; adjusting = null;
  setMode("think");
  const r = await post(`/api/approvals/${e.ref}/revise`, { note }).catch((x) => ({ error: x.message }));
  setMode("idle");
  say(r.error ? "That didn't work: " + r.error : "I changed it. It's waiting for your OK again.");
  setTimeout(refresh, 800);
}
$("#bubbles").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("[data-a]"); if (!btn || !ringing) return;
  const e = ringing, a = btn.dataset.a;
  btn.closest(".acts").querySelectorAll("button").forEach((x) => (x.disabled = true));
  post("/api/call/answered", {}).catch(() => {});
  if (a === "approve" || a === "reject") {
    const r = await post(`/api/approvals/${e.ref}/${a}`).catch((x) => ({ status: "failed", error: x.message }));
    await post(`/api/events/${e.id}/seen`).catch(() => {});
    if (a === "approve" && (r.status === "failed" || r.error)) return endCall("I tried, but it didn't work. It's in the chat.");
    endCall(null);
    return quick(a === "approve" ? "done" : "okay");
  }
  if (a === "adjust") {
    endCall(null); handled.add(e.id); adjusting = e;
    say("What should be different?");
    setTimeout(() => { if (window.Voice && adjusting) { Voice.listen(true); listening(true); } }, 1600);
    return;
  }
  if (a === "snooze") {  // the reminder stays; it rings again in ten minutes
    snoozed[e.id] = Date.now() + 10 * 60000; stopRing(); drop(document.querySelector(`.bubble.call[data-ev="${e.id}"]`));
    ringing = null; native("calling:0"); $("#mini").classList.remove("ringing"); setMode("idle"); say("I'll remind you again in ten minutes."); return;
  }
  if (a === "copy") { try { await navigator.clipboard.writeText(e.ref); } catch {} }
  await post(`/api/events/${e.id}/seen`).catch(() => {});
  if (a === "open") native("dash:" + (e.conversation_id ? `/#chat=${e.conversation_id}` : e.kind === "mail" || e.kind === "mail_code" ? "/#mail=unread" : e.ref === "day" ? "/#day" : "/#home"));
  endCall(a === "copy" ? "Copied." : null);
  if (a === "ok") quick("okay");
});
// picked up on the phone: stop ringing here
setInterval(async () => {
  if (!ringing) return;
  const c = await api("/api/call").catch(() => null);
  if (c && c.by === "phone" && c.at * 1000 > Date.now() - 30000) { handled.add(ringing.id); endCall(null); }
}, 2000);

// opened only for a call: once everything is handled and her reply has faded, the window closes again
let hideT = 0;
function maybeHide() {
  if (!CALL) return;
  clearTimeout(hideT);
  hideT = setTimeout(() => { if (!ringing && !queue.length && !busy && !Aloud.active && !linePlaying && !listenB && !adjusting && !document.querySelector(".bubble")) native("hide"); }, 1500);
}
function stopAll() { Aloud.stop(); stopRing(); ringing = null; native("calling:0"); $("#mini").classList.remove("ringing"); setMode("idle"); }
window.amadeusShown = (reason) => { if (reason === "call") refresh(); };  // the window was shown (again)

(async () => {
  await window.IDENTITY;
  try { const c = await api("/api/core"); if (c.topics) core.topics(c.topics); } catch {}
  await refresh();
  setInterval(refresh, 4000);
  shape();
  if (CALL) setTimeout(maybeHide, 4000);  // opened for a call that was already handled elsewhere
})();
