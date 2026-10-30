# =========================================================
# FILE: chatbot/crm_lead_signals.py
# =========================================================
# Push a real-time WebSocket notification to the assigned
# sales agent whenever a lead is labelled HOT or FOLLOW UP.
# Call push_label_notification() from crm_automation.py's
# _apply_conversation_label() after a successful label save.
# =========================================================

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def push_label_notification(session, label_name: str):
    """
    Send a channel-layer group message to the assigned sales person.
    Safe to call from synchronous Django views / model hooks.
    Falls back silently if channels is not installed or the layer
    is not configured — so this never breaks the normal request cycle.
    """
    try:
        assigned_user = session.assigned_sales_person
        if not assigned_user:
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        group_name = f"crm_user_{assigned_user.id}"

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type":         "lead_label_change",
                "session_id":   session.id,
                "session_name": session.user_name or session.phone_number or f"#{session.id}",
                "label":        label_name,
                "phone":        session.phone_number or "",
            },
        )
    except Exception as exc:
        # Never let a notification failure break the main flow
        print(f"[WS NOTIFY] push_label_notification error: {exc}")


def push_new_message_notification(session, preview: str):
    """
    Notify the assigned agent of a new incoming WhatsApp message.
    Call this from the webhook handler after saving an inbound message.
    """
    try:
        assigned_user = session.assigned_sales_person
        if not assigned_user:
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        group_name = f"crm_user_{assigned_user.id}"

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type":         "new_message",
                "session_id":   session.id,
                "session_name": session.user_name or session.phone_number or f"#{session.id}",
                "preview":      preview[:100],
            },
        )
    except Exception as exc:
        print(f"[WS NOTIFY] push_new_message_notification error: {exc}")


def push_reminder_notification(reminder):
    """
    Notify the creator of a reminder that it's now due.
    Call from a Celery beat task or management command.
    """
    try:
        target_user = reminder.created_by
        if not target_user:
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        group_name = f"crm_user_{target_user.id}"
        session    = reminder.session

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type":         "reminder_due",
                "session_id":   session.id,
                "session_name": session.user_name or session.phone_number or f"#{session.id}",
                "note":         reminder.note,
                "reminder_at":  reminder.reminder_at.strftime("%d %b %Y %I:%M %p"),
            },
        )
    except Exception as exc:
        print(f"[WS NOTIFY] push_reminder_notification error: {exc}")


def push_message_status_notification(message_id, status):
    """
    Notify the assigned agent of a message status update (sent/delivered/read).
    Call from the webhook status handler.
    """
    try:
        from .models import ChatMessage
        
        message = ChatMessage.objects.filter(id=message_id).first()
        if not message:
            return
            
        assigned_user = message.session.assigned_sales_person
        if not assigned_user:
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        group_name = f"crm_user_{assigned_user.id}"

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type":         "message_status",
                "message_id":   message.id,
                "session_id":   message.session.id,
                "status":       status,
            },
        )
    except Exception as exc:
        print(f"[WS NOTIFY] push_message_status_notification error: {exc}")


def push_chat_closed_notification(session):
    """
    Notify the assigned agent that a chat has been closed due to 24h inactivity.
    Includes available templates for re-engagement.
    """
    try:
        from .models import CRMTemplate
        
        assigned_user = session.assigned_sales_person
        if not assigned_user:
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        # Get available templates
        templates = list(CRMTemplate.objects.values('id', 'title')[:5])

        group_name = f"crm_user_{assigned_user.id}"

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type":         "chat_closed",
                "session_id":   session.id,
                "session_name": session.user_name or session.phone_number or f"#{session.id}",
                "phone":        session.phone_number or "",
                "templates":    templates,
            },
        )
    except Exception as exc:
        print(f"[WS NOTIFY] push_chat_closed_notification error: {exc}")


def push_chat_assigned_notification(session, assigned_user):
    """
    Notify a sales agent when a chat is assigned to them.
    Call from crm_assign_chat after successful assignment.
    """
    try:
        if not assigned_user:
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        group_name = f"crm_user_{assigned_user.id}"

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type":         "chat_assigned",
                "session_id":   session.id,
                "session_name": session.user_name or session.phone_number or f"#{session.id}",
                "phone":        session.phone_number or "",
                "assigned_by":  assigned_user.get_full_name() or assigned_user.username,
            },
        )
    except Exception as exc:
        print(f"[WS NOTIFY] push_chat_assigned_notification error: {exc}")