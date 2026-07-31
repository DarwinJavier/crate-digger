"""Dependency-free API logic smoke tests for constrained environments."""

import os
import sys
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

    def test_optional_intelligence_can_be_disabled(self):
        toggles = app.FeatureToggles(external_taxonomy=False, axis_inference=False,
                                     slate_diversity=False, adaptive_questions=False)
        response = app.recommend(self.request(features=toggles, discovery_depth=None, visibility="any"))
        self.assertEqual(response["tuning_questions"], [])
        self.assertIsNone(response["slate_diversity"])
        self.assertTrue(all(not values for values in response["external_intent_by_axis"].values()))

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
        })
        self.assertEqual(result["entity"]["corpus_status"], "verified_discovery")
        self.assertEqual(result["match"]["matched_descriptors"], ["nocturnal"])
        self.assertEqual(
            [reason["provenance"]["source"] for reason in result["reasons"]],
            ["llm_inferred", "musicbrainz"],
        )

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
        stages = response["analysis_report"]["execution_recipe"]
        self.assertEqual(
            next(stage for stage in stages if stage["stage"] == "outside_candidate_generation")[
                "instruction"
            ],
            app.CANDIDATE_SCOUT_INSTRUCTION,
        )


if __name__ == "__main__":
    unittest.main()
