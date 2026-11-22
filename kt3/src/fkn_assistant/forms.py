"""Local sandbox. Identity and button events must be supplied by the trusted caller."""

import hashlib
import json
import os
import re
import secrets
import uuid
from contextlib import contextmanager
from datetime import date, timedelta

import psycopg
from psycopg.types.json import Jsonb

from fkn_assistant.config import RESOURCES

RULES = json.loads((RESOURCES / "form_rules.json").read_text())
DSN = os.environ.get(
    "KT3_PG_DSN", "postgresql://kt3:kt3-local-only@127.0.0.1:15432/kt3"
)
NUMBERS = {
    "один": 1,
    "одна": 1,
    "one": 1,
    "два": 2,
    "две": 2,
    "two": 2,
    "три": 3,
    "three": 3,
    "четыре": 4,
    "four": 4,
    "пять": 5,
    "five": 5,
    "ноль": 0,
    "zero": 0,
}
MONTHS = "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()
LABELS = {
    "building": ("корпус", "building"),
    "reason": ("причину", "reason"),
    "language": ("язык справки", "certificate language"),
    "date": ("дату", "date"),
    "copies": ("число экземпляров", "number of copies"),
    "format": ("формат", "format"),
    "purpose": ("цель", "purpose"),
}


def rule_reference(route, field):
    clause_id = f"{route}.{field}"
    return {
        "source_kind": "synthetic",
        "doc_id": "kt3_form_rules",
        "version": RULES["release"],
        "clause_id": clause_id,
        "citation_id": f"{RULES['release']}:{clause_id}",
        "path": "form_rules.json",
        "text": RULES[route]["clauses"][field],
    }


def with_rules(answer, fields):
    answer["citations"] = [rule_reference(answer["route"], field) for field in fields]
    return answer


def route_for(text):
    if re.search(
        r"пропуск(?![а-я]*\s+(?:занят|экзам))|temporary pass|(?:forgot|lost) my pass",
        text,
        re.I,
    ):
        if not re.search(r"пропуск[аи]\s+(?:пар|лекци|семинар)", text, re.I):
            return "temp_pass"
    if re.search(
        r"справк[ауи]\s+(?:об|с места)\s+обучени|(?:enrollment|enrolment|student status) certificate|(?:оформи|нужна|закажи).*справк",
        text,
        re.I,
    ):
        return "enrollment_certificate"
    return None


def english(text):
    return not bool(re.search("[а-яё]", text, re.I))


def result(status, route, answer, fields=None, missing=(), invalid=(), **extra):
    return dict(
        status=status,
        route=route,
        answer=answer,
        fields=fields or {},
        missing_fields=list(missing),
        invalid_fields=list(invalid),
        citations=[],
        **extra,
    )


def extract(route, text, now):
    s = text.lower()
    values = {}
    if route == "temp_pass":
        for name, days in (
            ("вчера|yesterday", -1),
            ("завтра|tomorrow", 1),
            ("сегодня|today", 0),
        ):
            if re.search(name, s):
                values["date"] = str(now.date() + timedelta(days=days))
        match = re.search(r"\b(\d{4}-\d\d-\d\d)\b", s)
        if match:
            values["date"] = match[1]
        match = re.search(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", s)
        if match:
            values["date"] = (
                f"{match[3]}-{MONTHS.index(match[2]) + 1:02d}-{int(match[1]):02d}"
            )
        match = re.search(r"\bdemo_[a-z0-9]+\b", s)
        if match:
            values["building"] = match[0].upper()
        if re.search(r"забы[лв]|forgot", s):
            values["reason"] = "forgot"
        if re.search(r"потеря|утеря|lost", s):
            values["reason"] = "lost"
    else:
        for pattern, key, val in (
            (r"английск|english", "language", "en"),
            (r"русск|russian", "language", "ru"),
            (r"бумажн|on paper|hard copy", "format", "paper"),
            (r"электрон|electronic|digital", "format", "electronic"),
            (r"работодател|employer", "purpose", "для работодателя"),
            (r"виз[аыу]|visa", "purpose", "для визы"),
        ):
            if re.search(pattern, s):
                values[key] = val
        purpose = re.search(r"(?:цель\s*[:—-]\s*|для\s+)([^.,;!?]+)", s)
        if purpose and "purpose" not in values:
            values["purpose"] = "для " + purpose[1].strip()
        copies = re.search(
            r"\b(-?\d+|" + "|".join(NUMBERS) + r")\s+(?:экземпляр|копи|cop(?:y|ies))", s
        )
        if copies:
            raw = copies[1]
            values["copies"] = NUMBERS[raw] if raw in NUMBERS else int(raw)
    return values


class Sandbox:
    def __init__(self):
        self.db = psycopg.connect(
            DSN, autocommit=True, connect_timeout=3, options="-c statement_timeout=2500"
        )
        self.db.execute("""create table if not exists kt3_drafts(
            space text, session text, owner text, id uuid primary key, route text, body jsonb, sources jsonb,
            status text, revision int, token text, shown timestamptz, expires timestamptz,
            seq bigserial)""")
        self.db.execute("""create table if not exists kt3_applications(
            draft uuid primary key, number uuid unique, space text, owner text, route text, created timestamptz, status text)""")
        self.db.execute("""create table if not exists kt3_events(
            seq bigserial primary key, space text, session text, owner text, event text, revision int, at timestamptz)""")
        self.db.execute("""create table if not exists kt3_history(
            seq bigserial primary key, space text, session text, owner text, at timestamptz, question text, answer text)""")

    def execute(self, stage, deadline, sql, params):
        timeout_ms = 2500
        if deadline is not None:
            timeout_ms = max(1, int(deadline.remaining(stage, 2.5) * 1000))
        self.db.execute(
            "select set_config('statement_timeout', %s, false)", (str(timeout_ms),)
        )
        if deadline is not None:
            deadline.remaining(stage, 2.5)
        return self.db.execute(sql, params)

    def evidence(self, key):
        events = self.execute(
            "evidence",
            None,
            "select event,revision from kt3_events where space=%s and session=%s and owner=%s order by seq",
            key,
        ).fetchall()
        applications = self.execute(
            "evidence",
            None,
            """select a.number::text,a.status from kt3_applications a
               join kt3_drafts d on a.draft=d.id
               where d.space=%s and d.session=%s and d.owner=%s order by a.number""",
            key,
        ).fetchall()
        return {
            "events": [
                {"event": event, "revision": revision} for event, revision in events
            ],
            "applications": [
                {"number": number, "status": status} for number, status in applications
            ],
        }

    def remember(self, key, now, question, answer, deadline=None):
        self.execute(
            "history",
            deadline,
            "delete from kt3_history where space=%s and at < %s",
            (key[0], now - timedelta(days=30)),
        )
        self.execute(
            "history",
            deadline,
            "insert into kt3_history(space,session,owner,at,question,answer) values(%s,%s,%s,%s,%s,%s)",
            (*key, now, question, answer),
        )

    def history(self, key, now, deadline=None):
        rows = self.execute(
            "history",
            deadline,
            """select question,answer from kt3_history where space=%s and session=%s and owner=%s
                      and at between %s and %s order by seq desc limit 5""",
            (*key, now - timedelta(days=30), now),
        ).fetchall()
        return list(reversed(rows))

    def event(self, key, event, revision, now, deadline=None):
        self.execute(
            "forms",
            deadline,
            "insert into kt3_events(space,session,owner,event,revision,at) values(%s,%s,%s,%s,%s,%s)",
            (*key, event, revision, now),
        )

    @contextmanager
    def action_transaction(self, deadline):
        if deadline is not None:
            deadline.remaining("forms", 2.5)
        with self.db.transaction():
            yield
            if deadline is not None:
                deadline.remaining("forms", 2.5)

    def handle(
        self,
        key,
        profile,
        now,
        text,
        button=None,
        schedule_down=False,
        fail_submit=False,
        deadline=None,
        interpretation=None,
    ):
        owner = str(profile["id"])
        if key[2] != owner or not profile.get("is_synthetic"):
            raise ValueError("untrusted_identity")
        with self.action_transaction(deadline):
            self.execute(
                "forms",
                deadline,
                "select pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("|".join((key[0], owner)),),
            )
            self.execute(
                "forms",
                deadline,
                "delete from kt3_drafts where space=%s and expires<=%s",
                (key[0], now),
            )
            self.execute(
                "forms",
                deadline,
                "delete from kt3_events where space=%s and at < %s",
                (key[0], now - timedelta(days=90)),
            )
            select = """select id,route,body,sources,status,revision,token,shown from kt3_drafts
                        where space=%s and session=%s and owner=%s"""
            if button:
                row = self.execute(
                    "forms",
                    deadline,
                    select + " and id::text=%s for update",
                    (*key, str(button.get("draft_id", ""))),
                ).fetchone()
            else:
                row = self.execute(
                    "forms",
                    deadline,
                    select + " order by seq desc limit 1 for update",
                    key,
                ).fetchone()
            if button:
                return self.button(key, row, now, button, fail_submit, deadline)
            route = route_for(text) if interpretation is None else interpretation.route
            if (
                row
                and row[4] in ("clarify", "draft_ready")
                and (not route or route == row[1])
            ):
                route = row[1]
            else:
                row = None
            if not route:
                return None
            en = english(text)
            if profile.get("status") != "studying" or re.search(
                r"за (?:друга|подругу|одногруппника|него|неё|сестру|брата)|на чужое имя|for (?:my|a) (?:friend|brother|sister)",
                text,
                re.I,
            ):
                return with_rules(
                    result(
                        "refuse",
                        route,
                        "Only the owner can apply."
                        if en
                        else "Оформление доступно только учащемуся для себя.",
                    ),
                    ["eligibility"],
                )
            fields = dict(row[2]) if row else {}
            sources = dict(row[3]) if row else {}
            rules = RULES[route]
            for name in rules["profile"]:
                fields[name] = profile[name]
                sources[name] = "profile"
            fields["student_id"], sources["student_id"] = owner, "profile"
            defaults = rules.get("defaults", {"date": str(now.date())})
            for k, v in defaults.items():
                if k not in fields:
                    fields[k], sources[k] = v, "default"
            fields_from_text = (
                extract(route, text, now)
                if interpretation is None or route != interpretation.route
                else interpretation.fields
            )
            for k, v in fields_from_text.items():
                fields[k], sources[k] = v, "user"
            missing = [k for k in rules["user_fields"] if k not in fields]
            invalid = []
            if "date" in fields:
                try:
                    if date.fromisoformat(fields["date"]) < now.date():
                        invalid.append("date")
                except ValueError:
                    invalid.append("date")
            if (
                "building" in fields
                and fields["building"] not in RULES["temp_pass"]["buildings"]
            ):
                invalid.append("building")
            if "copies" in fields and fields["copies"] < 1:
                invalid.append("copies")
            status = "clarify" if missing or invalid else "draft_ready"
            revision = row[5] + 1 if row else 1
            draft = row[0] if row else uuid.uuid4()
            token = secrets.token_urlsafe(24) if status == "draft_ready" else None
            stored_token = hashlib.sha256(token.encode()).hexdigest() if token else None
            self.execute(
                "forms",
                deadline,
                """insert into kt3_drafts(space,session,owner,id,route,body,sources,status,revision,token,shown,expires)
                  values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                  on conflict(id) do update set body=excluded.body,
                  sources=excluded.sources,status=excluded.status,revision=excluded.revision,token=excluded.token,
                  shown=excluded.shown,expires=excluded.expires""",
                (
                    *key,
                    draft,
                    route,
                    Jsonb(fields),
                    Jsonb(sources),
                    status,
                    revision,
                    stored_token,
                    now,
                    now + timedelta(hours=24),
                ),
            )
            if schedule_down and "building" in missing:
                self.event(key, "schedule_unavailable", revision, now, deadline)
            self.event(key, status, revision, now, deadline)
            answer = (
                "Check your draft and confirm."
                if en
                else "Проверь черновик и нажми «Подтвердить»."
            )
            if missing or invalid:
                labels = ", ".join(LABELS[k][int(en)] for k in missing + invalid)
                answer = f"Please specify: {labels}." if en else f"Уточни {labels}."
                if schedule_down:
                    answer = "Расписание недоступно. " + answer
            return with_rules(
                result(
                    status,
                    route,
                    answer,
                    fields,
                    missing,
                    invalid,
                    field_sources=sources,
                    draft_id=str(draft),
                    revision=revision,
                    confirmation=token,
                ),
                missing + invalid or ["confirmation"],
            )

    def button(self, key, row, now, button, fail_submit, deadline):
        if (
            not row
            or str(row[0]) != button.get("draft_id")
            or row[5] != button.get("revision")
        ):
            return result("refuse", "rag_answer", "Карточка недоступна или устарела.")
        draft, route, fields, sources, status, revision, token, shown = row
        action = button.get("action")
        if action == "cancel" and status in (
            "draft_ready",
            "clarify",
            "submitted",
            "cancelled",
        ):
            self.execute(
                "forms",
                deadline,
                "update kt3_drafts set status='cancelled',token=null where id=%s",
                (draft,),
            )
            self.execute(
                "forms",
                deadline,
                "update kt3_applications set status='withdrawn' where draft=%s and status='received'",
                (draft,),
            )
            if status != "cancelled":
                self.event(key, "cancelled", revision, now, deadline)
            return result("cancelled", route, "Заявка отменена.")
        supplied = hashlib.sha256(
            str(button.get("confirmation", "")).encode()
        ).hexdigest()
        if (
            action != "confirm"
            or status not in ("draft_ready", "submitted")
            or not token
            or not secrets.compare_digest(token, supplied)
            or now >= shown + timedelta(minutes=15)
        ):
            return result("refuse", route, "Нужно актуальное подтверждение владельца.")
        previous = self.execute(
            "forms",
            deadline,
            "select number from kt3_applications where draft=%s",
            (draft,),
        ).fetchone()
        if previous:
            return result(
                "submitted", route, "Заявка уже принята.", number=str(previous[0])
            )
        if fail_submit:
            self.event(key, "submit_unavailable", revision, now, deadline)
            return result(
                "temporary_error", route, "Черновик сохранён. Попробуй позже."
            )
        total, same = self.execute(
            "forms",
            deadline,
            """select count(*),count(*) filter(where route=%s)
                        from kt3_applications where space=%s and owner=%s and created between %s and %s""",
            (
                route,
                key[0],
                key[2],
                now.replace(hour=0, minute=0, second=0, microsecond=0),
                now,
            ),
        ).fetchone()
        if total >= 10 or same >= 3:
            return result("refuse", route, "Достигнут суточный лимит заявок.")
        number = uuid.uuid4()
        self.execute(
            "forms",
            deadline,
            "insert into kt3_applications values(%s,%s,%s,%s,%s,%s,'received')",
            (draft, number, key[0], key[2], route, now),
        )
        self.execute(
            "forms",
            deadline,
            "update kt3_drafts set status='submitted' where id=%s",
            (draft,),
        )
        self.event(key, "submitted", revision, now, deadline)
        return result(
            "submitted",
            route,
            "Заявка принята в учебной песочнице.",
            number=str(number),
        )
