"""Interface-only trust and recovery contracts for the listener experience."""

import unittest

from listener_ui import listener_page


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

    def test_prompt_starters_hide_during_request_and_return_on_reset(self):
        self.assertIn("document.querySelector('.prompt-starters').hidden=true", self.page)
        self.assertIn("document.querySelector('.prompt-starters').hidden=false", self.page)

    def test_calibration_controls_explain_distance_and_familiarity(self):
        expected = (
            "Keep every recommendation in the original genre or its closest subgenre.",
            "Include adjacent genres and hybrids with an obvious connection.",
            "Explore related traditions with a clear musical bridge.",
            "Cross into different genres while preserving what matters most.",
            "Ignore genre boundaries if the chosen quality still comes through.",
            "Favor canonical artists and accessible entry points within this musical world.",
            "Mix established artists with lesser-known discoveries.",
            "Focus on lesser-known artists outside the usual recommendation lists.",
            "cannot guarantee that every artist will be new",
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
            "Request understood",
            "Preparing candidate possibilities",
            "Researching promising records",
            "Verifying album identities",
            "Comparing the final path",
            "Writing the listening notes",
        ):
            self.assertIn(state, self.page)
        self.assertIn("Elapsed time:", self.page)
        self.assertIn("AbortController", self.page)
        self.assertIn("role=\"status\" aria-live=\"polite\"", self.page)
        self.assertIn("crateDiggerActiveJob", self.page)
        self.assertNotIn("simulatedProgress", self.page)
        self.assertNotRegex(self.page, r"progress\s*:\s*\d+")

    def test_failure_recovery_preserves_context_and_offers_actions(self):
        self.assertIn("Your request and calibration have been preserved.", self.page)
        self.assertIn("retryRecommendations()", self.page)
        self.assertIn("Revise calibration", self.page)
        self.assertIn("Edit original request", self.page)
        self.assertIn("lastRecommendationBody", self.page)

    def test_prompt_starters_teach_capabilities_without_auto_submitting(self):
        for copy in (
            "Describe a feeling, a musical connection, a constraint, or a rabbit hole",
            "Begin with a feeling",
            "Connect two worlds",
            "Set a difficult constraint",
            "Explore what you can ask",
            "Famous references are welcome.",
            "Show another idea ↻",
        ):
            self.assertIn(copy, self.page)
        self.assertEqual(self.page.count("data-prompt-mode="), 3)
        self.assertIn("crateDiggerExamplePrompt", self.page)
        self.assertIn("crypto.getRandomValues", self.page)
        self.assertIn("function useExamplePrompt(prompt)", self.page)
        self.assertIn("You can edit it before continuing.", self.page)
        self.assertNotIn("useExamplePrompt(prompt);$('form').requestSubmit()", self.page)

    def test_prompt_gallery_covers_distinct_discovery_modes(self):
        for mode in ("feeling", "bridge", "artistic", "constraint", "challenge"):
            self.assertIn(f"mode:'{mode}'", self.page)
        for prompt_fragment in (
            "walking home after a party",
            "haunted spaciousness of 1950s torch songs",
            "dub’s use of negative space and chamber music",
            "compressed imagery and unstable speakers of Sylvia Plath",
            "canonical dream-pop and shoegaze records",
        ):
            self.assertIn(prompt_fragment, self.page)

    def test_existing_recommendation_presentation_remains_present(self):
        for contract in (
            "Why this", "Evidence trail", "Sound & mood", "Genre orientation",
            "Sounds like:", "index+1} of ${results.length}",
        ):
            self.assertIn(contract, self.page)
        self.assertIn("results=data.results||[]", self.page)
        self.assertIn("const r=results[index]", self.page)

    def test_interface_does_not_add_model_calls(self):
        self.assertEqual(self.page.count("api('/recommendation-jobs'"), 1)
        self.assertEqual(self.page.count("api('/recommendations'"), 0)
        self.assertIn("getApi(`/recommendation-jobs/", self.page)
        self.assertEqual(self.page.count("api('/tuning-questions'"), 2)
        self.assertNotIn("/chat/completions", self.page)
        self.assertNotIn("/responses", self.page)

if __name__ == "__main__":
    unittest.main()
