# Frozen evaluation harness

`frozen_cases.json` is the holdout set. Once cases are added, do not edit their
briefs or expected constraints during a run. Put game-derived and other development
cases under `research/taxonomies/`; they are calibration data, not holdout evidence.

Run `python evaluation/run_harness.py`. The harness is deterministic and makes no
network calls. Optional recommendation features can be disabled per case so the
legacy controlled-vocabulary path remains a baseline.

## Evaluation Room

Run the API and open `http://127.0.0.1:8000/evaluation`.

The interface uses a hybrid workflow:

1. Contributors enter and review all 25 unseen briefs.
2. The freeze action becomes available only at exactly 25 briefs.
3. Freezing makes the holdout immutable.
4. Evaluators work through one brief at a time and receive three recommendations.
5. Every recommendation receives five 1-to-5 ratings plus a required explanation.

Draft prompts are stored in `briefs.csv`; judgments are stored in `feedback.csv`.
The current listening room exercises the platform arm and labels it neutrally as
Set A. Additional blinded arms must be imported or implemented before the comparative
LLM/platform/hybrid experiment is run.
