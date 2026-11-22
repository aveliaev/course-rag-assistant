import csv
import json
import re
import time
from datetime import datetime

import psycopg
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client import models as qm
from qdrant_client.http.exceptions import ApiException, ResponseHandlingException

from fkn_assistant.config import PROFILE_CONTEXT, RESOURCES
from fkn_assistant.forms import Sandbox, english, result
from fkn_assistant.index import MANIFEST, URL, Encoder, sparse
from fkn_assistant.model_client import (
    ApiError,
    Deadline,
    GenerationOptions,
    ModelClient,
)
from fkn_assistant.providers.gigachat import MODEL
from fkn_assistant.rag_answer import RagAnswer

PROMPT = (RESOURCES / "rag_prompt.txt").read_text()
OPTIONS: GenerationOptions = {
    "model": MODEL,
    "temperature": 0.1,
    "max_tokens": 250,
    "stream": False,
    "function_call": "none",
}
PERIOD = re.compile(r"\b(20\d\d)\s*[/–-]\s*(20\d\d|\d{2})\b")
COURSE = re.compile(
    r"пуд|формул[аеуы].{0,22}оцен|(?:оценк|балл|аттестаци).{0,45}[«\"]|из чего складывается|grading|syllabus|final grade|assessment.{0,35}course",
    re.I,
)


def period_for(text, followup=False):
    match = PERIOD.search(text)
    if not followup and not re.search(
        r"изучал|изучала|проходил|проходила|повторно изучаю|я учусь|я изучаю|мой период|период изучения|took|studied|studying|enrolled in",
        text,
        re.I,
    ):
        return None
    if match and int(match[2][-2:]) == (int(match[1]) + 1) % 100:
        return f"{match[1]}/{int(match[1]) + 1}"
    return None


def eq(key, value):
    return qm.FieldCondition(key=key, match=qm.MatchValue(value=value))


class Search:
    def __init__(self, repo):
        self.index = json.loads(MANIFEST.read_text())
        self.encoder = Encoder()
        self.client = QdrantClient(url=URL, timeout=3)
        if (
            self.client.count(self.index["collection"], exact=True).count
            != self.index["chunks"]
        ):
            raise ValueError("Индекс не соответствует manifest")
        with (repo / "tmp_dataset/programs/programs.csv").open() as f:
            self.programs = list(csv.DictReader(f))

        with (repo / "tmp_dataset/registry.csv").open() as f:
            self.syllabus_urls = {
                r["source_url"].rstrip("/"): (r["doc_id"], r["academic_year"])
                for r in csv.DictReader(f)
                if r["doc_kind"] == "syllabus" and r["source_url"]
            }

    def linked_syllabus(self, text):
        links = re.findall(r"https?://[^\s<>]+", text)
        resolved = {
            self.syllabus_urls[url.rstrip("/.,;)")]
            for url in links
            if url.rstrip("/.,;)") in self.syllabus_urls
        }
        return next(iter(resolved)) if len(resolved) == 1 else None

    def retrieve(self, question, profile, period, deadline=None):
        programs = [
            r["program_id"]
            for r in self.programs
            if r["name"].casefold() == profile["educational_program"].casefold()
            and r["campus"] == profile["campus"]
            and profile["level"] in r["level"]
        ]
        scopes = [
            qm.Filter(
                must=[
                    eq("scope", "university"),
                    qm.IsEmptyCondition(is_empty=qm.PayloadField(key="program_ids")),
                ]
            )
        ]
        if len(programs) == 1:
            scopes.append(eq("program_ids", programs[0]))
        current = qm.Filter(
            must=[eq("is_current", "true")], must_not=[eq("doc_kind", "syllabus")]
        )
        versions = [current]
        linked = self.linked_syllabus(question)
        if linked:
            versions.append(
                qm.Filter(
                    must=[eq("doc_id", linked[0]), eq("academic_year", linked[1])]
                )
            )
        elif period:
            versions.append(
                qm.Filter(
                    must=[eq("doc_kind", "syllabus"), eq("academic_year", period)]
                )
            )
        levels = {
            "Бакалавриат": "Бакалавриат/специалитет",
            "Магистратура": "Магистратура",
        }
        allowed_levels = [eq("level", "")]
        if profile["level"] in levels:
            allowed_levels.append(eq("level", levels[profile["level"]]))
        condition = qm.Filter(
            must=[
                qm.Filter(should=scopes),
                qm.Filter(should=versions),
                qm.Filter(should=allowed_levels),
                qm.Filter(
                    should=[
                        eq("intake_year", ""),
                        eq("intake_year", str(profile["admission_year"])),
                    ]
                ),
            ]
        )
        dense = self.encoder.encode(["query: " + question])[0].tolist()
        both = [
            qm.Prefetch(using="dense", query=dense, limit=20, filter=condition),
            qm.Prefetch(
                using="bm25", query=sparse(question), limit=20, filter=condition
            ),
        ]
        client = self.client
        if deadline is not None:
            timeout = deadline.remaining("search", 3)
            if timeout < 3:
                client = QdrantClient(url=URL, timeout=timeout)
        try:
            found = client.query_points(
                self.index["collection"],
                prefetch=both,
                query=qm.FusionQuery(fusion=qm.Fusion.RRF),
                limit=20,
                with_payload=True,
                timeout=3 if client is self.client else None,
            )
        finally:
            if client is not self.client:
                client.close()
        if deadline is not None:
            deadline.remaining("search", 3)
        return [dict(item.payload, score=item.score) for item in found.points]


class Exhausted(Exception):
    pass


class Steps:
    def __init__(self, limit):
        self.limit = limit
        self.log = []

    def take(self, name):
        if len(self.log) >= self.limit:
            raise Exhausted
        self.log.append(name)


class Rag:
    def __init__(
        self,
        search,
        client: ModelClient | None,
        sandbox=None,
        threshold=0.5,
        planning=False,
    ):
        self.search = search
        self.client = client
        self.sandbox = sandbox or Sandbox()
        self.threshold = threshold
        self.planning = planning

    def turn(
        self, space, session, profile, text, now, button=None, limit=None, fail=None
    ):
        start = time.monotonic()
        deadline = Deadline(15)
        steps = Steps(limit if limit is not None else (7 if self.planning else 6))
        trace = {
            "steps": steps.log,
            "retrieved": [],
            "context": [],
            "model": None,
            "usage": {},
            "calls": 0,
            "error": None,
        }
        key = (space, session, str(profile["id"]))
        en = english(text)
        try:
            steps.take("profile")
            try:
                clock = datetime.fromisoformat(now)
            except (TypeError, ValueError):
                return result(
                    "refuse", "rag_answer", "Некорректная дата запроса."
                ), trace
            if (
                len(text) > 2000
                or not profile.get("is_synthetic")
                or clock.tzinfo is None
            ):
                return result(
                    "refuse", "rag_answer", "Некорректный запрос или профиль."
                ), trace
            form_args = {}
            if self.planning and not button and text.strip():
                from fkn_assistant.planner import interpret

                steps.take("plan")
                trace["plan"] = {"calls": 0}
                form_args["interpretation"] = interpret(
                    self.client, text, clock, deadline, trace["plan"]
                )
            steps.take("forms")
            form = self.sandbox.handle(
                key,
                profile,
                clock,
                text,
                button,
                fail == "schedule",
                fail == "submit",
                deadline=deadline,
                **form_args,
            )
            if form is not None:
                return form, trace
            steps.take("history")
            history = self.sandbox.history(key, clock, deadline=deadline)
            followup = bool(
                history
                and (
                    "период изучения" in history[-1][1].lower()
                    or "academic year did you" in history[-1][1]
                )
                and len(text) < 100
            )
            period = period_for(text, followup)
            query = text
            linked = self.search.linked_syllabus(text)
            if followup and (period or linked):
                query = history[-1][0] if not linked else history[-1][0] + " " + text
            steps.take("search")
            if fail == "search":
                raise ApiError("search", "search_unavailable")
            hits = self.search.retrieve(query, profile, period, deadline)
            trace["retrieved"] = [
                {
                    k: h[k]
                    for k in ("citation_id", "doc_id", "clause_id", "version", "score")
                }
                for h in hits
            ]
            if COURSE.search(query) and not (period or linked):
                response = result(
                    "clarify",
                    "rag_answer",
                    "Which academic year did you take this course in?"
                    if en
                    else "Уточни фактический период изучения дисциплины (например, 2025/2026) или пришли ссылку на ПУД.",
                )
            elif not hits or hits[0]["score"] < self.threshold:
                response = result(
                    "refuse",
                    "rag_answer",
                    "I could not find an applicable source."
                    if en
                    else "Не нашёл применимого правила. Уточни вопрос или обратись в учебный офис своей программы.",
                )
            else:
                steps.take("context")
                response = self.generate(
                    text, profile, now, history, hits[:5], steps, trace, deadline
                )
            self.sandbox.remember(
                key, clock, text, response["answer"], deadline=deadline
            )
            return response, trace
        except Exhausted as exc:
            trace["error"] = {"stage": "budget", "code": str(exc) or "step_limit"}
            if str(exc) == "context_limit":
                return result(
                    "refuse", "rag_answer", "Не удалось уместить источники в контекст."
                ), trace
            return result(
                "refuse",
                "rag_answer",
                "The step limit was reached."
                if en
                else "Достигнут лимит шагов. Заявка не отправлена.",
            ), trace
        except (
            ApiError,
            ApiException,
            ResponseHandlingException,
            psycopg.Error,
            TimeoutError,
        ) as exc:
            err = (
                exc.details
                if isinstance(exc, ApiError)
                else {"stage": steps.log[-1], "code": type(exc).__name__}
            )
            trace["error"] = err
            if button and steps.log[-1] == "forms":
                return result(
                    "temporary_error",
                    "rag_answer",
                    "Статус операции уточняется. Повтори действие с той же карточкой.",
                ), trace
            if err["code"] == "deadline_exceeded":
                return result(
                    "refuse", "rag_answer", "Истекло время обработки запроса."
                ), trace
            return result(
                "refuse",
                "rag_answer",
                "Service temporarily unavailable."
                if en
                else "Сервис временно недоступен. Не удалось проверить результат.",
            ), trace
        finally:
            if plan := trace.get("plan"):
                trace["calls"] += plan["calls"]
                plan_usage = plan.get("usage", {})
                trace["answer_model"] = trace["model"]
                trace["answer_usage"] = trace["usage"]
                trace["usage"] = {
                    k: (trace["answer_usage"].get(k) or 0) + (plan_usage.get(k) or 0)
                    for k in trace["answer_usage"].keys() | plan_usage.keys()
                }
                trace["model"] = trace["model"] or plan.get("model")
            trace["latency_sec"] = round(time.monotonic() - start, 4)

    def generate(self, text, profile, now, history, hits, steps, trace, deadline):
        # Count separate bounded pieces with the provider tokenizer; reserve chat framing overhead.
        base = json.dumps(
            {
                "question": text,
                "now": now,
                "profile": {k: profile[k] for k in PROFILE_CONTEXT},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        previous = [json.dumps(pair, ensure_ascii=False) for pair in history]
        excerpts = [
            f"S{i} | {h['title']} | {h['clause_id']} | {h['version']}\n{h['text']}"
            for i, h in enumerate(hits, 1)
        ]
        pieces = [PROMPT, base, *previous, *excerpts]
        sizes = self.client.count_tokens(MODEL, pieces, deadline)
        history_sizes = sizes[2 : 2 + len(previous)]
        context = sizes[2 + len(previous) :]
        prefix = sizes[0] + sizes[1] + sum(history_sizes) + 80
        while previous and (
            sum(history_sizes) + sizes[1] > 400 or prefix + sum(context) > 2900
        ):
            previous.pop(0)
            prefix -= history_sizes.pop(0)
        while context and (sum(context) > 2000 or prefix + sum(context) > 2900):
            context.pop()
        if not context or prefix > 2900:
            raise Exhausted("context_limit")
        used = hits[: len(context)]
        trace["context"] = used
        trace["input_budget"] = {
            "system": sizes[0],
            "input": sizes[1],
            "history": sum(history_sizes),
            "sources": sum(context),
            "framing_reserve": 80,
        }
        content = "\n".join(
            [base, *previous, "UNTRUSTED_HSE_CONTENT", *excerpts[: len(context)]]
        )
        steps.take("generate")
        deadline.remaining("chat", 12)
        messages = [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": content},
        ]
        trace["calls"] = 1
        completion = self.client.generate(messages, OPTIONS, deadline, timeout=12)
        trace.update(
            raw_model_output=completion.text,
            model=completion.model,
            usage=completion.usage,
            request_id=completion.request_id,
            finish_reason=completion.finish_reason,
        )
        try:
            obj = RagAnswer.from_response(completion.text)
        except ValidationError as exc:
            trace["validation_error"] = {
                "stage": "schema",
                "codes": [issue["type"] for issue in exc.errors(include_input=False)],
            }
            obj = None
        ids = []
        if obj is not None:
            ids = [int(label[1:]) - 1 for label in obj.citations]
            if any(i >= len(used) for i in ids) or (
                not ids and obj.status in ("answer", "answer_partial")
            ):
                trace["validation_error"] = {
                    "stage": "citations",
                    "codes": ["missing_or_out_of_context"],
                }
                obj = None
        trace["model_schema_and_citations_ok"] = obj is not None
        if obj is None:
            ids = [0]
            answer = result("answer_partial", "rag_answer", used[0]["text"][:740])
            trace["fallback"] = "extractive"
        else:
            answer = result(obj.status, "rag_answer", obj.answer)
        answer["citations"] = [
            {
                k: used[i][k]
                for k in (
                    "doc_id",
                    "clause_id",
                    "version",
                    "source_url",
                    "path",
                    "citation_id",
                )
            }
            for i in ids
        ]
        return answer
