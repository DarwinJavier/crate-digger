# Per-request recommendation analysis report

Every `POST /recommendations` response includes `analysis_report` by default. Set
`include_analysis_report` to `false` only when a smaller listener-facing payload is
needed.

The report is a decision record, not an LLM explanation written after selection. It
is assembled from the same request, candidate pool, score components, and selection
results used by the runtime.

## Reading order

1. `ask_analysis` preserves the raw request, the controlled intent, mapping coverage,
   and seed-resolution outcome.
2. `execution_recipe` gives the ordered stages. It includes the corpus retrieval rule
   and, when attempted, the exact outside-candidate and Researcher instructions plus
   the structured candidate-generation input.
3. `candidate_summary` counts each terminal disposition.
4. `candidates` is the complete ledger. It includes every corpus album and every
   optional outside proposal considered during the request.
5. `final_selection_logic` repeats the final order with its evidence and records the
   outside-discovery state.
6. `game_comparison_guide` aligns the ledger with the evaluation dimensions used in
   `research/taxonomies/recommendation-calibration-cases.csv`.

## Candidate dispositions

- `excluded_by_hard_constraint`: failed a year, bucket, seed-artist, or mood rule.
- `rejected_no_relevance_evidence`: survived constraints but had no qualifying
  descriptor, label, seed-bucket, or fan-overlap evidence.
- `ranked_candidate`: qualified and received a deterministic base rank but did not
  enter the diversity shortlist.
- `diversity_shortlist`: entered the expanded shortlist but was not materialized as a
  reserve.
- `displaced_one_album_per_artist`: removed because another album by the artist was
  already ahead of it.
- `displaced_before_final_selection`: was a usable reserve but lost during path
  blending, requested-count truncation, or freshness handling.
- `final_selection`: appeared in the returned slate. `final_rank` gives its position.
- Outside candidates additionally expose proposal, research, identity-verification,
  duplicate, and constraint outcomes.

## Diagnosing repeated albums

Filter `candidates` by artist, album, or MusicBrainz release-group ID across saved
responses. Compare:

- `matched_descriptors` and `score_breakdown` to see what changed between asks;
- `base_rank`, `disposition`, and `final_rank` to see where selection changed;
- `risk_flags` to find records that qualified only through a broad contextual bridge;
- `game_comparison.intent_fidelity_runtime_proxy`, which excludes novelty,
  visibility, core-corpus bonuses, and broad seed-bucket similarity;
- `freshness` in selected public results when listener and journey IDs are supplied.

A `weak_bridge` warning means the album qualified without a direct requested
descriptor, curated label-territory match, or researched outside-candidate fit. It is
the main signal to inspect when the same album appears across seemingly different
asks.

## Comparison with the recommendation games

The report uses the same independent dimensions established by the calibration
games: intent fidelity, evidence confidence, discovery distance, visibility, bridge
legibility, and diversity contribution. Runtime values are diagnostic proxies, not
human ratings. The historical game slates remain calibration evidence and must not be
presented as an unseen holdout benchmark.

For a side-by-side review, use one row per candidate with these columns:

| Ask | Candidate | Final? | Direct intent proxy | Evidence confidence | Distance | Visibility | Risk flags | Runtime reason | Game or curator note |
| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |
| Raw brief | Artist, album | disposition and rank | `game_comparison.intent_fidelity_runtime_proxy` | `game_comparison.evidence_confidence` | `game_comparison.discovery_distance` | `game_comparison.visibility` | `risk_flags` | `decision_reasons` | calibration CSV `notes` |

This format deliberately keeps machine rationale and curator judgment in separate
columns.
