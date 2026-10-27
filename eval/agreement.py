"""Compute agreement before adjudication; incomplete/invalid annotation files fail."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from audit import BASE, ROOT, digest, norm, write_json

CATEGORIES = {
    "status": {"answer", "answer_partial", "clarify", "draft_ready", "refuse", "escalation_offered", "temporary_error"},
    "scenario": {"none", "temp_pass", "enrollment_certificate", "sick_notice"},
    "answerability": {"full", "partial", "none", "needs_context"},
    "escalation": {"not_needed", "offer", "uncertain"},
    "gold_validity": {"valid", "revise", "uncertain"},
}
FACT_LABELS = {"supported", "unsupported", "uncertain"}


def read_rows(path):
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate case IDs: {path}")
    return {r["id"]: r for r in rows}


def categorical(left, right):
    if len(left) != len(right):
        raise ValueError("Paired labels required")
    n = len(left)
    a, b = Counter(left), Counter(right)
    agree = sum(x == y for x, y in zip(left, right))
    observed = agree / n if n else None
    expected = sum(a[k] * b[k] for k in a.keys() | b.keys()) / n**2 if n else None
    kappa = (observed - expected) / (1 - expected) if n and expected < 1 else None
    return {"n": n, "matches": agree, "agreement": observed, "expected_agreement": expected,
            "cohens_kappa": kappa, "marginal_a": dict(a), "marginal_b": dict(b),
            "confusion": [{"a": x, "b": y, "count": count}
                          for (x, y), count in sorted(Counter(zip(left, right)).items())]}


def sets(left, right):
    pair = [(set(a), set(b)) for a, b in zip(left, right)]
    both = sum(len(a & b) for a, b in pair)
    total = sum(len(a) + len(b) for a, b in pair)
    nonempty = [(a, b) for a, b in pair if a or b]
    return {"n": len(pair), "exact_matches": sum(a == b for a, b in pair),
            "exact_agreement": sum(a == b for a, b in pair) / len(pair) if pair else None,
            "intersection_items": both, "total_selected_items": total,
            "micro_set_f1": 2 * both / total if total else None,
            "macro_set_f1_nonempty": sum(2 * len(a & b) / (len(a) + len(b)) for a, b in nonempty) / len(nonempty) if nonempty else None,
            "both_empty_cases": len(pair) - len(nonempty)}


def canonical(value):
    # Do not coerce false/0, absent/null or string/numeric values into equality.
    if isinstance(value, str):
        return ("string", norm(value))
    if isinstance(value, dict):
        return ("object", tuple(sorted((k, canonical(v)) for k, v in value.items())))
    if isinstance(value, list):
        return ("array", tuple(map(canonical, value)))
    return (type(value).__name__, value)


def fields(left, right):
    slots = matches = drafts = full = 0
    for a, b in zip(left, right):
        if not a and not b:
            continue
        drafts += 1
        full += canonical(a) == canonical(b)
        for key in a.keys() | b.keys():
            slots += 1
            matches += key in a and key in b and canonical(a[key]) == canonical(b[key])
    return {"field_slots": slots, "matching_fields": matches,
            "field_agreement": matches / slots if slots else None,
            "draft_cases_with_any_fields": drafts, "fully_matching_drafts": full,
            "full_draft_agreement": full / drafts if drafts else None}


def validate(rows, tasks):
    if rows.keys() != tasks.keys():
        raise ValueError(f"Coverage mismatch; missing={sorted(tasks.keys()-rows.keys())}, extra={sorted(rows.keys()-tasks.keys())}")
    identities = {(r["annotator_id"], r["annotator_kind"]) for r in rows.values()}
    if len(identities) != 1 or next(iter(identities))[1] not in {"human", "ai"}:
        raise ValueError("One identified annotator and kind required per file")
    warnings = []
    for cid, row in rows.items():
        for key, options in CATEGORIES.items():
            if row.get(key) not in options:
                raise ValueError(f"{cid}: invalid {key}: {row.get(key)}")
        facts = tasks[cid]["candidate_facts"]
        if row["fact_labels"].keys() != facts.keys() or any(v not in FACT_LABELS for v in row["fact_labels"].values()):
            raise ValueError(f"{cid}: complete valid fact labels required")
        if not set(row["required_fact_ids"]) <= facts.keys():
            raise ValueError(f"{cid}: unknown required fact")
        if any(row["fact_labels"][f] != "supported" for f in row["required_fact_ids"]):
            raise ValueError(f"{cid}: unsupported/uncertain fact cannot be mandatory")
        if not isinstance(row["field_values"], dict) or not isinstance(row["source_ids"], list):
            raise ValueError(f"{cid}: invalid fields or sources")
        valid_fact_evidence = set()
        for evidence in row["evidence"]:
            did = evidence["document_id"]
            path = BASE / "annotation/RUBRIC.md" if did == "contract" else BASE / "evidence" / f"{did}.txt"
            if not path.is_file():
                warnings.append({"id": cid, "issue": "missing_evidence_file", "evidence": evidence})
                continue
            lines = path.read_text().splitlines()
            start, end = evidence["line_start"], evidence["line_end"]
            if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end <= len(lines):
                warnings.append({"id": cid, "issue": "invalid_evidence_locator", "evidence": evidence})
                continue
            excerpt = "\n".join(lines[start-1:end])
            if did != "contract":
                import re
                excerpt = "\n".join(re.sub(r"^\d+: ", "", l) for l in lines[start-1:end])
            if not evidence.get("quote") or norm(evidence["quote"]) not in norm(excerpt):
                warnings.append({"id": cid, "issue": "quote_not_literal_at_locator", "evidence": evidence})
                continue
            fact_id = evidence.get("fact_id")
            if fact_id not in facts:
                warnings.append({"id": cid, "issue": "unknown_fact_in_evidence", "evidence": evidence})
            else:
                valid_fact_evidence.add(fact_id)
        for fid, label in row["fact_labels"].items():
            if label == "supported" and fid not in valid_fact_evidence:
                warnings.append({"id": cid, "fact_id": fid, "issue": "supported_fact_without_valid_quote"})
    return warnings


def compute(left, right, tasks):
    warnings_a, warnings_b = validate(left, tasks), validate(right, tasks)
    identity_a = next(iter(left.values()))["annotator_id"]
    identity_b = next(iter(right.values()))["annotator_id"]
    if identity_a == identity_b:
        raise ValueError("Two different annotator IDs required")
    ids = sorted(tasks)
    report = {"n_cases": len(ids), "split": "dev", "pre_adjudication": True,
              "annotator_a": {"id": identity_a, "kind": next(iter(left.values()))["annotator_kind"]},
              "annotator_b": {"id": identity_b, "kind": next(iter(right.values()))["annotator_kind"]},
              "evidence_warnings": {"a": warnings_a, "b": warnings_b}}
    for key in CATEGORIES:
        report[key] = categorical([left[i][key] for i in ids], [right[i][key] for i in ids])
    atom_keys = [(i, f) for i in ids for f in tasks[i]["candidate_facts"]]
    report["fact_support"] = categorical([left[i]["fact_labels"][f] for i, f in atom_keys],
                                          [right[i]["fact_labels"][f] for i, f in atom_keys])
    report["required_fact_membership"] = categorical(
        [f in left[i]["required_fact_ids"] for i, f in atom_keys],
        [f in right[i]["required_fact_ids"] for i, f in atom_keys])
    source_keys = [(i, s) for i in ids for s in sorted(
        {d["document_id"] for d in tasks[i]["source_pool"]} |
        set(left[i]["source_ids"]) | set(right[i]["source_ids"]))]
    report["source_membership"] = categorical(
        [s in left[i]["source_ids"] for i, s in source_keys],
        [s in right[i]["source_ids"] for i, s in source_keys])
    for key in ("required_fact_ids", "source_ids"):
        report[key] = sets([left[i][key] for i in ids], [right[i][key] for i in ids])
    report["fields"] = fields([left[i]["field_values"] for i in ids], [right[i]["field_values"] for i in ids])
    report["disagreements"] = [{"id": i, "dimensions": [k for k in CATEGORIES if left[i][k] != right[i][k]],
                                 "fact_labels": [f for f in tasks[i]["candidate_facts"] if left[i]["fact_labels"][f] != right[i]["fact_labels"][f]],
                                 "required_fact_sets_differ": set(left[i]["required_fact_ids"]) != set(right[i]["required_fact_ids"]),
                                 "source_sets_differ": set(left[i]["source_ids"]) != set(right[i]["source_ids"]),
                                 "fields_differ": canonical(left[i]["field_values"]) != canonical(right[i]["field_values"])} for i in ids]
    report["disagreements"] = [r for r in report["disagreements"] if r["dimensions"] or r["fact_labels"] or any(r[k] for k in ("required_fact_sets_differ", "source_sets_differ", "fields_differ"))]
    report["rubric_ready_by_primary_thresholds"] = all(report[k]["agreement"] >= .9 and report[k]["cohens_kappa"] is not None and report[k]["cohens_kappa"] >= .8 for k in ("status", "scenario", "answerability", "escalation"))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    parser.add_argument("--tasks", type=Path, default=BASE / "annotation/tasks_dev.jsonl")
    parser.add_argument("--output", type=Path, default=BASE / "reports/agreement.json")
    args = parser.parse_args()
    tasks, a, b = map(read_rows, (args.tasks, args.a, args.b))
    report = compute(a, b, tasks)
    report["input_sha256"] = {"tasks": digest(args.tasks), "a": digest(args.a), "b": digest(args.b),
                                "rubric": digest(BASE / "annotation/RUBRIC.md")}
    write_json(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("disagreements", "evidence_warnings")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
