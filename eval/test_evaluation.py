import json
import tempfile
import unittest
from pathlib import Path

from agreement import canonical, categorical, compute, fields, read_rows, sets


class AgreementTests(unittest.TestCase):
    def test_kappa_with_unequal_marginals(self):
        # 20 YY, 5 YN, 10 NY, 15 NN: p_o=.7, p_e=.5, kappa=.4.
        a = ["yes"] * 25 + ["no"] * 25
        b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
        result = categorical(a, b)
        self.assertEqual(result["matches"], 35)
        self.assertAlmostEqual(result["agreement"], .7)
        self.assertAlmostEqual(result["cohens_kappa"], .4)

    def test_degenerate_distribution_is_not_kappa_one(self):
        result = categorical(["answer"] * 3, ["answer"] * 3)
        self.assertEqual(result["agreement"], 1)
        self.assertIsNone(result["cohens_kappa"])
        self.assertIsNone(categorical([], [])["agreement"])

    def test_unpaired_labels_fail(self):
        with self.assertRaises(ValueError):
            categorical(["a"], [])

    def test_set_f1_and_empty_denominators(self):
        result = sets([["F1", "F2"], []], [["F2", "F3"], []])
        self.assertEqual(result["micro_set_f1"], .5)
        self.assertEqual(result["exact_matches"], 1)
        self.assertEqual(result["both_empty_cases"], 1)
        self.assertIsNone(sets([[]], [[]])["micro_set_f1"])

    def test_fields_distinguish_missing_null_and_types(self):
        result = fields([{"x": None, "n": 1}], [{"n": "1"}])
        self.assertEqual(result["field_slots"], 2)
        self.assertEqual(result["matching_fields"], 0)
        self.assertNotEqual(canonical(False), canonical(0))
        self.assertEqual(canonical("  Иванов \nИван"), canonical("иванов Иван"))
        self.assertIsNone(fields([{}], [{}])["full_draft_agreement"])

    def test_duplicate_ids_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl"
            path.write_text('{"id":"E1"}\n{"id":"E1"}\n')
            with self.assertRaises(ValueError):
                read_rows(path)

    def test_missing_annotations_cannot_be_silently_dropped(self):
        with self.assertRaises(ValueError):
            compute({}, {}, {"E1": {"candidate_facts": {}}})


if __name__ == "__main__":
    unittest.main()
