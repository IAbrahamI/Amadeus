// The setup, the first time the dashboard opens where no installer ran: a popup you finish before anything else.
// The AI engine (Ollama), your folder and a model, then mail. firstrun.py does the work.
(async () => {
  await window.IDENTITY;
  let s = await api("/api/setup");
  if (!s.needed) return;
  const STEPS = ["Engine", "Model", "Mail", "Ready"];
  const veil = document.createElement("div");
  veil.className = "setup";
  document.body.append(veil);
  let chosen = "", folder = s.folder, provider = "gmail", mailDone = false;
  const page = (at, html) => {
    const keep = veil.querySelector("input:focus");
    if (keep) return;  // you're typing: the next look comes after that
    veil.innerHTML = `<div class="setup-box" role="dialog" aria-modal="true" aria-labelledby="suTitle">
      <div class="setup-head"><span class="setup-tag" id="suTitle">SETUP_</span><span class="setup-sub">${esc(NAME())}, first start</span></div>
      <ol class="setup-steps">${STEPS.map((n, i) => `<li class="${i < at ? "done" : i === at ? "on" : ""}">${n}</li>`).join("")}</ol>
      <div class="setup-body">${html}</div></div>`;
  };
  const text = (t) => `<p class="setup-p">${t}</p>`;
  const trouble = (t) => (t ? `<p class="setup-p setup-bad">${esc(t)}</p>` : "");
  const buttons = (html) => `<p class="setup-p setup-bad setup-msg"></p><div class="setup-acts">${html}</div>`;
  const working = (at, j) => page(at, text(esc(j.text || "Working…")) + (j.pct == null ? `<div class="setup-bar busy"><i></i></div>` : `<div class="setup-bar"><i style="width:${j.pct}%"></i></div><p class="setup-p setup-dim">${j.pct}%</p>`));
  const tell = async (action, extra) => {
    const r = await post("/api/setup", { action, ...extra });
    if (r.error) { const m = veil.querySelector(".setup-msg"); if (m) m.textContent = r.error; return false; }
    step();
    return true;
  };

  async function mailStep() {
    const d = await api("/api/mail/direct"), p = d.providers[provider], simple = p.auth !== "microsoft" && !p.manual;
    page(2, `${text(`Want ${esc(NAME())} to read and draft your mail? This is optional, and it only sends what you approve. The login stays on this computer.`)}
      ${d.accounts.length ? `<div class="setup-pick"><span><b>Connected</b><br>${d.accounts.map((a) => esc(a.email)).join("<br>")}</span></div>` : ""}
      <form class="pform" id="suMail"><label>Provider<select id="suProv">${Object.entries(d.providers).map(([k, v]) => `<option value="${k}" ${k === provider ? "selected" : ""}>${esc(v.name)}</option>`).join("")}</select></label>
      ${simple ? `<p class="setup-p setup-dim">${esc(p.how)}${p.link ? ` <a href="${esc(p.link)}" target="_blank" rel="noopener">Open that page</a>` : ""}</p>
        <label>Address<input id="suEmail" autocomplete="off" spellcheck="false"></label><label>App password<input id="suPass" type="password" autocomplete="off"></label>`
        : text("You can connect this one on the Mail page once setup is done.")}
      ${buttons(`${simple ? `<button class="btn" type="submit">Connect</button>` : ""}<span class="grow"></span><button class="btn go" type="button" id="suNext">${d.accounts.length ? "Continue" : "Skip for now"}</button>`)}</form>`);
    $("#suProv").onchange = (e) => { provider = e.target.value; mailStep(); };
    $("#suNext").onclick = () => { mailDone = true; step(); };
    $("#suMail").onsubmit = async (e) => {
      e.preventDefault();
      if (!simple) return;
      const m = veil.querySelector(".setup-msg"), pass = $("#suPass");
      m.textContent = "Trying to sign in…";
      const r = await post("/api/mail/direct/add", { provider, email: $("#suEmail").value.trim(), password: pass.value, imap: {}, smtp: {} });
      pass.value = "";
      if (r.error) { m.textContent = "That didn't work: " + r.error; return; }
      document.activeElement.blur();
      mailStep();
    };
  }

  async function step() {
    s = await api("/api/setup");
    const j = s.job || {}, busy = j.kind && !j.done, again = () => setTimeout(step, 1200);
    if (busy) { working(j.kind === "begin" || s.picks.length ? 1 : 0, j); return again(); }
    if (s.ollama !== "running" && !s.model_ready) {
      const has = s.ollama === "installed";
      page(0, `${text(`${esc(NAME())} thinks with an AI model that runs on this computer, so your conversations stay here. A free app called Ollama runs that model. ${has ? "It's installed, but not running." : "I'll install it for you."}`)}
        ${j.kind === "ollama" ? trouble(j.error) : ""}${buttons(`<span class="grow"></span><button class="btn go" id="suGo">${s.can_install && !has ? "Install Ollama" : "Start Ollama"}</button>`)}`);
      $("#suGo").onclick = () => tell("ollama");
      return;
    }
    if (!s.model_ready) {
      if (!s.picks.length) {
        if (j.kind === "scan" && j.error) {
          page(1, `${trouble(j.error)}${buttons(`<span class="grow"></span><button class="btn go" id="suGo">Try again</button>`)}`);
          $("#suGo").onclick = () => tell("scan");
          return;
        }
        await post("/api/setup", { action: "scan" });  // (nothing is running here: that returned above)
        page(1, `${text("Checking what this computer can run…")}<div class="setup-bar busy"><i></i></div>`);
        return again();
      }
      chosen = chosen || s.picks[0].model;
      page(1, `${text("Your notes and projects stay in one folder of plain files, and any notes app can open them.")}
        <form class="pform"><label>Your folder<input id="suFolder" value="${esc(folder)}" autocomplete="off" spellcheck="false"></label></form>
        ${text(`Now pick the model. I measured this computer, and the first one is what I'd use.`)}
        <div class="setup-picks">${s.picks.map((p, i) => `<label class="setup-pick"><input type="radio" name="suModel" value="${esc(p.model)}" ${p.model === chosen ? "checked" : ""}>
          <span><b>${esc(p.model)}</b>${i === 0 ? '<em class="setup-rec">recommended</em>' : ""}<br>${p.size} GB download${p.speed ? `, about ${p.speed} words per second` : ""}<br><small>${esc(p.about)}</small></span></label>`).join("")}</div>
        ${s.too_old ? trouble("Your Ollama is too old for this model. I can update it, or you can pick another model.") : j.kind === "begin" || j.kind === "ollama" ? trouble(j.error) : ""}
        ${buttons(`${s.too_old && s.can_install ? `<button class="btn" type="button" id="suUpdate">Update Ollama</button>` : ""}<span class="grow"></span><button class="btn go" id="suGo">Download and set up</button>`)}`);
      if ($("#suUpdate")) $("#suUpdate").onclick = () => tell("update_ollama");
      veil.querySelectorAll("[name=suModel]").forEach((r) => (r.onchange = () => { chosen = r.value; }));
      $("#suFolder").oninput = (e) => { folder = e.target.value; };
      $("#suGo").onclick = () => tell("begin", { model: chosen, folder });
      return;
    }
    if (!mailDone) return mailStep();
    page(3, `${text(`That's it. ${esc(NAME())} is ready, and you can change all of this later in Settings.`)}${buttons(`<span class="grow"></span><button class="btn go" id="suGo">Start</button>`)}`);
    $("#suGo").onclick = async () => {
      const r = await post("/api/setup", { action: "finish" });
      if (r.error) { veil.querySelector(".setup-msg").textContent = r.error; return; }
      page(3, `${text("Starting up…")}<div class="setup-bar busy"><i></i></div>`);
      const back = async () => { try { const h = await api("/api/setup"); if (!h.needed) return location.reload(); } catch {} setTimeout(back, 1000); };
      setTimeout(back, 2500);
    };
  }
  await step();
  post("/api/setup", { action: "shown" });
})();
