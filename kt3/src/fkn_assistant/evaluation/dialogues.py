"""Seven KT2 acceptance dialogues against the same turn handler and real sandbox database."""

import uuid
from datetime import datetime, timedelta


def scenarios(app, profile):
    base = datetime.fromisoformat("2026-10-27T10:00:00+03:00")
    run_id = uuid.uuid4().hex
    results = []
    for name in (
        "certificate_language",
        "pass_building",
        "submit_error",
        "step_limit",
        "edit",
        "repeat",
        "cancel",
    ):
        space = f"scenario-{run_id}-{name}"
        session = "dialog"
        transcript = []

        def turn(text="", button=None, **opts):
            now = base + timedelta(minutes=len(transcript))
            answer, trace = app.turn(
                space, session, profile, text, now.isoformat(), button, **opts
            )
            transcript.append(
                dict(
                    text=text,
                    button=button and button["action"],
                    now=now.isoformat(),
                    fixture=opts,
                    response={k: v for k, v in answer.items() if k != "confirmation"},
                    trace=trace,
                    evidence=app.sandbox.evidence((space, session, str(profile["id"]))),
                )
            )
            return answer

        def click(card, action="confirm", **opts):
            button = {k: card.get(k) for k in ("draft_id", "revision", "confirmation")}
            return turn(button=dict(button, action=action), **opts)

        def count():
            return app.sandbox.db.execute(
                "select count(*) from kt3_applications where space=%s", (space,)
            ).fetchone()[0]

        checks = []
        if name == "certificate_language":
            first = turn("Оформи бумажную справку об обучении для работодателя.")
            ready = turn("На английском.")
            checks = [
                first["missing_fields"] == ["language"],
                ready["status"] == "draft_ready",
                ready["fields"].get("language") == "en",
                ready["fields"].get("format") == "paper",
                count() == 0,
                click(ready)["status"] == "submitted",
                count() == 1,
                click(ready)["status"] == "submitted",
                count() == 1,
                click(ready, "cancel")["status"] == "cancelled",
                transcript[-1]["evidence"]["applications"][0]["status"] == "withdrawn",
            ]
        elif name == "pass_building":
            first = turn("Забыл пропуск, нужен временный на завтра.")
            ready = turn("DEMO_B")
            checks = [
                first["missing_fields"] == ["building"],
                ready["status"] == "draft_ready",
                ready["fields"].get("building") == "DEMO_B",
                ready["fields"].get("date") == "2026-10-28",
                count() == 0,
                click(ready, "cancel")["status"] == "cancelled",
                count() == 0,
            ]
        else:
            card = turn("Забыл пропуск. Нужен временный на завтра в DEMO_A.")
            checks = [card["status"] == "draft_ready", count() == 0]
            if name == "submit_error":
                fail = click(card, fail="submit")
                checks.extend(
                    [
                        fail["status"] == "temporary_error",
                        count() == 0,
                        click(card)["status"] == "submitted",
                        count() == 1,
                    ]
                )
            if name == "step_limit":
                fail = click(card, limit=1)
                checks.extend(
                    [
                        fail["status"] == "refuse",
                        transcript[-1]["trace"]["error"]["code"] == "step_limit",
                        count() == 0,
                    ]
                )
            if name == "edit":
                new = turn("Исправь корпус на DEMO_B.")
                checks.extend(
                    [
                        new["fields"].get("building") == "DEMO_B",
                        click(card)["status"] == "refuse",
                        count() == 0,
                        click(new)["status"] == "submitted",
                        count() == 1,
                    ]
                )
            if name == "repeat":
                first = click(card)
                second = click(card)
                checks.extend(
                    [
                        first["status"] == "submitted",
                        len(transcript[-2]["evidence"]["applications"]) == 1,
                        second.get("number") == first.get("number"),
                        count() == 1,
                    ]
                )
            if name == "cancel":
                checks.extend(
                    [
                        click(card, "cancel")["status"] == "cancelled",
                        click(card)["status"] == "refuse",
                        count() == 0,
                    ]
                )
        journal = [
            r[0]
            for r in app.sandbox.db.execute(
                "select event from kt3_events where space=%s order by seq", (space,)
            )
        ]
        checks.append(journal.count("submitted") == count())
        results.append(
            dict(
                scenario=name,
                passed=all(checks),
                checks=checks,
                journal=journal,
                applications=count(),
                turns=transcript,
            )
        )
    return results
