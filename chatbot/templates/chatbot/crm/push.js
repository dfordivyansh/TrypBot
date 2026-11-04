// TrypBot CRM - push notifications (Firebase Cloud Messaging), loaded by base.html.
// Asks once per device for permission, then registers this browser so the
// agent gets "new lead" / "new message" notifications (chatbot/push.py).
{% if enabled %}
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import { getMessaging, getToken, isSupported } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-messaging.js";

const CONFIG = {{ config_json|safe }};
const VAPID_KEY = "{{ vapid_key|escapejs }}";
const SW_URL = "{% url 'crm_push_sw' %}";
const REGISTER_URL = "{% url 'crm_push_register' %}";
const LATER_KEY = "trypbot-push-later";      // "Not now": ask again after this time
const SENT_KEY = "trypbot-push-token";       // token last saved on the server
const RESEND_MS = 12 * 3600 * 1000;          // refresh the server's copy twice a day

function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content || "";
}

async function enablePush() {
  const reg = await navigator.serviceWorker.register(SW_URL, { scope: "/crm/" });
  const messaging = getMessaging(initializeApp(CONFIG));
  const token = await getToken(messaging, { vapidKey: VAPID_KEY, serviceWorkerRegistration: reg });
  if (!token) return;

  let sent = {};
  try { sent = JSON.parse(localStorage.getItem(SENT_KEY) || "{}"); } catch (e) {}
  if (sent.token !== token || Date.now() - (sent.at || 0) > RESEND_MS) {
    const res = await fetch(REGISTER_URL, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify({ token }),
    });
    if (res.ok) localStorage.setItem(SENT_KEY, JSON.stringify({ token, at: Date.now() }));
  }
  // The service worker (crm/push-sw.js) shows every push, CRM open or not.
}

function showAskBanner() {
  if (document.getElementById("pushAsk")) return;
  const box = document.createElement("div");
  box.id = "pushAsk";
  box.setAttribute("role", "dialog");
  box.style.cssText = "position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:9999;" +
    "width:min(420px,calc(100% - 24px));background:#fff;color:#111827;border-radius:14px;" +
    "box-shadow:0 10px 30px rgba(0,0,0,.25);padding:16px;font-size:14px;line-height:1.4";
  box.innerHTML =
    '<div style="display:flex;gap:12px;align-items:flex-start">' +
      '<i class="fa-solid fa-bell" style="color:#00a86b;font-size:22px;margin-top:2px"></i>' +
      '<div><div style="font-weight:700;font-size:15px">Turn on notifications</div>' +
      '<div style="color:#4b5563;margin-top:2px">Get a notification on this device when a lead is assigned to you or your customer sends a message.</div></div>' +
    '</div>' +
    '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:12px">' +
      '<button type="button" id="pushLater" style="padding:8px 14px;border-radius:8px;color:#4b5563;font-weight:600">Not now</button>' +
      '<button type="button" id="pushAllow" style="padding:8px 16px;border-radius:8px;background:#00a86b;color:#fff;font-weight:700">Turn on</button>' +
    '</div>';
  document.body.appendChild(box);

  box.querySelector("#pushLater").onclick = () => {
    localStorage.setItem(LATER_KEY, String(Date.now() + 3 * 24 * 3600 * 1000));
    box.remove();
  };
  box.querySelector("#pushAllow").onclick = async () => {
    box.remove();
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      enablePush().catch(err => console.warn("[push] could not turn on:", err));
    } else {
      localStorage.setItem(LATER_KEY, String(Date.now() + 30 * 24 * 3600 * 1000));
    }
  };
}

(async () => {
  try {
    if (!("Notification" in window) || !("serviceWorker" in navigator)) return;
    if (!(await isSupported())) return;
    if (Notification.permission === "granted") return enablePush();
    if (Notification.permission === "denied") return;
    if (Date.now() < Number(localStorage.getItem(LATER_KEY) || 0)) return;
    showAskBanner();
  } catch (err) {
    console.warn("[push]", err);
  }
})();
{% endif %}
