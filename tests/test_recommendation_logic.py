import unittest
from pathlib import Path

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

    def test_external_taxonomy_has_eight_axes_and_477_terms(self):
        taxonomy = logic.load_external_taxonomy(Path(
            "research/taxonomies/music-descriptor-taxonomy/music-descriptor-taxonomy.json"
        ))
        self.assertEqual(len(taxonomy["by_id"]), 477)
        self.assertEqual(set(taxonomy["metadata"]["dimensions"]), set(logic.EXTERNAL_AXES))

    def test_axis_inference_is_definition_backed_and_confidence_labeled(self):
        taxonomy = logic.load_external_taxonomy(Path(
            "research/taxonomies/music-descriptor-taxonomy/music-descriptor-taxonomy.json"
        ))
        inferred = logic.infer_external_axes("nocturnal anxious urban music", taxonomy)
        assignments = [item for values in inferred.values() for item in values]
        self.assertTrue(assignments)
        self.assertTrue(all(item["confidence_state"] in {"core", "probable", "possible"}
                            for item in assignments))

    def test_axis_inference_rejects_single_incidental_definition_word(self):
        taxonomy = logic.load_external_taxonomy(Path(
            "research/taxonomies/music-descriptor-taxonomy/music-descriptor-taxonomy.json"
        ))
        inferred = logic.infer_external_axes(
            "records that show a similar sensation of wholeness as To Pimp a Butterfly",
            taxonomy,
        )
        assignments = [item["descriptor_id"] for values in inferred.values() for item in values]
        self.assertNotIn("hazy", assignments)
        self.assertTrue(all(item["evidence"] for item in assignments))

    def test_tuning_questions_separate_interpretation_genre_distance_and_visibility(self):
        questions = logic.tuning_questions("I like the chaotic quality", False, None, None)
        self.assertEqual([item["id"] for item in questions],
                         ["interpretation_focus", "genre_distance", "visibility"])

    def test_genre_distance_has_five_levels_independent_of_visibility(self):
        questions = logic.tuning_questions("I want hypnotic rap with warm melodies", False, None, None)
        self.assertEqual([item["id"] for item in questions],
                         ["interpretation_focus", "genre_distance", "visibility"])
        self.assertEqual(len(questions[1]["options"]), 5)
        self.assertEqual(questions[1]["options"][0]["label"], "Same genre")
        self.assertEqual(questions[1]["options"][3]["label"], "Different genres")
        self.assertIn("popularity", questions[2]["help"])

    def test_pairwise_diversity_reports_every_pair(self):
        items = [
            {"id": "a", "descriptors": ["dark"], "bucket": "A", "region": "UK", "decade": 199},
            {"id": "b", "descriptors": ["warm"], "bucket": "B", "region": "BR", "decade": 197},
            {"id": "c", "descriptors": ["dark"], "bucket": "A", "region": "UK", "decade": 198},
        ]
        report = logic.pairwise_slate_diversity(items)
        self.assertEqual(len(report["pairs"]), 3)
        self.assertGreater(report["average_distance"], 0)

    def test_visual_preserve_and_transform_are_complements(self):
        image = {"brightness": 0.8, "warmth": 0.7}
        candidate = {"brightness": 0.7, "warmth": 0.6}
        preserve = logic.visual_match(image, candidate, "preserve")["score"]
        transform = logic.visual_match(image, candidate, "transform")["score"]
        self.assertAlmostEqual(preserve + transform, 1.0)


if __name__ == "__main__":
    unittest.main()
