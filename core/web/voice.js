// Voice in the window: optional voice lines you added (a "voice pack": which clip plays on which action or word;
// replies themselves are text), the avatar's mouth follows the audio, and push-to-talk records you
// (mic button or Ctrl+Space).
(() => {
  const V = { on: true, queue: [], playing: false, sent: 0, lang: "en", rec: null, chunks: [], ctx: null, onText: null, busy: null,
    pack: {} };  // ~/.local/share/amadeus/voice/clips/voice-pack.json (empty: no clips)
  fetch("/api/voice/pack").then((r) => r.json()).then((p) => { V.pack = p || {}; }).catch(() => {});
  const pick = (list) => (list && list.length ? list[Math.floor(Math.random() * list.length)] : null);
  // voice lines are on unless you mute them (🔇); the setting is shared by the dashboard and the small window
  try { V.on = localStorage.getItem("voice") !== "off"; } catch { V.on = true; }
  addEventListener("storage", (e) => { if (e.key === "voice") { V.on = e.newValue === "on"; if (!V.on) V.queue = []; window.dispatchEvent(new Event("voicechange")); } });

  const WORDS = { de: /\b(und|ich|nicht|du|ist|der|die|das|ein|eine|mit|für|auf|noch|heute|ja|nein|bitte)\b/gi,
    es: /\b(el|la|los|las|que|de|y|en|un|una|por|para|con|hoy|sí|no|qué|está|eres)\b/gi,
    en: /\b(the|and|you|is|are|to|of|it|not|what|for|with|today|yes|please)\b/gi };
  function detect(text) {
    let best = V.lang, n = 0;
    for (const [l, re] of Object.entries(WORDS)) { const c = (text.match(re) || []).length; if (c > n) { n = c; best = l; } }
    return n >= 2 ? best : V.lang;
  }
  const clean = (t) => t.replace(/```[\s\S]*?```/g, " (code) ").replace(/\[mood:\s*\w*\]?/gi, "").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "").replace(/[*_`#>|~]/g, "").replace(/^\s*[-•]\s+/gm, "").replace(/\s+/g, " ").trim();

  function analyser(audio) {
    try {
      V.ctx = V.ctx || new AudioContext();
      const src = V.ctx.createMediaElementSource(audio), an = V.ctx.createAnalyser();
      an.fftSize = 512; src.connect(an); an.connect(V.ctx.destination);
      const buf = new Uint8Array(an.fftSize);
      const tick = () => {
        if (audio.paused || audio.ended) return;
        an.getByteTimeDomainData(buf);
        let peak = 0; for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
        if (peak > 10 && window.Avatar) Avatar.talk();  // the mouth moves with the actual audio
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    } catch { const t = setInterval(() => (audio.paused || audio.ended ? clearInterval(t) : window.Avatar && Avatar.talk()), 150); }
  }

  async function next() {
    if (V.playing || !V.queue.length) return;
    V.playing = true;
    const item = V.queue.shift();
    try {
      if (!item.clip) throw new Error("no clip");  // replies are text; only voice-pack clips are played
      const a = new Audio(`/voice-clip/${item.clip}.ogg`);
      analyser(a);
      await new Promise((res) => { a.onended = res; a.onerror = res; a.play().catch(res); });
    } catch (e) { console.warn("voice:", e.message); }
    V.playing = false;
    next();
  }

  function enqueue() {}  // text is never read aloud (replies are text); kept so older callers do nothing

  window.Voice = {
    get on() { return V.on; },
    toggle() { V.on = !V.on; try { localStorage.setItem("voice", V.on ? "on" : "off"); } catch {} if (!V.on) this.stop();
      window.dispatchEvent(new Event("voicechange")); return V.on; },
    stop() { V.queue = []; },
    // feed the growing reply while it streams; complete sentences are spoken right away
    start() { V.sent = 0; },
    stream(full) {
      const text = full.replace(/\[mood:[^\]]*\]?/gi, "");
      for (;;) {
        const rest = text.slice(V.sent), m = rest.match(/[.!?…](\s|$)/);
        if (!m) return;
        const end = m.index + m[0].length;
        if (end === rest.length && !/\s$/.test(rest)) return;                     // could still be "3.5": wait for more
        if ((text.slice(0, V.sent + end).match(/```/g) || []).length % 2) return;  // inside a code block: wait
        enqueue(rest.slice(0, end)); V.sent += end;
      }
    },
    finish(full) { const text = full.replace(/\[mood:[^\]]*\]?/gi, ""); enqueue(text.slice(V.sent)); V.sent = text.length; },
    say(text) { enqueue(text); },
    clip(name) { if (V.on) { V.queue.push({ clip: name }); next(); } },
    // short lines for actions (hello = you answered a call, approved, rejected, failed; only when sounds are on). Replies are never read aloud.
    sfx(action) {
      const line = pick((V.pack.actions || {})[action]);
      if (line) this.clip(line);
    },
    // reactions to things YOU say (the pack's "hear" list: [regex, [clips]]); at most one per message
    hear(text) {
      const t = (text || "").toLowerCase();
      const eggs = (V.pack.hear || []).map(([re, lines]) => { try { return [new RegExp(re, "i"), lines]; } catch { return null; } }).filter(Boolean);
      for (const [re, lines] of eggs) if (re.test(t)) { this.clip(pick(lines)); return true; }
      return false;
    },
    // reactions to its own replies (the pack's "reply" list)
    react(reply) {
      const t = (reply || "").replace(/\[mood:[^\]]*\]?/gi, "").trim();
      for (const [re, lines] of V.pack.reply || []) { try { if (new RegExp(re, "i").test(t)) { this.clip(pick(lines)); return; } } catch {} }
    },
    get ringtone() { return V.pack.ringtone || ""; },
    // push-to-talk: start() on press, stop() on release → onText(text, lang)
    // listen(true) (after the wake word): stops by itself 2 s after you stop talking (8 s if nothing is said, 60 s max)
    async listen(auto = false) {
      if (V.rec) return;
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
        if (auto) autoStop(stream);
        V.chunks = [];
        // Opus in WebM: WebKit's default (AAC in MP4) records nothing on this system
        const type = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"].find((t) => MediaRecorder.isTypeSupported(t));
        V.rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
        V.rec.ondataavailable = (e) => e.data.size && V.chunks.push(e.data);
        V.rec.onstop = async () => {
          stream.getTracks().forEach((t) => t.stop());
          const blob = new Blob(V.chunks, { type: V.rec.mimeType || "audio/webm" }); V.rec = null;
          if (blob.size < 2000) { V.busy && V.busy(false); return V.onText && V.hint && V.hint("I didn't catch that: hold the mic button while you speak."); }
          V.busy && V.busy(true);
          try {
            const r = await fetch("/api/voice/stt", { method: "POST", headers: { "content-type": blob.type }, body: blob });
            const d = await r.json();
            if (d.language) V.lang = d.language;
            if (d.text && V.onText) V.onText(d.text, d.language);
            else if (V.hint) V.hint(d.error ? "Listening failed: " + d.error : "I didn't catch that, try again a bit louder.");
          } catch (e) { console.warn("stt:", e.message); }
          V.busy && V.busy(false);
        };
        V.rec.start();
        V.queue = [];  // it stops talking when you start
      } catch (e) { V.hint ? V.hint("Microphone not available: " + e.message) : console.warn(e); }
    },
    release() { if (V.rec && V.rec.state === "recording") V.rec.stop(); },
    get recordingAuto() { return !!V.auto; },
    get recording() { return !!V.rec; },
    set onText(fn) { V.onText = fn; },
    set onBusy(fn) { V.busy = fn; },
    set onSpeak(fn) { V.speaking = fn; },
    set onHint(fn) { V.hint = fn; },
  };

  function autoStop(stream) {
    // Ends the recording when you're done talking: 2 s of quiet after you spoke (short pauses between words are fine),
    // 8 s if you say nothing, 60 s at most. "Quiet" is measured against the room's own noise, so a soft voice or a
    // quiet microphone still counts as talking. Clicking the mic sends right away.
    const ctx = new AudioContext(), src = ctx.createMediaStreamSource(stream), an = ctx.createAnalyser();
    an.fftSize = 1024; src.connect(an);
    const buf = new Float32Array(an.fftSize), t0 = Date.now();
    let spoke = false, lastLoud = Date.now(), floor = 1, level = 0;
    V.auto = true;
    const tick = setInterval(() => {
      an.getFloatTimeDomainData(buf);
      const rms = Math.sqrt(buf.reduce((s, x) => s + x * x, 0) / buf.length), now = Date.now();
      level = 0.6 * level + 0.4 * rms;                      // smooth over ~0.3 s, so gaps between syllables don't count
      floor = Math.min(floor * 1.002 + 1e-5, Math.max(level, 1e-4));  // slowly follows the quietest level = room noise
      if (level > Math.max(floor * 3, 0.003)) { spoke = true; lastLoud = now; }
      const done = (spoke && now - lastLoud > 2000) || (!spoke && now - t0 > 8000) || now - t0 > 60000;
      if (done || !V.rec) { clearInterval(tick); ctx.close(); V.auto = false; document.body.classList.remove("listening"); if (V.rec) Voice.release(); }
    }, 100);
  }

  // Ctrl+Space = hold to talk
  let held = false;
  addEventListener("keydown", (e) => { if (e.ctrlKey && e.code === "Space" && !held) { held = true; e.preventDefault(); Voice.listen(); document.body.classList.add("listening"); } });
  addEventListener("keyup", (e) => { if (held && (e.code === "Space" || e.key === "Control")) { held = false; Voice.release(); document.body.classList.remove("listening"); } });
})();
