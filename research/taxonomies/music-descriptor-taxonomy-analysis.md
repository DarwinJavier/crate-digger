# Music descriptor taxonomy analysis

## Summary

The supplied package is a coherent external taxonomy rather than an unstructured
tag list. It contains 477 unique nodes arranged under eight semantic dimensions:
atmosphere, form, lyrics, mood, style, technique, theme, and vocals.

The hierarchy contains 8 tier-1 roots, 269 tier-2 nodes, 168 tier-3 nodes, and 32
tier-4 nodes. Parent and child references are structurally complete. The package
also includes stable slug identifiers, display names, definitions, descendant
counts, source paragraph references, and reserved alias and related-term fields.

## Relationship to the album worklist

After lowercase and hyphen normalization, 260 of the 262 unique free-form terms in
the supplied album worklist resolve to taxonomy node identifiers. Those matches
cover 4,419 of 4,421 descriptor assignments. The only unmatched source values are
`warbly` and `sleepv`; the latter appears likely to require curator review, but is
not corrected here.

Matched assignments by root dimension:

| Dimension | Assignments |
|---|---:|
| Atmosphere | 1,235 |
| Mood | 1,062 |
| Style | 957 |
| Theme | 620 |
| Vocals | 254 |
| Lyrics | 238 |
| Technique | 38 |
| Form | 15 |

This explains why descriptor ordering matters. Each album has a ranked sequence
drawn from a known hierarchy, not merely a bag of unrelated prose labels.

## Relationship to the active vocabulary

The active `data/vocab.csv` contains 60 approved terms. Eleven identifiers overlap
the external taxonomy exactly. Most native terms are deliberately more specific to
this corpus, particularly production traits and scenes. The external taxonomy has
no equivalent for the project's historically grounded scene vocabulary.

The systems should remain separate:

- The active vocabulary is compact, curator-approved, and directly scoreable.
- The external taxonomy provides broad coverage, hierarchy, query expansion, and
  ordered source descriptors.
- A reviewed crosswalk can connect them without treating similar words as exact
  synonyms.

## Recommended integration model

Preserve external album assignments in a separate future table or source file with:

- album identity;
- taxonomy ID and taxonomy version;
- original rank and source term;
- assignment source and evidence;
- confidence;
- review state;
- optional approved active-vocabulary mapping.

Do not copy all 477 nodes into `data/vocab.csv`. Instead, create an explicit
crosswalk whose relationship is one of `exact`, `narrower`, `broader`, or `related`.
Every crosswalk row should be human-approved.

Descriptor position should be preserved as evidence. A reasonable hypothesis for
evaluation is ranks 1-3 as primary, 4-7 as supporting, 8-10 as complementary, and
later ranks as retrieval-only context. These boundaries and weights are not active
policy until tested against contrast albums and frozen recommendation briefs.

Suggested use by dimension:

- atmosphere and mood: candidate retrieval and controlled-mood mapping;
- style: broad retrieval context, not a substitute for verified scenes;
- technique and form: supplemental sonic or structural evidence;
- vocals: filters and explanation details;
- lyrics and theme: thematic filters or explanations, not assumed sonic similarity.

Contrast albums should be held in a separate evaluation or boundary set so they can
test exclusions and oppositions without becoming ordinary recommendation candidates.

## Package quality findings

The package reports 17 source-validation issues. Eight nodes lack source definitions,
and nine declared child counts disagree with the extracted hierarchy. These issues
are surfaced rather than silently repaired. The `aliases` and `related_ids` fields
are currently empty, so synonym expansion and cross-axis relations require later
curation.

No application scoring behavior has been changed as part of this analysis.
