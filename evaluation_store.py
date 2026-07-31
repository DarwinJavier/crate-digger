"""Local CSV-backed storage for frozen briefs and blinded evaluation feedback."""

from __future__ import annotations

import csv
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EVALUATION_DIR = ROOT / "evaluation"
BRIEFS_PATH = EVALUATION_DIR / "briefs.csv"
FEEDBACK_PATH = EVALUATION_DIR / "feedback.csv"
FROZEN_PATH = EVALUATION_DIR / "frozen_cases.json"
LOCK = threading.Lock()

BRIEF_FIELDS = [
    "id", "brief", "seed_artist", "seed_album", "liked_quality", "discovery_depth",
    "visibility", "exclusions", "visual_role", "submitted_by", "created_at",
]
FEEDBACK_FIELDS = [
    "case_id", "evaluator_id", "system_arm", "artist", "album", "year", "position",
    "requested_quality", "discovery_value", "connection_clarity", "save_revisit",
    "explanation_trust", "justification", "created_at",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _case_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:42]
    return slug or "brief"


def frozen_cases() -> list[dict]:
    if not FROZEN_PATH.exists():
        return []
    return json.loads(FROZEN_PATH.read_text(encoding="utf-8")).get("cases", [])


def is_frozen() -> bool:
    return bool(frozen_cases())


def list_briefs() -> list[dict[str, str]]:
    frozen = frozen_cases()
    return frozen if frozen else _read_csv(BRIEFS_PATH)


def save_brief(payload: dict) -> dict:
    if is_frozen():
        raise ValueError("The holdout is frozen. Briefs can no longer be edited.")
    brief = str(payload.get("brief") or "").strip()
    submitted_by = str(payload.get("submitted_by") or "").strip()
    if not brief or not submitted_by:
        raise ValueError("Brief and contributor name are required.")
    with LOCK:
        rows = _read_csv(BRIEFS_PATH)
        supplied_id = str(payload.get("id") or "").strip()
        base = supplied_id or _case_id(f"{submitted_by}-{brief}")
        case_id = base
        existing_ids = {row["id"] for row in rows}
        counter = 2
        while case_id in existing_ids and not supplied_id:
            case_id = f"{base}-{counter}"
            counter += 1
        row = {field: str(payload.get(field) or "").strip() for field in BRIEF_FIELDS}
        row["id"] = case_id
        row["created_at"] = next((item["created_at"] for item in rows if item["id"] == case_id), _now())
        rows = [item for item in rows if item["id"] != case_id] + [row]
        rows.sort(key=lambda item: (item["created_at"], item["id"]))
        _write_csv(BRIEFS_PATH, rows, BRIEF_FIELDS)
        return row


def freeze_briefs() -> dict:
    with LOCK:
        if is_frozen():
            raise ValueError("The holdout has already been frozen.")
        rows = _read_csv(BRIEFS_PATH)
        if len(rows) != 25:
            raise ValueError(f"Exactly 25 briefs are required before freezing; found {len(rows)}.")
        payload = {
            "schema_version": "1.1",
            "frozen_on": _now(),
            "status": "frozen",
            "note": "Holdout prompts. Do not tune against outcomes.",
            "cases": rows,
        }
        FROZEN_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload


def save_feedback(payload: dict) -> dict:
    required = ("case_id", "evaluator_id", "artist", "album", "justification")
    if any(not str(payload.get(field) or "").strip() for field in required):
        raise ValueError("Case, evaluator, recommendation, and written justification are required.")
    for field in ("requested_quality", "discovery_value", "connection_clarity",
                  "save_revisit", "explanation_trust"):
        value = int(payload.get(field) or 0)
        if value not in range(1, 6):
            raise ValueError(f"{field} must be rated from 1 to 5.")
    row = {field: str(payload.get(field) or "").strip() for field in FEEDBACK_FIELDS}
    row["created_at"] = _now()
    with LOCK:
        rows = _read_csv(FEEDBACK_PATH)
        identity = (row["case_id"], row["evaluator_id"], row["system_arm"], row["artist"], row["album"])
        rows = [item for item in rows if
                (item["case_id"], item["evaluator_id"], item["system_arm"], item["artist"], item["album"]) != identity]
        rows.append(row)
        _write_csv(FEEDBACK_PATH, rows, FEEDBACK_FIELDS)
    return row


def evaluation_state(evaluator_id: str = "") -> dict:
    briefs = list_briefs()
    feedback = _read_csv(FEEDBACK_PATH)
    evaluator_rows = [row for row in feedback if not evaluator_id or row["evaluator_id"] == evaluator_id]
    counts: dict[str, int] = {}
    for row in evaluator_rows:
        counts[row["case_id"]] = counts.get(row["case_id"], 0) + 1
    completed = sorted(case_id for case_id, count in counts.items() if count >= 3)
    return {
        "frozen": is_frozen(),
        "briefs": briefs,
        "brief_count": len(briefs),
        "target_count": 25,
        "feedback_count": len(evaluator_rows),
        "completed_case_ids": completed,
    }
