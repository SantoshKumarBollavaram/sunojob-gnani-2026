from copy import deepcopy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from sunojob.diagnostics import diagnose, diagnostic_payloads
from sunojob.models import Extraction, SourceTurn
from sunojob.providers import ProviderError, build_extraction_payload, response_text
from sunojob.wire_schema import generation_schema


ROOT = Path(__file__).resolve().parents[1]
CASE = json.loads((ROOT / "fixtures/catering_cases.json").read_text())["cases"][0]
SOURCES = [SourceTurn.model_validate(s) for s in CASE["sources"]]


def reply(text):
    return {"modelVersion": "test-model", "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}


GOOD = [reply("OK"), reply('{"ok": true}'), reply(json.dumps(CASE["gold_extraction"]))]


class RequestContractTests(unittest.TestCase):
    def test_provider_schema_uses_only_basic_keywords(self):
        allowed = {"type", "properties", "required", "items", "enum"}
        def visit(node):
            self.assertLessEqual(set(node), allowed)
            for child in node.get("properties", {}).values():
                visit(child)
            if "items" in node:
                visit(node["items"])
        visit(generation_schema(Extraction.model_json_schema()))

    def test_top_level_properties_and_requirements_preserved(self):
        schema = generation_schema(Extraction.model_json_schema())
        self.assertEqual(set(schema["properties"]), {"instructions", "corrections", "questions"})
        self.assertEqual(set(schema["required"]), {"instructions", "corrections", "questions"})

    def test_instruction_evidence_structure_is_preserved(self):
        schema = generation_schema(Extraction.model_json_schema())
        item = schema["properties"]["instructions"]["items"]
        self.assertIn("evidence", item["required"])
        evidence = item["properties"]["evidence"]["items"]
        self.assertIn("quote", evidence["required"])
        self.assertIn("turn_id", evidence["required"])
        self.assertEqual(evidence["properties"]["occurrence"]["type"], "integer")

    def test_instruction_kind_enums_preserved(self):
        schema = generation_schema(Extraction.model_json_schema())
        enum = schema["properties"]["instructions"]["items"]["properties"]["kind"]["enum"]
        self.assertIn("prohibition", enum)
        self.assertIn("permission_required", enum)

    def test_schema_conversion_does_not_mutate_domain_schema(self):
        schema = Extraction.model_json_schema()
        before = deepcopy(schema)
        generation_schema(schema)
        self.assertEqual(schema, before)

    def test_bad_references_and_unsupported_shapes_fail_explicitly(self):
        schemas = [
            {"$ref": "https://example.invalid/schema"},
            {"$ref": "#/$defs/missing"},
            {"$defs": {"loop": {"$ref": "#/$defs/loop"}}, "$ref": "#/$defs/loop"},
            {"anyOf": [{"type": "string"}, {"type": "null"}]},
        ]
        for schema in schemas:
            with self.subTest(schema=schema):
                with self.assertRaises(ValueError):
                    generation_schema(schema)

    def test_json_pointer_escaping_is_supported(self):
        schema = {"$defs": {"a/b~c": {"type": "string"}}, "$ref": "#/$defs/a~1b~0c"}
        self.assertEqual(generation_schema(schema), {"type": "string"})

    def test_payload_uses_native_response_format_and_enum_mime(self):
        config = build_extraction_payload(SOURCES)["generationConfig"]
        self.assertNotIn("responseMimeType", config)
        self.assertNotIn("responseJsonSchema", config)
        self.assertEqual(config["responseFormat"]["text"]["mimeType"], "APPLICATION_JSON")
        self.assertEqual(config["responseFormat"]["text"]["schema"]["type"], "object")

    def test_local_validation_is_still_strict(self):
        for change in ("bad_subject", "empty_evidence", "extra_approval"):
            data = deepcopy(CASE["gold_extraction"])
            if change == "bad_subject":
                data["instructions"][0]["subject"] = "INVALID SUBJECT"
            elif change == "empty_evidence":
                data["instructions"][0]["evidence"] = []
            else:
                data["customer_confirmed"] = True
            with self.subTest(change=change):
                with self.assertRaises(ValidationError):
                    Extraction.model_validate(data)

    def test_empty_source_is_rejected_before_payload_building(self):
        with self.assertRaises(ValueError):
            build_extraction_payload([])

    def test_probe_requests_increase_one_layer_at_a_time(self):
        stages = diagnostic_payloads(SOURCES)
        self.assertEqual([name for name, _ in stages], ["basic_text", "minimal_structured_json", "full_card"])
        self.assertNotIn("responseFormat", stages[0][1]["generationConfig"])
        self.assertEqual(set(stages[1][1]["generationConfig"]["responseFormat"]["text"]["schema"]["properties"]), {"ok"})
        self.assertEqual(stages[2][1], build_extraction_payload(SOURCES))


class DiagnosticTests(unittest.TestCase):
    def run_sequence(self, responses):
        calls = []
        def transport(url, headers, payload):
            calls.append((url, headers, payload))
            response = responses[len(calls) - 1]
            if isinstance(response, Exception):
                raise response
            return response
        with patch("sys.stdout", new_callable=io.StringIO):
            report = diagnose(SOURCES, "secret-for-test", case_id=CASE["id"], transport=transport)
        return report, calls

    def test_all_probes_succeed_and_produce_evaluable_draft(self):
        report, calls = self.run_sequence(GOOD)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(stage["passed"] for stage in report["stages"]))
        self.assertNotIn("error", report)
        self.assertEqual(report["card"]["status"], "draft")
        self.assertFalse(report["card"]["customer_confirmed"])
        self.assertFalse(report["card"]["owner_confirmed"])
        self.assertNotIn("secret-for-test", json.dumps(report))

    def test_first_failure_stops_after_one_request(self):
        report, calls = self.run_sequence([ProviderError("HTTP 400")])
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["stages"][-1]["name"], "basic_text")
        self.assertIn("error", report)

    def test_second_failure_preserves_successful_baseline(self):
        report, calls = self.run_sequence([GOOD[0], ProviderError("HTTP 400")])
        self.assertEqual(len(calls), 2)
        self.assertTrue(report["stages"][0]["passed"])
        self.assertFalse(report["stages"][1]["passed"])

    def test_full_card_failure_preserves_two_successful_controls(self):
        report, calls = self.run_sequence([GOOD[0], GOOD[1], ProviderError("HTTP 400")])
        self.assertEqual(len(calls), 3)
        self.assertTrue(report["stages"][1]["passed"])
        self.assertEqual(report["stages"][-1]["name"], "full_card")
        self.assertNotIn("card", report)

    def test_invalid_json_control_stops_before_full_card(self):
        report, calls = self.run_sequence([GOOD[0], reply("not JSON")])
        self.assertEqual(len(calls), 2)
        self.assertIn("error", report)

    def test_wrong_control_value_stops_before_full_card(self):
        report, calls = self.run_sequence([GOOD[0], reply('{"ok": false}')])
        self.assertEqual(len(calls), 2)
        self.assertIn("error", report)

    def test_quote_validation_failure_is_not_a_successful_card(self):
        bad = deepcopy(CASE["gold_extraction"])
        bad["instructions"][0]["evidence"][0]["quote"] = "Customer never said this."
        report, calls = self.run_sequence([GOOD[0], GOOD[1], reply(json.dumps(bad))])
        self.assertEqual(len(calls), 3)
        self.assertNotIn("card", report)
        self.assertFalse(report["stages"][-1]["passed"])

    def test_error_details_redact_key(self):
        report, _ = self.run_sequence([ProviderError("Rejected secret-for-test")])
        self.assertNotIn("secret-for-test", json.dumps(report))

    def test_malformed_or_blocked_response_stops_diagnostics(self):
        for response in ({}, {"candidates": [{"finishReason": "MAX_TOKENS"}]}):
            with self.subTest(response=response):
                report, calls = self.run_sequence([response])
                self.assertEqual(len(calls), 1)
                self.assertIn("error", report)

    def test_bad_content_parts_are_reported_explicitly(self):
        with self.assertRaises(ProviderError):
            response_text({"candidates": [{"finishReason": "STOP", "content": None}]})


if __name__ == "__main__":
    unittest.main()
