from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from chatbot.models import Booking, ChatMessage, ChatSession
from chatbot.website_bookings import record_booking


class Command(BaseCommand):
    help = (
        "Fill CRM -> Booking with the website bookings saved before it existed "
        "(from the booking system messages and the chats' data). Safe to run again."
    )

    def handle(self, *args, **options):
        before = Booking.objects.count()

        # Each new booking / payment change left a system message with the
        # booking; oldest first, so the first one sets the booking date.
        messages = (ChatMessage.objects
                    .filter(sender_type="system", raw_payload__has_key="website_booking")
                    .select_related("session").order_by("created_at"))
        for msg in messages.iterator():
            b = (msg.raw_payload or {}).get("website_booking") or {}
            if b.get("code"):
                record_booking(b, msg.session, created_at=msg.created_at)

        # Bookings kept only in a chat's data.
        for session in ChatSession.objects.filter(data__has_key="website_bookings").iterator():
            for code, b in ((session.data or {}).get("website_bookings") or {}).items():
                if isinstance(b, dict) and not Booking.objects.filter(code=code).exists():
                    record_booking(b, session, created_at=parse_datetime(b.get("received_at") or ""))

        self.stdout.write(self.style.SUCCESS(
            f"Bookings: {Booking.objects.count()} ({Booking.objects.count() - before} new)"))
