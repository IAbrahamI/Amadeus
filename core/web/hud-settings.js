// The HUD's Settings pages (Assistant, Voice, Skills, Connectors, Playbooks, Memory, Phone, Reminders) and "Your day".
// Helpers come from hud.js.
const set = { page: null, avatar: "", pair: null };
const field = (label, html) => `<label>${label}${html}</label>`;
const back = '<button class="btn" data-act="setpage" data-page="">‹ Settings</button>';
const head = (title, hint) => `<div class="phead">${back}<b>${title}</b></div>${hint ? note(hint) : ""}`;
const onoff = (on, attrs) => `<button class="btn${on ? " go" : ""}" ${attrs}>${on ? "On" : "Off"}</button>`;
const info = (id) => `<p class="sample" id="${id}"></p>`;
const say = (id, t) => { const e = $("#" + id); if (e) e.textContent = t; };

async function settingsPage(page) {
  set.page = page || null; clearInterval(set.pair);
  if (!page) return loadSettings();
  body().scrollTop = 0;
  await (PAGES[page] || loadSettings)();
}
const PAGES = {
  async assistant() {
    const d = await api("/api/assistant"), own = d.persona === "custom";
    set.avatar = d.avatar;
    const tile = (id, img, label) => `<button type="button" class="avt${id === set.avatar ? " on" : ""}" data-act="avpick" data-av="${esc(id)}"><img src="${img}" alt="" onerror="this.src='/agent.svg'"><span>${esc(label)}</span></button>`;
    body().innerHTML = head("Assistant", "Who your assistant is. Saving restarts it once, which takes a few seconds.") +
      `<form class="pform" id="asForm">${field("Name", `<input id="asName" value="${esc(d.name)}" autocomplete="off">`)}
        <label>Personality<span class="radio"><label class="chk"><input type="radio" name="pm" value="pick" ${own ? "" : "checked"}> One of these</label>
          <select id="asPersona">${d.personas.filter((p) => p !== "custom").map((p) => `<option ${p === d.persona ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></span>
          <span class="radio"><label class="chk"><input type="radio" name="pm" value="own" ${own ? "checked" : ""}> My own</label></span>
          <textarea id="asPersonaText" rows="4" placeholder="A few lines about how it should be: tone, what it cares about…">${own ? esc(d.persona_text) : ""}</textarea></label>
        <label>Face (for calls and the phone app)<div class="avts">${tile("", "/agent.svg", "Default agent")}${d.avatars.map((a) => tile(a, `/avatar/${encodeURIComponent(a)}/${encodeURIComponent(a)}_normal1.png`, a)).join("")}</div></label>
        <div class="acts"><input type="file" id="asFiles" accept="image/png" multiple><button type="button" class="btn" data-act="avup">Upload as my avatar</button></div>
        <div class="acts"><button type="button" class="btn" data-act="asreset">Use the defaults</button><span class="grow"></span><button class="btn go">Save</button></div>${info("asInfo")}</form>`;
  },
  async voice() {
    const d = await api("/api/voice/voices");
    body().innerHTML = head("Voice", "The voice that reads your briefs aloud. Everything runs on this PC.") +
      (!d.piper ? note("The voice service isn't set up yet (see the install guide, \"Optional: voice\").") : rows(d.voices.map((v) => `<div class="row"><span class="k">${v.id === d.selected ? "▶" : ""}</span>
        <div class="t"><b>${esc(v.name)}</b><span>${esc(v.about)}</span></div><div class="acts">${v.installed ? `<button class="btn" data-act="vtest" data-v="${esc(v.id)}">Test</button>` : ""}
        ${v.id === d.selected ? '<span class="chip st st-done">In use</span>' : v.installed ? `<button class="btn go" data-act="vuse" data-v="${esc(v.id)}">Use</button>`
          : v.downloading ? '<span class="chip">Downloading…</span>' : `<button class="btn" data-act="vget" data-v="${esc(v.id)}">Download</button>`}</div></div>`))) +
      `<h3 style="margin-top:22px">+ Add a voice</h3><form class="pform" id="voiceAdd">${field("By name, from the Piper voice list", '<input id="voiceName" placeholder="e.g. fr_FR-siwis-medium" autocomplete="off">')}
        <div class="acts"><button class="btn go">Download</button></div></form>
        <div class="acts" style="margin-top:10px"><input type="file" id="voiceFiles" accept=".onnx,.json" multiple><button class="btn" data-act="vup">Add my own files</button></div>${info("voiceInfo")}`;
    if (d.voices && d.voices.some((v) => v.downloading)) setTimeout(() => set.page === "voice" && curView === "settings" && PAGES.voice(), 3000);
  },
  async skills() {
    const list = await api("/api/skills");
    body().innerHTML = head("Skills", `Instructions ${esc(NAME())} pulls in by itself when your message needs them. Switch one off to stop it.`) +
      rows(list.map((s) => `<div class="row"><span class="k">${s.mode === "background" ? "always" : s.mode}</span><div class="t"><b>${esc(s.name)}</b><span class="wrap">${esc(s.description)}${s.triggers && s.triggers.length ? ` · loads on: ${esc(s.triggers.slice(0, 6).join(", "))}` : ""}</span></div>
        <div class="acts">${s.own ? `<button class="btn" data-act="skrm" data-n="${esc(s.name)}">Remove</button>` : ""}${s.mode === "background" ? "" : onoff(s.active, `data-act="sktoggle" data-n="${esc(s.name)}" data-on="${s.active ? 1 : 0}"`)}</div></div>`)) +
      `<h3 style="margin-top:22px">+ Add your own skill</h3>${note('Write it yourself, or add a SKILL.md in the open <a href="https://agentskills.io" target="_blank" rel="noopener">agentskills.io</a> format.')}
      <form class="pform" id="skAdd">${field("Name", '<input id="skName" placeholder="e.g. meeting-notes" autocomplete="off">')}${field("What it's for", '<input id="skDesc" autocomplete="off">')}
        ${field("Words that load it", '<input id="skTrig" placeholder="meeting, minutes, notes" autocomplete="off">')}${field("The instructions", '<textarea id="skBody" rows="4"></textarea>')}
        <div class="acts"><input type="file" id="skFile" accept=".md"><span class="grow"></span><button class="btn go">Add skill</button></div>${info("skInfo")}</form>`;
  },
  async connectors() {
    const [list, ob] = await Promise.all([api("/api/connectors"), api("/api/obsidian")]);
    body().innerHTML = head("Connectors", "What it may use. Anything that changes something always asks you first.") +
      `<h3>Obsidian</h3>` + (ob.connected
        ? `${note(`Your to-dos and notes live in the Amadeus folder of your vault: ${esc(ob.vault)}. Every hour a snapshot is saved, so any change can be undone.`)}<div class="acts"><span class="grow"></span><button class="btn" data-act="obsoff">Disconnect</button></div>${info("obsInfo")}`
        : `${note("Optional. Keeps your to-dos and notes in an Amadeus folder of your Obsidian vault, with an hourly snapshot so any change can be undone. Right now they live in Amadeus' own folder.")}
           <form class="pform" id="obsForm">${field("Your vault folder", `<input id="obsVault" value="${esc(ob.suggestion)}" placeholder="~/Documents/My Vault" autocomplete="off">`)}<div class="acts"><span class="grow"></span><button class="btn go">Connect</button></div>${info("obsInfo")}</form>`) +
      `<h3 style="margin-top:22px">What it may use</h3>` +
      rows(list.map((c) => `<div class="row"><span class="k">${c.own ? "yours" : ""}</span><div class="t"><b>${esc(c.own ? c.name : c.id)}</b><span class="wrap">${esc(c.description)}${c.tools.length ? " · " + c.tools.map((t) => esc(t) + (c.approval_tools.includes(t) ? " (asks)" : "")).join(", ") : ""}${c.missing ? " · " + esc(c.missing) : ""}</span></div>
        <div class="acts">${c.own ? `<button class="btn" data-act="connrm" data-n="${esc(c.name)}">Remove</button>` : ""}${onoff(c.enabled, `data-act="conntoggle" data-id="${esc(c.id)}" data-on="${c.enabled ? 1 : 0}"`)}</div></div>`)) +
      `<h3 style="margin-top:22px">+ Add your own connector</h3>${note('Any <a href="https://modelcontextprotocol.io" target="_blank" rel="noopener">MCP</a> server that runs on this PC. Its tools always ask you first, and what comes back is treated as data.')}
      <form class="pform" id="connAdd">${field("Name", '<input id="connName" placeholder="e.g. Files" autocomplete="off">')}${field("Command that starts it", '<input id="connCmd" placeholder="npx -y @modelcontextprotocol/server-filesystem ~/Documents" autocomplete="off">')}
        ${field("Settings it needs (one NAME=value per line, optional)", '<textarea id="connEnv" rows="2"></textarea>')}<div class="acts"><span class="grow"></span><button class="btn go">Add connector</button></div>${info("connInfo")}</form>`;
  },
  async playbooks() {
    const list = await api("/api/playbooks");
    body().innerHTML = head("Playbooks", "Fixed recipes it follows step by step. Say the words, or press Run.") +
      rows(list.map((p) => `<div class="row"><span class="k">${p.own ? "yours" : ""}</span><div class="t"><b>${esc(p.title)}</b><span class="wrap">${esc(p.about)} · say: ${esc(p.triggers.join(", "))}</span></div>
        <div class="acts">${p.own ? `<button class="btn" data-act="pbrm" data-id="${esc(p.name)}">Remove</button>` : ""}<button class="btn go" data-act="pbrun" data-t="${esc(p.title)}">Run</button></div></div>`)) +
      `<h3 style="margin-top:22px">+ Add your own playbook</h3><form class="pform" id="pbAdd">${field("Title", '<input id="pbTitle" placeholder="e.g. Friday wrap-up" autocomplete="off">')}
        ${field("Words that start it", '<input id="pbTrig" placeholder="wrap up the week" autocomplete="off">')}${field("The steps, one per line", '<textarea id="pbSteps" rows="4"></textarea>')}
        <div class="acts"><span class="grow"></span><button class="btn go">Add playbook</button></div>${info("pbInfo")}</form>`;
  },
  async memory() {
    const [p, l] = await Promise.all([api("/api/profile"), api("/api/learning")]);
    const last = (l.log || []).slice(-1)[0], ask = p.asking || [], rules = Object.entries(p.rules || {});
    body().innerHTML = head("Memory", "What it knows about you and how you work. All of it stays on this PC.") +
      `<form class="pform" id="profForm">${field(`Your profile <small>${p.pending} new observation(s) waiting${p.updated ? " · updated " + esc(p.updated.replace("T", " ")) : ""}</small>`, `<textarea id="profText" rows="8">${esc(p.profile)}</textarea>`)}
        <div class="acts"><button type="button" class="btn" data-act="profmerge">Fold in what's new</button><span class="grow"></span><button class="btn go">Save</button></div>${info("profInfo")}</form>
      <h3 style="margin-top:22px">Important people</h3><form class="pform" id="vipForm">${field("Their mail always reaches you (one name or address per line)", `<textarea id="vipText" rows="3">${esc((p.vip || []).join("\n"))}</textarea>`)}
        <div class="acts"><span class="grow"></span><button class="btn go">Save</button></div>${info("vipInfo")}</form>
      <h3 style="margin-top:22px">How you ask for things</h3>${ask.length ? rows(ask.map((a) => `<div class="row"><span class="k">${a.n > 1 ? "×" + a.n : ""}</span><div class="t"><b>“${esc(a.say)}”</b><span>${esc(a.means)}</span></div><button class="btn" data-act="askrm" data-say="${esc(a.say)}">Forget</button></div>`)) : note("Nothing yet. This is learned as you use it.")}
      <h3 style="margin-top:22px">Lessons from your ratings</h3>${(l.lessons || []).length ? rows(l.lessons.map((x) => `<div class="row"><span class="k">+${x.helpful || 0} −${x.harmful || 0}</span><div class="t"><span class="wrap">${esc(x.text)}</span></div><button class="btn" data-act="lessonrm" data-id="${esc(x.id)}">Forget</button></div>`)) : note("No lessons yet. Answers you rate as not good become lessons overnight.")}
      <div class="acts" style="margin-top:10px"><button class="btn" data-act="learn">Learn now</button><span class="sample" id="learnInfo">${last ? `Last run ${esc(last.day)}: test ${Math.round(last.before * 100)}% → ${Math.round(last.after * 100)}%${last.kept ? "" : " (not kept)"}` : ""}</span></div>
      <h3 style="margin-top:22px">Mail filing rules</h3>${rules.length ? rows(rules.map(([a, f]) => `<div class="row"><span class="k">→</span><div class="t"><b>${esc(a)}</b><span>${esc(f)}</span></div><span></span></div>`)) : note("None yet.")}`;
  },
  async phone() {
    const d = await api("/api/devices");
    body().innerHTML = head("Phone", "Your phone reaches this PC only through your private Tailscale network.") +
      `<div class="phone"><div><p class="prose">${d.mode === "visible" ? "<b>Visible:</b> your paired phone can reach it." : "<b>Private:</b> not reachable from outside this PC."}</p>
        <div class="acts"><button class="btn" data-act="pmode" data-m="private">Private</button><button class="btn" data-act="pmode" data-m="visible">Visible</button></div>${info("modeInfo")}
        <p class="sample">${d.host ? "https://" + esc(d.host) : "Tailscale is not running on this PC."}</p>
        <div class="acts"><button class="btn go" data-act="pair">Pair a phone</button></div><div id="pairCode"></div></div>
        ${d.host ? `<img class="qr" id="phoneQr" src="/api/devices/qr?${Date.now()}" alt="QR code for the phone app">` : ""}</div>
      <h3 style="margin-top:22px">Paired phones</h3>${d.devices.length ? rows(d.devices.map((x) => `<div class="row"><span class="k">Phone</span><div class="t"><b>${esc(x.name)}</b><span>paired ${new Date(x.created * 1000).toLocaleDateString()} · last seen ${ago(x.last_seen)}</span></div><button class="btn" data-act="unpair" data-id="${esc(x.id)}">Remove</button></div>`)) : note("No phone paired yet.")}`;
  },
  async reminders() {
    const list = await api("/api/reminders");
    body().innerHTML = head("Reminders", `What ${esc(NAME())} will remind you of. Ask in the chat to add, move or remove one.`) +
      (list.length ? rows(list.map((r) => `<div class="row"><span class="k">${r.next_run ? ago(r.next_run) : "–"}</span><div class="t"><b>${esc(r.text)}</b><span>${esc(r.schedule)}</span></div><span></span></div>`)) : note("No reminders."));
  },
};

// ---------- "Your day": the morning brief and the evening summary (click the clock) ----------
const DAYK = { morning: "Morning brief", now: "So far today", evening: "Evening summary" };
let speaking = null;
async function loadDay(reports) {
  reports = reports || (await api("/api/day")).reports;
  body().innerHTML = (reports.length ? reports.map((r, i) => `<section class="dayrep"><h3>${DAYK[r.kind] || esc(r.kind)} · ${hhmm(r.at)} <button class="btn" data-act="listen" data-i="${i}">▶ Listen</button></h3><div class="md">${md(stripMood(r.text))}</div></section>`).join("")
    : note("Nothing yet today. The morning brief comes at 07:00 and the evening summary at 21:00.")) +
    `<div class="acts"><button class="btn go" data-act="daynow">Summarize so far</button></div>${info("dayInfo")}`;
  body().dataset.reports = JSON.stringify(reports.map((r) => r.text));
}
VIEWS.day = { side: 1, title: "Your day", meta: new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }), load: () => loadDay() };
$(".hud.tl").onclick = () => open("day"); $(".hud.tl").title = "Your day: the morning brief and the evening summary"; $(".hud.tl").style.cursor = "pointer";
VIEWS.settings.load = () => settingsPage(set.page = null);

body().addEventListener("click", async (e) => {
  const a = e.target.closest("[data-act]"); if (!a) return;
  const act = a.dataset.act, d = a.dataset;
  if (act === "setpage") settingsPage(d.page);
  if (act === "avpick") { set.avatar = d.av; body().querySelectorAll(".avt").forEach((x) => x.classList.toggle("on", x === a)); }
  if (act === "avup") {
    const files = [...$("#asFiles").files]; if (!files.length) return say("asInfo", "Pick one or more PNG files first.");
    const read = (f) => new Promise((ok) => { const r = new FileReader(); r.onload = () => ok({ name: f.name, data: r.result }); r.readAsDataURL(f); });
    say("asInfo", "Uploading…");
    const r = await post("/api/assistant/upload", { set: "custom", files: await Promise.all(files.map(read)) });
    if (r.error) return say("asInfo", "That didn't work: " + r.error);
    await PAGES.assistant(); set.avatar = "custom"; say("asInfo", `Saved ${r.saved.length} image(s). "custom" is picked: press Save.`);
    body().querySelectorAll(".avt").forEach((x) => x.classList.toggle("on", x.dataset.av === "custom"));
  }
  if (act === "asreset") { if (!confirm("Use the default assistant (default name, personality and icon)? Your own files are kept.")) return; await post("/api/assistant/reset", {}); restarted(); }
  if (act === "vuse") { await post("/api/voice/voices/select", { id: d.v }); PAGES.voice(); }
  if (act === "vget") { await post("/api/voice/voices/download", { id: d.v }); PAGES.voice(); }
  if (act === "vtest") {
    const was = (await api("/api/voice/voices")).selected;
    if (d.v !== was) await post("/api/voice/voices/select", { id: d.v });
    await speakText(`Hello, I'm ${NAME()}. This is how I sound when I read your morning brief.`, a);
    if (d.v !== was) await post("/api/voice/voices/select", { id: was });
  }
  if (act === "vup") {
    const files = [...$("#voiceFiles").files];
    if (!files.some((f) => f.name.endsWith(".onnx")) || !files.some((f) => f.name.endsWith(".onnx.json"))) return say("voiceInfo", "Pick both files: <name>.onnx and <name>.onnx.json.");
    for (const f of files) { const r = await fetch(`/api/voice/voices/upload?name=${encodeURIComponent(f.name)}`, { method: "POST", body: f }).then((x) => x.json()); if (r.error) return say("voiceInfo", "That didn't work: " + r.error); }
    PAGES.voice();
  }
  if (act === "sktoggle") { await post("/api/skills", { name: d.n, active: d.on !== "1" }); PAGES.skills(); }
  if (act === "skrm") { if (!confirm(`Remove your skill "${d.n}"?`)) return; await post("/api/skills/remove", { name: d.n }); PAGES.skills(); }
  if (act === "obsoff") {
    if (!confirm("Disconnect Obsidian? Your files stay in the vault. New to-dos and notes go to Amadeus' own folder.")) return;
    const r = await post("/api/obsidian/disconnect", {});
    say("obsInfo", r.error ? "That didn't work: " + r.error : "Disconnected. Restarting…");
    if (!r.error) setTimeout(() => PAGES.connectors(), 5000);
  }
  if (act === "conntoggle") { await post("/api/connectors", { id: d.id, enabled: d.on !== "1" }); PAGES.connectors(); }
  if (act === "connrm") { if (!confirm(`Remove the connector "${d.n}"?`)) return; await post("/api/connectors/remove", { name: d.n }); PAGES.connectors(); }
  if (act === "pbrm") { if (!confirm("Remove this playbook?")) return; await post("/api/playbooks/remove", { id: d.id }); PAGES.playbooks(); }
  if (act === "pbrun") { open("chat"); send("Run playbook: " + d.t); }
  if (act === "profmerge") { say("profInfo", "Updating your profile…"); const r = await post("/api/profile/merge", {}); $("#profText").value = r.profile; say("profInfo", r.merged ? "Updated." : "Nothing new to add."); }
  if (act === "askrm") { await post("/api/asking/remove", { say: d.say }); PAGES.memory(); }
  if (act === "lessonrm") { await post("/api/learning/forget", { id: d.id }); PAGES.memory(); }
  if (act === "learn") { a.disabled = true; say("learnInfo", "Learning (this takes a minute)…"); const r = await post("/api/learning/run", {}); say("learnInfo", r.added ? `Learned ${r.added} new lesson(s).` : `Nothing new: ${r.reason || "no mistakes"}.`); a.disabled = false; }
  if (act === "pmode") { say("modeInfo", "Switching…"); const r = await post(`/api/phone/${d.m}`, {}); await PAGES.phone(); say("modeInfo", plain(r.text || r.error || "")); }
  if (act === "unpair") { if (!confirm("Remove this phone? It loses access right away.")) return; await post(`/api/devices/${d.id}/revoke`, {}); PAGES.phone(); }
  if (act === "pair") {
    const r = await post("/api/devices/code", {});
    if (r.error) return ($("#pairCode").textContent = "That didn't work: " + r.error);
    $("#pairCode").innerHTML = `<div class="paircode">${esc(r.code)}</div>${note(`Scan the QR code with the app, or type the code. Valid ${r.minutes} minutes, once.`)}`;
    if ($("#phoneQr")) $("#phoneQr").src = `/api/devices/qr?code=${r.code}&${Date.now()}`;
    const before = (await api("/api/devices")).devices.length, until = Date.now() + r.minutes * 60000;
    clearInterval(set.pair);
    set.pair = setInterval(async () => {  // once paired (or expired) the code disappears from the screen
      const x = await api("/api/devices").catch(() => null), paired = x && x.devices.length > before;
      if (!paired && Date.now() < until) return;
      clearInterval(set.pair); if (set.page === "phone" && curView === "settings") { await PAGES.phone(); $("#pairCode").innerHTML = note(paired ? "✓ Phone paired." : "The code expired. Make a new one if you need it."); }
    }, 2000);
  }
  if (act === "daynow") { a.disabled = true; say("dayInfo", `${NAME()} is writing it…`); setMode("think"); try { await loadDay((await post("/api/day/now", {})).reports); } catch (x) { say("dayInfo", "That didn't work: " + x.message); } setMode("idle"); }
  if (act === "listen") speakText(JSON.parse(body().dataset.reports || "[]")[Number(d.i)], a);
});
body().addEventListener("submit", async (e) => {
  const f = e.target, id = f.id;
  const forms = {
    async asForm() {
      const own = f.querySelector("[name=pm]:checked").value === "own";
      const r = await post("/api/assistant", { name: $("#asName").value, avatar: set.avatar, ...(own ? { persona_text: $("#asPersonaText").value } : { persona: $("#asPersona").value }) });
      if (r.error) return say("asInfo", "That didn't work: " + r.error);
      restarted();
    },
    async obsForm() {
      say("obsInfo", "Connecting…");
      const r = await post("/api/obsidian/connect", { vault: $("#obsVault").value });
      if (r.error) return say("obsInfo", "That didn't work: " + r.error);
      say("obsInfo", (r.kept.length ? `Connected. These were already in your vault, so yours stayed and the ones in Amadeus' folder weren't copied: ${r.kept.join(", ")}. ` : "Connected. ") + "Restarting…");
      setTimeout(() => PAGES.connectors(), 5000);
    },
    async voiceAdd() { const v = $("#voiceName").value.trim(); if (!v) return; const r = await post("/api/voice/voices/download", { id: v }); say("voiceInfo", r.error ? "That didn't work: " + r.error : "Downloading… it shows in the list when it's ready."); if (!r.error) setTimeout(PAGES.voice, 800); },
    async skAdd() {
      const file = $("#skFile").files[0];
      if (file && file.size > 200000) return say("skInfo", "That file is too large for a skill.");
      say("skInfo", "Adding…");
      const r = await post("/api/skills/add", file ? { file: await file.text(), name: $("#skName").value } : { name: $("#skName").value, description: $("#skDesc").value, triggers: $("#skTrig").value, body: $("#skBody").value });
      if (r.error) return say("skInfo", "That didn't work: " + r.error); PAGES.skills();
    },
    async connAdd() {
      const env = Object.fromEntries($("#connEnv").value.split("\n").map((l) => l.trim()).filter((l) => l.includes("=")).map((l) => [l.slice(0, l.indexOf("=")).trim(), l.slice(l.indexOf("=") + 1).trim()]));
      say("connInfo", "Starting it to check…");
      const r = await post("/api/connectors/add", { name: $("#connName").value, command: $("#connCmd").value, env });
      if (r.error) return say("connInfo", "That didn't work: " + r.error); PAGES.connectors();
    },
    async pbAdd() { const r = await post("/api/playbooks/add", { title: $("#pbTitle").value, triggers: $("#pbTrig").value, steps: $("#pbSteps").value }); if (r.error) return say("pbInfo", "That didn't work: " + r.error); PAGES.playbooks(); },
    async profForm() { await post("/api/profile", { profile: $("#profText").value }); say("profInfo", "Saved."); },
    async vipForm() { const r = await post("/api/mail/vip", { vip: $("#vipText").value.split("\n") }); $("#vipText").value = r.vip.join("\n"); say("vipInfo", "Saved."); },
  };
  if (forms[id]) { e.preventDefault(); forms[id](); }
});
body().addEventListener("input", (e) => {  // typing your own personality picks "My own"
  if (e.target.id === "asPersonaText") body().querySelector("[name=pm][value=own]").checked = true;
});
body().addEventListener("change", (e) => { if (e.target.id === "asPersona") body().querySelector("[name=pm][value=pick]").checked = true; });
async function restarted() {  // Amadeus restarts with the new settings: wait until it's back, then reload
  say("asInfo", "Saved. Restarting…");
  for (let i = 0; i < 30; i++) { await new Promise((r) => setTimeout(r, 1500)); try { await fetch("/api/identity"); return location.reload(); } catch {} }
}
// read a text aloud with the local voice (Piper); press again to stop
async function speakText(text, btn) {
  if (speaking) { speaking.pause(); speaking = null; btn.textContent = "▶ Listen"; setMode("idle"); return; }
  const label = btn.textContent; btn.disabled = true; btn.textContent = "…";
  try {
    const r = await fetch("/api/voice/tts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: plain(text) }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    speaking = new Audio(URL.createObjectURL(await r.blob()));
    const talk = setInterval(() => core.talk(), 140);  // the core moves with the voice while it reads
    speaking.onended = () => { clearInterval(talk); speaking = null; btn.textContent = label; setMode("idle"); };
    speaking.onpause = speaking.onended;
    setMode("speak"); await speaking.play(); btn.textContent = "■ Stop";
  } catch (x) { btn.textContent = label; subtitle("Can't read it aloud: " + (x.message.includes("No text-to-speech") ? "no voice installed (see the install guide)." : x.message)); }
  btn.disabled = false;
}
