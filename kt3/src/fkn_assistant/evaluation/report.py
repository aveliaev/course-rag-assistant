#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path

from fkn_assistant.config import REPO
from fkn_assistant.evaluation.dataset import snapshot

VERDICTS = {"pass", "fail", "not_verifiable", "n/a"}
RUBRIC = ("outcome", "evidence", "form", "safety")


def ratio(metric):
    if metric is None or metric["total"] == 0:
        return "н/п"
    passed, total = metric["passed"], metric["total"]
    percent = f"{100 * passed / total:.1f}".replace(".", ",")
    return f"{passed}/{total} ({percent}%)"


def seconds(value):
    if value is None:
        return "н/п"
    return f"{value:.3f}".replace(".", ",") + " с"


def load_grades(path, cases):
    allowed = {row["case_id"] for row in cases}
    grades = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        case_id = row["case_id"]
        if case_id not in allowed or case_id in grades:
            raise ValueError(f"Неизвестный или повторяющийся ID {case_id}")
        marks = row["checks"]
        if set(marks) != set(RUBRIC) or not set(marks.values()) <= VERDICTS:
            raise ValueError(f"Неверная рубрика для {case_id}")
        if marks["outcome"] == "n/a" or marks["safety"] == "n/a":
            raise ValueError(f"Исход и безопасность применимы к {case_id}")
        grades[case_id] = marks
    return grades


def human_review(run, grade_path):
    packet = run / "review.json"
    if not packet.exists():
        if grade_path is not None:
            raise ValueError(
                "Сначала сформируй review.json полным первым проходом dev."
            )
        return (
            "Выборка для смысловой проверки станет доступна после первого прохода dev."
        )
    cases = json.loads(packet.read_text())
    if grade_path is None:
        return f"Команде подготовлена выборка из {len(cases)} ответов. Ручная оценка ожидается."
    grades = load_grades(grade_path, cases)
    outcomes = Counter()
    for marks in grades.values():
        outcomes[verdict(marks)] += 1
    return (
        f"Вручную проверено {len(grades)}/{len(cases)} ответов первого повтора. "
        f"Выполнили применимые условия {outcomes['pass']}, не выполнили {outcomes['fail']}, "
        f"не удалось проверить {outcomes['not_verifiable']}."
    )


def verdict(checks):
    if "fail" in checks.values():
        return "fail"
    if "not_verifiable" in checks.values():
        return "not_verifiable"
    return "pass"


def agreement(run, repo, first, second):
    cases = [c for c in review_cases(run, repo) if c["double_review"]]
    left = load_grades(first, cases)
    right = load_grades(second, cases)
    if len(left) != len(cases) or len(right) != len(cases):
        raise ValueError(
            f"Каждому участнику нужно разметить все {len(cases)} общих кейсов."
        )
    total = len(cases)
    left_dist = Counter(map(verdict, left.values()))
    right_dist = Counter(map(verdict, right.values()))
    matches = sum(
        verdict(left[c["case_id"]]) == verdict(right[c["case_id"]]) for c in cases
    )
    expected = sum(left_dist[k] * right_dist[k] for k in left_dist) / total**2
    kappa = (
        None
        if expected == 1
        else round((matches / total - expected) / (1 - expected), 4)
    )
    return {
        "matched": matches,
        "total": total,
        "cohens_kappa": kappa,
        "disagreements": [
            c["case_id"] for c in cases if left[c["case_id"]] != right[c["case_id"]]
        ],
    }


def render(run, grade_path):
    settings = json.loads((run / "run.json").read_text())["settings"]
    s = json.loads((run / "summary.json").read_text())
    if settings["variant"] == "rag-b0":
        from fkn_assistant.evaluation.report_rag import render as render_rag

        return render_rag(run, grade_path)
    models = ", ".join(
        f"`{name}` ({count})"
        for name, count in sorted(
            s["api_models"].items(), key=lambda pair: str(pair[0])
        )
    )
    token_avg = s["avg_tokens_per_successful_response"]
    latency_label = (
        "полного хода"
        if settings.get("latency_scope") == "end_to_end"
        else "до полного ответа API"
    )
    lines = [
        "# 8.1 Baseline. Один промпт с GigaChat Ultra",
        "",
        f"Набор `{settings['dataset']}`, релиз `{settings['dataset_release']}`. "
        f"Записано {s['attempted']}/{s['planned']} попыток. "
        f"Ответов API {s['http_responses']}, ошибок {s['errors']}. "
        f"В журналах API зафиксированы версии {models or 'н/п'}.",
        "",
        "| Показатель | Результат |",
        "|---|---|",
        "| Модель | `GigaChat-3-Ultra`, один вызов на кейс |",
        "| Промпт | [prompt.txt](prompt.txt), точный текст в run.json |",
        f"| Валидный формат | {ratio(s['valid_format'])} |",
        f"| Допустимый статус | {ratio(s['status_ok'])} |",
        f"| Допустимый маршрут | {ratio(s['route_ok'])} |",
        f"| Формат, статус и маршрут совпали во всех трёх повторах | {ratio(s['format_status_route_all_3_repeats'])} |",
        f"| P50 / P95 {latency_label} | {seconds(s['p50_sec'])} / {seconds(s['p95_sec'])} |",
        f"| Суммарное время активного прогона | {seconds(s['active_run_sec'])} |",
        f"| Токены по данным API | {s['usage']['total_tokens']} "
        f"(вход {s['usage']['prompt_tokens']}, выход {s['usage']['completion_tokens']}, "
        f"сведения о расходе вернулись для {s['responses_with_usage']} ответов) |",
        f"| Токенов на успешный запрос в среднем | {token_avg if token_avg is not None else 'н/п'} |",
        f"| Стоимость запроса | {s['marginal_cost_rub_per_request']:.0f} ₽ в рамках Freemium |",
        "",
        "Ошибки формата засчитываются как ошибки в автоматических метриках статуса, маршрута и формы. "
        "Совпадение формы требует правильных статуса, маршрута, полей и списков уточнений.",
        "",
        "| Форма | Кейсы | Совпадение формы | Совпадение отдельных полей |",
        "|---|---:|---:|---:|",
    ]
    for key, label in (
        ("temp_pass", "Временный пропуск"),
        ("enrollment_certificate", "Справка об обучении"),
    ):
        form = s["forms"][key]
        lines.append(
            f"| {label} | {form['cases']} | {ratio(form['form_ok'])} | {ratio(form['fields'])} |"
        )
    lines += [
        "",
        human_review(run, grade_path),
        "",
        "У режима с одним промптом нет доступа к выдержкам из регламентов и ПУД. "
        "Для проверенных ответов со ссылками на применимые пункты нужен этап с поиском. "
        "Результаты черновиков относятся к первому ходу. Отправка, повтор и отмена проверяются отдельно.",
        "",
        "Задержку считаем по полным ответам API. Ошибки учитываем отдельным числом. "
        "При подсчёте долей по попыткам каждый повтор входит в знаменатель, но не считается новым кейсом.",
    ]
    return "\n".join(lines) + "\n"


def review_cases(run, repo):
    if (run / "review.json").is_file():
        return json.loads((run / "review.json").read_text())
    settings = json.loads((run / "run.json").read_text())["settings"]
    by_id = {
        c["id"]: c
        for c in map(json.loads, snapshot(repo, "dev_148.jsonl").splitlines())
    }
    cases = []
    for case_id in settings["manual_review_ids"]:
        answer_path = run / "responses" / f"{case_id}-1.json"
        if not answer_path.is_file():
            raise SystemExit("Дождись ответов для всех 50 случаев первого повтора.")
        case = by_id[case_id]
        answer = json.loads(answer_path.read_text())
        cases.append(
            {
                "case_id": case_id,
                "category": case["category"],
                "question": case["input"],
                "now": case["now"],
                "timezone": case["timezone"],
                "profile_id": case["student_profile_id"],
                "expected": case["expected"],
                "response": answer["raw_answer"],
                "normalized_response": answer["parsed"],
                "double_review": case_id in settings["double_review_ids"],
            }
        )
    return cases


def render_review(run, repo):
    cases = review_cases(run, repo)
    if not cases:
        raise SystemExit(
            "Ручная выборка предусмотрена для dev, выбери папку прогона dev."
        )
    profiles = {p["id"]: p for p in json.loads(snapshot(repo, "students.json"))}
    lines = [
        "# Ручная проверка первого повтора",
        "",
        "Начните с кейсов, отмеченных «Двойная проверка». "
        "Примените рубрику из README и запишите итоговые метки отдельно.",
        "",
    ]
    for case in sorted(cases, key=lambda c: (not c["double_review"], c["case_id"])):
        case_id = case["case_id"]
        tag = " · Двойная проверка" if case["double_review"] else ""
        profile = profiles[case["profile_id"]]
        response = case.get("normalized_response")
        if response is None:
            response = case.get("response")
        lines.extend(
            [
                f"## {case_id} · {case['category']}{tag}",
                "",
                f"Время {case['now']} · {case['timezone']} · профиль `{case['profile_id']}`",
                "",
                f"{profile['educational_program']}, курс {profile['course']}, набор {profile['admission_year']}.",
                "",
                "Вопрос и ответ приложения:",
                "",
                "    " + json.dumps(case["question"], ensure_ascii=False),
                "",
                *[
                    "    " + line
                    for line in json.dumps(
                        response, ensure_ascii=False, indent=2
                    ).splitlines()
                ],
                "",
                "Эталон для проверки:",
                "",
                *[
                    "    " + line
                    for line in json.dumps(
                        case["expected"], ensure_ascii=False, indent=2
                    ).splitlines()
                ],
                "",
            ]
        )
        if "retrieved_context" in case:
            lines.append("Выдержки, которые получила модель")
            lines.append("")
            for item in case["retrieved_context"]:
                lines.extend(
                    [
                        f"- {item['doc_id']}, {item['clause_id']}, версия {item['version']}. {item['text']}",
                        "",
                    ]
                )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Отчёт §8.1 из результатов запуска")
    parser.add_argument("run", type=Path)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--grades", type=Path)
    options.add_argument("--review", action="store_true")
    options.add_argument("--agreement", nargs=2, type=Path, metavar=("FIRST", "SECOND"))
    parser.add_argument("--repo", type=Path, default=REPO)
    args = parser.parse_args()
    if args.review:
        print(render_review(args.run, args.repo))
    elif args.agreement:
        print(
            json.dumps(
                agreement(args.run, args.repo, *args.agreement),
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(render(args.run, args.grades), end="")


if __name__ == "__main__":
    main()
