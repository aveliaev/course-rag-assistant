import json
from math import sqrt


def proportion(metric):
    n = metric["total"]
    if not n:
        return "н/п"
    passed = metric["passed"]
    return f"{passed}/{n} ({passed / n:.1%})"


def wilson(passed, n):
    if not n:
        return "н/п"
    p = passed / n
    z = 1.96
    center = p + z * z / (2 * n)
    width = z * sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    factor = 1 + z * z / n
    return f"{(center - width) / factor:.1%}–{(center + width) / factor:.1%}"


def render(run, grade_path):
    from fkn_assistant.evaluation.report import human_review

    s = json.loads((run / "summary.json").read_text())
    settings = json.loads((run / "run.json").read_text())["settings"]
    rows = [
        json.loads(p.read_text()) for p in sorted((run / "responses").glob("*.json"))
    ]
    first = [r for r in rows if r["repeat"] == 1]
    lines = [
        "# §8.1. RAG-бейзлайн B0",
        "",
        f"Релиз {settings['dataset_release']}. Набор {settings['dataset']}. "
        f"Сохранено {s['attempted']}/{s['planned']} ходов, {len(first)} разных кейсов. "
        f"Вызовов генерации {s['generation_calls']}, ошибок хода {s['errors']}.",
        "",
        "| Показатель | Результат |",
        "|---|---:|",
    ]
    values = [
        (
            "Модель API",
            ", ".join(f"{m} ({n})" for m, n in s["api_models"].items())
            or "нет генераций",
        ),
        ("Промпт", "[rag_prompt.txt](rag_prompt.txt)"),
        ("Формат ответа приложения", proportion(s["valid_format"])),
        ("Совпадение ожидаемого статуса", proportion(s["status_ok"])),
        ("Допустимый маршрут", proportion(s["route_ok"])),
        ("Gold-документ в top-5", proportion(s["gold_hit_5"])),
        ("Gold-документ в top-20", proportion(s["gold_hit_20"])),
        ("Есть цитата из допустимого документа", proportion(s["cited_gold_document"])),
        ("Ответы выдержкой после ошибки формата или ссылки", s["fallback_count"]),
        ("P50 / P95 полного хода, с", f"{s['p50_sec']} / {s['p95_sec']}"),
        ("Длительность прогона, с", s["active_run_sec"]),
        ("Токены по usage.total_tokens", s["usage"]["total_tokens"]),
        (
            "Из них вход / выход по данным API",
            f"{s['usage']['prompt_tokens']} / {s['usage']['completion_tokens']}",
        ),
        ("Токены кэшированного входа сверх тарифицируемых", s["input_cached_tokens"]),
        ("Фактические расходы на запрос", "0 ₽ при Freemium и локальных сервисах"),
        ("Превышения бюджета генерации", s["budget_violations"]),
        ("Ходы дольше 15 с", s.get("deadline_exceeded", "н/п")),
        (
            "Проверки действий по журналу",
            proportion(s["action_ok"]) if "action_ok" in s else "н/п",
        ),
        (
            "Токены в среднем на ход",
            round(s["usage"]["total_tokens"] / len(rows), 1) if rows else "н/п",
        ),
    ]
    for label, value in values:
        lines.append(f"| {label} | {value} |")
    lines.extend(
        [
            "",
            "| Форма | Кейсов | Полное совпадение первого хода, все повторы | Верные поля |",
            "|---|---:|---:|---:|",
        ]
    )
    for key, label in (
        ("temp_pass", "Временный пропуск"),
        ("enrollment_certificate", "Справка об обучении"),
    ):
        form = s["forms"][key]
        lines.append(
            f"| {label} | {form['cases']} | {proportion(form['form_ok'])} | {proportion(form['fields'])} |"
        )
    lines.extend(
        [
            "",
            "Оценка относится к локальной версии правил песочницы, описанной в form_rules.json. "
            "Совпадение первого хода формы включает источники полей, подтверждение, ссылки на правила и журнал.",
            "",
            "Стоимость API в этом прогоне составляет 0 ₽ в пределах квоты Freemium. "
            "Для платной модели стоимость хода рассчитывается по среднему числу тарифицируемых входных "
            "и выходных токенов и ставкам выбранной модели. У Ultra нет публичной платной ставки. "
            "Указанная стоимость не включает инфраструктуру и труд.",
            "",
            "| Категория | Допустимый статус в первом повторе | 95% интервал Уилсона |",
            "|---|---:|---:|",
        ]
    )
    for category in sorted({r["category"] for r in first}):
        group = [r for r in first if r["category"] == category]
        passed = sum(r["checks"]["status_ok"] for r in group)
        lines.append(
            f"| {category} | {passed}/{len(group)} | {wilson(passed, len(group))} |"
        )
    lines.extend(
        [
            "",
            human_review(run, grade_path),
            "",
            "Gold-hit проверяет совпадение ID документа для кейсов с официальными эталонными источниками. "
            "Отсутствие поиска в таком кейсе считается промахом. "
            "Смысл утверждения и соответствие конкретному пункту оцениваются по ручной рубрике.",
            "",
            f"Цель по задержке P95 ≤ 15 с: {'достигнута' if s['p95_sec'] is not None and s['p95_sec'] <= 15 else 'не достигнута'}. "
            "Вывод по целям полного успеха 85% и смысловой корректности цитирования 95% требует разметки ответов.",
            "",
            "E2E измеряется при уже загруженном индексе и включает обращения к Postgres, поиск, "
            "подсчёт токенов и получение полного ответа. Ошибки инфраструктуры перечислены отдельно.",
        ]
    )
    return "\n".join(lines) + "\n"
