"""Smoke through the real eval CLI and local stores, with model replies from a fixture."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from fkn_assistant.evaluation import runner
from fkn_assistant.forms import RULES, route_for
from fkn_assistant.model_client import Completion
from fkn_assistant.planner import PROMPT


class FixtureClient:
    def __init__(self, *_):
        pass

    def count_tokens(self, model, pieces, deadline):
        return [len(piece) // 8 + 1 for piece in pieces]

    def generate(self, messages, options, deadline, *, timeout):
        if messages[0]["content"] == PROMPT:
            text = json.loads(messages[-1]["content"])["message"]
            route = route_for(text) or "rag_answer"
            fields = RULES.get(route, {}).get("user_fields", ())
            reply = {"route": route, "spans": {field: text for field in fields}}
        else:
            reply = {
                "status": "answer_partial",
                "answer": "Проверка подключения фикстуры.",
                "citations": ["S1"],
            }
        return Completion(
            json.dumps(reply, ensure_ascii=False),
            "fixture-not-live",
            {},
            "stop",
            "fixture",
        )

    def close(self):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    with patch.object(runner, "GigaChat", FixtureClient):
        runner.main(
            [
                "--variant",
                "rag-b1",
                "--dataset",
                "smoke",
                "--repeats",
                "1",
                "--output",
                str(output),
            ]
        )
    rows = [
        json.loads(path.read_text())
        for path in sorted((output / "responses").glob("*.json"))
    ]
    assert len(rows) == 20
    assert all(
        r["trace"].get("plan", {}).get("model") == "fixture-not-live" for r in rows
    )
    assert any(r["trace"]["calls"] == 2 for r in rows)
    assert all(r["error"] is None and r["checks"]["action_ok"] for r in rows)
    assert all(r["trace"]["calls"] <= 2 and len(r["trace"]["steps"]) <= 7 for r in rows)
    proof = {
        "variant": "rag-b1",
        "dataset": "dev smoke",
        "model_backend": "deterministic fixture, no provider calls",
        "retrieval_backend": "local Qdrant and full frozen corpus",
        "planned": 20,
        "completed": len(rows),
        "validated_plan": sum("route" in r["trace"]["plan"] for r in rows),
        "two_model_steps": sum(r["trace"]["calls"] == 2 for r in rows),
        "run_errors": sum(bool(r["error"]) for r in rows),
        "unexpected_writes": sum(not r["checks"]["action_ok"] for r in rows),
        "measurement_kind": "integration only, not model quality or latency evidence",
    }
    (output / "integration-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
