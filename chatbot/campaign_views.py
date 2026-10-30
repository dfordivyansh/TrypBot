# =========================================================
# FILE: chatbot/campaign_views.py
# =========================================================
# CRM screens + JSON endpoints for:
#   • Campaigns   (list / create wizard / detail / actions / export)
#   • Tags        (manage, apply to contacts)
#   • Segments    (saved audience filters)
#   • Marketing opt-out + contact import
# The heavy lifting lives in campaign_engine.py.
# =========================================================

import csv
import json
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from . import campaign_engine as eng
from .crm_views import get_user_role
from .decorators import crm_login_required
from .models import (
    Campaign,
    CampaignRecipient,
    ChatSession,
    ContactTag,
    ConversationLabel,
    CRMTemplate,
    Segment,
)

TAG_COLORS = ["#25D366", "#0EA5E9", "#6366F1", "#A855F7", "#EC4899",
              "#EF4444", "#F97316", "#EAB308", "#14B8A6", "#64748B"]


# =========================================================
# SMALL HELPERS
# =========================================================

def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return {}


def _err(msg, status=400):
    return JsonResponse({"success": False, "error": msg}, status=status)


def _fmt(dt):
    return timezone.localtime(dt).strftime("%d %b, %I:%M %p") if dt else ""


def _is_manager(role):
    return role in ("admin", "manager")


def _campaign_qs(user, role):
    qs = Campaign.objects.all()
    if not _is_manager(role):
        qs = qs.filter(created_by=user)
    return qs


def _get_campaign(request, campaign_id):
    role = get_user_role(request.user)
    return get_object_or_404(_campaign_qs(request.user, role), pk=campaign_id), role


def _tag_dict(t):
    return {"id": t.id, "name": t.name, "color": t.color}


def filter_contacts(qs, params):
    """
    Filters shared by the Contacts page and its bulk actions.
    `params` is a dict-like (request.GET or a JSON dict): q, start_date, end_date, tag, opt.
    """
    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(user_name__icontains=q) | Q(phone_number__icontains=q))

    start = parse_date(params.get("start_date") or "") if params.get("start_date") else None
    end = parse_date(params.get("end_date") or "") if params.get("end_date") else None
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)

    tag = params.get("tag")
    if tag == "none":
        qs = qs.filter(tags__isnull=True)
    elif tag and str(tag).isdigit():
        qs = qs.filter(tags__id=int(tag))

    opt = params.get("opt")
    if opt == "out":
        qs = qs.filter(marketing_opt_out=True)
    elif opt == "in":
        qs = qs.filter(marketing_opt_out=False)
    return qs.distinct()


def _sessions_from_body(request, body, role):
    """Sessions selected either by explicit ids or by 'all contacts matching the page filters'."""
    qs = eng.base_contacts_qs(request.user, role)
    if body.get("select_all"):
        return filter_contacts(qs, body.get("filters") or {})
    ids = eng._int_list(body.get("session_ids"))
    return qs.filter(id__in=ids)


def describe_filters(filters):
    """Human-readable chips for a saved filter dict."""
    f = filters or {}
    out = []
    tag_ids = eng._int_list(f.get("tags"))
    if tag_ids:
        names = list(ContactTag.objects.filter(id__in=tag_ids).values_list("name", flat=True))
        out.append(("Tags " + ("all of " if f.get("tag_mode") == "all" else "any of ") + ", ".join(names)))
    ex = eng._int_list(f.get("exclude_tags"))
    if ex:
        out.append("Not tagged " + ", ".join(ContactTag.objects.filter(id__in=ex).values_list("name", flat=True)))
    labels = eng._int_list(f.get("labels"))
    if labels:
        out.append("Label " + ", ".join(ConversationLabel.objects.filter(id__in=labels).values_list("name", flat=True)))
    users = eng._int_list(f.get("assigned_to"))
    if users:
        out.append("Assigned to " + ", ".join(User.objects.filter(id__in=users).values_list("username", flat=True)))
    if f.get("q"):
        out.append(f"Search “{f['q']}”")
    if f.get("destination"):
        out.append(f"Destination {f['destination']}")
    if f.get("source"):
        out.append(f"Source {f['source']}")
    if f.get("created_from") or f.get("created_to"):
        out.append(f"Added {f.get('created_from') or '…'} → {f.get('created_to') or '…'}")
    if f.get("active_within_days"):
        out.append(f"Messaged in last {f['active_within_days']} days")
    if f.get("inactive_days"):
        out.append(f"No message for {f['inactive_days']}+ days")
    return out or ["All contacts"]


# =========================================================
# CAMPAIGN LIST
# =========================================================

STATUS_TABS = [("", "All"), ("running", "Running"), ("scheduled", "Scheduled"),
               ("draft", "Draft"), ("paused", "Paused"), ("completed", "Completed"),
               ("failed", "Failed"), ("cancelled", "Cancelled")]


@crm_login_required
@require_GET
def campaign_list(request):
    role = get_user_role(request.user)
    base = _campaign_qs(request.user, role)

    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()

    qs = base.select_related("created_by").annotate(**eng.stats_annotations())
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(template_title__icontains=q))

    page = Paginator(qs.order_by("-created_at"), 20).get_page(request.GET.get("page", 1))
    for c in page:
        c.stats = eng.stats_dict({
            "r_total": c.r_total, "r_pending": c.r_pending, "r_sent": c.r_sent,
            "r_delivered": c.r_delivered, "r_read": c.r_read, "r_replied": c.r_replied,
            "r_failed": c.r_failed, "r_skipped": c.r_skipped,
        })

    counts = dict(base.values_list("status").annotate(n=Count("id")))
    since = timezone.now() - timedelta(days=30)
    sent_30d = CampaignRecipient.objects.filter(campaign__in=base, sent_at__gte=since).count()
    read_30d = CampaignRecipient.objects.filter(campaign__in=base, read_at__gte=since).count()

    return render(request, "chatbot/crm/campaigns/list.html", {
        "campaigns": page,
        "status": status,
        "q": q,
        "tabs": [(k, label, counts.get(k, 0) if k else sum(counts.values())) for k, label in STATUS_TABS],
        "sent_30d": sent_30d,
        "read_rate_30d": round(read_30d * 100 / sent_30d) if sent_30d else 0,
        "active_count": counts.get("running", 0) + counts.get("scheduled", 0),
        "total_count": sum(counts.values()),
        "user_role": role,
    })


@crm_login_required
@require_GET
def campaign_list_stats(request):
    """Lightweight poll used by the list page to refresh running campaigns."""
    role = get_user_role(request.user)
    ids = eng._int_list((request.GET.get("ids") or "").split(","))
    qs = _campaign_qs(request.user, role).filter(id__in=ids).annotate(**eng.stats_annotations())
    data = {}
    for c in qs:
        data[c.id] = {
            "status": c.status,
            "status_label": c.get_status_display(),
            "stats": eng.stats_dict({
                "r_total": c.r_total, "r_pending": c.r_pending, "r_sent": c.r_sent,
                "r_delivered": c.r_delivered, "r_read": c.r_read, "r_replied": c.r_replied,
                "r_failed": c.r_failed, "r_skipped": c.r_skipped,
            }),
        }
    return JsonResponse({"success": True, "campaigns": data})


# =========================================================
# CREATE WIZARD
# =========================================================

@crm_login_required
@require_GET
def campaign_create(request):
    role = get_user_role(request.user)

    templates = []
    for t in CRMTemplate.objects.all():
        templates.append({
            "id": t.id, "title": t.title, "name": t.template_name,
            "language": t.language, "text": t.template_text,
            "placeholders": eng.template_placeholders(t.template_text),
            "ready": bool(t.template_name),
        })

    tag_qs = ContactTag.objects.all()
    segments = [{"id": s.id, "name": s.name, "filters": s.filters} for s in Segment.objects.all()]
    labels = [{"id": l.id, "name": l.name} for l in ConversationLabel.objects.all()]
    users = []
    if _is_manager(role):
        users = [{"id": u.id, "name": u.get_full_name() or u.username}
                 for u in User.objects.filter(is_active=True).order_by("username")]

    return render(request, "chatbot/crm/campaigns/create.html", {
        "wizard_data": {
            "templates": templates,
            "tags": [_tag_dict(t) for t in tag_qs],
            "segments": segments,
            "labels": labels,
            "users": users,
            "role": role,
            "limits": {"csv_rows": eng.CSV_MAX_ROWS, "recipients": eng.MAX_RECIPIENTS},
            "sources": [{"value": k, "label": v} for k, v in [
                ("name", "Contact name"), ("first_name", "First name"), ("phone", "Phone number"),
                ("destination", "Destination"), ("email", "Email"),
                ("column", "CSV column"), ("fixed", "Fixed text")]],
            "fallbacks": eng.DEFAULT_FALLBACKS,
            "prefill_segment": request.GET.get("segment", ""),
            "from_selection": request.GET.get("from") == "selection",
            "urls": {
                "create": reverse("crm_campaign_create_api"),
                "preview": reverse("crm_campaign_audience_preview"),
                "contacts": reverse("crm_campaign_audience_contacts"),
                "csv": reverse("crm_campaign_audience_csv"),
                "media": reverse("crm_campaign_media"),
                "segment_save": reverse("crm_segment_save"),
                "tag_save": reverse("crm_tag_save"),
                "templates": reverse("crm_templates"),
            },
        },
    })


@crm_login_required
@require_POST
def campaign_create_api(request):
    role = get_user_role(request.user)
    try:
        campaign, summary = eng.create_campaign(request.user, role, _body(request))
    except eng.AudienceError as exc:
        return _err(str(exc))
    except ValueError as exc:
        return _err(str(exc))
    return JsonResponse({
        "success": True,
        "id": campaign.id,
        "status": campaign.status,
        "summary": summary,
        "redirect": reverse("crm_campaign_detail", args=[campaign.id]),
    })


@crm_login_required
@require_POST
def campaign_audience_preview(request):
    role = get_user_role(request.user)
    body = _body(request)
    a_type = body.get("type", "filters")

    if a_type == "segment":
        seg = Segment.objects.filter(pk=body.get("segment_id")).first()
        if not seg:
            return _err("Segment not found.", 404)
        filters = seg.filters
    else:
        filters = body.get("filters") or {}

    qs = eng.resolve_audience(filters, request.user, role)
    if a_type == "contacts":
        qs = qs.filter(id__in=eng._int_list(body.get("session_ids")))

    return JsonResponse({"success": True, **eng.audience_preview(qs)})


@crm_login_required
@require_POST
def campaign_audience_contacts(request):
    """Paged contact picker for the 'choose specific contacts' mode."""
    role = get_user_role(request.user)
    body = _body(request)
    qs = eng.resolve_audience(body.get("filters") or {}, request.user, role).order_by("-updated_at")
    page = Paginator(qs.prefetch_related("tags").select_related("lead"), 30).get_page(body.get("page") or 1)
    rows = []
    for s in page:
        ctx = eng.recipient_context(s)
        rows.append({
            "id": s.id, "name": ctx["name"], "phone": ctx["phone"],
            "destination": ctx["destination"], "opted_out": s.marketing_opt_out,
            "tags": [_tag_dict(t) for t in s.tags.all()],
        })
    return JsonResponse({
        "success": True, "contacts": rows, "page": page.number,
        "pages": page.paginator.num_pages, "total": page.paginator.count,
    })


@crm_login_required
@require_POST
def campaign_audience_csv(request):
    f = request.FILES.get("file")
    if not f:
        return _err("Please choose a file.")
    try:
        parsed = eng.parse_contacts_file(f)
    except ValueError as exc:
        return _err(str(exc))
    except Exception:
        return _err("Could not read this file. Please upload a .csv or .xlsx file.")

    existing = eng.sessions_by_phone([r["phone"] for r in parsed["rows"]])
    return JsonResponse({
        "success": True,
        "columns": parsed["columns"],
        "rows": parsed["rows"],
        "invalid": parsed["invalid"][:20],
        "invalid_count": len(parsed["invalid"]),
        "duplicates": parsed["duplicates"],
        "total_rows": parsed["total_rows"],
        "existing_count": len(existing),
        "new_count": len(parsed["rows"]) - len(existing),
        "opted_out_count": sum(1 for s in existing.values() if s.marketing_opt_out),
    })


@crm_login_required
@require_POST
def campaign_media_upload(request):
    """Upload a header image and return a public https link (Cloudinary)."""
    f = request.FILES.get("file")
    if not f:
        return _err("Please choose an image.")
    if f.content_type not in ("image/jpeg", "image/png"):
        return _err("WhatsApp headers accept JPG or PNG images only.")
    if f.size > 5 * 1024 * 1024:
        return _err("Image must be 5 MB or smaller.")
    from .views import upload_to_cloudinary
    url = upload_to_cloudinary(f)
    if not url:
        return _err("Upload failed. You can paste a public image link instead.", 502)
    return JsonResponse({"success": True, "url": url, "filename": f.name})


# =========================================================
# CAMPAIGN DETAIL
# =========================================================

SOURCE_LABELS = {
    "name": "Contact name", "first_name": "First name", "phone": "Phone number",
    "destination": "Destination", "email": "Email",
}


def _variable_summary(campaign):
    out = []
    for n in eng.template_placeholders(campaign.template_text):
        spec = (campaign.variable_mapping or {}).get(str(n), {}) or {}
        src = spec.get("source", "")
        if src == "column":
            label = f"column “{spec.get('value', '')}”"
        elif src == "fixed":
            label = f"“{spec.get('value', '')}”"
        else:
            label = SOURCE_LABELS.get(src, src)
        out.append(f"{{{{{n}}}}} ← {label}")
    return out


def _audience_label(campaign):
    if campaign.audience_type == "segment":
        return f"Segment: {campaign.segment.name}" if campaign.segment else "Saved segment (deleted)"
    if campaign.audience_type == "csv":
        return "Uploaded contact file"
    if campaign.audience_type == "contacts":
        return "Hand-picked contacts"
    return "; ".join(describe_filters(campaign.audience_filters))


@crm_login_required
@require_GET
def campaign_detail(request, campaign_id):
    campaign, role = _get_campaign(request, campaign_id)
    first = campaign.recipients.exclude(status="skipped").order_by("id").first()
    payload = _stats_payload(campaign)
    placeholders = eng.template_placeholders(campaign.template_text)

    page_data = {
        "status": campaign.status,
        "stats": payload["stats"],
        "failures": payload["failures"],
        "info": {
            "last_error": campaign.last_error,
            "scheduled_at": payload["scheduled_at"],
            "started_at": payload["started_at"],
            "completed_at": payload["completed_at"],
        },
        "preview_text": eng.render_template_text(campaign.template_text, first.variables if first else {}),
        "has_variables": bool(placeholders),
        "header": {
            "type": campaign.header_media_type,
            "url": campaign.header_media_url,
            "filename": campaign.header_media_filename,
        },
        "template_title": campaign.template_title,
        "template_name": campaign.template_name,
        "language": campaign.template_language,
        "audience_label": _audience_label(campaign),
        "variables": _variable_summary(campaign),
        "urls": {
            "stats": reverse("crm_campaign_stats", args=[campaign.id]),
            "recipients": reverse("crm_campaign_recipients", args=[campaign.id]),
            "action": reverse("crm_campaign_action", args=[campaign.id, "ACTION"]),
            "export": reverse("crm_campaign_export", args=[campaign.id]),
        },
    }
    return render(request, "chatbot/crm/campaigns/detail.html", {
        "campaign": campaign,
        "page_data": page_data,
    })


def _stats_payload(campaign):
    failures = list(
        campaign.recipients.filter(status="failed")
        .values("error_message").annotate(n=Count("id")).order_by("-n")[:5]
    )
    return {
        "success": True,
        "status": campaign.status,
        "status_label": campaign.get_status_display(),
        "last_error": campaign.last_error,
        "scheduled_at": _fmt(campaign.scheduled_at),
        "started_at": _fmt(campaign.started_at),
        "completed_at": _fmt(campaign.completed_at),
        "stats": eng.campaign_stats(campaign),
        "failures": [{"message": f["error_message"] or "Unknown error", "count": f["n"]} for f in failures],
    }


@crm_login_required
@require_GET
def campaign_stats_api(request, campaign_id):
    campaign, _ = _get_campaign(request, campaign_id)
    return JsonResponse(_stats_payload(campaign))


RECIPIENT_FILTERS = {
    "pending":   Q(status__in=("pending", "sending")),
    "sent":      Q(sent_at__isnull=False),
    "delivered": Q(delivered_at__isnull=False),
    "read":      Q(read_at__isnull=False),
    "replied":   Q(replied_at__isnull=False),
    "failed":    Q(status="failed"),
    "skipped":   Q(status="skipped"),
}


@crm_login_required
@require_GET
def campaign_recipients_api(request, campaign_id):
    campaign, _ = _get_campaign(request, campaign_id)
    qs = campaign.recipients.all()

    flt = request.GET.get("filter", "")
    if flt in RECIPIENT_FILTERS:
        qs = qs.filter(RECIPIENT_FILTERS[flt])

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))

    page = Paginator(qs.order_by("id"), 25).get_page(request.GET.get("page", 1))
    rows = []
    for r in page:
        rows.append({
            "id": r.id, "name": r.name, "phone": r.phone,
            "chat_url": reverse("crm_chat_detail", args=[r.session_id]) if r.session_id else "",
            "status": r.status,
            "sent_at": _fmt(r.sent_at), "delivered_at": _fmt(r.delivered_at),
            "read_at": _fmt(r.read_at), "replied": r.replied_at is not None,
            "replied_at": _fmt(r.replied_at),
            "error": r.error_message, "error_code": r.error_code,
        })
    return JsonResponse({
        "success": True, "rows": rows, "page": page.number,
        "pages": page.paginator.num_pages, "total": page.paginator.count,
    })


@crm_login_required
@require_POST
def campaign_action(request, campaign_id, action):
    campaign, role = _get_campaign(request, campaign_id)
    body = _body(request)

    try:
        if action == "start":
            if campaign.status != "draft":
                return _err("Only draft campaigns can be started.")
            if not body.get("consent"):
                return _err("Please confirm that these contacts have opted in to receive WhatsApp messages.")
            if not campaign.recipients.filter(status="pending").exists():
                return _err("This campaign has no contacts to send to.")
            scheduled_at = None
            if body.get("mode") == "later":
                try:
                    scheduled_at = datetime.fromisoformat(str(body.get("at")))
                except ValueError:
                    return _err("Please choose a valid schedule date and time.")
                if timezone.is_naive(scheduled_at):
                    scheduled_at = timezone.make_aware(scheduled_at)
                if scheduled_at <= timezone.now() + timedelta(seconds=30):
                    return _err("The scheduled time must be in the future.")
            campaign.consent_confirmed = True
            campaign.save(update_fields=["consent_confirmed"])
            eng.launch_campaign(campaign, scheduled_at)

        elif action == "pause":
            eng.pause_campaign(campaign)
        elif action == "resume":
            eng.resume_campaign(campaign)
        elif action == "cancel":
            eng.cancel_campaign(campaign)
        elif action == "retry":
            n = eng.retry_failed(campaign)
            return JsonResponse({"success": True, "message": f"Retrying {n} failed message(s)."})
        elif action == "duplicate":
            copy = eng.duplicate_campaign(campaign, request.user)
            return JsonResponse({"success": True, "redirect": reverse("crm_campaign_detail", args=[copy.id])})
        elif action == "delete":
            if campaign.status in ("running", "scheduled"):
                return _err("Pause or cancel the campaign before deleting it.")
            campaign.delete()
            return JsonResponse({"success": True, "redirect": reverse("crm_campaign_list")})
        else:
            return _err("Unknown action.", 404)
    except ValueError as exc:
        return _err(str(exc))

    campaign.refresh_from_db()
    return JsonResponse(_stats_payload(campaign))


@crm_login_required
@require_GET
def campaign_export(request, campaign_id):
    campaign, _ = _get_campaign(request, campaign_id)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    safe = "".join(ch if ch.isalnum() else "_" for ch in campaign.name)[:40] or "campaign"
    response["Content-Disposition"] = f'attachment; filename="campaign_{safe}_{timezone.now():%Y%m%d}.csv"'
    w = csv.writer(response)
    w.writerow(["Name", "Phone", "Status", "Sent at", "Delivered at", "Read at", "Replied", "Error code", "Error"])
    for r in campaign.recipients.all().iterator():
        w.writerow([r.name, r.phone, r.status, _fmt(r.sent_at), _fmt(r.delivered_at), _fmt(r.read_at),
                    "yes" if r.replied_at else "", r.error_code, r.error_message])
    return response


# =========================================================
# TAGS & SEGMENTS PAGE
# =========================================================

@crm_login_required
@require_GET
def audience_page(request):
    role = get_user_role(request.user)
    scope = Q(sessions__assigned_sales_person=request.user) if role == "sales" else Q()
    tags = ContactTag.objects.annotate(
        contact_count=Count("sessions", filter=scope, distinct=True)
    ).order_by("name")

    segments = []
    for s in Segment.objects.select_related("created_by"):
        qs = eng.resolve_audience(s.filters, request.user, role)
        segments.append({
            "id": s.id, "name": s.name, "description": s.description,
            "chips": describe_filters(s.filters),
            "count": qs.count(), "opted_out": qs.filter(marketing_opt_out=True).count(),
            "created_by": s.created_by.username if s.created_by else "",
            "created_at": s.created_at,
        })

    return render(request, "chatbot/crm/campaigns/audience.html", {
        "tags": tags,
        "segments": segments,
        "colors": TAG_COLORS,
        "user_role": role,
        "can_manage": _is_manager(role),
        "opted_out_total": eng.base_contacts_qs(request.user, role).filter(marketing_opt_out=True).count(),
    })


@crm_login_required
@require_POST
def tag_save(request):
    role = get_user_role(request.user)
    body = _body(request)
    name = (body.get("name") or "").strip()[:60]
    color = body.get("color") or TAG_COLORS[0]
    if not name:
        return _err("Tag name is required.")
    if not (isinstance(color, str) and len(color) in (4, 7) and color.startswith("#")):
        color = TAG_COLORS[0]

    tag_id = body.get("id")
    if tag_id:
        if not _is_manager(role):
            return _err("Only managers can edit tags.", 403)
        tag = get_object_or_404(ContactTag, pk=tag_id)
        if ContactTag.objects.filter(name__iexact=name).exclude(pk=tag.pk).exists():
            return _err("A tag with this name already exists.")
        tag.name, tag.color = name, color
        tag.save(update_fields=["name", "color"])
    else:
        if ContactTag.objects.filter(name__iexact=name).exists():
            return _err("A tag with this name already exists.")
        tag = ContactTag.objects.create(name=name, color=color, created_by=request.user)
    return JsonResponse({"success": True, "tag": _tag_dict(tag)})


@crm_login_required
@require_POST
def tag_delete(request, tag_id):
    role = get_user_role(request.user)
    if not _is_manager(role):
        return _err("Only managers can delete tags.", 403)
    get_object_or_404(ContactTag, pk=tag_id).delete()
    return JsonResponse({"success": True})


@crm_login_required
@require_POST
def segment_save(request):
    role = get_user_role(request.user)
    body = _body(request)
    name = (body.get("name") or "").strip()[:120]
    if not name:
        return _err("Segment name is required.")
    filters = body.get("filters") or {}
    if not isinstance(filters, dict):
        return _err("Invalid filters.")
    if Segment.objects.filter(name__iexact=name).exists():
        return _err("A segment with this name already exists.")
    seg = Segment.objects.create(
        name=name, description=(body.get("description") or "")[:255],
        filters=filters, created_by=request.user)
    return JsonResponse({"success": True, "segment": {"id": seg.id, "name": seg.name, "filters": seg.filters}})


@crm_login_required
@require_POST
def segment_delete(request, segment_id):
    role = get_user_role(request.user)
    seg = get_object_or_404(Segment, pk=segment_id)
    if not _is_manager(role) and seg.created_by_id != request.user.id:
        return _err("You can only delete segments you created.", 403)
    seg.delete()
    return JsonResponse({"success": True})


# =========================================================
# CONTACT ACTIONS  (tags, opt-out, import)
# =========================================================

@crm_login_required
@require_POST
def contacts_tag_apply(request):
    role = get_user_role(request.user)
    body = _body(request)
    sessions = _sessions_from_body(request, body, role)
    total = sessions.count()
    if total == 0:
        return _err("No contacts selected.")

    add_ids = eng._int_list(body.get("add"))
    remove_ids = eng._int_list(body.get("remove"))
    new_name = (body.get("new_tag") or "").strip()
    if new_name:
        tag = eng.get_or_create_tag(new_name, request.user)
        if tag:
            add_ids.append(tag.id)
    if not add_ids and not remove_ids:
        return _err("Choose a tag to add or remove.")

    add_tags = list(ContactTag.objects.filter(id__in=add_ids))
    remove_tags = list(ContactTag.objects.filter(id__in=remove_ids))
    through = ChatSession.tags.through
    ids = list(sessions.values_list("id", flat=True))

    for tag in add_tags:
        have = set(through.objects.filter(contacttag_id=tag.id, chatsession_id__in=ids)
                   .values_list("chatsession_id", flat=True))
        through.objects.bulk_create(
            [through(chatsession_id=i, contacttag_id=tag.id) for i in ids if i not in have],
            batch_size=500)
    for tag in remove_tags:
        through.objects.filter(contacttag_id=tag.id, chatsession_id__in=ids).delete()

    return JsonResponse({"success": True, "count": total})


@crm_login_required
@require_POST
def contacts_opt_out(request):
    role = get_user_role(request.user)
    body = _body(request)
    sessions = _sessions_from_body(request, body, role)
    n = eng.set_opt_out(sessions, bool(body.get("opted_out", True)))
    return JsonResponse({"success": True, "count": n})


@crm_login_required
@require_POST
def contacts_import(request):
    role = get_user_role(request.user)
    f = request.FILES.get("file")
    if not f:
        return _err("Please choose a file.")
    if request.POST.get("consent") != "true":
        return _err("Please confirm that these contacts have opted in to receive WhatsApp messages.")
    try:
        parsed = eng.parse_contacts_file(f)
    except ValueError as exc:
        return _err(str(exc))
    except Exception:
        return _err("Could not read this file. Please upload a .csv or .xlsx file.")
    if not parsed["rows"]:
        return _err("No valid phone numbers found in this file.")

    tag_names = [t.strip() for t in (request.POST.get("tags") or "").split(",") if t.strip()]
    result = eng.import_contacts(
        parsed["rows"], request.user, role, tag_names=tag_names,
        consent_text=f"Import confirmed by {request.user.username}")
    return JsonResponse({
        "success": True, **result,
        "invalid": len(parsed["invalid"]), "duplicates": parsed["duplicates"],
    })
