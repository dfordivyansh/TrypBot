"""Chat page shows the ad lead-form answers card.  Run: python manage.py test chatbot.test_lead_form_card"""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .models import ChatSession


@override_settings(ALLOWED_HOSTS=["testserver", "127.0.0.1"])
class LeadFormCardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("boss", password="pw")
        self.client.force_login(self.admin)

    def _open(self, session):
        return self.client.get(f"/crm/chat/{session.id}/")

    def test_card_shows_campaign_and_answers(self):
        s = ChatSession.objects.create(
            phone_number="919876543210", user_name="Rahul",
            data={"google_ads": {
                "campaign_name": "Goa Summer", "received_at": "2026-09-26T10:00:00+05:30",
                "answers": {"what_place_would_you_like_to_visit?": "Goa",
                            "what_is_your_travel_budget?": "50000"}}})
        r = self._open(s)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("Lead Form Answers", html)
        self.assertIn("Google Ads", html)
        self.assertIn("Goa Summer", html)
        self.assertIn("What place would you like to visit?", html)
        self.assertIn("50000", html)

    def test_meta_card(self):
        s = ChatSession.objects.create(
            phone_number="919800000001", user_name="Amit",
            data={"meta_ads": {"campaign_name": "Diwali", "answers": {"city": "Delhi"}}})
        html = self._open(s).content.decode()
        self.assertIn("Meta Ads", html)
        self.assertIn("Delhi", html)

    def test_no_card_for_normal_chat(self):
        s = ChatSession.objects.create(phone_number="919811111111", user_name="Plain", data={})
        r = self._open(s)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Lead Form Answers", r.content.decode())
