"""Strict labelled-slot scorer. Unmatched claims require manual adjudication."""

from .models import Extraction, SourceTurn
from .validation import canonical, signature, validate_card


def expected_signature(item):
    return (item["kind"], item["subject"], canonical(item["value"]))


def score_case(case, prediction):
    expected = {expected_signature(item) for item in case["expected_instructions"]}
    restrictions = {item for item in expected if item[0] in {
        "prohibition", "permission_required", "budget", "constraint"
    }}
    expected_corrections = {
        (c["kind"], c["subject"], canonical(c["before"]), canonical(c["after"]))
        for c in case["expected_corrections"]
    }
    base = {
        "case_id": case["id"], "expected_instructions": len(expected),
        "expected_restrictions": len(restrictions),
        "expected_corrections": len(expected_corrections),
    }
    try:
        if prediction is None:
            raise ValueError("No prediction supplied")
        extraction = Extraction.model_validate(prediction)
        sources = [SourceTurn.model_validate(turn) for turn in case["sources"]]
        validate_card(extraction, sources)
    except ValueError as exc:
        return {**base, "valid_card": False, "error": str(exc),
                "instructions_matched": 0, "restrictions_kept": 0,
                "corrections_applied": 0, "unmatched_claims": [],
                "questions_needed": bool(case.get("question_required")),
                "questions_present": False, "strict_case_pass": False,
                "missing_instructions": sorted(expected)}

    actual = {signature(item) for item in extraction.instructions}
    by_id = {item.id: item for item in extraction.instructions}
    actual_corrections = {
        (by_id[c.instruction_id].kind, by_id[c.instruction_id].subject,
         canonical(c.before), canonical(c.after)) for c in extraction.corrections
    }
    questions_needed = bool(case.get("question_required"))
    questions_present = bool(extraction.questions)
    return {
        **base, "valid_card": True,
        "instructions_matched": len(actual & expected),
        "restrictions_kept": len(actual & restrictions),
        "corrections_applied": len(actual_corrections & expected_corrections),
        "missing_instructions": sorted(expected - actual),
        "unmatched_claims": sorted(actual - expected),
        "unexpected_corrections": sorted(actual_corrections - expected_corrections),
        "questions_needed": questions_needed, "questions_present": questions_present,
        "strict_case_pass": actual == expected and actual_corrections == expected_corrections
            and (not questions_needed or questions_present),
    }


def evaluate(cases, predictions):
    case_ids = [case["id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Duplicate evaluation case IDs")
    unknown = set(predictions) - set(case_ids)
    if unknown:
        raise ValueError(f"Unknown prediction case IDs: {sorted(unknown)}")
    results = [score_case(case, predictions.get(case["id"])) for case in cases]
    totals = {
        "cases": len(results),
        "valid_cards": sum(r["valid_card"] for r in results),
        "strict_case_passes": sum(r["strict_case_pass"] for r in results),
        "failed_or_missing_cases": sum(not r["valid_card"] for r in results),
        "instructions_expected": sum(r["expected_instructions"] for r in results),
        "instructions_matched": sum(r["instructions_matched"] for r in results),
        "restrictions_expected": sum(r["expected_restrictions"] for r in results),
        "restrictions_kept": sum(r["restrictions_kept"] for r in results),
        "corrections_expected": sum(r["expected_corrections"] for r in results),
        "corrections_applied": sum(r["corrections_applied"] for r in results),
        "unmatched_claims_requiring_review": sum(len(r["unmatched_claims"]) for r in results),
        "invented_actions_confirmed_by_human": None,
    }
    return {
        "scoring": "strict canonical-slot matching; unmatched is not synonymous with invented",
        "limitations": [
            "An exact supporting quote does not prove the extracted meaning is correct.",
            "Synonyms or alternate canonical subjects can fail strict matching; review them manually.",
            "Clarification checks count presence, not semantic adequacy of the question.",
            "These are development fixtures, not evidence of real-world accuracy.",
        ],
        "totals": totals, "cases": results,
    }
