"""
ASGI config for convoapi project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'convoapi.settings')
django.setup()

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import chatbot.routing

print("=" * 50)
print("[ASGI] Loading ASGI application...")
print(f"[ASGI] WebSocket routes: {chatbot.routing.websocket_urlpatterns}")
print("=" * 50)

inner_application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            chatbot.routing.websocket_urlpatterns
        )
    ),
})

# Campaign sender: a daemon thread that sends queued / scheduled WhatsApp
# campaigns. Disable with CAMPAIGN_INLINE_WORKER=0 and run
# `python manage.py run_campaigns` instead if you prefer a separate process.
from chatbot.campaign_engine import start_background_worker
if start_background_worker():
    print("[ASGI] Campaign worker thread started")

print("[ASGI] ASGI application loaded successfully")
print("=" * 50)

# Add application-level logging (removed debug prints in production)
async def application(scope, receive, send):
    # Debug prints removed for production performance
    # print(f"[ASGI] Request scope type: {scope.get('type')}")
    # print(f"[ASGI] Request path: {scope.get('path')}")
    # if scope.get('type') == 'websocket':
    #     print(f"[ASGI] WebSocket connection attempt to: {scope.get('path')}")
    return await inner_application(scope, receive, send)
