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
- [ ] Confirm Last.fm signal path with `$env:LASTFM_API_KEY`.

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
7. [ ] Last.fm signal path works and is never persisted to `corpus.db`.

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
- [ ] Add label expansion support when needed: 4AD, Factory, Creation, Sarah Records,
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

## Phase 3 - Signals and relationships

**Goal:** deepen the reasoning layer beyond tags: typed album-to-album relationships
and better ranking.

Tasks:
- [ ] Populate verified album-to-album relationship edges.
- [ ] Use relationship edges in scoring and reasons.
- [ ] Add descriptor soft-matching if needed.
- [ ] Add `POST /feedback` writing to a local log.

Exit criteria:
- [ ] At least 100 verified relationship edges.
- [ ] At least one brief is demonstrably answered better via an edge than via tags alone.
- [ ] Feedback endpoint logging works.

---

## Phase 4 - Mini evaluation harness

**Goal:** honestly test whether the platform beats an LLM alone.

Tasks:
- [ ] Write and freeze 25 test briefs.
- [ ] Run 3 arms: LLM alone, platform, platform plus LLM summary.
- [ ] Blind-rate with 2-3 friends.
- [ ] Add automated checks for entity existence, constraints, and traps.

Exit criteria:
- [ ] Results are written up honestly, including where the LLM alone won.
- [ ] Decision recorded: continue, adjust corpus, or rethink.

---

## Phase 5 - Share and shape

**Goal:** put it in front of humans and agents; decide what this becomes.

Candidate tasks:
- [ ] MCP server wrapper.
- [ ] Merge with or power the Music Archaeology Engine front end.
- [ ] Write the Mr. Dasein essay documenting the build.
- [ ] First outreach conversations.

Exit criteria:
- [ ] Defined after Phase 4.

---

## Standing reminders

- Curation is the moat; the software is a weekend. When time is short, curate.
- Buckets J, K, M are where this beats every LLM. Feed them.
- Never let a change violate AGENTS.md hard rules to hit a phase deadline.
- `brain/recommendation-logic.md` records the active recommendation policy and the
  pressure-test findings that guide later retrieval, evidence, and evaluation work.
