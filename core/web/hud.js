// The dashboard (index.html): the core in the middle, the views as CRT boxes around it.
const $ = (s) => document.querySelector(s);
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  if (r.status === 401) { document.body.innerHTML = "<p style='padding:30px;color:var(--text)'>Please open it with the <code>amadeus</code> command.</p>"; throw new Error("unauthorized"); }
  return r.json();
};
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const stripMood = (t) => (t || "").replace(/\s*\[mood:\s*\w*\]?\s*$/i, "").replace(/\[mood:\s*\w+\]/gi, "");
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
  if (docked) {  // big views: the core docks bottom-left, centred in its own column so its rings never run under the box
    const col = Math.round(Math.min(440, Math.max(300, W * .25)));
    const r = narrow ? 34 : Math.min((col - 34) / 2 / 1.42, H * .19);
    app.style.setProperty("--col", col + "px"); app.style.setProperty("--dockr", r + "px");
    core.target(narrow ? W - r - 30 : col / 2, narrow ? H - r - 30 : H - r * 1.42 - 24, r, true);
  } else if (sideMode) {  // short lists: the core moves left and shrinks only a little
    const pw = Math.min(400, W * .34) + 28;
    core.target((W - pw) / 2, H * .46, Math.min(W - pw, H) * .29);
  } else core.target(W / 2, H * .46, Math.min(W, H) * (narrow ? .32 : .31));
}
new ResizeObserver(() => place()).observe(stage); place();
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
  approvals: { side: 1, title: "Approvals", meta: "", load: loadApprovals },
  calendar: { title: "Calendar", meta: "", load: () => loadCalendar() },
  mail: { title: "Mail", meta: "Thunderbird", load: () => loadMail() },
  projects: { title: "Projects", meta: "Vault · Projects/", load: () => loadProjects() },  // Calendar, Mail, Projects: hud-views.js
  memory: { title: "Memory", meta: "Hindsight · local", load: loadMemory },
  settings: { title: "Settings", meta: "", load: loadSettings },
};
const body = () => $("#pbody");
function open(v) {
  document.querySelectorAll(".nav").forEach((b) => b.setAttribute("aria-current", String(b.dataset.v === v)));
  curView = VIEWS[v] ? v : "home";
  if (!VIEWS[v]) { docked = sideMode = false; app.classList.remove("docked", "side"); place(); return; }
  const V = VIEWS[v];
  $("#ptitle").textContent = V.title; $("#pmeta").textContent = V.meta; body().innerHTML = "";
  sideMode = !!V.side && core.size.W >= 900; docked = !sideMode;
  app.classList.toggle("docked", docked); app.classList.toggle("side", sideMode); place();
  const pn = $("#panel"); pn.classList.remove("boot"); void pn.offsetWidth; pn.classList.add("boot");
  V.load();
}
document.querySelectorAll(".nav").forEach((b) => (b.onclick = () => open(b.dataset.v)));
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
const state = { cid: null, msgs: [], busy: false, chatTab: "now", past: null, apprCount: -1, spoken: false };
const SYSTEM_CHATS = new Set(["reminders", "mail", "day"]);
async function today() {
  state.cid = (await api("/api/quickchat")).id;
  const d = await api(`/api/conversations/${state.cid}`);
  state.msgs = d.messages;
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
  if (m.role === "assistant" && m.content.trim()) return `<div class="ln a"><span class="ts">${hhmm(m.created)}</span><span class="who">${esc(NAME().toUpperCase())}</span><div class="m">${md(stripMood(m.content))}</div></div>`;
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
      `<button class="row pick" data-act="past" data-i="${i}"><span class="k">${new Date(c.updated * 1000).toLocaleDateString([], { day: "numeric", month: "short" })}</span><div class="t"><b>${esc(c.title)}</b><span>${new Date(c.updated * 1000).toLocaleDateString([], { weekday: "long" })}</span></div><span class="open">Open ›</span></button>`)) : note("No earlier conversations yet."));
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
  if (!state.cid) await today();
  const now = Date.now() / 1000;
  state.msgs.push({ role: "user", content: text, created: now });
  renderGhost();
  liveLine(lineHtml({ role: "user", content: text, created: now }));
  subtitle("…");
  let acc = "", started = false, line = null;
  try {
    const r = await fetch(`/api/conversations/${state.cid}/messages`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, voice: spoken }) });
    const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = chunk.match(/^event: (.*)$/m)?.[1], data = JSON.parse(chunk.match(/^data: (.*)$/m)?.[1] || "{}");
        if (ev === "token") {
          acc += data; core.talk();
          if (!started) { started = true; setMode("speak"); line = liveLine(lineHtml({ role: "assistant", content: " ", created: Date.now() / 1000 }));
            state.msgs.push({ role: "assistant", content: "…", created: Date.now() / 1000 }); renderGhost(); }
          subtitle(acc);
          const gl = $("#ghost .ln:last-child .m"); if (gl) { gl.innerHTML = md(stripMood(acc)); $("#ghost .gin").scrollTop = 1e6; }
          if (line) { line.querySelector(".m").innerHTML = md(stripMood(acc)); liveLine(); }
        }
        if (ev === "tool") setMode("think");
        if (ev === "approval") { acc = ""; started = false; counts(); subtitle(`I need your OK first: ${data.summary}`); if (curView === "approvals") loadApprovals(); }
        if (ev === "error") subtitle("⚠ " + data.message);
      }
    }
  } catch (e) { subtitle("⚠ " + e.message); }
  finally {
    state.busy = false; setTimeout(() => setMode("idle"), 500);
    if (window.Voice) Voice.react(acc);
    await today();
    if (curView === "chat" && state.chatTab === "now") renderChat();
    counts();
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

// ---------- voice: the mic, Ctrl + Space, the wake word ----------
if (window.Voice) {
  const mic = $("#mic");
  const listening = (on) => { mic.classList.toggle("on", on); if (on) { setMode("listen"); subtitle("Listening…", "LISTENING"); } else if (!state.busy) setMode("idle"); };
  mic.onclick = () => { if (Voice.recording) { Voice.release(); listening(false); } else { Voice.listen(); listening(true); } };
  Voice.onBusy = (b) => { if (b) subtitle("Writing down what you said…", "LISTENING"); };
  Voice.onHint = (msg) => { listening(false); subtitle(msg); };
  Voice.onText = (text) => { listening(false); state.spoken = true; send(text); };
  new MutationObserver(() => listening(document.body.classList.contains("listening"))).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  window.amadeusWake = (d) => {  // the wake word while the window is open (popup.py)
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
async function loadApprovals() {
  const list = await api("/api/approvals?status=pending");
  $("#pmeta").textContent = `${list.length} waiting`;
  body().innerHTML = note("Anything that changes something waits here first. Approve it, reject it, or press Adjust and say what should be different.") +
    (list.length ? rows(list.map((a) => `<div class="row ask" data-id="${esc(a.id)}"><span class="chip">${esc(TOOL_KIND(a.tool))}</span>` +
      `<div class="t"><b>${esc(a.conversation_title || "Chat")}${a.revised ? '<em class="chip amber rev">Revised</em>' : ""}</b><span class="md">${md(a.summary)}</span>${a.feedback ? `<em class="why">Changed: ${esc(a.feedback)}</em>` : ""}</div>` +
      `<div class="acts"><button class="btn" data-act="reject">Reject</button><button class="btn adj" data-act="adj">Adjust</button><button class="btn go" data-act="approve">Approve</button></div></div>`))
      : note("Nothing waiting for you."));
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
  ["phone", "Phone", "Pair a phone, private or visible", '<rect x="7" y="3" width="10" height="18"/><path d="M11 18h2"/>'],
  ["reminders", "Reminders", "What it will remind you of", '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l3 2"/>']];
function loadSettings() {
  body().innerHTML = `<div class="themes"><div class="thl">Main colour</div><div class="sw">${Object.entries(THEMES).map(([id, t]) =>
    `<button data-th="${id}" class="${id === window.THEME ? "on" : ""}" style="--s:rgb(${t.a})"><i></i><span>${t.name}</span></button>`).join("")}</div>
    <p class="thn">Changes the whole look, including the core. Amber always means "needs you".</p></div><div class="tiles">${TILES.map(([id, t, s, ic]) => `<button class="tile" data-act="setpage" data-page="${id}"><svg viewBox="0 0 24 24">${ic}</svg><b>${t}</b><span>${s}</span></button>`).join("")}</div>`;
}

// ---------- clicks and forms inside the box ----------
body().addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
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
    if (r.error) { row.classList.remove("redo"); row.querySelector(".t .md").textContent = "⚠ " + r.error; return; }
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
    if (window.Voice) Voice.sfx(act === "approve" ? (r.status === "failed" ? "failed" : "approved") : "rejected");
    subtitle(act === "approve" ? (r.status === "failed" ? "That didn't work: " + (r.result || "") : "Done.") : "Okay, I won't do that.");
    loadApprovals(); counts();
  }
  if (act === "adj" && !row.querySelector(".adjform")) {
    row.insertAdjacentHTML("beforeend", '<form class="adjform"><span>WHAT SHOULD BE DIFFERENT?</span><input placeholder="e.g. make it 16:00 and a bit warmer" aria-label="What should be different"><button class="btn go">Send</button></form>');
    row.querySelector(".adjform input").focus();
  }
  if (act === "ctab" || act === "past") { state.chatTab = act === "past" ? Number(a.dataset.i) : a.dataset.tab; if (act === "ctab" && a.dataset.tab === "history") state.past = null; renderChat(); }
  if (act === "toappr") open("approvals");

});

// ---------- start ----------
(async () => {
  await window.IDENTITY;
  $("#q").placeholder = `Ask ${NAME()}… try “show my calendar”`;
  await today(); counts(); nextUp(); memStats(); mailCount();
  setInterval(counts, 8000); setInterval(nextUp, 60000); setInterval(mailCount, 60000); setInterval(memStats, 300000);
  try { const m = await api("/api/models"); $("#tag").innerHTML = `<b></b>Core online · ${esc(m.default)} · local only`; } catch {}
  const h = location.hash.slice(1);  // deep links from the desktop call: #approvals, #chat
  if (VIEWS[h]) open(h);
  if (h) history.replaceState(null, "", "/");
})();
