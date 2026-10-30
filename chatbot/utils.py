"""
TrypDeals Travel Bot — utils.py  v18.1.0
=========================================

Company: TrypDeals Tech Labs Pvt. Ltd.
Address: FF 16, One Mart Mall, Sector 6, Vasundhara, Ghaziabad - 201012

CHANGES IN v18.1.0 (over v18.0.0):

  RAW MESSAGE EXTRACTION:
    - Added extract_travel_details() to parse destination, days, and expected date from user messages
    - Added ask_missing_travel_details() to prompt user for missing information
    - Added generate_travel_summary() to create handoff summary from extracted details
    - Modified chat flow to handle raw message extraction when form not filled

CHANGES IN v18.0.0 (over v17.7.0):

  FLOW REDESIGN — TWO PATHS ONLY:

  PATH A — BEST SELLER DESTINATIONS:
    1. User mentions a best-seller destination.
    2. Bot sends the teaser card (STAGE_BEST_SELLER_SENT).
    3. Bot IMMEDIATELY follows with the full pre-written itinerary.
    4. Three options presented: "Send Full Itinerary" | "Modify" | "Talk to Expert"
       - "Send Full Itinerary" → re-sends the full itinerary (already displayed).
       - "Modify" → sends the Basic Travel Flow form; when user submits the
         form the bot replies with a handoff message (details shared with agent)
         and marks the lead FOLLOW UP. NO itinerary is generated.
       - "Talk to Expert" → immediate lead handoff, mark FOLLOW UP.

  PATH B — ALL OTHER DESTINATIONS:
    1. User mentions any non-best-seller Indian destination.
    2. Bot confirms destination and sends the Basic Travel Flow form.
    3. When user submits the form → bot replies with a handoff message
       (details shared with agent) and marks the lead FOLLOW UP.
    4. NO itinerary is generated for non-best-seller destinations.

  REMOVED:
    - AI itinerary generation for non-best-seller destinations.
    - Package selection stage for non-best-seller destinations.
    - Day-wise custom flow for non-best-seller destinations.
    - Group tour flow routing (now goes straight to agent handoff).
    - STAGE_PACKAGE, STAGE_CUSTOM_FLOW_SENT, STAGE_ITINERARY_REVIEW (for
      non-best-seller), STAGE_TICKET_CHECK, STAGE_POST_ITINERARY no longer
      used as intermediate stages for new conversations; retained as constants
      for backward compatibility with existing sessions.
"""

from .models import Lead, FAQ, Package, ChatMessage
import re
import json
import random
import logging
from difflib import get_close_matches
from openai import OpenAI
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
from .crm_helpers import mark_lead_today

logger = logging.getLogger("trypdeals.utils")

# ─────────────────────────────────────────────────────────────────────────────
# RAW MESSAGE TRAVEL DETAIL EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def extract_travel_details(message: str) -> dict:
    """
    Extract destination, days, and expected date from user message using regex patterns.
    Returns dict with keys: destination, days, expected_date
    """
    msg_lower = message.lower()
    result = {
        "destination": None,
        "days": None,
        "expected_date": None
    }
    
    # Extract destination (Indian cities/states)
    indian_destinations = [
        "goa", "kerala", "rajasthan", "jaipur", "udaipur", "jaisalmer", "jodhpur",
        "delhi", "agra", "varanasi", "lucknow", "rishikesh", "haridwar",
        "mumbai", "pune", "maharashtra", "lonavala", "mahabaleshwar",
        "bangalore", "mysore", "coorg", "chikmagalur", "karnataka",
        "chennai", "tamil nadu", "pondicherry", "ooty", "kodaikanal",
        "hyderabad", "telangana", "warangal",
        "kolkata", "darjeeling", "gangtok", "sikkim", "west bengal",
        "gujarat", "ahmedabad", "kutch", "gir", "somnath",
        "himachal", "shimla", "manali", "dharamshala", "spiti", "kullu",
        "jammu", "kashmir", "srinagar", "gulmarg", "pahalgam", "ladakh", "leh",
        "andaman", "port blair", "havelock", "neil island",
        "meghalaya", "shillong", "cherrapunji", "assam", "kaziranga",
        "madhya pradesh", "bhopal", "khajuraho", "orchha", "pachmarhi",
        "odisha", "puri", "konark", "bhubaneswar",
        "karnataka", "hampi", "badami", "gokarna",
        "uttarakhand", "nainital", "mussoorie", "dehradun", "auli"
    ]
    
    for dest in indian_destinations:
        if dest in msg_lower:
            result["destination"] = dest.title()
            break
    
    # Extract number of days
    days_patterns = [
        r'(\d+)\s*days?',
        r'(\d+)\s*day',
        r'for\s+(\d+)\s*days?',
        r'(\d+)\s*nights?',
    ]
    
    for pattern in days_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            result["days"] = int(match.group(1))
            break
    
    # Extract expected date
    date_patterns = [
        r'on\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
        r'on\s+(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4})',
        r'by\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
        r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            result["expected_date"] = match.group(1)
            break
    
    return result


def ask_missing_travel_details(extracted: dict) -> str:
    """
    Generate a message asking for missing travel details.
    """
    missing = []
    if not extracted.get("destination"):
        missing.append("destination")
    if not extracted.get("days"):
        missing.append("number of days")
    if not extracted.get("expected_date"):
        missing.append("expected travel date")
    
    if not missing:
        return None
    
    if len(missing) == 1:
        return f"Please provide your {missing[0]}."
    elif len(missing) == 2:
        return f"Please provide your {missing[0]} and {missing[1]}."
    else:
        return f"Please provide your {', '.join(missing[:-1])}, and {missing[-1]}."


def generate_travel_summary(session, extracted: dict) -> str:
    """
    Generate a handoff summary message from extracted travel details.
    """
    destination = extracted.get("destination", "Unknown")
    days = extracted.get("days", "Not specified")
    expected_date = extracted.get("expected_date", "Not specified")
    name = session.data.get("_name", session.user_name or "WhatsApp User")
    
    summary = (
        f"Thank you for sharing your travel details!\n\n"
        f"Here's a summary of your trip:\n"
        f"• Destination: {destination}\n"
        f"• Duration: {days} days\n"
        f"• Expected Travel Date: {expected_date}\n\n"
        f"Our travel expert will contact you shortly to assist with your booking."
    )
    
    return summary


def handle_raw_travel_message(session, message: str) -> dict:
    """
    Handle raw user messages to extract travel details and transfer lead.
    This is used when user doesn't fill the form but provides details in chat.
    """
    data = session.data
    extracted = extract_travel_details(message)
    
    # Check if we have enough information
    missing_prompt = ask_missing_travel_details(extracted)
    if missing_prompt:
        # Ask for missing details
        return {
            "message": missing_prompt,
            "options": []
        }
    
    # We have all details - process the lead
    logger.info(f"[RAW TRAVEL MESSAGE] Extracted details: {extracted}")
    
    # Update session data with extracted details
    data.update({
        "destination": extracted.get("destination"),
        "days": extracted.get("days"),
        "expected_date": extracted.get("expected_date"),
    })
    session.data = data
    
    # Removed mark_lead_new_lead - only using mark_lead_today for conversational flow
    
    # Create travel request record
    try:
        _create_travel_request(
            session,
            {
                "destination": extracted.get("destination", ""),
                "days": extracted.get("days"),
                "days_raw": str(extracted.get("days", "")),
                "adults": 1,  # Default to 1 adult
                "children_count": 0,
                "children_ages": [],
                "special_notes": "Details extracted from chat message",
                "name": data.get("_name", session.user_name or "WhatsApp User"),
            },
            {"message": message, "source": "raw_chat_extraction"}
        )
    except Exception as e:
        logger.error(f"[RAW TRAVEL MESSAGE] _create_travel_request failed: {e}")
    
    # Create/update lead record
    try:
        Lead.objects.get_or_create(
            session=session,
            defaults={
                "name": data.get("_name", session.user_name or "WhatsApp User"),
                "phone": session.phone_number or "",
                "destination": extracted.get("destination", "Unknown"),
            },
        )
    except Exception as e:
        logger.error(f"[RAW TRAVEL MESSAGE] Lead creation failed: {e}")
    
    # Generate and send summary message
    summary_msg = generate_travel_summary(session, extracted)
    
    # Move to STAGE_CHAT and enable human takeover
    data["stage"] = STAGE_CHAT
    data["_expert_contacted"] = True
    data["_followup_stopped"] = True
    session.data = data
    session.step = STAGE_CHAT
    session.is_human_takeover = True
    _save_session(session)
    
    logger.info(f"[RAW TRAVEL MESSAGE] Lead transferred to agent, stage → STAGE_CHAT")
    
    return {
        "message": summary_msg,
        "options": ["Plan New Trip"],
        "social_card": SOCIAL_CARD,
    }


CURRENT_YEAR = datetime.now().year

# ─────────────────────────────────────────────────────────────────────────────
# COMPANY IDENTITY
# ─────────────────────────────────────────────────────────────────────────────

COMPANY_NAME    = "TrypDeals Tech Labs Pvt. Ltd."
COMPANY_SHORT   = "TrypDeals"
COMPANY_ADDRESS = "FF 16, One Mart Mall, Sector 6, Vasundhara, Ghaziabad - 201012"
PAYMENT_LINK    = "https://u.payu.in/OrASiub3Iwk9"

# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP FLOW IDs
# ─────────────────────────────────────────────────────────────────────────────

FLOW_BASIC_TRAVEL = "1245269247547202"
FLOW_GROUP_DATE   = "1678629570100298"
FLOW_DAYWISE_3    = "2078491493069421"
FLOW_DAYWISE_4    = "2597095570807811"
FLOW_DAYWISE_5    = "1021696370251955"
FLOW_DAYWISE_6    = "1904753046904418"

DAYWISE_FLOW_MAP = {
    3: FLOW_DAYWISE_3,
    4: FLOW_DAYWISE_4,
    5: FLOW_DAYWISE_5,
    6: FLOW_DAYWISE_6,
}

FLOW_ID_TO_DAYS = {v: k for k, v in DAYWISE_FLOW_MAP.items()}

FLOW_SCREEN_IDS = {
    FLOW_BASIC_TRAVEL: "FLOW_BASIC_TRAVEL",
    FLOW_GROUP_DATE:   "GROUP_DATE_PICKER",
    FLOW_DAYWISE_3:    "CUSTOM_ITINERARY_ONE",
    FLOW_DAYWISE_4:    "CUSTOM_ITINERARY_TWO",
    FLOW_DAYWISE_5:    "CUSTOM_ITINERARY_THREE",
    FLOW_DAYWISE_6:    "CUSTOM_ITINERARY_SIX",
}

FLOW_NAMES = {
    FLOW_BASIC_TRAVEL: "FLOW_BASIC_TRAVEL",
    FLOW_GROUP_DATE:   "FLOW_GROUP_DATE",
    FLOW_DAYWISE_3:    "FLOW_DAYWISE_3",
    FLOW_DAYWISE_4:    "FLOW_DAYWISE_4",
    FLOW_DAYWISE_5:    "FLOW_DAYWISE_5",
    FLOW_DAYWISE_6:    "FLOW_DAYWISE_6",
}

# ─────────────────────────────────────────────────────────────────────────────
# DEEPSEEK SETUP
# ─────────────────────────────────────────────────────────────────────────────

DEEPSEEK_MODEL = "deepseek-v4-flash"

_deepseek_client = OpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
    timeout=45.0,
    max_retries=1,
)


def _deepseek(prompt: str) -> str:
    try:
        response = _deepseek_client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"[DEEPSEEK ERROR] {e}")
        return ""


def _strip_markdown(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s]*[•✓➡►▶▸▹◆◇→]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s]*[*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# STAGE CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

STAGE_IDLE               = 10
STAGE_DESTINATION        = 9
STAGE_FLOW_SENT          = 11
STAGE_BEST_SELLER_SENT   = 15
STAGE_GROUP_TOUR_CHOICE  = 12
STAGE_GROUP_TOUR_DATE    = 13
STAGE_PACKAGE            = 20
STAGE_CUSTOM_FLOW_SENT   = 21
STAGE_ITINERARY_REVIEW   = 23
STAGE_MODIFY             = 31
STAGE_TICKET_CHECK       = 29
STAGE_POST_ITINERARY     = 25
STAGE_CHAT               = 99
STAGE_LEAD_HANDOFF       = 201
# Conversational 3-question flow stages
STAGE_CONV_DESTINATION   = 50
STAGE_CONV_SERIOUSNESS   = 51
STAGE_CONV_DATE          = 52
STAGE_CONV_PERSONS       = 53

# Main menu ("Hi"): Book a Tour / Cab Enquiry / My Booking
STAGE_MENU               = 64
STAGE_CAB_FROM           = 60
STAGE_CAB_TO             = 61
STAGE_CAB_PAX            = 62
STAGE_BOOKING_ID         = 63

STAGE_NAMES = {
    STAGE_IDLE:             "STAGE_IDLE",
    STAGE_DESTINATION:      "STAGE_DESTINATION",
    STAGE_FLOW_SENT:        "STAGE_FLOW_SENT",
    STAGE_BEST_SELLER_SENT: "STAGE_BEST_SELLER_SENT",
    STAGE_GROUP_TOUR_CHOICE:"STAGE_GROUP_TOUR_CHOICE",
    STAGE_GROUP_TOUR_DATE:  "STAGE_GROUP_TOUR_DATE",
    STAGE_PACKAGE:          "STAGE_PACKAGE",
    STAGE_CUSTOM_FLOW_SENT: "STAGE_CUSTOM_FLOW_SENT",
    STAGE_ITINERARY_REVIEW: "STAGE_ITINERARY_REVIEW",
    STAGE_MODIFY:           "STAGE_MODIFY",
    STAGE_TICKET_CHECK:     "STAGE_TICKET_CHECK",
    STAGE_POST_ITINERARY:   "STAGE_POST_ITINERARY",
    STAGE_CHAT:             "STAGE_CHAT",
    STAGE_LEAD_HANDOFF:     "STAGE_LEAD_HANDOFF",
    STAGE_CONV_DESTINATION: "STAGE_CONV_DESTINATION",
    STAGE_CONV_SERIOUSNESS: "STAGE_CONV_SERIOUSNESS",
    STAGE_CONV_DATE:        "STAGE_CONV_DATE",
    STAGE_CONV_PERSONS:     "STAGE_CONV_PERSONS",
    STAGE_MENU:             "STAGE_MENU",
    STAGE_CAB_FROM:         "STAGE_CAB_FROM",
    STAGE_CAB_TO:           "STAGE_CAB_TO",
    STAGE_CAB_PAX:          "STAGE_CAB_PAX",
    STAGE_BOOKING_ID:       "STAGE_BOOKING_ID",
}

# Legacy aliases
STEP_IDLE                 = STAGE_IDLE
STEP_DESTINATION          = 1
STEP_DAYS                 = 6
STEP_PACKAGE_SELECTION    = STAGE_PACKAGE
STEP_TRAVELLERS           = 7
STEP_TRAVELLERS_CHILDREN  = 71
STEP_ITINERARY_REVIEW     = STAGE_ITINERARY_REVIEW
STEP_MODIFY_FREE          = STAGE_MODIFY
STEP_POST_ITINERARY       = STAGE_POST_ITINERARY
STEP_TICKET_CHECK         = STAGE_TICKET_CHECK
STEP_CITY                 = 2
STEP_CONFIRM              = 8
STEP_CUSTOMIZE            = 50
STEP_CHAT                 = STAGE_CHAT
STEP_LEAD_HANDOFF         = STAGE_LEAD_HANDOFF
STEP_MODIFY_CHOICE        = 26
STEP_MODIFY_DAYS          = 27
STEP_MODIFY_DESTINATION   = 28
STEP_MODIFY_DAY_WISE      = 30


def _stage_name(stage: int) -> str:
    return STAGE_NAMES.get(stage, f"UNKNOWN({stage})")


# ─────────────────────────────────────────────────────────────────────────────
# FLOW LOGGING HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _log_flow_dispatch(flow_id: str, flow_data: dict, session_data: dict,
                       current_stage: int, next_stage: int) -> None:
    logger.info(
        "[FLOW DISPATCH]\n"
        f"  CURRENT STAGE : {_stage_name(current_stage)}\n"
        f"  FLOW NAME     : {FLOW_NAMES.get(flow_id, flow_id)}\n"
        f"  FLOW DATA     : {json.dumps(flow_data, ensure_ascii=False)[:400]}\n"
        f"  SESSION DATA  : destination={session_data.get('confirmed_destination') or session_data.get('destination')}, "
        f"days={session_data.get('days')}, adults={session_data.get('adults')}, "
        f"tour_type={session_data.get('tour_type')}\n"
        f"  NEXT STAGE    : {_stage_name(next_stage)}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# GROUP TOUR MIN-DATE HELPER (21 days from today)
# ─────────────────────────────────────────────────────────────────────────────

def _min_group_tour_date() -> datetime:
    return datetime.utcnow() + timedelta(days=21)


def _min_group_tour_date_str() -> str:
    return _min_group_tour_date().strftime("%d %b %Y")


# ─────────────────────────────────────────────────────────────────────────────
# CRM MESSAGE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _save_flow_message_to_crm(session, parsed_payload: dict, flow_id: str) -> None:
    try:
        flow_name = FLOW_NAMES.get(flow_id, flow_id)
        lines = [f"[Form Submitted: {flow_name}]", ""]
        label_map = {
            "name":             "Name",
            "trip_days":        "Trip Duration",
            "adults":           "Adults",
            "children":         "Children",
            "child_ages":       "Child Ages",
            "special_notes":    "Special Notes",
            "departure_option": "Departure Option",
            "custom_date":      "Custom Date",
        }
        for key, value in parsed_payload.items():
            if value in (None, "", [], {}):
                continue
            day_match = re.match(r"^day(\d+)_(activity|stay)$", key)
            if day_match:
                day_num = day_match.group(1)
                field   = day_match.group(2).title()
                lines.append(f"Day {day_num} {field}: {value}")
            else:
                label = label_map.get(key, key.replace("_", " ").title())
                lines.append(f"{label}: {value}")
        message_text = "\n".join(lines).strip()
        if not message_text:
            return
        ChatMessage.objects.create(
            session=session,
            sender_type="user",
            message=message_text,
        )
        session.last_message  = f"[Form: {flow_name}]"
        session.updated_at    = timezone.now()
        session.unread_count  = (session.unread_count or 0) + 1
        session.save(update_fields=["last_message", "updated_at", "unread_count"])
    except Exception as exc:
        logger.error(f"[CRM FLOW MSG] Could not save flow message: {exc}")


def _save_bot_reply_to_crm(session, message_text: str, whatsapp_message_id: str = "") -> None:
    if not message_text or not message_text.strip():
        return
    try:
        # Some handlers save their reply themselves and generate_response
        # saves it again; keep one copy of the same text within a minute.
        if ChatMessage.objects.filter(
            session=session, sender_type="bot", message=message_text.strip(),
            created_at__gte=timezone.now() - timedelta(seconds=60),
        ).exists():
            return
        ChatMessage.objects.create(
            session=session,
            sender_type="bot",
            message=message_text.strip(),
            whatsapp_message_id=whatsapp_message_id,
            message_status="sent" if whatsapp_message_id else "sent",
        )
        preview = message_text.strip()[:120]
        session.last_message = preview
        session.updated_at   = timezone.now()
        session.save(update_fields=["last_message", "updated_at"])
    except Exception as exc:
        logger.error(f"[CRM BOT MSG] Could not save bot reply: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# BEST SELLER PACKAGES  (teaser cards — shown first)
# ─────────────────────────────────────────────────────────────────────────────

BEST_SELLER_PACKAGES = {
    "rameshwaram": {
        "title": "Madurai Rameshwaram Kanyakumari Tour — 4 Days",
        "body": (
            "Our most popular South India pilgrimage circuit.\n\n"
            "Day 1: Madurai — Meenakshi Amman Temple, Thirumalai Nayakkar Mahal\n"
            "Day 2: Rameshwaram — Ramanathaswamy Temple, Dhanushkodi Beach, APJ Memorial\n"
            "Day 3: Kanyakumari — Vivekananda Rock Memorial, Thiruvalluvar Statue\n"
            "Day 4: Kanyakumari sightseeing and departure\n\n"
            "Includes: 3 Nights 3 Star AC Hotels, Breakfast, Private AC Vehicle\n"
            "Starting from Rs. 9,000 per person (group of 4–5)"
        ),
    },
    "varanasi": {
        "title": "Ayodhya Varanasi Prayagraj Tour — 4 Days",
        "body": (
            "Our best seller for Uttar Pradesh spiritual travel.\n\n"
            "Day 1: Varanasi — Kashi Vishwanath, Ganga Aarti, Assi Ghat\n"
            "Day 2: Varanasi and Sarnath — Dhamek Stupa, Sarnath Museum\n"
            "Day 3: Prayagraj — Triveni Sangam, then transfer to Ayodhya\n"
            "Day 4: Ayodhya — Ram Janmabhoomi, Hanuman Garhi, Ram Ki Paidi\n\n"
            "Includes: 3 Nights 3 Star AC Hotels, Breakfast, Private AC Vehicle\n"
            "Starting from Rs. 10,000 per person (group of 4–5)"
        ),
    },
    "ayodhya": {
        "title": "Ayodhya Prayagraj Varanasi Tour — 4 Days",
        "body": (
            "Our best seller for Uttar Pradesh sacred sites.\n\n"
            "Day 1: Ayodhya — Ram Janmabhoomi, Hanuman Garhi, Guptar Ghat\n"
            "Day 2: Prayagraj — Triveni Sangam, then transfer to Varanasi\n"
            "Day 3: Varanasi and Sarnath — Sarnath, Dhamek Stupa\n"
            "Day 4: Varanasi — Kashi Vishwanath, Ganga Aarti, departure\n\n"
            "Includes: 3 Nights 3 Star AC Hotels, Breakfast, Private AC Vehicle\n"
            "Starting from Rs. 10,000 per person (group of 4–5)"
        ),
    },
    "nashik": {
        "title": "Maharashtra 3 Jyotirlinga Tour — 3 Days",
        "body": (
            "Cover Ghrishneshwar, Trimbakeshwar and Bhimashankar in one circuit.\n\n"
            "Day 1: Pune to Ghrishneshwar, Ellora Caves, night Aurangabad\n"
            "Day 2: Nashik Trimbakeshwar, Shirdi Sai Baba Temple\n"
            "Day 3: Shani Shingnapur, Bhimashankar, drop Pune\n\n"
            "Includes: 2 Nights 3 Star AC Hotels, Breakfast, Private AC Vehicle\n"
            "Starting from Rs. 7,000 per person (group of 4–7)"
        ),
    },
    "puri": {
        "title": "Bhubaneswar Puri Odisha Tour — 4 Days",
        "body": (
            "Best seller for Odisha — temples, sea and wildlife.\n\n"
            "Day 1: Bhubaneswar — Lingaraj Temple, Udayagiri Caves, Dhauli Stupa\n"
            "Day 2: Puri — Jagannath Temple, Puri Beach, Gundicha Temple\n"
            "Day 3: Chilika Lake — Dolphin sighting, boat safari\n"
            "Day 4: Konark Sun Temple, Chandrabhaga Beach, departure\n\n"
            "Includes: 3 Nights 3 Star AC Hotels, Breakfast, Private AC Vehicle\n"
            "Starting from Rs. 10,000 per person (group of 4–5)"
        ),
    },
    "ujjain": {
        "title": "Ujjain Omkareshwar Indore Tour — 3 Days",
        "body": (
            "Best seller for Madhya Pradesh Jyotirlinga circuit.\n\n"
            "Day 1: Ujjain — Mahakaleshwar Temple, Kal Bhairav, Ram Ghat\n"
            "Day 2: Omkareshwar — Jyotirlinga Temple, Narmada Ghat, then Indore\n"
            "Day 3: Indore — Rajwada Palace, Lal Bagh, departure\n\n"
            "Includes: 2 Nights 3 Star AC Hotels, Breakfast, Private AC Vehicle\n"
            "Starting from Rs. 7,900 per person (group of 4–5)"
        ),
    },
    "coorg": {
        "title": "Bangalore Mysore Coorg Tour — 4 Days",
        "body": (
            "Most booked Karnataka nature and heritage circuit.\n\n"
            "Day 1: Bangalore to Mysore — Palace, Chamundi Hill, Brindavan Gardens\n"
            "Day 2: Coorg — Dubare Elephant Camp, Raja Seat, Golden Temple\n"
            "Day 3: Coorg — Talacauvery, Bhagamandala, Abbey Falls, Madikeri Fort\n"
            "Day 4: Coorg to Bangalore drop\n\n"
            "Includes: 3 Nights 3 Star AC Hotels, Breakfast, Private AC Vehicle\n"
            "Starting from Rs. 11,120 per person (group of 4–8)"
        ),
    },
    "dwarka": {
        "title": "Dwarka Somnath Gujarat Tour — 4 Days",
        "body": (
            "Best seller for Gujarat pilgrimage and Gir wildlife.\n\n"
            "Day 1: Rajkot to Dwarka — Dwarkadhish Temple, Bet Dwarka, Nageshwar Jyotirlinga\n"
            "Day 2: Dwarka to Somnath via Porbandar — Kirti Mandir, Somnath Temple\n"
            "Day 3: Diu day trip — Diu Fort, Nagoa Beach, Gangeshwar Temple\n"
            "Day 4: Gir Safari, Junagadh, drop Rajkot\n\n"
            "Includes: 3 Nights Hotels, Breakfast, Private AC Vehicle\n"
            "Starting from Rs. 9,500 per person (group of 4–5)"
        ),
    },
    "gokarna": {
        "title": "Gokarna Murudeshwar Jog Falls Tour — 3 Days",
        "body": (
            "Best seller for Karnataka coastal and waterfall circuit.\n\n"
            "Day 1: Hubli to Gokarna — Om Beach, Kudle Beach, Mahabaleshwar Temple\n"
            "Day 2: Murudeshwar — Shiva Statue, Murudeshwar Temple, Beach\n"
            "Day 3: Jog Falls — Raja, Roarer, Rocket, Rani viewpoints — drop Hubli\n\n"
            "Includes: 2 Nights Hotels, Breakfast, Private AC Vehicle\n"
            "Starting from Rs. 7,200 per person (group of 4)"
        ),
    },
    "hampi": {
        "title": "Hospet Hampi Badami Aihole Pattadakal Tour — 3 Days",
        "body": (
            "Best seller for Karnataka heritage — UNESCO World Heritage sites.\n\n"
            "Day 1: Hospet to Hampi — Virupaksha Temple, Hampi Bazaar, Hemakuta Hill\n"
            "Day 2: Hampi — Vittala Temple, Stone Chariot, Lotus Mahal, Elephant Stables\n"
            "Day 3: Pattadakal, Aihole, Badami Cave Temples — drop Hospet\n\n"
            "Includes: 2 Nights Hotels, Breakfast, Private AC Vehicle\n"
            "Starting from Rs. 7,900 per person (group of 4–5)"
        ),
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# BEST SELLER FULL ITINERARIES
# ─────────────────────────────────────────────────────────────────────────────

BEST_SELLER_FULL_ITINERARIES = {
    "rameshwaram": """Madurai Rameshwaram Kanyakumari Tour Package 4 days 

Tour itinerary 

Day 1 – Madurai (150 km approx)

Morning 6.00 am pick up from Madurai. Drive through scenic temples and bustling city life. Check into hotel. Then proceed for sightseeing and visit below places.

• Meenakshi Amman Temple

• Thirumalai Nayakkar Mahal

• Gandhi Memorial Museum

Evening return to hotel. Night stay.


Day 2 – Madurai to Rameshwaram (175 km approx)

Morning drive to Rameshwaram passing through green fields and villages. Check into hotel. Then proceed for sightseeing and visit below places.

• Ramanathaswamy Temple

• Agni Theertham

• Panchmukhi Hanuman Temple

• Floating Stone

• Lakshman Theertham

Evening return to hotel. Night stay.


Day 3 – Rameshwaram to Kanyakumari (310 km approx)

Morning proceed for sightseeing and visit below places.

• Dhanushkodi Beach

• Dhanushkodi Ruins

• APJ Abdul Kalam Memorial

Till 4.00 pm sightseeing. Then drive to Kanyakumari passing through coastal roads, scenic beaches and small towns. Check into hotel. Night stay.


Day 4 – Kanyakumari to Madurai (245 km approx)

Morning proceed for sightseeing and visit below places.

• Vivekananda Rock Memorial

• Thiruvalluvar Statue

• Kanyakumari Temple

• Triveni Sangam

• Gandhi Mandapam

• Sunset View Point

Evening drive back to Madurai with enroute scenic views. Drop at Madurai by evening.


Hotel Names 3 star ac


Madurai – Hotel vani villa or similar


Rameshwaram – Hotel  wyt or similar


Kanyakumari – Hotel jeyam or similar


Package Price per person


For 2 adults – Rs. 15000 per person


For 3 adults – Rs. 12000 per person


For 4-5 adults – Rs. 9800 per person


For 6-10 adults – Rs. 8700 per person


For 11 -12 adults - Rs 7500 Per person 


Inclusions


Accommodation in 3 star ac hotels on double/triple sharing basis


Breakfast at hotel


All transfers and sightseeing by private ac vehicle as per group size


Driver charges, toll, parking, fuel, interstate taxes


Exclusions


Any train/flight/bus fare


Lunch, dinner, beverages


Monument entry charges, boating, guide charges


Personal expenses, tips, shopping


Anything not mentioned in inclusions


Payment Policy


20% advance at time of booking


30% on arrival at the time of tour start


50% in mid of the tour


Child Policy


Child up to 6 years: Free


Child 6 to 8 years: Half charge


Child above 8 years: Full charge


Cancellation Policy


10% or Rs. 3000 per person whichever is higher


25% cancellation between 45 to 30 days before departure


50% cancellation between 30 to 15 days before departure


75% cancellation between 15 to 5 days before departure


100% cancellation within 5 days of departure or no-show


Cancellation charges are as percentage of total tour cost.


For long weekend, holidays and festivals extra charges applicable.""",

    "varanasi": """Ayodhya Varanasi Uttar Pradesh Tour Package 4 Days

Day 1 Varanasi Arrival and Sightseeing

Pickup from Varanasi airport or railway station at 08:12 and proceed to hotel.
Check in and freshen up.
- Visit Kashi Vishwanath Temple
- Visit Bharat Mata Mandir
- Visit Durga Temple
- Visit Sankat Mochan Hanuman Temple
- Visit Tulsi Manas Mandir
- Visit New Vishwanath Temple (BHU)
- Visit Assi Ghat
- Visit Dashashwamedh Ghat
- Witness Evening Ganga Aarti
- Visit Manikarnika Ghat
Overnight stay at hotel in Varanasi.

Day 2 Varanasi and Sarnath Sightseeing

After breakfast proceed for sightseeing.
- Visit Sarnath
- Visit Dhamek Stupa
- Visit Chaukhandi Stupa
- Visit Mulagandha Kuti Vihar
- Visit Sarnath Museum
Return to Varanasi.
Free time for local market and ghats.
Optional evening Ganga Aarti.
Overnight stay at hotel in Varanasi.

Day 3 Varanasi to Prayagraj Sightseeing and Ayodhya Stay

After breakfast check out from hotel.
Drive to Prayagraj.
- Visit Triveni Sangam for holy dip if desired
- Visit Anand Bhavan
- Visit Hanuman Mandir
Proceed to Ayodhya.
Check in to hotel in Ayodhya.
Overnight stay at hotel in Ayodhya.

Day 4 Ayodhya Sightseeing and Departure

After breakfast check out from hotel.
- Visit Ram Janmabhoomi
- Visit Hanuman Garhi
- Visit Kanak Bhawan
- Visit Dashrath Mahal
- Visit Nageshwarnath Temple
- Visit Treta Ke Thakur
- Visit Ram Ki Paidi
- Visit Guptar Ghat
- Visit Mani Parvat
Drop at Ayodhya airport or railway station at 19:12.

SUGGESTED ACCOMMODATION

Varanasi Day 1 and Day 2: Treebo Hotel Saumendra Residency Kashi or similar
Ayodhya Day 3: Hotel Ramayana Suites or similar

PACKAGE COST PER PERSON

Rs. 14,000 per person for group of 2 persons
Rs. 12,000 per person for group of 3 persons
Rs. 10,000 per person for group of 4 to 5 persons
Rs. 9,000 per person for group of 6 to 7 persons
Rs. 7,500 per person for group of 8 to 12 persons

INCLUSIONS

Well appointed rooms in mentioned hotels
Daily breakfast
AC vehicle for transfers and sightseeing
Driver allowance, toll and parking
All applicable hotel taxes

EXCLUSIONS

Any meals other than breakfast
Any transport not mentioned
Entry tickets and boating charges
Tips, insurance and personal expenses
Delays due to natural or political reasons
Airfare or train fare
GST at 5 percent

PAYMENT POLICY

20 percent advance at time of booking
20 percent after hotel voucher
60 percent during tour in parts
For tours between 15 December to 2 January: 50 percent advance required

CHILD POLICY

Child up to 6 years: Free
Child 6 to 8 years: Half charge
Child above 8 years: Full charge

CANCELLATION POLICY

Minimum Rs. 3000 per person
25 percent between 45 to 30 days
50 percent between 30 to 15 days
75 percent between 15 to 5 days
100 percent within 5 days or no show

HOTEL POLICY

Check in time: 12 pm
Check out time: 11 am
Early check in subject to availability
Late check out extra charges applicable

VEHICLE POLICY

CNG, Petrol or Diesel vehicle as per availability
No guarantee of luggage carrier""",

    "ayodhya": """Ayodhya Varanasi Uttar Pradesh Tour Package 4 Days

Day 1 Ayodhya Arrival and Sightseeing

Pickup from Ayodhya Airport or Railway Station at 08:12 and proceed for sightseeing.
- Visit Ram Janmabhoomi
- Visit Hanuman Garhi
- Visit Kanak Bhawan
- Visit Dashrath Mahal
- Visit Nageshwarnath Temple
- Visit Treta Ke Thakur
- Visit Ram Ki Paidi
- Visit Guptar Ghat
- Visit Mani Parvat
Check in to hotel in Ayodhya.
Overnight stay at hotel in Ayodhya.

Day 2 Ayodhya to Prayagraj Sightseeing and Varanasi Stay

After breakfast check out from hotel.
Drive to Prayagraj.
- Visit Triveni Sangam for holy dip if desired
- Visit Anand Bhavan
- Visit Hanuman Mandir
Proceed to Varanasi.
Check in to hotel in Varanasi.
Overnight stay at hotel in Varanasi.

Day 3 Varanasi and Sarnath Sightseeing

After breakfast proceed for sightseeing.
- Visit Sarnath
- Visit Dhamek Stupa
- Visit Chaukhandi Stupa
- Visit Mulagandha Kuti Vihar
- Visit Sarnath Museum
Return to Varanasi.
Free time for local market and ghats.
Optional Evening Ganga Aarti.
Overnight stay at hotel in Varanasi.

Day 4 Varanasi Sightseeing and Departure

After breakfast check out from hotel.
- Visit Kashi Vishwanath Temple
- Visit Bharat Mata Mandir
- Visit Durga Temple
- Visit Sankat Mochan Hanuman Temple
- Visit Tulsi Manas Mandir
- Visit New Vishwanath Temple (BHU)
- Visit Assi Ghat
- Visit Dashashwamedh Ghat
- Witness Evening Ganga Aarti
- Visit Manikarnika Ghat
Drop at Varanasi Airport or Railway Station at 19:12.

SUGGESTED ACCOMMODATION

Ayodhya Day 1: Hotel Ramayana Suites or similar
Varanasi Day 2 and Day 3: Treebo Hotel Saumendra Residency Kashi or similar

PACKAGE COST PER PERSON

Rs. 14,000 per person for group of 2 persons
Rs. 12,000 per person for group of 3 persons
Rs. 10,000 per person for group of 4 to 5 persons
Rs. 9,000 per person for group of 6 to 7 persons
Rs. 7,500 per person for group of 8 to 12 persons

INCLUSIONS

Well appointed rooms in mentioned hotels
Daily breakfast
AC vehicle for transfers and sightseeing
Driver allowance, toll and parking
All applicable hotel taxes

EXCLUSIONS

Any meals other than breakfast
Any transport not mentioned
Entry tickets and boating charges
Tips, insurance and personal expenses
Delays due to natural or political reasons
Airfare or train fare
GST at 5 percent

PAYMENT POLICY

20 percent advance at time of booking
20 percent after hotel voucher
60 percent during tour in parts
For tours between 15 December to 2 January: 50 percent advance required

CHILD POLICY

Child up to 6 years: Free
Child 6 to 8 years: Half charge
Child above 8 years: Full charge

CANCELLATION POLICY

Minimum Rs. 3000 per person
25 percent between 45 to 30 days
50 percent between 30 to 15 days
75 percent between 15 to 5 days
100 percent within 5 days or no show

HOTEL POLICY

Check in time: 12 pm
Check out time: 11 am
Early check in subject to availability
Late check out extra charges applicable

VEHICLE POLICY

CNG, Petrol or Diesel vehicle as per availability
No guarantee of luggage carrier""",

    "nashik": """Maharashtra 3 Jyotirlinga Tour Package 3 Days

Day 1 Arrival Pune, Grishneshwar and Ellora, Transfer to Aurangabad

Pickup from Pune.
Proceed towards Grishneshwar Jyotirlinga Temple.
- Visit Grishneshwar Jyotirlinga Temple
- Explore the ancient Ellora Caves
Drive to Aurangabad.
Check in to your hotel in Aurangabad.
Overnight stay at hotel in Aurangabad.

Day 2 Aurangabad, Nashik, Trimbakeshwar and Transfer to Shirdi

Enjoy breakfast at the hotel.
Check out from the hotel.
Drive to Nashik.
- Visit Trimbakeshwar Jyotirlinga Temple
- Explore Nashik city attractions including Kalaram Temple, Sita Gufa, Panchavati and Godavari Ghat
Drive to Shirdi.
- Visit Shirdi Sai Baba Temple
Check in to your hotel in Shirdi.
Overnight stay at hotel in Shirdi.

Day 3 Shani Shingnapur, Bhimashankar and Departure

Enjoy breakfast at the hotel.
Check out from the hotel.
- Visit Shani Shingnapur Temple
Proceed towards Bhimashankar Jyotirlinga Temple.
- Visit Bhimashankar Jyotirlinga Temple
Begin your journey back to Pune.
Drop off at Pune by Night.

SUGGESTED ACCOMMODATION

Aurangabad Day 1: Hotel Great Annapurna or similar
Shirdi Day 2: Hotel Sai Shrushti or similar

FINAL PRICE

Rs. 11,000 per person for 2 members
Rs. 8,000 per person for 3 members
Rs. 7,000 per person for 4 to 7 members
Rs. 6,000 per person for 8 or more members

INCLUSIONS

Well appointed rooms in the above mentioned hotels
Daily breakfast in hotels
AC Vehicle for all the surface transfers and sightseeing
Drivers allowance, toll and parking
All applicable hotel taxes

EXCLUSIONS

Any meals other than those mentioned above
Any transportation which is not mentioned in the itinerary
Entrance fees to the amusement parks and boating charges
Any portage at Airport and Hotels, tips, insurance, beverages, mineral water, telephone charges and all items of personal nature
Any services not specifically mentioned in the inclusions
Expenses caused by the factors beyond our control like rail and flight delays, road blocks, vehicle mal-functions, political disturbances etc
Any Airfare or Train fare
GST at 5 percent

PAYMENT POLICY

20 percent advance at time of booking
20 percent after hotel booking voucher
60 percent during tour in parts
For tours between 15 December to 2 January: 50 percent advance required

CHILD POLICY

Child up to 6 years: Free
Child 6 to 8 years: Half charge
Child above 8 years: Full charge

CANCELLATION POLICY

Minimum Rs. 3000 cancellation charge per person
25 percent cancellation between 45 to 30 days before departure
50 percent cancellation between 30 to 15 days before departure
75 percent cancellation between 15 to 5 days before departure
100 percent cancellation within 5 days of departure or no show
Cancellation charges are calculated on total tour cost

HOTEL POLICY

Check in time: 12 pm
Check out time: 11 am
Early check in subject to availability and will incur additional charges depending on the check in time requested
Late check out subject to availability and may incur additional charges

VEHICLE POLICY

CNG or Petrol or Diesel vehicle will be provided depending on availability
No guarantee for providing vehicle carrier or luggage carrier attachment""",

    "puri": """Bhubaneswar Puri Odisha Tour Package 4 Days

Day 1 Arrival and Bhubaneswar Sightseeing

Pickup from Bhubaneswar airport or station at 07:00.
Proceed to hotel for check in and freshen up.
- Visit Lingaraj Temple
- Explore Udayagiri and Khandagiri Caves
- Visit Dhauli Shanti Stupa
- Discover the Odisha State Museum
Overnight stay at hotel in Bhubaneswar.

Day 2 Puri Sightseeing

After breakfast, check out from Bhubaneswar hotel and proceed to Puri.
Check in to Puri hotel and freshen up.
- Visit Jagannath Temple
- Relax at Puri Beach
- Explore Gundicha Temple
- Visit Swargadwar Beach
- Visit Loknath Temple
Overnight stay at hotel in Puri.

Day 3 Chilika Lake Excursion

After breakfast, proceed for a full day excursion to Chilika Lake (Satapada).
- Enjoy a boat ride on Chilika Lake
- Spot Irrawaddy Dolphins
- Visit the Sea Mouth (confluence of Chilika Lake and Bay of Bengal)
Return to Puri for overnight stay.

Day 4 Konark, Sakshi Gopal and Departure

After breakfast, check out from Puri hotel.
Proceed to Konark.
- Visit the Konark Sun Temple
- Relax at Chandrabhaga Beach
- Visit Ramachandi Temple
Proceed to Sakshi Gopal.
- Visit Sakshi Gopal Temple
- Visit Pipili Applique Village for local handicrafts
Drop off at Bhubaneswar airport or station by 19:00.

SUGGESTED ACCOMMODATION

Bhubaneswar Day 1: Itsy Hotel Siddhartha or similar
Puri Day 2 and Day 3: Hotel Kakkson Inn or similar

PACKAGE COST PER PERSON

Rs. 14,000 per person for group of 2 persons
Rs. 12,000 per person for group of 3 persons
Rs. 10,000 per person for group of 4 to 5 persons
Rs. 9,000 per person for group of 6 to 7 persons
Rs. 8,000 per person for group of 8 to 12 persons

INCLUSIONS

Well appointed rooms in the above mentioned hotels
Daily breakfast in hotels
AC Vehicle for all the surface transfers and sightseeing
Drivers allowance, toll and parking
All applicable hotel taxes

EXCLUSIONS

Any meals other than those mentioned above
Any transportation which is not mentioned in the itinerary
Entrance fees to the amusement parks and boating charges
Any portage at Airport and Hotels, tips, insurance, beverages, mineral water, telephone charges and all items of personal nature
Any services not specifically mentioned in the inclusions
Expenses caused by the factors beyond our control like rail and flight delays, road blocks, vehicle mal-functions, political disturbances etc
Any Airfare or Train fare
GST at 5 percent

PAYMENT POLICY

20 percent advance at time of booking
20 percent after hotel booking voucher
60 percent during tour in parts
For tours between 15 December to 2 January: 50 percent advance required

CHILD POLICY

Child up to 6 years: Free
Child 6 to 8 years: Half charge
Child above 8 years: Full charge

CANCELLATION POLICY

Minimum Rs. 3000 cancellation charge per person
25 percent cancellation between 45 to 30 days before departure
50 percent cancellation between 30 to 15 days before departure
75 percent cancellation between 15 to 5 days before departure
100 percent cancellation within 5 days of departure or no show
Cancellation charges are calculated on total tour cost

HOTEL POLICY

Check in time: 12 pm
Check out time: 11 am
Early check in subject to availability and will incur additional charges depending on the check in time requested
Late check out subject to availability and may incur additional charges

VEHICLE POLICY

CNG or Petrol or Diesel vehicle will be provided depending on availability
No guarantee for providing vehicle carrier or luggage carrier attachment""",

    "ujjain": """Ujjain Omkareshwar Indore Tour Package 3 Days

Day 1 Arrival Ujjain

Pick up from Ujjain railway station and check in to hotel.
Proceed for sightseeing and visit:
- Mahakaleshwar Temple
- Harsiddhi Temple
- Kal Bhairav Temple
- Ram Ghat
- Sandipani Ashram
- Bade Ganeshji Ka Mandir
Evening free for local market visit.
Overnight stay at Ujjain.

Day 2 Ujjain to Omkareshwar to Indore

After breakfast proceed to Omkareshwar. Sightseeing includes:
- Omkareshwar Jyotirlinga Temple
- Mamleshwar Temple
- Narmada Ghat
- Boating in Narmada River
- Siddhanath Temple
Later drive to Indore.
On arrival, check in to hotel.
Evening visit:
- Sarafa Bazaar (for street food and local shopping)
Overnight stay at Indore.

Day 3 Indore Sightseeing and Departure

After breakfast proceed for Indore sightseeing and visit:
- Rajwada Palace
- Lal Bagh Palace
- Khajrana Ganesh Temple
- Central Museum
- Annapurna Temple
- Chappan Dukan (for local snacks)
Later transfer to Indore railway station or airport for onward journey.
Tour ends.

SUGGESTED ACCOMMODATION

Ujjain 1 Night: Hotel Sindur or similar
Indore 1 Night: Hotel D9 or similar

PACKAGE COST PER PERSON

Rs. 10,600 per person for group of 2 persons
Rs. 8,700 per person for group of 3 persons
Rs. 7,900 per person for group of 4 to 5 persons
Rs. 7,100 per person for group of 6 to 7 persons
Rs. 5,600 per person for group of 12 persons

INCLUSIONS

Well appointed rooms in above mentioned hotels
Daily breakfast in hotels
AC vehicle for all transfers and sightseeing with driver allowance, toll and parking
All applicable hotel taxes
GST at 5 percent

EXCLUSIONS

Meals other than those mentioned
Entrance fees and boating charges
Portage, tips, insurance, beverages, mineral water, telephone charges and personal expenses
Any services not specifically mentioned in inclusions
Expenses due to delays, road blocks, strikes etc
Airfare or Train fare

CHILD POLICY

Child below 4 years: Complimentary
Child 5 to 6 years: 50 percent of package cost
Child above 6 years: Treated as adult

CANCELLATION POLICY

10 percent or Rs. 3000 per person whichever higher
25 percent between 45 to 30 days before departure
50 percent between 30 to 15 days before departure
75 percent between 15 to 5 days before departure
100 percent within 5 days or no show""",

    "coorg": """Bangalore Mysore Coorg Tour Package 4 Days

Day 1 Bangalore Arrival to Mysore Sightseeing and Stay

Morning pickup from Bangalore and proceed for Mysore for todays sightseeing.
On arrival visit following places:
- Srirangapatna
- Dariya Daulat Bagh
- Gumbaz
- Tipu Fort
- Sri Ranganathaswamy Temple
- Mysore Palace
- Chamundi Hill
- Mysore Zoo
- Nandi Statue Big Bull
- St Philomena Church
- Jaganmohan Palace
- Brindavan Gardens
Evening check into hotel and stay at Mysore.

Day 2 Mysore to Coorg Sightseeing and Stay

Morning after breakfast check out and proceed for Coorg for todays sightseeing.
On arrival visit following places:
- Dubare Elephant Camp
- Golden Temple Bylakuppe
- Nisargadhama
- Raja Seat
Evening check into hotel and stay at Coorg.

Day 3 Coorg Sightseeing and Stay

Morning after breakfast proceed for Coorg for todays sightseeing.
On arrival visit following places:
- Talacauvery
- Bhagamandala
- Omkareshwara Temple
- Madikeri Fort
- Abbey Falls
Evening return to hotel and stay at Coorg.

Day 4 Coorg to Bangalore Drop

Morning after breakfast check out and proceed for Coorg for todays sightseeing.
On arrival visit following places:
- Dubare Elephant Camp
- Nisargadhama
Later proceed to Bangalore and drop.

SUGGESTED ACCOMMODATION

Mysore: Patel Comforts Inn or similar (3 Star)
Coorg: Itsy Hotel Vijaya Comforts or similar (3 Star)

TOTAL TOUR PACKAGE PRICE

2 persons: Rs. 15,480 per person
3 persons: Rs. 12,080 per person
4 to 8 persons: Rs. 11,120 per person
9 to 12 persons: Rs. 9,160 per person

INCLUSIONS

Vehicle as per group size
Accommodation in 3 Star Hotel rooms with breakfast
Driver charges, parking, toll and taxes

EXCLUSIONS

Flight or train tickets
Entry tickets, boating, personal expenses
Meals other than breakfast
Anything not mentioned in inclusions

PAYMENT POLICY

20 percent advance at time of booking
20 percent after hotel booking voucher
60 percent during tour in parts
For tours between 15 December to 2 January: 50 percent advance required

CHILD POLICY

Child up to 6 years: Free
Child 6 to 8 years: Half charge
Child above 8 years: Full charge

CANCELLATION POLICY

Minimum Rs. 3000 cancellation charge per person
25 percent cancellation between 45 to 30 days before departure
50 percent cancellation between 30 to 15 days before departure
75 percent cancellation between 15 to 5 days before departure
100 percent cancellation within 5 days of departure or no show
Cancellation charges are calculated on total tour cost

FINAL NOTE

Extra charges apply during long weekends, holidays and festival dates.""",

    "dwarka": """Dwarka Somnath Tour Package 4 Days

Day 1 Rajkot to Dwarka

Morning arrival at Rajkot.
Meet and greet by our representative.
Drive to the sacred town of Dwarka.
- Visit Dwarkadeesh Temple
- Take a holy dip in Gomti River
- Visit Nageshwar Jyotirling, Gopi Talav, Bet Dwarka
- Enroute visit Rukmani Temple
- Explore coastal temples
- Attend evening Aarti at Dwarkadeesh Temple
Overnight stay in Dwarka.

Day 2 Dwarka to Porbandar to Somnath

Breakfast at hotel.
Drive to Porbandar.
- Visit Kirti Mandir (birthplace of Mahatma Gandhi)
Proceed to Somnath.
- Visit Junagadh Gate, Bhalka Tirth, Somnath Temple, Triveni Ghat
- Attend evening Aarti and Light and Sound Show at Somnath Temple
Overnight stay in Somnath.

Day 3 Somnath to Diu and Back to Somnath

Breakfast at hotel.
Day trip to Diu.
- Visit Naida Caves, Nagoa Beach, Gangeshwar Mahadev Temple, Diu Fort, Ghoghla Beach, Sunset Point, St. Paul Church
Evening return to Somnath.
Overnight stay in Somnath.

Day 4 Somnath to Sasangir to Junagadh to Rajkot

Breakfast at hotel.
Proceed to Sasangir — home of the Asiatic Lion.
- Enjoy Gir Jungle Safari
Proceed to Junagadh.
- Visit Uperkot Fort, Ashok Rock Edict, Mahabat Maqbara, Junagadh Museum
Evening drop at Rajkot.
Tour ends with memorable experiences.

SUGGESTED ACCOMMODATION

1 Night in Dwarka: Hotel Rajmandir or similar
2 Nights in Somnath: Hotel Madhuram or similar

PACKAGE COST PER PERSON

For 6 persons: Rs. 8,500
For 4 to 5 persons: Rs. 9,500
For 3 persons: Rs. 10,800
For 2 persons: Rs. 14,300

Note: Extra charge of Rs. 2,000 per person applicable during Janmashtami, Navratri, Diwali, Christmas, New Year and Makar Sankranti.

INCLUSIONS

All transfers and sightseeing by AC vehicle
Accommodation in 2 Star hotels
Breakfast as per itinerary (CP Plan)
Toll, parking, driver allowance

EXCLUSIONS

Airfare or Train fare
Entry tickets for monuments
Camera or Video charges
Meals other than mentioned
Personal expenses like laundry, tips, phone calls

CANCELLATION POLICY

Minimum cancellation: 10 percent or Rs. 3,000 (whichever higher)
45 to 30 days before tour: 25 percent of total cost
30 to 15 days before tour: 50 percent
15 to 5 days before tour: 75 percent
Less than 5 days or no show: 100 percent""",

    "gokarna": """Gokarna Murudeshwar Jog Falls Tour Package 3 Days from Hubli

Day 1 Hubli to Gokarna Sightseeing and Stay

Morning pickup from Hubli and drive to Gokarna.
Check into hotel. After refreshment proceed for sightseeing.
- Om Beach: Famous for its Om shaped shoreline and water activities
- Kudle Beach: Serene beach ideal for sunset and relaxation
- Half Moon Beach: Small crescent shaped beach accessible by trek or boat
- Paradise Beach: Isolated beach known for camping and pristine waters
- Mahabaleshwar Temple: Ancient temple dedicated to Lord Shiva
- Koti Tirtha: Sacred tank surrounded by temples, used for rituals
- Gokarna Main Beach: Popular beach for pilgrims and evening walks

Day 2 Gokarna to Murudeshwar Sightseeing and Stay

Morning after breakfast proceed for todays sightseeing.
- Mirjan Fort: 16th century fort surrounded by greenery and history
- Murudeshwar Temple: Renowned Shiva temple on the seashore
- Raja Gopura: 20 storey temple tower with panoramic views
- Murudeshwar Shiva Statue: World's second tallest Shiva statue
- Murudeshwar Beach: Scenic beach ideal for leisure and photography

Day 3 Murudeshwar to Jog Falls Sightseeing and Hubli Drop

Today is the last day of your tour.
Check out from hotel and proceed for sightseeing.
- Raja Viewpoint: Best view of the main waterfall stream
- Roarer Viewpoint: Powerful jet of water creating roaring sound
- Rocket Viewpoint: Stream of water plunging in a straight line
- Rani Viewpoint: Graceful cascading stream like a queen's flow
Drop at Hubli.

SUGGESTED ACCOMMODATION

Gokarna: Hotel Gananjay or similar
Murudeshwar: RNS Highway Hotel or similar

PRICE PER PERSON

2 persons by Dzire or Etios: Rs. 11,150 per person
3 persons by Dzire or Etios: Rs. 8,500 per person
4 persons by Dzire or Etios: Rs. 7,200 per person
5 persons by Innova: Rs. 7,750 per person
6 persons by Innova: Rs. 6,700 per person
7 persons by Innova: Rs. 6,000 per person
8 persons by Tempo Traveller: Rs. 6,600 per person
9 persons by Tempo Traveller: Rs. 6,000 per person
10 persons by Tempo Traveller: Rs. 5,600 per person
11 persons by Tempo Traveller: Rs. 5,300 per person
12 persons by Tempo Traveller: Rs. 5,050 per person

CHILD POLICY

Child up to 6 years: Free
Child 6 to 8 years: Half charge
Child above 8 years: Full charge

PAYMENT POLICY

20 percent advance at time of booking
30 percent on arrival at the time of tour start
50 percent in mid of the tour

CANCELLATION POLICY

10 percent or Rs. 3000 per person whichever is higher
25 percent cancellation between 45 to 30 days before departure
50 percent cancellation between 30 to 15 days before departure
75 percent cancellation between 15 to 5 days before departure
100 percent cancellation within 5 days of departure or no show""",

    "hampi": """Hospet Hampi Badami Aihole Pattadakal Tour Package 3 Days

Day 1 Hospet to Hampi

Pickup from Hospet.
Drive to Hampi.
Check in.
Sightseeing:
- Virupaksha Temple
- Hampi Bazaar
- Hemakuta Hill
Overnight stay in Hampi.

Day 2 Hampi Sightseeing

- Vittala Temple and Stone Chariot
- Queen's Bath
- Lotus Mahal
- Elephant Stables
- Sasivekalu Ganesha
- Matanga Hill
Overnight stay in Hampi.

Day 3 Hampi to Badami via Aihole and Pattadakal — Drop Hospet

- Visit Pattadakal Virupaksha Temple
- Visit Mallikarjuna Temple
- Visit Aihole Durga Temple
- Visit Lad Khan Temple
- Visit Badami Cave Temples
- Visit Agastya Lake
- Visit Bhutanatha Temple
Evening drive to Hospet.
Drop.

SUGGESTED ACCOMMODATION

Hampi: Hotel PBS Grand or similar
Badami: Hotel Raj Sangam or similar

PACKAGE COST PER PERSON

Rs. 10,900 per person for group of 2 persons
Rs. 8,900 per person for group of 3 persons
Rs. 7,900 per person for group of 4 to 5 persons
Rs. 7,400 per person for group of 6 to 7 persons
Rs. 6,900 per person for group of 8 to 11 persons
Rs. 5,900 per person for group of 12 or more persons

INCLUSIONS

AC hotel stay twin or triple sharing
Daily vegetarian breakfast
AC cab with driver
Sightseeing, toll, parking, GST

EXCLUSIONS

Meals not mentioned
Entry fees
Personal expenses
Train or airfare
Services not specified

CHILD POLICY

Below 5 years: Complimentary
5 to 8 years: 50 percent of package cost
Above 8 years: Adult charge

CANCELLATION POLICY

Minimum cancellation is 10 percent or Rs. 3000 whichever is maximum per person per tour
25 percent between 45 to 30 days before tour departure
50 percent between 30 to 15 days before tour departure
75 percent between 15 to 5 days before tour departure
100 percent on the same day and no show and 5 days remaining
Cancellation charges as percentage of total tour cost""",
}

# Aliases so alternate spellings resolve to the same best seller key
_BEST_SELLER_ALIASES = {
    "rameswaram":   "rameshwaram",
    "madurai":      "rameshwaram",
    "kanyakumari":  "rameshwaram",
    "allahabad":    "varanasi",
    "prayagraj":    "varanasi",
    "sarnath":      "varanasi",
    "faizabad":     "ayodhya",
    "shirdi":       "nashik",
    "trimbakeshwar":"nashik",
    "bhimashankar": "nashik",
    "konark":       "puri",
    "bhubaneswar":  "puri",
    "chilika":      "puri",
    "omkareshwar":  "ujjain",
    "indore":       "ujjain",
    "mysore":       "coorg",
    "kodagu":       "coorg",
    "somnath":      "dwarka",
    "gir":          "dwarka",
    "diu":          "dwarka",
    "murudeshwar":  "gokarna",
    "jog falls":    "gokarna",
    "hospet":       "hampi",
    "badami":       "hampi",
    "aihole":       "hampi",
    "pattadakal":   "hampi",
}

# How long (minutes) to wait before auto follow-up when best seller was sent
BEST_SELLER_FOLLOWUP_MINUTES = 10


def _get_best_seller_key(destination: str) -> str | None:
    """Return the canonical best-seller key for a destination string, or None."""
    d = destination.strip().lower()
    if d in BEST_SELLER_PACKAGES:
        return d
    if d in _BEST_SELLER_ALIASES:
        return _BEST_SELLER_ALIASES[d]
    return None


def _build_best_seller_teaser_message(bs_key: str) -> str:
    pkg = BEST_SELLER_PACKAGES.get(bs_key)
    if not pkg:
        return ""
    return (
        f"Our Best Seller Package for you:\n\n"
        f"{pkg['title']}\n\n"
        f"{pkg['body']}"
    )


def _get_best_seller_full_itinerary(bs_key: str) -> str | None:
    """Return the full pre-written itinerary for the given best seller key, or None."""
    return BEST_SELLER_FULL_ITINERARIES.get(bs_key)


# ─────────────────────────────────────────────────────────────────────────────
# INTELLIGENT DESTINATION DETECTOR
# ─────────────────────────────────────────────────────────────────────────────

_ALL_DEST_LOWER: set[str] = set()
_ALL_DEST_LOWER.update(d.lower() for d in BEST_SELLER_PACKAGES.keys())
_ALL_DEST_LOWER.update(d.lower() for d in _BEST_SELLER_ALIASES.keys())


def _ensure_dest_lookup_populated() -> None:
    global _ALL_DEST_LOWER
    if len(_ALL_DEST_LOWER) < 50:
        try:
            _ALL_DEST_LOWER.update(d.lower() for d in VALID_DESTINATIONS)
            _ALL_DEST_LOWER.update(c.lower() for c in ALL_INDIAN_CITIES)
            _ALL_DEST_LOWER.update(d.lower() for d in FEATURED_DESTINATIONS)
        except Exception:
            pass


def detect_destination_in_message(message: str) -> str | None:
    _ensure_dest_lookup_populated()
    msg = message.lower().strip()

    noise = r"\b(i want to go to|i want to visit|plan a trip to|trip to|travel to|" \
            r"going to|visit|book|tour|package|for|in|at|near|around|from|the|a|an|" \
            r"hello|hi|hey|can i|get more info|more info|info on|about|interested in|" \
            r"looking for|want to know|tell me about|yatra|trip)\b"
    cleaned = re.sub(noise, " ", msg).strip()

    if cleaned in _ALL_DEST_LOWER:
        return cleaned

    tokens = cleaned.split()
    for token in tokens:
        token = token.strip(".,!?-;:")
        if len(token) >= 4 and token in _ALL_DEST_LOWER:
            return token
    for i in range(len(tokens) - 1):
        bigram = tokens[i] + " " + tokens[i + 1]
        if bigram in _ALL_DEST_LOWER:
            return bigram

    candidates = list(_ALL_DEST_LOWER)
    single_words = [w.strip(".,!?-;:") for w in tokens if len(w) >= 4]
    for word in single_words:
        matches = get_close_matches(word, candidates, n=1, cutoff=0.84)
        if matches:
            return matches[0]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# INTENT CLASSIFIER
# ─────────────────────────────────────────────────────────────────────────────

INTENT_ANSWER          = "ANSWER"
INTENT_MODIFY          = "MODIFY"
INTENT_GENERAL         = "GENERAL"
INTENT_NEW_ENQUIRY     = "NEW_ENQUIRY"
INTENT_EXPERT          = "EXPERT"
INTENT_GREETING        = "GREETING"
INTENT_COMPANY         = "COMPANY_INFO"
INTENT_DISCOUNT        = "DISCOUNT"
INTENT_MEAL_PRICE      = "MEAL_PRICE"
INTENT_BEST_SELLER_OK  = "BEST_SELLER_OK"
INTENT_BEST_SELLER_MOD = "BEST_SELLER_MOD"

_NEW_ENQUIRY_TRIGGERS = {
    "start new trip", "plan new trip", "new trip", "restart",
    "re plan", "replan", "start over", "fresh start",
    "plan my trip", "plan trip", "plan a trip", "book a trip",
}

_EXPERT_TRIGGERS = {
    "talk to expert", "connect me", "call me", "book now",
    "get quote", "speak to agent", "speak to expert", "i want to book",
}

_GREETING_PATTERNS = {
    "hi", "hii", "hiii", "hello", "helloo", "helo", "hey", "heyy",
    "good morning", "good afternoon", "good evening", "good night",
    "sup", "yo", "howdy", "greetings", "start", "begin", "get started",
    "lets start", "let's start", "ok start", "okay start",
}

_COMPANY_INFO_PATTERNS = [
    r"\b(who are you|what are you|about you|your company|company name)\b",
    r"\b(address|location|office|where are you)\b",
    r"\b(trypdeals|tryp deals|trip deals)\b",
    r"\b(contact|phone|email|reach you)\b",
]

_DISCOUNT_PATTERNS = [
    r"\b(discount|offer|rebate|reduce price|less price)\b",
    r"\b(better deal|best price|special offer|any offer|better offer)\b",
    r"\b(too expensive|costly|high price|budget issue|expensive)\b",
    r"\b(can you reduce|cheaper option|budget package|less expensive|afford)\b",
]

_MEAL_PRICE_PATTERNS = [
    r"\b(meal|meals|food|lunch|dinner|breakfast|snack|snacks|eating|eat)\b.*\b(cost|price|charge|how much|rate|amount|fee)\b",
    r"\b(cost|price|charge|how much|rate|amount|fee)\b.*\b(meal|meals|food|lunch|dinner|breakfast|snack|snacks)\b",
    r"\b(meal cost|food cost|meal price|food price|meal charge|food charge|meal rate|food rate)\b",
    r"\b(how much.*(?:eat|food|meal|lunch|dinner)|(?:eat|food|meal|lunch|dinner).*how much)\b",
    r"\b(meal included|food included|is meal|are meals|includes meal|includes food)\b",
    r"\b(meal price|khana|khaana|khane ka|khane ki|khane ke)\b",
]

_BEST_SELLER_OK_PHRASES    = {"looks good", "looks great", "this is good", "perfect", "ok", "okay"}
_BEST_SELLER_MODIFY_PHRASES = {"modify", "change", "customize", "i want to change", "modify this"}


def classify_intent(message: str, stage: int, data: dict) -> str:
    msg = _norm(message)

    # "Hi 🙏", "Hello!", "hi sir", "namaste" are greetings too.
    bare = re.sub(r"[^a-z' ]+", " ", msg)
    bare = re.sub(r"\b(sir|mam|madam|ji|there|team|trypdeals)\b", " ", bare)
    bare = " ".join(bare.split())
    if msg in _GREETING_PATTERNS or bare in _GREETING_PATTERNS or bare in ("namaste", "namaskar", "hi hello", "hello hi"):
        return INTENT_GREETING
    if msg in _NEW_ENQUIRY_TRIGGERS:
        return INTENT_NEW_ENQUIRY
    if msg in _EXPERT_TRIGGERS or _is_lead_trigger(message):
        return INTENT_EXPERT
    if any(re.search(p, msg) for p in _COMPANY_INFO_PATTERNS):
        return INTENT_COMPANY
    if any(re.search(p, msg) for p in _MEAL_PRICE_PATTERNS):
        return INTENT_MEAL_PRICE
    if any(re.search(p, msg) for p in _DISCOUNT_PATTERNS):
        return INTENT_DISCOUNT

    if stage == STAGE_BEST_SELLER_SENT:
        if msg in _BEST_SELLER_OK_PHRASES:
            return INTENT_BEST_SELLER_OK
        if msg in _BEST_SELLER_MODIFY_PHRASES:
            return INTENT_BEST_SELLER_MOD
        if any(t in msg for t in ["talk to expert", "expert", "connect", "agent"]):
            return INTENT_EXPERT

    return INTENT_ANSWER


# ─────────────────────────────────────────────────────────────────────────────
# HELPER UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    return text.lower().replace("\u200d", "").strip()


def _make(message: str, options: list = None, auto_followup: str = "",
          social_card: dict = None, flow_payload: dict = None) -> dict:
    result = {
        "message":       _strip_markdown(message),
        "options":       options or [],
        "auto_followup": auto_followup,
    }
    if social_card:
        result["social_card"] = social_card
    if flow_payload:
        result["flow_payload"] = flow_payload
    return result


def _save_history(data: dict, role: str, content: str) -> dict:
    history = data.get("_history", [])
    history.append({"role": role, "content": content})
    data["_history"] = history[-20:]
    return data


def _save_session(session) -> None:
    try:
        update_fields = [
            field.name for field in session._meta.fields
            if field.name in ("generated_itinerary", "itinerary", "last_itinerary",
                              "data", "step", "updated_at", "customization_mode",
                              "current_custom_day", "day_customizations", "extracted_days")
        ]
        if update_fields:
            session.save(update_fields=update_fields)
        else:
            session.save()
    except Exception:
        session.save()


def _persist_itinerary(session, itinerary: str) -> None:
    for attr in ("generated_itinerary", "itinerary", "last_itinerary"):
        try:
            setattr(session, attr, itinerary)
        except Exception:
            pass
    session.data["_last_itinerary"] = itinerary

    # Removed mark_lead_follow_up - only using mark_lead_today for conversational flow

    try:
        session.refresh_from_db()
    except Exception:
        pass

    _save_session(session)
    _save_bot_reply_to_crm(session, itinerary)


def _history_str(data: dict, n: int = 10) -> str:
    history = data.get("_history", [])
    if not history:
        return "(Start of conversation)"
    lines = []
    for turn in history[-n:]:
        role = "User" if turn.get("role") == "user" else "Bot"
        lines.append(f"{role}: {turn.get('content', '')}")
    return "\n".join(lines)


def _update_last_active(session) -> None:
    session.data["_last_active_ts"] = datetime.utcnow().isoformat()
    session.data["_followup_stopped"] = False
    session.save(update_fields=["data"])


def _session_context_str(data: dict) -> str:
    parts = []
    dest = data.get("confirmed_destination") or data.get("destination")
    if dest:
        parts.append(f"Destination: {dest}")
    if data.get("adults"):
        parts.append(f"Adults: {data['adults']}")
    children_ages = data.get("children_ages", [])
    if children_ages:
        parts.append(f"Children: {_format_children_summary(children_ages)}")
    elif data.get("children_count", 0) == 0:
        parts.append("Children: None")
    if data.get("days"):
        parts.append(f"Duration: {data['days']} days")
    if data.get("tour_type"):
        parts.append(f"Tour type: {data['tour_type']}")
    if data.get("departure_date"):
        parts.append(f"Departure date: {data['departure_date']}")
    if data.get("special_notes"):
        parts.append(f"Special notes: {data['special_notes']}")
    return "\n".join(parts) if parts else "No trip details collected yet."


def _format_children_summary(children_ages: list) -> str:
    if not children_ages:
        return "No children"
    count    = len(children_ages)
    ages_str = ", ".join(str(a) for a in children_ages)
    return f"{count} {'child' if count == 1 else 'children'} (Age{'s' if count > 1 else ''}: {ages_str})"


def _blank_session() -> dict:
    return {
        "stage":                STAGE_IDLE,
        "destination":          None,
        "confirmed_destination":None,
        "days":                 None,
        "adults":               None,
        "children_count":       0,
        "children_ages":        [],
        "special_notes":        "",
        "selected_package":     None,
        "selected_places":      [],
        "tour_type":            None,
        "departure_date":       None,
        "welcome_sent":         False,
        "_history":             [],
        "_trip_packages":       [],
        "_last_itinerary":      "",
        "_itinerary_sent":      False,
        "_pending_modifications":[],
        "_discount_level":      0,
        "_chat_turn":           0,
        "_expert_contacted":    False,
        "_followup_stopped":    False,
        "_itinerary_variation": 0,
        "_last_active_ts":      datetime.utcnow().isoformat(),
        "_last_followup_sent":  0,
        "_flow_sent":           False,
        "_custom_flow_sent":    False,
        "_name":                "",
        "_modify_mode":         "",
        "_best_seller_sent_ts": None,
        "_best_seller_key":     None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP FLOW PAYLOAD BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def build_flow_message(flow_id: str, header_text: str, body_text: str,
                       cta_text: str = "Fill Form",
                       flow_token: str = "unused") -> dict:
    screen_id = FLOW_SCREEN_IDS.get(flow_id, "FORM")
    return {
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": header_text},
            "body":   {"text": body_text},
            "footer": {"text": COMPANY_SHORT},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token":           flow_token,
                    "flow_id":              flow_id,
                    "flow_cta":             cta_text,
                    "flow_action":          "navigate",
                    "flow_action_payload":  {"screen": screen_id},
                },
            },
        },
    }


def build_basic_travel_flow() -> dict:
    return build_flow_message(
        FLOW_BASIC_TRAVEL,
        "Trip Details",
        "Please fill in your travel details below.",
        "Fill Form",
    )


# ─────────────────────────────────────────────────────────────────────────────
# FLOW SUBMISSION PARSERS
# ─────────────────────────────────────────────────────────────────────────────

def parse_basic_travel_flow(payload: dict) -> dict:
    result = {
        "name":           payload.get("name", "").strip(),
        "destination":    payload.get("destination", "").strip(),
        "days_raw":       str(payload.get("trip_days", "")).strip(),
        "adults":         0,
        "children_count": 0,
        "children_ages":  [],
        "special_notes":  payload.get("special_notes", "").strip(),
    }
    days_str = result["days_raw"].lower()
    result["days"] = int(days_str) if days_str.isdigit() else None

    try:
        result["adults"] = max(1, int(str(payload.get("adults", 2)).strip()))
    except (ValueError, TypeError):
        result["adults"] = 2

    try:
        result["children_count"] = int(str(payload.get("children", 0)).strip())
    except (ValueError, TypeError):
        result["children_count"] = 0

    ages_raw = str(payload.get("child_ages", "")).strip()
    if ages_raw and ages_raw not in ("0", "-"):
        age_nums = re.findall(r"\d{1,2}", ages_raw)
        result["children_ages"] = [int(a) for a in age_nums if 1 <= int(a) <= 17]

    return result


def _normalise_date_string(raw: str) -> str:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%d %b %Y")
        except ValueError:
            continue
    return raw


def extract_flow_response_json(interactive: dict) -> dict | None:
    try:
        nfm      = interactive.get("nfm_reply", {})
        raw_json = nfm.get("response_json", "")
        if not raw_json:
            logger.warning("[FLOW] response_json missing or empty")
            return None
        parsed = json.loads(raw_json)
        logger.debug(f"[FLOW] Parsed response_json keys: {list(parsed.keys())}")
        return parsed
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"[FLOW PARSE ERROR] extract_flow_response_json: {e}")
        return None


def identify_flow_from_response(payload: dict, session_data: dict) -> str | None:
    stage = session_data.get("stage", STAGE_IDLE)

    if stage in (STAGE_FLOW_SENT, STAGE_BEST_SELLER_SENT):
        logger.debug(f"[FLOW ID] Stage={_stage_name(stage)} → FLOW_BASIC_TRAVEL")
        return FLOW_BASIC_TRAVEL

    if "destination" in payload or "trip_days" in payload or "travel_date" in payload:
        logger.debug("[FLOW ID] Key 'destination'/'trip_days'/'travel_date' found → FLOW_BASIC_TRAVEL")
        return FLOW_BASIC_TRAVEL

    logger.warning(
        f"[FLOW ID] Cannot identify flow. Payload keys: {list(payload.keys())}, stage={_stage_name(stage)}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# DESTINATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def autocorrect_destination(destination: str) -> str:
    dest_lower  = destination.strip().lower()
    candidates  = [d.lower() for d in VALID_DESTINATIONS]
    matches     = get_close_matches(dest_lower, candidates, n=1, cutoff=0.82)
    if matches:
        for d in VALID_DESTINATIONS:
            if d.lower() == matches[0]:
                return d
    city_candidates = [c.lower() for c in ALL_INDIAN_CITIES]
    city_matches    = get_close_matches(dest_lower, city_candidates, n=1, cutoff=0.82)
    if city_matches:
        for c in ALL_INDIAN_CITIES:
            if c.lower() == city_matches[0]:
                return c
    return destination.strip().title()


def is_valid_indian_destination(destination: str) -> bool:
    dest       = destination.strip()
    dest_lower = dest.lower()
    for d in VALID_DESTINATIONS:
        if d.lower() == dest_lower:
            return True
    for c in ALL_INDIAN_CITIES:
        if c.lower() == dest_lower:
            return True
    if get_close_matches(dest_lower, [d.lower() for d in VALID_DESTINATIONS], n=1, cutoff=0.80):
        return True
    if get_close_matches(dest_lower, [c.lower() for c in ALL_INDIAN_CITIES], n=1, cutoff=0.80):
        return True
    answer = _deepseek(
        f'Is "{dest}" a real Indian travel destination, tourist place, hill station, beach, '
        f'village, pilgrimage site, district, city, or state in India?\n\nReply ONLY YES or NO.'
    ).strip().upper()
    return answer.startswith("YES")


def _is_international(message: str) -> bool:
    msg = _norm(message)
    return any(dest in msg for dest in INTERNATIONAL_DESTINATIONS)


def _is_hard_block(message: str) -> bool:
    msg = _norm(message)
    return any(re.search(p, msg) for p in HARD_BLOCK_PATTERNS)


def _is_lead_trigger(message: str) -> bool:
    msg      = _norm(message)
    triggers = ["call me", "connect me", "book now",
                "i want to book", "speak to agent", "speak to expert"]
    return any(t in msg for t in triggers)


STOP_FOLLOWUP_PATTERNS = [
    r"\b(stop|not interested|cancel|no thanks|no thank you)\b",
    r"\b(book|booking confirmed|confirmed|done deal|finalised|finalized)\b",
]


def _should_stop_followup(message: str) -> bool:
    msg = message.lower()
    return any(re.search(p, msg) for p in STOP_FOLLOWUP_PATTERNS)


# ─────────────────────────────────────────────────────────────────────────────
# COMPANY INFO HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def _handle_company_info(message: str) -> str:
    msg = message.lower()
    if any(k in msg for k in ["address", "location", "office", "where"]):
        return (f"Our office:\n\n{COMPANY_NAME}\n{COMPANY_ADDRESS}\n\n"
                f"Would you like to plan a trip?")
    return (f"We are {COMPANY_SHORT} — specialising in domestic India tour packages.\n"
            f"Office: {COMPANY_ADDRESS}\n\nWhere would you like to travel?")


# ─────────────────────────────────────────────────────────────────────────────
# MEAL PRICE HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def _handle_meal_price_query() -> str:
    return (
        "Meals are not included in the package price.\n\n"
        "You can expect to spend approximately Rs. 300 or more per meal per person "
        "at local restaurants and dhabas near the sightseeing areas.\n\n"
        "Budget travellers can find good meals for Rs. 150 to Rs. 300, while "
        "mid-range restaurants typically charge Rs. 300 to Rs. 600 per person."
    )


# ─────────────────────────────────────────────────────────────────────────────
# FAQ CONTEXT
# ─────────────────────────────────────────────────────────────────────────────

def _get_faq_context(message: str) -> str:
    msg = _norm(message)
    try:
        faqs      = FAQ.objects.all()
        questions = [f.question.lower() for f in faqs]
        matches   = get_close_matches(msg, questions, n=1, cutoff=0.50)
        if matches:
            faq = FAQ.objects.filter(question__iexact=matches[0]).first()
            if faq:
                return faq.answer
        for faq in faqs:
            if faq.keywords:
                keywords = [k.strip().lower() for k in faq.keywords.split(",")]
                if any(k in msg for k in keywords):
                    return faq.answer
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# DISCOUNT LADDER
# ─────────────────────────────────────────────────────────────────────────────

def _handle_discount_request(message: str, data: dict) -> dict:
    current_level = data.get("_discount_level", 0)
    if current_level == 0:
        data["_discount_level"] = 1
        return _make("We can offer a 2% special discount. Would that work for you?",
                     ["Yes, That Works", "I Need More Discount"])
    elif current_level == 1:
        data["_discount_level"] = 2
        return _make("We can extend the discount to 4%. Does that work?",
                     ["Yes, 4% Works", "I Need More Discount"])
    elif current_level == 2:
        data["_discount_level"] = 3
        return _make("We can go up to 6% — that is our maximum special discount. Shall we finalise?",
                     ["Yes, 6% Final", "Talk to Expert for Better Deal"])
    else:
        return _make("For anything beyond 6%, our travel expert can personally work out a deal.",
                     ["Yes, Connect Me to Expert", "No Thanks"])


# ─────────────────────────────────────────────────────────────────────────────
# LEAD HANDOFF
# ─────────────────────────────────────────────────────────────────────────────

SOCIAL_CARD = {"type": "social_card", "links": []}


def handle_lead_handoff(session) -> dict:
    data     = session.data
    dest     = data.get("confirmed_destination") or data.get("destination", "")
    dest_str = f" for your {dest} trip" if dest else ""
    try:
        Lead.objects.get_or_create(
            session=session,
            defaults={
                "name":        data.get("_name", "WhatsApp User"),
                "phone":       session.phone_number or "",
                "destination": dest or "Unknown",
            },
        )
    except Exception:
        pass
    
    # Mark as TODAY lead with source-based assignment on handoff
    try:
        mark_lead_today(session)
        session.refresh_from_db()
        logger.info(f"[LEAD HANDOFF] Marked as TODAY lead for session {session.id}")
    except Exception as e:
        logger.error(f"[LEAD HANDOFF] mark_lead_today failed: {e}")
    
    session.step          = STAGE_CHAT
    session.data["stage"] = STAGE_CHAT
    session.data["_expert_contacted"]  = True
    session.data["_followup_stopped"]  = True
    _save_session(session)
    logger.info(f"[LEAD HANDOFF] dest={dest}, stage → STAGE_CHAT")
    msg = (f"Connecting you with our travel expert{dest_str} for final pricing and booking. "
           f"Our team will contact you shortly.")
    return _make(msg, ["Plan New Trip"], social_card=SOCIAL_CARD)


def _build_form_submission_handoff_message(session, parsed: dict) -> str:
    """
    Build the agent handoff message that summarises the trip details
    collected from the Basic Travel Flow form submission.
    """
    data        = session.data
    dest        = parsed.get("destination", "") or data.get("confirmed_destination") or data.get("destination", "")
    name        = parsed.get("name", "").strip()
    days        = parsed.get("days")
    adults      = parsed.get("adults", 2)
    children    = parsed.get("children_count", 0)
    child_ages  = parsed.get("children_ages", [])
    notes       = parsed.get("special_notes", "").strip()

    lines = []
    if dest:
        lines.append(f"Destination: {dest}")
    if name:
        lines.append(f"Name: {name}")
    if days:
        lines.append(f"Duration: {days} Days")
    if adults:
        lines.append(f"Adults: {adults}")
    if children:
        age_str = ", ".join(str(a) for a in child_ages) if child_ages else "not specified"
        lines.append(f"Children: {children} (Ages: {age_str})")
    if notes:
        lines.append(f"Special Notes: {notes}")

    details_block = "\n".join(lines)

    intro = (
        f"Thank you! We have received your travel details and are connecting you "
        f"with our travel expert who will get in touch with you shortly.\n\n"
        f"Here are the details shared with our team:\n\n"
        f"{details_block}\n\n"
        f"Our expert will customise the best package for you and confirm availability."
    )
    return intro


# ─────────────────────────────────────────────────────────────────────────────
# BEST SELLER FLOW  (v18.0.0)
# ─────────────────────────────────────────────────────────────────────────────

def _send_best_seller_package(session, bs_key: str) -> dict:
    """
    PATH A — Step 1 & 2:
    Send teaser card only (removed full itinerary sending).
    Move to STAGE_BEST_SELLER_SENT.
    Options: Modify | Talk to Expert
    """
    data = session.data

    teaser_msg    = _build_best_seller_teaser_message(bs_key)

    if not teaser_msg:
        # Should never happen for a valid key, but guard anyway
        return _handle_destination_flow_sent(session, bs_key.title())

    data["stage"]                = STAGE_BEST_SELLER_SENT
    data["_best_seller_sent_ts"] = datetime.utcnow().isoformat()
    data["_best_seller_key"]     = bs_key
    if not data.get("confirmed_destination"):
        data["destination"]           = bs_key.title()
        data["confirmed_destination"] = bs_key.title()

    session.data = data
    session.step = STAGE_BEST_SELLER_SENT
    _save_session(session)

    # Removed mark_lead_follow_up - only using mark_lead_today for conversational flow

    logger.info(f"[BEST SELLER] Sent teaser only for key={bs_key}, stage → STAGE_BEST_SELLER_SENT")

    # Only send teaser message (removed full itinerary)
    # Save to CRM to avoid duplicate saves in generate_response
    _save_bot_reply_to_crm(session, teaser_msg)

    return {
        "message": teaser_msg,
        "options": ["Modify", "Talk to Expert"],
        "social_card": SOCIAL_CARD,
    }


def _handle_stage_best_seller_sent(session, message: str, intent: str) -> dict:
    """
    PATH A — handle user response at STAGE_BEST_SELLER_SENT.

    "Modify"               → send Basic Travel Flow form; on submission → handoff with details.
    "Talk to Expert"       → immediate handoff, mark FOLLOW UP.
    """
    data   = session.data
    msg_l  = _norm(message)
    bs_key = data.get("_best_seller_key", "")

    # "Modify" — send Basic Travel Flow form
    if intent == INTENT_BEST_SELLER_MOD or msg_l in _BEST_SELLER_MODIFY_PHRASES:
        data["stage"]      = STAGE_FLOW_SENT
        data["_flow_sent"] = True
        session.data       = data
        session.step       = STAGE_FLOW_SENT
        _save_session(session)
        logger.info("[BEST SELLER MOD] User wants to modify → sending basic travel flow")
        return _make(
            "Please fill in your travel details below and our travel expert "
            "will create a customised package for you.",
            [],
            flow_payload=build_basic_travel_flow(),
        )

    # Ambiguous — re-show the options
    pkg_title = BEST_SELLER_PACKAGES.get(bs_key, {}).get("title", "our best seller package")
    return _make(
        f"Would you like to proceed with {pkg_title}?",
        ["Modify", "Talk to Expert"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# NON-BEST-SELLER DESTINATION FLOW  (v18.0.0)
# ─────────────────────────────────────────────────────────────────────────────

def _handle_destination_flow_sent(session, destination: str) -> dict:
    """
    Confirm destination and send summary message with all details.
    """
    data = session.data
    data["destination"]           = destination
    data["confirmed_destination"] = destination
    data["stage"]                 = STAGE_FLOW_SENT
    data["_flow_sent"]            = True
    session.data = data
    session.step = STAGE_FLOW_SENT
    _save_session(session)

    # Build summary with all details (matching old format)
    lines = []
    if destination:
        lines.append(f"Destination: {destination.upper()}")
    
    # Travel date
    travel_date = data.get("departure_date") or data.get("travel_date")
    if travel_date:
        lines.append(f"Travel Date: {travel_date}")
    
    # Travelers
    adults = data.get("adults") or 0          # may be stored as None
    children = data.get("children_count") or 0
    if adults == 1 and children == 0:
        travelers = "Solo"
    elif adults > 0 or children > 0:
        total = adults + children
        travelers = f"{total} Traveler{'s' if total > 1 else ''}"
    else:
        travelers = "Not specified"
    lines.append(f"Travelers: {travelers}")
    
    # Planning Status
    seriousness = data.get("seriousness")
    if seriousness:
        lines.append(f"Planning Status: {seriousness}")

    details_block = "\n".join(lines) if lines else "No details collected yet."

    # Removed mark_lead_follow_up - only using mark_lead_today for conversational flow

    logger.info(f"[DESTINATION] Confirmed: {destination}, stage → STAGE_FLOW_SENT")
    return _make(
        f"Thanks for sharing your travel details!\n\n"
        f"{details_block}\n\n"
        f"Our Sales Agent will contact you soon with the best options.",
        [],
    )


def _handle_destination_collection(session, message: str) -> dict:
    """
    Validate destination and route to best-seller flow or non-best-seller flow.
    """
    data     = session.data
    raw_dest = message.strip()

    if len(raw_dest) < 3 or _is_hard_block(raw_dest):
        return _make(
            "Please tell me which destination in India you would like to travel to.",
        )

    corrected = autocorrect_destination(raw_dest)

    if not is_valid_indian_destination(corrected):
        return _make(
            f'"{raw_dest}" does not appear to be a valid Indian destination. '
            f"Please enter a city, state, or tourist place in India.",
        )

    if _is_international(raw_dest):
        return _make(
            f"{COMPANY_SHORT} specialises in domestic India travel only. "
            f"Please choose an Indian destination.",
        )

    # All destinations: confirm and send form (removed best seller packages)
    return _handle_destination_flow_sent(session, corrected)


# ─────────────────────────────────────────────────────────────────────────────
# FLOW SUBMISSION HANDLER  (v18.0.0 — simplified)
# ─────────────────────────────────────────────────────────────────────────────

def handle_flow_basic_travel_submission(session, payload: dict,
                                        raw_payload: dict = None) -> dict:
    """
    REMOVED - WhatsApp Flow form is no longer used.
    All interactions now go through conversational flow.
    """
    logger.warning("[FLOW SUBMISSION] Flow submission called but flow is disabled. Redirecting to conversational flow.")
    # Redirect to conversational destination stage
    data = session.data
    data["stage"] = STAGE_CONV_DESTINATION
    session.data = data
    session.step = STAGE_CONV_DESTINATION
    _save_session(session)
    return _handle_conv_destination(session, "")


def handle_flow_submission(session, interactive: dict) -> dict:
    """
    Central dispatcher for all WhatsApp Flow nfm_reply submissions.
    In v18.0.0, only the Basic Travel Flow is used.
    """
    data          = session.data
    current_stage = data.get("stage", STAGE_IDLE)

    logger.info(f"[FLOW SUBMISSION] Incoming nfm_reply. Stage={_stage_name(current_stage)}")

    parsed_payload = extract_flow_response_json(interactive)

    if parsed_payload is None:
        logger.error(
            f"[FLOW SUBMISSION] response_json missing/invalid at stage={_stage_name(current_stage)}")
        return _make(
            "We could not read your form submission. Please try again.",
            [],
            flow_payload=build_basic_travel_flow(),
        )

    flow_id = identify_flow_from_response(parsed_payload, data)

    if flow_id:
        _save_flow_message_to_crm(session, parsed_payload, flow_id)

    logger.info(f"[FLOW SUBMISSION] Identified flow: {FLOW_NAMES.get(flow_id, flow_id)}, "
                f"stage={_stage_name(current_stage)}")

    # Route to basic travel form handler
    if flow_id == FLOW_BASIC_TRAVEL or "destination" in parsed_payload or "trip_days" in parsed_payload or "travel_date" in parsed_payload:
        if flow_id != FLOW_BASIC_TRAVEL:
            _save_flow_message_to_crm(session, parsed_payload, FLOW_BASIC_TRAVEL)
        return handle_flow_basic_travel_submission(session, parsed_payload, interactive)

    # Stage-based fallback
    if current_stage in (STAGE_FLOW_SENT, STAGE_BEST_SELLER_SENT):
        logger.warning("[FLOW SUBMISSION] Stage-based fallback → FLOW_BASIC_TRAVEL")
        _save_flow_message_to_crm(session, parsed_payload, FLOW_BASIC_TRAVEL)
        return handle_flow_basic_travel_submission(session, parsed_payload, interactive)

    logger.error(
        f"[FLOW SUBMISSION] Could not route flow submission.\n"
        f"  Stage     : {_stage_name(current_stage)}\n"
        f"  Payload   : {json.dumps(parsed_payload, ensure_ascii=False)[:500]}\n"
        f"  Session   : dest={data.get('confirmed_destination')}, days={data.get('days')}"
    )
    return _make(
        "We were unable to process your form submission. "
        "Please contact our team or try again.",
        ["Talk to Expert", "Plan New Trip"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# PERSISTENCE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _create_travel_request(session, parsed: dict, raw_payload: dict) -> object:
    try:
        from .models import TravelRequest
        TravelRequest.objects.filter(
            session=session, is_active=True).update(is_active=False)
        return TravelRequest.objects.create(
            session=session,
            destination=parsed.get("destination", ""),
            days=parsed.get("days"),
            days_raw=parsed.get("days_raw", ""),
            adults=parsed.get("adults", 2),
            children_count=parsed.get("children_count", 0),
            children_ages=parsed.get("children_ages", []),
            special_notes=parsed.get("special_notes", ""),
            raw_payload=raw_payload,
            is_active=True,
        )
    except Exception as e:
        logger.error(f"[TravelRequest] Create error: {e}")
        return None


def _get_active_travel_request(session):
    try:
        from .models import TravelRequest
        return TravelRequest.objects.filter(session=session, is_active=True).first()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATIONAL 3-QUESTION FLOW
# ─────────────────────────────────────────────────────────────────────────────

def _handle_conv_seriousness(session, message: str) -> dict:
    """
    Handle STAGE_CONV_SERIOUSNESS - ask how serious user is about the trip.
    Based on seriousness and destination type, either send itinerary or transfer to sales.
    """
    data = session.data
    msg = message.strip()
    destination = data.get("destination", "").lower()
    
    # Check if user selected an option
    if msg in SERIOUSNESS_OPTIONS:
        seriousness = msg
        data["seriousness"] = seriousness
        data["stage"] = STAGE_CONV_DATE
        session.data = data
        session.step = STAGE_CONV_DATE
        _save_session(session)
        
        reply = "When are you planning to travel?"
        return _make(reply, TRAVEL_DATE_OPTIONS)
    
    # If user didn't select an option, try to understand their response
    ai_reply = _deepseek(
        f"You are a helpful travel assistant for {COMPANY_SHORT}. "
        f"User said: \"{message}\"\n\n"
        f"Classify their seriousness about the trip into one of these categories:\n"
        f"- 'Just Exploring' (if they're just browsing, not serious)\n"
        f"- 'Planning Trip' (if they're planning but not ready to book)\n"
        f"- 'Ready to Book' (if they're ready to book)\n\n"
        f"Return ONLY the exact category name."
    )
    
    if ai_reply:
        ai_reply = _strip_markdown(ai_reply).strip()
        if ai_reply in SERIOUSNESS_OPTIONS:
            seriousness = ai_reply
            data["seriousness"] = seriousness
            data["stage"] = STAGE_CONV_DATE
            session.data = data
            session.step = STAGE_CONV_DATE
            _save_session(session)
            
            reply = "When are you planning to travel?"
            return _make(reply, TRAVEL_DATE_OPTIONS)
    
    # If we can't classify, ask again with options
    return _make(
        "Please select how serious you are about this trip:",
        SERIOUSNESS_OPTIONS
    )


def _handle_conv_destination(session, message: str) -> dict:
    """
    Handle STAGE_CONV_DESTINATION - ask for destination and answer questions gently using DeepSeek.
    Uses DeepSeek to validate Indian destinations and correct spelling errors.
    Answers user questions and re-asks for destination.
    """
    data = session.data
    msg = message.strip()
    
    # Use DeepSeek to extract and validate destination
    ai_reply = _deepseek(
        f"You are a helpful travel assistant for {COMPANY_SHORT}. "
        f"User said: \"{message}\"\n\n"
        f"Extract the destination from their message. "
        f"Check if it's an Indian destination. "
        f"If it's a foreign destination (not in India), return 'FOREIGN'. "
        f"If it's an Indian destination, return the corrected spelling (e.g., 'Rameshwaram', 'Varanasi', 'Goa', 'Kerala', etc.). "
        f"If no destination is mentioned, return 'NO_DESTINATION'. "
        f"Correct common spelling errors (e.g., 'Raameshwaram' -> 'Rameshwaram', 'Varanasi' -> 'Varanasi'). "
        f"Return ONLY the destination name or 'FOREIGN' or 'NO_DESTINATION'."
    )
    
    if ai_reply:
        ai_reply = _strip_markdown(ai_reply).strip()
        
        if ai_reply == "FOREIGN":
            # Foreign destination - reject politely
            reply = "We currently only deal with Indian destinations. Please tell me which destination in India you would like to travel to."
            _save_history(data, "user", message)
            _save_history(data, "assistant", reply)
            session.data = data
            session.save()
            return _make(reply)
        
        elif ai_reply != "NO_DESTINATION" and len(ai_reply) >= 3:
            # Valid Indian destination - save and move to seriousness stage
            corrected = ai_reply
            data["destination"] = corrected
            data["confirmed_destination"] = corrected
            data["stage"] = STAGE_CONV_SERIOUSNESS
            session.data = data
            session.step = STAGE_CONV_SERIOUSNESS
            _save_session(session)
            
            reply = "Great choice!\n\nWhat's your current planning status for this trip?"
            return _make(reply, SERIOUSNESS_OPTIONS)
    
    # No destination found - use DeepSeek to answer question and re-ask for destination
    ai_reply = _deepseek(
        f"You are a helpful travel assistant for {COMPANY_SHORT}. "
        f"User asked: \"{message}\"\n\n"
        f"Answer their question in a simple, friendly way (1-2 sentences max). "
        f"Keep it short and conversational. No emojis. "
        f"After answering, ask: 'Which destination in India would you like to travel to?' "
        f"If they ask about foreign destinations, say: 'We currently only serve Indian destinations. Which Indian destination would you like to visit?' "
        f"Use \\n for line breaks if response is longer."
    )
    
    if ai_reply:
        ai_reply = _strip_markdown(ai_reply)
        _save_history(data, "user", message)
        _save_history(data, "assistant", ai_reply)
        session.data = data
        session.save()
        return _make(ai_reply)

    # Ask for destination
    return _make(
        "Which destination in India would you like to travel to?",
    )


def _handle_conv_date(session, message: str) -> dict:
    """
    Handle STAGE_CONV_DATE - ask for expected travel date using natural language understanding.
    Can extract date from cluttered responses and handle multiple information in one message.
    Uses current year (2026) for date extraction. Answers questions and re-asks for date.
    Has fallback logic when DeepSeek API fails.
    Handles option button selections.
    """
    data = session.data
    msg = _norm(message)
    current_year = datetime.now().year
    
    # Check if user selected an option
    if message.strip() in TRAVEL_DATE_OPTIONS:
        travel_date = message.strip()
        data["travel_date"] = travel_date
        data["travel_date_original"] = travel_date
        data["stage"] = STAGE_CONV_PERSONS
        session.data = data
        session.step = STAGE_CONV_PERSONS
        _save_session(session)
        
        reply = "How many people will be traveling?"
        return _make(reply, PERSONS_OPTIONS)
    
    try:
        # Use DeepSeek to extract travel date from natural language
        ai_reply = _deepseek(
            f"You are a helpful travel assistant for {COMPANY_SHORT}. "
            f"User said: \"{message}\"\n\n"
            f"Extract the expected travel date from their message. "
            f"The user might provide multiple pieces of information in one message. "
            f"Focus ONLY on the travel date/timing. "
            f"Current year is {current_year}. Use this year if the user mentions a month without a year. "
            f"Return ONLY the date in a simple format like 'Under 1 Month', 'Next week', 'August {current_year}', 'First week of August', 'in 2 weeks', etc. "
            f"If no date is mentioned, return 'NO_DATE'. "
            f"Be concise and natural."
        )
        
        if ai_reply and ai_reply.strip() != "NO_DATE":
            travel_date = _strip_markdown(ai_reply).strip()
            # Save both original input and extracted date
            data["travel_date"] = travel_date
            data["travel_date_original"] = message.strip()  # Save original customer input
            data["stage"] = STAGE_CONV_PERSONS
            session.data = data
            session.step = STAGE_CONV_PERSONS
            _save_session(session)
            
            reply = "How many people will be traveling?"
            return _make(reply, PERSONS_OPTIONS)
    except Exception as e:
        logger.error(f"[CONV DATE] DeepSeek API failed: {e}")
        # Fallback: use original message as date if it contains date-like content
        if len(message.strip()) >= 2:
            data["travel_date"] = message.strip()
            data["travel_date_original"] = message.strip()
            data["stage"] = STAGE_CONV_PERSONS
            session.data = data
            session.step = STAGE_CONV_PERSONS
            _save_session(session)
            
            reply = "How many people will be traveling?"
            return _make(reply, PERSONS_OPTIONS)
    
    # No date found - use DeepSeek to answer question and re-ask for date
    try:
        ai_reply = _deepseek(
            f"You are a helpful travel assistant for {COMPANY_SHORT}. "
            f"User asked: \"{message}\"\n\n"
            f"Answer their question in a simple, friendly way (1-2 sentences max). "
            f"Keep it short and conversational. No emojis. "
            f"After answering, ask: 'When are you planning to travel?' "
            f"Use \\n for line breaks if response is longer."
        )
        
        if ai_reply:
            ai_reply = _strip_markdown(ai_reply)
            _save_history(data, "user", message)
            _save_history(data, "assistant", ai_reply)
            session.data = data
            session.save()
            return _make(ai_reply, TRAVEL_DATE_OPTIONS)
    except Exception as e:
        logger.error(f"[CONV DATE] DeepSeek API failed for question: {e}")
    
    # Ask for date again with options
    return _make(
        "When are you planning to travel?",
        TRAVEL_DATE_OPTIONS
    )


def _handle_conv_persons(session, message: str) -> dict:
    """
    Handle STAGE_CONV_PERSONS - ask for number of persons using natural language understanding.
    Can extract number of persons from cluttered responses and handle multiple information in one message.
    Answers questions and re-asks for number of persons.
    Has fallback logic when DeepSeek API fails.
    Handles option button selections.
    Validates input to ensure it's about number of travelers.
    """
    data = session.data
    msg = _norm(message)
    
    # Check if user selected an option
    if message.strip() in PERSONS_OPTIONS:
        persons = message.strip()
        data["persons"] = persons
        data["persons_original"] = persons
        
        # Check if destination is featured and user is ready to book
        destination = data.get("destination", "").lower()
        seriousness = data.get("seriousness", "")
        is_featured = destination in [d.lower() for d in BEST_SELLER_PACKAGES.keys()]
        
        _create_travel_request(
            session,
            {
                "destination": data.get("destination", ""),
                "departure_date": data.get("travel_date", ""),
                "adults": _convert_persons_to_number(persons),
            },
            {"conversational_flow": True}
        )
        
        try:
            Lead.objects.get_or_create(
                session=session,
                defaults={
                    "name": data.get("_name", "WhatsApp User"),
                    "phone": session.phone_number or "",
                    "destination": data.get("destination", "Unknown"),
                },
            )
        except Exception:
            pass
        
        # Send summary message first
        date = data.get("travel_date_original", data.get("travel_date", "Not specified"))
        num_persons = data.get("persons_original", persons)
        seriousness = data.get("seriousness", "Not specified")
        
        summary_msg = (
            f"Thanks for sharing your travel details!\n\n"
            f"Destination: {data.get('destination', 'Unknown')}\n"
            f"Travel Date: {date}\n"
            f"Travelers: {num_persons}\n"
            f"Seriousness: {seriousness}\n\n"
        )
        
        # Check if destination has full itinerary
        full_itinerary = _get_full_itinerary(destination)
        if full_itinerary:
            # Append full itinerary to summary
            final_message = summary_msg + f"Here's the complete itinerary:\n\n{full_itinerary}\n\nI am connecting you with our travel expert for the further details."
            data["itinerary_sent"] = True
        else:
            # No itinerary available
            final_message = summary_msg + "Our Sales Agent will contact you soon with the best options."
        
        # Save to CRM
        _save_bot_reply_to_crm(session, final_message)
        
        # Mark lead as TODAY after summary message is saved to CRM
        # This applies to both widget users (who provided phone at beginning) and WhatsApp users
        try:
            mark_lead_today(session)
            session.refresh_from_db()
        except Exception as e:
            logger.error(f"[CONV FLOW TODAY] mark_lead_today failed: {e}")
        
        # Widget users now provide phone at beginning, so enable human takeover immediately
        # WhatsApp users also enable human takeover immediately
        data["stage"] = STAGE_CHAT
        data["_expert_contacted"] = True
        data["_followup_stopped"] = True
        session.data = data
        session.step = STAGE_CHAT
        session.is_human_takeover = True
        _save_session(session)
        
        return {
            "message": final_message,
            "options": [],
            "social_card": SOCIAL_CARD,
        }
    
    try:
        # First, validate if the message is about number of travelers
        validation_reply = _deepseek(
            f"You are a helpful travel assistant for {COMPANY_SHORT}. "
            f"User said: \"{message}\"\n\n"
            f"Is this message about the number of people/travelers? "
            f"Return 'YES' if it mentions number of people, travelers, persons, or group size. "
            f"Return 'NO' if it's about something else (questions, greetings, unrelated topics). "
            f"Be concise."
        )
        
        if validation_reply and validation_reply.strip() == "NO":
            # Input is not about number of travelers - ask again
            return _make(
                "Please enter or select the Expected Number of Travelers.",
                PERSONS_OPTIONS
            )
        
        # Use DeepSeek to extract number of persons from natural language
        ai_reply = _deepseek(
            f"You are a helpful travel assistant for {COMPANY_SHORT}. "
            f"User said: \"{message}\"\n\n"
            f"Extract the number of people traveling from their message. "
            f"The user might provide multiple pieces of information in one message. "
            f"Focus ONLY on the number of people/travelers. "
            f"Return the text as-is (e.g., '2 people', 'family of 4', '10 persons', 'Solo', 'Couple'). "
            f"If no number is mentioned, return 'NO_NUMBER'. "
            f"Be concise."
        )
        
        if ai_reply and ai_reply.strip() != "NO_NUMBER":
            # Save the extracted text as-is (no number conversion)
            persons = _strip_markdown(ai_reply).strip()
            if persons:
                # Save both extracted text and original input
                data["persons"] = persons
                data["persons_original"] = message.strip()  # Save original customer input
                
                # Create travel request
                _create_travel_request(
                    session,
                    {
                        "destination": data.get("destination", ""),
                        "departure_date": data.get("travel_date", ""),
                        "adults": persons,
                    },
                    {"conversational_flow": True}
                )
                
                # Create lead record
                try:
                    Lead.objects.get_or_create(
                        session=session,
                        defaults={
                            "name": data.get("_name", "WhatsApp User"),
                            "phone": session.phone_number or "",
                            "destination": data.get("destination", "Unknown"),
                        },
                    )
                except Exception:
                    pass
                
                # Build summary message using original customer input
                destination = data.get("destination", "Unknown")
                date = data.get("travel_date_original", data.get("travel_date", "Not specified"))  # Use original input
                num_persons = data.get("persons_original", persons)  # Use original input
                
                summary_msg = (
                    f"Thanks for sharing your travel details!\n\n"
                    f"Destination: {destination}\n"
                    f"Travel Date: {date}\n"
                    f"Travelers: {num_persons}\n\n"
                )
                
                # Check if we already have name and phone
                has_name = data.get("_name", "").strip() != ""
                has_phone = session.phone_number and session.phone_number.strip() != ""
                
                logger.info(f"[NAME PHONE CHECK] has_name={has_name}, has_phone={has_phone}, phone_number='{session.phone_number}', data_name='{data.get('_name', '')}', is_widget={is_widget}")
                logger.info(f"[NAME PHONE CHECK] Conversation flow complete, checking if name/phone needed")
                
                # For widget users, always ask for name/phone even if present to ensure proper flow
                # For WhatsApp users, only ask if missing
                if is_widget or not has_name or not has_phone:
                    # Ask for name and phone
                    if not has_name:
                        summary_msg += "To proceed, please share your name:"
                        data["_collecting_name"] = True
                        logger.info(f"[NAME PHONE CHECK] Setting _collecting_name=True")
                    elif not has_phone:
                        summary_msg += "To proceed, please share your WhatsApp number:"
                        data["_collecting_phone"] = True
                        logger.info(f"[NAME PHONE CHECK] Setting _collecting_phone=True")
                    
                    session.data = data
                    _save_session(session)
                    
                    logger.info(f"[NAME PHONE CHECK] Returning name/phone prompt")
                    return {
                        "message": summary_msg,
                        "options": [],
                        "social_card": SOCIAL_CARD,
                    }
                else:
                    # Already have name and phone (WhatsApp only), proceed to handoff
                    summary_msg += "Our Sales Agent will contact you soon with the best options."
                    
                    # Move to STAGE_CHAT and enable human takeover
                    data["stage"] = STAGE_CHAT
                    data["_expert_contacted"] = True
                    data["_followup_stopped"] = True
                    session.data = data
                    session.step = STAGE_CHAT
                    session.is_human_takeover = True
                    _save_session(session)
                    
                    logger.info(f"[CONV FLOW COMPLETE] dest={destination}, date={date}, persons={num_persons}, stage → STAGE_CHAT")
                    
                    return {
                        "message": summary_msg,
                        "options": [],  # No Plan New Trip button
                        "social_card": SOCIAL_CARD,
                    }
    except ValueError:
        pass
    except Exception as e:
        logger.error(f"[CONV PERSONS] DeepSeek API failed: {e}")
    
    # No valid number found - ask again
    return _make(
        "Please enter or select the Expected Number of Travelers.",
        PERSONS_OPTIONS
    )


def _answer_destination_question(message: str) -> str:
    """
    Answer user questions about destinations gently without emojis.
    Uses FAQ system for destination-related queries.
    """
    msg = _norm(message)
    
    # Check FAQ database first
    faq_answer = _get_faq_context(message)
    if faq_answer:
        # Remove emojis from FAQ answer
        import emoji
        clean_answer = emoji.replace_emoji(faq_answer, replace='')
        return clean_answer.strip()
    
    # Simple destination-based responses
    destination_keywords = {
        "goa": "Goa is known for its beautiful beaches, vibrant nightlife, and Portuguese heritage. It is a great destination for relaxation and water activities.",
        "kerala": "Kerala offers backwaters, hill stations, and beaches. It is perfect for nature lovers and those seeking a peaceful retreat.",
        "rajasthan": "Rajasthan is famous for its forts, palaces, and desert landscapes. It is ideal for history enthusiasts and cultural experiences.",
        "himachal": "Himachal Pradesh offers mountain landscapes, trekking, and scenic beauty. It is great for adventure seekers and nature lovers.",
        "kashmir": "Kashmir is known as paradise on earth with its beautiful valleys, lakes, and mountains. It is perfect for romantic getaways.",
        "delhi": "Delhi offers a mix of historical monuments and modern attractions. It is great for cultural experiences and shopping.",
        "mumbai": "Mumbai is the financial capital with Bollywood, beaches, and colonial architecture. It is ideal for urban experiences.",
        "bangalore": "Bangalore is known for its parks, tech hubs, and pleasant weather. It is great for city breaks and food lovers.",
    }
    
    for keyword, response in destination_keywords.items():
        if keyword in msg:
            return response
    
    return None


# ─────────────────────────────────────────────────────────────────────────────
# STAGE: CHAT (post-handoff)
# ─────────────────────────────────────────────────────────────────────────────

def _handle_stage_chat(session, message: str) -> dict:
    data = session.data
    msg  = _norm(message)

    new_trip_triggers = [
        "plan new trip", "new trip", "plan another",
        "different destination", "book another", "new destination",
    ]
    if any(t in msg for t in new_trip_triggers):
        new_data = _blank_session()
        new_data["_history"] = data.get("_history", [])
        new_data["stage"]    = STAGE_DESTINATION
        session.step         = STAGE_DESTINATION
        session.data         = new_data
        session.save()
        return _make("Where would you like to travel next?")

    # Check if user message contains travel details (destination, days, date)
    # This handles cases where user provides details without filling the form
    extracted = extract_travel_details(message)
    has_travel_details = any([
        extracted.get("destination"),
        extracted.get("days"),
        extracted.get("expected_date")
    ])
    
    if has_travel_details:
        # Try to handle as raw travel message
        raw_response = handle_raw_travel_message(session, message)
        # If it asked for missing details, return that
        if raw_response and not raw_response.get("options"):
            return raw_response
        # If it successfully processed the lead, return the summary
        if raw_response and "summary" in raw_response.get("message", "").lower():
            return raw_response

    # Removed mark_lead_new_lead - only using mark_lead_today for conversational flow

    _save_history(data, "user", message)
    reply = chat_response(message, data)
    _save_history(data, "assistant", reply)
    data["_chat_turn"] = data.get("_chat_turn", 0) + 1
    session.data       = data
    session.save()

    return {"message": reply, "options": ["Plan New Trip", "Talk to Expert"]}


# ─────────────────────────────────────────────────────────────────────────────
# WEBSITE BOOKINGS (quotation code TD-XXXXXX from www.trypdeals.com)
# ─────────────────────────────────────────────────────────────────────────────

def _handle_booking_code(session, message: str, code: str) -> dict:
    """
    The customer sent their website quotation code (the booking page and
    emails pre-fill it in the WhatsApp message). Reply with the booking
    details and the one or two things the team still needs, then hand the
    chat to the sales team.
    """
    from .website_bookings import (ESTIMATE_NOTE, fetch_remote_booking, find_booking,
                                   requirement_questions, summary_lines)

    booking = find_booking(session, code)
    if not booking:
        # Not in the CRM yet (e.g. its webhook failed): ask the website.
        booking = fetch_remote_booking(code)
        session.refresh_from_db()

    data = session.data
    _save_history(data, "user", message)

    if not booking:
        reply = (f"Thank you for sharing your booking ID {code}. We could not find it in our system right now. "
                 f"Our booking team will check it and reply to you here shortly.")
        _save_history(data, "assistant", reply)
        session.data = data
        session.save()
        return _handoff_with_message(session, reply)

    # Keep the booking on this chat even if it came in under another number.
    bookings = data.get("website_bookings") or {}
    bookings.setdefault(code, booking)
    data["website_bookings"] = bookings
    data["active_booking_code"] = code

    first = (booking.get("name") or "").split(" ")[0]
    status = booking.get("paymentStatus") or "pending"
    lines = [f"Thank you{', ' + first if first else ''}. Here are the details of your booking {code}:", ""]
    lines += summary_lines(booking, for_customer=True)
    if any("*" in l for l in lines):
        lines += ["", ESTIMATE_NOTE]
    if status in ("pending", "failed"):
        lines += ["", "You can complete the advance payment from the booking page, or our team will help you here."]
    questions = requirement_questions(booking)
    lines += ["", "To plan everything properly, please tell us:"]
    lines += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
    lines += ["", "Our booking team is now connected to this chat and will reply here."]
    reply = "\n".join(lines)

    _save_history(data, "assistant", reply)
    session.data = data
    session.save()
    return _handoff_with_message(session, reply)


def _handoff_with_message(session, reply: str) -> dict:
    """Hand the chat to the sales team (assign + human mode) but send `reply`."""
    response = handle_lead_handoff(session)
    response["message"] = _strip_markdown(reply)
    response["options"] = []
    return response


# ─────────────────────────────────────────────────────────────────────────────
# MAIN MENU (greeting): Book a Tour / Cab Enquiry / My Booking
# ─────────────────────────────────────────────────────────────────────────────

MENU_TOUR    = "Book a Tour"
MENU_CAB     = "Cab Enquiry"
MENU_BOOKING = "My Booking"
MAIN_MENU_OPTIONS = [MENU_TOUR, MENU_CAB, MENU_BOOKING]

_MENU_WORDS = {
    "tour":    {"book a tour", "book tour", "tour booking", "book a trip", "tour package", "tour packages"},
    "cab":     {"cab enquiry", "cab inquiry", "cab", "taxi", "book a cab", "cab booking", "book cab", "car rental"},
    "booking": {"my booking", "booking enquiry", "booking inquiry", "recent booking", "booking status", "my bookings"},
}

# Data that must survive starting a new flow (website bookings, ad lead forms).
_KEEP_KEYS = ("_history", "website_bookings", "website_booking", "website_booking_card",
              "active_booking_code", "google_ads", "meta_ads")


def _fresh_data(data: dict) -> dict:
    new_data = _blank_session()
    for k in _KEEP_KEYS:
        if k in data:
            new_data[k] = data[k]
    return new_data


def _menu_choice(message: str, stage: int):
    m = _norm(message).strip(" .!?")
    if stage == STAGE_MENU and m in ("1", "2", "3"):
        return {"1": "tour", "2": "cab", "3": "booking"}[m]
    for key, words in _MENU_WORDS.items():
        if m in words:
            return key
    return None


def _main_menu(session) -> dict:
    data = session.data
    name = (session.user_name or "").strip()
    first = name.split(" ")[0] if name and not name.replace("+", "").isdigit() else ""
    reply = (f"Hi{' ' + first if first else ''}! Welcome to {COMPANY_SHORT}.\n\n"
             f"How can we help you today?\n"
             f"1. {MENU_TOUR}\n"
             f"2. {MENU_CAB}\n"
             f"3. {MENU_BOOKING} (ask about a recent booking)")
    data["welcome_sent"] = True
    data["stage"] = STAGE_MENU
    session.step = STAGE_MENU
    session.data = data
    _save_session(session)
    return _make(reply, MAIN_MENU_OPTIONS)


def _start_menu_choice(session, choice: str, message: str) -> dict:
    data = _fresh_data(session.data)
    data["welcome_sent"] = True
    _save_history(data, "user", message)

    if choice == "tour":
        data["stage"] = STAGE_CONV_DESTINATION
        reply = "Our travel agents will help you plan the perfect trip.\n\nWhich destination in India would you like to visit?"
    elif choice == "cab":
        data["stage"] = STAGE_CAB_FROM
        data["cab_enquiry"] = {}
        reply = "Sure, we will help you book a cab.\n\nWhich city will you start from (pickup city)?"
    else:
        data["stage"] = STAGE_BOOKING_ID
        data["_booking_id_tries"] = 0
        reply = ("Sure. Please share your booking ID.\n\n"
                 "It looks like TD-XXXXXX and is in your booking email and on the payment page.")

    _save_history(data, "assistant", reply)
    session.step = data["stage"]
    session.data = data
    _save_session(session)
    return _make(reply)


def _handle_cab_stage(session, message: str, stage: int) -> dict:
    data = session.data
    cab = data.get("cab_enquiry") or {}
    text = re.sub(r"\s+", " ", message).strip()[:80]
    _save_history(data, "user", message)

    if stage == STAGE_CAB_FROM:
        both = re.match(r"(?i)^(?:from\s+)?(.+?)\s+to\s+(.+)$", text)
        if both:
            cab["from"], cab["to"] = both.group(1).strip().title(), both.group(2).strip().title()
            data["stage"] = STAGE_CAB_PAX
            reply = "How many people will travel (adults and children)?"
        else:
            cab["from"] = text.title()
            data["stage"] = STAGE_CAB_TO
            reply = "And where do you want to go (destination city)?"
    elif stage == STAGE_CAB_TO:
        cab["to"] = text.title()
        data["stage"] = STAGE_CAB_PAX
        reply = "How many people will travel (adults and children)?"
    else:
        cab["travellers"] = text
        data["cab_enquiry"] = cab
        session.data = data
        _save_session(session)
        return _finish_cab_enquiry(session)

    data["cab_enquiry"] = cab
    _save_history(data, "assistant", reply)
    session.step = data["stage"]
    session.data = data
    _save_session(session)
    return _make(reply)


def _finish_cab_enquiry(session) -> dict:
    """Save the cab enquiry on the lead + a note, then hand over to the sales team."""
    from .models import InternalNote
    data = session.data
    cab = data.get("cab_enquiry") or {}
    pax = cab.get("travellers", "")
    count = re.search(r"\d+", pax)
    summary = f"Cab enquiry: {cab.get('from', '?')} to {cab.get('to', '?')}, {pax or '?'} traveller(s)"

    try:
        lead, _ = Lead.objects.get_or_create(
            session=session,
            defaults={"full_name": session.user_name or None, "phone": session.phone_number or "",
                      "source": "whatsapp", "status": "new", "priority": "medium"},
        )
        lead.departure_city = (cab.get("from") or "")[:255] or lead.departure_city
        lead.destination = (cab.get("to") or "")[:255] or lead.destination
        if count:
            lead.travellers = int(count.group(0))
        lead.notes = (f"{lead.notes}\n{summary}" if lead.notes else summary)[:5000]
        lead.save()
        InternalNote.objects.create(session=session, added_by=None, note=f"{summary} (collected by the bot)")
    except Exception as exc:
        logger.error(f"[CAB ENQUIRY] could not save lead: {exc}")

    data["destination"] = cab.get("to", "")
    data["lead_category"] = "cab"  # routed by Admin -> Lead category rules
    session.current_destination = (cab.get("to") or "")[:255]
    session.data = data
    _save_session(session)

    reply = (f"Thank you! Here is your cab enquiry:\n"
             f"From: {cab.get('from', '-')}\n"
             f"To: {cab.get('to', '-')}\n"
             f"Travellers: {pax or '-'}\n\n"
             f"Our cab expert is now connected to this chat and will share the best fare and vehicle options shortly.")
    _save_history(data, "assistant", reply)
    return _handoff_with_message(session, reply)


def _handle_booking_id_stage(session, message: str) -> dict:
    """Waiting for a TD-XXXXXX code (a message with a code is handled before this)."""
    data = session.data
    tries = data.get("_booking_id_tries", 0) + 1
    data["_booking_id_tries"] = tries
    _save_history(data, "user", message)
    if tries >= 2:
        reply = "No problem. Our booking team is now connected to this chat and will help you find your booking."
        _save_history(data, "assistant", reply)
        session.data = data
        _save_session(session)
        return _handoff_with_message(session, reply)
    reply = ("That does not look like a booking ID. Please send it in this format: TD-XXXXXX "
             "(for example TD-7K3M9P). You can find it in your booking email.")
    _save_history(data, "assistant", reply)
    session.data = data
    _save_session(session)
    return _make(reply, ["Talk to Expert"])


# ─────────────────────────────────────────────────────────────────────────────
# CHAT ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def chat_response(user_message: str, data: dict) -> str:
    if _is_hard_block(user_message):
        return "We can only assist with travel planning and trip-related queries."
    if _is_international(user_message):
        return f"{COMPANY_SHORT} focuses exclusively on domestic India travel."

    if any(re.search(p, _norm(user_message)) for p in _MEAL_PRICE_PATTERNS):
        return _handle_meal_price_query()

    faq_context  = _get_faq_context(user_message)
    trip_context = _session_context_str(data)
    history      = _history_str(data)
    faq_block    = f"\nRELEVANT INFO:\n{faq_context}\n" if faq_context else ""

    # Real packages from www.trypdeals.com that match the message / destination,
    # and the customer's website booking if they have one.
    tours_block = booking_block = ""
    try:
        from .website_tours import tours_context
        dest = data.get("confirmed_destination") or data.get("destination") or ""
        tours = tours_context(user_message, dest)
        if tours:
            tours_block = f"\nMATCHING TOURS ON OUR WEBSITE (use only these, with the exact price and link):\n{tours}\n"
    except Exception as exc:
        logger.warning(f"[CHAT] website tours unavailable: {exc}")
    try:
        from .website_bookings import booking_context, find_booking
        code = data.get("active_booking_code")
        booking = (data.get("website_bookings") or {}).get(code) if code else data.get("website_booking")
        if booking:
            booking_block = f"\nCUSTOMER'S WEBSITE BOOKING:\n{booking_context(booking)}\n"
    except Exception as exc:
        logger.warning(f"[CHAT] booking context unavailable: {exc}")

    prompt = (f"You are a travel consultant at {COMPANY_SHORT} ({COMPANY_NAME}).\n"
              f"RULES: Plain text only. No asterisks. No markdown. No emojis. Professional English only.\n"
              f"Do NOT start with 'Great!', 'Sure!', or 'Of course!' Be direct and concise.\n"
              f"IMPORTANT: If the user asks about meal price, food cost, or lunch/dinner cost, "
              f"always reply: Meals are not included in the package. Approximately Rs. 300 or more "
              f"per meal per person at local restaurants near sightseeing areas.\n"
              f"COMPANY INFO: Office: {COMPANY_ADDRESS}\n"
              f"TRIP CONTEXT: {trip_context}\n"
              f"{booking_block}"
              f"{tours_block}"
              f"{faq_block}"
              f"RECENT CONVERSATION:\n{history}\n"
              f'USER MESSAGE: "{user_message}"\n'
              f"HOW TO REPLY:\n"
              f"1. Answer the question first in 2-4 lines. If matching tours are listed and relevant, suggest "
              f"one or two of them with their price and link. Never invent prices, packages or links.\n"
              f"2. Prices are estimates; the final amount is confirmed after discussing the full requirements.\n"
              f"3. Then ask one or two short questions to collect the customer's requirements, only for details "
              f"not already known from the trip context, booking or conversation: travel date, number of adults "
              f"and children, starting city, budget or hotel category, and for booked trips the pickup point or "
              f"special needs. Number the questions if there are two.")

    reply = _deepseek(prompt)
    return (_strip_markdown(reply) if reply else
            "Please provide more details so I can assist you accurately.")


# ─────────────────────────────────────────────────────────────────────────────
# FOLLOW-UP ENGINE
# ─────────────────────────────────────────────────────────────────────────────

FOLLOWUP_MESSAGES = {
    1: ("We'd love to hear about your experience! Please leave us a review on our Google Business Profile: "
        "https://g.page/r/CWVfCkThNtBNEBM/review"),
    2: ("Visit our website for amazing travel deals and packages: "
        "https://www.trypdeals.com/"),
    3: ("Explore our YouTube channel for travel tips, destination guides, and more: "
        "https://www.youtube.com/channel/UC7OhVnGISPDQ9cQ_T-x_1gw/"),
}

FOLLOWUP_INTERVALS_MINUTES = {1: 10, 2: 90, 3: 270}

BEST_SELLER_FOLLOWUP_MESSAGE = (
    "Just following up on the package we sent. "
    "Our team is available to answer any questions or help you book. "
    "Would you like to connect with a travel expert?"
)


def get_pending_followup(session) -> str | None:
    data = session.data
    if data.get("_followup_stopped"):
        return None

    stage = data.get("stage", STAGE_IDLE)
    if stage == STAGE_BEST_SELLER_SENT:
        bs_ts = data.get("_best_seller_sent_ts")
        if bs_ts:
            try:
                sent_dt      = datetime.fromisoformat(bs_ts)
                minutes_idle = (datetime.utcnow() - sent_dt).total_seconds() / 60
                if minutes_idle >= BEST_SELLER_FOLLOWUP_MINUTES:
                    return BEST_SELLER_FOLLOWUP_MESSAGE
            except Exception:
                pass
        return None

    if not data.get("_itinerary_sent"):
        return None
    last_active = data.get("_last_active_ts")
    if not last_active:
        return None
    try:
        last_dt = datetime.fromisoformat(last_active)
    except Exception:
        return None
    minutes_idle  = (datetime.utcnow() - last_dt).total_seconds() / 60
    last_followup = data.get("_last_followup_sent", 0)
    for level in [1, 2, 3, 4]:
        if last_followup < level and minutes_idle >= FOLLOWUP_INTERVALS_MINUTES[level]:
            return FOLLOWUP_MESSAGES[level]
    return None


def record_followup_sent(session, level: int) -> None:
    session.data["_last_followup_sent"] = level
    session.save(update_fields=["data"])


def record_best_seller_followup_sent(session) -> None:
    """
    Called by the scheduler after the best seller follow-up message is sent.
    Removed mark_lead_follow_up - only using mark_lead_today for conversational flow.
    """
    # Removed mark_lead_follow_up - only using mark_lead_today for conversational flow
    data = session.data
    data["_followup_stopped"] = True
    data["stage"]             = STAGE_CHAT
    data["_expert_contacted"] = True
    session.data              = data
    session.step              = STAGE_CHAT
    _save_session(session)
    logger.info(f"[BEST SELLER FOLLOWUP] Session {session.id} handed off after 10-min idle.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT — generate_response()
# ─────────────────────────────────────────────────────────────────────────────

def generate_response(message: str, session, is_widget: bool = False) -> dict:
    """
    Central message handler for all incoming WhatsApp messages.

    v18.0.0 routing:
      Best-seller destination → teaser + full itinerary → [Send Full Itinerary | Modify | Talk to Expert]
      Non-best-seller         → Basic Travel Flow form  → agent handoff with details
      Any "Modify" after best-seller → Basic Travel Flow form → agent handoff with details
    
    Args:
        message: User message text
        session: ChatSession object
        is_widget: Whether this request is from the widget (default False for WhatsApp)
    """
    if message == "__FLOW_SUBMITTED__":
        return _make("Form received. Processing your request.", [])

    data = session.data
    _update_last_active(session)

    if _should_stop_followup(message):
        data["_followup_stopped"] = True

    if "stage" not in data:
        data["stage"] = getattr(session, "step", STAGE_IDLE)

    current_stage = data.get("stage", STAGE_IDLE)
    intent        = classify_intent(message, current_stage, data)

    logger.debug(
        f"[GENERATE_RESPONSE] msg={message[:60]!r}, stage={_stage_name(current_stage)}, intent={intent}")

    # ── Website quotation code (TD-XXXXXX) ───────────────────────────────────
    # The website pre-fills it in the WhatsApp message after an online booking.
    from .website_bookings import code_in
    booking_code = code_in(message)
    if booking_code and intent != INTENT_EXPERT:
        response = _handle_booking_code(session, message, booking_code)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    # ── Main menu choice / cab enquiry / booking ID steps ────────────────────
    menu_choice = _menu_choice(message, current_stage)
    if menu_choice:
        response = _start_menu_choice(session, menu_choice, message)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response
    if current_stage == STAGE_MENU and intent not in (INTENT_EXPERT, INTENT_GREETING):
        # Typed a place instead of tapping a menu option: start the tour flow there.
        detected = detect_destination_in_message(message)
        if detected:
            new_data = _fresh_data(data)
            new_data["welcome_sent"] = True
            new_data["destination"] = detected
            new_data["stage"] = STAGE_CONV_SERIOUSNESS
            session.step = STAGE_CONV_SERIOUSNESS
            session.current_destination = detected
            session.data = new_data
            _save_session(session)
            reply = f"Great! I see you're interested in {detected.title()}.\n\nWhat's your current planning status for this trip?"
            _save_bot_reply_to_crm(session, reply)
            return _make(reply, SERIOUSNESS_OPTIONS)
    if intent not in (INTENT_EXPERT, INTENT_GREETING):
        if current_stage in (STAGE_CAB_FROM, STAGE_CAB_TO, STAGE_CAB_PAX):
            response = _handle_cab_stage(session, message, current_stage)
            _save_bot_reply_to_crm(session, response.get("message", ""))
            return response
        if current_stage == STAGE_BOOKING_ID:
            response = _handle_booking_id_stage(session, message)
            _save_bot_reply_to_crm(session, response.get("message", ""))
            return response

    # ── Hard blocks ───────────────────────────────────────────────────────────
    if _is_hard_block(message):
        reply = "We can only assist with travel planning and trip-related queries."
        _save_bot_reply_to_crm(session, reply)
        return _make(reply)

    if _is_international(message):
        reply = (f"{COMPANY_SHORT} specialises in domestic India travel only. "
                 f"Which Indian destination would you like to explore?")
        _save_bot_reply_to_crm(session, reply)
        return _make(reply)

    # ── Universal intents (work at any stage) ─────────────────────────────────
    if intent == INTENT_COMPANY:
        reply = _handle_company_info(message)
        _save_history(data, "user", message)
        _save_history(data, "assistant", reply)
        session.data = data
        session.save()
        _save_bot_reply_to_crm(session, reply)
        return _make(reply, ["Plan My Trip"])

    if intent == INTENT_MEAL_PRICE:
        reply = _handle_meal_price_query()
        _save_history(data, "user", message)
        _save_history(data, "assistant", reply)
        session.data = data
        session.save()
        _save_bot_reply_to_crm(session, reply)
        return _make(reply, ["Plan My Trip"])

    if intent == INTENT_GREETING:
        # Check if user has already submitted form data - don't reset if they have
        has_form_data = bool(data.get("destination") or data.get("days") or 
                          data.get("confirmed_destination") or 
                          _get_active_travel_request(session))
        
        if has_form_data:
            # Already planning something: show the main menu, keep the details.
            _save_history(data, "user", message)
            session.data = data
            response = _main_menu(session)
            _save_bot_reply_to_crm(session, response.get("message", ""))
            return response
        
        # Check if the greeting message contains a destination
        detected_destination = detect_destination_in_message(message)
        
        if detected_destination:
            # Destination found in message - set it and move to next stage
            new_data = _blank_session()
            new_data["welcome_sent"] = True
            new_data["destination"] = detected_destination
            new_data["stage"] = STAGE_CONV_SERIOUSNESS
            session.step = STAGE_CONV_SERIOUSNESS
            session.current_destination = detected_destination
            session.data = new_data
            session.save()
            
            reply = f"Great! I see you're interested in {detected_destination.title()}.\n\nWhat's your current planning status for this trip?"
            _save_bot_reply_to_crm(session, reply)
            return _make(reply, SERIOUSNESS_OPTIONS)
        else:
            # Plain greeting: main menu (Book a Tour / Cab Enquiry / My Booking)
            session.data = _fresh_data(data)
            _save_history(session.data, "user", message)
            response = _main_menu(session)
            _save_bot_reply_to_crm(session, response.get("message", ""))
            return response

    if intent == INTENT_NEW_ENQUIRY:
        # Check if user has already submitted form data - don't reset if they have
        has_form_data = bool(data.get("destination") or data.get("days") or 
                          data.get("confirmed_destination") or 
                          _get_active_travel_request(session))
        
        # If user explicitly clicked "Plan New Trip", force reset regardless of existing data
        msg_normalized = _norm(message)
        if "plan new trip" in msg_normalized or "plan my trip" in msg_normalized:
            # Force reset and start fresh
            new_data = _blank_session()
            new_data["welcome_sent"] = True
            new_data["_history"] = data.get("_history", [])
            new_data["stage"] = STAGE_CONV_DESTINATION
            session.step = STAGE_CONV_DESTINATION
            session.data = new_data
            session.save()
            reply = "Our travel agents will help you plan the perfect trip.\n\nWhich destination in India would you like to visit?"
            _save_bot_reply_to_crm(session, reply)
            return _make(reply)
        
        if has_form_data:
            # User already has form data, ask if they want to plan a new trip
            reply = "Would you like to plan a new trip, or do you have questions about your current travel request?"
            _save_history(data, "user", message)
            _save_history(data, "assistant", reply)
            session.data = data
            session.save()
            _save_bot_reply_to_crm(session, reply)
            return _make(reply, ["Plan New Trip", "Talk to Expert"])
        
        # Check if the new enquiry message contains a destination
        detected_destination = detect_destination_in_message(message)
        
        if detected_destination:
            # Destination found in message - set it and move to next stage
            new_data = _blank_session()
            new_data["welcome_sent"] = True
            new_data["_history"] = data.get("_history", [])
            new_data["destination"] = detected_destination
            new_data["stage"] = STAGE_CONV_SERIOUSNESS
            session.step = STAGE_CONV_SERIOUSNESS
            session.current_destination = detected_destination
            session.data = new_data
            session.save()
            
            reply = f"Great! I see you're interested in {detected_destination.title()}.\n\nWhat's your current planning status for this trip?"
            _save_bot_reply_to_crm(session, reply)
            return _make(reply, SERIOUSNESS_OPTIONS)
        else:
            # No destination found - send welcome message asking for destination
            new_data = _blank_session()
            new_data["welcome_sent"] = True
            new_data["_history"] = data.get("_history", [])
            new_data["stage"] = STAGE_CONV_DESTINATION
            session.step = STAGE_CONV_DESTINATION
            session.data = new_data
            session.save()
            reply = "Our travel agents will help you plan the perfect trip.\n\nWhich destination in India would you like to visit?"
            _save_bot_reply_to_crm(session, reply)
            return _make(reply)

    if intent == INTENT_EXPERT:
        # Removed mark_lead_follow_up - only using mark_lead_today for conversational flow
        response = handle_lead_handoff(session)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    if intent == INTENT_DISCOUNT and data.get("confirmed_destination"):
        result = _handle_discount_request(message, data)
        session.data = data
        _save_session(session)
        _save_bot_reply_to_crm(session, result.get("message", ""))
        return result

    # ── First-contact welcome ─────────────────────────────────────────────────
    # For widget users, handle first message (destination selection) specially
    if is_widget and not data.get("welcome_sent"):
        # Widget user's first message - should be a destination from the options
        detected_destination = detect_destination_in_message(message)
        
        if detected_destination:
            # Destination found in message - set it and move to next stage
            data["welcome_sent"] = True
            data["destination"] = detected_destination
            data["stage"] = STAGE_CONV_SERIOUSNESS
            session.step = STAGE_CONV_SERIOUSNESS
            session.current_destination = detected_destination
            session.data = data
            _save_session(session)
            
            reply = f"Great! I see you're interested in {detected_destination.title()}.\n\nWhat's your current planning status for this trip?"
            _save_bot_reply_to_crm(session, reply)
            return _make(reply, SERIOUSNESS_OPTIONS)
        else:
            # User typed something else - still set welcome_sent and ask for destination
            data["welcome_sent"] = True
            data["stage"] = STAGE_CONV_DESTINATION
            session.data = data
            session.step = STAGE_CONV_DESTINATION
            _save_session(session)
            
            reply = "Which destination in India would you like to visit?"
            _save_bot_reply_to_crm(session, reply)
            return _make(reply)
    
    # Skip first-contact welcome for WhatsApp users (original logic)
    if not is_widget and not data.get("welcome_sent"):
        # Check if the first message contains a destination
        detected_destination = detect_destination_in_message(message)
        
        if detected_destination:
            # Destination found in message - set it and move to next stage
            data["welcome_sent"] = True
            data["destination"] = detected_destination
            data["stage"] = STAGE_CONV_SERIOUSNESS
            session.step = STAGE_CONV_SERIOUSNESS
            session.current_destination = detected_destination
            session.data = data
            _save_session(session)
            
            reply = f"Great! I see you're interested in {detected_destination.title()}.\n\nWhat's your current planning status for this trip?"
            _save_bot_reply_to_crm(session, reply)
            return _make(reply, SERIOUSNESS_OPTIONS)
        else:
            # No destination found - acknowledge user's response and ask for destination
            data["welcome_sent"] = True
            data["stage"] = STAGE_CONV_DESTINATION
            session.data = data
            session.step = STAGE_CONV_DESTINATION
            _save_session(session)
            
            # Check if user said yes/no to the planning question
            msg_lower = message.lower()
            if any(word in msg_lower for word in ["yes", "yeah", "sure", "definitely", "absolutely", "of course"]):
                reply = "Great! Which destination in India would you like to visit?"
            elif any(word in msg_lower for word in ["no", "not", "maybe", "just browsing"]):
                reply = "No problem! Feel free to explore. If you'd like to plan a trip later, just let me know which destination in India interests you."
            else:
                # Generic response - ask for destination
                reply = "Which destination in India would you like to visit?"
            
            _save_bot_reply_to_crm(session, reply)
            return _make(reply)

    # ── Destination detection (for stages where destination not yet set) ───────
    _dest_detection_stages = {
        STAGE_IDLE, STAGE_DESTINATION, STAGE_CHAT,
        STAGE_POST_ITINERARY, STAGE_BEST_SELLER_SENT,
    }
    # For widget users, don't run destination detection in STAGE_CONV_SERIOUSNESS
    # since we already handled their destination selection in the first-contact logic
    # Also skip destination detection in STAGE_IDLE for widget users on first message
    if not is_widget:
        _dest_detection_stages.add(STAGE_CONV_SERIOUSNESS)
    
    # Skip destination detection for widget users on their first message (welcome_sent is False)
    # to prevent best-seller package flow from overriding conversational flow
    if is_widget and not data.get("welcome_sent"):
        logger.info(f"[WIDGET FIRST MESSAGE] Skipping destination detection, will be handled by first-contact logic")
    elif (current_stage in _dest_detection_stages
            and not data.get("confirmed_destination")
            and intent not in (INTENT_EXPERT, INTENT_GREETING, INTENT_NEW_ENQUIRY,
                               INTENT_COMPANY, INTENT_MEAL_PRICE, INTENT_DISCOUNT)):
        detected = detect_destination_in_message(message)
        if detected:
            bs_key = _get_best_seller_key(detected)
            if bs_key:
                logger.info(f"[DEST DETECT] Found '{detected}' → best seller key '{bs_key}'")
                response = _send_best_seller_package(session, bs_key)
                # Note: _save_bot_reply_to_crm is already called inside _send_best_seller_package
                return response
            else:
                # Non-best-seller detected destination
                corrected = autocorrect_destination(detected)
                response  = _handle_destination_flow_sent(session, corrected)
                _save_bot_reply_to_crm(session, response.get("message", ""))
                return response

    # ── Stage: BEST_SELLER_SENT ───────────────────────────────────────────────
    if current_stage == STAGE_BEST_SELLER_SENT:
        response = _handle_stage_best_seller_sent(session, message, intent)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    # ── Stage: DESTINATION ───────────────────────────────────────────────────
    if current_stage == STAGE_DESTINATION:
        response = _handle_destination_collection(session, message)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    # ── Stage: IDLE ───────────────────────────────────────────────────────────
    if current_stage == STAGE_IDLE:
        # Check if user message contains travel details (destination, days, date)
        # This handles cases where new user provides details without going through form
        extracted = extract_travel_details(message)
        has_travel_details = any([
            extracted.get("destination"),
            extracted.get("days"),
            extracted.get("expected_date")
        ])
        
        if has_travel_details and len(message.strip()) >= 3:
            # Try to handle as raw travel message
            raw_response = handle_raw_travel_message(session, message)
            # If it asked for missing details, return that
            if raw_response and not raw_response.get("options"):
                _save_bot_reply_to_crm(session, raw_response.get("message", ""))
                return raw_response
            # If it successfully processed the lead, return the summary
            if raw_response and "summary" in raw_response.get("message", "").lower():
                _save_bot_reply_to_crm(session, raw_response.get("message", ""))
                return raw_response
        
        # Normal flow: ask for destination
        if len(message.strip()) >= 3:
            data["stage"] = STAGE_DESTINATION
            session.data  = data
            session.step  = STAGE_DESTINATION
            _save_session(session)
            response = _handle_destination_collection(session, message)
            _save_bot_reply_to_crm(session, response.get("message", ""))
            return response
        reply = "Which destination in India would you like to travel to?"
        _save_bot_reply_to_crm(session, reply)
        return _make(reply)

    # ── Stage: FLOW_SENT (legacy - redirect to conversational flow) ───────────
    if current_stage == STAGE_FLOW_SENT:
        # Legacy stage - redirect to conversational flow
        logger.info(f"[STAGE_FLOW_SENT] Legacy stage detected - redirecting to conversational flow")
        
        # Move to conversational destination stage
        data["stage"] = STAGE_CONV_DESTINATION
        session.data = data
        session.step = STAGE_CONV_DESTINATION
        _save_session(session)
        
        # Route to conversational destination handler
        response = _handle_conv_destination(session, message)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    # ── Stage: CONVERSATIONAL FLOW ────────────────────────────────────────────
    if current_stage == STAGE_CONV_DESTINATION:
        response = _handle_conv_destination(session, message)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response
    
    if current_stage == STAGE_CONV_SERIOUSNESS:
        response = _handle_conv_seriousness(session, message)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response
    
    if current_stage == STAGE_CONV_DATE:
        response = _handle_conv_date(session, message)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response
    
    if current_stage == STAGE_CONV_PERSONS:
        response = _handle_conv_persons(session, message)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    # ── Stage: CHAT (post-handoff) ────────────────────────────────────────────
    if current_stage == STAGE_CHAT:
        _save_history(data, "user", message)
        session.data = data
        response = _handle_stage_chat(session, message)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    # ── Legacy stages (sessions created before v18.0.0) ──────────────────────
    # For any pre-existing sessions stuck in old stages, guide them to the form.
    if current_stage in (STAGE_PACKAGE, STAGE_CUSTOM_FLOW_SENT, STAGE_ITINERARY_REVIEW,
                         STAGE_MODIFY, STAGE_TICKET_CHECK, STAGE_POST_ITINERARY,
                         STAGE_GROUP_TOUR_CHOICE, STAGE_GROUP_TOUR_DATE,
                         STEP_MODIFY_CHOICE, STEP_MODIFY_DAYS,
                         STEP_MODIFY_DESTINATION, STEP_MODIFY_DAY_WISE,
                         STEP_MODIFY_FREE, STEP_CUSTOMIZE, STEP_CONFIRM):

        dest = data.get("confirmed_destination") or data.get("destination")

        # If user asks to talk to expert, just hand off
        if intent == INTENT_EXPERT or _is_lead_trigger(message):
            response = handle_lead_handoff(session)
            _save_bot_reply_to_crm(session, response.get("message", ""))
            return response

        # Otherwise re-engage with the flow form
        data["stage"]      = STAGE_FLOW_SENT
        data["_flow_sent"] = True
        session.data       = data
        session.step       = STAGE_FLOW_SENT
        _save_session(session)

        reply_msg = (
            "To help our travel expert assist you, please fill in your travel details."
            if not dest else
            f"To help our travel expert customise your {dest} trip, please fill in your travel details."
        )
        response = _make(reply_msg, [], flow_payload=build_basic_travel_flow())
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    # ── Fallback ──────────────────────────────────────────────────────────────
    _save_history(data, "user", message)
    reply = chat_response(message, data)
    _save_history(data, "assistant", reply)
    session.data = data
    session.save()
    _save_bot_reply_to_crm(session, reply)
    return _make(reply, ["Plan My Trip"])


# ─────────────────────────────────────────────────────────────────────────────
# STATIC DATA
# ─────────────────────────────────────────────────────────────────────────────

FEATURED_DESTINATIONS = [
    "Somnath", "Mallikarjun", "Mahakaleshwar", "Omkareshwar", "Kedarnath",
    "Bhimashankar", "Kashi Vishwanath", "Trimbakeshwar",
    "Rameshwaram", "Other (Please Specify)",
]

TRAVEL_DATE_OPTIONS = [
    "Next Week",
    "After 15 Days",
    "Next Month",
    "After 2 Month",
    "After 3 Month",
    "Not Decided",
]

PERSONS_OPTIONS = [
    "Solo",
    "Couple",
    "More than 2",
]

SERIOUSNESS_OPTIONS = [
    "Just Exploring",
    "Planning Trip",
    "Ready to Book",
]

def _convert_persons_to_number(persons_str: str) -> int:
    """
    Convert persons string option to numeric value for database.
    """
    persons_map = {
        "Solo": 1,
        "Couple": 2,
        "More than 2": 3,
    }
    return persons_map.get(persons_str, 2)  # Default to 2 if unknown


def _get_full_itinerary(destination: str) -> str:
    """
    Get full itinerary for a destination (case-insensitive).
    Returns empty string if not found.
    """
    dest_lower = destination.lower()
    return BEST_SELLER_FULL_ITINERARIES.get(dest_lower, "")

INTERNATIONAL_DESTINATIONS = [
    "dubai", "bali", "thailand", "singapore", "maldives", "bhutan",
    "nepal", "europe", "usa", "uk", "paris", "london", "new york",
    "malaysia", "vietnam", "sri lanka", "indonesia", "turkey", "greece",
    "japan", "australia", "canada", "italy", "spain", "france",
    "new zealand", "south africa", "egypt", "switzerland", "germany",
    "china", "hong kong", "taiwan", "south korea", "russia", "brazil",
    "mexico", "argentina", "peru", "kenya", "tanzania", "morocco",
    "portugal", "netherlands", "belgium", "sweden", "norway", "finland",
    "denmark", "austria", "czech republic", "poland", "hungary", "croatia",
    "georgia", "armenia", "azerbaijan", "uzbekistan", "cambodia",
    "laos", "myanmar", "philippines", "fiji", "seychelles", "mauritius",
    "zanzibar", "oman", "qatar", "bahrain", "kuwait", "jordan", "israel",
    "abu dhabi", "doha", "muscat",
]

HARD_BLOCK_PATTERNS = [
    r"\bhack\b", r"\bmalware\b", r"\bvirus\b", r"\bporn\b", r"\bsex\b",
    r"\bweapon\b", r"\bdrug\b", r"\bkill\b", r"\bsuicide\b",
    r"\bcode\b.*\bpython\b", r"\bdjango\b", r"\bjavascript\b",
    r"\bhtml\b", r"\bcss\b",
]

VALID_DESTINATIONS = [
    "Andaman", "Port Blair", "Havelock Island", "Neil Island", "Baratang Island",
    "Andhra Pradesh", "Visakhapatnam", "Araku Valley", "Tirupati", "Vijayawada",
    "Rajahmundry", "Nagarjuna Sagar", "Srikalahasti", "Lepakshi",
    "Arunachal Pradesh", "Tawang", "Ziro", "Dirang", "Bomdila", "Namdapha",
    "Mechuka", "Along", "Pasighat",
    "Assam", "Guwahati", "Kaziranga", "Majuli", "Jorhat", "Tezpur",
    "Haflong", "Silchar", "Sibsagar",
    "Bihar", "Patna", "Bodh Gaya", "Nalanda", "Rajgir", "Vaishali",
    "Pawapuri", "Madhubani",
    "Chandigarh",
    "Chhattisgarh", "Raipur", "Jagdalpur", "Chitrakote", "Barnawapara",
    "Sirpur", "Mainpat",
    "Daman", "Diu", "Silvassa",
    "Delhi", "New Delhi",
    "Goa", "North Goa", "South Goa", "Panaji", "Calangute", "Baga",
    "Anjuna", "Palolem", "Colva",
    "Gujarat", "Ahmedabad", "Surat", "Vadodara", "Rajkot", "Gandhinagar",
    "Dwarka", "Somnath", "Gir", "Kutch", "Rann Of Kutch", "Saputara",
    "Palitana", "Lothal", "Daman", "Statue Of Unity", "Nageshwar",
    "Haryana", "Gurugram", "Faridabad", "Panipat", "Kurukshetra",
    "Pinjore", "Morni Hills", "Surajkund",
    "Himachal Pradesh", "Shimla", "Manali", "Dharamshala", "Mcleodganj",
    "Kasol", "Spiti", "Kaza", "Chail", "Dalhousie", "Khajjiar",
    "Kullu", "Mandi", "Bir Billing", "Sangla", "Chitkul", "Narkanda",
    "Palampur", "Barot", "Kalpa", "Tirthan Valley",
    "Kashmir", "Srinagar", "Gulmarg", "Pahalgam", "Sonamarg",
    "Jammu", "Vaishno Devi", "Patnitop",
    "Leh Ladakh", "Leh", "Nubra Valley", "Pangong Lake", "Zanskar",
    "Tso Moriri", "Kargil",
    "Jharkhand", "Ranchi", "Jamshedpur", "Deoghar", "Betla",
    "Hundru Falls", "Panchghagh",
    "Karnataka", "Bangalore", "Mysore", "Coorg", "Hampi", "Gokarna",
    "Chikmagalur", "Sakleshpur", "Kodagu", "Udupi", "Mangalore",
    "Badami", "Pattadakal", "Aihole", "Belur", "Halebid",
    "Jog Falls", "Dandeli", "Agumbe", "Kabini",
    "Kerala", "Munnar", "Alleppey", "Wayanad", "Thekkady", "Kovalam",
    "Varkala", "Kochi", "Thrissur", "Kozhikode", "Kumarakom",
    "Bekal", "Kannur", "Palakkad",
    "Lakshadweep", "Agatti", "Bangaram",
    "Madhya Pradesh", "Bhopal", "Indore", "Jabalpur", "Ujjain", "Gwalior",
    "Orchha", "Khajuraho", "Kanha", "Bandhavgarh", "Pench", "Pachmarhi",
    "Sanchi", "Mandu", "Amarkantak", "Omkareshwar", "Mahakaleshwar",
    "Maharashtra", "Mumbai", "Pune", "Nashik", "Aurangabad", "Nagpur",
    "Mahabaleshwar", "Lonavala", "Alibaug", "Shirdi", "Ajanta Ellora",
    "Kolhapur", "Ratnagiri", "Matheran", "Tadoba", "Igatpuri",
    "Lavasa", "Murud", "Shrivardhan", "Trimbakeshwar", "Bhimashankar", "Grishneshwar",
    "Manipur", "Imphal", "Loktak Lake", "Keibul Lamjao",
    "Meghalaya", "Shillong", "Cherrapunji", "Mawlynnong", "Dawki",
    "Mawsynram", "Nongriat",
    "Mizoram", "Aizawl", "Champhai", "Phawngpui",
    "Nagaland", "Kohima", "Dimapur", "Dzukou Valley",
    "North East", "Northeast India",
    "Odisha", "Bhubaneswar", "Puri", "Konark", "Chilika Lake",
    "Daringbadi", "Simlipal", "Cuttack", "Gopalpur",
    "Pondicherry", "Puducherry", "Auroville",
    "Punjab", "Amritsar", "Ludhiana", "Jalandhar", "Patiala",
    "Anandpur Sahib", "Fatehgarh Sahib", "Wagah Border", "Chandigarh",
    "Rajasthan", "Jaipur", "Jaisalmer", "Udaipur", "Jodhpur", "Pushkar",
    "Ajmer", "Bikaner", "Ranthambore", "Mount Abu", "Chittorgarh",
    "Bundi", "Kota", "Sariska", "Bharatpur", "Alwar", "Mandawa",
    "Pali", "Barmer", "Nathdwara",
    "Sikkim", "Gangtok", "Pelling", "Lachung", "Lachen", "Yuksom",
    "Ravangla", "Namchi", "Gurudongmar Lake",
    "Tamil Nadu", "Chennai", "Ooty", "Kodaikanal", "Madurai",
    "Rameswaram", "Kanyakumari", "Mahabalipuram", "Thanjavur",
    "Coimbatore", "Tiruchirapalli", "Vellore", "Yercaud",
    "Coonoor", "Hogenakkal", "Tirunelveli",
    "Telangana", "Hyderabad", "Warangal", "Nagarjuna Sagar",
    "Medak", "Nizamabad", "Ramoji Film City",
    "Tripura", "Agartala", "Unakoti", "Neermahal",
    "Uttar Pradesh", "Varanasi", "Ayodhya", "Agra", "Mathura",
    "Vrindavan", "Prayagraj", "Lucknow", "Allahabad",
    "Dudhwa", "Chitrakoot", "Kashi Vishwanath", "Vaidyanath",
    "Uttarakhand", "Haridwar", "Rishikesh", "Dehradun", "Nainital",
    "Mussoorie", "Jim Corbett", "Kedarnath", "Badrinath", "Char Dham",
    "Gangotri", "Yamunotri", "Auli", "Lansdowne", "Munsiyari",
    "Chopta", "Chakrata", "Binsar", "Kausani",
    "West Bengal", "Kolkata", "Darjeeling", "Siliguri", "Sundarbans",
    "Digha", "Shantiniketan", "Bishnupur", "Kalimpong", "Mandarmani",
    "Jaldapara", "Murshidabad",
    "Mallikarjun Jyotirlinga", "Jyotirlinga Circuit",
    "Char Dham Yatra", "Do Dham", "Rameshwaram",
]

ALL_INDIAN_CITIES = {
    "Port Blair", "Havelock Island", "Neil Island", "Visakhapatnam", "Vijayawada",
    "Tirupati", "Guntur", "Nellore", "Kurnool", "Rajahmundry", "Kakinada",
    "Guwahati", "Silchar", "Dibrugarh", "Jorhat", "Tezpur", "Majuli",
    "Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Bodh Gaya", "Nalanda",
    "Raipur", "Bhilai", "Bilaspur", "Jagdalpur",
    "Delhi", "New Delhi", "Noida", "Gurgaon", "Gurugram", "Faridabad", "Ghaziabad",
    "Panaji", "Margao", "Vasco Da Gama",
    "Ahmedabad", "Surat", "Vadodara", "Rajkot", "Gandhinagar", "Dwarka",
    "Bangalore", "Bengaluru", "Mysore", "Hubli", "Mangalore", "Coorg",
    "Thiruvananthapuram", "Kochi", "Kozhikode", "Thrissur", "Alleppey",
    "Munnar", "Wayanad", "Thekkady", "Varkala", "Kovalam",
    "Bhopal", "Indore", "Jabalpur", "Gwalior", "Ujjain", "Khajuraho", "Orchha",
    "Mumbai", "Pune", "Nashik", "Aurangabad", "Nagpur", "Shirdi", "Lonavala",
    "Imphal", "Shillong", "Cherrapunji", "Aizawl", "Kohima", "Dimapur",
    "Bhubaneswar", "Cuttack", "Puri", "Konark",
    "Pondicherry", "Puducherry",
    "Amritsar", "Ludhiana", "Jalandhar", "Patiala", "Chandigarh",
    "Jaipur", "Jaisalmer", "Udaipur", "Jodhpur", "Pushkar", "Bikaner",
    "Gangtok", "Pelling", "Lachung", "Darjeeling", "Siliguri",
    "Chennai", "Coimbatore", "Madurai", "Rameswaram", "Kanyakumari",
    "Ooty", "Kodaikanal", "Thanjavur",
    "Hyderabad", "Warangal", "Secunderabad",
    "Agartala",
    "Lucknow", "Kanpur", "Agra", "Varanasi", "Prayagraj", "Allahabad",
    "Mathura", "Vrindavan", "Ayodhya", "Faizabad", "Chitrakoot",
    "Dehradun", "Haridwar", "Rishikesh", "Nainital", "Mussoorie",
    "Kolkata", "Howrah", "Asansol", "Siliguri", "Darjeeling",
    "Sundarbans", "Digha", "Shantiniketan",
    "Leh", "Srinagar", "Gulmarg", "Pahalgam", "Jammu",
}

ARRIVAL_GATEWAY = {
    "kerala":         {"airport": "Kochi International Airport (COK)", "city": "Kochi"},
    "munnar":         {"airport": "Kochi International Airport (COK)", "city": "Kochi"},
    "alleppey":       {"airport": "Kochi International Airport (COK)", "city": "Kochi"},
    "wayanad":        {"airport": "Calicut International Airport (CCJ)", "city": "Kozhikode"},
    "thekkady":       {"airport": "Madurai Airport (IXM)", "city": "Madurai"},
    "kovalam":        {"airport": "Trivandrum International Airport (TRV)", "city": "Thiruvananthapuram"},
    "varkala":        {"airport": "Trivandrum International Airport (TRV)", "city": "Thiruvananthapuram"},
    "kumarakom":      {"airport": "Kochi International Airport (COK)", "city": "Kochi"},
    "ooty":           {"airport": "Coimbatore International Airport (CJB)", "city": "Coimbatore"},
    "kodaikanal":     {"airport": "Madurai Airport (IXM)", "city": "Madurai"},
    "pondicherry":    {"airport": "Chennai International Airport (MAA)", "city": "Chennai"},
    "rameswaram":     {"airport": "Madurai Airport (IXM)", "city": "Madurai"},
    "rameshwaram":    {"airport": "Madurai Airport (IXM)", "city": "Madurai"},
    "kanyakumari":    {"airport": "Trivandrum International Airport (TRV)", "city": "Thiruvananthapuram"},
    "mahabalipuram":  {"airport": "Chennai International Airport (MAA)", "city": "Chennai"},
    "madurai":        {"airport": "Madurai Airport (IXM)", "city": "Madurai"},
    "gokarna":        {"airport": "Goa International Airport (GOI)", "city": "Goa"},
    "coorg":          {"airport": "Mangalore International Airport (IXE)", "city": "Mangalore"},
    "kodagu":         {"airport": "Mangalore International Airport (IXE)", "city": "Mangalore"},
    "chikmagalur":    {"airport": "Mangalore International Airport (IXE)", "city": "Mangalore"},
    "hampi":          {"airport": "Hubli Airport (HBX)", "city": "Hubli"},
    "mysore":         {"airport": "Mysuru Airport (MYQ)", "city": "Mysore"},
    "mangalore":      {"airport": "Mangalore International Airport (IXE)", "city": "Mangalore"},
    "goa":            {"airport": "Goa International Airport, Dabolim (GOI)", "city": "Goa"},
    "mumbai":         {"airport": "Chhatrapati Shivaji Maharaj International Airport (BOM)", "city": "Mumbai"},
    "pune":           {"airport": "Pune Airport (PNQ)", "city": "Pune"},
    "shirdi":         {"airport": "Shirdi Airport (SAG)", "city": "Shirdi"},
    "nashik":         {"airport": "Ozar Airport, Nashik (ISK)", "city": "Nashik"},
    "nagpur":         {"airport": "Dr. Babasaheb Ambedkar International Airport, Nagpur (NAG)", "city": "Nagpur"},
    "aurangabad":     {"airport": "Aurangabad Airport (IXU)", "city": "Aurangabad"},
    "manali":         {"airport": "Kullu Manali Airport (KUU)", "city": "Chandigarh"},
    "shimla":         {"airport": "Shimla Airport (SLV)", "city": "Shimla"},
    "dharamshala":    {"airport": "Gaggal Airport (DHM)", "city": "Dharamshala"},
    "kashmir":        {"airport": "Sheikh ul-Alam International Airport, Srinagar (SXR)", "city": "Srinagar"},
    "srinagar":       {"airport": "Sheikh ul-Alam International Airport, Srinagar (SXR)", "city": "Srinagar"},
    "gulmarg":        {"airport": "Sheikh ul-Alam International Airport, Srinagar (SXR)", "city": "Srinagar"},
    "pahalgam":       {"airport": "Sheikh ul-Alam International Airport, Srinagar (SXR)", "city": "Srinagar"},
    "jammu":          {"airport": "Jammu Airport (IXJ)", "city": "Jammu"},
    "vaishno devi":   {"airport": "Jammu Airport (IXJ)", "city": "Jammu"},
    "leh ladakh":     {"airport": "Kushok Bakula Rimpochee Airport, Leh (IXL)", "city": "Leh"},
    "leh":            {"airport": "Kushok Bakula Rimpochee Airport, Leh (IXL)", "city": "Leh"},
    "haridwar":       {"airport": "Jolly Grant Airport, Dehradun (DED)", "city": "Dehradun"},
    "rishikesh":      {"airport": "Jolly Grant Airport, Dehradun (DED)", "city": "Dehradun"},
    "char dham":      {"airport": "Jolly Grant Airport, Dehradun (DED)", "city": "Dehradun"},
    "kedarnath":      {"airport": "Jolly Grant Airport, Dehradun (DED)", "city": "Dehradun"},
    "badrinath":      {"airport": "Jolly Grant Airport, Dehradun (DED)", "city": "Dehradun"},
    "nainital":       {"airport": "Pantnagar Airport (PGH)", "city": "Pantnagar"},
    "mussoorie":      {"airport": "Jolly Grant Airport, Dehradun (DED)", "city": "Dehradun"},
    "dehradun":       {"airport": "Jolly Grant Airport, Dehradun (DED)", "city": "Dehradun"},
    "jim corbett":    {"airport": "Pantnagar Airport (PGH)", "city": "Pantnagar"},
    "varanasi":       {"airport": "Lal Bahadur Shastri International Airport (VNS)", "city": "Varanasi"},
    "ayodhya":        {"airport": "Ayodhya Airport (AYJ)", "city": "Ayodhya"},
    "agra":           {"airport": "Agra Airport (AGR)", "city": "Agra"},
    "mathura":        {"airport": "Agra Airport (AGR)", "city": "Agra"},
    "vrindavan":      {"airport": "Agra Airport (AGR)", "city": "Agra"},
    "prayagraj":      {"airport": "Prayagraj Airport (IXD)", "city": "Prayagraj"},
    "allahabad":      {"airport": "Prayagraj Airport (IXD)", "city": "Prayagraj"},
    "lucknow":        {"airport": "Chaudhary Charan Singh International Airport, Lucknow (LKO)", "city": "Lucknow"},
    "jaipur":         {"airport": "Jaipur International Airport (JAI)", "city": "Jaipur"},
    "jaisalmer":      {"airport": "Jaisalmer Airport (JSA)", "city": "Jaisalmer"},
    "udaipur":        {"airport": "Maharana Pratap Airport, Udaipur (UDR)", "city": "Udaipur"},
    "jodhpur":        {"airport": "Jodhpur Airport (JDH)", "city": "Jodhpur"},
    "pushkar":        {"airport": "Kishangarh Airport (KQH)", "city": "Ajmer"},
    "dwarka":         {"airport": "Rajkot Airport (RAJ)", "city": "Rajkot"},
    "somnath":        {"airport": "Diu Airport (DIU)", "city": "Junagadh"},
    "gir":            {"airport": "Diu Airport (DIU)", "city": "Junagadh"},
    "diu":            {"airport": "Diu Airport (DIU)", "city": "Diu"},
    "andaman":        {"airport": "Veer Savarkar International Airport, Port Blair (IXZ)", "city": "Port Blair"},
    "port blair":     {"airport": "Veer Savarkar International Airport, Port Blair (IXZ)", "city": "Port Blair"},
    "north east":     {"airport": "Lokpriya Gopinath Bordoloi International Airport, Guwahati (GAU)", "city": "Guwahati"},
    "assam":          {"airport": "Lokpriya Gopinath Bordoloi International Airport, Guwahati (GAU)", "city": "Guwahati"},
    "meghalaya":      {"airport": "Shillong Airport, Umroi (SHL)", "city": "Guwahati"},
    "shillong":       {"airport": "Shillong Airport, Umroi (SHL)", "city": "Guwahati"},
    "sikkim":         {"airport": "Pakyong Airport (PYG)", "city": "Siliguri"},
    "gangtok":        {"airport": "Pakyong Airport (PYG)", "city": "Siliguri"},
    "pelling":        {"airport": "Bagdogra Airport (IXB)", "city": "Siliguri"},
    "darjeeling":     {"airport": "Bagdogra Airport (IXB)", "city": "Siliguri"},
    "puri":           {"airport": "Biju Patnaik International Airport, Bhubaneswar (BBI)", "city": "Bhubaneswar"},
    "bhubaneswar":    {"airport": "Biju Patnaik International Airport, Bhubaneswar (BBI)", "city": "Bhubaneswar"},
    "bodh gaya":      {"airport": "Gaya Airport (GAY)", "city": "Gaya"},
    "ujjain":         {"airport": "Devi Ahilya Bai Holkar Airport, Indore (IDR)", "city": "Indore"},
    "indore":         {"airport": "Devi Ahilya Bai Holkar Airport, Indore (IDR)", "city": "Indore"},
    "khajuraho":      {"airport": "Khajuraho Airport (HJR)", "city": "Khajuraho"},
    "amritsar":       {"airport": "Sri Guru Ram Dass Jee International Airport, Amritsar (ATQ)", "city": "Amritsar"},
    "delhi":          {"airport": "Indira Gandhi International Airport (DEL)", "city": "Delhi"},
    "new delhi":      {"airport": "Indira Gandhi International Airport (DEL)", "city": "Delhi"},
    "bangalore":      {"airport": "Kempegowda International Airport (BLR)", "city": "Bangalore"},
    "hyderabad":      {"airport": "Rajiv Gandhi International Airport, Hyderabad (HYD)", "city": "Hyderabad"},
    "chennai":        {"airport": "Chennai International Airport (MAA)", "city": "Chennai"},
    "kolkata":        {"airport": "Netaji Subhash Chandra Bose International Airport (CCU)", "city": "Kolkata"},
    "tirupati":       {"airport": "Tirupati Airport (TIR)", "city": "Tirupati"},
    "visakhapatnam":  {"airport": "Visakhapatnam Airport (VTZ)", "city": "Visakhapatnam"},
    "default":        {"airport": "Nearest major airport", "city": "Nearest hub city"},
}