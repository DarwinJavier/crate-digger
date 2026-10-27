# plan.md - Music Context Sandbox: Phased Plan

One builder, nights and weekends. Each phase has goals, tasks, and exit criteria.
A phase is not done until every exit criterion passes. Per AGENTS.md, the builder
announces phase completion and stops for human review before starting the next phase.

Status legend: [ ] todo, [~] in progress, [x] done

---

## Phase 0 - Repo and environment

**Goal:** a clean, versioned workspace where every later step is reproducible.

Tasks:
- [x] Create repo folder under `C:\Users\djhle\Code_Projects\`.
- [x] Add provided files: `app.py`, `AGENTS.md`, `plan.md`, `corpus-playbook.md`,
      and the seed album CSV.
- [x] Move source data into `data/`.
- [x] Add `.gitignore` for generated outputs, caches, and local env files.
- [x] Install approved base deps for the active Python runtime: `requests`,
      `fastapi`, `uvicorn`.
- [x] Initialize git.
- [x] Set a real MusicBrainz contact via `$env:MUSICBRAINZ_CONTACT`.
- [x] Run MusicBrainz resolution once contact is configured.
- [x] First commit.

Exit criteria:
- [x] `python -m py_compile build_corpus.py app.py` passes.
- [x] `git init` completed.
- [x] `git log` shows the initial commit.

---

## Phase 1 - Barebones recommendation proof

**Goal:** prove that curated descriptors plus provenance-labeled reasons can power
honest local recommendations over the current anchor corpus before doing the long
600-1,000 album expansion.

Tasks:
- [x] Add `build_corpus.py` with `resolve`, `build`, and `stats` commands.
- [x] Add starter controlled vocabulary in `data/vocab.csv`.
- [x] Add an approved starter descriptor core in `data/descriptors.csv`.
- [x] Generate `build/corpus.db` and `exports/corpus.jsonl`.
- [x] Keep `app.py` compatible with the generated SQLite schema.
- [x] Preserve the no-empty-reasons recommendation rule.
- [x] Integrate research-informed intent coverage, confidence-weighted score evidence,
      score-preserving diversity, and explanation-fidelity fields.
- [x] Gate MusicBrainz calls on a real User-Agent contact.
- [x] Run `python build_corpus.py resolve` after `$env:MUSICBRAINZ_CONTACT` is set.
- [x] Review and fix any rows in `data/unresolved.csv` after live resolution.
- [x] Keep Last.fm as an optional query-time adapter, not a Phase 1 dependency.

Exit criteria:
1. [x] `/health` returns `ok: true` with nonzero album and core counts.
2. [x] Standard smoke brief (`nocturnal elegant reverb-drenched`, seed `The Cure`,
   novelty `non_obvious`) returns at least 3 results, each with at least 1
   provenance-labeled reason.
3. [x] Impossible constraint (`year_min: 2030`) returns
   `coverage.status: "no_match"`.
4. [x] Out-of-corpus seed such as `Taylor Swift` returns `unknown` when no
   MusicBrainz contact is configured, with a coverage note.
5. [x] Hard mood exclusion removes matching albums from results.
6. [x] Live MusicBrainz resolution has run with a real contact and unresolved rows
   have been reviewed.
7. [x] Core recommendations work without optional Last.fm or LLM credentials;
   Last.fm remains query-time only when configured.

Current Phase 1 corpus:
- 177 albums.
- 36 core descriptor-annotated albums.
- Buckets A-N represented.
- Years 1978-2024.

---

## Phase 2 - Corpus foundation

**Goal:** grow the verified corpus to 600-1,000 albums with 150-300 core albums,
spread across the 14 buckets and decades per the corpus playbook allocation table.

Tasks:
- [ ] Resolve all seed albums against MusicBrainz.
- [ ] Fix or discard everything in `data/unresolved.csv`; rerun until clean.
- [~] Add label expansion support when needed: integrated a curated 69-label graph for
      label lookup, genre/scene traversal, and verified release-label reasoning; catalog-based
      MusicBrainz expansion remains to be implemented. Initial targets include 4AD, Factory, Creation, Sarah Records,
      Kranky, Projekt, Sacred Bones, Captured Tracks, Dais, Slumberland, Mo'Wax.
- [ ] Manual research passes for hard buckets J, K, and M.
- [ ] Review and tighten `data/vocab.csv`.
- [ ] Annotate descriptors for at least 150 core albums, stretch 300.
- [ ] Rebuild and run `stats`; check spread against playbook quotas.

Exit criteria:
- [ ] At least 600 albums in `corpus.db`, all with resolved release-group MBIDs.
- [ ] At least 150 albums with `corpus_status = core`.
- [ ] Every bucket A-N has at least 10 albums.
- [ ] Every decade 1970s-2020s is represented.
- [ ] Zero rows lingering in `data/unresolved.csv`.
- [ ] `build` runs clean with no unknown-tag warnings.

On completion, post:

```text
=== BAREBONES READY ===
Corpus: <N> albums (<N core>) across <N> buckets, <year-min>-<year-max>
Checklist: [pass/fail per Phase 2 exit criterion]
Known gaps: <list>
Awaiting human go-ahead for Phase 3.
```

Then stop for human review.

---

## Phase 3 - Evaluation harness

**Goal:** honestly test whether the platform beats an LLM alone.

Tasks:
- [ ] Treat the completed recommendation games as a development/calibration set;
      preserve their cases, curator profiles, corrections, and known failure modes.
- [ ] Turn the game-derived evaluation contract into a scored rubric covering intent
      fidelity, evidence confidence, discovery distance, visibility, bridge
      legibility, descriptor precision/recall, axis coverage, and slate diversity.
- [ ] Write and freeze 25 new holdout briefs that were not used to tune the system.
- [ ] Run 3 arms: LLM alone, platform, platform plus LLM summary.
- [ ] Blind-rate with 2-3 friends.
- [ ] Add automated checks for entity existence, constraints, and traps.

Exit criteria:
- [ ] Game results are reported as calibration evidence, separate from holdout results.
- [ ] Results are written up honestly, including where the LLM alone won.
- [ ] Decision recorded: continue, adjust corpus, or rethink.

---

## Experimental track R - Recommendation intelligence (explicitly authorized 2026-07-19)

**Goal:** implement the game-derived recommendation controls and evidence model now,
without claiming Phase 2 corpus readiness or weakening the provenance boundary.

This track was explicitly authorized by the human while Phase 2 remains open. It is
an experimental track, not a silent transition into Phase 3 or Phase 4. Features may
operate over the current corpus, but quality claims must wait for the frozen harness.

Tasks:
- [x] Add adaptive tuning questions plus independent discovery-depth and visibility controls.
- [x] Add artist-arc, scoped evidence, confidence-state, and completeness schemas.
- [x] Load the 477-term external taxonomy for optional active brief retrieval.
- [x] Add an explicit, approval-gated project/external descriptor crosswalk.
- [x] Add optional axis-by-axis intent inference and pairwise slate-diversity scoring.
- [x] Add image feature input/extraction and preservation/transformation scoring.
- [x] Add quarantined external candidate scouting that cannot bypass corpus verification.
- [x] Freeze a versioned evaluation harness with feature toggles and deterministic checks.
- [x] Add a local brief-entry and one-at-a-time listening interface with immutable
      freezing, autosaved ratings, and required qualitative justification.
- [x] Reframe the hand-curated corpus as a calibration anchor set rather than a
      recommendation ceiling (explicitly authorized 2026-07-23).
- [x] Add optional brain-guided OpenAI candidate discovery with strict structured
      output, query-time MusicBrainz verification, provenance-labeled inference,
      and deterministic fallback to calibrated anchors.
- [x] Add a listener-facing prompt calibration round with genre-boundary guidance,
      five discovery-depth levels, independent visibility controls, compact intent
      titles, editorial explanations, and grouped descriptor/label/scene context.
- [x] Replace generic meaning controls with one request-specific interpretive question,
      five genre-distance levels, independent visibility, and arbitrary named-artist
      seed extraction constrained to the listener's own wording.
- [x] Add a web-enabled Researcher pass before final MusicBrainz resolution, reject
      unsupported contextual bridges, and expose answer-level label and scene routes.
- [x] Add a disposable MusicBrainz identity cache plus context-aware listener exposure
      history; cached status is never a ranking feature, and strong records may return
      for materially different journeys.
- [x] Add a complete per-request analysis report with the exact execution recipe,
      every considered corpus and outside candidate, selection dispositions, weak-bridge
      warnings, and fields aligned to the recommendation-game comparison axes.
- [x] Remove inventory-source quotas, add a separate comparative slate pass, make
      visibility a slate requirement, carry explicit reference-record context, and
      reject inconsistent MusicBrainz title/year matches.
- [x] Make the listener UI discovery-only: skip corpus album scoring and report only
      proposed, researched, verified, and selected discovery candidates. Preserve
      corpus retrieval behind an explicit feature toggle for calibration/evaluation.
- [x] Add conditional musical-orientation calibration for ambiguous reference-free
      requests without turning verified exemplars into recommendation inventory.
- [x] Split situational calibration into an orientation stage followed by interpretation,
      genre-distance, and visibility questions generated from the selected world.
- [x] Add an auditable final quality gate with strong/qualified/reject verdicts and one
      bounded research pass over unused generated candidates when the initial slate is short.
- [x] Add process-local background recommendation jobs and honest listener-facing progress
      checkpoints without exposing provisional album identities or simulated percentages.
- [x] Add a curated listener prompt deck with session-stable inspiration, capability-based
      starting points, and an expandable gallery that never submits without listener action.
- [x] Add an environment-controlled public mode that preserves recommendation behavior while
      hiding evaluation writes, framework documentation, detailed health diagnostics, and
      internal request-level analysis reports.
- [x] Add anonymous public journey feedback with structured fit, discovery, listening-intent,
      and flow signals; strict SQLite storage; and a bearer-protected owner CSV export.
- [x] Add a Render Blueprint with pinned Python dependencies, deterministic corpus build,
      public-mode defaults, health checks, dashboard-only secrets, and persistent feedback disk.

Exit criteria:
- [x] Existing Phase 1 smoke checks still pass.
- [x] Every new inference exposes source, numeric confidence, and Core/Probable/Possible state.
- [x] Disabling optional features reproduces the legacy controlled-vocabulary path.
- [x] External taxonomy and crosswalk validation pass without unknown identifiers.
- [x] Scouted entities never appear as recommendations until resolved and curated.
- [ ] Frozen cases are immutable by convention and calibration cases remain separate.
      Harness exists, but zero genuinely new holdout prompts have been approved.
- [x] Current limitations are reported without claiming Phase 2 or Phase 3 completion.

---

## Experimental track S - Spotify listening (authorized 2026-10-26)

**Goal:** connect the listener's Spotify account for exploration, private playlist
export, and playback control without adding Spotify content to recommendation data.
This is an explicitly approved side track while corpus and evaluation gates stay open.

Tasks and exit checks:
- [x] Amend AGENTS.md rule 5 for the approved account/listening exception.
- [x] Implement PKCE, browser-bound one-use OAuth state, expiring server-side
      sessions, CSRF checks, per-user cookies, refresh, and disconnect.
- [x] Link the listener and each recommendation to a separate Spotify controls page.
- [x] Add explicit track selection, private playlist creation/addition, album/track
      search, track queueing, device selection, and play/pause/next/previous.
- [x] Keep account data, tokens, and Spotify search results out of the corpus,
      recommendation evidence, exports, and model prompts. Add no dependencies.
- [x] Document developer dashboard configuration, Premium/allowlist restrictions,
      process-local session limits, and partial playlist failure behavior.
- [x] Record passing offline security/transport tests and required recommendation smoke checks:
      63 existing tests plus 14 real-ASGI integration tests pass; Python compilation
      and listener/Spotify JavaScript syntax checks pass. Health, reason-bearing
      recommendations, impossible-year no-match, and outside-corpus seed checks pass.
- [ ] Configure the user's Spotify app and verify authorization, playlist export,
      and playback against the real account. No real account actions taken yet.

Status: implementation passes offline validation; live-account acceptance remains
pending the user's Spotify Developer Dashboard setup. No Phase 2+ completion claim.

---

## Phase 4 - Targeted enrichment, conditional

**Goal:** address only the recommendation failures demonstrated by Phase 3.

Candidate tasks, selected from evaluation evidence:
- [ ] Add verified album-to-album relationship edges when a failed brief needs them.
- [ ] Evaluate Wikidata's CC0 structured data for those relationship edges, joined
      through stable MusicBrainz or Wikidata identifiers.
- [ ] Use relationship edges in scoring and reasons only when they demonstrably
      improve a frozen failure case.
- [ ] Add descriptor soft-matching when vocabulary misses justify it.
- [ ] Add local feedback logging when continued human evaluation needs it.

Exit criteria:
- [ ] Every implemented enrichment traces to a documented Phase 3 failure.
- [ ] Re-evaluation shows whether each enrichment improved that failure without
      weakening constraints, provenance, or explanation fidelity.
- [ ] If Phase 3 demonstrates no material enrichment need, record that decision and
      close this phase without adding machinery.

---

## Phase 5 - Share and shape

**Goal:** put it in front of humans and agents; decide what this becomes.

Candidate tasks:
- [ ] MCP server wrapper.
- [ ] Merge with or power the Music Archaeology Engine front end.
- [ ] Write the Mr. Dasein essay documenting the build.
- [ ] First outreach conversations.

Exit criteria:
- [ ] Defined after the Phase 3 evaluation and any required Phase 4 enrichment.

---

## Standing reminders

- Curation is the moat; the software is a weekend. When time is short, curate.
- Buckets J, K, M are where this beats every LLM. Feed them.
- Never let a change violate AGENTS.md hard rules to hit a phase deadline.
- `brain/recommendation-logic.md` records the active recommendation policy and the
  pressure-test findings that guide later retrieval, evidence, and evaluation work.
