// Amadeus phone app: makes it installable and shows its calls as notifications. Pushes carry no content: the details
// are fetched from your PC over your private Tailscale connection when the notification arrives.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});  // always live from your PC (no offline copy of your data)
self.addEventListener("push", (e) => {
  e.waitUntil((async () => {
    let title = "Amadeus", body = "Amadeus needs you.";
    try {
      const ev = await (await fetch("/api/events", { credentials: "include" })).json();
      if (ev.length) { title = ev.length === 1 ? ev[0].title : `${ev.length} things for you`; body = ev.length === 1 ? (ev[0].body || "").slice(0, 140) : ev.slice(0, 3).map((x) => x.title).join(" · "); }
    } catch {}
    await self.registration.showNotification(title, { body, icon: "/logo-192.png", badge: "/logo-192.png", tag: "amadeus", renotify: true, vibrate: [200, 100, 200] });
  })());
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil((async () => {
    const all = await clients.matchAll({ type: "window", includeUncontrolled: true });
    if (all.length) return all[0].focus();
    return clients.openWindow("/");
  })());
});
