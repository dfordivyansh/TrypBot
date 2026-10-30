# =========================================================
# FILE: chatbot/routing.py
# =========================================================

from django.urls import re_path
from . import consumers

print("[WEBSOCKET ROUTING] Loading WebSocket routes...")

websocket_urlpatterns = [
    re_path(r'^crm/notifications/$', consumers.CRMNotificationConsumer.as_asgi()),
]

print(f"[WEBSOCKET ROUTING] Loaded {len(websocket_urlpatterns)} route(s)")
# Debug print removed for production performance
# print(f"[WEBSOCKET ROUTING] Routes: {websocket_urlpatterns}")