"""Interface-only trust and recovery contracts for the listener experience."""

import subprocess
import unittest
from pathlib import Path

from listener_ui import listener_page


ROOT = Path(__file__).resolve().parents[1]


class ListenerUiTrustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = listener_page()

    def test_results_keep_selected_calibration_across_navigation(self):
        self.assertIn("Your calibration", self.page)
        self.assertIn("calibrationAnswers.find", self.page)
        self.assertIn("calibrationSummaryMarkup()", self.page)
        self.assertIn("function move(delta)", self.page)
        self.assertIn("render();", self.page)

    def test_revise_calibration_preserves_original_request_and_answers(self):
        self.assertIn("function reviseCalibration()", self.page)
        self.assertIn("renderCalibration(currentQuestions)", self.page)
        self.assertIn("$('brief').value=lastBrief", self.page)
        self.assertIn("calibrationSelection[id]", self.page)

    def test_calibration_controls_explain_distance_and_familiarity(self):
        expected = (
            "Stay within the original genre or immediate neighboring styles.",
            "Allow nearby subgenres and hybrids.",
            "Cross into closely related traditions.",
            "Change genres while preserving the selected defining quality.",
            "Any genre may qualify if the defining quality survives.",
            "Favor established artists and easier entry points.",
            "Combine recognizable anchors with underheard artists.",
            "Prioritize artists outside the usual recommendation loop.",
            "does not guarantee that every artist will be unknown",
        )
        for copy in expected:
            self.assertIn(copy, self.page)

    def test_verification_copy_separates_identity_from_interpretation(self):
        self.assertIn("Album identity verified", self.page)
        self.assertIn("MusicBrainz confirmed the album and artist identity.", self.page)
        self.assertIn("The musical connection is Crate Digger’s interpretation.", self.page)

    def test_loading_uses_observable_request_states_without_fake_percentage(self):
        for state in (
            "Understanding the request",
            "Preparing calibration",
            "Researching possible records",
        ):
            self.assertIn(state, self.page)
        self.assertIn("Elapsed time:", self.page)
        self.assertIn("AbortController", self.page)
        self.assertNotIn("simulatedProgress", self.page)
        self.assertNotRegex(self.page, r"progress\s*:\s*\d+")

    def test_failure_recovery_preserves_context_and_offers_actions(self):
        self.assertIn("Your request and calibration have been preserved.", self.page)
        self.assertIn("retryRecommendations()", self.page)
        self.assertIn("Revise calibration", self.page)
        self.assertIn("Edit original request", self.page)
        self.assertIn("lastRecommendationBody", self.page)

    def test_existing_recommendation_presentation_remains_present(self):
        for contract in (
            "Why this", "Evidence trail", "Sound & mood", "Genre orientation",
            "Sounds like:", "index+1} of ${results.length}",
        ):
            self.assertIn(contract, self.page)
        self.assertIn("results=data.results||[]", self.page)
        self.assertIn("const r=results[index]", self.page)

    def test_interface_does_not_add_model_calls(self):
        self.assertEqual(self.page.count("api('/recommendations'"), 1)
        self.assertEqual(self.page.count("api('/tuning-questions'"), 2)
        self.assertNotIn("/chat/completions", self.page)
        self.assertNotIn("/responses", self.page)

    def test_only_interface_and_interface_test_files_are_modified(self):
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        changed = [line[3:].replace("\\", "/") for line in status]
        self.assertEqual(
            set(changed),
            {"listener_ui.py", "tests/test_listener_ui_trust.py"},
        )


if __name__ == "__main__":
    unittest.main()
