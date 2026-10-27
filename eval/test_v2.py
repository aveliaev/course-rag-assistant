import copy
import csv
import json
import unittest

from audit import BASE
from build_v2 import OUT, read_jsonl
from validate_v2 import validate


class RevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = read_jsonl(OUT / "fkn_golden_300.jsonl")
        cls.originals = read_jsonl(BASE / "inputs/fkn_golden_300.jsonl")
        cls.profiles = {p["id"]: p for p in json.loads((BASE / "inputs/students.json").read_text())}
        with (OUT / "registry.csv").open() as stream:
            cls.registry = {r["doc_id"]: r for r in csv.DictReader(stream)}
        cls.schemas = json.loads((OUT / "form_schemas.json").read_text())

    def check_rows(self, rows):
        return validate(rows, self.originals, self.profiles, self.registry, self.schemas)

    def test_full_revision_has_valid_sources_and_branches(self):
        self.assertEqual(self.check_rows(self.rows), [])

    def test_missing_case_is_not_removed_from_denominator(self):
        self.assertTrue(any("300 cases" in e for e in self.check_rows(self.rows[:-1])))

    def test_ready_draft_cannot_have_unknown_language(self):
        rows = copy.deepcopy(self.rows)
        row = next(c for c in rows if c["id"] == "E120")
        row["expected"]["branches"][0]["request_fields"]["language"] = None
        self.assertTrue(any("incomplete ready draft" in e for e in self.check_rows(rows)))

    def test_own_profile_and_consent_are_enforced(self):
        rows = copy.deepcopy(self.rows)
        row = next(c for c in rows if c["id"] == "E120")
        branch = row["expected"]["branches"][0]
        branch["request_fields"]["student_id"] = "demo-student-001"
        branch["submit_calls"] = 1
        errors = self.check_rows(rows)
        self.assertTrue(any("owner mismatch" in e for e in errors))
        self.assertTrue(any("unconsented side effect" in e for e in errors))

    def test_certificate_language_is_not_interface_language(self):
        row = next(c for c in self.rows if c["id"] == "E013")
        branch = row["expected"]["branches"][0]
        self.assertEqual(branch["status"], "clarify")
        self.assertIsNone(branch["collected_fields"]["language"])
        self.assertFalse(branch["card_required"])
        self.assertEqual(branch["required_fact_ids"], ["F4"])
        self.assertEqual(branch["clarification_fields"], ["language"])

    def test_formulas_not_required_for_clarifying_branch(self):
        for cid, required in [("E002", ["F6"]), ("E127", ["F2"])]:
            row = next(c for c in self.rows if c["id"] == cid)
            clarify, answer = row["expected"]["branches"]
            self.assertEqual(clarify["required_fact_ids"], required)
            self.assertGreater(len(answer["required_fact_ids"]), len(required))

    def test_targeted_weight_question_does_not_require_entire_formula(self):
        for cid in ("E103", "E159", "E289"):
            branch = next(c for c in self.rows if c["id"] == cid)["expected"]["branches"][0]
            self.assertEqual(branch["required_fact_ids"], ["F2"])
            self.assertIn("F1", branch["optional_fact_ids"])

    def test_feedback_receipt_is_not_upload_deadline(self):
        expected = next(c for c in self.rows if c["id"] == "E217")["expected"]
        self.assertEqual(expected["status"], "answer_partial")
        self.assertIn("получение", expected["facts"]["F2"]["text"])
        self.assertIn("не установлен", expected["facts"]["F2"]["text"])

    def test_behavioral_constraints_are_not_required_response_prose(self):
        for case in self.rows:
            behavior = set(case["expected"]["behavior_fact_ids"])
            for branch in case["expected"]["branches"]:
                self.assertFalse(behavior & set(branch["required_fact_ids"]))


if __name__ == "__main__":
    unittest.main()
