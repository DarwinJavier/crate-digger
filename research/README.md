# Research references

This directory keeps research inputs separate from the active corpus and serving
code. Material here may inform design and curation, but it is not recommendation
evidence unless it is explicitly reviewed, provenance-labeled, and promoted into
the appropriate source-of-truth CSV.

## Layout

- `papers/`: source PDFs and text extracted from them for local analysis.
- `mir/`: secure Music Information Retrieval web ingestion, including inert raw
  HTML, sanitized text, derived summaries, provenance manifests, and tests.
- `taxonomies/`: external descriptor taxonomies and analysis. These do not replace
  `data/vocab.csv`.
- `taxonomies/recommendation-calibration-*.csv` and
  `taxonomies/recommendation-calibration-learnings.md`: recommendation-game cases,
  curator profiles by semantic axis, and accumulated inference corrections.
- `taxonomies/archive/`: original supplied archives retained for provenance.

## Boundaries

- `data/vocab.csv` remains the approved recommendation vocabulary.
- External taxonomy identifiers must not enter API scoring without a reviewed
  crosswalk and explicit human approval.
- Raw or automatically extracted research remains reference material.
- Album assignments require source, confidence, and evidence outside the taxonomy
  definition itself.

## Version-control policy

The repository tracks the research tooling, documentation, tests, synthesis, and
curated taxonomy and calibration files. It does not currently track these local
research artifacts:

- source-paper PDFs and their extracted text;
- raw quarantined or sanitized MIR downloads;
- generated MIR outputs and operational logs;
- original taxonomy archive bundles.

These artifacts are not runtime dependencies. The active application is rebuilt
from the CSV sources in `data/`, while reviewed research conclusions live in
`brain/research-synthesis.md` and `brain/recommendation-logic.md`.

The excluded artifacts should be retained locally when useful for provenance. If
the project later needs to publish or archive them, first review their licensing,
redistribution rights, size, and provenance. Then remove the relevant narrow rule
from `.gitignore` and add only the reviewed files. Do not force-add the entire
research directory.
