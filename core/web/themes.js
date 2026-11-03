// Colour themes for the dashboard: Default (blue), Purple and Red. Each sets the CSS variables of hud.css and the
// colours of the core (core.js). Amber always means "needs you", in every theme. The choice is saved in the Core
// settings (so the phone can follow later) and cached here, so the page opens in it without a flash.
// Never use a data-theme attribute for this: browsers and hosts set that one on <html> themselves.
window.THEMES = {
  blue: { name: "Default", a: "95,216,255", a2: "140,215,255", a3: "30,88,120", ln: "18,50,74", vd: "4,7,12", line: "#12324A", lineHi: "#1E5878",
    text: "#D4E6F2", dim: "#6E8BA0", ink: "#031018", void: "#04070C", deck: "#08101A",
    k: ["95,216,255", "140,170,255", "79,224,166"], rc: "225,248,255", rc2: "255,255,255", hi: "235,250,255", cc: "#B69CFF", ccr: "182,156,255", ccink: "#120a26" },
  purple: { name: "Purple", a: "182,140,255", a2: "205,180,255", a3: "72,40,135", ln: "44,30,76", vd: "7,5,14", line: "#2C1E4C", lineHi: "#4C3684",
    text: "#E7DFF8", dim: "#9083AA", ink: "#12082A", void: "#07050E", deck: "#100A1C",
    k: ["182,140,255", "255,130,215", "110,190,255"], rc: "255,150,225", rc2: "255,225,245", hi: "245,238,255", cc: "#5FD8FF", ccr: "95,216,255", ccink: "#031018" },
  red: { name: "Red", a: "255,82,96", a2: "255,145,150", a3: "125,28,40", ln: "76,24,32", vd: "12,4,5", line: "#4A1820", lineHi: "#7C2A36",
    text: "#F5DCDE", dim: "#A57E84", ink: "#1A0406", void: "#0C0405", deck: "#160A0C",
    k: ["255,82,96", "255,150,95", "255,195,205"], rc: "255,196,110", rc2: "255,236,200", hi: "255,240,240", cc: "#B69CFF", ccr: "182,156,255", ccink: "#120a26" },
};
window.applyTheme = (id) => {
  if (!THEMES[id]) id = "blue";  // an unknown or removed theme: the default
  const T = THEMES[id], r = document.documentElement.style;
  window.TH = T; window.THEME = id;
  const v = { "--a": T.a, "--a2": T.a2, "--a3": T.a3, "--ln": T.ln, "--vd": T.vd, "--line": T.line, "--line-hi": T.lineHi, "--text": T.text, "--dim": T.dim,
    "--ink": T.ink, "--void": T.void, "--deck": T.deck, "--cyan": `rgb(${T.a})`, "--cc": T.cc, "--ccr": T.ccr, "--ccink": T.ccink,
    "--k0": `rgb(${T.k[0]})`, "--k1": `rgb(${T.k[1]})`, "--k2": `rgb(${T.k[2]})`, "--rc": `rgb(${T.rc})` };
  for (const k in v) r.setProperty(k, v[k]);
  try { localStorage.setItem("theme-hud", id); } catch {}
  if (window.Core && Core.recolor) Core.recolor();
  document.querySelectorAll("button[data-th]").forEach((b) => b.classList.toggle("on", b.dataset.th === id));
};
(() => { let id = "blue"; try { id = localStorage.getItem("theme-hud") || "blue"; } catch {} applyTheme(id); })();
fetch("/api/theme").then((r) => r.json()).then((d) => { if (d.theme && d.theme !== window.THEME) applyTheme(d.theme); }).catch(() => {});
