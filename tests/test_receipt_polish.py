"""Receipt presentation, time conversion and email-preview upgrade boundaries."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sunojob.delivery import DeliveryManager
from sunojob.models import Extraction, SourceTurn
from sunojob.receipt import HTML_PRESENTATION_VERSION, display_time, receipt_html, receipt_json
from sunojob.workflow import ReviewStore, WorkflowError
from test_email_delivery import FakeMailer
from test_voice_workflow import CASE


class ReceiptPresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ReviewStore(Path(self.temp.name) / "reviews.sqlite3")
        sources = [SourceTurn.model_validate(source) for source in CASE["sources"]]
        self.sid = self.store.create(sources, Extraction.model_validate(CASE["gold_extraction"]))["id"]
        rb = self.store.prepare_readback(self.sid, 1, "Offline readback")["readback"]
        self.store.ready_readback(self.sid, 1, rb["id"], "offline-audio")
        self.store.complete_readback(self.sid, 1, rb["id"])
        self.store.reply(self.sid, 1, rb["id"], "I confirm")
        token = self.store.issue_owner_review(self.sid, 1)["token"]
        self.store.owner_accept(self.sid, token, 1, "Demo Owner", True)
        self.receipt = self.store.receipt(self.sid)
        self.mailer = FakeMailer()
        self.delivery = DeliveryManager(self.store, self.mailer)

    def prepare(self):
        return self.delivery.prepare(self.sid, 1, "customer@example.com", "owner@example.com")

    def test_india_time_converts_the_instant_across_midnight(self):
        self.assertEqual(display_time("2026-11-07T19:00:00+00:00"), "08 Nov 2026 · 12:30:00 AM IST")
        self.assertEqual(display_time("2026-11-08T00:30:00+05:30"), "08 Nov 2026 · 12:30:00 AM IST")

    def test_naive_or_invalid_times_are_not_mislabeled_as_india_time(self):
        self.assertEqual(display_time("2026-11-07T19:00:00"), "Time unavailable")
        self.assertEqual(display_time("invalid"), "Time unavailable")

    def test_html_uses_local_times_and_readable_instructions(self):
        html = receipt_html(self.receipt).decode()
        self.assertNotIn("(UTC)", html)
        self.assertNotIn("+00:00", html)
        self.assertIn("India Standard Time", html)
        self.assertIn("Prepare lunch boxes", html)
        self.assertIn("40 lunch boxes", html)
        self.assertIn("Do not add onion", html)
        self.assertIn("Ask before changing the menu", html)
        self.assertIn("Conversation history", html)
        self.assertNotIn("<table", html)

    def test_every_instruction_source_and_correction_remains_in_html(self):
        html = receipt_html(self.receipt).decode()
        from html import escape
        for source in self.receipt["card"]["sources"]:
            self.assertIn(escape(source["text"], quote=True), html)
        for instruction in self.receipt["card"]["extraction"]["instructions"]:
            for evidence in instruction["evidence"]:
                self.assertIn(escape(evidence["quote"], quote=True), html)
        self.assertIn("50", html)
        self.assertIn("Net changes", html)
        self.assertIn("Card SHA-256", html)
        self.assertIn('<details class="record-details">', html)

    def test_rendering_is_deterministic_and_does_not_change_signed_record_data(self):
        before = deepcopy(self.receipt)
        data = receipt_json(self.receipt)
        self.assertEqual(receipt_html(self.receipt), receipt_html(self.receipt))
        self.assertEqual(self.receipt, before)
        self.assertEqual(receipt_json(self.receipt), data)
        self.assertEqual(receipt_json(self.store.receipt(self.sid)), data)

    def test_old_prepared_preview_is_rejected_before_any_submission(self):
        job = self.prepare()
        job.pop("html_presentation_version")
        with self.store.connect() as db:
            db.execute("UPDATE review_mail_jobs SET body=? WHERE id=?", (json.dumps(job), job["id"]))
        with self.assertRaisesRegex(WorkflowError, "layout changed"):
            self.delivery.send(self.sid, job["id"], True)
        self.assertEqual(self.mailer.calls, [])
        self.assertEqual(self.delivery.get(self.sid, job["id"])["state"], "prepared")
        self.assertIsNone(self.store.get(self.sid).get("delivery_in_progress"))

    def test_changed_attachment_bytes_invalidate_preview_before_submission(self):
        job = self.prepare()
        self.assertEqual(job["html_presentation_version"], HTML_PRESENTATION_VERSION)
        with patch("sunojob.delivery.receipt_html", return_value=b"changed-after-preview"):
            with self.assertRaisesRegex(WorkflowError, "layout changed"):
                self.delivery.send(self.sid, job["id"], True)
        self.assertEqual(self.mailer.calls, [])

    def test_accepted_old_job_remains_idempotent_after_presentation_upgrade(self):
        job = self.prepare()
        sent = self.delivery.send(self.sid, job["id"], True)
        sent.pop("html_presentation_version")
        with self.store.connect() as db:
            db.execute("UPDATE review_mail_jobs SET body=? WHERE id=?", (json.dumps(sent), sent["id"]))
        self.assertEqual(self.delivery.send(self.sid, job["id"], True)["state"], "complete")
        fresh = self.prepare()
        self.delivery.send(self.sid, fresh["id"], True)
        self.assertEqual(len(self.mailer.calls), 2)
