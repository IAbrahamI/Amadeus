// Loaded once by amadeus-mail-start: minimizes the first Thunderbird main window that opens, then does nothing more.
let done = false;
function check(w) {
  if (!done && w && w.normalWindow && /thunderbird/i.test(w.resourceClass || "")) { w.minimized = true; done = true; }
}
workspace.windowAdded.connect(check);
