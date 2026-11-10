from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from sunojob.evaluation import evaluate, score_case
from sunojob.models import Evidence, Extraction, SourceTurn
from sunojob.providers import GeminiExtractor, ProviderError, SYSTEM_PROMPT
from sunojob.validation import CardValidationError, resolve_evidence, validate_card


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "fixtures/catering_cases.json").read_text())["cases"]


def example():
    return deepcopy(CASES[0])


def sources(case):
    return [SourceTurn.model_validate(turn) for turn in case["sources"]]


def validate(case):
    return validate_card(Extraction.model_validate(case["gold_extraction"]), sources(case))


def response_for(extraction, finish="STOP"):
    return {"candidates": [{"finishReason": finish, "content": {"parts": [
        {"text": json.dumps(extraction, ensure_ascii=False)}
    ]}}]}


class CardCoreTests(unittest.TestCase):
    def test_all_labelled_examples_are_valid_drafts(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                card = validate(case)
                self.assertEqual(card["status"], "draft")
                self.assertFalse(card["customer_confirmed"])
                self.assertFalse(card["owner_confirmed"])
                self.assertTrue(card["requires_human_review"])

    def test_evidence_offsets_recover_exact_original_text(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                card = validate(case)
                by_id = {s["id"]: s["text"] for s in case["sources"]}
                for span in card["resolved_evidence"]:
                    self.assertEqual(by_id[span["turn_id"]][span["start"]:span["end"]], span["quote"])

    def test_empty_evidence_rejected(self):
        case = example()
        case["gold_extraction"]["instructions"][0]["evidence"] = []
        with self.assertRaises(ValidationError):
            validate(case)

    def test_fabricated_quote_rejected(self):
        case = example()
        case["gold_extraction"]["instructions"][0]["evidence"][0]["quote"] = "Charge 9000 rupees."
        with self.assertRaises(CardValidationError):
            validate(case)

    def test_quote_from_unknown_turn_rejected(self):
        case = example()
        case["gold_extraction"]["instructions"][0]["evidence"][0]["turn_id"] = "nonexistent"
        with self.assertRaises(CardValidationError):
            validate(case)

    def test_evidence_must_match_whitespace_exactly(self):
        case = example()
        case["gold_extraction"]["instructions"][2]["evidence"][0]["quote"] = "Do  not add onion."
        with self.assertRaises(CardValidationError):
            validate(case)

    def test_ambiguous_quote_occurrence_resolves_requested_position(self):
        turn = SourceTurn(id="t1", text="No onion. No onion.")
        evidence = Evidence(turn_id="t1", quote="No onion.", occurrence=1)
        self.assertEqual(resolve_evidence(evidence, {turn.id: turn})["start"], 10)

    def test_out_of_range_quote_occurrence_rejected(self):
        turn = SourceTurn(id="t1", text="No onion.")
        with self.assertRaises(CardValidationError):
            resolve_evidence(Evidence(turn_id="t1", quote="No onion.", occurrence=1), {turn.id: turn})

    def test_blank_source_rejected(self):
        with self.assertRaises(ValidationError):
            SourceTurn(id="t1", text="  \n ")

    def test_duplicate_turn_ids_rejected(self):
        case = example()
        case["sources"].append(deepcopy(case["sources"][0]))
        with self.assertRaises(CardValidationError):
            validate(case)

    def test_model_cannot_supply_confirmation_fields(self):
        case = example()
        case["gold_extraction"]["customer_confirmed"] = True
        with self.assertRaises(ValidationError):
            validate(case)

    def test_instruction_cannot_hide_extra_approval_field(self):
        case = example()
        case["gold_extraction"]["instructions"][0]["approved"] = True
        with self.assertRaises(ValidationError):
            validate(case)

    def test_duplicate_instruction_id_rejected(self):
        case = example()
        case["gold_extraction"]["instructions"][1]["id"] = "i1"
        with self.assertRaises(CardValidationError):
            validate(case)

    def test_contradictory_active_quantities_rejected(self):
        case = example()
        item = deepcopy(case["gold_extraction"]["instructions"][1])
        item.update(id="i5", value="50")
        case["gold_extraction"]["instructions"].append(item)
        with self.assertRaises(CardValidationError):
            validate(case)

    def test_duplicate_fact_rejected(self):
        case = example()
        item = deepcopy(case["gold_extraction"]["instructions"][0])
        item["id"] = "i5"
        case["gold_extraction"]["instructions"].append(item)
        with self.assertRaises(CardValidationError):
            validate(case)

    def test_correction_after_must_match_current_value(self):
        case = example()
        case["gold_extraction"]["corrections"][0]["after"] = "45"
        with self.assertRaises(CardValidationError):
            validate(case)

    def test_correction_needs_known_target(self):
        case = example()
        case["gold_extraction"]["corrections"][0]["instruction_id"] = "i999"
        with self.assertRaises(CardValidationError):
            validate(case)

    def test_source_digest_changes_after_transcript_change(self):
        case = example()
        before = validate(case)["source_sha256"]
        case["sources"][0]["text"] += " Additional sentence."
        self.assertNotEqual(validate(case)["source_sha256"], before)

    def test_quote_presence_is_not_semantic_proof(self):
        case = example()
        case["gold_extraction"]["instructions"][2]["value"] = "include"
        # Evidence exists, but the polarity is wrong. The structural validator
        # cannot prove semantics; the labelled scorer catches this reversal.
        self.assertEqual(validate(case)["status"], "draft")
        result = score_case(example(), case["gold_extraction"])
        self.assertFalse(result["strict_case_pass"])
        self.assertEqual(result["restrictions_kept"], 1)
        self.assertEqual(len(result["unmatched_claims"]), 1)

    def test_missing_prediction_remains_in_denominators(self):
        case = example()
        result = evaluate([case], {})["totals"]
        self.assertEqual(result["restrictions_expected"], 2)
        self.assertEqual(result["restrictions_kept"], 0)
        self.assertEqual(result["corrections_expected"], 1)
        self.assertEqual(result["failed_or_missing_cases"], 1)

    def test_invalid_prediction_counts_as_failure(self):
        case = example()
        bad = deepcopy(case["gold_extraction"])
        bad["instructions"][0]["evidence"] = []
        result = score_case(case, bad)
        self.assertFalse(result["valid_card"])
        self.assertEqual(result["restrictions_kept"], 0)

    def test_removed_restriction_counted_as_missing(self):
        case = example()
        bad = deepcopy(case["gold_extraction"])
        bad["instructions"] = bad["instructions"][:-1]
        result = score_case(case, bad)
        self.assertEqual(result["restrictions_kept"], 1)
        self.assertEqual(len(result["missing_instructions"]), 1)

    def test_omitted_correction_record_does_not_get_credit(self):
        case = example()
        bad = deepcopy(case["gold_extraction"])
        bad["corrections"] = []
        result = score_case(case, bad)
        self.assertEqual(result["instructions_matched"], 4)
        self.assertEqual(result["corrections_applied"], 0)
        self.assertFalse(result["strict_case_pass"])

    def test_unmatched_claim_is_not_automatically_called_invented(self):
        case = example()
        bad = deepcopy(case["gold_extraction"])
        item = deepcopy(bad["instructions"][0])
        item.update(id="i9", subject="food_boxes")
        bad["instructions"].append(item)
        report = evaluate([case], {case["id"]: bad})
        self.assertEqual(report["totals"]["unmatched_claims_requiring_review"], 1)
        self.assertIsNone(report["totals"]["invented_actions_confirmed_by_human"])

    def test_duplicate_cases_and_unknown_predictions_rejected(self):
        case = example()
        with self.assertRaises(ValueError):
            evaluate([case, case], {})
        with self.assertRaises(ValueError):
            evaluate([case], {"unknown-case": {}})

    def test_gold_controls_exercise_scorer_without_model_claims(self):
        report = evaluate(CASES, {c["id"]: c["gold_extraction"] for c in CASES})
        self.assertEqual(report["totals"]["strict_case_passes"], len(CASES))


class ProviderTests(unittest.TestCase):
    def test_parses_response_and_keeps_key_out_of_url_and_body(self):
        calls = []
        def transport(url, headers, body):
            calls.append((url, headers, body))
            return response_for(example()["gold_extraction"])
        provider = GeminiExtractor("test-secret", transport=transport)
        output = provider.extract(sources(example()))
        self.assertEqual(len(output.instructions), 4)
        url, headers, body = calls[0]
        self.assertNotIn("test-secret", url)
        self.assertNotIn("test-secret", json.dumps(body))
        self.assertEqual(headers["x-goog-api-key"], "test-secret")
        user_data = json.loads(body["contents"][0]["parts"][0]["text"])
        self.assertEqual(set(user_data), {"source_turns"})
        self.assertNotIn("gold_extraction", user_data)

    def test_truncated_model_response_rejected(self):
        provider = GeminiExtractor("test", transport=lambda *a: response_for(example()["gold_extraction"], "MAX_TOKENS"))
        with self.assertRaises(ProviderError):
            provider.extract(sources(example()))

    def test_blocked_model_response_rejected(self):
        provider = GeminiExtractor("test", transport=lambda *a: {"promptFeedback": {"blockReason": "SAFETY"}})
        with self.assertRaises(ProviderError):
            provider.extract(sources(example()))

    def test_missing_fields_from_model_rejected(self):
        provider = GeminiExtractor("test", transport=lambda *a: response_for({"instructions": []}))
        with self.assertRaises(ValidationError):
            provider.extract(sources(example()))

    def test_thinking_parts_not_parsed_as_answer(self):
        response = response_for(example()["gold_extraction"])
        response["candidates"][0]["content"]["parts"].insert(0, {"thought": True, "text": "Internal reasoning"})
        output = GeminiExtractor("test", transport=lambda *a: response).extract(sources(example()))
        self.assertEqual(len(output.instructions), 4)

    def test_untrusted_transcript_kept_out_of_system_instructions(self):
        case = deepcopy(CASES[8])
        captured = []
        def transport(url, headers, body):
            captured.append(body)
            return response_for(case["gold_extraction"])
        GeminiExtractor("test", transport=transport).extract(sources(case))
        self.assertEqual(captured[0]["systemInstruction"]["parts"][0]["text"], SYSTEM_PROMPT)
        self.assertNotIn(case["sources"][0]["text"], SYSTEM_PROMPT)

    def test_invalid_key_and_model_rejected_before_network(self):
        for key, model in (("", "gemini-2.5-flash"), ("a b", "gemini-2.5-flash"),
                           ("abc\x00def", "gemini-2.5-flash"), ("test", "../other?key=test")):
            with self.subTest(model=model):
                with self.assertRaises(ProviderError):
                    GeminiExtractor(key, model)


class CLITests(unittest.TestCase):
    def test_failed_model_attempt_is_saved_without_credentials(self):
        from sunojob.__main__ import run
        captured = []
        def save(data):
            captured.append(deepcopy(data))
            return "failed-attempt.json"
        with patch("sys.argv", ["sunojob", "extract", "--case", example()["id"]]), \
             patch.dict("os.environ", {"GEMINI_API_KEY": "secret-for-test"}), \
             patch("sunojob.__main__.GeminiExtractor.extract", side_effect=ProviderError("Rate limited")), \
             patch("sunojob.__main__.write_result", side_effect=save), \
             patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(ValueError, "Failed attempt recorded"):
                run()
        self.assertEqual(captured[0]["error"], "Rate limited")
        self.assertNotIn("secret-for-test", json.dumps(captured))
        self.assertIn("sources", captured[0])

    def test_failed_attempt_can_be_scored_without_dropping_denominators(self):
        from sunojob.__main__ import run
        case = example()
        attempt = {"case_id": case["id"], "provider": "gemini", "error": "Rate limited",
                   "sources": [s.model_dump() for s in sources(case)]}
        captured = []
        with patch("sys.argv", ["sunojob", "evaluate", "--result", "unused.json"]), \
             patch("sunojob.__main__.load_json", return_value=attempt), \
             patch("sunojob.__main__.get_case", return_value=case), \
             patch("sunojob.__main__.write_result", side_effect=lambda data: captured.append(data) or "report.json"), \
             patch("sys.stdout", new_callable=io.StringIO):
            run()
        self.assertEqual(captured[0]["totals"]["instructions_expected"], 4)
        self.assertEqual(captured[0]["totals"]["instructions_matched"], 0)
        self.assertEqual(captured[0]["totals"]["failed_or_missing_cases"], 1)

    def test_offline_demo_does_not_claim_model_performance(self):
        result = subprocess.run([sys.executable, "-m", "sunojob", "demo", "--case", "catering_te_correction"],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not a model prediction", result.stdout)
        self.assertIn("neither party has confirmed", result.stdout)

    def test_labelled_demo_cannot_be_scored_as_live_extraction(self):
        from sunojob.__main__ import run
        case = example()
        saved = {"case_id": case["id"], "provider": "labelled_fixture_not_AI", "card": validate(case)}
        with patch("sys.argv", ["sunojob", "evaluate", "--result", "unused.json"]), \
             patch("sunojob.__main__.load_json", return_value=saved):
            with self.assertRaisesRegex(ValueError, "actual model"):
                run()


if __name__ == "__main__":
    unittest.main()
