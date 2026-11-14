// Her speech bubble in its own small window (the desktop app keeps it above or below the core). It shows what the mini
// core has in its #bubbles (web/mini.js) and hands clicks on the buttons back to it. Clicks anywhere else reach the desktop.
const box = document.getElementById("bubbles");
const send = (msg) => { try { window.amadeusBridge.postMessage(msg); } catch {} };
function shape() {
  const r = box.getBoundingClientRect();
  send("shape:" + JSON.stringify(box.children.length ? [[Math.round(r.x) - 2, Math.round(r.y) - 2, Math.round(r.width) + 4, Math.round(r.height) + 14]] : [[0, 0, 1, 1]]));
}
// as tall as what she says needs (the app caps it at part of the screen): the window follows the text
let asked = 0;
function fit() {
  document.body.classList.add("measuring");  // its whole height, not what fits the window right now
  const need = Math.ceil(box.scrollHeight) + 18;  // the bubble, its tail and a margin
  document.body.classList.remove("measuring");
  if (box.children.length && Math.abs(need - asked) > 2) { asked = need; send("bubble-size:" + need); }
}
window.amadeusSetBubble = (html) => {
  box.innerHTML = html;
  box.querySelectorAll(".bubble").forEach((b) => b.classList.add("show"));
  box.classList.toggle("in", !!html);
  fit();
  shape();
};
// above the core the tail points down to it, below the core up
window.amadeusBubbleSide = (below) => { document.body.classList.toggle("below", !!below); shape(); };
box.addEventListener("click", (e) => { const b = e.target.closest("[data-a]"); if (b) send("bubble-click:" + b.dataset.a); });
addEventListener("resize", () => { shape(); });
send("bubble-ready");  // anything said while this window was still loading
