# Recommendation calibration learnings

Status: research record, not active runtime logic

This record turns the recommendation exercises into reusable evidence without
promoting external descriptors into the active project vocabulary or corpus.

## Files

- `recommendation-calibration-cases.csv` records every slate, including useful
  adjacent recommendations that did not satisfy the preferred discovery depth.
- `recommendation-descriptor-calibration.csv` records prediction performance and
  the principal correction for each curator-reviewed candidate.
- `recommendation-curator-profiles-by-axis.csv` preserves complete curator profiles
  across the external taxonomy's eight semantic axes.

## Value proposition tested

The system should surface overlooked music and unfamiliar listening paths through
typed, explainable connections. Genre and popularity are candidate attributes, not
the primary definition of similarity. Descriptors provide the connective tissue;
artist arc, cultural context, geography, era, and evidence provide additional
constraints and explanations.

## Independent controls

Discovery distance and visibility must not be collapsed into one number.

- Discovery tier describes conceptual distance from the seed.
- Visibility describes whether a candidate is canonical, overlooked, underground,
  or frontier material.
- A Tier 5 result is not valid merely because it is obscure.
- A Tier 2 result is not a failure. It is useful when the listener wants a safer or
  more adjacent path.

Working discovery ladder:

1. Same genre, scene, era, or canonical association.
2. Adjacent conversation with an obvious contextual or career-arc bridge.
3. Cross-genre connection with strong sonic or thematic overlap.
4. Cross-era, geography, tradition, or musical-form connection.
5. Surface-dissimilar candidate with high intent fidelity and an evidence-backed,
   intelligible bridge.

## Inference protocol

For each query:

1. Preserve the user's words as the raw North Star.
2. Translate the liked quality into separate controlled-taxonomy axes. Do not turn
   the full seed album profile into the request.
3. Mark the required bridge descriptors. These are eligibility constraints.
4. Generate candidates across more than one genre, era, scene, or tradition.
5. Score intent fidelity separately from discovery distance and visibility.
6. Treat artist arc as contextual metadata. It may strengthen an explanation but
   must not rescue a candidate that misses the requested quality.
7. Produce a complete inferred external-taxonomy profile, grouped by axis and
   labeled `llm_inferred` with confidence.
8. Keep facts, cover observations, inferred descriptors, and curator assignments
   separate. Cover art is weak corroboration only.
9. After curator feedback, preserve both prediction and reference. Measure exact
   controlled-term precision and recall and record axis-level gaps.
10. Explain both what the candidate preserves and what it transforms.

## Findings from the two recommendation rounds

### Metallica, Load, density

The revised slate clustered in the same 1990s career-pivot conversation. Bowie was
the strongest quality match because `dense` was curator-confirmed. U2 and R.E.M.
demonstrated that a persuasive discography analogy cannot replace the requested
descriptor. This slate is retained as Tier 2 evidence, not labeled a failure.

### Korn, Issues, despair and anxiety

The better slate decomposed the request into three bridge modes:

- Xiu Xiu preserved naked psychological despair and anxiety.
- Dalek preserved density, rhythmic pressure, and anxiety while translating private
  anguish into political and dystopian despair.
- Planning for Burial preserved depressive weight while translating agitation into
  lethargy, longing, loneliness, and self-hatred.

This created meaningful genre distance without losing the requested experience.

### Jane's Addiction, Jane's Addiction, complete underground environment

The clarification stage selected deep discovery and defined the request as a complete
social environment: bohemian community, intoxication or instability, a concealed
urban underside, and artifact-like proximity to the scene. This produced strong
cross-context candidates, but curator feedback exposed a crucial separation:

- Kollaps supported the environmental bridge and a highly specific mechanical,
  ritualistic, urban, and politically charged album profile.
- Expensive Shit supported the communal and oppositional bridge, while its album
  profile was more melodic, polyphonic, triumphant, and uplifting than the initial
  context-heavy inference suggested.
- Gulp! remained a plausible scene recommendation, but its concise curator profile
  did not support most of the contextual descriptors projected onto it.

An environment can qualify a recommendation when it is documented, but it does not
authorize corresponding album-level descriptors. Scene evidence and album evidence
must be scored and explained as different branches.

## Descriptor calibration findings

- Candidate discovery is currently stronger than complete descriptor assignment.
- Semantic near-synonyms are still errors in a controlled taxonomy. For example,
  `self-loathing` cannot replace `self-hatred`.
- Vocal identity requires factual care. `male-vocalist` was incorrect for Xiu Xiu;
  the curator reference uses `nonbinary-vocalist`.
- Broad labels conceal decisive specificity. `political` and `conscious` did not
  recover Dalek's antiracist, anticolonial, anti-authoritarian, socialist, and other
  ideological descriptors.
- Context must not be promoted automatically into an album descriptor. Evidence of
  isolation during creation did not authorize the descriptor `isolation` for
  Planning for Burial.
- The same boundary applies to scenes. A record may emerge from an underground,
  bohemian, drug-associated, or politically unstable environment without carrying
  every one of those ideas as an album descriptor.
- Axis coverage matters. Strong mood overlap can still omit vocals, lyrical mode,
  themes, or musical construction that define the album.
- Full profile completeness and recommendation relevance are separate evaluations.
  A recommendation can be good even when its inferred profile needs correction.

## Evaluation contract

Evaluate each candidate on independent measures:

- intent fidelity: support for the specific liked quality;
- evidence confidence: strength and provenance of supporting claims;
- discovery distance: conceptual distance from the seed;
- visibility: canonical to frontier status, when documented;
- bridge legibility: whether the connection can be stated using contributed evidence;
- descriptor precision and recall: exact controlled-term agreement after feedback;
- axis coverage: which semantic branches were recovered or missed;
- diversity contribution: whether the slate opens a distinct path.

No single measure should silently stand in for another. In particular, obscurity
does not prove distance, artist arc does not prove relevance, and persuasive prose
does not prove evidence.
