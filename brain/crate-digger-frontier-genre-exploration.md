---
name: explore-frontier-genres
description: Guide cross-genre exploration for the Crate Digger AI discovery agent only when a request is explicitly classified as a frontier ask. Use it to find defensible paths beyond familiar genre boundaries through sonic, aesthetic, historical, cultural, functional, and audience proximities. Never use it for ordinary recommendations, and never modify, retrain, reweight, override, or write results into the current recommendation engine.
---

# Frontier Genre Exploration

## Purpose

Use this guide to explore beyond a listener's established genre neighborhood when the active request is a **frontier ask**. Find credible cross-genre routes, bridge recordings, and revealing destinations while preserving a clear explanation of how each move connects to the request.

Treat this skill as a temporary exploration layer. It may read the active request and any context the current system exposes, but it must not change the recommendation engine, its rankings, weights, profiles, embeddings, taxonomies, rules, or stored state.

## Activation gate

Run this skill only when the calling system has explicitly marked the request as a frontier ask, or when the user unmistakably asks to cross, stretch, or escape genre boundaries.

Typical frontier asks include:

- “Take me somewhere unfamiliar from shoegaze.”
- “Find a path from dub to experimental electronic music.”
- “What is beyond the edge of my usual jazz listening?”
- “Give me surprising music that still connects to this album.”
- “Bridge these two distant styles.”
- “Explore across genres, not just within the obvious neighborhood.”

If no explicit frontier classification exists and the language is ambiguous, do not self-activate. Return control to the normal request router.

## Non-trigger conditions

Do not use this skill for:

- ordinary similarity, “more like this,” or same-genre recommendations;
- routine discovery already handled by the current engine;
- requests for canonical, popular, safe, or familiar choices;
- genre definitions, taxonomic lookup, or metadata cleanup alone;
- playlist sequencing without a cross-genre exploration goal;
- requests where “frontier” refers to technology, geography, history, or another non-musical meaning;
- background enrichment that was not requested by the user or calling system.

When these conditions apply, leave the task entirely to the existing engine or relevant workflow.

## Isolation contract

Obey all of the following:

1. **Read only.** Treat the engine, listener model, catalog scores, and taxonomy as immutable inputs.
2. **No hidden re-ranking.** Do not substitute frontier results for the engine's ordinary results.
3. **No persistence.** Do not save inferred preferences, altered weights, new genre edges, or exploration outcomes unless a separate authorized process explicitly requests it.
4. **No retraining or tuning.** Do not modify embeddings, classifiers, prompts, thresholds, or recommendation logic.
5. **No taxonomy overwrite.** Use a temporary multi-relational graph for reasoning; do not replace the engine's genre hierarchy.
6. **Namespaced output.** Label all results as `frontier_exploration` so downstream systems can keep them separate.
7. **Clean handoff.** Return the exploration result and stop. The current engine remains authoritative outside this frontier ask.

## Operating model

Do not treat genre as one tree or use one universal distance. Use the existing taxonomy only as a navigational reference. Build a temporary, query-specific graph in which nodes may be genres, scenes, movements, artists, albums, tracks, production aesthetics, or descriptors.

Use typed relationships such as:

- `SUBGENRE_OF`, `OVERLAPS_WITH`, `FUSION_OF`
- `EMERGED_FROM`, `INFLUENCED_BY`, `REINTERPRETS`
- `SONICALLY_SIMILAR_TO`, `TEXTURALLY_SIMILAR_TO`, `PRODUCTIONALLY_SIMILAR_TO`
- `ASSOCIATED_WITH_SCENE`, `SHARES_AUDIENCE_WITH`
- `MOOD_SIMILAR_TO`, `FUNCTIONALLY_SIMILAR_TO`

Keep genre, scene, movement, geography, era, mood, texture, instrumentation, production aesthetic, and listening function as distinct concept types. Do not flatten descriptors such as “lo-fi,” “gothic,” “psychedelic,” “ambient,” or “experimental” into genre labels without checking how they function in context.

## Proximity dimensions

Score or describe each candidate independently across the dimensions relevant to the ask:

| Dimension | Question | Useful evidence |
|---|---|---|
| Sonic | Does it resemble the source in audible form? | Timbre, rhythm, harmony, instrumentation, vocals, structure |
| Aesthetic/experiential | Does it produce a related felt experience? | Texture, atmosphere, intensity, spatial character, descriptors |
| Production | Are the recording and sound-design methods related? | Effects, sampling, distortion, mix space, arrangement |
| Genealogical | Is there a documented lineage or influence path? | Predecessors, derivatives, fusions, artist transitions |
| Cultural/scene | Do the styles share social or institutional context? | Places, labels, venues, musicians, publications, communities |
| Audience | Do meaningful listener populations overlap? | Collections, playlists, reviews, follows, session transitions |
| Functional | Does the music serve a similar listening use? | Dance, focus, contemplation, ritual, protest, exercise |
| Semantic | Are the styles discussed with related language? | Reviews, interviews, liner notes, biographies, tags |

Never present a composite score as objective truth. If scores are available, retain the component scores. If they are not measured, use qualitative labels such as `strong`, `moderate`, or `weak` and identify them as judgments.

## Cross-genre navigation logic

### 1. Establish the frontier

Extract:

- source anchors: artists, tracks, albums, genres, or descriptors;
- desired direction: heavier, stranger, more rhythmic, older, more global, less familiar, and so on;
- invariants: qualities that must remain recognizable;
- novelty tolerance and exclusions;
- requested destination, if any.

Define the frontier as the point where ordinary similarity stops being sufficient but at least one meaningful connection can still be explained.

### 2. Choose dimensions before candidates

Select two to four proximity dimensions that best express the request. Do not default to taxonomy alone.

Examples:

- “Same haze, less rock” → aesthetic + production + sonic.
- “Trace where this came from” → genealogy + scene + semantic.
- “Move me from listening to dancing” → functional + rhythmic + audience.
- “Bridge these two genres” → use the strongest dimensions on each side; they may differ.

### 3. Generate several route families

Consider at least three distinct routes before selecting results:

- **Adjacent step:** cross one boundary while preserving several source traits.
- **Bridge chain:** use one or two intermediates between source and destination.
- **Shared-property leap:** move farther taxonomically while preserving a strong texture, function, or production trait.
- **Lineage route:** follow predecessors, fusions, derivatives, or reinterpretations.
- **Scene route:** follow shared artists, labels, cities, venues, or audiences.

Do not force every ask to use every route family.

### 4. Evaluate directionality

Separate similarity from transition accessibility. A route can be easier in one direction than the other.

For each step, ask:

- What familiar property carries forward?
- What new property is introduced?
- Is the size of the jump appropriate for the listener's novelty tolerance?
- Would reversing the route create a harder transition?

### 5. Balance connection and novelty

Prefer candidates that are connected enough to explain and different enough to justify frontier exploration.

Use this conceptual rule:

```text
frontier_value = connection_to_anchor × novelty × route_coherence × evidence_quality
```

For bridge candidates:

```text
bridge_value = connection_to_source × connection_to_destination × novelty × explanation_quality
```

These are decision aids, not mandatory numeric formulas.

### 6. Diversify the final set

Avoid returning several candidates that represent the same move. Prefer a small set spanning different defensible routes, such as one sonic neighbor, one historical route, one shared-aesthetic leap, and one adventurous destination.

## Execution workflow

1. Confirm the activation gate is satisfied.
2. Read the request and available engine context without changing either.
3. Identify anchors, direction, invariants, exclusions, and novelty tolerance.
4. Choose the relevant proximity dimensions.
5. Generate a temporary candidate graph with typed relationships.
6. Develop multiple route families and inspect intermediate bridges.
7. Check candidates against the actual requested qualities, not genre labels alone.
8. Remove weakly supported, redundant, tokenistic, or merely surprising candidates.
9. Order the remaining routes from accessible to adventurous unless the user asks otherwise.
10. Explain each move using specific preserved and newly introduced properties.
11. Attach confidence and provenance to factual claims.
12. Emit an isolated `frontier_exploration` result and return control without persisting changes.

## Confidence and provenance

Keep source assertions separate rather than collapsing disagreements into one “correct” genre assignment.

For each material claim, track when available:

- subject and scope: artist, career period, album, track, or section;
- relationship or genre assertion;
- source and retrieval date;
- evidence type: catalog, criticism, audio analysis, listener behavior, or curator judgment;
- confidence in the claim;
- centrality: whether the item is canonical or peripheral to the genre;
- boundary status: `core`, `near-core`, `hybrid`, `boundary`, `influenced-by`, `adjacent`, or `disputed`.

Apply these rules:

- Distinguish measured evidence from inference and illustrative scoring.
- Do not invent numeric precision.
- Prefer multiple independent signals for non-obvious leaps.
- State disagreement when credible sources classify an item differently.
- Scope genre claims at the lowest useful level; do not flatten an artist's entire career.
- Lower confidence when evidence is sparse, culturally narrow, circular, or platform-generated.
- Treat catalog labels as evidence, not ground truth.

## Output expectations

Return a concise, listener-facing exploration. Adapt the number of routes to the ask; three to six is usually enough.

Use this structure:

```text
frontier_exploration

Anchor
- What the exploration starts from.

Frontier direction
- What remains constant and what is allowed to change.

Routes
1. Source → bridge → destination
   Why it connects: specific proximity dimensions.
   What changes: the novelty introduced.
   Entry point: artist, album, or track.
   Confidence: high / medium / low, with a short reason.

Most accessible next step
- One clear starting recommendation.

Most adventurous credible step
- One farther destination whose connection can still be explained.

Notes
- Disputed labels, provenance limitations, or asymmetric transitions if relevant.
```

If the ask requests a path, show the sequence. If it requests options, group them by route type. Do not bury the recommendations under ontology commentary.

## Guardrails

- Do not activate merely to make ordinary recommendations seem more creative.
- Do not equate geographic or cultural distance with musical novelty.
- Do not use Western commercial taxonomies as universal structure.
- Do not exoticize, tokenize, or decontextualize traditions to create surprise.
- Do not claim influence or lineage from sonic resemblance alone.
- Do not confuse listener co-occurrence with historical causation.
- Do not force hybrids into a single parent genre.
- Do not recommend a genre label without a concrete musical entry point when catalog data permits one.
- Do not let novelty overwhelm the user's stated invariants or exclusions.
- Do not create endless chains; every step must add explanatory value.
- Do not expose internal speculative scores as factual measurements.
- Do not write any frontier inference back into the current engine.

## Examples

### Example: open frontier from shoegaze

**Ask:** “I love shoegaze. Take me somewhere unfamiliar without losing the enveloping feeling.”

**Interpretation:** Preserve immersive texture and spatial production; allow rhythm, instrumentation, and genre lineage to change.

Possible routes:

1. `shoegaze → ambient rock → ambient`
   - Connection: enveloping space, sustained texture, blurred edges.
   - Change: less song structure and fewer rock rhythms.
2. `shoegaze → blackgaze → atmospheric black metal`
   - Connection: dense guitar layers and immersion.
   - Change: harsher vocals, greater intensity, metal lineage.
3. `shoegaze → dream pop → ethereal wave`
   - Connection: submerged vocals, atmosphere, shared audiences.
   - Change: less distortion and a more spectral, gothic palette.

Do not describe these paths as equally close on every dimension.

### Example: bridge two genres

**Ask:** “Build a path from dub to ambient techno.”

Possible path:

```text
dub → ambient dub → dub techno → ambient techno
```

Explain the handoffs through production lineage: spatial mixing, delay, bass emphasis, repetition, and progressively more electronic rhythmic structure. Note that this route is strong genealogically and productionally, not merely taxonomically.

### Example: shared-property leap

**Ask:** “I like the ritualistic repetition of minimal techno, but I want something outside electronic dance music.”

Explore through functional and experiential proximity rather than genre ancestry. Candidate territories might include minimalist composition, percussion-centered traditions, or drone-based music, but verify cultural context and choose concrete works whose repetition actually matches the request. Do not imply lineage without evidence.

### Example: non-trigger

**Ask:** “Give me five more dream-pop albums like this one.”

Do not run this skill. Return the request to the current recommendation engine because it asks for ordinary within-neighborhood similarity.

## Completion check

Before returning, verify:

- The ask passed the frontier activation gate.
- The current engine was treated as read-only and unchanged.
- The route uses named proximity dimensions.
- Every recommendation has a concrete connection to the anchor.
- Novelty is meaningful rather than arbitrary.
- Lineage, culture, sound, audience, and function were not conflated.
- Uncertain or disputed claims are labeled.
- The output is isolated as `frontier_exploration`.
- No exploration result or inferred preference was persisted.

