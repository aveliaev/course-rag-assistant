"""Run metadata, document-level retrieval metrics and B0 scoring. Gold only enters here."""

import json

from fkn_assistant.config import BASE, PACKAGE
from fkn_assistant.evaluation.dataset import FORM_CONTEXT, fixed_sample, write_json
from fkn_assistant.forms import RULES, rule_reference
from fkn_assistant.index import MANIFEST, checksum
from fkn_assistant.rag import OPTIONS, PROMPT
from fkn_assistant.rag_answer import RagAnswer
from fkn_assistant.retrieval_config import calibration, search_fingerprint


def settings(repo):
    files = sorted(
        path.relative_to(BASE).as_posix()
        for path in PACKAGE.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    files.extend(
        (
            "infra/compose.yaml",
            "infra/requirements-lock.txt",
            "pyproject.toml",
            "run_b0.sh",
        )
    )
    return {
        "prompt": PROMPT,
        "request_options": OPTIONS,
        "schema": RagAnswer.model_json_schema(),
        "index": json.loads(MANIFEST.read_text()),
        "rules": RULES,
        "max_steps": 6,
        "programs_sha256": checksum(repo / "tmp_dataset/programs/programs.csv"),
        "code": {name: checksum(BASE / name) for name in files},
        "retrieval_calibration": calibration(),
        "input_tokens_max": 2900,
        "local_cost_rub": 0,
        "billing_basis": "PERS Freemium, compute on local machine",
    }


def calibrate(search, cases, profiles):
    from fkn_assistant.rag import period_for

    rows = []
    for case in fixed_sample(cases, 20):
        allowed = {
            s["document_id"]
            for s in case["expected"].get("allowed_sources", [])
            if s.get("source_kind") != "synthetic"
        }
        if case["category"] in FORM_CONTEXT:
            continue
        hits = search.retrieve(
            case["input"],
            profiles[case["student_profile_id"]],
            period_for(case["input"]),
        )
        rows.append(
            {
                "id": case["id"],
                "score": hits[0]["score"] if hits else 0,
                "has_reference": bool(allowed),
                "hit5": any(h["doc_id"] in allowed for h in hits[:5]),
            }
        )
    # Count correct passes (applicable document retrieved) and correct abstentions.
    scores = {
        str(t): sum(
            (r["score"] >= t and r["hit5"])
            or (r["score"] < t and not r["has_reference"])
            for r in rows
        )
        for t in (0.45, 0.5, 0.55, 0.65)
    }
    best = max(scores, key=lambda t: (scores[t], -abs(float(t) - 0.5)))
    data = dict(
        collection=search.index["collection"],
        search_code=search_fingerprint(),
        threshold=float(best),
        candidates=scores,
        rows=rows,
        source="frozen dev smoke (overlaps full dev); default Qdrant RRF",
    )
    write_json(MANIFEST.with_name("retrieval.json"), data)
    return data


def attempt(app, case, profile, repeat, space):
    # Keep each independent case and repeat isolated, including restarts after a partial write.
    import uuid

    session = f"{case['id']}-{repeat}-{uuid.uuid4().hex}"
    answer, trace = app.turn(space, session, profile, case["input"], case["now"])
    has_confirmation = bool(answer.pop("confirmation", None))
    gold = case["expected"]
    statuses = gold.get("acceptable_statuses", [gold["status"]])
    routes = gold.get("acceptable_routes") or (
        [gold["route"]] if gold.get("route") else []
    )
    good_status = answer["status"] in statuses
    good_route = (answer["route"] in routes) if routes else None
    gold_fields = gold.get("request_fields") or {}
    fields = answer["fields"]
    matching = sum(
        k in fields and type(fields[k]) is type(v) and fields[k] == v
        for k, v in gold_fields.items()
    )
    evidence = app.sandbox.evidence((space, session, str(profile["id"])))
    journal = evidence["events"]
    # Only a ready card counts as a created draft in KT2. A clarify card stores working fields.
    observed_actions = {
        "created_drafts": sum(e["event"] == "draft_ready" for e in journal),
        "submit_application_calls": sum(
            e["event"] in ("submitted", "submit_unavailable") for e in journal
        ),
        "created_tickets": 0,
        "sent_emails": 0,
        "unsupported_application_writes": sum(
            e["event"] == "unsupported_application_write" for e in journal
        ),
    }
    # These channels have no senders in the local sandbox. An application must also have a durable row.
    action_ok = (
        all(
            observed_actions[k] == value
            for k, value in gold.get("tool_assertions", {}).items()
        )
        and not evidence["applications"]
    )
    form_ok = None
    retrieved = trace["retrieved"]
    sources = {h["citation_id"] for h in trace["context"]}
    valid_cites = all(h["citation_id"] in sources for h in answer["citations"])
    field_sources_ok = confirmation_ok = rule_ok = None
    if gold.get("request_type") in FORM_CONTEXT:
        field_sources_ok = answer.get("field_sources", {}) == (
            gold.get("field_sources") or {}
        )
        confirmation_ok = has_confirmation == gold["requires_confirmation"]
        needed = answer["missing_fields"] + answer["invalid_fields"]
        if not needed:
            needed = (
                ["eligibility"] if answer["status"] == "refuse" else ["confirmation"]
            )
        rule_ok = answer["route"] == gold["request_type"] and answer["citations"] == [
            rule_reference(answer["route"], field) for field in needed
        ]
        valid_cites = rule_ok
        form_ok = bool(
            good_status
            and good_route
            and matching == len(gold_fields)
            and set(fields) == set(gold_fields)
            and sorted(answer["missing_fields"])
            == sorted(gold.get("missing_fields", []))
            and sorted(answer["invalid_fields"])
            == sorted(gold.get("invalid_fields", []))
            and field_sources_ok
            and confirmation_ok
            and action_ok
            and rule_ok
        )
    allowed = {
        s["document_id"]
        for s in gold.get("allowed_sources", [])
        if s.get("source_kind") != "synthetic"
    }
    valid = (
        answer["status"]
        in ("answer", "answer_partial", "clarify", "refuse", "draft_ready")
        and 0 < len(answer["answer"]) <= 800
        and valid_cites
    )
    checks = {
        "valid_format": valid,
        "status_ok": good_status and not trace["error"],
        "route_ok": good_route,
        "form_ok": form_ok,
        "field_sources_ok": field_sources_ok,
        "confirmation_ok": confirmation_ok,
        "rule_ok": rule_ok,
        "action_ok": action_ok,
        "form_fields_total": len(gold_fields),
        "form_fields_correct": matching,
        "no_unsupported_citations": valid_cites,
    }
    for k in (5, 20):
        checks[f"gold_hit_{k}"] = (
            any(h["doc_id"] in allowed for h in retrieved[:k]) if allowed else None
        )
    checks["cited_gold_document"] = (
        any(h["doc_id"] in allowed for h in answer["citations"]) if allowed else None
    )
    return dict(
        case_id=case["id"],
        category=case["category"],
        repeat=repeat,
        model=trace["model"],
        raw_answer=json.dumps(answer, ensure_ascii=False),
        parsed=answer,
        checks=checks,
        error=trace["error"],
        usage=trace["usage"],
        latency_sec=trace["latency_sec"],
        now=case["now"],
        trace=trace,
        action_evidence={
            **evidence,
            "observed": observed_actions,
            "expected": gold.get("tool_assertions", {}),
        },
    )
