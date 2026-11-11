// The workspace of a project (Projects → a project → Open workspace): its files on the left, the open file in the middle, the chat with
// Amadeus and Claude Code on the right. While Claude Code works you see each step and the file it's on, and you can edit along.
// It's another layout of the project page (hud-views.js), so the chat, the privacy preview and the approvals are the very same.
const ws = { file: null, seen: 0, dirty: false, follow: true, poll: null, files: [], open: {}, last: 0, live: [], binary: false };
const wsApi = (rest) => `/api/projects/${encodeURIComponent(proj.d.name)}${rest}`;
const wsIcon = (open) => (open ? "▾" : "▸");

function closeWorkspace() {
  if (ws.dirty && proj.ws && !confirm("You have unsaved changes in " + ws.file + ". Leave anyway?")) return false;
  clearInterval(ws.poll); ws.poll = null;
  proj.ws = false; app.classList.remove("ws-on");
  Object.assign(ws, { file: null, seen: 0, dirty: false, files: [], last: 0, live: [] });
  return true;
}

function wsTree() {
  // folders first, then files; a dot marks what changed in the last 15 seconds, a bar what the agent is on right now
  const root = {};
  for (const f of ws.files) { let at = root; const parts = f.path.split("/"); parts.slice(0, -1).forEach((p) => (at = at[p + "/"] = at[p + "/"] || {})); at[parts.at(-1)] = f; }
  const now = Date.now() / 1000, on = ws.live.length ? ws.live.at(-1).path : "";
  const level = (node, prefix, depth) => Object.keys(node).sort((a, b) => (b.endsWith("/") - a.endsWith("/")) || a.localeCompare(b)).map((k) => {
    const path = prefix + k, pad = `style="padding-left:${8 + depth * 14}px"`;
    if (k.endsWith("/")) {
      const open = ws.open[path] !== false;
      return `<button class="wsrow dir" data-act="wsdir" data-d="${esc(path)}" ${pad}><i>${wsIcon(open)}</i>${esc(k.slice(0, -1))}</button>` + (open ? level(node[k], path, depth + 1) : "");
    }
    const f = node[k], fresh = now - f.modified < 15;
    return `<button class="wsrow${f.path === ws.file ? " on" : ""}${f.path === on ? " agent" : ""}" data-act="wsfile" data-f="${esc(f.path)}" ${pad} title="${esc(f.path)}"><i>${fresh ? "●" : ""}</i>${esc(k)}</button>`;
  }).join("");
  $("#wsTree").innerHTML = level(root, "", 0) || note("No files yet.");
}

function wsNumbers() {
  const t = $("#wsText"), n = t.value.split("\n").length;
  $("#wsNums").textContent = Array.from({ length: n }, (_, i) => i + 1).join("\n");
  $("#wsNums").scrollTop = t.scrollTop;
}

function wsState(text, warn) { const e = $("#wsState"); if (e) { e.textContent = text || ""; e.classList.toggle("warn", !!warn); } }

async function wsOpen(path, quiet) {
  if (ws.dirty && path !== ws.file && !confirm("You have unsaved changes in " + ws.file + ". Open the other file anyway?")) return;
  const f = await api(wsApi(`/file?path=${encodeURIComponent(path)}`));
  const t = $("#wsText"); if (!t) return;
  ws.file = path; ws.dirty = false; ws.binary = !!f.binary || !!f.error; ws.seen = f.modified || 0;
  $("#wsPath").textContent = path;
  t.readOnly = ws.binary;
  if (!quiet || !ws.binary) { const top = t.scrollTop, same = quiet; t.value = f.error ? "" : f.binary ? "" : f.text; if (same) t.scrollTop = top; else t.scrollTop = 0; }
  wsState(f.error ? "That didn't work: " + f.error : f.binary ? "Not a text file: open it in the file manager." : quiet ? "Updated from disk" : "");
  $("#wsSave").disabled = true; $("#wsReload").hidden = true;
  wsNumbers(); wsTree();
}

async function wsSave(overwrite) {
  if (!ws.file || ws.binary) return;
  const r = await post(wsApi("/file"), { path: ws.file, text: $("#wsText").value, seen: ws.seen, overwrite: !!overwrite });
  if (r.changed) { wsState("It changed on disk while you were editing.", true); $("#wsReload").hidden = false; $("#wsSave").textContent = "Save mine anyway"; $("#wsSave").dataset.over = "1"; return; }
  if (r.error) return wsState("That didn't work: " + r.error, true);
  ws.seen = r.modified; ws.dirty = false; ws.last = Math.max(ws.last, r.modified);
  $("#wsSave").disabled = true; $("#wsSave").textContent = "Save"; delete $("#wsSave").dataset.over; $("#wsReload").hidden = true;
  wsState("Saved");
}

async function wsTick() {
  if (!proj.ws || curView !== "projects" || !$("#wsTree")) return clearInterval(ws.poll);
  let d; try { d = await api(wsApi("/changes")); } catch { return; }
  if (d.error) return;
  const newest = d.files.reduce((a, f) => (f.modified > (a ? a.modified : 0) ? f : a), null);
  ws.files = d.files; ws.live = d.live || [];
  $("#wsLive").innerHTML = d.running ? `<b class="cc">Claude Code is working</b>` + (ws.live.slice(-4).map((s) => `<p>${esc(s.text)}</p>`).join("") || "<p>Starting…</p>") : "";
  $("#wsLive").hidden = !d.running;
  const mine = d.files.find((f) => f.path === ws.file);
  if (ws.file && !mine) wsState("This file was removed.", true);
  else if (mine && mine.modified > ws.seen + 0.0005) {  // the open file changed on disk
    if (ws.dirty) { wsState("The agent changed this file while you were editing.", true); $("#wsReload").hidden = false; }
    else await wsOpen(ws.file, true);
  }
  // follow the agent: the file it's on, or the one that changed last, as long as you aren't in the middle of an edit
  const lead = ws.live.length && ws.live.at(-1).path && d.files.some((f) => f.path === ws.live.at(-1).path) ? ws.live.at(-1).path : newest && newest.modified > ws.last ? newest.path : "";
  if (ws.follow && d.running && !ws.dirty && lead && lead !== ws.file) await wsOpen(lead);
  if (newest) ws.last = Math.max(ws.last, newest.modified);
  wsTree();
  if (ws.wasRunning && !d.running) renderProject();  // it finished: the result goes into the chat
  ws.wasRunning = d.running;
}

async function renderWorkspace(d, chat, chip, label) {
  app.classList.add("ws-on");
  $("#pmeta").textContent = `${d.files.length} file${d.files.length === 1 ? "" : "s"}`;
  const built = body().querySelector(".ws");
  if (built && built.dataset.p === d.name) {  // only the chat is new: the file you're editing stays as it is
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
      <section class="wsedit"><div class="wsbar"><b id="wsPath">No file open</b><span id="wsState"></span><span class="grow"></span>
          <button class="btn" id="wsReload" data-act="wsreload" hidden>Load the new version</button><button class="btn go" id="wsSave" data-act="wssave" disabled>Save</button></div>
        <div class="wscode"><pre id="wsNums" aria-hidden="true"></pre><textarea id="wsText" spellcheck="false" autocomplete="off" autocapitalize="off" wrap="off" aria-label="File contents"></textarea></div>
        <div id="wsLive" class="wslive" hidden></div></section>
      <aside class="wschat">${chat}</aside></div></div>`;
  ws.files = d.files; ws.last = d.files.reduce((a, f) => Math.max(a, f.modified), 0); ws.wasRunning = d.running;
  wsTree();
  const side = body().querySelector(".wschat"); side.scrollTop = side.scrollHeight;
  const first = d.files.find((f) => f.path === "Overview.md") || d.files[0];
  if (first) await wsOpen(first.path);
  clearInterval(ws.poll); ws.poll = setInterval(wsTick, 2000); wsTick();
}

body().addEventListener("click", async (e) => {
  const a = e.target.closest("[data-act]"); if (!a) return;
  const act = a.dataset.act;
  if (act === "wsopen") { proj.ws = true; proj.shown = null; renderProject(); }
  if (act === "wsclose") { if (closeWorkspace()) renderProject(); }
  if (act === "wsfile") wsOpen(a.dataset.f);
  if (act === "wsdir") { ws.open[a.dataset.d] = ws.open[a.dataset.d] === false; wsTree(); }
  if (act === "wssave") wsSave(a.dataset.over === "1");
  if (act === "wsreload") { ws.dirty = false; wsOpen(ws.file); }
});
body().addEventListener("input", (e) => {
  if (e.target.id === "wsText") { if (!ws.dirty) { ws.dirty = true; $("#wsSave").disabled = false; wsState("Not saved"); } wsNumbers(); }
  if (e.target.id === "wsFollow") ws.follow = e.target.checked;
});
body().addEventListener("scroll", (e) => { if (e.target.id === "wsText") $("#wsNums").scrollTop = e.target.scrollTop; }, true);
body().addEventListener("keydown", (e) => {
  if (e.target.id !== "wsText") return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); wsSave(); }
  if (e.key === "Tab" && !e.shiftKey) {  // Tab indents, like in an editor
    e.preventDefault(); const t = e.target, s = t.selectionStart;
    t.setRangeText("  ", s, t.selectionEnd, "end"); t.dispatchEvent(new Event("input", { bubbles: true }));
  }
});
body().addEventListener("submit", async (e) => {
  if (e.target.id !== "wsNew") return;
  e.preventDefault();
  const name = $("#wsNewName").value.trim(); if (!name) return;
  if (ws.files.some((f) => f.path === name)) { $("#wsNewName").value = ""; return wsOpen(name); }
  const r = await post(wsApi("/file"), { path: name, text: "", seen: 0 });
  if (r.error) return wsState("That didn't work: " + r.error, true);
  $("#wsNewName").value = ""; await wsTick(); wsOpen(r.path);
});
addEventListener("beforeunload", (e) => { if (ws.dirty) { e.preventDefault(); e.returnValue = ""; } });
