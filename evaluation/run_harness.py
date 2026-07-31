"""Dependency-light frozen recommendation evaluation harness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recommendation_logic import annotation_completeness, confidence_state


def main() -> int:
    payload = json.loads((Path(__file__).parent / "frozen_cases.json").read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    checks = {
        "schema_version": payload.get("schema_version") in {"1.0", "1.1"},
        "frozen": payload.get("status") == "frozen",
        "unique_ids": len({case.get("id") for case in cases}) == len(cases),
        "confidence_boundaries": [confidence_state(value) for value in (0.9, 0.7, 0.4)]
        == ["core", "probable", "possible"],
        "completeness_bounded": 0 <= annotation_completeness({"mood": ["x"]})["score"] <= 1,
    }
    print(json.dumps({"cases": len(cases), "checks": checks}, indent=2, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
