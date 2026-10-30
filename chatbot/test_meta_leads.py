"""
Tests for the Meta (Facebook / Instagram) Lead Ads webhook.

Run:  python manage.py test chatbot.test_meta_leads

The Graph API is always mocked - nothing here talks to Meta.
"""

import hashlib
import hmac
import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ChatSession, Lead, RoundRobinTracker, SalesProfile

SECRET = "app-secret-xyz"
VERIFY = "verify-token-abc"


def sign(body: bytes, secret=SECRET):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def graph_response(field_data, status=200, **extra):
    r = mock.Mock(status_code=status, text="err")
    r.json.return_value = {
        "id": "L1", "created_time": "2026-09-26T10:00:00+0000",
        "form_id": "F1", "ad_id": "A1", "ad_name": "Ad One",
        "adset_name": "Adset", "campaign_id": "C1", "campaign_name": "Diwali Offer",
        "platform": "fb", "field_data": field_data, **extra,
    }
    return r


def fd(name, *values):
    return {"name": name, "values": list(values)}


def webhook_body(*leadgen_ids, field="leadgen", obj="page"):
    return {
        "object": obj,
        "entry": [{
            "id": "PAGE1", "time": 1,
            "changes": [{"field": field, "value": {
                "leadgen_id": lid, "form_id": "F1", "ad_id": "A1", "page_id": "PAGE1"}}
                for lid in leadgen_ids],
        }],
    }


@override_settings(META_APP_SECRET=SECRET, META_LEADS_VERIFY_TOKEN=VERIFY,
                   META_PAGE_ACCESS_TOKEN="page-token", META_GRAPH_VERSION="v22.0")
class MetaLeadsWebhookTests(TestCase):
    def setUp(self):
        self.url = reverse("meta_leads_webhook")
        self.rep = User.objects.create_user("rep1", password="pw")
        SalesProfile.objects.create(
            user=self.rep, role="sales", is_active_for_assignment=True,
            is_active_for_meta=True, is_active_for_website=False, assignment_order=1)

    def post(self, payload, signature="auto", secret=SECRET):
        body = json.dumps(payload).encode()
        headers = {}
        if signature == "auto":
            headers["HTTP_X_HUB_SIGNATURE_256"] = sign(body, secret)
        elif signature:
            headers["HTTP_X_HUB_SIGNATURE_256"] = signature
        return self.client.post(self.url, body, content_type="application/json", **headers)

    # ---------- verification handshake ----------

    def test_verification_handshake_ok(self):
        r = self.client.get(self.url, {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "12345"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"12345")

    def test_verification_wrong_token_rejected(self):
        r = self.client.get(self.url, {"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"})
        self.assertEqual(r.status_code, 403)

    def test_verification_missing_token_rejected(self):
        r = self.client.get(self.url, {"hub.mode": "subscribe", "hub.challenge": "1"})
        self.assertEqual(r.status_code, 403)

    @override_settings(META_LEADS_VERIFY_TOKEN="")
    def test_verification_unconfigured_rejected(self):
        r = self.client.get(self.url, {"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"})
        self.assertEqual(r.status_code, 403)

    # ---------- signature security ----------

    @mock.patch("chatbot.views.requests.get")
    def test_bad_signature_rejected(self, g):
        r = self.post(webhook_body("L1"), signature="sha256=deadbeef")
        self.assertEqual(r.status_code, 403)
        g.assert_not_called()
        self.assertFalse(Lead.objects.exists())

    @mock.patch("chatbot.views.requests.get")
    def test_missing_signature_rejected(self, g):
        r = self.post(webhook_body("L1"), signature=None)
        self.assertEqual(r.status_code, 403)
        g.assert_not_called()

    @mock.patch("chatbot.views.requests.get")
    def test_signature_from_wrong_secret_rejected(self, g):
        r = self.post(webhook_body("L1"), secret="other-secret")
        self.assertEqual(r.status_code, 403)
        g.assert_not_called()

    @override_settings(META_APP_SECRET="")
    @mock.patch("chatbot.views.requests.get")
    def test_unconfigured_secret_rejects_everything(self, g):
        r = self.post(webhook_body("L1"))
        self.assertEqual(r.status_code, 403)
        g.assert_not_called()

    def test_get_or_post_only(self):
        self.assertEqual(self.client.put(self.url).status_code, 405)

    # ---------- happy path ----------

    @mock.patch("chatbot.views.requests.get")
    def test_lead_created_and_assigned_via_meta_pool(self, g):
        g.return_value = graph_response([
            fd("full_name", "Rahul Sharma"), fd("phone_number", "+919876543210"),
            fd("email", "rahul@example.com"), fd("city", "Delhi"),
        ])
        r = self.post(webhook_body("L1"))
        self.assertEqual(r.status_code, 200, r.content)

        session = ChatSession.objects.get(phone_number="919876543210")
        self.assertEqual(session.user_name, "Rahul Sharma")
        self.assertEqual(session.assigned_sales_person, self.rep)
        self.assertEqual(session.data["meta_ads"]["campaign_name"], "Diwali Offer")
        self.assertEqual(session.data["meta_ads"]["leadgen_id"], "L1")
        self.assertEqual(session.data["meta_ads"]["answers"], {"city": "Delhi"})

        lead = Lead.objects.get(session=session)
        self.assertEqual((lead.source, lead.email, lead.full_name), ("meta_ads", "rahul@example.com", "Rahul Sharma"))
        self.assertIn("Diwali Offer", lead.notes)
        # meta pool uses RoundRobinTracker id=3
        self.assertTrue(RoundRobinTracker.objects.filter(id=3, last_assigned_order=1).exists())

    @mock.patch("chatbot.views.requests.get")
    def test_graph_called_with_leadgen_id_and_page_token(self, g):
        g.return_value = graph_response([fd("full_name", "A"), fd("phone_number", "9876543210")])
        self.post(webhook_body("LEAD-99"))
        url = g.call_args.args[0]
        params = g.call_args.kwargs["params"]
        self.assertEqual(url, "https://graph.facebook.com/v22.0/LEAD-99")
        self.assertEqual(params["access_token"], "page-token")
        self.assertIn("field_data", params["fields"])
        self.assertIn("campaign_name", params["fields"])

    @mock.patch("chatbot.views.requests.get")
    def test_first_last_name_and_custom_contact_field(self, g):
        g.return_value = graph_response([
            fd("first_name", "Priya"), fd("last_name", "Singh"), fd("contact_number", "98123 45678")])
        self.post(webhook_body("L2"))
        lead = Lead.objects.get(phone="919812345678")
        self.assertEqual(lead.full_name, "Priya Singh")

    @mock.patch("chatbot.views.requests.get")
    def test_custom_questions_kept_as_answers(self, g):
        g.return_value = graph_response([
            fd("full_name", "Amit"), fd("phone_number", "9800000001"),
            fd("when_do_you_want_to_travel_", "Next month"), fd("destination", "Goa", "Kerala")])
        self.post(webhook_body("L3"))
        s = ChatSession.objects.get(phone_number="919800000001")
        self.assertEqual(s.data["meta_ads"]["answers"]["when_do_you_want_to_travel_"], "Next month")
        self.assertEqual(s.data["meta_ads"]["answers"]["destination"], "Goa, Kerala")

    @mock.patch("chatbot.views.requests.get")
    def test_lead_without_phone_still_saved(self, g):
        g.return_value = graph_response([fd("full_name", "No Phone"), fd("email", "np@example.com")])
        self.post(webhook_body("L4"))
        lead = Lead.objects.get(full_name="No Phone")
        self.assertEqual((lead.phone, lead.source), ("", "meta_ads"))

    # ---------- multiple / ignored / duplicates ----------

    @mock.patch("chatbot.views.requests.get")
    def test_multiple_leads_in_one_webhook(self, g):
        g.side_effect = [
            graph_response([fd("full_name", "One"), fd("phone_number", "9800000011")]),
            graph_response([fd("full_name", "Two"), fd("phone_number", "9800000012")]),
        ]
        r = self.post(webhook_body("LA", "LB"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Lead.objects.count(), 2)

    @mock.patch("chatbot.views.requests.get")
    def test_other_fields_and_objects_ignored(self, g):
        self.assertEqual(self.post(webhook_body("L1", field="feed")).status_code, 200)
        self.assertEqual(self.post(webhook_body("L1", obj="instagram")).status_code, 200)
        g.assert_not_called()
        self.assertFalse(Lead.objects.exists())

    @mock.patch("chatbot.views.requests.get")
    def test_duplicate_delivery_without_phone_not_duplicated(self, g):
        g.return_value = graph_response([fd("full_name", "Anon")])
        self.post(webhook_body("SAME"))
        self.post(webhook_body("SAME"))
        self.assertEqual(ChatSession.objects.count(), 1)
        self.assertEqual(g.call_count, 1)            # 2nd delivery short-circuits before calling Meta

    @mock.patch("chatbot.views.requests.get")
    def test_same_person_new_submission_updates_same_lead(self, g):
        g.side_effect = [
            graph_response([fd("full_name", "Rahul"), fd("phone_number", "9876543210")]),
            graph_response([fd("full_name", "Rahul S"), fd("phone_number", "9876543210")], campaign_name="Second"),
        ]
        self.post(webhook_body("X1"))
        self.post(webhook_body("X2"))
        self.assertEqual(Lead.objects.filter(phone="919876543210").count(), 1)
        self.assertEqual(Lead.objects.get(phone="919876543210").full_name, "Rahul S")

    # ---------- failure handling (Meta must retry) ----------

    @mock.patch("chatbot.views.requests.get")
    def test_graph_error_returns_500_so_meta_retries_then_succeeds(self, g):
        g.return_value = graph_response([], status=400)
        r = self.post(webhook_body("R1"))
        self.assertEqual(r.status_code, 500)
        self.assertFalse(Lead.objects.exists())

        g.return_value = graph_response([fd("full_name", "Retry"), fd("phone_number", "9800000021")])
        r = self.post(webhook_body("R1"))               # Meta's retry
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Lead.objects.filter(phone="919800000021").count(), 1)

    @override_settings(META_PAGE_ACCESS_TOKEN="")
    @mock.patch("chatbot.views.requests.get")
    def test_missing_page_token_returns_500(self, g):
        r = self.post(webhook_body("R2"))
        self.assertEqual(r.status_code, 500)
        g.assert_not_called()

    @mock.patch("chatbot.views.requests.get")
    def test_one_bad_lead_does_not_lose_the_others(self, g):
        g.side_effect = [
            graph_response([], status=500),
            graph_response([fd("full_name", "Good"), fd("phone_number", "9800000031")]),
        ]
        r = self.post(webhook_body("BAD", "GOOD"))
        self.assertEqual(r.status_code, 500)             # Meta retries the batch
        self.assertTrue(Lead.objects.filter(phone="919800000031").exists())

    def test_invalid_json_with_valid_signature(self):
        body = b"not json"
        r = self.client.post(self.url, body, content_type="application/json",
                             HTTP_X_HUB_SIGNATURE_256=sign(body))
        self.assertEqual(r.status_code, 400)
