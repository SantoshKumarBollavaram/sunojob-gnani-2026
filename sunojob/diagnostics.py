"""Three bounded API probes, stopping at the first failure. No retries."""

import argparse
import getpass
import json
import os
import sys

from pydantic import ValidationError

from .__main__ import display_card, get_case, write_result
from .models import Extraction, SourceTurn
from .providers import (
    DEFAULT_GEMINI_MODEL, GeminiExtractor, ProviderError,
    build_extraction_payload, http_post, response_text,
)
from .validation import validate_card


def diagnostic_payloads(sources):
    return [
        ("basic_text", {
            "contents": [{"role": "user", "parts": [{"text": "Reply with OK."}]}],
            "generationConfig": {"maxOutputTokens": 512},
        }),
        ("minimal_structured_json", {
            "contents": [{"role": "user", "parts": [{"text": 'Return an object with ok set to true.'}]}],
            "generationConfig": {
                "maxOutputTokens": 1024,
                "responseFormat": {"text": {"mimeType": "APPLICATION_JSON", "schema": {
                    "type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
                }}},
            },
        }),
        ("full_card", build_extraction_payload(sources)),
    ]


def diagnose(sources, api_key, model=DEFAULT_GEMINI_MODEL, case_id=None, transport=None):
    # Reuse key/model validation before a network request.
    provider = GeminiExtractor(api_key, model)
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": provider.api_key, "Content-Type": "application/json"}
    report = {"provider": "gemini", "model": model, "case_id": case_id,
              "sources": [s.model_dump() for s in sources],
              "diagnostic": True, "stages": [], "http_attempts": []}

    for index, (name, payload) in enumerate(diagnostic_payloads(sources), 1):
        print(f"{index}/3 Testing {name}...", flush=True)
        events = []
        # Fictional case request bodies are saved for reproducible diagnostics.
        # API keys and authentication headers are never part of the report.
        stage = {"name": name, "request_body": payload, "passed": False}
        try:
            if transport is None:
                body = http_post(endpoint, headers, payload, max_attempts=1, trace=events)
            else:
                body = transport(endpoint, headers, payload)
            text = response_text(body)
            stage["model_returned"] = body.get("modelVersion")
            stage["response_text"] = text.replace(api_key, "[REDACTED]")
            if name == "minimal_structured_json" and json.loads(text) != {"ok": True}:
                raise ValueError("Minimal JSON response did not match the control object")
            if name == "full_card":
                extraction = Extraction.model_validate_json(text)
                report["card"] = validate_card(extraction, sources)
                report["model_returned"] = body.get("modelVersion")
            stage["passed"] = True
        except (ProviderError, ValueError) as exc:
            if isinstance(exc, ValidationError):
                error = "Local schema validation failed: " + ", ".join(
                    ".".join(map(str, e["loc"])) for e in exc.errors(include_input=False)
                )
            else:
                error = str(exc)
            # The key is never in the prompt; redact it again defensively.
            error = error.replace(api_key, "[REDACTED]")
            stage["error"] = error
            report["error"] = error
        stage["http_attempts"] = events
        report["http_attempts"].extend({"stage": name, **event} for event in events)
        report["stages"].append(stage)
        if not stage["passed"]:
            print(f"STOP: {name} failed. {stage['error']}", flush=True)
            return report
        print(f"PASS: {name}", flush=True)
    return report


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="catering_en_correction")
    parser.add_argument("--model", default=os.environ.get("SUNOJOB_GEMINI_MODEL", DEFAULT_GEMINI_MODEL))
    args = parser.parse_args()
    case = get_case(args.case)
    sources = [SourceTurn.model_validate(s) for s in case["sources"]]
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        key = getpass.getpass("Gemini API key (hidden): ").strip()
    print(f"Model: {args.model}. Up to 3 generation requests; no retries.", flush=True)
    report = diagnose(sources, key, args.model, case_id=case["id"])
    path = write_result(report)
    if "card" in report:
        display_card(report["card"])
    print(f"Saved result: {path}")
    return 1 if "error" in report else 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except (ProviderError, ValueError, OSError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.", file=sys.stderr)
        sys.exit(1)
