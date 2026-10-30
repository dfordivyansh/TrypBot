from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from django.shortcuts import render
from django.http import HttpResponse, FileResponse, JsonResponse
from django.utils import timezone
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
import os

from datetime import datetime, timedelta
from urllib.parse import quote

from concurrent.futures import ThreadPoolExecutor

from .models import ChatSession, ChatMessage, Lead
from .utils import (
    generate_response,
    handle_flow_submission,
    STAGE_CHAT,
    STAGE_FLOW_SENT,
    STAGE_CUSTOM_FLOW_SENT,
)
from .crm_helpers import assign_by_source, mark_lead_today

import threading
import uuid
import math
import time
import json
import hmac
import hashlib
import re
import requests
from django.db import transaction
import cloudinary
import cloudinary.uploader


# ======================================================
# CONFIG
# ======================================================

SESSION_TIMEOUT = 30

GOOGLE_MAPS_API_KEY = "AIzaSyAeTdIGqr794DWdBIYpF8hxdbuJkx1dR1o"

SERPAPI_KEY = "eb4cf4fc276dc07a4cd115fe843d273cecd0e0e92ac5d2e198809dd45e49746f"

GOOGLE_PLACE_BASE = "https://maps.googleapis.com/maps/api/place"

GOOGLE_GEOCODE_BASE = "https://maps.googleapis.com/maps/api"


# ======================================================
# CLOUDINARY UTILITIES
# ======================================================

def upload_to_cloudinary(image_url_or_file, public_id=None):
    """
    Upload an image to Cloudinary from a URL or file.
    Returns the Cloudinary URL or None on failure.
    """
    try:
        cloudinary.config(
            cloud_name=settings.CLOUDINARY['cloud_name'],
            upload_preset=settings.CLOUDINARY['upload_preset'],
            secure=True
        )
        
        upload_options = {
            'upload_preset': settings.CLOUDINARY['upload_preset'],
            'resource_type': 'image',
        }
        
        if public_id:
            upload_options['public_id'] = public_id
        
        print(f"[CLOUDINARY] Attempting upload. Type: {'URL' if isinstance(image_url_or_file, str) and image_url_or_file.startswith(('http://', 'https://')) else 'File/Bytes'}")
        
        # If it's a URL, upload from URL
        if isinstance(image_url_or_file, str) and image_url_or_file.startswith(('http://', 'https://')):
            result = cloudinary.uploader.upload(image_url_or_file, **upload_options)
        else:
            # Assume it's file content (bytes) or file object
            result = cloudinary.uploader.upload(image_url_or_file, **upload_options)
        
        print(f"[CLOUDINARY] Upload success. URL: {result.get('secure_url')}")
        return result.get('secure_url')
    except Exception as e:
        import traceback
        print(f"[CLOUDINARY] Upload error: {e}")
        traceback.print_exc()
        return None


# ======================================================
# CHAT API  (non-WhatsApp REST endpoint — used by web widget / testing)
# ======================================================

@api_view(["POST", "GET"])
def chat_api(request):

    try:

        message = request.data.get("message", "").strip()
        session_id = request.data.get("session_id")

        if not message:
            return Response({
                "success": False,
                "error": "Message required"
            }, status=400)

        if not session_id:
            session_id = str(uuid.uuid4())

        session, created = ChatSession.objects.get_or_create(
            session_id=session_id,
            defaults={"step": 1, "data": {}},
        )

        if session.updated_at:
            if session.updated_at < (timezone.now() - timedelta(minutes=SESSION_TIMEOUT)):
                session.step = 1
                session.data = {}
                session.save()

        # --------------------------------------------------
        # CHECK 3-MINUTE TIMEOUT FOR HUMAN ASSIGNMENT
        # --------------------------------------------------
        # If user hasn't sent a message in 3+ minutes and not under human takeover,
        # assign to human agent using round-robin
        if session.last_customer_message_time:
            time_since_last_message = timezone.now() - session.last_customer_message_time
            if time_since_last_message >= timedelta(minutes=3):
                if not session.is_human_takeover and not session.assigned_sales_person:
                    try:
                        assigned_user = assign_by_source(session)
                        if assigned_user:
                            mark_lead_today(session)
                            session.refresh_from_db()
                            session.is_human_takeover = True
                            session.save(update_fields=['is_human_takeover'])
                            print(f"[TIMEOUT ASSIGNMENT] Session {session.session_id} assigned to {assigned_user.username} after 3+ min inactivity")
                    except Exception as e:
                        print(f"[TIMEOUT ASSIGNMENT ERROR] {e}")

        # --------------------------------------------------
        # SAVE USER MESSAGE
        # --------------------------------------------------

        ChatMessage.objects.create(
            session=session,
            sender_type="user",
            message=message
        )

        bot_response = generate_response(message, session)

        if isinstance(bot_response, dict):

            reply_text = bot_response.get(
                "message",
                "Sorry, no response generated."
            )

            options = bot_response.get(
                "options",
                []
            )

            flow_payload = bot_response.get(
                "flow_payload",
                None
            )

        else:

            reply_text = str(bot_response)

            options = []

            flow_payload = None

        # --------------------------------------------------
        # SAVE BOT MESSAGE
        # --------------------------------------------------
        # Note: Bot message is already saved by _save_bot_reply_to_crm() in utils.py
        # to avoid duplicates. We just need to update session metadata.
        try:
            # Check if message already exists (saved by utils.py)
            existing_msg = ChatMessage.objects.filter(
                session=session,
                sender_type="bot",
                message=reply_text or ""
            ).latest('created_at')
            # Message exists, just update session metadata
        except ChatMessage.DoesNotExist:
            # Fallback: create if not exists (shouldn't happen normally)
            # Only create if message text is not empty
            if reply_text:
                ChatMessage.objects.create(
                    session=session,
                    sender_type="bot",
                    message=reply_text,
                    is_interactive=bool(options) or bool(flow_payload),
                )

        session.updated_at   = timezone.now()
        session.last_message = reply_text
        session.save()

        return Response({
            "success":      True,
            "reply":        reply_text,
            "options":      options,
            "flow_payload": flow_payload,   # web widget can render its own Flow-equivalent UI
            "step":         session.step,
            "session_id":   session.session_id,
            "data":         session.data
        })

    except Exception as e:

        return Response({
            "success": False,
            "error":   str(e)
        }, status=500)


# ======================================================
# UI
# ======================================================

def chatbot_ui(request):
    return render(request, "chatbot/index.html")


# ──────────────────────────────────────────────
# FOLLOW-UP CONFIG - REMOVED
# Automatic follow-ups have been disabled

SALES_AGENT_TRANSFER_MESSAGE = (
    "It looks like you may have questions about your travel plan. "
    "I am connecting you with one of our travel experts who will personally "
    "assist you with the best pricing and booking options. "
    "They will reach out to you very shortly!"
)

TYPING_INDICATOR_THRESHOLD = 900   # chars — split long replies at this boundary

# --------------------------------------------------------------------------
# HEAVY STAGES (v16.0.1 fix)
# --------------------------------------------------------------------------
# Previously this referenced legacy v15 STEP_* numbers (6, 7, 71, 27, 28, 50)
# that no longer exist in the v16 DFA — those steps never fire anymore because
# destination/days/travellers are no longer collected via free chat, they come
# from the WhatsApp Flow submission. The actual heavy (Gemini-calling) stages
# in v16 are STAGE_PACKAGE (package selection -> itinerary generation) and
# STAGE_MODIFY (regeneration after a modification request). Flow-sent stages
# (STAGE_FLOW_SENT / STAGE_CUSTOM_FLOW_SENT) are NOT heavy — they just display
# a form and wait, so no "please wait" text should precede them.
# --------------------------------------------------------------------------

HEAVY_STAGES = {
    20,   # STAGE_PACKAGE          — package chosen -> itinerary generation
    31,   # STAGE_MODIFY            — modification -> possible regeneration
    23,   # STAGE_ITINERARY_REVIEW  — approval -> may trigger regeneration
}

_WAIT_MESSAGES = {
    20: "Finding the best tour packages for you. Please wait a moment...",
    31: "Updating your itinerary. Please wait a moment...",
    23: "Reviewing your itinerary. Please wait a moment...",
}
_WAIT_MSG_DEFAULT = "Processing your request. Please wait a moment..."


def _get_wait_message(stage: int) -> str:
    """Returns the appropriate wait message for the given session stage."""
    return _WAIT_MESSAGES.get(stage, _WAIT_MSG_DEFAULT)


# ======================================================
# SEND TYPING INDICATOR
# ======================================================

def send_typing_indicator(to: str, user_message_id: str) -> None:
    """
    Marks the user's message as read and shows the typing indicator.

    Args:
        to              : user's WhatsApp phone number
        user_message_id : 'id' field from the incoming messages webhook
                          (e.g. "wamid.HBgL...")
    """
    if not user_message_id:
        print("[TYPING] Skipped — no user_message_id")
        return

    url = (
        f"https://graph.facebook.com/v22.0/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type":  "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status":            "read",
        "message_id":        user_message_id,
        "typing_indicator":  {"type": "text"},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=5)
        print(f"[TYPING] {resp.status_code} → {resp.text}")
    except Exception as e:
        print(f"[TYPING] Error: {e}")


# ======================================================
# INTERNAL HELPER — plain text only, no options
# ======================================================

def _send_plain_text(to: str, message: str) -> None:
    """Sends a short plain-text message with no interactive options."""
    url = (
        f"https://graph.facebook.com/v22.0/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type":  "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to":   str(to),
        "type": "text",
        "text": {"preview_url": False, "body": str(message)},
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=5)
        print(f"[PLAIN TEXT] {resp.status_code} → {resp.text}")
    except Exception as e:
        print(f"[PLAIN TEXT] Error: {e}")


# ======================================================
# SEND WHATSAPP MESSAGE  (plain text / buttons / list — NOT Flows)
# ======================================================

def send_whatsapp_message(
    to: str,
    message: str,
    options: list = None,
    user_message_id: str = "",
    session=None,
) -> dict:
    """
    Sends a WhatsApp message with optional interactive buttons / list.
    This function is for plain text and button/list interactives ONLY.
    WhatsApp Flow messages must go through send_flow_message() instead —
    do not pass flow payloads here.
    
    Args:
        to: Phone number to send to
        message: Message content
        options: Optional list of button options
        user_message_id: WhatsApp message ID for typing indicator
        session: ChatSession for spam detection tracking
    """

    # --------------------------------------------------
    # SPAM DETECTION - Check if messaging should be allowed
    # --------------------------------------------------
    if session:
        try:
            from .spam_detection import SpamDetector, RateLimiter
            
            # Check if messaging is allowed
            allowed, reason = SpamDetector.should_allow_messaging(session)
            if not allowed:
                print(f"[SPAM DETECTION] Messaging blocked: {reason}")
                return {"error": f"Messaging blocked: {reason}"}
            
            # Check rate limits
            allowed, reason = RateLimiter.check_rate_limit(session)
            if not allowed:
                print(f"[RATE LIMIT] Messaging blocked: {reason}")
                return {"error": f"Rate limit exceeded: {reason}"}
                
        except Exception as e:
            print(f"Spam detection error: {e}")

    url = (
        f"https://graph.facebook.com/v22.0/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type":  "application/json",
    }

    message = str(message)
    is_long = len(message) > TYPING_INDICATOR_THRESHOLD

    def _interactive(body_text: str, opts: list) -> dict:
        if len(opts) <= 3:
            buttons = [
                {"type": "reply", "reply": {"id": o, "title": o[:20]}}
                for o in opts
            ]
            return {
                "messaging_product": "whatsapp",
                "to":   str(to),
                "type": "interactive",
                "interactive": {
                    "type":   "button",
                    "body":   {"text": body_text},
                    "action": {"buttons": buttons},
                },
            }
        rows = [{"id": o, "title": o[:24]} for o in opts[:10]]
        return {
            "messaging_product": "whatsapp",
            "to":   str(to),
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body_text},
                "action": {
                    "button":   "View Options",
                    "sections": [{"title": "Available Options", "rows": rows}],
                },
            },
        }

    def _post(label: str, payload: dict) -> dict:
        print(f"\n========== {label} PAYLOAD ==========")
        print(payload)
        resp = requests.post(url, headers=headers, json=payload)
        print(f"\n========== {label} RESPONSE ==========")
        print(resp.status_code, resp.text)
        return resp.json()

    # ── LONG MESSAGE ──────────────────────────────────────────────────────
    if is_long:
        if user_message_id:
            send_typing_indicator(to, user_message_id)
            time.sleep(0.5)

        text_payload = {
            "messaging_product": "whatsapp",
            "to":   str(to),
            "type": "text",
            "text": {"preview_url": False, "body": message[:4096]},
        }
        result = _post("LONG TEXT", text_payload)

        if not options:
            return result

        return _post("LONG + OPTIONS", _interactive("What would you like to do next?", options))

    # ── SHORT MESSAGE — no options ─────────────────────────────────────────
    if not options:
        return _post("SHORT TEXT", {
            "messaging_product": "whatsapp",
            "to":   str(to),
            "type": "text",
            "text": {"preview_url": False, "body": message},
        })

    # ── SHORT MESSAGE — with options ───────────────────────────────────────
    return _post("INTERACTIVE", _interactive(message, options))


# ======================================================
# SEND WHATSAPP TEMPLATE MESSAGE
# ======================================================

def send_whatsapp_template_message(to: str, template_name: str, components: list = None) -> dict:
    """
    Sends a WhatsApp template message to a phone number.
    Template messages can be sent to new numbers (outside 24-hour window).
    
    Args:
        to: Phone number with country code (e.g., "919876543210")
        template_name: Name of the template in WhatsApp Business API
        components: Optional list of template components for dynamic values
    
    Returns:
        dict: WhatsApp API response
    """
    url = (
        f"https://graph.facebook.com/v22.0/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type":  "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": str(to),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en"},
        }
    }
    
    if components:
        payload["template"]["components"] = components

    print(f"\n========== TEMPLATE MESSAGE PAYLOAD ==========")
    print(payload)
    resp = requests.post(url, headers=headers, json=payload)
    print(f"\n========== TEMPLATE MESSAGE RESPONSE ==========")
    print(resp.status_code, resp.text)
    return resp.json()


# ======================================================
# SEND WHATSAPP FLOW MESSAGE  (v16.0.1 fix)
#
# build_flow_message() in utils.py returns ONLY the
# {"type": "interactive", "interactive": {...}} portion — it deliberately
# omits "messaging_product" and "to" because utils.py has no access to the
# phone number. This function must add BOTH required top-level fields before
# POSTing, or the Cloud API rejects the request.
# ======================================================

def send_flow_message(to: str, payload: dict) -> dict:
    """
    Sends a WhatsApp Flow interactive message.

    `payload` is the dict returned by build_basic_travel_flow() / build_daywise_flow()
    in utils.py: {"type": "interactive", "interactive": {...}}.
    This function adds the required messaging_product/to envelope fields.
    """
    url = (
        f"https://graph.facebook.com/v22.0/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    full_payload = {
        "messaging_product": "whatsapp",
        "to": str(to),
        **payload,   # contributes "type" and "interactive"
    }

    print("\n========== FLOW MESSAGE PAYLOAD ==========")
    print(full_payload)

    response = requests.post(url, headers=headers, json=full_payload, timeout=10)

    print("\n========== FLOW MESSAGE RESPONSE ==========")
    print(response.status_code, response.text)

    try:
        return response.json()
    except Exception:
        return {"success": False, "status_code": response.status_code, "text": response.text}


# ======================================================
# TRANSFER TO SALES AGENT
# ======================================================

def _transfer_to_sales_agent(session):
    from .models import ChatMessage

    try:
        session.refresh_from_db()

        session.data["_expert_contacted"]   = True
        session.data["_last_followup_sent"] = 3
        session.updated_at = timezone.now()
        session.save()

        _send_plain_text(session.phone_number, SALES_AGENT_TRANSFER_MESSAGE)

        ChatMessage.objects.create(
            session=session,
            sender_type="bot",
            message=SALES_AGENT_TRANSFER_MESSAGE,
        )

        print(f"[TRANSFER] Lead marked for sales followup: {session.id}")

    except Exception as e:
        print(e)


# ======================================================
# AUTO FOLLOW-UP SENDER - REMOVED
# Automatic follow-ups have been disabled
# ======================================================

# ======================================================
# MESSAGE STATUS HANDLER
# ======================================================

def handle_message_status(status_data):
    """
    Handle WhatsApp message status updates (sent, delivered, read).
    Updates ChatMessage.message_status based on webhook status.
    """
    try:
        from .models import ChatMessage
        from .crm_lead_signals import push_message_status_notification
        
        message_id = status_data.get("id", "")
        status = status_data.get("status", "")
        
        print(f"\n========== MESSAGE STATUS ==========")
        print(f"Message ID: {message_id}")
        print(f"Status: {status}")
        
        # Log error details for failed messages
        if status == "failed":
            error_code = status_data.get("errors", [{}])[0].get("code", "")
            error_title = status_data.get("errors", [{}])[0].get("title", "")
            error_message = status_data.get("errors", [{}])[0].get("message", "")
            print(f"Error Code: {error_code}")
            print(f"Error Title: {error_title}")
            print(f"Error Message: {error_message}")
        
        if not message_id:
            return
        
        # Map WhatsApp status to our model status
        status_mapping = {
            "sent": "sent",
            "delivered": "delivered",
            "read": "read",
            "failed": "failed",
        }
        
        new_status = status_mapping.get(status)
        if not new_status:
            print(f"Unknown status: {status}")
            return

        # Campaign delivery tracking (no-op unless the message belongs to a campaign)
        try:
            from .campaign_engine import on_status_update
            on_status_update(
                message_id, new_status,
                timestamp=status_data.get("timestamp"),
                errors=status_data.get("errors"),
            )
        except Exception as e:
            print(f"[CAMPAIGN] status hook error: {e}")
        
        # Update message status in database
        updated = ChatMessage.objects.filter(
            whatsapp_message_id=message_id
        ).update(message_status=new_status)
        
        if updated:
            print(f"Updated {updated} message(s) to status: {new_status}")
            # Get the message ID to send WebSocket notification
            message = ChatMessage.objects.filter(whatsapp_message_id=message_id).first()
            if message:
                push_message_status_notification(message.id, new_status)

                # Tell the agent in the chat why it failed and how to fix it.
                if new_status == "failed" and not (isinstance(message.raw_payload, dict) and "campaign_id" in message.raw_payload):
                    try:
                        from .whatsapp_errors import note_delivery_failure
                        err = (status_data.get("errors") or [{}])[0]
                        details = (err.get("error_data") or {}).get("details") or err.get("message") or err.get("title") or ""
                        # Keep Meta's error on the message too (shown on the red icon).
                        payload = message.raw_payload if isinstance(message.raw_payload, dict) else {}
                        payload["delivery_error"] = {"code": err.get("code"), "details": details}
                        ChatMessage.objects.filter(pk=message.pk).update(raw_payload=payload)
                        what = "The bot's reply" if message.sender_type == "bot" else "This message"
                        note_delivery_failure(message=message, code=err.get("code"), details=details, what=what)
                    except Exception as e:
                        print(f"[DELIVERY NOTE] {e}")

                # --------------------------------------------------
                # SPAM DETECTION - Track delivery failures
                # --------------------------------------------------
                # Broadcast messages are excluded: every receipt would count as a
                # "bot message" and trigger low-engagement alerts for every recipient.
                is_campaign_msg = (
                    isinstance(message.raw_payload, dict)
                    and "campaign_id" in message.raw_payload
                )
                try:
                    if not is_campaign_msg:
                        from .spam_detection import SpamDetector
                        SpamDetector.update_engagement_metrics(
                            message.session,
                            message_type='bot',
                            delivery_status=new_status
                        )
                except Exception as e:
                    print(f"Spam detection error: {e}")
        else:
            print(f"No message found with ID: {message_id}")
            
    except Exception as e:
        print(f"Error handling message status: {e}")


# ======================================================
# WHATSAPP WEBHOOK
# ======================================================

@api_view(["GET", "POST"])
def whatsapp_webhook(request):

    # --------------------------------------------------
    # VERIFY WEBHOOK
    # --------------------------------------------------

    if request.method == "GET":
        verify_token = request.GET.get("hub.verify_token")
        challenge    = request.GET.get("hub.challenge")

        print("\n========== WEBHOOK VERIFY ==========")
        print("VERIFY TOKEN:", verify_token)
        print("CHALLENGE:",    challenge)

        if verify_token == settings.WHATSAPP_VERIFY_TOKEN:
            print("WEBHOOK VERIFIED SUCCESSFULLY")
            return HttpResponse(challenge)

        print("WEBHOOK VERIFICATION FAILED")
        return HttpResponse("Verification failed")

    # --------------------------------------------------
    # RECEIVE MESSAGE
    # --------------------------------------------------

    try:

        print("\n========== WHATSAPP WEBHOOK HIT ==========")

        body    = request.data
        entry   = body.get("entry", [])

        if not entry:
            return Response({"success": True})

        changes = entry[0].get("changes", [])
        if not changes:
            return Response({"success": True})

        value = changes[0].get("value", {})

        # --------------------------------------------------
        # PHONE NUMBER VALIDATION
        # --------------------------------------------------

        metadata                = value.get("metadata", {})
        incoming_phone_id       = str(metadata.get("phone_number_id",     ""))
        incoming_display_number = str(metadata.get("display_phone_number", ""))

        print("\n========== PHONE VALIDATION ==========")
        print("INCOMING PHONE ID:", incoming_phone_id)
        print("INCOMING NUMBER:",   incoming_display_number)
        print("EXPECTED PHONE ID:", settings.WHATSAPP_PHONE_NUMBER_ID)

        # Ignore messages from other platform (772434515947390)
        if incoming_phone_id == "772434515947390":
            print(f"IGNORED — other platform: {incoming_display_number}")
            return Response({"success": True, "ignored": True, "reason": "other_platform"})

        if incoming_phone_id != str(settings.WHATSAPP_PHONE_NUMBER_ID):
            print(f"IGNORED — different number: {incoming_display_number}")
            return Response({"success": True, "ignored": True, "reason": "different_phone_number"})

        statuses = value.get("statuses", [])
        if statuses:
            # Handle message status updates (sent, delivered, read)
            for status in statuses:
                handle_message_status(status)
            return Response({"success": True, "type": "status"})

        messages = value.get("messages", [])
        if not messages:
            return Response({"success": True})

        # --------------------------------------------------
        # MESSAGE DATA
        # --------------------------------------------------

        message_data = messages[0]

        print("\n========== MESSAGE DATA ==========")
        print(message_data)

        message_id   = message_data.get("id",   "")   # wamid
        user_number  = message_data.get("from", "")
        
        contact_name = (
            value.get("contacts", [{}])[0]
            .get("profile", {})
            .get("name", "")
        )
        message_type = message_data.get("type", "")

        print("\n========== MESSAGE TYPE ==========")
        print(message_type)

        message_text = ""
        is_flow_submission = False
        flow_interactive    = None   # raw interactive dict, kept for flow handling
        media_url          = None    # Cloudinary URL for images
        media_type         = None    # image, video, document, audio

        if message_type == "text":
            message_text = message_data.get("text", {}).get("body", "").strip()

        elif message_type in ("image", "video", "document", "audio"):
            # Handle media messages
            media_data = message_data.get(message_type, {})
            media_id = media_data.get("id", "")
            
            if media_id:
                # Download media from WhatsApp and upload to Cloudinary
                try:
                    from .crm_views import download_whatsapp_media
                    downloaded_url, mime_type, filename = download_whatsapp_media(media_id)
                    
                    if downloaded_url and message_type == "image":
                        # Upload to Cloudinary for images
                        cloudinary_url = upload_to_cloudinary(downloaded_url)
                        if cloudinary_url:
                            media_url = cloudinary_url
                            print(f"[CLOUDINARY] Received image uploaded: {cloudinary_url}")
                        else:
                            media_url = downloaded_url
                    else:
                        media_url = downloaded_url
                    
                    media_type = message_type
                    message_text = f"[{message_type.capitalize()}]"  # Placeholder text
                except Exception as e:
                    print(f"[WEBHOOK] Media download/upload error: {e}")
                    message_text = f"[{message_type.capitalize()} - Error loading]"

        elif message_type == "interactive":
            interactive      = message_data.get("interactive", {})
            interactive_type = interactive.get("type", "")

            print("\n========== INTERACTIVE DATA ==========")
            print(interactive)

            if interactive_type == "list_reply":
                message_text = (
                    interactive.get("list_reply", {}).get("id")
                    or interactive.get("list_reply", {}).get("title", "")
                )

            elif interactive_type == "button_reply":
                message_text = (
                    interactive.get("button_reply", {}).get("id")
                    or interactive.get("button_reply", {}).get("title", "")
                )

            elif interactive_type == "nfm_reply":
                # v16.0.1 fix:
                #   - Do NOT touch `session` here — it doesn't exist yet.
                #   - Do NOT pre-parse response_json here — it's a JSON STRING,
                #     and parsing/routing needs the session, which we don't have
                #     until after the session lookup below. We just remember
                #     that this is a flow submission and carry the raw
                #     `interactive` dict forward.
                is_flow_submission = True
                flow_interactive   = interactive
                # Placeholder text so the existing dedup/empty-message guards
                # below behave the same way as for normal messages.
                message_text = "__FLOW_SUBMITTED__"

        message_text = str(message_text).replace("Select ", "").strip()

        print("\n========== FINAL USER MESSAGE ==========")
        print(message_text)

        if not message_text:
            return Response({"success": True})

        # --------------------------------------------------
        # GET / CREATE SESSION
        # --------------------------------------------------

        with transaction.atomic():

            from .models import ChatSession, ChatMessage

            session, created = ChatSession.objects.select_for_update().get_or_create(
                session_id=user_number,
                defaults={"step": 1, "data": {}},
            )

            # Check for duplicate message ID to prevent saving to CRM
            # But still allow processing so bot can reply
            duplicate_exists = ChatMessage.objects.filter(
                session=session,
                whatsapp_message_id=message_id
            ).exists()

            # The lock is released at the end of the reply; one left behind
            # by a restart or crash mid-reply expires after 2 minutes so the
            # chat does not go silent for good.
            import time as _time
            # Meta re-delivers a message when we answer with an error; once
            # the bot has replied to it, answering again only piles up copies.
            if duplicate_exists:
                user_msg = ChatMessage.objects.filter(session=session, whatsapp_message_id=message_id).order_by("created_at").first()
                if user_msg and ChatMessage.objects.filter(session=session, sender_type="bot", created_at__gte=user_msg.created_at).exists():
                    print(f"[DUPLICATE] {message_id} already answered — ignored")
                    return Response({"success": True})

            if session.data.get("_processing") and _time.time() - float(session.data.get("_processing_at") or 0) < 120:
                print("MESSAGE IGNORED — PROCESSING ACTIVE")
                return Response({"success": True})

            session.data["_processing"]       = True
            session.data["_processing_at"]    = _time.time()
            session.data["_last_message_id"]  = message_id
            session.data["_followup_stopped"] = True
            session.phone_number              = user_number

            if contact_name:
                session.user_name = contact_name

            session.save()

            # --------------------------------------------------
            # CHECK 3-MINUTE TIMEOUT FOR HUMAN ASSIGNMENT
            # --------------------------------------------------
            # If user hasn't sent a message in 3+ minutes and not under human takeover,
            # assign to human agent using round-robin
            if session.last_customer_message_time:
                time_since_last_message = timezone.now() - session.last_customer_message_time
                if time_since_last_message >= timedelta(minutes=3):
                    if not session.is_human_takeover and not session.assigned_sales_person:
                        try:
                            assigned_user = assign_by_source(session)
                            if assigned_user:
                                mark_lead_today(session)
                                session.refresh_from_db()
                                session.is_human_takeover = True
                                session.save(update_fields=['is_human_takeover'])
                                print(f"[TIMEOUT ASSIGNMENT] Session {session.session_id} assigned to {assigned_user.username} after 3+ min inactivity")
                        except Exception as e:
                            print(f"[TIMEOUT ASSIGNMENT ERROR] {e}")

            # Record opt-in for new sessions
            if created:
                try:
                    from .spam_detection import SpamDetector
                    SpamDetector.record_opt_in(
                        phone_number=user_number,
                        method='whatsapp',
                        session=session,
                        consent_text='User initiated WhatsApp conversation'
                    )
                    print(f"[OPT-IN] Recorded opt-in for new session {session.id}")
                except Exception as e:
                    print(f"[OPT-IN ERROR] Failed to record opt-in: {e}")

        print("\n========== SESSION ==========")
        print("SESSION ID:", session.session_id, "| STEP:", session.step)

        # --------------------------------------------------
        # SAVE USER MESSAGE
        # --------------------------------------------------

        # When the customer actually sent it. Meta re-delivers a message for
        # days while our webhook errors, and its 24-hour window counts from
        # this time, not from when we finally receive it.
        sent_at = timezone.now()
        try:
            ts = int(message_data.get("timestamp") or 0)
            if ts:
                from datetime import datetime, timezone as dt_timezone
                sent_at = min(sent_at, datetime.fromtimestamp(ts, tz=dt_timezone.utc))
        except (TypeError, ValueError):
            pass
        received_late = (timezone.now() - sent_at) >= timedelta(hours=23, minutes=50)

        # Only save to CRM if not a duplicate
        if not duplicate_exists:
            user_msg = ChatMessage.objects.create(
                session=session,
                sender_type="user",
                message=message_text,
                whatsapp_message_id=message_id,
                raw_payload=message_data,
                # these columns are NOT NULL — plain text messages have no media
                media_url=media_url or "",
                media_type=media_type or "",
            )
            if (timezone.now() - sent_at) > timedelta(minutes=2):
                ChatMessage.objects.filter(pk=user_msg.pk).update(created_at=sent_at)
        else:
            print(f"[DUPLICATE] Skipping CRM save for message ID {message_id} (already exists)")

        # Update last customer message time for 24-hour window
        if not session.last_customer_message_time or sent_at > session.last_customer_message_time:
            session.last_customer_message_time = sent_at
            session.save(update_fields=["last_customer_message_time"])

        if received_late:
            # WhatsApp would reject any free-text reply (131047), so don't let
            # the bot answer; tell the team to re-open the chat with a template.
            hours = int((timezone.now() - sent_at).total_seconds() // 3600)
            print(f"[LATE MESSAGE] {user_number}: sent {hours}h ago — bot reply skipped")
            if not duplicate_exists:
                try:
                    from .models import InternalNote
                    InternalNote.objects.create(
                        session=session, added_by=None,
                        note=(f"This message reached the CRM late: the customer sent it "
                              f"{timezone.localtime(sent_at).strftime('%d %b %Y, %I:%M %p')} ({hours} hours ago). "
                              f"WhatsApp's 24-hour window is closed - reply with a template (Follow Up)."),
                    )
                except Exception as e:
                    print(f"[LATE MESSAGE] note error: {e}")
                session.unread_count = (session.unread_count or 0) + 1
            session.last_message = message_text[:500]
            session.updated_at = timezone.now()
            session.data["_processing"] = False
            session.save()
            return Response({"success": True, "late": True})

        # --------------------------------------------------
        # CAMPAIGNS — reply tracking + STOP / SUBSCRIBE keywords
        # --------------------------------------------------
        if not duplicate_exists and not is_flow_submission:
            try:
                from .campaign_engine import on_inbound_message, OPT_OUT_REPLY, OPT_IN_REPLY
                opt_result = on_inbound_message(session, message_text)
            except Exception as e:
                opt_result = None
                print(f"[CAMPAIGN] inbound hook error: {e}")

            if opt_result:
                confirm = OPT_OUT_REPLY if opt_result == "opted_out" else OPT_IN_REPLY
                _send_plain_text(user_number, confirm)
                try:
                    from .utils import _save_bot_reply_to_crm
                    _save_bot_reply_to_crm(session, confirm)
                except Exception as e:
                    print(f"[CAMPAIGN] could not save opt-out confirmation: {e}")
                session.data["_processing"] = False
                session.save()
                return Response({"success": True, "marketing_opt": opt_result})

        # --------------------------------------------------
        # SPAM DETECTION - Update engagement metrics
        # --------------------------------------------------
        try:
            from .spam_detection import SpamDetector
            SpamDetector.update_engagement_metrics(
                session, 
                message_type='user', 
                message_text=message_text
            )
        except Exception as e:
            print(f"Spam detection error: {e}")

        # --------------------------------------------------
        # HUMAN TAKEOVER CHECK
        # --------------------------------------------------

        session.refresh_from_db(fields=["is_human_takeover"])

        # Allow flow submissions to be processed even during human takeover
        # to save form data and send summary, but keep bot silent for other messages
        if session.is_human_takeover and not is_flow_submission:
            print("HUMAN TAKEOVER ACTIVE — bot silent")
            session.unread_count       += 1
            session.updated_at          = timezone.now()
            session.data["_processing"] = False
            session.save()
            # Notify assigned sales person about new message
            try:
                from .crm_lead_signals import push_new_message_notification
                push_new_message_notification(session, message_text[:100])
            except Exception as e:
                print(f"Failed to send notification: {e}")
            return Response({"success": True, "human_takeover": True})

        # --------------------------------------------------
        # TYPING INDICATOR — fire immediately on receipt
        # --------------------------------------------------

        send_typing_indicator(user_number, message_id)

        # --------------------------------------------------
        # WAIT MESSAGE for heavy stages
        #
        # v16.0.1 fix: read from session.data["stage"] (the v16 DFA stage),
        # not session.step (legacy field, may be stale). Also skip entirely
        # for flow submissions sent to STAGE_FLOW_SENT / STAGE_CUSTOM_FLOW_SENT —
        # those are NOT heavy on receipt of the flow message itself; the
        # heavy work only happens once the flow handler decides to call
        # generate_itinerary() inside handle_flow_submission().
        # --------------------------------------------------

        current_stage = session.data.get("stage", session.step)

        if not is_flow_submission and current_stage in HEAVY_STAGES:
            wait_msg = _get_wait_message(current_stage)
            print(f"\n[WAIT MSG] Sending for stage {current_stage}: {wait_msg}")
            _send_plain_text(user_number, wait_msg)
        elif is_flow_submission:
            # Flow submissions that land in STAGE_PACKAGE-adjacent territory
            # (group tour date selection, day-wise submission, package pick)
            # always trigger itinerary generation — show the wait message.
            wait_msg = _get_wait_message(20)
            print(f"\n[WAIT MSG] Sending for flow submission: {wait_msg}")
            _send_plain_text(user_number, wait_msg)

        # --------------------------------------------------
        # GENERATE RESPONSE
        #
        # v16.0.1 fix: flow submissions are routed to handle_flow_submission()
        # with the RAW interactive dict (so it can extract+parse response_json
        # itself), never through generate_response() with the sentinel string.
        # --------------------------------------------------

        print("\n========== GENERATING RESPONSE ==========")

        if is_flow_submission:
            bot_response = handle_flow_submission(session, flow_interactive)
        else:
            bot_response = generate_response(message_text, session)

        print("\n========== RAW BOT RESPONSE ==========")
        print(bot_response)

        if isinstance(bot_response, dict):

            reply_text = bot_response.get(
                "message",
                "Sorry, no response generated."
            )

            options = bot_response.get(
                "options",
                []
            )

            flow_payload = bot_response.get(
                "flow_payload",
                None
            )

        else:

            reply_text = str(bot_response)

            options = []

            flow_payload = None

        print("\n========== FLOW PAYLOAD ==========")
        print(flow_payload)

        print("\n========== OPTIONS ==========")
        print(options)

        print("\n========== FINAL REPLY ==========")
        print(reply_text)

        # --------------------------------------------------
        # UPDATE SESSION
        #
        # v16.0.1 fix: don't blindly reset the follow-up ladder if this
        # turn ended in a handoff (_expert_contacted) — handle_lead_handoff()
        # in utils.py already set _followup_stopped=True and we must not
        # immediately undo that here.
        # --------------------------------------------------

        if not session.data.get("_expert_contacted"):
            session.data["_followup_stopped"]   = False
            session.data["_last_followup_sent"] = 0

        session.updated_at          = timezone.now()
        session.last_message        = reply_text
        session.unread_count       += 1
        session.data["_processing"] = False
        session.save()

        # --------------------------------------------------
        # SEND WHATSAPP REPLY
        #
        # v16.0.1 fix: flow_payload now reliably routes to send_flow_message(),
        # which adds the required messaging_product/to envelope.
        # --------------------------------------------------

        print("\n========== SENDING WHATSAPP MESSAGE ==========")

        try:
            if flow_payload:
                whatsapp_response = send_flow_message(user_number, flow_payload)
            else:
                whatsapp_response = send_whatsapp_message(
                    user_number,
                    reply_text,
                    options,
                    user_message_id=message_id,
                )
        except Exception as e:
            # Logged, but still answer Meta with 200 so it does not re-deliver
            # the message and make the bot reply again.
            import traceback; traceback.print_exc()
            print(f"[WHATSAPP SEND FAILED] {user_number}: {e}")
            whatsapp_response = {"error": str(e)}
        if isinstance(whatsapp_response, dict) and whatsapp_response.get("error"):
            print(f"[WHATSAPP SEND FAILED] {user_number}: {whatsapp_response.get('error')}")

        # --------------------------------------------------
        # SAVE BOT MESSAGE
        # --------------------------------------------------
        # Note: Bot message is already saved by _save_bot_reply_to_crm() in utils.py
        # to avoid duplicates. We just need the message ID for status tracking.
        try:
            # Try to find the bot message saved by utils.py (within last 30 seconds)
            thirty_seconds_ago = timezone.now() - timezone.timedelta(seconds=30)
            
            bot_msg = ChatMessage.objects.filter(
                session=session,
                sender_type="bot",
                created_at__gte=thirty_seconds_ago
            ).latest('created_at')
            
            # Update bot message with WhatsApp message ID for status tracking
            whatsapp_message_id = ""
            if isinstance(whatsapp_response, dict):
                whatsapp_message_id = whatsapp_response.get("messages", [{}])[0].get("id", "")
            
            if whatsapp_message_id:
                bot_msg.whatsapp_message_id = whatsapp_message_id
                bot_msg.message_status = "sent"
                bot_msg.save(update_fields=["whatsapp_message_id", "message_status"])
                
        except ChatMessage.DoesNotExist:
            # Fallback: create if not exists (shouldn't happen normally)
            # Only create if message text is not empty AND no recent duplicate exists
            if reply_text:
                # Check for duplicate message in last minute to prevent duplicates
                one_minute_ago = timezone.now() - timezone.timedelta(minutes=1)
                if ChatMessage.objects.filter(
                    session=session,
                    sender_type="bot",
                    message=reply_text,
                    created_at__gte=one_minute_ago
                ).exists():
                    print(f"[DUPLICATE PREVENTION] Skipping duplicate bot message for session {session.id}")
                else:
                    whatsapp_message_id = ""
                    if isinstance(whatsapp_response, dict):
                        whatsapp_message_id = whatsapp_response.get("messages", [{}])[0].get("id", "")
                    
                    bot_msg = ChatMessage.objects.create(
                        session=session,
                        sender_type="bot",
                        message=reply_text,
                        is_interactive=bool(options) or bool(flow_payload),
                        whatsapp_message_id=whatsapp_message_id,
                        message_status="sent" if whatsapp_message_id else "sent"
                    )
            else:
                bot_msg = None

        print("\n========== WHATSAPP API RESPONSE ==========")
        print(whatsapp_response)

        # --------------------------------------------------
        # FOLLOW-UP SYSTEM REMOVED
        # Automatic follow-ups have been completely disabled
        # --------------------------------------------------

        print(f"\n[FOLLOW-UP] Disabled — automatic follow-ups removed")

        return Response({"success": True})

    except Exception as e:

        print("\n========== WHATSAPP ERROR ==========")
        print(str(e))

        try:
            if "session" in locals():
                session.data["_processing"] = False
                session.save()
        except Exception:
            pass

        import traceback; traceback.print_exc()

        return Response({"success": False, "error": str(e)}, status=500)


from django.contrib.auth.decorators import login_required


@login_required
def dashboard(request):

    sessions = ChatSession.objects.all().order_by("-updated_at")

    session_id = request.GET.get("session")

    active_session = None
    messages = []

    if session_id:

        active_session = ChatSession.objects.get(id=session_id)

        messages = ChatMessage.objects.filter(
            session=active_session
        ).order_by("created_at")

        active_session.unread_count = 0
        active_session.save()

    if request.method == "POST":

        text = request.POST.get("message")

        if text and active_session:

            send_whatsapp_message(active_session.phone_number, text)

            ChatMessage.objects.create(
                session=active_session,
                sender_type="agent",
                message=text
            )

        if request.POST.get("human_takeover"):
            active_session.is_human_takeover = True
            active_session.save()

    return render(
        request,
        "chatbot/dashboard.html",
        {
            "sessions": sessions,
            "active_session": active_session,
            "messages": messages,
        }
    )


# =========================================================================================================
# HOTEL / PLACES UTILITIES — unchanged from prior version
# =========================================================================================================

def pick_city(address=""):
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) >= 3:
        return parts[-3]
    if len(parts) >= 2:
        return parts[0]
    return parts[0] if parts else ""


def generate_future_dates():
    check_in = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    check_out = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    return {"check_in": check_in, "check_out": check_out}


def get_city_coordinates(city):
    try:
        url = (
            f"{GOOGLE_GEOCODE_BASE}/geocode/json"
            f"?address={city}"
            f"&key={GOOGLE_MAPS_API_KEY}"
        )
        response = requests.get(url, timeout=20)
        data = response.json()
        print("GEOCODE RESPONSE:", data)
        results = data.get("results", [])
        if not results:
            return None
        location = results[0].get("geometry", {}).get("location", {})
        return {"lat": location.get("lat"), "lng": location.get("lng")}
    except Exception as e:
        print("GEOCODE ERROR:", e)
        return None


def generate_grid_points(lat, lng):
    points = []
    offsets = [-0.02, 0, 0.02]
    for lat_offset in offsets:
        for lng_offset in offsets:
            points.append({"lat": lat + lat_offset, "lng": lng + lng_offset})
    return points


def fetch_place_details(place_id):
    try:
        fields = ",".join([
            "formatted_phone_number",
            "international_phone_number",
            "website",
        ])
        url = (
            f"{GOOGLE_PLACE_BASE}/details/json"
            f"?place_id={place_id}"
            f"&fields={fields}"
            f"&key={GOOGLE_MAPS_API_KEY}"
        )
        response = requests.get(url, timeout=20)
        json_data = response.json()
        return json_data.get("result", {})
    except Exception as e:
        print("PLACE DETAILS ERROR:", e)
        return {}


@api_view(["GET"])
def search_hotels_api(request):
    try:
        city = request.GET.get("query", "").strip()
        if not city:
            return Response({"success": False, "error": "Query required"}, status=400)

        coordinates = get_city_coordinates(city)
        if not coordinates:
            return Response({"success": False, "error": "City not found"}, status=400)

        lat = coordinates["lat"]
        lng = coordinates["lng"]

        grid_points = generate_grid_points(lat, lng)
        all_hotels = {}

        for point in grid_points:
            try:
                search_url = (
                    f"{GOOGLE_PLACE_BASE}/nearbysearch/json"
                    f"?location={point['lat']},{point['lng']}"
                    f"&radius=3000"
                    f"&type=lodging"
                    f"&key={GOOGLE_MAPS_API_KEY}"
                )
                response = requests.get(search_url, timeout=15)
                json_data = response.json()
                status_ = json_data.get("status")
                print("GRID STATUS:", status_)
                if status_ != "OK":
                    continue
                hotels = json_data.get("results", [])
                for hotel in hotels:
                    place_id = hotel.get("place_id")
                    if place_id and place_id not in all_hotels:
                        all_hotels[place_id] = hotel
            except Exception as grid_error:
                print("GRID ERROR:", grid_error)

        def process_hotel(hotel):
            try:
                place_id = hotel.get("place_id")
                details = fetch_place_details(place_id)

                photo_ref = None
                if hotel.get("photos"):
                    photo_ref = hotel.get("photos", [{}])[0].get("photo_reference")

                photo_url = None
                if photo_ref:
                    photo_url = (
                        "https://trypbot.duckdns.org/api/place-photo/"
                        f"?ref={photo_ref}&w=400"
                    )

                return {
                    "place_id": place_id,
                    "name": hotel.get("name"),
                    "address": hotel.get("vicinity"),
                    "phone": details.get("formatted_phone_number"),
                    "rating": hotel.get("rating"),
                    "user_ratings_total": hotel.get("user_ratings_total", 0),
                    "location": hotel.get("geometry", {}).get("location"),
                    "photo_ref": photo_ref,
                    "photo_url": photo_url,
                }
            except Exception as e:
                print("PROCESS HOTEL ERROR:", e)
                return None

        results = []
        hotel_list = list(all_hotels.values())

        with ThreadPoolExecutor(max_workers=20) as executor:
            processed_hotels = executor.map(process_hotel, hotel_list)

        for item in processed_hotels:
            if item:
                results.append(item)

        results = sorted(results, key=lambda x: (x.get("user_ratings_total", 0)), reverse=True)

        return Response({"success": True, "total_hotels": len(results), "results": results})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["POST"])
def hotel_rates_api(request):
    try:
        SERPAPI_KEY = "eb4cf4fc276dc07a4cd115fe843d273cecd0e0e92ac5d2e198809dd45e49746f"

        hotel_name = request.data.get("hotelName", "").strip()
        hotel_name = hotel_name.replace("&", "and").replace("'", "").replace('"', "").strip()

        if not hotel_name:
            return Response({"success": False, "error": "hotelName required"}, status=400)

        print("\n===================================")
        print("GOOGLE HOTEL SEARCH STARTED")
        print("HOTEL NAME:", hotel_name)
        print("===================================\n")

        dates = generate_future_dates()
        check_in = dates["check_in"]
        check_out = dates["check_out"]

        print("CHECK IN:", check_in)
        print("CHECK OUT:", check_out)

        serp_url = (
            "https://serpapi.com/search.json"
            f"?engine=google_hotels"
            f"&q={quote(hotel_name + ' hotel')}"
            f"&check_in_date={check_in}"
            f"&check_out_date={check_out}"
            f"&adults=2"
            f"&currency=INR"
            f"&gl=in"
            f"&hl=en"
            f"&api_key={SERPAPI_KEY}"
        )

        print("SERP URL:", serp_url)

        response = requests.get(
            serp_url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=60
        )

        print("SERP STATUS:", response.status_code)

        if response.status_code != 200:
            return Response({
                "success": False,
                "error": "SerpAPI request failed",
                "status_code": response.status_code,
                "response": response.text[:1000]
            })

        try:
            data = response.json()
        except Exception as e:
            return Response({"success": False, "error": "Invalid SerpAPI JSON", "details": str(e)})

        print("SERP RESPONSE:", data)

        hotel = None
        properties = data.get("properties") or []

        if properties:
            hotel = properties[0]
        elif data.get("type") == "hotel":
            hotel = data

        if not hotel:
            return Response({"success": False, "error": "Hotel not found", "response": data})

        print("HOTEL:", hotel.get("name"))

        featured_prices = hotel.get("featured_prices") or hotel.get("prices") or []
        print("FEATURED PRICES:", featured_prices)

        pricing_vendors = []
        prices = []

        for item in featured_prices:
            try:
                vendor_name = item.get("source") or item.get("name") or "Vendor"

                total_price = 0
                if item.get("total_rate"):
                    total_price = item["total_rate"].get("extracted_lowest", 0)
                elif item.get("rate_per_night"):
                    total_price = item["rate_per_night"].get("extracted_lowest", 0)
                elif item.get("price"):
                    total_price = item.get("price")

                total_price = float(total_price)
                if total_price <= 0:
                    continue

                before_tax = 0
                if item.get("total_rate"):
                    before_tax = item["total_rate"].get("extracted_before_taxes_fees", 0)
                elif item.get("rate_per_night"):
                    before_tax = item["rate_per_night"].get("extracted_before_taxes_fees", 0)

                before_tax = float(before_tax) if before_tax else 0
                tax = (total_price - before_tax) if before_tax > 0 else 0

                prices.append(total_price)

                pricing_vendors.append({
                    "name": vendor_name,
                    "code": vendor_name.lower().replace(" ", "_"),
                    "rate": round(total_price),
                    "tax": round(tax),
                    "booking_link": item.get("link"),
                })
            except Exception as e:
                print("PRICE PARSE ERROR:", e)

        if not pricing_vendors:
            fallback_price = 0
            rate_data = hotel.get("rate_per_night") or {}
            if rate_data.get("extracted_lowest"):
                fallback_price = rate_data.get("extracted_lowest")
            elif hotel.get("price"):
                fallback_price = hotel.get("price")

            try:
                fallback_price = float(fallback_price)
            except Exception:
                fallback_price = 0

            if fallback_price > 0:
                prices.append(fallback_price)
                pricing_vendors.append({
                    "name": "Google Hotels",
                    "code": "google_hotels",
                    "rate": round(fallback_price),
                    "tax": 0,
                    "booking_link": hotel.get("link") or "https://www.google.com/travel/hotels"
                })

        if not prices:
            return Response({"success": False, "error": "No pricing available", "response": data})

        average_rate = round(sum(prices) / len(prices))
        print("AVERAGE RATE:", average_rate)

        pricing_vendors = sorted(pricing_vendors, key=lambda x: x["rate"])

        return Response({
            "success": True,
            "data": {
                "hotel_key": hotel.get("property_token") or hotel.get("name", "").lower().replace(" ", "-"),
                "average_rate": average_rate,
                "currency": "INR",
                "vendor_count": len(pricing_vendors),
                "check_in": check_in,
                "check_out": check_out,
                "pricing_vendors": pricing_vendors,
                "hotel_name": hotel.get("name"),
                "hotel_address": hotel.get("address"),
                "hotel_link": hotel.get("link"),
                "thumbnail": hotel.get("thumbnail"),
                "last_rate_updated": timezone.now(),
            }
        })

    except Exception as e:
        print("SERP HOTEL ERROR:", e)
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(["GET"])
def place_photo_api(request):
    try:
        photo_ref = request.GET.get("ref")
        width = request.GET.get("w", "800")

        if not photo_ref:
            return Response({"success": False, "error": "Photo reference missing"}, status=400)

        google_url = (
            "https://maps.googleapis.com/maps/api/place/photo"
            f"?maxwidth={width}"
            f"&photo_reference={photo_ref}"
            f"&key={GOOGLE_MAPS_API_KEY}"
        )

        response = requests.get(
            google_url,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20
        )

        print("STATUS:", response.status_code)
        print("TYPE:", response.headers.get("Content-Type"))

        if response.status_code != 200:
            return Response({
                "success": False,
                "error": "Google image fetch failed",
                "status_code": response.status_code
            }, status=400)

        content_type = response.headers.get("Content-Type", "")

        if "image" not in content_type:
            return Response({
                "success": False,
                "error": "Invalid image response",
                "content_type": content_type,
                "preview": response.text[:500]
            }, status=400)

        return HttpResponse(response.content, content_type=content_type)

    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


# ======================================================
# WIDGET LEAD CREATION API
# ======================================================

@csrf_exempt
def widget_lead_create(request):
    """
    Create lead from website widget
    POST /api/lead/
    {
        "name": "",
        "phone": "",
        "source": "website",
        "page": "current_url",
        "browser": "",
        "device": ""
    }
    """
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "error": "Only POST method allowed"
        }, status=405)
    
    try:
        import json
        data = json.loads(request.body)
        name = data.get("name", "").strip()
        phone = data.get("phone", "").strip()
        source = data.get("source", "website")
        page_url = data.get("page", "")
        browser = data.get("browser", "")
        device = data.get("device", "")

        # Allow anonymous leads (no phone required)
        if not name:
            return JsonResponse({
                "success": False,
                "error": "Name is required"
            }, status=400)

        # Clean phone number (remove non-digits) if provided
        phone_cleaned = ''
        if phone:
            phone_cleaned = ''.join(filter(str.isdigit, phone))
            
            # Add +91 if not present and it's 10 digits
            if len(phone_cleaned) == 10:
                phone_cleaned = "91" + phone_cleaned

        # Create or get chat session
        if phone_cleaned:
            session, created = ChatSession.objects.get_or_create(
                phone_number=phone_cleaned,
                defaults={
                    "user_name": name,
                    "step": 1,
                    "data": {},
                    "is_active": True
                }
            )

            if not created:
                session.user_name = name
                session.save()
        else:
            # Create session without phone for anonymous leads
            session = ChatSession.objects.create(
                user_name=name,
                phone_number="",
                step=1,
                data={},
                is_active=True
            )

        # Create lead
        lead, lead_created = Lead.objects.get_or_create(
            session=session,
            defaults={
                "full_name": name,
                "phone": phone_cleaned,
                "source": source,
                "page_url": page_url,
                "browser": browser,
                "device": device,
                "status": "new",
                "priority": "medium"
            }
        )

        if not lead_created:
            # Update existing lead with new info
            lead.full_name = name
            lead.source = source
            lead.page_url = page_url
            lead.browser = browser
            lead.device = device
            lead.save()

        return JsonResponse({
            "success": True,
            "lead_id": lead.id,
            "session_id": session.session_id,
            "message": "Lead created successfully"
        }, status=201)

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


@csrf_exempt
def widget_lead_update(request, lead_id):
    """
    Update lead information
    PATCH /api/lead/<lead_id>/
    {
        "name": "",
        "phone": ""
    }
    """
    if request.method != "PATCH":
        return JsonResponse({
            "success": False,
            "error": "Only PATCH method allowed"
        }, status=405)
    
    try:
        import json
        data = json.loads(request.body)
        name = data.get("name", "").strip()
        phone = data.get("phone", "").strip()

        if not name or not phone:
            return JsonResponse({
                "success": False,
                "error": "Name and phone are required"
            }, status=400)

        # Get lead
        try:
            lead = Lead.objects.get(id=lead_id)
        except Lead.DoesNotExist:
            return JsonResponse({
                "success": False,
                "error": "Lead not found"
            }, status=404)

        # Clean phone number
        phone_cleaned = ''.join(filter(str.isdigit, phone))
        if len(phone_cleaned) == 10:
            phone_cleaned = "91" + phone_cleaned

        # Update lead
        lead.full_name = name
        lead.phone = phone_cleaned
        lead.save()

        # Update session if exists
        if lead.session:
            lead.session.user_name = name
            if phone_cleaned:
                lead.session.phone_number = phone_cleaned
            lead.session.save()

        # Mark as Today and assign
        from .utils import mark_lead_today
        mark_lead_today(lead.session)

        return JsonResponse({
            "success": True,
            "message": "Lead updated successfully"
        }, status=200)

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


# ======================================================
# SHARED: save a lead coming from an ad platform
# ======================================================

def _save_ad_lead(source, meta_key, meta, full_name, phone, email, notes, fallback_name):
    """
    Create/update the ChatSession + Lead for a lead-form submission from an ad
    platform (Google Ads, Meta Ads …) and route it through assignment.

    Same phone number → same session/lead (repeat submissions update instead
    of duplicating). Assignment problems never fail the save — the lead is
    already visible in the CRM either way.
    Returns (session, lead). Raises if the database write itself fails.
    """
    with transaction.atomic():
        if phone:
            session, created = ChatSession.objects.select_for_update().get_or_create(
                phone_number=phone,
                defaults={
                    "user_name": full_name or phone,
                    "step": 1,
                    "data": {},
                    "is_active": True,
                },
            )
            if not created and full_name:
                session.user_name = full_name
        else:
            session = ChatSession.objects.create(
                user_name=full_name or fallback_name,
                phone_number="",
                step=1,
                data={},
                is_active=True,
            )

        session.data[meta_key] = meta
        session.save()

        lead, lead_created = Lead.objects.get_or_create(
            session=session,
            defaults={
                "full_name": full_name,
                "phone":     phone,
                "email":     email or None,
                "source":    source,
                "status":    "new",
                "priority":  "medium",
                "notes":     notes,
            },
        )
        if not lead_created:
            lead.full_name = full_name or lead.full_name
            lead.phone = phone or lead.phone
            lead.email = email or lead.email
            lead.source = source
            lead.save()

    try:
        from .utils import mark_lead_today
        mark_lead_today(session)
    except Exception as exc:
        print(f"[AD LEAD] mark_lead_today error: {exc}")

    return session, lead


# ======================================================
# GOOGLE ADS LEAD FORM WEBHOOK
# ======================================================
# Google Ads posts here in real time whenever someone submits a Lead Form
# Extension ad. Docs: https://support.google.com/google-ads/answer/9552490
#
# Configure in Google Ads → Assets → your Lead form asset → Webhook
# integration:
#   Webhook URL: https://<domain>/api/leads/google-ads/
#   Key:         settings.GOOGLE_ADS_LEAD_WEBHOOK_KEY
#
# Google requires a fast (<5s) 200 response shaped {"api_version": "1.0"}
# for every request it considers successfully delivered, including its own
# "Send test data" health checks — so we always return that shape and only
# vary the HTTP status.
# ======================================================

GOOGLE_ADS_API_VERSION = "1.0"

# Google's standard built-in column ids for the fields we care about.
# Custom questions the advertiser adds to the form arrive with their own
# column_id/column_name and are preserved as-is in session.data.
_GA_NAME_COLUMNS = ("FULL_NAME",)
_GA_FIRST_LAST_COLUMNS = ("FIRST_NAME", "LAST_NAME")
_GA_PHONE_COLUMNS = ("PHONE_NUMBER",)
_GA_EMAIL_COLUMNS = ("EMAIL", "WORK_EMAIL")
_GA_KNOWN_COLUMNS = set(_GA_NAME_COLUMNS + _GA_FIRST_LAST_COLUMNS + _GA_PHONE_COLUMNS + _GA_EMAIL_COLUMNS)

# If the form uses a CUSTOM question for the phone number instead of
# Google's built-in "Phone number" field, it arrives as a custom column
# with its own generated column_id — recognise it by its label instead
# (e.g. "Contact number", "Contact No.", "Mobile Number", "WhatsApp No").
_GA_PHONE_LABEL_RE = re.compile(r"(phone|contact|mobile|whatsapp)", re.IGNORECASE)


def _google_ads_ack(status=200, **extra):
    return JsonResponse({"api_version": GOOGLE_ADS_API_VERSION, **extra}, status=status)


@csrf_exempt
def google_ads_lead_webhook(request):
    """
    Receive a Google Ads Lead Form Extension submission and create/update
    the matching ChatSession + Lead, then route it through the same
    assignment pool as website leads.
    """
    if request.method != "POST":
        return _google_ads_ack(status=405)

    try:
        payload = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        print("[GOOGLE ADS LEAD] Invalid JSON body")
        return _google_ads_ack(status=400)

    expected_key = getattr(settings, "GOOGLE_ADS_LEAD_WEBHOOK_KEY", "")
    received_key = payload.get("google_key", "")
    if not expected_key or not received_key or not hmac.compare_digest(str(received_key), str(expected_key)):
        print("[GOOGLE ADS LEAD] Rejected — google_key did not match")
        return _google_ads_ack(status=403)

    # Google periodically sends is_test pings (and the "Send test data"
    # button in the UI uses it too) — acknowledge but don't create real
    # CRM records for them.
    is_test = str(payload.get("is_test", "")).strip() in ("1", "true", "True")

    columns = {}
    extra_columns = {}
    phone_like_custom = []   # (column_name, value) for unrecognised columns that look like a phone field
    for col in payload.get("user_column_data") or []:
        col_id = (col.get("column_id") or "").strip().upper()
        col_name = col.get("column_name") or col_id
        value = (col.get("string_value") or "").strip()
        if not value:
            continue
        if col_id in _GA_KNOWN_COLUMNS or not col_id:
            columns[col_id] = value
        elif _GA_PHONE_LABEL_RE.search(col_name):
            phone_like_custom.append((col_name, value))
        else:
            extra_columns[col_name] = value

    full_name = columns.get("FULL_NAME", "").strip()
    if not full_name:
        first = columns.get("FIRST_NAME", "")
        last = columns.get("LAST_NAME", "")
        full_name = f"{first} {last}".strip()

    # Prefer Google's built-in PHONE_NUMBER field; fall back to a custom
    # question labeled something like "Contact number" if that's what the
    # form actually uses.
    raw_phone = columns.get("PHONE_NUMBER", "")
    if not raw_phone and phone_like_custom:
        raw_phone = phone_like_custom[0][1]

    email = columns.get("EMAIL", "") or columns.get("WORK_EMAIL", "")

    from .campaign_engine import normalize_phone
    phone = normalize_phone(raw_phone) or ""

    print(f"[GOOGLE ADS LEAD] name={full_name!r} phone={phone!r} email={email!r} "
          f"campaign={payload.get('campaign_name')!r} is_test={is_test}")

    if is_test:
        return _google_ads_ack()

    if not full_name and not phone and not email:
        print("[GOOGLE ADS LEAD] Empty submission — nothing to save")
        return _google_ads_ack()

    google_ads_meta = {
        "campaign_id":   payload.get("campaign_id", ""),
        "campaign_name": payload.get("campaign_name", ""),
        "adgroup_id":    payload.get("adgroup_id", ""),
        "adgroup_name":  payload.get("adgroup_name", ""),
        "form_id":       payload.get("form_id", ""),
        "lead_id":       payload.get("lead_id", ""),
        "gcl_id":        payload.get("gcl_id", ""),
        "received_at":   timezone.now().isoformat(),
    }
    if extra_columns:
        google_ads_meta["answers"] = extra_columns

    try:
        session, lead = _save_ad_lead(
            source="google_ads",
            meta_key="google_ads",
            meta=google_ads_meta,
            full_name=full_name,
            phone=phone,
            email=email,
            notes=(f"Google Ads campaign: {google_ads_meta['campaign_name']}"
                   if google_ads_meta["campaign_name"] else ""),
            fallback_name="Google Ads Lead",
        )
    except Exception as exc:
        print(f"[GOOGLE ADS LEAD] Failed to save lead: {exc}")
        import traceback
        traceback.print_exc()
        return _google_ads_ack(status=500)

    return _google_ads_ack(lead_id=lead.id, session_id=session.id)


# ======================================================
# WEBSITE BOOKING WEBHOOK (www.trypdeals.com online booking)
# ======================================================
# The website's Firebase function (functions/payments.js in the website
# project) posts here when a visitor reaches the payment step for a short
# tour (up to 2 days) or a cab, and again when the payment status changes
# (paid / failed). Same details as the booking email to info@trypdeals.com.
#
#   URL:    https://<domain>/api/leads/website-booking/
#   Header: X-Webhook-Key: settings.WEBSITE_BOOKING_WEBHOOK_KEY
#
# The booking is saved on the customer's chat (found by mobile number, the
# same key WhatsApp uses), so when they message on WhatsApp with their
# quotation code the bot already knows the booking. The chat is assigned and
# labelled like other website leads, but the bot stays on to answer.
# ======================================================

from django.db.models import Q as models_Q
from .website_bookings import save_booking


@csrf_exempt
def website_booking_webhook(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    expected_key = getattr(settings, "WEBSITE_BOOKING_WEBHOOK_KEY", "")
    received_key = request.headers.get("X-Webhook-Key", "")
    if not expected_key or not received_key or not hmac.compare_digest(str(received_key), str(expected_key)):
        print("[WEBSITE BOOKING] Rejected - bad webhook key")
        return JsonResponse({"ok": False}, status=403)

    try:
        payload = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "invalid json"}, status=400)

    b = payload.get("booking") or {}
    code = str(b.get("code") or "").strip()
    if not re.fullmatch(r"TD-[A-Z0-9]{6}", code):
        return JsonResponse({"ok": False, "error": "missing booking code"}, status=400)

    try:
        session, lead, first_time, status = save_booking(b)
    except Exception as exc:
        print(f"[WEBSITE BOOKING] Failed to save {code}: {exc}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"ok": False}, status=500)

    phone = session.phone_number

    print(f"[WEBSITE BOOKING] {code} {status} phone={phone!r} session={session.id} first={first_time}")

    if first_time or status == "paid":
        # Assign + "Today" label + notify the rep, like other website leads,
        # but keep the bot answering: the customer usually messages next on
        # WhatsApp with this quotation code.
        try:
            was_takeover = session.is_human_takeover
            mark_lead_today(session)
            if not was_takeover:
                ChatSession.objects.filter(pk=session.pk).update(is_human_takeover=False)
        except Exception as exc:
            print(f"[WEBSITE BOOKING] assignment error: {exc}")

    return JsonResponse({"ok": True, "session_id": session.id, "lead_id": lead.id})


# ======================================================
# WEBSITE ENQUIRY WEBHOOK (cab / route / small tour / website chat)
# ======================================================
# The website's Firebase functions post every enquiry here instead of emailing
# info@ (only big tour packages are still emailed). Same key as the booking
# webhook.
#
#   URL:    https://<domain>/api/leads/website-enquiry/
#   Header: X-Webhook-Key: settings.WEBSITE_BOOKING_WEBHOOK_KEY
#   Body:   {"enquiry": {"id", "kind": cab|route|tour|chat, "title", "name",
#            "mobile", "email", "from", "to", "travelDate", "travellers",
#            "rows": [[label, value], ...], "page", "transcript"}}
# ======================================================

@csrf_exempt
def website_enquiry_webhook(request):
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    expected_key = getattr(settings, "WEBSITE_BOOKING_WEBHOOK_KEY", "")
    received_key = request.headers.get("X-Webhook-Key", "")
    if not expected_key or not received_key or not hmac.compare_digest(str(received_key), str(expected_key)):
        print("[WEBSITE ENQUIRY] Rejected - bad webhook key")
        return JsonResponse({"ok": False}, status=403)

    try:
        payload = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "invalid json"}, status=400)

    e = payload.get("enquiry") or {}
    if not e.get("id") or not (e.get("mobile") or e.get("email")):
        return JsonResponse({"ok": False, "error": "missing enquiry id or contact"}, status=400)

    from .website_bookings import save_enquiry
    try:
        session, lead, first_time = save_enquiry(e)
    except Exception as exc:
        print(f"[WEBSITE ENQUIRY] Failed to save {e.get('id')}: {exc}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"ok": False}, status=500)

    print(f"[WEBSITE ENQUIRY] {e.get('kind')} {e.get('id')} session={session.id} first={first_time}")

    if first_time:
        # Assign + "Today" label + notify the rep; the bot stays on in case
        # the customer messages on WhatsApp.
        try:
            was_takeover = session.is_human_takeover
            mark_lead_today(session)
            if not was_takeover:
                ChatSession.objects.filter(pk=session.pk).update(is_human_takeover=False)
        except Exception as exc:
            print(f"[WEBSITE ENQUIRY] assignment error: {exc}")

    return JsonResponse({"ok": True, "session_id": session.id, "lead_id": lead.id})


# ======================================================
# META (FACEBOOK / INSTAGRAM) LEAD ADS WEBHOOK
# ======================================================
# Setup (Meta for Developers -> your App):
#   1. Webhooks -> Page -> Callback URL  https://<domain>/api/leads/meta-ads/
#      Verify token = settings.META_LEADS_VERIFY_TOKEN -> subscribe to "leadgen"
#   2. settings.META_APP_SECRET        (App -> Settings -> Basic)
#   3. settings.META_PAGE_ACCESS_TOKEN (Page token with leads_retrieval)
#   4. Subscribe the Page to the app (POST /{page-id}/subscribed_apps?subscribed_fields=leadgen)
#
# Meta only sends a leadgen_id - the actual form answers are fetched from the
# Graph API. If that fetch fails we answer 500 so Meta retries (for ~36 h);
# the leadgen_id is remembered so retries never create duplicates.
# ======================================================

def _meta_field_values(field):
    vals = [str(v).strip() for v in (field.get("values") or []) if str(v).strip()]
    return ", ".join(vals)


def _process_meta_lead(leadgen_id, webhook_value):
    """Fetch one lead from the Graph API and save it. Raises on failure."""
    if not leadgen_id:
        return None

    if ChatSession.objects.filter(data__meta_ads__leadgen_id=str(leadgen_id)).exists():
        print(f"[META LEAD] leadgen {leadgen_id} already saved - skipping duplicate delivery")
        return None

    token = getattr(settings, "META_PAGE_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("META_PAGE_ACCESS_TOKEN is not configured")

    version = getattr(settings, "META_GRAPH_VERSION", "v22.0")
    resp = requests.get(
        f"https://graph.facebook.com/{version}/{leadgen_id}",
        params={
            "access_token": token,
            "fields": "field_data,created_time,ad_id,ad_name,adset_id,adset_name,"
                      "campaign_id,campaign_name,form_id,platform,is_organic",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Graph API {resp.status_code}: {resp.text[:300]}")
    data = resp.json()

    fields, extra, phone_like = {}, {}, []
    for f in data.get("field_data") or []:
        name = (f.get("name") or "").strip().lower()
        value = _meta_field_values(f)
        if not value:
            continue
        if name in ("full_name", "first_name", "last_name", "phone_number", "phone", "email", "work_email"):
            fields[name] = value
        elif _GA_PHONE_LABEL_RE.search(name):
            phone_like.append(value)
        else:
            extra[name] = value

    full_name = fields.get("full_name") or f"{fields.get('first_name', '')} {fields.get('last_name', '')}".strip()
    email = fields.get("email") or fields.get("work_email") or ""
    raw_phone = fields.get("phone_number") or fields.get("phone") or (phone_like[0] if phone_like else "")

    from .campaign_engine import normalize_phone
    phone = normalize_phone(raw_phone) or ""

    meta = {
        "leadgen_id":    str(leadgen_id),
        "form_id":       data.get("form_id") or webhook_value.get("form_id", ""),
        "ad_id":         data.get("ad_id") or webhook_value.get("ad_id", ""),
        "ad_name":       data.get("ad_name", ""),
        "adset_name":    data.get("adset_name", ""),
        "campaign_id":   data.get("campaign_id", ""),
        "campaign_name": data.get("campaign_name", ""),
        "platform":      data.get("platform", ""),
        "page_id":       webhook_value.get("page_id", ""),
        "created_time":  data.get("created_time", ""),
        "received_at":   timezone.now().isoformat(),
    }
    if extra:
        meta["answers"] = extra

    print(f"[META LEAD] leadgen={leadgen_id} name={full_name!r} phone={phone!r} email={email!r} "
          f"campaign={meta['campaign_name']!r}")

    notes = f"Meta Ads campaign: {meta['campaign_name']}" if meta["campaign_name"] else "Meta Ads lead form"
    return _save_ad_lead(
        source="meta_ads", meta_key="meta_ads", meta=meta,
        full_name=full_name, phone=phone, email=email,
        notes=notes, fallback_name="Meta Ads Lead",
    )


@csrf_exempt
def meta_leads_webhook(request):
    # -- Step 1: Meta's one-time verification handshake
    if request.method == "GET":
        expected = getattr(settings, "META_LEADS_VERIFY_TOKEN", "")
        token = request.GET.get("hub.verify_token", "")
        if (request.GET.get("hub.mode") == "subscribe" and expected and token
                and hmac.compare_digest(token, expected)):
            return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")
        print("[META LEAD] Verification failed - verify token mismatch")
        return HttpResponse("Forbidden", status=403, content_type="text/plain")

    if request.method != "POST":
        return JsonResponse({"success": False}, status=405)

    # -- Step 2: verify the request really came from Meta
    secret = getattr(settings, "META_APP_SECRET", "")
    if not secret:
        print("[META LEAD] Rejected - META_APP_SECRET is not configured")
        return JsonResponse({"success": False}, status=403)
    raw = request.body
    expected_sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get("X-Hub-Signature-256", ""), expected_sig):
        print("[META LEAD] Rejected - bad X-Hub-Signature-256")
        return JsonResponse({"success": False}, status=403)

    try:
        payload = json.loads(raw or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"success": False}, status=400)

    if payload.get("object") != "page":
        return JsonResponse({"success": True, "ignored": True})

    # -- Step 3: one webhook can carry several leads
    failures = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "leadgen":
                continue
            value = change.get("value") or {}
            try:
                _process_meta_lead(value.get("leadgen_id"), value)
            except Exception as exc:
                failures += 1
                print(f"[META LEAD] Failed to process leadgen {value.get('leadgen_id')}: {exc}")

    if failures:
        # non-2xx makes Meta retry later - duplicates are prevented by leadgen_id
        return JsonResponse({"success": False, "failed": failures}, status=500)
    return JsonResponse({"success": True})


# ======================================================
# WIDGET CHAT API
# ======================================================

@csrf_exempt
def widget_chat(request):
    """
    Handle widget chat messages
    POST /api/chat/
    {
        "lead_id": "",
        "message": ""
    }
    """
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "error": "Only POST method allowed"
        }, status=405)
    
    try:
        import json
        data = json.loads(request.body)
        lead_id = data.get("lead_id")
        message = data.get("message", "").strip()

        if not lead_id or not message:
            return JsonResponse({
                "success": False,
                "error": "lead_id and message are required"
            }, status=400)

        # Get lead
        try:
            lead = Lead.objects.get(id=lead_id)
        except Lead.DoesNotExist:
            return JsonResponse({
                "success": False,
                "error": "Lead not found"
            }, status=404)

        session = lead.session

        # Check if we're collecting name or phone
        session_data = session.data
        collecting_name = session_data.get("_collecting_name", False)
        collecting_phone = session_data.get("_collecting_phone", False)

        if collecting_name:
            # Save name
            session.user_name = message
            session_data["_name"] = message
            session_data["_collecting_name"] = False
            session_data["_collecting_phone"] = True  # Now ask for phone
            session.data = session_data
            session.save()

            return JsonResponse({
                "success": True,
                "message": "Thank you! Now please share your WhatsApp number:",
                "options": []
            }, status=200)

        if collecting_phone:
            # Save phone and update lead
            phone_cleaned = ''.join(filter(str.isdigit, message))
            if len(phone_cleaned) == 10:
                phone_cleaned = "91" + phone_cleaned

            session.phone_number = phone_cleaned
            session_data["_collecting_phone"] = False
            session_data["_phone"] = phone_cleaned
            session.data = session_data
            session.save()

            # Update lead
            lead.full_name = session_data.get("_name", "")
            lead.phone = phone_cleaned
            lead.save()

            # Mark as Today and assign
            from .utils import mark_lead_today
            mark_lead_today(session)

            # Proceed to handoff
            from .utils import handle_lead_handoff
            handoff_response = handle_lead_handoff(session)

            return JsonResponse({
                "success": True,
                "message": handoff_response.get("message", ""),
                "options": handoff_response.get("options", []),
                "social_card": handoff_response.get("social_card")
            }, status=200)

        # Check for human takeover
        session.refresh_from_db(fields=["is_human_takeover"])
        if session.is_human_takeover:
            # Return human takeover response with WhatsApp button
            return JsonResponse({
                "success": True,
                "message": "This conversation has been transferred to our travel expert. Continue chatting on WhatsApp for personalized assistance.",
                "options": [],
                "human_takeover": True,
                "whatsapp_number": "918766247711"
            }, status=200)

        # Save user message
        ChatMessage.objects.create(
            session=session,
            sender_type="user",
            message=message
        )

        # Generate bot response (generate_response already saves bot message to CRM)
        bot_response = generate_response(message, session, is_widget=True)

        if isinstance(bot_response, dict):
            reply_text = bot_response.get("message", "Sorry, no response generated.")
            options = bot_response.get("options", [])
        else:
            reply_text = str(bot_response)
            options = []

        return JsonResponse({
            "success": True,
            "message": reply_text,
            "options": options
        }, status=200)

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


# ======================================================
# WIDGET STATIC FILE SERVING
# ======================================================

@csrf_exempt
def widget_files(request, file_name):
    """
    Serve widget static files
    GET /widget/widget.js
    GET /widget/widget.css
    GET /widget/chat-icon.svg
    GET /widget/close.svg
    """
    if request.method != "GET":
        return JsonResponse({
            "success": False,
            "error": "Only GET method allowed"
        }, status=405)
    
    try:
        # Get widget directory path
        widget_dir = os.path.join(settings.BASE_DIR, 'widget')
        
        # Security check - only allow specific files
        allowed_files = ['widget.js', 'widget.css', 'chat-icon.svg', 'close.svg']
        if file_name not in allowed_files:
            return JsonResponse({
                "success": False,
                "error": "File not allowed"
            }, status=403)
        
        file_path = os.path.join(widget_dir, file_name)
        
        if not os.path.exists(file_path):
            return JsonResponse({
                "success": False,
                "error": "File not found"
            }, status=404)
        
        # Determine content type
        content_types = {
            'widget.js': 'application/javascript',
            'widget.css': 'text/css',
            'chat-icon.svg': 'image/svg+xml',
            'close.svg': 'image/svg+xml'
        }
        
        content_type = content_types.get(file_name, 'application/octet-stream')
        
        # Read and return file
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        response = HttpResponse(file_content, content_type=content_type)
        
        # Add CORS headers for widget embedding
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET'
        response['Access-Control-Allow-Headers'] = '*'
        
        # Cache control
        if file_name.endswith('.svg'):
            response['Cache-Control'] = 'public, max-age=86400'  # 1 day
        else:
            response['Cache-Control'] = 'public, max-age=3600'  # 1 hour
        
        return response
        
    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)