"""Record correction verification without replacing initial annotation metrics."""
import json
from collections import Counter

from audit import BASE, digest, write_json
from build_v2 import OUT, read_jsonl


def main():
    gold = read_jsonl(OUT / "fkn_golden_300.jsonl")
    result = {"gold_sha256": digest(OUT / "fkn_golden_300.jsonl"),
              "kind": "verification_of_corrections_after_discussion_not_new_blind_agreement",
              "reviewers": {}, "unresolved": []}
    union = set()
    expected_ids = {r["id"] for r in gold if r["split"] == "dev"} | {
        "E010", "E013", "E015", "E032", "E264", "E267", "E275", "E296"}
    for label in ("a", "b"):
        review = read_jsonl(OUT / f"review_{label}.jsonl")
        resolution = read_jsonl(OUT / f"resolution_{label}.jsonl")
        if len(review) != len(expected_ids) or {r["id"] for r in review} != expected_ids:
            raise ValueError(f"Review {label}: incomplete or duplicate coverage")
        issues = {r["id"] for r in review if r["verdict"] != "valid"}
        if len(resolution) != len(issues) or {r["id"] for r in resolution} != issues:
            raise ValueError(f"Resolution {label}: incomplete or duplicate coverage")
        unresolved = [r["id"] for r in resolution if not r["resolved"] or r["remaining_issues"]]
        result["unresolved"].extend({"reviewer": label, "id": cid} for cid in unresolved)
        union |= issues
        result["reviewers"][label] = {"cases_reviewed": len(review),
                                     "review_verdicts": dict(Counter(r["verdict"] for r in review)),
                                     "cases_rechecked": len(resolution), "all_own_issues_resolved": not unresolved,
                                     "review_sha256": digest(OUT / f"review_{label}.jsonl"),
                                     "resolution_sha256": digest(OUT / f"resolution_{label}.jsonl")}
    result["distinct_cases_with_resolved_review_comments"] = len(union)
    result["reviewed_case_ids"] = sorted(expected_ids)
    result["resolution_case_ids"] = sorted(union)
    result["all_300_semantically_double_reviewed"] = False
    write_json(OUT / "correction_verification.json", result)
    if result["unresolved"]:
        raise SystemExit("Unresolved correction comments")
    manifest = json.loads((OUT / "manifest.json").read_text())
    artifacts = ["fkn_golden_300.jsonl", "registry.csv", "form_schemas.json", "design_doc_kt2.md",
                 "reviewed_candidate.jsonl", "review_input_manifest.json", "review_a.jsonl", "review_b.jsonl",
                 "resolution_a.jsonl", "resolution_b.jsonl", "correction_verification.json"]
    manifest["artifact_sha256"] = {name: digest(OUT / name) for name in artifacts}
    write_json(OUT / "manifest.json", manifest)
    print(json.dumps({"reviewed_cases_per_agent": len(expected_ids), "resolved_cases": len(union),
                      "remaining_issues": result["unresolved"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
