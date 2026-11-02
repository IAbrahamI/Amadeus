// The animated avatar, if you added a sprite set (config "avatar"; files <set>/<set>_<expression><1-3>.png, see
// docs/INSTALL.md): expressions, lip-sync, eyes that follow the mouse, subtle head tilt. Without one, the window shows
// the default agent icon instead. Eyes: irises are found by their violet colour, cut out, and slid inside the eye
// whites (sprites with other eye colours simply keep still eyes).
(() => {
  const MOODS = { normal: "normal", happy: "happy", thinking: "sided_thinking", surprised: "sided_surprised",
    worried: "sided_worried", sad: "sad", annoyed: "annoyed", blush: "blush", wink: "winking" };
  const NO_EYES = new Set(["winking", "eyes_closed", "sided_eyes_closed"]);
  const MAX_DX = 4, MAX_DY = 1;               // pixels in sprite space; larger shifts show seams
  const S = { on: false, mood: "normal", frame: 1, lastToken: 0, mouse: [0, 0], imgs: {}, eyes: {}, tilt: 0 };
  let canvas, ctx, stage;

  const key = (m, f) => `${MOODS[m] || "normal"}${f}`;
  let SET = "";
  const url = (k) => `/avatar/${SET}/${SET}_${k}.png`;
  const PAD = 40;                             // extra rows above the sprite for the completed head
  function load(k) {
    if (S.imgs[k]) return S.imgs[k];
    const im = new Image(); im.src = url(k); S.imgs[k] = { ready: false };
    im.onload = () => {
      S.imgs[k] = { ready: true, c: completeHead(im) };
      if (!S.eyes[k.replace(/\d$/, "")]) detectEyes(k.replace(/\d$/, ""), im);
    };
    return S.imgs[k];
  }

  // The sprites are cut flat at the top of the head. Fit a circle to the head outline (rows 0..60),
  // then draw the missing crown: mirrored hair from the top rows, clipped to the circle, with a dark outline.
  function completeHead(im) {
    const w = im.naturalWidth, h = im.naturalHeight;
    const c = document.createElement("canvas"); c.width = w; c.height = h + PAD;
    const g = c.getContext("2d"); g.drawImage(im, 0, PAD);
    const rows = g.getImageData(0, PAD, w, 61).data;
    const span = (y) => { let a = -1, b = -1; for (let x = 0; x < w; x++) if (rows[(y * w + x) * 4 + 3] > 128) { if (a < 0) a = x; b = x; } return [a, b]; };
    const [a0, b0] = span(0), [a1, b1] = span(60);
    if (a0 < 0 || a1 < 0 || b0 - a0 < 20) return c;
    const cx = (a0 + b0) / 2, h0 = (b0 - a0) / 2, h1 = (b1 - a1) / 2;
    const yc = (h1 * h1 - h0 * h0 + 3600) / 120, R = Math.sqrt(h0 * h0 + yc * yc);
    const top = yc - R;                        // negative: rows missing above the image
    if (!(top < -2 && top > -PAD)) return c;
    const cyc = PAD + yc, depth = Math.ceil(-top) + 2;
    g.save();
    g.beginPath(); g.arc(cx, cyc, R, 0, Math.PI * 2); g.rect(0, PAD, w, h); g.clip("evenodd");
    g.beginPath(); g.arc(cx, cyc, R, 0, Math.PI * 2); g.clip();
    g.translate(0, PAD); g.scale(1, -1);       // mirror the top hair rows upward
    g.drawImage(im, a0 - 4, 0, b0 - a0 + 8, depth + 4, a0 - 4, 0, b0 - a0 + 8, depth + 4);
    g.restore();
    g.save(); g.beginPath(); g.rect(0, 0, w, PAD + 1); g.clip();
    g.beginPath(); g.arc(cx, cyc, R - 1.5, Math.PI, 2 * Math.PI);
    g.strokeStyle = "rgba(70,28,14,.9)"; g.lineWidth = 3; g.stroke(); g.restore();
    return c;
  }

  // Find iris pixels (violet) and the eye area (iris + white of the eye) for one expression.
  function detectEyes(expr, im) {
    if (NO_EYES.has(expr)) { S.eyes[expr] = null; return; }
    const w = im.naturalWidth, h = im.naturalHeight;
    const x0 = Math.floor(w * 0.15), x1 = Math.floor(w * 0.85), y0 = Math.floor(h * 0.20), y1 = Math.floor(h * 0.36);
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const g = c.getContext("2d"); g.drawImage(im, 0, 0);
    const d = g.getImageData(x0, y0, x1 - x0, y1 - y0); const p = d.data, W = x1 - x0, H = y1 - y0;
    const iris = new Uint8Array(W * H), area = new Uint8Array(W * H);
    for (let i = 0; i < W * H; i++) {
      const r = p[i * 4] / 255, gg = p[i * 4 + 1] / 255, b = p[i * 4 + 2] / 255, a = p[i * 4 + 3];
      if (a < 200) continue;
      const mx = Math.max(r, gg, b), mn = Math.min(r, gg, b), s = mx ? (mx - mn) / mx : 0;
      let hue = 0;
      if (mx !== mn) {
        if (mx === r) hue = ((gg - b) / (mx - mn)) % 6; else if (mx === gg) hue = (b - r) / (mx - mn) + 2; else hue = (r - gg) / (mx - mn) + 4;
        hue = ((hue * 60) + 360) % 360 / 360;
      }
      const violet = hue > 0.6 && hue < 0.82 && s > 0.10 && mx > 0.2;
      if (violet) { iris[i] = 1; area[i] = 1; } else if (mx > 0.75 && s < 0.18) area[i] = 1;
    }
    // fill each iris row between its leftmost and rightmost violet pixel (pupil + highlights), per eye half
    let cnt = 0, sumX = 0;
    for (let i = 0; i < W * H; i++) if (iris[i]) { cnt++; sumX += i % W; }
    if (cnt < 400) { S.eyes[expr] = null; return; }
    const mid = sumX / cnt;
    for (let y = 0; y < H; y++) for (const side of [0, 1]) {
      let a = -1, b = -1;
      for (let x = 0; x < W; x++) if (iris[y * W + x] && ((x < mid) === !side)) { if (a < 0) a = x; b = x; }
      if (a >= 0) for (let x = a; x <= b; x++) { iris[y * W + x] = 1; area[y * W + x] = 1; }
    }
    let bx0 = W, by0 = H, bx1 = 0, by1 = 0;
    for (let i = 0; i < W * H; i++) if (area[i] && iris[i]) { const x = i % W, y = (i / W) | 0; bx0 = Math.min(bx0, x); bx1 = Math.max(bx1, x); by0 = Math.min(by0, y); by1 = Math.max(by1, y); }
    const pad = 8; bx0 = Math.max(0, bx0 - pad); by0 = Math.max(0, by0 - pad); bx1 = Math.min(W - 1, bx1 + pad); by1 = Math.min(H - 1, by1 + pad);
    S.eyes[expr] = { ox: x0 + bx0, oy: y0 + by0, w: bx1 - bx0 + 1, h: by1 - by0 + 1, src: d, W, bx0, by0, iris, area,
      center: [(x0 + (bx0 + bx1) / 2) / w, (PAD + y0 + (by0 + by1) / 2) / (h + PAD)] };
  }

  // Build the eye patch for an offset: irises removed (eye-white fill), then redrawn shifted, clipped to the eye area.
  const patchCache = {};
  function patch(expr, dx, dy) {
    const e = S.eyes[expr]; if (!e) return null;
    const k = `${expr}:${dx}:${dy}`; if (patchCache[k]) return patchCache[k];
    const out = new ImageData(e.w, e.h), o = out.data, src = e.src.data;
    for (let y = 0; y < e.h; y++) for (let x = 0; x < e.w; x++) {
      const si = (e.by0 + y) * e.W + (e.bx0 + x), di = (y * e.w + x) * 4;
      if (e.iris[si]) { o[di] = 226; o[di + 1] = 224; o[di + 2] = 236; o[di + 3] = 255; }
      else { o[di] = src[si * 4]; o[di + 1] = src[si * 4 + 1]; o[di + 2] = src[si * 4 + 2]; o[di + 3] = src[si * 4 + 3]; }
    }
    for (let y = 0; y < e.h; y++) for (let x = 0; x < e.w; x++) {
      const si = (e.by0 + y) * e.W + (e.bx0 + x); if (!e.iris[si]) continue;
      const tx = x + dx, ty = y + dy; if (tx < 0 || ty < 0 || tx >= e.w || ty >= e.h) continue;
      const ti = (e.by0 + ty) * e.W + (e.bx0 + tx); if (!e.area[ti]) continue;
      const di = (ty * e.w + tx) * 4;
      o[di] = src[si * 4]; o[di + 1] = src[si * 4 + 1]; o[di + 2] = src[si * 4 + 2]; o[di + 3] = 255;
    }
    return (patchCache[k] = out);
  }

  // Drawing is done only when something visible changes (sprite frame, eye offset, head tilt), and the
  // full-size sprite is composed off-screen and copied down to a canvas the size it is shown at.
  // This keeps scrolling smooth in the small desktop window.
  const work = document.createElement("canvas"), wctx = work.getContext("2d");
  let rect = null, last = "";
  const measure = () => { if (canvas) rect = canvas.getBoundingClientRect(); };
  function draw() {
    if (!S.on) return;
    const talking = Date.now() - S.lastToken < 350;
    S.frame = talking ? [1, 2, 3, 2][Math.floor(Date.now() / 110) % 4] : 1;
    const k = key(S.mood, S.frame), sp = load(k);
    if (!sp.ready) return;
    if (!rect || !rect.width) measure();
    const r = rect, expr = MOODS[S.mood] || "normal", e = S.eyes[expr];
    let nx = 0, ny = 0;
    if (r && r.width) {
      const cx = r.left + (e ? e.center[0] : 0.5) * r.width, cy = r.top + (e ? e.center[1] : 0.3) * r.height;
      nx = Math.max(-1, Math.min(1, (S.mouse[0] - cx) / (window.innerWidth * 0.35)));
      ny = Math.max(-1, Math.min(1, (S.mouse[1] - cy) / (window.innerHeight * 0.5)));
    }
    const dx = Math.round(nx * MAX_DX), dy = Math.round(ny * MAX_DY);
    S.tilt += (nx * 1.6 - S.tilt) * 0.15;   // smooth, subtle head tilt (degrees)
    const tilt = S.tilt.toFixed(1), w = Math.max(1, Math.round((r && r.width || 230) * (window.devicePixelRatio || 1)));
    const state = `${k}|${dx}|${dy}|${tilt}|${w}|${!!e}`;
    if (state === last) return;
    const im = sp.c, h = Math.round(w * im.height / im.width);
    if (!state.startsWith(last.split("|").slice(0, 3).join("|") + "|") || canvas.width !== w) {
      if (work.width !== im.width || work.height !== im.height) { work.width = im.width; work.height = im.height; }
      wctx.clearRect(0, 0, work.width, work.height);
      wctx.drawImage(im, 0, 0);
      if (e) { const pt = patch(expr, dx, dy); if (pt) wctx.putImageData(pt, e.ox, e.oy + PAD); }
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      ctx.imageSmoothingQuality = "high";
      ctx.clearRect(0, 0, w, h);
      ctx.drawImage(work, 0, 0, w, h);
    }
    canvas.style.transform = `rotate(${tilt}deg) translateX(${(S.tilt * 2).toFixed(1)}px)`;
    last = state;
  }

  window.Avatar = {
    async init(api) {
      const a = await api("/api/avatar");
      if (!a.available) return false;
      SET = a.set;
      stage = document.querySelector("#avatarPanel .stage");
      canvas = document.createElement("canvas"); canvas.id = "avatarCanvas"; ctx = canvas.getContext("2d", { willReadFrequently: false });
      stage.innerHTML = ""; stage.appendChild(canvas);
      window.addEventListener("mousemove", (ev) => { S.mouse = [ev.clientX, ev.clientY]; });
      window.addEventListener("resize", measure);
      document.addEventListener("scroll", measure, { capture: true, passive: true });
      setInterval(measure, 1000);
      Object.values(MOODS).forEach((m) => [1, 2, 3].forEach((f) => load(`${m}${f}`)));
      setInterval(draw, 60);
      return true;
    },
    show(on) { S.on = on; },
    setMood(m) { S.mood = MOODS[m] ? m : "normal"; },
    talk() { S.lastToken = Date.now(); },
    // subtitles: the last sentence or two of what it is saying; hidden again a few seconds after it stops
    subtitle(text, holdMs = 0) {
      const el = document.getElementById("avatarSub"); if (!el) return;
      clearTimeout(S.subTimer);
      let t = (text || "").replace(/[*_`#>]/g, "").replace(/\s+/g, " ").trim();
      if (t.length > 140) { const cut = t.slice(-140); const i = cut.search(/[.!?…]\s/); t = (i >= 0 && i < 100 ? cut.slice(i + 2) : "…" + cut.trim()); }
      el.textContent = t; el.classList.toggle("on", !!t);
      if (t && holdMs) S.subTimer = setTimeout(() => el.classList.remove("on"), holdMs);
    },
    moods: Object.keys(MOODS),
  };
})();
