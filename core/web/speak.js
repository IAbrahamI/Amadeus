// Reading answers aloud while they are written (the dashboard and the mini core): every finished sentence goes to
// the voice right away and the next one is prepared while the current one plays, with a short breath in between.
// The server turns each piece into what a person would say (speech.py). Code, tables and long lists stay in the chat,
// and after a couple of short sentences (about 250 characters) it says the rest is in the chat. The text can type in, in step with the voice.
// Hooks: busy() (the answer is still coming), talk() (a voice pulse), speaking(on), idle(), failed(error), strip(text).
window.makeAloud = (h) => {
  const A = {
    active: false, gen: 0, queue: [], playing: null, taken: 0, spoken: 0, inCode: false, items: 0, saidCode: false, cut: false,
    shown: 0, reveal: null, done: null,
    start() {
      A.stop();
      Object.assign(this, { active: true, gen: this.gen + 1, queue: [], taken: 0, spoken: 0, inCode: false, items: 0, saidCode: false, cut: false, shown: 0, reveal: null, done: null });
    },
    // the reply so far; done = it's complete (the last piece needs no full stop)
    feed(text, done) {
      if (!this.active || this.cut) return;
      const t = h.strip(text);
      for (;;) {
        const rest = t.slice(this.taken), nl = rest.indexOf("\n");
        if (nl < 0 && !done) {  // an unfinished line: speak its finished sentences already
          const m = !this.inCode && !/^\s*(?:[-*+]|\d+[.)]|\||#)/.test(rest) && rest.match(/^.*?[.!?](?=\s)/);
          if (m) { this.taken += m[0].length; this.say(m[0], 380); continue; }
          return;
        }
        const line = nl < 0 ? rest : rest.slice(0, nl);
        this.taken += nl < 0 ? rest.length : nl + 1;
        this.line(line);
        if (nl < 0 || this.cut) return;
      }
    },
    line(l) {
      if (/^\s*```/.test(l)) { this.inCode = !this.inCode; if (!this.saidCode) { this.saidCode = true; this.say("The code is in the chat.", 450); } return; }
      if (this.inCode || /^\s*\|/.test(l) || !l.trim()) return;
      if (/^\s*(?:[-*+•]|\d+[.)])\s+/.test(l)) {  // a list: the first three items, then a pointer to the chat
        if (++this.items === 4) return this.say("And more, see the chat.", 450);
        if (this.items > 4) return;
      } else this.items = 0;
      this.say(l, 550);
    },
    // one piece to speak; it shows in the chat up to here while it plays, then a short pause (gap, ms) before the next
    say(piece, gap) {
      if (!piece.trim() || this.cut) return;
      if (this.spoken && this.spoken + piece.length > 250) { this.cut = true; piece = "The rest is in the chat."; }  // the first piece always goes
      this.spoken += piece.length;
      const upto = this.cut ? Infinity : this.taken;
      const audio = fetch("/api/voice/tts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: piece, speech: true, limit: 2000 }) })
        .then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText); return URL.createObjectURL(await r.blob()); });
      audio.catch(() => {});
      this.queue.push({ audio, upto, gap });
      if (!this.playing) this.next(this.gen);
    },
    async next(gen) {
      if (gen !== this.gen) return;
      const it = this.queue.shift();
      if (!it) { this.playing = null; if (!h.busy()) this.end(); return; }
      this.playing = true;
      let url;
      try { url = await it.audio; } catch (e) { this.fail(e); return; }
      if (gen !== this.gen) return;
      const a = this.playing = new Audio(url), from = this.shown;
      clearInterval(this.talk); clearInterval(this.type);
      this.talk = setInterval(h.talk, 140);  // the core moves with the voice
      // the text types in while it is said, so what you read is what you hear
      this.type = setInterval(() => {
        if (!a.duration || !isFinite(a.duration) || !this.reveal) return;
        const end = Math.min(it.upto, 1e9), f = Math.min(1, a.currentTime / a.duration);
        this.show(isFinite(it.upto) ? from + Math.round((end - from) * f) : from);
      }, 50);
      h.speaking(true);
      a.onended = a.onerror = () => {
        clearInterval(this.talk); clearInterval(this.type); URL.revokeObjectURL(url);
        this.show(it.upto);
        setTimeout(() => this.next(gen), it.gap || 350);  // a breath between sentences
      };
      a.play().catch(() => a.onended());
    },
    show(n) { if (n > this.shown) { this.shown = n; if (this.reveal) this.reveal(n); } },
    end() {
      clearInterval(this.talk); clearInterval(this.type);
      const was = this.active; this.active = false; this.playing = null; this.queue = [];
      h.speaking(false);
      if (this.reveal) this.reveal(Infinity);
      h.idle();
      const d = this.done; this.done = null; if (was && d) d();
    },
    fail(e) { this.end(); h.failed(e); },
};
  A.stop = () => { A.gen++; if (A.playing && A.playing.pause) A.playing.pause(); if (A.active) A.end(); };
  return A;
};
