from django.core.management.base import BaseCommand

from chatbot.website_tours import CACHE_FILE, fetch_and_store


class Command(BaseCommand):
    help = "Download the www.trypdeals.com tour catalogue used in bot replies (also refreshes itself every 12 hours)."

    def handle(self, *args, **options):
        count = fetch_and_store()
        self.stdout.write(self.style.SUCCESS(f"Synced {count} website tours to {CACHE_FILE}"))
