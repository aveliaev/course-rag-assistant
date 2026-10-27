"""Offline audit and evidence bundle. Run from any directory with Python 3.10+."""
import argparse
from bisect import bisect_right
import csv
import hashlib
import json
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "eval"
PROFILE_FIELDS = {"student_full_name": "full_name", "study_group": "study_group",
                  "course": "course", "educational_program": "educational_program", "email": "email"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in values))


def norm(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value))).strip().casefold()


def extract(path):
    if path.suffix == ".md":
        return path.read_text().splitlines(), "source_line"
    if path.suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            tree = ET.fromstring(archive.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return [
            "".join(t.text or "" for t in p.findall(".//w:t", ns))
            for p in tree.findall(".//w:p", ns)], "extracted_paragraph"
    if path.suffix == ".pdf":
        import fitz  # PyMuPDF; only needed for the six referenced PDF documents.
        lines = []
        with fitz.open(path) as pdf:
            for page_index, page in enumerate(pdf):
                lines.append(f"[PDF page {page_index + 1}]")
                lines.extend(page.get_text().splitlines())
        return lines, "extracted_line_with_page_markers"
    raise ValueError(f"Unsupported format: {path.suffix}")


def run():
    cases = [json.loads(l) for l in (BASE / "inputs/fkn_golden_300.jsonl").read_text().splitlines() if l.strip()]
    profiles = json.loads((BASE / "inputs/students.json").read_text())
    profile_map = {p["id"]: p for p in profiles}
    registry = list(csv.DictReader((ROOT / "tmp_dataset/registry.csv").open()))
    docs = {d["doc_id"]: d for d in registry}
    programs = list(csv.DictReader((ROOT / "tmp_dataset/programs/programs.csv").open()))
    program_map = {p["name"]: p["program_id"] for p in programs}
    source_ids = sorted({s["document_id"] for c in cases for key in ("allowed_sources", "distractor_sources")
                         for s in c["expected"].get(key, [])})
    corpus_check = []
    for doc in registry:
        path = ROOT / "tmp_dataset" / doc["path"]
        actual = digest(path) if path.is_file() else None
        corpus_check.append({"document_id": doc["doc_id"], "path": doc["path"],
                             "exists": path.is_file(), "expected_sha256": doc["sha256"],
                             "actual_sha256": actual, "hash_matches": actual == doc["sha256"]})
    corpus_map = {d["document_id"]: d for d in corpus_check}
    extraction = {}
    searchable = {}
    for doc_id in source_ids:
        if doc_id not in docs:
            extraction[doc_id] = {"error": "missing registry entry"}
            continue
        d = docs[doc_id]
        try:
            lines, locator = extract(ROOT / "tmp_dataset" / d["path"])
            out = BASE / "evidence" / f"{doc_id}.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(f"{i}: {l}" for i, l in enumerate(lines, 1)) + "\n")
            extraction[doc_id] = {"evidence_path": str(out.relative_to(ROOT)), "locator_kind": locator,
                                  "text_chars": sum(map(len, lines)), "lines": lines}
            normalized_lines = [norm(l) for l in lines]
            offsets, offset = [], 0
            for line in normalized_lines:
                offsets.append(offset)
                offset += len(line) + 1
            searchable[doc_id] = (" ".join(normalized_lines), offsets)
        except Exception as exc:
            extraction[doc_id] = {"error": f"{type(exc).__name__}: {exc}"}
    linked = []
    packets = []
    for case in cases:
        expected = case["expected"]
        profile = profile_map.get(case["student_profile_id"])
        program_id = program_map.get(profile["educational_program"]) if profile else None
        issues = []
        sources = []
        for role in ("allowed_sources", "distractor_sources"):
            for source in expected.get(role, []):
                did = source["document_id"]
                doc = docs.get(did)
                ext = extraction.get(did, {})
                item = dict(source, role=role, registry=doc,
                            file_integrity=corpus_map.get(did),
                            extracted={k: v for k, v in ext.items() if k != "lines"})
                item["snapshot_version"] = f"sha256:{corpus_map[did]['actual_sha256']}" if did in corpus_map else None
                flags = []
                if doc:
                    if doc["scope"] == "program" and program_id not in doc["program_ids"].split(";"):
                        flags.append("program_mismatch")
                    if doc["intake_year"] and str(profile.get("admission_year") if profile else None) not in doc["intake_year"].split(";"):
                        flags.append("intake_mismatch")
                    if doc["is_current"] != "true":
                        flags.append("not_marked_current")
                    if "отсутств" in source.get("clause_id", "").casefold():
                        flags.append("absence_claim_not_a_citable_clause")
                    if doc["doc_type"] == "syllabus":
                        flags.append("enrollment_fixture_not_provided")
                else:
                    flags.append("missing_document")
                item["review_flags"] = flags
                sources.append(item)
        fields = []
        for field, value in expected.get("request_fields", {}).items():
            origin = PROFILE_FIELDS.get(field)
            if origin and profile:
                status = "profile_exact_match" if value == profile.get(origin) else "profile_mismatch"
                ref = f"eval/inputs/students.json#{case['student_profile_id']}/{origin}"
                evidence_value = profile.get(origin)
            elif value is None:
                status, ref, evidence_value = "unknown_requires_clarification", None, None
            elif norm(value) in norm(case["input"]):
                status, ref, evidence_value = "literal_in_input", f"{case['id']}/input", value
            else:
                status, ref, evidence_value = "needs_semantic_or_default_review", None, None
            fields.append({"field": field, "value": value, "status": status,
                           "source": ref, "source_value": evidence_value})
        fact_bindings = []
        for number, fact in enumerate(expected["required_facts"], 1):
            queries = [("full_fact", fact)]
            formula = re.match(r"^\d{4}/\d{4},.*?модул[ья]:\s*(.+)$", fact)
            if formula:
                queries.append(("formula_body", formula.group(1)))
            matches = []
            for source in expected["allowed_sources"]:
                did = source["document_id"]
                if did not in searchable:
                    continue
                text, offsets = searchable[did]
                for kind, query in queries:
                    normalized_query = norm(query)
                    index = text.find(normalized_query)
                    if index < 0:
                        continue
                    start = bisect_right(offsets, index)
                    end = bisect_right(offsets, index + len(normalized_query) - 1)
                    matches.append({"document_id": did, "match_kind": kind,
                                    "line_start": start, "line_end": end,
                                    "matched_text": query,
                                    "quote": "\n".join(extraction[did]["lines"][start-1:end])})
                    break
            fact_bindings.append({"fact_id": f"F{number}", "candidate_fact": fact,
                                  "literal_matches": matches,
                                  "semantic_support_verified": False})
        if not profile:
            issues.append("missing_profile")
        if expected.get("request_type") and expected["request_type"] != "certificate":
            issues.append("request_type_outside_MVP_requires_policy_decision")
        if expected["status"] in ("handoff", "resist_attack", "draft_request"):
            issues.append("author_label_is_not_runtime_status")
        if expected.get("acceptable_statuses"):
            issues.append("branch_specific_rubric_required")
        if any(f["status"] == "profile_mismatch" for f in fields):
            issues.append("profile_field_mismatch")
        linked.append({"id": case["id"], "split": case["split"], "category": case["category"],
                       "profile_id": case["student_profile_id"], "profile_found": profile is not None,
                       "student_program_id": program_id, "source_bindings": sources, "field_bindings": fields,
                       "fact_bindings": fact_bindings,
                       "review_flags": issues, "semantic_gold_verified": False})
        if case["split"] == "dev":
            # Same neutral candidate pool for both reviewers; author labels are withheld.
            pool = {s["document_id"]: {"document_id": s["document_id"],
                    "registry": s["registry"], "extracted": s["extracted"]} for s in sources}
            packets.append({"id": case["id"], "category": case["category"], "input": case["input"],
                            "now": case["now"], "profile": profile,
                            "candidate_facts": {f"F{i}": f for i, f in enumerate(expected["required_facts"], 1)},
                            "candidate_fields": expected.get("request_fields", {}),
                            "source_pool": list(pool.values())})
    write_jsonl(BASE / "reports/corpus_integrity.jsonl", corpus_check)
    write_jsonl(BASE / "reports/linked_cases.jsonl", linked)
    write_jsonl(BASE / "annotation/tasks_dev.jsonl", packets)
    summary = {
        "case_count": len(cases), "unique_case_ids": len({c['id'] for c in cases}),
        "splits": dict(Counter(c["split"] for c in cases)), "profile_count": len(profiles),
        "referenced_profiles": len({c["student_profile_id"] for c in cases}),
        "missing_profiles": sorted({c["student_profile_id"] for c in cases} - profile_map.keys()),
        "registry_documents": len(registry), "unique_registry_ids": len(docs),
        "missing_corpus_paths": [c["document_id"] for c in corpus_check if not c["exists"]],
        "hash_mismatches": [c["document_id"] for c in corpus_check if c["exists"] and not c["hash_matches"]],
        "referenced_documents": len(source_ids), "missing_referenced_ids": sorted(set(source_ids) - docs.keys()),
        "extraction_errors": {k: v["error"] for k, v in extraction.items() if "error" in v},
        "empty_extractions": [k for k, v in extraction.items() if not v.get("error") and not v["text_chars"]],
        "runtime_fixtures_not_provided": ["course_enrollments", "schedule", "versioned_form_schemas", "submission_and_escalation_stubs", "multi_turn_continuations"],
        "field_provenance": dict(Counter(f["status"] for c in linked for f in c["field_bindings"])),
        "candidate_fact_count": sum(len(c["fact_bindings"]) for c in linked),
        "facts_with_literal_match": sum(bool(f["literal_matches"]) for c in linked for f in c["fact_bindings"]),
        "case_review_flags": dict(Counter(f for c in linked for f in c["review_flags"])),
        "source_review_flags": dict(Counter(f for c in linked for s in c["source_bindings"]
                                             if s["role"] == "allowed_sources" for f in s["review_flags"])),
        "semantic_gold_verified": False,
        "note": "Integrity, text extraction and literal field matching do not establish semantic ground truth."
    }
    write_json(BASE / "reports/audit_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    run()
