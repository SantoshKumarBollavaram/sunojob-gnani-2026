"""Evidence and internal-consistency checks; these are not semantic proofs."""

import hashlib
import json

from .models import Extraction, SourceTurn


class CardValidationError(ValueError):
    pass


def canonical(value):
    return " ".join(value.split()).casefold()


def signature(instruction):
    return (instruction.kind, instruction.subject, canonical(instruction.value))


def resolve_evidence(evidence, turns):
    source = turns.get(evidence.turn_id)
    if source is None:
        raise CardValidationError(f"Unknown source turn: {evidence.turn_id}")
    start = -1
    for _ in range(evidence.occurrence + 1):
        start = source.text.find(evidence.quote, start + 1)
        if start < 0:
            raise CardValidationError(
                f"Evidence is absent from {evidence.turn_id}, or occurrence is invalid"
            )
    return {
        "turn_id": source.id,
        "quote": evidence.quote,
        "start": start,
        "end": start + len(evidence.quote),
        "offset_unit": "unicode_code_points",
    }


def validate_card(extraction: Extraction, sources: list[SourceTurn]):
    if not sources:
        raise CardValidationError("At least one source turn is required")
    turns = {turn.id: turn for turn in sources}
    if len(turns) != len(sources):
        raise CardValidationError("Source turn IDs must be unique")
    if len(extraction.instructions) == 0 and len(extraction.questions) == 0:
        raise CardValidationError("Empty extraction must include a clarification question")
    ids, seen, singles = {}, set(), set()
    spans = []
    for item in extraction.instructions:
        if item.id in ids:
            raise CardValidationError("Instruction IDs must be unique")
        ids[item.id] = item
        sig = signature(item)
        if sig in seen:
            raise CardValidationError("Duplicate active instruction")
        seen.add(sig)
        slot = (item.kind, item.subject)
        if item.kind in {"quantity", "deadline", "budget"}:
            if slot in singles:
                raise CardValidationError(f"Multiple active values for {item.kind}/{item.subject}")
            singles.add(slot)
        for evidence in item.evidence:
            spans.append({"instruction_id": item.id, **resolve_evidence(evidence, turns)})

    corrected = set()
    for index, correction in enumerate(extraction.corrections):
        item = ids.get(correction.instruction_id)
        if item is None:
            raise CardValidationError("Correction refers to a nonexistent instruction")
        if correction.instruction_id in corrected:
            raise CardValidationError("Use one net correction per instruction in this checkpoint")
        corrected.add(correction.instruction_id)
        if canonical(correction.before) == canonical(correction.after):
            raise CardValidationError("Correction must change the value")
        if canonical(correction.after) != canonical(item.value):
            raise CardValidationError("Correction after-value does not match the active instruction")
        if any(other.kind == item.kind and other.subject == item.subject
               and canonical(other.value) == canonical(correction.before)
               for other in extraction.instructions):
            raise CardValidationError("Withdrawn correction value is still active")
        for evidence in correction.evidence:
            spans.append({"correction_index": index, **resolve_evidence(evidence, turns)})

    source_json = json.dumps([s.model_dump() for s in sources], ensure_ascii=False,
                             sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": 1,
        "status": "draft",
        "customer_confirmed": False,
        "owner_confirmed": False,
        "sources": [s.model_dump() for s in sources],
        "source_sha256": hashlib.sha256(source_json.encode()).hexdigest(),
        "extraction": extraction.model_dump(),
        "resolved_evidence": spans,
        "validation": "structure, evidence existence and internal correction consistency only",
        "requires_human_review": True,
    }
