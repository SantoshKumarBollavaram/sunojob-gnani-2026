"""Completion evidence and recording scores. All service calls are offline doubles."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from sunojob.checkpoint import audit_database
from sunojob.delivery import DeliveryManager
from sunojob.models import Extraction, SourceTurn
from sunojob.recording_eval import fixture_labels, run_recording, summarize, tokens, word_errors
from sunojob.workflow import ReviewStore
from test_email_delivery import FakeMailer
from test_voice_workflow import CASE, FakeServices


class CompletionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "reviews.sqlite3"
        self.store = ReviewStore(self.path)
        self.sources = [SourceTurn.model_validate(source) for source in CASE["sources"]]
        self.sid = self.store.create(self.sources, Extraction.model_validate(CASE["gold_extraction"]))["id"]

    def approve(self):
        rb = self.store.prepare_readback(self.sid, 1, "Test readback")["readback"]
        self.store.ready_readback(self.sid, 1, rb["id"], "test-audio")
        self.store.complete_readback(self.sid, 1, rb["id"])
        self.store.reply(self.sid, 1, rb["id"], "I confirm")
        token = self.store.issue_owner_review(self.sid, 1)["token"]
        self.store.owner_accept(self.sid, token, 1, "Private Display Name", True)

    def test_missing_database_is_not_created(self):
        absent = self.path.parent / "absent.sqlite3"
        self.assertFalse(audit_database(absent)["database_present"])
        self.assertFalse(absent.exists())

    def test_audit_leaves_database_bytes_unchanged_and_drafts_pending(self):
        before = self.path.read_bytes()
        report = audit_database(self.path)
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(report["sessions"][0]["both_approvals_match"])
        self.assertFalse(report["sessions"][0]["receipt_verified"])

    def test_both_approvals_do_not_claim_smtp_or_inbox_delivery(self):
        self.approve()
        item = audit_database(self.path)["sessions"][0]
        self.assertTrue(item["both_approvals_match"])
        self.assertTrue(item["receipt_verified"])
        self.assertFalse(item["both_copies_accepted_by_smtp"])
        self.assertEqual(item["inbox_delivery"], "not_verified")
        self.assertNotIn("Private Display Name", json.dumps(item))

    def test_saved_smtp_acceptance_still_does_not_verify_inboxes(self):
        self.approve()
        manager = DeliveryManager(self.store, FakeMailer())
        job = manager.prepare(self.sid, 1, "customer@example.com", "owner@example.com")
        self.assertFalse(audit_database(self.path)["sessions"][0]["both_copies_accepted_by_smtp"])
        manager.send(self.sid, job["id"], True)
        report = audit_database(self.path)
        item = report["sessions"][0]
        self.assertTrue(item["both_copies_accepted_by_smtp"])
        self.assertEqual(item["inbox_delivery"], "not_verified")
        self.assertNotIn("customer@example.com", json.dumps(report))

    def test_correction_does_not_reuse_old_approval_receipt_or_mail(self):
        self.approve()
        self.store.start_change(self.sid, 1, "Make it 45")
        item = audit_database(self.path)["sessions"][0]
        self.assertFalse(item["both_approvals_match"])
        self.assertFalse(item["receipt_verified"])

    def test_tampered_card_marks_record_as_unusable(self):
        with self.store.connect() as db:
            body = json.loads(db.execute("SELECT body FROM review_sessions WHERE id=?", (self.sid,)).fetchone()[0])
            body["card"]["extraction"]["instructions"][0]["value"] = "tampered"
            db.execute("UPDATE review_sessions SET body=? WHERE id=?", (json.dumps(body), self.sid))
        report = audit_database(self.path)
        self.assertEqual(report["issues"], [self.sid[:8]])
        self.assertFalse(report["sessions"][0]["receipt_verified"])


class RecordingServices(FakeServices):
    def __init__(self, transcript):
        super().__init__()
        self.transcript = transcript
        self.received_sources = None
        self.fail_transcription = False

    def transcribe(self, audio, language):
        self.asr_calls += 1
        if self.fail_transcription:
            raise RuntimeError("secret-key-should-never-appear")
        return self.transcript, {"unused_metadata": "private-test"}

    def extract(self, sources):
        self.received_sources = deepcopy(sources)
        if self.fail_extract:
            raise RuntimeError("secret-key-should-never-appear")
        data = deepcopy(CASE["gold_extraction"])
        for instruction in data["instructions"]:
            instruction["evidence"] = [{"turn_id": "turn-1", "quote": sources[0].text}]
        for correction in data["corrections"]:
            correction["evidence"] = [{"turn_id": "turn-1", "quote": sources[0].text}]
        return Extraction.model_validate(data), {}


class RecordingEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.audio = self.folder / "speech.webm"
        self.audio.write_bytes(b"offline-audio; FakeServices avoids an actual provider call")
        self.labels = fixture_labels("catering_en_correction").model_dump()

    def run_one(self, service):
        return run_recording(self.labels, self.audio, service, self.folder)

    def test_different_asr_wording_is_validated_against_actual_transcript(self):
        transcript = "Prepare 50 actually 40 lunch boxes. Do not add onion. Ask before menu changes."
        service = RecordingServices(transcript)
        result, path = self.run_one(service)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["scoring"]["totals"]["strict_case_passes"], 1)
        self.assertEqual(result["scoring"]["totals"]["restrictions_kept"], 2)
        self.assertEqual(service.received_sources[0].text, transcript)
        self.assertNotEqual(service.received_sources[0].text, self.labels["reference_text"])
        self.assertEqual(json.loads(path.read_text())["attempt_id"], result["attempt_id"])

    def test_transcription_failure_stays_in_denominator_and_redacts_error(self):
        service = RecordingServices("unused")
        service.fail_transcription = True
        result, path = self.run_one(service)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stage"], "transcription")
        self.assertEqual(result["scoring"]["totals"]["instructions_expected"], 4)
        self.assertEqual(result["scoring"]["totals"]["instructions_matched"], 0)
        self.assertNotIn("secret-key", path.read_text())
        self.assertIsNone(service.received_sources)

    def test_extraction_failure_retains_transcription_and_expected_restrictions(self):
        service = RecordingServices(self.labels["reference_text"])
        service.fail_extract = True
        result, path = self.run_one(service)
        self.assertEqual(result["stage"], "extraction")
        self.assertEqual(result["transcription_score"]["word_error_rate"], 0)
        self.assertEqual(result["scoring"]["totals"]["restrictions_expected"], 2)
        self.assertNotIn("secret-key", path.read_text())

    def test_summary_counts_failure_and_repeat_recording_separately(self):
        self.run_one(RecordingServices(self.labels["reference_text"]))
        service = RecordingServices("unused")
        service.fail_transcription = True
        self.run_one(service)
        report = summarize(self.folder)
        self.assertEqual(report["totals"]["attempts"], 2)
        self.assertEqual(report["distinct_input_recordings"], 1)
        self.assertEqual(report["totals"]["failed_pipelines"], 1)
        self.assertEqual(report["totals"]["instructions_expected"], 8)
        self.assertEqual(report["totals"]["instructions_matched"], 4)
        self.assertTrue(any("offline_test_double" in group for group in report["attempt_groups"]))

    def test_summary_recomputes_scores_instead_of_trusting_saved_totals(self):
        result, path = self.run_one(RecordingServices(self.labels["reference_text"]))
        result["scoring"]["totals"]["instructions_matched"] = 9000
        path.write_text(json.dumps(result))
        self.assertEqual(summarize(self.folder)["totals"]["instructions_matched"], 4)

    def test_duplicate_attempt_files_are_rejected(self):
        result, path = self.run_one(RecordingServices(self.labels["reference_text"]))
        (self.folder / "attempt-copy.json").write_text(path.read_text())
        with self.assertRaisesRegex(ValueError, "Duplicate attempt"):
            summarize(self.folder)

    def test_invalid_labels_prevent_all_service_calls(self):
        self.labels["collection"] = "unsubstantiated-benchmark"
        service = RecordingServices("unused")
        with self.assertRaises(ValueError):
            self.run_one(service)
        self.assertEqual(service.asr_calls, 0)

    def test_duplicate_label_slots_are_rejected(self):
        self.labels["expected_instructions"].append(deepcopy(self.labels["expected_instructions"][0]))
        with self.assertRaises(ValueError):
            self.run_one(RecordingServices("unused"))

    def test_word_errors_preserve_telugu_combining_marks(self):
        self.assertEqual(tokens("ఉల్లిపాయ వేయవద్దు."), ["ఉల్లిపాయ", "వేయవద్దు"])
        self.assertEqual(word_errors("ఉల్లిపాయ వేయవద్దు.", "ఉల్లిపాయ వేయవద్దు")["word_error_rate"], 0)
        self.assertEqual(word_errors("Do not add onion", "Do add onion")["word_edit_errors"], 1)
        self.assertIsNone(word_errors("", "word")["word_error_rate"])

    def test_multiturn_fixture_is_not_silently_flattened(self):
        with self.assertRaisesRegex(ValueError, "single-turn"):
            fixture_labels("catering_en_multiturn")

    def test_interrupted_provider_call_is_saved_as_failed_attempt(self):
        service = RecordingServices("unused")
        def interrupted(*args):
            raise KeyboardInterrupt()
        service.transcribe = interrupted
        result, path = self.run_one(service)
        self.assertEqual(result["error_type"], "KeyboardInterrupt")
        self.assertTrue(path.is_file())
        self.assertEqual(summarize(self.folder)["totals"]["failed_pipelines"], 1)
