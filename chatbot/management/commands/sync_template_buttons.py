from datetime import timedelta

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from chatbot.models import ChatMessage, CRMTemplate

GRAPH = "https://graph.facebook.com/v22.0"


def template_buttons(template_id):
    """The buttons of an approved WhatsApp template, from Meta: [{type, text, phone_number|url}]."""
    res = requests.get(
        f"{GRAPH}/{template_id}",
        params={"fields": "name,status,components", "access_token": settings.WHATSAPP_ACCESS_TOKEN},
        timeout=20,
    )
    body = res.json()
    if "error" in body:
        raise ValueError(body["error"].get("message") or body["error"])
    buttons = []
    for component in body.get("components") or []:
        if component.get("type") != "BUTTONS":
            continue
        for b in component.get("buttons") or []:
            item = {"type": b.get("type", ""), "text": b.get("text", "")}
            if b.get("phone_number"):
                item["phone_number"] = b["phone_number"]
            if b.get("url"):
                item["url"] = b["url"]
            buttons.append(item)
    return body.get("name", ""), buttons


class Command(BaseCommand):
    help = (
        "Read each CRM template's buttons (Call Now, links ...) from Meta, save them, "
        "and add them to the template messages sent in the last 90 days, so the chat shows them."
    )

    def handle(self, *args, **options):
        since = timezone.now() - timedelta(days=90)
        for t in CRMTemplate.objects.exclude(whatsapp_template_id=""):
            try:
                name, buttons = template_buttons(t.whatsapp_template_id)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f"{t.title}: could not read template {t.whatsapp_template_id} from Meta ({exc}). "
                    f"Add its buttons in Admin -> CRM Templates instead."))
                continue
            t.buttons = buttons
            t.save(update_fields=["buttons", "updated_at"])

            updated = 0
            if buttons:
                sent = ChatMessage.objects.filter(
                    sender_type="sales", message=t.template_text, created_at__gte=since)
                for msg in sent:
                    payload = msg.raw_payload if isinstance(msg.raw_payload, dict) else {}
                    if payload.get("buttons"):
                        continue
                    payload.update({"template": t.template_name, "buttons": buttons})
                    ChatMessage.objects.filter(pk=msg.pk).update(raw_payload=payload)
                    updated += 1
            self.stdout.write(self.style.SUCCESS(
                f"{t.title} ({name or t.template_name}): buttons {buttons or 'none'} | "
                f"added to {updated} sent message(s)"))
