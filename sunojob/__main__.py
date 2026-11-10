"""Checkpoint CLI: labelled demo, validated model extraction and evaluation."""

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile

from pydantic import ValidationError

from .evaluation import evaluate
from .models import Extraction, SourceTurn
from .providers import DEFAULT_GEMINI_MODEL, GeminiExtractor, ProviderError
from .validation import validate_card


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "fixtures" / "catering_cases.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def get_case(case_id):
    for case in load_json(CASES)["cases"]:
        if case["id"] == case_id:
            return case
    raise ValueError(f"Unknown case: {case_id}")


def write_result(data):
    folder = ROOT / ".local" / "sunojob-core"
    folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="result-", suffix=".json", dir=folder)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return name


def display_card(card):
    print("\nDRAFT — requires review; neither party has confirmed.")
    for item in card["extraction"]["instructions"]:
        print(f"  [{item['kind']}] {item['subject']}: {item['value']}")
        for evidence in item["evidence"]:
            print(f"    Source {evidence['turn_id']}: {evidence['quote']}")
    for correction in card["extraction"]["corrections"]:
        print(f"  Correction: {correction['before']} -> {correction['after']}")
    for question in card["extraction"]["questions"]:
        print(f"  Needs clarification: {question['text']}")


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Validate a labelled fixture; no AI/API call")
    demo.add_argument("--case", default="catering_en_correction")
    extract = commands.add_parser("extract", help="Extract a draft; at most 3 HTTP attempts on 503")
    source = extract.add_mutually_exclusive_group(required=True)
    source.add_argument("--case")
    source.add_argument("--gnani-report", type=Path)
    source.add_argument("--text-file", type=Path)
    extract.add_argument("--language", default="unknown",
                         choices=["en-IN", "te-IN", "hi-IN", "mixed", "unknown"])
    extract.add_argument("--model", default=os.environ.get("SUNOJOB_GEMINI_MODEL", DEFAULT_GEMINI_MODEL))
    scoring = commands.add_parser("evaluate", help="Score one saved extraction against its fixture")
    scoring.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "demo":
        case = get_case(args.case)
        sources = [SourceTurn.model_validate(s) for s in case["sources"]]
        extraction = Extraction.model_validate(case["gold_extraction"])
        card = validate_card(extraction, sources)
        data = {"case_id": case["id"], "provider": "labelled_fixture_not_AI",
                "model": None, "card": card}
        print("OFFLINE FIXTURE DEMO — this is not a model prediction or accuracy result.")
        display_card(card)
    elif args.command == "extract":
        case_id = args.case
        if case_id:
            sources = [SourceTurn.model_validate(s) for s in get_case(case_id)["sources"]]
        else:
            if args.gnani_report:
                text = load_json(args.gnani_report).get("transcript")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("The Gnani report contains no transcript")
            else:
                text = args.text_file.read_text(encoding="utf-8")
            sources = [SourceTurn(id="turn-1", text=text, language=args.language)]
        # This also catches duplicate IDs before a paid request.
        if len({s.id for s in sources}) != len(sources):
            raise ValueError("Duplicate source turn IDs")
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            key = getpass.getpass("Gemini API key (hidden; different from Gnani): ").strip()
        print(f"Extracting using {args.model} (at most 3 HTTP attempts for 503)...", flush=True)
        data = {"case_id": case_id, "provider": "gemini", "model": args.model,
                "sources": [s.model_dump() for s in sources]}
        extractor = None
        try:
            extractor = GeminiExtractor(key, args.model)
            extraction = extractor.extract(sources)
            card = validate_card(extraction, sources)
        except (ValidationError, ValueError, ProviderError) as exc:
            if isinstance(exc, ValidationError):
                reason = "Schema validation failed: " + ", ".join(
                    ".".join(map(str, e["loc"])) for e in exc.errors(include_input=False)
                )
            else:
                reason = str(exc)
            data["error"] = reason
            data["http_attempts"] = extractor.attempts if extractor is not None else []
            failed_path = write_result(data)
            raise ValueError(f"{reason}\nFailed attempt recorded: {failed_path}") from None
        data["card"] = card
        data["http_attempts"] = extractor.attempts
        data["model_returned"] = extractor.model_version
        display_card(card)
    else:
        saved = load_json(args.result)
        if saved.get("provider") != "gemini":
            raise ValueError("Use an actual model extraction result, not the labelled demo")
        if not saved.get("case_id"):
            raise ValueError("This result has no labelled case; assess it manually")
        case = get_case(saved["case_id"])
        saved_sources = saved.get("sources", saved.get("card", {}).get("sources"))
        if saved_sources != [SourceTurn.model_validate(s).model_dump() for s in case["sources"]]:
            raise ValueError("Saved sources differ from the labelled case")
        prediction = saved.get("card", {}).get("extraction")
        data = evaluate([case], {case["id"]: prediction})
        if saved.get("error"):
            data["recorded_attempt_error"] = saved["error"]
        print(json.dumps(data["totals"], ensure_ascii=False, indent=2))
        print("Strict matches only. Manually inspect missing and unmatched claims.")
    print(f"\nSaved result: {write_result(data)}")


if __name__ == "__main__":
    try:
        run()
    except ValidationError as exc:
        # Do not print arbitrary full model output or the entire input on failure.
        locations = [".".join(map(str, e["loc"])) for e in exc.errors(include_input=False)]
        print("FAILED: Schema validation at " + ", ".join(locations), file=sys.stderr)
        sys.exit(1)
    except (ValueError, ProviderError, OSError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.", file=sys.stderr)
        sys.exit(1)
