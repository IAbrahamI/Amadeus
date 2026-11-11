// Colours for code in the project workspace, like a code editor: comments, strings, numbers, keywords, types, functions.
// Small and offline on purpose (no library from the internet): one pass with one pattern per language.
const Highlight = (() => {
  const words = (s) => s.split(" ").join("|");
  const C_LIKE = { comment: String.raw`//[^\n]*|/\*[\s\S]*?\*/` };
  const STR = String.raw`"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'`;
  const NUM = String.raw`\b(?:0x[\da-fA-F_]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\b`;
  const FN = String.raw`\b[A-Za-z_$][\w$]*(?=\s*\()`;
  const TYPE = String.raw`\b[A-Z][A-Za-z0-9_]*\b`;
  const LANGS = {
    py: { comment: "#[^\\n]*", string: String.raw`[rbfuRBFU]{0,2}(?:"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')`, deco: String.raw`@[\w.]+`,
          keyword: words("and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case"),
          constant: words("True False None self cls"), builtin: words("print len range open str int float dict list set tuple bool isinstance super enumerate zip map filter sorted min max sum any all") },
    js: { ...C_LIKE, string: STR + String.raw`|\x60(?:\\.|[^\x60\\])*\x60`, deco: String.raw`@[\w.]+`,
          keyword: words("async await break case catch class const continue debugger default delete do else export extends finally for from function if import in instanceof let new of return static super switch throw try typeof var void while with yield interface type enum implements private public protected readonly as"),
          constant: words("true false null undefined this NaN Infinity"), builtin: words("console document window Math JSON Promise Array Object String Number Map Set Date Error") },
    rs: { ...C_LIKE, string: STR, deco: String.raw`#!?\[[^\]\n]*\]`, keyword: words("as async await break const continue crate dyn else enum extern fn for if impl in let loop match mod move mut pub ref return static struct super trait type unsafe use where while"),
          constant: words("true false self Self None Some Ok Err"), builtin: words("println format vec String Vec Option Result Box") },
    go: { ...C_LIKE, string: STR + String.raw`|\x60[^\x60]*\x60`, keyword: words("break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var"),
          constant: words("true false nil iota"), builtin: words("make len cap append new panic error string int bool byte") },
    c: { ...C_LIKE, string: STR, deco: String.raw`#\s*\w+`, keyword: words("auto break case catch class const continue default delete do else enum extern for friend goto if inline namespace new operator private protected public return sizeof static struct switch template this throw try typedef union using virtual void volatile while abstract extends final implements import interface package super synchronized throws var"),
         constant: words("true false null nullptr NULL this"), builtin: words("int char float double long short unsigned signed bool string std printf System") },
    sh: { comment: "#[^\\n]*", string: STR, keyword: words("if then else elif fi for in do done while until case esac function return local export set unset source exit"),
          constant: words("true false"), builtin: words("echo cd ls rm cp mv mkdir grep sed awk cat printf read test sudo git python3 npm"), variable: String.raw`\$\{?[\w@#?*!-]+\}?` },
    css: { comment: String.raw`/\*[\s\S]*?\*/`, string: STR, keyword: String.raw`@[\w-]+|!important`, prop: String.raw`[\w-]+(?=\s*:)`, constant: String.raw`#[\da-fA-F]{3,8}\b`, number: String.raw`-?\b\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|s|ms|deg|fr)?\b` },
    json: { prop: String.raw`"(?:\\.|[^"\\\n])*"(?=\s*:)`, string: STR, constant: words("true false null") },
    yaml: { comment: "#[^\\n]*", prop: String.raw`^[ \t-]*[\w.-]+(?=\s*:)`, string: STR, constant: words("true false null yes no on off") },
    toml: { comment: "#[^\\n]*", deco: String.raw`^\s*\[[^\]\n]+\]`, prop: String.raw`^\s*[\w.-]+(?=\s*=)`, string: String.raw`"""[\s\S]*?"""|` + STR, constant: words("true false") },
    sql: { comment: String.raw`--[^\n]*|/\*[\s\S]*?\*/`, string: STR, keyword: "(?i:" + words("select from where insert into values update set delete create table index drop alter add join left right inner outer on group by order having limit as and or not null is in like distinct primary key references default") + ")" },
    html: { comment: String.raw`<!--[\s\S]*?-->`, tag: String.raw`</?[\w:-]+|/?>`, prop: String.raw`\s[\w:@.-]+(?==)`, string: STR },
    md: { heading: String.raw`^#{1,6} [^\n]*`, code: String.raw`\x60\x60\x60[\s\S]*?\x60\x60\x60|\x60[^\x60\n]+\x60`, strong: String.raw`\*\*[^*\n]+\*\*|__[^_\n]+__`, link: String.raw`\[[^\]\n]+\]\([^)\n]+\)`, list: String.raw`^\s*(?:[-*+]|\d+\.)\s` },
  };
  const EXT = { py: "py", pyw: "py", js: "js", mjs: "js", cjs: "js", jsx: "js", ts: "js", tsx: "js", rs: "rs", go: "go", c: "c", h: "c", cpp: "c", cc: "c", hpp: "c",
    java: "c", cs: "c", kt: "c", kts: "c", swift: "c", sh: "sh", bash: "sh", zsh: "sh", css: "css", scss: "css", json: "json", yml: "yaml", yaml: "yaml", toml: "toml",
    sql: "sql", html: "html", htm: "html", xml: "html", svg: "html", vue: "html", md: "md", markdown: "md" };
  // what each part is called in the colours (hud.css .hl-*)
  const CLASS = { comment: "c", string: "s", string2: "s", number: "n", keyword: "k", constant: "o", builtin: "b", type: "t", fn: "f", deco: "d", prop: "p", tag: "k",
    variable: "p", heading: "k", code: "s", strong: "o", link: "f", list: "d" };
  const built = {};
  function pattern(lang) {
    if (built[lang]) return built[lang];
    const L = LANGS[lang], parts = [];
    const order = ["comment", "heading", "code", "deco", "prop", "string", "string2", "variable", "tag", "keyword", "constant", "builtin", "strong", "link", "list", "number", "fn", "type"];
    for (const name of order) {
      let rx = L[name];
      if (!rx && name === "number" && !["md", "html"].includes(lang)) rx = NUM;
      if (!rx && name === "fn" && !["md", "html", "css", "json", "yaml", "toml", "sql"].includes(lang)) rx = FN;
      if (!rx && name === "type" && ["py", "js", "rs", "go", "c"].includes(lang)) rx = TYPE;
      if (!rx) continue;
      const wordy = ["keyword", "constant", "builtin"].includes(name) && !/[\\(@#!]/.test(rx.slice(0, 3));
      parts.push(`(?<${name}>${wordy ? `\\b(?:${rx})\\b` : rx})`);
    }
    let flags = "gm";
    const src = parts.join("|").replace(/\(\?i:([^)]*)\)/g, (_, inner) => inner.replace(/[a-z]/g, (ch) => `[${ch}${ch.toUpperCase()}]`));
    return (built[lang] = new RegExp(src, flags));
  }
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  function lang(path) { const m = /\.([\w]+)$/.exec(path || ""); return m ? EXT[m[1].toLowerCase()] || "" : ""; }
  function html(text, path) {
    const l = lang(path);
    if (!l || text.length > 400000) return esc(text);
    const rx = pattern(l);
    let out = "", at = 0;
    rx.lastIndex = 0;
    for (let m; (m = rx.exec(text)); ) {
      if (!m[0]) { rx.lastIndex++; continue; }
      const name = Object.keys(m.groups).find((k) => m.groups[k] !== undefined);
      out += esc(text.slice(at, m.index)) + `<span class="hl-${CLASS[name] || "p"}">${esc(m[0])}</span>`;
      at = m.index + m[0].length;
    }
    return out + esc(text.slice(at));
  }
  return { html, lang };
})();
