import contextlib
import io
import sys
import unittest
from unittest.mock import patch

from scripts import validate_paraphrases
from tests.helpers import CASES


class ParaphraseSuiteTests(unittest.TestCase):
    def test_labels_cover_all_types_and_new_wording(self):
        original_notes = {note for case in CASES for note in case["input"]["operator_notes"]}
        covered = set()
        for case in validate_paraphrases.cases():
            self.assertTrue(all(note not in original_notes for note in case["input"]["operator_notes"]))
            self.assertEqual(len(case["input"]["operator_notes"]), len(case["expected_output"]["directive_interpretation"]))
            covered.update(d["directive_type"] for d in case["expected_output"]["directive_interpretation"])
        self.assertEqual(covered, {"solar_reduction", "no_charge_window", "no_discharge_window",
                                   "minimum_battery_reserve", "max_grid_window", "no_op"})

    def test_offline_cases_preserve_reference_optimum(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["runner", "--offline"]), contextlib.redirect_stdout(output):
            self.assertEqual(validate_paraphrases.main(), 0)
        self.assertIn("cases=7 failures=0", output.getvalue())
        self.assertIn("no language-model evidence", output.getvalue())