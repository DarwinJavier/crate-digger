import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import evaluation_store as store


class EvaluationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = patch.multiple(
            store,
            BRIEFS_PATH=root / "briefs.csv",
            FEEDBACK_PATH=root / "feedback.csv",
            FROZEN_PATH=root / "frozen.json",
        )
        self.paths.start()

    def tearDown(self):
        self.paths.stop()
        self.temp.cleanup()

    def test_requires_exactly_25_before_freeze(self):
        store.save_brief({"brief": "New prompt", "submitted_by": "r1"})
        with self.assertRaisesRegex(ValueError, "Exactly 25"):
            store.freeze_briefs()

    def test_freeze_makes_briefs_immutable(self):
        for index in range(25):
            store.save_brief({"brief": f"Unseen prompt {index}", "submitted_by": "r1"})
        payload = store.freeze_briefs()
        self.assertEqual(len(payload["cases"]), 25)
        with self.assertRaisesRegex(ValueError, "frozen"):
            store.save_brief({"brief": "Late prompt", "submitted_by": "r1"})

    def test_feedback_requires_scales_and_written_reason(self):
        base = {
            "case_id": "case-1", "evaluator_id": "r1", "system_arm": "platform",
            "artist": "Artist", "album": "Album", "requested_quality": 4,
            "discovery_value": 5, "connection_clarity": 4, "save_revisit": 4,
            "explanation_trust": 3,
        }
        with self.assertRaisesRegex(ValueError, "justification"):
            store.save_feedback(base)
        base["justification"] = "The requested quality is clearly audible."
        saved = store.save_feedback(base)
        self.assertEqual(saved["requested_quality"], "4")


if __name__ == "__main__":
    unittest.main()
