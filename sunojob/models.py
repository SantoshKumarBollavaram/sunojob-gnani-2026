"""Domain-independent proposed instructions, with explicit source references."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Subject = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
Kind = Literal["task", "prohibition", "permission_required", "quantity", "deadline", "budget", "constraint"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SourceTurn(StrictModel):
    id: Identifier
    speaker: Literal["customer", "owner"] = "customer"
    language: Literal["en-IN", "te-IN", "hi-IN", "mixed", "unknown"] = "unknown"
    text: Annotated[str, StringConstraints(min_length=1, max_length=20000)]

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Source text cannot be blank")
        return value


class Evidence(StrictModel):
    turn_id: Identifier
    quote: Text
    occurrence: Annotated[int, Field(ge=0)] = 0

    @field_validator("quote")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Evidence cannot be whitespace")
        return value


class Instruction(StrictModel):
    id: Identifier
    kind: Kind
    subject: Subject
    value: Text
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=10)]

    @field_validator("value")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Instruction value cannot be blank")
        return value


class Correction(StrictModel):
    instruction_id: Identifier
    before: Text
    after: Text
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=10)]


class Question(StrictModel):
    text: Text
    reason: Literal["missing", "conflict", "unclear"]


class Extraction(StrictModel):
    instructions: Annotated[list[Instruction], Field(max_length=50)]
    corrections: Annotated[list[Correction], Field(max_length=30)]
    questions: Annotated[list[Question], Field(max_length=20)]
