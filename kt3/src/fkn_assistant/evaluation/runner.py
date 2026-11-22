#!/usr/bin/env python3
import argparse
import fcntl
import json
import math
import platform
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from fkn_assistant.config import BASE, PROFILE_CONTEXT, REPO, RESOURCES
from fkn_assistant.evaluation.dataset import (
    DATA_COMMIT,
    FORM_CONTEXT,
    digest,
    fixed_sample,
    snapshot,
    write_json,
)
from fkn_assistant.model_client import ApiError, Deadline
from fkn_assistant.providers import gigachat
from fkn_assistant.providers.gigachat import CHAT, OPTIONS, GigaChat

MODEL_FIELDS = {
    "temp_pass": {"date", "building", "reason"},
    "enrollment_certificate": {"language", "format", "copies", "purpose"},
    "rag_answer": set(),
}
STATUSES = {"answer", "answer_partial", "clarify", "draft_ready", "refuse"}


def messages_for(case, profile, prompt):
    user_input = {
        "question": case["input"],
        "now": case["now"],
        "timezone": case["timezone"],
        "profile": {key: profile[key] for key in PROFILE_CONTEXT if key in profile},
    }
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
    ]


def parse_answer(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    route = value.get("route")
    answer = value.get("answer")
    fields = value.get("fields")
    if not isinstance(status, str) or status not in STATUSES:
        return None
    if not isinstance(route, str) or route not in MODEL_FIELDS:
        return None
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 800:
        return None
    if not isinstance(fields, dict) or fields.keys() - MODEL_FIELDS[route]:
        return None
    if any(type(field) not in (str, int) for field in fields.values()):
        return None
    for key in ("missing_fields", "invalid_fields"):
        values = value.get(key)
        if not isinstance(values, list):
            return None
        if any(
            not isinstance(item, str) or item not in MODEL_FIELDS[route]
            for item in values
        ):
            return None
        if len(values) != len(set(values)):
            return None
    if not isinstance(value.get("citations"), list):
        return None
    return value


def evaluate(raw, expected, profile):
    answer = parse_answer(raw)
    form = expected.get("request_type") in FORM_CONTEXT
    gold_fields = expected.get("request_fields") or {}
    allowed_routes = expected.get("acceptable_routes")
    if allowed_routes is None and expected.get("route"):
        allowed_routes = [expected["route"]]
    flags = {
        "valid_format": answer is not None,
        "status_ok": False,
        "no_unsupported_citations": False
        if answer is None
        else not answer["citations"],
        "route_ok": False if allowed_routes else None,
        "form_fields_total": len(gold_fields),
        "form_fields_correct": 0,
        "form_ok": False if form else None,
    }
    if answer is None:
        return None, flags
    flags["status_ok"] = answer["status"] in expected.get(
        "acceptable_statuses", [expected["status"]]
    )
    if allowed_routes:
        flags["route_ok"] = answer["route"] in allowed_routes
    fields = dict(answer["fields"])
    if answer["route"] in FORM_CONTEXT:
        for field in FORM_CONTEXT[answer["route"]]:
            fields[field] = profile[field]
        fields["student_id"] = profile["id"]
    if form:
        flags["form_fields_correct"] = sum(
            type(fields.get(k)) is type(v) and fields[k] == v
            for k, v in gold_fields.items()
        )
        flags["form_ok"] = (
            flags["status_ok"]
            and flags["route_ok"]
            and flags["form_fields_correct"] == len(gold_fields)
            and fields.keys() == gold_fields.keys()
            and sorted(answer["missing_fields"])
            == sorted(expected.get("missing_fields", []))
            and sorted(answer["invalid_fields"])
            == sorted(expected.get("invalid_fields", []))
        )
    return dict(answer, fields=fields), flags


def percentile(times, p):
    if not times:
        return None
    return round(sorted(times)[math.ceil(len(times) * p) - 1], 3)


def metric(rows, field):
    values = [row["checks"][field] for row in rows if row["checks"][field] is not None]
    return {"passed": sum(values), "total": len(values)}


def summarize(path, rows, planned, active_sec, manual_count, *, pricing):
    success = [row for row in rows if row.get("error") is None]
    times = [row["latency_sec"] for row in rows]
    token_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    tokens = {
        k: sum(row.get("usage", {}).get(k, 0) or 0 for row in rows) for k in token_keys
    }
    summary = {
        "planned": planned,
        "attempted": len(rows),
        "http_responses": len(success),
        "errors": len(rows) - len(success),
        "active_run_sec": round(active_sec, 2),
        "p50_sec": round(statistics.median(times), 3) if times else None,
        "p95_sec": percentile(times, 0.95),
        "usage": tokens,
        "responses_with_usage": sum(
            "total_tokens" in row.get("usage", {}) for row in success
        ),
        "avg_tokens_per_successful_response": round(
            tokens["total_tokens"] / len(success), 2
        )
        if success and all("total_tokens" in r.get("usage", {}) for r in success)
        else None,
        "marginal_cost_rub_per_request": 0.0,
        "pricing": pricing,
        "api_models": dict(Counter(r.get("model") for r in success)),
        "manual_planned": manual_count,
        "manual_graded": 0,
    }
    for field in ("valid_format", "status_ok", "route_ok", "no_unsupported_citations"):
        summary[field] = metric(rows, field)
    summary["format_status_route_all_3_repeats"] = None
    grouped = {}
    for row in rows:
        grouped.setdefault(row["case_id"], []).append(row)
    if (
        planned == 444
        and len(rows) == planned
        and all(len(g) == 3 for g in grouped.values())
    ):
        summary["format_status_route_all_3_repeats"] = {
            "passed": sum(
                all(
                    r["checks"]["valid_format"]
                    and r["checks"]["status_ok"]
                    and r["checks"]["route_ok"] is not False
                    for r in group
                )
                for group in grouped.values()
            ),
            "total": len(grouped),
        }
    if rows and "action_ok" in rows[0]["checks"]:
        summary["action_ok"] = metric(rows, "action_ok")
    summary["forms"] = {}
    for category in FORM_CONTEXT:
        group = [row for row in rows if row["category"] == category]
        summary["forms"][category] = {
            "cases": len({row["case_id"] for row in group}),
            "form_ok": metric(group, "form_ok"),
            "fields": {
                "passed": sum(r["checks"]["form_fields_correct"] for r in group),
                "total": sum(r["checks"]["form_fields_total"] for r in group),
            },
        }
    if rows and "trace" in rows[0]:
        for field in ("gold_hit_5", "gold_hit_20", "cited_gold_document"):
            summary[field] = metric(rows, field)
        versions = [
            name
            for r in rows
            for name in (
                (r["trace"].get("plan") or {}).get("model"),
                r["trace"].get("answer_model", r["model"]),
            )
            if name
        ]
        summary["http_responses"] = len(versions)
        summary["api_models"] = dict(Counter(versions))
        summary["generation_calls"] = sum(r["trace"]["calls"] for r in rows)
        summary["fallback_count"] = sum(bool(r["trace"].get("fallback")) for r in rows)

        def over_budget(usage, max_input, max_output):
            return (usage.get("prompt_tokens") or 0) + (
                usage.get("precached_prompt_tokens") or 0
            ) > max_input or (usage.get("completion_tokens") or 0) > max_output

        summary["budget_violations"] = sum(
            over_budget(r["trace"].get("answer_usage", r["usage"]), 2900, 250)
            or over_budget(r["trace"].get("plan", {}).get("usage", {}), 1400, 120)
            or r["trace"]["calls"] > (2 if "plan" in r["trace"] else 1)
            for r in rows
        )
        summary["deadline_exceeded"] = sum(r["latency_sec"] > 15 for r in rows)
        summary["input_cached_tokens"] = sum(
            r["usage"].get("precached_prompt_tokens", 0) for r in rows
        )
    write_json(path / "summary.json", summary)


def run(args):
    data = snapshot(args.repo, "dev_148.jsonl")
    profiles_raw = snapshot(args.repo, "students.json")
    cases = [json.loads(line) for line in data.splitlines() if line.strip()]
    if len(cases) != 148 or any(c["split"] != "dev" for c in cases):
        raise SystemExit("Ожидался замороженный dev-набор из 148 примеров.")
    profiles = {row["id"]: row for row in json.loads(profiles_raw)}
    if args.dataset in ("dialogues", "calibrate"):
        if args.variant != "rag-b0":
            raise SystemExit("Этот набор предназначен для rag-b0.")
        args.output.mkdir(parents=True, exist_ok=True)
        from fkn_assistant.rag import Rag, Search

        if args.dataset == "dialogues":
            from fkn_assistant.evaluation.dialogues import scenarios
            from fkn_assistant.forms import RULES

            result = scenarios(Rag(None, None), profiles["demo-student-001"])
            write_json(args.output / "dialogues.json", result)
            write_json(
                args.output / "run.json",
                {
                    "variant": "rag-b0",
                    "dataset": "dialogues",
                    "git_data_commit": DATA_COMMIT,
                    "profiles_sha256": digest(profiles_raw),
                    "clock": "2026-10-27T10:00:00+03:00",
                    "sandbox_rules": RULES["release"],
                    "files": {
                        name: digest((BASE / name).read_bytes())
                        for name in (
                            "src/fkn_assistant/evaluation/dialogues.py",
                            "src/fkn_assistant/forms.py",
                            "src/fkn_assistant/resources/form_rules.json",
                            "src/fkn_assistant/rag.py",
                            "infra/compose.yaml",
                        )
                    },
                },
            )
            print(f"{sum(row['passed'] for row in result)}/{len(result)}")
            if not all(row["passed"] for row in result):
                raise SystemExit(1)
        else:
            from fkn_assistant.evaluation.rag_eval import calibrate

            result = calibrate(Search(args.repo), cases, profiles)
            write_json(args.output / "calibration.json", result)
        return
    prompt = (RESOURCES / "prompt.txt").read_text(encoding="utf-8")
    if args.dataset == "smoke":
        cases = fixed_sample(cases, 20)
    review = (
        fixed_sample(cases, 50, minimum_forms=True) if args.dataset == "dev" else []
    )
    double_review = fixed_sample(review, 10) if review else []
    jobs = [(case, repeat) for repeat in range(1, args.repeats + 1) for case in cases]
    settings = {
        "variant": args.variant,
        "latency_scope": "end_to_end",
        "dataset": args.dataset,
        "repeats": args.repeats,
        "git_data_commit": DATA_COMMIT,
        "dataset_sha256": digest(data),
        "dataset_release": cases[0]["eval_release"],
        "profiles_sha256": digest(profiles_raw),
        "script_sha256": digest(Path(__file__).read_bytes()),
        "client_sha256": digest((Path(gigachat.__file__)).read_bytes()),
        "endpoint": CHAT,
        "sdk_version": version("openai"),
        "pydantic_version": version("pydantic"),
        "python_version": platform.python_version(),
        "machine": platform.machine(),
        "request_options": OPTIONS,
        "seed": None,
        "seed_note": "API v1 без поля seed",
        "prompt": prompt,
        "case_ids": [c["id"] for c in cases],
        "manual_review_ids": [c["id"] for c in review],
        "double_review_ids": [c["id"] for c in double_review],
    }
    if args.variant in ("rag-b0", "rag-b1", "search-only"):
        from fkn_assistant.evaluation.rag_eval import settings as rag_settings

        settings.update(rag_settings(args.repo))
        settings["runtime_versions"] = {
            package: version(package)
            for package in (
                "numpy",
                "onnxruntime",
                "tokenizers",
                "qdrant-client",
                "psycopg",
                "httpx",
            )
        }
        if args.variant == "search-only":
            settings.update(
                prompt=None,
                request_options=None,
                schema=None,
                endpoint=None,
                seed_note="Детерминированный поиск и цитата без генерации",
                billing_basis="Нет обращения к API генерации. Локальные ресурсы отдельно.",
            )
        elif args.variant == "rag-b1":
            from fkn_assistant.planner import (
                INPUT_LIMIT,
                OPTIONS as PLAN_OPTIONS,
                PROMPT as PLAN_PROMPT,
            )

            settings.update(
                max_steps=7,
                plan_prompt=PLAN_PROMPT,
                plan_request_options=PLAN_OPTIONS,
                plan_input_tokens_max=INPUT_LIMIT,
            )
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Эта папка уже занята прогоном.") from None
        execute(args, jobs, profiles, review, settings)


def execute(args, jobs, profiles, review, settings):
    output = args.output
    metadata = output / "run.json"
    if metadata.exists():
        if json.loads(metadata.read_text())["settings"] != settings:
            raise SystemExit(
                "Настройки изменились. Для нового замера укажи другую --output."
            )
    else:
        write_json(
            metadata,
            {
                "settings": settings,
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    results = output / "responses"
    results.mkdir(exist_ok=True)
    completed = {
        (row["case_id"], row["repeat"]): row
        for file in results.glob("*.json")
        for row in [json.loads(file.read_text())]
    }
    old_summary = output / "summary.json"
    active = (
        json.loads(old_summary.read_text())["active_run_sec"]
        if old_summary.exists()
        else 0
    )
    review_path = output / "review.json"
    pending = any((case["id"], repeat) not in completed for case, repeat in jobs)
    client = (
        GigaChat(args.env, args.ca)
        if pending and args.variant != "search-only"
        else None
    )
    rag = None
    if pending and args.variant in ("rag-b0", "rag-b1", "search-only"):
        from fkn_assistant.rag import Rag, Search

        search = Search(args.repo)
        threshold = settings["retrieval_calibration"]["threshold"]
        if args.variant == "search-only":
            from fkn_assistant.search_only import SearchOnly

            rag = SearchOnly(search, threshold)
        else:
            rag = Rag(
                search, client, threshold=threshold, planning=args.variant == "rag-b1"
            )
    timer = time.perf_counter()
    try:
        for case, repeat in jobs:
            key = (case["id"], repeat)
            if key in completed:
                continue
            profile = profiles[case["student_profile_id"]]
            if rag:
                from fkn_assistant.evaluation.rag_eval import attempt

                row = attempt(
                    rag,
                    case,
                    profile,
                    repeat,
                    digest(str(output.resolve()).encode())[:16],
                )
                if row["error"] and row["error"]["code"] in (
                    400,
                    401,
                    402,
                    403,
                    404,
                    429,
                ):
                    raise ApiError(row["error"]["stage"], row["error"]["code"])
            else:
                started = time.perf_counter()
                deadline = Deadline(60)
                messages = messages_for(case, profile, settings["prompt"])
                row = {
                    "case_id": case["id"],
                    "category": case["category"],
                    "repeat": repeat,
                    "model": None,
                    "raw_answer": None,
                    "usage": {},
                    "error": None,
                }
                try:
                    completion = client.generate(
                        messages, OPTIONS, deadline, timeout=45
                    )
                    row.update(
                        model=completion.model,
                        usage=completion.usage,
                        finish_reason=completion.finish_reason,
                        request_id=completion.request_id,
                        raw_answer=completion.text,
                    )
                except ApiError as error:
                    if error.details["code"] in (400, 401, 403, 404, 429):
                        raise
                    row["error"] = error.details
                except (KeyError, IndexError, TypeError):
                    row["error"] = {
                        "stage": "chat",
                        "code": "invalid_provider_response",
                    }
                row["latency_sec"] = round(time.perf_counter() - started, 4)
                row["parsed"], row["checks"] = evaluate(
                    row["raw_answer"], case["expected"], profile
                )
            write_json(results / f"{case['id']}-{repeat}.json", row)
            completed[key] = row
            if len(completed) in (1, len(jobs)) or len(completed) % 20 == 0:
                print(f"{len(completed)}/{len(jobs)}", flush=True)
    finally:
        if client:
            client.close()
        rows = [
            completed[(case["id"], r)]
            for case, r in jobs
            if (case["id"], r) in completed
        ]
        summarize(
            output,
            rows,
            len(jobs),
            active + time.perf_counter() - timer,
            len(review),
            pricing=settings.get(
                "billing_basis",
                "GigaChat-3-Ultra under GIGACHAT_API_PERS Freemium quota",
            ),
        )
        if (
            review
            and all((case["id"], 1) in completed for case in review)
            and not review_path.exists()
        ):
            write_json(
                review_path,
                [
                    {
                        "case_id": c["id"],
                        "category": c["category"],
                        "question": c["input"],
                        "now": c["now"],
                        "timezone": c["timezone"],
                        "profile_id": c["student_profile_id"],
                        "expected": c["expected"],
                        "response": completed[(c["id"], 1)]["raw_answer"],
                        "double_review": c["id"] in settings["double_review_ids"],
                        "normalized_response": completed[(c["id"], 1)]["parsed"],
                        **(
                            {
                                "retrieved_context": completed[(c["id"], 1)]["trace"][
                                    "context"
                                ]
                            }
                            if "trace" in completed[(c["id"], 1)]
                            else {}
                        ),
                    }
                    for c in review
                ],
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description="КТ3 — сравнение конфигураций на dev.")
    parser.add_argument(
        "--variant",
        choices=["prompt-only", "rag-b0", "rag-b1", "search-only"],
        default="prompt-only",
    )
    parser.add_argument(
        "--dataset", choices=["smoke", "dev", "dialogues", "calibrate"], default="dev"
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--env", type=Path, default=REPO / ".env")
    parser.add_argument(
        "--ca", type=Path, default=RESOURCES / "russian_trusted_root_ca_pem.crt"
    )
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats должен быть положительным.")
    try:
        run(args)
    except ApiError as error:
        raise SystemExit(
            f"Прогон прерван: {error}. Повтори ту же команду для продолжения."
        ) from None


if __name__ == "__main__":
    main()
