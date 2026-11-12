// The dashboard (index.html): the core in the middle, the views as CRT boxes around it.
const $ = (s) => document.querySelector(s);
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  if (r.status === 401) { document.body.innerHTML = "<p style='padding:30px;color:var(--text)'>Please open it with the <code>amadeus</code> command.</p>"; throw new Error("unauthorized"); }
  return r.json();
};
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// replies are shown clean: no mood tag, no emoji or decorative symbols (the model is asked for none; this is the safety net)
const noEmoji = (t) => String(t || "").replace(/[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\uFE0F\u200D\u20E3]\s?/gu, "");
const stripMood = (t) => noEmoji((t || "").replace(/\s*\[mood:\s*\w*\]?\s*$/i, "").replace(/\[mood:\s*\w+\]/gi, ""));
const plain = (t) => stripMood(t).replace(/```[\s\S]*?```/g, " ").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/[*_`#>|~]/g, "").replace(/\s+/g, " ").trim();
const hhmm = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const app = $("#app"), stage = $("#stage");

// ---------- clock ----------
function tick() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  $("#clock").textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  $("#bigtime").textContent = `${p(d.getHours())}:${p(d.getMinutes())}`;
  $("#date").textContent = d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
}
tick(); setInterval(tick, 1000);

// ---------- the core and where it sits ----------
const core = Core.start(stage);
let docked = false, sideMode = false, curView = "home";
function place() {
  const { W, H } = core.size, narrow = W < 760;
  const chat = app.classList.contains("ws-on") && document.querySelector(".wschat"), grid = chat && document.querySelector(".wsgrid");
  if (chat && chat.offsetWidth) {  // the workspace fills the screen: a small core floats in the corner under the chat
    const s = stage.getBoundingClientRect(), c = chat.getBoundingClientRect(), g = grid.getBoundingClientRect();
    const r = Math.max(26, Math.min(50, c.width / 2 / 1.42 - 10, H * .07));
    app.style.setProperty("--wscore", Math.round(r * 1.42 * 2 + 18) + "px");
    core.target(c.width > 500 ? c.right - s.left - r * 1.42 - 10 : c.left - s.left + c.width / 2, g.bottom - s.top - r * 1.42 - 4, r, true);
  } else if (docked) {  // big views: the core docks bottom-left, centred in its own column so its rings never run under the box
    const col = Math.round(Math.min(440, Math.max(300, W * .25)));
    const r = narrow ? 34 : Math.min((col - 34) / 2 / 1.42, H * .19);
    app.style.setProperty("--col", col + "px"); app.style.setProperty("--dockr", r + "px");
    core.target(narrow ? W - r - 30 : col / 2, narrow ? H - r - 30 : H - r * 1.42 - 24, r, true);
  } else if (sideMode) {  // short lists: the core moves left and shrinks only a little
    const pw = Math.min(400, W * .34) + 28;
    core.target((W - pw) / 2, H * .46, Math.min(W - pw, H) * .29);
  } else core.target(W / 2, H * .46, Math.min(W, H) * (narrow ? .32 : .31));
}
core.onResize = place; place();
const STATE = { idle: "Idle", think: "Recalling", speak: "Speaking", listen: "Listening" };
function setMode(m) { core.mode(m); $("#state").textContent = STATE[m]; }

// the line under the core: the last thing it said (click: the conversation)
function subtitle(text, who) {
  const t = plain(text);
  $("#sub").querySelector(".who").textContent = who || NAME().toUpperCase();
  $("#subText").textContent = t.length > 260 ? "…" + t.slice(-260) : t;
}
$("#sub").onclick = () => open("chat");

// ---------- views ----------
const VIEWS = {
  chat: { side: 1, title: "Chat", meta: "Today", load: loadChat },
  todo: { side: 1, title: "ToDo", meta: "ToDo.md", load: loadTodo },
  approvals: { side: 1, title: "Approvals", meta: "", load: () => { apprTab = "pending"; loadApprovals(); } },
  calendar: { title: "Calendar", meta: "", load: () => loadCalendar() },
  mail: { title: "Mail", meta: "", load: () => loadMail() },
  projects: { title: "Projects", meta: "Your projects folder", load: () => loadProjects() },  // Calendar, Mail, Projects: hud-views.js
  memory: { title: "Memory", meta: "Hindsight · local", load: loadMemory },
  settings: { title: "Settings", meta: "", load: loadSettings },
};
const body = () => $("#pbody");
function open(v) {
  if (v !== "projects" && typeof closeWorkspace === "function" && proj.ws && !closeWorkspace()) return;
  document.querySelectorAll(".nav").forEach((b) => b.setAttribute("aria-current", String(b.dataset.v === v)));
  curView = VIEWS[v] ? v : "home";
  if (!VIEWS[v]) { docked = sideMode = false; app.classList.remove("docked", "side"); place(); return; }
  const V = VIEWS[v];
  $("#ptabs").innerHTML = "";  // a view with tabs (the calendar) puts its switch here
  $("#ptitle").textContent = V.title; $("#pmeta").textContent = V.meta; body().innerHTML = "";
  sideMode = !!V.side && core.size.W >= 900; docked = !sideMode;
  app.classList.toggle("docked", docked); app.classList.toggle("side", sideMode); place();
  const pn = $("#panel"); pn.classList.remove("boot"); void pn.offsetWidth; pn.classList.add("boot");
  V.load();
}
document.querySelectorAll(".nav").forEach((b) => (b.onclick = () => open(b.dataset.v)));
$("#ptabs").addEventListener("click", (e) => { const a = e.target.closest('[data-act="caltab"]'); if (a) calPick(a); });  // (hud-views.js)
document.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => open(b.dataset.go)));
$("#close").onclick = () => open("home");
addEventListener("keydown", (e) => { if (e.key === "Escape" && curView !== "home" && !e.target.closest("input, textarea")) open("home"); });
const rows = (list) => `<div class="rows">${list.join("")}</div>`;
const note = (t) => `<p class="prose">${t}</p>`;

// ---------- counts: what waits for you ----------
async function counts() {
  try {
    const [ap, td] = await Promise.all([api("/api/approvals?status=pending"), api("/api/todo")]);
    const n = ap.length, t = td.items.length;
    $("#wAppr").textContent = n; $("#wTodo").textContent = t;
    $("#nAppr").textContent = n; $("#nAppr").hidden = !n; $("#nTodo").hidden = true;
    if (curView === "approvals" && !body().querySelector(".adjform, .redo") && n !== state.apprCount) loadApprovals();
    state.apprCount = n;
  } catch {}
}
async function mailCount() {
  try {
    const st = await (await fetch("/api/mail/status")).json();
    if (!st.connected) { $("#wMail").textContent = "–"; return; }
    $("#wMail").textContent = (await (await fetch("/api/mail/unread")).json()).length ?? "–";
  } catch { $("#wMail").textContent = "–"; }
}
async function nextUp() {
  try {
    const d = new Date(), ymd = (x) => x.toISOString().slice(0, 10), end = new Date(d.getTime() + 7 * 864e5);
    const occ = (await api(`/api/calendar?from=${ymd(d)}&to=${ymd(end)}`)).filter((o) => o.all_day ? o.occ_end.slice(0, 10) > ymd(d) : new Date(o.occ_end) > d);
    const o = occ.sort((a, b) => a.occ_start.localeCompare(b.occ_start))[0];
    if (!o) { $("#nextUp").innerHTML = "<span>Nothing planned this week</span>"; return; }
    const day = new Date(o.occ_start.slice(0, 10) + "T00:00"), today = new Date(); today.setHours(0, 0, 0, 0);
    const diff = Math.round((day - today) / 864e5);
    const when = diff === 0 ? "Today" : diff === 1 ? "Tomorrow" : day.toLocaleDateString([], { weekday: "long" });
    $("#nextUp").innerHTML = `<b>${esc(o.title)}</b><span>${when}${o.all_day ? " · all day" : " · " + o.occ_start.slice(11, 16)}${o.location ? " · " + esc(o.location) : ""}</span>`;
  } catch {}
}
async function memStats() {
  try {
    const m = await api("/api/core");
    if (m.error) { $("#memStats").textContent = "Memory not reachable"; return; }
    const n = (x) => Number(x || 0).toLocaleString(), at = m.last_learned ? new Date(m.last_learned) : null;
    const when = !at ? "–" : at.toDateString() === new Date().toDateString() ? at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : at.toLocaleDateString([], { day: "numeric", month: "short" });
    $("#memStats").innerHTML = `Facts <i>${n(m.facts)}</i><br>Experiences <i>${n(m.experiences)}</i><br>Observations <i>${n(m.observations)}</i><br>Last learned <i>${when}</i>`;
    core.topics(m.topics || []);
  } catch {}
}

// ---------- the conversation (one per day) ----------
const state = { fb: {}, cid: null, msgs: [], busy: false, chatTab: "now", past: null, apprCount: -1, spoken: false };
const SYSTEM_CHATS = new Set(["reminders", "mail", "day"]);
async function today() {
  state.cid = (await api("/api/quickchat")).id;
  const [d, l] = await Promise.all([api(`/api/conversations/${state.cid}`), api("/api/learning").catch(() => ({}))]);
  state.msgs = d.messages; state.fb = l.feedback || {};
  const last = [...d.messages].reverse().find((m) => m.role === "assistant" && m.content.trim());
  subtitle(last ? last.content : `Hi, I'm ${NAME()}. Everything stays on this PC, and anything that changes something waits for your OK.`);
  renderGhost();
  return d;
}
// Home: today's conversation as a faint log above the ask box (newest brightest); hover shows all of it
function renderGhost() {
  const g = $("#ghost"); if (!g) return;
  const shown = state.msgs.filter((m) => m.role === "user" || (m.role === "assistant" && m.content.trim()) || m.role === "approval");
  g.innerHTML = `<div class="gh"><b>CHAT</b><small>Today · ${shown.length} message${shown.length === 1 ? "" : "s"}</small><span class="grow"></span><button data-go-chat>Open ›</button></div>` +
    `<div class="gin">${shown.length ? `<div class="log">${shown.map(lineHtml).join("")}</div>` : ""}</div>`;
  const n = g.querySelector(".gin"); n.scrollTop = n.scrollHeight;
}
$("#ghost").addEventListener("click", (e) => { if (e.target.closest("[data-go-chat]")) open("chat"); });
$("#ghost").addEventListener("mouseenter", () => setTimeout(() => { const n = $("#ghost .gin"); if (n) n.scrollTop = n.scrollHeight; }, 360));
const lineHtml = (m) => {
  if (m.role === "user") return `<div class="ln u"><span class="ts">${hhmm(m.created)}</span><span class="who">YOU</span><div class="m">${esc(m.content)}</div></div>`;
  if (m.role === "assistant" && m.content.trim()) return `<div class="ln a"><span class="ts">${hhmm(m.created)}</span><span class="who">${esc(NAME().toUpperCase())}</span><div class="m">${md(stripMood(m.content))}</div>` +
    (m.id ? `<div class="rate" data-mid="${m.id}"><button data-act="rate" data-s="1" class="${state.fb[m.id] === 1 ? "on" : ""}">Good</button><button data-act="rate" data-s="-1" class="${state.fb[m.id] === -1 ? "on" : ""}">Not good</button></div>` : "") + "</div>";
  if (m.role === "approval") {
    const st = m.meta.status || "pending";
    return `<div class="ln k ${st}"><span class="ts">${hhmm(m.created)}</span><span class="who">${st === "pending" ? "WAITING FOR YOUR OK" : st.toUpperCase()}</span><div class="m">${esc(plain(m.content).slice(0, 240))}${st === "pending" ? ' <button class="linkish" data-act="toappr">Approvals ›</button>' : ""}</div></div>`;
  }
  return "";
};
const logHtml = (msgs) => `<div class="log">${msgs.map(lineHtml).join("") || note("Nothing said yet today.")}</div>`;
function chatTabs() {
  const on = (id) => (state.chatTab === id || (id === "history" && typeof state.chatTab === "number") ? " on" : "");
  return `<div class="ctabs"><button class="ctab${on("now")}" data-act="ctab" data-tab="now">Now<i class="live"></i></button>` +
    `<button class="ctab${on("history")}" data-act="ctab" data-tab="history">History${state.past ? `<small>${state.past.length}</small>` : ""}</button></div>`;
}
async function loadChat() { state.chatTab = "now"; await renderChat(); }
async function renderChat() {
  if (state.chatTab === "now") {
    if (!state.busy) await today();
    body().innerHTML = chatTabs() + logHtml(state.msgs);
    const l = body().querySelector(".log"); if (l && l.lastElementChild) l.lastElementChild.scrollIntoView({ block: "nearest" });
    return;
  }
  if (!state.past) state.past = (await api("/api/conversations")).filter((c) => !SYSTEM_CHATS.has(c.id) && c.id !== state.cid && !c.title.startsWith("🗂️"));
  if (state.chatTab === "history") {
    body().innerHTML = chatTabs() + note("Pick an earlier conversation to read it.") + (state.past.length ? rows(state.past.map((c, i) =>
      `<button class="row pick" data-act="past" data-i="${i}"><span class="k">${new Date(c.updated * 1000).toLocaleDateString([], { day: "numeric", month: "short" })}</span><div class="t"><b>${esc(noEmoji(c.title))}</b><span>${new Date(c.updated * 1000).toLocaleDateString([], { weekday: "long" })}</span></div><span class="open">Open ›</span></button>`)) : note("No earlier conversations yet."));
    return;
  }
  const c = state.past[state.chatTab], d = await api(`/api/conversations/${c.id}`);
  body().innerHTML = chatTabs() + `<div class="pasthead"><button class="btn" data-act="ctab" data-tab="history">‹ History</button><span><b>${esc(c.title)}</b><small>${new Date(c.updated * 1000).toLocaleDateString()} · read only</small></span></div>` + logHtml(d.messages);
}
function liveLine(html) {  // while the reply streams: keep the open Chat box in step
  if (curView !== "chat" || state.chatTab !== "now") return null;
  const l = body().querySelector(".log"); if (!l) return null;
  if (html) l.insertAdjacentHTML("beforeend", html);
  l.lastElementChild.scrollIntoView({ block: "nearest" });
  return l.lastElementChild;
}
async function send(text) {
  if (!text || state.busy) return;
  state.busy = true; setMode("think");
  const spoken = state.spoken; state.spoken = false;
  const aloud = spkMode === "always" || (spkMode === "voice" && spoken);
  if (aloud) Aloud.start(); else stopAloud();
  if (!state.cid) await today();
  const now = Date.now() / 1000;
  state.msgs.push({ role: "user", content: text, created: now });
  renderGhost();
  liveLine(lineHtml({ role: "user", content: text, created: now }));
  subtitle("…");
  let acc = "", started = false, line = null, own = false;
  const render = (n) => {  // show the reply (with speech: only as far as it has been spoken)
    const t = stripMood(acc).slice(0, n);
    subtitle(t || "…");
    const gl = $("#ghost .ln:last-child .m"); if (gl) { gl.innerHTML = md(t || "…"); $("#ghost .gin").scrollTop = 1e6; }
    if (line) { line.querySelector(".m").innerHTML = md(t || "…"); liveLine(); }
  };
  if (aloud) Aloud.reveal = render;
  try {
    const r = await fetch(`/api/conversations/${state.cid}/messages`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, voice: spoken, speak: aloud }) });
    const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = chunk.match(/^event: (.*)$/m)?.[1], data = JSON.parse(chunk.match(/^data: (.*)$/m)?.[1] || "{}");
        if (ev === "say" && aloud && Aloud.active) { own = true; Aloud.reveal = null; Aloud.own(data); }  // she says this; the screen shows the full answer
        if (ev === "token") {
          acc += data;
          if (!started) { started = true; if (!aloud) setMode("speak"); line = liveLine(lineHtml({ role: "assistant", content: " ", created: Date.now() / 1000 }));
            state.msgs.push({ role: "assistant", content: "…", created: Date.now() / 1000 }); renderGhost(); if (aloud) render(0); }
          if (aloud && Aloud.active && !own) Aloud.feed(acc, false); else { core.talk(); render(Infinity); }
        }
        if (ev === "tool") setMode("think");
        if (ev === "say_line" && aloud) new Audio(`/api/voice/line/${data}`).play().catch(() => {});
        if (ev === "approval") { if (Aloud.active) { stopAloud(); render(Infinity); } acc = ""; started = false; counts(); subtitle(`I need your OK first: ${data.summary}`); if (curView === "approvals") loadApprovals(); }
        if (ev === "error") subtitle("That didn't work: " + data.message);
      }
    }
  } catch (e) { subtitle("That didn't work: " + e.message); }
  finally {
    state.busy = false;
    const settle = async () => {  // the reply is complete (and, with speech, fully spoken): the stored chat takes over
      await today();
      if (curView === "chat" && state.chatTab === "now") renderChat();
      counts();
    };
    if (Aloud.active) { Aloud.done = settle; Aloud.feed(acc, true); if (!Aloud.playing && !Aloud.queue.length) Aloud.end(); }
    else { render(Infinity); setTimeout(() => setMode("idle"), 500); settle(); }
  }
}
// "show my calendar", "open mail": opens the view right away; everything else goes to the assistant
const INTENTS = [["calendar", /calend|my week|schedule/], ["mail", /mail|inbox/], ["todo", /to-?dos?\b/], ["approvals", /approv|waiting/],
  ["projects", /project/], ["memory", /memor/], ["settings", /setting/], ["chat", /chat|conversation/]];
function intent(q) {
  const t = q.toLowerCase().trim();
  if (/^(close|back|home)$/.test(t)) return "home";
  if (!/^(show|open|go to|display)\b/.test(t) || t.split(/\s+/).length > 6) return null;
  return (INTENTS.find(([, re]) => re.test(t)) || [])[0] || null;
}
$("#ask").onsubmit = (e) => {
  e.preventDefault();
  const q = $("#q").value.trim(); if (!q) return; $("#q").value = "";
  const v = intent(q);
  if (v) return open(v);
  send(q);
};

// ---------- the VOICE tag (spoken answers): SPOKEN = when you talked to it (default), ON = every answer, OFF ----------
// The chat always keeps the full text. Stored in Core as voice / always / off.
const VMODES = { voice: ["SPOKEN", "Speaks only when you asked by voice"], always: ["ON", "Reads every answer aloud"], off: ["OFF", "Answers stay text only"] };
let spkMode = "voice", hasVoice = true;
function setVoiceTag() {
  const t = $("#vTag");
  t.classList.toggle("on", hasVoice && spkMode === "always"); t.classList.toggle("half", hasVoice && spkMode === "voice"); t.classList.toggle("warn", !hasVoice);
  $("#vTagT").textContent = hasVoice ? VMODES[spkMode][0] : "NONE";
  t.title = hasVoice ? `Spoken answers: ${VMODES[spkMode][1]} (click to change)` : "No voice installed: pick or download one under Settings → Voice";
}
api("/api/voice/replies").then((d) => { spkMode = VMODES[d.mode] ? d.mode : "voice"; hasVoice = !!d.voice; setVoiceTag(); }).catch(setVoiceTag);
$("#vTag").onclick = () => {
  if (Aloud.active) return stopAloud();  // while it speaks the tag says STOP: it stops her, the mode stays
  if (!hasVoice) return;
  spkMode = { voice: "always", always: "off", off: "voice" }[spkMode]; setVoiceTag();
  post("/api/voice/replies", { mode: spkMode });
};
// Read an answer aloud while it is still being written: every finished sentence goes to the voice right away, the next
// one is prepared while the current one plays, so you hear it within a few seconds. The server turns each piece into
// what a person would say ("2 PM", no links, ids or Markdown). Code, tables and long lists stay in the chat, and after
// about 600 characters it says the rest is in the chat. The voice is the one from Settings → Voice.
const Aloud = makeAloud({  // speak.js
  busy: () => state.busy, talk: () => core.talk(), strip: stripMood,
  speaking: (on) => { desktop("speaking:" + (on ? 1 : 0)); $("#vTag").classList.toggle("speaking", on); if (on) { setMode("speak"); $("#state").textContent = "Speaking"; } },
  idle: () => { if (!state.busy) setMode("idle"); },
  failed: (e) => {
    if (/text-to-speech|voice/i.test(e.message)) { hasVoice = false; setVoiceTag(); }
    subtitle(/text-to-speech|voice/i.test(e.message) ? "I can't speak yet: pick or download a voice under Settings → Voice." : "I couldn't speak that: " + e.message);
  },
});
function stopAloud() { Aloud.stop(); }
addEventListener("keydown", (e) => { if (e.key === "Escape" && Aloud.active) stopAloud(); });

// ---------- dictating into a box (the project's message box): what you say is written there, you send it yourself ----------
const dictate = {  // while it's on, body.dictating lights the box's mic (it survives the page redrawing the box)
  on: false,
  box: () => $("#projText"),
  toggle() {
    if (!window.Voice) return;
    if (Voice.recording) { Voice.release(); return; }  // the second click ends it; Whisper writes it into the box
    stopAloud(); this.on = true; document.body.classList.add("dictating");
    Voice.listen();
  },
  take(text) {
    if (!this.on) return false;
    const t = this.box();
    if (t) {
      const before = t.value && !/\s$/.test(t.value) ? t.value + " " : t.value;
      t.value = before + text.trim(); t.dispatchEvent(new Event("input", { bubbles: true })); t.focus(); t.setSelectionRange(t.value.length, t.value.length);
    }
    this.done(); return true;  // meant for the box: never sent as a chat message
  },
  busy(b) { document.body.classList.toggle("dictbusy", this.on && b); },
  done() { this.on = false; document.body.classList.remove("dictating", "dictbusy"); },
};

// ---------- voice: the mic, Ctrl + Space, the wake word ----------
if (window.Voice) {
  const mic = $("#mic");
  const listening = (on) => { mic.classList.toggle("on", on); if (on) { setMode("listen"); subtitle("Listening…", "LISTENING"); } else if (!state.busy) setMode("idle"); };
  mic.onclick = () => { stopAloud(); if (Voice.recording) { Voice.release(); listening(false); } else { Voice.listen(); listening(true); } };
  Voice.onBusy = (b) => { dictate.busy(b); if (b) subtitle("Writing down what you said…", "LISTENING"); };
  Voice.onHint = (msg) => { listening(false); dictate.done(); subtitle(msg); };
  Voice.onText = (text) => { listening(false); if (dictate.take(text)) return; state.spoken = true; send(text); };
  new MutationObserver(() => listening(document.body.classList.contains("listening"))).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  window.amadeusWake = (d) => {  // the wake word while the window is open
    if (Voice.recording && !Voice.recordingAuto) return;  // you're talking through the mic button: that's the one that counts
    const on = d.stage === "listening";
    document.body.classList.toggle("listening", on);
    if (on) return;
    if (d.stage === "text" && d.text) Voice.onText(d.text);
    else if (d.stage === "cancel" && !d.quiet) subtitle(`I didn't catch a request. Say "${NAME()}" and what you need.`);
  };
}

// ---------- ToDo: your own items go straight into ToDo.md ----------
async function loadTodo() {
  const { items } = await api("/api/todo");
  $("#pmeta").textContent = `ToDo.md · ${items.length} open`;
  body().innerHTML = `<form class="todoadd" id="todoAdd"><span class="plus" aria-hidden="true">+</span><input id="todoNew" placeholder="Add a to-do…" aria-label="Add a to-do" autocomplete="off"><button class="btn go">Add</button></form>` +
    (items.length ? rows(items.map((t, i) => `<div class="row" data-i="${i}"><button class="box" data-act="tick" aria-label="Done"></button><div class="t"><b>${esc(t)}</b></div><span></span></div>`)) : note("Nothing on your ToDo."));
  body().dataset.items = JSON.stringify(items);
}

// ---------- Approvals: Reject / Adjust / Approve ----------
// two tabs: what waits for you, and History (what you approved or rejected, with a way to where it landed)
let apprTab = "pending";
async function loadApprovals() {
  if (apprTab === "history") return loadApprovalHistory();
  const list = await api("/api/approvals?status=pending");
  $("#pmeta").textContent = `${list.length} waiting`;
  body().innerHTML = apprTabs(list.length) + note("Anything that changes something waits here first. Approve it, reject it, or press Adjust and say what should be different.") +
    (list.length ? rows(list.map((a) => `<div class="row ask" data-id="${esc(a.id)}"><span class="chip">${esc(TOOL_KIND(a.tool))}</span>` +
      `<div class="t"><b>${esc(a.conversation_title || "Chat")}${a.revised ? '<em class="chip amber rev">Revised</em>' : ""}</b><span class="md">${md(noEmoji(a.summary))}</span>${a.feedback ? `<em class="why">Changed: ${esc(a.feedback)}</em>` : ""}</div>` +
      `<div class="acts"><button class="btn" data-act="reject">Reject</button><button class="btn adj" data-act="adj">Adjust</button><button class="btn go" data-act="approve">Approve</button></div></div>`))
      : note("Nothing waiting for you."));
}
const apprTabs = (n) => `<div class="ctabs"><button class="ctab${apprTab === "pending" ? " on" : ""}" data-act="atab" data-tab="pending">Waiting${n ? `<small>${n}</small>` : ""}</button>` +
  `<button class="ctab${apprTab === "history" ? " on" : ""}" data-act="atab" data-tab="history">History</button></div>`;
const ASTATE = { done: ["st-done", "Done"], rejected: ["st-idle", "Rejected"], failed: ["st-wait", "Failed"] };
async function loadApprovalHistory() {
  const [all, waiting] = await Promise.all([api("/api/approvals?status=all"), api("/api/approvals?status=pending")]);
  const list = all.filter((a) => a.status !== "pending").slice(0, 80);
  $("#pmeta").textContent = "History";
  body().innerHTML = apprTabs(waiting.length) + (list.length ? rows(list.map((a) => {
    const [c, l] = ASTATE[a.status] || ["st-idle", a.status], link = whereItLanded(a);
    return `<div class="row ahist ${c}"><span class="chip">${esc(TOOL_KIND(a.tool))}</span><div class="t"><b>${esc(a.conversation_title || "Chat")}</b>` +
      `<span class="md">${md(noEmoji(a.summary))}</span>${a.feedback ? `<em class="why">Changed: ${esc(a.feedback)}</em>` : ""}` +
      `${a.status === "failed" && a.result ? `<em class="why">${esc(String(a.result).slice(0, 200))}</em>` : ""}<small class="when">${ago(a.decided || a.created)}</small></div>` +
      `<div class="acts"><span class="chip st ${c}">${l}</span>${link ? `<button class="btn" data-act="landed" data-link="${esc(JSON.stringify(link))}">Open ›</button>` : ""}</div></div>`;
  })) : note("Nothing decided yet."));
}
// where a done action can be seen: the calendar week, the reminders, the mail, the to-dos, the project
function whereItLanded(a) {
  if (a.status !== "done") return null;
  let args = {}; try { args = JSON.parse(a.args || "{}"); } catch {}
  const t = a.tool;
  if (t.startsWith("calendar")) return { view: "calendar", day: (args.start || args.start_date || "").slice(0, 10) };
  if (t.includes("reminder")) return { view: "reminders" };
  if (t.startsWith("todo") || t === "notes_add") return { view: t.startsWith("todo") ? "todo" : "memory" };
  if (t.startsWith("mail_") && t !== "mail_send") return { view: "mail" };
  if (t === "send_to_work" || t === "continue_project") return { view: "projects", project: args.project || "" };
  return null;
}
const TOOL_KIND = (t) => (t.startsWith("mail") ? "Mail" : t.startsWith("calendar") ? "Calendar" : t.includes("reminder") ? "Reminder" : t.includes("todo") ? "ToDo"
  : t.startsWith("mcp_") ? "Connector" : t.includes("work") || t.includes("claude") ? "Work" : t.replace(/_/g, " "));

// ---------- Memory ----------
async function loadMemory() {
  body().innerHTML = `<h3>What the core shows</h3>${note("Every point stands for memories on this PC. Bright clusters are topics, and lines join memories that belong together. While it recalls something, the points it uses light up amber, so you can watch it think.")}
    <div class="legend"><div><i style="background:var(--k0)"></i><p><b>Facts</b> · what is true about you and the world</p></div>
    <div><i style="background:var(--k1)"></i><p><b>Experiences</b> · things you did and talked about</p></div>
    <div><i style="background:var(--k2)"></i><p><b>Observations</b> · patterns it noticed, like how you ask for things</p></div>
    <div><i style="background:var(--rc)"></i><p><b>Recalling</b> · points lit while it answers</p></div></div>
    <h3 style="margin-top:22px">Stored</h3><div class="md" id="memText">Loading…</div>`;
  const m = await api("/api/memory");
  const el = $("#memText"); if (el) el.innerHTML = m.error ? esc(m.error) : md(m.text);
}

// ---------- Settings: the pages, and the look ----------
const TILES = [["assistant", "Assistant", "Name, personality and look", '<circle cx="12" cy="9" r="4"/><path d="M5 20c1-4 4-6 7-6s6 2 7 6"/>'],
  ["voice", "Voice", "The voice that reads your briefs", '<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/>'],
  ["skills", "Skills", "What it pulls in by itself", '<path d="M8 4h8v5l-4 3-4-3zM6 14h12v6H6z"/>'],
  ["connectors", "Connectors", "What it may use, what asks first", '<path d="M9 3v5M15 3v5M7 8h10v4a5 5 0 0 1-10 0zM12 17v4"/>'],
  ["playbooks", "Playbooks", "Fixed recipes like plan my day", '<path d="M6 4h12v16H6zM9 9h6M9 13h6M9 17h3"/>'],
  ["memory", "Memory", "Profile, important people, lessons", '<circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4c3 3 3 13 0 16"/>'],
  ["phone", "Phone", "Pair a phone, private or visible", '<rect x="7" y="3" width="10" height="18"/><path d="M11 18h2"/>']];
function loadSettings() {
  body().innerHTML = `<div class="themes"><div class="thl">Main colour</div><div class="sw">${Object.entries(THEMES).map(([id, t]) =>
    `<button data-th="${id}" class="${id === window.THEME ? "on" : ""}" style="--s:rgb(${t.a})"><i></i><span>${t.name}</span></button>`).join("")}</div>
    <p class="thn">Changes the whole look, including the core. Amber always means "needs you".</p></div><div class="tiles">${TILES.map(([id, t, s, ic]) => `<button class="tile" data-act="setpage" data-page="${id}"><svg viewBox="0 0 24 24">${ic}</svg><b>${t}</b><span>${s}</span></button>`).join("")}</div>`;
}

// ---------- clicks and forms inside the box ----------
body().addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  if (f.classList.contains("ratenote")) {
    const box = f.closest(".rate"), id = box.dataset.mid;
    await post(`/api/messages/${id}/feedback`, { score: -1, note: f.querySelector("input").value.trim() }); state.fb[id] = -1;
    f.remove(); box.querySelectorAll("button[data-act=rate]").forEach((b) => b.classList.toggle("on", b.dataset.s === "-1")); return;
  }
  if (f.id === "todoAdd") {
    const v = $("#todoNew").value.trim(); if (!v) return;
    await post("/api/todo/add", { items: [v] }); await loadTodo(); counts();
    const first = [...body().querySelectorAll(".row")].find((r) => r.querySelector("b").textContent === v);
    if (first) first.classList.add("fresh");
    $("#todoNew").focus(); return;
  }
  if (f.classList.contains("adjform")) {
    const noteText = f.querySelector("input").value.trim(); if (!noteText) return;
    const row = f.closest(".row"); f.remove();
    row.classList.add("redo"); row.querySelector(".t .md").textContent = "Redrafting…";
    setMode("think");
    const r = await post(`/api/approvals/${row.dataset.id}/revise`, { note: noteText });
    setMode("idle");
    if (r.error) { row.classList.remove("redo"); row.querySelector(".t .md").textContent = "That didn't work: " + r.error; return; }
    subtitle("I changed it. Have a look.");
    loadApprovals(); counts();
  }
});
body().addEventListener("click", (e) => {  // the main colour (Settings): saved in Core, so it stays everywhere
  const th = e.target.closest("button[data-th]");
  if (th) { applyTheme(th.dataset.th); post("/api/theme", { theme: th.dataset.th }); }
});
body().addEventListener("click", async (e) => {
  const a = e.target.closest("[data-act]"); if (!a) return;
  const row = a.closest(".row"), act = a.dataset.act;
  if (act === "tick") {
    const items = JSON.parse(body().dataset.items || "[]");
    row.classList.add("done");
    await post("/api/todo/done", { item: items[Number(row.dataset.i)] });
    setTimeout(() => { loadTodo(); counts(); }, 400);
  }
  if (act === "approve" || act === "reject") {
    row.querySelectorAll("button").forEach((b) => (b.disabled = true));
    const r = await api(`/api/approvals/${row.dataset.id}/${act}`, { method: "POST" });
    subtitle(act === "approve" ? (r.status === "failed" ? "That didn't work: " + (r.result || "") : "Done.") : "Okay, I won't do that.");
    loadApprovals(); counts();
    if (act === "approve" && r.status === "failed") new Audio("/api/voice/line/failed").play().catch(() => {});  // never quiet about a failure
  }
  if (act === "adj" && !row.querySelector(".adjform")) {
    row.insertAdjacentHTML("beforeend", '<form class="adjform"><span>WHAT SHOULD BE DIFFERENT?</span><input placeholder="e.g. make it 16:00 and a bit warmer" aria-label="What should be different"><button class="btn go">Send</button></form>');
    row.querySelector(".adjform input").focus();
  }
  if (act === "ctab" || act === "past") { state.chatTab = act === "past" ? Number(a.dataset.i) : a.dataset.tab; if (act === "ctab" && a.dataset.tab === "history") state.past = null; renderChat(); }
  if (act === "toappr") open("approvals");
  if (act === "atab") { apprTab = a.dataset.tab; loadApprovals(); }
  if (act === "landed") {
    const l = JSON.parse(a.dataset.link);
    if (l.view === "calendar") { if (l.day) { cal.week = monday(new Date(l.day + "T00:00")); } open("calendar"); }
    else if (l.view === "reminders") { cal.tab = "rem"; open("calendar"); }
    else if (l.view === "projects") { open("projects"); if (l.project) { proj.sel = l.project; renderProjects(); } }
    else open(l.view);
  }
  if (act === "rate") {  // your rating teaches it (core/amadeus_core/learning.py): "Not good" asks what was wrong, optionally
    const box = a.closest(".rate"), id = box.dataset.mid, score = Number(a.dataset.s);
    if (score < 0 && !box.querySelector("form")) {
      box.insertAdjacentHTML("beforeend", '<form class="ratenote"><input placeholder="What was wrong? (optional)" aria-label="What was wrong"><button class="btn">Send</button></form>');
      box.querySelector("input").focus(); return;
    }
    await post(`/api/messages/${id}/feedback`, { score, note: "" }); state.fb[id] = score;
    box.querySelectorAll("button[data-act=rate]").forEach((b) => b.classList.toggle("on", Number(b.dataset.s) === score));
  }

});

// ---------- the model chip (ask bar): which local model answers today's chat and the next ones ----------
const MODEL = { info: [], chat: "", def: "" };
const short = (n) => n.replace(/-(\d+)k$/i, "");  // "qwen3.5-9b-48k" shows as "qwen3.5-9b" + "48k"
const kctx = (c) => (c ? `${Math.round(c / 1024)}k` : "");
async function loadModels() {
  try {
    const m = await api("/api/models");
    if (m.offline) throw new Error("Ollama isn't running");
    Object.assign(MODEL, { info: m.info || m.models.map((name) => ({ name })), chat: m.chat, def: m.default });
    const cur = MODEL.info.find((x) => x.name === m.chat) || { name: m.chat };
    $("#cModelT").textContent = short(m.chat); $("#cModelC").textContent = kctx(cur.ctx);
  } catch { $("#cModelT").textContent = "offline"; $("#cModelC").textContent = ""; }
}
function modelPop() {
  const pop = $("#pop");
  if (!pop.hidden) return closePop();
  pop.innerHTML = '<div class="ph"><b>MODEL_</b><small>local · installed</small></div>' + MODEL.info.map((x) =>
    `<button type="button" role="option" class="pi${x.name === MODEL.chat ? " on" : ""}" data-model="${esc(x.name)}" aria-selected="${x.name === MODEL.chat}"><span class="ck">${x.name === MODEL.chat ? "●" : ""}</span>` +
    `<span class="pt"><b>${esc(x.name)}</b><small>${esc([x.name === MODEL.def ? "Default" : "", x.params, x.quant].filter(Boolean).join(" · "))}</small></span>` +
    `<span class="pm">${[kctx(x.ctx), x.size ? x.size + " GB" : ""].filter(Boolean).join(" · ")}</span></button>`).join("") +
    '<p class="pf">Switching reloads the model, about 10 s. Memory jobs keep their own.</p>';
  pop.hidden = false; $("#cModel").setAttribute("aria-expanded", "true");
  const f = $(".cmd").getBoundingClientRect(), a = $("#cModel").getBoundingClientRect();
  pop.style.right = Math.max(8, f.right - a.right) + "px";
}
function closePop() { $("#pop").hidden = true; $("#cModel").setAttribute("aria-expanded", "false"); }
$("#cModel").onclick = (e) => { e.stopPropagation(); modelPop(); };
$("#pop").onclick = async (e) => {
  const b = e.target.closest("[data-model]"); if (!b) return;
  closePop();
  if (b.dataset.model === MODEL.chat) return;
  const r = await post("/api/models", { model: b.dataset.model });
  if (r.error) return subtitle("That didn't work: " + r.error);
  await loadModels();
  const say = `Switched to ${r.chat}. Give me a few seconds to load it.`;  // she confirms it in the chat
  subtitle(say); liveLine(lineHtml({ role: "assistant", content: say, created: Date.now() / 1000 }));
  state.msgs.push({ role: "assistant", content: say, created: Date.now() / 1000 }); renderGhost();
};
addEventListener("click", (e) => { if (!e.target.closest("#pop, #cModel")) closePop(); });
addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#pop").hidden) closePop(); });

// ---------- the desktop window: the logo goes back to the mini core, the X closes Amadeus ----------
const desktop = (msg) => { try { (window.amadeusBridge || window.webkit.messageHandlers.amadeus).postMessage(msg); return true; } catch { return false; } };
$("#toMini").onclick = () => desktop("mini");
$("#quitApp").onclick = () => desktop("quit");
if (!window.amadeusBridge && !(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.amadeus)) $("#quitApp").hidden = true;

// ---------- start ----------
(async () => {
  await window.IDENTITY;
  $("#q").placeholder = `Ask ${NAME()}… try “show my calendar”`;
  await today(); counts(); nextUp(); memStats(); mailCount();
  setInterval(counts, 8000); setInterval(nextUp, 60000); setInterval(mailCount, 60000); setInterval(memStats, 300000);
  loadModels();
  // deep links from the call window, the tray and notifications: #approvals, #day, #chat=<id>, #mail=<id>, #reminders, …
  const h = location.hash.slice(1);
  if (VIEWS[h]) open(h);
  else if (h === "messages") open("chat");
  else if (h === "reminders") { cal.tab = "rem"; open("calendar"); }
  else if (h === "settings=assistant") { open("settings"); settingsPage("assistant"); }
  else if (h === "mail=unread") open("mail");
  else if (/^mail=\d+$/.test(h)) {
    open("mail");
    const m = await (await fetch(`/api/mail/message/${h.slice(5)}`)).json().catch(() => ({ error: "not found" }));
    if (!m.error) { mail.open = m; mail.acc = m.accountId || mail.acc; renderMail(); }
  } else if (h.startsWith("chat=")) {
    const id = h.slice(5);
    open("chat");
    if (id !== state.cid) {  // an earlier chat: open it read-only in History
      state.past = (await api("/api/conversations")).filter((c) => !SYSTEM_CHATS.has(c.id) || c.id === id);
      const i = state.past.findIndex((c) => c.id === id);
      if (i >= 0) { state.chatTab = i; renderChat(); }
    }
  }
  if (h) history.replaceState(null, "", "/");
})();

// ---------- a new version: a small chip in the top bar ----------
async function checkUpdateChip() {
  const u = await api("/api/update").catch(() => null), c = $("#updChip");
  if (!u || !c) return;
  c.hidden = !(u.enabled && (u.available || u.restart));
  c.textContent = u.restart ? "Restart to update" : `Update ${u.latest}`;
}
$("#updChip").onclick = () => { open("settings"); settingsPage("assistant"); };
checkUpdateChip();
setInterval(checkUpdateChip, 3600000);
