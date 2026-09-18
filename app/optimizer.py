"""Lossless battery LP: 96 variables, 49 equalities, no integer decisions."""

import json
import math

import numpy as np
from scipy.optimize import linprog

from app.directives import compile_bounds
from app.errors import GridWiseError
from app.replay import replay
from app.schemas import Directive, PlanHour, Scenario, Schedule, validate_directives


def optimize(scenario: Scenario, directives: list[Directive], time_limit: float = 3.0) -> Schedule:
    if not math.isfinite(time_limit) or time_limit <= 0:
        raise GridWiseError("request_deadline")
    directives = validate_directives(scenario, directives)
    compiled = compile_bounds(scenario, directives)
    battery = scenario.battery
    objective = np.zeros(96)
    objective[:24] = [hour.tariff_bdt_per_kwh for hour in scenario.hours]
    matrix = np.zeros((49, 96))
    rhs = np.zeros(49)
    for hour in range(24):
        matrix[hour, hour] = 1
        matrix[hour, 24 + hour] = 1
        matrix[hour, 48 + hour] = -1
        rhs[hour] = scenario.hours[hour].demand_kwh
        matrix[24 + hour, 72 + hour] = 1
        matrix[24 + hour, 48 + hour] = -1
        if hour:
            matrix[24 + hour, 71 + hour] = -1
    rhs[24] = battery.initial_energy_kwh
    matrix[48, 95] = 1
    rhs[48] = battery.initial_energy_kwh
    bounds = ([(0, cap) for cap in compiled.grid]
              + [(0, solar) for solar in compiled.solar]
              + [(-discharge, charge) for discharge, charge in zip(compiled.discharge, compiled.charge)]
              + [(reserve, battery.capacity_kwh) for reserve in compiled.reserve])
    solution = linprog(objective, A_eq=matrix, b_eq=rhs, bounds=bounds, method="highs",
                       options={"time_limit": time_limit, "primal_feasibility_tolerance": 1e-8,
                                "dual_feasibility_tolerance": 1e-8})
    if solution.status == 2:
        raise GridWiseError("infeasible_schedule")
    if not solution.success or solution.x is None:
        raise GridWiseError("solver_not_optimal")

    def clean(value: float) -> float:
        return 0.0 if abs(value) < 1e-9 else float(value)

    energy = battery.initial_energy_kwh
    hours = []
    for hour in range(24):
        flow = clean(solution.x[48 + hour])
        energy += flow
        hours.append(PlanHour(
            hour=hour, grid_kwh=clean(solution.x[hour]), solar_used_kwh=clean(solution.x[24 + hour]),
            battery_action="charge" if flow > 0 else "discharge" if flow < 0 else "idle",
            battery_kwh=abs(flow), battery_energy_after_kwh=clean(energy),
        ))
    result = Schedule(
        scenario_id=scenario.scenario_id, directive_interpretation=directives, hourly_plan=hours,
        total_grid_kwh=math.fsum(h.grid_kwh for h in hours),
        total_cost_bdt=math.fsum(h.grid_kwh * source.tariff_bdt_per_kwh for h, source in zip(hours, scenario.hours)),
        peak_grid_kwh=max(h.grid_kwh for h in hours),
        plan_summary=(f"Minimum-cost 24-hour schedule with {sum(d.applies for d in directives)} applicable "
                      "directives; battery returns to its initial energy. Unused solar is curtailed."),
    )
    # Validate precisely the JSON representation returned to clients, not solver arrays.
    replay(scenario, directives, json.loads(result.model_dump_json()))
    return result