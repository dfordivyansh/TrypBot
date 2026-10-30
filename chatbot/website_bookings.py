"""
Website bookings (www.trypdeals.com short tours + cabs with a PayU advance).

views.website_booking_webhook saves each booking on the customer's chat: in
session.data and, durably, in the raw_payload of a "system" ChatMessage
(session.data can be reset by "Plan New Trip"). The bot uses these helpers to
answer a customer who messages with their quotation code (TD-XXXXXX) and to
give the AI the booking as context.
"""
import re

BOOKING_CODE_RE = re.compile(r"\bTD-?([A-Z0-9]{6})\b", re.IGNORECASE)

STATUS_TEXT = {
    "pending": "payment pending (enquiry)",
    "paid": "advance PAID",
    "failed": "payment failed",
    "amount_mismatch": "paid, amount mismatch",
}

# How the advance status reads to the customer.
CUSTOMER_STATUS_TEXT = {
    "pending": "not paid yet",
    "paid": "received, thank you",
    "failed": "payment did not go through",
    "amount_mismatch": "received (our team will confirm the amount)",
}


def rs(n):
    try:
        return f"Rs. {int(n):,}"
    except (TypeError, ValueError):
        return ""


def code_in(message):
    """The TD-XXXXXX quotation code in a message, normalised, or None."""
    m = BOOKING_CODE_RE.search(message or "")
    return f"TD-{m.group(1).upper()}" if m else None


def summary_lines(b, for_customer=False):
    """Readable lines for a booking dict (CRM note, system message, bot reply)."""
    lines = []
    if b.get("type") == "cab":
        cab = b.get("cab") or {}
        route = " -> ".join(x for x in (cab.get("from"), cab.get("stops"), cab.get("to")) if x)
        lines.append(f"Cab: {route} ({cab.get('tripType') or 'Round Trip'})")
        if cab.get("vehicle"):
            lines.append(f"Vehicle: {cab['vehicle']}")
        lines.append(f"Pickup date: {b.get('travelDate') or '-'}" + (f", drop: {cab['dropDate']}" if cab.get("dropDate") else ""))
        kids = []
        if b.get("childrenPaid"):
            kids.append(f"{b['childrenPaid']} child(ren) 6+")
        if b.get("childrenFree"):
            kids.append(f"{b['childrenFree']} under 6")
        lines.append(f"Travellers: {b.get('adults') or 0} adult(s)" + (", " + ", ".join(kids) if kids else ""))
        if cab.get("fareEstimate"):
            lines.append(f"Estimated cab fare: {rs(cab['fareEstimate'])}*")
    else:
        tour = b.get("tour") or {}
        lines.append(f"Tour: {tour.get('title') or '-'}" + (f" ({tour['duration']})" if tour.get("duration") else ""))
        lines.append(f"Travel date: {b.get('travelDate') or '-'}")
        kids = []
        if b.get("childrenHalf"):
            kids.append(f"{b['childrenHalf']} child(ren) 6-8 yrs")
        if b.get("childrenFree"):
            kids.append(f"{b['childrenFree']} under 6")
        lines.append(f"Travellers: {b.get('adults') or 0} adult(s)" + (", " + ", ".join(kids) if kids else ""))
        est = b.get("estimate") or {}
        if est.get("total"):
            rate = f" ({est['tierLabel']} rate {rs(est.get('perPerson'))} per person)" if est.get("tierLabel") else ""
            lines.append(f"Estimated package cost: {rs(est['total'])}*{rate}")
    status = b.get("paymentStatus") or "pending"
    status_text = (CUSTOMER_STATUS_TEXT if for_customer else STATUS_TEXT).get(status, status)
    lines.append(f"Advance: {rs(b.get('amount'))} - {status_text}")
    slug = (b.get("tour") or {}).get("slug")
    if slug:
        lines.append(f"Tour page: https://www.trypdeals.com/tours/{slug}/")
    return lines


ESTIMATE_NOTE = "*This total amount will be finalised after discussing the full requirements with you."


def find_booking(session=None, code=None):
    """The latest saved booking with this code (any chat), or this chat's latest booking."""
    from .models import ChatMessage

    if code and session is not None:
        b = ((session.data or {}).get("website_bookings") or {}).get(code)
        if b:
            return b
    qs = ChatMessage.objects.filter(sender_type="system", raw_payload__has_key="website_booking")
    if code:
        qs = qs.filter(raw_payload__website_booking__code=code)
    elif session is not None:
        qs = qs.filter(session=session)
    else:
        return None
    msg = qs.order_by("-created_at").first()
    if msg:
        return (msg.raw_payload or {}).get("website_booking")
    if session is not None and not code:
        return (session.data or {}).get("website_booking")
    return None


# The website's checkout function also answers server-to-server lookups by
# code (action "lookup", same shared key as the booking webhook). Used when a
# customer sends a code whose webhook never reached the CRM.
LOOKUP_URL = "https://asia-south1-group-tours-96e7a.cloudfunctions.net/bookingCheckout"


def fetch_remote_booking(code):
    """The booking from the website by code, saved into the CRM; None if not found."""
    # requests (certifi CA bundle), not urllib: on the EC2 Windows server the
    # system store lacks Google's root and urllib failed CERTIFICATE_VERIFY_FAILED.
    import requests
    from django.conf import settings

    key = getattr(settings, "WEBSITE_BOOKING_WEBHOOK_KEY", "")
    if not code:
        return None
    if not key:
        print(f"[BOOKING LOOKUP] {code}: WEBSITE_BOOKING_WEBHOOK_KEY missing in .env")
        return None
    booking = None
    # Two tries: the website function can be slow to wake up or drop a request.
    for attempt in (1, 2):
        try:
            res = requests.post(LOOKUP_URL, json={"action": "lookup", "code": code},
                                headers={"X-Webhook-Key": key}, timeout=20)
            if res.status_code == 200:
                booking = res.json().get("booking")
                break
            print(f"[BOOKING LOOKUP] {code}: HTTP {res.status_code} (try {attempt})")
            if res.status_code in (400, 403, 404):
                return None
        except Exception as exc:
            print(f"[BOOKING LOOKUP] {code}: {exc} (try {attempt})")
    else:
        return None
    if not booking or booking.get("code") != code:
        return None
    try:
        save_booking(booking)
    except Exception as exc:
        print(f"[BOOKING LOOKUP] could not save {code}: {exc}")
    return booking


def requirement_questions(b):
    """One or two questions that collect what the team still needs for this booking."""
    if b.get("type") == "cab":
        cab = b.get("cab") or {}
        qs = ["What is the exact pickup address and your preferred pickup time?"]
        if not cab.get("vehicle"):
            qs.append("Do you have a vehicle preference (sedan, SUV like Innova, or Tempo Traveller), and how much luggage will you carry?")
        else:
            qs.append("Would you like any stops or sightseeing on the way?")
        return qs
    return [
        "Which city will you start from, and where should we pick you up (railway station, airport or hotel)?",
        "Any hotel preference or special requirement (senior citizens, extra bed, food preference)?",
    ]


def booking_context(b):
    """Short text for the AI prompt."""
    if not b:
        return ""
    return f"Quotation code {b.get('code')}\n" + "\n".join(summary_lines(b, for_customer=True))


def save_booking(b):
    """
    Save a website booking on the customer's chat (found or created by mobile
    number, the key WhatsApp uses): session data + CRM card, Lead fields, and
    a system message / internal note when the booking is new or its payment
    status changed. Returns (session, lead, first_time, status).
    Used by views.website_booking_webhook and by the bot's code lookup.
    """
    from django.db import transaction
    from django.db.models import Q as models_Q
    from django.utils import timezone
    from .models import ChatMessage, ChatSession, Lead

    code = str(b.get("code") or "").strip()
    from .campaign_engine import normalize_phone
    from .models import InternalNote
    phone = normalize_phone(b.get("mobile")) or ""
    name = str(b.get("name") or "").strip()[:255]
    email = str(b.get("email") or "").strip()[:254]
    status = str(b.get("paymentStatus") or "pending")
    is_cab = b.get("type") == "cab"
    what = (f"Cab {(b.get('cab') or {}).get('from', '')} to {(b.get('cab') or {}).get('to', '')}"
            if is_cab else (b.get("tour") or {}).get("title") or "Tour")
    summary = summary_lines(b)

    with transaction.atomic():
        session = None
        if phone:
            # WhatsApp chats use the bare number as session_id; reuse that
            # chat (or a CRM chat with this number) so the booking and the
            # customer's WhatsApp messages land in one place.
            session = (ChatSession.objects.select_for_update()
                       .filter(models_Q(session_id=phone) | models_Q(phone_number=phone))
                       .order_by("-updated_at").first())
        if session is None:
            session = ChatSession(
                session_id=phone or "",
                phone_number=phone,
                user_name=name or phone or "Website Booking",
                step=1,
                data={},
                is_active=True,
            )
        elif name and (not session.user_name or session.user_name == session.phone_number):
            session.user_name = name

        data = session.data if isinstance(session.data, dict) else {}
        bookings = data.get("website_bookings") or {}
        previous = bookings.get(code) or {}
        first_time = not previous
        status_changed = previous.get("paymentStatus") != status

        record = {**b, "received_at": timezone.now().isoformat()}
        bookings[code] = record
        data["website_bookings"] = bookings
        data["website_booking"] = record  # the latest one, for the bot
        # Shown on the CRM chat page with the ad lead-form cards.
        data["website_booking_card"] = {
            "campaign_name": f"{code} - {what}",
            "received_at": record["received_at"],
            "answers": {line.split(":", 1)[0]: line.split(":", 1)[1].strip() for line in summary if ":" in line},
        }
        from .crm_helpers import _tour_days
        tour = b.get("tour") or {}
        days = None if is_cab else _tour_days(tour.get("duration"), tour.get("title"), tour.get("slug"))
        data["lead_category"] = "cab" if is_cab else (f"tour_{days}day" if days else "personal_tour")
        if not is_cab and (b.get("tour") or {}).get("title"):
            session.current_package = (b["tour"]["title"])[:255]
        dest = ((b.get("cab") or {}).get("to") if is_cab else (b.get("tour") or {}).get("title")) or ""
        if dest:
            session.current_destination = dest[:255]
        session.data = data
        session.save()

        lead, lead_created = Lead.objects.get_or_create(
            session=session,
            defaults={"phone": phone, "source": "website", "status": "new", "priority": "medium"},
        )
        lead.full_name = name or lead.full_name
        lead.phone = phone or lead.phone
        lead.email = email or lead.email
        lead.destination = dest[:255] or lead.destination
        lead.travel_date = str(b.get("travelDate") or "")[:255] or lead.travel_date
        lead.travellers = int(b.get("travellers") or b.get("adults") or lead.travellers or 1)
        if is_cab:
            lead.departure_city = ((b.get("cab") or {}).get("from") or "")[:255] or lead.departure_city
        est_total = (b.get("estimate") or {}).get("total") or (b.get("cab") or {}).get("fareEstimate")
        if est_total:
            lead.budget = rs(est_total)
        if lead_created:
            lead.source = "website"
        if status == "paid":
            lead.priority = "high"
        note_line = f"Website booking {code} ({what}): {STATUS_TEXT.get(status, status)}"
        if note_line not in (lead.notes or ""):
            lead.notes = (f"{lead.notes}\n{note_line}" if lead.notes else note_line)[:5000]
        lead.save()

        if first_time or status_changed:
            title = ("New website booking" if first_time else "Website booking update") + f" {code}"
            text = title + "\n" + "\n".join(summary)
            ChatMessage.objects.create(session=session, sender_type="system", message=text,
                                       raw_payload={"website_booking": record})
            InternalNote.objects.create(session=session, added_by=None, note=text)
            session.last_message = f"{title}: {STATUS_TEXT.get(status, status)}"
            session.unread_count = (session.unread_count or 0) + 1
            session.save(update_fields=["last_message", "unread_count", "updated_at"])

    return session, lead, first_time, status


# ---------------------------------------------------------------------------
# Website enquiries (cab, route trip plan, small tour, website chat) posted by
# the website's Firebase functions to views.website_enquiry_webhook. Only big
# tour packages are still emailed to info@; everything else lands here.
# ---------------------------------------------------------------------------

ENQUIRY_KINDS = {
    "cab": "Cab Enquiry",
    "route": "Route Trip Enquiry",
    "tour": "Tour Enquiry",
    "personal": "Personal Tour Enquiry",
    "chat": "Website Chat Lead",
}


def save_enquiry(e):
    """
    Save a website enquiry on the customer's chat (found or created by mobile
    number): CRM card, Lead fields, a system message and an internal note.
    The same enquiry id twice is saved once. Returns (session, lead, first_time).
    """
    from django.db import transaction
    from django.db.models import Q as models_Q
    from django.utils import timezone
    from .campaign_engine import normalize_phone
    from .models import ChatMessage, ChatSession, InternalNote, Lead

    eid = str(e.get("id") or "").strip()[:100]
    kind = e.get("kind") if e.get("kind") in ENQUIRY_KINDS else "tour"
    kind_label = ENQUIRY_KINDS[kind]
    phone = normalize_phone(e.get("mobile")) or ""
    name = str(e.get("name") or "").strip()[:255]
    email = str(e.get("email") or "").strip()[:254]
    title = str(e.get("title") or kind_label).strip()[:200]
    rows = [(str(k), str(v)) for k, v in (e.get("rows") or []) if v not in (None, "")]

    with transaction.atomic():
        session = None
        if phone:
            session = (ChatSession.objects.select_for_update()
                       .filter(models_Q(session_id=phone) | models_Q(phone_number=phone))
                       .order_by("-updated_at").first())
        if session is None:
            session = ChatSession(session_id=phone or f"web-{eid}", phone_number=phone,
                                  user_name=name or phone or kind_label, step=1, data={}, is_active=True)
        elif name and (not session.user_name or session.user_name == session.phone_number):
            session.user_name = name

        data = session.data if isinstance(session.data, dict) else {}
        seen = data.get("website_enquiries") or []
        first_time = eid not in seen
        if first_time and eid:
            data["website_enquiries"] = (seen + [eid])[-50:]
        received_at = timezone.now().isoformat()
        data["website_enquiry_card"] = {
            "campaign_name": f"{kind_label} - {title}",
            "received_at": received_at,
            "answers": dict(rows),
        }
        from .crm_helpers import _tour_days
        if kind in ("cab", "route"):
            data["lead_category"] = kind
        elif kind == "tour":
            days = _tour_days(title, e.get("page"))
            data["lead_category"] = f"tour_{days}day" if days else "personal_tour"
        else:
            data["lead_category"] = "personal_tour"
        dest = str(e.get("to") or "")[:255]
        if dest:
            session.current_destination = dest
        session.data = data
        session.save()

        lead, created = Lead.objects.get_or_create(
            session=session,
            defaults={"phone": phone, "source": "website", "status": "new", "priority": "medium"},
        )
        lead.full_name = name or lead.full_name
        lead.phone = phone or lead.phone
        lead.email = email or lead.email
        lead.destination = dest or lead.destination
        if e.get("from"):
            lead.departure_city = str(e["from"])[:255]
        if e.get("travelDate"):
            lead.travel_date = str(e["travelDate"])[:255]
        try:
            n = int(str(e.get("travellers") or "").split("-")[0].rstrip("+"))
            lead.travellers = n or lead.travellers
        except (TypeError, ValueError):
            pass
        note_line = f"{kind_label}: {title}"
        if note_line not in (lead.notes or ""):
            lead.notes = (f"{lead.notes}\n{note_line}" if lead.notes else note_line)[:5000]
        lead.save()

        if first_time:
            text = f"New {kind_label} from the website\n{title}\n" + "\n".join(f"{k}: {v}" for k, v in rows)
            if e.get("page"):
                text += f"\nPage: https://www.trypdeals.com{e['page']}"
            ChatMessage.objects.create(session=session, sender_type="system", message=text,
                                       raw_payload={"website_enquiry": {**e, "received_at": received_at}})
            InternalNote.objects.create(session=session, added_by=None,
                                        note=text + (f"\n\n{e['transcript']}"[:4000] if e.get("transcript") else ""))
            session.last_message = f"New {kind_label}: {title}"[:500]
            session.unread_count = (session.unread_count or 0) + 1
            session.save(update_fields=["last_message", "unread_count", "updated_at"])

    return session, lead, first_time
