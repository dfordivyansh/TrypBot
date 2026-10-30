"""
Run the WhatsApp campaign sender as a standalone process.

The Daphne process already runs the sender in a background thread, so this
is only needed if you set CAMPAIGN_INLINE_WORKER=0 or want a separate worker:

    python manage.py run_campaigns            # keep running
    python manage.py run_campaigns --once     # one pass, then exit (Task Scheduler / cron)
"""

import time

from django.core.management.base import BaseCommand

from chatbot.campaign_engine import run_worker_once, worker_loop


class Command(BaseCommand):
    help = "Send queued and scheduled WhatsApp campaigns."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true",
                            help="Process everything that is due, then exit.")
        parser.add_argument("--interval", type=float, default=3.0,
                            help="Seconds to sleep when idle (default 3).")

    def handle(self, *args, **opts):
        if opts["once"]:
            total = 0
            while True:
                n = run_worker_once()
                total += n
                if n == 0:
                    break
            self.stdout.write(self.style.SUCCESS(f"Processed {total} message(s)."))
            return

        self.stdout.write("Campaign worker running — press Ctrl+C to stop.")
        try:
            worker_loop(idle_sleep=opts["interval"])
        except KeyboardInterrupt:
            self.stdout.write("Stopped.")
