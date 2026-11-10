"""Network-free checks of real adapters, rather than the UI's service doubles."""

import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sunojob.models import SourceTurn
from sunojob.providers import ProviderError
from sunojob.speech import LiveServices
from test_voice_workflow import CASE, wav_bytes


class LiveAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.services = LiveServices("test-gnani-secret", "test-gemini-secret",
                                     "test-model", self.root / "audio")

    @patch("sunojob.speech.requests.post")
    def test_stt_sends_converted_audio_and_keeps_actual_transcript(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {
            "success": True, "transcript": "Do not add onion.", "model": "prisma-v3.0"}
        text, info = self.services.transcribe(base64.b64encode(wav_bytes(.25)).decode(), "en-IN")
        self.assertEqual(text, "Do not add onion.")
        self.assertEqual(info["duration_seconds"], .25)
        self.assertTrue((self.root / "audio" / info["audio_file"]).exists())
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.vachana.ai/stt/v3")
        self.assertEqual(kwargs["data"], {"model": "prisma-v3.0", "language_code": "en-IN"})
        self.assertEqual(kwargs["headers"]["X-API-Key-ID"], "test-gnani-secret")
        self.assertFalse(kwargs["allow_redirects"])

    @patch("sunojob.speech.requests.post")
    def test_tts_repairs_streaming_wav_using_existing_normalizer(self, post):
        original = wav_bytes(.25)
        streaming = bytearray(original)
        streaming[4:8] = b"\xff" * 4
        streaming[40:44] = b"\xff" * 4
        post.return_value = Mock(status_code=200, content=bytes(streaming))
        result = self.services.synthesize("Do not add onion.", "en-IN")
        self.assertEqual(result, original)
        self.assertEqual(post.call_args.kwargs["json"]["voice"], "Kaveri")
        self.assertEqual(post.call_args.kwargs["json"]["audio_config"]["sample_rate"], 16000)

    @patch("sunojob.speech.GeminiExtractor")
    def test_failed_extraction_attempt_is_retained_without_credentials(self, factory):
        provider = factory.return_value
        provider.attempts = [{"attempt": 1, "status": 503, "will_retry": False}]
        provider.validation_attempts = []
        provider.extract.side_effect = ProviderError("Simulated failure")
        sources = [SourceTurn.model_validate(source) for source in CASE["sources"]]
        with self.assertRaises(ProviderError):
            self.services.extract(sources)
        reports = list((self.root / "voice-attempts").glob("*.json"))
        self.assertEqual(len(reports), 1)
        body = reports[0].read_text()
        self.assertNotIn("test-gnani-secret", body)
        self.assertNotIn("test-gemini-secret", body)
        self.assertEqual(json.loads(body)["http_attempts"][0]["status"], 503)
