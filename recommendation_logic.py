"""Pure deterministic recommendation-intelligence helpers with no service dependencies."""

import csv
import json
import re
from pathlib import Path


SCORING_POLICY_VERSION = "recommendation-intelligence-v2"
EXTERNAL_AXES = ("atmosphere", "form", "lyrics", "mood", "style", "technique", "theme", "vocals")
CONFIDENCE_THRESHOLDS = {"core": 0.85, "probable": 0.60, "possible": 0.30}
SCORING_WEIGHTS = {
    "descriptor_match": 2.0,
    "label_catalog_match": 1.25,
    "seed_bucket": 1.5,
    "fan_overlap": 1.0,
    "deep_cut": 1.0,
    "core_evidence": 0.5,
    "obvious_novelty_penalty": -0.5,
}
BRIEF_STOPWORDS = {
    "a", "an", "and", "for", "from", "i", "in", "is", "it", "me", "music",
    "of", "on", "or", "please", "some", "that", "the", "this", "to", "want", "with",
}


def find_unmapped_terms(text: str, intent: dict) -> list[str]:
    recognized_words = {
        word for key in ("moods", "sonic_traits", "scenes")
        for slug in intent.get(key, []) for word in slug.replace("-", " ").split()
    }
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return sorted({
        token for token in tokens
        if len(token) > 2 and token not in BRIEF_STOPWORDS and token not in recognized_words
    })[:12]


def intent_coverage(intent: dict) -> dict:
    mapped = {
        "mood": intent.get("moods", []),
        "sonic_trait": intent.get("sonic_traits", []),
        "scene": intent.get("scenes", []),
    }
    mapped_dimensions = [name for name, values in mapped.items() if values]
    unmapped = intent.get("unmapped_terms", [])
    if not mapped_dimensions:
        status = "unmapped" if unmapped else "empty"
    elif unmapped:
        status = "partial"
    else:
        status = "mapped"
    return {
        "status": status,
        "mapped_dimensions": mapped_dimensions,
        "mapped_descriptor_count": sum(len(values) for values in mapped.values()),
        "unmapped_terms": unmapped,
    }


def score_component(feature: str, confidence: float, detail: str) -> dict:
    base_weight = SCORING_WEIGHTS[feature]
    contribution = base_weight * confidence if base_weight > 0 else base_weight
    return {
        "feature": feature,
        "detail": detail,
        "base_weight": base_weight,
        "confidence": confidence,
        "contribution": round(contribution, 3),
    }


def confidence_state(confidence: float) -> str:
    """Return a stable three-level evidence state for a numeric confidence."""
    value = max(0.0, min(1.0, float(confidence)))
    if value >= CONFIDENCE_THRESHOLDS["core"]:
        return "core"
    if value >= CONFIDENCE_THRESHOLDS["probable"]:
        return "probable"
    return "possible"


def load_external_taxonomy(path: Path) -> dict:
    """Load and structurally validate the external descriptor taxonomy."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = payload.get("nodes", [])
    by_id = {node["id"]: node for node in nodes}
    if len(by_id) != 477:
        raise ValueError(f"Expected 477 external descriptors, found {len(by_id)}")
    unknown_axes = {node.get("root_dimension") for node in nodes} - set(EXTERNAL_AXES)
    if unknown_axes:
        raise ValueError(f"Unknown external taxonomy axes: {sorted(unknown_axes)}")
    return {"metadata": payload, "by_id": by_id}


def load_approved_crosswalk(path: Path, project_vocab: dict[str, set[str]], external: dict) -> dict:
    """Load only explicit approved mappings and reject unknown identifiers."""
    mappings: dict[str, list[dict]] = {}
    if not path.exists():
        return mappings
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("approved", "").strip().lower() != "yes":
                continue
            kind, slug, external_id = row["project_kind"], row["project_slug"], row["external_id"]
            if slug not in project_vocab.get(kind, set()):
                raise ValueError(f"Crosswalk references unknown project descriptor: {kind}/{slug}")
            if external_id not in external["by_id"]:
                raise ValueError(f"Crosswalk references unknown external descriptor: {external_id}")
            mappings.setdefault(external_id, []).append({
                "kind": kind, "slug": slug, "relationship": row.get("relationship", "related")
            })
    return mappings


def infer_external_axes(text: str, external: dict, limit_per_axis: int = 5) -> dict[str, list[dict]]:
    """Deterministically retrieve definition-backed external terms axis by axis."""
    words = set(re.findall(r"[a-z0-9]+", text.casefold())) - BRIEF_STOPWORDS
    output = {axis: [] for axis in EXTERNAL_AXES}
    if not words:
        return output
    for node in external["by_id"].values():
        if node.get("tier") == 1:
            continue
        haystack = " ".join([node.get("name") or "", node.get("definition") or ""])
        node_words = set(re.findall(r"[a-z0-9]+", haystack.casefold())) - BRIEF_STOPWORDS
        overlap = words & node_words
        exact = node["id"].replace("-", " ") in text.casefold()
        # A single shared definition word is too weak to infer a descriptor. It
        # previously mapped comparison grammar such as "as" onto unrelated terms.
        if not exact and len(overlap) < 2:
            continue
        confidence = min(0.95, 0.45 + 0.12 * len(overlap) + (0.25 if exact else 0.0))
        output[node["root_dimension"]].append({
            "descriptor_id": node["id"],
            "name": node["name"],
            "definition": node.get("definition"),
            "confidence": round(confidence, 3),
            "confidence_state": confidence_state(confidence),
            "source": "llm_inferred" if not exact else "curator",
            "evidence": "exact brief term" if exact else f"definition overlap: {', '.join(sorted(overlap))}",
        })
    for axis in output:
        output[axis].sort(key=lambda item: (-item["confidence"], item["descriptor_id"]))
        output[axis] = output[axis][:limit_per_axis]
    return output


def tuning_questions(brief: str, has_image: bool, depth: int | None,
                     visibility: str | None, include_interpretation: bool = True) -> list[dict]:
    """Fallback interpretation plus independent genre-distance and visibility controls."""
    questions = []
    if include_interpretation:
        questions.append({
            "id": "interpretation_focus",
            "question": "Which part of the request should survive?",
            "help": "This establishes the essential thread before the engine considers genres.",
            "options": [
                {"value": "sound", "label": "The sound",
                 "description": "Production, rhythm, texture, and arrangement.",
                 "interpretation": "Preserve the defining sonic and structural qualities."},
                {"value": "feeling", "label": "The feeling",
                 "description": "Mood, tension, warmth, and emotional effect.",
                 "interpretation": "Preserve the emotional effect even if the sound changes."},
                {"value": "context", "label": "The context",
                 "description": "Scene, culture, era, and artistic environment.",
                 "interpretation": "Preserve the cultural and scene context."},
                {"value": "blend", "label": "The whole tension",
                 "description": "Let sound, feeling, and context work together.",
                 "interpretation": "Preserve the strongest combination of sound, feeling, and context."},
            ],
        })
    if depth is None:
        questions.append({
            "id": "genre_distance",
            "question": "How far outside the starting genre should we explore?",
            "help": "Genre distance is separate from popularity and from the quality you want preserved.",
            "options": [
                {"value": 1, "label": "Same genre",
                 "description": "Keep every recommendation in the original genre or its closest subgenre.",
                 "interpretation": "Keep every recommendation inside the stated genre."},
                {"value": 2, "label": "Nearby genres",
                 "description": "Include adjacent genres and hybrids with an obvious connection.",
                 "interpretation": "Allow only nearby subgenres and genre hybrids."},
                {"value": 3, "label": "Related genres",
                 "description": "Explore related traditions with a clear musical bridge.",
                 "interpretation": "Allow adjacent genres with a clear musical bridge."},
                {"value": 4, "label": "Different genres",
                 "description": "Cross into different genres while preserving what matters most.",
                 "interpretation": "Allow distant genres only when the calibrated quality remains strong."},
                {"value": 5, "label": "Any genre",
                 "description": "Ignore genre boundaries if the chosen quality still comes through.",
                 "interpretation": "Allow any genre when the essential calibrated experience survives."},
            ],
        })
    if not visibility:
        questions.append({
            "id": "visibility",
            "question": "How established should the artists be?",
            "help": "This is about popularity, not musical distance. An obscure record can still be a close match.",
            "options": [
                {"value": "familiar", "label": "Established",
                 "description": "Favor canonical artists and accessible entry points within this musical world.",
                 "interpretation": "Favor familiar artists without changing genre distance."},
                {"value": "mixed", "label": "Balanced discovery",
                 "description": "Mix established artists with lesser-known discoveries.",
                 "interpretation": "Mix familiar and underheard artists."},
                {"value": "underheard", "label": "Underground",
                 "description": "Focus on lesser-known artists outside the usual recommendation lists.",
                 "interpretation": "Prioritize underheard artists when evidence is comparable."},
            ],
        })
    if has_image:
        questions.append({
            "id": "visual_role",
            "question": "Should the music preserve the image or transform it over time?",
            "help": "The image can be a destination or the beginning of a changing arc.",
            "options": [
                {"value": "preserve", "label": "Preserve it", "description": "Stay inside the image's atmosphere.",
                 "interpretation": "Preserve the image's atmosphere."},
                {"value": "transform", "label": "Transform it", "description": "Use the image as a point of departure.",
                 "interpretation": "Transform the image's atmosphere over the journey."},
                {"value": "journey", "label": "Build an arc", "description": "Begin close, then gradually move away.",
                 "interpretation": "Begin near the image and gradually transform it."},
            ],
        })
    return questions


def annotation_completeness(by_axis: dict[str, list], evidence_count: int = 0) -> dict:
    """Estimate coverage, never truth, from represented axes and evidence volume."""
    represented = [axis for axis in EXTERNAL_AXES if by_axis.get(axis)]
    axis_score = len(represented) / len(EXTERNAL_AXES)
    evidence_score = min(1.0, evidence_count / 8) if evidence_count else 0.0
    score = round(0.8 * axis_score + 0.2 * evidence_score, 3)
    return {"score": score, "state": confidence_state(score), "represented_axes": represented,
            "missing_axes": [axis for axis in EXTERNAL_AXES if axis not in represented],
            "method": "axis_coverage_plus_evidence_volume", "is_truth_estimate": False}


def descriptor_distance(left: set[str], right: set[str]) -> float:
    union = left | right
    return 1.0 if not union else 1.0 - len(left & right) / len(union)


def pairwise_slate_diversity(items: list[dict]) -> dict:
    """Report descriptor and metadata separation among every result pair."""
    pairs = []
    for index, left in enumerate(items):
        for right in items[index + 1:]:
            descriptor = descriptor_distance(set(left.get("descriptors", [])), set(right.get("descriptors", [])))
            metadata = sum((left.get(key) != right.get(key)) for key in ("bucket", "region", "decade")) / 3
            distance = round(0.7 * descriptor + 0.3 * metadata, 3)
            pairs.append({"left": left["id"], "right": right["id"], "distance": distance})
    average = round(sum(pair["distance"] for pair in pairs) / len(pairs), 3) if pairs else 0.0
    return {"average_distance": average, "pairs": pairs, "method": "descriptor_jaccard_plus_metadata",
            "provenance": {"source": "curator", "confidence": 0.75,
                           "confidence_state": confidence_state(0.75)}}


def select_pairwise_diverse(scored: list[tuple], n_results: int, strength: float = 0.2) -> list[tuple]:
    """Greedily balance evidence score with distance from the selected slate."""
    if not scored or strength <= 0:
        return select_diverse(scored, n_results)
    maximum = max(float(item[0]) for item in scored) or 1.0
    remaining = list(scored)
    selected = [remaining.pop(0)]
    while remaining and len(selected) < n_results:
        def utility(item: tuple) -> tuple:
            album = item[1]
            tags = set(item[3])
            value_for = lambda record, key: record[key] if key in record.keys() else None
            distances = []
            for chosen in selected:
                other = chosen[1]
                descriptor = descriptor_distance(tags, set(chosen[3]))
                metadata = sum((value_for(album, key) != value_for(other, key))
                               for key in ("bucket", "region")) / 2
                distances.append(0.7 * descriptor + 0.3 * metadata)
            diversity = min(distances) if distances else 0.0
            value = (1 - strength) * (float(item[0]) / maximum) + strength * diversity
            return (value, float(item[0]), -(value_for(album, "year") or 9999))
        chosen = max(remaining, key=utility)
        remaining.remove(chosen)
        selected.append(chosen)
    return selected


def visual_match(image: dict, candidate: dict, mode: str = "preserve") -> dict:
    """Score a candidate's explicit visual profile against image features."""
    keys = ("brightness", "warmth", "saturation", "contrast", "openness", "depth", "density")
    shared = [key for key in keys if image.get(key) is not None and candidate.get(key) is not None]
    if not shared:
        return {"score": None, "mode": mode, "features": [], "source": "curator", "confidence": 0.0,
                "confidence_state": "possible"}
    similarity = sum(1 - abs(float(image[key]) - float(candidate[key])) for key in shared) / len(shared)
    score = similarity if mode == "preserve" else 1 - similarity if mode == "transform" else 0.5
    confidence = round(len(shared) / len(keys), 3)
    return {"score": round(max(0.0, min(1.0, score)), 3), "mode": mode, "features": shared,
            "source": "curator", "confidence": confidence,
            "confidence_state": confidence_state(confidence)}


def select_diverse(scored: list[tuple], n_results: int) -> list[tuple]:
    """Preserve score order; diversify only candidates tied on evidence score."""
    remaining = list(scored)
    selected: list[tuple] = []
    bucket_counts: dict[str, int] = {}
    region_counts: dict[str, int] = {}
    decade_counts: dict[int, int] = {}
    while remaining and len(selected) < n_results:
        top_score = remaining[0][0]
        tied = [item for item in remaining if item[0] == top_score]
        tied.sort(key=lambda item: (
            bucket_counts.get(item[1]["bucket"], 0),
            region_counts.get(item[1]["region"], 0),
            decade_counts.get((item[1]["year"] or 0) // 10, 0),
            item[1]["year"] or 9999,
            item[1]["title"],
        ))
        chosen = tied[0]
        remaining.remove(chosen)
        selected.append(chosen)
        album = chosen[1]
        bucket_counts[album["bucket"]] = bucket_counts.get(album["bucket"], 0) + 1
        region_counts[album["region"]] = region_counts.get(album["region"], 0) + 1
        decade = (album["year"] or 0) // 10
        decade_counts[decade] = decade_counts.get(decade, 0) + 1
    return selected
