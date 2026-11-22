"""One B0 turn on the local synthetic session."""

import argparse
import json
from pathlib import Path

from fkn_assistant.config import REPO, RESOURCES
from fkn_assistant.evaluation.dataset import snapshot
from fkn_assistant.providers.gigachat import GigaChat
from fkn_assistant.rag import Rag, Search
from fkn_assistant.retrieval_config import calibration


def main():
    parser = argparse.ArgumentParser(
        description="Вопрос к B0 или действие с карточкой песочницы."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--question")
    group.add_argument(
        "--button-json",
        type=Path,
        help="JSON события action, draft_id, revision, confirmation",
    )
    parser.add_argument("--session", default="demo")
    parser.add_argument("--student", default="demo-student-001")
    parser.add_argument("--now", default="2026-10-27T10:00:00+03:00")
    parser.add_argument("--repo", type=Path, default=REPO)
    args = parser.parse_args()
    profiles = {p["id"]: p for p in json.loads(snapshot(args.repo, "students.json"))}
    if args.student not in profiles:
        parser.error("Требуется ID синтетического профиля КТ2.")
    event = json.loads(args.button_json.read_text()) if args.button_json else None
    app = Rag(
        Search(args.repo),
        GigaChat(REPO / ".env", RESOURCES / "russian_trusted_root_ca_pem.crt"),
        threshold=calibration()["threshold"],
    )
    answer, trace = app.turn(
        "local-demo",
        args.session,
        profiles[args.student],
        args.question or "",
        args.now,
        event,
    )
    print(
        json.dumps(
            {
                "answer": answer,
                "steps": trace["steps"],
                "elapsed_seconds": trace["latency_sec"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
