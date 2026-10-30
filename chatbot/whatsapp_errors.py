"""
Why a WhatsApp message was not delivered, and what the team can do about it.

explain() turns a Meta error (code + text) and the customer's number into a
short reason and a fix. note_delivery_failure() posts it in the chat as a
TrypBot system message, so the agent sees it right under the failed message.
"""

# code -> (reason, how to fix)
ERRORS = {
    131026: (
        "This number is not on WhatsApp, or the customer has blocked us or not accepted WhatsApp's latest terms.",
        "Call the customer and confirm their WhatsApp number (with the right country code). "
        "Ask them to send 'Hi' to +91 87662 47711, then reply here. If they use another WhatsApp number, add it with + New Chat.",
    ),
    131047: (
        "More than 24 hours have passed since the customer's last message, so WhatsApp allows only an approved template.",
        "Use 📎 → Follow Up and send a template. When the customer replies, normal messages work again for 24 hours.",
    ),
    131049: (
        "WhatsApp held this message back to protect the customer's experience (too many business messages without replies).",
        "Wait a day before trying again, or call the customer. Avoid sending several templates in a row.",
    ),
    131050: (
        "The customer has stopped marketing messages from us on WhatsApp.",
        "Call the customer instead. Only send messages they ask for.",
    ),
    131056: (
        "Too many messages were sent to this customer in a short time.",
        "Wait a few minutes and send again.",
    ),
    131021: (
        "This is our own business number, so WhatsApp will not send to it.",
        "Check the customer's number in the chat header (pencil icon).",
    ),
    131030: (
        "This number is not in the allowed test list of the WhatsApp account.",
        "Use the live WhatsApp number setup, or add this number to the test recipients in Meta.",
    ),
    131051: (
        "WhatsApp does not support this message type.",
        "Send it as plain text or as a document instead.",
    ),
    131052: (
        "The customer's media could not be downloaded.",
        "Ask the customer to send the file again.",
    ),
    131053: (
        "The file could not be sent (wrong format or too large).",
        "Send a JPG/PNG image, MP4 video or PDF under 16 MB.",
    ),
    131000: (
        "WhatsApp had a temporary problem sending this message.",
        "Try again in a few minutes.",
    ),
    131005: (
        "Our WhatsApp account is not allowed to send this message.",
        "Ask the admin to check the WhatsApp Business account permissions in Meta.",
    ),
    131008: (
        "The message was missing something WhatsApp needs.",
        "Send it again; if it keeps failing, tell the admin.",
    ),
    131009: (
        "WhatsApp rejected a value in the message (often the phone number or template text).",
        "Check the customer's number and country code, then send again.",
    ),
    131016: (
        "WhatsApp's service is overloaded right now.",
        "Try again in a few minutes.",
    ),
    131042: (
        "Payment problem on our WhatsApp Business account.",
        "Ask the admin to check billing in Meta Business Manager.",
    ),
    131045: (
        "Our WhatsApp number is not registered correctly.",
        "Ask the admin to check the phone number status in Meta.",
    ),
    131057: (
        "Our WhatsApp Business account is under maintenance.",
        "Try again later.",
    ),
    132000: (
        "The template's variables did not match the approved template.",
        "Ask the admin to check the template in Admin → CRM Templates.",
    ),
    132001: (
        "This template name or language does not exist or is not approved in Meta.",
        "Ask the admin to check the template name in Admin → CRM Templates matches the approved one in Meta.",
    ),
    132005: (
        "The template text became too long after filling it in.",
        "Use a shorter template.",
    ),
    132007: (
        "The template breaks WhatsApp's content rules.",
        "Use another template, or edit and re-approve it in Meta.",
    ),
    132012: (
        "The template's parameters are in the wrong format.",
        "Ask the admin to check the template in Admin → CRM Templates.",
    ),
    132015: (
        "This template is paused by Meta because of low quality.",
        "Use another template.",
    ),
    132016: (
        "This template is disabled by Meta.",
        "Use another template.",
    ),
    133010: (
        "Our WhatsApp number is not registered on the Cloud API.",
        "Ask the admin to register the number in Meta.",
    ),
    130429: (
        "We are sending too many messages per second.",
        "Wait a minute and try again.",
    ),
    130472: (
        "Meta did not deliver this message as part of a WhatsApp experiment on this user.",
        "Send it again later, or use a template.",
    ),
    190: (
        "The WhatsApp access token has expired.",
        "Ask the admin to update WHATSAPP_ACCESS_TOKEN in .env and restart the service.",
    ),
    100: (
        "WhatsApp rejected the request (invalid parameter, often the phone number).",
        "Check the customer's number and country code (pencil icon in the chat header).",
    ),
}

# Country codes we see most, for a readable note on international numbers.
COUNTRIES = {
    "1": "USA/Canada", "44": "UK", "971": "UAE", "966": "Saudi Arabia", "974": "Qatar",
    "968": "Oman", "965": "Kuwait", "973": "Bahrain", "65": "Singapore", "60": "Malaysia",
    "61": "Australia", "64": "New Zealand", "977": "Nepal", "880": "Bangladesh",
    "94": "Sri Lanka", "49": "Germany", "33": "France", "39": "Italy", "31": "Netherlands",
    "27": "South Africa", "81": "Japan", "86": "China", "852": "Hong Kong",
}


def number_note(phone):
    """A hint about the number itself (international / looks wrong), or ''."""
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if not digits:
        return "There is no phone number on this chat."
    if digits.startswith("91"):
        if len(digits) != 12 or digits[2] not in "6789":
            return f"+{digits} does not look like a valid Indian mobile number (91 + 10 digits starting with 6-9)."
        return ""
    country = next((COUNTRIES[c] for c in sorted(COUNTRIES, key=len, reverse=True) if digits.startswith(c)), None)
    where = f" ({country})" if country else ""
    return (f"+{digits} is an international number{where}. WhatsApp delivers only if this exact number, "
            f"with this country code, has WhatsApp.")


def explain(code=None, details="", phone=""):
    """(reason, fix) for a failed message, in plain words."""
    try:
        code = int(code) if code not in (None, "") else None
    except (TypeError, ValueError):
        code = None
    reason, fix = ERRORS.get(code, (
        f"WhatsApp could not deliver this message{f' (error {code})' if code else ''}"
        f"{': ' + details if details else ''}.",
        "Check the customer's number, then try again. If it keeps failing, call the customer.",
    ))
    # The number only matters when WhatsApp could not reach it.
    note = number_note(phone) if code in (131026, 100, 131009, None) else ""
    if note:
        reason = f"{reason} {note}"
        if "international" in note:
            fix = (f"{fix} For an international number, ask the customer for the number they use on WhatsApp "
                   f"and save it with the full country code.")
    return reason, fix


def note_delivery_failure(message=None, session=None, code=None, details="", what="This message"):
    """Post TrypBot's explanation in the chat (once per failed message)."""
    from .models import ChatMessage

    session = session or (message.session if message else None)
    if session is None:
        return None
    from django.utils import timezone
    key = f"{message.id}" if message else f"{timezone.localdate()}:{code}:{details}"[:120]
    if ChatMessage.objects.filter(session=session, sender_type="system",
                                  raw_payload__delivery_error__key=key).exists():
        return None
    reason, fix = explain(code, details, session.phone_number or session.session_id)
    text = f"⚠️ {what} was not delivered.\nReason: {reason}\nHow to fix: {fix}"
    return ChatMessage.objects.create(
        session=session, sender_type="system", message=text,
        raw_payload={"delivery_error": {"key": key, "code": code, "details": details,
                                        "reason": reason, "fix": fix, "what": what}},
    )
