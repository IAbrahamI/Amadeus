// The workspace of a project (Projects → a project → Open workspace): its files on the left, the editor in the middle, the chat with
// Amadeus and Claude Code on the right. The editor works like a code editor: files open as tabs, and a tab dragged to the left, right,
// top or bottom of an editor splits it there. Markdown shows its source next to how it reads. While Claude Code works you see each
// step and the file it's on, and the open files follow what it changes. It's another layout of the project page (hud-views.js), so
// the chat, the privacy preview and the approvals are the very same.
const ws = { follow: true, poll: null, files: [], open: {}, last: 0, live: [], wasRunning: false,
  bufs: {},          // path -> { text, seen, dirty, binary, error, conflict, gone }: one per file, shared by every tab that shows it
  layout: null,      // { group } or { dir: "row" | "col", a, b }: how the editor is split
  groups: {},        // id -> { tabs: [path], active: path, preview: true }
  focus: null, next: 1, project: "" };
const wsApi = (rest) => `/api/projects/${encodeURIComponent(proj.d.name)}${rest}`;
const wsIcon = (open) => (open ? "▾" : "▸");
const isMd = (path) => /\.(md|markdown)$/i.test(path || "");
const dirtyAny = () => Object.values(ws.bufs).some((b) => b.dirty);
const store = { get(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window: no memory of the layout */ } } };

function closeWorkspace() {
  if (proj.ws && dirtyAny() && !confirm("You have unsaved changes. Leave the workspace anyway?")) return false;
  clearInterval(ws.poll); ws.poll = null;
  proj.ws = false; app.classList.remove("ws-on");
  place();  // the core goes back to its corner of the stage
  Object.assign(ws, { files: [], last: 0, live: [], bufs: {}, layout: null, groups: {}, focus: null, project: "" });
  return true;
}

// ---------- the layout: groups of tabs, split in rows and columns ----------
function newGroup(tabs = [], active = null) {
  const id = "g" + ws.next++;
  ws.groups[id] = { tabs, active: active || tabs[0] || null, preview: true };
  return id;
}
function findNode(node, id, parent = null, side = null) {
  if (!node) return null;
  if (node.group === id) return { node, parent, side };
  return findNode(node.a, id, node, "a") || findNode(node.b, id, node, "b");
}
function replaceNode(oldNode, parent, side, fresh) { if (!parent) ws.layout = fresh; else parent[side] = fresh; }
function removeGroup(id) {
  const at = findNode(ws.layout, id);
  delete ws.groups[id];
  if (!at) return;
  if (!at.parent) { ws.layout = null; return; }
  const sibling = at.parent[at.side === "a" ? "b" : "a"];
  const up = findParent(ws.layout, at.parent);
  replaceNode(at.parent, up && up.parent, up && up.side, sibling);
  if (ws.focus === id) ws.focus = firstGroup(ws.layout);
}
function findParent(node, target, parent = null, side = null) {
  if (!node) return null;
  if (node === target) return { parent, side };
  return node.group ? null : findParent(node.a, target, node, "a") || findParent(node.b, target, node, "b");
}
function firstGroup(node) { return !node ? null : node.group || firstGroup(node.a); }
function allGroups(node, out = []) { if (node) { if (node.group) out.push(node.group); else { allGroups(node.a, out); allGroups(node.b, out); } } return out; }

// put a file in a group: as a tab in the middle, or in a new group to one side ("left" | "right" | "top" | "bottom")
function placeTab(path, target, where = "center", from = null) {
  if (!path) return;
  if (!ws.layout) { ws.layout = { group: newGroup() }; target = ws.layout.group; }
  target = target && ws.groups[target] ? target : ws.focus || firstGroup(ws.layout);
  if (from && ws.groups[from]) {  // moved, not copied: it leaves the group it came from
    const g = ws.groups[from];
    g.tabs = g.tabs.filter((t) => t !== path);
    if (g.active === path) g.active = g.tabs[g.tabs.length - 1] || null;
  }
  let into = target;
  if (where !== "center") {
    const at = findNode(ws.layout, target);
    into = newGroup();
    const fresh = { group: into }, before = where === "left" || where === "top";
    replaceNode(at.node, at.parent, at.side, { dir: where === "left" || where === "right" ? "row" : "col", a: before ? fresh : at.node, b: before ? at.node : fresh });
  }
  const g = ws.groups[into];
  if (!g.tabs.includes(path)) g.tabs.push(path);
  g.active = path; ws.focus = into;
  if (from && ws.groups[from] && !ws.groups[from].tabs.length && from !== into) removeGroup(from);
  remember();
}
function closeTab(id, path) {
  const g = ws.groups[id]; if (!g) return;
  const elsewhere = Object.entries(ws.groups).some(([gid, o]) => gid !== id && o.tabs.includes(path));
  if (ws.bufs[path] && ws.bufs[path].dirty && !elsewhere && !confirm(path + " has unsaved changes. Close it anyway?")) return;
  g.tabs = g.tabs.filter((t) => t !== path);
  if (g.active === path) g.active = g.tabs[g.tabs.length - 1] || null;
  if (!elsewhere) delete ws.bufs[path];
  if (!g.tabs.length && allGroups(ws.layout).length > 1) removeGroup(id);
  remember(); drawEditors();
}
function remember() {
  if (!ws.project) return;
  const strip = (n) => n && (n.group ? { tabs: ws.groups[n.group].tabs, active: ws.groups[n.group].active, preview: ws.groups[n.group].preview } : { dir: n.dir, a: strip(n.a), b: strip(n.b) });
  store.set("amadeus-ws:" + ws.project, strip(ws.layout));
}
function restore(saved, files) {
  const exists = new Set(files.map((f) => f.path));
  const build = (n) => {
    if (!n) return null;
    if (n.tabs) { const tabs = n.tabs.filter((t) => exists.has(t)); if (!tabs.length) return null; const id = newGroup(tabs, exists.has(n.active) ? n.active : tabs[0]); ws.groups[id].preview = n.preview !== false; return { group: id }; }
    const a = build(n.a), b = build(n.b);
    return a && b ? { dir: n.dir, a, b } : a || b;
  };
  ws.layout = build(saved);
  ws.focus = firstGroup(ws.layout);
}

// ---------- the files on the left ----------
function wsTree() {
  // folders first, then files; a dot marks what changed in the last 15 seconds, a bar what the agent is on right now
  const root = {};
  for (const f of ws.files) { let at = root; const parts = f.path.split("/"); parts.slice(0, -1).forEach((p) => (at = at[p + "/"] = at[p + "/"] || {})); at[parts.at(-1)] = f; }
  const now = Date.now() / 1000, on = ws.live.length ? ws.live.at(-1).path : "", shown = ws.focus && ws.groups[ws.focus] ? ws.groups[ws.focus].active : "";
  const level = (node, prefix, depth) => Object.keys(node).sort((a, b) => (b.endsWith("/") - a.endsWith("/")) || a.localeCompare(b)).map((k) => {
    const path = prefix + k, pad = `style="padding-left:${8 + depth * 14}px"`;
    if (k.endsWith("/")) {
      const open = ws.open[path] !== false;
      return `<button class="wsrow dir" data-act="wsdir" data-d="${esc(path)}" ${pad}><i>${wsIcon(open)}</i>${esc(k.slice(0, -1))}</button>` + (open ? level(node[k], path, depth + 1) : "");
    }
    const f = node[k], fresh = now - f.modified < 15;
    return `<button class="wsrow${f.path === shown ? " on" : ""}${f.path === on ? " agent" : ""}" data-act="wsfile" data-f="${esc(f.path)}" draggable="true" ${pad} title="${esc(f.path)}"><i>${fresh ? "●" : ""}</i>${esc(k)}</button>`;
  }).join("");
  const el = $("#wsTree"); if (el) el.innerHTML = level(root, "", 0) || note("No files yet.");
}

// ---------- the editors ----------
async function load(path, force) {
  const b = ws.bufs[path];
  if (b && !force) return b;
  const f = await api(wsApi(`/file?path=${encodeURIComponent(path)}`));
  return (ws.bufs[path] = { text: f.text || "", seen: f.modified || 0, dirty: false, binary: !!f.binary, error: f.error || "", conflict: false, gone: false });
}
function tabLabel(path) { return path.split("/").pop(); }
function groupHtml(id) {
  const g = ws.groups[id], p = g.active, b = p && ws.bufs[p];
  const tabs = g.tabs.map((t) => { const tb = ws.bufs[t] || {};
    return `<div class="wstab${t === p ? " on" : ""}${tb.dirty ? " dirty" : ""}${tb.conflict ? " warn" : ""}" draggable="true" data-act="wstab" data-g="${id}" data-f="${esc(t)}" title="${esc(t)}">` +
      `<span>${esc(tabLabel(t))}</span><button data-act="wstabx" data-g="${id}" data-f="${esc(t)}" aria-label="Close ${esc(t)}">${tb.dirty ? "●" : "×"}</button></div>`; }).join("");
  const md = p && isMd(p) && g.preview;
  const state = !b ? "" : b.error ? "That didn't work: " + b.error : b.binary ? "Not a text file: open it in the file manager." : b.gone ? "This file was removed." :
    b.conflict ? (b.dirty ? "Changed on disk while you were editing." : "") : b.dirty ? "Not saved" : "";
  return `<div class="wsgroup${id === ws.focus ? " focus" : ""}" data-g="${id}"><div class="wstabs" data-g="${id}">${tabs}<span class="grow"></span>` +
    (p && isMd(p) ? `<button class="wsbtn" data-act="wspreview" data-g="${id}" title="Show how it reads">${g.preview ? "Hide preview" : "Preview"}</button>` : "") +
    (b && b.conflict && b.dirty ? `<button class="wsbtn" data-act="wsreload" data-g="${id}">Load the new version</button>` : "") +
    (p ? `<button class="wsbtn" data-act="wssplit" data-g="${id}" title="Open this file again on the right">Split</button><button class="wsbtn go" data-act="wssave" data-g="${id}" ${b && b.dirty ? "" : "disabled"}>${b && b.conflict && b.dirty ? "Save mine anyway" : "Save"}</button>` : "") +
    `</div><div class="wsstate${b && (b.conflict || b.error || b.gone) ? " warn" : ""}">${esc(state)}</div>` +
    (p ? `<div class="wsbody${md ? " md2" : ""}"><div class="wscode${p && !Highlight.lang(p) ? " plain" : ""}"><pre class="wsnums" aria-hidden="true"></pre><div class="wsarea"><pre class="wshl" aria-hidden="true"></pre>` +
      `<textarea class="wstext" data-g="${id}" spellcheck="false" autocomplete="off" autocapitalize="off" wrap="off" aria-label="${esc(p)}" ${b && (b.binary || b.error) ? "readonly" : ""}></textarea></div></div>` +
      (md ? `<div class="wsmd md"></div>` : "") + `</div>` : `<div class="wsempty">${note("Open a file from the list, or drop a tab here.")}</div>`) +
    `<div class="wsdrop" hidden></div></div>`;
}
function layoutHtml(n) {
  if (!n) return `<div class="wsempty">${note("Open a file from the list on the left.")}</div>`;
  if (n.group) return groupHtml(n.group);
  return `<div class="wssplit ws-${n.dir}">${layoutHtml(n.a)}${layoutHtml(n.b)}</div>`;
}
function fill(id) {  // the open file's text, colours, line numbers and preview into a group
  const el = body().querySelector(`.wsgroup[data-g="${id}"]`), g = ws.groups[id];
  if (!el || !g || !g.active) return;
  const b = ws.bufs[g.active], t = el.querySelector(".wstext");
  if (!b || !t) return;
  if (t.value !== b.text) { const top = t.scrollTop, left = t.scrollLeft; t.value = b.text; t.scrollTop = top; t.scrollLeft = left; }
  paint(el, g.active);
}
let paintTimers = {};
function paint(el, path, now) {
  const t = el.querySelector(".wstext"), h = el.querySelector(".wshl"), nums = el.querySelector(".wsnums"), mdv = el.querySelector(".wsmd");
  const go = () => {
    nums.textContent = Array.from({ length: t.value.split("\n").length }, (_, i) => i + 1).join("\n");
    if (Highlight.lang(path)) h.innerHTML = Highlight.html(t.value, path) + "\n";
    if (mdv) mdv.innerHTML = md(t.value);
    scrollSync(el);
  };
  clearTimeout(paintTimers[el.dataset.g]);
  if (now || t.value.length < 60000) go(); else paintTimers[el.dataset.g] = setTimeout(go, 150);
}
function scrollSync(el) {
  const t = el.querySelector(".wstext"), h = el.querySelector(".wshl"), mdv = el.querySelector(".wsmd");
  if (h) h.style.transform = `translate(${-t.scrollLeft}px, ${-t.scrollTop}px)`;
  el.querySelector(".wsnums").scrollTop = t.scrollTop;
  if (mdv && t.scrollHeight > t.clientHeight) mdv.scrollTop = (t.scrollTop / (t.scrollHeight - t.clientHeight)) * (mdv.scrollHeight - mdv.clientHeight);
}
async function drawEditors() {
  const box = $("#wsEditors"); if (!box) return;
  const keep = document.activeElement && document.activeElement.classList.contains("wstext") ? [document.activeElement.dataset.g, document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
  for (const id of allGroups(ws.layout)) if (ws.groups[id].active) await load(ws.groups[id].active);
  box.innerHTML = layoutHtml(ws.layout);
  for (const id of allGroups(ws.layout)) fill(id);
  if (keep) { const t = box.querySelector(`.wstext[data-g="${keep[0]}"]`); if (t) { t.focus(); t.setSelectionRange(keep[1], keep[2]); } }
  wsTree();
}
function refreshTabs(path) {  // the tab marks and save buttons, without touching the text you're typing in
  for (const id of allGroups(ws.layout)) {
    const g = ws.groups[id]; if (!g.tabs.includes(path)) continue;
    const el = body().querySelector(`.wsgroup[data-g="${id}"]`); if (!el) continue;
    const b = ws.bufs[path] || {};
    el.querySelectorAll(`.wstab[data-f="${CSS.escape(path)}"]`).forEach((t) => { t.classList.toggle("dirty", !!b.dirty); t.querySelector("button").textContent = b.dirty ? "●" : "×"; });
    if (g.active === path) { const s = el.querySelector('.wsbtn[data-act="wssave"]'); if (s) s.disabled = !b.dirty; const st = el.querySelector(".wsstate"); if (st && !b.conflict) st.textContent = b.dirty ? "Not saved" : st.textContent === "Not saved" ? "" : st.textContent; }
  }
}
async function openFile(path, target, where = "center", from = null) {
  if (!path) return;
  await load(path);
  placeTab(path, target, where, from);
  await drawEditors();
}
async function save(id, overwrite) {
  const g = ws.groups[id], path = g && g.active, b = path && ws.bufs[path];
  if (!b || b.binary || b.error) return;
  const r = await post(wsApi("/file"), { path, text: b.text, seen: b.seen, overwrite: !!overwrite });
  if (r.changed) { b.conflict = true; return drawEditors(); }
  if (r.error) { b.error = ""; const st = body().querySelector(`.wsgroup[data-g="${id}"] .wsstate`); if (st) { st.textContent = "That didn't work: " + r.error; st.classList.add("warn"); } return; }
  Object.assign(b, { seen: r.modified, dirty: false, conflict: false });
  ws.last = Math.max(ws.last, r.modified);
  await drawEditors();
  const st = body().querySelector(`.wsgroup[data-g="${id}"] .wsstate`); if (st) st.textContent = "Saved";
}

// ---------- what Claude Code is doing, every two seconds ----------
async function wsTick() {
  if (!proj.ws || curView !== "projects" || !$("#wsEditors")) return clearInterval(ws.poll);
  let d; try { d = await api(wsApi("/changes")); } catch { return; }
  if (d.error) return;
  const newest = d.files.reduce((a, f) => (f.modified > (a ? a.modified : 0) ? f : a), null);
  ws.files = d.files; ws.live = d.live || [];
  const live = $("#wsLive");
  live.innerHTML = d.running ? `<b class="cc">Claude Code is working</b>` + (ws.live.slice(-4).map((s) => `<p>${esc(s.text)}</p>`).join("") || "<p>Starting…</p>") : "";
  live.hidden = !d.running;
  let redraw = false;
  for (const [path, b] of Object.entries(ws.bufs)) {  // open files that changed on disk
    const f = d.files.find((x) => x.path === path);
    if (!f) { if (!b.gone) { b.gone = true; redraw = true; } continue; }
    if (f.modified > b.seen + 0.0005) {
      if (b.dirty) { if (!b.conflict) { b.conflict = true; redraw = true; } }
      else { await load(path, true); redraw = true; }
    }
  }
  // follow the agent: the file it's on, or the one that changed last, in the editor you used last, as long as you aren't editing it
  const lead = ws.live.length && ws.live.at(-1).path && d.files.some((f) => f.path === ws.live.at(-1).path) ? ws.live.at(-1).path : newest && newest.modified > ws.last ? newest.path : "";
  const g = ws.focus && ws.groups[ws.focus], cur = g && g.active && ws.bufs[g.active];
  if (ws.follow && d.running && lead && (!g || lead !== g.active) && !(cur && cur.dirty)) { await openFile(lead, ws.focus); redraw = false; }
  if (newest) ws.last = Math.max(ws.last, newest.modified);
  if (redraw) await drawEditors(); else wsTree();
  if (ws.wasRunning && !d.running) renderProject();  // it finished: the result goes into the chat
  ws.wasRunning = d.running;
}

async function renderWorkspace(d, chat, chip, label) {
  app.classList.add("ws-on");
  $("#pmeta").textContent = `${d.files.length} file${d.files.length === 1 ? "" : "s"}`;
  const built = body().querySelector(".ws");
  if (built && built.dataset.p === d.name) {  // only the chat is new: the editors stay as they are
    const side = built.querySelector(".wschat"), text = $("#projText"), keep = text ? text.value : "", had = document.activeElement === text;
    const at = side.scrollTop, end = side.scrollHeight - at - side.clientHeight < 80;
    side.innerHTML = chat;
    if ($("#projText")) { $("#projText").value = keep; if (had) $("#projText").focus(); }
    side.scrollTop = end ? side.scrollHeight : at;
    built.querySelector(".phead .chip").className = `chip st ${chip}`; built.querySelector(".phead .chip").textContent = label;
    return;
  }
  body().innerHTML = `<div class="ws" data-p="${esc(d.name)}"><div class="phead"><button class="btn" data-act="wsclose">‹ Overview</button><b>${esc(d.name)}</b><span class="chip st ${chip}">${label}</span>
      <label class="chk wsfollow" title="While Claude Code works, the file it's on opens by itself"><input type="checkbox" id="wsFollow" ${ws.follow ? "checked" : ""}> Follow the agent</label><span class="grow"></span>
      <button class="btn" data-act="projterm" title="Opens a terminal with Claude Code in this project's folder">Open in Claude Code</button></div>
    <div class="wsgrid"><aside class="wstree"><h3>Files</h3><div id="wsTree"></div>
        <form id="wsNew"><input id="wsNewName" placeholder="+ new file, e.g. src/app.py" aria-label="New file" autocomplete="off" spellcheck="false"></form></aside>
      <section class="wsedit"><div id="wsEditors"></div><div id="wsLive" class="wslive" hidden></div></section>
      <aside class="wschat">${chat}</aside></div></div>`;
  ws.project = d.name; ws.files = d.files; ws.last = d.files.reduce((a, f) => Math.max(a, f.modified), 0); ws.wasRunning = d.running;
  ws.bufs = {}; ws.groups = {}; ws.layout = null;
  restore(store.get("amadeus-ws:" + d.name), d.files);
  if (!ws.layout) { const first = d.files.find((f) => f.path === "Overview.md") || d.files[0]; ws.layout = { group: newGroup(first ? [first.path] : []) }; ws.focus = ws.layout.group; }
  await drawEditors();
  const side = body().querySelector(".wschat"); side.scrollTop = side.scrollHeight;
  place(); setTimeout(place, 400);  // a small core in the corner under the chat (again once the panel has settled)
  clearInterval(ws.poll); ws.poll = setInterval(wsTick, 2000); wsTick();
}

// ---------- what you do ----------
body().addEventListener("click", async (e) => {
  const a = e.target.closest("[data-act]");
  const group = e.target.closest(".wsgroup");
  if (group && ws.focus !== group.dataset.g) { ws.focus = group.dataset.g; body().querySelectorAll(".wsgroup").forEach((x) => x.classList.toggle("focus", x === group)); wsTree(); }
  if (!a) return;
  const act = a.dataset.act, id = a.dataset.g;
  if (act === "wsopen") { proj.ws = true; proj.shown = null; renderProject(); }
  if (act === "wsclose") { if (closeWorkspace()) renderProject(); }
  if (act === "wsfile") openFile(a.dataset.f, ws.focus);
  if (act === "wsdir") { ws.open[a.dataset.d] = ws.open[a.dataset.d] === false; wsTree(); }
  if (act === "wstab" && !e.target.closest("button")) { ws.groups[id].active = a.dataset.f; ws.focus = id; remember(); drawEditors(); }
  if (act === "wstabx") { e.stopPropagation(); closeTab(id, a.dataset.f); }
  if (act === "wssave") save(id, a.textContent.includes("anyway"));
  if (act === "wsreload") { const p = ws.groups[id].active; await load(p, true); drawEditors(); }
  if (act === "wspreview") { ws.groups[id].preview = !ws.groups[id].preview; remember(); drawEditors(); }
  if (act === "wssplit") openFile(ws.groups[id].active, id, "right");
});
body().addEventListener("auxclick", (e) => { const t = e.target.closest(".wstab"); if (t && e.button === 1) closeTab(t.dataset.g, t.dataset.f); });  // middle click closes, as in an editor
body().addEventListener("input", (e) => {
  if (e.target.id === "wsFollow") ws.follow = e.target.checked;
  if (!e.target.classList.contains("wstext")) return;
  const id = e.target.dataset.g, path = ws.groups[id] && ws.groups[id].active, b = path && ws.bufs[path];
  if (!b) return;
  b.text = e.target.value; b.dirty = true;
  paint(e.target.closest(".wsgroup"), path);
  for (const other of allGroups(ws.layout)) if (other !== id && ws.groups[other].active === path) fill(other);  // the same file open twice
  refreshTabs(path);
});
body().addEventListener("scroll", (e) => { if (e.target.classList && e.target.classList.contains("wstext")) scrollSync(e.target.closest(".wsgroup")); }, true);
body().addEventListener("keydown", (e) => {
  if (!e.target.classList.contains("wstext")) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(e.target.dataset.g); }
  if (e.key === "Tab" && !e.shiftKey) {  // Tab indents, like in an editor
    e.preventDefault(); const t = e.target, s = t.selectionStart;
    t.setRangeText("  ", s, t.selectionEnd, "end"); t.dispatchEvent(new Event("input", { bubbles: true }));
  }
});
body().addEventListener("submit", async (e) => {
  if (e.target.id !== "wsNew") return;
  e.preventDefault();
  const name = $("#wsNewName").value.trim(); if (!name) return;
  if (ws.files.some((f) => f.path === name)) { $("#wsNewName").value = ""; return openFile(name, ws.focus); }
  const r = await post(wsApi("/file"), { path: name, text: "", seen: 0 });
  if (r.error) return alert("That didn't work: " + r.error);
  $("#wsNewName").value = ""; await wsTick(); openFile(r.path, ws.focus);
});

// dragging: a tab (or a file from the list) onto an editor. The middle adds it there, an edge splits the editor to that side
let dragging = null;
const zoneOf = (el, e) => {
  const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
  const edge = Math.min(x, 1 - x, y, 1 - y);
  if (edge > 0.22) return "center";
  return edge === x ? "left" : edge === 1 - x ? "right" : edge === y ? "top" : "bottom";
};
body().addEventListener("dragstart", (e) => {
  const t = e.target.closest(".wstab, .wsrow[data-f]"); if (!t) return;
  if (!t.dataset.f) return;
  dragging = { path: t.dataset.f, from: t.classList.contains("wstab") ? t.dataset.g : null };
  e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragging.path);
});
body().addEventListener("dragover", (e) => {
  const g = dragging && e.target.closest(".wsgroup"); if (!g) return;
  e.preventDefault();
  const zone = e.target.closest(".wstabs") ? "center" : zoneOf(g, e), d = g.querySelector(".wsdrop");
  body().querySelectorAll(".wsdrop").forEach((x) => { if (x !== d) x.hidden = true; });
  d.hidden = false; d.className = "wsdrop " + zone;
});
body().addEventListener("dragleave", (e) => { const g = e.target.closest(".wsgroup"); if (g && !g.contains(e.relatedTarget)) g.querySelector(".wsdrop").hidden = true; });
body().addEventListener("drop", async (e) => {
  const g = dragging && e.target.closest(".wsgroup"); if (!g) return;
  e.preventDefault();
  const zone = e.target.closest(".wstabs") ? "center" : zoneOf(g, e), { path, from } = dragging; dragging = null;
  body().querySelectorAll(".wsdrop").forEach((x) => (x.hidden = true));
  if (from === g.dataset.g && zone === "center") return;
  if (from === g.dataset.g && ws.groups[from].tabs.length === 1) return;  // splitting a group by its only tab: nothing to split
  await openFile(path, g.dataset.g, zone, from);
});
body().addEventListener("dragend", () => { dragging = null; body().querySelectorAll(".wsdrop").forEach((x) => (x.hidden = true)); });
addEventListener("beforeunload", (e) => { if (dirtyAny()) { e.preventDefault(); e.returnValue = ""; } });
