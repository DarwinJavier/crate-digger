# Crate Digger

An agent-first music intelligence sandbox for finding records through context, not popularity alone. Crate Digger turns a hand-curated corpus spanning post-punk, dream pop, shoegaze, slowcore, trip-hop, darkwave, coldwave, and underrepresented regional scenes into typed, evidence-backed recommendations. Its differentiator is trust: entities are verified, interpretations are labeled, and the system says when its evidence or coverage is insufficient.

## Features

- **Context-led discovery:** Translates natural-language briefs such as `nocturnal elegant reverb-drenched` into musical intent, constraints, and discovery controls.
- **Evidence-backed recommendations:** Every result includes at least one reason with a source label, numeric confidence, and confidence state.
- **Independent discovery controls:** Separates genre distance from artist visibility so listeners can ask for a familiar sound without defaulting to familiar names.
- **Verified outside-corpus discovery:** Optional model-guided candidates must resolve against MusicBrainz before they can appear; musical fit remains labeled `llm_inferred`.
- **Curated calibration anchors:** Uses a human-maintained corpus and controlled vocabulary as the trusted foundation rather than treating model recall as fact.
- **Honest coverage states:** Reports `no_match`, `known_outside_corpus`, or `unknown` instead of fabricating results.
- **Auditable analysis:** Can return the request interpretation, candidates considered, selection dispositions, evidence quality, and weak-bridge warnings.
- **Listener and evaluation rooms:** Includes local interfaces for guided discovery, frozen evaluation briefs, ratings, and qualitative feedback.
- **Deterministic corpus pipeline:** Builds a disposable SQLite database and JSONL export from versioned CSV sources of truth.
- **Optional external signals:** Supports query-time Last.fm signals without writing Last.fm data into the corpus.

## Current status

The recommendation proof and experimental recommendation-intelligence track are implemented. Corpus expansion is still in progress: the current documented baseline is 177 verified albums, including 36 core descriptor-annotated albums, across buckets A-N and years 1978-2024.

This is a local research sandbox, not a finished consumer recommendation service. Phase 2 targets at least 600 verified albums and 150 core albums before the project can claim barebones corpus readiness. Comparative holdout evaluation is also not complete.

## Prerequisites

- Python 3.12
- `requests`, `fastapi`, and `uvicorn`
- A MusicBrainz contact email or project URL for entity resolution
- An OpenAI API key only for optional model-guided discovery and prose
- A Last.fm API key only for optional query-time signals

## Setup

Clone the repository and enter it:

```text
git clone <your-repository-url>
cd crate-digger
```

Create a virtual environment and install the approved base dependencies in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install requests fastapi uvicorn
```

Create the local environment file:

```powershell
Copy-Item .env.example .env
```

Then fill in only the values needed for the features you want to use:

| Variable | Required | Description |
| --- | --- | --- |
| `MUSICBRAINZ_CONTACT` | For MusicBrainz calls | Descriptive contact email or project URL used in the required User-Agent |
| `OPENAI_API_KEY` | For model-guided discovery | Enables structured candidate discovery, intent inference, and bounded explanation prose |
| `OPENAI_MODEL` | For model-guided discovery | Model used for optional query-time inference; a cost-conscious default is provided |
| `LASTFM_API_KEY` | For Last.fm signals | Enables optional query-time similar-artist and tag signals that are never stored |

Never commit `.env` or expose its values to browser code.

## Build the corpus

The CSV files under `data/` are authoritative. Build outputs under `build/` and `exports/` are generated and can be recreated at any time.

```powershell
python build_corpus.py resolve
python build_corpus.py enrich-musicbrainz
python build_corpus.py build
python build_corpus.py stats
```

MusicBrainz operations require `MUSICBRAINZ_CONTACT` and are deliberately limited to one request per second. Local builds and statistics do not require network access.

To scout candidates for human review:

```powershell
python build_corpus.py scout --query "artist:Cocteau Twins" --limit 10
```

Scouting never bypasses verification or human curation.

## Run

Start the local API from the repository root after building the corpus:

```powershell
uvicorn app:app --reload
```

Open:

- `http://127.0.0.1:8000/` for the basic interface
- `http://127.0.0.1:8000/listen` for guided listener discovery
- `http://127.0.0.1:8000/evaluation` for the evaluation room
- `http://127.0.0.1:8000/docs` for interactive API documentation

Core corpus recommendations work without OpenAI or Last.fm credentials. Features that need unavailable external services return labeled fallback or coverage states.

## API

Recommendation and discovery endpoints:

```text
POST /recommendations
POST /recommendation-jobs
GET  /recommendation-jobs/{job_id}
POST /tuning-questions
GET  /labels
```

Evaluation endpoints:

```text
GET  /evaluation/state
POST /evaluation/briefs
POST /evaluation/freeze
POST /evaluation/feedback
GET  /evaluation
```

Platform endpoints:

```text
GET /health
GET /
GET /listen
```

Example recommendation request:

```json
{
  "brief": "nocturnal elegant reverb-drenched",
  "seeds": [{"artist": "The Cure"}],
  "novelty": "non_obvious",
  "n_results": 5,
  "discovery_depth": 4,
  "visibility": "obscure",
  "include_analysis_report": true
}
```

The full request schema, including hard constraints, calibration answers, reference records, image features, and feature toggles, is available at `/docs`.

## Tests

Run the required syntax check:

```powershell
python -m py_compile app.py build_corpus.py
```

Run the standard-library test suite:

```powershell
python -m unittest discover -s tests -v
```

Run the deterministic evaluation harness:

```powershell
python evaluation/run_harness.py
```

Before declaring an application change complete, also verify:

- `/health` returns `ok: true` with a nonzero album count.
- The standard smoke brief returns results and every result has at least one provenance-labeled reason.
- `year_min: 2030` returns `coverage.status: "no_match"`.
- An out-of-corpus seed returns `known_outside_corpus` or `unknown`.

## Project structure

```text
crate-digger/
|-- app.py                         # FastAPI routes, runtime orchestration, and local interfaces
|-- build_corpus.py                # Resolution, enrichment, build, scouting, and statistics
|-- recommendation_logic.py        # Intent, confidence, diversity, and scoring helpers
|-- listener_ui.py                 # Guided listener discovery interface
|-- evaluation_ui.py               # Evaluation-room interface
|-- evaluation_store.py            # Frozen briefs and evaluator feedback storage
|
|-- data/                          # Human-maintained source CSVs and resolved entity data
|-- brain/                         # Recommendation policy and research synthesis
|-- evaluation/                    # Frozen cases, briefs, feedback, and deterministic harness
|-- research/                      # Taxonomy research and quarantined local artifacts
|-- tests/                         # Application, logic, UI, and evaluation tests
|
|-- build/                         # Generated SQLite databases; not committed
|-- exports/                       # Generated JSONL corpus; not committed
|-- corpus-playbook.md             # Corpus design, buckets, and curation strategy
|-- plan.md                        # Phased delivery plan and readiness gates
|-- AGENTS.md                      # Engineering, provenance, security, and data-rights rules
|-- .env.example                   # Safe environment-variable template
`-- README.md                      # Project overview and operating instructions
```

## Trust, provenance, and data rules

- MusicBrainz verifies entity identity and release dates; it does not verify musical interpretation.
- Human curation, MusicBrainz, Wikidata, Last.fm, and model inference remain visibly distinct sources.
- Model-proposed musical relationships remain `llm_inferred` with numeric confidence.
- A recommendation with an empty `reasons` list must never be returned.
- Descriptors must belong to the approved vocabulary in `data/vocab.csv`.
- Last.fm is query-time only and is never written into the corpus.
- Spotify, Apple Music, and Rate Your Music data are not used.
- Generated databases and exports are disposable; data corrections belong in the source CSVs.

These boundaries are product features, not implementation trivia. They make the system's recommendations inspectable and let a listener distinguish verified identity from curator judgment and probabilistic interpretation.

## Evaluation

The project is designed to test whether a curated, provenance-aware platform can outperform an LLM alone on recommendation quality and trust. The planned comparison has three arms: LLM alone, platform, and platform plus LLM summary.

Development and calibration cases remain separate from the future holdout set. Once 25 unseen briefs are approved and frozen, they must not be edited during an evaluation run. Current results should not be presented as comparative proof until that holdout is complete.

## Authoritative documents

- `AGENTS.md` - engineering, provenance, security, and data-rights rules
- `plan.md` - phased roadmap, exit criteria, and current status
- `corpus-playbook.md` - corpus allocation and curation strategy
- `brain/recommendation-logic.md` - active recommendation policy
- `evaluation/README.md` - frozen evaluation workflow

When documents conflict, follow `AGENTS.md` for non-negotiable engineering and trust boundaries, then `plan.md` for phase scope and readiness.
