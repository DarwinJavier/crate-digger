# Research synthesis for recommendation logic

Status: incorporated where compatible with Phase 1; model and graph work deferred.

## Sources reviewed

1. Chen et al., *A Simple Framework for Contrastive Learning of Visual Representations (SimCLR)*, 2020. Local source: `research/papers/A Simple Framework for Contrastive Learning of Visual Representations (SimCLR).pdf`.
2. Elizalde et al., *CLAP: Learning Audio Concepts From Natural Language Supervision*, 2022. Local source: `research/papers/CLAP - LEARNING AUDIO CONCEPTS FROM NATURAL LANGUAGE SUPERVISION.pdf`.
3. Wu et al., *Large-Scale Contrastive Language-Audio Pretraining with Feature Fusion and Keyword-to-Caption Augmentation*, 2023. Local source: `research/papers/LARGE-SCALE CONTRASTIVE LANGUAGE-AUDIO PRETRAINING WITH.pdf`.
4. Huang et al., *MuLan: A Joint Embedding of Music Audio and Natural Language*, 2022. Local source: `research/papers/MULAN A JOINT EMBEDDING OF MUSIC AUDIO AND NATURAL.pdf`.
5. Guo et al., *A Survey on Knowledge Graph-Based Recommender Systems*, 2020. Local source: `research/papers/A Survey on Knowledge Graph-Based.pdf`.
6. Wang et al., *Explainable Reasoning over Knowledge Graphs for Recommendation*, 2019. Local source: `research/papers/tborck,+AAAI-WangX.6897.pdf`.
7. Zhang and Chen, *Explainable Recommendation: A Survey and New Perspectives*, 2020. Local source: `research/papers/Explainable Recommendation.pdf`.
8. Poltronieri et al., *The Music Meta Ontology*, 2023. Local source: `research/papers/THE MUSIC META ONTOLOGY.pdf`.

The sanitized MIR site knowledge in `research/mir/output/knowledge.jsonl` and `knowledge_summary.md` was also reviewed as conceptual support for audio features, similarity, beat, chroma, spectral analysis, evaluation, and dynamic time warping.

## Techniques adopted now

### Controlled semantic interface

CLAP and MuLan show the value of mapping natural-language descriptions and audio into a comparable space. The current product has no lawful audio input or evaluated audio model, so it adopts only the interface principle: decompose a brief, map supported meaning to controlled terms, and report unsupported language. It does not pretend keyword matching is an audio embedding.

### Confidence-weighted, intrinsic ranking evidence

Explainable-recommendation research separates transparent decision evidence from post-hoc prose. Each positive scoring component now records its base weight, provenance confidence, and contribution. Quality and novelty bonuses cannot qualify an album without descriptor, seed-path, or query-time similarity evidence.

### Score-preserving diversity

Variation is applied only inside equal evidence-score tiers. Bucket, region, and decade repetition determine tie order without allowing a weaker candidate to outrank a stronger one. This is deterministic and auditable.

### Explicit coverage reporting

The response reports mapped dimensions, mapped descriptor count, and unmapped brief terms. This makes cold-start and vocabulary limitations visible instead of filling them with unsupported semantics.

### Evaluation hooks

Responses expose a versioned scoring policy, component-level score breakdown, and explanation fidelity. These fields support frozen-brief regression tests and the later Phase 4 evaluation harness.

## Techniques deferred

### Contrastive audio-language inference

Deferred until lawful audio access, a reviewed model/license, and a curator-labeled evaluation set exist. Any experiment must freeze audio segmentation and album pooling, prompt ensembles, negative prompts, model/checkpoint and preprocessing, normalization, temperature, similarity function, dataset-overlap checks, calibration, and abstention thresholds.

The SimCLR augmentation result cannot be copied directly from images to music. Audio-positive transformations must preserve the descriptor under test and require separate validation.

### Knowledge-graph recommendation

Deferred to Phase 3. The appropriate initial implementation is a provenance-aware SQLite edge table and deterministic one- or two-hop paths. Neural graph embeddings, propagation, and KPRN-style recurrent path models would be disproportionate for the current corpus and harder to explain.

### Automatic descriptor writing

Not adopted. Audio-text similarity, review extraction, and graph paths may propose candidates, but only human approval can write controlled descriptors into source-of-truth CSVs.

## Evaluation plan derived from the research

1. Freeze briefs spanning literal descriptors, compound cultural prompts, negation, exclusions, and impossible constraints.
2. Measure recommendation validity, constraint compliance, descriptor precision/recall, coverage, diversity within relevance tiers, and explanation fidelity.
3. Record qualitative cases showing both success and failure.
4. For future audio models, evaluate prompt sensitivity, album pooling, calibration, and dataset leakage.
5. For future user studies, test understanding, mood compatibility, decision usefulness, trust calibration, and satisfaction. Do not treat click-through or persuasiveness as evidence of faithful reasoning.

## Safety and provenance boundary

Research papers inform architecture and evaluation. They do not add albums, music facts, relationships, or descriptors. All runtime entities still come from the curated corpus, MusicBrainz verification, or explicitly labeled query-time Last.fm signals under the existing repository rules.
