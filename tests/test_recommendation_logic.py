import unittest

import recommendation_logic as logic


class RecommendationLogicTests(unittest.TestCase):
    def test_fallback_reports_unmapped_language(self):
        intent = {"moods": ["nocturnal"], "sonic_traits": [], "scenes": []}
        intent["unmapped_terms"] = logic.find_unmapped_terms("nocturnal glossy clubbing", intent)
        self.assertEqual(intent["unmapped_terms"], ["clubbing", "glossy"])
        self.assertEqual(logic.intent_coverage(intent)["status"], "partial")

    def test_confidence_weights_positive_evidence(self):
        component = logic.score_component("descriptor_match", 0.85, "nocturnal")
        self.assertEqual(component["contribution"], 1.7)

    def test_diversity_changes_only_tied_scores(self):
        def candidate(score, title, bucket, region, year):
            album = {"title": title, "bucket": bucket, "region": region, "year": year}
            return (score, album, [], [], [])

        scored = [
            candidate(5.0, "A", "A", "UK", 1980),
            candidate(4.0, "B", "A", "UK", 1981),
            candidate(4.0, "C", "B", "JP", 1991),
        ]
        selected = logic.select_diverse(scored, 3)
        self.assertEqual([item[1]["title"] for item in selected], ["A", "C", "B"])


if __name__ == "__main__":
    unittest.main()
