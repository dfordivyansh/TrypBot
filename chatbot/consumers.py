# =========================================================
# FILE: chatbot/consumers.py
# WebSocket consumer for CRM real-time notifications
# =========================================================

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User


class CRMNotificationConsumer(AsyncWebsocketConsumer):
    """
    Each authenticated CRM user connects here.
    Group name: crm_user_{user_id}

    Events pushed to client:
      { type: "lead_label_change", session_id, session_name, label, phone }
      { type: "new_message",       session_id, session_name, preview }
      { type: "reminder_due",      session_id, session_name, note, reminder_at }
    """

    async def connect(self):
        print(f"[WEBSOCKET] Connection attempt from: {self.scope.get('client')}")
        user = self.scope.get("user")
        print(f"[WEBSOCKET] User: {user}, Authenticated: {user.is_authenticated if user else False}")
        
        if not user or not user.is_authenticated:
            print("[WEBSOCKET] Connection rejected - not authenticated")
            await self.close()
            return

        self.user_id   = user.id
        self.group_name = f"crm_user_{self.user_id}"

        print(f"[WEBSOCKET] User {self.user_id} connecting to group {self.group_name}")
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        print(f"[WEBSOCKET] Connection accepted for user {self.user_id}")

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        # Client → server messages are not used right now (read-only push channel)
        pass

    # ── Channel-layer event handlers ─────────────────────────────────────────

    async def lead_label_change(self, event):
        """Fired by crm_lead_signals when a label changes to HOT / FOLLOW UP."""
        await self.send(text_data=json.dumps({
            "type":         "lead_label_change",
            "session_id":   event["session_id"],
            "session_name": event["session_name"],
            "label":        event["label"],
            "phone":        event.get("phone", ""),
        }))

    async def new_message(self, event):
        """Fired when an incoming WhatsApp message arrives for the user's session."""
        await self.send(text_data=json.dumps({
            "type":         "new_message",
            "session_id":   event["session_id"],
            "session_name": event["session_name"],
            "preview":      event.get("preview", ""),
        }))

    async def reminder_due(self, event):
        """Fired by the reminder-checker management command / Celery beat."""
        await self.send(text_data=json.dumps({
            "type":         "reminder_due",
            "session_id":   event["session_id"],
            "session_name": event["session_name"],
            "note":         event.get("note", ""),
            "reminder_at":  event.get("reminder_at", ""),
        }))

    async def message_status(self, event):
        """Fired when a message status changes (sent/delivered/read)."""
        await self.send(text_data=json.dumps({
            "type":         "message_status",
            "message_id":   event["message_id"],
            "session_id":   event["session_id"],
            "status":       event["status"],
        }))

    async def chat_closed(self, event):
        """Fired when a chat is closed due to 24h inactivity."""
        await self.send(text_data=json.dumps({
            "type":         "chat_closed",
            "session_id":   event["session_id"],
            "session_name": event["session_name"],
            "phone":        event.get("phone", ""),
            "templates":    event.get("templates", []),
        }))

    async def chat_assigned(self, event):
        """Fired when a chat is assigned to a sales agent."""
        await self.send(text_data=json.dumps({
            "type":         "chat_assigned",
            "session_id":   event["session_id"],
            "session_name": event["session_name"],
            "phone":        event.get("phone", ""),
            "assigned_by":  event.get("assigned_by", ""),
        }))