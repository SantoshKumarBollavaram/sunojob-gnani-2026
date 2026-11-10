"""Regression coverage for inconsistent successive model corrections. Offline only."""

from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from sunojob.models import Extraction, SourceTurn
from sunojob.providers import GeminiExtractor, ProviderError
from sunojob.speech import LiveServices
from sunojob.validation import CardValidationError, validate_card
from sunojob.webapp import create_app
from sunojob.workflow import ReviewStore


CASE = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/catering_cases.json').read_text())['cases'][0]
SOURCES = [SourceTurn.model_validate(s) for s in CASE['sources']] + [
    SourceTurn(id='turn-2', language='en-IN', text='Yeah, can you change the lunchboxes to 45?')
]


def revised():
    data = deepcopy(CASE['gold_extraction'])
    data['instructions'][1]['value'] = '45'
    quote = {'turn_id': 'turn-2', 'quote': SOURCES[-1].text, 'occurrence': 0}
    data['instructions'][1]['evidence'] = [quote]
    data['corrections'][0]['after'] = '45'
    data['corrections'][0]['evidence'].append(quote)
    return data


def stale():
    data = revised()
    data['corrections'][0]['after'] = '40'
    return data


def body(data):
    return {'modelVersion': 'offline-model', 'candidates': [
        {'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(data)}]}}
    ]}


class Response:
    def __init__(self, status, data=None):
        self.status_code, self.data = status, data
        self.text, self.headers = 'offline test response', {}

    def json(self):
        return body(self.data)


class CorrectionRecoveryTests(unittest.TestCase):
    def run_provider(self, candidates):
        calls = []
        def transport(url, headers, payload):
            calls.append(deepcopy(payload))
            return body(candidates[len(calls) - 1])
        provider = GeminiExtractor('test-key', transport=transport)
        with patch('sys.stderr', new_callable=io.StringIO):
            result = provider.extract(SOURCES)
        return provider, result, calls

    def test_consistent_first_candidate_makes_one_request(self):
        provider, result, calls = self.run_provider([revised()])
        self.assertEqual(len(calls), 1)
        self.assertTrue(provider.validation_attempts[0]['valid'])
        self.assertEqual(result.instructions[1].value, '45')

    def test_stale_historical_after_value_gets_one_recovery_and_full_validation(self):
        provider, result, calls = self.run_provider([stale(), revised()])
        self.assertEqual(len(calls), 2)
        self.assertEqual([v['valid'] for v in provider.validation_attempts], [False, True])
        self.assertEqual(provider.validation_attempts[0]['extraction']['corrections'][0]['after'], '40')
        data = json.loads(calls[1]['contents'][0]['parts'][0]['text'])
        self.assertEqual(data['source_turns'], [s.model_dump() for s in SOURCES])
        self.assertIn('validation_feedback', data)
        self.assertNotIn('test-key', json.dumps(calls))
        self.assertEqual(result.corrections[0].before, '50')
        self.assertEqual(result.corrections[0].after, '45')
        self.assertEqual(result.instructions[2].value, 'exclude')
        self.assertEqual(result.instructions[3].value, 'ask_first')
        card = validate_card(result, SOURCES)
        self.assertFalse(card['customer_confirmed'])
        self.assertFalse(card['owner_confirmed'])

    def test_two_inconsistent_candidates_fail_without_third_request(self):
        transport = Mock(return_value=body(stale()))
        provider = GeminiExtractor('test-key', transport=transport)
        with patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaisesRegex(CardValidationError, 'after-value'):
                provider.extract(SOURCES)
        self.assertEqual(transport.call_count, 2)
        self.assertEqual([x['valid'] for x in provider.validation_attempts], [False, False])

    def test_duplicate_net_corrections_get_one_recovery(self):
        duplicate = revised()
        duplicate['corrections'].append(deepcopy(duplicate['corrections'][0]))
        provider, result, calls = self.run_provider([duplicate, revised()])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result.corrections), 1)

    def test_fabricated_source_quote_still_fails_without_recovery(self):
        invalid = revised()
        invalid['instructions'][0]['evidence'][0]['quote'] = 'Never spoken.'
        transport = Mock(return_value=body(invalid))
        with self.assertRaisesRegex(CardValidationError, 'Evidence is absent'):
            GeminiExtractor('test-key', transport=transport).extract(SOURCES)
        self.assertEqual(transport.call_count, 1)

    def test_recovered_candidate_with_fabricated_quote_is_rejected(self):
        invalid = revised()
        invalid['instructions'][0]['evidence'][0]['quote'] = 'Never spoken.'
        transport = Mock(side_effect=[body(stale()), body(invalid)])
        with patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaisesRegex(CardValidationError, 'Evidence is absent'):
                GeminiExtractor('test-key', transport=transport).extract(SOURCES)
        self.assertEqual(transport.call_count, 2)

    def test_recovery_http_503_is_not_retried(self):
        sender = Mock(side_effect=[Response(200, stale()), Response(503)])
        provider = GeminiExtractor('test-key')
        with patch('sunojob.providers._requests_post', sender), patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaisesRegex(ProviderError, '503'):
                provider.extract(SOURCES)
        self.assertEqual(sender.call_count, 2)
        self.assertEqual([a['generation'] for a in provider.attempts], [1, 2])
        self.assertFalse(provider.attempts[-1]['will_retry'])

    def test_initial_503_retries_and_recovery_have_total_limit_four(self):
        sender = Mock(side_effect=[Response(503), Response(503), Response(200, stale()), Response(200, revised())])
        provider = GeminiExtractor('test-key')
        with patch('sunojob.providers._requests_post', sender), patch('sunojob.providers.time.sleep'), patch('sys.stderr', new_callable=io.StringIO):
            result = provider.extract(SOURCES)
        self.assertEqual(sender.call_count, 4)
        self.assertEqual([a['status'] for a in provider.attempts], [503, 503, 200, 200])
        self.assertEqual([a['generation'] for a in provider.attempts], [1, 1, 1, 2])
        self.assertEqual(result.instructions[1].value, '45')

    def test_validation_history_is_reset_between_separate_extractions(self):
        provider = GeminiExtractor('test-key', transport=Mock(return_value=body(revised())))
        provider.extract(SOURCES)
        provider.extract(SOURCES)
        self.assertEqual(len(provider.validation_attempts), 1)

    def test_live_adapter_saves_both_rejected_and_valid_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            services = LiveServices('gnani-test', 'gemini-test', 'test-model', Path(folder) / 'voice-audio')
            sender = Mock(side_effect=[Response(200, stale()), Response(200, revised())])
            with patch('sunojob.providers._requests_post', sender), patch('sys.stderr', new_callable=io.StringIO):
                result, meta = services.extract(SOURCES)
            report = json.loads((Path(folder) / 'voice-attempts' / meta['attempt_report']).read_text())
            self.assertEqual([a['valid'] for a in report['validation_attempts']], [False, True])
            self.assertEqual(report['extraction']['instructions'][1]['value'], '45')
            self.assertNotIn('gemini-test', json.dumps(report))
            self.assertEqual(result.instructions[1].value, '45')

    def test_failed_recovery_preserves_old_version_then_retry_creates_unapproved_v2(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ReviewStore(Path(folder) / 'reviews.sqlite3')
            initial = store.create(SOURCES[:1], Extraction.model_validate(CASE['gold_extraction']))
            sid = initial['id']
            services = LiveServices('gnani-test', 'gemini-test', 'test-model', Path(folder) / 'voice-audio')
            app = create_app(store, services)
            with TestClient(app) as client:
                headers = {'x-sunojob-token': app.state.token}
                sender = Mock(side_effect=[Response(200, stale()), Response(200, stale()), Response(200, revised())])
                with patch('sunojob.providers._requests_post', sender), patch('sys.stderr', new_callable=io.StringIO):
                    failed = client.post(f'/api/sessions/{sid}/correct-text', json={'version': 1, 'text': SOURCES[-1].text}, headers=headers)
                    self.assertEqual(failed.status_code, 422)
                    pending = store.get(sid)
                    self.assertEqual(pending['version'], 1)
                    self.assertEqual(pending['state'], 'needs_correction')
                    self.assertEqual(pending['card']['extraction']['instructions'][1]['value'], '40')
                    updated = client.post(f'/api/sessions/{sid}/correct-text', json={'version': 1, 'text': SOURCES[-1].text}, headers=headers)
                self.assertEqual(updated.status_code, 200, updated.text)
                final = updated.json()
                self.assertEqual(final['version'], 2)
                self.assertEqual(final['state'], 'draft')
                self.assertEqual(len(final['card']['sources']), 2)
                self.assertIsNone(final['customer_confirmation'])
                self.assertIsNone(final['owner_confirmation'])
                self.assertIsNone(final['pending_text'])
                self.assertEqual(final['card']['extraction']['instructions'][1]['value'], '45')


if __name__ == '__main__':
    unittest.main()
