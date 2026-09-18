"""Create the dashboard's public input-only fixture; never ship reference answers."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    cases = json.loads((ROOT / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json").read_text(encoding="utf-8-sig"))["cases"]
    inputs = [{key: case[key] for key in ("id", "label", "input")} for case in cases]
    target = ROOT / "frontend" / "assets" / "samples.json"
    target.write_text(json.dumps(inputs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(inputs)} public inputs; no reference answers.")


if __name__ == "__main__":
    main()