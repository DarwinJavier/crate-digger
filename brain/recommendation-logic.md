# Recommendation Logic: Systematic Review and Operating Policy

Status: active design policy

Purpose: preserve what the recommendation pressure tests taught us, separate what
the current product can safely do from what still needs to be built, and give the
runtime a compact set of rules for interpreting briefs and explaining results.

## 1. What we learned

### The corpus is a trust layer, not a catalogue of all music

The local corpus does not need every record ever released. It needs a deliberately
curated set of anchors with strong descriptors and provenance. It can answer from
that foundation honestly and identify coverage gaps. It cannot discover an unknown
album merely because a user supplies a mood.

Live discovery is therefore a separate future workflow:

1. Interpret the brief using controlled concepts.
2. Generate a broad external candidate pool from permitted discovery sources.
3. Resolve candidate identity and factual metadata.
4. collect claim-level evidence from independent sources.
5. Score only candidates that pass an evidence threshold.
6. Put new candidates through human review before they enter the curated corpus.

An externally researched candidate is not curator-approved. The product must label
that distinction and must not write live research directly to `descriptors.csv`.

### MusicBrainz verifies identity; it does not understand mood

MusicBrainz is useful for canonical artists, release groups, dates, countries, and
structured relationships when those relationships are present. It is not a mood
search engine and should not generate recommendations by itself.

Use its API, not site crawling. Calls must be sequential, at most one request per
second, with a descriptive User-Agent and contact. Cache stored CC0 facts and avoid
query-time polling where a local resolution result is available.

### Evidence sources have different jobs

Source selection is claim-specific:

| Source | Appropriate use | Important limit |
|---|---|---|
| Human curator | Approved descriptors and relationships | Must use controlled vocabulary |
| MusicBrainz | Identity, release facts, structured credits | Sparse for mood and cultural interpretation |
| Artist, label, or Bandcamp page | Release facts and first-party descriptions | Promotional language is not independent validation |
| Interviews | Direct statements about intent and influences | Attribute the statement to the speaker |
| Liner notes and personnel credits | Producers, players, studios, recording details | Prefer primary credits over copied databases |
| Critic reviews | Independent descriptions of sound, mood, and context | Store a paraphrased claim and citation, not review text |
| NTS programming and specialist radio | Scene relevance and discovery paths | Inclusion alone does not prove a descriptor |
| Wikipedia | Discovery of references and cautious factual orientation | Follow and assess the underlying citation |
| Listener reviews | Candidate generation or weak corroboration | Low confidence and never sole support |
| Cover art | Observable visual properties | Never infer sonic mood from artwork alone |
| Lyrics | Themes when rights and access permit analysis | Do not store or reproduce lyrics |

Discogs, Spotify, Apple Music, and Rate Your Music are not automated data sources
for this repository. Product links are not evidence.

### Evidence must remain atomic and attributable

Every researched claim should eventually have:

- subject, predicate, and object;
- source URL, title, publisher, and retrieval date;
- evidence scope: album, track, artist, release, or scene;
- provenance type and confidence;
- review status: candidate, approved, or rejected.

Facts, curator judgments, model similarities, and externally researched claims must
not be blended into one unlabeled score or prose assertion.

### Audio embeddings are evidence, not facts

Models such as CLAP, MuLan, OpenL3, MusicFM, MERT, and Jukebox-style embeddings map
audio to vectors. A vector can support similarity or a trained descriptor score,
but its dimensions are not automatically named concepts such as tempo or mood.

For long recordings, compute track or section embeddings before album aggregation.
Compare vectors through validated probes or audio-language similarity. Store the
result as model-derived evidence with model/version metadata and confidence, never
as a documented fact. Generated embedding indexes remain disposable build artifacts.

The contrastive-learning papers sharpen this into an evaluation policy:

- Audio and text require separate encoders projected into a shared normalized space.
- Similarity is a model score, commonly cosine similarity, not a semantic fact.
- Prompt wording materially affects zero-shot results, so a future experiment must use
  a frozen prompt ensemble rather than one convenient descriptor phrase.
- Long and variable-duration audio requires an explicit segmentation and pooling policy.
- Positive-pair construction, negative sampling, temperature, projection heads, dataset
  overlap, and noisy annotations are experimental variables that must be recorded.
- A model may enter ranking only after evaluation against curator-approved labels, with
  retrieval and classification metrics reported separately.

### Extraction should be parallel; judgment should be constrained

Metadata, reviews, audio, and cover art are independent evidence channels. They
should not form a chain in which one agent's unsupported conclusion becomes the
next agent's premise. A provenance-aware evidence store should feed a deterministic
scorer restricted to the approved vocabulary. The LLM may map a brief to that
vocabulary and compose prose over retrieved evidence only.

### Broad prompts need decomposition

A phrase such as `Y2K clubbing` mixes dimensions:

- era: approximately the turn of the millennium;
- listening context: club-oriented;
- energy: kinetic, euphoric, charged, or tense;
- sonic character: digital, synthetic, bass-forward, or glossy;
- possible scenes or genres.

These dimensions should remain separate. Only dimensions represented in the active
controlled vocabulary can affect current retrieval. Unrepresented concepts should
be reported as coverage gaps, not silently replaced with invented tags.

Likewise, a mood is rarely one sound. `Nocturnal` can be kinetic, haunted, sensual,
communal, or contemplative. `Frenetic` can mean fast, rhythmically dense, nervous,
abrupt, chaotic, intricate, or physically propulsive. Subtypes improve candidate
diversity, but only approved vocabulary terms may enter ranking.

### Variation must be controlled

Repeated prompts should not always return the identical slate, but randomness must
never rescue a weak match. The future ranking design should:

1. retrieve a qualified pool larger than the requested result count;
2. remove or penalize recently returned albums;
3. apply a hard evidence threshold;
4. group candidates by meaningful descriptor subtype;
5. enforce artist, era, geography, scene, and discovery-path diversity where data
   supports those dimensions;
6. sample or rotate only within a strong relevance tier;
7. accept a stable request or session seed so a result can be reproduced.

Conceptually, ranking combines relevance, evidence confidence, novelty, diversity
contribution, and a bounded rotation factor. Exact weights require an evaluation
harness and must not be selected by the LLM.

### Discovery distance and visibility are independent

Recommendation calibration showed that novelty cannot be represented by one slider.
Discovery distance describes how far the conceptual bridge travels; visibility
describes whether the destination is canonical, overlooked, underground, or frontier
material. A highly obscure same-scene record can still be adjacent, while a familiar
record can form a distant cross-context bridge.

Artist-arc similarity is contextual evidence, not automatic relevance. It may explain
why two records occupy comparable career moments, but it cannot qualify a candidate
that misses the user's requested quality. The raw liked quality remains the North
Star and should become an explicit eligibility constraint before distance, visibility,
or diversity reorders candidates.

External-taxonomy experiments must compare assignments by semantic axis. Mood,
atmosphere, style, theme, lyrics, vocals, form, and technique are not interchangeable.
Complete profile accuracy and recommendation quality are evaluated separately.

### Visual prompts require explicit perceptual controls

Before interpreting an image semantically, record observable palette temperature,
brightness, saturation, contrast, spatial openness, depth, density, texture, geometry,
human arrangement, and motion cues. These observations define visual constraints but
do not prove musical descriptors.

Ask the user to choose among materially different semantic readings. Then state which
visual properties each recommendation preserves, transforms, or deliberately opposes.
Unless contrast is requested, at least one candidate should preserve the dominant
palette and spatial quality. A cold, nocturnal, or claustrophobic candidate may follow
a bright, warm, open image when it serves a declared narrative role such as aftermath.

The local SimCLR research supports keeping appearance and spatial information
available and testing robustness across altered views. It does not authorize direct
image-to-music semantics or make visual similarity recommendation evidence.

For visual prompts without a seed genre, apply discovery distance between candidates
as well as between each candidate and the interpreted image. An exploratory slate
should normally span distinct musical ecosystems. Three individually persuasive
bridges do not satisfy exploration when they cluster around the same genre lineage,
production vocabulary, audience, or cultural conversation.

### Explanations must be faithful to ranking

An explanation may mention only evidence that actually contributed to the result.
The response should distinguish:

- documented fact;
- curator-approved descriptor;
- query-time third-party signal;
- model-derived similarity;
- externally researched, not-yet-approved candidate.

Prefer a concise reason with expandable evidence. The prose layer may reorganize or
summarize supplied claims, but cannot add albums, comparisons, relationships, or
music facts.

Research on explainable recommendation distinguishes intrinsic explanations from
post-hoc rationalizations. Crate-digger uses the intrinsic approach: every positive
ranking component is returned with its weight, confidence, and provenance. Novelty
and corpus-quality signals may reorder relevant candidates but cannot create relevance.
Explanation fidelity is therefore testable as the share of positive ranking weight
represented by returned evidence.

Evaluation must cover both recommendation quality and explanation quality. Initial
offline measures are constraint compliance, evidence coverage, explanation fidelity,
descriptor precision/recall on frozen briefs, and qualitative failure cases. User
studies should later test whether explanations help listeners understand the result,
judge mood compatibility, and make a listening decision. Persuasiveness alone is not
proof of faithfulness.

### Knowledge graphs are typed claim paths, not inferred associations

The knowledge-graph research supports explicit subject-predicate-object claims and
path-based reasons. The Music Meta Ontology adds two requirements useful here:
modular schemas and claim-level provenance. A future graph path may connect a seed to
a candidate through a verified producer, label, scene, or performer, but every edge
must be individually sourced. Shared attributes do not automatically prove influence.

The current phase does not implement graph propagation, learned graph embeddings, or
multi-hop neural path scoring. Those require Phase 3 authorization, verified edges,
and evaluation. SQLite edge tables remain the preferred one-person-simple design.

## 2. Recommended architecture

The target architecture is:

```text
User brief
  -> controlled intent mapper
  -> corpus retrieval and, later, a separately labeled live candidate scout
  -> independent metadata, text, audio, and visual evidence extractors
  -> provenance-aware evidence store
  -> deterministic controlled-vocabulary scorer
  -> diversity and rotation selector
  -> faithful explanation composer
  -> candidate review queue for anything outside the curated corpus
```

The current application implements corpus retrieval, constrained intent mapping,
deterministic scoring, limited artist diversity, and faithful explanation. Live
scouting, claim storage, embedding signals, rotation history, and candidate review
are future features and must pass the relevant phase gate before implementation.

## 3. Runtime policy

The application reads the marked block below into its LLM prompts. Keep it compact,
operational, and consistent with `AGENTS.md`.

<!-- RUNTIME_POLICY_START -->
- Treat a broad music brief as separate mood, sonic, scene, era, context, and energy dimensions before mapping it.
- Return only terms present in the supplied controlled vocabulary. Never create a near-synonym just to fill a slot.
- Use fewer terms when evidence is ambiguous. An empty dimension is more honest than a fabricated match.
- Do not treat a cultural phrase such as Y2K clubbing as one mood. Map only its supported dimensions and leave unavailable dimensions unrepresented.
- A descriptor may have multiple subtypes. Select terms that preserve the user's particular meaning instead of collapsing everything to the broadest mood.
- In explanations, mention only the supplied albums and evidence claims. Do not add facts, influences, genres, comparisons, or relationships.
- Keep provenance distinctions intact. A curator tag, MusicBrainz fact, Last.fm signal, and model inference are not interchangeable.
- Randomness may vary equally qualified results, but it must never create relevance or evidence.
- Report mapped dimensions and unsupported brief language; do not hide vocabulary coverage gaps.
- Every positive ranking contribution must appear in structured evidence with its weight, provenance, and confidence.
- Corpus quality and novelty may reorder relevant candidates, but neither may qualify an otherwise irrelevant album.
- Diversify only within equally scored evidence tiers so variety cannot outrank stronger support.
- Interpret the request before searching. Ask one request-specific question about what must survive, then keep genre distance and artist visibility as independent controls.
- For reference-free situational, functional, visual, or emotional requests with several plausible musical readings, use two calibration stages. Ask only for a musical orientation first. After selection, generate the interpretation question inside that musical world, followed by genre distance and artist visibility. Offer three contrasting sonic directions, an open path, and a listener-supplied alternative. Any displayed exemplar must be identity-verified and remains orientation context, never seed inventory or an automatic recommendation.
- Genre distance controls movement across genres only. It does not stand for geography, obscurity, scene distance, or cache status.
- The curated corpus is calibration evidence, never reserved recommendation inventory. Curated and query-time candidates receive no source quota; every displayed album must win on the calibrated bridge.
- Listener mode disables corpus candidates entirely. Corpus retrieval remains available only as an explicit calibration/evaluation control; discovery failure never triggers a corpus substitution.
- Artist visibility is a slate requirement. `underheard` excludes familiar artists; `mixed` includes at least one underheard and one recognizable artist whenever evidence-backed candidates of both kinds survive verification.
- Use separate interpretation, candidate generation, research, identity verification, and comparative selection passes. Structured schemas validate handoffs but do not replace comparative reasoning.
- Treat proposed outside albums as provisional. Research the defining calibrated bridge first, reject unsupported candidates, and resolve only the shortlist through MusicBrainz.
- MusicBrainz cache presence is a performance detail and must never contribute to relevance. Prefer unseen records when evidence is comparable, but allow a returning album when it has a substantially different or uniquely strong role.
- Record labels and music scenes are journey-level exploration routes. Do not present them as album metadata unless the specific relationship is independently supported.
<!-- RUNTIME_POLICY_END -->

## 4. Implementation priorities

1. Add intent coverage reporting so unmapped dimensions are visible to the user.
2. Add deterministic, seeded rotation over a sufficiently large qualified corpus
   pool, plus recent-result avoidance.
3. Add structured evidence and candidate-review schemas before any live scout.
4. Evaluate retrieval quality and variation with frozen briefs including nocturnal,
   frenetic, and Y2K clubbing.
5. Only then consider external discovery connectors and model-derived audio evidence.

These are priorities, not authorization to skip the phase protocol in `plan.md`.
