// The first start of the Mac app, where no installer ran: Ollama, your folder, and a model.
(async () => {
  await window.IDENTITY;
  let s = await api("/api/setup");
  if (!s.needed) return;
  const box = document.createElement("div");
  box.className = "setup";
  document.body.append(box);
  let chosen = "", folder = s.folder, asked = false;
  const page = (html) => { box.innerHTML = `<div class="setup-in"><h2>Set up ${esc(NAME())}</h2>${html}</div>`; };
  const progress = (j) => `<p class="prose">${esc(j.text || "Working…")}</p>${j.pct == null ? "" : `<div class="setup-bar"><i style="width:${j.pct}%"></i></div>`}`;
  const failed = (j) => j.done && j.error ? `<p class="prose setup-bad">${esc(j.error)}</p>` : "";
  const tell = async (action, extra) => {
    const r = await post("/api/setup", { action, ...extra });
    if (r.error) { box.querySelector(".setup-msg").textContent = r.error; return; }
    asked = false; step();
  };
  async function step() {
    s = await api("/api/setup");
    const j = s.job, busy = j.kind && !j.done, again = () => setTimeout(step, 1200);
    if (j.kind === "begin" && j.done && !j.error) {
      page(`<p class="prose">Everything is ready. Starting up…</p>`);
      return setTimeout(() => location.reload(), 6000);
    }
    if (busy) { page(progress(j)); return again(); }
    if (s.ollama !== "running") {
      page(`<p class="prose">${esc(NAME())} thinks with a model that runs on this computer, through a free app called Ollama. ${s.ollama === "installed" ? "It's installed but not running." : "It isn't installed yet."}</p>
        ${j.kind === "ollama" ? failed(j) : ""}<p class="setup-msg prose setup-bad"></p>
        <div class="acts"><span class="grow"></span><button class="btn go" id="suGo">${s.can_install && s.ollama !== "installed" ? "Install Ollama" : "Start Ollama"}</button></div>`);
      $("#suGo").onclick = () => tell("ollama");
      return;
    }
    if (!s.picks.length) {
      if (j.kind === "scan" && j.error) {
        page(`${failed(j)}<div class="acts"><span class="grow"></span><button class="btn go" id="suGo">Try again</button></div>`);
        $("#suGo").onclick = () => tell("scan");
        return;
      }
      if (!asked) { asked = true; await post("/api/setup", { action: "scan" }); }
      page(`<p class="prose">Checking what this computer can run…</p>`);
      return again();
    }
    chosen = chosen || s.picks[0].model;
    page(`<p class="prose">Your notes and projects stay in one folder of plain files. Any notes app can open the Notes folder inside it.</p>
      <form class="pform" id="suForm"><label>Your folder<input id="suFolder" value="${esc(folder)}" autocomplete="off" spellcheck="false"></label></form>
      <p class="prose">Pick the model. I checked these against your memory and speed, and the first is the one I'd take.</p>
      <div class="setup-picks">${s.picks.map((p, i) => `<label class="setup-pick"><input type="radio" name="suModel" value="${esc(p.model)}" ${p.model === chosen ? "checked" : ""}>
        <span><b>${esc(p.model)}</b>${i === 0 ? ' <em>recommended</em>' : ""}<br>${p.size} GB download${p.speed ? `, about ${p.speed} words per second` : ""}. ${esc(p.about)}</span></label>`).join("")}</div>
      ${j.kind === "begin" ? failed(j) : ""}<p class="setup-msg prose setup-bad"></p>
      <div class="acts"><span class="grow"></span><button class="btn go" id="suGo">Set it up</button></div>`);
    box.querySelectorAll("[name=suModel]").forEach((r) => (r.onchange = () => { chosen = r.value; }));
    $("#suFolder").oninput = (e) => { folder = e.target.value; };
    $("#suGo").onclick = () => tell("begin", { model: chosen, folder });
  }
  step();
})();
