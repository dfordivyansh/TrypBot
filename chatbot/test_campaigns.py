"""
Tests for WhatsApp campaigns, tags, segments and opt-out.

Run:  python manage.py test chatbot.test_campaigns

The WhatsApp API is always mocked — nothing here sends a real message.
"""

import io
import json
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import campaign_engine as eng
from .models import (
    Campaign, CampaignRecipient, ChatMessage, ChatSession, ContactTag,
    CRMTemplate, OptInRecord, SalesProfile, Segment,
)


def ok_send(*args, **kwargs):
    ok_send.n += 1
    return {"ok": True, "id": f"wamid.TEST{ok_send.n}"}


ok_send.n = 0


def fail(code, message="boom", **kw):
    base = {"ok": False, "code": str(code), "message": message, "retry": False, "throttle": False, "fatal": False}
    base.update(kw)
    return base


class Base(TestCase):
    def setUp(self):
        patcher = mock.patch.object(eng, "SEND_INTERVAL", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        p2 = mock.patch.object(eng, "THROTTLE_SLEEP", 0)
        p2.start()
        self.addCleanup(p2.stop)

        self.admin = User.objects.create_superuser("boss", "b@x.com", "pw")
        self.tpl = CRMTemplate.objects.create(
            title="Promo", template_name="promo_offer", language="en_US",
            template_text="Hi {{1}}, special offer for {{2}}!",
        )
        self.plain_tpl = CRMTemplate.objects.create(
            title="Plain", template_name="plain_hello", template_text="Hello from TrypDeals")
        self.s1 = ChatSession.objects.create(session_id="919811111111", phone_number="919811111111", user_name="Asha Rao", current_destination="Goa")
        self.s2 = ChatSession.objects.create(session_id="919822222222", phone_number="919822222222", user_name="Vikram")
        self.s3 = ChatSession.objects.create(session_id="919833333333", phone_number="919833333333", user_name="Neha", marketing_opt_out=True)
        self.client.force_login(self.admin)

    def payload(self, **over):
        data = {
            "name": "Test blast",
            "template_id": self.tpl.id,
            "mapping": {"1": {"source": "first_name", "fallback": "there"}, "2": {"source": "fixed", "value": "Char Dham"}},
            "audience": {"type": "filters", "filters": {}},
            "schedule": {"mode": "now"},
            "consent": True,
        }
        data.update(over)
        return data

    def post(self, url, data):
        return self.client.post(url, json.dumps(data), content_type="application/json")

    def create(self, **over):
        r = self.post(reverse("crm_campaign_create_api"), self.payload(**over))
        return r, (Campaign.objects.filter(pk=r.json().get("id")).first() if r.status_code == 200 else None)


class PhoneTests(TestCase):
    def test_normalize(self):
        n = eng.normalize_phone
        self.assertEqual(n("9876543210"), "919876543210")
        self.assertEqual(n("+91 98765-43210"), "919876543210")
        self.assertEqual(n("09876543210"), "919876543210")
        self.assertEqual(n("0091 9876543210"), "919876543210")
        self.assertEqual(n("919876543210.0"), "919876543210")
        self.assertEqual(n("9.19876543210E+11"), "919876543210")
        self.assertEqual(n("+14155552671"), "14155552671")
        self.assertIsNone(n("12345"))
        self.assertIsNone(n("5876543210"))     # Indian mobiles start with 6-9
        self.assertIsNone(n(""))
        self.assertIsNone(n(None))
        self.assertIsNone(n("abc"))

    def test_variables(self):
        ctx = eng.recipient_context(None, "919811111111", "Asha Rao", {"city": "Delhi"})
        m = {"1": {"source": "first_name"}, "2": {"source": "column", "value": "city"},
             "3": {"source": "destination", "fallback": "your trip"}, "4": {"source": "fixed", "value": "X\nY"}}
        v = eng.compute_variables(m, [1, 2, 3, 4], ctx)
        self.assertEqual(v, {"1": "Asha", "2": "Delhi", "3": "your trip", "4": "X Y"})
        # empty name -> fallback, never an empty string (WhatsApp rejects those)
        v = eng.compute_variables({"1": {"source": "name"}}, [1], eng.recipient_context(None, "1", ""))
        self.assertEqual(v["1"], "there")


class PagesRender(Base):
    def test_all_pages_load(self):
        r, c = self.create(schedule={"mode": "draft"})
        self.assertEqual(r.status_code, 200, r.content)
        for name, args in [
            ("crm_campaign_list", []), ("crm_campaign_create", []), ("crm_audience", []),
            ("crm_contacts", []), ("crm_campaign_detail", [c.id]),
        ]:
            resp = self.client.get(reverse(name, args=args))
            self.assertEqual(resp.status_code, 200, name)
        self.assertContains(self.client.get(reverse("crm_contacts")), "Asha Rao")
        self.assertContains(self.client.get(reverse("crm_contacts")), "Opted out")
        self.assertContains(self.client.get(reverse("crm_campaign_list")), "Test blast")

    def test_sidebar_has_campaigns(self):
        self.assertContains(self.client.get(reverse("crm_contacts")), reverse("crm_campaign_list"))

    def test_login_required(self):
        self.client.logout()
        for name in ["crm_campaign_list", "crm_campaign_create", "crm_audience"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)


class CreateCampaign(Base):
    def test_create_now_skips_opted_out(self):
        r, c = self.create()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(c.status, "running")
        self.assertEqual(c.template_language, "en_US")
        recs = {x.phone: x for x in c.recipients.all()}
        self.assertEqual(len(recs), 3)
        self.assertEqual(recs["919811111111"].variables, {"1": "Asha", "2": "Char Dham"})
        self.assertEqual(recs["919833333333"].status, "skipped")
        self.assertEqual(recs["919811111111"].status, "pending")

    def test_validation_errors(self):
        cases = [
            (dict(name=""), "name"),
            (dict(template_id=999), "template"),
            (dict(mapping={"1": {"source": "name"}}), "Variable"),
            (dict(mapping={"1": {"source": "fixed", "value": ""}, "2": {"source": "name"}}), "text"),
            (dict(consent=False), "opted in"),
            (dict(schedule={"mode": "later", "at": "2001-01-01T10:00"}), "future"),
            (dict(header={"type": "image", "url": "http://insecure/x.png"}), "https"),
            (dict(audience={"type": "contacts", "session_ids": []}), "Select at least one"),
            (dict(audience={"type": "segment", "segment_id": 999}), "Segment not found"),
        ]
        for over, needle in cases:
            r, _ = self.create(**over)
            self.assertEqual(r.status_code, 400, over)
            self.assertIn(needle.lower(), r.json()["error"].lower(), over)
        self.assertEqual(Campaign.objects.count(), 0)   # nothing half-created

    def test_draft_needs_no_consent(self):
        r, c = self.create(schedule={"mode": "draft"}, consent=False)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.status, "draft")

    def test_all_opted_out_rejected_and_rolled_back(self):
        r, _ = self.create(audience={"type": "contacts", "session_ids": [self.s3.id]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("opted out", r.json()["error"])
        self.assertEqual(Campaign.objects.count(), 0)

    def test_scheduled(self):
        at = (timezone.localtime() + timezone.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
        r, c = self.create(schedule={"mode": "later", "at": at})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(c.status, "scheduled")

    def test_tag_filters(self):
        vip = ContactTag.objects.create(name="VIP")
        self.s1.tags.add(vip)
        r, c = self.create(audience={"type": "filters", "filters": {"tags": [vip.id]}})
        self.assertEqual(c.recipients.count(), 1)
        r, c = self.create(name="ex", audience={"type": "filters", "filters": {"exclude_tags": [vip.id]}})
        self.assertEqual(sorted(c.recipients.values_list("phone", flat=True)), ["919822222222", "919833333333"])

    def test_tag_all_mode(self):
        a, b = ContactTag.objects.create(name="A"), ContactTag.objects.create(name="B")
        self.s1.tags.add(a, b)
        self.s2.tags.add(a)
        _, c = self.create(audience={"type": "filters", "filters": {"tags": [a.id, b.id], "tag_mode": "all"}})
        self.assertEqual(list(c.recipients.values_list("phone", flat=True)), ["919811111111"])
        _, c = self.create(name="any", audience={"type": "filters", "filters": {"tags": [a.id, b.id], "tag_mode": "any"}})
        self.assertEqual(c.recipients.count(), 2)

    def test_segment(self):
        vip = ContactTag.objects.create(name="VIP")
        self.s2.tags.add(vip)
        seg = Segment.objects.create(name="VIPs", filters={"tags": [vip.id]})
        _, c = self.create(audience={"type": "segment", "segment_id": seg.id})
        self.assertEqual(list(c.recipients.values_list("phone", flat=True)), ["919822222222"])
        self.assertEqual(c.segment, seg)

    def test_duplicate_phone_sessions_deduped(self):
        ChatSession.objects.create(session_id="dup", phone_number="+919811111111", user_name="Asha again")
        _, c = self.create()
        self.assertEqual(c.recipients.filter(phone="919811111111").count(), 1)

    def test_csv_audience_creates_contacts_and_tags(self):
        rows = [{"phone": "9876500001", "name": "New One", "extra": {"city": "Pune"}},
                {"phone": "919811111111", "name": "Asha", "extra": {}},
                {"phone": "12", "name": "bad", "extra": {}}]
        r, c = self.create(
            mapping={"1": {"source": "column", "value": "city", "fallback": "friend"}, "2": {"source": "fixed", "value": "Goa"}},
            audience={"type": "csv", "csv_rows": rows, "csv_tags": ["Imported", "imported"], "create_contacts": True})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(c.recipients.count(), 2)
        new = ChatSession.objects.get(phone_number="919876500001")
        # must use the phone as session_id so the customer's reply lands in the SAME chat
        self.assertEqual(new.session_id, "919876500001")
        self.assertEqual(list(new.tags.values_list("name", flat=True)), ["Imported"])
        self.assertTrue(OptInRecord.objects.filter(phone_number="919876500001", opt_in_method="import").exists())
        rec = c.recipients.get(phone="919876500001")
        self.assertEqual(rec.variables["1"], "Pune")
        self.assertEqual(c.recipients.get(phone="919811111111").variables["1"], "friend")

    def test_csv_without_creating_contacts(self):
        r, c = self.create(audience={"type": "csv", "csv_rows": [{"phone": "9876500002", "name": "X"}], "create_contacts": False})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ChatSession.objects.filter(phone_number="919876500002").exists())
        self.assertIsNone(c.recipients.get().session)

    def test_too_many_recipients(self):
        with mock.patch.object(eng, "MAX_RECIPIENTS", 1):
            r, _ = self.create()
        self.assertEqual(r.status_code, 400)
        self.assertIn("Too many", r.json()["error"])


class Worker(Base):
    def run_all(self):
        while eng.run_worker_once():
            pass

    def test_sends_records_and_completes(self):
        _, c = self.create()
        with mock.patch.object(eng, "graph_send_template", side_effect=ok_send) as m:
            self.run_all()
        c.refresh_from_db()
        self.assertEqual(c.status, "completed")
        self.assertIsNotNone(c.completed_at)
        self.assertEqual(m.call_count, 2)           # opted-out contact never sent to
        call = m.call_args_list[0]
        self.assertEqual(call.args[1], "promo_offer")
        self.assertEqual(call.args[2], "en_US")
        comps = call.args[3]
        self.assertEqual(comps, [{"type": "body", "parameters": [
            {"type": "text", "text": "Asha"}, {"type": "text", "text": "Char Dham"}]}])
        rec = c.recipients.get(phone="919811111111")
        self.assertEqual(rec.status, "sent")
        self.assertTrue(rec.whatsapp_message_id.startswith("wamid."))
        msg = ChatMessage.objects.get(session=self.s1)
        self.assertEqual(msg.message, "Hi Asha, special offer for Char Dham!")
        self.assertEqual(msg.raw_payload["campaign_id"], c.id)
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.last_message, "Hi Asha, special offer for Char Dham!")

    def test_does_not_bump_inbox_order(self):
        before = ChatSession.objects.get(pk=self.s1.pk).updated_at
        _, c = self.create()
        with mock.patch.object(eng, "graph_send_template", side_effect=ok_send):
            self.run_all()
        self.assertEqual(ChatSession.objects.get(pk=self.s1.pk).updated_at, before)

    def test_no_double_send_when_run_twice(self):
        _, c = self.create()
        with mock.patch.object(eng, "graph_send_template", side_effect=ok_send) as m:
            self.run_all()
            self.run_all()
        self.assertEqual(m.call_count, 2)

    def test_header_media_component(self):
        _, c = self.create(template_id=self.plain_tpl.id, mapping={},
                           header={"type": "document", "url": "https://x.com/a.pdf", "filename": "Trip.pdf"})
        with mock.patch.object(eng, "graph_send_template", side_effect=ok_send) as m:
            self.run_all()
        self.assertEqual(m.call_args.args[3], [{"type": "header", "parameters": [
            {"type": "document", "document": {"link": "https://x.com/a.pdf", "filename": "Trip.pdf"}}]}])

    def test_per_recipient_failure_continues(self):
        _, c = self.create()
        seq = [fail("131026", "Message undeliverable"), {"ok": True, "id": "wamid.OK"}]
        with mock.patch.object(eng, "graph_send_template", side_effect=seq):
            self.run_all()
        c.refresh_from_db()
        self.assertEqual(c.status, "completed")
        self.assertEqual(c.recipients.filter(status="failed").count(), 1)
        self.assertEqual(c.recipients.get(status="failed").error_code, "131026")

    def test_fatal_error_stops_campaign_and_keeps_recipients_pending(self):
        _, c = self.create()
        with mock.patch.object(eng, "graph_send_template", return_value=fail("132001", "Template does not exist", fatal=True)) as m:
            self.run_all()
        c.refresh_from_db()
        self.assertEqual(c.status, "failed")
        self.assertIn("132001", c.last_error)
        self.assertEqual(m.call_count, 1)                      # did not burn through the list
        self.assertEqual(c.recipients.filter(status="pending").count(), 2)
        self.assertEqual(c.recipients.filter(status="failed").count(), 0)

    def test_resume_after_fatal_sends_remaining_exactly_once(self):
        _, c = self.create()
        with mock.patch.object(eng, "graph_send_template", return_value=fail("190", "token", fatal=True)):
            self.run_all()
        eng.resume_campaign(Campaign.objects.get(pk=c.pk))
        with mock.patch.object(eng, "graph_send_template", side_effect=ok_send) as m:
            self.run_all()
        self.assertEqual(m.call_count, 2)
        self.assertEqual(Campaign.objects.get(pk=c.pk).status, "completed")

    def test_retryable_error_is_retried_then_succeeds(self):
        _, c = self.create(audience={"type": "contacts", "session_ids": [self.s1.id]})
        seq = [fail("130429", "rate", retry=True, throttle=True), {"ok": True, "id": "wamid.OK"}]
        with mock.patch.object(eng, "graph_send_template", side_effect=seq) as m:
            self.run_all()
        self.assertEqual(m.call_count, 2)
        self.assertEqual(c.recipients.get().status, "sent")

    def test_retry_gives_up_after_max_attempts(self):
        _, c = self.create(audience={"type": "contacts", "session_ids": [self.s1.id]})
        with mock.patch.object(eng, "graph_send_template", return_value=fail("network", "down", retry=True)):
            self.run_all()
        r = c.recipients.get()
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.attempts, eng.MAX_ATTEMPTS)

    def test_consecutive_failures_pause_campaign(self):
        for i in range(12):
            ChatSession.objects.create(session_id=f"9198000000{i:02d}", phone_number=f"9198000000{i:02d}")
        _, c = self.create()
        with mock.patch.object(eng, "graph_send_template", return_value=fail("131009", "x")) as m, \
                mock.patch.object(eng, "PER_RECIPIENT_CODES", set()):
            self.run_all()
        c.refresh_from_db()
        self.assertEqual(c.status, "failed")
        self.assertEqual(m.call_count, eng.CONSECUTIVE_FAIL_MAX)
        self.assertIn("in a row", c.last_error)

    def test_pause_and_cancel(self):
        _, c = self.create()
        eng.pause_campaign(c)
        with mock.patch.object(eng, "graph_send_template", side_effect=ok_send) as m:
            self.run_all()
        self.assertEqual(m.call_count, 0)
        eng.cancel_campaign(Campaign.objects.get(pk=c.pk))
        c.refresh_from_db()
        self.assertEqual(c.status, "cancelled")
        self.assertEqual(c.recipients.filter(status="pending").count(), 0)

    def test_opt_out_after_launch_is_respected(self):
        _, c = self.create()
        ChatSession.objects.filter(pk=self.s1.pk).update(marketing_opt_out=True)
        with mock.patch.object(eng, "graph_send_template", side_effect=ok_send) as m:
            self.run_all()
        self.assertEqual(m.call_count, 1)
        self.assertEqual(c.recipients.get(phone="919811111111").status, "skipped")

    def test_scheduled_campaign_starts_when_due(self):
        at = timezone.now() + timezone.timedelta(hours=1)
        _, c = self.create()
        Campaign.objects.filter(pk=c.pk).update(status="scheduled", scheduled_at=at)
        with mock.patch.object(eng, "graph_send_template", side_effect=ok_send) as m:
            self.run_all()
            self.assertEqual(m.call_count, 0)
            Campaign.objects.filter(pk=c.pk).update(scheduled_at=timezone.now() - timezone.timedelta(seconds=1))
            self.run_all()
        self.assertEqual(m.call_count, 2)
        self.assertEqual(Campaign.objects.get(pk=c.pk).status, "completed")

    def test_retry_failed_action(self):
        _, c = self.create()
        with mock.patch.object(eng, "graph_send_template", side_effect=[fail("131026"), {"ok": True, "id": "w1"}]):
            self.run_all()
        c = Campaign.objects.get(pk=c.pk)
        self.assertEqual(eng.retry_failed(c), 1)
        with mock.patch.object(eng, "graph_send_template", side_effect=ok_send) as m:
            self.run_all()
        self.assertEqual(m.call_count, 1)
        self.assertEqual(Campaign.objects.get(pk=c.pk).recipients.filter(status="failed").count(), 0)

    def test_stale_sending_recovered_as_failed_not_resent(self):
        _, c = self.create()
        CampaignRecipient.objects.filter(campaign=c, phone="919811111111").update(
            status="sending", claimed_at=timezone.now() - timezone.timedelta(minutes=30))
        with mock.patch.object(eng, "graph_send_template", side_effect=ok_send) as m:
            self.run_all()
        self.assertEqual(m.call_count, 1)                 # only the other contact
        self.assertEqual(c.recipients.get(phone="919811111111").status, "failed")

    @override_settings(WHATSAPP_ACCESS_TOKEN="")
    def test_missing_credentials(self):
        _, c = self.create()
        with mock.patch.object(eng, "graph_send_template") as m:
            self.run_all()
        c.refresh_from_db()
        self.assertEqual(m.call_count, 0)
        self.assertEqual(c.status, "failed")
        self.assertIn("credentials", c.last_error)
        self.assertEqual(c.recipients.filter(status="pending").count(), 2)


class GraphErrors(TestCase):
    def resp(self, status, body):
        m = mock.Mock(status_code=status, ok=200 <= status < 300)
        m.json.return_value = body
        return m

    def test_success(self):
        with mock.patch.object(eng.requests, "post", return_value=self.resp(200, {"messages": [{"id": "wamid.X"}]})) as p:
            r = eng.graph_send_template("919811111111", "promo", "en", [{"type": "body", "parameters": []}])
        self.assertEqual(r, {"ok": True, "id": "wamid.X"})
        sent = p.call_args.kwargs["json"]
        self.assertEqual(sent["template"]["language"], {"code": "en"})
        self.assertEqual(sent["type"], "template")

    def test_classification(self):
        def call(status, code, details=None):
            err = {"code": code, "message": "m"}
            if details:
                err["error_data"] = {"details": details}
            with mock.patch.object(eng.requests, "post", return_value=self.resp(status, {"error": err})):
                return eng.graph_send_template("1", "t", "en", [])
        self.assertTrue(call(400, 132001)["fatal"])
        self.assertTrue(call(401, 190)["fatal"])
        r = call(429, 130429)
        self.assertTrue(r["retry"] and r["throttle"] and not r["fatal"])
        r = call(400, 131026)
        self.assertFalse(r["retry"] or r["fatal"])
        self.assertIn("template name", call(400, 132001, "template name does not exist")["message"])

    def test_network_error(self):
        with mock.patch.object(eng.requests, "post", side_effect=eng.requests.ConnectionError("down")):
            r = eng.graph_send_template("1", "t", "en", [])
        self.assertTrue(r["retry"] and not r["ok"])


class WebhookHooks(Base):
    def make_recipient(self):
        _, c = self.create(audience={"type": "contacts", "session_ids": [self.s1.id]})
        with mock.patch.object(eng, "graph_send_template", return_value={"ok": True, "id": "wamid.ABC"}):
            while eng.run_worker_once():
                pass
        return c, c.recipients.get()

    def test_status_progression_and_out_of_order(self):
        c, r = self.make_recipient()
        self.assertTrue(eng.on_status_update("wamid.ABC", "sent", "1700000000"))
        eng.on_status_update("wamid.ABC", "read", "1700000100")          # read arrives before delivered
        r.refresh_from_db()
        self.assertEqual(r.status, "read")
        self.assertIsNotNone(r.delivered_at)
        self.assertIsNotNone(r.read_at)
        eng.on_status_update("wamid.ABC", "delivered", "1700000050")     # late delivered must not downgrade
        r.refresh_from_db()
        self.assertEqual(r.status, "read")
        stats = eng.campaign_stats(c)
        self.assertEqual((stats["sent"], stats["delivered"], stats["read"], stats["failed"]), (1, 1, 1, 0))

    def test_async_failure(self):
        c, r = self.make_recipient()
        eng.on_status_update("wamid.ABC", "failed", None,
                             [{"code": 131026, "title": "Message Undeliverable", "message": "Not on WhatsApp"}])
        r.refresh_from_db()
        self.assertEqual((r.status, r.error_code), ("failed", "131026"))
        self.assertEqual(eng.campaign_stats(c)["failed"], 1)

    def test_unknown_message_id(self):
        self.assertFalse(eng.on_status_update("wamid.NOPE", "read"))
        self.assertFalse(eng.on_status_update("", "read"))

    def test_via_real_status_handler_and_no_spam_metrics(self):
        from .views import handle_message_status
        from .models import UserEngagement
        c, r = self.make_recipient()
        handle_message_status({"id": "wamid.ABC", "status": "delivered", "timestamp": "1700000000"})
        handle_message_status({"id": "wamid.ABC", "status": "read", "timestamp": "1700000001"})
        r.refresh_from_db()
        self.assertEqual(r.status, "read")
        self.assertEqual(ChatMessage.objects.get(session=self.s1).message_status, "read")
        # broadcast receipts must not create conversational spam-risk data
        self.assertFalse(UserEngagement.objects.filter(session=self.s1).exists())

    def test_reply_attribution(self):
        c, r = self.make_recipient()
        self.assertIsNone(eng.on_inbound_message(self.s1, "Yes please share details"))
        r.refresh_from_db()
        self.assertIsNotNone(r.replied_at)
        self.assertEqual(eng.campaign_stats(c)["replied"], 1)

    def test_stop_and_subscribe(self):
        for word in ["STOP", " stop ", "Unsubscribe", "stop!", "OPT OUT"]:
            ChatSession.objects.filter(pk=self.s2.pk).update(marketing_opt_out=False)
            s = ChatSession.objects.get(pk=self.s2.pk)
            self.assertEqual(eng.on_inbound_message(s, word), "opted_out", word)
            self.assertTrue(ChatSession.objects.get(pk=self.s2.pk).marketing_opt_out)
        s = ChatSession.objects.get(pk=self.s2.pk)
        self.assertEqual(eng.on_inbound_message(s, "SUBSCRIBE"), "opted_in")
        self.assertFalse(ChatSession.objects.get(pk=self.s2.pk).marketing_opt_out)

    def test_normal_messages_never_opt_out(self):
        for text in ["Please cancel my booking", "don't stop the tour", "stop at Jaipur on day 2",
                     "I want to remove one person", "Hi", "start"]:
            self.assertIsNone(eng.on_inbound_message(self.s2, text), text)
        self.assertFalse(ChatSession.objects.get(pk=self.s2.pk).marketing_opt_out)

    def test_stop_through_the_real_webhook(self):
        from django.conf import settings
        payload = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID, "display_phone_number": "1"},
            "contacts": [{"profile": {"name": "Vikram"}}],
            "messages": [{"id": "wamid.IN1", "from": "919822222222", "type": "text", "text": {"body": "STOP"}}],
        }}]}]}
        with mock.patch("chatbot.views._send_plain_text") as send, \
                mock.patch("chatbot.views.generate_response") as bot:
            r = self.client.post("/api/whatsapp-webhook/", json.dumps(payload), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json().get("marketing_opt"), "opted_out")
        self.assertTrue(ChatSession.objects.get(pk=self.s2.pk).marketing_opt_out)
        send.assert_called_once()
        self.assertIn("unsubscribed", send.call_args.args[1])
        bot.assert_not_called()                       # the chatbot must not answer a STOP
        self.assertFalse(ChatSession.objects.get(pk=self.s2.pk).data.get("_processing"))
        self.assertTrue(ChatMessage.objects.filter(session=self.s2, sender_type="bot", message__contains="unsubscribed").exists())


class FileParsing(TestCase):
    def upload(self, name, content):
        return SimpleUploadedFile(name, content if isinstance(content, bytes) else content.encode())

    def test_csv_with_header(self):
        r = eng.parse_contacts_file(self.upload("c.csv", "Name,Mobile Number,Tags,City\nRahul,98765 43210,\"a, b\",Delhi\nBad,123,,X\nDup,9876543210,,Y\n,+919812345678,,\n"))
        self.assertEqual([x["phone"] for x in r["rows"]], ["919876543210", "919812345678"])
        self.assertEqual(r["rows"][0]["tags"], ["a", "b"])
        self.assertEqual(r["rows"][0]["extra"]["City"], "Delhi")
        self.assertEqual((len(r["invalid"]), r["duplicates"]), (1, 1))
        self.assertEqual(r["invalid"][0]["row"], 3)
        self.assertIn("City", r["columns"])
        self.assertNotIn("Mobile Number", r["columns"])

    def test_headerless_csv(self):
        r = eng.parse_contacts_file(self.upload("c.csv", "9876543210,Rahul\n9812345678,Priya\n"))
        self.assertEqual(len(r["rows"]), 2)
        self.assertEqual(r["rows"][1]["name"], "Priya")

    def test_semicolon_and_bom(self):
        r = eng.parse_contacts_file(self.upload("c.csv", b"\xef\xbb\xbfphone;name\n9876543210;Rahul\n"))
        self.assertEqual(r["rows"][0]["name"], "Rahul")

    def test_xlsx(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["phone", "name"])
        ws.append([9876543210, "Rahul"])                  # number cell, not text
        ws.append([9.19812345678e11, "Priya"])            # float cell
        buf = io.BytesIO()
        wb.save(buf)
        r = eng.parse_contacts_file(self.upload("c.xlsx", buf.getvalue()))
        self.assertEqual([x["phone"] for x in r["rows"]], ["919876543210", "919812345678"])

    def test_errors(self):
        with self.assertRaisesMessage(ValueError, "phone column"):
            eng.parse_contacts_file(self.upload("c.csv", "name,city\nA,B\n"))
        with self.assertRaisesMessage(ValueError, "empty"):
            eng.parse_contacts_file(self.upload("c.csv", ""))
        with self.assertRaisesMessage(ValueError, ".xlsx"):
            eng.parse_contacts_file(self.upload("c.xls", "x"))
        with mock.patch.object(eng, "CSV_MAX_ROWS", 1):
            with self.assertRaisesMessage(ValueError, "limit"):
                eng.parse_contacts_file(self.upload("c.csv", "phone\n9876543210\n9812345678\n"))

    def test_upload_endpoint(self):
        admin = User.objects.create_superuser("a2", "a@x.com", "pw")
        ChatSession.objects.create(session_id="919876543210", phone_number="919876543210", marketing_opt_out=True)
        self.client.force_login(admin)
        r = self.client.post(reverse("crm_campaign_audience_csv"),
                             {"file": self.upload("c.csv", "phone,name\n9876543210,A\n9812345678,B\n")})
        j = r.json()
        self.assertTrue(j["success"])
        self.assertEqual((j["existing_count"], j["new_count"], j["opted_out_count"]), (1, 1, 1))
        r = self.client.post(reverse("crm_campaign_audience_csv"), {"file": self.upload("c.csv", "name\nA\n")})
        self.assertEqual(r.status_code, 400)


class ActionsApi(Base):
    def act(self, c, action, body=None):
        return self.post(reverse("crm_campaign_action", args=[c.id, action]), body or {})

    def test_lifecycle(self):
        _, c = self.create(schedule={"mode": "draft"})
        r = self.act(c, "start", {"mode": "now"})
        self.assertEqual(r.status_code, 400)                                 # consent required
        r = self.act(c, "start", {"mode": "now", "consent": True})
        self.assertEqual(r.json()["status"], "running")
        self.assertEqual(self.act(c, "pause").json()["status"], "paused")
        self.assertEqual(self.act(c, "resume").json()["status"], "running")
        self.assertEqual(self.act(c, "delete").status_code, 400)             # can't delete while running
        self.assertEqual(self.act(c, "cancel").json()["status"], "cancelled")
        dup = self.act(c, "duplicate").json()
        copy = Campaign.objects.get(pk=dup["redirect"].rstrip("/").split("/")[-1])
        self.assertEqual(copy.status, "draft")
        self.assertEqual(copy.recipients.filter(status="pending").count(), 2)
        self.assertEqual(copy.recipients.filter(status="skipped").count(), 1)   # opted-out stays skipped
        self.assertEqual(self.act(c, "delete").status_code, 200)
        self.assertFalse(Campaign.objects.filter(pk=c.pk).exists())
        self.assertEqual(self.act(copy, "bogus").status_code, 404)

    def test_start_schedule_in_past_rejected(self):
        _, c = self.create(schedule={"mode": "draft"})
        r = self.act(c, "start", {"mode": "later", "at": "2001-01-01T10:00", "consent": True})
        self.assertEqual(r.status_code, 400)

    def test_stats_recipients_export(self):
        _, c = self.create()
        s = self.client.get(reverse("crm_campaign_stats", args=[c.id])).json()
        self.assertEqual(s["stats"]["total"], 3)
        self.assertEqual(s["stats"]["skipped"], 1)
        self.assertEqual(s["stats"]["sendable"], 2)
        rr = self.client.get(reverse("crm_campaign_recipients", args=[c.id]) + "?filter=skipped").json()
        self.assertEqual([x["phone"] for x in rr["rows"]], ["919833333333"])
        rr = self.client.get(reverse("crm_campaign_recipients", args=[c.id]) + "?q=asha").json()
        self.assertEqual(rr["total"], 1)
        csv_resp = self.client.get(reverse("crm_campaign_export", args=[c.id]))
        self.assertEqual(csv_resp["Content-Type"].split(";")[0], "text/csv")
        self.assertIn("919811111111", csv_resp.content.decode())

    def test_list_stats_endpoint(self):
        _, c = self.create()
        j = self.client.get(reverse("crm_campaign_list_stats") + f"?ids={c.id},abc,999").json()
        self.assertEqual(list(j["campaigns"].keys()), [str(c.id)])


class AudienceApi(Base):
    def test_preview_counts(self):
        j = self.post(reverse("crm_campaign_audience_preview"), {"type": "filters", "filters": {}}).json()
        self.assertEqual((j["total"], j["opted_out"], j["eligible"]), (3, 1, 2))
        self.assertEqual(len(j["sample"]), 2)
        j = self.post(reverse("crm_campaign_audience_preview"), {"type": "filters", "filters": {"q": "asha"}}).json()
        self.assertEqual(j["total"], 1)
        j = self.post(reverse("crm_campaign_audience_preview"), {"type": "filters", "filters": {"destination": "goa"}}).json()
        self.assertEqual(j["total"], 1)

    def test_activity_filters(self):
        ChatSession.objects.filter(pk=self.s1.pk).update(last_customer_message_time=timezone.now() - timezone.timedelta(days=2))
        ChatSession.objects.filter(pk=self.s2.pk).update(last_customer_message_time=timezone.now() - timezone.timedelta(days=60))
        p = lambda f: self.post(reverse("crm_campaign_audience_preview"), {"type": "filters", "filters": f}).json()["total"]
        self.assertEqual(p({"active_within_days": 7}), 1)
        self.assertEqual(p({"inactive_days": 30}), 2)     # s2 (60d) + s3 (never)

    def test_picker_pagination(self):
        j = self.post(reverse("crm_campaign_audience_contacts"), {"filters": {}, "page": 1}).json()
        self.assertEqual(j["total"], 3)
        self.assertTrue(any(c["opted_out"] for c in j["contacts"]))

    def test_media_upload_validation(self):
        r = self.client.post(reverse("crm_campaign_media"), {"file": SimpleUploadedFile("a.gif", b"GIF89a", content_type="image/gif")})
        self.assertEqual(r.status_code, 400)
        with mock.patch("chatbot.views.upload_to_cloudinary", return_value="https://cdn.x/y.png"):
            r = self.client.post(reverse("crm_campaign_media"), {"file": SimpleUploadedFile("a.png", b"\x89PNG", content_type="image/png")})
        self.assertEqual(r.json()["url"], "https://cdn.x/y.png")


class TagsAndOptOut(Base):
    def test_tag_crud_and_apply(self):
        r = self.post(reverse("crm_tag_save"), {"name": "VIP", "color": "#ff0000"})
        tag = ContactTag.objects.get()
        self.assertEqual(tag.color, "#ff0000")
        self.assertEqual(self.post(reverse("crm_tag_save"), {"name": "vip"}).status_code, 400)   # case-insensitive dup
        self.assertEqual(self.post(reverse("crm_tag_save"), {"name": " "}).status_code, 400)
        self.assertEqual(self.post(reverse("crm_tag_save"), {"id": tag.id, "name": "Gold"}).status_code, 200)

        r = self.post(reverse("crm_contacts_tag_apply"), {"session_ids": [self.s1.id, self.s2.id], "add": [tag.id], "new_tag": "Fresh"})
        self.assertEqual(r.json()["count"], 2)
        self.assertEqual(self.s1.tags.count(), 2)
        # applying twice must not duplicate
        self.post(reverse("crm_contacts_tag_apply"), {"session_ids": [self.s1.id], "add": [tag.id]})
        self.assertEqual(self.s1.tags.filter(pk=tag.pk).count(), 1)
        self.post(reverse("crm_contacts_tag_apply"), {"session_ids": [self.s1.id], "remove": [tag.id]})
        self.assertFalse(self.s1.tags.filter(pk=tag.pk).exists())
        self.assertEqual(self.post(reverse("crm_contacts_tag_apply"), {"session_ids": [self.s1.id]}).status_code, 400)
        self.assertEqual(self.post(reverse("crm_contacts_tag_apply"), {"session_ids": []}).status_code, 400)
        self.assertEqual(self.post(reverse("crm_tag_delete", args=[tag.id]), {}).status_code, 200)

    def test_apply_to_all_matching_filter(self):
        r = self.post(reverse("crm_contacts_tag_apply"), {"select_all": True, "filters": {"q": "ne"}, "new_tag": "Matched"})
        names = set(ContactTag.objects.get(name="Matched").sessions.values_list("user_name", flat=True))
        self.assertEqual(names, {"Neha"})
        self.post(reverse("crm_contacts_tag_apply"), {"select_all": True, "filters": {}, "add": [ContactTag.objects.get(name="Matched").id]})
        self.assertEqual(ContactTag.objects.get(name="Matched").sessions.count(), 3)

    def test_opt_out_api(self):
        r = self.post(reverse("crm_contacts_opt_out"), {"session_ids": [self.s1.id, self.s2.id], "opted_out": True})
        self.assertEqual(r.json()["count"], 2)
        self.s1.refresh_from_db()
        self.assertTrue(self.s1.marketing_opt_out)
        self.assertIsNotNone(self.s1.marketing_opt_out_at)
        self.post(reverse("crm_contacts_opt_out"), {"session_ids": [self.s1.id], "opted_out": False})
        self.s1.refresh_from_db()
        self.assertFalse(self.s1.marketing_opt_out)
        self.assertIsNone(self.s1.marketing_opt_out_at)

    def test_opt_out_select_all_filtered(self):
        self.post(reverse("crm_contacts_opt_out"), {"select_all": True, "filters": {"opt": "in"}, "opted_out": True})
        self.assertEqual(ChatSession.objects.filter(marketing_opt_out=True).count(), 3)

    def test_contacts_page_filters(self):
        tag = ContactTag.objects.create(name="VIP")
        self.s1.tags.add(tag)
        page = lambda q: self.client.get(reverse("crm_contacts") + q).context["contacts"]
        self.assertEqual([c.user_name for c in page(f"?tag={tag.id}")], ["Asha Rao"])
        self.assertEqual(page("?tag=none").paginator.count, 2)
        self.assertEqual([c.user_name for c in page("?opt=out")], ["Neha"])
        self.assertEqual(page("?opt=in").paginator.count, 2)

    def test_import_contacts(self):
        f = SimpleUploadedFile("c.csv", b"phone,name,tags\n9876500001,New One,warm\n919811111111,Asha,\nbad,x,\n")
        r = self.client.post(reverse("crm_contacts_import"), {"file": f, "tags": "Batch1", "consent": "true"})
        j = r.json()
        self.assertEqual((j["created"], j["existing"], j["invalid"]), (1, 1, 1))
        new = ChatSession.objects.get(phone_number="919876500001")
        self.assertEqual(sorted(new.tags.values_list("name", flat=True)), ["Batch1", "warm"])
        self.assertEqual(sorted(self.s1.tags.values_list("name", flat=True)), ["Batch1"])
        # consent required
        f = SimpleUploadedFile("c.csv", b"phone\n9876500009\n")
        self.assertEqual(self.client.post(reverse("crm_contacts_import"), {"file": f}).status_code, 400)

    def test_segment_crud_and_permissions(self):
        r = self.post(reverse("crm_segment_save"), {"name": "Goa people", "filters": {"destination": "goa"}})
        seg = Segment.objects.get()
        self.assertEqual(self.post(reverse("crm_segment_save"), {"name": "goa PEOPLE", "filters": {}}).status_code, 400)
        page = self.client.get(reverse("crm_audience"))
        self.assertContains(page, "Goa people")
        self.assertContains(page, "Destination goa")
        self.assertEqual(self.post(reverse("crm_segment_delete", args=[seg.id]), {}).status_code, 200)


class Permissions(TestCase):
    def setUp(self):
        self.sales1 = User.objects.create_user("s1", password="pw")
        self.sales2 = User.objects.create_user("s2", password="pw")
        SalesProfile.objects.create(user=self.sales1, role="sales")
        SalesProfile.objects.create(user=self.sales2, role="sales")
        self.mgr = User.objects.create_user("m", password="pw")
        SalesProfile.objects.create(user=self.mgr, role="manager")
        self.tpl = CRMTemplate.objects.create(title="T", template_name="t", template_text="Hello")
        self.mine = ChatSession.objects.create(session_id="919811111111", phone_number="919811111111", assigned_sales_person=self.sales1)
        self.theirs = ChatSession.objects.create(session_id="919822222222", phone_number="919822222222", assigned_sales_person=self.sales2)

    def create_as(self, user, **aud):
        self.client.force_login(user)
        r = self.client.post(reverse("crm_campaign_create_api"), json.dumps({
            "name": "x", "template_id": self.tpl.id, "mapping": {}, "audience": aud or {"type": "filters", "filters": {}},
            "schedule": {"mode": "draft"}}), content_type="application/json")
        return r

    def test_sales_only_reach_their_own_contacts(self):
        r = self.create_as(self.sales1)
        c = Campaign.objects.get(pk=r.json()["id"])
        self.assertEqual(list(c.recipients.values_list("phone", flat=True)), ["919811111111"])
        # can't smuggle someone else's contact in by id
        r = self.create_as(self.sales1, type="contacts", session_ids=[self.theirs.id], filters={})
        self.assertEqual(r.status_code, 400)

    def test_manager_sees_everything(self):
        r = self.create_as(self.mgr)
        self.assertEqual(Campaign.objects.get(pk=r.json()["id"]).recipients.count(), 2)

    def test_campaign_visibility(self):
        c = Campaign.objects.get(pk=self.create_as(self.sales1).json()["id"])
        self.client.force_login(self.sales2)
        self.assertEqual(self.client.get(reverse("crm_campaign_detail", args=[c.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse("crm_campaign_action", args=[c.id, "delete"]), "{}", content_type="application/json").status_code, 404)
        self.assertEqual(self.client.get(reverse("crm_campaign_export", args=[c.id])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("crm_campaign_list")), ">x<")
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.get(reverse("crm_campaign_detail", args=[c.id])).status_code, 200)

    def test_sales_cannot_tag_or_optout_others_contacts(self):
        self.client.force_login(self.sales1)
        r = self.client.post(reverse("crm_contacts_opt_out"), json.dumps({"session_ids": [self.theirs.id], "opted_out": True}), content_type="application/json")
        self.assertEqual(r.json()["count"], 0)
        self.theirs.refresh_from_db()
        self.assertFalse(self.theirs.marketing_opt_out)

    def test_only_managers_delete_tags(self):
        tag = ContactTag.objects.create(name="T1")
        self.client.force_login(self.sales1)
        self.assertEqual(self.client.post(reverse("crm_tag_delete", args=[tag.id]), "{}", content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(reverse("crm_tag_save"), json.dumps({"id": tag.id, "name": "zz"}), content_type="application/json").status_code, 403)
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.post(reverse("crm_tag_delete", args=[tag.id]), "{}", content_type="application/json").status_code, 200)
