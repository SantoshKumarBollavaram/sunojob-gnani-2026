"""Version boundaries, separate acceptance, portable exports and upgrade safety."""

from copy import deepcopy
from email.parser import BytesParser
from email.policy import default
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient

from sunojob.models import Extraction, SourceTurn
from sunojob.receipt import email_drafts, receipt_html, receipt_json, verify_receipt
from sunojob.webapp import create_app
from sunojob.workflow import ReviewStore, WorkflowError
from test_voice_workflow import CASE, FakeServices


class OwnerReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "review.sqlite3"
        self.store = ReviewStore(self.path)
        self.services = FakeServices()
        self.app = create_app(self.store, self.services)
        self.client = TestClient(self.app)
        self.csrf = {"x-sunojob-token": self.app.state.token}
        self.sources = [SourceTurn.model_validate(s) for s in CASE["sources"]]
        self.extraction = Extraction.model_validate(CASE["gold_extraction"])
        self.initial = self.store.create(self.sources, self.extraction)
        self.sid = self.initial["id"]

    def confirm(self, version=1):
        rb = self.store.prepare_readback(self.sid, version, "Offline readback")["readback"]
        self.store.ready_readback(self.sid, version, rb["id"], "offline-test-audio")
        self.store.complete_readback(self.sid, version, rb["id"])
        return self.store.reply(self.sid, version, rb["id"], "I confirm")

    def invite(self):
        self.confirm()
        return self.store.issue_owner_review(self.sid, 1)["token"]

    def both(self, name="Demo Owner"):
        token = self.invite()
        body = self.store.owner_accept(self.sid, token, 1, name, True)
        return token, body

    def revise(self):
        text = "Make it 45 lunch boxes."
        pending = self.store.start_change(self.sid, 1, text)
        sources = self.sources + [SourceTurn(id="turn-2", text=text, language="en-IN")]
        extraction, _ = self.services.extract(sources)
        return self.store.finish_change(self.sid, 1, pending["operation"], sources, extraction)

    def test_owner_review_requires_customer_confirmation(self):
        with self.assertRaises(WorkflowError):
            self.store.issue_owner_review(self.sid, 1)

    def test_owner_token_is_not_stored_in_plaintext_or_owner_response(self):
        token = self.invite()
        body = self.store.get(self.sid)
        self.assertNotIn(token, json.dumps(body))
        self.assertIn("token_sha256", body["owner_review"])
        public = self.store.owner_view(self.sid, token)
        self.assertNotIn("owner_review", public)

    def test_rotating_link_revokes_previous_link(self):
        old = self.invite()
        new = self.store.issue_owner_review(self.sid, 1)["token"]
        with self.assertRaises(WorkflowError): self.store.owner_view(self.sid, old)
        self.assertEqual(self.store.owner_view(self.sid, new)["version"], 1)

    def test_expired_link_cannot_accept(self):
        token = self.invite()
        with patch("sunojob.workflow.now", return_value="9999-01-01T00:00:00+00:00"):
            with self.assertRaisesRegex(WorkflowError, "expired"):
                self.store.owner_accept(self.sid, token, 1, "Owner", True)

    def test_owner_token_cannot_read_another_session(self):
        token = self.invite()
        other = self.store.create(self.sources, self.extraction)
        with self.assertRaises(WorkflowError): self.store.owner_view(other["id"], token)

    def test_checkbox_is_required_and_name_cannot_inject_headers(self):
        token = self.invite()
        for name, reviewed in [("Owner", False), (" ", True), ("Owner\nBcc: other@example.com", True)]:
            with self.subTest(name=name):
                with self.assertRaises(WorkflowError):
                    self.store.owner_accept(self.sid, token, 1, name, reviewed)

    def test_both_approvals_reference_same_card_and_create_one_receipt(self):
        _, body = self.both()
        self.assertEqual(body["state"], "both_confirmed")
        receipt = self.store.receipt(self.sid)
        for role in ("customer_confirmation", "owner_confirmation"):
            self.assertEqual(receipt[role]["sha256"], receipt["card_sha256"])
            self.assertEqual(receipt[role]["version"], receipt["version"])
            self.assertFalse(receipt[role]["identity_verified"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM review_receipts").fetchone()[0], 1)

    def test_duplicate_acceptance_cannot_mint_another_receipt(self):
        token, _ = self.both()
        before = receipt_json(self.store.receipt(self.sid))
        with self.assertRaises(WorkflowError):
            self.store.owner_accept(self.sid, token, 1, "Another Owner", True)
        self.assertEqual(before, receipt_json(self.store.receipt(self.sid)))

    def test_receipt_is_stable_across_restart(self):
        self.both()
        before = receipt_json(self.store.receipt(self.sid))
        self.assertEqual(before, receipt_json(ReviewStore(self.path).receipt(self.sid)))

    def test_correction_invalidates_both_approvals_and_owner_link(self):
        token, _ = self.both()
        old = receipt_json(self.store.receipt(self.sid))
        new = self.revise()
        self.assertEqual(new["version"], 2)
        self.assertIsNone(new["customer_confirmation"])
        self.assertIsNone(new["owner_confirmation"])
        with self.assertRaises(WorkflowError): self.store.owner_view(self.sid, token)
        with self.assertRaises(WorkflowError): self.store.receipt(self.sid)
        self.assertEqual(old, receipt_json(self.store.receipt(self.sid, version=1)))

    def test_new_version_needs_customer_then_owner_again(self):
        self.both(); self.revise()
        self.confirm(version=2)
        with self.assertRaises(WorkflowError): self.store.receipt(self.sid)
        new_token = self.store.issue_owner_review(self.sid, 2)["token"]
        self.store.owner_accept(self.sid, new_token, 2, "Owner", True)
        self.assertEqual(self.store.receipt(self.sid)["version"], 2)

    def test_pending_correction_blocks_current_receipt_immediately(self):
        self.both()
        pending = self.store.start_change(self.sid, 1, "Make it 45")
        with self.assertRaises(WorkflowError): self.store.receipt(self.sid)
        self.store.fail_change(self.sid, pending["operation"])
        with self.assertRaises(WorkflowError): self.store.receipt(self.sid)

    def test_owner_request_is_not_silently_applied_as_customer_instruction(self):
        token = self.invite()
        before = self.store.get(self.sid)["card"]
        body = self.store.owner_request_change(self.sid, token, 1, "Can we use 45 boxes?")
        self.assertEqual(body["state"], "owner_changes_requested")
        self.assertEqual(body["card"], before)
        self.assertIsNone(body["owner_confirmation"])
        with self.assertRaises(WorkflowError): self.store.receipt(self.sid)
        with self.assertRaises(WorkflowError): self.store.owner_accept(self.sid, token, 1, "Owner", True)
        with self.assertRaises(WorkflowError): self.store.prepare_readback(self.sid, 1, "Old card")
        self.assertEqual(self.revise()["version"], 2)

    def test_html_escapes_untrusted_names(self):
        self.both(name='<img src=x onerror="alert(1)">')
        html = receipt_html(self.store.receipt(self.sid)).decode()
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;img', html)
        self.assertIn("Do not add onion", html)
        self.assertIn("Ask me before changing", html)

    def test_modified_receipt_detected(self):
        self.both()
        receipt = deepcopy(self.store.receipt(self.sid))
        receipt["owner_confirmation"]["name"] = "Different person"
        with self.assertRaises(WorkflowError): verify_receipt(receipt)

    def test_two_emails_have_identical_attachments_and_are_unsent(self):
        self.both()
        receipt = self.store.receipt(self.sid)
        data = email_drafts(receipt, "customer@example.com", "owner@example.com")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for role, recipient in [("customer", "customer@example.com"), ("owner", "owner@example.com")]:
                msg = BytesParser(policy=default).parsebytes(archive.read(role + "-draft.eml"))
                self.assertEqual(str(msg["To"]), recipient)
                self.assertEqual(msg["X-Unsent"], "1")
                self.assertIsNone(msg["From"])
                attachments = {part.get_filename(): part.get_payload(decode=True) for part in msg.iter_attachments()}
                self.assertEqual(attachments["shared-record.html"], receipt_html(receipt))
                self.assertEqual(attachments["shared-record.json"], receipt_json(receipt))

    def test_email_injection_and_invalid_addresses_rejected(self):
        self.both()
        for value in ["a@example.com\r\nBcc: other@example.com", "Name <a@example.com>", "a@@example.com", "a@example..com"]:
            with self.subTest(address=value):
                with self.assertRaises(ValueError): email_drafts(self.store.receipt(self.sid), value, "owner@example.com")

    def test_upgrade_reads_old_body_without_owner_fields(self):
        with self.store.connect() as db:
            body = self.store.get(self.sid)
            body.pop("owner_review", None); body.pop("owner_change_request", None)
            db.execute("UPDATE review_sessions SET body=? WHERE id=?", (json.dumps(body), self.sid))
        reopened = ReviewStore(self.path)
        self.assertIsNone(reopened.get(self.sid)["owner_review"])
        self.assertEqual(reopened.get(self.sid)["card"], self.initial["card"])

    def test_owner_http_requires_scoped_token_and_csrf(self):
        token = self.invite()
        path = f"/api/owner/{self.sid}"
        self.assertEqual(self.client.get(path).status_code, 409)
        self.assertEqual(self.client.get(path, headers={"x-owner-token": token}).status_code, 200)
        data = {"version": 1, "name": "Owner", "reviewed": True}
        self.assertEqual(self.client.post(path + "/accept", json=data, headers={"x-owner-token": token}).status_code, 403)
        self.assertEqual(self.client.post(path + "/accept", json=data, headers=self.csrf).status_code, 409)

    def test_http_owner_acceptance_and_email_download_complete(self):
        self.confirm()
        invitation = self.client.post(f"/api/sessions/{self.sid}/owner-link", headers=self.csrf,
                                      json={"version": 1}).json()
        token = invitation["path"].split("#")[1]
        accepted = self.client.post(f"/api/owner/{self.sid}/accept", headers={**self.csrf, "x-owner-token": token},
                                   json={"version": 1, "name": "Demo Owner", "reviewed": True})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["state"], "both_confirmed")
        response = self.client.post(f"/api/sessions/{self.sid}/email-drafts", headers=self.csrf,
                                   json={"version": 1, "customer_email": "customer@example.com", "owner_email": "owner@example.com"})
        self.assertEqual(response.status_code, 200, response.text[:100])
        self.assertEqual(response.headers["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIn("owner-draft.eml", archive.namelist())
            self.assertIn("customer-draft.eml", archive.namelist())

    def test_customer_and_owner_download_exact_same_bytes(self):
        token, _ = self.both()
        for kind in ["html", "json"]:
            customer = self.client.get(f"/api/sessions/{self.sid}/receipt?version=1&kind={kind}")
            owner = self.client.get(f"/api/owner/{self.sid}/receipt?version=1&kind={kind}", headers={"x-owner-token": token})
            self.assertEqual(customer.status_code, 200, customer.text)
            self.assertEqual(owner.status_code, 200, owner.text)
            self.assertEqual(customer.content, owner.content)
            self.assertIn("attachment", customer.headers["Content-Disposition"])

    def test_receipt_routes_do_not_export_before_both_approve(self):
        token = self.invite()
        self.assertEqual(self.client.get(f"/api/sessions/{self.sid}/receipt?version=1").status_code, 409)
        self.assertEqual(self.client.get(f"/api/owner/{self.sid}/receipt?version=1", headers={"x-owner-token": token}).status_code, 409)
        self.assertEqual(self.client.post(f"/api/sessions/{self.sid}/email-drafts", headers=self.csrf,
                         json={"version": 1, "customer_email": "customer@example.com", "owner_email": "owner@example.com"}).status_code, 409)

    def test_stale_download_version_and_email_draft_version_rejected(self):
        self.both()
        self.assertEqual(self.client.get(f"/api/sessions/{self.sid}/receipt?version=2").status_code, 409)
        self.assertEqual(self.client.post(f"/api/sessions/{self.sid}/email-drafts", headers=self.csrf,
                         json={"version": 2, "customer_email": "customer@example.com", "owner_email": "owner@example.com"}).status_code, 409)

    def test_owner_link_only_uses_fragment_and_not_query_parameter(self):
        self.confirm()
        response = self.client.post(f"/api/sessions/{self.sid}/owner-link", headers=self.csrf, json={"version": 1})
        path = response.json()["path"]
        self.assertIn("#", path)
        self.assertNotIn("?", path)
        page = self.client.get(path.split("#")[0])
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(path.split("#")[1], page.text)
        self.assertEqual(page.headers["Referrer-Policy"], "no-referrer")

    def test_static_dom_ids_used_by_each_controller_exist(self):
        root = Path(__file__).resolve().parents[1] / "sunojob/static"
        class IDs(HTMLParser):
            def __init__(self): super().__init__(); self.ids = []
            def handle_starttag(self, tag, attrs):
                for key, value in attrs:
                    if key == "id": self.ids.append(value)
        for html, js in [("index.html", "app.js"), ("owner.html", "owner.js")]:
            parser = IDs(); parser.feed((root / html).read_text())
            self.assertEqual(len(parser.ids), len(set(parser.ids)))
            used = re.findall(r"\$\('([^']+)'\)", (root / js).read_text())
            self.assertTrue(set(used).issubset(set(parser.ids)), set(used) - set(parser.ids))


if __name__ == "__main__": unittest.main()
