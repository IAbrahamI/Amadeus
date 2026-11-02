// Amadeus Bridge: answers requests from Amadeus Core (through the native host thunderbird/bridge_host.py).
// Read: accounts, recent mail, search, one message. Write: save a draft, send (Amadeus asks you before it calls these).
const MAX_BODY = 20000;

async function accounts() {
  const list = await messenger.accounts.list(false);
  return list.filter((a) => a.type !== "none").map((a) => ({
    id: a.id, name: a.name, type: a.type,
    identities: (a.identities || []).map((i) => ({ id: i.id, email: i.email, name: i.name })),
  }));
}

function header(m) {
  return { id: m.id, messageId: m.headerMessageId, date: m.date, from: m.author, to: m.recipients, cc: m.ccList,
    subject: m.subject, read: m.read, flagged: m.flagged, folder: m.folder && (m.folder.path || m.folder.name),
    folderId: m.folder && m.folder.id, accountId: m.folder && m.folder.accountId };
}

async function collect(list, limit) {
  const out = [];
  let page = list;
  while (page) {
    for (const m of page.messages) { out.push(header(m)); if (out.length >= limit) return out; }
    if (!page.id) break;
    page = await messenger.messages.continueList(page.id);
  }
  return out;
}

async function inboxes(accountId) {
  try {
    const q = { specialUse: ["inbox"] };
    if (accountId) q.accountId = accountId;
    return await messenger.folders.query(q);
  } catch (e) {  // older API: walk the accounts
    const res = [];
    for (const a of await messenger.accounts.list(true)) {
      if (accountId && a.id !== accountId) continue;
      for (const f of a.folders || []) if ((f.specialUse || []).includes("inbox") || f.type === "inbox") res.push(f);
    }
    return res;
  }
}

async function recent({ accountId, folderId, days = 2, limit = 30, unreadOnly = false }) {
  const fromDate = new Date(Date.now() - days * 864e5);
  let out = [];
  for (const f of folderId ? [{ id: folderId }] : await inboxes(accountId)) {
    const q = { folderId: f.id, fromDate };
    if (unreadOnly) q.unread = true;
    out = out.concat(await collect(await messenger.messages.query(q), limit));
  }
  return out.sort((a, b) => new Date(b.date) - new Date(a.date)).slice(0, limit);
}

async function search({ query, days = 90, limit = 20, accountId }) {
  const q = { fromDate: new Date(Date.now() - days * 864e5), fullText: query };
  if (accountId) q.accountId = accountId;
  try {
    return await collect(await messenger.messages.query(q), limit);
  } catch (e) {  // fullText not supported: search subject and sender
    const a = await collect(await messenger.messages.query({ ...q, fullText: undefined, subject: query }), limit);
    const b = await collect(await messenger.messages.query({ ...q, fullText: undefined, author: query }), limit);
    const seen = new Set();
    return a.concat(b).filter((m) => !seen.has(m.id) && seen.add(m.id)).slice(0, limit);
  }
}

function textOf(part) {
  let plain = "", html = "";
  (function walk(p) {
    if (!p) return;
    if (p.body && p.contentType === "text/plain" && !plain) plain = p.body;
    if (p.body && p.contentType === "text/html" && !html) html = p.body;
    (p.parts || []).forEach(walk);
  })(part);
  if (plain) return plain;
  return htmlText(html);
}

// HTML mail as readable text that KEEPS links: <a href="URL">Confirm</a> becomes "Confirm (URL)", so verification and
// sign-in links stay usable.
function htmlText(html) {
  return html.replace(/<style[\s\S]*?<\/style>|<script[\s\S]*?<\/script>/gi, "")
    .replace(/<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi, (m, url, text) => {
      const t = text.replace(/<[^>]+>/g, "").trim();
      return /^(mailto:|#)/i.test(url) ? t : (t && t !== url ? `${t} (${url})` : url);
    })
    .replace(/<br\s*\/?>|<\/p>|<\/div>|<\/tr>|<\/li>/gi, "\n")
    .replace(/<[^>]+>/g, "").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/\n{3,}/g, "\n\n").trim();
}

async function read({ id }) {
  const m = await messenger.messages.get(id);
  let body = "";
  try {
    const parts = await messenger.messages.listInlineTextParts(id);
    const plain = parts.find((p) => p.contentType === "text/plain");
    const html = parts.find((p) => p.contentType === "text/html");
    // plain text if there is one; but if it has no links while the HTML part does, use the HTML (links kept)
    body = plain && (/https?:\/\//.test(plain.content) || !html) ? plain.content
      : html ? htmlText(html.content) : textOf({ parts: parts.map((p) => ({ contentType: p.contentType, body: p.content })) });
  } catch (e) {
    body = textOf(await messenger.messages.getFull(id));
  }
  let attachments = [];
  try { attachments = (await messenger.messages.listAttachments(id)).map((a) => ({ name: a.name, size: a.size, contentType: a.contentType })); } catch (e) {}
  return { ...header(m), body: body.slice(0, MAX_BODY), truncated: body.length > MAX_BODY, attachments };
}

async function compose({ accountId, to, cc, subject, body, replyTo }) {
  let identityId;
  if (accountId) {
    const a = await messenger.accounts.get(accountId);
    identityId = a && a.identities && a.identities[0] && a.identities[0].id;
  }
  const details = { plainTextBody: body || "", isPlainText: true };
  if (identityId) details.identityId = identityId;
  if (to) details.to = Array.isArray(to) ? to : [to];
  if (cc) details.cc = Array.isArray(cc) ? cc : [cc];
  if (subject) details.subject = subject;
  return replyTo ? messenger.compose.beginReply(replyTo, "replyToSender", details) : messenger.compose.beginNew(null, details);
}

async function closeTab(tab) {
  try { await messenger.windows.remove(tab.windowId); } catch (e) { try { await messenger.tabs.remove(tab.id); } catch (e2) {} }
}

async function draft(args) {
  const tab = await compose(args);
  try {
    const r = await messenger.compose.saveMessage(tab.id, { mode: "draft" });
    return { saved: true, messageId: r && r.messages && r.messages[0] && r.messages[0].headerMessageId };
  } finally { await closeTab(tab); }
}

async function send(args) {
  const tab = await compose(args);
  const r = await messenger.compose.sendMessage(tab.id, { mode: "sendNow" });
  return { sent: true, messageId: r && r.headerMessageId };
}

// ---------- folders and organizing ----------
const SKIP = ["trash", "sent", "drafts", "templates", "outbox"];

async function allFolders(accountId) {
  let list;
  try {
    list = await messenger.folders.query(accountId ? { accountId } : {});
  } catch (e) {  // older API: walk the tree
    list = [];
    const walk = (fs) => (fs || []).forEach((f) => { list.push(f); walk(f.subFolders); });
    for (const a of await messenger.accounts.list(true)) if (!accountId || a.id === accountId) walk(a.folders);
  }
  return list.filter((f) => !f.isRoot && f.path !== "/");
}

async function folders({ accountId }) {
  const out = [];
  for (const f of await allFolders(accountId)) {
    let info = {};
    try { info = await messenger.folders.getFolderInfo(f.id); } catch (e) {}
    out.push({ id: f.id, accountId: f.accountId, name: f.name, path: f.path, specialUse: f.specialUse || [],
      unread: info.unreadMessageCount ?? null, total: info.totalMessageCount ?? null });
  }
  return out;
}

async function unread({ accountId, limit = 100, includeJunk = true }) {
  let out = [];
  for (const f of await allFolders(accountId)) {
    const use = f.specialUse || [];
    if (use.some((u) => SKIP.includes(u)) || (!includeJunk && use.includes("junk"))) continue;
    try {
      const info = await messenger.folders.getFolderInfo(f.id);
      if (!info.unreadMessageCount) continue;
    } catch (e) {}
    out = out.concat(await collect(await messenger.messages.query({ folderId: f.id, unread: true }), limit));
    if (out.length >= limit) break;
  }
  return out.sort((a, b) => new Date(b.date) - new Date(a.date)).slice(0, limit);
}

async function headers({ ids }) {
  const out = [];
  for (const id of ids) { try { out.push(header(await messenger.messages.get(id))); } catch (e) { out.push({ id, missing: true }); } }
  return out;
}

async function markRead({ ids, read = true }) {
  for (const id of ids) await messenger.messages.update(id, { read });
  return { updated: ids.length };
}

async function flag({ ids, flagged = true }) {  // the ★ flag in Thunderbird
  for (const id of ids) await messenger.messages.update(id, { flagged });
  return { updated: ids.length };
}

async function move({ ids, folderId }) {
  await messenger.messages.move(ids, folderId);
  return { moved: ids.length };
}

async function trash({ ids }) {  // into the Trash only (never deleted for good: skipTrash = false)
  await messenger.messages.delete(ids, false);
  return { trashed: ids.length };
}

async function junk({ ids, junk = true }) {  // also trains Thunderbird's own spam filter
  for (const id of ids) await messenger.messages.update(id, { junk });
  return { updated: ids.length };
}

async function forward({ id, to, body, accountId }) {
  const details = { to: Array.isArray(to) ? to : [to] };
  if (body) { details.plainTextBody = body; details.isPlainText = true; }
  if (accountId) {
    const a = await messenger.accounts.get(accountId);
    if (a && a.identities && a.identities[0]) details.identityId = a.identities[0].id;
  }
  const tab = await messenger.compose.beginForward(id, "forwardInline", details);
  const r = await messenger.compose.sendMessage(tab.id, { mode: "sendNow" });
  return { sent: true, messageId: r && r.headerMessageId };
}

async function attachments({ id }) {
  return (await messenger.messages.listAttachments(id)).map((a) => ({ name: a.name, size: a.size, contentType: a.contentType, part: a.partName }));
}

async function attachment({ id, part }) {  // one attachment's content (base64), for saving or reading
  const file = await messenger.messages.getAttachmentFile(id, part);
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.length > 25 * 1024 * 1024) throw new Error("attachment larger than 25 MB");
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return { name: file.name, size: bytes.length, contentType: file.type, data: btoa(bin) };
}

// Thunderbird's address books: names and mail addresses only
async function contacts({ query, limit = 10 }) {
  const out = [];
  for (const c of await messenger.contacts.quickSearch(query)) {
    const p = c.properties || {};
    let name = p.DisplayName || [p.FirstName, p.LastName].filter(Boolean).join(" ");
    let emails = [p.PrimaryEmail, p.SecondEmail].filter(Boolean);
    if (p.vCard) {
      name = name || ((p.vCard.match(/^FN[^:]*:(.*)$/m) || [])[1] || "").trim();
      emails = emails.concat([...p.vCard.matchAll(/^EMAIL[^:]*:(.*)$/gm)].map((m) => m[1].trim()));
    }
    emails = [...new Set(emails)];
    if (emails.length) out.push({ name, emails });
    if (out.length >= limit) break;
  }
  return out;
}

async function createFolder({ parentId, name }) {
  const f = await messenger.folders.create(parentId, name);
  return { id: f.id, path: f.path, name: f.name };
}

const OPS = { ping: async () => "pong", accounts, recent, search, read, draft, send, folders, unread, headers, markRead, flag, move, createFolder,
  trash, junk, forward, attachments, attachment, contacts };

let port = null;
function connect() {
  port = messenger.runtime.connectNative("amadeus_bridge");
  port.onMessage.addListener(async (msg) => {
    try {
      const fn = OPS[msg.op];
      if (!fn) throw new Error("unknown operation " + msg.op);
      port.postMessage({ id: msg.id, ok: true, result: await fn(msg.args || {}) });
    } catch (e) {
      port.postMessage({ id: msg.id, ok: false, error: String((e && e.message) || e) });
    }
  });
  port.onDisconnect.addListener(() => { port = null; setTimeout(connect, 5000); });
}
connect();

// New mail arrived (any folder): only a signal goes to Amadeus, no mail content. Amadeus then checks the new mail itself.
messenger.messages.onNewMailReceived.addListener((folder, list) => {
  if (port && list && list.messages && list.messages.length) port.postMessage({ event: "new_mail", count: list.messages.length });
}, true);
