"""Compile validated directives into LP bounds, without mutating the request."""

from dataclasses import dataclass

from app.errors import GridWiseError
from app.schemas import Directive, Scenario, validate_directives


@dataclass(frozen=True)
class Bounds:
    solar: list[float]
    reserve: list[float]
    charge: list[float]
    discharge: list[float]
    grid: list[float | None]


def compile_bounds(scenario: Scenario, directives: list[Directive]) -> Bounds:
    directives = validate_directives(scenario, directives)
    battery = scenario.battery
    bounds = Bounds(
        solar=[h.solar_kwh for h in scenario.hours],
        reserve=[battery.minimum_energy_kwh] * 24,
        charge=[battery.max_charge_kwh_per_hour] * 24,
        discharge=[battery.max_discharge_kwh_per_hour] * 24,
        grid=[None] * 24,
    )
    solar_hours: set[int] = set()
    for directive in directives:
        adjustment = directive.structured_adjustment
        if adjustment is None:
            continue
        for hour in adjustment.hours:
            match directive.directive_type:
                case "solar_reduction":
                    if hour in solar_hours:
                        raise GridWiseError("ambiguous_solar_overlap")
                    solar_hours.add(hour)
                    bounds.solar[hour] *= adjustment.factor
                case "minimum_battery_reserve":
                    bounds.reserve[hour] = max(bounds.reserve[hour], adjustment.minimum_energy_kwh)
                case "no_charge_window":
                    bounds.charge[hour] = 0.0
                case "no_discharge_window":
                    bounds.discharge[hour] = 0.0
                case "max_grid_window":
                    old = bounds.grid[hour]
                    bounds.grid[hour] = adjustment.max_grid_kwh if old is None else min(old, adjustment.max_grid_kwh)
    return bounds