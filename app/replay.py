"""Independent verification: deliberately does not import the LP/compiler."""

import math

from pydantic import ValidationError

from app.errors import GridWiseError
from app.schemas import Directive, Scenario, Schedule, validate_directives


def replay(scenario: Scenario, directives: list[Directive], payload: dict,
           tolerance: float = 1e-6) -> Schedule:
    """Inspect serialized values against original inputs and independent directives.

    Tests pass organizer/hand-labeled directives here, not the response's claims.
    Runtime can only verify the model-derived meaning, not unknown ground truth.
    """
    try:
        result = Schedule.model_validate(payload)
    except ValidationError as exc:
        raise GridWiseError("invalid_schedule_shape") from exc
    # Input/model normalization must not mask an invalid serialized output order.
    for raw in payload["directive_interpretation"]:
        change = raw["structured_adjustment"]
        if change is not None and change["hours"] != sorted(change["hours"]):
            raise GridWiseError("invalid_schedule_directive_hours")
    expected = validate_directives(scenario, directives)
    actual = validate_directives(scenario, result.directive_interpretation)
    if [d.note_index for d in result.directive_interpretation] != list(range(len(expected))):
        raise GridWiseError("invalid_schedule_directive_order")
    for first, second in zip(expected, actual):
        if first.model_dump(exclude={"explanation"}) != second.model_dump(exclude={"explanation"}):
            raise GridWiseError("interpretation_mismatch")
    if result.scenario_id != scenario.scenario_id:
        raise GridWiseError("scenario_mismatch")
    battery = scenario.battery
    energy = battery.initial_energy_kwh
    costs = []
    for original, step in zip(scenario.hours, result.hourly_plan):
        solar = original.solar_kwh
        reserve = battery.minimum_energy_kwh
        charge_limit = battery.max_charge_kwh_per_hour
        discharge_limit = battery.max_discharge_kwh_per_hour
        grid_limit = math.inf
        reductions = []
        for directive in expected:
            change = directive.structured_adjustment
            if change is None or original.hour not in change.hours:
                continue
            if directive.directive_type == "solar_reduction":
                reductions.append(change.factor)
            elif directive.directive_type == "minimum_battery_reserve":
                reserve = max(reserve, change.minimum_energy_kwh)
            elif directive.directive_type == "no_charge_window":
                charge_limit = 0.0
            elif directive.directive_type == "no_discharge_window":
                discharge_limit = 0.0
            elif directive.directive_type == "max_grid_window":
                grid_limit = min(grid_limit, change.max_grid_kwh)
        if len(reductions) > 1:
            raise GridWiseError("ambiguous_solar_overlap")
        if reductions:
            solar = original.solar_kwh * reductions[0]
        charge = step.battery_kwh if step.battery_action == "charge" else 0.0
        discharge = step.battery_kwh if step.battery_action == "discharge" else 0.0
        energy += charge - discharge
        if not math.isfinite(energy):
            raise GridWiseError("nonfinite_battery_state")
        residuals = [
            step.solar_used_kwh - solar, step.grid_kwh - grid_limit,
            charge - charge_limit, discharge - discharge_limit,
            reserve - energy, energy - battery.capacity_kwh,
            abs(energy - step.battery_energy_after_kwh),
            abs(step.grid_kwh + step.solar_used_kwh + discharge - original.demand_kwh - charge),
        ]
        if any(math.isnan(value) or value > tolerance for value in residuals):
            raise GridWiseError("schedule_constraint_violation")
        costs.append(step.grid_kwh * original.tariff_bdt_per_kwh)
    if abs(energy - battery.initial_energy_kwh) > tolerance:
        raise GridWiseError("battery_not_neutral")
    try:
        total_grid = math.fsum(h.grid_kwh for h in result.hourly_plan)
        total_cost = math.fsum(costs)
    except (OverflowError, ValueError) as exc:
        raise GridWiseError("nonfinite_totals") from exc
    if (not math.isfinite(total_grid) or not math.isfinite(total_cost)
            or abs(total_grid - result.total_grid_kwh) > tolerance
            or abs(total_cost - result.total_cost_bdt) > tolerance
            or abs(max(h.grid_kwh for h in result.hourly_plan) - result.peak_grid_kwh) > tolerance):
        raise GridWiseError("inconsistent_totals")
    return result