# Recommendation intelligence implementation

This layer implements the recommendation-game learnings without replacing the
project vocabulary or weakening corpus trust.

## Request controls

- `discovery_depth`: 1 through 5. It controls distance from the obvious conversation.
- `visibility`: `any`, `familiar`, `mixed`, or `underheard`. This is independent of depth.
- `meaning_focus`: sound, emotion, artist context, or all. Adaptive questions expose
  this when words such as chaotic or dense are ambiguous.
- `visual_role`: preserve, transform, or journey.
- `features`: independent switches for questions, depth, external taxonomy retrieval,
  axis inference, diversity, visual scoring, and frozen evaluation.

## Descriptor systems

`data/vocab.csv` remains the active curated project vocabulary. The 477-term external
taxonomy is a second retrieval vocabulary organized over atmosphere, form, lyrics,
mood, style, technique, theme, and vocals. Query-time assignments include evidence,
numeric confidence, and a Core/Probable/Possible state. They do not write into
`data/descriptors.csv`.

`data/descriptor_crosswalk.csv` is approval-gated. The initial approved rows are exact
identifier matches authorized as part of this implementation. Definition compatibility
still needs ongoing curator review. Non-exact mappings must not be activated merely
because labels feel related.

## Label graph

`data/label_catalog.json` is curator-authored source data for label lookup and
exploration. The build validates its 69 modeled entities, controlled attributes,
terms, and graph targets before compiling them into SQLite. Albums connect to these
entities only through conservative exact-name matches against stored MusicBrainz
release-label metadata. Anchor artists remain descriptive catalog terms and do not
create album-label facts. Label genres, moods, textures, and scenes can support a
recommendation only when both the MusicBrainz album-label edge and matching curated
label term are exposed in the reason evidence. Unmodeled related labels remain
frontier nodes and cannot enter recommendations.

## Evidence and context

- `data/artist_arcs.csv` stores album-specific career stage, transition, reputation,
  and context.
- `data/descriptor_evidence.csv` keeps album, track, and scene evidence separate.
- `data/image_features.csv` stores approved visual profiles for candidate covers.
- Annotation completeness estimates axis coverage and evidence volume. It explicitly
  reports that it is not an estimate of truth.

## Images

The local web form extracts low-level appearance features in the browser. These are
used only when an album has an approved visual profile. Preservation rewards similarity;
transformation rewards contrast; journey remains neutral until a sequence model is
supported. Semantic image interpretation remains a user or curator input.

## External scouting

`python build_corpus.py scout --query "..."` searches MusicBrainz release groups and
writes only to `data/external_candidates.csv`. Every row is `pending_review` and cannot
enter recommendation retrieval until it is resolved and deliberately added to the
curated corpus.

The listener API also supports a separate query-time discovery path. OpenAI receives
the parsed brief, controlled intent, discovery controls, seed context, curated label
territories, and already-selected anchors. It proposes a structured candidate slate.
Every candidate must independently resolve as a MusicBrainz release group before it can
be displayed. The MusicBrainz identity is verified evidence; the musical connection
remains `llm_inferred` with numeric confidence. Query-time discoveries do not write to
curator CSVs and do not require manual admission to the calibration set.

## Evaluation

`evaluation/run_harness.py` validates the frozen holdout contract without network
calls. `evaluation/frozen_cases.json` is intentionally separate from the game-derived
calibration cases. The harness is implemented, but the holdout contains zero cases
until the human supplies or approves new prompts that were not used for tuning.
