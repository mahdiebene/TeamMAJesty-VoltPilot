import copy
import json
import unittest

from pydantic import ValidationError

from app.directives import compile_bounds
from app.errors import GridWiseError
from app.json_utils import load_json
from app.optimizer import optimize
from app.replay import replay
from app.schemas import Directive, Scenario, validate_directives
from tests.helpers import CASES, analytic, directive, sample


class ContractTests(unittest.TestCase):
    def test_all_public_requests_and_reference_schedules(self):
        for i, case in enumerate(CASES):
            with self.subTest(case=case["id"]):
                scenario, directives = sample(i)
                replay(scenario, directives, case["expected_output"])

    def test_invalid_request_values(self):
        for field, value in [("demand_kwh", True), ("solar_kwh", "1"),
                             ("tariff_bdt_per_kwh", float("inf")), ("demand_kwh", -1),
                             ("hour", True), ("hour", 0.0), ("hour", 24)]:
            with self.subTest(field=field, value=value):
                data = copy.deepcopy(CASES[0]["input"])
                data["hours"][0][field] = value
                with self.assertRaises(ValidationError):
                    Scenario.model_validate(data)

    def test_duplicates_missing_notes_and_battery(self):
        for transform in [
            lambda d: d["hours"].pop(),
            lambda d: d["hours"][0].update(hour=1),
            lambda d: d.update(operator_notes=[]),
            lambda d: d.update(operator_notes=[" "]),
            lambda d: d["battery"].update(initial_energy_kwh=999999),
            lambda d: d.pop("scenario_id"),
        ]:
            data = copy.deepcopy(CASES[0]["input"])
            transform(data)
            with self.assertRaises(ValidationError):
                Scenario.model_validate(data)

    def test_explicit_metadata_and_tariff_policy(self):
        data = analytic().model_dump()
        data["metadata"] = {"ignored": True}
        data["hours"][0]["tariff_bdt_per_kwh"] = -1
        scenario = Scenario.model_validate(data)
        self.assertNotIn("metadata", scenario.model_dump())
        result = optimize(scenario, [directive()])
        replay(scenario, [directive()], json.loads(result.model_dump_json()))

    def test_guardrails(self):
        valid = directive("solar_reduction", [2, 1], factor=0.2).model_dump()
        self.assertEqual(valid["structured_adjustment"]["hours"], [1, 2])
        changes = [
            {"applies": False}, {"applies": 1}, {"directive_type": "invented"},
            {"note_index": True}, {"extra": 5}, {"explanation": " "},
            {"structured_adjustment": {"hours": [1, 1], "factor": 0.2}},
            {"structured_adjustment": {"hours": [1.0], "factor": 0.2}},
            {"structured_adjustment": {"hours": [], "factor": 0.2}},
            {"structured_adjustment": {"hours": [1], "factor": 1.1}},
            {"structured_adjustment": {"hours": [1], "factor": True}},
            {"structured_adjustment": {"hours": [1], "factor": "0.2"}},
            {"structured_adjustment": {"hours": [1], "factor": 0.2, "demand_kwh": 0}},
            {"structured_adjustment": {"hours": [1]}},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Directive.model_validate(valid | change)
        with self.assertRaises(ValidationError):
            Directive.model_validate(directive().model_dump() | {"structured_adjustment": {"hours": [1]}})

    def test_mapping_and_capacity(self):
        scenario, directives = sample()
        self.assertEqual(validate_directives(scenario, directives[::-1]), directives)
        for items in [directives[:1], [directives[0], directives[0]],
                      [directive("minimum_battery_reserve", [0], minimum_energy_kwh=1e6), directives[1]]]:
            with self.assertRaises(GridWiseError):
                validate_directives(scenario, items)

    def test_nonstandard_json(self):
        for text in ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}']:
            with self.assertRaises(ValueError):
                load_json(text)


class OptimizationTests(unittest.TestCase):
    def test_all_public_optima(self):
        for i, case in enumerate(CASES):
            with self.subTest(case=case["id"]):
                scenario, directives = sample(i)
                before = scenario.model_dump_json()
                result = optimize(scenario, directives)
                self.assertAlmostEqual(result.total_cost_bdt, case["expected_output"]["total_cost_bdt"], places=6)
                replay(scenario, directives, json.loads(result.model_dump_json()))
                self.assertEqual(before, scenario.model_dump_json())

    def test_analytical_boundaries(self):
        for settings, expected in [
            ({"demand": 0}, 0), ({}, 32), ({"demand": 0.5}, 12),
            ({"solar": 3}, 10), ({"capacity": 0}, 72), ({"rate": 0}, 72),
        ]:
            with self.subTest(settings=settings):
                result = optimize(analytic(**settings), [directive()])
                self.assertAlmostEqual(result.total_cost_bdt, expected, places=6)

    def test_asymmetric_decimal_rates_and_zero_tariff(self):
        data = analytic(demand=0.3, initial=0.1).model_dump()
        data["battery"].update(max_charge_kwh_per_hour=0.2, max_discharge_kwh_per_hour=0.1)
        for h in data["hours"]:
            h["tariff_bdt_per_kwh"] = 0
        scenario = Scenario.model_validate(data)
        result = optimize(scenario, [directive()])
        self.assertEqual(result.total_cost_bdt, 0)
        self.assertAlmostEqual(result.hourly_plan[-1].battery_energy_after_kwh, 0.1)

    def test_end_of_hour_reserve_and_late_charge_restriction(self):
        scenario = analytic(initial=2)
        data = scenario.model_dump()
        data["operator_notes"] = ["Reserve at hour zero.", "No charging late."]
        scenario = Scenario.model_validate(data)
        directives = [directive("minimum_battery_reserve", [0], minimum_energy_kwh=4),
                      directive("no_charge_window", list(range(12, 24)), index=1)]
        result = optimize(scenario, directives)
        self.assertGreaterEqual(result.hourly_plan[0].battery_energy_after_kwh, 4)
        self.assertAlmostEqual(result.hourly_plan[-1].battery_energy_after_kwh, 2)

    def test_overlap_compilation(self):
        scenario = analytic(initial=2)
        data = scenario.model_dump() | {"operator_notes": ["a", "b", "c"]}
        scenario = Scenario.model_validate(data)
        for kind, value_name, values, attr, expected in [
            ("minimum_battery_reserve", "minimum_energy_kwh", [2, 5, 3], "reserve", 5),
            ("max_grid_window", "max_grid_kwh", [4, 2, 3], "grid", 2),
        ]:
            items = [directive(kind, [1, 2], index=i, **{value_name: v}) for i, v in enumerate(values)]
            self.assertEqual(getattr(compile_bounds(scenario, items), attr)[1], expected)
            replay(scenario, items, optimize(scenario, items).model_dump())
        items = [directive("no_charge_window", [1]), directive("no_discharge_window", [1], index=1), directive(index=2)]
        self.assertEqual(optimize(scenario, items).hourly_plan[1].battery_action, "idle")

    def test_solar_overlap_fails_without_invented_semantics(self):
        scenario, _ = sample()
        items = [directive("solar_reduction", [12], index=i, factor=0.5) for i in range(2)]
        with self.assertRaisesRegex(GridWiseError, "ambiguous_solar_overlap"):
            optimize(scenario, items)

    def test_shuffle_and_scenario_id_do_not_change_optimal_cost(self):
        scenario, items = sample()
        data = scenario.model_dump()
        data["hours"].reverse()
        data["scenario_id"] = "new ID"
        result = optimize(Scenario.model_validate(data), items)
        self.assertEqual(result.scenario_id, "new ID")
        self.assertAlmostEqual(result.total_cost_bdt, optimize(scenario, items).total_cost_bdt)

    def test_infeasible_and_expired_budget(self):
        with self.assertRaisesRegex(GridWiseError, "infeasible_schedule"):
            optimize(analytic(capacity=0), [directive("max_grid_window", [0], max_grid_kwh=0)])
        with self.assertRaisesRegex(GridWiseError, "request_deadline"):
            optimize(analytic(), [directive()], time_limit=0)

    def test_replay_detects_corruption_without_compiler(self):
        from unittest.mock import patch
        scenario, items = sample()
        original = optimize(scenario, items).model_dump()
        mutations = [
            lambda d: d["hourly_plan"][0].update(grid_kwh=999),
            lambda d: d["hourly_plan"][0].update(battery_energy_after_kwh=999),
            lambda d: d.update(total_cost_bdt=0),
            lambda d: d.update(peak_grid_kwh=0),
            lambda d: d.update(scenario_id="wrong"),
            lambda d: d["hourly_plan"][0].update(grid_kwh=float("nan")),
            lambda d: d["hourly_plan"].reverse(),
            lambda d: d["directive_interpretation"].reverse(),
            lambda d: d["directive_interpretation"][0]["structured_adjustment"]["hours"].reverse(),
        ]
        with patch("app.directives.compile_bounds", side_effect=AssertionError("replay must be independent")):
            replay(scenario, items, original)
            for mutate in mutations:
                corrupted = copy.deepcopy(original)
                mutate(corrupted)
                with self.assertRaises(GridWiseError):
                    replay(scenario, items, corrupted)


if __name__ == "__main__":
    unittest.main()