"""Independent checks of invalidation, refresh, archives and delivery recovery."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from sunojob.checkpoint import audit_database
from sunojob.delivery import DeliveryManager
from sunojob.models import Extraction, SourceTurn
from sunojob.receipt import receipt_json
from sunojob.webapp import create_app
from sunojob.workflow import ReviewStore, WorkflowError
from test_email_delivery import FakeMailer
from test_voice_workflow import CASE, FakeServices


class InvalidationAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ReviewStore(Path(self.temp.name) / "reviews.sqlite3")
        self.sources = [SourceTurn.model_validate(source) for source in CASE["sources"]]
        self.services = FakeServices()
        self.mailer = FakeMailer()
        self.app = create_app(self.store, self.services, self.mailer)
        self.client = TestClient(self.app)
        self.headers = {"x-sunojob-token": self.app.state.token}
        self.sid = self.store.create(self.sources, Extraction.model_validate(CASE["gold_extraction"]))["id"]
        self.delivery = self.app.state.delivery

    def both(self):
        rb = self.store.prepare_readback(self.sid, 1, "Offline readback")["readback"]
        self.store.ready_readback(self.sid, 1, rb["id"], "offline-audio")
        self.store.complete_readback(self.sid, 1, rb["id"])
        self.store.reply(self.sid, 1, rb["id"], "I confirm")
        self.owner_token = self.store.issue_owner_review(self.sid, 1)["token"]
        return self.store.owner_accept(self.sid, self.owner_token, 1, "Demo Owner", True)

    def failed_correction(self):
        self.both()
        pending = self.store.start_change(self.sid, 1, "Make it 45 lunch boxes.")
        return self.store.fail_change(self.sid, pending["operation"])

    def prepare(self):
        return self.delivery.prepare(self.sid, 1, "customer@example.com", "owner@example.com")

    def test_repeated_refresh_requests_never_change_approvals_or_database(self):
        self.both()
        before = self.store.path.read_bytes()
        receipt_before = receipt_json(self.store.receipt(self.sid))
        for _ in range(10):
            for path in ("/api/status", "/api/sessions", f"/api/sessions/{self.sid}",
                         f"/api/sessions/{self.sid}/receipts", f"/api/sessions/{self.sid}/email-jobs"):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(receipt_json(self.store.receipt(self.sid)), receipt_before)
        self.assertEqual(self.store.get(self.sid)["state"], "both_confirmed")
        self.assertEqual(self.mailer.calls, [])

    def test_valid_failed_correction_is_not_reported_as_corruption(self):
        self.failed_correction()
        report = audit_database(self.store.path)
        item = report["sessions"][0]
        self.assertEqual(report["issues"], [])
        self.assertTrue(item["pending_correction"])
        self.assertTrue(item["saved_approval_snapshot_verified"])
        self.assertFalse(item["both_approvals_match"])
        self.assertFalse(item["receipt_verified"])
        self.assertEqual(item["last_action"], "correction_failed")

    def test_pending_correction_cannot_reuse_either_approval_or_send_email(self):
        self.failed_correction()
        with self.assertRaises(WorkflowError):
            self.prepare()
        with self.assertRaises(WorkflowError):
            self.store.owner_accept(self.sid, self.owner_token, 1, "Owner", True)
        self.assertEqual(self.client.get(f"/api/sessions/{self.sid}/receipt?version=1").status_code, 409)
        self.assertEqual(self.mailer.calls, [])

    def test_archived_receipt_remains_available_without_reapproving_pending_correction(self):
        self.failed_correction()
        before = self.store.path.read_bytes()
        history = self.client.get(f"/api/sessions/{self.sid}/receipts")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()[0]["version"], 1)
        self.assertFalse(history.json()[0]["is_current_approval"])
        html = self.client.get(f"/api/sessions/{self.sid}/receipts/1?kind=html")
        data = self.client.get(f"/api/sessions/{self.sid}/receipts/1?kind=json")
        self.assertEqual(html.status_code, 200)
        self.assertIn("Archived approval snapshot", html.text)
        self.assertIn("does not approve a current", html.text)
        self.assertIn("Archived-", html.headers["Content-Disposition"])
        self.assertEqual(data.content, receipt_json(self.store.receipt(self.sid, version=1)))
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertIsNone(self.store.get(self.sid)["customer_confirmation"])

    def test_archive_unavailable_before_any_owner_approval(self):
        self.assertEqual(self.client.get(f"/api/sessions/{self.sid}/receipts").json(), [])
        self.assertEqual(self.client.get(f"/api/sessions/{self.sid}/receipts/1").status_code, 409)

    def test_archive_current_flag_requires_matching_live_approvals(self):
        self.both()
        self.assertTrue(self.store.receipt_history(self.sid)[0]["is_current_approval"])
        self.store.start_change(self.sid, 1, "Make it 45")
        self.assertFalse(self.store.receipt_history(self.sid)[0]["is_current_approval"])

    def test_archived_snapshot_survives_a_completed_new_version(self):
        self.both()
        text = "Make it 45 lunch boxes."
        pending = self.store.start_change(self.sid, 1, text)
        sources = self.sources + [SourceTurn(id="turn-2", text=text, language="en-IN")]
        extraction, _ = self.services.extract(sources)
        self.store.finish_change(self.sid, 1, pending["operation"], sources, extraction)
        snapshots = self.store.receipt_history(self.sid)
        self.assertEqual([row["version"] for row in snapshots], [1])
        self.assertFalse(snapshots[0]["is_current_approval"])
        self.assertEqual(self.client.get(f"/api/sessions/{self.sid}/receipts/1").status_code, 200)
        self.assertEqual(self.client.get(f"/api/sessions/{self.sid}/receipts/2").status_code, 409)

    def test_current_activity_is_metadata_only_and_not_persisted(self):
        self.failed_correction()
        before = self.store.path.read_bytes()
        body = self.client.get(f"/api/sessions/{self.sid}").json()
        self.assertEqual(set(body["last_activity"]), {"kind", "at"})
        self.assertEqual(body["last_activity"]["kind"], "correction_failed")
        self.assertNotIn("last_activity", self.store.get(self.sid))
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_corrupt_confirmation_still_fails_the_audit(self):
        self.both()
        with self.store.connect() as db:
            body = self.store.get(self.sid)
            body["owner_confirmation"]["sha256"] = "wrong"
            db.execute("UPDATE review_sessions SET body=? WHERE id=?", (json.dumps(body), self.sid))
        self.assertEqual(audit_database(self.store.path)["issues"], [self.sid[:8]])

    def test_message_construction_failure_releases_lock_without_submission(self):
        self.both()
        job = self.prepare()
        with patch("sunojob.delivery.submission_message", side_effect=ValueError("private-error-do-not-save")):
            result = self.delivery.send(self.sid, job["id"], True)
        self.assertEqual(result["state"], "complete_with_errors")
        self.assertEqual([target["status"] for target in result["targets"]], ["failed_before_submission"] * 2)
        self.assertNotIn("private-error", json.dumps(result))
        self.assertIsNone(self.store.get(self.sid).get("delivery_in_progress"))
        self.assertEqual(self.mailer.calls, [])
        self.store.start_change(self.sid, 1, "Make it 45")  # Request is usable without a restart.

    def test_second_recipient_construction_failure_preserves_first_acceptance(self):
        self.both()
        job = self.prepare()
        from sunojob.delivery import submission_message
        count = 0
        def compose(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise ValueError("test construction failure")
            return submission_message(*args)
        with patch("sunojob.delivery.submission_message", side_effect=compose):
            result = self.delivery.send(self.sid, job["id"], True)
        self.assertEqual([target["status"] for target in result["targets"]],
                         ["accepted_by_smtp", "failed_before_submission"])
        fresh = self.prepare()
        self.delivery.send(self.sid, fresh["id"], True)
        self.assertEqual(len(self.mailer.calls), 2)
        self.assertEqual(self.mailer.calls[-1][1], "owner@example.com")

    def test_parallel_repeat_send_does_not_duplicate_submission(self):
        self.both()
        job = self.prepare()
        started, release = threading.Event(), threading.Event()
        original = self.mailer.submit
        def held(message, recipient):
            if not started.is_set():
                started.set()
                if not release.wait(5):
                    raise RuntimeError("test wait timed out")
            return original(message, recipient)
        self.mailer.submit = held
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.delivery.send, self.sid, job["id"], True)
            try:
                self.assertTrue(started.wait(5))
                second = executor.submit(self.delivery.send, self.sid, job["id"], True).result(timeout=5)
                self.assertEqual(second["state"], "sending")
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5)["state"], "complete")
        self.assertEqual(len(self.mailer.calls), 2)

    def test_parallel_owner_acceptance_creates_exactly_one_receipt(self):
        rb = self.store.prepare_readback(self.sid, 1, "Offline readback")["readback"]
        self.store.ready_readback(self.sid, 1, rb["id"], "offline-audio")
        self.store.complete_readback(self.sid, 1, rb["id"])
        self.store.reply(self.sid, 1, rb["id"], "I confirm")
        token = self.store.issue_owner_review(self.sid, 1)["token"]
        def accept(name):
            try:
                self.store.owner_accept(self.sid, token, 1, name, True)
                return True
            except WorkflowError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(accept, ["Owner one", "Owner two"]))
        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(len(self.store.receipt_history(self.sid)), 1)

    def test_restored_draft_after_restart_keeps_archives_and_pending_correction(self):
        self.failed_correction()
        reopened = ReviewStore(self.store.path)
        reopened.recover_interrupted()
        self.assertEqual(reopened.get(self.sid)["state"], "needs_correction")
        self.assertEqual(reopened.get(self.sid)["pending_text"], "Make it 45 lunch boxes.")
        self.assertFalse(reopened.receipt_history(self.sid)[0]["is_current_approval"])
