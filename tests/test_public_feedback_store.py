"""Durability and validation contracts for anonymous public feedback."""

import csv
import io
import tempfile
import unittest
from pathlib import Path

from public_feedback_store import export_public_feedback_csv, save_public_feedback


class PublicFeedbackStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "public_feedback.db"
        self.payload = {
            "journey_id": "journey-123",
            "prompt": "Nocturnal music with tension but no obvious gloom.",
            "calibration": [
                {"question_id": "genre_distance", "selected_label": "Different genres"},
                {"question_id": "visibility", "selected_label": "Underground"},
            ],
            "results": [
                {"artist": "Artist", "album": "Album", "year": 2001, "rg_mbid": "mbid-1"}
            ],
            "request_fit": 4,
            "discovery_expansion": "significantly",
            "listen_intent": "yes_multiple",
            "flow_rating": 5,
            "message": "Keep the calibration, but explain the visibility control sooner.",
            "app_version": "0.1",
            "scoring_policy": "test-policy",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_and_export_preserve_the_reviewable_journey_snapshot(self):
        receipt = save_public_feedback(self.database_path, self.payload)
        self.assertTrue(receipt["feedback_id"])
        rows = list(csv.DictReader(io.StringIO(export_public_feedback_csv(self.database_path))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["journey_id"], "journey-123")
        self.assertEqual(rows[0]["request_fit"], "4")
        self.assertIn("Different genres", rows[0]["calibration_json"])
        self.assertIn("mbid-1", rows[0]["results_json"])
        self.assertEqual(rows[0]["source"], "listener_submitted")

    def test_one_journey_can_submit_feedback_only_once(self):
        save_public_feedback(self.database_path, self.payload)
        with self.assertRaisesRegex(ValueError, "already been submitted"):
            save_public_feedback(self.database_path, self.payload)

    def test_invalid_ratings_enums_and_oversized_messages_are_rejected(self):
        invalid_cases = (
            {"request_fit": 0},
            {"flow_rating": 6},
            {"discovery_expansion": "amazed"},
            {"listen_intent": "absolutely"},
            {"message": "x" * 1001},
        )
        for index, change in enumerate(invalid_cases):
            with self.subTest(change=change):
                payload = {**self.payload, **change, "journey_id": f"invalid-{index}"}
                with self.assertRaises(ValueError):
                    save_public_feedback(self.database_path, payload)

    def test_empty_export_has_headers_without_creating_a_database(self):
        export = export_public_feedback_csv(self.database_path)
        self.assertIn("feedback_id,journey_id,prompt", export)
        self.assertFalse(self.database_path.exists())


if __name__ == "__main__":
    unittest.main()
