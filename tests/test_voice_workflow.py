import base64
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import wave

from fastapi.testclient import TestClient

from sunojob.models import Extraction, SourceTurn
from sunojob.providers import ProviderError
from sunojob.readback import readback_text
from sunojob.speech import captured_wav
from sunojob.webapp import create_app
from sunojob.workflow import ReviewStore, WorkflowError, digest, reply_kind


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "fixtures/catering_cases.json").read_text())["cases"]
CASE = CASES[0]


def wav_bytes(seconds=.1):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b"\x24\x12" * int(seconds * 16000))
    return output.getvalue()


class FakeServices:
    mode = "offline_test"
    model = "offline_test_double"
    def __init__(self):
        self.spoken = []
        self.asr_calls = 0
        self.fail_extract = False
        self.fail_tts = False
    def extract(self, sources):
        if self.fail_extract:
            raise ProviderError("Offline simulated extraction failure")
        case = CASES[1] if sources[0].language == "te-IN" else CASE
        data = deepcopy(case["gold_extraction"])
        if len(sources) > 1:
            last = sources[-1]
            data["instructions"][1]["value"] = "45"
            data["instructions"][1]["evidence"] = [{"turn_id": last.id, "quote": last.text}]
            data["corrections"][0]["after"] = "45"
            data["corrections"][0]["evidence"].append({"turn_id": last.id, "quote": last.text})
        return Extraction.model_validate(data), {"origin": "offline_test_double"}
    def transcribe(self, audio, language):
        self.asr_calls += 1
        return self.spoken.pop(0), {"origin": "offline_test_double"}
    def synthesize(self, text, language):
        if self.fail_tts:
            raise ProviderError("Offline simulated speech failure")
        return wav_bytes()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "review.sqlite3"
        self.store = ReviewStore(self.path)
        self.sources = [SourceTurn.model_validate(s) for s in CASE["sources"]]
        self.extraction = Extraction.model_validate(CASE["gold_extraction"])
        self.initial = self.store.create(self.sources, self.extraction)
        self.sid = self.initial["id"]
    def ready(self):
        body = self.store.prepare_readback(self.sid, 1, "Test readback")
        token = body["readback"]["id"]
        self.store.ready_readback(self.sid, 1, token, "test-audio-hash")
        self.store.complete_readback(self.sid, 1, token)
        return token
    def revision(self, text="Actually make it 45 lunch boxes."):
        pending = self.store.start_change(self.sid, 1, text)
        sources = self.sources + [SourceTurn(id="turn-2", text=text, language="en-IN")]
        extraction, _ = FakeServices().extract(sources)
        return self.store.finish_change(self.sid, 1, pending["operation"], sources, extraction)

    def test_create_is_draft_and_persists_after_reopening(self):
        result = ReviewStore(self.path).get(self.sid)
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["state"], "draft")
        self.assertIsNone(result["customer_confirmation"])
        self.assertIsNone(result["owner_confirmation"])
    def test_confirmation_requires_a_readback(self):
        with self.assertRaises(WorkflowError):
            self.store.reply(self.sid, 1, "missing", "I confirm")
    def test_completion_requires_successful_audio_generation(self):
        rb = self.store.prepare_readback(self.sid, 1, "Test")["readback"]
        with self.assertRaises(WorkflowError):
            self.store.complete_readback(self.sid, 1, rb["id"])
    def test_confirmation_requires_playback_completion(self):
        rb = self.store.prepare_readback(self.sid, 1, "Test")["readback"]
        self.store.ready_readback(self.sid, 1, rb["id"], "audio")
        with self.assertRaises(WorkflowError):
            self.store.reply(self.sid, 1, rb["id"], "I confirm")
    def test_explicit_confirmation_is_tied_to_exact_version_and_digest(self):
        token = self.ready()
        result = self.store.reply(self.sid, 1, token, "I confirm")
        self.assertEqual(result["state"], "customer_confirmed")
        approval = result["customer_confirmation"]
        self.assertEqual(approval["version"], 1)
        self.assertEqual(approval["sha256"], digest(result["card"]))
        self.assertFalse(approval["identity_verified"])
        self.assertIsNone(result["owner_confirmation"])
    def test_telugu_confirmation(self):
        result = self.store.reply(self.sid, 1, self.ready(), "అవును")
        self.assertEqual(result["state"], "customer_confirmed")
    def test_no_does_not_confirm(self):
        result = self.store.reply(self.sid, 1, self.ready(), "No")
        self.assertEqual(result["state"], "needs_correction")
        self.assertIsNone(result["customer_confirmation"])
    def test_yes_but_starts_correction_instead_of_confirming(self):
        result = self.store.reply(self.sid, 1, self.ready(), "Yes, but make it 45")
        self.assertEqual(result["state"], "updating")
        self.assertIsNone(result["customer_confirmation"])
        self.assertIsNone(result["readback"])
    def test_new_version_needs_a_new_readback(self):
        token = self.ready()
        result = self.revision()
        self.assertEqual(result["version"], 2)
        self.assertIsNone(result["readback"])
        with self.assertRaises(WorkflowError):
            self.store.reply(self.sid, 1, token, "I confirm")
    def test_correction_clears_prior_confirmation_but_keeps_history(self):
        self.store.reply(self.sid, 1, self.ready(), "I confirm")
        result = self.revision()
        self.assertIsNone(result["customer_confirmation"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM review_versions WHERE session_id=?", (self.sid,)).fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM review_events WHERE kind='customer_confirm'", ()).fetchone()[0], 1)
    def test_second_readback_invalidates_old_token(self):
        token = self.ready()
        self.store.prepare_readback(self.sid, 1, "Another readback")
        with self.assertRaises(WorkflowError):
            self.store.reply(self.sid, 1, token, "I confirm")
    def test_consumed_confirmation_cannot_be_replayed(self):
        token = self.ready()
        self.store.reply(self.sid, 1, token, "I confirm")
        with self.assertRaises(WorkflowError):
            self.store.reply(self.sid, 1, token, "I confirm")
    def test_clarifications_block_confirmation(self):
        case = CASES[5]
        body = self.store.create([SourceTurn.model_validate(s) for s in case["sources"]], Extraction.model_validate(case["gold_extraction"]))
        sid = body["id"]
        rb = self.store.prepare_readback(sid, 1, "Question")["readback"]
        self.store.ready_readback(sid, 1, rb["id"], "audio")
        self.store.complete_readback(sid, 1, rb["id"])
        with self.assertRaisesRegex(WorkflowError, "clarification"):
            self.store.reply(sid, 1, rb["id"], "yes")
    def test_inflight_change_blocks_another_change_and_readback(self):
        self.store.start_change(self.sid, 1, "Make it 45")
        with self.assertRaises(WorkflowError):
            self.store.start_change(self.sid, 1, "Make it 46")
        with self.assertRaises(WorkflowError):
            self.store.prepare_readback(self.sid, 1, "Test")
    def test_failed_change_recovers_without_approval(self):
        pending = self.store.start_change(self.sid, 1, "Make it 45")
        result = self.store.fail_change(self.sid, pending["operation"])
        self.assertEqual(result["state"], "needs_correction")
        self.assertIsNone(result["customer_confirmation"])
        self.assertEqual(result["pending_text"], "Make it 45")
    def test_restart_recovers_interrupted_change(self):
        self.store.start_change(self.sid, 1, "Make it 45")
        reopened = ReviewStore(self.path)
        reopened.recover_interrupted()
        self.assertEqual(reopened.get(self.sid)["state"], "needs_correction")
    def test_failed_correction_cannot_be_bypassed_by_reading_old_card(self):
        pending = self.store.start_change(self.sid, 1, "Make it 45")
        self.store.fail_change(self.sid, pending["operation"])
        with self.assertRaisesRegex(WorkflowError, "not been applied"):
            self.store.prepare_readback(self.sid, 1, "Old card")
    def test_wrong_operation_cannot_commit(self):
        self.store.start_change(self.sid, 1, "Make it 45")
        with self.assertRaises(WorkflowError):
            self.store.finish_change(self.sid, 1, "wrong-operation", self.sources, self.extraction)
    def test_integrity_check_detects_card_tampering(self):
        with self.store.connect() as db:
            body = deepcopy(self.initial)
            body["card"]["extraction"]["instructions"][1]["value"] = "999"
            db.execute("UPDATE review_sessions SET body=? WHERE id=?", (json.dumps(body), self.sid))
        with self.assertRaisesRegex(WorkflowError, "integrity"):
            self.store.get(self.sid)


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = ReviewStore(Path(self.temp.name) / "review.sqlite3")
        self.services = FakeServices()
        self.app = create_app(self.store, self.services)
        self.client = TestClient(self.app)
        self.headers = {"x-sunojob-token": self.app.state.token}
    def post(self, path, data):
        return self.client.post(path, json=data, headers=self.headers)
    def create(self):
        result = self.post("/api/sessions/text", {"text": CASE["sources"][0]["text"], "language": "en-IN"})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()
    def listen(self, body):
        result = self.post(f"/api/sessions/{body['id']}/readback", {"version": body["version"]})
        self.assertEqual(result.status_code, 200, result.text)
        result = result.json()
        rb = result["session"]["readback"]
        done = self.post(f"/api/sessions/{body['id']}/readback-complete", {"version": body["version"], "readback_id": rb["id"]})
        self.assertEqual(done.status_code, 200, done.text)
        return done.json()
    def test_home_and_assets_respond(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn('sunojob-token', self.client.get("/").text)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)
    def test_missing_csrf_token_rejected(self):
        result = self.client.post("/api/sessions/text", json={"text": "Hello"})
        self.assertEqual(result.status_code, 403)
    def test_cross_origin_post_rejected(self):
        result = self.client.post("/api/sessions/text", json={"text": "Hello"}, headers={**self.headers, "Origin": "https://elsewhere.invalid"})
        self.assertEqual(result.status_code, 403)
    def test_bad_host_rejected(self):
        self.assertEqual(self.client.get("/", headers={"Host": "elsewhere.invalid"}).status_code, 400)
    def test_voice_request_has_transcript_sources(self):
        self.services.spoken = [CASE["sources"][0]["text"]]
        result = self.post("/api/sessions/voice", {"audio": "test", "language": "en-IN"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["card"]["sources"][0]["text"], CASE["sources"][0]["text"])
    def test_complete_voice_confirmation_path(self):
        body = self.listen(self.create())
        self.services.spoken = ["I confirm"]
        result = self.post(f"/api/sessions/{body['id']}/reply-voice", {"audio": "test", "version": 1, "readback_id": body["readback"]["id"]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["session"]["state"], "customer_confirmed")
        self.assertIsNone(result.json()["session"]["owner_confirmation"])
    def test_yes_but_creates_version_two(self):
        body = self.listen(self.create())
        self.services.spoken = ["Yes, but make it 45 lunch boxes."]
        result = self.post(f"/api/sessions/{body['id']}/reply-voice", {"audio": "test", "version": 1, "readback_id": body["readback"]["id"]})
        self.assertEqual(result.status_code, 200, result.text)
        new = result.json()["session"]
        self.assertEqual(new["version"], 2)
        self.assertIsNone(new["customer_confirmation"])
        self.assertIsNone(new["readback"])
        self.assertEqual(new["card"]["extraction"]["instructions"][1]["value"], "45")
    def test_stale_reply_rejected_before_asr_request(self):
        body = self.listen(self.create())
        updated = self.post(f"/api/sessions/{body['id']}/correct-text", {"version": 1, "text": "Actually make it 45 lunch boxes."})
        self.assertEqual(updated.status_code, 200, updated.text)
        calls = self.services.asr_calls
        result = self.post(f"/api/sessions/{body['id']}/reply-voice", {"audio": "test", "version": 1, "readback_id": body["readback"]["id"]})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(calls, self.services.asr_calls)
    def test_failed_tts_does_not_allow_completion(self):
        body = self.create(); self.services.fail_tts = True
        result = self.post(f"/api/sessions/{body['id']}/readback", {"version": 1})
        self.assertEqual(result.status_code, 502)
        token = self.store.get(body["id"])["readback"]["id"]
        result = self.post(f"/api/sessions/{body['id']}/readback-complete", {"version": 1, "readback_id": token})
        self.assertEqual(result.status_code, 409)
    def test_failed_extraction_recovers_correction_state(self):
        body = self.create(); self.services.fail_extract = True
        result = self.post(f"/api/sessions/{body['id']}/correct-text", {"version": 1, "text": "Make it 45 lunch boxes."})
        self.assertEqual(result.status_code, 502)
        self.assertEqual(self.store.get(body["id"])["state"], "needs_correction")
    def test_plain_yes_in_correction_endpoint_does_not_approve(self):
        body = self.create()
        result = self.post(f"/api/sessions/{body['id']}/correct-text", {"version": 1, "text": "I confirm"})
        self.assertEqual(result.status_code, 409)
        self.assertIsNone(self.store.get(body["id"])["customer_confirmation"])
    def test_session_list_has_no_credentials(self):
        self.create()
        data = self.client.get("/api/sessions").json()
        self.assertEqual(len(data), 1)
        self.assertEqual(set(data[0]), {"id", "version", "state", "language", "updated_at"})


class SpeechAndReadbackTests(unittest.TestCase):
    def test_pcm_conversion_measures_actual_samples(self):
        wav, duration = captured_wav(base64.b64encode(wav_bytes(.25)).decode())
        self.assertAlmostEqual(duration, .25)
        with wave.open(io.BytesIO(wav), "rb") as audio:
            self.assertEqual(audio.getframerate(), 16000)
    def test_overlong_recording_rejected_instead_of_cropped(self):
        with self.assertRaisesRegex(ValueError, "not cropped"):
            captured_wav(base64.b64encode(wav_bytes(25.5)).decode())
    def test_bad_audio_rejected(self):
        for data in ("!invalid", "", base64.b64encode(b"not audio").decode()):
            with self.subTest(data=data):
                with self.assertRaises(ValueError): captured_wav(data)
    def test_whole_utterance_confirmation_only(self):
        self.assertEqual(reply_kind("I confirm."), "confirm")
        self.assertEqual(reply_kind("అవును"), "confirm")
        self.assertEqual(reply_kind("Yes, but make it 45"), "change")
        self.assertEqual(reply_kind("No, do not confirm"), "change")
        self.assertEqual(reply_kind("కాదు"), "reject")
    def test_readback_contains_restrictions_and_correction(self):
        from sunojob.validation import validate_card
        card = validate_card(Extraction.model_validate(CASE["gold_extraction"]), [SourceTurn.model_validate(s) for s in CASE["sources"]])
        english = readback_text(card, "en-IN")
        self.assertIn("Do not add onion", english)
        self.assertIn("Ask me before changing", english)
        self.assertIn("earlier 50; now 40", english)
        self.assertIn("ఉల్లిపాయ", readback_text(card, "te-IN"))


if __name__ == "__main__": unittest.main()
