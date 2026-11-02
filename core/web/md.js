// Small, safe Markdown renderer shared by the dashboard and the small window (no external libraries).
// Everything is HTML-escaped first; only http(s)/mailto links are made clickable.
// Supports: headings, bold/italic/strike, inline code, fenced code (with language + copy button), quotes,
// bullet/numbered/task lists (one level of nesting), tables, horizontal rules, links, line breaks.
(() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function inline(t) {
    const codes = [];
    t = t.replace(/`([^`\n]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);  // protect inline code
    t = esc(t)
      .replace(/\*\*\*([^*\n]+)\*\*\*/g, "<b><i>$1</i></b>")
      .replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>")
      .replace(/__([^_\n]+)__/g, "<b>$1</b>")
      .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<i>$2</i>")
      .replace(/(^|[^\w])_([^_\n]+)_(?!\w)/g, "$1<i>$2</i>")
      .replace(/~~([^~\n]+)~~/g, "<s>$1</s>")
      .replace(/\[([^\]\n]+)\]\(((?:https?:|mailto:)[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?])/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
    return t.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[+i])}</code>`);
  }

  const isRow = (l) => /^\s*\|.*\|\s*$/.test(l);
  const isSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  const LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

  function list(lines, i) {
    const first = lines[i].match(LIST), ordered = /\d/.test(first[2]), base = first[1].length;
    let html = ordered ? `<ol${+first[2] > 1 ? ` start="${parseInt(first[2])}"` : ""}>` : "<ul>";
    while (i < lines.length) {
      const m = lines[i].match(LIST);
      if (!m || m[1].length < base || (m[1].length === base && /\d/.test(m[2]) !== ordered)) break;  // new list type: new list
      if (m[1].length > base) {  // nested list belongs to the previous item
        const [sub, j] = list(lines, i);
        html = html.replace(/<\/li>$/, sub + "</li>"); i = j; continue;
      }
      let text = m[3], task = "";
      const t = text.match(/^\[([ xX])\]\s+(.*)$/);
      if (t) { task = `<input type="checkbox" disabled ${t[1] !== " " ? "checked" : ""}> `; text = t[2]; }
      i++;
      while (i < lines.length && lines[i].trim() && !LIST.test(lines[i]) && /^\s{2,}/.test(lines[i])) text += " " + lines[i++].trim();
      html += `<li>${task}${inline(text)}</li>`;
    }
    return [html + (ordered ? "</ol>" : "</ul>"), i];
  }

  function md(src) {
    const lines = String(src ?? "").replace(/\r\n?/g, "\n").split("\n");
    let out = "", i = 0, para = [];
    const flush = () => { if (para.length) { out += `<p>${para.map(inline).join("<br>")}</p>`; para = []; } };
    while (i < lines.length) {
      const l = lines[i];
      const fence = l.match(/^\s*(```|~~~)\s*([\w+#.-]*)\s*$/);
      if (fence) {
        flush();
        const code = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith(fence[1])) code.push(lines[i++]);
        i++;
        out += `<div class="code"><div class="code-head"><span>${esc(fence[2] || "text")}</span><button type="button" class="copy">Copy</button></div>` +
          `<pre><code>${esc(code.join("\n"))}</code></pre></div>`;
        continue;
      }
      if (!l.trim()) { flush(); i++; continue; }
      const h = l.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
      if (h) { flush(); const n = Math.min(6, h[1].length + 2); out += `<h${n}>${inline(h[2])}</h${n}>`; i++; continue; }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)) { flush(); out += "<hr>"; i++; continue; }
      if (isRow(l) && i + 1 < lines.length && isSep(lines[i + 1])) {
        flush();
        const head = cells(l);
        i += 2;
        let body = "";
        while (i < lines.length && isRow(lines[i])) body += "<tr>" + cells(lines[i++]).map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
        out += `<div class="table"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
        continue;
      }
      if (/^\s*>/.test(l)) {
        flush();
        const q = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
        out += `<blockquote>${md(q.join("\n"))}</blockquote>`;
        continue;
      }
      if (LIST.test(l)) {
        flush();
        const [html, j] = list(lines, i);
        out += html; i = j; continue;
      }
      para.push(l.trim()); i++;
    }
    flush();
    return out;
  }

  // copy buttons on code blocks (works for anything rendered by md())
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".code .copy"); if (!b) return;
    const code = b.closest(".code").querySelector("code").textContent;
    const done = () => { b.textContent = "Copied"; setTimeout(() => (b.textContent = "Copy"), 1200); };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(code).then(done, () => {});
    else { const t = document.createElement("textarea"); t.value = code; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); done(); }
  });

  window.md = md;
})();
