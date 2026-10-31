# =========================================================
# FILE: chatbot/crm_views.py   v2.0
# =========================================================
# Changes vs v1
# ─────────────
# • Paginator page size bumped to 100 (was 40).
# • push_label_notification() called after label changes to
#   HOT / FOLLOW UP so the assigned agent gets a WebSocket ping.
# • crm_all_reminders() — date-wise "All Reminders" view.
# • crm_reminder_for_date() — AJAX endpoint for date picker.
# =========================================================

import csv
import json
import mimetypes
import os
import openpyxl
import traceback
import uuid
from datetime import datetime, timedelta

import requests
import re

from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_GET, require_POST

from .decorators import crm_login_required
from .forms import CRMLoginForm, NoteForm, ReminderForm
from .models import (
    Booking,
    ChatMessage,
    ChatSession,
    ConversationLabel,
    ConversationStatus,
    Lead,
    InternalNote,
    Itinerary,
    Reminder,
    SalesProfile,
)
from .utils import _deepseek
from .views import send_whatsapp_message, send_whatsapp_template_message
from .models import CRMTemplate

try:
    from .views import send_whatsapp_media as _send_whatsapp_media_external
except ImportError:
    _send_whatsapp_media_external = None

# ── WebSocket notification helper (graceful fallback if channels missing) ───
try:
    from .crm_lead_signals import push_label_notification, push_new_message_notification, push_message_status_notification, push_chat_assigned_notification
except ImportError:
    def push_label_notification(session, label_name):
        pass
    def push_new_message_notification(session, preview):
        pass
    def push_message_status_notification(message_id, status):
        pass
    def push_chat_assigned_notification(session, assigned_user):
        pass


# =========================================================
# PAGE SIZE
# =========================================================

CONV_PAGE_SIZE = 50    # conversations per load; the list fetches the next 50 on scroll (crm_conversations_page)


# =========================================================
# DEEPSEEK WRAPPER
# =========================================================

def _crm_deepseek(prompt: str, max_tokens: int = 4000) -> str:
    from .utils import _deepseek_client, DEEPSEEK_MODEL
    try:
        response = _deepseek_client.with_options(timeout=90.0).chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if not content:
            reason = getattr(choice, "finish_reason", "unknown")
            raise RuntimeError(
                f"DeepSeek returned an empty response body (finish_reason={reason}, max_tokens={max_tokens})."
            )
        return content
    except Exception as e:
        raise RuntimeError(f"DeepSeek API call failed: {e}") from e


# =========================================================
# WHATSAPP MEDIA CONFIG
# =========================================================

WHATSAPP_API_VERSION     = getattr(settings, "WHATSAPP_API_VERSION", "v19.0")
WHATSAPP_PHONE_NUMBER_ID = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN    = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "")

WHATSAPP_GRAPH_BASE = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"

MAX_UPLOAD_SIZE = 16 * 1024 * 1024  # 16 MB

ALLOWED_MEDIA_CONTENT_TYPES = {
    "image/jpeg":       "image",
    "image/png":        "image",
    "image/webp":       "image",
    "video/mp4":        "video",
    "video/3gpp":       "video",
    "audio/aac":        "audio",
    "audio/mp4":        "audio",
    "audio/mpeg":       "audio",
    "audio/amr":        "audio",
    "audio/ogg":        "audio",
    "application/pdf":  "document",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.ms-excel": "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
    "application/vnd.ms-powerpoint": "document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "document",
    "text/plain":       "document",
    "application/zip":  "document",
}


# =========================================================
# RBAC HELPERS
# =========================================================

def get_user_role(user):
    if user.is_superuser:
        return "admin"
    try:
        return user.salesprofile.role
    except SalesProfile.DoesNotExist:
        return "sales"


def team_user_ids(user):
    """The user's id plus, for a team leader, their team members' ids."""
    try:
        profile = user.salesprofile
    except SalesProfile.DoesNotExist:
        return [user.pk]
    if not profile.is_team_leader:
        return [user.pk]
    return [user.pk] + [pk for pk in profile.team_members.values_list("pk", flat=True) if pk != user.pk]


def filter_sessions_for_user(qs, user, role=None):
    if role is None:
        role = get_user_role(user)
    if role == "sales":
        # A team leader also sees the team members' chats.
        return qs.filter(assigned_sales_person_id__in=team_user_ids(user))
    return qs


def has_session_access(session, user, role=None):
    if role is None:
        role = get_user_role(user)
    if role in ("admin", "manager"):
        return True
    return session.assigned_sales_person_id in team_user_ids(user)


def assignable_user_ids(user):
    """
    Who a sales person may hand a chat to: themselves, their own team (team
    leader) and the team they are a member of (its leader and the other members).
    """
    ids = team_user_ids(user)
    for leader in SalesProfile.objects.filter(team_members=user, is_team_leader=True):
        ids.append(leader.user_id)
        ids.extend(leader.team_members.values_list("pk", flat=True))
    return list(dict.fromkeys(ids))


def assign_users_for(user, role, sales_users):
    """People in the chat's "Assign To" list."""
    if role != "sales":
        return sales_users
    return User.objects.filter(pk__in=assignable_user_ids(user), is_active=True)


def _day_start(day):
    """Midnight (India time) at the start of a date, as an aware datetime."""
    return timezone.make_aware(datetime.combine(day, datetime.min.time()))


def _on_day(field, day):
    """Filter kwargs for one local day. Unlike field__date, it can use an index."""
    return {f"{field}__gte": _day_start(day), f"{field}__lt": _day_start(day + timedelta(days=1))}


def can_download_data(user):
    """Only admins download data (contacts, lead analysis and campaign exports)."""
    return get_user_role(user) == "admin"


# =========================================================
# INTERNAL UTILITIES
# =========================================================

def get_or_create_conv_status(session):
    status, _ = ConversationStatus.objects.get_or_create(
        session=session,
        defaults={"assigned_to": session.assigned_sales_person}
    )
    return status


def _generate_session_id(phone):
    return f"crm_{phone}_{uuid.uuid4().hex[:8]}"


BOOKING_MODULE = "booking"


def _has_booking():
    return Exists(Booking.objects.filter(session=OuterRef("pk")))


def list_module(request, session=None):
    """
    Which chat list is shown: "booking" (chats with a website booking, CRM ->
    Booking) or "chats" (all the others). ?module=booking, or the open chat's.
    """
    module = request.GET.get("module", "")
    if module in (BOOKING_MODULE, "chats"):
        return module
    if session is not None and Booking.objects.filter(session=session).exists():
        return BOOKING_MODULE
    return "chats"


def build_session_list(request, role=None, apply_date_filter=True, module="chats"):
    if role is None:
        role = get_user_role(request.user)

    filter_param = request.GET.get("filter", "all")
    search_q     = request.GET.get("q", "").strip()

    # The list shows only these related rows. No prefetch of messages: that
    # loaded every message (with its raw payload) of every chat on the page.
    sessions = ChatSession.objects.select_related(
        "assigned_sales_person",
        "conv_status",
        "conv_status__label",
        "lead",
    ).order_by("-updated_at")

    sessions = filter_sessions_for_user(sessions, request.user, role)
    # Booking chats have their own list (CRM -> Booking), not in Chats.
    sessions = sessions.filter(_has_booking() if module == BOOKING_MODULE else ~_has_booking())

    if search_q:
        sessions = sessions.filter(
            Q(user_name__icontains=search_q)    |
            Q(phone_number__icontains=search_q) |
            Q(last_message__icontains=search_q)
        )

    if filter_param == "open":
        sessions = sessions.filter(
            Q(conv_status__closed=False) | Q(conv_status__isnull=True)
        )
    elif filter_param == "closed":
        sessions = sessions.filter(conv_status__closed=True)
    elif filter_param == "human":
        sessions = sessions.filter(is_human_takeover=True)
    elif filter_param not in ("all", ""):
        sessions = sessions.filter(
            conv_status__label__name__iexact=filter_param.replace("-", " ")
        )

    selected_date      = None
    date_filter_active = False

    if apply_date_filter:
        date_str = request.GET.get("date", "").strip()
        if date_str:
            parsed = parse_date(date_str)
            if parsed:
                selected_date      = parsed
                date_filter_active = True
                sessions = sessions.filter(**_on_day("updated_at", selected_date))

    sessions = apply_list_filters(request, sessions)

    return sessions, filter_param, selected_date, date_filter_active


# "Select Filters" sheet on the chat list (start / end date, several labels,
# agent, chat type). All optional, combined with the filters above.
LIST_FILTER_PARAMS = ("start", "end", "labels", "agent", "type")


def apply_list_filters(request, sessions):
    start = parse_date(request.GET.get("start", "").strip() or "")
    end   = parse_date(request.GET.get("end", "").strip() or "")
    if start:
        sessions = sessions.filter(updated_at__gte=_day_start(start))
    if end:
        sessions = sessions.filter(updated_at__lt=_day_start(end + timedelta(days=1)))

    label_ids = [int(x) for x in request.GET.get("labels", "").split(",") if x.strip().isdigit()]
    if label_ids:
        sessions = sessions.filter(conv_status__label_id__in=label_ids)

    agent = request.GET.get("agent", "").strip()
    if agent == "none":
        sessions = sessions.filter(assigned_sales_person__isnull=True)
    elif agent.isdigit():
        sessions = sessions.filter(assigned_sales_person_id=int(agent))

    chat_type = request.GET.get("type", "").strip()
    if chat_type == "open":
        sessions = sessions.filter(Q(conv_status__closed=False) | Q(conv_status__isnull=True))
    elif chat_type == "closed":
        sessions = sessions.filter(conv_status__closed=True)
    return sessions


def list_filters_active(request):
    """How many sheet filters are set (chat type "all" doesn't count)."""
    n = 0
    if request.GET.get("start") or request.GET.get("end"):
        n += 1
    if request.GET.get("labels"):
        n += 1
    if request.GET.get("agent"):
        n += 1
    if request.GET.get("type") in ("open", "closed"):
        n += 1
    return n


STATS_CACHE_SECONDS = 30
STATUS_POLL_LIMIT = 50   # sent messages whose ticks the open chat refreshes


def _stats_for_user(user, role):
    """Header counts. One query instead of six, cached for a few seconds per user."""
    cache_key = f"crm_stats:{user.pk}:{role}"
    try:
        stats = cache.get(cache_key)
    except Exception:
        stats = None
    if stats is not None:
        return stats

    base_qs = filter_sessions_for_user(ChatSession.objects.all(), user, role)
    stats = base_qs.aggregate(
        total_leads=Count("id"),
        open_leads=Count("id", filter=Q(conv_status__closed=False) | Q(conv_status__isnull=True)),
        hot_leads=Count("id", filter=Q(conv_status__label__name="HOT")),
        pending_leads=Count("id", filter=Q(conv_status__label__name="PENDING")),
        paid_leads=Count("id", filter=Q(conv_status__label__name="PAID")),
    )
    today_msgs = ChatMessage.objects.filter(**_on_day("created_at", timezone.localdate()))
    if role == "sales":
        today_msgs = today_msgs.filter(session__in=base_qs)
    stats["today_msgs"] = today_msgs.count()

    try:
        cache.set(cache_key, stats, STATS_CACHE_SECONDS)
    except Exception:
        pass
    return stats


# =========================================================
# MEDIA HELPERS — WhatsApp Cloud API
# =========================================================

def _media_type_for_mime(mime):
    if mime in ALLOWED_MEDIA_CONTENT_TYPES:
        return ALLOWED_MEDIA_CONTENT_TYPES[mime]
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "document"


def _whatsapp_headers():
    return {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}


def upload_media_to_whatsapp(file_obj, mime_type):
    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_TOKEN:
        return None

    url = f"{WHATSAPP_GRAPH_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/media"

    file_obj.seek(0)
    files = {
        "file": (getattr(file_obj, "name", "upload"), file_obj, mime_type),
    }
    data = {"messaging_product": "whatsapp"}

    try:
        resp = requests.post(url, headers=_whatsapp_headers(), data=data, files=files, timeout=60)
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception:
        traceback.print_exc()
        return None


def send_whatsapp_media_message(phone, media_id=None, media_url=None,
                                 msg_type="document", caption="", filename=""):
    if _send_whatsapp_media_external is not None:
        return _send_whatsapp_media_external(
            phone, media_id=media_id, media_url=media_url,
            msg_type=msg_type, caption=caption, filename=filename
        )

    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_TOKEN:
        raise RuntimeError("WhatsApp credentials are not configured.")

    url = f"{WHATSAPP_GRAPH_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    media_obj = {}
    cloudinary_url = None
    
    # Upload to Cloudinary if media_url is provided and it's an image
    if media_url and msg_type == "image":
        try:
            from .views import upload_to_cloudinary
            cloudinary_url = upload_to_cloudinary(media_url)
            if cloudinary_url:
                media_url = cloudinary_url  # Use Cloudinary URL instead
                print(f"[CLOUDINARY] Image uploaded: {cloudinary_url}")
        except Exception as e:
            print(f"[CLOUDINARY] Upload failed, using original URL: {e}")
    
    if media_id:
        media_obj["id"] = media_id
    elif media_url:
        media_obj["link"] = media_url
    else:
        raise ValueError("Either media_id or media_url is required.")

    if caption and msg_type in ("image", "video", "document"):
        media_obj["caption"] = caption

    if filename and msg_type == "document":
        media_obj["filename"] = filename

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": msg_type,
        msg_type: media_obj,
    }

    resp = requests.post(
        url,
        headers={**_whatsapp_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    
    return resp.json(), cloudinary_url


def download_whatsapp_media(media_id):
    if not WHATSAPP_ACCESS_TOKEN:
        return None, None, None

    try:
        meta_url  = f"{WHATSAPP_GRAPH_BASE}/{media_id}"
        meta_resp = requests.get(meta_url, headers=_whatsapp_headers(), timeout=30)
        meta_resp.raise_for_status()
        meta = meta_resp.json()

        file_url  = meta.get("url")
        mime_type = meta.get("mime_type", "application/octet-stream")
        if not file_url:
            return None, None, None

        file_resp = requests.get(file_url, headers=_whatsapp_headers(), timeout=60)
        file_resp.raise_for_status()

        ext      = mimetypes.guess_extension(mime_type) or ""
        filename = f"{media_id}{ext}"

        return file_resp.content, mime_type, filename
    except Exception:
        traceback.print_exc()
        return None, None, None


def save_incoming_media_message(session, media_id, mime_type, caption="",
                                 whatsapp_message_id="", download_now=True):
    media_type = _media_type_for_mime(mime_type)

    msg = ChatMessage.objects.create(
        session=session,
        sender_type="user",
        message=caption or "",
        media_type=media_type,
        media_mime_type=mime_type,
        whatsapp_media_id=media_id,
        whatsapp_message_id=whatsapp_message_id,
    )

    if download_now:
        content, real_mime, filename = download_whatsapp_media(media_id)
        if content:
            save_dir   = f"crm_incoming/{session.id}/"
            saved_path = default_storage.save(
                os.path.join(save_dir, filename),
                ContentFile(content)
            )
            msg.media_url       = settings.MEDIA_URL + saved_path
            msg.media_mime_type = real_mime or mime_type
            msg.media_filename  = filename
            msg.save(update_fields=["media_url", "media_mime_type", "media_filename"])

    icon = {"image": "🖼", "video": "🎥", "audio": "🎵", "document": "📎"}.get(media_type, "📎")
    session.last_message = f"{icon} {caption or media_type.title()}"
    session.updated_at   = timezone.now()
    session.unread_count = (session.unread_count or 0) + 1
    session.save(update_fields=["last_message", "updated_at", "unread_count"])

    # Notify assigned agent of new incoming message
    push_new_message_notification(session, session.last_message)

    return msg


# =========================================================
# AUTH: LOGIN
# =========================================================

def crm_login(request):
    if request.user.is_authenticated:
        return redirect("crm_chat_home")

    form = CRMLoginForm(request, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        return redirect(request.GET.get("next", "crm_chat_home"))

    return render(request, "chatbot/crm/login.html", {"form": form})


# =========================================================
# AUTH: LOGOUT
# =========================================================

@crm_login_required
def crm_logout(request):
    logout(request)
    return redirect("crm_login")


# =========================================================
# DASHBOARD
# =========================================================

@crm_login_required
def crm_dashboard(request):
    # The "Message" page was removed from the CRM (new chats: "+" on the chat
    # list; bulk sends: Campaigns). Old links land on the chat list.
    return redirect("crm_chat_home")
    role  = get_user_role(request.user)
    stats = _stats_for_user(request.user, role)
    templates = CRMTemplate.objects.all()

    return render(request, "chatbot/crm/dashboard.html", {
        "stats":     stats,
        "user_role": role,
        "templates": templates,
    })


# =========================================================
# CHAT HOME
# =========================================================

@crm_login_required
def crm_chat_home(request):
    role = get_user_role(request.user)

    module = list_module(request)
    sessions, active_filter, selected_date, date_filter_active = build_session_list(request, role, module=module)
    search_q = request.GET.get("q", "")
    labels   = ConversationLabel.objects.all()

    if role == "sales":
        sales_users = User.objects.filter(pk__in=team_user_ids(request.user))
    else:
        sales_users = User.objects.filter(
            salesprofile__isnull=False
        ).select_related("salesprofile")

    visible_session_ids = filter_sessions_for_user(
        ChatSession.objects.all(), request.user, role
    ).values_list("id", flat=True)

    reminders = Reminder.objects.filter(
        done=False,
        reminder_at__gte=timezone.now(),
        session_id__in=visible_session_ids,
    ).select_related("session", "created_by").order_by("reminder_at")[:10]

    page_obj = Paginator(sessions, CONV_PAGE_SIZE).get_page(request.GET.get("page", 1))

    return render(request, "chatbot/crm/chat_detail.html", {
        "module":             module,
        "conv_next_url":      _conv_next_url(request, page_obj, module),
        "list_qs":            _conv_list_querystring(request, module),
        "list_filters_on":    list_filters_active(request),
        "whatsapp_number":    getattr(settings, "WHATSAPP_DISPLAY_NUMBER", ""),
        "active_session":     None,
        "conv_status":        None,
        "messages":           [],
        "notes":              [],
        "reminders":          reminders,
        "labels":             labels,
        "sales_users":        sales_users,
        "assign_users":       assign_users_for(request.user, role, sales_users),
        "sessions":           page_obj,
        "active_filter":      active_filter,
        "search_q":           search_q,
        "note_form":          NoteForm(),
        "reminder_form":      ReminderForm(),
        "user_role":          role,
        "selected_date":      selected_date,
        "date_filter_active": date_filter_active,
    })


# =========================================================
# CHAT DETAIL
# =========================================================

_AD_SOURCE_LABELS = (
    ("google_ads", "Google Ads"),
    ("meta_ads", "Meta Ads"),
    # Online booking on www.trypdeals.com (views.website_booking_webhook).
    ("website_booking_card", "Website Booking"),
    # Cab / route / small-tour / chat enquiries (views.website_enquiry_webhook).
    ("website_enquiry_card", "Website Enquiry"),
)


def _lead_form_cards(session):
    """Ad lead-form submissions (Google / Meta) and website bookings saved on the session, for the chat page."""
    from django.utils.dateparse import parse_datetime

    data = session.data if isinstance(session.data, dict) else {}
    cards = []
    for key, label in _AD_SOURCE_LABELS:
        meta = data.get(key)
        if not isinstance(meta, dict):
            continue
        answers = [
            (str(q).replace("_", " ").strip().capitalize(), a)
            for q, a in (meta.get("answers") or {}).items() if a not in (None, "")
        ]
        received = parse_datetime(meta.get("received_at") or "")
        cards.append({
            "source":   label,
            "heading":  {"website_booking_card": "Booking Details", "website_enquiry_card": "Enquiry Details"}.get(key, "Lead Form Answers"),
            "campaign_label": {"website_booking_card": "Booking", "website_enquiry_card": "Enquiry"}.get(key, "Campaign"),
            "campaign": meta.get("campaign_name") or "",
            "ad":       meta.get("ad_name") or meta.get("adgroup_name") or "",
            "form_id":  meta.get("form_id") or "",
            "received": received,
            "answers":  answers,
        })
    return cards


@crm_login_required
def crm_chat_detail(request, session_id):
    from django.utils import timezone
    from datetime import timedelta
    
    role    = get_user_role(request.user)
    session = get_object_or_404(ChatSession, id=session_id)

    if not has_session_access(session, request.user, role):
        return redirect("crm_chat_home")

    conv_status = get_or_create_conv_status(session)

    session.unread_count = 0
    session.save(update_fields=["unread_count"])

    messages  = list(ChatMessage.objects.filter(session=session).order_by("created_at"))
    _attach_fail_reasons(session, messages)
    notes     = InternalNote.objects.filter(session=session).select_related("added_by").order_by("-created_at")
    reminders = Reminder.objects.filter(session=session).order_by("reminder_at")
    labels    = ConversationLabel.objects.all()
    templates = CRMTemplate.objects.all()

    if role == "sales":
        sales_users = User.objects.filter(pk__in=team_user_ids(request.user))
    else:
        sales_users = User.objects.filter(
            salesprofile__isnull=False
        ).select_related("salesprofile")

    # A booking chat opens in the Booking list, the others in Chats.
    module = list_module(request, session)
    sessions, active_filter, selected_date, date_filter_active = build_session_list(request, role, module=module)
    search_q = request.GET.get("q", "")
    page_obj = Paginator(sessions, CONV_PAGE_SIZE).get_page(request.GET.get("page", 1))

    # Calculate 24-hour window status
    # WhatsApp opens the window only when the customer messages; bot replies,
    # website bookings and CRM edits also touch updated_at, so don't use it.
    hours_since_activity = _hours_since_customer_message(session)
    is_window_active = hours_since_activity < 24 and not conv_status.closed

    # --------------------------------------------------
    # SPAM DETECTION - Get engagement data
    # --------------------------------------------------
    try:
        from .models import UserEngagement, SpamRiskAlert, OptInRecord
        from .spam_detection import SpamDetector
        
        engagement = SpamDetector.get_or_create_engagement(session)
        spam_alerts = SpamRiskAlert.objects.filter(session=session, resolved=False).order_by("-created_at")
        active_alert = spam_alerts.first() if spam_alerts.exists() else None
        
        # Check opt-in status
        has_opt_in = OptInRecord.objects.filter(
            phone_number__endswith=session.phone_number[-10:] if session.phone_number else "",
            is_active=True
        ).exists() if session.phone_number else False
        
    except Exception as e:
        print(f"Error loading spam detection data: {e}")
        engagement = None
        active_alert = None
        has_opt_in = False

    return render(request, "chatbot/crm/chat_detail.html", {
        "module":             module,
        "conv_next_url":      _conv_next_url(request, page_obj, module),
        "list_qs":            _conv_list_querystring(request, module),
        "list_filters_on":    list_filters_active(request),
        "whatsapp_number":    getattr(settings, "WHATSAPP_DISPLAY_NUMBER", ""),
        "lead_forms":         _lead_form_cards(session),
        "active_session":     session,
        "conv_status":        conv_status,
        "messages":           messages,
        "notes":              notes,
        "reminders":          reminders,
        "labels":             labels,
        "templates":          templates,
        "sales_users":        sales_users,
        "assign_users":       assign_users_for(request.user, role, sales_users),
        "sessions":           page_obj,
        "active_filter":      active_filter,
        "search_q":           search_q,
        "note_form":          NoteForm(),
        "reminder_form":      ReminderForm(),
        "user_role":          role,
        "selected_date":      selected_date,
        "date_filter_active": date_filter_active,
        "is_window_active":   is_window_active,
        "hours_since_activity": hours_since_activity,
        "engagement":         engagement,
        "active_alert":       active_alert,
        "has_opt_in":         has_opt_in,
    })


# =========================================================
# WHATSAPP SEND HELPERS
# =========================================================

# Meta error codes the sales team is most likely to hit, in plain words
WHATSAPP_ERROR_HINTS = {
    131047: "Customer has not messaged in the last 24 hours. WhatsApp only allows a template message now - use 'Send Template'.",
    131026: "Message could not be delivered: this number may not be on WhatsApp, or the customer has blocked/not accepted the new terms.",
    131049: "WhatsApp did not deliver this message to keep engagement healthy. Try again later or use a template.",
    131056: "Too many messages sent to this customer in a short time. Wait a little and try again.",
    131021: "Cannot send a message to the business's own number.",
    131030: "This number is not in the allowed recipients list (WhatsApp test number).",
    190: "WhatsApp access token has expired. Update WHATSAPP_ACCESS_TOKEN in .env and restart the service.",
}


def _whatsapp_number(raw):
    """Phone in WhatsApp format (country code + digits, no '+'), or None if invalid.

    Keeps foreign country codes as they are; bare 10-digit numbers get +91.
    """
    from .campaign_engine import normalize_phone
    return normalize_phone(raw)


def _hours_since_customer_message(session):
    """Hours since the customer's last WhatsApp message (a large number if never).

    One number can have more than one chat (website booking / ad lead chats
    next to the WhatsApp one), so look at every chat with the same number.
    """
    from django.db.models import Q
    digits = "".join(ch for ch in (session.phone_number or session.session_id or "") if ch.isdigit())[-10:]
    same_number = Q(session=session)
    if len(digits) == 10:
        same_number |= Q(session__phone_number__endswith=digits) | Q(session__session_id__startswith="91" + digits)
    times = [t for t in (
        ChatMessage.objects.filter(same_number, sender_type="user")
        .order_by("-created_at").values_list("created_at", flat=True).first(),
        session.last_customer_message_time,
    ) if t]
    if not times:
        return 9999.0
    return (timezone.now() - max(times)).total_seconds() / 3600


def _attach_fail_reasons(session, messages):
    """
    For each failed outgoing message set fail_reason / fail_fix / fail_code /
    fail_guess, shown when the agent taps the red icon. Taken from TrypBot's
    delivery note or the error Meta reported; for older failures with neither,
    a best guess from the 24-hour window at the time it was sent.
    """
    from .whatsapp_errors import explain
    failed = [m for m in messages if m.message_status == "failed" and m.sender_type != "user"]
    if not failed:
        return
    notes = {}
    for m in messages:
        err = (m.raw_payload or {}).get("delivery_error") if isinstance(m.raw_payload, dict) else None
        if m.sender_type == "system" and isinstance(err, dict) and err.get("key"):
            notes[str(err["key"])] = err
    user_times = [m.created_at for m in messages if m.sender_type == "user"]
    phone = session.phone_number or session.session_id
    for m in failed:
        note = notes.get(str(m.id))
        recorded = (m.raw_payload or {}).get("delivery_error") if isinstance(m.raw_payload, dict) else None
        if note:
            m.fail_reason, m.fail_fix, m.fail_code, m.fail_guess = note.get("reason"), note.get("fix"), note.get("code"), False
            continue
        if isinstance(recorded, dict) and recorded.get("code"):
            code = recorded["code"]
            reason, fix = explain(code, recorded.get("details", ""), phone)
            m.fail_reason, m.fail_fix, m.fail_code, m.fail_guess = reason, fix, code, False
            continue
        last_user = max((t for t in user_times if t <= m.created_at), default=None)
        code = 131047 if last_user is None or (m.created_at - last_user).total_seconds() >= 24 * 3600 else None
        reason, fix = explain(code, "", phone)
        m.fail_reason, m.fail_fix, m.fail_code, m.fail_guess = reason, fix, code, True


def _note_send_error(session, response, what):
    """Post TrypBot's reason + fix for a send that WhatsApp refused straight away."""
    try:
        from .whatsapp_errors import note_delivery_failure
        error = response.get("error") if isinstance(response, dict) else None
        if isinstance(error, dict):
            code = error.get("code")
            details = (error.get("error_data") or {}).get("details") or error.get("message") or ""
        else:
            code, details = None, str(error or "No response from WhatsApp")
        note_delivery_failure(session=session, code=code, details=details, what=what)
    except Exception as exc:
        print(f"[DELIVERY NOTE] {exc}")


def _whatsapp_error_text(response):
    """None if the Graph API accepted the message, otherwise a readable reason."""
    if not isinstance(response, dict):
        return "No response from WhatsApp. Please try again."
    error = response.get("error")
    if error:
        if isinstance(error, str):  # spam / rate-limit guard in send_whatsapp_message
            return error
        code = error.get("code")
        details = (error.get("error_data") or {}).get("details") or error.get("message") or "Unknown error"
        return WHATSAPP_ERROR_HINTS.get(code, f"WhatsApp error {code}: {details}")
    if not response.get("messages"):
        return "WhatsApp did not accept the message. Please try again."
    return None


# =========================================================
# SEND TEXT MESSAGE
# =========================================================

@crm_login_required
@require_POST
def crm_send_message(request, session_id):
    role    = get_user_role(request.user)
    session = get_object_or_404(ChatSession, id=session_id)

    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    try:
        body = json.loads(request.body)
        text = body.get("message", "").strip()
    except Exception:
        text = request.POST.get("message", "").strip()

    if not text:
        return JsonResponse({"success": False, "error": "Empty message"}, status=400)

    # Check if session has phone number
    if not session.phone_number:
        return JsonResponse({
            "success": False,
            "error": "Session does not have a phone number. Cannot send message."
        }, status=400)

    phone_number = _whatsapp_number(session.phone_number)
    print(f"[CRM SEND] DB phone '{session.phone_number}' -> sending to '{phone_number}'")
    if not phone_number:
        return JsonResponse({
            "success": False,
            "error": f"Invalid phone number '{session.phone_number}'. Cannot send message."
        }, status=400)

    # Meta accepts a free-text message outside the 24-hour window and only
    # reports the failure later (131047), so stop it here with a clear reason.
    hours = _hours_since_customer_message(session)
    if hours >= 24:
        detail = ("The customer has never messaged on WhatsApp" if hours >= 9999
                  else f"The customer last messaged {int(hours)} hours ago")
        return JsonResponse({
            "success": False,
            "error": f"{detail} (outside WhatsApp's 24-hour window). Use 'Send Template' instead.",
            "is_template_required": True,
        }, status=400)

    # Check if WhatsApp credentials are configured for local testing
    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_TOKEN:
        print("[SEND MESSAGE] WhatsApp credentials not configured - using local test mode")
        # Simulate successful message send for local testing
        whatsapp_response = {
            "messages": [{"id": f"local_test_{uuid.uuid4().hex[:12]}"}]
        }
    else:
        whatsapp_response = send_whatsapp_message(phone_number, text)

    send_error = _whatsapp_error_text(whatsapp_response)
    if send_error:
        print(f"[CRM SEND] FAILED to {phone_number}: {whatsapp_response}")
        _note_send_error(session, whatsapp_response, "Your message")
        return JsonResponse({"success": False, "error": send_error}, status=400)

    # Extract WhatsApp message ID from response to prevent webhook duplication
    whatsapp_message_id = whatsapp_response.get("messages", [{}])[0].get("id", "")

    msg = ChatMessage.objects.create(
        session=session,
        sender_type="sales",
        message=text,
        whatsapp_message_id=whatsapp_message_id,
        message_status="sent",
    )
    session.last_message = text
    session.updated_at   = timezone.now()
    session.save(update_fields=["last_message", "updated_at"])

    return JsonResponse({
        "success": True,
        "message": {
            "id":     msg.id,
            "text":   msg.message,
            "sender": request.user.get_full_name() or request.user.username,
            "time":   msg.created_at.strftime("%I:%M %p"),
            "type":   "sales",
            "status": "sent",
        }
    })


# =========================================================
# SEND FILE
# =========================================================

@crm_login_required
@require_POST
def crm_send_file(request, session_id):
    role    = get_user_role(request.user)
    session = get_object_or_404(ChatSession, id=session_id)

    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"success": False, "error": "No file received."}, status=400)

    if uploaded.size > MAX_UPLOAD_SIZE:
        return JsonResponse(
            {"success": False, "error": "File is too large (max 16 MB)."},
            status=400
        )

    caption = request.POST.get("caption", "").strip()

    mime         = uploaded.content_type or "application/octet-stream"
    media_type   = _media_type_for_mime(mime)
    display_icon = {"image": "🖼", "video": "🎥", "audio": "🎵", "document": "📎"}.get(media_type, "📎")

    save_dir  = f"crm_files/{session_id}/"
    save_path = default_storage.save(
        os.path.join(save_dir, uploaded.name),
        uploaded
    )
    media_url = request.build_absolute_uri(settings.MEDIA_URL + save_path)
    
    # Upload to Cloudinary for images
    cloudinary_url = None
    if media_type == "image":
        try:
            from .views import upload_to_cloudinary
            # Read file content and upload to Cloudinary
            with default_storage.open(save_path, "rb") as f:
                file_content = f.read()
            cloudinary_url = upload_to_cloudinary(file_content)
            if cloudinary_url:
                media_url = cloudinary_url  # Use Cloudinary URL
                print(f"[CLOUDINARY] CRM image uploaded: {cloudinary_url}")
        except Exception as e:
            print(f"[CLOUDINARY] CRM upload failed, using local: {e}")
            import traceback
            traceback.print_exc()

    msg = ChatMessage.objects.create(
        session=session,
        sender_type="sales",
        message=caption or uploaded.name,
        media_url=media_url,
        media_type=media_type,
        media_mime_type=mime,
        media_filename=uploaded.name,
    )

    sent_ok    = False
    send_error = None
    result     = None
    try:
        with default_storage.open(save_path, "rb") as f:
            f.name = uploaded.name
            whatsapp_media_id = upload_media_to_whatsapp(f, mime)

        if whatsapp_media_id:
            result, _ = send_whatsapp_media_message(
                session.phone_number,
                media_id=whatsapp_media_id,
                msg_type=media_type,
                caption=caption,
                filename=uploaded.name,
            )
            sent_ok = True
        else:
            # Use Cloudinary URL if available for images
            final_media_url = cloudinary_url if cloudinary_url else media_url
            result, _ = send_whatsapp_media_message(
                session.phone_number,
                media_url=final_media_url,
                msg_type=media_type,
                caption=caption,
                filename=uploaded.name,
            )
            sent_ok = True
    except Exception as exc:
        traceback.print_exc()
        send_error = str(exc)
        try:
            fallback_text = f"{display_icon} {uploaded.name}"
            if caption:
                fallback_text += f"\n{caption}"
            fallback_text += f"\n{media_url}"
            result = send_whatsapp_message(session.phone_number, fallback_text)
            sent_ok = True
        except Exception:
            traceback.print_exc()

    # WhatsApp's id for the message, so its delivered / read ticks reach this row.
    if isinstance(result, dict):
        wamid = (result.get("messages") or [{}])[0].get("id", "")
        if wamid:
            msg.whatsapp_message_id = wamid
            msg.save(update_fields=["whatsapp_message_id"])

    preview_text         = f"{display_icon} {caption or uploaded.name}"
    session.last_message = preview_text
    session.updated_at   = timezone.now()
    session.save(update_fields=["last_message", "updated_at"])

    if not sent_ok:
        msg.message_status = "failed"
        msg.save(update_fields=["message_status"])
        return JsonResponse({
            "success": False,
            "error":   f"File saved but WhatsApp delivery failed: {send_error}",
            "message": {
                "id":         msg.id,
                "text":       msg.message,
                "media_url":  msg.media_url,
                "media_type": msg.media_type,
                "filename":   msg.media_filename,
                "time":       msg.created_at.strftime("%I:%M %p"),
                "type":       "sales",
            }
        }, status=502)

    return JsonResponse({
        "success": True,
        "message": {
            "id":         msg.id,
            "text":       msg.message,
            "media_url":  msg.media_url,
            "media_type": msg.media_type,
            "filename":   msg.media_filename,
            "time":       msg.created_at.strftime("%I:%M %p"),
            "type":       "sales",
            "status": "delivered",
        }
    })


# =========================================================
# MEDIA PROXY
# =========================================================

@crm_login_required
@require_GET
def crm_media_proxy(request, message_id):
    msg  = get_object_or_404(ChatMessage, id=message_id)
    role = get_user_role(request.user)

    if not has_session_access(msg.session, request.user, role):
        raise Http404("Not found.")

    if msg.media_url:
        return HttpResponseRedirect(msg.media_url)

    if msg.whatsapp_media_id:
        content, mime_type, filename = download_whatsapp_media(msg.whatsapp_media_id)
        if not content:
            raise Http404("Media could not be retrieved.")

        save_dir   = f"crm_incoming/{msg.session_id}/"
        saved_path = default_storage.save(
            os.path.join(save_dir, filename),
            ContentFile(content)
        )
        msg.media_url       = settings.MEDIA_URL + saved_path
        msg.media_mime_type = mime_type or msg.media_mime_type
        msg.media_filename  = filename
        msg.save(update_fields=["media_url", "media_mime_type", "media_filename"])

        return HttpResponseRedirect(msg.media_url)

    raise Http404("No media associated with this message.")


# =========================================================
# BULK ADD CHATS (Excel / CSV, from the Add New Chat sheet)
# =========================================================

BULK_ADD_LIMIT = 50


def _bulk_rows(uploaded):
    """[(name, phone_raw, row_number)] from an .xlsx or .csv upload."""
    import csv
    import io
    name_lower = (uploaded.name or "").lower()
    if name_lower.endswith(".csv"):
        text = uploaded.read().decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
    elif name_lower.endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(uploaded, read_only=True, data_only=True)
        rows = [list(r) for r in wb.active.iter_rows(values_only=True)]
        wb.close()
    else:
        raise ValueError("Upload an Excel (.xlsx) or CSV file.")

    def cell(v):
        if isinstance(v, float) and v.is_integer():
            v = int(v)  # Excel stores long numbers as floats
        return str(v).strip() if v is not None else ""

    rows = [[cell(v) for v in r] for r in rows if r and any(cell(v) for v in r)]
    if not rows:
        return []
    # Header row: find the Name and Mobile columns; else column A = name, B = mobile.
    head = [h.lower() for h in rows[0]]
    phone_col = next((i for i, h in enumerate(head) if any(k in h for k in ("mobile", "phone", "number", "whatsapp", "contact"))), None)
    name_col = next((i for i, h in enumerate(head) if "name" in h), None)
    start = 1 if phone_col is not None or name_col is not None else 0
    if phone_col is None:
        phone_col = 1 if len(rows[0]) > 1 else 0
    if name_col is None:
        name_col = 0 if phone_col != 0 else None
    out = []
    for n, r in enumerate(rows[start:], start=start + 1):
        phone = r[phone_col] if phone_col < len(r) else ""
        name = r[name_col] if name_col is not None and name_col < len(r) else ""
        out.append((name, phone, n))
    return out


@crm_login_required
@require_POST
def crm_bulk_add_chats(request):
    """Add up to BULK_ADD_LIMIT contacts as chats + leads (no message is sent)."""
    from .campaign_engine import normalize_phone
    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"success": False, "error": "Choose an Excel or CSV file."}, status=400)
    if uploaded.size > 2 * 1024 * 1024:
        return JsonResponse({"success": False, "error": "File is too large (max 2 MB)."}, status=400)
    try:
        rows = _bulk_rows(uploaded)
    except Exception as exc:
        return JsonResponse({"success": False, "error": f"Could not read the file: {exc}"}, status=400)
    if not rows:
        return JsonResponse({"success": False, "error": "The file has no contacts."}, status=400)
    if len(rows) > BULK_ADD_LIMIT:
        return JsonResponse({"success": False,
                             "error": f"The file has {len(rows)} contacts. Upload at most {BULK_ADD_LIMIT} at a time."}, status=400)

    added, existing, invalid, seen = 0, 0, [], set()
    for name, raw, row_no in rows:
        name = name[:255]
        phone = normalize_phone(raw)
        if not phone or not (7 <= len(phone) <= 15):
            invalid.append(f"Row {row_no}: '{raw or '(empty)'}'")
            continue
        if phone in seen:
            continue
        seen.add(phone)
        session = (ChatSession.objects.filter(Q(session_id=phone) | Q(phone_number=phone))
                   .order_by("-updated_at").first())
        if session:
            existing += 1
            if name and (not session.user_name or session.user_name == session.phone_number):
                session.user_name = name
                session.save(update_fields=["user_name"])
        else:
            session = ChatSession.objects.create(
                session_id=phone, phone_number=phone, user_name=name or phone,
                is_human_takeover=True, assigned_sales_person=request.user,
                last_message="Lead added from CRM (Excel upload)",
            )
            try:
                get_or_create_conv_status(session)
            except Exception:
                traceback.print_exc()
            added += 1
        try:
            Lead.objects.get_or_create(
                session=session,
                defaults={"full_name": name or None, "phone": phone, "source": "crm",
                          "status": "new", "priority": "medium", "assigned_to": request.user},
            )
        except Exception:
            traceback.print_exc()

    return JsonResponse({"success": True, "added": added, "existing": existing,
                         "invalid": invalid[:20], "invalid_count": len(invalid)})


@crm_login_required
def crm_bulk_add_sample(request):
    """A sample Excel file for the bulk upload."""
    import io
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Contacts"
    ws.append(["Name", "Mobile"])
    ws.append(["Ravi Kumar", "9876543210"])
    ws.append(["Priya Shah", "+91 98765 43211"])
    ws.append(["John (UAE)", "+971501234567"])
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 20
    buf = io.BytesIO()
    wb.save(buf)
    response = HttpResponse(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="trypbot-contacts-sample.xlsx"'
    return response


# =========================================================
# SEND TO NEW NUMBER
# =========================================================

@crm_login_required
@require_POST
def crm_send_to_number(request):
    try:
        body    = json.loads(request.body)
        phone   = body.get("phone", "").strip()
        name    = body.get("name", "").strip()
        message = body.get("message", "").strip()
        template_id = body.get("template_id")
        is_template = body.get("is_template", False)
        # "Add New Chat" without a template: just save the contact as a lead.
        save_only = bool(body.get("save_only"))
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid JSON body."}, status=400)

    phone = phone.lstrip("+").replace(" ", "").replace("-", "")

    if not phone:
        return JsonResponse({"success": False, "error": "Phone number is required."}, status=400)

    if not phone.isdigit() or not (7 <= len(phone) <= 15):
        return JsonResponse(
            {"success": False,
             "error": "Enter a valid number with country code (digits only, 7–15 digits)."},
            status=400,
        )

    # Validate template or message
    if save_only:
        pass
    elif is_template:
        if not template_id:
            return JsonResponse({"success": False, "error": "Template ID is required for template messages."}, status=400)
        try:
            template = CRMTemplate.objects.get(id=template_id)
            message = template.template_text
        except CRMTemplate.DoesNotExist:
            return JsonResponse({"success": False, "error": "Template not found."}, status=404)
    else:
        if not message:
            return JsonResponse({"success": False, "error": "Message cannot be empty."}, status=400)

    try:
        # Reuse the customer's WhatsApp chat if there is one (WhatsApp keys
        # chats by the bare number as session_id); a new chat also gets the
        # bare number so the customer's reply lands in this same chat.
        session = (ChatSession.objects
                   .filter(Q(session_id=phone) | Q(phone_number=phone))
                   .order_by("-updated_at").first())
        created = session is None
        if created:
            session = ChatSession.objects.create(
                session_id=phone,
                phone_number=phone,
                user_name=name or phone,
                is_human_takeover=True,
            )
    except Exception as exc:
        traceback.print_exc()
        return JsonResponse(
            {"success": False, "error": f"Could not create or find session: {exc}"},
            status=500,
        )

    if not created and name and (not session.user_name or session.user_name == session.phone_number):
        session.user_name = name
        session.save(update_fields=["user_name"])

    # Every chat added from the CRM is also a lead.
    try:
        lead, lead_created = Lead.objects.get_or_create(
            session=session,
            defaults={"full_name": name or None, "phone": phone, "source": "crm",
                      "status": "new", "priority": "medium", "assigned_to": request.user},
        )
        if not lead_created and name and not lead.full_name:
            lead.full_name = name
            lead.save(update_fields=["full_name"])
    except Exception:
        traceback.print_exc()

    if save_only:
        if created:
            session.assigned_sales_person = request.user
            session.last_message = "Lead added from CRM"
            session.save(update_fields=["assigned_sales_person", "last_message", "updated_at"])
            try:
                get_or_create_conv_status(session)
            except Exception:
                traceback.print_exc()
        from django.urls import reverse
        return JsonResponse({
            "success":      True,
            "session_id":   session.id,
            "redirect_url": reverse("crm_chat_detail", args=[session.id]),
            "created":      created,
        })

    # Check 24-hour window for non-template messages
    if not is_template:
        from datetime import timedelta
        twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
        
        last_user_message = ChatMessage.objects.filter(
            session=session,
            sender_type='user'
        ).order_by('-created_at').first()
        
        if not last_user_message or last_user_message.created_at < twenty_four_hours_ago:
            if last_user_message:
                hours_since = (timezone.now() - last_user_message.created_at).total_seconds() / 3600
                detail = f"User last messaged {int(hours_since)} hours ago"
            else:
                detail = "User has never messaged this number"
            return JsonResponse({
                "success": False,
                "error": f"{detail} (outside 24-hour window). Use a template message instead.",
                "is_template_required": True
            }, status=400)

    try:
        if is_template:
            # Use WhatsApp template API for template messages
            whatsapp_response = send_whatsapp_template_message(
                to=phone,
                template_name=template.template_name,
            )
        else:
            # Send regular text message
            whatsapp_response = send_whatsapp_message(phone, message)
    except Exception as exc:
        traceback.print_exc()
        error_msg = str(exc)
        # Check if error is related to 24-hour window restriction
        if "template" in error_msg.lower() or "24" in error_msg.lower() or "window" in error_msg.lower():
            return JsonResponse(
                {"success": False, "error": "This number is outside the 24-hour messaging window. Please use a WhatsApp template message to initiate conversation.", "is_template_required": True},
                status=400,
            )
        return JsonResponse(
            {"success": False, "error": f"WhatsApp delivery failed: {exc}"},
            status=502,
        )

    # Check for errors reported by the WhatsApp API before treating this as delivered
    if isinstance(whatsapp_response, dict) and "error" in whatsapp_response:
        return JsonResponse(
            {"success": False, "error": f"WhatsApp API error: {whatsapp_response.get('error', {}).get('message', 'Unknown error')}"},
            status=400,
        )

    # Extract WhatsApp message ID
    whatsapp_message_id = ""
    if isinstance(whatsapp_response, dict):
        whatsapp_message_id = whatsapp_response.get("messages", [{}])[0].get("id", "")

    try:
        msg = ChatMessage.objects.create(
            session=session,
            sender_type="sales",
            message=message,
            whatsapp_message_id=whatsapp_message_id,
            message_status="delivered",
        )
    except Exception as exc:
        traceback.print_exc()
        return JsonResponse(
            {"success": False, "error": f"Message sent but could not be saved: {exc}"},
            status=500,
        )

    session.last_message      = message
    session.updated_at        = timezone.now()
    session.is_human_takeover = True
    session.save(update_fields=["last_message", "updated_at", "is_human_takeover"])

    if created:
        session.assigned_sales_person = request.user
        session.save(update_fields=["assigned_sales_person"])
        try:
            get_or_create_conv_status(session)
            # Notify the assigned user about the new lead
            push_chat_assigned_notification(session, request.user)
        except Exception:
            traceback.print_exc()

    from django.urls import reverse
    redirect_url = reverse("crm_chat_detail", args=[session.id])

    return JsonResponse({
        "success":      True,
        "session_id":   session.id,
        "redirect_url": redirect_url,
        "created":      created,
    })


# =========================================================
# BULK LEADS
# =========================================================

@crm_login_required
@require_GET
def crm_bulk_leads(request):
    role = get_user_role(request.user)

    qs = ChatSession.objects.exclude(
        phone_number__isnull=True
    ).exclude(phone_number="")

    qs = filter_sessions_for_user(qs, request.user, role)

    search_q = request.GET.get("q", "").strip()
    if search_q:
        qs = qs.filter(
            Q(user_name__icontains=search_q) |
            Q(phone_number__icontains=search_q)
        )

    qs = qs.order_by("-updated_at")

    leads = [
        {
            "id":    s.id,
            "name":  s.user_name or "",
            "phone": s.phone_number,
        }
        for s in qs
    ]

    return JsonResponse({"success": True, "leads": leads})


# =========================================================
# UPDATE LABEL  — with WebSocket notification
# =========================================================

@crm_login_required
@require_POST
def crm_update_label(request):
    role = get_user_role(request.user)

    try:
        body       = json.loads(request.body)
        session_id = body.get("session_id")
        label_id   = body.get("label_id")
    except Exception:
        session_id = request.POST.get("session_id")
        label_id   = request.POST.get("label_id")

    session = get_object_or_404(ChatSession, id=session_id)

    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    conv_status = get_or_create_conv_status(session)

    if label_id:
        label = get_object_or_404(ConversationLabel, id=label_id)
        conv_status.label = label
    else:
        conv_status.label = None

    conv_status.save()

    # ── Push WebSocket notification for NEW LEAD / FOLLOW UP labels ──
    if conv_status.label:
        label_upper = conv_status.label.name.upper()
        if label_upper in ("NEW LEAD", "FOLLOW UP"):
            push_label_notification(session, conv_status.label.name)

    return JsonResponse({
        "success":     True,
        "label_name":  conv_status.label.name  if conv_status.label else "",
        "label_color": conv_status.label.color if conv_status.label else "",
    })


# =========================================================
# ASSIGN CHAT
# =========================================================

@crm_login_required
@require_POST
def crm_assign_chat(request):
    role = get_user_role(request.user)

    try:
        body       = json.loads(request.body)
        session_id = body.get("session_id")
        user_id    = body.get("user_id")
    except Exception:
        session_id = request.POST.get("session_id")
        user_id    = request.POST.get("user_id")

    session = get_object_or_404(ChatSession, id=session_id)

    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    if role == "sales" and user_id and int(user_id) not in assignable_user_ids(request.user):
        return JsonResponse(
            {"success": False, "error": "You can assign chats only to yourself or your team members."},
            status=403,
        )

    if user_id:
        user = get_object_or_404(User, id=user_id)
        session.assigned_sales_person = user
        conv_status = get_or_create_conv_status(session)
        conv_status.assigned_to = user
        conv_status.save()
        assigned_name = user.get_full_name() or user.username
        # Notify the assigned user
        push_chat_assigned_notification(session, user)
    else:
        if role == "sales":
            return JsonResponse(
                {"success": False, "error": "Sales agents cannot un-assign chats."},
                status=403,
            )
        session.assigned_sales_person = None
        conv_status = get_or_create_conv_status(session)
        conv_status.assigned_to = None
        conv_status.save()
        assigned_name = "Unassigned"

    session.save(update_fields=["assigned_sales_person"])
    return JsonResponse({"success": True, "assigned_name": assigned_name})


# =========================================================
# CHECK FOR NEW ASSIGNMENTS (Polling-based notifications)
# =========================================================

@crm_login_required
@require_GET
def crm_check_assignments(request):
    """
    Check for recent updates on chats assigned to the current user.
    Used for polling-based notifications when WebSocket is not available.
    Returns: new assignments, new messages, label changes, etc.
    """
    from django.utils import timezone
    from datetime import timedelta
    
    user = request.user
    one_minute_ago = timezone.now() - timedelta(minutes=1)
    
    # Get all sessions assigned to this user
    user_sessions = ChatSession.objects.filter(
        assigned_sales_person=user
    ).select_related('conv_status', 'conv_status__label')
    
    # Check for recent assignments (sessions assigned in the last minute)
    recent_assignments = user_sessions.filter(
        updated_at__gte=one_minute_ago
    ).order_by('-updated_at')[:10]
    
    assignments = []
    for session in recent_assignments:
        assignments.append({
            'id': session.id,
            'session_name': session.user_name or session.phone_number or f"#{session.id}",
            'phone': session.phone_number or "",
            'updated_at': session.updated_at.strftime("%I:%M %p"),
        })
    
    # Check for new messages on assigned chats
    from .models import ChatMessage
    new_messages = ChatMessage.objects.filter(
        session__assigned_sales_person=user,
        sender_type="user",  # Only customer messages
        created_at__gte=one_minute_ago
    ).select_related('session').order_by('-created_at')[:10]
    
    messages = []
    for msg in new_messages:
        messages.append({
            'id': msg.id,
            'session_id': msg.session.id,
            'session_name': msg.session.user_name or msg.session.phone_number or f"#{msg.session.id}",
            'message': msg.message[:100],
            'created_at': msg.created_at.strftime("%I:%M %p"),
        })
    
    # Check for label changes on assigned chats
    # Only the chats whose label changed in the last minute (this runs every
    # 30 s for every open CRM tab, so don't walk all of the user's chats).
    label_changes = []
    for session in user_sessions.filter(conv_status__updated_at__gte=one_minute_ago,
                                        conv_status__label__isnull=False):
        if session.conv_status and session.conv_status.label:
            if session.conv_status.updated_at and session.conv_status.updated_at >= one_minute_ago:
                label_changes.append({
                    'session_id': session.id,
                    'session_name': session.user_name or session.phone_number or f"#{session.id}",
                    'label': session.conv_status.label.name,
                    'updated_at': session.conv_status.updated_at.strftime("%I:%M %p"),
                })
    
    return JsonResponse({
        'success': True,
        'assignments': assignments,
        'new_messages': messages,
        'label_changes': label_changes,
    })


# =========================================================
# ADD NOTE
# =========================================================

@crm_login_required
@require_POST
def crm_add_note(request):
    role = get_user_role(request.user)

    try:
        body       = json.loads(request.body)
        session_id = body.get("session_id")
        note_text  = body.get("note", "").strip()
    except Exception:
        session_id = request.POST.get("session_id")
        note_text  = request.POST.get("note", "").strip()

    if not note_text:
        return JsonResponse({"success": False, "error": "Note is empty"}, status=400)

    session = get_object_or_404(ChatSession, id=session_id)

    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    note = InternalNote.objects.create(
        session=session,
        added_by=request.user,
        note=note_text,
    )

    return JsonResponse({
        "success": True,
        "note": {
            "id":         note.id,
            "text":       note.note,
            "added_by":   request.user.get_full_name() or request.user.username,
            "created_at": note.created_at.strftime("%d %b %Y %I:%M %p"),
        }
    })


# =========================================================
# DELETE NOTE
# =========================================================

@crm_login_required
def crm_delete_note(request, note_id):
    note = get_object_or_404(InternalNote, id=note_id)
    role = get_user_role(request.user)

    if not has_session_access(note.session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    if note.added_by != request.user and role not in ("admin", "manager"):
        return JsonResponse({"success": False, "error": "Forbidden"}, status=403)

    note.delete()
    return JsonResponse({"success": True})


# =========================================================
# ADD REMINDER
# =========================================================

@crm_login_required
@require_POST
def crm_add_reminder(request):
    role = get_user_role(request.user)

    try:
        body        = json.loads(request.body)
        session_id  = body.get("session_id")
        note_text   = body.get("note", "").strip()
        reminder_at = body.get("reminder_at", "")
    except Exception:
        session_id  = request.POST.get("session_id")
        note_text   = request.POST.get("note", "").strip()
        reminder_at = request.POST.get("reminder_at", "")

    if not note_text or not reminder_at:
        return JsonResponse({"success": False, "error": "Note and time required"}, status=400)

    session = get_object_or_404(ChatSession, id=session_id)

    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    dt = parse_datetime(reminder_at)
    if not dt:
        return JsonResponse({"success": False, "error": "Invalid datetime format"}, status=400)

    reminder = Reminder.objects.create(
        session=session,
        note=note_text,
        reminder_at=dt,
        created_by=request.user,
    )

    return JsonResponse({
        "success": True,
        "reminder": {
            "id":          reminder.id,
            "note":        reminder.note,
            "reminder_at": reminder.reminder_at.strftime("%d %b %Y %I:%M %p"),
        }
    })


# =========================================================
# REMINDER DONE / DELETE
# =========================================================

@crm_login_required
def crm_reminder_done(request, reminder_id):
    role     = get_user_role(request.user)
    reminder = get_object_or_404(Reminder, id=reminder_id)

    if not has_session_access(reminder.session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    # Body {"done": false} moves a completed reminder back to pending.
    done = True
    try:
        body = json.loads(request.body or b"{}")
        if isinstance(body, dict) and "done" in body:
            done = bool(body["done"])
    except (ValueError, TypeError):
        pass
    reminder.done = done
    reminder.save(update_fields=["done"])
    return JsonResponse({"success": True, "done": done})


@crm_login_required
def crm_reminder_delete(request, reminder_id):
    role     = get_user_role(request.user)
    reminder = get_object_or_404(Reminder, id=reminder_id)

    if not has_session_access(reminder.session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    reminder.delete()
    return JsonResponse({"success": True})


# =========================================================
# RENAME CHAT (pencil next to the number)
# =========================================================

@crm_login_required
@require_POST
def crm_rename_chat(request, session_id):
    role    = get_user_role(request.user)
    session = get_object_or_404(ChatSession, id=session_id)
    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)
    try:
        name = str(json.loads(request.body or b"{}").get("name", "")).strip()[:255]
    except (ValueError, TypeError, AttributeError):
        name = ""
    if not name:
        return JsonResponse({"success": False, "error": "Name cannot be empty."}, status=400)
    session.user_name = name
    session.save(update_fields=["user_name"])
    Lead.objects.filter(session=session).update(full_name=name)
    return JsonResponse({"success": True, "name": name})


# =========================================================
# BLOCK / UNBLOCK CHAT
# =========================================================
# Blocking stops the bot (human takeover), opts the number out of campaigns
# and closes the chat; unblocking lifts the opt-out and reopens it.

@crm_login_required
@require_POST
def crm_block_chat(request, session_id):
    role    = get_user_role(request.user)
    session = get_object_or_404(ChatSession, id=session_id)
    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    data = session.data if isinstance(session.data, dict) else {}
    blocked = not data.get("blocked")
    data["blocked"] = blocked
    session.data = data
    conv_status = get_or_create_conv_status(session)
    if blocked:
        session.is_human_takeover = True
        session.marketing_opt_out = True
        session.marketing_opt_out_at = timezone.now()
        conv_status.closed = True
    else:
        session.marketing_opt_out = False
        session.marketing_opt_out_at = None
        conv_status.closed = False
    session.save(update_fields=["data", "is_human_takeover", "marketing_opt_out", "marketing_opt_out_at"])
    conv_status.save(update_fields=["closed"])
    return JsonResponse({"success": True, "blocked": blocked, "closed": conv_status.closed})


# =========================================================
# HUMAN TAKEOVER TOGGLE
# =========================================================

@crm_login_required
@require_POST
def crm_human_takeover(request, session_id):
    role    = get_user_role(request.user)
    session = get_object_or_404(ChatSession, id=session_id)

    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    session.is_human_takeover = not session.is_human_takeover
    session.save(update_fields=["is_human_takeover"])

    return JsonResponse({
        "success":           True,
        "is_human_takeover": session.is_human_takeover,
    })


# =========================================================
# CLOSE / REOPEN TICKET
# =========================================================

@crm_login_required
@require_POST
def crm_close_ticket(request, session_id):
    role    = get_user_role(request.user)
    session = get_object_or_404(ChatSession, id=session_id)

    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    conv_status        = get_or_create_conv_status(session)
    conv_status.closed = not conv_status.closed
    conv_status.save(update_fields=["closed"])

    return JsonResponse({"success": True, "closed": conv_status.closed})


# =========================================================
# CONVERSATION LIST — NEXT PAGE (infinite scroll)
# =========================================================

def _conv_list_querystring(request, module="chats"):
    """filter / search / date / list (Booking) of the current list, kept on links and next-page requests."""
    from urllib.parse import urlencode
    keep = {k: request.GET.get(k) for k in ("filter", "q", "date") + LIST_FILTER_PARAMS if request.GET.get(k)}
    if module == BOOKING_MODULE:
        keep["module"] = BOOKING_MODULE
    return urlencode(keep)


def _conv_next_url(request, page_obj, module="chats"):
    if not page_obj.has_next():
        return ""
    from django.urls import reverse
    qs = _conv_list_querystring(request, module)
    return f"{reverse('crm_conversations_page')}?page={page_obj.next_page_number()}" + (f"&{qs}" if qs else "")


@crm_login_required
@require_GET
def crm_conversations_page(request):
    """The next CONV_PAGE_SIZE conversations of the sidebar list, as HTML rows."""
    role = get_user_role(request.user)
    module = list_module(request)
    sessions, _, _, _ = build_session_list(request, role, module=module)
    page_obj = Paginator(sessions, CONV_PAGE_SIZE).get_page(request.GET.get("page", 1))
    html = render(request, "chatbot/crm/_conv_items.html", {
        "sessions": page_obj,
        "active_session": None,
        "list_qs": _conv_list_querystring(request, module),
    }).content.decode("utf-8")
    return JsonResponse({"html": html, "next_url": _conv_next_url(request, page_obj, module)})


# =========================================================
# LIVE POLLING — CONVERSATION LIST
# =========================================================

@crm_login_required
@require_GET
def crm_live(request):
    role = get_user_role(request.user)

    sessions = ChatSession.objects.select_related(
        "assigned_sales_person",
        "conv_status",
        "conv_status__label",
    ).order_by("-updated_at")

    sessions = filter_sessions_for_user(sessions, request.user, role)
    sessions = sessions[:50]

    data = []
    for s in sessions:
        label_name  = ""
        label_color = "#888"
        closed      = False

        try:
            cs = s.conv_status
            if cs.label:
                label_name  = cs.label.name
                label_color = cs.label.color
            closed = cs.closed
        except Exception:
            pass

        assigned = ""
        if s.assigned_sales_person:
            assigned = (
                s.assigned_sales_person.get_full_name()
                or s.assigned_sales_person.username
            )

        data.append({
            "id":                s.id,
            "name":              s.user_name or s.phone_number or "Unknown",
            "phone":             s.phone_number or "",
            "last_message":      (s.last_message or "")[:80],
            "unread_count":      s.unread_count,
            "assigned":          assigned,
            "label_name":        label_name,
            "label_color":       label_color,
            "closed":            closed,
            "is_human_takeover": s.is_human_takeover,
            "updated_at":        s.updated_at.strftime("%d %b %Y %I:%M %p") if s.updated_at else "",
        })

    visible_ids = filter_sessions_for_user(
        ChatSession.objects.all(), request.user, role
    ).values_list("id", flat=True)

    due_reminders = Reminder.objects.filter(
        done=False,
        reminder_at__lte=timezone.now(),
        session_id__in=visible_ids,
    ).count()

    return JsonResponse({
        "success":       True,
        "sessions":      data,
        "due_reminders": due_reminders,
    })


# =========================================================
# LIVE MESSAGES — SINGLE CHAT
# =========================================================

@crm_login_required
@require_GET
def crm_live_messages(request, session_id):
    role    = get_user_role(request.user)
    session = get_object_or_404(ChatSession, id=session_id)

    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    after_id = request.GET.get("after", 0)

    messages = ChatMessage.objects.filter(
        session_id=session_id,
        id__gt=after_id,
    ).order_by("created_at")

    data = []
    for m in messages:
        if m.sender_type == "bot":
            sender_name = "TrypBot AI"
        elif m.sender_type in ("sales", "agent"):
            if session.assigned_sales_person:
                sender_name = (
                    session.assigned_sales_person.get_full_name()
                    or session.assigned_sales_person.username
                )
            else:
                sender_name = "Agent"
        else:
            sender_name = ""

        media_url = ""
        if m.media_url:
            media_url = m.media_url
        elif m.whatsapp_media_id:
            from django.urls import reverse
            media_url = reverse("crm_media_proxy", args=[m.id])

        data.append({
            "id":          m.id,
            "sender_type": m.sender_type,
            "sender_name": sender_name,
            "message":     m.message,
            "created_at":  m.created_at.strftime("%I:%M %p"),
            "media_url":   media_url,
            "media_type":  m.media_type or "",
            "filename":    m.media_filename or "",
        })

    # Current ticks of the last sent messages, so the open chat updates them.
    statuses = dict(
        ChatMessage.objects.filter(session_id=session_id)
        .exclude(sender_type="user").exclude(whatsapp_message_id__isnull=True).exclude(whatsapp_message_id="")
        .order_by("-id").values_list("id", "message_status")[:STATUS_POLL_LIMIT]
    )

    return JsonResponse({"success": True, "messages": data, "statuses": statuses})


# =========================================================
# ALL REMINDERS — date-wise view for sales person
# =========================================================

@crm_login_required
def crm_all_reminders(request):
    """
    Notes and reminders: ?tab=pending (default) or ?tab=completed, newest
    reminder time first. Each row links to its chat.
    """
    role = get_user_role(request.user)
    tab  = "completed" if request.GET.get("tab") == "completed" else "pending"

    visible_ids = filter_sessions_for_user(
        ChatSession.objects.all(), request.user, role
    ).values_list("id", flat=True)

    base = Reminder.objects.filter(session_id__in=visible_ids)
    qs = (base.filter(done=(tab == "completed"))
          .select_related("session", "created_by")
          .order_by("-reminder_at")[:500])

    return render(request, "chatbot/crm/all_reminders.html", {
        "reminders":       list(qs),
        "tab":             tab,
        "pending_count":   base.filter(done=False).count(),
        "completed_count": base.filter(done=True).count(),
        "today_str":       timezone.localdate().isoformat(),
        "user_role":       role,
    })


# =========================================================
# REMINDER DATE AJAX — returns reminders for a given date (JSON)
# =========================================================

@crm_login_required
@require_GET
def crm_reminders_for_date(request):
    """
    AJAX: GET /crm/reminders/for-date/?date=YYYY-MM-DD
    Returns reminders for the requested date for the current user.
    """
    role     = get_user_role(request.user)
    date_str = request.GET.get("date", "").strip()

    if not date_str:
        return JsonResponse({"success": False, "error": "date param required"}, status=400)

    parsed = parse_date(date_str)
    if not parsed:
        return JsonResponse({"success": False, "error": "Invalid date format"}, status=400)

    visible_ids = filter_sessions_for_user(
        ChatSession.objects.all(), request.user, role
    ).values_list("id", flat=True)

    reminders = Reminder.objects.filter(
        session_id__in=visible_ids,
        reminder_at__date=parsed,
    ).select_related("session").order_by("reminder_at")

    data = [
        {
            "id":           r.id,
            "note":         r.note,
            "reminder_at":  r.reminder_at.strftime("%I:%M %p"),
            "done":         r.done,
            "session_id":   r.session_id,
            "session_name": r.session.user_name or r.session.phone_number or f"#{r.session_id}",
            "phone":        r.session.phone_number or "",
        }
        for r in reminders
    ]

    return JsonResponse({"success": True, "date": date_str, "reminders": data})


# =========================================================
# CONTACTS PAGE
# =========================================================

@crm_login_required
def crm_contacts(request):
    role       = get_user_role(request.user)
    search_q   = request.GET.get("q", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date   = request.GET.get("end_date", "").strip()

    contacts = ChatSession.objects.exclude(
        phone_number__isnull=True
    ).exclude(phone_number="")

    contacts = filter_sessions_for_user(contacts, request.user, role)

    # search / date range / tag / opt-out filters (shared with the bulk actions)
    from .campaign_views import filter_contacts
    from .models import ContactTag
    tag_filter = request.GET.get("tag", "").strip()
    opt_filter = request.GET.get("opt", "").strip()
    contacts = filter_contacts(contacts, {
        "q": search_q, "start_date": start_date, "end_date": end_date,
        "tag": tag_filter, "opt": opt_filter,
    })

    today_count = filter_sessions_for_user(
        ChatSession.objects.exclude(phone_number__isnull=True).exclude(phone_number=""),
        request.user, role
    ).filter(created_at__date=timezone.now().date()).count()

    contacts = contacts.prefetch_related("tags").order_by("-updated_at")
    page_obj = Paginator(contacts, 100).get_page(request.GET.get("page", 1))

    return render(request, "chatbot/crm/contacts.html", {
        "contacts":       page_obj,
        "search_q":       search_q,
        "total_contacts": page_obj.paginator.count,
        "user_role":      role,
        "today_count":    today_count,
        "all_tags":       ContactTag.objects.all(),
        "all_tags_json":  [{"id": t.id, "name": t.name, "color": t.color} for t in ContactTag.objects.all()],
        "tag_filter":     tag_filter,
        "opt_filter":     opt_filter,
        "filters_json":   {"q": search_q, "start_date": start_date, "end_date": end_date,
                           "tag": tag_filter, "opt": opt_filter},
    })


# =========================================================
# CONTACTS EXPORT (CSV / TXT)
# =========================================================

CONTACT_EXPORT_HEADERS = [
    "Name", "Phone", "Email", "Destination", "Source",
    "Assigned To", "Created At", "Updated At",
]


def _contact_export_row(contact):
    lead = getattr(contact, "lead", None)
    assigned = contact.assigned_sales_person
    return [
        contact.user_name or "",
        contact.phone_number or "",
        (lead.email if lead and lead.email else "") or "",
        (lead.destination if lead and lead.destination else contact.current_destination) or "",
        (lead.source if lead else "") or "",
        (assigned.get_full_name() or assigned.username) if assigned else "",
        timezone.localtime(contact.created_at).strftime("%Y-%m-%d %H:%M") if contact.created_at else "",
        timezone.localtime(contact.updated_at).strftime("%Y-%m-%d %H:%M") if contact.updated_at else "",
    ]


@crm_login_required
def crm_export_contacts(request):
    if not can_download_data(request.user):
        return HttpResponseForbidden("Only admins can download data.")
    role          = get_user_role(request.user)
    search_q      = request.GET.get("q", "").strip()
    start_date    = request.GET.get("start_date", "").strip()
    end_date      = request.GET.get("end_date", "").strip()
    ids_param     = request.GET.get("ids", "").strip()
    export_format = request.GET.get("format", "csv").strip().lower()

    contacts = ChatSession.objects.exclude(
        phone_number__isnull=True
    ).exclude(phone_number="")

    contacts = filter_sessions_for_user(contacts, request.user, role)

    if ids_param:
        id_list = [i for i in ids_param.split(",") if i.isdigit()]
        contacts = contacts.filter(id__in=id_list)
    else:
        if search_q:
            contacts = contacts.filter(
                Q(user_name__icontains=search_q) |
                Q(phone_number__icontains=search_q)
            )

        if start_date and end_date:
            contacts = contacts.filter(created_at__date__range=[start_date, end_date])
        elif start_date:
            contacts = contacts.filter(created_at__date__gte=start_date)
        elif end_date:
            contacts = contacts.filter(created_at__date__lte=end_date)

    contacts = contacts.select_related("lead", "assigned_sales_person").order_by("-updated_at")

    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")

    if export_format == "txt":
        response = HttpResponse(content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="contacts_{timestamp}.txt"'
        response.write("\t".join(CONTACT_EXPORT_HEADERS) + "\r\n")
        for contact in contacts:
            response.write("\t".join(str(v) for v in _contact_export_row(contact)) + "\r\n")
        return response

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="contacts_{timestamp}.csv"'
    writer = csv.writer(response)
    writer.writerow(CONTACT_EXPORT_HEADERS)
    for contact in contacts:
        writer.writerow(_contact_export_row(contact))
    return response


# =========================================================
# ITINERARY HELPERS
# =========================================================

def _build_daywise_section(post_data):
    day_lines = []
    day_num   = 1

    while True:
        activity_key = f"activity_{day_num}"
        if activity_key not in post_data:
            break

        activity = post_data.get(activity_key, "").strip()
        stay     = post_data.get(f"stay_{day_num}", "").strip()

        line = f"Day {day_num}: {activity or 'No activity specified'}"
        if stay:
            line += f"\n  Night Stay: {stay}"

        day_lines.append(line)
        day_num += 1

        if day_num > 30:
            break

    return "\n".join(day_lines) if day_lines else "No day-wise plan provided."


def _restore_days(post_data):
    days    = []
    day_num = 1
    while day_num <= 30:
        activity_key = f"activity_{day_num}"
        if activity_key not in post_data and day_num > 1:
            break
        days.append({
            "day":      day_num,
            "activity": post_data.get(activity_key, "").strip(),
            "stay":     post_data.get(f"stay_{day_num}", "").strip(),
        })
        day_num += 1

    return days or [{"day": 1, "activity": "", "stay": ""}]


def _build_title(arrival_city: str, drop_city: str, total_days: int) -> str:
    route = arrival_city
    if drop_city and drop_city.lower() != arrival_city.lower():
        route += f" → {drop_city}"
    return f"{route} — {total_days}D Package"


# =========================================================
# CREATE ITINERARY
# =========================================================

FIXED_POLICIES = """

INCLUSIONS

• Well appointed rooms in mentioned hotels
• Daily breakfast
• A C vehicle for transfers and sightseeing
• Driver allowance toll and parking
• All applicable hotel taxes

EXCLUSIONS

• Any meals other than breakfast
• Any transport not mentioned
• Entry tickets and boating charges
• Tips insurance and personal expenses
• Delays due to natural or political reasons
• Airfare or train fare
• GST at 5 percent

PAYMENT POLICY

• 20 percent advance at time of booking
• 20 percent after hotel voucher
• 60 percent during tour in parts
• For tours between 15 December to 2 January 50 percent advance required

CHILD POLICY

• Child up to 6 years Free
• Child 6 to 8 years Half charge
• Child above 8 years Full charge

CANCELLATION POLICY

• Minimum Rs 3000 per person
• 25 percent between 45 to 30 days
• 50 percent between 30 to 15 days
• 75 percent between 15 to 5 days
• 100 percent within 5 days or no show

HOTEL POLICY

• Check in time 12 pm
• Check out time 11 am
• Early check in subject to availability
• Late check out extra charges applicable

VEHICLE POLICY

• CNG Petrol or Diesel vehicle as per availability
• No guarantee of luggage carrier

"""


@crm_login_required
def crm_create_itinerary(request):
    if request.method != "POST":
        return render(request, "chatbot/crm/create_itinerary.html", {
            "validation_errors": [],
            "form_data":         {},
            "restored_days":     [{"day": 1, "activity": "", "stay": ""}],
            "itinerary":         None,
            "error":             None,
            "itinerary_id":      None,
            "trip_meta":         {},
        })

    arrival_city   = request.POST.get("arrival_city",   "").strip()
    arrival_date   = request.POST.get("arrival_date",   "").strip()
    arrival_time   = request.POST.get("arrival_time",   "").strip()
    drop_city      = request.POST.get("drop_city",      "").strip()
    drop_date      = request.POST.get("drop_date",      "").strip()
    drop_time      = request.POST.get("drop_time",      "").strip()
    adults         = request.POST.get("adults",         "").strip()
    children       = request.POST.get("children",       "").strip()
    child_ages     = request.POST.get("child_ages",     "").strip()
    hotel_category = request.POST.get("hotel_category", "").strip()
    rooms          = request.POST.get("rooms",          "").strip()
    sharing        = request.POST.get("sharing",        "").strip()
    meal_plan      = request.POST.get("meal_plan",      "").strip()
    vehicle_type   = request.POST.get("vehicle_type",   "").strip()
    notes          = request.POST.get("notes",          "").strip()
    effective_drop = drop_city or arrival_city

    daywise_section = _build_daywise_section(request.POST)
    total_days      = daywise_section.count("Day ")

    validation_errors = []
    if not arrival_city:
        validation_errors.append("Arrival city is required.")
    if not adults or not adults.isdigit() or int(adults) < 1:
        validation_errors.append("Please enter a valid number of adults (minimum 1).")
    if not hotel_category:
        validation_errors.append("Please select a hotel category.")
    if not meal_plan:
        validation_errors.append("Please select a meal plan.")
    if not vehicle_type:
        validation_errors.append("Please select a vehicle type.")
    if total_days == 0:
        validation_errors.append("Please add at least one day to the itinerary.")

    if validation_errors:
        return render(request, "chatbot/crm/create_itinerary.html", {
            "validation_errors": validation_errors,
            "form_data":         request.POST,
            "restored_days":     _restore_days(request.POST),
            "itinerary":         None,
            "error":             None,
            "itinerary_id":      None,
            "trip_meta":         {},
        })

    prompt = f"""
    You are a professional travel package writer for an Indian travel agency called Trypdeals.

    Generate a complete, client-ready tour package document.

    STRICT RULES

    • Output plain text only
    • Do not use markdown
    • Do not use **, ##, ###, --- or ===
    • Use CAPITAL LETTERS for all section headings
    • Use only the bullet symbol •
    • Leave one blank line between sections
    • Never mention Dinner
    • Never add timestamps
    • Make the itinerary realistic and geographically practical
    • Keep sightseeing locations logically grouped
    • Ensure smooth routing with minimal backtracking

    DOCUMENT STRUCTURE

    PACKAGE TITLE

    Write destination name followed by TOUR PACKAGE

    GUEST DETAILS

    • Adults: {adults}
    • Children: {children or "0"}{f" (Ages: {child_ages})" if child_ages else ""}
    • Travel Dates: {arrival_date or "TBD"}{f" to {drop_date}" if drop_date else ""}
    • Accommodation: {hotel_category}{f" | {rooms} Rooms" if rooms else ""}{f" | {sharing}" if sharing else ""}
    • Meal Plan: {meal_plan}
    • Vehicle: {vehicle_type}

    DAY-WISE ITINERARY

    Create detailed sightseeing itinerary for each day.

    Format:

    DAY 1: DESTINATION NAME

    • Arrival / pickup details
    • Sightseeing point
    • Sightseeing point
    • Sightseeing point
    • Leisure activity if applicable
    • Overnight stay at city

    DAY 2: DESTINATION NAME

    • Morning activity
    • Sightseeing point
    • Sightseeing point
    • Sightseeing point
    • Overnight stay at city

    Rules:

    • Start first day with arrival and pickup
    • Last day must end with drop-off
    • Include major tourist attractions
    • Keep attractions geographically sensible
    • Mention overnight stay every night
    • Mention drop-off on final day
    • Do not include hotel names
    • Do not mention meal timings
    • Do not add pricing inside itinerary

    BASE ITINERARY DATA

    {daywise_section}

    ARRIVAL DETAILS

    Pickup City: {arrival_city}
    Arrival Date: {arrival_date or "TBD"}
    Arrival Time: {arrival_time or "TBD"}

    DROP DETAILS

    Drop City: {effective_drop}
    Drop Date: {drop_date or "TBD"}
    Drop Time: {drop_time or "TBD"}

    SUGGESTED ACCOMMODATION

    Provide city-wise stay plan only.

    Format:

    • City Name (Day X) - ____________________

    Leave hotel names blank.

    COST ESTIMATE

    Calculate realistic per-person package cost in INR based on:

    • Hotel Category: {hotel_category}
    • Meal Plan: {meal_plan}
    • Vehicle Type: {vehicle_type}
    • Adults: {adults}
    • Children: {children or "0"}
    • Rooms: {rooms or "Required"}
    • Sharing: {sharing or "Standard"}
    • Duration: {total_days} Days

    Output:

    FINAL PRICE: ₹[Amount]/- Per Person

    (Excluding GST @ 5%)

    IMPORTANT NOTES

    Generate only travel related notes.

    {f"Special Instructions: {notes}" if notes else ""}

    IMPORTANT

    Do NOT generate:

    • INCLUSIONS
    • EXCLUSIONS
    • PAYMENT POLICY
    • CANCELLATION POLICY
    • CHILD POLICY
    • HOTEL POLICY
    • VEHICLE POLICY

    Those sections will be added separately.

    Return only the final itinerary document.
    """

    try:
        max_tokens = min(8000, max(4000, total_days * 350))
        itinerary_text = _crm_deepseek(prompt, max_tokens=max_tokens)

        if not itinerary_text or not itinerary_text.strip():
            raise ValueError("Empty response received from AI.")

        itinerary_text = itinerary_text.strip() + "\n\n" + FIXED_POLICIES

        itinerary_obj = Itinerary.objects.create(
            title           = _build_title(arrival_city, effective_drop, total_days),
            generated_by_ai = itinerary_text,
            total_days      = total_days,
            status          = "generated",
        )

    except Exception as exc:
        traceback.print_exc()
        return render(request, "chatbot/crm/create_itinerary.html", {
            "itinerary":         None,
            "error":             f"Unable to generate the itinerary right now. (Reason: {exc})",
            "itinerary_id":      None,
            "validation_errors": [],
            "form_data":         request.POST,
            "restored_days":     _restore_days(request.POST),
            "trip_meta":         {},
        })

    trip_meta = {
        "arrival_city":   arrival_city,
        "drop_city":      effective_drop,
        "total_days":     total_days,
        "adults":         adults,
        "children":       children or "0",
        "hotel_category": hotel_category,
        "meal_plan":      meal_plan,
        "vehicle_type":   vehicle_type,
        "arrival_date":   arrival_date,
        "drop_date":      drop_date,
        "rooms":          rooms,
        "sharing":        sharing,
    }

    return render(request, "chatbot/crm/create_itinerary.html", {
        "itinerary":         itinerary_text,
        "error":             None,
        "itinerary_id":      itinerary_obj.pk,
        "validation_errors": [],
        "form_data":         {},
        "restored_days":     [{"day": 1, "activity": "", "stay": ""}],
        "trip_meta":         trip_meta,
    })


# =========================================================
# CRM TEMPLATES
# =========================================================

@crm_login_required
def crm_templates(request):
    templates = CRMTemplate.objects.all()

    return render(
        request,
        "chatbot/crm/templates.html",
        {
            "templates": templates
        }
    )


@crm_login_required
@require_GET
def crm_api_templates(request):
    """API endpoint to get list of CRM templates for dropdown"""
    try:
        from .models import CRMTemplate
        print(f"[TEMPLATES API] CRMTemplate model imported successfully")
        templates = CRMTemplate.objects.all()
        print(f"[TEMPLATES API] Query executed, count: {templates.count()}")
        templates_data = list(templates.values('id', 'title', 'template_text'))
        print(f"[TEMPLATES API] Templates data: {templates_data}")
        return JsonResponse({
            "success": True,
            "templates": templates_data
        })
    except Exception as e:
        print(f"[TEMPLATES API] Error: {e}")
        import traceback
        print(f"[TEMPLATES API] Traceback: {traceback.format_exc()}")
        return JsonResponse({
            "success": False,
            "error": str(e),
            "templates": []
        }, status=500)


@crm_login_required
@require_POST
def crm_send_template(request, session_id):
    """
    Send a template message to a closed/inactive chat session.
    This re-opens the chat for engagement.
    """
    from .views import send_whatsapp_template_message
    
    role = get_user_role(request.user)
    session = get_object_or_404(ChatSession, id=session_id)

    if not has_session_access(session, request.user, role):
        return JsonResponse({"success": False, "error": "Access denied."}, status=403)

    try:
        body = json.loads(request.body)
        template_id = body.get("template_id")
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid request"}, status=400)

    if not template_id:
        return JsonResponse({"success": False, "error": "Template ID required"}, status=400)

    try:
        template = CRMTemplate.objects.get(id=template_id)
    except CRMTemplate.DoesNotExist:
        return JsonResponse({"success": False, "error": "Template not found"}, status=404)

    # Check if template has a WhatsApp template name
    if not template.template_name:
        return JsonResponse({
            "success": False, 
            "error": "Template does not have a WhatsApp template name. Please add the approved template name from Meta."
        }, status=400)

    # Send template message via WhatsApp API (proper template format)
    # Ensure phone number has country code
    phone_number = session.phone_number
    if not phone_number:
        return JsonResponse({
            "success": False,
            "error": "Session does not have a phone number. Cannot send template message."
        }, status=400)
    
    phone_number = _whatsapp_number(phone_number)
    if not phone_number:
        return JsonResponse({
            "success": False,
            "error": f"Invalid phone number '{session.phone_number}'. Cannot send template message."
        }, status=400)

    # Approved templates can go at any time, inside the 24-hour window too
    # (the "Follow Up" option in the attach sheet).
    last_user_message = ChatMessage.objects.filter(
        session=session, sender_type='user'
    ).order_by('-created_at').first()

    # Log template details for debugging
    print(f"[TEMPLATE SEND] Template Name: {template.template_name}")
    print(f"[TEMPLATE SEND] Phone: {phone_number}")
    print(f"[TEMPLATE SEND] Template Text: {template.template_text}")
    print(f"[TEMPLATE SEND] Last user message: {last_user_message.created_at if last_user_message else 'None'}")
    
    # Check if WhatsApp credentials are configured
    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_TOKEN:
        print("[TEMPLATE SEND] WhatsApp credentials not configured - using local test mode")
        # Simulate successful template send for local testing
        whatsapp_response = {
            "messages": [{"id": f"local_test_{uuid.uuid4().hex[:12]}"}]
        }
    else:
        whatsapp_response = send_whatsapp_template_message(
            to=phone_number,
            template_name=template.template_name,
            components=None
        )
    
    # Extract WhatsApp message ID
    whatsapp_message_id = ""
    if isinstance(whatsapp_response, dict):
        whatsapp_message_id = whatsapp_response.get("messages", [{}])[0].get("id", "")
    
    send_error = _whatsapp_error_text(whatsapp_response)
    if send_error:
        print(f"[TEMPLATE SEND] FAILED to {phone_number}: {whatsapp_response}")
        _note_send_error(session, whatsapp_response, f"The template \"{template.title}\"")
        return JsonResponse({"success": False, "error": send_error}, status=400)

    # Save message to database
    msg = ChatMessage.objects.create(
        session=session,
        sender_type="sales",
        message=template.template_text,
        whatsapp_message_id=whatsapp_message_id,
        message_status="sent",
    )

    # Re-open the chat if it was closed
    conv_status, _ = ConversationStatus.objects.get_or_create(session=session)
    if conv_status.closed:
        conv_status.closed = False
        conv_status.save(update_fields=['closed'])
    
    if not session.is_active:
        session.is_active = True
        session.save(update_fields=['is_active'])

    session.last_message = template.template_text
    session.updated_at = timezone.now()
    session.save(update_fields=["last_message", "updated_at"])

    return JsonResponse({
        "success": True,
        "message": {
            "id": msg.id,
            "text": msg.message,
            "sender": request.user.get_full_name() or request.user.username,
            "time": msg.created_at.strftime("%I:%M %p"),
            "type": "sales",
            "status": "delivered",
        }
    })


# =========================================================
# DAYWISE STATS
# =========================================================

@crm_login_required
@require_GET
def crm_daywise_stats(request):
    """
    GET /crm/daywise-stats/?start=YYYY-MM-DD&end=YYYY-MM-DD

    Returns:
    {
        "success": true,
        "labels": [{"name": "HOT", "color": "#ef4444"}, …],   ← ALL labels
        "rows": [
            {
                "date":   "2025-06-01",
                "new":    12,
                "hot":    4,
                "paid":   2,
                "open":   8,
                "labels": [
                    {"name": "HOT",     "color": "#ef4444", "count": 4},
                    {"name": "PAID",    "color": "#22c55e", "count": 2},
                    {"name": "PENDING", "color": "#f59e0b", "count": 1},
                    …
                ]
            },
            …
        ]
    }
    """
    role  = get_user_role(request.user)
    start = request.GET.get("start", "").strip()
    end   = request.GET.get("end",   "").strip()

    # ── Base queryset: same scope + filters as the Lead Analysis page ──
    # (admin: all chats; team leader: own team; sales: own), so the
    # day-wise numbers add up to the page's Total Leads.
    qs = ChatSession.objects.all()
    if role != "admin":
        qs = qs.filter(assigned_sales_person_id__in=team_user_ids(request.user))
    sales_person = request.GET.get("sales_person", "").strip()
    if sales_person == "none":
        qs = qs.filter(assigned_sales_person__isnull=True)
    elif sales_person.isdigit() and (role == "admin" or int(sales_person) in team_user_ids(request.user)):
        qs = qs.filter(assigned_sales_person_id=int(sales_person))
    source = request.GET.get("source", "").strip()
    if source:
        qs = qs.filter(lead__source=source)

    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)

    # ── All labels that exist in the system ────────────────────
    all_labels = list(
        ConversationLabel.objects.order_by("order", "name")
        .values("name", "color")
    )

    # ── Core aggregations (unchanged logic) ────────────────────
    def _by_day(filtered_qs):
        return {
            str(r["day"]): r["count"]
            for r in (
                filtered_qs
                .annotate(day=TruncDate("created_at"))
                .values("day")
                .annotate(count=Count("id"))
                .order_by("day")
            )
        }

    new_map  = _by_day(qs)
    hot_map  = _by_day(qs.filter(conv_status__label__name__iexact="HOT"))
    paid_map = _by_day(qs.filter(conv_status__label__name__iexact="PAID"))
    open_map = _by_day(
        qs.filter(Q(conv_status__closed=False) | Q(conv_status__isnull=True))
    )

    # ── Per-label counts by day ────────────────────────────────
    # Build one dict per label:  label_name → {date_str: count}
    label_maps = {}
    for lb in all_labels:
        label_maps[lb["name"]] = _by_day(
            qs.filter(conv_status__label__name__iexact=lb["name"])
        )
    # Chats with no label, so each day's label columns add up to its total.
    no_label = {"name": "No Label", "color": "#9ca3af"}
    label_maps[no_label["name"]] = _by_day(
        qs.filter(Q(conv_status__isnull=True) | Q(conv_status__label__isnull=True))
    )
    all_labels.append(no_label)

    # ── Merge all days ─────────────────────────────────────────
    all_days = sorted(
        set(new_map)
        | set(hot_map)
        | set(paid_map)
        | set(open_map)
        | {day for lm in label_maps.values() for day in lm}
    )

    rows = []
    for day in all_days:
        label_counts = [
            {
                "name":  lb["name"],
                "color": lb["color"],
                "count": label_maps[lb["name"]].get(day, 0),
            }
            for lb in all_labels
        ]

        rows.append(
            {
                "date":   day,
                "new":    new_map.get(day,  0),
                "hot":    hot_map.get(day,  0),
                "paid":   paid_map.get(day, 0),
                "open":   open_map.get(day, 0),
                "labels": label_counts,
            }
        )

    return JsonResponse({"success": True, "labels": all_labels, "rows": rows})


# =========================================================
# LEAD ANALYSIS
# =========================================================

# Label filter value for chats with no label (sales person filter uses "none").
NO_LABEL_FILTER = "__none__"

@crm_login_required
def crm_lead_analysis(request):
    """
    Lead analysis page with filtering by labels (Hot, Follow Up, Paid)
    and sales person-wise breakdown. Admins see all data, sales persons see only their own.
    """
    try:
        from django.utils import timezone
        from datetime import timedelta
        
        role = get_user_role(request.user)
        is_admin = role == "admin"
        
        print(f"[LEAD ANALYSIS DEBUG] User: {request.user.username}, is_staff: {request.user.is_staff}, is_superuser: {request.user.is_superuser}, is_admin: {is_admin}, role: {role}")
        
        # Get filter parameters
        label_filter = request.GET.get("label", "").strip()
        sales_person_filter = request.GET.get("sales_person", "").strip()
        date_from = request.GET.get("date_from", "").strip()
        date_to = request.GET.get("date_to", "").strip()
        status_filter = request.GET.get("status", "").strip()
        source_filter = request.GET.get("source", "").strip()
        
        # Get all labels for filter dropdown
        labels = ConversationLabel.objects.all().order_by("order", "name")
        
        # Get sales persons for filter dropdown - filtered by role
        if is_admin:
            # Admins see all sales persons
            sales_persons = User.objects.filter(
                salesprofile__isnull=False
            ).order_by('first_name', 'last_name')
        else:
            # A sales person sees only themselves; a team leader sees their
            # team (and can pick one member from the dropdown).
            visible_ids = team_user_ids(request.user)
            sales_persons = User.objects.filter(
                id__in=visible_ids,
                salesprofile__isnull=False
            ).order_by('first_name', 'last_name')
            if sales_person_filter not in {str(pk) for pk in visible_ids}:
                sales_person_filter = "" if len(visible_ids) > 1 else str(request.user.id)

        # Build base queryset - include ALL sessions like Chats tab does
        # Use ChatSession to match Chats tab logic exactly
        from .models import ChatSession
        queryset = ChatSession.objects.select_related('assigned_sales_person')

        # Admin: every chat. Sales: their own. Team leader: their team's.
        # Same rule as the Chats list (filter_sessions_for_user).
        if not is_admin:
            queryset = queryset.filter(assigned_sales_person_id__in=team_user_ids(request.user))
        
        # Apply source filter (website vs meta/whatsapp)
        if source_filter:
            queryset = queryset.filter(lead__source=source_filter)
        
        # Apply label filter - only filter if label is selected, otherwise show all
        if label_filter == NO_LABEL_FILTER:
            queryset = queryset.filter(Q(conv_status__isnull=True) | Q(conv_status__label__isnull=True))
        elif label_filter:
            queryset = queryset.filter(
                Q(conv_status__label__name__iexact=label_filter)
            )

        # Apply sales person filter ("none" = not assigned to anyone)
        if sales_person_filter == "none":
            queryset = queryset.filter(assigned_sales_person__isnull=True)
        elif sales_person_filter:
            queryset = queryset.filter(assigned_sales_person_id=sales_person_filter)
        
        # Date filters use the lead's created time, not its last activity
        if date_from:
            try:
                from datetime import datetime
                date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
                # Leads created on or after this date
                queryset = queryset.filter(created_at__date__gte=date_from_obj)
            except ValueError:
                pass
        
        if date_to:
            try:
                from datetime import datetime
                date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
                # Leads created on or before this date
                queryset = queryset.filter(created_at__date__lte=date_to_obj)
            except ValueError:
                pass
        
        # Calculate 24-hour activity status for each lead
        twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
        leads_with_status = []
        
        for session in queryset.select_related('conv_status__label'):
            # Get conversation status from select_related (may not exist for all sessions)
            try:
                conv_status = session.conv_status
            except ConversationStatus.DoesNotExist:
                conv_status = None
            label = conv_status.label if conv_status else None
            # The chat's own assignee: the same field the Chats list and the
            # filters use, so the table and the counts agree.
            assigned_to = session.assigned_sales_person
            closed = conv_status.closed if conv_status else False
            
            is_active = session.updated_at >= twenty_four_hours_ago and not closed
            leads_with_status.append({
                'session': session,
                'label': label,
                'assigned_to': assigned_to,
                'closed': closed,
                'is_active': is_active,
                'hours_since_activity': (timezone.now() - session.updated_at).total_seconds() / 3600
            })
        
        # Apply status filter if provided
        if status_filter == "active":
            leads_with_status = [l for l in leads_with_status if l['is_active']]
        elif status_filter == "inactive":
            leads_with_status = [l for l in leads_with_status if not l['is_active']]
        
        # Newest leads first
        leads_with_status.sort(key=lambda x: x['session'].created_at, reverse=True)
        
        # Counts are taken from exactly the leads listed below (after every
        # filter, the status one too), so each box adds up to Total Leads:
        # leads without a label and leads not assigned get their own row.
        from collections import Counter
        label_count = Counter(l['label'].id if l['label'] else None for l in leads_with_status)
        label_stats = {}
        for label in labels:
            if label_count.get(label.id):
                label_stats[label.name] = {'count': label_count[label.id], 'color': label.color}
        if label_count.get(None):
            label_stats['No Label'] = {'count': label_count[None], 'color': '#9ca3af'}

        person_count = Counter(l['assigned_to'] for l in leads_with_status)
        sales_stats = {}
        for person, count in sorted(person_count.items(),
                                    key=lambda kv: (kv[0] is None, -kv[1])):
            if person is None:
                sales_stats['none'] = {'name': 'Not Assigned', 'count': count}
            else:
                sales_stats[person.id] = {'name': person.get_full_name() or person.username, 'count': count}
        
        # Pagination - show all leads without pagination
        from django.core.paginator import Paginator
        # 100 rows per page: listing all leads at once made the page very
        # heavy on phones. The counts above still cover every lead.
        paginator = Paginator(leads_with_status, 100)
        page_params = request.GET.copy()
        page_params.pop("page", None)
        page_qs = page_params.urlencode()
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)
        
        # Total = the leads listed (same set as the counts above)
        total_leads_count = len(leads_with_status)
        print(f"[TOTAL LEADS DEBUG] Final total_leads_count: {total_leads_count}")
        
        return render(
            request,
            "chatbot/crm/lead_analysis.html",
            {
                "leads": page_obj,
                "labels": labels,
                "sales_persons": sales_persons,
                "label_stats": label_stats,
                "sales_stats": sales_stats,
                "label_filter": label_filter,
                "sales_person_filter": sales_person_filter,
                "date_from": date_from,
                "date_to": date_to,
                "status_filter": status_filter,
                "user_role": role,
                "total_leads": total_leads_count,
                "is_admin": is_admin,
                # Admin or team leader: choose a person from the dropdown.
                "can_pick_person": is_admin or len(sales_persons) > 1,
                # Current filters, kept on the page links.
                "page_qs": page_qs,
            }
        )
    except Exception as e:
        import traceback
        print(f"[ERROR] crm_lead_analysis: {e}")
        print(traceback.format_exc())
        from django.http import HttpResponse
        return HttpResponse(f"<h1>Error</h1><p>{str(e)}</p><pre>{traceback.format_exc()}</pre>", status=500)


# =========================================================
# LEAD ANALYSIS EXPORT (EXCEL)
# =========================================================

@crm_login_required
def crm_export_leads_analysis(request):
    """
    Export leads from analysis page to Excel format.
    Supports day-wise export and all leads export.
    Columns: Name, Phone Number, Label, Sales Person
    """
    if not can_download_data(request.user):
        return HttpResponseForbidden("Only admins can download data.")
    try:
        from django.utils import timezone
        from datetime import timedelta
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        
        role = get_user_role(request.user)
        is_admin = role == "admin"
        
        # Get filter parameters
        label_filter = request.GET.get("label", "").strip()
        sales_person_filter = request.GET.get("sales_person", "").strip()
        date_from = request.GET.get("date_from", "").strip()
        date_to = request.GET.get("date_to", "").strip()
        status_filter = request.GET.get("status", "").strip()
        source_filter = request.GET.get("source", "").strip()
        export_type = request.GET.get("type", "all").strip()  # 'all' or 'daywise'
        
        # Require date range for export
        if not date_from or not date_to:
            from django.http import JsonResponse
            return JsonResponse({"success": False, "error": "Please select date range (from and to) to download leads."}, status=400)
        
        # Build base queryset - use ChatSession to match analysis page logic
        from .models import ChatSession
        queryset = ChatSession.objects.select_related(
            'assigned_sales_person',
            'conv_status',
            'conv_status__label',
            'conv_status__assigned_to'
        )
        
        # Filter by user role - match analysis page logic (team leader: own team)
        if not is_admin:
            queryset = queryset.filter(assigned_sales_person_id__in=team_user_ids(request.user))
        
        # Apply filters - match analysis page logic
        if source_filter:
            queryset = queryset.filter(lead__source=source_filter)
        
        if label_filter == NO_LABEL_FILTER:
            queryset = queryset.filter(Q(conv_status__isnull=True) | Q(conv_status__label__isnull=True))
        elif label_filter:
            queryset = queryset.filter(conv_status__label__name__iexact=label_filter)

        if sales_person_filter == "none":
            queryset = queryset.filter(assigned_sales_person__isnull=True)
        elif sales_person_filter:
            queryset = queryset.filter(assigned_sales_person_id=sales_person_filter)

        if date_from:
            try:
                from datetime import datetime
                date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
                # Lead created time (matches analysis page)
                queryset = queryset.filter(created_at__date__gte=date_from_obj)
            except ValueError:
                pass
        
        if date_to:
            try:
                from datetime import datetime
                date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
                # Lead created time (matches analysis page)
                queryset = queryset.filter(created_at__date__lte=date_to_obj)
            except ValueError:
                pass
        
        if status_filter == "active":
            twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
            queryset = queryset.filter(
                updated_at__gte=twenty_four_hours_ago,
                conv_status__closed=False
            )
        elif status_filter == "inactive":
            twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
            queryset = queryset.filter(
                updated_at__lt=twenty_four_hours_ago
            )
        
        # Create Excel workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Leads Export"
        
        # Define headers
        headers = ["Name", "Phone Number", "Label", "Sales Person", "Created At", "Last Activity", "Status"]
        
        # Apply header styling
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        
        # Sort by latest to old (created_at descending)
        queryset = queryset.order_by('-created_at')
        
        # Add data rows
        row_num = 2
        for session in queryset:
            # Get conversation status
            conv_status = getattr(session, 'conv_status', None)
            
            # The chat's assignee (same field as the analysis page and filters)
            sales_person_name = "Not Assigned"
            if session.assigned_sales_person:
                sales_person_name = session.assigned_sales_person.get_full_name() or session.assigned_sales_person.username
            
            # Get label name
            label_name = conv_status.label.name if conv_status and conv_status.label else ""
            
            # Get status
            twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
            if conv_status and conv_status.closed:
                status = "Closed"
            elif session.updated_at >= twenty_four_hours_ago:
                status = "Active"
            else:
                status = "Inactive"
            
            ws.cell(row=row_num, column=1, value=session.user_name or "")
            ws.cell(row=row_num, column=2, value=session.phone_number or "")
            ws.cell(row=row_num, column=3, value=label_name)
            ws.cell(row=row_num, column=4, value=sales_person_name)
            ws.cell(row=row_num, column=5, value=session.created_at.strftime("%Y-%m-%d %H:%M") if session.created_at else "")
            ws.cell(row=row_num, column=6, value=session.updated_at.strftime("%Y-%m-%d %H:%M") if session.updated_at else "")
            ws.cell(row=row_num, column=7, value=status)
            
            row_num += 1
        
        # Auto-adjust column widths
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column].width = adjusted_width
        
        # Generate response
        from django.http import HttpResponse
        from io import BytesIO
        
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        filename = f"leads_export_{timestamp}.xlsx"
        
        response = HttpResponse(
            output.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        import traceback
        print(f"[ERROR] crm_export_leads_analysis: {e}")
        print(traceback.format_exc())
        from django.http import HttpResponse
        return HttpResponse(f"<h1>Error</h1><p>{str(e)}</p><pre>{traceback.format_exc()}</pre>", status=500)


# ======================================================
# ROLE HELPER
# ======================================================
# No auth wiring yet — every visitor is treated as "admin" so all
# sync/toggle controls render and work. Swap this out later for
# request.user.salesprofile.role once login is wired up.
# ======================================================
 
def _get_user_role(request):
    return "admin"
 
 