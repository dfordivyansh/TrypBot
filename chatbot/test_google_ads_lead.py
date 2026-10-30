"""
Tests for the Google Ads Lead Form Extension webhook.

Run:  python manage.py test chatbot.test_google_ads_lead
"""

import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ChatSession, Lead, RoundRobinTracker, SalesProfile

WEBHOOK_KEY = "test-secret-key-123"


def col(column_id, value):
    return {"column_id": column_id, "column_name": column_id.title(), "string_value": value}


@override_settings(GOOGLE_ADS_LEAD_WEBHOOK_KEY=WEBHOOK_KEY)
class GoogleAdsLeadWebhookTests(TestCase):
    def setUp(self):
        self.url = reverse("google_ads_lead_webhook")
        self.rep = User.objects.create_user("rep1", password="pw")
        SalesProfile.objects.create(
            user=self.rep, role="sales",
            is_active_for_assignment=True, is_active_for_website=True,
            is_active_for_meta=False, assignment_order=1,
        )

    def post(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    def base_payload(self, **over):
        p = {
            "campaign_id": "23552109975",
            "campaign_name": "Trip Packages - Search",
            "google_key": WEBHOOK_KEY,
            "form_id": "form123",
            "gcl_id": "gcl123",
            "lead_id": "lead123",
            "is_test": "0",
            "user_column_data": [
                col("FULL_NAME", "Rahul Sharma"),
                col("PHONE_NUMBER", "+91 98765 43210"),
                col("EMAIL", "rahul@example.com"),
            ],
        }
        p.update(over)
        return p

    # ── happy path ──────────────────────────────────────────

    def test_creates_lead_and_session(self):
        r = self.post(self.base_payload())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["api_version"], "1.0")

        session = ChatSession.objects.get(phone_number="919876543210")
        self.assertEqual(session.user_name, "Rahul Sharma")
        self.assertEqual(session.data["google_ads"]["campaign_name"], "Trip Packages - Search")
        self.assertEqual(session.data["google_ads"]["lead_id"], "lead123")

        lead = Lead.objects.get(session=session)
        self.assertEqual(lead.full_name, "Rahul Sharma")
        self.assertEqual(lead.phone, "919876543210")
        self.assertEqual(lead.email, "rahul@example.com")
        self.assertEqual(lead.source, "google_ads")
        self.assertIn("Trip Packages - Search", lead.notes)

    def test_assigned_through_website_pool(self):
        self.post(self.base_payload())
        session = ChatSession.objects.get(phone_number="919876543210")
        self.assertEqual(session.assigned_sales_person, self.rep)
        # website pool uses RoundRobinTracker id=2
        self.assertTrue(RoundRobinTracker.objects.filter(id=2, last_assigned_order=1).exists())

    def test_first_last_name_fallback(self):
        payload = self.base_payload(user_column_data=[
            col("FIRST_NAME", "Priya"),
            col("LAST_NAME", "Singh"),
            col("PHONE_NUMBER", "9812345678"),
        ])
        self.post(payload)
        lead = Lead.objects.get(phone="919812345678")
        self.assertEqual(lead.full_name, "Priya Singh")

    def test_repeat_submission_updates_not_duplicates(self):
        self.post(self.base_payload())
        self.post(self.base_payload(user_column_data=[
            col("FULL_NAME", "Rahul Sharma Updated"),
            col("PHONE_NUMBER", "+91 98765 43210"),
            col("EMAIL", "rahul@example.com"),
        ]))
        self.assertEqual(ChatSession.objects.filter(phone_number="919876543210").count(), 1)
        self.assertEqual(Lead.objects.filter(phone="919876543210").count(), 1)
        self.assertEqual(Lead.objects.get(phone="919876543210").full_name, "Rahul Sharma Updated")

    def test_custom_questions_preserved(self):
        payload = self.base_payload(user_column_data=[
            col("FULL_NAME", "Amit"),
            col("PHONE_NUMBER", "9876500000"),
            {"column_id": "CQ_1", "column_name": "Preferred destination", "string_value": "Goa"},
        ])
        self.post(payload)
        session = ChatSession.objects.get(phone_number="919876500000")
        self.assertEqual(session.data["google_ads"]["answers"]["Preferred destination"], "Goa")

    def test_custom_contact_number_field_used_as_phone(self):
        """Form uses a CUSTOM question labeled 'Contact number' instead of
        Google's built-in Phone number field — must still populate Lead.phone."""
        payload = self.base_payload(user_column_data=[
            col("FULL_NAME", "Kiran"),
            {"column_id": "CQ_42", "column_name": "Contact number", "string_value": "9800011122"},
        ])
        r = self.post(payload)
        self.assertEqual(r.status_code, 200, r.content)
        lead = Lead.objects.get(full_name="Kiran")
        self.assertEqual(lead.phone, "919800011122")
        session = ChatSession.objects.get(phone_number="919800011122")
        # must not also be duplicated into the free-text answers blob
        self.assertNotIn("Contact number", session.data["google_ads"].get("answers", {}))

    def test_builtin_phone_number_preferred_over_custom_contact_field(self):
        payload = self.base_payload(user_column_data=[
            col("FULL_NAME", "Dual"),
            col("PHONE_NUMBER", "9811122233"),
            {"column_id": "CQ_1", "column_name": "Alternate contact number", "string_value": "9899988877"},
        ])
        self.post(payload)
        lead = Lead.objects.get(full_name="Dual")
        self.assertEqual(lead.phone, "919811122233")

    def test_no_phone_still_creates_a_record(self):
        payload = self.base_payload(user_column_data=[col("FULL_NAME", "No Phone Guy")])
        r = self.post(payload)
        self.assertEqual(r.status_code, 200)
        lead = Lead.objects.get(full_name="No Phone Guy")
        self.assertEqual(lead.phone, "")
        self.assertEqual(lead.source, "google_ads")

    # ── security / verification ────────────────────────────

    def test_wrong_key_rejected(self):
        r = self.post(self.base_payload(google_key="wrong-key"))
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Lead.objects.exists())

    def test_missing_key_rejected(self):
        payload = self.base_payload()
        del payload["google_key"]
        r = self.post(payload)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Lead.objects.exists())

    @override_settings(GOOGLE_ADS_LEAD_WEBHOOK_KEY="")
    def test_unconfigured_key_rejects_everything(self):
        r = self.post(self.base_payload())
        self.assertEqual(r.status_code, 403)

    def test_get_not_allowed(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 405)

    def test_invalid_json_handled(self):
        r = self.client.post(self.url, "not json", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    # ── Google's own health checks ─────────────────────────

    def test_is_test_ping_does_not_create_lead(self):
        for truthy in ("1", "true", "True"):
            r = self.post(self.base_payload(is_test=truthy))
            self.assertEqual(r.status_code, 200)
        self.assertFalse(Lead.objects.exists())
        self.assertFalse(ChatSession.objects.exists())

    def test_empty_submission_acked_but_not_saved(self):
        r = self.post(self.base_payload(user_column_data=[]))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Lead.objects.exists())

    def test_response_always_has_api_version(self):
        for payload_mod in [{}, {"google_key": "bad"}]:
            r = self.post(self.base_payload(**payload_mod))
            self.assertEqual(r.json().get("api_version"), "1.0")
