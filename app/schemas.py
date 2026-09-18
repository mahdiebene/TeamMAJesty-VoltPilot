"""Strict JSON-domain models. Unknown request metadata cannot affect constraints."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.errors import GridWiseError

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Energy = Annotated[Number, Field(ge=0)]
HourIndex = Annotated[int, Field(strict=True, ge=0, le=23)]
Text = Annotated[str, Field(strict=True, min_length=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class RequestModel(StrictModel):
    model_config = ConfigDict(strict=True, extra="ignore", allow_inf_nan=False)


class Battery(RequestModel):
    capacity_kwh: Energy
    initial_energy_kwh: Energy
    minimum_energy_kwh: Energy
    max_charge_kwh_per_hour: Energy
    max_discharge_kwh_per_hour: Energy

    @model_validator(mode="after")
    def physical_bounds(self) -> Self:
        if not self.minimum_energy_kwh <= self.initial_energy_kwh <= self.capacity_kwh:
            raise ValueError("Invalid battery bounds")
        return self


class Hour(RequestModel):
    hour: HourIndex
    demand_kwh: Energy
    solar_kwh: Energy
    tariff_bdt_per_kwh: Number


class Scenario(RequestModel):
    scenario_id: str
    operator_notes: Annotated[list[Text], Field(min_length=1, max_length=3)]
    hours: Annotated[list[Hour], Field(min_length=24, max_length=24)]
    battery: Battery

    @field_validator("operator_notes")
    @classmethod
    def nonblank_notes(cls, notes: list[str]) -> list[str]:
        if any(not note.strip() for note in notes):
            raise ValueError("Blank operator note")
        return notes

    @field_validator("hours")
    @classmethod
    def chronological_hours(cls, hours: list[Hour]) -> list[Hour]:
        if {item.hour for item in hours} != set(range(24)):
            raise ValueError("Hours must cover 0 through 23 exactly once")
        return sorted(hours, key=lambda item: item.hour)


class Window(StrictModel):
    hours: Annotated[list[HourIndex], Field(min_length=1, max_length=24)]

    @field_validator("hours")
    @classmethod
    def unique_sorted_hours(cls, hours: list[int]) -> list[int]:
        if len(set(hours)) != len(hours):
            raise ValueError("Duplicate directive hours")
        return sorted(hours)


class SolarAdjustment(Window):
    factor: Annotated[Number, Field(ge=0, le=1)]


class ReserveAdjustment(Window):
    minimum_energy_kwh: Energy


class GridAdjustment(Window):
    max_grid_kwh: Energy


DirectiveType = Literal[
    "solar_reduction", "minimum_battery_reserve", "no_charge_window",
    "no_discharge_window", "max_grid_window", "no_op",
]


class Directive(StrictModel):
    note_index: Annotated[int, Field(strict=True, ge=0)]
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: SolarAdjustment | ReserveAdjustment | GridAdjustment | Window | None
    explanation: Text

    @model_validator(mode="after")
    def exact_shape(self) -> Self:
        shapes = {
            "solar_reduction": SolarAdjustment,
            "minimum_battery_reserve": ReserveAdjustment,
            "max_grid_window": GridAdjustment,
            "no_charge_window": Window,
            "no_discharge_window": Window,
            "no_op": type(None),
        }
        if type(self.structured_adjustment) is not shapes[self.directive_type]:
            raise ValueError("Wrong adjustment shape")
        if self.applies != (self.directive_type != "no_op"):
            raise ValueError("Inconsistent applies flag")
        if not self.explanation.strip():
            raise ValueError("Blank explanation")
        return self


class Interpretation(StrictModel):
    directive_interpretation: Annotated[list[Directive], Field(min_length=1, max_length=3)]


def validate_directives(scenario: Scenario, directives: list[Directive]) -> list[Directive]:
    """Normalize only complete unique mappings; never repair numeric meanings."""
    if (len(directives) != len(scenario.operator_notes)
            or {d.note_index for d in directives} != set(range(len(scenario.operator_notes)))):
        raise GridWiseError("invalid_directive_mapping")
    for directive in directives:
        adjustment = directive.structured_adjustment
        if (isinstance(adjustment, ReserveAdjustment)
                and adjustment.minimum_energy_kwh > scenario.battery.capacity_kwh):
            raise GridWiseError("reserve_exceeds_capacity")
    return sorted(directives, key=lambda item: item.note_index)


class PlanHour(StrictModel):
    hour: HourIndex
    grid_kwh: Energy
    solar_used_kwh: Energy
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: Energy
    battery_energy_after_kwh: Energy

    @model_validator(mode="after")
    def action_consistency(self) -> Self:
        if self.battery_action == "idle" and self.battery_kwh != 0:
            raise ValueError("Idle magnitude must be zero")
        if self.battery_action != "idle" and self.battery_kwh <= 0:
            raise ValueError("Active action requires positive magnitude")
        return self


class Schedule(StrictModel):
    scenario_id: str
    directive_interpretation: Annotated[list[Directive], Field(min_length=1, max_length=3)]
    hourly_plan: Annotated[list[PlanHour], Field(min_length=24, max_length=24)]
    total_grid_kwh: Energy
    total_cost_bdt: Number
    peak_grid_kwh: Energy
    plan_summary: Text

    @field_validator("hourly_plan")
    @classmethod
    def ordered_plan(cls, hours: list[PlanHour]) -> list[PlanHour]:
        if [item.hour for item in hours] != list(range(24)):
            raise ValueError("Plan must contain hours 0 through 23 in order")
        return hours