"""Evaluate one checked recording at a time; references never enter the model prompt."""

import argparse
import base64
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import time
import unicodedata
import uuid

from pydantic import Field, model_validator

from .evaluation import evaluate
from .models import Kind, SourceTurn, StrictModel, Subject, Text
from .providers import DEFAULT_GEMINI_MODEL
from .speech import LiveServices
from .validation import canonical, validate_card


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".local/recording-evaluation"


class ExpectedInstruction(StrictModel):
    kind: Kind
    subject: Subject
    value: Text


class ExpectedCorrection(StrictModel):
    kind: Kind
    subject: Subject
    before: Text
    after: Text


class Labels(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    language: str = Field(pattern=r"^(en-IN|te-IN|mixed)$")
    collection: str = Field(pattern=r"^(scripted_development|independent_natural)$")
    reference_text: str = Field(min_length=1, max_length=20000)
    expected_instructions: list[ExpectedInstruction] = Field(max_length=50)
    expected_corrections: list[ExpectedCorrection] = Field(max_length=30)
    question_required: bool

    @model_validator(mode="after")
    def consistent_labels(self):
        if not tokens(self.reference_text):
            raise ValueError("Reference must contain spoken words")
        signatures = [(item.kind, item.subject, canonical(item.value)) for item in self.expected_instructions]
        if len(signatures) != len(set(signatures)):
            raise ValueError("Expected instructions contain duplicate slots")
        if not signatures and not self.question_required:
            raise ValueError("Empty instructions require a clarification label")
        for correction in self.expected_corrections:
            if ((correction.kind, correction.subject, canonical(correction.after)) not in signatures
                    or canonical(correction.before) == canonical(correction.after)):
                raise ValueError("Expected correction must change a value and match an active instruction")
        return self


def fixture_labels(case_id):
    cases = json.loads((ROOT / "fixtures/catering_cases.json").read_text(encoding="utf-8"))["cases"]
    case = next((case for case in cases if case["id"] == case_id), None)
    if not case or len(case["sources"]) != 1:
        raise ValueError("Choose a single-turn fixture for this recording check")
    return Labels.model_validate({"id": case_id, "language": case["sources"][0]["language"],
        "collection": "scripted_development", "reference_text": case["sources"][0]["text"],
        "expected_instructions": case["expected_instructions"],
        "expected_corrections": case["expected_corrections"],
        "question_required": case.get("question_required", False)})


def tokens(text):
    value = unicodedata.normalize("NFC", text).casefold()
    return "".join(char if unicodedata.category(char)[0] in "LNM" else " " for char in value).split()


def word_errors(reference, hypothesis):
    expected, actual = tokens(reference), tokens(hypothesis)
    previous = list(range(len(actual) + 1))
    for i, word in enumerate(expected, 1):
        current = [i]
        for j, candidate in enumerate(actual, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (word != candidate)))
        previous = current
    errors = previous[-1]
    return {"word_edit_errors": errors, "reference_words": len(expected),
            "word_error_rate": errors / len(expected) if expected else None,
            "normalization": "NFC, casefold, punctuation separation; no number or script equivalence"}


def score_result(result):
    labels = Labels.model_validate(result["labels"]).model_dump()
    transcript = result.get("transcript") or ""
    case = {"id": result["attempt_id"], "expected_instructions": labels["expected_instructions"],
            "expected_corrections": labels["expected_corrections"],
            "question_required": labels["question_required"],
            "sources": [SourceTurn(id="turn-1", text=transcript or "No transcript available.",
                                    language=labels["language"]).model_dump()]}
    # Evidence must match the recognized transcript, while the expected slots
    # come from the independently checked reference. Never validate ASR quotes
    # against the different reference wording.
    prediction = result.get("extraction") if result.get("status") == "success" else None
    return evaluate([case], {case["id"]: prediction})


def run_recording(labels, audio_path, services, output_dir):
    labels = Labels.model_validate(labels).model_dump()
    audio_path, output_dir = Path(audio_path), Path(output_dir)
    if not audio_path.is_file() or not 0 < audio_path.stat().st_size <= 4_000_000:
        raise ValueError("Choose a nonempty recording smaller than 4 MB")
    audio = audio_path.read_bytes()
    labels_hash = hashlib.sha256(json.dumps(labels, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    result = {"schema_version": 1, "attempt_id": uuid.uuid4().hex, "labels": labels,
              "labels_sha256": labels_hash, "input_audio_sha256": hashlib.sha256(audio).hexdigest(),
              "reference_checked_before_request": True, "model": services.model,
              "service_mode": services.mode, "started_at": datetime.now(timezone.utc).isoformat(),
              "status": "failed", "stage": "transcription", "transcript": None,
              "extraction": None, "invented_actions_confirmed_by_human": None}
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        language = "te-IN" if labels["language"] in {"te-IN", "mixed"} else "en-IN"
        transcript, provenance = services.transcribe(base64.b64encode(audio).decode(), language)
        # Validate transcription before using it. Returned provider metadata is
        # intentionally not copied; it is not needed to compute these scores.
        sources = [SourceTurn(id="turn-1", text=transcript, language=labels["language"])]
        result["transcript"] = transcript
        result["transcription_elapsed_seconds"] = time.monotonic() - started
        result["stage"] = "extraction"
        extraction, metadata = services.extract(sources)
        validate_card(extraction, sources)
        result["extraction"] = extraction.model_dump()
        result["status"] = "success"
        result["stage"] = "complete"
    except (Exception, KeyboardInterrupt) as exc:
        # Provider exception text or validation inputs can contain credentials
        # or arbitrary model text; save only the class and the failed stage.
        result["error_type"] = type(exc).__name__
    result["elapsed_seconds"] = time.monotonic() - started
    result["transcription_score"] = word_errors(labels["reference_text"], result.get("transcript") or "")
    result["scoring"] = score_result(result)
    path = output_dir / ("attempt-" + result["attempt_id"] + ".json")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result, path


def summarize(folder):
    paths = sorted(Path(folder).glob("attempt-*.json"))
    totals = {"attempts": 0, "successful_pipelines": 0, "failed_pipelines": 0,
              "strict_case_passes": 0, "instructions_expected": 0, "instructions_matched": 0,
              "restrictions_expected": 0, "restrictions_kept": 0, "corrections_expected": 0,
              "corrections_applied": 0, "unmatched_claims_requiring_review": 0}
    ids, recordings, groups = set(), set(), {}
    for path in paths:
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("schema_version") != 1 or not re.fullmatch(r"[a-f0-9]{32}", result.get("attempt_id", "")):
            raise ValueError("An evaluation file has an invalid format")
        if result["attempt_id"] in ids:
            raise ValueError("Duplicate attempt ID; remove duplicate copies before summarizing")
        ids.add(result["attempt_id"])
        scores = score_result(result)["totals"]
        totals["attempts"] += 1
        totals["successful_pipelines"] += result["status"] == "success"
        totals["failed_pipelines"] += result["status"] != "success"
        for field in totals.keys() - {"attempts", "successful_pipelines", "failed_pipelines"}:
            totals[field] += scores[field]
        recordings.add(result["input_audio_sha256"])
        key = result["labels"]["collection"] + "/" + result["labels"]["language"] + "/" + result["model"] + "/" + result["service_mode"]
        groups[key] = groups.get(key, 0) + 1
    return {"totals": totals, "distinct_input_recordings": len(recordings), "attempt_groups": groups,
            "invented_actions_confirmed_by_human": None,
            "limitations": ["Every saved attempt is counted, including failures and repeated recordings.",
                "A scripted development recording is not an independent real-world accuracy test.",
                "Offline test services are not live model performance.",
                "Strict slot matching needs manual review for paraphrases and unsupported claims.",
                "Clarification presence is checked; question adequacy and condition meaning require human review.",
                "No TTS, confirmation, owner approval, SMTP or inbox delivery is tested by this runner."]}


def key(name, label):
    value = os.environ.get(name, "").strip() or getpass.getpass(label).strip()
    if not value or any(not 33 <= ord(char) <= 126 for char in value):
        raise ValueError("Enter a valid API key at the hidden prompt")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    template = commands.add_parser("template", help="Print labels and wording for a scripted practice recording; no API calls")
    template.add_argument("--case", default="catering_en_correction")
    run = commands.add_parser("run", help="One STT request and one logical extraction; no email or TTS")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--case")
    source.add_argument("--labels", type=Path)
    run.add_argument("--audio", type=Path, required=True)
    run.add_argument("--reference-checked", action="store_true", help="You listened and checked the reference and expected slots before this request")
    run.add_argument("--model", default=os.environ.get("SUNOJOB_GEMINI_MODEL", DEFAULT_GEMINI_MODEL))
    run.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    summary = commands.add_parser("summary", help="Summarize all saved attempts without API requests")
    summary.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.command == "template":
        print(json.dumps(fixture_labels(args.case).model_dump(), ensure_ascii=False, indent=2))
    elif args.command == "summary":
        print(json.dumps(summarize(args.output_dir), ensure_ascii=False, indent=2))
    else:
        if not args.reference_checked:
            raise ValueError("Listen to the recording and check its reference text and expected slots first; then add --reference-checked")
        labels = (fixture_labels(args.case) if args.case else
                  Labels.model_validate(json.loads(args.labels.read_text(encoding="utf-8")))).model_dump()
        if not args.audio.is_file() or not 0 < args.audio.stat().st_size <= 4_000_000:
            raise ValueError("Choose a nonempty recording smaller than 4 MB")
        services = LiveServices(key("GNANI_API_KEY", "Gnani API key (hidden): "),
                                key("GEMINI_API_KEY", "Gemini API key (hidden): "),
                                args.model, args.output_dir / "audio")
        print("Starting one STT request and one logical extraction (up to 3 HTTP attempts on 503). No email or TTS.", flush=True)
        result, path = run_recording(labels, args.audio, services, args.output_dir)
        print(json.dumps({"status": result["status"], "stage": result["stage"],
                          "totals": result["scoring"]["totals"],
                          "transcription_score": result["transcription_score"]}, ensure_ascii=False, indent=2))
        print(f"Saved evaluation: {path}")
        if result["status"] != "success":
            raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError):
        raise SystemExit("Evaluation could not start. Check the case, labels, recording path and reference-check flag; no error input is echoed.") from None
    except (KeyboardInterrupt, EOFError):
        raise SystemExit("Cancelled. Check saved attempts before starting again.") from None
