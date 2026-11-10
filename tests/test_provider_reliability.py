from copy import deepcopy
import io
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

from sunojob.models import SourceTurn
from sunojob.providers import (
    DEFAULT_GEMINI_MODEL, GeminiExtractor, ProviderError, _requests_post, http_post,
)


ROOT = Path(__file__).resolve().parents[1]
CASE = json.loads((ROOT / "fixtures/catering_cases.json").read_text())["cases"][0]


class Response:
    def __init__(self, status, body=None, headers=None, text="Provider response"):
        self.status_code = status
        self.body = body if body is not None else {"ok": True}
        self.headers = headers or {}
        self.text = text

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class ProviderReliabilityTests(unittest.TestCase):
    def call(self, responses):
        sender = Mock(side_effect=responses)
        delays, trace = [], []
        with patch("sys.stderr", new_callable=io.StringIO):
            result = http_post("https://example.invalid", {"x-goog-api-key": "test-key"}, {},
                               request=sender, sleeper=delays.append, trace=trace)
        return result, sender, delays, trace

    def test_default_uses_documented_current_flash_lite(self):
        self.assertEqual(DEFAULT_GEMINI_MODEL, "gemini-3.5-flash-lite")
        self.assertEqual(GeminiExtractor("test-key").model, DEFAULT_GEMINI_MODEL)

    def test_two_503s_then_success_preserves_all_attempts(self):
        result, sender, delays, trace = self.call([Response(503), Response(503), Response(200)])
        self.assertEqual(result, {"ok": True})
        self.assertEqual(sender.call_count, 3)
        self.assertEqual(delays, [1.0, 2.0])
        self.assertEqual([t["status"] for t in trace], [503, 503, 200])
        self.assertFalse(trace[-1]["will_retry"])

    def test_persistent_503_stops_after_three_attempts(self):
        sender = Mock(return_value=Response(503))
        delays, trace = [], []
        with patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaisesRegex(ProviderError, "HTTP 503"):
                http_post("url", {"x-goog-api-key": "test-key"}, {}, request=sender,
                          sleeper=delays.append, trace=trace)
        self.assertEqual(sender.call_count, 3)
        self.assertEqual(delays, [1.0, 2.0])
        self.assertEqual(len(trace), 3)
        self.assertFalse(trace[-1]["will_retry"])

    def test_other_http_errors_do_not_retry(self):
        for status in (400, 401, 403, 404, 429, 500, 502, 504):
            with self.subTest(status=status):
                sender, sleeper, trace = Mock(return_value=Response(status)), Mock(), []
                with self.assertRaises(ProviderError):
                    http_post("url", {"x-goog-api-key": "test-key"}, {},
                              request=sender, sleeper=sleeper, trace=trace)
                self.assertEqual(sender.call_count, 1)
                sleeper.assert_not_called()
                self.assertEqual(trace[0]["status"], status)

    def test_numeric_retry_after_is_respected(self):
        _, _, delays, _ = self.call([Response(503, headers={"Retry-After": "5"}), Response(200)])
        self.assertEqual(delays, [5.0])

    def test_long_or_unparseable_retry_after_stops_automatic_retry(self):
        for value in ("60", "NaN", "-1", "later", "Thu, 05 Nov 2026 23:00:00 GMT"):
            with self.subTest(value=value):
                sender = Mock(return_value=Response(503, headers={"Retry-After": value}))
                sleeper = Mock()
                with self.assertRaises(ProviderError):
                    http_post("url", {"x-goog-api-key": "test-key"}, {},
                              request=sender, sleeper=sleeper)
                self.assertEqual(sender.call_count, 1)
                sleeper.assert_not_called()

    def test_invalid_json_is_not_retried(self):
        sender = Mock(return_value=Response(200, body=ValueError("bad JSON")))
        with self.assertRaisesRegex(ProviderError, "invalid JSON"):
            http_post("url", {"x-goog-api-key": "test-key"}, {}, request=sender)
        self.assertEqual(sender.call_count, 1)

    def test_network_error_is_recorded_without_retry(self):
        sender, sleeper, trace = Mock(side_effect=ProviderError("Network error")), Mock(), []
        with self.assertRaises(ProviderError):
            http_post("url", {"x-goog-api-key": "test-key"}, {},
                      request=sender, sleeper=sleeper, trace=trace)
        self.assertEqual(sender.call_count, 1)
        sleeper.assert_not_called()
        self.assertIsNone(trace[0]["status"])
        self.assertEqual(trace[0]["outcome"], "network_or_client_error")

    def test_error_body_redacts_key(self):
        sender = Mock(return_value=Response(403, text="Bad header test-key"))
        with self.assertRaises(ProviderError) as caught:
            http_post("url", {"x-goog-api-key": "test-key"}, {}, request=sender)
        self.assertNotIn("test-key", str(caught.exception))
        self.assertIn("[REDACTED]", str(caught.exception))

    def test_transport_exception_does_not_expose_key(self):
        class RequestException(Exception):
            pass
        fake = types.SimpleNamespace(RequestException=RequestException,
            post=Mock(side_effect=RequestException("secret-token-in-exception")))
        with patch.dict("sys.modules", {"requests": fake}):
            with self.assertRaises(ProviderError) as caught:
                _requests_post("url")
        self.assertNotIn("secret-token-in-exception", str(caught.exception))

    def test_attempt_limits_cannot_be_unbounded(self):
        for value in (0, 4, -1, True, 2.5):
            with self.subTest(value=value):
                sender = Mock()
                with self.assertRaises(ValueError):
                    http_post("url", {}, {}, max_attempts=value, request=sender)
                sender.assert_not_called()

    def test_one_attempt_policy_disables_retry(self):
        sender, sleeper = Mock(return_value=Response(503)), Mock()
        with self.assertRaises(ProviderError):
            http_post("url", {"x-goog-api-key": "test-key"}, {}, max_attempts=1,
                      request=sender, sleeper=sleeper)
        self.assertEqual(sender.call_count, 1)
        sleeper.assert_not_called()

    def test_extractor_exposes_attempts_and_returned_model_version(self):
        body = {"modelVersion": "gemini-test-returned", "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(CASE["gold_extraction"])}]}}
        ]}
        sender = Mock(return_value=Response(200, body=body))
        with patch("sunojob.providers._requests_post", sender):
            provider = GeminiExtractor("test-key")
            result = provider.extract([SourceTurn.model_validate(s) for s in CASE["sources"]])
        self.assertEqual(len(result.instructions), 4)
        self.assertEqual(provider.model_version, "gemini-test-returned")
        self.assertEqual([e["status"] for e in provider.attempts], [200])
        self.assertNotIn("test-key", json.dumps(provider.attempts))
        request_body = sender.call_args.kwargs["json"]
        self.assertNotIn("temperature", request_body["generationConfig"])

    def test_cli_saves_attempt_trace_on_failure(self):
        from sunojob.__main__ import run
        saved = []
        def failed_extract(provider, sources):
            provider.attempts = [{"attempt": 1, "status": 503, "will_retry": False}]
            raise ProviderError("Provider unavailable")
        with patch("sys.argv", ["sunojob", "extract", "--case", CASE["id"]]), \
             patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}), \
             patch("sunojob.providers.GeminiExtractor.extract", failed_extract), \
             patch("sunojob.__main__.write_result", side_effect=lambda data: saved.append(deepcopy(data)) or "saved.json"), \
             patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(ValueError, "Failed attempt recorded"):
                run()
        self.assertEqual(saved[0]["http_attempts"][0]["status"], 503)


if __name__ == "__main__":
    unittest.main()
