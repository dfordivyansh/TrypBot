"""
CRM push notifications, browser side: the script that asks for permission
and registers the device (crm/push.js), the service worker that shows the
notifications (crm/push-sw.js), and the endpoint that saves a device token.
Sending: chatbot/push.py.
"""

import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from .decorators import crm_login_required
from .models import PushDevice


def _firebase_context():
    return {
        "config_json": json.dumps(settings.FIREBASE_WEB_CONFIG),
        "vapid_key": settings.FIREBASE_VAPID_KEY,
        "enabled": bool(settings.FIREBASE_WEB_CONFIG.get("apiKey") and settings.FIREBASE_VAPID_KEY),
    }


def _javascript(template, request):
    response = HttpResponse(render_to_string(template, _firebase_context(), request=request),
                            content_type="application/javascript; charset=utf-8")
    # Always the current version (the service worker updates with each deploy).
    response["Cache-Control"] = "no-cache"
    return response


def push_script(request):
    """crm/push.js: loaded by every CRM page (base.html)."""
    return _javascript("chatbot/crm/push.js", request)


def push_service_worker(request):
    """crm/push-sw.js: served under /crm/ so it covers the CRM pages."""
    return _javascript("chatbot/crm/push-sw.js", request)


@crm_login_required
@require_POST
def push_register(request):
    """Save this browser's FCM token for the logged-in user."""
    try:
        token = str(json.loads(request.body or b"{}").get("token", "")).strip()
    except (ValueError, TypeError, AttributeError):
        token = ""
    if not token or len(token) > 512:
        return JsonResponse({"success": False, "error": "No token."}, status=400)
    PushDevice.objects.update_or_create(token=token, defaults={
        "user": request.user,
        "user_agent": request.headers.get("User-Agent", "")[:255],
    })
    return JsonResponse({"success": True})
