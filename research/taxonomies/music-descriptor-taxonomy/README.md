# Music descriptor taxonomy

Integration-ready hierarchy extracted from `TAXONOMY.docx`.

## Recommended use

- Use `id` as the stable database/API key and `name` for display.
- Use `parent_id` and `child_ids` for navigation and faceted filtering.
- Use `root_dimension` to keep the eight semantic axes distinct.
- Embed `name + definition` for semantic retrieval; retain hierarchy as metadata.
- Put curated cross-axis connections in `related_ids`; do not overload `parent_id`.
- Store evidence and confidence on each album/track assignment outside the taxonomy.

## Assignment model

```json
{
  "entity_id": "musicbrainz-recording-id",
  "descriptor_id": "hazy",
  "confidence": 0.86,
  "source": "editorial-text|audio-model|human",
  "evidence": "short explanation",
  "scope": "track|release|artist"
}
```

## Contents

- `music-descriptor-taxonomy.json`: 477 nodes, hierarchy, definitions, reverse child index, and source-validation findings.
- `music-descriptor-taxonomy.schema.json`: JSON Schema for structural validation.
- `README.md`: integration guidance and assignment contract.

## Data-quality policy

Labels and definitions are preserved from the source except for whitespace normalization. Missing definitions and declared-child-count mismatches are surfaced in `validation_issues`, not silently invented or corrected.
