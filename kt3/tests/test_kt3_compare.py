import json
import threading
import unittest
import uuid
from datetime import datetime, timedelta
from http.server import HTTPServer

import httpx

from fkn_assistant.forms import Sandbox
from fkn_assistant.model_client import Completion
from fkn_assistant.rag import Rag
from fkn_assistant.sandbox_api import Gateway, handler_for
from test_b0 import SearchFixture


NOW = datetime.fromisoformat("2026-10-27T10:00:00+03:00")


def profile():
    return {
        "id": "test-" + uuid.uuid4().hex,
        "is_synthetic": True,
        "status": "studying",
        "study_group": "DEMO",
        "full_name": "Фикстура",
        "level": "Бакалавриат",
        "educational_program": "ПМИ",
        "faculty": "ФКН",
        "campus": "Москва",
        "admission_year": 2024,
        "course": 3,
    }


class PlanningFixture:
    def __init__(self, plan):
        self.plan = plan
        self.calls = 0

    def count_tokens(self, model, pieces, deadline):
        return [10] * len(pieces)

    def generate(self, messages, options, deadline, *, timeout):
        self.calls += 1
        answer = (
            self.plan
            if options["max_tokens"] == 120
            else {"status": "answer", "answer": "Половина", "citations": ["S1"]}
        )
        return Completion(
            json.dumps(answer, ensure_ascii=False),
            "fixture",
            {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            "stop",
            "fixture",
        )


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.profile = profile()
        self.space = self.profile["id"]
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.db.close)

    def test_b1_ignores_fabricated_fields_and_only_trusted_button_submits(self):
        client = PlanningFixture(
            {
                "route": "temp_pass",
                "spans": {"building": "DEMO_A", "reason": "забыл", "date": "завтра"},
            }
        )
        app = Rag(SearchFixture(), client, sandbox=self.sandbox, planning=True)
        first, trace = app.turn(
            self.space,
            "forms",
            self.profile,
            "Пропуск забыл, нужен вход завтра.",
            NOW.isoformat(),
        )
        self.assertEqual(first["missing_fields"], ["building"])
        self.assertEqual(trace["plan"]["accepted_fields"], ["date", "reason"])
        ready, _ = app.turn(
            self.space, "forms", self.profile, "DEMO_A", NOW.isoformat()
        )
        self.assertEqual(ready["status"], "draft_ready")
        self.assertEqual(ready["fields"]["date"], "2026-10-28")
        key = (self.space, "forms", self.profile["id"])
        self.assertFalse(self.sandbox.evidence(key)["applications"])
        submitted, trace = app.turn(
            self.space,
            "forms",
            self.profile,
            "",
            NOW.isoformat(),
            button={
                "action": "confirm",
                **{k: ready[k] for k in ("draft_id", "revision", "confirmation")},
            },
        )
        self.assertEqual(submitted["status"], "submitted")
        self.assertEqual(trace["calls"], 0)
        self.assertEqual(client.calls, 2)
        self.assertEqual(len(self.sandbox.evidence(key)["applications"]), 1)

    def test_b1_counts_both_generations_and_uses_shared_retrieval(self):
        client = PlanningFixture({"route": "rag_answer", "spans": {}})
        search = SearchFixture()
        app = Rag(search, client, sandbox=self.sandbox, planning=True)
        reply, trace = app.turn(
            self.space,
            "answer",
            self.profile,
            "Как считается итог? Я изучаю в 2025/26.",
            NOW.isoformat(),
        )
        self.assertEqual(reply["status"], "answer")
        self.assertEqual(reply["citations"][0]["version"], "2025/2026")
        self.assertEqual(trace["calls"], 2)
        self.assertEqual(trace["usage"]["total_tokens"], 10)
        self.assertEqual(len(trace["steps"]), 7)

    def test_http_staff_confirmation_is_scoped_and_idempotent(self):
        other = profile()
        profiles = {p["id"]: p for p in (self.profile, other)}
        now = [NOW]
        gateway = Gateway(self.sandbox, profiles, clock=lambda: now[0])
        auth = {"Authorization": "Bearer fixture-local-token"}
        with HTTPServer(
            ("127.0.0.1", 0), handler_for(gateway, "fixture-local-token")
        ) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{server.server_port}"
                ) as client:
                    path = "/v1/staff/preview"
                    data = {
                        "profile_id": self.profile["id"],
                        "request_id": "demo",
                        "class": "E1",
                        "summary": "Нужна консультация",
                    }
                    self.assertEqual(client.post(path, json=data).status_code, 401)
                    self.assertEqual(
                        client.post(
                            path, json=data | {"class": "E5"}, headers=auth
                        ).status_code,
                        422,
                    )
                    self.assertEqual(
                        client.post(
                            "/v1/forms/turn",
                            json={
                                "profile_id": self.profile["id"],
                                "session_id": "s",
                                "text": "Оформи временный пропуск завтра в DEMO_A, свой забыл",
                            },
                            headers=auth,
                        ).json()["status"],
                        "draft_ready",
                    )
                    card = client.post(path, json=data, headers=auth).json()
                    check = "select ticket_id from kt3_staff_cards where id=%s"
                    self.assertIsNone(
                        self.sandbox.db.execute(check, (card["card_id"],)).fetchone()[0]
                    )
                    payload = {
                        "profile_id": self.profile["id"],
                        **{key: card[key] for key in ("card_id", "confirmation")},
                    }
                    confirm = "/v1/staff/confirm"
                    self.assertEqual(
                        client.post(
                            confirm,
                            json=payload | {"profile_id": other["id"]},
                            headers=auth,
                        ).status_code,
                        403,
                    )
                    now[0] += timedelta(minutes=16)
                    self.assertEqual(
                        client.post(confirm, json=payload, headers=auth).status_code,
                        409,
                    )
                    now[0] = NOW
                    sent = client.post(confirm, json=payload, headers=auth)
                    repeated = client.post(confirm, json=payload, headers=auth)
                    self.assertEqual(
                        (sent.status_code, repeated.status_code), (201, 200)
                    )
                    self.assertEqual(sent.json(), repeated.json())
                    self.assertEqual(
                        client.post(path, json=data, headers=auth).status_code, 409
                    )

                    def offer(request, summary):
                        card = client.post(
                            path,
                            json=data | {"request_id": request, "summary": summary},
                            headers=auth,
                        ).json()
                        return {
                            "profile_id": self.profile["id"],
                            **{k: card[k] for k in ("card_id", "confirmation")},
                        }

                    old = offer("edit", "Черновая сводка")
                    changed = offer("edit", "Актуальная сводка")
                    self.assertEqual(
                        client.post(confirm, json=old, headers=auth).status_code, 409
                    )
                    self.assertEqual(
                        client.post(confirm, json=changed, headers=auth).status_code,
                        201,
                    )
                    self.assertEqual(
                        client.post(
                            confirm, json=offer("next", "Следующий"), headers=auth
                        ).status_code,
                        201,
                    )
                    blocked = client.post(
                        confirm, json=offer("fourth", "Четвёртый"), headers=auth
                    )
                    self.assertEqual(blocked.json(), {"code": "weekly_limit_reached"})
            finally:
                server.shutdown()
                thread.join()
