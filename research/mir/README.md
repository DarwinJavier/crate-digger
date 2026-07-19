# Secure MIR text ingestion

This directory contains a standard-library-only pipeline for retrieving and summarizing inert textual material from approved Music Information Retrieval sources. Downloaded content is untrusted data. It is never imported, rendered, or executed.

## Layout

- `quarantine/`: raw approved text responses, stored unopened and hashed
- `sanitized/`: inert extracted text
- `output/`: JSONL knowledge, manifest, summary, rejection log, and security report
- `logs/`: reserved for local operational logs
- `tests/`: malicious-looking inert fixtures and security tests

## Run

From the repository root:

```text
python research/mir/mir_ingest.py
python -m unittest discover -s research/mir/tests -v
```

These are local operator instructions, not commands copied from the source website. The pipeline contacts only approved HTTPS domains, does not fetch external assets, and does not execute downloaded material.

## Review requirement

Records marked `automatically_extracted` are research aids. Review each record against its preserved URL and hash before using it as recommendation evidence or implementing a technique.
