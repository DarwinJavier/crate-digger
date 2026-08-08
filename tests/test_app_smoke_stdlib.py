"""Dependency-free API logic smoke tests for constrained environments."""

import os
import sys
import time
import types
import unittest
from pathlib import Path


class BaseModel:
    def __init__(self, **values):
        for name in getattr(type(self), "__annotations__", {}):
            if name in values:
                value = values[name]
            else:
                default = getattr(type(self), name, None)
                value = default() if callable(default) and getattr(default, "_field_factory", False) else default
            setattr(self, name, value)


def Field(default=None, default_factory=None, **_kwargs):
    if default_factory is not None:
        def factory():
            return default_factory()
        factory._field_factory = True
        return factory
    return default


class FastAPI:
    def __init__(self, **_kwargs):
        pass

    def post(self, _path, **_kwargs):
        return lambda function: function

    def get(self, _path, **_kwargs):
        return lambda function: function


fastapi = types.ModuleType("fastapi")
fastapi.FastAPI = FastAPI
responses = types.ModuleType("fastapi.responses")
responses.HTMLResponse = object
pydantic = types.ModuleType("pydantic")
pydantic.BaseModel = BaseModel
pydantic.Field = Field
requests = types.ModuleType("requests")
requests.get = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network call in smoke test"))
os.environ["CRATE_DIGGER_SKIP_DOTENV"] = "1"
sys.modules.setdefault("fastapi", fastapi)
sys.modules.setdefault("fastapi.responses", responses)
sys.modules.setdefault("pydantic", pydantic)
sys.modules.setdefault("requests", requests)

import app


class AppSmokeTests(unittest.TestCase):
    def request(self, **overrides):
        values = {
            "brief": "nocturnal elegant reverb-drenched",
            "seeds": [app.Seed(artist="The Cure")],
            "hard_constraints": app.HardConstraints(),
            "novelty": "non_obvious",
            "n_results": 5,
            "use_lastfm": False,
            "discovery_depth": 4,
            "visibility": "underheard",
            "features": app.FeatureToggles(),
        }
        values.update(overrides)
        return app.RecRequest(**values)

    def test_health_and_standard_recommendation(self):
        self.assertTrue(app.health()["ok"])
        response = app.recommend(self.request())
        self.assertGreaterEqual(len(response["results"]), 3)
        self.assertTrue(all(result["reasons"] for result in response["results"]))
        self.assertTrue(all(result["match"]["explanation_fidelity"] == 1.0 for result in response["results"]))
        self.assertEqual(len(response["external_intent_by_axis"]), 8)
        self.assertIn("slate_diversity", response)
        self.assertEqual(app.health()["labels"], 69)
        report = response["analysis_report"]
        self.assertEqual(report["ask_analysis"]["raw_request"]["brief"], self.request().brief)
        self.assertEqual(report["candidate_summary"]["total_considered"], len(report["candidates"]))
        self.assertEqual(
            len([item for item in report["candidates"]
                 if item["disposition"] == "final_selection"]),
            len(response["results"]),
        )
        self.assertTrue(all("score_breakdown" in item for item in report["candidates"]))
        self.assertTrue(any(
            "weak_bridge" in " ".join(item["risk_flags"])
            for item in report["candidates"]
        ))

    def test_progress_callback_and_background_job_report_real_stages(self):
        events = []
        app.recommend(
            self.request(),
            lambda stage, message, **details: events.append((stage, message, details)),
        )
        self.assertEqual(events[0][0], "request_understood")
        self.assertIn("quality_selection", [event[0] for event in events])
        self.assertEqual(events[-1][0], "complete")

        created = app.create_recommendation_job(self.request())
        deadline = time.time() + 2
        status = app.recommendation_job_status(created["job_id"])
        while status["status"] == "running" and time.time() < deadline:
            time.sleep(0.01)
            status = app.recommendation_job_status(created["job_id"])
        self.assertEqual(status["status"], "complete")
        self.assertTrue(status["result"]["results"])
        self.assertEqual(status["events"][0]["stage"], "request_understood")

    def test_listener_ui_uses_discovery_only_and_places_restart_after_profile(self):
        page = app.listener_page()
        self.assertIn("features:{corpus_candidates:false}", page)
        self.assertIn("Genre orientation", page)
        profile = page.index('<div class="listening-profile">')
        restart = page.index('<div class="begin-again-row">')
        source = page.index('<div class="source">', restart)
        self.assertLess(profile, restart)
        self.assertLess(restart, source)

    def test_label_catalog_search_and_provenance(self):
        response = app.labels(genre="dream pop")
        self.assertGreater(response["count"], 0)
        self.assertEqual(response["provenance"]["source"], "curator")
        self.assertTrue(any(item["name"] == "4AD" for item in response["results"]))

    def test_adaptive_calibration_adds_stable_genre_and_visibility_controls(self):
        original_key = app.OPENAI_KEY
        original_call = app.openai_json_response
        app.OPENAI_KEY = "test-key"
        app.openai_json_response = lambda *_args: {
            "interpretation": "The request points to social environment rather than guitar tone.",
            "must_preserve": ["underground community"],
            "may_change": ["genre", "era"],
            "detected_genres": ["alternative rock"],
            "seed_artists": ["Jane's Addiction", "Invented Artist"],
            "questions": [{
                "id": "environment_focus",
                "question": "Which part of that environment matters?",
                "help": "This changes the contextual bridge.",
                "options": [
                    {"value": "community", "label": "Bohemian community",
                     "description": "A lived counterculture.",
                     "interpretation": "Preserve a lived countercultural community."},
                    {"value": "danger", "label": "Dangerous decadence",
                     "description": "Risk and intoxication.",
                     "interpretation": "Preserve danger and intoxication."},
                    {"value": "whole", "label": "The complete environment",
                     "description": "Hold the full social tension.",
                     "interpretation": "Preserve the complete social environment."},
                ],
            }],
        }
        try:
            output = app.analyze_calibration("More like Jane's Addiction's social environment")
        finally:
            app.OPENAI_KEY = original_key
            app.openai_json_response = original_call
        self.assertEqual(output["seed_artists"], ["Jane's Addiction"])
        self.assertEqual(
            [question["id"] for question in output["questions"]],
            ["environment_focus", "genre_distance", "visibility"],
        )

    def test_reference_free_prompt_gets_verified_musical_orientation(self):
        original_key = app.OPENAI_KEY
        original_call = app.openai_json_response
        original_verify = app.verify_release_group
        app.OPENAI_KEY = "test-key"
        app.openai_json_response = lambda *_args: {
            "interpretation": "Heavy rain could imply several very different musical worlds.",
            "must_preserve": ["rain-soaked atmosphere"],
            "may_change": ["genre", "instrumentation"],
            "detected_genres": [],
            "seed_artists": [],
            "reference": {"artist": "", "album": ""},
            "questions": [{
                "id": "musical_orientation",
                "question": "What does heavy rain sound like in your head?",
                "help": "This establishes a musical starting point.",
                "options": [{
                    "value": "weightless",
                    "label": "Weightless and immersive",
                    "description": "Long tones and blurred edges.",
                    "interpretation": "Begin in an ambient, rhythm-light musical world.",
                    "exemplar_artist": "Grouper",
                    "exemplar_album": "Ruins",
                }, {
                    "value": "physical",
                    "label": "Dark and physical",
                    "description": "Heavy bass and insistent rhythm.",
                    "interpretation": "Begin with bass weight, rhythm, and urban tension.",
                    "exemplar_artist": "",
                    "exemplar_album": "",
                }, {
                    "value": "intimate",
                    "label": "Intimate and reflective",
                    "description": "Sparse and emotionally close.",
                    "interpretation": "Begin with sparse, intimate music.",
                    "exemplar_artist": "",
                    "exemplar_album": "",
                }],
            }],
        }
        app.verify_release_group = lambda candidate: {
            **candidate, "artist": "Grouper", "album": "Ruins", "year": 2014,
            "rg_mbid": "verified-orientation", "verification_score": 1.0,
        }
        try:
            output = app.analyze_calibration("music for heavy rain")
        finally:
            app.OPENAI_KEY = original_key
            app.openai_json_response = original_call
            app.verify_release_group = original_verify
        question = output["questions"][0]
        self.assertEqual(question["id"], "musical_orientation")
        self.assertEqual(len(question["options"]), 5)
        self.assertEqual(question["options"][0]["exemplar"]["rg_mbid"], "verified-orientation")
        self.assertEqual(question["options"][3]["value"], "custom_orientation")
        self.assertEqual(question["options"][4]["value"], "open_orientation")
        self.assertEqual(output["seed_artists"], [])
        self.assertEqual(output["reference"], {"artist": "", "album": ""})

    def test_orientation_detection_is_conditional_and_has_a_model_free_fallback(self):
        original_key = app.OPENAI_KEY
        app.OPENAI_KEY = ""
        try:
            rain = app.analyze_calibration("music for heavy rain")
            anchored = app.analyze_calibration("music for heavy rain like Burial")
            genre = app.analyze_calibration("ambient music for heavy rain")
        finally:
            app.OPENAI_KEY = original_key
        self.assertEqual(rain["questions"][0]["id"], "musical_orientation")
        self.assertEqual(len(rain["questions"]), 1)
        self.assertEqual(len(rain["questions"][0]["options"]), 5)
        self.assertEqual(anchored["questions"][0]["id"], "interpretation_focus")
        self.assertEqual(genre["questions"][0]["id"], "interpretation_focus")

    def test_abstract_comparison_gets_orientation_but_musical_reference_does_not(self):
        original_key = app.OPENAI_KEY
        app.OPENAI_KEY = ""
        try:
            purple = app.analyze_calibration("I want music that sounds like the color purple")
            painting = app.analyze_calibration("music that feels like a faded painting")
            artist = app.analyze_calibration("I want music that sounds like Burial")
            concrete = app.analyze_calibration("purple-toned psychedelic soul")
        finally:
            app.OPENAI_KEY = original_key
        self.assertEqual(purple["stage"], "orientation")
        self.assertEqual(purple["questions"][0]["id"], "musical_orientation")
        self.assertEqual(painting["stage"], "orientation")
        self.assertEqual(artist["stage"], "calibration")
        self.assertEqual(concrete["stage"], "calibration")

    def test_orientation_answer_unlocks_second_calibration_stage(self):
        original_key = app.OPENAI_KEY
        app.OPENAI_KEY = ""
        try:
            response = app.get_tuning_questions(app.RecRequest(
                brief="music for heavy rain",
                calibration_answers=[app.CalibrationAnswer(
                    question_id="musical_orientation",
                    question="What should this sound like in your head?",
                    selected_label="Rhythmic and physical",
                    interpretation="Begin with a rhythm-led, bass-weighted sound.",
                )],
            ))
        finally:
            app.OPENAI_KEY = original_key
        self.assertEqual(
            [question["id"] for question in response["questions"]],
            ["interpretation_focus", "genre_distance", "visibility"],
        )

    def test_listener_ui_supports_custom_orientation_without_making_it_a_seed(self):
        page = app.listener_page()
        self.assertIn("custom-orientation", page)
        self.assertIn("custom_orientation_text", page)
        self.assertIn("listener-supplied musical orientation", page)
        self.assertIn("const seeds=(calibrationData.seed_artists||[])", page)
        self.assertIn("Listening inside that world", page)
        self.assertIn("calibration_answers:orientationAnswers", page)
        self.assertIn("calibrationAnswers=[...orientationAnswers,...stageAnswers]", page)
        self.assertIn("orientationAnswers.length?'3'", page)

    def test_optional_intelligence_can_be_disabled(self):
        toggles = app.FeatureToggles(external_taxonomy=False, axis_inference=False,
                                     slate_diversity=False, adaptive_questions=False)
        response = app.recommend(self.request(features=toggles, discovery_depth=None, visibility="any"))
        self.assertEqual(response["tuning_questions"], [])
        self.assertIsNone(response["slate_diversity"])
        self.assertTrue(all(not values for values in response["external_intent_by_axis"].values()))

    def test_listener_discovery_mode_skips_corpus_inventory(self):
        toggles = app.FeatureToggles(outside_discovery=False, corpus_candidates=False)
        response = app.recommend(self.request(features=toggles))
        self.assertEqual(response["results"], [])
        self.assertEqual(response["analysis_report"]["candidates"], [])
        stages = [
            stage["stage"] for stage in response["analysis_report"]["execution_recipe"]
        ]
        self.assertIn("listener_discovery_mode", stages)
        self.assertNotIn("pull_initial_corpus_list", stages)
        self.assertIn("calibration corpus remains separate", response["coverage"]["notes"][0])

    def test_frontier_guide_is_isolated_to_explicit_frontier_scouting(self):
        intent = {"moods": [], "sonic_traits": [], "scenes": [], "unmapped_terms": []}
        frontier = app.candidate_scout_payload(
            self.request(discovery_depth=None, genre_distance=4), intent, [], [], [],
        )
        deep = app.candidate_scout_payload(
            self.request(discovery_depth=None, genre_distance=3), intent, [], [], [],
        )
        open_translation = app.candidate_scout_payload(
            self.request(discovery_depth=None, genre_distance=5), intent, [], [], [],
        )
        context = frontier["frontier_exploration"]
        self.assertEqual(context["namespace"], "frontier_exploration")
        self.assertEqual(context["activation"], "explicit_genre_distance_4")
        self.assertEqual(context["persistence"], "none")
        self.assertEqual(context["engine_authority"], "unchanged")
        self.assertEqual(context["slate_contract"]["minimum_distinct_genre_families"], 3)
        self.assertEqual(context["slate_contract"]["maximum_final_records_per_genre_family"], 2)
        self.assertIn("# Frontier Genre Exploration", context["guide"])
        self.assertNotIn("frontier_exploration", deep)
        self.assertNotIn("frontier_exploration", open_translation)

    def test_calibration_copy_removes_third_person_product_language(self):
        self.assertEqual(
            app.calibration_display_copy(
                "The listener wants boundary-crossing rock with a volatile underground identity."
            ),
            "Boundary-crossing rock with a volatile underground identity.",
        )

    def test_frontier_slate_uses_three_genre_families_when_pool_supports_it(self):
        def result(name, family):
            return {
                "entity": {"artist": name, "title": name, "rg_mbid": name},
                "match": {"novelty_tier": "underheard"},
                "descriptor_groups": {"genre_family": family, "genres": [family]},
                "reasons": [{"provenance": {"confidence": 0.8}}],
            }

        pool = [
            result("Punk 1", "punk"), result("Punk 2", "post-punk"),
            result("Rock 1", "garage rock"), result("Rock 2", "punk blues"),
            result("Jazz 1", "spiritual jazz"), result("Salsa 1", "salsa"),
        ]
        selected = app.enforce_frontier_genre_diversity(
            pool[:5], pool, "underheard", 5,
        )
        families = {app.result_genre_family(item) for item in selected}
        self.assertGreaterEqual(len(families), 3)
        self.assertTrue({"jazz", "salsa"} & families)

    def test_impossible_constraint_is_no_match(self):
        response = app.recommend(self.request(hard_constraints=app.HardConstraints(year_min=2030)))
        self.assertEqual(response["coverage"]["status"], "no_match")
        self.assertTrue(all(
            item["disposition"] == "excluded_by_hard_constraint"
            for item in response["analysis_report"]["candidates"]
            if item["source_path"] == "curated_corpus"
        ))

    def test_outside_seed_is_visible(self):
        response = app.recommend(self.request(seeds=[app.Seed(artist="Taylor Swift")]))
        self.assertEqual(response["seeds"][0]["status"], "unknown")

    def test_ungrounded_relational_reference_abstains_instead_of_using_seed_list(self):
        toggles = app.FeatureToggles(outside_discovery=False)
        response = app.recommend(self.request(
            brief="records that show a similar sensation of wholeness as To Pimp a Butterfly",
            seeds=[app.Seed(artist="Kendrick Lamar")],
            features=toggles,
        ))
        self.assertEqual(response["results"], [])
        self.assertEqual(response["coverage"]["status"], "no_match")
        self.assertIn("not grounded", response["coverage"]["notes"][-1])

    def test_relational_reference_to_in_corpus_seed_can_use_curated_path(self):
        response = app.recommend(self.request(
            brief="records with a similar nocturnal feeling as The Cure",
            seeds=[app.Seed(artist="The Cure")],
        ))
        self.assertGreater(len(response["results"]), 0)

    def test_hard_mood_exclusion_removes_matching_albums(self):
        baseline = app.recommend(self.request())
        excluded_mood = baseline["parsed_intent"]["moods"][0]
        response = app.recommend(
            self.request(hard_constraints=app.HardConstraints(exclude_moods=[excluded_mood]))
        )
        self.assertTrue(
            all(excluded_mood not in result["match"]["matched_descriptors"] for result in response["results"])
        )

    def test_verified_discovery_keeps_inference_and_identity_provenance_separate(self):
        result = app.verified_candidate_result({
            "artist": "Verified Artist",
            "album": "Verified Album",
            "year": 1994,
            "rg_mbid": "00000000-0000-0000-0000-000000000001",
            "connection": "Preserves the requested restraint while shifting the scene context",
            "matched_descriptors": ["nocturnal", "nocturnal"],
            "scenes": ["coldwave"],
            "confidence": 0.78,
            "visibility": "underheard",
            "verification_score": 0.99,
            "research": {
                "genres": ["industrial hip hop", "experimental hip hop"],
                "sound_preview": "Clipped drums, abrasive electronics, and tightly projected vocals.",
            },
        })
        self.assertEqual(result["entity"]["corpus_status"], "verified_discovery")
        self.assertEqual(result["match"]["matched_descriptors"], ["nocturnal"])
        self.assertEqual(
            [reason["provenance"]["source"] for reason in result["reasons"]],
            ["llm_inferred", "musicbrainz"],
        )
        self.assertEqual(result["descriptor_groups"]["genres"][0], "industrial hip hop")
        self.assertIn("Clipped drums", result["descriptor_groups"]["sound_preview"])

    def test_identity_cache_avoids_a_repeat_musicbrainz_request(self):
        original_path = app.RUNTIME_DB_PATH
        original_agent = app.USER_AGENT
        cache_path = Path("tmp/test-runtime-identity-cache.db")
        cache_path.unlink(missing_ok=True)
        app.RUNTIME_DB_PATH = cache_path
        app.USER_AGENT = "test-agent"
        runtime = app.runtime_db()
        runtime.execute(
            """INSERT INTO identity_cache
               (normalized_artist, normalized_album, artist, album, year, rg_mbid,
                verification_score, verified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("cached artist", "cached album", "Cached Artist", "Cached Album", 1999,
             "00000000-0000-0000-0000-000000000099", 0.99, 1),
        )
        runtime.commit()
        runtime.close()
        try:
            resolved = app.verify_release_group({
                "artist": "Cached Artist",
                "album": "Cached Album",
                "connection": "Test",
                "matched_descriptors": ["nocturnal"],
                "scenes": [],
                "confidence": 0.8,
                "visibility": "mixed",
            })
        finally:
            app.RUNTIME_DB_PATH = original_path
            app.USER_AGENT = original_agent
            cache_path.unlink(missing_ok=True)
        self.assertEqual(resolved["identity_source"], "musicbrainz_cache")

    def test_identity_cache_rejects_a_conflicting_release_year(self):
        original_path = app.RUNTIME_DB_PATH
        original_agent = app.USER_AGENT
        cache_path = Path("tmp/test-runtime-conflicting-year.db")
        cache_path.unlink(missing_ok=True)
        app.RUNTIME_DB_PATH = cache_path
        app.USER_AGENT = "test-agent"
        runtime = app.runtime_db()
        runtime.execute(
            """INSERT INTO identity_cache
               (normalized_artist, normalized_album, artist, album, year, rg_mbid,
                verification_score, verified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("test artist", "test album", "Test Artist", "Test Album", 1983,
             "00000000-0000-0000-0000-000000000083", 0.99, 1),
        )
        runtime.commit()
        runtime.close()
        try:
            resolved = app.verify_release_group({
                "artist": "Test Artist", "album": "Test Album", "year": 1971,
                "connection": "Test", "matched_descriptors": [], "scenes": [],
                "confidence": 0.8, "visibility": "familiar",
            })
        finally:
            app.RUNTIME_DB_PATH = original_path
            app.USER_AGENT = original_agent
            cache_path.unlink(missing_ok=True)
        self.assertIsNone(resolved)

    def test_mixed_visibility_includes_an_underheard_survivor(self):
        familiar = [{
            "entity": {"artist": f"Known {index}", "title": "Album", "rg_mbid": f"k{index}"},
            "match": {"novelty_tier": "anchor"},
        } for index in range(3)]
        underheard = {
            "entity": {"artist": "Underheard", "title": "Album", "rg_mbid": "u"},
            "match": {"novelty_tier": "underheard"},
        }
        selected = app.enforce_visibility(familiar, familiar + [underheard], "mixed", 3)
        selected_ids = [item["entity"]["rg_mbid"] for item in selected]
        self.assertIn("u", selected_ids)
        self.assertTrue(any(item_id.startswith("k") for item_id in selected_ids))

    def test_repeat_can_return_for_a_different_strong_journey(self):
        original_path = app.RUNTIME_DB_PATH
        cache_path = Path("tmp/test-runtime-freshness.db")
        cache_path.unlink(missing_ok=True)
        app.RUNTIME_DB_PATH = cache_path
        runtime = app.runtime_db()
        runtime.execute(
            """INSERT INTO recommendation_exposures
               (listener_id, journey_id, rg_mbid, intent_signature, reason_signature, shown_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("listener", "old-journey", "a", "different-intent", "reason", 1),
        )
        runtime.commit()
        runtime.close()
        results = [
            {"entity": {"artist": "A", "title": "A", "rg_mbid": "a", "corpus_status": "core"},
             "match": {"score": 10}},
            {"entity": {"artist": "B", "title": "B", "rg_mbid": "b", "corpus_status": "core"},
             "match": {"score": 5}},
            {"entity": {"artist": "C", "title": "C", "rg_mbid": "c", "corpus_status": "core"},
             "match": {"score": 4}},
        ]
        req = self.request(listener_id="listener", journey_id="new-journey", n_results=2)
        try:
            selected = app.apply_freshness(results, req, "new-intent")
        finally:
            app.RUNTIME_DB_PATH = original_path
            cache_path.unlink(missing_ok=True)
        self.assertEqual([item["entity"]["rg_mbid"] for item in selected], ["a", "b"])
        self.assertTrue(selected[0]["freshness"]["previously_recommended"])

    def test_same_intent_repeat_yields_to_comparable_unseen_records(self):
        original_path = app.RUNTIME_DB_PATH
        cache_path = Path("tmp/test-runtime-same-intent.db")
        cache_path.unlink(missing_ok=True)
        app.RUNTIME_DB_PATH = cache_path
        runtime = app.runtime_db()
        runtime.execute(
            """INSERT INTO recommendation_exposures
               (listener_id, journey_id, rg_mbid, intent_signature, reason_signature, shown_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("listener", "old-journey", "a", "same-intent", "reason", 1),
        )
        runtime.commit()
        runtime.close()
        results = [
            {"entity": {"artist": "A", "title": "A", "rg_mbid": "a", "corpus_status": "core"},
             "match": {"score": 5}},
            {"entity": {"artist": "B", "title": "B", "rg_mbid": "b", "corpus_status": "core"},
             "match": {"score": 4.7}},
            {"entity": {"artist": "C", "title": "C", "rg_mbid": "c", "corpus_status": "core"},
             "match": {"score": 4.6}},
        ]
        req = self.request(listener_id="listener", journey_id="new-journey", n_results=2)
        try:
            selected = app.apply_freshness(results, req, "same-intent")
        finally:
            app.RUNTIME_DB_PATH = original_path
            cache_path.unlink(missing_ok=True)
        self.assertEqual([item["entity"]["rg_mbid"] for item in selected], ["b", "c"])

    def test_final_selection_has_no_inventory_source_quota(self):
        anchor = {
            "entity": {"artist": "Anchor", "title": "Known", "corpus_status": "core"},
            "match": {"score": 4.0, "matched_descriptors": []},
            "reasons": [],
        }
        discoveries = [
            {
                "entity": {"artist": f"Discovery {index}", "title": f"Album {index}",
                           "corpus_status": "verified_discovery"},
                "match": {"score": 3.0 - index / 10, "matched_descriptors": ["nocturnal"],
                          "novelty_tier": "underheard"},
                "reasons": [{"relationship_type": "researched_inferred_fit",
                             "claim": "Strong bridge",
                             "provenance": {"source": "llm_inferred", "confidence": 0.8}}],
            }
            for index in range(4)
        ]
        path = app.deterministic_slate([anchor] + discoveries, "underheard", 4)
        self.assertEqual(len(path), 4)
        self.assertTrue(all(item["entity"]["corpus_status"] == "verified_discovery" for item in path))

    def test_final_selector_rejects_weak_fit_and_allows_one_qualified_result(self):
        original_key = app.OPENAI_KEY
        original_call = app.openai_json_response
        app.OPENAI_KEY = "test-key"

        def candidate(index):
            return {
                "entity": {
                    "artist": f"Artist {index}", "title": f"Album {index}",
                    "year": 2000 + index, "rg_mbid": f"mbid-{index}",
                    "corpus_status": "verified_discovery",
                },
                "match": {
                    "score": 4.0 - index / 10, "matched_descriptors": ["nocturnal"],
                    "novelty_tier": "underheard",
                },
                "descriptor_groups": {"genres": ["ambient"]},
                "reasons": [{
                    "relationship_type": "researched_inferred_fit", "claim": "Supported bridge",
                    "provenance": {"source": "llm_inferred", "confidence": 0.8},
                }],
            }

        candidates = [candidate(index) for index in range(4)]
        assessments = [
            ("strong", [], 0.9),
            ("qualified", ["limited forward motion"], 0.75),
            ("qualified", ["limited warmth"], 0.7),
            ("reject", ["contradicts the essential mood"], 0.9),
        ]
        def quality_response(*args, **_kwargs):
            self.assertEqual(args[-1], 3600)
            return {"assessments": [{
                "rg_mbid": f"mbid-{index}", "fit": fit,
                "satisfied_requirements": ["alert solitude"],
                "weaknesses": weaknesses, "selection_reason": "Test assessment",
                "confidence": confidence,
            } for index, (fit, weaknesses, confidence) in enumerate(assessments)],
                    "selected_rg_mbids": ["mbid-0", "mbid-1", "mbid-2", "mbid-3"]}
        app.openai_json_response = quality_response
        try:
            selected = app.select_recommendation_slate(
                self.request(n_results=4, visibility="any"), candidates,
            )
        finally:
            app.OPENAI_KEY = original_key
            app.openai_json_response = original_call
        self.assertEqual(
            [item["entity"]["rg_mbid"] for item in selected],
            ["mbid-0", "mbid-1"],
        )
        self.assertEqual(selected[1]["quality_assessment"]["fit"], "qualified")
        self.assertEqual(
            selected[1]["quality_assessment"]["provenance"]["source"], "llm_inferred",
        )
        summary = app.quality_gate_summary(candidates)
        self.assertEqual(
            summary["counts"],
            {"strong": 1, "qualified": 2, "reject": 1, "unassessed": 0},
        )
        self.assertEqual(summary["status"], "complete")

    def test_failed_quality_gate_returns_no_unassessed_substitute(self):
        original_key = app.OPENAI_KEY
        original_call = app.openai_json_response
        app.OPENAI_KEY = "test-key"
        app.openai_json_response = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("quality gate unavailable")
        )
        candidate = {
            "entity": {
                "artist": "Artist", "title": "Album", "year": 2001,
                "rg_mbid": "mbid", "corpus_status": "verified_discovery",
            },
            "match": {"score": 4.0, "matched_descriptors": ["nocturnal"]},
            "descriptor_groups": {"genres": ["ambient"]},
            "reasons": [{
                "claim": "Supported bridge", "relationship_type": "researched_inferred_fit",
                "provenance": {"source": "llm_inferred", "confidence": 0.8},
            }],
        }
        try:
            selected = app.select_recommendation_slate(
                self.request(n_results=1, visibility="any"), [candidate],
            )
        finally:
            app.OPENAI_KEY = original_key
            app.openai_json_response = original_call
        self.assertEqual(selected, [])
        summary = app.quality_gate_summary([candidate])
        self.assertEqual(summary["status"], "unavailable")
        self.assertEqual(summary["counts"]["unassessed"], 1)

    def test_recommendation_pipeline_can_include_verified_outside_candidate(self):
        original_key = app.OPENAI_KEY
        original_agent = app.USER_AGENT
        original_generate = app.generate_album_candidates
        original_research = app.research_album_candidates
        original_verify = app.verify_release_group
        original_copy = app.compose_listener_copy
        original_parse = app.parse_brief
        original_select = app.select_recommendation_slate
        app.OPENAI_KEY = "test-key"
        app.USER_AGENT = "test-agent"
        app.generate_album_candidates = lambda *_args: [{
            "artist": "Outside Artist",
            "album": "Outside Album",
            "connection": "Carries the requested nocturnal atmosphere into a different scene",
            "matched_descriptors": ["nocturnal"],
            "scenes": ["coldwave"],
            "confidence": 0.8,
            "visibility": "underheard",
        }]
        app.research_album_candidates = lambda *_args: {
            "findings": [{
                "candidate_index": 0,
                "verdict": "supported",
                "bridge_summary": "Research supports the requested nocturnal bridge.",
                "supported_requirements": ["nocturnal atmosphere"],
                "limitations": [],
            }],
            "rabbit_holes": {
                "labels": [{"name": "4AD", "why": "A useful catalogue route.",
                            "provenance": {"source": "curator", "confidence": 0.8}}],
                "scenes": [{"name": "Coldwave", "why": "A useful scene route.",
                            "provenance": {"source": "llm_inferred", "confidence": 0.7}}],
            },
            "sources": [{"url": "https://example.test/source", "title": "Test source"}],
        }
        app.verify_release_group = lambda candidate: {
            **candidate,
            "year": 1997,
            "rg_mbid": "00000000-0000-0000-0000-000000000002",
            "verification_score": 0.99,
        }
        app.compose_listener_copy = lambda *_args: {
            "intent_title": "Nocturnal paths beyond the obvious",
            "summary": "A mixed calibrated and verified path.",
            "explanations": [{
                "rg_mbid": "00000000-0000-0000-0000-000000000002",
                "explanation": "A sharp, evidence-bounded editorial explanation.",
            }],
        }
        app.parse_brief = lambda *_args: {
            "moods": ["nocturnal"],
            "sonic_traits": ["reverb-drenched"],
            "scenes": [],
            "unmapped_terms": [],
        }
        app.select_recommendation_slate = lambda req, candidates: sorted(
            candidates,
            key=lambda item: item["entity"]["corpus_status"] != "verified_discovery",
        )[:req.n_results]
        try:
            response = app.recommend(self.request())
        finally:
            app.OPENAI_KEY = original_key
            app.USER_AGENT = original_agent
            app.generate_album_candidates = original_generate
            app.research_album_candidates = original_research
            app.verify_release_group = original_verify
            app.compose_listener_copy = original_copy
            app.parse_brief = original_parse
            app.select_recommendation_slate = original_select
        discoveries = [
            result for result in response["results"]
            if result["entity"]["corpus_status"] == "verified_discovery"
        ]
        self.assertEqual(len(discoveries), 1)
        self.assertEqual(response["discovery"]["status"], "verified")
        self.assertEqual(response["summary"], "A mixed calibrated and verified path.")
        self.assertEqual(response["intent_title"], "Nocturnal paths beyond the obvious")
        self.assertEqual(response["discovery"]["researched"], 1)
        self.assertEqual(response["rabbit_holes"]["scenes"][0]["name"], "Coldwave")
        self.assertIn("editorial_explanation", discoveries[0])
        outside = [
            item for item in response["analysis_report"]["candidates"]
            if item["source_path"] == "llm_outside_discovery"
        ]
        self.assertEqual(len(outside), 1)
        self.assertEqual(outside[0]["disposition"], "final_selection")
        self.assertEqual(outside[0]["research"]["verdict"], "supported")
        self.assertFalse(any(
            flag.startswith("weak_bridge") for flag in outside[0]["risk_flags"]
        ))
        stages = response["analysis_report"]["execution_recipe"]
        self.assertEqual(
            next(stage for stage in stages if stage["stage"] == "outside_candidate_generation")[
                "instruction"
            ],
            app.CANDIDATE_SCOUT_INSTRUCTION,
        )

    def test_short_quality_slate_researches_existing_reserve_once(self):
        originals = {
            "key": app.OPENAI_KEY, "agent": app.USER_AGENT,
            "generate": app.generate_album_candidates,
            "research": app.research_album_candidates,
            "verify": app.verify_release_group,
            "copy": app.compose_listener_copy,
            "parse": app.parse_brief,
            "select": app.select_recommendation_slate,
        }
        app.OPENAI_KEY = "test-key"
        app.USER_AGENT = "test-agent"
        proposals = [{
            "artist": f"Reserve Artist {index}", "album": f"Reserve Album {index}",
            "year": 1990 + index, "connection": "A supported nocturnal bridge.",
            "matched_descriptors": ["nocturnal"], "scenes": [], "confidence": 0.8,
            "visibility": "underheard", "genre_family": f"family-{index}",
            "frontier_route": "A distinct route.",
        } for index in range(12)]
        research_batch_sizes = []

        def research(_req, candidates, _labels):
            research_batch_sizes.append(len(candidates))
            supported = range(1) if len(research_batch_sizes) == 1 else range(len(candidates))
            return {
                "findings": [{
                    "candidate_index": index, "verdict": "supported",
                    "bridge_summary": "Research supports the bridge.",
                    "supported_requirements": ["nocturnal"], "limitations": [],
                    "visibility": "underheard", "release_year": candidates[index]["year"],
                    "genres": ["ambient"], "sound_preview": "Spacious and alert.",
                } for index in supported],
                "rabbit_holes": {"labels": [], "scenes": []}, "sources": [],
            }

        app.generate_album_candidates = lambda *_args: proposals
        app.research_album_candidates = research
        app.verify_release_group = lambda candidate: {
            **candidate, "rg_mbid": f"mbid-{candidate['album'].split()[-1]}",
            "verification_score": 0.99,
        }
        app.compose_listener_copy = lambda *_args: {
            "intent_title": "Reserve path", "summary": "A replenished path.",
            "explanations": [],
        }
        app.parse_brief = lambda *_args: {
            "moods": ["nocturnal"], "sonic_traits": [], "scenes": [],
            "unmapped_terms": [],
        }
        app.select_recommendation_slate = lambda req, candidates: candidates[:req.n_results]
        try:
            response = app.recommend(self.request(
                seeds=[], visibility="underheard",
                features=app.FeatureToggles(corpus_candidates=False),
            ))
        finally:
            app.OPENAI_KEY = originals["key"]
            app.USER_AGENT = originals["agent"]
            app.generate_album_candidates = originals["generate"]
            app.research_album_candidates = originals["research"]
            app.verify_release_group = originals["verify"]
            app.compose_listener_copy = originals["copy"]
            app.parse_brief = originals["parse"]
            app.select_recommendation_slate = originals["select"]
        self.assertEqual(research_batch_sizes, [8, 4])
        self.assertEqual(len(response["results"]), 5)
        self.assertTrue(response["discovery"]["reserve_used"])
        self.assertEqual(response["discovery"]["reserve_researched"], 4)
        self.assertEqual(response["discovery"]["reserve_verified"], 4)


if __name__ == "__main__":
    unittest.main()
