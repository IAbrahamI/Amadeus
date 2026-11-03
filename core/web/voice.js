// Talking to her in the window: push-to-talk (the mic, holding the core, or Ctrl+Space) records you and turns it
// into text (local Whisper through the voice service). Her answers are spoken by speak.js; there are no voice lines.
(() => {
  const V = { lang: "en", rec: null, chunks: [], onText: null, busy: null, hint: null, auto: false };

  window.Voice = {
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
      } catch (e) { V.hint ? V.hint("Microphone not available: " + e.message) : console.warn(e); }
    },
    release() { if (V.rec && V.rec.state === "recording") V.rec.stop(); },
    get recordingAuto() { return !!V.auto; },
    get recording() { return !!V.rec; },
    set onText(fn) { V.onText = fn; },
    get onText() { return V.onText; },  // the wake word hands its text to the page through this
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
