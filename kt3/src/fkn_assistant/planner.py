"""B1: propose a route and literal field spans, then normalize them in code."""

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fkn_assistant.config import RESOURCES
from fkn_assistant.forms import RULES, extract
from fkn_assistant.model_client import ApiError
from fkn_assistant.providers.gigachat import MODEL

PROMPT = (RESOURCES / "plan_prompt.txt").read_text()
OPTIONS = {
    "model": MODEL,
    "temperature": 0.1,
    "max_tokens": 120,
    "stream": False,
    "function_call": "none",
}
INPUT_LIMIT = 1400


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    route: Literal["temp_pass", "enrollment_certificate", "rag_answer"]
    spans: dict[str, str] = Field(max_length=4)


@dataclass(frozen=True)
class Interpretation:
    route: str | None
    fields: dict[str, str | int]


def interpret(client, text, now, deadline, trace):
    user = json.dumps({"message": text}, ensure_ascii=False)
    try:
        sizes = client.count_tokens(MODEL, [PROMPT, user], deadline)
        if sum(sizes) + 80 > INPUT_LIMIT:
            trace["fallback"] = "plan_input_limit"
            return None
        deadline.remaining("plan", 4)
        trace["calls"] = 1
        completion = client.generate(
            [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}],
            OPTIONS,
            deadline,
            timeout=4,
        )
        trace.update(
            model=completion.model,
            usage=completion.usage,
            request_id=completion.request_id,
        )
        plan = Plan.model_validate_json(completion.text)
    except ApiError as exc:
        if exc.details["code"] in (400, 401, 402, 403, 404, 429, "deadline_exceeded"):
            raise
        trace["fallback"] = exc.details["code"]
        return None
    except ValidationError:
        trace["fallback"] = "invalid_plan"
        return None
    trace["route"] = plan.route
    if plan.route == "rag_answer":
        return Interpretation(None, {})
    fields = {}
    for key in RULES[plan.route]["user_fields"]:
        span = plan.spans.get(key)
        if span and span in text:
            value = extract(plan.route, span, now).get(key)
            if value is not None:
                fields[key] = value
    trace["accepted_fields"] = sorted(fields)
    return Interpretation(plan.route, fields)
