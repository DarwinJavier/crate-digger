# Visual prompt assessment for music discovery

Status: research protocol, not active runtime logic

## Purpose

Images can define a listening intent, a narrative journey, or a contrast operation.
They do not provide evidence that a candidate album has particular musical
descriptors. Visual observations, semantic interpretation, album evidence, and
curator assignments remain separate.

## Research basis

Chen et al.'s SimCLR paper shows that useful visual representations depend strongly
on the composition of spatial and appearance transformations. Cropping changes the
available local and global structure; color distortion changes brightness, contrast,
saturation, and hue. The paper also shows that a contrastive objective can discard
transformation-specific information in its projection space even when an earlier
representation retains it.

This project does not infer that SimCLR embeddings contain musical meaning. The
practical lesson is narrower: do not let one obvious property, such as palette, act
as a shortcut for the whole image, and do not discard color or spatial information
before the downstream recommendation intent is known.

Local source: `research/papers/A Simple Framework for Contrastive Learning of Visual
Representations (SimCLR).pdf`.

## Three-layer assessment

### 1. Observable visual structure

Record observations without emotional interpretation:

- palette: warm, cool, neutral, mixed;
- brightness: bright, midtone, dark;
- saturation and contrast;
- spatial openness: expansive, bounded, enclosed, claustrophobic;
- depth: flat, layered, deep-perspective;
- density: empty, sparse, populated, crowded;
- texture: clean, grainy, weathered, glossy, organic, mechanical;
- geometry: soft, angular, symmetrical, fragmented;
- light source and time-of-day cues;
- human scale, arrangement, gaze, and visible motion.

These are image observations, not music descriptors.

### 2. Semantic interpretations

Generate multiple plausible readings, such as ritual, belonging, threat, solitude,
celebration, memory, or displacement. Ask an adaptive question when different
readings would materially change the candidates.

Do not assume that a crowd means celebration, darkness means sadness, warm color
means happy music, or open space means calm. The user selects or corrects the
interpretation.

### 3. Musical journey contract

After clarification, state which visual properties each candidate:

- preserves;
- transforms;
- deliberately opposes;
- uses only as a sequencing role.

At least one recommendation should preserve the dominant palette and spatial quality
unless the user explicitly requests contrast. A contrasting recommendation remains
valid when its role is declared, as Burial's cold nocturnal aftermath deliberately
inverted the bright open public space in visual round 2.

## Manual robustness checks

Before candidate generation, test the interpretation mentally against altered views:

- Grayscale check: would the interpretation survive without color?
- Crop check: does it depend on one object or on the whole composition?
- Global-local check: do the crowd and the individual details tell different stories?
- Brightness check: is darkness being inferred from subject matter despite bright light?
- Space check: is an open image being translated into claustrophobic music without an
  explicit narrative reason?

These checks are inspired by the importance of augmentation choice in visual
representation learning. They are not claims that manual inspection reproduces a
trained contrastive model.

## Evaluation

Evaluate visual rounds on independent measures:

- exact external-taxonomy descriptor agreement;
- visual-role fulfillment;
- palette preservation or declared transformation;
- spatial preservation or declared transformation;
- narrative coherence across the slate;
- discovery-tier compliance;
- evidence separation between image interpretation and album facts.

Also evaluate pairwise slate diversity. A set can contain three individually valid
visual bridges while remaining insufficiently exploratory because the candidates
share genre lineage, production vocabulary, audience, era, or discovery ecosystem.

For an exploratory three-album slate, target three distinguishable musical ecosystems
and allow no more than one strong proximity overlap between any pair. Cross-genre
means diversity among the recommendations, not merely the absence of a seed genre.
