import json
from pathlib import Path

from app.schemas import Directive, Scenario

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json").read_text(encoding="utf-8-sig"))["cases"]


def sample(index=0):
    case = CASES[index]
    return (Scenario.model_validate(case["input"]),
            [Directive.model_validate(d) for d in case["expected_output"]["directive_interpretation"]])


def directive(kind="no_op", hours=None, index=0, **values):
    return Directive.model_validate({
        "note_index": index, "applies": kind != "no_op", "directive_type": kind,
        "structured_adjustment": None if kind == "no_op" else {"hours": hours, **values},
        "explanation": "Independently labeled test directive.",
    })


def analytic(demand=1.0, capacity=10.0, rate=2.0, solar=0.0, initial=0.0):
    return Scenario.model_validate({
        "scenario_id": "analytical-not-a-production-key", "operator_notes": ["Unrelated administrative note."],
        "battery": {"capacity_kwh": capacity, "initial_energy_kwh": initial, "minimum_energy_kwh": 0,
                    "max_charge_kwh_per_hour": rate, "max_discharge_kwh_per_hour": rate},
        "hours": [{"hour": h, "demand_kwh": demand, "solar_kwh": solar if h < 12 else 0,
                   "tariff_bdt_per_kwh": 1 if h < 12 else 5} for h in range(24)],
    })