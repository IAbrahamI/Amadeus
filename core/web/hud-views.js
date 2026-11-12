// The HUD's big views: Calendar (a week), Mail (one inbox per account) and Projects. Helpers come from hud.js.
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const hm = (iso) => (iso && iso.length > 10 ? iso.slice(11, 16) : "");
const ago = (t) => { const d = new Date(t * 1000), tm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString() ? tm : `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${tm}`; };

// ---------- Calendar: one week, your own changes need no approval ----------
const cal = { week: null, occ: [], edit: null };
const monday = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return addDays(x, -((x.getDay() + 6) % 7)); };
// the switch between the week and the reminders, in the panel's header: a highlight slides to the side you pick
function calTabs() {
  $("#ptabs").innerHTML = `<div class="seg${cal.tab === "rem" ? " right" : ""}" role="tablist" aria-label="Calendar or reminders"><i aria-hidden="true"></i>` +
    `<button role="tab" aria-selected="${cal.tab !== "rem"}" data-act="caltab" data-t="week">Week</button><button role="tab" aria-selected="${cal.tab === "rem"}" data-act="caltab" data-t="rem">Reminders</button></div>`;
  return "";
}
async function loadReminders() {
  const list = await api("/api/reminders");
  $("#pmeta").textContent = `${list.length} active`;
  const when = (r) => r.next_run ? new Date(r.next_run * 1000).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–";
  const how = (r) => r.schedule.startsWith("once ") ? "once" : r.schedule.replace(/^weekly (\w+)/, "every $1").replace(/^weekdays/, "weekdays at").replace(/^daily/, "every day at");
  body().innerHTML = calTabs() + `<form class="pform remnew" id="remNew"><div class="remrow"><input id="remText" placeholder="Remind me to…" aria-label="What" autocomplete="off" required>
      <input id="remWhen" placeholder="in 10 minutes · tomorrow 9:00 · daily 07:30" aria-label="When" autocomplete="off" required><button class="btn go">Add</button></div><p class="sample" id="remInfo"></p></form>` +
    (list.length ? rows(list.map((r) => `<div class="row"><span class="k">${esc(when(r))}</span><div class="t"><b>${esc(r.text.replace(/\s*\[mail:\d+\]/, ""))}</b><span>${esc(how(r))}</span></div>
      <div class="acts"><button class="btn" data-act="remrm" data-id="${esc(r.id)}">Remove</button></div></div>`)) : note("No reminders. Add one above, or ask in the chat."));
}
async function loadCalendar() {
  if (cal.tab === "rem") return loadReminders();
  if (!cal.week) cal.week = monday(new Date());
  const from = cal.week, to = addDays(from, 7);
  cal.occ = await api(`/api/calendar?from=${ymd(from)}&to=${ymd(to)}`);
  const days = [...Array(7)].map((_, i) => addDays(from, i)), today = ymd(new Date());
  const wk = Math.ceil(((from - new Date(from.getFullYear(), 0, 1)) / 864e5 + new Date(from.getFullYear(), 0, 1).getDay() + 1) / 7);
  $("#pmeta").textContent = `Week ${wk} · ${from.toLocaleDateString([], { day: "numeric", month: "short" })} – ${addDays(from, 6).toLocaleDateString([], { day: "numeric", month: "short" })}`;
  const timed = cal.occ.filter((o) => !o.all_day), allDay = cal.occ.filter((o) => o.all_day);
  const hrs = timed.map((o) => [Number(o.occ_start.slice(11, 13)), Math.ceil(Number(o.occ_end.slice(11, 13)) + Number(o.occ_end.slice(14, 16)) / 60)]);
  // the whole day, 00:00 to 24:00, in a box that scrolls; it opens at the busy part (from 8:00, or the earliest event)
  const first = Math.min(8, ...hrs.map((h) => h[0])), h0 = 0, h1 = 24;
  const H = 46, hours = [...Array(h1 - h0)].map((_, i) => h0 + i);
  let h = calTabs() + `<div class="calbar"><button class="btn" data-act="calweek" data-d="-7">‹</button><button class="btn" data-act="calweek" data-d="0">This week</button>` +
    `<button class="btn" data-act="calweek" data-d="7">›</button><span class="grow"></span><button class="btn go" data-act="calnew">+ New event</button></div>`;
  h += `<div id="calEdit"></div><div class="weekwrap weekscroll" id="calScroll"><div class="week w7"><div class="dh"></div>` +
    days.map((d) => `<div class="dh${ymd(d) === today ? " today" : ""}">${d.toLocaleDateString([], { weekday: "short" })} ${d.getDate()}</div>`).join("");
  if (allDay.length) h += `<div class="hr allday">all day</div>` + days.map((d) => `<div class="alld">${allDay.filter((o) => o.occ_start.slice(0, 10) <= ymd(d) && o.occ_end.slice(0, 10) > ymd(d))
    .map((o) => `<button class="ev mini${o.created_by === "amadeus" ? " amadeus" : ""}" data-act="calopen" data-id="${esc(o.id)}">${esc(o.title)}</button>`).join("")}</div>`).join("");
  h += `<div>${hours.map((x) => `<div class="hr">${String(x).padStart(2, "0")}:00</div>`).join("")}</div>`;
  days.forEach((d) => {
    const key = ymd(d), list = timed.filter((o) => o.occ_start.slice(0, 10) === key).sort((a, b) => a.occ_start.localeCompare(b.occ_start));
    const lanes = [];  // side by side when they overlap
    list.forEach((o) => { let l = lanes.findIndex((end) => end <= o.occ_start); if (l < 0) l = lanes.push("") - 1; lanes[l] = o.occ_end; o._lane = l; });
    h += `<div class="col${key === today ? " today" : ""}" data-day="${key}">` + hours.map(() => '<div class="slot"></div>').join("");
    list.forEach((o) => {
      const s = (new Date(o.occ_start) - new Date(key + "T00:00")) / 36e5, e = Math.min(24, (new Date(o.occ_end) - new Date(key + "T00:00")) / 36e5);
      const w = 100 / lanes.length;
      h += `<button class="ev${o.created_by === "amadeus" ? " amadeus" : ""}" data-act="calopen" data-id="${esc(o.id)}" style="top:${(s - h0) * H + 2}px;height:${Math.max(20, (e - s) * H - 4)}px;left:calc(${o._lane * w}% + 3px);width:calc(${w}% - 6px)">` +
        `<b>${esc(o.title)}${o.repeat ? " ↻" : ""}</b><span>${hm(o.occ_start)}${o.location ? " · " + esc(o.location) : ""}</span></button>`;
    });
    if (key === today) { const n = new Date(), y = (n.getHours() + n.getMinutes() / 60 - h0) * H; if (y > 0 && y < hours.length * H) h += `<div class="now" style="top:${y}px"></div>`; }
    h += "</div>";
  });
  const keep = cal.scrolled && $("#calScroll") ? $("#calScroll").scrollTop : null;
  body().innerHTML = h + "</div></div>";
  const box = $("#calScroll");
  box.scrollTop = keep !== null ? keep : Math.max(0, (first - h0) * H - 4);
  box.onscroll = () => (cal.scrolled = true);
  if (cal.edit) calForm(cal.edit === "new" ? null : cal.occ.find((o) => o.id === cal.edit));
}
function calForm(o, day) {
  const box = $("#calEdit"); if (!box) return;
  const ev = o || { title: "", start: (day || ymd(new Date())) + "T09:00", end: (day || ymd(new Date())) + "T10:00", all_day: 0, location: "", notes: "" };
  box.innerHTML = `<form class="pform calform" id="calForm"><div class="calrow"><label>Title<input name="title" value="${esc(ev.title)}" required></label>
      <label>Day<input type="date" name="date" value="${esc(ev.start.slice(0, 10))}" required></label></div>
    <div class="calrow"><label class="chk"><input type="checkbox" name="all_day" ${ev.all_day ? "checked" : ""}> All day</label>
      <label>From<input type="time" name="from" value="${hm(ev.start) || "09:00"}"></label><label>To<input type="time" name="to" value="${hm(ev.end) || "10:00"}"></label>
      <label>Where<input name="location" value="${esc(ev.location || "")}"></label></div>
    <label>Notes<input name="notes" value="${esc(ev.notes || "")}"></label>
    ${o && o.repeat ? note("This repeats: a change applies to the whole series.") : ""}
    <div class="acts">${o ? '<button type="button" class="btn" data-act="caldel">Delete</button>' : ""}<span class="grow"></span>
      <button type="button" class="btn" data-act="calcancel">Cancel</button><button class="btn go">${o ? "Save" : "Add"}</button></div><p class="sample" id="calMsg"></p></form>`;
  box.querySelector("input[name=title]").focus();
}
async function calSave(f) {
  const allDay = f.all_day.checked, date = f.date.value, from = f.from.value || "09:00", to = f.to.value || "10:00";
  const ev = cal.edit && cal.edit !== "new" ? cal.occ.find((o) => o.id === cal.edit) : null;
  const b = { title: f.title.value, all_day: allDay, location: f.location.value, notes: f.notes.value,
    start: allDay ? date : `${date}T${from}`, end: allDay ? "" : `${to > from ? date : ymd(addDays(new Date(date + "T00:00"), 1))}T${to}` };
  if (ev) Object.assign(b, { repeat: ev.repeat || "", repeat_until: ev.repeat_until || "", alert: ev.alert });
  const r = await api(ev ? `/api/calendar/${ev.id}` : "/api/calendar", { method: ev ? "PATCH" : "POST", body: JSON.stringify(b) });
  if (r.error) { $("#calMsg").textContent = "That didn't work: " + r.error; return; }
  cal.edit = null; cal.week = monday(new Date(date + "T00:00")); loadCalendar(); nextUp();
}

// ---------- Mail: one inbox per account, never mixed ----------
const mail = { acc: null, accounts: [], off: [], unread: {}, list: [], open: null, days: 30 };
async function loadMail() {
  let st;
  try { st = await (await fetch("/api/mail/status")).json(); } catch { st = { connected: false }; }
  // nothing to show yet (no account connected directly, and Thunderbird isn't running): it starts with adding an
  // account, so the page never ends at "open Thunderbird". Thunderbird stays one of the ways, further down.
  mail.tbDown = st.setup !== false && !st.connected;
  if (st.setup === false || !st.connected) {
    mail.accounts = []; mail.off = []; mail.acc = "__add"; mail.open = null;
    $("#pmeta").textContent = "No account connected";
    return renderMail();
  }
  mail.accounts = st.accounts; mail.off = st.off || [];
  const on = mail.accounts.filter((a) => !mail.off.includes(a.id));
  if (!mail.acc || (mail.acc !== "__add" && !on.some((a) => a.id === mail.acc))) mail.acc = on[0] ? on[0].id : "__add";
  try { mail.unread = {}; (await (await fetch("/api/mail/unread")).json()).forEach((m) => (mail.unread[m.accountId] = (mail.unread[m.accountId] || 0) + 1)); } catch {}
  $("#pmeta").textContent = `${on.length} account${on.length === 1 ? "" : "s"}, kept apart`;
  await renderMail();
}
const mailRail = () => '<nav class="acc-tabs" aria-label="Accounts">' + mail.accounts.filter((a) => !mail.off.includes(a.id)).map((a) => {
  const n = mail.unread[a.id] || 0, addr = (a.identities[0] || {}).email || a.type;
  return `<button class="acc${a.id === mail.acc ? " on" : ""}" aria-current="${a.id === mail.acc}" data-act="acc" data-acc="${esc(a.id)}"><span><b>${esc(a.name)}</b><small>${esc(addr)}</small></span>${n ? `<em>${n}</em>` : ""}</button>`;
}).join("") + `<button class="acc add${mail.acc === "__add" ? " on" : ""}" data-act="acc" data-acc="__add"><span><b>+ Add account</b></span></button></nav>`;
// Two ways to connect an account: directly with the provider, or through Thunderbird on this PC.
let mailProvider = "gmail";
async function addMailBox() {
  const d = await api("/api/mail/direct"), p = d.providers[mailProvider], srv = (id, label, host, port) =>
    field(label, `<span class="radio"><input id="${id}Host" placeholder="${host}" autocomplete="off"><input id="${id}Port" placeholder="${port}" inputmode="numeric" style="max-width:90px"></span>`);
  const form = p.auth === "microsoft"
    ? (d.microsoft ? `<div class="acts"><span class="grow"></span><button type="button" class="btn go" data-act="dms">Sign in with Microsoft</button></div>`
      : `${note("Microsoft only lets apps sign in that are registered with them. It's free and takes about five minutes, once. This is from Microsoft's documentation as I know it: if a screen looks different, tell Amadeus.")}
        <ol class="mssteps"><li>Open <a href="https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade" target="_blank" rel="noopener">Microsoft Entra → App registrations</a> and sign in. Choose <b>New registration</b>.</li>
        <li>Name: <b>Amadeus</b>. Account types: <b>Accounts in any organizational directory and personal Microsoft accounts</b>.</li>
        <li>Redirect URI: platform <b>Public client/native (mobile &amp; desktop)</b>, address <code>${esc(d.ms_redirect)}</code>. Register.</li>
        <li>Under <b>API permissions</b> → Add a permission → Microsoft Graph → Delegated: <b>IMAP.AccessAsUser.All</b>, <b>Mail.Send</b>, <b>offline_access</b>.</li>
        <li>Copy the <b>Application (client) ID</b> from the overview and paste it here.</li></ol>
        <form class="pform" id="msApp">${field("Application (client) ID", '<input id="msAppId" placeholder="1a2b3c4d-1234-5678-9abc-1234567890ab" autocomplete="off" spellcheck="false">')}
        <div class="acts"><span class="grow"></span><button class="btn go">Save</button></div>${info("msInfo")}</form>`)
    : `<form class="pform" id="dForm">${field("Address", '<input id="dEmail" autocomplete="off" spellcheck="false">')}
        ${field("App password", '<input id="dPass" type="password" autocomplete="off">')}
        ${p.manual ? srv("dImap", "IMAP server and port (SSL)", "imap.example.com", "993") + srv("dSmtp", "SMTP server and port (SSL)", "smtp.example.com", "465") : ""}
        <div class="acts"><span class="grow"></span><button class="btn go">Connect</button></div></form>`;
  return `<h3>Add a mail account</h3>${mail.tbDown ? note("Thunderbird isn't running, so its accounts aren't shown. Connect an account directly below, or open Thunderbird further down.") : ""}<h3 style="margin-top:14px">Directly with your provider</h3>
    ${note("Works without other apps, and it isn't limited by what Thunderbird's add-on can do. The login stays on this PC, in a file only you can read, and only goes to that provider's server.")}
    <div class="pform"><label>Provider<select id="dProv" data-act="dprov">${Object.entries(d.providers).map(([k, v]) => `<option value="${k}" ${k === mailProvider ? "selected" : ""}>${esc(v.name)}</option>`).join("")}</select></label></div>
    ${note(esc(p.how) + (p.link ? ` <a href="${esc(p.link)}" target="_blank" rel="noopener">Open that page</a>` : ""))}${form}${info("dInfo")}
    ${d.accounts.length ? `<h3 style="margin-top:18px">Connected directly</h3>` + rows(d.accounts.map((a) => `<div class="row"><span class="k">${esc(a.providerName)}</span><div class="t"><b>${esc(a.email)}</b></div><button class="btn" data-act="drm" data-id="${esc(a.id)}" data-email="${esc(a.email)}">Remove</button></div>`)) : ""}
    <h3 style="margin-top:22px">Through Thunderbird</h3>
    ${note(`If you already use Thunderbird: your sign-in stays there. ${esc(NAME())} only sees mail while Thunderbird runs and what its add-on can reach, so some mail may not work this way, like accounts Thunderbird can't add, or mail it hasn't downloaded.`)}
    ${d.thunderbird ? `${note("In Thunderbird: <b>☰ → Account Settings → Account Actions → Add Mail Account</b>. The account then shows up here by itself.")}<div class="acts"><button class="btn go" data-act="tbopen">Open Thunderbird</button></div>`
      : note("To use it, run <code>./install.sh --setup</code> and say yes to Thunderbird.")}`;
}
const when = (d) => { const x = new Date(d), t = new Date(); return x.toDateString() === t.toDateString() ? x.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  : x.toDateString() === addDays(t, -1).toDateString() ? "Yesterday" : x.toLocaleDateString([], { day: "numeric", month: "short" }); };
async function renderMail() {
  let main;
  if (mail.acc === "__add") {
    main = `<div class="addacc">${await addMailBox()}
      <h3 style="margin-top:22px">Which accounts ${esc(NAME())} may read</h3>${note("Switched off, it never reads that account: not here, not in the chat, not for the evening summary.")}` +
      rows(mail.accounts.map((a) => { const off = mail.off.includes(a.id);
        return `<div class="row"><span class="k">${esc((a.identities[0] || {}).email || a.type)}</span><div class="t"><b>${esc(a.name)}</b></div><button class="btn${off ? "" : " go"}" data-act="accread" data-acc="${esc(a.id)}" data-read="${off ? 1 : 0}">${off ? "Off" : "On"}</button></div>`; })) + "</div>";
  } else if (mail.open) {
    const m = mail.open;
    main = `<div class="reader"><div class="phead"><button class="btn" data-act="mailback">‹ Inbox</button><b>${esc(m.subject || "(no subject)")}</b></div>
      <div class="meta">From ${esc(m.from)}<br>To ${esc((m.to || []).join(", "))}<br>${new Date(m.date).toLocaleString()}${m.attachments && m.attachments.length ? "<br>Attachments: " + m.attachments.map((a) => esc(a.name)).join(", ") : ""}</div>
      <div class="acts"><button class="btn" data-act="mailsum">Summarize</button><button class="btn go" data-act="mailreply">Reply with ${esc(NAME())}</button><button class="btn" data-act="mailunread">Mark unread</button></div>
      <div class="mailbody">${esc(m.body)}${m.truncated ? "\n[…]" : ""}</div></div>`;
  } else {
    // the inbox, newest first: the last month at first, "Show older" goes further back (a year at most)
    mail.list = await (await fetch(`/api/mail/recent?days=${mail.days}&limit=300&account=${encodeURIComponent(mail.acc)}`)).json().catch(() => []);
    const more = mail.days < 365 ? `<div class="acts" style="margin-top:12px"><button class="btn" data-act="mailolder">Show older (${mail.days < 90 ? "3 months" : "a year"})</button></div>` : "";
    main = Array.isArray(mail.list) && mail.list.length ? `<p class="sample">${mail.list.length} mails in the inbox, last ${mail.days < 365 ? mail.days + " days" : "year"}</p>` +
        rows(mail.list.map((m) => `<button class="row pick${m.read ? "" : " unread"}" data-act="mailopen" data-id="${m.id}"><span class="k">${when(m.date)}</span><div class="t"><b>${esc(m.from)}</b><span>${esc(m.subject || "(no subject)")}</span></div><span></span></button>`)) + more
      : Array.isArray(mail.list) ? note(`No mail in the inbox in the last ${mail.days} days.`) + more : note("That didn't work: " + esc(mail.list.error || "Mail didn't load."));
  }
  body().innerHTML = `<div class="mailwrap">${mailRail()}<div class="mailmain">${main}</div></div>`;
}
// asks in today's chat (sent right away, or left in the ask bar for you to finish)
function askChat(text, now) { if (now) { open("chat"); send(text); } else { $("#q").value = text; $("#q").focus(); } }

// ---------- Projects: a list, and inside one the overview, files, runs and a message box ----------
const proj = { sel: null, d: null, to: "a", preview: null, poll: null };
const ST = { needs: ["st-wait", "Needs you"], active: ["st-active", "Active"], idle: ["st-idle", "Idle"], done: ["st-done", "Done"] };
async function loadProjects() { proj.sel = null; await renderProjects(); }
async function renderProjects() {
  clearInterval(proj.poll);
  if (proj.sel === "new") {
    body().innerHTML = `<div class="pnew"><button class="btn" data-act="proj" data-p="">‹ Projects</button><h3 style="margin-top:18px">New project</h3>
      ${note(`Give it a name and say in a sentence what it's about. ${esc(NAME())} then asks you a few questions in the chat and writes a clean spec for the project. You approve it before anything is saved.`)}
      <form class="pform" id="projNew"><label>Name<input id="pName" placeholder="e.g. Learn Rust" autocomplete="off" required></label>
      <label>What is it about?<textarea id="pAbout" rows="3" placeholder="e.g. I want to build a small CLI tool in Rust by Christmas"></textarea></label>
      <div class="acts"><button class="btn go">Start the interview</button></div></form></div>`;
    return;
  }
  if (proj.sel) return renderProject();
  const [list, fo] = await Promise.all([api("/api/projects"), api("/api/projects/folder")]);
  proj.folder = fo;
  $("#pmeta").textContent = fo.path.replace(/^\/home\/[^/]+/, "~");
  body().innerHTML = folderBar(fo) + `<div class="rows"><button class="row pick newp" data-act="proj" data-p="new"><span class="k">+</span><div class="t"><b>New project</b><span>${esc(NAME())} interviews you and writes the overview</span></div><span></span></button>` +
    list.map((p) => { const [c, l] = ST[p.state] || ST.idle;
      return `<button class="row pick ps ${c}" data-act="proj" data-p="${esc(p.name)}"><span class="k">▸</span><div class="t"><b>${esc(p.name)}</b><span>${p.files} file${p.files === 1 ? "" : "s"} · changed ${ago(p.updated)}${p.last_run ? " · last run " + ago(p.last_run) : ""}</span></div><span class="chip st ${c}">${l}</span></button>`; }).join("") + "</div>" +
    '<div class="stlegend"><span class="st-wait">Needs you</span><span class="st-active">Active</span><span class="st-idle">Idle</span><span class="st-done">Done</span></div>';
}
// where the projects live: shown on top, changed here (or with ./install.sh --setup); amber while still among your notes
const folderBar = (fo) => fo.in_notes
  ? `<div class="pfolder warn"><b>Your projects are still among your notes.</b><span>Give them their own folder, so a work run never sees your notes.</span>${folderForm(fo, "~/Amadeus/Projects")}</div>`
  : `<div class="pfolder"><span class="k">Folder</span><code>${esc(fo.path)}</code><button class="btn" data-act="pfchange">Change</button><div id="pfForm"></div></div>`;
const folderForm = (fo, suggest) => `<form class="pform pfform" id="pfSet"><div class="calrow"><label>New folder<input id="pfPath" value="${esc(suggest || fo.path)}" autocomplete="off"></label></div>
  ${fo.projects.length ? `<label class="chk"><input type="checkbox" id="pfMove" checked> Move my ${fo.projects.length} project${fo.projects.length === 1 ? "" : "s"} there (${fo.projects.map(esc).join(", ")})</label>` : ""}
  <div class="acts"><span class="grow"></span><button class="btn go">Use this folder</button></div><p class="sample" id="pfInfo"></p></form>`;
async function renderProject() {
  clearInterval(proj.poll);  // (each refresh starts its own: without this the old ones kept refreshing the page forever)
  const d = proj.d = await api(`/api/projects/${encodeURIComponent(proj.sel)}`);
  if (!d.error) post(`/api/projects/${encodeURIComponent(proj.sel)}/seen`, {}).catch(() => {});  // its results are on screen: no call about them later
  if (d.error) { proj.sel = null; return renderProjects(); }
  const [c, l] = ST[d.state] || ST.idle, last = d.runs[d.runs.length - 1];
  const items = d.messages.map((m) => ({ t: m.created, h: m.role === "user" ? `<div class="tline you"><span class="ts">${ago(m.created)}</span><div><b>You → ${esc(NAME())}</b><p>${esc(m.content)}</p></div></div>`
      : `<div class="tline"><span class="ts">${ago(m.created)}</span><div><b>${esc(NAME())}</b><div class="md">${md(stripMood(m.content))}</div></div></div>` }))
    .concat(d.runs.map((r) => ({ t: r.created, h: `<div class="tline you"><span class="ts">${ago(r.created)}</span><div><b>You → Claude Code</b><p>${esc((r.task || "").slice(0, 600))}</p></div></div>` +
      `<div class="tline${r.status === "running" ? " run" : ""}"><span class="ts">${r.finished ? ago(r.finished) : "now"}</span><div><b class="cc">Claude Code · ${r.status === "running" ? "working…" : r.status}${r.cost ? ` · $${r.cost.toFixed(2)}` : ""}</b>${r.summary ? `<div class="md">${md(r.summary)}</div>` : ""}</div></div>` })))
    .sort((a, b) => a.t - b.t);
  const q = d.state === "needs" && last ? `<div class="tline q"><span class="ts">${ago(last.finished || last.created)}</span><div><b>Questions for you</b>${note("The last run ended with questions. Your answer goes to Claude Code (through the privacy filter, and you see exactly what leaves first).")}
    <form class="qform" id="projAnswer"><input placeholder="Your answers, e.g. 1 yes, 2 Munich, 3 yes" aria-label="Answer"><button class="btn go">Continue the project</button></form></div></div>` : "";
  $("#pmeta").textContent = `${d.files.length} file${d.files.length === 1 ? "" : "s"}`;
  const readAt = body().scrollTop, atEnd = body().scrollHeight - readAt - body().clientHeight < 80;
  const chat = `<h3>Timeline</h3><div class="tlist">${items.map((i) => i.h).join("") || note(`Nothing here yet. Talk to ${esc(NAME())} about the project, or give Claude Code its first task.`)}${q}</div>
      <form class="pcomp${proj.to === "c" ? " cc" : ""}" id="projSend"><span class="tolabel">Send to</span><div class="to" role="radiogroup" aria-label="Send to">
        <button type="button" class="${proj.to === "a" ? "on" : ""}" role="radio" aria-checked="${proj.to === "a"}" data-act="to" data-who="a">${esc(NAME())}</button>
        <button type="button" class="${proj.to === "c" ? "on" : ""}" role="radio" aria-checked="${proj.to === "c"}" data-act="to" data-who="c">Claude Code</button></div>
        <p class="tohint">${proj.to === "c" ? "Starts or continues a Claude Code run in this project's folder. You see exactly what leaves the PC before it's sent." : `${esc(NAME())} knows this project and can hand work to Claude Code for you.`}</p>
        <textarea id="projText" rows="1" placeholder="${proj.to === "c" ? "Task or answer for Claude Code…" : `Message to ${esc(NAME())} about this project…`}" aria-label="Message" autocomplete="off" spellcheck="true"></textarea>
        <div class="pcrow"><button type="button" class="mic pmic" data-act="pmic" title="Talk: click to start, click again when you're done. The text goes into the box, you send it."><svg viewBox="0 0 24 24"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zM5 11a7 7 0 0 0 14 0M12 18v3"/></svg><span class="eq" aria-hidden="true"><i></i><i></i><i></i><i></i></span></button>
        <small class="pmhint">Enter sends · Shift+Enter new line</small><span class="grow"></span><button class="btn go psend">${proj.to === "c" ? "Send to Claude Code ›" : `Send to ${esc(NAME())} ›`}</button></div><div id="projPreview" class="preview" hidden></div><p class="sample" id="projInfo"></p></form>`;
  if (proj.ws) return renderWorkspace(d, chat, c, l);
  body().innerHTML = `<div class="phead"><button class="btn" data-act="proj" data-p="">‹ Projects</button><b>${esc(d.name)}</b><span class="chip st ${c}">${l}</span><span class="grow"></span>
      <button class="btn" data-act="projdone" data-done="${d.state === "done" ? 0 : 1}">${d.state === "done" ? "Open again" : "Mark done"}</button><button class="btn" data-act="projterm" title="Opens a terminal with Claude Code in this project's folder">Open in Claude Code</button><button class="btn go" data-act="wsopen" title="Files, editor and chat side by side: watch the agent work and edit along">Open workspace</button></div>
    <div class="pgrid"><div class="pside"><h3>Overview</h3><div class="ov md">${d.overview ? md(d.overview) : note("No Overview.md yet.")}</div>
      <h3 style="margin-top:18px">Files</h3><div class="files">${d.files.map((f) => `<div><button class="linkfile" data-act="projfile" data-f="${esc(f.path)}">${esc(f.path)}</button><small>${Math.max(1, Math.round(f.size / 1024))} KB</small></div>`).join("") || note("No files yet.")}</div><div id="projFile"></div></div>
    <div class="pmain">${chat}</div></div>`;
  // down to the newest only when you open it, or something new came while you were at the end: never while you read further up
  const tl = body().querySelector(".tlist"), count = tl ? tl.children.length : 0;
  if (tl && tl.lastElementChild && (proj.shown !== d.name || (atEnd && count !== proj.count))) tl.lastElementChild.scrollIntoView({ block: "nearest" });
  else body().scrollTop = readAt;
  proj.shown = d.name; proj.count = count;
  if (d.running) proj.poll = setInterval(async () => { post(`/api/projects/${encodeURIComponent(d.name)}/seen`, {}).catch(() => {}); const x = await api(`/api/projects/${encodeURIComponent(d.name)}`); if (!x.running && proj.sel === d.name && curView === "projects") renderProject(); }, 5000);
}
// to Claude Code: first the privacy filter's preview (exactly what leaves), then the send you confirm
async function toClaude(text, info) {
  const name = proj.d.name;
  if (!proj.preview || proj.preview.text !== text) {
    const pv = await post(`/api/projects/${encodeURIComponent(name)}/claude`, { text });
    if (pv.error) { info.textContent = "That didn't work: " + pv.error; return; }
    proj.preview = { text, preview: pv.preview };
    const box = $("#projPreview"); box.hidden = false;
    box.innerHTML = `<b>Exactly this goes to Claude Code${pv.findings.length ? ` (the privacy filter replaced: ${esc(pv.findings.join(", "))})` : ""}:</b><div>${esc(pv.preview)}</div>
      <div class="acts"><button type="button" class="btn" data-act="pvcancel">Cancel</button><button type="button" class="btn go cc" data-act="pvsend">Send it</button></div>`;
    return;
  }
  const r = await post(`/api/projects/${encodeURIComponent(name)}/claude`, { text, confirm: true, preview: proj.preview.preview });
  proj.preview = null;
  if (r.error) { info.textContent = "That didn't work: " + r.error; return; }
  subtitle(r.resumed ? "Claude Code continues the project." : "Claude Code started on the project.");
  renderProject();
}
async function toAssistant(text) {
  const name = proj.d.name, { id } = await post(`/api/projects/${encodeURIComponent(name)}/chat`, {});
  const tl = body().querySelector(".tlist");
  tl.insertAdjacentHTML("beforeend", `<div class="tline you"><span class="ts">now</span><div><b>You → ${esc(NAME())}</b><p>${esc(text)}</p></div></div><div class="tline"><span class="ts">now</span><div><b>${esc(NAME())}</b><div class="md">…</div></div></div>`);
  const out = tl.lastElementChild.querySelector(".md"); out.scrollIntoView({ block: "nearest" });
  setMode("think"); let acc = "";
  try {
    const r = await fetch(`/api/conversations/${id}/messages`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }) });
    const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = chunk.match(/^event: (.*)$/m)?.[1], data = JSON.parse(chunk.match(/^data: (.*)$/m)?.[1] || "{}");
        if (ev === "token") { acc += data; setMode("speak"); core.talk(); out.innerHTML = md(stripMood(acc)); subtitle(acc); }
        if (ev === "approval") { counts(); subtitle(`I need your OK first: ${data.summary}`); }
        if (ev === "error") out.textContent = "That didn't work: " + data.message;
      }
    }
  } finally { setTimeout(() => setMode("idle"), 500); if (proj.sel === name && curView === "projects") renderProject(); }
}

// ---------- clicks and forms of these views ----------
function calPick(a) { if (a.dataset.act !== "caltab") return; cal.tab = a.dataset.t; cal.edit = null; cal.scrolled = false; a.closest(".seg").classList.toggle("right", cal.tab === "rem"); setTimeout(loadCalendar, 180); }
body().addEventListener("click", async (e) => {
  const a = e.target.closest("[data-act]"); if (!a) return;
  const act = a.dataset.act;
  if (act === "remrm") { a.disabled = true; await post(`/api/reminders/${a.dataset.id}/delete`); loadReminders(); counts(); }
  if (act === "calweek") { cal.scrolled = false; const n = Number(a.dataset.d); cal.week = n ? addDays(cal.week, n) : monday(new Date()); cal.edit = null; loadCalendar(); }
  if (act === "calnew") { cal.edit = "new"; calForm(null); }
  if (act === "calopen") { cal.edit = a.dataset.id; calForm(cal.occ.find((o) => o.id === a.dataset.id)); body().scrollTop = 0; }
  if (act === "calcancel") { cal.edit = null; $("#calEdit").innerHTML = ""; }
  if (act === "caldel") {
    const o = cal.occ.find((x) => x.id === cal.edit);
    if (!confirm(`Delete "${o ? o.title : "this event"}"${o && o.repeat ? " (the whole series)" : ""}?`)) return;
    await api(`/api/calendar/${cal.edit}`, { method: "DELETE" }); cal.edit = null; loadCalendar(); nextUp();
  }
  if (act === "acc") { mail.acc = a.dataset.acc; mail.open = null; mail.days = 30; renderMail(); }
  if (act === "mailolder") { mail.days = mail.days < 90 ? 90 : 365; a.textContent = "Loading…"; renderMail(); }
  if (act === "accread") { const r = await post("/api/mail/accounts", { id: a.dataset.acc, read: a.dataset.read === "1" }); mail.off = r.off; renderMail(); mailCount(); }
  if (act === "dms") {
    const r = await post("/api/mail/direct/microsoft", {});
    if (r.error) return say("dInfo", "That didn't work: " + r.error);
    window.open(r.url, "_blank");
    say("dInfo", "Finish signing in in your browser, then come back here.");
  }
  if (act === "drm") {
    if (!confirm(`Remove ${a.dataset.email}? ${NAME()} forgets the login. Your mail stays at your provider.`)) return;
    await post("/api/mail/direct/remove", { id: a.dataset.id }); return loadMail();
  }
  if (act === "tbopen") { await post("/api/mail/thunderbird", {}); a.textContent = "Opening Thunderbird…"; }
  if (act === "mailopen") {
    const id = Number(a.dataset.id), m = await (await fetch(`/api/mail/message/${id}`)).json();
    if (m.error) { subtitle("That didn't work: " + m.error); return; }
    mail.open = m; renderMail();
    if (!m.read) { post("/api/mail/markread", { ids: [id], read: true }); mail.unread[m.accountId] = Math.max(0, (mail.unread[m.accountId] || 1) - 1); mailCount(); }
  }
  if (act === "mailback") { mail.open = null; renderMail(); }
  if (act === "mailunread") { await post("/api/mail/markread", { ids: [mail.open.id], read: false }); mail.open = null; renderMail(); mailCount(); }
  if (act === "mailsum") askChat(`Summarize email [${mail.open.id}] ("${mail.open.subject}") in a few sentences and tell me if I need to do anything.`, true);
  if (act === "mailreply") askChat(`Draft a reply to email [${mail.open.id}] ("${mail.open.subject}") from ${mail.open.from}. My points: `, false);
  if (act === "pfchange") $("#pfForm").innerHTML = folderForm(proj.folder);
  if (act === "proj") { proj.sel = a.dataset.p || null; proj.preview = null; closeWorkspace(); renderProjects(); body().scrollTop = 0; }
  if (act === "projdone") { await post(`/api/projects/${encodeURIComponent(proj.d.name)}/state`, { done: a.dataset.done === "1" }); renderProject(); }
  if (act === "projterm") { const r = await post(`/api/projects/${encodeURIComponent(proj.d.name)}/terminal`, {}); $("#projInfo").textContent = r.error ? "Couldn't open it: " + r.error : "Opened Claude Code in a terminal."; }
  if (act === "projfile") {
    const f = await api(`/api/projects/${encodeURIComponent(proj.d.name)}/file?path=${encodeURIComponent(a.dataset.f)}`);
    $("#projFile").innerHTML = `<div class="filebox"><div class="phead"><b>${esc(a.dataset.f)}</b><span class="grow"></span><button class="btn" data-act="projfileclose">Close</button></div>` +
      (f.error ? note("That didn't work: " + esc(f.error)) : f.binary ? note("Not a text file: open it in the file manager.") : /\.md$/i.test(a.dataset.f) ? `<div class="md">${md(f.text)}</div>` : `<pre>${esc(f.text)}</pre>`) + "</div>";
  }
  if (act === "projfileclose") $("#projFile").innerHTML = "";
  if (act === "to") { proj.to = a.dataset.who; proj.preview = null; const keep = $("#projText").value; await renderProject(); $("#projText").value = keep; fitText($("#projText")); $("#projText").focus(); }
  if (act === "pmic") dictate.toggle();
  if (act === "pvcancel") { proj.preview = null; $("#projPreview").hidden = true; }
  if (act === "pvsend") toClaude(proj.preview.text, $("#projInfo"));
});
body().addEventListener("submit", async (e) => {
  if (e.target.id === "msApp") {
    e.preventDefault();
    const r = await post("/api/mail/direct/microsoft-app", { client_id: $("#msAppId").value });
    if (r.error) return say("msInfo", "That didn't work: " + r.error);
    mail.acc = "__add"; loadMail();
    return;
  }
  if (e.target.id === "remNew") {
    e.preventDefault();
    const r = await post("/api/reminders", { text: $("#remText").value, when: $("#remWhen").value });
    if (r.error) return ($("#remInfo").textContent = "That didn't work: " + r.error);
    loadReminders();
    return;
  }
  const f = e.target;
  if (f.id === "calForm") { e.preventDefault(); calSave(f); }
  if (f.id === "pfSet") {
    e.preventDefault();
    const path = $("#pfPath").value.trim(), move = !!($("#pfMove") && $("#pfMove").checked), fo = proj.folder;
    if (move && !confirm(`Move these projects to ${path}?\n\n${fo.projects.join("\n")}\n\nThey are moved, not copied: afterwards they're only in the new folder. Their Claude Code sessions move with them.`)) return;
    $("#pfInfo").textContent = move ? "Moving…" : "Saving…";
    const r = await post("/api/projects/folder", { path, move });
    if (r.error) { $("#pfInfo").textContent = "That didn't work: " + r.error; return; }
    subtitle(r.moved && r.moved.length ? `Moved ${r.moved.length} project(s) to ${r.path}.` : `Projects now live in ${r.path}.`);
    renderProjects();
  }
  if (f.id === "projNew") {
    e.preventDefault();
    const n = $("#pName").value.trim(), about = $("#pAbout").value.trim(); if (!n) return;
    open("chat"); send(`New project: ${n}. ${about}`.trim());
  }
  if (f.id === "projAnswer" || f.id === "projSend") {
    e.preventDefault();
    const inp = f.querySelector("input, textarea"), text = inp.value.trim(); if (!text) return;
    if (f.id === "projAnswer" || proj.to === "c") return toClaude(text, $("#projInfo"));
    inp.value = ""; fitText(inp); toAssistant(text);
  }
});

// The project's message box grows with what you write (up to about half the screen, then it scrolls), like a chat box
function fitText(t) {
  if (!t || t.tagName !== "TEXTAREA") return;
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight + 2, Math.max(120, innerHeight * 0.45)) + "px";
}
document.addEventListener("input", (e) => { if (e.target.id === "projText") fitText(e.target); });
document.addEventListener("keydown", (e) => {
  if (e.target.id !== "projText" || e.key !== "Enter" || e.shiftKey || e.isComposing) return;
  e.preventDefault(); e.target.form.requestSubmit();
});

// Adding a mail account directly
document.addEventListener("change", (e) => { if (e.target.id === "dProv") { mailProvider = e.target.value; renderMail(); } });
document.addEventListener("submit", async (e) => {
  if (e.target.id !== "dForm") return;
  e.preventDefault();
  const v = (id) => { const x = document.getElementById(id); return x ? x.value.trim() : ""; }, pass = document.getElementById("dPass");
  say("dInfo", "Trying to sign in…");
  const r = await post("/api/mail/direct/add", { provider: mailProvider, email: v("dEmail"), password: pass.value,
    imap: { host: v("dImapHost"), port: Number(v("dImapPort") || 993), security: "ssl" }, smtp: { host: v("dSmtpHost"), port: Number(v("dSmtpPort") || 465), security: "ssl" } });
  pass.value = "";
  if (r.error) return say("dInfo", "That didn't work: " + r.error);
  mail.acc = null; loadMail();
});
