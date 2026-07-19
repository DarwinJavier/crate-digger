"""Pure deterministic recommendation policy helpers with no service dependencies."""

import re


SCORING_POLICY_VERSION = "research-informed-v1"
SCORING_WEIGHTS = {
    "descriptor_match": 2.0,
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
