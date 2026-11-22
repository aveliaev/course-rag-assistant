import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from fkn_assistant.config import RESOURCES
from fkn_assistant.forms import Sandbox
from fkn_assistant.model_client import ApiError, Completion, Deadline
from fkn_assistant.providers.gigachat import GigaChat
from fkn_assistant.rag import OPTIONS, Rag
from fkn_assistant.rag_answer import RagAnswer


class SchemaTests(unittest.TestCase):
    def test_fences_and_invalid_values(self):
        payload = {"status": "answer", "answer": "Текст", "citations": ["S1"]}
        text = json.dumps(payload)
        self.assertEqual(RagAnswer.from_response(text).citations, ["S1"])
        self.assertEqual(
            RagAnswer.from_response(
                chr(96) * 3 + "json\n" + text + "\n" + chr(96) * 3
            ).answer,
            "Текст",
        )
        for override in (
            {"status": "draft_ready"},
            {"answer": "a" * 801},
            {"answer": 1},
            {"citations": ["S1", "S1"]},
            {"citations": ["S6"]},
            {"extra": 1},
        ):
            with self.subTest(override=override), self.assertRaises(ValidationError):
                RagAnswer.from_response(json.dumps(payload | override))


class SdkTests(unittest.TestCase):
    def test_sdk_request_usage_and_http_error_without_retry(self):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.path, "/v1/chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer fixture")
            self.assertTrue(request.headers["rquid"])
            self.assertEqual(
                json.loads(request.content), OPTIONS | {"messages": messages}
            )
            if len(requests) > 1:
                return httpx.Response(429)
            return httpx.Response(
                200,
                headers={"x-request-id": "fixture"},
                json={
                    "model": "GigaChat-3-Ultra:mock",
                    "choices": [
                        {"message": {"content": "fixture"}, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "total_tokens": 5,
                        "precached_prompt_tokens": 7,
                    },
                },
            )

        messages = [{"role": "user", "content": "Тест"}]
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / ".env"
            with patch.dict("os.environ", {"GIGACHAT_CREDENTIALS": "fixture"}):
                client = GigaChat(env, RESOURCES / "russian_trusted_root_ca_pem.crt")
            client.close()
            client.http = httpx.Client(transport=httpx.MockTransport(handler))
            try:
                with patch.object(
                    client,
                    "post",
                    return_value=(
                        {"access_token": "fixture", "expires_at": 4_000_000_000_000},
                        "fixture",
                    ),
                ) as oauth:
                    completion = client.generate(
                        messages, OPTIONS, Deadline(15), timeout=12
                    )
                    self.assertEqual(completion.request_id, "fixture")
                    self.assertEqual(completion.usage["precached_prompt_tokens"], 7)
                    with self.assertRaises(ApiError) as error:
                        client.generate(messages, OPTIONS, Deadline(15), timeout=12)
                    self.assertEqual(error.exception.details["code"], 429)
                    oauth.assert_called_once()
                self.assertEqual(len(requests), 2)
            finally:
                client.close()

    def test_expired_deadline_stops_next_io(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"GIGACHAT_CREDENTIALS": "fixture"}):
                client = GigaChat(
                    Path(directory) / ".env",
                    RESOURCES / "russian_trusted_root_ca_pem.crt",
                )
            try:
                with patch.object(client, "post") as post:
                    with self.assertRaises(ApiError) as error:
                        client.count_tokens(OPTIONS["model"], ["fixture"], Deadline(0))
                    self.assertEqual(
                        error.exception.details["code"], "deadline_exceeded"
                    )
                    post.assert_not_called()
            finally:
                client.close()


class SearchFixture:
    def __init__(self):
        self.requests = []

    def linked_syllabus(self, text):
        return None

    def retrieve(self, question, profile, period, deadline):
        self.requests.append((question, period))
        if not period:
            return []
        return [
            {
                "title": "ПУД",
                "doc_id": "syllabus-2025",
                "clause_id": "1",
                "version": period,
                "text": "Экзамен составляет половину итоговой оценки.",
                "source_url": "https://example.com/syllabus",
                "path": "fixture",
                "citation_id": "syllabus-2025:1",
                "score": 1,
            }
        ]


class ClientFixture:
    def __init__(
        self, text='{"status":"answer","answer":"Половина","citations":["S1"]}'
    ):
        self.calls = 0
        self.text = text

    def count_tokens(self, model, pieces, deadline):
        return [10] * len(pieces)

    def generate(self, messages, options, deadline, *, timeout):
        self.calls += 1
        return Completion(self.text, "mock", {}, "stop", "fixture")


class RagTests(unittest.TestCase):
    def setUp(self):
        import uuid

        self.search = SearchFixture()
        self.client = ClientFixture()
        self.app = Rag(self.search, self.client, sandbox=Sandbox())
        self.addCleanup(self.app.sandbox.db.close)
        self.space = "test-" + uuid.uuid4().hex
        self.profile = dict(
            id="fixture",
            is_synthetic=True,
            status="studying",
            level="Бакалавриат",
            educational_program="ПМИ",
            faculty="ФКН",
            campus="Москва",
            admission_year=2024,
            course=3,
        )

    def turn(self, question, **options):
        return self.app.turn(
            self.space,
            "test",
            self.profile,
            question,
            "2026-10-27T10:00:00+03:00",
            **options,
        )

    def test_actual_period_is_taken_from_follow_up(self):
        question = "Какая формула оценки в ПУД дисциплины?"
        first, _ = self.turn(question)
        second, trace = self.turn("2025/2026")
        self.assertEqual(first["status"], "clarify")
        self.assertEqual(
            self.search.requests, [(question, None), (question, "2025/2026")]
        )
        self.assertEqual(second["citations"][0]["version"], "2025/2026")
        self.assertEqual(trace["calls"], 1)

    def test_search_failure_skips_generation(self):
        answer, trace = self.turn("Где опубликованы правила?", fail="search")
        self.assertEqual(answer["status"], "refuse")
        self.assertEqual(trace["error"]["code"], "search_unavailable")
        self.assertEqual(trace["calls"], 0)
        self.assertEqual(self.client.calls, 0)

    def test_expires_after_slow_tokenizer_and_skips_generation(self):
        start = [100.0]

        def count_tokens(model, pieces, deadline):
            start[0] += 16
            return [10] * len(pieces)

        self.client.count_tokens = count_tokens
        with patch(
            "fkn_assistant.rag.Deadline",
            side_effect=lambda seconds: Deadline(seconds, clock=lambda: start[0]),
        ):
            answer, trace = self.turn("Я изучал эту дисциплину в 2025/2026. Какой ПУД?")
        self.assertEqual(answer["status"], "refuse")
        self.assertEqual(trace["error"]["code"], "deadline_exceeded")
        self.assertEqual(trace["calls"], 0)
        self.assertEqual(self.client.calls, 0)

    def test_out_of_context_citation_falls_back(self):
        self.client.text = '{"status":"answer","answer":"Текст","citations":["S2"]}'
        answer, trace = self.turn("Я изучал эту дисциплину в 2025/2026. Какой ПУД?")
        self.assertEqual(answer["status"], "answer_partial")
        self.assertEqual(trace["validation_error"]["stage"], "citations")
        self.assertEqual(answer["citations"][0]["citation_id"], "syllabus-2025:1")


if __name__ == "__main__":
    unittest.main()
