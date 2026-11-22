"""Provider-independent interfaces used by the pipeline and eval harness."""

import time
from dataclasses import dataclass
from typing import Protocol, TypedDict


class Message(TypedDict):
    role: str
    content: str


class GenerationOptions(TypedDict):
    model: str
    temperature: float
    max_tokens: int
    stream: bool
    function_call: str


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    usage: dict[str, int]
    finish_reason: str | None
    request_id: str | None


class ApiError(Exception):
    def __init__(self, stage: str, code: str | int, request_id: str | None = None):
        super().__init__(f"{stage}: {code}")
        self.details = {"stage": stage, "code": code, "request_id": request_id}


class Deadline:
    def __init__(self, seconds: float, *, clock=time.monotonic):
        self.clock = clock
        self.end = clock() + seconds

    def remaining(self, stage: str, cap: float) -> float:
        remaining = min(cap, self.end - self.clock())
        if remaining <= 0:
            raise ApiError(stage, "deadline_exceeded")
        return remaining


class Generator(Protocol):
    def generate(
        self,
        messages: list[Message],
        options: GenerationOptions,
        deadline: Deadline,
        *,
        timeout: float,
    ) -> Completion: ...


class ModelClient(Generator, Protocol):
    def count_tokens(
        self, model: str, pieces: list[str], deadline: Deadline
    ) -> list[int]: ...
