"""
Website call routing (2026-11-03).

The Call buttons on www.trypdeals.com keep showing the company number, but a
tap dials the agent on duty. The website reads the roster from
GET /api/call-roster/ and picks the agent itself: the active agents take
turns, one per rotation slot (CallSettings.rotation_minutes), round the clock;
a page category with its own CallRoute uses only its agents. Each tap is sent
to POST /api/call-click/ and saved as a CallLead.

/crm/calls/ is the call log: how many calls went to which agent, and the
list of calls. Agents, page routes and the rotation time are managed in
Django Admin (Call agents / Call routes / Call settings); admin.py clears the
roster cache on every change.

The website side is src/lib/callRouting.js in the Group Tours project.
"""
import json
import re
from datetime import datetime

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .crm_views import get_user_role, team_user_ids
from .decorators import crm_login_required
from .models import CALL_CATEGORY_CHOICES, CallAgent, CallLead, CallRoute, CallSettings

CATEGORIES = dict(CALL_CATEGORY_CHOICES)
ROSTER_CACHE_KEY = "call_roster_v1"
SITE_URL_RE = re.compile(r"^https?://(www\.trypdeals\.com|trypdeals\.com|localhost(:\d+)?|127\.0\.0\.1(:\d+)?)(/|$)")
CLICKS_PER_IP_HOUR = 40


def _cache(op, *args):
    """The cache is Redis; if Redis is down these endpoints still work, just
    without the cache (and without the per-IP limit)."""
    try:
        return getattr(cache, op)(*args)
    except Exception:
        return None


def build_roster():
    pick = lambda items: [{"id": a.id, "phone": a.phone} for a in items]
    routes = {}
    for route in CallRoute.objects.filter(is_active=True).prefetch_related("agents"):
        active = sorted((a for a in route.agents.all() if a.is_active), key=lambda a: (a.order, a.id))
        if active:
            routes[route.category] = pick(active)
    return {
        "rotationMinutes": CallSettings.get().rotation_minutes,
        "default": pick(CallAgent.objects.filter(is_active=True)),
        "routes": routes,
    }


def clear_roster_cache():
    _cache("delete", ROSTER_CACHE_KEY)


# ---------------------------------------------------------------------------
# Public endpoints used by the website
# ---------------------------------------------------------------------------

@require_GET
def call_roster(request):
    data = _cache("get", ROSTER_CACHE_KEY)
    if data is None:
        data = build_roster()
        _cache("set", ROSTER_CACHE_KEY, data, 60)
    resp = JsonResponse(data)
    resp["Cache-Control"] = "public, max-age=300"
    return resp


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None


@csrf_exempt
@require_POST
def call_click(request):
    """One tap on a website Call button. The page sends it with
    navigator.sendBeacon (text/plain JSON), so there is no CORS preflight."""
    ip = _client_ip(request)
    key = f"call_click_ip:{ip}"
    hits = _cache("get", key, 0) or 0
    if hits >= CLICKS_PER_IP_HOUR:
        return HttpResponse(status=429)
    _cache("set", key, hits + 1, 3600)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=400)
    page_url = str(body.get("url", ""))[:500]
    if not SITE_URL_RE.match(page_url):
        return HttpResponse(status=400)

    agent = None
    try:
        agent = CallAgent.objects.filter(pk=int(body.get("agentId"))).first()
    except (TypeError, ValueError):
        pass
    category = body.get("category") if body.get("category") in CATEGORIES else "other"
    referrer = str(body.get("referrer", ""))[:500]
    ua = request.META.get("HTTP_USER_AGENT", "")
    CallLead.objects.create(
        agent=agent,
        agent_name=agent.name if agent else "",
        agent_phone=agent.phone if agent else "",
        category=category,
        page_url=page_url,
        page_title=str(body.get("title", ""))[:300],
        referrer=referrer if referrer.startswith("http") else "",
        device="mobile" if re.search(r"Mobi|Android|iPhone", ua) else "desktop",
        visitor_id=re.sub(r"[^\w-]", "", str(body.get("visitor", "")))[:40],
        ip=ip,
    )
    return HttpResponse(status=204)


# ---------------------------------------------------------------------------
# CRM: call log
# ---------------------------------------------------------------------------

def _visible_calls(user):
    """Admin and managers see every call; a sales person (or team leader)
    sees the calls of the agents linked to them or their team."""
    qs = CallLead.objects.select_related("agent")
    if get_user_role(user) in ("admin", "manager"):
        return qs
    return qs.filter(agent__user_id__in=team_user_ids(user))


def _per_agent(qs):
    rows = qs.values("agent_name").annotate(n=Count("id")).order_by("-n")
    return [{"name": r["agent_name"] or "Company number", "n": r["n"]} for r in rows]


def clean_phone(value):
    """'+91 98765-43210' -> '9876543210', or '' if it is not an Indian mobile."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if re.match(r"^[6-9]\d{9}$", digits) else ""


@crm_login_required
@require_POST
def crm_call_customer(request, call_id):
    """The agent adds (or clears) the caller's number from their call log."""
    call = _visible_calls(request.user).filter(pk=call_id).first()
    if not call:
        return JsonResponse({"success": False, "error": "Call not found."}, status=404)
    try:
        raw = str(json.loads(request.body or "{}").get("customer_phone", "")).strip()
    except ValueError:
        return JsonResponse({"success": False, "error": "Bad request."}, status=400)
    phone = clean_phone(raw)
    if raw and not phone:
        return JsonResponse({"success": False, "error": "Please enter a 10-digit Indian mobile number."}, status=400)
    call.customer_phone = phone
    call.save(update_fields=["customer_phone"])
    return JsonResponse({"success": True, "customer_phone": phone})


@crm_login_required
def crm_calls(request):
    role = get_user_role(request.user)
    visible = _visible_calls(request.user)
    qs = visible

    start = request.GET.get("start", "")
    end = request.GET.get("end", "")
    agent_id = request.GET.get("agent", "")
    try:
        if start:
            qs = qs.filter(created_at__date__gte=datetime.strptime(start, "%Y-%m-%d").date())
        if end:
            qs = qs.filter(created_at__date__lte=datetime.strptime(end, "%Y-%m-%d").date())
    except ValueError:
        start = end = ""
    if agent_id == "none":
        qs = qs.filter(agent__isnull=True)
    elif agent_id.isdigit():
        qs = qs.filter(agent_id=int(agent_id))

    today_qs = visible.filter(created_at__date=timezone.localdate())
    page = Paginator(qs, 100).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "chatbot/crm/calls.html", {
        "page": page,
        "calls": page.object_list,
        "total": qs.count(),
        "per_agent": _per_agent(qs),
        "today_total": today_qs.count(),
        "today_per_agent": _per_agent(today_qs),
        "agents": CallAgent.objects.all(),
        "filtered": bool(start or end or agent_id),
        "f": {"start": start, "end": end, "agent": agent_id},
        "page_qs": params.urlencode(),
        "user_role": role,
        "is_admin": role in ("admin", "manager"),
    })
