// Amadeus Core web UI (no build step, no external libraries).
const $ = (s) => document.querySelector(s);
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  if (r.status === 401) { document.body.innerHTML = "<p style='padding:30px'>Please open Amadeus with the <code>amadeus</code> command.</p>"; throw new Error("unauthorized"); }
  return r.json();
};
const esc = (s) => (s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Markdown rendering: see md.js (window.md)

// ---------- Amadeus avatar (see avatar.js) ----------
const setMood = (m) => {
  if (!window.Avatar) return;
  Avatar.setMood(m);
  const el = $("#avatarMood"); if (el && m) el.textContent = "Mood · " + m;
};
async function initAvatar() {
  const animated = await Avatar.init(api);
  if (!animated)  // no sprite set: the default agent icon stands in the box
    $("#avatarPanel .stage").innerHTML = `<img class="avatar-default" src="/agent.svg" alt="">`;
  const btn = $("#avatarToggle");
  btn.classList.remove("hidden");
  // the avatar lives in the bottom-right box; the button shows or hides it
  let on = true; try { on = localStorage.getItem("avatar") !== "off"; } catch {}
  const apply = () => {
    if (animated) Avatar.show(on);
    $("#avatarBox").classList.toggle("hidden", !on);
    btn.classList.toggle("on", on);
    btn.title = on ? "The avatar is shown (click to hide)" : "The avatar is hidden (click to show)";
  };
  btn.onclick = () => { on = !on; try { localStorage.setItem("avatar", on ? "on" : "off"); } catch {} apply(); };
  apply();
}

// ---------- light / dark (follows the system until you pick one) ----------
function initTheme() {
  const btn = $("#themeBtn"), root = document.documentElement;
  const isDark = () => root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  const paint = () => {
    btn.innerHTML = isDark()
      ? '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
      : '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z"/></svg>';
    btn.title = isDark() ? "Switch to light" : "Switch to dark";
  };
  btn.onclick = () => { root.dataset.theme = isDark() ? "light" : "dark"; try { localStorage.setItem("theme", root.dataset.theme); } catch {} paint(); };
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paint);
  paint();
}

// ---------- right column: clock, today, what waits for you, Claude Code ----------
function tickClock() {
  const d = new Date();
  $("#railClock").textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  $("#railDate").textContent = d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }).replace(",", " ·");
}
async function loadRail() {
  try {
    const h = await api("/api/app/home");
    $("#railToday").innerHTML = h.today.length ? h.today.slice(0, 4).map((e) =>
      `<span class="t">${e.all_day ? "all day" : esc(String(e.start).slice(11, 16))}</span><span>${esc(e.title)}</span>`).join("")
      : `<span class="t">—</span><span class="muted">Nothing planned today</span>`;
  } catch {}
  try {
    const run = (await api("/api/projects")).find((p) => p.status === "running");
    $("#railWork").hidden = !run;
    if (run) {
      $("#railWorkName").textContent = run.name;
      $("#railWorkInfo").textContent = run.last_run ? "Started " + new Date(run.last_run * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
    }
  } catch {}
}
// "Your day": click the clock card for today's morning brief and evening summary
const DAY_LABEL = { morning: "☀️ Morning brief", now: "🕑 So far today", evening: "🌙 Evening summary" };
function renderDayReports(reports) {
  $("#dayBody").innerHTML = reports.length ? reports.map((r) =>
    `<section><h4>${DAY_LABEL[r.kind] || r.kind} <small>${new Date(r.at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</small></h4>${md(stripMood(r.text))}</section>`).join("")
    : `<p class="hint" style="padding:0">Nothing yet today. The morning brief comes at 07:00 and the evening summary at 21:00; "Summarize so far" makes one now.</p>`;
}
async function showDay() {
  $("#dayTitle").textContent = "Your day · " + new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
  $("#dayInfo").textContent = "";
  renderDayReports((await api("/api/day")).reports);
  if (!$("#dayDialog").open) $("#dayDialog").showModal();
}
$("#railClockBox").onclick = showDay;
$("#railClockBox").onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showDay(); } };
$("#dayClose").onclick = () => $("#dayDialog").close();
$("#dayNow").onclick = async () => {
  const b = $("#dayNow"); b.disabled = true; $("#dayInfo").textContent = `${NAME()} is writing it…`;
  try { renderDayReports((await api("/api/day/now", { method: "POST", body: "{}" })).reports); $("#dayInfo").textContent = ""; }
  catch (e) { $("#dayInfo").textContent = "That didn't work: " + e.message; }
  b.disabled = false;
};

document.querySelectorAll("[data-go]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); show(a.dataset.go); }));
const stripMood = (t) => t.replace(/\s*\[mood:\s*\w*\]?\s*$/i, "").replace(/\[mood:\s*\w+\]/gi, "");

const state = { cid: null, models: [], defaultModel: "", busy: false, aStatus: "pending", poll: null };

// ---------- views ----------
const IN_SETTINGS = ["settings", "skills", "connectors", "playbooks", "memory", "phone"];
function show(view) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  document.querySelectorAll(".views button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $("#settingsBtn").classList.toggle("active", IN_SETTINGS.includes(view));
  if (view === "projects") proj.name = null;
  $("#sidebar").classList.remove("open");
  ({ todo: loadTodo, projects: loadProjects, approvals: loadApprovals, connectors: loadConnectors, skills: loadSkills, reminders: loadReminders, calendar: loadCalendar, mail: loadMail, playbooks: loadPlaybooks, phone: loadPhone, memory: loadMemory }[view] || (() => {}))();
}
document.querySelectorAll(".views button").forEach((b) => (b.onclick = () => show(b.dataset.view)));
// the Settings wheel (bottom left) and its pages: skills, connectors, playbooks, memory
$("#settingsBtn").onclick = () => show("settings");
document.querySelectorAll("[data-goto]").forEach((b) => (b.onclick = () => show(b.dataset.goto)));
$("#menuBtn").onclick = () => $("#sidebar").classList.toggle("open");

// ---------- conversations ----------
const SYSTEM_CHATS = new Set(["reminders", "mail", "day"]);  // "day": the old "Your day" chat (now the clock card)  // internal threads (reminders, mail filing): reachable from cards, not listed
async function loadConversations() {
  const list = (await api("/api/conversations")).filter((c) => !SYSTEM_CHATS.has(c.id));
  $("#convList").innerHTML = list.map((c) =>
    `<li data-id="${c.id}" class="${c.id === state.cid ? "active" : ""}"><span title="Double-click to rename">${esc(c.title)}</span>` +
    `<button class="ren" title="Rename">✎</button><button class="del" title="Delete">✕</button></li>`).join("");
  $("#convList").querySelectorAll("li").forEach((li) => {
    li.onclick = (e) => {
      if (e.target.classList.contains("del")) return deleteConv(li.dataset.id);
      if (e.target.classList.contains("ren")) return renameConv(li);
      if (e.target.tagName === "INPUT") return;
      openConv(li.dataset.id); show("chat");
    };
    li.querySelector("span").ondblclick = (e) => { e.stopPropagation(); renameConv(li); };
  });
}
function renameConv(li) {
  const span = li.querySelector("span"), old = span.textContent;
  const inp = document.createElement("input"); inp.value = old; inp.className = "rename";
  span.replaceWith(inp); inp.focus(); inp.select();
  let done = false;
  const finish = async (save) => {
    if (done) return; done = true;
    const t = inp.value.trim();
    if (save && t && t !== old) {
      await api(`/api/conversations/${li.dataset.id}`, { method: "PATCH", body: JSON.stringify({ title: t }) });
      if (li.dataset.id === state.cid) $("#convTitle").value = t;
    }
    loadConversations();
  };
  inp.onkeydown = (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); };
  inp.onblur = () => finish(true);
}
async function deleteConv(id) {
  if (!confirm("Delete this conversation? This cannot be undone.")) return;
  await api(`/api/conversations/${id}`, { method: "DELETE" });
  if (id === state.cid) newChat();
  loadConversations();
}
// one chat per day: "Today" opens today's chat (it is created with the day's first message)
const todayChat = async () => (await api("/api/quickchat")).id;
async function newChat() {
  await openConv(await todayChat());
  show("chat"); $("#input").focus();
}
$("#newChat").onclick = newChat;

async function openConv(id) {
  state.cid = id;
  const d = await api(`/api/conversations/${id}`);
  $("#convTitle").value = d.conversation.title;
  if (d.conversation.model) $("#modelSelect").value = d.conversation.model;
  renderMessages(d.messages);
  const lastA = [...d.messages].reverse().find((x) => x.role === "assistant" && x.meta && x.meta.mood);
  if (lastA && !state.busy) setMood(lastA.meta.mood);
  loadConversations();
  const pending = d.messages.some((m) => m.role === "approval" && m.meta.status === "pending");
  clearInterval(state.poll);
  if (d.busy && !state.busy) {  // still working (e.g. after you approved or rejected): show it, refresh when done
    $("#messages").insertAdjacentHTML("beforeend", `<div class="msg assistant typing working">${NAME()} is working on it…</div>`);
    $("#messages").scrollTop = $("#messages").scrollHeight;
    setMood("thinking");
    state.poll = setInterval(() => refreshWhileBusy(id), 1500);
  } else if (pending) state.poll = setInterval(() => refreshIfChanged(id, d.messages.length), 2500);
}
async function refreshWhileBusy(id) {
  if (state.cid !== id || state.busy) return;
  const d = await api(`/api/conversations/${id}`);
  if (!d.busy) { clearInterval(state.poll); openConv(id); }
}
async function refreshIfChanged(id, count) {
  if (state.cid !== id || state.busy) return;
  const d = await api(`/api/conversations/${id}`);
  if (d.messages.length !== count) openConv(id);
}
$("#convTitle").onchange = () => state.cid && api(`/api/conversations/${state.cid}`, { method: "PATCH", body: JSON.stringify({ title: $("#convTitle").value }) }).then(loadConversations);

// ---------- messages ----------
// Where a finished action can be seen: the reminder, the calendar day, the mail folder.
function actionLink(tool, meta) {
  let a = {}; try { a = typeof meta.args === "string" ? JSON.parse(meta.args) : meta.args || {}; } catch {}
  const res = meta.result || "", idm = res.match(/\[(?:id )?([0-9a-f]{12})\]/);
  if (tool === "create_reminder") return { view: "reminders", id: idm && idm[1], text: a.text };
  if (tool === "calendar_add" || tool === "calendar_update") return { view: "calendar", day: (a.start || "").slice(0, 10), id: idm && idm[1] };
  if (tool === "calendar_block_days") return { view: "calendar", day: (a.start_date || "").slice(0, 10), id: idm && idm[1] };
  if (tool.startsWith("mail_") && tool !== "mail_send") return { view: "mail", folder: tool === "mail_move" ? a.folder : "" };
  return null;
}
function openLink(l) {
  if (l.view === "calendar") {
    const day = l.day || (cal.occ.find((o) => o.id === l.id) || {}).start?.slice(0, 10);
    if (day) { const d = new Date(day + "T00:00"); cal.month = new Date(d.getFullYear(), d.getMonth(), 1); cal.sel = day; }
    cal.flash = l.id;
    show("calendar");
    return;
  }
  if (l.view === "mail") { if (l.folder) mail.wantFolder = l.folder; show("mail"); return; }
  show(l.view);
  if (l.view === "reminders") setTimeout(() => {
    const c = [...document.querySelectorAll("#reminderList .card")].find((x) => (l.id && x.dataset.id === l.id) || (l.text && x.dataset.text === l.text));
    if (c) { c.scrollIntoView({ block: "center" }); c.classList.add("flash"); setTimeout(() => c.classList.remove("flash"), 2000); }
  }, 300);
}
function approvalCard(id, tool, summary, meta = {}) {
  const st = meta.status || "pending";
  const pill = { pending: "warn", done: "ok", rejected: "bad", failed: "bad" }[st];
  const link = st === "done" ? actionLink(tool, meta) : null;
  return `<div class="card approval ${st} ${link ? "linked" : ""}" data-aid="${id}" ${link ? `data-link="${encodeURIComponent(JSON.stringify(link))}" title="Open"` : ""}>
    <div class="head">${st === "pending" ? "Needs your approval" : "Action"} · <code>${esc(tool)}</code> <span class="pill ${pill}">${st}</span>${link ? `<span class="open">Open →</span>` : ""}</div>
    <div>${md(summary)}</div>
    ${st === "pending" ? `<div class="actions"><button class="btn-ok" data-act="approve">Approve</button><button class="btn-bad" data-act="reject">Reject</button></div>` : ""}
    ${meta.result && st !== "pending" ? `<div class="result">${esc(meta.result)}</div>` : ""}</div>`;
}
function renderMessages(msgs) {
  const box = $("#messages");
  if (!msgs.length) { box.innerHTML = `<div class="empty"><h1>Hi, I'm ${esc(NAME())}.</h1><p>Your private assistant. Everything stays on this PC. Anything that changes something waits for your approval.</p></div>`; return; }
  box.innerHTML = msgs.map((m) => {
    if (m.role === "user") return `<div class="msg user">${esc(m.content)}</div>`;
    if (m.role === "assistant") return m.content.trim() ? `<div class="msg assistant">${md(m.content)}</div>` : "";
    if (m.role === "approval") return approvalCard(m.meta.approval_id, m.meta.tool, m.content, m.meta);
    if (m.role === "tool" && !m.meta.approval_id) return `<div class="msg tool">🔧 used ${esc(m.meta.name)}</div>`;
    return "";
  }).join("");
  bindApprovalButtons(box);
  box.scrollTop = box.scrollHeight;
}
document.addEventListener("click", (e) => {
  const c = e.target.closest(".card.approval.linked");
  if (c && !e.target.closest("button, a")) openLink(JSON.parse(decodeURIComponent(c.dataset.link)));
});
function bindApprovalButtons(root) {
  root.querySelectorAll(".card.approval .actions button").forEach((b) => (b.onclick = async () => {
    const card = b.closest(".card");
    card.querySelectorAll("button").forEach((x) => (x.disabled = true));
    const r = await api(`/api/approvals/${card.dataset.aid}/${b.dataset.act}`, { method: "POST" });
    if (window.Voice) Voice.sfx(b.dataset.act === "approve" ? (r.status === "failed" ? "failed" : "approved") : "rejected");
    updateBadge();
    if ($("#view-approvals").classList.contains("active")) loadApprovals();
    if (state.cid) openConv(state.cid);
  }));
}

// ---------- sending (streamed) ----------
// grow the message box with its text: CSS field-sizing where supported, otherwise resize only when the line count changes
if (!CSS.supports("field-sizing", "content")) {
  let lines = 1;
  $("#input").addEventListener("input", (e) => {
    const n = (e.target.value.match(/\n/g) || []).length + 1 + Math.floor(e.target.value.length / 90);
    if (n === lines) return;  // no layout work on ordinary keystrokes
    lines = n; e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 220) + "px";
  });
}
$("#input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); } });
$("#composer").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("#input").value.trim();
  if (!text || state.busy) return;
  state.busy = true; $("#send").disabled = true;
  state.egg = window.Voice ? Voice.hear(text) : false;
  if (!state.cid) state.cid = await todayChat();
  $("#input").value = ""; $("#input").style.height = "auto";
  const box = $("#messages");
  if (box.querySelector(".empty")) box.innerHTML = "";
  box.insertAdjacentHTML("beforeend", `<div class="msg user">${esc(text)}</div><div class="msg assistant typing"></div>`);
  setMood("thinking");
  let bubble = box.lastElementChild, acc = "";
  box.scrollTop = box.scrollHeight;
  try {
    const r = await fetch(`/api/conversations/${state.cid}/messages`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, model: $("#modelSelect").value, voice: !!state.spoken }) });
    state.spoken = false;
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = chunk.match(/^event: (.*)$/m)?.[1], data = JSON.parse(chunk.match(/^data: (.*)$/m)?.[1] || "{}");
        if (ev === "token") { acc += data; bubble.innerHTML = md(stripMood(acc)); Avatar.talk(); Avatar.subtitle(stripMood(acc));
          const mm = acc.match(/\[mood:\s*(\w+)\]/i); if (mm) setMood(mm[1].toLowerCase()); }
        if (ev === "tool") { bubble.insertAdjacentHTML("beforebegin", `<div class="msg tool">🔧 using ${esc(data.name)}…</div>`); }
        if (ev === "approval") { acc = ""; bubble.insertAdjacentHTML("beforebegin", approvalCard(data.id, data.tool, data.summary)); bindApprovalButtons(box); updateBadge(); }
        if (ev === "error") { bubble.innerHTML = `⚠️ ${esc(data.message)}`; }
        box.scrollTop = box.scrollHeight;
      }
    }
  } finally {
    if (window.Avatar) Avatar.subtitle(stripMood(acc), 6000);
    if (window.Voice && !state.egg) Voice.react(acc);
    state.busy = false; $("#send").disabled = false;
    openConv(state.cid);
  }
};

// ---------- approvals dashboard ----------
document.querySelectorAll("[data-astatus]").forEach((b) => (b.onclick = () => {
  state.aStatus = b.dataset.astatus;
  document.querySelectorAll("[data-astatus]").forEach((x) => x.classList.toggle("active", x === b));
  loadApprovals();
}));
async function loadApprovals() {
  const list = await api(`/api/approvals?status=${state.aStatus}`);
  const box = $("#approvalList");
  box.innerHTML = list.length ? list.map((a) => {
    const when = new Date(a.created * 1000).toLocaleString();
    return approvalCard(a.id, a.tool, a.summary, a).replace('<div class="card approval',
      `<div class="card approval`).replace('<div class="head">',
      `<div class="meta"><b>${esc(a.conversation_title || "Chat")}</b><span>${when}</span><a href="#" data-open="${a.conversation_id}">Open chat →</a></div><div class="head">`);
  }).join("") : `<p class="hint">${state.aStatus === "pending" ? "Nothing waiting for you. 🎉" : "No history yet."}</p>`;
  bindApprovalButtons(box);
  box.querySelectorAll("[data-open]").forEach((l) => (l.onclick = (e) => { e.preventDefault(); openConv(l.dataset.open); show("chat"); }));
}
async function updateBadge() {
  const n = (await api("/api/approvals?status=pending")).length;
  $("#approvalBadge").textContent = n;
  $("#approvalBadge").classList.toggle("hidden", !n);
  const td = (await api("/api/todo")).items.length;
  $("#todoBadge").textContent = td; $("#todoBadge").classList.toggle("hidden", !td);
  $("#railApprovals").textContent = `${n} →`; $("#railApprovals").classList.toggle("hot", !!n);
  $("#railTodo").textContent = `${td} →`;
}

// ---------- projects (vault Projects/<Name>/, worked on by Claude Code; talk to Amadeus or Claude Code) ----------
const proj = { name: null, poll: null };
const ago = (t) => new Date(t * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" });
const RUN_PILL = { running: ["warn", "Claude Code is working…"], done: ["ok", "done"], failed: ["bad", "stopped"], stopped: ["bad", "stopped"] };
async function loadProjects() {
  clearInterval(proj.poll);
  if (proj.name) return openProject(proj.name);
  $("#projBack").hidden = true; $("#projDetail").hidden = true; $("#projList").hidden = false; $("#projNew").hidden = false; $("#projTerm").hidden = true;
  $("#projTitle").textContent = "Projects"; $("#projStatus").hidden = true;
  const list = await api("/api/projects");
  $("#projList").innerHTML = list.length ? list.map((p) => `<button class="card proj-card" data-p="${esc(p.name)}">
      <b>🗂️ ${esc(p.name)}</b><small>${p.files} file${p.files === 1 ? "" : "s"} · changed ${ago(p.updated)}${p.last_run ? ` · last Claude run ${ago(p.last_run)}` : ""}</small>
      ${p.status ? `<span class="pill ${RUN_PILL[p.status]?.[0] || ""}">${RUN_PILL[p.status]?.[1] || p.status}</span>` : ""}</button>`).join("")
    : `<p class="hint">No projects yet. Start one with ＋ New project, or ask ${esc(NAME())} to send something to work.</p>`;
  document.querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => openProject(b.dataset.p)));
}
async function openProject(name) {
  proj.name = name; clearInterval(proj.poll);
  const d = await api(`/api/projects/${encodeURIComponent(name)}`);
  if (d.error) { proj.name = null; return loadProjects(); }
  $("#projList").hidden = true; $("#projNew").hidden = true; $("#projBack").hidden = false; $("#projDetail").hidden = false; $("#projTerm").hidden = false;
  $("#projTitle").textContent = "🗂️ " + d.name;
  $("#projStatus").hidden = !d.running; $("#projStatus").className = "pill warn"; $("#projStatus").textContent = "Claude Code is working…";
  $("#projOverview").innerHTML = d.overview ? md(d.overview) : `<p class="hint" style="padding:0">No Overview.md yet.</p>`;
  $("#projFileCount").textContent = `(${d.files.length})`;
  $("#projFiles").innerHTML = d.files.map((f) => `<li><a href="#" data-f="${esc(f.path)}">${esc(f.path)}</a> <span class="hint" style="padding:0">${Math.max(1, Math.round(f.size / 1024))} KB</span></li>`).join("");
  $("#projFiles").querySelectorAll("[data-f]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); showProjectFile(d.name, a.dataset.f); }));
  // one timeline: your messages to the assistant and its answers, and every Claude Code run (what was asked, what came back)
  const items = d.messages.map((m) => ({ t: m.created, html: m.role === "user"
      ? `<div class="msg user"><span class="who">You → ${esc(NAME())}</span>${esc(m.content)}</div>`
      : `<div class="msg assistant"><span class="who">${esc(NAME())}</span>${md(m.content)}</div>` }))
    .concat(d.runs.map((r) => ({ t: r.created, html: `<div class="msg user to-claude"><span class="who">→ Claude Code</span>${esc((r.task || "").slice(0, 2000))}</div>` +
      (r.status === "running" ? `<div class="msg claude typing"><span class="who">Claude Code</span>working…</div>`
        : `<div class="msg claude"><span class="who">Claude Code · ${RUN_PILL[r.status]?.[1] || r.status}${r.cost ? ` · $${r.cost.toFixed(2)}` : ""}</span>${md(r.summary || "")}</div>`) })))
    .sort((a, b) => a.t - b.t);
  $("#projTimeline").innerHTML = items.length ? items.map((i) => i.html).join("")
    : `<p class="hint">Nothing here yet. Talk to ${esc(NAME())} about the project, or give Claude Code its first task.</p>`;
  $("#projTimeline").scrollTop = $("#projTimeline").scrollHeight;
  if (d.running) proj.poll = setInterval(async () => {
    const x = await api(`/api/projects/${encodeURIComponent(d.name)}`);
    if (!x.running && proj.name === d.name) openProject(d.name);
  }, 5000);
}
async function showProjectFile(name, path) {
  const f = await api(`/api/projects/${encodeURIComponent(name)}/file?path=${encodeURIComponent(path)}`);
  const box = $("#projFile"); box.hidden = false;
  box.innerHTML = `<div class="row"><b class="grow">${esc(path)}</b><button class="x" title="Close">✕</button></div>` +
    (f.error ? `<p class="hint">⚠️ ${esc(f.error)}</p>` : f.binary ? `<p class="hint">Not a text file; open it in Obsidian or the file manager.</p>`
      : /\.md$/i.test(path) ? `<div class="md">${md(f.text)}</div>` : `<pre>${esc(f.text)}</pre>`);
  box.querySelector(".x").onclick = () => (box.hidden = true);
}
$("#projBack").onclick = () => { proj.name = null; loadProjects(); };
$("#projNew").onclick = async () => {
  const name = prompt("Project name (also its folder in Obsidian Projects/):"); if (!name) return;
  const goal = prompt("What is it about? (one or two sentences, goes into Overview.md; optional)") || "";
  const r = await api("/api/projects", { method: "POST", body: JSON.stringify({ name, goal }) });
  if (r.error) return alert(r.error);
  openProject(r.name);
};
const projTo = () => document.querySelector('input[name="projTo"]:checked').value;
document.querySelectorAll('input[name="projTo"]').forEach((r) => (r.onchange = () => {
  const c = projTo() === "claude";
  $("#projInput").placeholder = c ? "Task or answer for Claude Code…" : `Write to ${NAME()} about this project…`;
  $("#projToHint").textContent = c ? "Goes through the privacy filter; you see exactly what leaves before it's sent. Continues the project's session."
    : "Knows the project and can hand work to Claude Code.";
  $("#projPreview").hidden = true; delete $("#projSend").dataset.preview; $("#projSend").textContent = "Send";
}));
$("#projInput").addEventListener("input", () => { $("#projPreview").hidden = true; delete $("#projSend").dataset.preview; $("#projSend").textContent = "Send"; });
$("#projInput").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#projComposer").requestSubmit(); } });
$("#projComposer").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("#projInput").value.trim(), name = proj.name, btn = $("#projSend");
  if (!text || !name || btn.disabled) return;
  if (projTo() === "claude") {
    if (!btn.dataset.preview) {  // first: show exactly what leaves the PC
      const pv = await api(`/api/projects/${encodeURIComponent(name)}/claude`, { method: "POST", body: JSON.stringify({ text }) });
      if (pv.error) { $("#projInfo").textContent = "⚠️ " + pv.error; return; }
      $("#projPreview").hidden = false;
      $("#projPreview").innerHTML = `<div class="hint" style="padding:0">Exactly this goes to Claude Code${pv.findings.length ? ` (privacy filter replaced: ${esc(pv.findings.join(", "))})` : ""}:</div><div>${esc(pv.preview)}</div>`;
      btn.dataset.preview = pv.preview; btn.textContent = "Send to Claude Code"; return;
    }
    const r = await api(`/api/projects/${encodeURIComponent(name)}/claude`, { method: "POST", body: JSON.stringify({ text, confirm: true, preview: btn.dataset.preview }) });
    $("#projInfo").textContent = r.error ? "⚠️ " + r.error : r.resumed ? "Claude Code continues the session…" : "Claude Code started…";
    if (!r.error) { $("#projInput").value = ""; $("#projPreview").hidden = true; delete btn.dataset.preview; btn.textContent = "Send"; }
    return openProject(name);
  }
  // to the assistant: the project's own conversation (it knows the project; anything that changes something still asks first)
  btn.disabled = true; $("#projInfo").textContent = `${NAME()} is thinking…`;
  const { id } = await api(`/api/projects/${encodeURIComponent(name)}/chat`, { method: "POST", body: "{}" });
  const tl = $("#projTimeline");
  tl.insertAdjacentHTML("beforeend", `<div class="msg user"><span class="who">You → ${esc(NAME())}</span>${esc(text)}</div><div class="msg assistant typing"><span class="who">${esc(NAME())}</span><span class="b"></span></div>`);
  $("#projInput").value = ""; tl.scrollTop = tl.scrollHeight;
  const bubble = tl.lastElementChild.querySelector(".b"); let acc = "";
  try {
    const r = await fetch(`/api/conversations/${id}/messages`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }) });
    const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = chunk.match(/^event: (.*)$/m)?.[1], data = JSON.parse(chunk.match(/^data: (.*)$/m)?.[1] || "{}");
        if (ev === "token") { acc += data; bubble.innerHTML = md(stripMood(acc)); tl.scrollTop = tl.scrollHeight; }
        if (ev === "approval") { $("#projInfo").innerHTML = `Needs your OK: <a href="#" id="projToApprovals">open Approvals →</a>`; updateBadge();
          $("#projToApprovals").onclick = (x) => { x.preventDefault(); show("approvals"); }; }
        if (ev === "error") bubble.innerHTML = `⚠️ ${esc(data.message)}`;
      }
    }
  } finally {
    btn.disabled = false;
    if (!$("#projInfo").innerHTML.includes("Approvals")) $("#projInfo").textContent = "";
    openProject(name);
  }
};

// ---------- ToDo (ToDo.md in the vault) ----------
async function loadTodo() {
  const { items } = await api("/api/todo");
  $("#todoList").innerHTML = items.length ? items.map((t, i) => `<label class="card todo-item"><input type="checkbox" data-i="${i}">
      <span>${esc(t)}</span></label>`).join("") : `<p class="hint">Nothing on your ToDo. 🎉</p>`;
  $("#todoList").querySelectorAll("input[type=checkbox]").forEach((c) => (c.onchange = async () => {
    c.closest(".todo-item").classList.add("done");
    await api("/api/todo/done", { method: "POST", body: JSON.stringify({ item: items[Number(c.dataset.i)] }) });
    setTimeout(() => { loadTodo(); updateBadge(); }, 400);
  }));
}
$("#todoForm").onsubmit = async (e) => {
  e.preventDefault();
  const t = $("#todoInput").value.trim(); if (!t) return;
  $("#todoInput").value = "";
  await api("/api/todo/add", { method: "POST", body: JSON.stringify({ items: [t] }) });
  loadTodo(); updateBadge();
};

// ---------- connectors / skills / reminders ----------
async function loadConnectors() {
  const list = await api("/api/connectors");
  $("#connectorList").innerHTML = list.map((c) => `<div class="card"><div class="row">
      <div class="grow"><b>${esc(c.id)}</b><div class="hint" style="padding:0">${esc(c.description)}</div>
      <div style="margin-top:6px">${c.tools.map((t) => `<code>${t}</code>${c.approval_tools.includes(t) ? ' <span class="pill warn">approval</span>' : ""}`).join(" ")}</div></div>
      <button class="switch ${c.enabled ? "on" : ""}" data-conn="${c.id}" aria-label="toggle"></button></div></div>`).join("");
  document.querySelectorAll("[data-conn]").forEach((b) => (b.onclick = async () => {
    await api("/api/connectors", { method: "POST", body: JSON.stringify({ id: b.dataset.conn, enabled: !b.classList.contains("on") }) });
    loadConnectors();
  }));
}
async function loadPhone() {
  const d = await api("/api/devices");
  $("#phoneMode").textContent = d.mode === "visible" ? "📱 visible (your paired phone can reach it)" : "🔒 private (not reachable from outside this PC)";
  $("#phoneUrl").textContent = d.host ? `https://${d.host}` : "(Tailscale is not running on this PC)";
  $("#phoneQr").src = d.host ? "/api/devices/qr?" + Date.now() : "";
  $("#deviceList").innerHTML = d.devices.length ? d.devices.map((x) => `<div class="ask-row"><span>📱 ${esc(x.name)} · paired ${new Date(x.created * 1000).toLocaleDateString()}
      · last seen ${new Date(x.last_seen * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}</span>
      <button data-revoke="${x.id}">Remove</button></div>`).join("") : `<p class="hint" style="padding:0">No phone paired yet.</p>`;
  document.querySelectorAll("[data-revoke]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Remove this phone? It loses access right away.")) return;
    await api(`/api/devices/${b.dataset.revoke}/revoke`, { method: "POST" }); loadPhone();
  }));
}
for (const m of ["private", "visible"]) $("#mode" + m[0].toUpperCase() + m.slice(1)).onclick = async () => {
  $("#modeInfo").textContent = "Switching…";
  const r = await api(`/api/phone/${m}`, { method: "POST" });
  $("#modeInfo").innerHTML = md(r.text || r.error || ""); loadPhone();
};
let pairWatch;
$("#pairBtn").onclick = async () => {
  const r = await api("/api/devices/code", { method: "POST" });
  $("#pairCode").innerHTML = r.error ? `⚠️ ${esc(r.error)}` : `<div class="code">${r.code}</div><div class="hint" style="padding:0">Scan the QR code with the Amadeus app (or type the code) · valid ${r.minutes} minutes, once</div>`;
  if (r.error) return;
  $("#phoneQr").src = `/api/devices/qr?code=${r.code}&${Date.now()}`;  // the QR now carries the code: scan and done
  // once the phone is paired (or the code expires) the code and the QR with it disappear from the screen
  const before = (await api("/api/devices")).devices.length, until = Date.now() + r.minutes * 60000;
  clearInterval(pairWatch);
  pairWatch = setInterval(async () => {
    const d = await api("/api/devices").catch(() => null);
    const paired = d && d.devices.length > before;
    if (!paired && Date.now() < until) return;
    clearInterval(pairWatch);
    $("#pairCode").innerHTML = paired ? `<div class="hint" style="padding:0">✓ Phone paired.</div>` : `<div class="hint" style="padding:0">The code expired. Make a new one if you need it.</div>`;
    loadPhone();  // the QR goes back to the plain address, the new phone shows in the list
  }, 2000);
};
async function loadPlaybooks() {
  const list = await api("/api/playbooks");
  $("#playbookList").innerHTML = list.map((p) => `<div class="card"><div class="row"><div class="grow"><b>${esc(p.title)}</b>
      <div class="hint" style="padding:0">${esc(p.about)}</div>
      <div class="sk-trig">Say: ${p.triggers.map((t) => `<code>${esc(t)}</code>`).join(" ")}</div></div>
      <button class="primary" data-run="${esc(p.title)}">▶ Run</button></div></div>`).join("");
  document.querySelectorAll("[data-run]").forEach((b) => (b.onclick = () => {
    show("chat"); $("#input").value = "Run playbook: " + b.dataset.run; $("#composer").requestSubmit();
  }));
}
async function loadClips() {
  const c = await api("/api/voice/clips");
  const btn = (n) => `<button class="clip" data-clip="${esc(n)}">▶ ${esc(n.replace(/^ringtone_/, "").replace(/_/g, " "))}</button>`;
  $("#clipList").innerHTML = `<div class="hint" style="padding:0">${c.lines.length} voice lines</div><div class="clips">${c.lines.map(btn).join("")}</div>
    <div class="hint" style="padding:8px 0 0">${c.ringtones.length} ringtones</div><div class="clips">${c.ringtones.map(btn).join("")}</div>`;
  let playing;
  document.querySelectorAll("[data-clip]").forEach((b) => (b.onclick = () => {
    if (playing) playing.pause();
    playing = new Audio(`/voice-clip/${b.dataset.clip}.ogg`); playing.play();
  }));
}
async function loadSkills() {
  loadClips();
  const list = await api("/api/skills");
  const badge = (s) => s.mode === "background" ? `<span class="sk-badge bg">Always on · background</span>`
    : s.mode === "auto" ? `<span class="sk-badge ${s.active ? "auto" : ""}">${s.active ? "Auto" : "Off"}</span>` : `<span class="sk-badge">Manual</span>`;
  $("#skillList").innerHTML = list.length ? list.map((s) => `<div class="card"><div class="row">
      <div class="grow"><b>${esc(s.name)}</b> ${badge(s)}<div class="hint" style="padding:0">${esc(s.description)}</div>
      ${s.triggers && s.triggers.length ? `<div class="sk-trig">Loads when you say: ${s.triggers.slice(0, 6).map((t) => `<code>${esc(t)}</code>`).join(" ")}${s.triggers.length > 6 ? " …" : ""}</div>` : ""}</div>
      ${s.mode === "background" ? "" : `<button class="switch ${s.active ? "on" : ""}" data-skill="${esc(s.name)}" aria-label="toggle"></button>`}</div></div>`).join("") : "<p class='hint'>No skills yet.</p>";
  document.querySelectorAll("[data-skill]").forEach((b) => (b.onclick = async () => {
    await api("/api/skills", { method: "POST", body: JSON.stringify({ name: b.dataset.skill, active: !b.classList.contains("on") }) });
    loadSkills();
  }));
}
async function loadReminders() {
  const list = await api("/api/reminders");
  $("#reminderList").innerHTML = list.length ? list.map((r) => `<div class="card" data-id="${esc(r.id)}" data-text="${esc(r.text)}"><b>${esc(r.text)}</b>
      <div class="hint" style="padding:0">${esc(r.schedule)} · next ${r.next_run ? new Date(r.next_run * 1000).toLocaleString() : "—"} · id ${r.id}</div></div>`).join("")
    : "<p class='hint'>No reminders.</p>";
}

// ---------- mail (Thunderbird holds the accounts; this page only reads) ----------
const mail = { list: [], open: null, accountsLoaded: false, folders: [] };
async function loadFolders() {
  mail.folders = await mailApi(`/api/mail/folders?account=${encodeURIComponent($("#mailAccount").value)}`);
  const cur = $("#mailFolder").value, names = {};
  [...$("#mailAccount").options].forEach((o) => (names[o.value] = o.textContent));
  const many = !$("#mailAccount").value && $("#mailAccount").options.length > 2;
  $("#mailFolder").innerHTML = `<option value="">Inbox</option><option value="@unread">Unread (all folders)</option>` +
    mail.folders.map((f) => `<option value="${esc(f.id)}">${many ? esc(names[f.accountId] || "") + " › " : ""}${esc(f.path.replace(/^\//, ""))}${f.unread ? ` (${f.unread})` : ""}</option>`).join("");
  $("#mailFolder").value = [...$("#mailFolder").options].some((o) => o.value === cur) ? cur : "";
}
const mailApi = async (path) => {
  const r = await fetch(path); const d = await r.json();
  if (!r.ok) throw Object.assign(new Error(d.error || "mail error"), { offline: d.offline });
  return d;
};
async function loadMail() {
  const off = $("#mailOffline");
  try {
    if (!mail.accountsLoaded) {
      const st = await mailApi("/api/mail/status");
      if (!st.connected) throw Object.assign(new Error(st.error || ""), { offline: true });
      $("#mailAccount").innerHTML = `<option value="">All accounts</option>` +
        st.accounts.map((a) => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("");
      mail.accountsLoaded = true;
    }
    await loadFolders();
    if (mail.wantFolder) { if ([...$("#mailFolder").options].some((o) => o.value === mail.wantFolder)) $("#mailFolder").value = mail.wantFolder; mail.wantFolder = null; }
    const q = $("#mailSearch").value.trim(), acc = encodeURIComponent($("#mailAccount").value), fo = $("#mailFolder").value;
    mail.list = await mailApi(q ? `/api/mail/search?q=${encodeURIComponent(q)}&account=${acc}`
      : fo === "@unread" ? `/api/mail/unread?account=${acc}`
      : `/api/mail/recent?days=${fo ? 90 : 14}&account=${acc}&folder=${encodeURIComponent(fo)}`);
    off.hidden = true;
    renderMailList();
  } catch (e) {
    off.hidden = false;
    off.innerHTML = e.offline ? `<b>Thunderbird isn't connected.</b> Open Thunderbird (with the Amadeus Bridge add-on installed) and this page fills itself.`
      : `⚠️ ${esc(e.message)}`;
    mail.accountsLoaded = false;
  }
}
function renderMailList() {
  $("#mailList").innerHTML = mail.list.map((m) => `<li data-id="${m.id}" class="${m.read ? "" : "unread"} ${mail.open === m.id ? "active" : ""}">
      <div class="f"><span>${esc(m.from)}${$("#mailFolder").value === "@unread" && m.folder ? ` · ${esc(m.folder.replace(/^\//, ""))}` : ""}</span><span>${new Date(m.date).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}</span></div>
      <div class="s">${esc(m.subject || "(no subject)")}</div></li>`).join("") || `<li class="hint">No mail here.</li>`;
}
async function openMail(id) {
  mail.open = id; renderMailList();
  $(".mail-wrap").classList.add("reading");
  $("#mailReader").innerHTML = `<p class="hint">Loading…</p>`;
  try {
    const m = await mailApi(`/api/mail/message/${id}`);
    $("#mailReader").innerHTML = `<button class="icon back" onclick="document.querySelector('.mail-wrap').classList.remove('reading')">← Back</button>
      <h3>${esc(m.subject || "(no subject)")}</h3>
      <div class="meta">From ${esc(m.from)}<br>To ${esc((m.to || []).join(", "))}${m.cc && m.cc.length ? "<br>Cc " + esc(m.cc.join(", ")) : ""}<br>${new Date(m.date).toLocaleString()}
        ${m.attachments && m.attachments.length ? "<br>📎 " + m.attachments.map((a) => esc(a.name)).join(", ") : ""}</div>
      <div class="acts"><button id="mailSum">✨ Summarize</button><button id="mailReply" class="primary">✍️ Reply with ${esc(NAME())}</button>
        <button id="mailUnread">Mark unread</button>
        <select id="mailMove"><option value="">Move to…</option>${mail.folders.filter((f) => f.accountId === m.accountId && f.id !== m.folderId)
          .map((f) => `<option value="${esc(f.id)}">${esc(f.path.replace(/^\//, ""))}</option>`).join("")}</select></div>
      <div class="body">${esc(m.body)}${m.truncated ? "\n[…]" : ""}</div>`;
    if (!m.read) {  // opening a mail marks it read, like any mail app
      fetch("/api/mail/markread", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ids: [id], read: true }) });
      const li = mail.list.find((x) => x.id === id); if (li) { li.read = true; renderMailList(); }
    }
    $("#mailUnread").onclick = async () => {
      await fetch("/api/mail/markread", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ids: [id], read: false }) });
      const li = mail.list.find((x) => x.id === id); if (li) { li.read = false; renderMailList(); }
    };
    $("#mailMove").onchange = async (e) => {
      if (!e.target.value) return;
      await fetch("/api/mail/move", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ids: [id], folderId: e.target.value }) });
      mail.list = mail.list.filter((x) => x.id !== id); mail.open = null; renderMailList();
      $("#mailReader").innerHTML = `<p class="hint">Moved.</p>`;
    };
    $("#mailSum").onclick = () => askInChat(`Summarize email [${id}] ("${m.subject}") in a few sentences and tell me if I need to do anything.`, true);
    $("#mailReply").onclick = () => askInChat(`Draft a reply to email [${id}] ("${m.subject}") from ${m.from}. My points: `, false);
  } catch (e) { $("#mailReader").innerHTML = `<p class="hint">⚠️ ${esc(e.message)}</p>`; }
}
// puts the request into today's chat (sent right away, or left in the box for you to finish)
async function askInChat(text, send) {
  await openConv(await todayChat()); show("chat");
  $("#input").value = text; $("#input").focus();
  if (send) $("#composer").requestSubmit();
}
// "Open in Claude Code": a terminal on the PC with Claude Code in this project's folder (on its last session)
$("#projTerm").onclick = async () => {
  const r = await api(`/api/projects/${encodeURIComponent(proj.name)}/terminal`, { method: "POST", body: "{}" });
  $("#projInfo").textContent = r.error ? "Couldn't open it: " + r.error : r.resumed ? "Opened Claude Code on this project's last session." : "Opened Claude Code in this project's folder.";
};
$("#mailList").onclick = (e) => { const li = e.target.closest("li[data-id]"); if (li) openMail(Number(li.dataset.id)); };
$("#mailAccount").onchange = () => { $("#mailFolder").value = ""; loadMail(); };
$("#mailFolder").onchange = loadMail;
$("#mailRefresh").onclick = loadMail;
let mailT; $("#mailSearch").oninput = () => { clearTimeout(mailT); mailT = setTimeout(loadMail, 400); };

// ---------- memory (profile + learned rules) ----------
async function loadMemory() {
  const p = await api("/api/profile");
  $("#profileText").value = p.profile;
  $("#profileInfo").textContent = `${p.pending} new observation(s) waiting to be folded in` + (p.updated ? ` · last update ${p.updated.replace("T", " ")}` : "");
  $("#mailVip").value = (p.vip || []).join("\n");
  const ask = p.asking || [];
  $("#askList").innerHTML = ask.length ? ask.map((a) => `<div class="ask-row"><span>“${esc(a.say)}” → ${esc(a.means)}${a.n > 1 ? ` <span class="hint" style="padding:0">(×${a.n})</span>` : ""}</span>
      <button class="x" data-forget="${esc(a.say)}" title="Forget this">✕</button></div>`).join("") : `<p class="hint" style="padding:0">Nothing yet. This is learned as you use it.</p>`;
  document.querySelectorAll("[data-forget]").forEach((b) => (b.onclick = async () => {
    await api("/api/asking/remove", { method: "POST", body: JSON.stringify({ say: b.dataset.forget }) }); loadMemory();
  }));
  const rules = Object.entries(p.rules || {});
  $("#mailRules").innerHTML = rules.length ? rules.map(([a, f]) => `<div>${esc(a)} → <b>${esc(f)}</b></div>`).join("") : `<p class="hint" style="padding:0">None yet.</p>`;
  $("#memoryList").innerHTML = `<p class="hint" style="padding:0">Loading…</p>`;
  const m = await api("/api/memory");
  $("#memoryList").innerHTML = m.error ? `⚠️ ${esc(m.error)}` : md(m.text.split("\n\n").slice(-1)[0]);
}
$("#vipSave").onclick = async () => {
  const r = await api("/api/mail/vip", { method: "POST", body: JSON.stringify({ vip: $("#mailVip").value.split("\n") }) });
  $("#mailVip").value = r.vip.join("\n"); $("#vipInfo").textContent = "Saved.";
};
$("#profileSave").onclick = async () => {
  await api("/api/profile", { method: "POST", body: JSON.stringify({ profile: $("#profileText").value }) });
  $("#profileInfo").textContent = "Saved.";
};
$("#profileMerge").onclick = async () => {
  $("#profileInfo").textContent = "Updating your profile…";
  const r = await api("/api/profile/merge", { method: "POST" });
  $("#profileText").value = r.profile;
  $("#profileInfo").textContent = r.merged ? "Updated." : "Nothing new to add.";
};

// ---------- calendar (shared with Amadeus) ----------
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const cal = { month: new Date(new Date().getFullYear(), new Date().getMonth(), 1), sel: ymd(new Date()), occ: [], editing: null };
const hm = (iso) => iso.length > 10 ? iso.slice(11, 16) : "";

async function loadCalendar() {
  const first = cal.month, start = addDays(first, -((first.getDay() + 6) % 7)), end = addDays(start, 42);
  $("#calTitle").textContent = first.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  cal.occ = await api(`/api/calendar?from=${ymd(start)}&to=${ymd(end)}`);
  const today = ymd(new Date());
  let html = "";
  for (let i = 0; i < 42; i++) {
    const d = addDays(start, i), key = ymd(d);
    const items = cal.occ.filter((o) => o.occ_start.slice(0, 10) <= key && (o.all_day ? o.occ_end.slice(0, 10) > key : o.occ_start.slice(0, 10) === key));
    const chips = items.slice(0, 3).map((o) => `<div class="chip ${o.created_by === "amadeus" ? "amadeus" : ""}" data-id="${o.id}" data-start="${o.occ_start}"
        draggable="${o.repeat ? "false" : "true"}" title="${esc(o.title)}">${hm(o.occ_start) ? hm(o.occ_start) + " " : ""}${esc(o.title)}</div>`).join("");
    html += `<div class="cal-cell ${d.getMonth() !== first.getMonth() ? "other" : ""} ${key === today ? "today" : ""} ${key === cal.sel ? "sel" : ""}" data-day="${key}">
      <span class="n">${d.getDate()}</span>${chips}${items.length > 3 ? `<span class="more">+${items.length - 3} more</span>` : ""}</div>`;
  }
  $("#calGrid").innerHTML = html;
  renderDay();
  if (cal.flash) { const c = document.querySelector(`.cal-day .agenda[data-id="${cal.flash}"]`); if (c) { c.classList.add("flash"); setTimeout(() => c.classList.remove("flash"), 2000); } cal.flash = null; }
}

function renderDay() {
  const d = new Date(cal.sel + "T00:00");
  $("#calDayTitle").textContent = d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  const items = cal.occ.filter((o) => o.occ_start.slice(0, 10) <= cal.sel && (o.all_day ? o.occ_end.slice(0, 10) > cal.sel : o.occ_start.slice(0, 10) === cal.sel));
  $("#calDayList").innerHTML = items.map((o) => `<div class="agenda ${o.created_by === "amadeus" ? "amadeus" : ""}" data-id="${o.id}">
      <div class="t">${esc(o.title)}${o.repeat ? " ↻" : ""}</div>
      <div class="s">${o.all_day ? "All day" : `${hm(o.occ_start)} – ${hm(o.occ_end)}`}${o.location ? " · " + esc(o.location) : ""}${o.created_by === "amadeus" ? ` · added by ${esc(NAME())}` : ""}</div>
      ${o.notes ? `<div class="s">${esc(o.notes)}</div>` : ""}</div>`).join("") || `<p class="hint" style="padding:0">Nothing planned.</p>`;
}

function openEditor(o, day) {
  const f = $("#calForm"); f.reset(); cal.editing = o ? o.id : null;
  $("#calFormTitle").textContent = o ? "Edit event" : "New event";
  $("#calDelete").hidden = !o; $("#calFormMsg").textContent = o && o.repeat ? "This repeats: changes apply to the whole series." : "";
  if (o) {
    const ev = cal.occ.find((x) => x.id === o.id) || o;
    f.title.value = ev.title; f.all_day.checked = !!ev.all_day; f.date.value = ev.start.slice(0, 10);
    f.from.value = hm(ev.start) || "09:00"; f.to.value = hm(ev.end) || "10:00";
    f.location.value = ev.location || ""; f.notes.value = ev.notes || ""; f.repeat.value = ev.repeat || "";
    f.repeat_until.value = ev.repeat_until || ""; f.alert.value = String(ev.alert);
  } else f.date.value = day || cal.sel;
  toggleTimes(); $("#calDialog").showModal(); f.title.focus();
}
const toggleTimes = () => document.querySelectorAll("#calForm .time").forEach((l) => (l.hidden = $("#calForm").all_day.checked));

async function saveEvent(e) {
  e.preventDefault();
  const f = $("#calForm"), allDay = f.all_day.checked;
  const body = { title: f.title.value, all_day: allDay, location: f.location.value, notes: f.notes.value, repeat: f.repeat.value,
    repeat_until: f.repeat.value ? f.repeat_until.value : "", alert: Number(f.alert.value),
    start: allDay ? f.date.value : `${f.date.value}T${f.from.value || "09:00"}`,
    end: allDay ? "" : `${f.to.value > f.from.value ? f.date.value : ymd(addDays(new Date(f.date.value + "T00:00"), 1))}T${f.to.value || "10:00"}` };
  const r = await api(cal.editing ? `/api/calendar/${cal.editing}` : "/api/calendar", { method: cal.editing ? "PATCH" : "POST", body: JSON.stringify(body) });
  if (r.error) { $("#calFormMsg").textContent = "⚠️ " + r.error; return; }
  $("#calDialog").close(); cal.sel = body.start.slice(0, 10); loadCalendar();
}

async function moveEvent(id, fromStart, toDay) {
  const o = cal.occ.find((x) => x.id === id); if (!o) return;
  const shift = (iso) => toDay + iso.slice(10);
  const days = (new Date(toDay + "T00:00") - new Date(fromStart.slice(0, 10) + "T00:00")) / 864e5;
  const endDay = ymd(addDays(new Date(o.end.slice(0, 10) + "T00:00"), days));
  await api(`/api/calendar/${id}`, { method: "PATCH", body: JSON.stringify({ start: shift(o.start), end: endDay + o.end.slice(10) }) });
  cal.sel = toDay; loadCalendar();
}

$("#calPrev").onclick = () => { cal.month = new Date(cal.month.getFullYear(), cal.month.getMonth() - 1, 1); loadCalendar(); };
$("#calNext").onclick = () => { cal.month = new Date(cal.month.getFullYear(), cal.month.getMonth() + 1, 1); loadCalendar(); };
$("#calToday").onclick = () => { const t = new Date(); cal.month = new Date(t.getFullYear(), t.getMonth(), 1); cal.sel = ymd(t); loadCalendar(); };
$("#calNew").onclick = () => openEditor(null, cal.sel);
$("#calDayAdd").onclick = () => openEditor(null, cal.sel);
$("#calCancel").onclick = () => $("#calDialog").close();
$("#calForm").onsubmit = saveEvent;
$("#calForm").all_day.onchange = toggleTimes;
$("#calDelete").onclick = async () => {
  const o = cal.occ.find((x) => x.id === cal.editing);
  if (!confirm(`Delete "${o ? o.title : "this event"}"${o && o.repeat ? " (the whole series)" : ""}?`)) return;
  await api(`/api/calendar/${cal.editing}`, { method: "DELETE" }); $("#calDialog").close(); loadCalendar();
};
$("#calGrid").onclick = (e) => {
  const chip = e.target.closest(".chip"); if (chip) return openEditor({ id: chip.dataset.id });
  const cell = e.target.closest(".cal-cell"); if (!cell) return;
  cal.sel = cell.dataset.day;
  document.querySelectorAll(".cal-cell.sel").forEach((c) => c.classList.remove("sel")); cell.classList.add("sel"); renderDay();
};
$("#calGrid").ondblclick = (e) => { const cell = e.target.closest(".cal-cell"); if (cell && !e.target.closest(".chip")) openEditor(null, cell.dataset.day); };
$("#calDayList").onclick = (e) => { const a = e.target.closest(".agenda"); if (a) openEditor({ id: a.dataset.id }); };
$("#calGrid").addEventListener("dragstart", (e) => { const c = e.target.closest(".chip"); if (c) e.dataTransfer.setData("text/plain", JSON.stringify({ id: c.dataset.id, start: c.dataset.start })); });
$("#calGrid").addEventListener("dragover", (e) => { const cell = e.target.closest(".cal-cell"); if (cell) { e.preventDefault(); cell.classList.add("drop"); } });
$("#calGrid").addEventListener("dragleave", (e) => { const cell = e.target.closest(".cal-cell"); if (cell) cell.classList.remove("drop"); });
$("#calGrid").addEventListener("drop", (e) => {
  e.preventDefault(); const cell = e.target.closest(".cal-cell"); if (!cell) return;
  const d = JSON.parse(e.dataTransfer.getData("text/plain") || "{}"); if (d.id) moveEvent(d.id, d.start, cell.dataset.day);
});
setInterval(() => { if ($("#view-calendar").classList.contains("active") && !$("#calDialog").open) loadCalendar(); }, 30000);

// ---------- voice: 🔊 toggle and push-to-talk mic ----------
function initVoice() {
  if (!window.Voice) return;
  const t = $("#voiceToggle"), mic = $("#micBtn");
  const paint = () => { t.innerHTML = `<span class="dot"></span>${Voice.on ? "Voice on" : "Voice off"}`; t.classList.toggle("on", Voice.on); t.title = Voice.on ? "Voice lines are on (click to mute)" : "Muted (click for the short voice lines on actions)"; };
  t.onclick = () => Voice.toggle(); addEventListener("voicechange", paint); paint();
  // click once to start recording, click again to send
  mic.addEventListener("click", (e) => {
    e.preventDefault();
    if (Voice.recording) { Voice.release(); mic.classList.remove("rec"); mic.title = "Click to talk"; }
    else { Voice.listen(); mic.classList.add("rec"); mic.title = "Recording… click again to send"; }
  });
  Voice.onBusy = (b) => { mic.classList.toggle("busy", b); $("#input").placeholder = b ? "Listening done, transcribing…" : `Ask ${NAME()}…`; };
  Voice.onHint = (msg) => { $("#input").placeholder = msg; setTimeout(() => ($("#input").placeholder = `Ask ${NAME()}…`), 4000); };
  Voice.onText = (text) => { show("chat"); $("#input").value = text; state.spoken = true; $("#composer").requestSubmit(); };
  // the wake word while the dashboard is open: the window stays here (popup.py); it listens and answers in the chat
  window.amadeusWake = (d) => {
    const listening = d.stage === "listening";
    document.body.classList.toggle("listening", listening); mic.classList.toggle("rec", listening);
    if (listening) { show("chat"); $("#input").placeholder = "Listening… (talk normally, I'll wait until you're done)"; return; }
    $("#input").placeholder = `Ask ${NAME()}…`;
    if (d.stage === "text" && d.text) Voice.onText(d.text);
    else if (d.stage === "cancel" && !d.quiet) Voice.onHint(`I didn't catch a request. Say "${NAME()}" and what you need.`);
  };
}

// ---------- start ----------
initTheme(); tickClock(); setInterval(tickClock, 15000);
(async () => {
  const m = await api("/api/models");
  state.models = m.models; state.defaultModel = m.default;
  $("#modelSelect").innerHTML = m.models.map((x) => `<option ${x === m.default ? "selected" : ""}>${esc(x)}</option>`).join("");
  $("#modelSelect").onchange = () => state.cid && api(`/api/conversations/${state.cid}`, { method: "PATCH", body: JSON.stringify({ model: $("#modelSelect").value }) });
  loadConversations(); updateBadge(); setInterval(updateBadge, 8000); initAvatar(); initVoice();
  loadRail(); setInterval(loadRail, 30000);
  // deep links from the desktop call: #approvals, #chat=<id>
  const h = location.hash.slice(1);
  if (["approvals", "reminders", "calendar", "mail", "memory", "todo", "projects"].includes(h)) show(h);
  else if (h === "mail=unread") { mail.wantFolder = "@unread"; show("mail"); }
  else if (/^mail=\d+$/.test(h)) { show("mail"); openMail(Number(h.slice(5))); }  // e.g. a reminder about one mail
  else if (h.startsWith("chat=")) openConv(h.slice(5));
  else if (h === "day") { openConv(await todayChat()); showDay(); }
  if (!h.startsWith("chat=") && h !== "day") openConv(await todayChat());  // the chat page always shows today's chat
  if (h) history.replaceState(null, "", "/");
})();
