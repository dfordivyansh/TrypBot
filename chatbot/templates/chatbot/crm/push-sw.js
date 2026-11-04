// TrypBot CRM - push notification service worker (served at /crm/push-sw.js).
// Shows the "new lead" / "new message" notifications sent by chatbot/push.py,
// also when the CRM is closed; a tap opens that chat.
//
// Same approach as the Group-Tours site (public/firebase-messaging-sw.js): the
// push is read here without the Firebase messaging SDK. With the SDK a push
// could show twice, or as Chrome's "This site has been updated in the
// background". Every push shows exactly one notification.

// FCM delivers { data: {title, body, url, tag} } (data-only, chatbot/push.py);
// a test from the Firebase console sends a notification block instead.
function readPush(event) {
  let raw = {};
  try { raw = event.data ? event.data.json() : {}; } catch (e) {
    try { raw = { data: { body: event.data.text() } }; } catch (e2) { raw = {}; }
  }
  const data = raw.data || {};
  const note = raw.notification || {};
  const pick = (...v) => v.find((x) => typeof x === "string" && x.trim()) || "";
  return {
    title: (pick(note.title, data.title) || "TrypBot CRM").slice(0, 120),
    body: (pick(note.body, data.body) || "Tap to open the CRM.").slice(0, 400),
    url: pick(data.url, raw.fcmOptions && raw.fcmOptions.link) || "/crm/",
    // Same tag (one per chat): a newer message replaces the older one.
    tag: pick(data.tag) || undefined,
  };
}

self.addEventListener("push", (event) => {
  const n = readPush(event);
  event.waitUntil(self.registration.showNotification(n.title, {
    body: n.body,
    tag: n.tag,
    renotify: !!n.tag,
    timestamp: Date.now(),
    data: { url: n.url },
  }));
});

// A new worker takes over straight away, so a fix is live on the next push.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || "/crm/", self.location.origin).href;
  event.waitUntil((async () => {
    const tabs = await clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const tab of tabs) {
      if (new URL(tab.url).origin === self.location.origin && "navigate" in tab) {
        // navigate() only works on tabs this worker controls; otherwise open a new one.
        try { await tab.navigate(url); return tab.focus(); } catch (e) { break; }
      }
    }
    return clients.openWindow(url);
  })());
});
