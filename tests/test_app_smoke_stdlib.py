"""Dependency-free API logic smoke tests for constrained environments."""

import sys
import types
import unittest


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
        }
        values.update(overrides)
        return app.RecRequest(**values)

    def test_health_and_standard_recommendation(self):
        self.assertTrue(app.health()["ok"])
        response = app.recommend(self.request())
        self.assertGreaterEqual(len(response["results"]), 3)
        self.assertTrue(all(result["reasons"] for result in response["results"]))
        self.assertTrue(all(result["match"]["explanation_fidelity"] == 1.0 for result in response["results"]))

    def test_impossible_constraint_is_no_match(self):
        response = app.recommend(self.request(hard_constraints=app.HardConstraints(year_min=2030)))
        self.assertEqual(response["coverage"]["status"], "no_match")

    def test_outside_seed_is_visible(self):
        response = app.recommend(self.request(seeds=[app.Seed(artist="Taylor Swift")]))
        self.assertEqual(response["seeds"][0]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
