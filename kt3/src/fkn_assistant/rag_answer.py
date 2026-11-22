"""Validation at the boundary between the language model and the application."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Citation = Annotated[str, Field(pattern=r"^S[1-5]$")]


class RagAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["answer", "answer_partial", "clarify", "refuse"]
    answer: Annotated[str, Field(min_length=1, max_length=800)]
    citations: list[Citation] = Field(json_schema_extra={"uniqueItems": True})

    @field_validator("citations")
    @classmethod
    def unique_citations(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("Повторяющиеся метки источников")
        return values

    @classmethod
    def from_response(cls, text: str) -> "RagAnswer":
        return cls.model_validate_json(
            re.sub(r"^\s*`{3}(?:json)?\s*|\s*`{3}\s*$", "", text)
        )
