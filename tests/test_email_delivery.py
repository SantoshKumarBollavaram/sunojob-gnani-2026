"""Offline submission tests. No real SMTP connection or email is made here."""

from copy import deepcopy
import json
from pathlib import Path
import smtplib
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from sunojob.delivery import DeliveryManager
from sunojob.mailer import MailConfig, SMTPMailer, submission_message
from sunojob.models import Extraction, SourceTurn
from sunojob.receipt import receipt_html, receipt_json
from sunojob.webapp import create_app
from sunojob.workflow import ReviewStore, WorkflowError
from test_voice_workflow import CASE, FakeServices


class FakeMailer:
    sender = "sender@example.com"
    def __init__(self):
        self.calls = []
        self.outcomes = []
        self.callback = None
    def submit(self, message, recipient):
        self.calls.append((message, recipient))
        if self.callback: self.callback()
        outcome = self.outcomes.pop(0) if self.outcomes else {"status": "accepted_by_smtp", "detail": "Offline test acceptance"}
        if isinstance(outcome, BaseException): raise outcome
        return outcome


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "reviews.sqlite3"
        self.store = ReviewStore(self.path)
        self.mailer = FakeMailer()
        self.manager = DeliveryManager(self.store, self.mailer)
        self.sources = [SourceTurn.model_validate(s) for s in CASE["sources"]]
        self.extraction = Extraction.model_validate(CASE["gold_extraction"])
        self.sid = self.store.create(self.sources, self.extraction)["id"]

    def both(self):
        rb = self.store.prepare_readback(self.sid, 1, "Offline readback")["readback"]
        self.store.ready_readback(self.sid, 1, rb["id"], "offline-audio")
        self.store.complete_readback(self.sid, 1, rb["id"])
        self.store.reply(self.sid, 1, rb["id"], "I confirm")
        token = self.store.issue_owner_review(self.sid, 1)["token"]
        self.store.owner_accept(self.sid, token, 1, "Demo Owner", True)

    def prepare(self):
        return self.manager.prepare(self.sid, 1, "customer@example.com", "owner@example.com")

    def ready(self):
        self.both(); return self.prepare()

    def test_prepare_requires_both_approvals_and_configured_transport(self):
        with self.assertRaises(WorkflowError): self.prepare()
        self.both()
        with self.assertRaises(WorkflowError): DeliveryManager(self.store).prepare(self.sid, 1, "customer@example.com", "owner@example.com")

    def test_preview_makes_no_network_calls_and_exposes_exact_recipients_and_digests(self):
        job = self.ready()
        self.assertEqual(self.mailer.calls, [])
        self.assertEqual(job["state"], "prepared")
        self.assertEqual([t["address"] for t in job["targets"]], ["customer@example.com", "owner@example.com"])
        self.assertEqual(len(job["attachments"]), 2)
        self.assertTrue(all(len(a["sha256"]) == 64 for a in job["attachments"]))

    def test_unchecked_confirmation_does_not_submit(self):
        job = self.ready()
        with self.assertRaises(WorkflowError): self.manager.send(self.sid, job["id"], False)
        self.assertEqual(self.mailer.calls, [])
        self.assertEqual(self.manager.get(self.sid, job["id"])["state"], "prepared")

    def test_one_submission_per_role_with_identical_receipt_attachments(self):
        job = self.ready()
        result = self.manager.send(self.sid, job["id"], True)
        self.assertEqual(result["state"], "complete")
        self.assertEqual(len(self.mailer.calls), 2)
        receipt = self.store.receipt(self.sid)
        for message, recipient in self.mailer.calls:
            self.assertEqual(str(message["To"]), recipient)
            self.assertIsNone(message["Bcc"])
            self.assertIsNone(message["X-Unsent"])
            self.assertIn("sender@example.com", message["From"])
            attachments = {p.get_filename(): p.get_payload(decode=True) for p in message.iter_attachments()}
            self.assertEqual(attachments["shared-record.html"], receipt_html(receipt))
            self.assertEqual(attachments["shared-record.json"], receipt_json(receipt))
        self.assertNotEqual(self.mailer.calls[0][0]["Message-ID"], self.mailer.calls[1][0]["Message-ID"])
        self.assertIsNone(self.store.get(self.sid).get("delivery_in_progress"))

    def test_repeat_same_job_returns_saved_outcome_without_resending(self):
        job = self.ready()
        first = self.manager.send(self.sid, job["id"], True)
        second = self.manager.send(self.sid, job["id"], True)
        self.assertEqual(first, second)
        self.assertEqual(len(self.mailer.calls), 2)

    def test_new_preview_does_not_resend_already_accepted_targets(self):
        job = self.ready(); self.manager.send(self.sid, job["id"], True)
        fresh = self.prepare()
        self.assertIn("not be automatically resent", fresh["targets"][0]["detail"])
        self.manager.send(self.sid, fresh["id"], True)
        self.assertEqual(len(self.mailer.calls), 2)

    def test_partial_failure_retries_only_failed_target_with_fresh_review(self):
        job = self.ready()
        self.mailer.outcomes = [{"status": "accepted_by_smtp", "detail": "test"}, {"status": "rejected", "detail": "test refusal"}]
        first = self.manager.send(self.sid, job["id"], True)
        self.assertEqual(first["state"], "complete_with_errors")
        self.manager.send(self.sid, job["id"], True)
        self.assertEqual(len(self.mailer.calls), 2)
        fresh = self.prepare(); self.manager.send(self.sid, fresh["id"], True)
        self.assertEqual(len(self.mailer.calls), 3)
        self.assertEqual(self.mailer.calls[-1][1], "owner@example.com")

    def test_unknown_outcome_is_not_retried_by_new_preview(self):
        job = self.ready()
        self.mailer.outcomes = [{"status": "unknown", "detail": "test uncertain"}]
        self.manager.send(self.sid, job["id"], True)
        fresh = self.prepare(); result = self.manager.send(self.sid, fresh["id"], True)
        self.assertEqual(result["targets"][0]["status"], "unknown")
        self.assertEqual(len(self.mailer.calls), 2)

    def test_expired_preview_rejected_without_submitting(self):
        job = self.ready()
        with patch("sunojob.delivery.now", return_value="9999-01-01T00:00:00+00:00"):
            with self.assertRaisesRegex(WorkflowError, "expired"): self.manager.send(self.sid, job["id"], True)
        self.assertEqual(self.mailer.calls, [])

    def test_sender_change_requires_new_preview(self):
        job = self.ready(); self.mailer.sender = "other@example.com"
        with self.assertRaisesRegex(WorkflowError, "Sender changed"): self.manager.send(self.sid, job["id"], True)
        self.assertEqual(self.mailer.calls, [])

    def test_card_change_invalidates_prepared_email(self):
        job = self.ready(); self.store.start_change(self.sid, 1, "Make it 45")
        with self.assertRaises(WorkflowError): self.manager.send(self.sid, job["id"], True)
        self.assertEqual(self.mailer.calls, [])

    def test_during_submission_correction_and_another_job_are_blocked(self):
        job = self.ready(); another = self.prepare()
        def callback():
            with self.assertRaisesRegex(WorkflowError, "still running"):
                self.store.start_change(self.sid, 1, "Make it 45")
            with self.assertRaisesRegex(WorkflowError, "still running"):
                self.manager.send(self.sid, another["id"], True)
            duplicate = self.manager.send(self.sid, job["id"], True)
            self.assertEqual(duplicate["state"], "sending")
        self.mailer.callback = callback
        result = self.manager.send(self.sid, job["id"], True)
        self.assertEqual(result["state"], "complete")
        self.assertEqual(len(self.mailer.calls), 2)

    def test_unexpected_error_is_uncertain_and_does_not_save_raw_secret(self):
        job = self.ready(); self.mailer.outcomes = [RuntimeError("password=do-not-store-this")]
        result = self.manager.send(self.sid, job["id"], True)
        self.assertEqual(result["targets"][0]["status"], "unknown")
        self.assertNotIn("do-not-store-this", json.dumps(self.manager.recent(self.sid)))

    def test_restart_marks_inflight_unknown_and_unstarted_not_attempted(self):
        job = self.ready(); self.mailer.outcomes = [KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt): self.manager.send(self.sid, job["id"], True)
        self.assertIsNotNone(self.store.get(self.sid)["delivery_in_progress"])
        reopened = DeliveryManager(ReviewStore(self.path), self.mailer)
        reopened.recover_interrupted()
        result = reopened.get(self.sid, job["id"])
        self.assertEqual([t["status"] for t in result["targets"]], ["unknown", "not_attempted"])
        self.assertIsNone(self.store.get(self.sid)["delivery_in_progress"])
        fresh = reopened.prepare(self.sid, 1, "customer@example.com", "owner@example.com")
        reopened.send(self.sid, fresh["id"], True)
        self.assertEqual(len(self.mailer.calls), 2)
        self.assertEqual(self.mailer.calls[-1][1], "owner@example.com")

    def test_known_outcomes_remain_saved_after_reopening(self):
        job = self.ready(); first = self.manager.send(self.sid, job["id"], True)
        self.assertEqual(first, DeliveryManager(ReviewStore(self.path), self.mailer).get(self.sid, job["id"]))

    def test_preview_identifier_cannot_be_used_for_another_session(self):
        job = self.ready(); other = self.store.create(self.sources, self.extraction)
        with self.assertRaises(WorkflowError): self.manager.send(other["id"], job["id"], True)
        self.assertEqual(self.mailer.calls, [])

    def test_http_preview_then_explicit_send_and_refresh(self):
        self.both()
        app = create_app(self.store, FakeServices(), self.mailer)
        client = TestClient(app); headers = {"x-sunojob-token": app.state.token}
        preview = client.post(f"/api/sessions/{self.sid}/email-preview", headers=headers,
                              json={"version": 1, "customer_email": "customer@example.com", "owner_email": "owner@example.com"})
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(self.mailer.calls, [])
        job = preview.json()
        self.assertEqual(client.post(f"/api/sessions/{self.sid}/send-emails", json={"preview_id": job["id"], "reviewed_recipients": True}).status_code, 403)
        sent = client.post(f"/api/sessions/{self.sid}/send-emails", headers=headers,
                           json={"preview_id": job["id"], "reviewed_recipients": True})
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["state"], "complete")
        self.assertEqual(client.get(f"/api/sessions/{self.sid}/email-jobs").json()[0]["state"], "complete")

    def test_status_reports_configuration_without_claiming_delivery(self):
        client = TestClient(create_app(self.store, FakeServices(), self.mailer))
        status = client.get("/api/status").json()
        self.assertEqual(status["email_delivery"], "smtp_configured")
        self.assertEqual(status["email_sender"], "sender@example.com")
        self.assertNotIn("password", json.dumps(status))

    def test_missing_recipients_name_both_fields_without_submission(self):
        self.both()
        app = create_app(self.store, FakeServices(), self.mailer)
        client = TestClient(app)
        for route in ("email-preview", "email-drafts"):
            for values in ({"customer_email": "", "owner_email": ""}, {}):
                response = client.post(f"/api/sessions/{self.sid}/{route}",
                                       headers={"x-sunojob-token": app.state.token},
                                       json={"version": 1, **values})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"], "Customer email is required. Owner email is required.")
        self.assertEqual(self.manager.recent(self.sid), [])
        self.assertEqual(self.mailer.calls, [])

    def test_bad_recipient_names_field_and_does_not_echo_input(self):
        self.both()
        app = create_app(self.store, FakeServices(), self.mailer)
        client = TestClient(app)
        for field in ("customer_email", "owner_email"):
            values = {"version": 1, "customer_email": "customer@example.com", "owner_email": "owner@example.com"}
            values[field] = "private-invalid-value"
            response = client.post(f"/api/sessions/{self.sid}/email-preview",
                                   headers={"x-sunojob-token": app.state.token}, json=values)
            self.assertEqual(response.status_code, 422)
            self.assertIn(field.replace("_", " ").capitalize(), response.json()["detail"])
            self.assertNotIn("private-invalid-value", response.text)
        self.assertEqual(self.manager.recent(self.sid), [])
        self.assertEqual(self.mailer.calls, [])

    def test_trimmed_recipients_produce_preview_without_sending(self):
        self.both()
        app = create_app(self.store, FakeServices(), self.mailer)
        response = TestClient(app).post(f"/api/sessions/{self.sid}/email-preview",
                                       headers={"x-sunojob-token": app.state.token},
                                       json={"version": 1, "customer_email": " customer@example.com ",
                                             "owner_email": " owner@example.com "})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([target["address"] for target in response.json()["targets"]],
                         ["customer@example.com", "owner@example.com"])
        self.assertEqual(self.mailer.calls, [])

    def test_invalid_version_is_actionable_without_echoing_input(self):
        app = create_app(self.store, FakeServices(), self.mailer)
        response = TestClient(app).post(f"/api/sessions/{self.sid}/email-preview",
                                       headers={"x-sunojob-token": app.state.token},
                                       json={"version": "private-invalid-value", "customer_email": "customer@example.com",
                                             "owner_email": "owner@example.com"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("Card version", response.json()["detail"])
        self.assertNotIn("private-invalid-value", response.text)


class SMTPTransportTests(unittest.TestCase):
    def setUp(self):
        self.config = MailConfig("smtp.example.com", 465, "ssl", "sender@example.com", "sender@example.com", "hidden-test-secret")
        self.connection = Mock(); self.connection.send_message.return_value = {}
        self.message = Mock()

    def submit(self, **kwargs):
        for name, value in kwargs.items(): getattr(self.connection, name).side_effect = value
        with patch("sunojob.mailer.smtplib.SMTP_SSL", return_value=self.connection) as factory:
            result = SMTPMailer(self.config).submit(self.message, "owner@example.com")
            return result, factory

    def test_ssl_validates_certificates_and_limits_envelope_to_one_recipient(self):
        result, factory = self.submit()
        self.assertEqual(result["status"], "accepted_by_smtp")
        context = factory.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.connection.send_message.assert_called_once_with(self.message, from_addr="sender@example.com", to_addrs=["owner@example.com"])

    def test_starttls_happens_before_authentication(self):
        config = MailConfig("smtp.example.com", 587, "starttls", "sender@example.com", "sender@example.com", "secret")
        with patch("sunojob.mailer.smtplib.SMTP", return_value=self.connection):
            result = SMTPMailer(config).submit(self.message, "owner@example.com")
        self.assertEqual(result["status"], "accepted_by_smtp")
        names = [call[0] for call in self.connection.method_calls]
        self.assertLess(names.index("starttls"), names.index("login"))

    def test_tls_failure_prevents_login_or_submission(self):
        config = MailConfig("smtp.example.com", 587, "starttls", "sender@example.com", "sender@example.com", "secret")
        self.connection.starttls.side_effect = smtplib.SMTPNotSupportedError("TLS missing")
        with patch("sunojob.mailer.smtplib.SMTP", return_value=self.connection):
            result = SMTPMailer(config).submit(self.message, "owner@example.com")
        self.assertEqual(result["status"], "failed_before_submission")
        self.connection.login.assert_not_called(); self.connection.send_message.assert_not_called()

    def test_authentication_error_is_known_failure_and_secret_is_not_exposed(self):
        result, _ = self.submit(login=smtplib.SMTPAuthenticationError(535, b"hidden-test-secret"))
        self.assertEqual(result["status"], "failed_before_submission")
        self.assertNotIn("hidden-test-secret", str(result))
        self.connection.send_message.assert_not_called()

    def test_explicit_data_rejection_is_not_acceptance(self):
        result, _ = self.submit(send_message=smtplib.SMTPDataError(451, b"test refusal"))
        self.assertEqual(result["status"], "rejected")

    def test_disconnect_during_submission_is_unknown(self):
        result, _ = self.submit(send_message=smtplib.SMTPServerDisconnected("lost reply"))
        self.assertEqual(result["status"], "unknown")

    def test_connection_failure_precedes_submission(self):
        with patch("sunojob.mailer.smtplib.SMTP_SSL", side_effect=OSError("network blocked")):
            result = SMTPMailer(self.config).submit(self.message, "owner@example.com")
        self.assertEqual(result["status"], "failed_before_submission")

    def test_quit_and_close_errors_cannot_erase_known_acceptance(self):
        result, _ = self.submit(quit=smtplib.SMTPServerDisconnected("quit failed"), close=OSError("close failed"))
        self.assertEqual(result["status"], "accepted_by_smtp")

    def test_plaintext_and_header_injection_configuration_rejected(self):
        for mode, sender in [("plain", "sender@example.com"), ("ssl", "sender@example.com\nBcc: other@example.com")]:
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError): MailConfig("smtp.example.com", 465, mode, sender, "username", "secret")
        self.assertNotIn("hidden-test-secret", repr(self.config))


if __name__ == "__main__": unittest.main()
