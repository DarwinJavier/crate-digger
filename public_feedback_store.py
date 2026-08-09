"""Durable, privacy-minimal storage for public listener feedback."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


LOCK = threading.Lock()
DISCOVERY_VALUES = {"not_at_all", "a_little", "somewhat", "significantly"}
LISTEN_VALUES = {"no", "maybe", "yes_one", "yes_multiple"}
EXPORT_FIELDS = [
    "feedback_id", "journey_id", "prompt", "calibration_json", "results_json",
    "request_fit", "discovery_expansion", "listen_intent", "flow_rating",
    "message", "app_version", "scoring_policy", "source", "created_at",
]


def _clean_text(value: object, field: str, maximum: int, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} is required.")
    if len(text) > maximum:
        raise ValueError(f"{field} must be {maximum} characters or fewer.")
    return text


def _rating(value: object, field: str) -> int:
    try:
        rating = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be rated from 1 to 5.") from exc
    if rating not in range(1, 6):
        raise ValueError(f"{field} must be rated from 1 to 5.")
    return rating


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS public_feedback (
            feedback_id TEXT PRIMARY KEY,
            journey_id TEXT NOT NULL UNIQUE,
            prompt TEXT NOT NULL,
            calibration_json TEXT NOT NULL,
            results_json TEXT NOT NULL,
            request_fit INTEGER NOT NULL CHECK(request_fit BETWEEN 1 AND 5),
            discovery_expansion TEXT NOT NULL,
            listen_intent TEXT NOT NULL,
            flow_rating INTEGER NOT NULL CHECK(flow_rating BETWEEN 1 AND 5),
            message TEXT NOT NULL,
            app_version TEXT NOT NULL,
            scoring_policy TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)


def save_public_feedback(database_path: Path, payload: dict) -> dict[str, str]:
    """Validate and store one anonymous submission for one completed journey."""
    if str(payload.get("website") or "").strip():
        raise ValueError("Feedback could not be submitted.")
    journey_id = _clean_text(payload.get("journey_id"), "journey_id", 80)
    prompt = _clean_text(payload.get("prompt"), "prompt", 2000)
    calibration = payload.get("calibration")
    results = payload.get("results")
    if not isinstance(calibration, list) or len(calibration) > 12:
        raise ValueError("calibration must contain no more than 12 selections.")
    if not isinstance(results, list) or not results or len(results) > 25:
        raise ValueError("results must contain between 1 and 25 albums.")
    calibration_json = json.dumps(calibration, ensure_ascii=False, separators=(",", ":"))
    results_json = json.dumps(results, ensure_ascii=False, separators=(",", ":"))
    if len(calibration_json) > 12000 or len(results_json) > 20000:
        raise ValueError("The journey snapshot is too large.")
    discovery = _clean_text(payload.get("discovery_expansion"), "discovery_expansion", 32)
    if discovery not in DISCOVERY_VALUES:
        raise ValueError("discovery_expansion has an unsupported value.")
    listen_intent = _clean_text(payload.get("listen_intent"), "listen_intent", 32)
    if listen_intent not in LISTEN_VALUES:
        raise ValueError("listen_intent has an unsupported value.")
    row = {
        "feedback_id": uuid.uuid4().hex,
        "journey_id": journey_id,
        "prompt": prompt,
        "calibration_json": calibration_json,
        "results_json": results_json,
        "request_fit": _rating(payload.get("request_fit"), "request_fit"),
        "discovery_expansion": discovery,
        "listen_intent": listen_intent,
        "flow_rating": _rating(payload.get("flow_rating"), "flow_rating"),
        "message": _clean_text(payload.get("message"), "message", 1000, required=False),
        "app_version": _clean_text(payload.get("app_version") or "unknown", "app_version", 40),
        "scoring_policy": _clean_text(
            payload.get("scoring_policy") or "unknown", "scoring_policy", 80
        ),
        "source": "listener_submitted",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with LOCK:
        connection = sqlite3.connect(database_path)
        try:
            _initialize(connection)
            connection.execute(
                f"INSERT INTO public_feedback ({', '.join(EXPORT_FIELDS)}) "
                f"VALUES ({', '.join('?' for _ in EXPORT_FIELDS)})",
                [row[field] for field in EXPORT_FIELDS],
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("Feedback has already been submitted for this journey.") from exc
        finally:
            connection.close()
    return {"feedback_id": row["feedback_id"], "created_at": row["created_at"]}


def export_public_feedback_csv(database_path: Path) -> str:
    """Return all submissions as a stable CSV export for the project owner."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=EXPORT_FIELDS)
    writer.writeheader()
    if not database_path.exists():
        return output.getvalue()
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        _initialize(connection)
        rows = connection.execute(
            "SELECT * FROM public_feedback ORDER BY created_at, feedback_id"
        ).fetchall()
        writer.writerows(dict(row) for row in rows)
    finally:
        connection.close()
    return output.getvalue()
