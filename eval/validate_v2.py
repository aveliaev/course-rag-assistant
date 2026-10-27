"""Validate v2 source identities, branch criteria and field provenance offline."""
import csv
import json
import re
from pathlib import Path

from audit import BASE, ROOT, digest, norm, write_json
from build_v2 import MVP, OUT, RUNTIME, read_jsonl


def validate(cases, originals, profiles, registry, schemas):
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    original_map = {c["id"]: c for c in originals}
    check(len(cases) == len(originals) == 300, "The revision must retain all 300 cases")
    check(len({c["id"] for c in cases}) == len(cases), "Duplicate case IDs")
    check({c["id"] for c in cases} == original_map.keys(), "Case ID set changed")
    for case in cases:
        cid, expected = case["id"], case["expected"]
        original = original_map.get(cid)
        if not original:
            continue
        for key in ("split", "input", "student_profile_id", "now", "category"):
            check(case[key] == original[key], f"{cid}: immutable {key} changed")
        check(case.get("schema_version") == "2.0", f"{cid}: schema_version")
        check(case.get("timezone") == "Europe/Moscow", f"{cid}: timezone")
        check(len(case["input"]) <= 2000, f"{cid}: input length")
        check(expected["status"] in RUNTIME, f"{cid}: invalid runtime status")
        check("required_facts" not in expected, f"{cid}: legacy global fact rubric is ambiguous")
        branches = expected["branches"]
        check(bool(branches), f"{cid}: no outcome branches")
        check(branches[0]["status"] == expected["status"], f"{cid}: primary branch mismatch")
        profile = profiles.get(case["student_profile_id"])
        check(profile is not None, f"{cid}: profile missing")
        for source in expected["allowed_sources"] + expected["distractor_sources"]:
            did = source["document_id"]
            check(did in registry, f"{cid}: unknown source {did}")
            if did not in registry:
                continue
            check(source["document_version"] == f"sha256:{registry[did]['sha256']}", f"{cid}: wrong content version {did}")
            check((ROOT / source["path"]).is_file(), f"{cid}: missing source file {did}")
            if source["evidence_role"] == "absence_check":
                check(source["citation_required"] is False, f"{cid}: absent clause cannot be required citation")
        for fid, fact in expected["facts"].items():
            check(isinstance(fact["text"], str) and bool(fact["text"].strip()), f"{cid}/{fid}: empty fact")
            for evidence in fact["evidence"]:
                did = evidence["document_id"]
                check(evidence["document_version"] == f"sha256:{registry[did]['sha256']}", f"{cid}/{fid}: evidence version")
                lines = (ROOT / evidence["evidence_path"]).read_text().splitlines()
                start, end = evidence["line_start"], evidence["line_end"]
                check(1 <= start <= end <= len(lines), f"{cid}/{fid}: invalid locator")
                quote = "\n".join(re.sub(r"^\d+: ", "", l) for l in lines[start-1:end])
                check(quote == evidence["quote"], f"{cid}/{fid}: quote differs from snapshot")
        for branch in branches:
            status, scenario = branch["status"], branch["scenario"]
            check(status in RUNTIME, f"{cid}: branch runtime status")
            check(scenario == "none" or scenario in MVP, f"{cid}: unsupported scenario")
            check(set(branch["required_fact_ids"]) <= expected["facts"].keys(), f"{cid}: undefined mandatory fact")
            check(set(branch["optional_fact_ids"]) <= expected["facts"].keys(), f"{cid}: undefined optional fact")
            check(not set(branch["required_fact_ids"]) & set(branch["optional_fact_ids"]), f"{cid}: required/optional overlap")
            check(not set(branch["required_fact_ids"]) & set(expected["behavior_fact_ids"]), f"{cid}: behavior need not be recited in response")
            check(branch["submit_calls"] == branch["escalation_create_calls"] == 0, f"{cid}: unconsented side effect")
            fields = branch.get("request_fields", branch.get("collected_fields", {}))
            if scenario == "none":
                check(not fields, f"{cid}: non-MVP action has draft fields")
                check(status != "draft_ready", f"{cid}: draft without scenario")
                continue
            required = schemas["forms"][scenario]["required"]
            defaults = schemas["forms"][scenario]["defaults"]
            check(set(fields) == set(required), f"{cid}: form field set")
            check(branch["card_required"] == (status == "draft_ready"), f"{cid}: clarification must not require a displayed draft")
            check(set(branch["field_sources"]) == set(fields), f"{cid}: provenance coverage")
            missing = [f for f in required if fields.get(f) is None]
            check(set(branch["clarification_fields"]) == set(missing), f"{cid}: missing-field question set")
            check(status != "draft_ready" or not missing, f"{cid}: incomplete ready draft")
            check(status != "clarify" or bool(missing), f"{cid}: superfluous clarification")
            for field, value in fields.items():
                source = branch["field_sources"][field]
                kind = source["kind"]
                if kind == "profile":
                    check(source["profile_id"] == case["student_profile_id"], f"{cid}/{field}: foreign profile")
                    check(profile is not None and value == profile.get(source["field"]), f"{cid}/{field}: profile mismatch")
                elif kind == "default":
                    check(field in defaults and type(value) is type(defaults[field]) and value == defaults[field], f"{cid}/{field}: bad default")
                elif kind == "user":
                    check(norm(source["quote"]) in norm(case["input"]), f"{cid}/{field}: quote not in input")
                elif kind == "unknown":
                    check(value is None, f"{cid}/{field}: invented unknown value")
                else:
                    check(False, f"{cid}/{field}: unknown provenance kind")
            check(fields.get("student_id") == case["student_profile_id"], f"{cid}: owner mismatch")
    return errors


def main():
    cases = read_jsonl(OUT / "fkn_golden_300.jsonl")
    originals = read_jsonl(BASE / "inputs/fkn_golden_300.jsonl")
    profiles = {p["id"]: p for p in json.loads((BASE / "inputs/students.json").read_text())}
    with (OUT / "registry.csv").open() as stream:
        registry = {r["doc_id"]: r for r in csv.DictReader(stream)}
    schemas = json.loads((OUT / "form_schemas.json").read_text())
    manifest = json.loads((OUT / "manifest.json").read_text())
    errors = validate(cases, originals, profiles, registry, schemas)
    for name, expected_hash in manifest["source_inputs"].items():
        if digest(BASE / "inputs" / name) != expected_hash:
            errors.append(f"Original input modified: {name}")
    if digest(OUT / "fkn_golden_300.jsonl") != manifest["gold_sha256"]:
        errors.append("Generated gold differs from manifest")
    baseline = json.loads((BASE / "reports/agreement.json").read_text())
    for label in ("a", "b"):
        if digest(BASE / f"annotation/annotator_{label}.jsonl") != baseline["input_sha256"][label]:
            errors.append(f"Original independent annotation {label} was overwritten")
    report = {"cases_checked": len(cases), "errors": errors,
              "structural_and_provenance_checks_passed": not errors,
              "all_300_semantically_double_reviewed": False}
    write_json(OUT / "validation.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
