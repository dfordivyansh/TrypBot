"""
TrypDeals Travel Bot — utils.py  v17.7.0
=========================================

Company: TrypDeals Tech Labs Pvt. Ltd.
Address: FF 16, One Mart Mall, Sector 6, Vasundhara, Ghaziabad - 201012

CHANGES IN v17.7.0 (over v17.6.0):

  1. FULL ITINERARY ON BEST SELLER "SEND FULL ITINERARIES" —
     When a user clicks "Looks Good" on the best seller package card, instead of
     immediately handing off to the sales agent, the bot now sends the complete
     pre-written itinerary for that destination (sourced from
     BEST_SELLER_FULL_ITINERARIES). The session moves to STAGE_ITINERARY_REVIEW
     and the user is presented with ["Pay and Book", "Talk to Expert", "Modify"]
     options — identical to the standard post-itinerary flow.
     The lead is still marked HOT at this point.

  2. NEW DATA STRUCTURE — BEST_SELLER_FULL_ITINERARIES —
     A dict mapping each best-seller key to the complete, verbatim itinerary
     text (day-wise plan, hotels, pricing, inclusions, exclusions, policies).
     This replaces AI-generated text for these 10 destinations and guarantees
     consistent, pre-approved content every time.

  3. No other behavioural changes beyond the above.

CHANGES IN v17.6.0 (over v17.5.0):
  [see previous version header]
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
from .crm_helpers import mark_lead_hot, mark_lead_follow_up

logger = logging.getLogger("trypdeals.utils")

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

DEEPSEEK_MODEL = "deepseek-chat"

_deepseek_client = OpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
)


def _deepseek(prompt: str) -> str:
    try:
        response = _deepseek_client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
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


def _save_bot_reply_to_crm(session, message_text: str) -> None:
    if not message_text or not message_text.strip():
        return
    try:
        ChatMessage.objects.create(
            session=session,
            sender_type="bot",
            message=message_text.strip(),
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
# BEST SELLER FULL ITINERARIES  (v17.7.0)
# ─────────────────────────────────────────────────────────────────────────────
# Complete pre-written itineraries sent when the user clicks "Looks Good"
# on the best seller teaser card. These are verbatim from the approved
# package documents and are NOT AI-generated.

BEST_SELLER_FULL_ITINERARIES = {
    "rameshwaram": """Madurai Rameshwaram Kanyakumari Tour Package 4 Days

Day 1 Madurai Sightseeing Stay

Morning pickup from Madurai. Proceed to hotel for check in.
Proceed for Madurai sightseeing.
- Meenakshi Amman Temple
- Thirumalai Nayakkar Mahal
- Gandhi Memorial Museum
Evening return to hotel.
Overnight stay at Madurai.

Day 2 Madurai to Rameshwaram Darshan Stay

Early morning drive from Madurai to Rameshwaram.
On arrival check in at hotel and freshen up.
Proceed for Rameshwaram darshan.
- Ramanathaswamy Temple
- Agni Theertham
- Panchmukhi Hanuman Temple
- Floating Stone
- Lakshman Theertham
Evening return to hotel.
Overnight stay at Rameshwaram.

Day 3 Rameshwaram Sightseeing then Transfer to Kanyakumari

After breakfast proceed for full day Rameshwaram sightseeing.
- Dhanushkodi Beach
- Dhanushkodi Ruins
- APJ Abdul Kalam Memorial
- Pamban Bridge
Till evening sightseeing.
Night board sleeper bus from Rameshwaram to Kanyakumari.
Overnight journey by sleeper bus.

Day 4 Kanyakumari Sightseeing and Drop

Early morning arrival at Kanyakumari.
Proceed to hotel for freshen up.
Proceed for Kanyakumari sightseeing.
- Vivekananda Rock Memorial
- Thiruvalluvar Statue
- Kanyakumari Amman Temple
- Triveni Sangam
- Gandhi Mandapam
- Sunset View Point
Evening drop at Kanyakumari or onward destination as per plan.

SUGGESTED ACCOMMODATION

Madurai: Hotel Venkateshwara or similar (3 Star AC)
Rameshwaram: 3 Star AC Hotel near Ramanathaswamy Temple
Kanyakumari: Hotel AR Residency or similar (Day use freshen up)

PACKAGE PRICE PER PERSON

For 2 adults: Rs. 14,000 per person
For 3 adults: Rs. 11,000 per person
For 4 to 5 adults: Rs. 9,000 per person
For 6 to 8 adults: Rs. 8,000 per person
For 9 to 12 adults: Rs. 7,500 per person

INCLUSIONS

Accommodation in 3 star AC hotels on double or triple sharing basis
Breakfast at hotel
All transfers and sightseeing by private AC vehicle as per group size from Madurai to Rameshwaram
Driver charges, toll, parking, fuel and interstate taxes

EXCLUSIONS

Any train, flight or bus fare
Lunch, dinner and beverages
Monument entry charges, boating and guide charges
Personal expenses, tips and shopping
Sleeper bus charges from Rameshwaram to Kanyakumari
Anything not mentioned in inclusions

PAYMENT POLICY

20 percent advance at time of booking
30 percent on arrival at the time of tour start
50 percent in mid of the tour

CHILD POLICY

Child up to 6 years: Free
Child 6 to 8 years: Half charge
Child above 8 years: Full charge

CANCELLATION POLICY

10 percent or Rs. 3000 per person whichever is higher
25 percent cancellation between 45 to 30 days before departure
50 percent cancellation between 30 to 15 days before departure
75 percent cancellation between 15 to 5 days before departure
100 percent cancellation within 5 days of departure or no show
Cancellation charges are calculated on total tour cost

IMPORTANT NOTE

For long weekends, holidays and festival dates extra charges applicable.""",

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


def _build_best_seller_message(bs_key: str) -> str:
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
        except Exception:
            pass


def detect_destination_in_message(message: str) -> str | None:
    _ensure_dest_lookup_populated()
    msg = message.lower().strip()

    noise = r"\b(i want to go to|i want to visit|plan a trip to|trip to|travel to|" \
            r"going to|visit|book|tour|package|for|in|at|near|around|from|the|a|an)\b"
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
# GROUP TOUR CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

GROUP_TOUR_DESTINATIONS = {"rameshwaram", "varanasi", "rameswaram"}

GROUP_TOUR_ITINERARIES = {
    "rameshwaram": {
        "default": """MADURAI RAMESHWARAM KANYAKUMARI TOUR PACKAGE 4 DAYS

GROUP TOUR ITINERARY

Day 1 - Madurai (150 km approx)
Morning 6.00 am pick up from Madurai. Check into hotel. Then proceed for sightseeing.
- Meenakshi Amman Temple
- Thirumalai Nayakkar Mahal
- Gandhi Memorial Museum
Evening return to hotel. Night stay.

Day 2 - Madurai to Rameshwaram (175 km approx)
Morning drive to Rameshwaram. Check into hotel. Proceed for sightseeing.
- Ramanathaswamy Temple
- Agni Theertham
- Panchmukhi Hanuman Temple
- Floating Stone
- Lakshman Theertham
Evening return to hotel. Night stay.

Day 3 - Rameshwaram to Kanyakumari (310 km approx)
Morning sightseeing.
- Dhanushkodi Beach
- Dhanushkodi Ruins
- APJ Abdul Kalam Memorial
Drive to Kanyakumari. Check into hotel. Night stay.

Day 4 - Kanyakumari to Madurai (245 km approx)
Morning sightseeing.
- Vivekananda Rock Memorial
- Thiruvalluvar Statue
- Kanyakumari Temple
- Triveni Sangam
- Gandhi Mandapam
- Sunset View Point
Evening drive to Madurai. Drop at Madurai by evening.

HOTEL NAMES 3 STAR AC
Madurai - 3 Star AC Hotel near Meenakshi Amman Temple
Rameshwaram - 3 Star AC Hotel near Ramanathaswamy Temple
Kanyakumari - 3 Star AC Hotel near Vivekananda Rock Memorial

INCLUSIONS
Accommodation in 3 star AC hotels on double/triple sharing basis
Breakfast at hotel
All transfers and sightseeing by private AC vehicle as per group size
Driver charges, toll, parking, fuel, interstate taxes

EXCLUSIONS
Any train/flight/bus fare
Lunch, dinner, beverages
Monument entry charges, boating, guide charges
Personal expenses, tips, shopping
Anything not mentioned in inclusions

Note: Extra charges applicable on long weekends, holidays and festivals.""",
    },
    "varanasi": {
        "default": """AYODHYA VARANASI PRAYAGRAJ GROUP TOUR PACKAGE

GROUP TOUR ITINERARY

Day 1 - Varanasi Arrival and Sightseeing
Pickup from Varanasi airport/railway station at 08:00 AM. Proceed to hotel. Check in and freshen up.
- Kashi Vishwanath Temple
- Bharat Mata Mandir
- Durga Temple
- Sankat Mochan Hanuman Temple
- Tulsi Manas Mandir
- New Vishwanath Temple (BHU)
- Assi Ghat
- Dashashwamedh Ghat
- Evening Ganga Aarti
- Manikarnika Ghat
Overnight stay at hotel in Varanasi.

Day 2 - Varanasi and Sarnath Sightseeing
After breakfast proceed for sightseeing.
- Sarnath
- Dhamek Stupa
- Chaukhandi Stupa
- Mulagandha Kuti Vihar
- Sarnath Museum
Return to Varanasi. Free time for local market and ghats.
Overnight stay at hotel in Varanasi.

Day 3 - Varanasi to Prayagraj and Ayodhya
After breakfast check out. Drive to Prayagraj.
- Triveni Sangam for holy dip if desired
- Anand Bhavan
- Hanuman Mandir
Proceed to Ayodhya. Check in to hotel.
Overnight stay at hotel in Ayodhya.

Day 4 - Ayodhya Sightseeing and Departure
After breakfast check out.
- Ram Janmabhoomi
- Hanuman Garhi
- Kanak Bhawan
- Dashrath Mahal
- Nageshwarnath Temple
- Treta Ke Thakur
- Ram Ki Paidi
- Guptar Ghat
- Mani Parvat
Drop at Ayodhya airport/railway station in evening.

HOTEL NAMES 3 STAR AC
Varanasi - 3 Star AC Hotel near the Ghats
Ayodhya - 3 Star AC Hotel near Ram Janmabhoomi

INCLUSIONS
Well appointed rooms in mentioned hotels
Daily breakfast
AC vehicle for transfers and sightseeing
Driver allowance toll and parking
All applicable hotel taxes

EXCLUSIONS
Any meals other than breakfast
Any transport not mentioned
Entry tickets and boating charges
Tips insurance and personal expenses
Airfare or train fare
GST at 5 percent

Note: Extra charges applicable on long weekends, holidays and festivals.
Hotel check in time 12 pm. Check out time 11 am.
Early check in subject to availability. Late check out extra charges applicable.""",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# GROUP TOUR ITINERARY HELPER
# ─────────────────────────────────────────────────────────────────────────────

_GROUP_PRICE_SECTION_HEADERS = [
    "GROUP TOUR PACKAGE PRICE",
    "PACKAGE COST PER PERSON",
    "PAYMENT POLICY",
    "CHILD POLICY",
    "CANCELLATION POLICY",
    "VEHICLE POLICY",
]


def _strip_group_tour_price_sections(text: str) -> str:
    lines  = text.splitlines()
    result = []
    skip   = False
    for line in lines:
        upper = line.strip().upper()
        if any(upper.startswith(h) for h in _GROUP_PRICE_SECTION_HEADERS):
            skip = True
        elif skip and upper and not upper.startswith(" ") and upper.endswith(
            tuple(["INCLUSIONS", "EXCLUSIONS", "NOTE", "HOTEL", "DAY ", "ITINERARY"])
        ):
            skip = False
        if not skip:
            result.append(line)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(result))
    return cleaned.strip()


def _get_group_tour_itinerary(destination: str, departure_date: str = None) -> str:
    dest_key = destination.lower().strip()
    if dest_key == "rameswaram":
        dest_key = "rameshwaram"
    dest_itins = GROUP_TOUR_ITINERARIES.get(dest_key, {})
    if departure_date and departure_date in dest_itins:
        raw = dest_itins[departure_date]
    else:
        raw = dest_itins.get(
            "default",
            f"Group tour itinerary for {destination} will be shared shortly."
        )
    return _strip_group_tour_price_sections(raw)


# ─────────────────────────────────────────────────────────────────────────────
# DESTINATION CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

DESTINATION_CONFIG = {
    "Rameshwaram": {
        "priority_places": ["Madurai", "Kanyakumari", "Trivandrum", "Kodaikanal"],
        "sightseeing": {
            "Rameshwaram": ["Ramanathaswamy Temple", "Agni Theertham", "Dhanushkodi Beach",
                            "Floating Stone", "Panchmukhi Hanuman Temple", "Lakshman Theertham",
                            "APJ Abdul Kalam Memorial", "Dhanushkodi Ruins"],
            "Madurai":     ["Meenakshi Amman Temple", "Thirumalai Nayakkar Mahal",
                            "Gandhi Memorial Museum", "Madurai Market"],
            "Kanyakumari": ["Vivekananda Rock Memorial", "Thiruvalluvar Statue",
                            "Kanyakumari Temple", "Triveni Sangam", "Gandhi Mandapam",
                            "Sunset View Point"],
            "Trivandrum":  ["Padmanabhaswamy Temple", "Napier Museum", "Zoo", "Kovalam Beach"],
            "Kodaikanal":  ["Kodaikanal Lake", "Coaker's Walk", "Bryant Park", "Pillar Rocks"],
        },
        "routes": {
            3: [["Rameshwaram", "Madurai", "Kanyakumari"],
                ["Rameshwaram", "Madurai", "Kodaikanal"]],
            4: [["Rameshwaram", "Madurai", "Kanyakumari", "Trivandrum"],
                ["Rameshwaram", "Madurai", "Kodaikanal", "Kanyakumari"],
                ["Madurai", "Rameshwaram", "Kanyakumari", "Trivandrum"]],
            5: [["Madurai", "Rameshwaram", "Kanyakumari", "Trivandrum", "Kodaikanal"],
                ["Rameshwaram", "Madurai", "Kanyakumari", "Trivandrum", "Kodaikanal"],
                ["Madurai", "Rameshwaram", "Dhanushkodi", "Kanyakumari", "Trivandrum"]],
            6: [["Madurai", "Rameshwaram", "Kanyakumari", "Trivandrum", "Kodaikanal", "Ooty"],
                ["Rameshwaram", "Madurai", "Kodaikanal", "Ooty", "Kanyakumari", "Trivandrum"],
                ["Madurai", "Rameshwaram", "Kanyakumari", "Trivandrum", "Alappuzha", "Kochi"]],
        },
    },
    "Varanasi": {
        "priority_places": ["Prayagraj", "Ayodhya", "Chitrakoot", "Gaya"],
        "sightseeing": {
            "Varanasi":   ["Kashi Vishwanath Temple", "Ganga Ghat Aarti", "Sarnath",
                           "Manikarnika Ghat", "Assi Ghat", "BHU Campus", "Bharat Mata Mandir"],
            "Prayagraj":  ["Triveni Sangam", "Anand Bhavan", "Allahabad Fort",
                           "Hanuman Mandir", "Alopi Devi Temple"],
            "Ayodhya":    ["Ram Janmabhoomi", "Hanuman Garhi", "Kanak Bhawan",
                           "Dashrath Mahal", "Ram Ki Paidi", "Guptar Ghat"],
            "Chitrakoot": ["Kamadgiri Temple", "Ramghat", "Bharat Milap Sthal",
                           "Gupt Godavari", "Hanuman Dhara"],
            "Gaya":       ["Vishnupad Temple", "Bodh Gaya", "Mahabodhi Temple",
                           "Falgu River", "Mangla Gauri Temple"],
        },
        "routes": {
            3: [["Varanasi", "Prayagraj", "Ayodhya"],
                ["Varanasi", "Sarnath", "Prayagraj"],
                ["Varanasi", "Prayagraj", "Chitrakoot"]],
            4: [["Varanasi", "Prayagraj", "Ayodhya", "Chitrakoot"],
                ["Varanasi", "Sarnath", "Prayagraj", "Ayodhya"],
                ["Varanasi", "Gaya", "Prayagraj", "Ayodhya"],
                ["Varanasi", "Prayagraj", "Chitrakoot", "Ayodhya"]],
            5: [["Varanasi", "Prayagraj", "Ayodhya", "Chitrakoot", "Gaya"],
                ["Varanasi", "Sarnath", "Prayagraj", "Ayodhya", "Mathura"],
                ["Gaya", "Varanasi", "Sarnath", "Prayagraj", "Ayodhya"]],
            6: [["Varanasi", "Sarnath", "Prayagraj", "Ayodhya", "Mathura", "Vrindavan"],
                ["Gaya", "Varanasi", "Prayagraj", "Ayodhya", "Chitrakoot", "Mathura"],
                ["Varanasi", "Prayagraj", "Chitrakoot", "Ayodhya", "Mathura", "Vrindavan"]],
        },
    },
    "Ayodhya": {
        "priority_places": ["Prayagraj", "Varanasi", "Chitrakoot", "Gaya"],
        "sightseeing": {
            "Ayodhya":    ["Ram Janmabhoomi", "Hanuman Garhi", "Kanak Bhawan",
                           "Dashrath Mahal", "Ram Ki Paidi", "Guptar Ghat", "Mani Parvat"],
            "Prayagraj":  ["Triveni Sangam", "Anand Bhavan", "Allahabad Fort", "Hanuman Mandir"],
            "Varanasi":   ["Kashi Vishwanath Temple", "Ganga Aarti", "Sarnath", "Assi Ghat"],
            "Chitrakoot": ["Kamadgiri Temple", "Ramghat", "Gupt Godavari", "Hanuman Dhara"],
            "Gaya":       ["Vishnupad Temple", "Bodh Gaya", "Mahabodhi Temple"],
        },
        "routes": {
            3: [["Ayodhya", "Prayagraj", "Varanasi"],
                ["Ayodhya", "Prayagraj", "Chitrakoot"],
                ["Ayodhya", "Varanasi", "Prayagraj"]],
            4: [["Ayodhya", "Prayagraj", "Varanasi", "Sarnath"],
                ["Ayodhya", "Prayagraj", "Chitrakoot", "Varanasi"],
                ["Ayodhya", "Prayagraj", "Varanasi", "Gaya"],
                ["Ayodhya", "Chitrakoot", "Prayagraj", "Varanasi"]],
            5: [["Ayodhya", "Prayagraj", "Varanasi", "Sarnath", "Gaya"],
                ["Ayodhya", "Prayagraj", "Chitrakoot", "Varanasi", "Gaya"],
                ["Ayodhya", "Mathura", "Prayagraj", "Varanasi", "Gaya"]],
            6: [["Ayodhya", "Mathura", "Vrindavan", "Prayagraj", "Varanasi", "Gaya"],
                ["Ayodhya", "Prayagraj", "Chitrakoot", "Varanasi", "Sarnath", "Gaya"],
                ["Mathura", "Ayodhya", "Prayagraj", "Varanasi", "Sarnath", "Bodh Gaya"]],
        },
    },
    "Nashik": {
        "priority_places": ["Bhimashankar", "Ghrishneshwar", "Shirdi", "Shani Shingnapur"],
        "sightseeing": {
            "Nashik":           ["Trimbakeshwar Temple", "Pandavleni Caves", "Kalaram Temple",
                                 "Ramkund", "Muktidham Temple", "Nashik Caves"],
            "Bhimashankar":     ["Bhimashankar Temple", "Bhima River Origin", "Wildlife Sanctuary"],
            "Ghrishneshwar":    ["Ghrishneshwar Temple", "Ajanta Ellora Caves", "Daulatabad Fort"],
            "Shirdi":           ["Sai Baba Temple", "Dwarkamai", "Chavadi", "Gurusthan",
                                 "Lendi Baug", "Sai Heritage Village"],
            "Shani Shingnapur": ["Shani Temple", "Open-air Temple", "Local Market"],
        },
        "routes": {
            3: [["Nashik", "Shirdi", "Shani Shingnapur"],
                ["Nashik", "Trimbakeshwar", "Shirdi"],
                ["Nashik", "Bhimashankar", "Shirdi"]],
            4: [["Nashik", "Bhimashankar", "Shirdi", "Shani Shingnapur"],
                ["Nashik", "Trimbakeshwar", "Shirdi", "Ghrishneshwar"],
                ["Nashik", "Shirdi", "Shani Shingnapur", "Bhimashankar"],
                ["Trimbakeshwar", "Nashik", "Shirdi", "Shani Shingnapur"]],
            5: [["Nashik", "Trimbakeshwar", "Bhimashankar", "Shirdi", "Shani Shingnapur"],
                ["Nashik", "Bhimashankar", "Ghrishneshwar", "Shirdi", "Shani Shingnapur"],
                ["Nashik", "Trimbakeshwar", "Shirdi", "Shani Shingnapur", "Ghrishneshwar"]],
            6: [["Nashik", "Trimbakeshwar", "Bhimashankar", "Ghrishneshwar", "Shirdi", "Shani Shingnapur"],
                ["Nashik", "Bhimashankar", "Ghrishneshwar", "Shirdi", "Shani Shingnapur", "Lonavala"],
                ["Nashik", "Trimbakeshwar", "Lonavala", "Bhimashankar", "Shirdi", "Shani Shingnapur"]],
        },
    },
    "Puri": {
        "priority_places": ["Konark", "Chilika Lake", "Bhubaneswar"],
        "sightseeing": {
            "Puri":         ["Jagannath Temple", "Puri Beach", "Gundicha Temple",
                             "Narendra Pond", "Sudarshana Crafts Museum"],
            "Konark":       ["Konark Sun Temple", "Chandrabhaga Beach", "Archaeological Museum"],
            "Chilika Lake": ["Boat Safari", "Nalabana Bird Sanctuary", "Dolphin Sighting",
                             "Kalijai Temple Island"],
            "Bhubaneswar":  ["Lingaraj Temple", "Udayagiri Caves", "Dhauli Shanti Stupa",
                             "Parasuramesvara Temple", "State Museum"],
        },
        "routes": {
            3: [["Puri", "Konark", "Bhubaneswar"],
                ["Puri", "Konark", "Chilika Lake"],
                ["Bhubaneswar", "Puri", "Konark"]],
            4: [["Puri", "Konark", "Chilika Lake", "Bhubaneswar"],
                ["Bhubaneswar", "Puri", "Konark", "Chilika Lake"],
                ["Puri", "Konark", "Bhubaneswar", "Chilika Lake"],
                ["Bhubaneswar", "Konark", "Puri", "Chilika Lake"]],
            5: [["Puri", "Konark", "Chilika Lake", "Bhubaneswar", "Cuttack"],
                ["Bhubaneswar", "Puri", "Konark", "Chilika Lake", "Gopalpur"],
                ["Puri", "Konark", "Bhubaneswar", "Cuttack", "Chilika Lake"]],
            6: [["Bhubaneswar", "Puri", "Konark", "Chilika Lake", "Gopalpur", "Cuttack"],
                ["Puri", "Konark", "Chilika Lake", "Bhubaneswar", "Cuttack", "Sambalpur"],
                ["Bhubaneswar", "Cuttack", "Puri", "Konark", "Chilika Lake", "Gopalpur"]],
        },
    },
    "Ujjain": {
        "priority_places": ["Omkareshwar", "Indore", "Maheshwar", "Mandu"],
        "sightseeing": {
            "Ujjain":      ["Mahakaleshwar Temple", "Kal Bhairav Temple", "Ram Ghat",
                            "Harsiddhi Temple", "Sandipani Ashram", "Vedh Shala"],
            "Omkareshwar": ["Omkareshwar Temple", "Mamleshwar Temple", "Ahilya Ghat",
                            "Boat Ride on Narmada"],
            "Indore":      ["Rajwada Palace", "Lal Bagh Palace", "Sarafa Bazaar",
                            "Patalpani Waterfall", "Chokhi Dhani"],
            "Maheshwar":   ["Ahilya Fort", "Maheshwar Temple", "Maheshwari Weaving", "Narmada Ghat"],
            "Mandu":       ["Jahaz Mahal", "Hindola Mahal", "Roopmati Pavilion",
                            "Baz Bahadur Palace", "Afghan Architecture"],
        },
        "routes": {
            3: [["Ujjain", "Omkareshwar", "Indore"],
                ["Ujjain", "Indore", "Maheshwar"],
                ["Ujjain", "Omkareshwar", "Maheshwar"]],
            4: [["Ujjain", "Omkareshwar", "Indore", "Maheshwar"],
                ["Ujjain", "Indore", "Maheshwar", "Mandu"],
                ["Ujjain", "Omkareshwar", "Maheshwar", "Mandu"],
                ["Indore", "Ujjain", "Omkareshwar", "Maheshwar"]],
            5: [["Ujjain", "Omkareshwar", "Indore", "Maheshwar", "Mandu"],
                ["Ujjain", "Indore", "Omkareshwar", "Maheshwar", "Mandu"],
                ["Indore", "Ujjain", "Omkareshwar", "Maheshwar", "Mandu"]],
            6: [["Ujjain", "Omkareshwar", "Indore", "Maheshwar", "Mandu", "Pachmarhi"],
                ["Indore", "Ujjain", "Omkareshwar", "Maheshwar", "Mandu", "Bhopal"],
                ["Ujjain", "Indore", "Omkareshwar", "Maheshwar", "Mandu", "Bhopal"]],
        },
    },
    "Coorg": {
        "priority_places": ["Mysore", "Ooty", "Chikmagalur", "Wayanad"],
        "sightseeing": {
            "Coorg":       ["Abbey Falls", "Raja's Seat", "Nagarhole National Park",
                            "Dubare Elephant Camp", "Talacauvery", "Brahmagiri Peak"],
            "Mysore":      ["Mysore Palace", "Chamundi Hill", "Brindavan Gardens", "Zoo", "Railway Museum"],
            "Ooty":        ["Botanical Gardens", "Ooty Lake", "Doddabetta Peak", "Rose Garden", "Tea Gardens"],
            "Chikmagalur": ["Mullayanagiri Peak", "Baba Budangiri", "Coffee Plantations",
                            "Hebbe Falls", "Z Point"],
            "Wayanad":     ["Edakkal Caves", "Banasura Sagar Dam", "Chembra Peak",
                            "Soochipara Falls", "Wildlife Sanctuary"],
        },
        "routes": {
            3: [["Coorg", "Mysore", "Ooty"],
                ["Coorg", "Chikmagalur", "Mysore"],
                ["Coorg", "Mysore", "Wayanad"]],
            4: [["Coorg", "Mysore", "Ooty", "Chikmagalur"],
                ["Coorg", "Chikmagalur", "Mysore", "Wayanad"],
                ["Chikmagalur", "Coorg", "Mysore", "Ooty"],
                ["Coorg", "Mysore", "Wayanad", "Ooty"]],
            5: [["Coorg", "Mysore", "Ooty", "Chikmagalur", "Wayanad"],
                ["Chikmagalur", "Coorg", "Mysore", "Ooty", "Wayanad"],
                ["Coorg", "Chikmagalur", "Mysore", "Wayanad", "Ooty"]],
            6: [["Coorg", "Chikmagalur", "Mysore", "Ooty", "Wayanad", "Munnar"],
                ["Chikmagalur", "Coorg", "Mysore", "Wayanad", "Ooty", "Munnar"],
                ["Coorg", "Mysore", "Ooty", "Chikmagalur", "Wayanad", "Munnar"]],
        },
    },
    "Dwarka": {
        "priority_places": ["Bet Dwarka", "Somnath", "Gir", "Diu"],
        "sightseeing": {
            "Dwarka":     ["Dwarkadhish Temple", "Rukmini Temple", "Gomti Ghat",
                           "Lighthouse", "Sudama Setu Bridge"],
            "Bet Dwarka": ["Bet Dwarka Island", "Shankhodhar Temple", "Handavav Beach"],
            "Somnath":    ["Somnath Temple", "Triveni Ghat", "Bhalka Tirth", "Prabhas Patan Museum"],
            "Gir":        ["Gir National Park Safari", "Devaliya Safari Park",
                           "Tulsi Shyam Temple", "Crocodile Breeding Center"],
            "Diu":        ["Diu Fort", "Nagoa Beach", "INS Khukri Memorial",
                           "St. Paul's Church", "Gangeshwar Temple"],
        },
        "routes": {
            3: [["Dwarka", "Bet Dwarka", "Somnath"],
                ["Dwarka", "Somnath", "Gir"],
                ["Dwarka", "Bet Dwarka", "Diu"]],
            4: [["Dwarka", "Bet Dwarka", "Somnath", "Gir"],
                ["Dwarka", "Somnath", "Gir", "Diu"],
                ["Dwarka", "Bet Dwarka", "Somnath", "Diu"],
                ["Bet Dwarka", "Dwarka", "Somnath", "Gir"]],
            5: [["Dwarka", "Bet Dwarka", "Somnath", "Gir", "Diu"],
                ["Dwarka", "Somnath", "Gir", "Diu", "Porbandar"],
                ["Bet Dwarka", "Dwarka", "Somnath", "Gir", "Diu"]],
            6: [["Dwarka", "Bet Dwarka", "Somnath", "Gir", "Diu", "Porbandar"],
                ["Dwarka", "Somnath", "Gir", "Diu", "Porbandar", "Junagadh"],
                ["Bet Dwarka", "Dwarka", "Somnath", "Gir", "Diu", "Junagadh"]],
        },
    },
    "Gokarna": {
        "priority_places": ["Murudeshwar", "Jog Falls", "Honavar", "Udupi", "Dandeli"],
        "sightseeing": {
            "Gokarna":     ["Om Beach", "Kudle Beach", "Half Moon Beach",
                            "Mahabaleshwar Temple", "Mirjan Fort"],
            "Murudeshwar": ["Murudeshwar Temple", "Shiva Statue", "Murudeshwar Beach", "Net Fish Island"],
            "Jog Falls":   ["Jog Falls Viewpoint", "Linganamakki Dam", "Trekking Trails"],
            "Honavar":     ["Kasarkod Beach", "Manki Beach", "Tada Beach", "Honavar Port"],
            "Udupi":       ["Krishna Temple", "Malpe Beach", "St. Mary's Island", "Kaup Beach", "Barkur"],
            "Dandeli":     ["Dandeli Wildlife Sanctuary", "River Rafting", "Kayaking", "Kulgi Nature Camp"],
        },
        "routes": {
            3: [["Gokarna", "Murudeshwar", "Udupi"],
                ["Gokarna", "Murudeshwar", "Jog Falls"],
                ["Gokarna", "Honavar", "Murudeshwar"]],
            4: [["Gokarna", "Murudeshwar", "Udupi", "Jog Falls"],
                ["Gokarna", "Honavar", "Murudeshwar", "Udupi"],
                ["Gokarna", "Murudeshwar", "Jog Falls", "Dandeli"],
                ["Gokarna", "Jog Falls", "Murudeshwar", "Udupi"]],
            5: [["Gokarna", "Murudeshwar", "Jog Falls", "Udupi", "Dandeli"],
                ["Gokarna", "Honavar", "Murudeshwar", "Udupi", "Jog Falls"],
                ["Gokarna", "Murudeshwar", "Udupi", "Dandeli", "Jog Falls"]],
            6: [["Gokarna", "Murudeshwar", "Jog Falls", "Honavar", "Udupi", "Dandeli"],
                ["Gokarna", "Honavar", "Murudeshwar", "Jog Falls", "Udupi", "Dandeli"],
                ["Dandeli", "Gokarna", "Murudeshwar", "Jog Falls", "Honavar", "Udupi"]],
        },
    },
}


def _get_destination_config(destination: str) -> dict | None:
    dest_title = destination.strip().title()
    if dest_title in DESTINATION_CONFIG:
        return DESTINATION_CONFIG[dest_title]
    dest_lower = destination.strip().lower()
    for key, cfg in DESTINATION_CONFIG.items():
        if key.lower() == dest_lower:
            return cfg
    return None


def _is_in_config(destination: str) -> bool:
    return _get_destination_config(destination) is not None


# ─────────────────────────────────────────────────────────────────────────────
# INTENT CLASSIFIER
# ─────────────────────────────────────────────────────────────────────────────

INTENT_ANSWER         = "ANSWER"
INTENT_MODIFY         = "MODIFY"
INTENT_GENERAL        = "GENERAL"
INTENT_NEW_ENQUIRY    = "NEW_ENQUIRY"
INTENT_EXPERT         = "EXPERT"
INTENT_GREETING       = "GREETING"
INTENT_COMPANY        = "COMPANY_INFO"
INTENT_DISCOUNT       = "DISCOUNT"
INTENT_MEAL_PRICE     = "MEAL_PRICE"
INTENT_BEST_SELLER_OK = "BEST_SELLER_OK"
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

_MODIFY_KEYWORDS = [
    "change", "modify", "update", "edit", "add", "remove", "replace",
    "different", "instead", "more", "less", "increase", "decrease",
    "hotel", "place", "destination", "sightseeing", "activity",
    "include", "exclude",
]

_BEST_SELLER_OK_PHRASES    = {"looks good", "send full itinerary" "looks great", "this is good", "perfect", "ok", "okay"}
_BEST_SELLER_MODIFY_PHRASES = {"modify", "change", "customize", "i want to change", "modify this"}


def classify_intent(message: str, stage: int, data: dict) -> str:
    msg = _norm(message)

    if msg in _GREETING_PATTERNS:
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

    if stage == STAGE_PACKAGE:
        if re.search(r'\b(package\s*)?\d+\b', msg):
            return INTENT_ANSWER
        if "create custom" in msg or "custom package" in msg:
            return INTENT_ANSWER

    if stage == STAGE_GROUP_TOUR_CHOICE:
        if any(t in msg for t in ["group", "group tour"]):
            return INTENT_ANSWER
        if any(t in msg for t in ["single", "private", "individual"]):
            return INTENT_ANSWER

    if stage == STAGE_ITINERARY_REVIEW:
        if _is_approval(message):
            return INTENT_ANSWER
        if any(t in msg for t in ["modify", "change", "edit", "update"]):
            return INTENT_MODIFY

    if stage == STAGE_TICKET_CHECK:
        yes_words = ["yes", "booked", "already booked", "done", "confirmed"]
        no_words  = ["no", "not yet", "haven't", "will book later"]
        if any(t in msg for t in yes_words):
            return INTENT_ANSWER
        if any(t in msg for t in no_words):
            return INTENT_ANSWER

    if stage == STAGE_POST_ITINERARY:
        if any(t in msg for t in ["talk to expert", "expert", "connect", "book", "agent"]):
            return INTENT_EXPERT
        if any(t in msg for t in ["modify", "change", "edit", "update"]):
            return INTENT_MODIFY

    if data.get("_itinerary_sent") or data.get("confirmed_destination"):
        if any(re.search(r'\b' + re.escape(kw) + r'\b', msg) for kw in _MODIFY_KEYWORDS):
            if stage not in (STAGE_PACKAGE,):
                return INTENT_MODIFY

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

    mark_lead_hot(session)

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
    if data.get("selected_places"):
        parts.append(f"Selected places: {', '.join(data['selected_places'])}")
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


def build_daywise_flow(days: int) -> dict | None:
    flow_id = DAYWISE_FLOW_MAP.get(days)
    if not flow_id:
        return None
    return build_flow_message(
        flow_id,
        f"Build Your {days}-Day Itinerary",
        f"Fill in the activity and night stay for each of your {days} days.",
        "Build Itinerary",
    )


def build_group_tour_date_picker(min_date_str: str) -> dict:
    return {
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": "Select Departure Date"},
            "body": {
                "text": (
                    f"Please select your preferred departure date.\n"
                    f"Earliest available date: {min_date_str}"
                )
            },
            "footer": {"text": COMPANY_SHORT},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token":           "unused",
                    "flow_id":              FLOW_GROUP_DATE,
                    "flow_cta":             "Select Date",
                    "flow_action":          "navigate",
                    "flow_action_payload":  {"screen": "GROUP_DATE_PICKER"},
                },
            },
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# FLOW SUBMISSION PARSERS
# ─────────────────────────────────────────────────────────────────────────────

def parse_basic_travel_flow(payload: dict) -> dict:
    result = {
        "name":           payload.get("name", "").strip(),
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


def parse_group_date_flow(payload: dict) -> str | None:
    departure_option = payload.get("departure_option", "").strip()
    custom_date      = payload.get("custom_date",      "").strip()

    if custom_date:
        return _normalise_date_string(custom_date)
    if departure_option and departure_option.lower() not in ("custom", "other", ""):
        return _normalise_date_string(departure_option)
    return None


def _normalise_date_string(raw: str) -> str:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%d %b %Y")
        except ValueError:
            continue
    return raw


def parse_daywise_flow(payload: dict, days: int) -> list:
    day_data = []
    for d in range(1, days + 1):
        activity = payload.get(f"day{d}_activity", "").strip()
        stay     = payload.get(f"day{d}_stay",     "").strip()
        day_data.append({"day": d, "activity": activity, "stay": stay})
    return day_data


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

    if stage == STAGE_FLOW_SENT:
        logger.debug("[FLOW ID] Stage=STAGE_FLOW_SENT → FLOW_BASIC_TRAVEL")
        return FLOW_BASIC_TRAVEL

    if stage == STAGE_GROUP_TOUR_DATE:
        logger.debug("[FLOW ID] Stage=STAGE_GROUP_TOUR_DATE → FLOW_GROUP_DATE")
        return FLOW_GROUP_DATE

    if stage == STAGE_CUSTOM_FLOW_SENT:
        days = session_data.get("days")
        if days and int(days) in DAYWISE_FLOW_MAP:
            flow_id = DAYWISE_FLOW_MAP[int(days)]
            logger.debug(f"[FLOW ID] Stage=STAGE_CUSTOM_FLOW_SENT, days={days} → {flow_id}")
            return flow_id

    if stage == STAGE_BEST_SELLER_SENT:
        if "name" in payload or "trip_days" in payload:
            return FLOW_BASIC_TRAVEL

    if "departure_option" in payload or "custom_date" in payload:
        logger.debug("[FLOW ID] Key 'departure_option'/'custom_date' found → FLOW_GROUP_DATE")
        return FLOW_GROUP_DATE

    if "name" in payload or "trip_days" in payload:
        logger.debug("[FLOW ID] Key 'name'/'trip_days' found → FLOW_BASIC_TRAVEL")
        return FLOW_BASIC_TRAVEL

    day_keys = [k for k in payload if re.match(r"^day\d+_activity$", k)]
    if day_keys:
        inferred_days = max(
            int(re.search(r"day(\d+)_activity", k).group(1)) for k in day_keys
        )
        inferred_id = DAYWISE_FLOW_MAP.get(inferred_days)
        if inferred_id:
            logger.debug(f"[FLOW ID] Day keys found, inferred {inferred_days} days → {inferred_id}")
            return inferred_id

    logger.warning(
        f"[FLOW ID] Cannot identify flow. Payload keys: {list(payload.keys())}, stage={_stage_name(stage)}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# RULE-BASED PACKAGE GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_packages_from_config(destination: str, days: int) -> list:
    cfg = _get_destination_config(destination)
    if not cfg:
        return []
    dest_title      = destination.strip().title()
    routes_for_days = cfg.get("routes", {}).get(days, [])
    if not routes_for_days:
        priority    = cfg.get("priority_places", [])
        places_pool = [dest_title] + priority
        stops       = _stops_for_days(days)
        routes_for_days = []
        if len(places_pool) >= stops:
            routes_for_days.append(places_pool[:stops])
            if len(places_pool) > stops:
                alt = [dest_title] + list(reversed(priority))
                routes_for_days.append(alt[:stops])
    packages = []
    seen = set()
    for route in routes_for_days:
        route_key = frozenset(r.lower() for r in route)
        if route_key in seen:
            continue
        seen.add(route_key)
        title = " - ".join(route) + f" ({days} Days)"
        packages.append({"title": title, "highlights": route, "route": route})
    return packages


def _present_packages_from_config(destination: str, days: int, data: dict) -> dict:
    packages = generate_packages_from_config(destination, days)
    if not packages:
        return {"message": "", "options": [], "packages": []}
    data["_trip_packages"] = packages
    header  = f"Available packages for your {days}-day trip to {destination}:"
    lines   = [header, ""]
    options = []
    for i, pkg in enumerate(packages, 1):
        lines.append(f"Package {i}: {pkg['title']}")
        options.append(f"Package {i}")
    options.append("Create Custom Package")
    lines += ["", "Select a package number or choose to create a custom itinerary."]
    return {"message": "\n".join(lines).strip(), "options": options, "packages": packages}


def _resolve_package_from_config(message: str, packages: list) -> dict | None:
    msg       = _norm(message)
    num_match = re.search(r"\b(?:package\s*)?(\d+)\b", msg)
    if num_match:
        idx = int(num_match.group(1)) - 1
        if 0 <= idx < len(packages):
            return packages[idx]
    for pkg in packages:
        if pkg.get("title", "").lower() in msg:
            return pkg
    return None


# ─────────────────────────────────────────────────────────────────────────────
# DESTINATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _stops_for_days(days: int) -> int:
    if days <= 3: return 2
    elif days == 4: return 3
    elif days == 5: return 4
    elif days == 6: return 5
    elif days == 7: return 6
    elif days == 8: return 7
    else: return 8


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


def _is_group_tour_destination(destination: str) -> bool:
    return destination.strip().lower() in GROUP_TOUR_DESTINATIONS


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
# APPROVAL DETECTION
# ─────────────────────────────────────────────────────────────────────────────

APPROVAL_EXACT = {
    "looks good", "looks great", "perfect", "confirmed", "approved" "send full itinerary",
    "satisfied", "great", "nice",
}

APPROVAL_CONTAINS = [
    "looks good", "looks great", "all good", "seems good" "send full itinerary",
]


def _is_approval(message: str) -> bool:
    msg = _norm(message)
    if msg in APPROVAL_EXACT:
        return True
    return any(phrase in msg for phrase in APPROVAL_CONTAINS)


def _is_modification_request(message: str) -> bool:
    msg = _norm(message)
    if _is_approval(message):
        return False
    for kw in _MODIFY_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', msg):
            return True
    return len(message.strip()) > 20


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
# HOTEL HELPER  (LEGACY — kept for backward compatibility only)
# ─────────────────────────────────────────────────────────────────────────────

def _hotels_for(destination: str) -> list:
    dest_lower  = destination.lower().strip()
    cities      = DESTINATION_TO_HOTEL_CITY.get(dest_lower, [])
    dest_title  = destination.title()
    if dest_title in HOTEL_DATA and dest_title not in cities:
        cities = [dest_title] + cities
    if not cities and dest_title in HOTEL_DATA:
        cities = [dest_title]
    result, seen = [], set()
    for city in cities:
        if city in HOTEL_DATA and city not in seen:
            result.append((city, random.choice(HOTEL_DATA[city])))
            seen.add(city)
    return result or [(destination, f"3 Star AC Hotel in {destination} (to be confirmed)")]


# ─────────────────────────────────────────────────────────────────────────────
# PRICING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _adult_per_person_rate(adults: int, days: int, destination: str) -> float:
    nights = max(days - 1, 0)
    if adults <= 4:
        veh_per_day = 4500
    elif adults == 5:
        veh_per_day = 5500
    elif adults <= 7:
        veh_per_day = 6500
    elif adults <= 12:
        veh_per_day = 8000
    elif adults <= 18:
        veh_per_day = 10000
    else:
        veh_per_day = 700 * adults
    total_vehicle    = veh_per_day * days
    total_hotel      = 1300 * adults * nights
    base             = total_vehicle + total_hotel
    total_adult_cost = base * 1.25
    if any(k in destination.lower() for k in ["alleppey", "kerala"]):
        total_adult_cost += 3000 * adults
    if adults == 0:
        return 0.0
    return round(total_adult_cost / adults, 2)


def _price_per_person(adults: int, days: int, destination: str,
                      children: list = None) -> float:
    return _adult_per_person_rate(adults, days, destination)


def _total_trip_cost(adults: int, days: int, destination: str,
                     children_ages: list = None) -> float:
    adult_rate = _adult_per_person_rate(adults, days, destination)
    total = adult_rate * adults
    for age in (children_ages or []):
        if age < 6:
            pass
        elif age <= 8:
            total += adult_rate * 0.5
        else:
            total += adult_rate
    return round(total, 2)


def _child_price_breakdown(adults: int, days: int, destination: str,
                           children_ages: list) -> str:
    if not children_ages:
        return ""
    adult_rate = _adult_per_person_rate(adults, days, destination)
    lines = []
    for age in children_ages:
        if age < 6:
            lines.append(f"  Child aged {age}: Free (below 6 years)")
        elif age <= 8:
            lines.append(f"  Child aged {age}: Rs. {round(adult_rate * 0.5):,.0f} (half charge, age 6-8)")
        else:
            lines.append(f"  Child aged {age}: Rs. {round(adult_rate):,.0f} (full charge, above 8 years)")
    return "\n".join(lines)


def _vehicle(adults: int, children_count: int = 0) -> str:
    total = adults + children_count
    if total <= 4:    return "Dzire / Etios"
    elif total == 5:  return "Ertiga"
    elif total <= 7:  return "Innova Crysta"
    elif total <= 12: return "12-Seater Tempo Traveller"
    else:             return "18-Seater Tempo Traveller"


def _extract_total_cost_from_itinerary(itinerary: str, data: dict) -> float:
    adults        = int(data.get("adults", 2))
    days          = int(data.get("days", 4))
    destination   = data.get("confirmed_destination") or data.get("destination", "India")
    children_ages = data.get("children_ages", [])
    return _total_trip_cost(adults, days, destination, children_ages)


# ─────────────────────────────────────────────────────────────────────────────
# AIRPORT GATEWAY
# ─────────────────────────────────────────────────────────────────────────────

def generate_arrival_gateway(city: str) -> dict:
    prompt = (f"You are an expert Indian travel routing assistant.\n"
              f"City: {city}\n"
              f'Return ONLY valid JSON: {{"airport": "Airport Name (CODE)", "city": "City Name"}}\n'
              f"No markdown. No explanation. Nearest airport to THIS city only.")
    try:
        response = _deepseek(prompt)
        response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(response)
        return {"airport": data.get("airport", "Nearest airport available"),
                "city":    data.get("city", city)}
    except Exception:
        return {"airport": "Nearest airport available", "city": city}


# ─────────────────────────────────────────────────────────────────────────────
# ITINERARY GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def generate_trip_title(destination: str, days: int) -> str:
    prompt = (f"Create a professional travel package title.\n"
              f"Destination: {destination}\nDuration: {days} Days\n"
              f"RULES: Max 10-12 words. No quotes. No markdown. Return ONLY title.")
    try:
        title = _deepseek(prompt)
        return _strip_markdown(title).replace("\n", "").strip()
    except Exception:
        return f"{destination} Tour {days} Days"


def generate_hotels(destination: str, days: int, places: list | None = None) -> str:
    cities = []
    for p in (places or []):
        p = (p or "").strip()
        if p and p not in cities:
            cities.append(p)
    if not cities:
        fallback_city = destination.strip().title() if destination else "Destination"
        cities = [fallback_city]
    lines = [f"{city} - 3 Star Hotel" for city in cities]
    return "\n".join(lines)


def _build_itinerary_prompt(data: dict) -> str:
    destination    = data.get("confirmed_destination") or data.get("destination", "India")
    days           = int(data.get("days", 4))
    adults         = int(data.get("adults", 2))
    children_ages  = data.get("children_ages", [])
    children_count = len(children_ages)
    nights         = max(days - 1, 0)
    selected_places = data.get("selected_places", [])

    trip_title  = generate_trip_title(destination, days)
    hotel_str   = generate_hotels(destination, days, selected_places)

    gateway_key = destination.lower().strip()
    gateway     = ARRIVAL_GATEWAY.get(gateway_key, ARRIVAL_GATEWAY.get("default"))
    if not gateway or gateway.get("city") in ("Nearest hub city", ""):
        gateway = generate_arrival_gateway(destination)

    first_airport = gateway.get("airport", "Nearest Airport")
    day1_city     = selected_places[0] if selected_places else destination

    if selected_places and len(selected_places) > 1:
        last_dest    = selected_places[-1]
        last_gateway = ARRIVAL_GATEWAY.get(last_dest.lower(), generate_arrival_gateway(last_dest))
        last_airport = last_gateway.get("airport", first_airport)
    else:
        last_airport = first_airport

    if children_ages:
        ages_str      = ", ".join(str(a) for a in children_ages)
        traveller_str = (f"{adults} Adults, {children_count} "
                         f"{'Child' if children_count == 1 else 'Children'} (Ages: {ages_str})")
    else:
        traveller_str = f"{adults} Adults"

    per_person      = _price_per_person(adults, days, destination, children_ages)
    total_cost      = _total_trip_cost(adults, days, destination, children_ages)
    advance_amount  = round(total_cost * 0.10, 2)
    child_breakdown = _child_price_breakdown(adults, days, destination, children_ages)
    veh             = _vehicle(adults, children_count)
    child_section   = (f"\nChild Price Breakdown:\n{child_breakdown}\n" if child_breakdown else "")

    places_block = ""
    if selected_places:
        places_list  = "\n".join(f"- {p}" for p in selected_places)
        places_block = f"""
MANDATORY CIRCUIT DESTINATIONS (in strict order):
{places_list}

CRITICAL RULES:
- Itinerary MUST follow this circuit in this exact order
- Day 1 sightseeing MUST be ONLY at {day1_city}
- Do NOT combine multiple cities on Day 1
- Last day drop at {last_airport}
"""

    special_notes = data.get("special_notes", "")
    notes_block   = f"\nSPECIAL REQUESTS: {special_notes}\n" if special_notes else ""
    pending_mods  = data.get("_pending_modifications", [])
    mods_block    = ("\nUSER REQUESTED CHANGES:\n" +
                    "\n".join(f"- {m}" for m in pending_mods) + "\n") if pending_mods else ""

    return f"""You are a professional Indian travel itinerary creator for {COMPANY_SHORT}.

CRITICAL FORMATTING RULES:
1. Do NOT use asterisks, double asterisks, hash symbols, or any markdown.
2. Do NOT use emojis anywhere.
3. Section headings in CAPITAL LETTERS on their own line.
4. Sightseeing MUST be bullet points using "- " prefix.
5. Write in strict professional English only.
6. The HOTEL NAMES section below already contains the exact text to use, one
   line per city. Copy it EXACTLY as given, unchanged. Do NOT invent, guess,
   add, or substitute any real hotel brand name anywhere in this document —
   only the exact "CityName - 3 Star Hotel" format is allowed.

MOST IMPORTANT — DAY 1:
- Day 1 MUST include sightseeing ONLY at {day1_city}.
- Even if airport is in another city, Day 1 sightseeing = {day1_city} ONLY.
- List at least 3 real attractions at {day1_city}.
- Do NOT include any other city on Day 1.

ALL TOURS START AND END AT AIRPORT ONLY.
- Day 1: Pickup from {first_airport}, transfer to {day1_city}, sightseeing at {day1_city}
- Last Day: Sightseeing at last city, then drop at {last_airport}

TRIP DETAILS
Destination  : {destination}
Duration     : {days} Days / {nights} Nights
Travellers   : {traveller_str}
Pickup       : {first_airport}
Drop         : {last_airport}
{places_block}{notes_block}{mods_block}

OUTPUT FORMAT

{trip_title}

PICKUP: {first_airport}
DROP: {last_airport}

[Write day-by-day itinerary with bullet-point sightseeing]

SUGGESTED ACCOMMODATION

{hotel_str}

TOTAL TOUR PACKAGE PRICE

Rs. {per_person:,.0f} per person (basis {adults} adults){child_section}
Total Trip Cost: Rs. {total_cost:,.0f}
Advance (10%): Rs. {advance_amount:,.0f}
Vehicle: {veh}

INCLUSIONS

Vehicle as per group size for entire circuit
Airport pickup and drop included
Accommodation in 3 Star AC rooms with breakfast
Driver charges, Parking charges, Toll taxes
All applicable taxes

EXCLUSIONS

Flight tickets (not included in package price)
Entry tickets to monuments and attractions
Boating and activity charges
Personal expenses and tips
Meals other than breakfast (approx Rs. 300 or more per meal per person at local restaurants)
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

Minimum Rs.3000 cancellation charge per person
25 percent cancellation between 45 to 30 days before departure
50 percent cancellation between 30 to 15 days before departure
75 percent cancellation between 15 to 5 days before departure
100 percent cancellation within 5 days of departure or no show

FINAL NOTE

Extra charges apply during long weekends, holidays, and festival dates.
Flight tickets are not included in the package price.
Package price covers ground transportation within the circuit only."""


def generate_itinerary(data: dict) -> dict:
    prompt        = _build_itinerary_prompt(data)
    itinerary_txt = _deepseek(prompt) or _fallback_itinerary(data)
    return {"itinerary": _strip_markdown(itinerary_txt)}


def generate_itinerary_from_daywise(data: dict, day_data: list) -> str:
    destination    = data.get("confirmed_destination") or data.get("destination", "India")
    days           = int(data.get("days", len(day_data)))
    adults         = int(data.get("adults", 2))
    children_ages  = data.get("children_ages", [])
    children_count = len(children_ages)
    nights         = max(days - 1, 0)
    veh            = _vehicle(adults, children_count)
    per_person     = _price_per_person(adults, days, destination, children_ages)
    total_cost     = _total_trip_cost(adults, days, destination, children_ages)
    advance_amount = round(total_cost * 0.10, 2)
    child_breakdown = _child_price_breakdown(adults, days, destination, children_ages)
    trip_title     = generate_trip_title(destination, days)
    special_notes  = data.get("special_notes", "")

    stay_cities = []
    for d in day_data:
        stay = (d.get("stay") or "").strip()
        if stay and stay not in stay_cities:
            stay_cities.append(stay)
    hotel_str = generate_hotels(destination, days, stay_cities)

    gateway_key   = destination.lower().strip()
    gateway       = ARRIVAL_GATEWAY.get(gateway_key, ARRIVAL_GATEWAY.get("default"))
    if not gateway or gateway.get("city") in ("Nearest hub city", ""):
        gateway = generate_arrival_gateway(destination)
    first_airport = gateway.get("airport", "Nearest Airport")

    traveller_str = f"{adults} Adults"
    if children_ages:
        ages_str      = ", ".join(str(a) for a in children_ages)
        traveller_str = f"{adults} Adults, {children_count} Children (Ages: {ages_str})"

    child_section = (f"\nChild Price Breakdown:\n{child_breakdown}\n" if child_breakdown else "")
    notes_block   = f"\nSPECIAL REQUESTS: {special_notes}\n" if special_notes else ""

    day_lines = []
    for d in day_data:
        day_lines.append(f"Day {d['day']} Activity: {d['activity']}")
        day_lines.append(f"Day {d['day']} Night Stay: {d['stay']}")
    day_block = "\n".join(day_lines)

    prompt = f"""You are a professional Indian travel itinerary creator for {COMPANY_SHORT}.

Format the following day-wise information into a clean travel itinerary.

CRITICAL FORMATTING RULES:
1. No asterisks, no markdown, no emojis.
2. Section headings in CAPITAL LETTERS.
3. Sightseeing in bullet points using "- " prefix.
4. Day 1 MUST include pickup from {first_airport} before sightseeing.
5. Last day MUST include drop to {first_airport}.
6. Professional English only.
7. The HOTEL NAMES section below already contains the exact text to use, one
   line per city. Copy it EXACTLY as given, unchanged. Do NOT invent, guess,
   add, or substitute any real hotel brand name anywhere in this document —
   only the exact "CityName - 3 Star Hotel" format is allowed.

TRIP DETAILS
Destination : {destination}
Duration    : {days} Days / {nights} Nights
Travellers  : {traveller_str}
Pickup      : {first_airport}
Drop        : {first_airport}
{notes_block}
DAY-WISE PLAN SUBMITTED BY USER:
{day_block}

OUTPUT FORMAT

{trip_title}

PICKUP: {first_airport}
DROP: {first_airport}

[Format each day using the submitted activity and stay details.
Day 1 must start with airport pickup. Last day must end with airport drop.
Expand each activity into 2-3 bullet point sightseeing items where possible.]

SUGGESTED ACCOMMODATION

{hotel_str}

TOTAL TOUR PACKAGE PRICE

Rs. {per_person:,.0f} per person (basis {adults} adults){child_section}
Total Trip Cost: Rs. {total_cost:,.0f}
Advance (10%): Rs. {advance_amount:,.0f}
Vehicle: {veh}

INCLUSIONS

Vehicle as per group size
Airport pickup and drop
Accommodation in 3 Star AC rooms with breakfast
Driver charges, Parking, Toll taxes
All applicable taxes

EXCLUSIONS

Flight tickets
Entry tickets to monuments
Boating and activity charges
Personal expenses and tips
Meals other than breakfast (approx Rs. 300 or more per meal per person)

PAYMENT POLICY

20 percent advance at time of booking
20 percent after hotel booking voucher
60 percent during tour in parts

CHILD POLICY

Child up to 6 years: Free
Child 6 to 8 years: Half charge
Child above 8 years: Full charge

CANCELLATION POLICY

Minimum Rs.3000 per person
25 percent between 45 to 30 days
50 percent between 30 to 15 days
75 percent between 15 to 5 days
100 percent within 5 days or no show

FINAL NOTE

Flight tickets are not included. Extra charges on holidays and festivals."""

    result = _deepseek(prompt)
    return _strip_markdown(result) if result else _fallback_itinerary(data)


def _fallback_itinerary(data: dict) -> str:
    dest            = data.get("confirmed_destination") or data.get("destination", "Destination")
    days            = int(data.get("days", 4))
    adults          = int(data.get("adults", 2))
    children_ages   = data.get("children_ages", [])
    children_count  = len(children_ages)
    nights          = max(days - 1, 0)
    veh             = _vehicle(adults, children_count)
    selected_places = data.get("selected_places", [])
    hotel_str       = generate_hotels(dest, days, selected_places)
    gateway         = ARRIVAL_GATEWAY.get(dest.lower(), ARRIVAL_GATEWAY.get("default"))
    first_airport   = gateway.get("airport", "Nearest Airport")
    traveller_str   = (f"{adults} Adults, {_format_children_summary(children_ages)}"
                       if children_ages else f"{adults} Adults")
    day1_city       = selected_places[0] if selected_places else dest

    lines = [
        f"{dest.upper()} TOUR PACKAGE", f"{days} Days / {nights} Nights", "",
        f"Pickup  : {first_airport}", f"Drop    : {first_airport}",
        f"Travellers : {traveller_str}", "",
    ]
    for d in range(days):
        day_num = d + 1
        if day_num == 1:
            lines += [f"Day {day_num}: Arrival and Sightseeing in {day1_city}", "",
                      f"Arrive at {first_airport}. Transfer to {day1_city}. Check-in and freshen up.",
                      f"Afternoon sightseeing in {day1_city}:",
                      f"- Main Temple / Famous Landmark of {day1_city}",
                      "- Local Market and Bazaar", "- Evening viewpoint or riverside",
                      f"Overnight stay in {day1_city}.", ""]
        elif day_num == days:
            lines += [f"Day {day_num}: Last Sightseeing and Departure", "",
                      "Morning sightseeing:", "- Morning walk and local sightseeing",
                      "- Last-minute shopping (optional)", "Post-lunch check-out from hotel.",
                      f"Transfer to {first_airport}. Tour ends.", ""]
        else:
            place = selected_places[d] if d < len(selected_places) else dest
            lines += [f"Day {day_num}: Sightseeing in {place}", "",
                      f"- Main attraction at {place}",
                      "- Visit popular historical or nature spots",
                      "- Evening leisure walk or local market",
                      f"Overnight stay in {place}.", ""]

    per_p           = _price_per_person(adults, days, dest, children_ages)
    total_cost      = _total_trip_cost(adults, days, dest, children_ages)
    advance_amount  = round(total_cost * 0.10, 2)
    child_breakdown = _child_price_breakdown(adults, days, dest, children_ages)
    lines += ["SUGGESTED ACCOMMODATION", "", hotel_str]
    lines += ["", "TOTAL TOUR PACKAGE PRICE", "",
              f"Rs. {per_p:,.0f} per person (basis {adults} adults)"]
    if child_breakdown:
        lines += ["", "Child Price Breakdown:", child_breakdown]
    lines += ["",
              f"Total Trip Cost: Rs. {total_cost:,.0f}",
              f"Advance (10%): Rs. {advance_amount:,.0f}",
              f"Vehicle: {veh}", "",
              "CHILD POLICY", "Child up to 6 years: Free",
              "Child 6 to 8 years: Half charge", "Child above 8 years: Full charge", "",
              "Note: Meals are not included. Approx Rs. 300 or more per meal at local restaurants.",
              "Note: Flight tickets are not included in the package price."]
    return "\n".join(lines)


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
    session.step          = STAGE_CHAT
    session.data["stage"] = STAGE_CHAT
    session.data["_expert_contacted"]  = True
    session.data["_followup_stopped"]  = True
    _save_session(session)
    logger.info(f"[LEAD HANDOFF] dest={dest}, stage → STAGE_CHAT")
    msg = (f"Connecting you with our travel expert{dest_str} for final pricing and booking. "
           f"Our team will contact you shortly.")
    return _make(msg, ["Plan New Trip"], social_card=SOCIAL_CARD)


# ─────────────────────────────────────────────────────────────────────────────
# BEST SELLER STAGE HANDLER  (v17.7.0 — updated)
# ─────────────────────────────────────────────────────────────────────────────

def _send_best_seller_package(session, bs_key: str) -> dict:
    """
    Send the best seller package teaser card for bs_key and move to STAGE_BEST_SELLER_SENT.
    Records the timestamp so the follow-up timer can fire after 10 minutes.
    """
    data = session.data
    msg  = _build_best_seller_message(bs_key)
    if not msg:
        return _handle_destination_collection(session, bs_key)

    data["stage"]                = STAGE_BEST_SELLER_SENT
    data["_best_seller_sent_ts"] = datetime.utcnow().isoformat()
    data["_best_seller_key"]     = bs_key
    dest_title = bs_key.title()
    if not data.get("confirmed_destination"):
        data["destination"]           = dest_title
        data["confirmed_destination"] = dest_title
    session.data = data
    session.step = STAGE_BEST_SELLER_SENT
    _save_session(session)

    try:
        mark_lead_follow_up(session)
    except Exception as e:
        logger.error(f"[BEST SELLER] mark_lead_follow_up failed: {e}")

    logger.info(f"[BEST SELLER] Sent teaser for key={bs_key}, stage → STAGE_BEST_SELLER_SENT")
    return _make(msg, ["Send Full Itinerary", "Modify", "Talk to Expert"])


def _handle_stage_best_seller_sent(session, message: str, intent: str) -> dict:
    """
    Handle user response to the best seller package teaser card.

    v17.7.0 CHANGE:
    Looks Good   → mark HOT + send FULL pre-written itinerary + move to STAGE_ITINERARY_REVIEW
                   (instead of immediately handing off to sales agent)
    Modify       → send basic travel flow; after submission → handoff
    Talk to Expert (INTENT_EXPERT handled upstream) → handoff + mark HOT
    """
    data   = session.data
    msg_l  = _norm(message)
    bs_key = data.get("_best_seller_key", "")

    # "Looks Good" — send the full pre-written itinerary
    if intent == INTENT_BEST_SELLER_OK or msg_l in _BEST_SELLER_OK_PHRASES:
        try:
            mark_lead_hot(session)
        except Exception as e:
            logger.error(f"[BEST SELLER OK] mark_lead_hot failed: {e}")

        full_itinerary = _get_best_seller_full_itinerary(bs_key)

        if full_itinerary:
            # Persist the itinerary and move to STAGE_ITINERARY_REVIEW
            _persist_itinerary(session, full_itinerary)
            data["_itinerary_sent"] = True
            data["_last_itinerary"] = full_itinerary
            data["stage"]           = STAGE_ITINERARY_REVIEW
            session.data            = data
            session.step            = STAGE_ITINERARY_REVIEW
            _save_session(session)

            logger.info(
                f"[BEST SELLER OK] Full itinerary sent for key={bs_key}, "
                f"stage → STAGE_ITINERARY_REVIEW"
            )
            return {
                "message": "Here is your complete tour package itinerary:\n\n" + full_itinerary,
                "options": ["Talk to Expert", "Modify"],
                "social_card": SOCIAL_CARD,
            }
        else:
            # No pre-written itinerary available — fall back to lead handoff
            logger.warning(
                f"[BEST SELLER OK] No full itinerary for key={bs_key}, falling back to handoff"
            )
            return handle_lead_handoff(session)

    # "Modify" — send basic travel flow to collect trip details
    if intent == INTENT_BEST_SELLER_MOD or msg_l in _BEST_SELLER_MODIFY_PHRASES:
        data["stage"]     = STAGE_FLOW_SENT
        data["_flow_sent"] = True
        session.data      = data
        session.step      = STAGE_FLOW_SENT
        _save_session(session)
        logger.info("[BEST SELLER MOD] User wants to modify → sending basic travel flow")
        return _make(
            "Please fill in your travel details and we will customise the package for you.",
            [],
            flow_payload=build_basic_travel_flow(),
        )

    # Ambiguous — re-show the options
    pkg_title = BEST_SELLER_PACKAGES.get(bs_key, {}).get("title", "our best seller package")
    return _make(
        f"Would you like to proceed with {pkg_title}?",
        ["Looks Good", "Modify", "Talk to Expert"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# PAY AND BOOK HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def handle_pay_and_book(session) -> dict:
    data       = session.data
    total_cost = _extract_total_cost_from_itinerary(data.get("_last_itinerary", ""), data)
    advance    = round(total_cost * 0.10, 2)
    dest       = data.get("confirmed_destination") or data.get("destination", "your destination")
    try:
        Lead.objects.get_or_create(
            session=session,
            defaults={
                "name":        data.get("_name", "WhatsApp User"),
                "phone":       session.phone_number or "",
                "destination": dest,
            },
        )
    except Exception:
        pass
    data["_followup_stopped"] = True
    session.data = data
    _save_session(session)
    msg = (
        f"To confirm your booking for {dest}, please pay the advance amount:\n\n"
        f"Total Trip Cost: Rs. {total_cost:,.0f}\n"
        f"Advance (10%): Rs. {advance:,.0f}\n\n"
        f"Payment Link: {PAYMENT_LINK}\n\n"
        f"After payment, share the transaction screenshot and our team will confirm your booking."
    )
    return _make(msg, ["Talk to Expert", "Modify"])


# ─────────────────────────────────────────────────────────────────────────────
# MODIFY ENGINE
# ─────────────────────────────────────────────────────────────────────────────

MODIFY_OPTIONS = ["Change Date", "Change Adults", "Change Child", "Other Changes"]


def handle_modify_menu(session) -> dict:
    return _make("What would you like to modify?", MODIFY_OPTIONS)


def handle_free_modify(session, message: str) -> dict:
    data      = session.data
    msg_lower = _norm(message)

    if any(t in msg_lower for t in ["talk to expert", "expert", "connect", "call me",
                                    "agent", "book now"]):
        return handle_lead_handoff(session)

    if "change date" in msg_lower or msg_lower == "date":
        data["_modify_mode"] = "date"
        session.data = data
        _save_session(session)
        if data.get("tour_type") == "group":
            min_date = _min_group_tour_date_str()
            return _make(
                f"Please select a new departure date (minimum 21 days from today: {min_date}).",
                [],
                flow_payload=build_group_tour_date_picker(min_date),
            )
        return _make("Please enter your new preferred travel date (e.g. 15 Aug 2025).", [])

    if "change adult" in msg_lower or msg_lower in ("adults", "change adults"):
        num_match = re.search(r'\b(\d+)\s*adult', msg_lower)
        if num_match:
            data["adults"] = int(num_match.group(1))
            data["_pending_modifications"] = [f"Changed adults to {data['adults']}"]
            return _regenerate_and_ask(session)
        data["_modify_mode"] = "adults"
        data["stage"] = STAGE_MODIFY
        session.data  = data
        _save_session(session)
        return _make("How many adults will be travelling?", [])

    if "change child" in msg_lower or msg_lower in ("child", "children", "change child"):
        num_match = re.search(r'\b(\d+)\s*child', msg_lower)
        if num_match:
            data["children_count"] = int(num_match.group(1))
            data["_pending_modifications"] = [f"Changed children count to {data['children_count']}"]
            return _regenerate_and_ask(session)
        data["_modify_mode"] = "children"
        data["stage"] = STAGE_MODIFY
        session.data  = data
        _save_session(session)
        return _make(
            "How many children will be travelling? Please also provide their ages "
            "(e.g. 2 children, ages 5 and 8).", [])

    regen_triggers = [
        "regenerate", "re-generate", "update itinerary", "apply changes",
        "generate itinerary", "apply", "generate", "yes generate", "yes update",
        "re-generate itinerary",
    ]
    if any(t in msg_lower for t in regen_triggers):
        return _regenerate_and_ask(session)

    modify_mode = data.get("_modify_mode", "")

    if modify_mode == "adults":
        num_match = re.search(r'\b(\d+)\b', msg_lower)
        if num_match:
            data["adults"] = int(num_match.group(1))
            data["_modify_mode"] = ""
            data["_pending_modifications"] = [f"Changed adults to {data['adults']}"]
            return _regenerate_and_ask(session)

    if modify_mode == "children":
        nums = re.findall(r'\b(\d+)\b', msg_lower)
        if nums:
            data["children_count"] = int(nums[0])
            if len(nums) > 1:
                data["children_ages"] = [int(n) for n in nums[1:] if 1 <= int(n) <= 17]
            data["_modify_mode"] = ""
            data["_pending_modifications"] = [f"Changed children: {data['children_count']}"]
            return _regenerate_and_ask(session)

    if modify_mode == "date":
        data["departure_date"] = message.strip()
        data["_modify_mode"]   = ""
        data["_pending_modifications"] = [f"Changed travel date to {message.strip()}"]
        return _regenerate_and_ask(session)

    pending_mods = data.get("_pending_modifications", [])
    pending_mods.append(message.strip())
    data["_pending_modifications"] = pending_mods[-10:]

    trip_context = _session_context_str(data)
    prompt = (f"You are a travel consultant at {COMPANY_SHORT}.\n"
              f"RULES: Plain text only. No markdown. No asterisks. 2-3 lines max. Professional English.\n"
              f"Do NOT start with 'Great!', 'Sure!', or 'Of course!'\n"
              f"Current trip: {trip_context}\n"
              f'User modification request: "{message}"\n'
              f"Confirm the change in 2 lines and ask if they want the itinerary regenerated.")

    reply = _strip_markdown(_deepseek(prompt))
    if not reply:
        reply = "Noted. Shall I regenerate the itinerary with this change applied?"

    _save_history(data, "user", message)
    _save_history(data, "assistant", reply)
    data["stage"]  = STAGE_MODIFY
    session.data   = data
    session.step   = STAGE_MODIFY
    _save_session(session)
    return _make(reply, ["Re-generate Itinerary", "More Changes", "Talk to Expert"])


def _regenerate_and_ask(session) -> dict:
    data = session.data
    try:
        result    = generate_itinerary(data)
        itinerary = result["itinerary"]
    except Exception:
        itinerary = _fallback_itinerary(data)

    _persist_itinerary(session, itinerary)
    data["_itinerary_sent"]        = True
    data["_last_itinerary"]        = itinerary
    data["_pending_modifications"] = []
    data["stage"]                  = STAGE_TICKET_CHECK
    session.data                   = data
    session.step                   = STAGE_TICKET_CHECK
    _save_session(session)
    return {
        "message": "Here is your updated itinerary.\n\n" + itinerary +
                   "\n\nHave you already booked your travel tickets (flight/train)?",
        "options": ["Yes, Tickets Are Booked", "No, Not Yet"],
        "social_card": SOCIAL_CARD,
    }


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


def _save_package_selection(session, travel_request, pkg: dict,
                            packages_shown: list, itinerary: str = "") -> object:
    try:
        from .models import PackageSelection
        idx = packages_shown.index(pkg) + 1 if pkg in packages_shown else 0
        return PackageSelection.objects.create(
            session=session,
            travel_request=travel_request,
            package_index=idx,
            package_title=pkg.get("title", ""),
            route=pkg.get("route", []),
            highlights=pkg.get("highlights", []),
            generated_itinerary=itinerary,
            raw_packages_shown=packages_shown,
        )
    except Exception as e:
        logger.error(f"[PackageSelection] Create error: {e}")
        return None


def _save_custom_itinerary(session, travel_request, flow_id: str, days: int,
                           day_data: list, itinerary: str, raw_payload: dict) -> object:
    try:
        from .models import CustomItinerary
        flow_choice_map = {
            FLOW_DAYWISE_3: "FLOW_DAYWISE_3",
            FLOW_DAYWISE_4: "FLOW_DAYWISE_4",
            FLOW_DAYWISE_5: "FLOW_DAYWISE_5",
            FLOW_DAYWISE_6: "FLOW_DAYWISE_6",
        }
        return CustomItinerary.objects.create(
            session=session,
            travel_request=travel_request,
            flow_id=flow_choice_map.get(flow_id, "FLOW_DAYWISE_3"),
            days=days,
            day_data=day_data,
            generated_itinerary=itinerary,
            raw_payload=raw_payload,
        )
    except Exception as e:
        logger.error(f"[CustomItinerary] Create error: {e}")
        return None


def _save_group_tour_lead(session, travel_request, destination: str,
                          departure_date: str, itinerary: str) -> object:
    try:
        from .models import GroupTourLead
        d = session.data
        return GroupTourLead.objects.create(
            session=session,
            travel_request=travel_request,
            destination=destination,
            departure_date=departure_date,
            adults=d.get("adults", 2),
            children_count=d.get("children_count", 0),
            children_ages=d.get("children_ages", []),
            itinerary_sent=itinerary,
            handed_off=True,
        )
    except Exception as e:
        logger.error(f"[GroupTourLead] Create error: {e}")
        return None


def _get_active_travel_request(session):
    try:
        from .models import TravelRequest
        return TravelRequest.objects.filter(session=session, is_active=True).first()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# DFA STAGE HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

def _handle_destination_collection(session, message: str) -> dict:
    """
    Validate and confirm the user's destination, then:
      1. Send the basic travel details flow.
      2. Mark the lead FOLLOW UP immediately.
    """
    data     = session.data
    raw_dest = message.strip()

    if len(raw_dest) < 3 or _is_hard_block(raw_dest):
        return _make(
            "Please tell me which destination in India you would like to travel to.",
            FEATURED_DESTINATIONS,
        )

    corrected = autocorrect_destination(raw_dest)

    if not is_valid_indian_destination(corrected):
        return _make(
            f'"{raw_dest}" does not appear to be a valid Indian destination. '
            f"Please enter a city, state, or tourist place in India.",
            FEATURED_DESTINATIONS,
        )

    if _is_international(raw_dest):
        return _make(
            f"{COMPANY_SHORT} specialises in domestic India travel only. "
            f"Please choose an Indian destination.",
            FEATURED_DESTINATIONS,
        )

    data["destination"]           = corrected
    data["confirmed_destination"] = corrected
    data["stage"]                 = STAGE_FLOW_SENT
    data["_flow_sent"]            = True
    session.data = data
    session.step = STAGE_FLOW_SENT
    _save_session(session)

    try:
        mark_lead_follow_up(session)
    except Exception as e:
        logger.error(f"[FOLLOW UP LABEL] Failed to label session {session.id}: {e}")

    logger.info(f"[DESTINATION] Confirmed: {corrected}, stage → STAGE_FLOW_SENT")
    return _make(
        f"Destination confirmed: {corrected}.\n\nPlease fill in your trip details below.",
        [],
        flow_payload=build_basic_travel_flow(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# FLOW SUBMISSION HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

def handle_flow_basic_travel_submission(session, payload: dict,
                                        raw_payload: dict = None) -> dict:
    """
    Mark the lead HOT immediately upon basic form submission, BEFORE routing
    to any downstream stage.
    """
    data           = session.data
    current_stage  = data.get("stage", STAGE_IDLE)
    parsed         = parse_basic_travel_flow(payload)
    days           = parsed.get("days")
    adults         = parsed["adults"]
    children_count = parsed["children_count"]
    children_ages  = parsed["children_ages"]
    special_notes  = parsed["special_notes"]
    days_raw       = parsed["days_raw"]
    name           = parsed.get("name", "")
    destination    = data.get("confirmed_destination") or data.get("destination", "")

    data.update({
        "days":           days,
        "adults":         adults,
        "children_count": children_count,
        "children_ages":  children_ages,
        "special_notes":  special_notes,
        "_name":          name,
    })
    session.data = data

    try:
        mark_lead_hot(session)
        session.refresh_from_db()
    except Exception as e:
        logger.error(f"[BASIC FORM HOT] mark_lead_hot failed: {e}")

    tr = _create_travel_request(
        session,
        {**parsed, "destination": destination, "days_raw": days_raw},
        raw_payload or payload,
    )

    # A. Days > 6 or "other"
    if days is None or days > 6:
        next_stage = STAGE_LEAD_HANDOFF
        _log_flow_dispatch(FLOW_BASIC_TRAVEL, parsed, data, current_stage, next_stage)
        if tr:
            try:
                tr.status    = "handoff"
                tr.routed_to = "STAGE_LEAD_HANDOFF"
                tr.save()
            except Exception:
                pass
        data["stage"] = next_stage
        session.data  = data
        session.step  = next_stage
        _save_session(session)
        return handle_lead_handoff(session)

    # B. Group Tour destinations
    if _is_group_tour_destination(destination):
        next_stage = STAGE_GROUP_TOUR_CHOICE
        _log_flow_dispatch(FLOW_BASIC_TRAVEL, parsed, data, current_stage, next_stage)
        if tr:
            try:
                tr.status    = "group"
                tr.routed_to = "STAGE_GROUP_TOUR_CHOICE"
                tr.save()
            except Exception:
                pass
        data["stage"] = next_stage
        session.data  = data
        session.step  = next_stage
        _save_session(session)
        return _make(
            f"For {destination}, we offer Group Tour (fixed departure, joining basis) "
            f"and Individual Tour (private vehicle, flexible dates). Which do you prefer?",
            ["Group Tour", "Individual Tour"],
        )

    # C. Destination in config
    if _is_in_config(destination):
        next_stage = STAGE_PACKAGE
        _log_flow_dispatch(FLOW_BASIC_TRAVEL, parsed, data, current_stage, next_stage)
        if tr:
            try:
                tr.status    = "packaged"
                tr.routed_to = "STAGE_PACKAGE"
                tr.save()
            except Exception:
                pass
        data["stage"] = next_stage
        session.data  = data
        session.step  = next_stage
        _save_session(session)
        result = _present_packages_from_config(destination, days, data)
        data["_trip_packages"] = result.get("packages", [])
        session.data = data
        _save_session(session)
        return _make(result["message"], result["options"])

    # D. Destination not in config → day-wise flow
    next_stage = STAGE_CUSTOM_FLOW_SENT
    _log_flow_dispatch(FLOW_BASIC_TRAVEL, parsed, data, current_stage, next_stage)
    if tr:
        try:
            tr.status    = "custom"
            tr.routed_to = f"STAGE_CUSTOM_FLOW_SENT_{days}"
            tr.save()
        except Exception:
            pass
    return _send_daywise_flow(session, days)


def handle_flow_group_date_submission(session, payload: dict,
                                      raw_payload: dict = None) -> dict:
    data          = session.data
    current_stage = data.get("stage", STAGE_IDLE)

    selected_date = parse_group_date_flow(payload)

    _log_flow_dispatch(FLOW_GROUP_DATE, payload, data, current_stage, STAGE_ITINERARY_REVIEW)
    logger.info(f"[GROUP DATE FLOW] Raw payload: {payload}, parsed date: {selected_date}")

    if not selected_date:
        logger.warning("[GROUP DATE FLOW] Could not parse date from payload — re-sending calendar")
        min_date = _min_group_tour_date_str()
        return _make(
            "We could not read your date selection. Please choose a departure date.",
            [],
            flow_payload=build_group_tour_date_picker(min_date),
        )

    parsed_dt = None
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y"):
        try:
            parsed_dt = datetime.strptime(selected_date, fmt)
            break
        except ValueError:
            continue

    if parsed_dt and parsed_dt < _min_group_tour_date():
        min_date = _min_group_tour_date_str()
        logger.warning(f"[GROUP DATE FLOW] Date {selected_date} too soon, min is {min_date}")
        return _make(
            f"The selected date is too soon. Group tours require a minimum of 21 days notice. "
            f"Please select a date from {min_date} or later.",
            [],
            flow_payload=build_group_tour_date_picker(min_date),
        )

    destination = data.get("confirmed_destination", "")
    data["departure_date"] = selected_date
    session.data = data

    itinerary = _get_group_tour_itinerary(destination, selected_date)

    _persist_itinerary(session, itinerary)
    data["_itinerary_sent"] = True
    data["_last_itinerary"] = itinerary
    data["stage"]           = STAGE_ITINERARY_REVIEW
    session.data            = data
    session.step            = STAGE_ITINERARY_REVIEW
    _save_session(session)

    tr = _get_active_travel_request(session)
    _save_group_tour_lead(session, tr, destination, selected_date, itinerary)

    logger.info(f"[GROUP DATE FLOW] Departure {selected_date} saved, stage → STAGE_ITINERARY_REVIEW")

    return {
        "message": (f"Group Tour Itinerary for departure on {selected_date}:\n\n" + itinerary),
        "options": ["Pay and Book", "Talk to Expert", "Modify"],
        "social_card": SOCIAL_CARD,
    }


def handle_flow_daywise_submission(session, payload: dict, flow_id: str,
                                   raw_payload: dict = None) -> dict:
    data          = session.data
    current_stage = data.get("stage", STAGE_IDLE)
    days          = FLOW_ID_TO_DAYS.get(flow_id) or int(data.get("days", 3))

    day_data = parse_daywise_flow(payload, days)

    _log_flow_dispatch(flow_id, payload, data, current_stage, STAGE_ITINERARY_REVIEW)
    logger.info(f"[DAYWISE FLOW] flow_id={flow_id}, days={days}, day_data={day_data}")

    if payload.get("special_notes"):
        data["special_notes"] = payload["special_notes"].strip()

    itinerary = generate_itinerary_from_daywise(data, day_data)
    _persist_itinerary(session, itinerary)
    data["_itinerary_sent"] = True
    data["_last_itinerary"] = itinerary
    data["stage"]           = STAGE_ITINERARY_REVIEW
    session.data            = data
    session.step            = STAGE_ITINERARY_REVIEW
    _save_session(session)

    tr = _get_active_travel_request(session)
    _save_custom_itinerary(session, tr, flow_id, days, day_data, itinerary,
                           raw_payload or payload)

    if data.get("_best_seller_key"):
        logger.info("[DAYWISE FROM BEST SELLER] Handing off to sales agent post-modification")
        try:
            mark_lead_hot(session)
        except Exception:
            pass
        return handle_lead_handoff(session)

    logger.info(f"[DAYWISE FLOW] Itinerary generated, stage → STAGE_ITINERARY_REVIEW")

    return {
        "message": "Here is your custom itinerary.\n\n" + itinerary,
        "options": ["Modify", "Talk to Expert"],
        "social_card": SOCIAL_CARD,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CENTRAL FLOW SUBMISSION DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

def handle_flow_submission(session, interactive: dict) -> dict:
    """
    Central dispatcher for all WhatsApp Flow nfm_reply submissions.
    """
    data          = session.data
    current_stage = data.get("stage", STAGE_IDLE)

    logger.info(f"[FLOW SUBMISSION] Incoming nfm_reply. Stage={_stage_name(current_stage)}")

    parsed_payload = extract_flow_response_json(interactive)

    if parsed_payload is None:
        logger.error(
            f"[FLOW SUBMISSION] response_json missing/invalid at stage={_stage_name(current_stage)}")
        msg = "We could not read your form submission. Please try again."

        if current_stage in (STAGE_FLOW_SENT, STAGE_BEST_SELLER_SENT):
            return _make(msg, [], flow_payload=build_basic_travel_flow())
        if current_stage == STAGE_GROUP_TOUR_DATE:
            return _make(msg, [], flow_payload=build_group_tour_date_picker(_min_group_tour_date_str()))
        if current_stage == STAGE_CUSTOM_FLOW_SENT:
            days = data.get("days")
            if days and int(days) in DAYWISE_FLOW_MAP:
                fp = build_daywise_flow(int(days))
                return _make(msg, [], flow_payload=fp) if fp else _make(msg, [])
        return _make(msg, [])

    flow_id = identify_flow_from_response(parsed_payload, data)

    if flow_id:
        _save_flow_message_to_crm(session, parsed_payload, flow_id)

    logger.info(f"[FLOW SUBMISSION] Identified flow: {FLOW_NAMES.get(flow_id, flow_id)}, "
                f"stage={_stage_name(current_stage)}")

    if flow_id == FLOW_BASIC_TRAVEL:
        return handle_flow_basic_travel_submission(session, parsed_payload, interactive)

    if flow_id == FLOW_GROUP_DATE:
        return handle_flow_group_date_submission(session, parsed_payload, interactive)

    if flow_id in DAYWISE_FLOW_MAP.values():
        return handle_flow_daywise_submission(session, parsed_payload, flow_id, interactive)

    logger.warning(f"[FLOW SUBMISSION] flow_id not matched in primary dispatch. "
                   f"Attempting key-based fallback. Keys: {list(parsed_payload.keys())}")

    if "name" in parsed_payload or "trip_days" in parsed_payload:
        logger.info("[FLOW SUBMISSION] Fallback → FLOW_BASIC_TRAVEL (key 'name'/'trip_days')")
        _save_flow_message_to_crm(session, parsed_payload, FLOW_BASIC_TRAVEL)
        return handle_flow_basic_travel_submission(session, parsed_payload, interactive)

    if "departure_option" in parsed_payload or "custom_date" in parsed_payload:
        logger.info("[FLOW SUBMISSION] Fallback → FLOW_GROUP_DATE")
        _save_flow_message_to_crm(session, parsed_payload, FLOW_GROUP_DATE)
        return handle_flow_group_date_submission(session, parsed_payload, interactive)

    day_keys = [k for k in parsed_payload if re.match(r"^day\d+_activity$", k)]
    if day_keys:
        inferred_days    = max(int(re.search(r"day(\d+)_activity", k).group(1)) for k in day_keys)
        inferred_flow_id = DAYWISE_FLOW_MAP.get(inferred_days)
        if inferred_flow_id:
            logger.info(f"[FLOW SUBMISSION] Fallback → FLOW_DAYWISE_{inferred_days} (key inference)")
            _save_flow_message_to_crm(session, parsed_payload, inferred_flow_id)
            return handle_flow_daywise_submission(session, parsed_payload, inferred_flow_id, interactive)

    if current_stage in (STAGE_FLOW_SENT, STAGE_BEST_SELLER_SENT):
        logger.warning("[FLOW SUBMISSION] Stage-based last resort → FLOW_BASIC_TRAVEL")
        _save_flow_message_to_crm(session, parsed_payload, FLOW_BASIC_TRAVEL)
        return handle_flow_basic_travel_submission(session, parsed_payload, interactive)

    if current_stage == STAGE_GROUP_TOUR_DATE:
        logger.warning("[FLOW SUBMISSION] Stage-based last resort → FLOW_GROUP_DATE")
        _save_flow_message_to_crm(session, parsed_payload, FLOW_GROUP_DATE)
        return handle_flow_group_date_submission(session, parsed_payload, interactive)

    if current_stage == STAGE_CUSTOM_FLOW_SENT:
        days = data.get("days")
        if days and int(days) in DAYWISE_FLOW_MAP:
            fid = DAYWISE_FLOW_MAP[int(days)]
            logger.warning(f"[FLOW SUBMISSION] Stage-based last resort → DAYWISE days={days}")
            _save_flow_message_to_crm(session, parsed_payload, fid)
            return handle_flow_daywise_submission(session, parsed_payload, fid, interactive)

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
# REMAINING DFA STAGE HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

def _send_daywise_flow(session, days: int) -> dict:
    data = session.data
    if days not in DAYWISE_FLOW_MAP:
        return handle_lead_handoff(session)

    data["stage"]             = STAGE_CUSTOM_FLOW_SENT
    data["_custom_flow_sent"] = True
    session.data              = data
    session.step              = STAGE_CUSTOM_FLOW_SENT
    _save_session(session)

    flow_payload = build_daywise_flow(days)
    destination  = data.get("confirmed_destination", "your destination")
    logger.info(f"[DAYWISE FLOW SENT] dest={destination}, days={days}")
    return _make(
        f"No predefined packages available for {destination}. "
        f"Build your custom {days}-day itinerary using the form below.",
        [],
        flow_payload=flow_payload,
    )


def _handle_stage_group_tour_choice(session, message: str) -> dict:
    data  = session.data
    msg_l = _norm(message)

    is_group      = any(t in msg_l for t in ["group", "group tour"])
    is_individual = any(t in msg_l for t in ["individual", "single", "private"])

    if is_group:
        data["tour_type"] = "group"
        data["stage"]     = STAGE_GROUP_TOUR_DATE
        session.data      = data
        session.step      = STAGE_GROUP_TOUR_DATE
        _save_session(session)
        min_date = _min_group_tour_date_str()
        logger.info(f"[GROUP TOUR CHOICE] Group selected, stage → STAGE_GROUP_TOUR_DATE")
        return _make(
            f"Please select your preferred group departure date. "
            f"Dates are available from {min_date} onwards (minimum 21 days from today).",
            [],
            flow_payload=build_group_tour_date_picker(min_date),
        )

    if is_individual:
        data["tour_type"] = "individual"
        destination       = data.get("confirmed_destination", "")
        days              = int(data.get("days", 4))
        logger.info(f"[GROUP TOUR CHOICE] Individual selected for {destination}")
        if _is_in_config(destination):
            data["stage"] = STAGE_PACKAGE
            session.data  = data
            session.step  = STAGE_PACKAGE
            _save_session(session)
            result = _present_packages_from_config(destination, days, data)
            data["_trip_packages"] = result.get("packages", [])
            session.data = data
            _save_session(session)
            return _make(result["message"], result["options"])
        return _send_daywise_flow(session, days)

    return _make(
        "Please choose Group Tour (fixed departure, joining basis) "
        "or Individual Tour (private vehicle, flexible dates).",
        ["Group Tour", "Individual Tour"],
    )


def _handle_stage_group_tour_date_text(session, message: str) -> dict:
    data          = session.data
    date_patterns = [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*\d{0,4})",
    ]
    selected_date = None
    for pattern in date_patterns:
        match = re.search(pattern, message.lower())
        if match:
            selected_date = _normalise_date_string(match.group(1))
            break

    if not selected_date and re.search(r'\d', message):
        selected_date = message.strip()

    if not selected_date:
        min_date = _min_group_tour_date_str()
        return _make(
            "Please select your departure date using the calendar.",
            [],
            flow_payload=build_group_tour_date_picker(min_date),
        )

    parsed_dt = None
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y"):
        try:
            parsed_dt = datetime.strptime(selected_date, fmt)
            break
        except ValueError:
            continue

    if parsed_dt and parsed_dt < _min_group_tour_date():
        min_date = _min_group_tour_date_str()
        return _make(
            f"The selected date is too soon. Group tours require a minimum of 21 days notice. "
            f"Please select a date from {min_date} or later.",
            [],
            flow_payload=build_group_tour_date_picker(min_date),
        )

    destination            = data.get("confirmed_destination", "")
    data["departure_date"] = selected_date
    session.data           = data

    itinerary = _get_group_tour_itinerary(destination, selected_date)

    _persist_itinerary(session, itinerary)
    data["_itinerary_sent"] = True
    data["_last_itinerary"] = itinerary
    data["stage"]           = STAGE_ITINERARY_REVIEW
    session.data            = data
    session.step            = STAGE_ITINERARY_REVIEW
    _save_session(session)

    tr = _get_active_travel_request(session)
    _save_group_tour_lead(session, tr, destination, selected_date, itinerary)

    return {
        "message": (f"Group Tour Itinerary for departure on {selected_date}:\n\n" + itinerary),
        "options": ["Pay and Book", "Talk to Expert", "Modify"],
        "social_card": SOCIAL_CARD,
    }


def _handle_stage_package(session, message: str) -> dict:
    data        = session.data
    packages    = data.get("_trip_packages", [])
    destination = data.get("confirmed_destination", "")
    days        = int(data.get("days", 4))
    msg_l       = _norm(message)

    if not packages:
        result = _present_packages_from_config(destination, days, data)
        data["_trip_packages"] = result.get("packages", [])
        session.data = data
        _save_session(session)
        return _make(result["message"], result["options"])

    if "create custom" in msg_l or "custom package" in msg_l:
        return _send_daywise_flow(session, days)

    selected_pkg = _resolve_package_from_config(message, packages)
    if not selected_pkg:
        result = _present_packages_from_config(destination, days, data)
        return _make(
            "Please select a package by number (e.g. Package 1).\n\n" + result["message"],
            result["options"],
        )

    data["selected_package"] = selected_pkg
    data["selected_places"]  = selected_pkg.get("route", selected_pkg.get("highlights", []))

    try:
        result    = generate_itinerary(data)
        itinerary = result["itinerary"]
    except Exception:
        itinerary = _fallback_itinerary(data)

    _persist_itinerary(session, itinerary)
    data["_itinerary_sent"] = True
    data["_last_itinerary"] = itinerary
    data["stage"]           = STAGE_ITINERARY_REVIEW
    session.data            = data
    session.step            = STAGE_ITINERARY_REVIEW
    _save_session(session)

    tr = _get_active_travel_request(session)
    _save_package_selection(session, tr, selected_pkg, packages, itinerary)

    return {
        "message": f"You selected: {selected_pkg['title']}\n\nHere is your itinerary:\n\n" + itinerary,
        "options": ["Talk to Expert", "Modify"],
        "social_card": SOCIAL_CARD,
    }


def _handle_stage_itinerary_review(session, message: str) -> dict:
    data = session.data
    if _is_approval(message):
        data["stage"] = STAGE_TICKET_CHECK
        session.data  = data
        session.step  = STAGE_TICKET_CHECK
        _save_session(session)
        return _make(
            "Have you already booked your travel tickets (flight/train)?",
            ["Yes, Tickets Are Booked", "No, Not Yet"],
        )
    if _norm(message) in {"modify", "change", "edit"}:
        data["stage"] = STAGE_MODIFY
        session.data  = data
        session.step  = STAGE_MODIFY
        _save_session(session)
        return handle_modify_menu(session)
    return handle_free_modify(session, message)


def _handle_stage_ticket_check(session, message: str) -> dict:
    data  = session.data
    msg_l = _norm(message)

    yes_triggers = ["yes", "booked", "already booked", "done", "confirmed",
                    "yes tickets are booked", "tickets are booked"]
    no_triggers  = ["no", "not yet", "haven't", "will book later", "no not yet"]

    if any(t in msg_l for t in yes_triggers):
        return handle_lead_handoff(session)

    if any(t in msg_l for t in no_triggers):
        data["stage"] = STAGE_POST_ITINERARY
        session.data  = data
        session.step  = STAGE_POST_ITINERARY
        _save_session(session)
        return _make(
            "Our travel expert can assist with complete booking including tickets.",
            ["Talk to Expert", "Modify"],
        )

    return _make(
        "Have you already booked your travel tickets (flight/train)?",
        ["Yes, Tickets Are Booked", "No, Not Yet"],
    )


def _handle_stage_post_itinerary(session, message: str) -> dict:
    data  = session.data
    msg_l = _norm(message)

    if any(t in msg_l for t in ["talk to expert", "expert", "connect", "call", "book", "agent"]):
        return handle_lead_handoff(session)

    if any(t in msg_l for t in ["modify", "change", "edit", "update"]):
        data["stage"] = STAGE_MODIFY
        session.data  = data
        session.step  = STAGE_MODIFY
        _save_session(session)
        return handle_modify_menu(session)

    return _make("What would you like to do next?", ["Talk to Expert", "Modify"])


def _handle_stage_chat(session, message: str) -> dict:
    data = session.data
    msg  = _norm(message)

    if data.get("_expert_contacted"):
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
            return _make("Where would you like to travel next?", FEATURED_DESTINATIONS)

    modify_triggers = ["customize", "change hotel", "modify", "add sightseeing", "update"]
    if any(t in msg for t in modify_triggers):
        data["stage"] = STAGE_MODIFY
        session.data  = data
        session.step  = STAGE_MODIFY
        session.save()
        return handle_modify_menu(session)

    _save_history(data, "user", message)
    reply = chat_response(message, data)
    _save_history(data, "assistant", reply)
    data["_chat_turn"] = data.get("_chat_turn", 0) + 1
    session.data       = data
    session.save()

    options = (["Pay and Book", "Modify", "Talk to Expert", "Plan New Trip"]
               if data.get("_itinerary_sent") else
               ["Plan New Trip", "Talk to Expert"])
    return {"message": reply, "options": options}


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

    prompt = (f"You are a travel consultant at {COMPANY_SHORT} ({COMPANY_NAME}).\n"
              f"RULES: Plain text only. No asterisks. No markdown. No emojis. Professional English only.\n"
              f"Do NOT start with 'Great!', 'Sure!', or 'Of course!' Be direct and concise.\n"
              f"IMPORTANT: If the user asks about meal price, food cost, or lunch/dinner cost, "
              f"always reply: Meals are not included in the package. Approximately Rs. 300 or more "
              f"per meal per person at local restaurants near sightseeing areas.\n"
              f"IMPORTANT: NEVER mention or invent any specific hotel brand name.\n"
              f"COMPANY INFO: Office: {COMPANY_ADDRESS}\n"
              f"TRIP CONTEXT: {trip_context}\n"
              f"{faq_block}"
              f"RECENT CONVERSATION:\n{history}\n"
              f'USER MESSAGE: "{user_message}"\n'
              f"Answer in 2-4 lines. Ask at most one follow-up question.")

    reply = _deepseek(prompt)
    return (_strip_markdown(reply) if reply else
            "Please provide more details so I can assist you accurately.")


# ─────────────────────────────────────────────────────────────────────────────
# FOLLOW-UP ENGINE
# ─────────────────────────────────────────────────────────────────────────────

FOLLOWUP_MESSAGES = {
    1: ("Just checking in — have you had a chance to review the travel plan? "
        "Happy to make any adjustments."),
    2: ("Would you like to adjust the package or explore other options? "
        "We can also check pricing for your specific travel dates."),
    3: ("If the package is over budget, we may be able to arrange a discount. "
        "Would you like us to check?"),
    4: ("Our travel team can work out the best possible price for you. "
        "Would you like to connect with an expert?"),
}

FOLLOWUP_INTERVALS_MINUTES = {1: 5, 2: 10, 3: 20, 4: 30}

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
    Marks lead FOLLOW UP and hands off to agent.
    """
    try:
        mark_lead_follow_up(session)
    except Exception:
        pass
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

def generate_response(message: str, session) -> dict:
    """
    Central message handler for all incoming WhatsApp messages.
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

    if _is_hard_block(message):
        reply = "We can only assist with travel planning and trip-related queries."
        _save_bot_reply_to_crm(session, reply)
        return _make(reply)

    if _is_international(message):
        reply = (f"{COMPANY_SHORT} specialises in domestic India travel only. "
                 f"Which Indian destination would you like to explore?")
        _save_bot_reply_to_crm(session, reply)
        return _make(reply, FEATURED_DESTINATIONS)

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
        return _make(reply, ["Plan My Trip"] if not data.get("_itinerary_sent")
                     else ["Modify", "Talk to Expert"])

    if intent == INTENT_GREETING:
        new_data                 = _blank_session()
        new_data["welcome_sent"] = True
        new_data["stage"]        = STAGE_DESTINATION
        session.step             = STAGE_DESTINATION
        session.data             = new_data
        session.save()
        reply = f"Welcome to {COMPANY_SHORT}. Which destination in India would you like to travel to?"
        _save_bot_reply_to_crm(session, reply)
        return _make(reply, FEATURED_DESTINATIONS)

    if intent == INTENT_NEW_ENQUIRY:
        new_data                 = _blank_session()
        new_data["welcome_sent"] = True
        new_data["_history"]     = data.get("_history", [])
        new_data["stage"]        = STAGE_DESTINATION
        session.step             = STAGE_DESTINATION
        session.data             = new_data
        session.save()
        reply = "Which destination in India would you like to plan a trip to?"
        _save_bot_reply_to_crm(session, reply)
        return _make(reply, FEATURED_DESTINATIONS)

    if intent == INTENT_EXPERT:
        if current_stage == STAGE_BEST_SELLER_SENT:
            try:
                mark_lead_hot(session)
            except Exception:
                pass
        response = handle_lead_handoff(session)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    if intent == INTENT_DISCOUNT and data.get("confirmed_destination"):
        result = _handle_discount_request(message, data)
        session.data = data
        _save_session(session)
        _save_bot_reply_to_crm(session, result.get("message", ""))
        return result

    if not data.get("welcome_sent"):
        data["welcome_sent"] = True
        data["stage"]        = STAGE_DESTINATION
        session.data         = data
        session.step         = STAGE_DESTINATION
        _save_session(session)
        reply = f"Welcome to {COMPANY_SHORT}. Which destination in India would you like to travel to?"
        _save_bot_reply_to_crm(session, reply)
        return _make(reply, FEATURED_DESTINATIONS)

    # INTELLIGENT DESTINATION DETECTION
    _dest_detection_stages = {
        STAGE_IDLE, STAGE_DESTINATION, STAGE_CHAT,
        STAGE_POST_ITINERARY, STAGE_BEST_SELLER_SENT,
    }
    if (current_stage in _dest_detection_stages
            and not data.get("confirmed_destination")
            and intent not in (INTENT_EXPERT, INTENT_GREETING, INTENT_NEW_ENQUIRY,
                               INTENT_COMPANY, INTENT_MEAL_PRICE, INTENT_DISCOUNT)):
        detected = detect_destination_in_message(message)
        if detected:
            bs_key = _get_best_seller_key(detected)
            if bs_key and not data.get("_best_seller_key"):
                logger.info(f"[DEST DETECT] Found '{detected}' → best seller key '{bs_key}'")
                response = _send_best_seller_package(session, bs_key)
                _save_bot_reply_to_crm(session, response.get("message", ""))
                return response

    # STAGE: BEST_SELLER_SENT
    if current_stage == STAGE_BEST_SELLER_SENT:
        response = _handle_stage_best_seller_sent(session, message, intent)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    # STAGE: DESTINATION
    if current_stage == STAGE_DESTINATION:
        response = _handle_destination_collection(session, message)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    # STAGE: IDLE
    if current_stage == STAGE_IDLE:
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
        return _make(reply, FEATURED_DESTINATIONS)

    # MODIFY intent
    if intent == INTENT_MODIFY:
        data["stage"] = STAGE_MODIFY
        session.data  = data
        session.step  = STAGE_MODIFY
        session.save()
        if _norm(message) in {"modify", "change", "edit", "update"}:
            response = handle_modify_menu(session)
        else:
            response = handle_free_modify(session, message)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    # Legacy stage mapping
    if current_stage in (STEP_MODIFY_CHOICE, STEP_MODIFY_DAYS,
                         STEP_MODIFY_DESTINATION, STEP_MODIFY_DAY_WISE,
                         STEP_MODIFY_FREE):
        data["stage"] = STAGE_MODIFY
        session.data  = data
        session.step  = STAGE_MODIFY
        _save_session(session)
        response = handle_free_modify(session, message)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    _save_history(data, "user", message)
    session.data = data

    if _norm(message) in {"pay and book", "pay & book"}:
        response = handle_pay_and_book(session)
        _save_bot_reply_to_crm(session, response.get("message", ""))
        return response

    # DFA Stage routing
    if current_stage == STAGE_FLOW_SENT:
        reply = "Please fill the travel details form to continue."
        _save_bot_reply_to_crm(session, reply)
        return _make(reply, [], flow_payload=build_basic_travel_flow())

    elif current_stage == STAGE_GROUP_TOUR_CHOICE:
        response = _handle_stage_group_tour_choice(session, message)

    elif current_stage == STAGE_GROUP_TOUR_DATE:
        response = _handle_stage_group_tour_date_text(session, message)

    elif current_stage == STAGE_PACKAGE:
        response = _handle_stage_package(session, message)

    elif current_stage == STAGE_CUSTOM_FLOW_SENT:
        days         = int(data.get("days", 3))
        flow_payload = build_daywise_flow(days)
        response     = _make(
            f"Please fill the {days}-day itinerary form to continue.",
            [],
            flow_payload=flow_payload,
        )

    elif current_stage == STAGE_ITINERARY_REVIEW:
        response = _handle_stage_itinerary_review(session, message)

    elif current_stage == STAGE_MODIFY:
        if _norm(message) in {"pay and book", "pay & book"}:
            response = handle_pay_and_book(session)
        else:
            response = handle_free_modify(session, message)

    elif current_stage == STAGE_TICKET_CHECK:
        response = _handle_stage_ticket_check(session, message)

    elif current_stage == STAGE_POST_ITINERARY:
        response = _handle_stage_post_itinerary(session, message)

    elif current_stage == STAGE_CHAT:
        if _norm(message) in {"pay and book", "pay & book"}:
            response = handle_pay_and_book(session)
        else:
            response = _handle_stage_chat(session, message)

    elif current_stage in (STEP_CUSTOMIZE, STEP_CONFIRM):
        data["stage"] = STAGE_MODIFY
        session.data  = data
        session.step  = STAGE_MODIFY
        _save_session(session)
        response = handle_free_modify(session, message)

    else:
        reply = chat_response(message, data)
        _save_history(data, "assistant", reply)
        session.data = data
        session.save()
        _save_bot_reply_to_crm(session, reply)
        return _make(reply, ["Plan My Trip"])

    if isinstance(response, dict) and response.get("message"):
        _save_history(data, "assistant", response["message"][:300])
        session.data = data
        session.save()
        _save_bot_reply_to_crm(session, response.get("message", ""))

    return response


# ─────────────────────────────────────────────────────────────────────────────
# STATIC DATA
# ─────────────────────────────────────────────────────────────────────────────

FEATURED_DESTINATIONS = [
    "Rameshwaram", "Varanasi", "Ayodhya", "Nashik", "Puri",
    "Ujjain", "Coorg", "Dwarka", "Gokarna", "Other (Please Specify)",
]

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
    "Palitana", "Lothal", "Daman", "Statue Of Unity",
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
    "Sanchi", "Mandu", "Amarkantak",
    "Maharashtra", "Mumbai", "Pune", "Nashik", "Aurangabad", "Nagpur",
    "Mahabaleshwar", "Lonavala", "Alibaug", "Shirdi", "Ajanta Ellora",
    "Kolhapur", "Ratnagiri", "Matheran", "Tadoba", "Igatpuri",
    "Lavasa", "Murud", "Shrivardhan",
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
    "Dudhwa", "Chitrakoot",
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

DESTINATION_TO_HOTEL_CITY = {
    "kerala": ["Kochi", "Alleppey", "Munnar", "Thekkady", "Thiruvananthapuram", "Wayanad"],
    "munnar": ["Munnar", "Kochi"], "alleppey": ["Alleppey", "Kochi", "Thekkady"],
    "wayanad": ["Wayanad"], "thekkady": ["Thekkady"],
    "kovalam": ["Thiruvananthapuram"], "varkala": ["Varkala"],
    "kumarakom": ["Alleppey"],
    "ooty": ["Ooty"], "kodaikanal": ["Kodaikanal"],
    "pondicherry": ["Pondicherry"], "puducherry": ["Pondicherry"],
    "rameswaram": ["Madurai"], "rameshwaram": ["Madurai"],
    "kanyakumari": ["Tirunelveli"],
    "mahabalipuram": ["Chennai"], "madurai": ["Madurai"],
    "gokarna": ["Gokarna"], "coorg": ["Coorg"], "kodagu": ["Coorg"],
    "chikmagalur": ["Chikmagalur"], "hampi": ["Hospet"], "mysore": ["Mysore"],
    "mangalore": ["Mangalore"], "udupi": ["Mangalore"], "bangalore": ["Bangalore"],
    "goa": ["Goa"], "north goa": ["Goa"], "south goa": ["Goa"],
    "mumbai": ["Mumbai"], "pune": ["Pune"],
    "mahabaleshwar": ["Mahabaleshwar"], "shirdi": ["Nashik"], "nashik": ["Nashik"],
    "nagpur": ["Nagpur"], "aurangabad": ["Aurangabad"],
    "manali": ["Manali"], "shimla": ["Shimla"],
    "dharamshala": ["Dharamshala", "Mcleodganj"], "mcleodganj": ["Mcleodganj"],
    "kashmir": ["Srinagar"], "srinagar": ["Srinagar"],
    "leh ladakh": ["Leh"], "leh": ["Leh"],
    "haridwar": ["Haridwar", "Rishikesh"], "rishikesh": ["Rishikesh", "Haridwar"],
    "nainital": ["Nainital"], "mussoorie": ["Dehradun"], "dehradun": ["Dehradun"],
    "varanasi": ["Varanasi"], "ayodhya": ["Varanasi", "Ayodhya"],
    "agra": ["Agra"], "mathura": ["Mathura"], "vrindavan": ["Mathura"],
    "prayagraj": ["Prayagraj"], "allahabad": ["Prayagraj"], "lucknow": ["Lucknow"],
    "jaipur": ["Jaipur"], "jaisalmer": ["Jaisalmer", "Jodhpur"], "udaipur": ["Udaipur"],
    "jodhpur": ["Jodhpur"], "pushkar": ["Pushkar", "Jaipur"],
    "gujarat": ["Ahmedabad"], "dwarka": ["Rajkot"], "somnath": ["Junagadh"],
    "gir": ["Junagadh"],
    "andaman": ["Chennai", "Kolkata"], "port blair": ["Port Blair"],
    "assam": ["Guwahati"], "kaziranga": ["Guwahati"],
    "meghalaya": ["Shillong"], "shillong": ["Shillong"],
    "sikkim": ["Siliguri", "Gangtok"], "gangtok": ["Gangtok", "Siliguri"],
    "darjeeling": ["Darjeeling", "Siliguri"],
    "puri": ["Puri"], "bhubaneswar": ["Bhubaneswar"],
    "konark": ["Bhubaneswar", "Puri"], "chilika lake": ["Bhubaneswar"],
    "bodh gaya": ["Gaya"], "nalanda": ["Patna"],
    "ujjain": ["Indore"],
    "delhi": ["New Delhi", "Noida", "Gurgaon"],
    "hyderabad": ["Hyderabad"], "chennai": ["Chennai"], "kolkata": ["Kolkata"],
    "tirupati": ["Tirupati"], "amritsar": ["Amritsar"],
}

# ─────────────────────────────────────────────────────────────────────────────
# LEGACY HOTEL BRAND DATA (kept for backward compatibility only — not used)
# ─────────────────────────────────────────────────────────────────────────────
HOTEL_DATA = {
    "Agra": ["Treebo The Empire Near Taj Mahal Agra", "Treebo The Royal Taj"],
    "Ahmedabad": ["Treebo Ambassador", "Treebo Prince Plaza"],
    "Alleppey": ["Treebo Premium Palmyra Milford", "Treebo Premium Vahada"],
    "Amritsar": ["Treebo Premium The Mustard Inn, Lawrence Road"],
    "Ayodhya": ["Treebo Ramayan Suites Ayodhya"],
    "Bangalore": ["Treebo Akshaya Lalbagh Inn", "Treebo Greenwood Premier Suites"],
    "Chandigarh": ["Treebo Jd Residency Mohali", "Treebo Premium Arista"],
    "Chennai": ["Treebo Elan", "Treebo Nestlay Casa"],
    "Chikmagalur": ["Treebo Orchid", "Treebo The Meridian"],
    "Coimbatore": ["Treebo Ess Grande", "Treebo Everest Residency Tidel Park"],
    "Coorg": ["Treebo Vrindavan, 3 Km From Madikeri Fort", "Treebo Green Land Kushalnagar"],
    "Dalhousie": ["Treebo Down Town, Dalhousie", "Treebo Anjukul"],
    "Darjeeling": ["Itsy Hotels Route 55"],
    "Dehradun": ["Treebo Blessing Bells", "Treebo Premium Pearl Avenue"],
    "Dharamshala": ["Treebo Ortus Residency"],
    "Goa": ["Treebo Lands End Beach Resort Morjim", "Treebo Aquamarine Arpora"],
    "Gokarna": ["Itsy Hotels Sands And Serenity"],
    "Gurgaon": ["Treebo Premium Eden Residency"],
    "Guwahati": ["Treebo Arna Residency", "Treebo Spring Brook"],
    "Haridwar": ["Treebo Tropical Roots, Bhupatwala Haridwar"],
    "Hyderabad": ["Treebo Fort Club", "Treebo Address Inn, Banjara Hills"],
    "Indore": ["Treebo Daksh Residency", "Treebo Grand Euro Pipliyahana Square"],
    "Jaipur": ["Treebo The Anchorage Malviya Nagar", "Treebo Bliss"],
    "Jaisalmer": ["Treebo Desert Harmony Camp"],
    "Jodhpur": ["Treebo Megh Niwas - Jodhpur"],
    "Kochi": ["Treebo The Qasr", "Treebo Time Square Marine Drive"],
    "Kodaikanal": ["Treebo Aall Season"],
    "Kolkata": ["Treebo Globe International", "Treebo Vedanta"],
    "Lucknow": ["Treebo Resto - Near Lucknow Railway Station", "Treebo Silver Grand"],
    "Mahabaleshwar": ["Treebo Hillway Inn Main Market"],
    "Madurai": ["Treebo Hotel (3 Star AC) Madurai"],
    "Manali": ["Treebo Premium Sattva With Mountain View"],
    "Mangalore": ["Treebo Pappilon Palace"],
    "Mcleodganj": ["Treebo Roshan House With Valley View"],
    "Mumbai": ["Treebo Olive Nest", "Treebo Blue Moon Powai"],
    "Munnar": ["Treebo Windsong Resort Munnar"],
    "Mysore": ["Treebo Premium Akshaya Mahal Inn"],
    "Nagpur": ["Treebo Chalets, Nagpur Airport"],
    "Nainital": ["Treebo Green Oak"],
    "New Delhi": ["Treebo C T International", "Treebo Mona Grand"],
    "Noida": ["Treebo The Eden Roc", "Treebo Modern Stays"],
    "Ooty": ["Treebo Light House, 900 Mtrs From Botanical Garden"],
    "Patna": ["Treebo The Pearl Bliss"],
    "Pondicherry": ["Treebo Grace Inn, 3 Min Walk From Promenade Beach"],
    "Pune": ["Treebo Premium Grand Emerald", "Treebo Classic Grande, Camp"],
    "Puri": ["Treebo Sidhartha Inn Baliapanda"],
    "Pushkar": ["Treebo Premium Royal Amar With Mountain View"],
    "Ranchi": ["Treebo B&B"],
    "Rishikesh": ["Itsy Hotels Nv, Tapovan", "Treebo Ak Residency"],
    "Shillong": ["Treebo Omega Stay Inn"],
    "Shimla": ["Treebo Varuna With Mountain View"],
    "Siliguri": ["Treebo Premium Blue Mountain Country Club And Resort"],
    "Thekkady": ["Treebo Kumuly Gate Thekkady"],
    "Thiruvananthapuram": ["Treebo West Fort Divine - Near Padmanabhaswamy Temple"],
    "Tirupati": ["Treebo Sls Grand"],
    "Udaipur": ["Treebo The Fresco Lake Pichola"],
    "Varanasi": ["Treebo Little Buddha", "Treebo Golden Kashi"],
    "Varkala": ["Treebo Majestic Retreat"],
    "Visakhapatnam": ["Treebo Celeste"],
    "Wayanad": ["Treebo Regalia Inn Wayanad With Swimming Pool"],
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