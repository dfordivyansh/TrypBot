"""
Push notifications to CRM agents (Firebase Cloud Messaging, HTTP v1 API).

A browser where an agent allowed notifications registers its FCM token
(push_views.register -> PushDevice). The agent then gets a notification when
a lead is assigned to them and when a customer writes on a chat assigned to
them, also with the CRM closed.

Sending needs the Firebase project's service account key
(settings.FIREBASE_SERVICE_ACCOUNT_FILE). The OAuth token is signed here with
`cryptography`, so no Google client library is needed. Without the key
nothing is sent and nothing fails.
"""

import base64
import json
import os
import threading
import time

import requests
from django.conf import settings
from django.db import close_old_connections, transaction

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

_access = {"token": None, "expires": 0}
_access_lock = threading.Lock()


def _service_account():
    path = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_FILE", "")
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        print(f"[PUSH] service account file unreadable: {exc}")
        return None


def is_configured():
    return _service_account() is not None


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _access_token(sa):
    """OAuth access token for FCM, from a JWT signed with the service account key."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    with _access_lock:
        if _access["token"] and _access["expires"] - 120 > time.time():
            return _access["token"]
        now = int(time.time())
        token_uri = sa.get("token_uri") or "https://oauth2.googleapis.com/token"
        header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = _b64(json.dumps({
            "iss": sa["client_email"], "scope": FCM_SCOPE, "aud": token_uri,
            "iat": now, "exp": now + 3600,
        }).encode())
        key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
        signature = key.sign(header + b"." + claims, padding.PKCS1v15(), hashes.SHA256())
        assertion = (header + b"." + claims + b"." + _b64(signature)).decode()
        res = requests.post(token_uri, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion,
        }, timeout=15)
        res.raise_for_status()
        body = res.json()
        _access["token"] = body["access_token"]
        _access["expires"] = now + int(body.get("expires_in", 3600))
        return _access["token"]


def _token_is_dead(res):
    """FCM says this browser's token no longer works (notifications turned off, site data cleared)."""
    text = res.text or ""
    return res.status_code == 404 or "UNREGISTERED" in text or (
        res.status_code == 400 and "registration token" in text.lower())


def _send(user_id, title, body, url, tag):
    from .models import PushDevice

    close_old_connections()
    try:
        sa = _service_account()
        tokens = list(PushDevice.objects.filter(user_id=user_id).values_list("token", flat=True))
        if not sa or not tokens:
            return
        project = sa.get("project_id") or settings.FIREBASE_WEB_CONFIG.get("projectId")
        endpoint = f"https://fcm.googleapis.com/v1/projects/{project}/messages:send"
        headers = {"Authorization": f"Bearer {_access_token(sa)}"}
        link = settings.CRM_BASE_URL.rstrip("/") + url
        for token in tokens:
            # Data only: the CRM's service worker shows it (crm/push-sw.js),
            # so a tap opens the chat.
            message = {"message": {
                "token": token,
                "data": {"title": title[:120], "body": body[:240], "url": link, "tag": tag},
                "webpush": {"headers": {"Urgency": "high", "TTL": "86400"}},
            }}
            res = requests.post(endpoint, json=message, headers=headers, timeout=15)
            if res.status_code < 300:
                continue
            if _token_is_dead(res):
                PushDevice.objects.filter(token=token).delete()
            else:
                print(f"[PUSH] FCM {res.status_code}: {res.text[:300]}")
    except Exception as exc:
        print(f"[PUSH] error: {exc}")
    finally:
        close_old_connections()


def notify_user(user, title, body, url="/crm/", tag=""):
    """Notify a user's devices in the background, once the current DB transaction is saved."""
    user_id = getattr(user, "pk", user)
    if not user_id or not is_configured():
        return
    transaction.on_commit(lambda: threading.Thread(
        target=_send, args=(user_id, title, body, url, tag), daemon=True).start())


def _chat_name(session):
    return session.user_name or session.phone_number or f"Chat #{session.id}"


def notify_lead_assigned(session, user):
    preview = (session.last_message or "").strip()
    notify_user(user, f"New lead: {_chat_name(session)}",
                preview[:160] or "A new lead was assigned to you",
                f"/crm/chat/{session.id}/", tag=f"chat-{session.id}")


def notify_new_message(session, text):
    """A customer wrote on a chat: tell the agent it is assigned to."""
    if session.assigned_sales_person_id:
        notify_user(session.assigned_sales_person_id, _chat_name(session),
                    (text or "").strip()[:200] or "New message",
                    f"/crm/chat/{session.id}/", tag=f"chat-{session.id}")
