"""
app.py — barebones recommendation platform over corpus.db

The smallest honest version of the agent-first idea:
  * Your curated corpus (corpus.db) is the trusted foundation.
  * MusicBrainz resolves seed artists at query time (facts, coverage honesty).
  * Last.fm provides similar-artist / tag SIGNALS, always labeled source="last_fm",
    never written into the corpus.
  * OpenAI (optional) maps intent, scouts brain-guided candidates, and writes
    bounded prose. Outside entities must resolve in MusicBrainz; inferred musical
    fit remains explicitly labeled.

Run it (PowerShell, from the repo root, after build_corpus.py build):
    pip install fastapi uvicorn requests
    # Copy .env.example to .env and add local credentials.
    uvicorn app:app --reload

Then open http://127.0.0.1:8000  (simple form)
       or http://127.0.0.1:8000/docs  (interactive API docs — free with FastAPI)
"""

import json
import hashlib
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from recommendation_logic import (
    SCORING_POLICY_VERSION,
    annotation_completeness,
    confidence_state,
    infer_external_axes,
    load_approved_crosswalk,
    load_external_taxonomy,
    pairwise_slate_diversity,
    find_unmapped_terms,
    intent_coverage,
    score_component,
    select_diverse,
    select_pairwise_diverse,
    tuning_questions,
    visual_match,
)
from evaluation_store import evaluation_state, freeze_briefs, save_brief, save_feedback
from evaluation_ui import evaluation_page
from listener_ui import listener_page

PROJECT_ROOT = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding the process environment."""
    if not path.exists():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            print(f"Ignoring malformed .env line {line_number}")
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            print(f"Ignoring invalid .env key on line {line_number}")
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


if os.environ.get("CRATE_DIGGER_SKIP_DOTENV") != "1":
    load_env_file(PROJECT_ROOT / ".env")

DB_PATH = PROJECT_ROOT / "build/corpus.db"
RUNTIME_DB_PATH = PROJECT_ROOT / "build/runtime_cache.db"
RECOMMENDATION_LOGIC_PATH = PROJECT_ROOT / "brain/recommendation-logic.md"
FRONTIER_GENRE_GUIDE_PATH = PROJECT_ROOT / "brain/crate-digger-frontier-genre-exploration.md"
EXTERNAL_TAXONOMY_PATH = PROJECT_ROOT / "research/taxonomies/music-descriptor-taxonomy/music-descriptor-taxonomy.json"
CROSSWALK_PATH = PROJECT_ROOT / "data/descriptor_crosswalk.csv"
ARTIST_ARCS_PATH = PROJECT_ROOT / "data/artist_arcs.csv"
EVIDENCE_PATH = PROJECT_ROOT / "data/descriptor_evidence.csv"
IMAGE_FEATURES_PATH = PROJECT_ROOT / "data/image_features.csv"
EXTERNAL_CANDIDATES_PATH = PROJECT_ROOT / "data/external_candidates.csv"
LASTFM_KEY = os.environ.get("LASTFM_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")
MUSICBRAINZ_CONTACT = os.environ.get("MUSICBRAINZ_CONTACT", "").strip()
USER_AGENT = os.environ.get(
    "MUSICBRAINZ_USER_AGENT",
    f"MusicCorpusSandbox/0.1 ({MUSICBRAINZ_CONTACT})" if MUSICBRAINZ_CONTACT else "",
)
CORPUS_VERSION = time.strftime("%Y-%m-%d", time.gmtime(DB_PATH.stat().st_mtime)) if DB_PATH.exists() else "missing"
MUSICBRAINZ_LOCK = threading.Lock()
MUSICBRAINZ_LAST_REQUEST = 0.0

app = FastAPI(title="Music Context Sandbox", version="0.1")


def load_runtime_policy() -> str:
    """Load the compact policy block shared by the LLM boundaries."""
    if not RECOMMENDATION_LOGIC_PATH.exists():
        return ""
    text = RECOMMENDATION_LOGIC_PATH.read_text(encoding="utf-8")
    start_marker = "<!-- RUNTIME_POLICY_START -->"
    end_marker = "<!-- RUNTIME_POLICY_END -->"
    if start_marker not in text or end_marker not in text:
        return ""
    return text.split(start_marker, 1)[1].split(end_marker, 1)[0].strip()


RUNTIME_POLICY = load_runtime_policy()


def load_frontier_genre_guide() -> str:
    """Load the read-only exploration guide supplied only to explicit Frontier scouting."""
    if not FRONTIER_GENRE_GUIDE_PATH.exists():
        return ""
    return FRONTIER_GENRE_GUIDE_PATH.read_text(encoding="utf-8-sig").strip()


FRONTIER_GENRE_GUIDE = load_frontier_genre_guide()


def musicbrainz_get(path: str, params: dict, timeout: int = 12):
    """Serialize MusicBrainz traffic and keep request starts at least one second apart."""
    global MUSICBRAINZ_LAST_REQUEST
    with MUSICBRAINZ_LOCK:
        remaining = 1.0 - (time.monotonic() - MUSICBRAINZ_LAST_REQUEST)
        if remaining > 0:
            time.sleep(remaining)
        MUSICBRAINZ_LAST_REQUEST = time.monotonic()
        return requests.get(
            f"https://musicbrainz.org/ws/2/{path.lstrip('/')}",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )


# ---------------------------------------------------------------------------
# Request / response contracts (the "agent-first" part: typed, validated)
# ---------------------------------------------------------------------------
class Seed(BaseModel):
    artist: str


class ReferenceRecord(BaseModel):
    """The record being translated, kept separate from recommendation inventory."""
    artist: str = ""
    album: str = ""


class CalibrationAnswer(BaseModel):
    question_id: str
    question: str = ""
    selected_label: str
    interpretation: str


class CalibrationContext(BaseModel):
    interpretation: str = ""
    must_preserve: list[str] = Field(default_factory=list)
    may_change: list[str] = Field(default_factory=list)
    detected_genres: list[str] = Field(default_factory=list)


class HardConstraints(BaseModel):
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    buckets: Optional[list[str]] = None          # e.g. ["D", "F"]
    exclude_seed_artists: bool = True
    exclude_moods: list[str] = Field(default_factory=list)


class FeatureToggles(BaseModel):
    adaptive_questions: bool = True
    discovery_depth: bool = True
    external_taxonomy: bool = True
    axis_inference: bool = True
    slate_diversity: bool = True
    visual_scoring: bool = True
    frozen_evaluation: bool = True
    outside_discovery: bool = True
    corpus_candidates: bool = True


class ImageFeatures(BaseModel):
    brightness: Optional[float] = None
    warmth: Optional[float] = None
    saturation: Optional[float] = None
    contrast: Optional[float] = None
    openness: Optional[float] = None
    depth: Optional[float] = None
    density: Optional[float] = None
    texture: str = ""
    geometry: str = ""
    human_arrangement: str = ""
    motion: str = ""


class RecRequest(BaseModel):
    brief: str = ""                              # "rainy, cinematic writing music"
    seeds: list[Seed] = Field(default_factory=list)
    reference: ReferenceRecord = Field(default_factory=ReferenceRecord)
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    novelty: str = "any"                         # any | non_obvious
    n_results: int = Field(default=5, ge=1, le=25)
    use_lastfm: bool = True
    discovery_depth: Optional[int] = Field(default=None, ge=1, le=5)
    genre_distance: Optional[int] = Field(default=None, ge=1, le=5)
    visibility: Optional[str] = None
    genre_boundary: Optional[str] = None
    meaning_focus: Optional[str] = None
    calibration: CalibrationContext = Field(default_factory=CalibrationContext)
    calibration_answers: list[CalibrationAnswer] = Field(default_factory=list)
    listener_id: str = ""
    journey_id: str = ""
    image_features: Optional[ImageFeatures] = None
    visual_role: str = "preserve"
    include_analysis_report: bool = True
    features: FeatureToggles = Field(default_factory=FeatureToggles)


class EvaluationBrief(BaseModel):
    id: str = ""
    brief: str
    seed_artist: str = ""
    seed_album: str = ""
    liked_quality: str = ""
    discovery_depth: str = ""
    visibility: str = ""
    exclusions: str = ""
    visual_role: str = ""
    submitted_by: str


class EvaluationFeedback(BaseModel):
    case_id: str
    evaluator_id: str
    system_arm: str = "platform"
    artist: str
    album: str
    year: str = ""
    position: str = ""
    requested_quality: int
    discovery_value: int
    connection_clarity: int
    save_revisit: int
    explanation_trust: int
    justification: str


def model_values(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return vars(model)


# ---------------------------------------------------------------------------
# Corpus access
# ---------------------------------------------------------------------------
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def runtime_db() -> sqlite3.Connection:
    """Open disposable query-time state; curated CSVs remain the source of truth."""
    RUNTIME_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(RUNTIME_DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS identity_cache (
            normalized_artist TEXT NOT NULL,
            normalized_album TEXT NOT NULL,
            artist TEXT NOT NULL,
            album TEXT NOT NULL,
            year INTEGER,
            rg_mbid TEXT NOT NULL,
            verification_score REAL NOT NULL,
            verified_at INTEGER NOT NULL,
            PRIMARY KEY (normalized_artist, normalized_album)
        );
        CREATE TABLE IF NOT EXISTS recommendation_exposures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listener_id TEXT NOT NULL,
            journey_id TEXT NOT NULL,
            rg_mbid TEXT NOT NULL,
            intent_signature TEXT NOT NULL,
            reason_signature TEXT NOT NULL,
            shown_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS exposure_listener_album
            ON recommendation_exposures(listener_id, rg_mbid, shown_at);
    """)
    return con


def normalized_identity(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def calibration_display_copy(value: str) -> str:
    """Keep model interpretation copy direct instead of narrating about a user persona."""
    text = str(value or "").strip()
    for pattern in (
        r"^the listener (?:wants|is looking for|seeks|is after)\s+",
        r"^the user (?:wants|is looking for|seeks|is after)\s+",
        r"^they (?:want|are looking for|seek|are after)\s+",
    ):
        revised = re.sub(pattern, "", text, flags=re.IGNORECASE)
        if revised != text:
            return revised[:1].upper() + revised[1:]
    return text


def genre_distance(req: RecRequest) -> int:
    """Prefer the clearer name while retaining API compatibility."""
    return req.genre_distance or req.discovery_depth or 3


def intent_signature(req: RecRequest, intent: dict) -> str:
    payload = {
        "intent": intent,
        "interpretation": req.calibration.interpretation,
        "must_preserve": req.calibration.must_preserve,
        "answers": [model_values(answer) for answer in req.calibration_answers],
        "reference": model_values(req.reference),
        "genre_distance": genre_distance(req),
    }
    stable = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def load_vocab(con) -> dict[str, set[str]]:
    vocab: dict[str, set[str]] = {"mood": set(), "sonic_trait": set(), "scene": set()}
    for r in con.execute("SELECT kind, slug FROM tags"):
        vocab.setdefault(r["kind"], set()).add(r["slug"])
    return vocab


def load_csv_records(path: Path) -> list[dict[str, str]]:
    import csv
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def album_context(artist: str, album: str) -> dict:
    match = lambda row: row.get("artist", "").casefold() == artist.casefold() and row.get("album", "").casefold() == album.casefold()
    arcs = [row for row in load_csv_records(ARTIST_ARCS_PATH) if row.get("approved", "").lower() == "yes" and match(row)]
    evidence = [row for row in load_csv_records(EVIDENCE_PATH) if row.get("approved", "").lower() == "yes" and match(row)]
    for row in arcs + evidence:
        numeric = float(row.get("confidence") or 0.0)
        row["confidence"] = numeric
        row["confidence_state"] = row.get("confidence_state") or confidence_state(numeric)
    by_scope = {scope: [] for scope in ("album", "track", "scene")}
    for row in evidence:
        by_scope.setdefault(row.get("scope", "album"), []).append(row)
    return {"artist_arc": arcs[0] if arcs else None, "evidence": by_scope}


def album_visual_features(artist: str, album: str) -> dict:
    for row in load_csv_records(IMAGE_FEATURES_PATH):
        if (row.get("approved", "").lower() == "yes" and
                row.get("artist", "").casefold() == artist.casefold() and
                row.get("album", "").casefold() == album.casefold()):
            output = {}
            for key in ("brightness", "warmth", "saturation", "contrast", "openness", "depth", "density"):
                output[key] = float(row[key]) if row.get(key, "").strip() else None
            return output
    return {}


def album_display_context(con: sqlite3.Connection, album_id: int,
                          matched: list[str]) -> dict:
    """Group display signals without changing their stored provenance."""
    rows = [dict(row) for row in con.execute(
        "SELECT tags.slug, tags.kind FROM album_tags "
        "JOIN tags ON tags.id=album_tags.tag_id WHERE album_tags.album_id=? "
        "ORDER BY tags.kind, tags.slug",
        (album_id,),
    )]
    matched_set = set(matched)
    sound_mood = [
        row["slug"] for row in rows
        if row["slug"] in matched_set and row["kind"] in {"mood", "sonic_trait"}
    ][:5]
    scenes = [
        row["slug"] for row in rows if row["kind"] == "scene"
        and (row["slug"] in matched_set or not matched_set)
    ][:2]
    if not scenes:
        scenes = [row["slug"] for row in rows if row["kind"] == "scene"][:2]
    labels = [row["name"] for row in con.execute(
        "SELECT DISTINCT labels.name FROM album_labels "
        "JOIN labels ON labels.id=album_labels.label_id "
        "WHERE album_labels.album_id=? ORDER BY labels.name LIMIT 3",
        (album_id,),
    )]
    return {"descriptors": sound_mood, "scenes": scenes, "labels": labels}


def label_matches_for_brief(con: sqlite3.Connection, album_id: int, brief: str) -> list[dict]:
    """Return only verified album-label links whose curated terms occur in the brief."""
    text = " ".join(re.findall(r"[a-z0-9]+", brief.casefold()))
    if not text:
        return []
    rows = con.execute(
        """SELECT labels.id, labels.name, labels.label_signal, labels.confidence AS label_confidence,
                  album_labels.confidence AS link_confidence, label_terms.kind, label_terms.value
           FROM album_labels JOIN labels ON labels.id=album_labels.label_id
           JOIN label_terms ON label_terms.label_id=labels.id
           WHERE album_labels.album_id=? AND label_terms.kind != 'anchor_artist'
           ORDER BY labels.name, label_terms.kind, label_terms.value""",
        (album_id,),
    )
    matches = []
    seen = set()
    for row in rows:
        normalized = " ".join(re.findall(r"[a-z0-9]+", row["value"].casefold()))
        match_key = (row["id"], normalized)
        if (match_key not in seen and normalized and
                re.search(r"(?:^| )" + re.escape(normalized) + r"(?: |$)", text)):
            matches.append(dict(row))
            seen.add(match_key)
    return matches


def search_labels(con: sqlite3.Connection, query: str = "", kind: str = "",
                  value: str = "", related_to: str = "", limit: int = 25) -> list[dict]:
    """Search the curated label graph without inferring new label relationships."""
    sql = "SELECT DISTINCT labels.* FROM labels"
    joins, clauses, params = [], [], []
    if query or value:
        joins.append("JOIN label_terms ON label_terms.label_id=labels.id")
    if query:
        clauses.append("(labels.name LIKE ? OR labels.label_signal LIKE ? OR label_terms.value LIKE ?)")
        needle = f"%{query}%"
        params.extend([needle, needle, needle])
    if value:
        clauses.append("label_terms.value = ? COLLATE NOCASE")
        params.append(value)
    if kind:
        if kind not in {"genre", "texture", "mood", "scene", "anchor_artist"}:
            return []
        clauses.append("label_terms.kind = ?")
        params.append(kind)
    if related_to:
        clauses.append("EXISTS (SELECT 1 FROM label_edges WHERE "
                       "(label_edges.source_label_id=labels.id AND label_edges.target_label_id=?) OR "
                       "(label_edges.source_label_id=? AND label_edges.target_label_id=labels.id))")
        params.extend([related_to, related_to])
    sql += " " + " ".join(joins)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY labels.name LIMIT ?"
    params.append(max(1, min(limit, 100)))
    output = []
    for row in con.execute(sql, params):
        item = dict(row)
        item["terms"] = {}
        for term in con.execute("SELECT kind, value FROM label_terms WHERE label_id=? ORDER BY kind, value", (row["id"],)):
            item["terms"].setdefault(term["kind"], []).append(term["value"])
        item["related_labels"] = [dict(edge) for edge in con.execute(
            "SELECT relationship_type, target_label_id, target_is_modeled, source, confidence FROM label_edges WHERE source_label_id=? ORDER BY relationship_type, target_label_id",
            (row["id"],))]
        output.append(item)
    return output


# ---------------------------------------------------------------------------
# Brief parsing: LLM if available, keyword fallback otherwise.
# Either way, output is CONSTRAINED to your controlled vocabulary.
# ---------------------------------------------------------------------------
def openai_json_response(instructions: str, prompt: str, name: str, schema: dict,
                         max_output_tokens: int = 1200) -> dict:
    """Call the Responses API with a strict JSON schema and return parsed output."""
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
        json={
            "model": OPENAI_MODEL,
            "instructions": instructions,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
            "text": {"format": {"type": "json_schema", "name": name,
                                "strict": True, "schema": schema}},
        },
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    raw = payload.get("output_text", "")
    if not raw:
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    raw += content.get("text", "")
    if not raw:
        raise ValueError("OpenAI returned no structured output")
    return json.loads(raw)


def openai_web_json_response(instructions: str, prompt: str, name: str, schema: dict,
                             max_output_tokens: int = 2200) -> tuple[dict, list[dict]]:
    """Run one evidence-retrieval pass and return structured findings plus used URLs."""
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
        json={
            "model": OPENAI_MODEL,
            "instructions": instructions,
            "input": prompt,
            "tools": [{"type": "web_search", "search_context_size": "medium"}],
            "include": ["web_search_call.action.sources"],
            "max_output_tokens": max_output_tokens,
            "text": {"format": {"type": "json_schema", "name": name,
                                "strict": True, "schema": schema}},
        },
        timeout=150,
    )
    response.raise_for_status()
    payload = response.json()
    raw = payload.get("output_text", "")
    sources: dict[str, dict] = {}
    for item in payload.get("output", []):
        if item.get("type") == "web_search_call":
            for source in (item.get("action") or {}).get("sources", []):
                url = str(source.get("url", "")).strip()
                if url:
                    sources[url] = {"url": url, "title": str(source.get("title", "")).strip()}
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                raw += content.get("text", "")
                for annotation in content.get("annotations", []):
                    url = str(annotation.get("url", "")).strip()
                    if url:
                        sources[url] = {
                            "url": url,
                            "title": str(annotation.get("title", "")).strip(),
                        }
    if not raw:
        raise ValueError("OpenAI researcher returned no structured output")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Some Responses payloads expose output_text both at the top level and in
        # content blocks. Accept the first complete JSON value if those copies were
        # concatenated, while still rejecting genuinely truncated JSON.
        parsed, _ = json.JSONDecoder().raw_decode(raw.lstrip())
    return parsed, list(sources.values())[:12]


def needs_musical_orientation(brief: str) -> bool:
    """Conservatively detect cold-start prompts that describe a use or scene, not music."""
    text = normalized_identity(brief)
    if not text:
        return False
    reference_markers = (
        " similar to ", " like ", " sounds like ", " start with ", " by ",
        " artist ", " album ", " record ",
    )
    padded = f" {text} "
    if any(marker in padded for marker in reference_markers):
        return False
    explicit_genres = {
        "ambient", "blues", "classical", "country", "dancehall", "disco", "drone",
        "dub", "electronic", "folk", "funk", "gospel", "hip hop", "house", "industrial",
        "jazz", "metal", "pop", "post punk", "punk", "r b", "rap", "reggae", "rock",
        "shoegaze", "slowcore", "soul", "techno", "trip hop",
    }
    if any(re.search(rf"(?:^| ){re.escape(genre)}(?: |$)", text) for genre in explicit_genres):
        return False
    situational_terms = {
        "rain", "rainy", "storm", "snow", "walk", "walking", "drive", "driving",
        "dinner", "cooking", "study", "studying", "work", "working", "sleep", "sleeping",
        "morning", "night", "party", "gym", "road trip", "sunset", "sunrise", "weather",
    }
    return (text.startswith("music for ") or text.startswith("soundtrack for ") or
            any(re.search(rf"(?:^| ){re.escape(term)}(?: |$)", text)
                for term in situational_terms))


def fallback_orientation_question() -> dict:
    """Offer concrete musical starting worlds when no model interpretation is available."""
    return {
        "id": "musical_orientation",
        "question": "What should this sound like in your head?",
        "help": "Choose a musical starting world, not a final genre restriction.",
        "options": [{
            "value": "spacious_immersive",
            "label": "Spacious and immersive",
            "description": "Blurred textures, patient movement, and room to breathe.",
            "interpretation": "Begin in a spacious, texture-led, rhythm-light musical world.",
        }, {
            "value": "rhythmic_physical",
            "label": "Rhythmic and physical",
            "description": "Bass weight, pulse, momentum, and sharper edges.",
            "interpretation": "Begin with a rhythm-led, bass-weighted, physically immediate sound.",
        }, {
            "value": "intimate_organic",
            "label": "Intimate and organic",
            "description": "Close voices, acoustic detail, and emotional stillness.",
            "interpretation": "Begin with sparse, intimate, organic instrumentation and close presence.",
        }, {
            "value": "custom_orientation",
            "label": "Something else",
            "description": "Name an artist, record, genre, or describe the sound in your head.",
            "interpretation": "Use the listener's own musical orientation as the starting point.",
        }, {
            "value": "open_orientation",
            "label": "Keep it open",
            "description": "Proceed without choosing a musical starting point.",
            "interpretation": "Do not impose a reference world; preserve only the original request.",
        }],
    }


def analyze_calibration(brief: str, has_image: bool = False,
                        musical_orientation: str = "") -> dict:
    """Form a request-specific hypothesis, then add stable genre/visibility controls."""
    awaiting_orientation = needs_musical_orientation(brief) and not musical_orientation.strip()
    fallback = {
        "interpretation": "The request may be about sound, feeling, or cultural context.",
        "must_preserve": [],
        "may_change": [],
        "detected_genres": [],
        "seed_artists": [],
        "reference": {"artist": "", "album": ""},
        "questions": ([fallback_orientation_question()] if awaiting_orientation
                      else tuning_questions(brief, has_image, None, None)),
        "source": "deterministic_policy",
    }
    if not OPENAI_KEY or not brief.strip():
        return fallback
    option_schema = {
        "type": "object",
        "properties": {
            "value": {"type": "string"},
            "label": {"type": "string"},
            "description": {"type": "string"},
            "interpretation": {"type": "string"},
            "exemplar_artist": {"type": "string"},
            "exemplar_album": {"type": "string"},
        },
        "required": ["value", "label", "description", "interpretation",
                     "exemplar_artist", "exemplar_album"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {
            "interpretation": {"type": "string"},
            "must_preserve": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "may_change": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "detected_genres": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "seed_artists": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            "reference": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string"},
                    "album": {"type": "string"},
                },
                "required": ["artist", "album"],
                "additionalProperties": False,
            },
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "question": {"type": "string"},
                        "help": {"type": "string"},
                        "options": {"type": "array", "minItems": 3, "maxItems": 5,
                                    "items": option_schema},
                    },
                    "required": ["id", "question", "help", "options"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["interpretation", "must_preserve", "may_change", "detected_genres",
                     "seed_artists", "reference", "questions"],
        "additionalProperties": False,
    }
    try:
        output = openai_json_response(
            "You are the interpretive calibration stage of a music discovery engine. "
            "Infer a concise hypothesis about the musical goal, then ask one "
            "question whose answers would materially change the recommendation path. Questions "
            "must be specific to this request, not reusable preference controls. If the request "
            "primarily describes weather, an activity, a place, a visual scene, a function, or an "
            "emotion and names no artist, record, or explicit genre, and the prompt supplies no "
            "selected musical orientation, you MUST make the question id "
            "musical_orientation. This rule has priority over asking what role the music should play "
            "or which emotional shade matters. Offer "
            "three contrasting sonic directions stated in concrete language. Each direction may "
            "include one real exemplar artist and album, or empty exemplar strings when an example "
            "would not clarify it. The exemplar establishes orientation only; it is not a seed or "
            "recommendation. If the request already names a useful artist, record, or sufficiently "
            "specific genre, do not ask musical_orientation. If the request "
            "names a genre, ask what quality of the reference should survive; genre travel is "
            "handled separately. If it points to a social environment, scene, era, lyrical stance, "
            "production detail, rhythm, or emotional contradiction, test that specific ambiguity. "
            "Only copy seed artist names explicitly present in the request. Separately extract one "
            "named reference record when present; do not treat it as recommendation inventory. "
            "Write the interpretation as direct, neutral product copy that begins with the musical "
            "goal itself. Never say 'the listener', 'the user', 'they want', or similar third-person "
            "framing. Do not recommend albums "
            "or introduce music facts. Each option's interpretation must be a direct instruction "
            "that can guide candidate eligibility.",
            (f"Listener brief:\n{brief}\n\n"
             f"Selected musical orientation:\n{musical_orientation or '(none yet)'}\n\n"
             "When a selected musical orientation is present, do not ask musical_orientation again. "
             "Ask which defining quality inside that selected musical world should matter most."),
            "adaptive_music_calibration",
            schema,
            1400,
        )
    except Exception as exc:
        print(f"Adaptive calibration failed ({exc}); using deterministic policy")
        return fallback
    brief_folded = brief.casefold()
    output["seed_artists"] = [
        artist for artist in output["seed_artists"]
        if normalized_identity(artist) in normalized_identity(brief_folded)
    ]
    output.setdefault("reference", {"artist": "", "album": ""})
    if awaiting_orientation and output["questions"]:
        output["questions"][0]["id"] = "musical_orientation"
        output["questions"] = output["questions"][:1]
    elif musical_orientation and output["questions"] and output["questions"][0]["id"] == "musical_orientation":
        output["questions"][0]["id"] = "interpretation_focus"
    for question in output["questions"]:
        if question["id"] != "musical_orientation":
            for option in question["options"]:
                option.pop("exemplar_artist", None)
                option.pop("exemplar_album", None)
            continue
        verified_options = []
        for option in question["options"][:3]:
            artist = option.pop("exemplar_artist", "").strip()
            album = option.pop("exemplar_album", "").strip()
            if artist and album:
                resolved = verify_release_group({"artist": artist, "album": album, "year": None})
                if resolved:
                    option["exemplar"] = {
                        "artist": resolved["artist"],
                        "album": resolved["album"],
                        "rg_mbid": resolved["rg_mbid"],
                        "provenance": {
                            "source": "musicbrainz",
                            "confidence": resolved["verification_score"],
                        },
                    }
            verified_options.append(option)
        verified_options.extend([
            {
                "value": "custom_orientation",
                "label": "Something else",
                "description": "Name an artist, record, genre, or describe the sound in your head.",
                "interpretation": "Use the listener's own musical orientation as the starting point.",
            },
            {
                "value": "open_orientation",
                "label": "Keep it open",
                "description": "Proceed without choosing a musical starting point.",
                "interpretation": "Do not impose a reference world; preserve only the original request.",
            },
        ])
        question["options"] = verified_options
    if not awaiting_orientation:
        stable = tuning_questions(brief, has_image, None, None, include_interpretation=False)
        output["questions"] = output["questions"] + stable
    output["interpretation"] = calibration_display_copy(output.get("interpretation", ""))
    output["source"] = "openai_interpretation"
    return output


def parse_brief(brief: str, vocab: dict[str, set[str]]) -> dict:
    intent = {"moods": [], "sonic_traits": [], "scenes": [], "unmapped_terms": []}
    if not brief.strip():
        return intent
    if OPENAI_KEY:
        try:
            return parse_brief_openai(brief, vocab)
        except Exception as e:
            print(f"OpenAI parse failed ({e}); using keyword fallback")
    elif ANTHROPIC_KEY:
        try:
            return parse_brief_llm(brief, vocab)
        except Exception as e:            # fall back rather than fail
            print(f"LLM parse failed ({e}); using keyword fallback")
    text = brief.lower()
    for kind, key in (("mood", "moods"), ("sonic_trait", "sonic_traits"), ("scene", "scenes")):
        for slug in vocab.get(kind, ()):
            if re.search(r"\b" + re.escape(slug.replace("-", " ")) + r"\b", text) or slug in text:
                intent[key].append(slug)
    intent["unmapped_terms"] = find_unmapped_terms(text, intent)
    return intent


def parse_brief_openai(brief: str, vocab: dict[str, set[str]]) -> dict:
    schema = {
        "type": "object",
        "properties": {
            "moods": {"type": "array", "items": {"type": "string", "enum": sorted(vocab["mood"])},
                      "maxItems": 5},
            "sonic_traits": {"type": "array",
                             "items": {"type": "string", "enum": sorted(vocab["sonic_trait"])},
                             "maxItems": 3},
            "scenes": {"type": "array", "items": {"type": "string", "enum": sorted(vocab["scene"])},
                       "maxItems": 2},
            "unmapped_terms": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        },
        "required": ["moods", "sonic_traits", "scenes", "unmapped_terms"],
        "additionalProperties": False,
    }
    raw = openai_json_response(
        "Map a listener's music request onto the supplied controlled vocabulary. "
        "Do not introduce albums, artists, facts, or relationships in this step.",
        f"Brief:\n{brief}\n\nControlled vocabulary:\n"
        f"Moods: {sorted(vocab['mood'])}\nSonic traits: {sorted(vocab['sonic_trait'])}\n"
        f"Scenes: {sorted(vocab['scene'])}",
        "listener_intent",
        schema,
        500,
    )
    brief_words = set(re.findall(r"[a-z0-9]+", brief.casefold()))
    unmapped = []
    for value in raw["unmapped_terms"]:
        candidate = str(value).strip().casefold()
        words = set(re.findall(r"[a-z0-9]+", candidate))
        if candidate and words and words <= brief_words:
            unmapped.append(candidate)
    return {
        "moods": list(dict.fromkeys(raw["moods"])),
        "sonic_traits": list(dict.fromkeys(raw["sonic_traits"])),
        "scenes": list(dict.fromkeys(raw["scenes"])),
        "unmapped_terms": unmapped[:8],
    }


def parse_brief_llm(brief: str, vocab: dict[str, set[str]]) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = (
        "Map this music brief onto the controlled vocabulary. Respond ONLY with JSON "
        '{"moods": [], "sonic_traits": [], "scenes": [], "unmapped_terms": []}. '
        "Use ONLY controlled terms in the first three lists. In unmapped_terms, copy at most "
        "8 brief words or short phrases whose meaning is not represented by selected terms. "
        "Pick up to 5 moods, 3 sonic_traits, and 2 scenes that best capture the brief. "
        "A list may be empty when the brief does not support that dimension.\n\n"
        f"MOODS: {sorted(vocab['mood'])}\n"
        f"SONIC_TRAITS: {sorted(vocab['sonic_trait'])}\n"
        f"SCENES: {sorted(vocab['scene'])}\n\n"
        f"OPERATING_POLICY:\n{RUNTIME_POLICY}\n\n"
        f"BRIEF: {brief}"
    )
    msg = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=300,
                                 messages=[{"role": "user", "content": prompt}])
    raw = json.loads(re.sub(r"```(json)?", "", msg.content[0].text).strip())
    brief_words = set(re.findall(r"[a-z0-9]+", brief.lower()))
    unmapped = []
    for value in raw.get("unmapped_terms", []):
        candidate = str(value).strip().lower()
        words = set(re.findall(r"[a-z0-9]+", candidate))
        if candidate and words and words <= brief_words:
            unmapped.append(candidate)
    # hard validation: silently drop anything outside the vocabulary
    return {
        "moods": [m for m in raw.get("moods", []) if m in vocab["mood"]],
        "sonic_traits": [s for s in raw.get("sonic_traits", []) if s in vocab["sonic_trait"]],
        "scenes": [s for s in raw.get("scenes", []) if s in vocab["scene"]],
        "unmapped_terms": unmapped[:8],
    }


# ---------------------------------------------------------------------------
# Seed resolution: corpus first, MusicBrainz second (coverage honesty)
# ---------------------------------------------------------------------------
def resolve_seed(con, artist_name: str) -> dict:
    row = con.execute("SELECT id, name, mbid FROM artists WHERE name = ? COLLATE NOCASE",
                      (artist_name,)).fetchone()
    if row:
        buckets = [r["bucket"] for r in con.execute(
            "SELECT DISTINCT bucket FROM albums WHERE artist_id=? AND bucket != ''", (row["id"],))]
        return {"artist": row["name"], "status": "in_corpus", "artist_id": row["id"],
                "buckets": buckets}
    # not ours — ask MusicBrainz if it at least exists (facts, not vibes)
    if not USER_AGENT:
        return {"artist": artist_name, "status": "unknown", "buckets": []}
    try:
        data = musicbrainz_get(
            "artist/",
            {"query": f'artist:"{artist_name}"', "fmt": "json", "limit": 1},
            timeout=10,
        ).json()
        hit = (data.get("artists") or [None])[0]
        if hit and int(hit.get("score", 0)) >= 90:
            return {"artist": hit["name"], "status": "known_outside_corpus",
                    "mbid": hit["id"], "buckets": []}
    except Exception:
        pass
    return {"artist": artist_name, "status": "unknown", "buckets": []}


# ---------------------------------------------------------------------------
# Last.fm signal (query-time only, always labeled, never stored)
# ---------------------------------------------------------------------------
def lastfm_similar_artists(artist: str, limit: int = 10) -> list[str]:
    if not LASTFM_KEY:
        return []
    try:
        data = requests.get("https://ws.audioscrobbler.com/2.0/", params={
            "method": "artist.getsimilar", "artist": artist, "api_key": LASTFM_KEY,
            "format": "json", "limit": limit}, headers={"User-Agent": USER_AGENT},
            timeout=10).json()
        return [a["name"] for a in data.get("similarartists", {}).get("artist", [])]
    except Exception:
        return []


def discovery_label_context(con: sqlite3.Connection, intent: dict) -> list[dict]:
    """Return compact curated label territories relevant to the parsed intent."""
    labels: dict[str, dict] = {}
    for kind, key in (("mood", "moods"), ("texture", "sonic_traits"), ("scene", "scenes")):
        for value in intent.get(key, []):
            for label in search_labels(con, kind=kind, value=value, limit=8):
                labels[label["id"]] = {
                    "name": label["name"],
                    "signal": label["label_signal"],
                    "matched_territory": f"{kind}:{value}",
                }
    return sorted(labels.values(), key=lambda item: item["name"])[:12]


CANDIDATE_SCOUT_INSTRUCTION = (
    "You are the candidate-scouting stage of an evidence-backed music discovery engine. "
    "Use your broad music knowledge to propose real released albums that fit the brain brief. "
    "Treat must_preserve and the selected calibration interpretations as eligibility requirements, "
    "not writing prompts. Genre distance controls only how far musical genre may change; visibility "
    "controls artist recognizability and is an eligibility requirement, not a decorative score. "
    "The reference record is context, never reserved inventory. For mixed visibility, propose at "
    "least eight genuinely underheard artists plus several recognizable anchors. For underheard "
    "visibility, every proposal must be underheard. Prefer 12-15 varied hypotheses across distinct traditions "
    "over canonical near-neighbors. When genre_distance is 4, Frontier is a slate-level cross-genre "
    "requirement, not a synonym for obscure adjacent rock: propose candidates across at least four "
    "materially distinct genre families and at least three route types, with no more than two proposals "
    "from one family. Preserve the calibrated quality while allowing instrumentation, rhythm, lineage, "
    "and scene to change. Consider defensible leaps into traditions such as jazz, Latin and salsa, pop, "
    "electronic, folk, soul and funk, dub, or other relevant families instead of forcing those examples. "
    "An obvious candidate must earn its place through the calibrated "
    "bridge. Do not claim that an album is on a label unless that relationship appears in the supplied "
    "context. Your candidates are provisional hypotheses: a Researcher will test the bridge, and "
    "MusicBrainz will verify only shortlisted identities. Keep each connection specific to the "
    "listener's request and do not present speculation as fact. Think broadly before returning the "
    "machine-readable candidate handoff; the schema is transport, not the reasoning method."
)

RESEARCHER_INSTRUCTION = (
    "You are the evidence-retrieval Researcher for a music discovery engine. Research whether each "
    "provisional album can support its proposed bridge to the calibrated request. Search for reliable "
    "album, artist, label, scene, historical, or cultural sources. Identity remains provisional until "
    "MusicBrainz resolves it later. Mark unsupported, contradictory, ambiguous, or weakly sourced "
    "candidates honestly. Do not rescue a candidate with generic genre similarity. A supported verdict "
    "requires evidence for the defining calibrated connection. Also assess artist visibility as "
    "familiar, underheard, or unknown from the available context; do not call a canonical artist "
    "underheard merely because an album is less famous. Return the supported original release year "
    "when one can be established, so MusicBrainz conflicts can be rejected. Return up to three "
    "evidence-supported genre orientations and one concise sound_preview describing instrumentation, "
    "rhythm, vocal approach, texture, or production without marketing language. Genre and sound "
    "remain contextual inferences, not verified identity facts. Rabbit-hole labels must be selected only "
    "from allowed_curated_label_routes. Scene rabbit holes belong to the whole journey and should be "
    "useful research routes, not unverified album metadata."
)


def candidate_scout_payload(req: RecRequest, intent: dict, seeds: list[dict],
                            label_context: list[dict], existing_entities: list[dict]) -> dict:
    """Return the exact structured input used by optional outside-corpus scouting."""
    payload = {
        "listener_brief": req.brief,
        "reference_record": model_values(req.reference),
        "controlled_intent": intent,
        "seed_artists": [seed["artist"] for seed in seeds],
        "calibrated_interpretation": req.calibration.interpretation,
        "must_preserve": req.calibration.must_preserve,
        "may_change": req.calibration.may_change,
        "calibration_answers": [model_values(answer) for answer in req.calibration_answers],
        "genre_distance": genre_distance(req),
        "visibility_preference": req.visibility or "any",
        "novelty": req.novelty,
        "curated_label_territories": label_context,
        "exclude_already_selected": [
            {"artist": entity["artist"], "album": entity["title"]}
            for entity in existing_entities
        ],
        "hard_constraints": model_values(req.hard_constraints),
    }
    if genre_distance(req) == 4 and FRONTIER_GENRE_GUIDE:
        payload["frontier_exploration"] = {
            "namespace": "frontier_exploration",
            "activation": "explicit_genre_distance_4",
            "persistence": "none",
            "engine_authority": "unchanged",
            "slate_contract": {
                "minimum_distinct_genre_families": min(3, req.n_results),
                "candidate_target_genre_families": 4,
                "maximum_final_records_per_genre_family": 2,
                "minimum_route_types": min(3, req.n_results),
                "fallback": "Keep only evidence-supported routes; never invent breadth to satisfy the quota.",
            },
            "guide": FRONTIER_GENRE_GUIDE,
        }
    return payload


def generate_album_candidates(req: RecRequest, intent: dict, seeds: list[dict],
                              vocab: dict[str, set[str]], label_context: list[dict],
                              existing_entities: list[dict]) -> list[dict]:
    """Use the brain-engine context to scout structured candidates from model knowledge."""
    descriptors = sorted(set().union(*vocab.values()))
    schema = {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "maxItems": 15,
                "items": {
                    "type": "object",
                    "properties": {
                        "artist": {"type": "string"},
                        "album": {"type": "string"},
                        "year": {"type": ["integer", "null"]},
                        "connection": {"type": "string"},
                        "matched_descriptors": {
                            "type": "array",
                            "items": {"type": "string", "enum": descriptors},
                            "maxItems": 6,
                        },
                        "scenes": {
                            "type": "array",
                            "items": {"type": "string", "enum": sorted(vocab["scene"])},
                            "maxItems": 2,
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "visibility": {
                            "type": "string",
                            "enum": ["familiar", "mixed", "underheard", "unknown"],
                        },
                        "genre_family": {
                            "type": "string",
                            "description": "One broad destination family, such as jazz, salsa, pop, punk, electronic, folk, soul/funk, dub, or metal.",
                        },
                        "frontier_route": {
                            "type": "string",
                            "enum": ["adjacent_step", "bridge_chain", "shared_property_leap", "lineage_route", "scene_route"],
                        },
                    },
                    "required": ["artist", "album", "year", "connection", "matched_descriptors", "scenes",
                                 "confidence", "visibility", "genre_family", "frontier_route"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }
    brain_brief = candidate_scout_payload(req, intent, seeds, label_context, existing_entities)
    output = openai_json_response(
        CANDIDATE_SCOUT_INSTRUCTION,
        json.dumps(brain_brief, ensure_ascii=False, indent=2),
        "album_candidate_slate",
        schema,
        4200,
    )
    return output["candidates"]


def research_album_candidates(req: RecRequest, candidates: list[dict],
                              label_context: list[dict]) -> dict:
    """Research provisional bridges in one web-enabled pass before identity verification."""
    if not candidates:
        return {"findings": [], "rabbit_holes": {"labels": [], "scenes": []}, "sources": []}
    finding = {
        "type": "object",
        "properties": {
            "candidate_index": {"type": "integer", "minimum": 0},
            "verdict": {"type": "string", "enum": [
                "supported", "partially_supported", "unsupported", "contradicted",
                "insufficient_evidence",
            ]},
            "bridge_summary": {"type": "string"},
            "supported_requirements": {
                "type": "array", "items": {"type": "string"}, "maxItems": 5,
            },
            "limitations": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            "visibility": {
                "type": "string", "enum": ["familiar", "underheard", "unknown"],
            },
            "release_year": {"type": ["integer", "null"]},
            "genres": {
                "type": "array", "items": {"type": "string"}, "maxItems": 3,
            },
            "sound_preview": {"type": "string"},
        },
        "required": ["candidate_index", "verdict", "bridge_summary",
                     "supported_requirements", "limitations", "visibility", "release_year",
                     "genres", "sound_preview"],
        "additionalProperties": False,
    }
    route = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "why": {"type": "string"}},
        "required": ["name", "why"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {
            "findings": {"type": "array", "items": finding, "maxItems": 15},
            "rabbit_holes": {
                "type": "object",
                "properties": {
                    "labels": {"type": "array", "items": route, "maxItems": 3},
                    "scenes": {"type": "array", "items": route, "maxItems": 2},
                },
                "required": ["labels", "scenes"],
                "additionalProperties": False,
            },
        },
        "required": ["findings", "rabbit_holes"],
        "additionalProperties": False,
    }
    payload = {
        "listener_brief": req.brief,
        "reference_record": model_values(req.reference),
        "calibration": model_values(req.calibration),
        "answers": [model_values(answer) for answer in req.calibration_answers],
        "genre_distance": genre_distance(req),
        "provisional_candidates": [
            {"index": index, **candidate} for index, candidate in enumerate(candidates)
        ],
        "allowed_curated_label_routes": label_context,
    }
    output, sources = openai_web_json_response(
        RESEARCHER_INSTRUCTION,
        json.dumps(payload, ensure_ascii=False, indent=2),
        "candidate_context_research",
        schema,
        5200,
    )
    def clean_research_copy(value: str) -> str:
        value = re.sub(r"\s*\(\[[^\]]+\]\(https?://[^)]+\)\)", "", str(value))
        value = re.sub(r"\s*\[([^\]]+)\]\(https?://[^)]+\)", r" \1", value)
        return value.strip()

    for item in output["findings"]:
        item["bridge_summary"] = clean_research_copy(item["bridge_summary"])
        item["genres"] = [clean_research_copy(value) for value in item.get("genres", [])][:3]
        item["sound_preview"] = clean_research_copy(item.get("sound_preview", ""))
        item["supported_requirements"] = [
            clean_research_copy(value) for value in item["supported_requirements"]
        ]
        item["limitations"] = [clean_research_copy(value) for value in item["limitations"]]
    allowed_labels = {item["name"].casefold(): item["name"] for item in label_context}
    output["rabbit_holes"]["labels"] = [
        {**item, "name": allowed_labels[item["name"].casefold()],
         "why": clean_research_copy(item["why"]),
         "provenance": {"source": "curator", "confidence": 0.8}}
        for item in output["rabbit_holes"]["labels"]
        if item["name"].casefold() in allowed_labels
    ][:3]
    output["rabbit_holes"]["scenes"] = [
        {**item, "why": clean_research_copy(item["why"]),
         "provenance": {"source": "llm_inferred", "confidence": 0.7}}
        for item in output["rabbit_holes"]["scenes"]
    ][:2]
    output["sources"] = sources
    return output


def verify_release_group(candidate: dict) -> Optional[dict]:
    """Resolve one model-proposed album against MusicBrainz before it can be displayed."""
    artist = candidate["artist"].replace('"', "")
    album = candidate["album"].replace('"', "")
    proposed_year = candidate.get("year")

    def year_is_consistent(resolved_year: Optional[int]) -> bool:
        if proposed_year is None or resolved_year is None:
            return True
        return abs(int(proposed_year) - int(resolved_year)) <= 1

    if DB_PATH.exists():
        corpus = db()
        cached_corpus = corpus.execute(
            """SELECT artists.name AS artist, albums.title AS album, albums.year,
                      albums.rg_mbid, 1.0 AS verification_score
               FROM albums JOIN artists ON artists.id=albums.artist_id
               WHERE artists.name=? COLLATE NOCASE AND albums.title=? COLLATE NOCASE
                     AND length(albums.rg_mbid)>0""",
            (artist, album),
        ).fetchone()
        corpus.close()
        if cached_corpus and year_is_consistent(cached_corpus["year"]):
            return {**candidate, **dict(cached_corpus), "identity_source": "musicbrainz_corpus"}
    runtime = runtime_db()
    cached = runtime.execute(
        """SELECT artist, album, year, rg_mbid, verification_score
           FROM identity_cache WHERE normalized_artist=? AND normalized_album=?""",
        (normalized_identity(artist), normalized_identity(album)),
    ).fetchone()
    runtime.close()
    if cached and year_is_consistent(cached["year"]):
        return {**candidate, **dict(cached), "identity_source": "musicbrainz_cache"}
    if not USER_AGENT:
        return None
    try:
        response = musicbrainz_get(
            "release-group/",
            {"query": f'artist:"{artist}" AND releasegroup:"{album}"',
             "fmt": "json", "limit": 5},
            timeout=12,
        )
        response.raise_for_status()
        hits = response.json().get("release-groups", [])
    except Exception:
        return None
    wanted_artist = normalized_identity(artist)
    wanted_album = normalized_identity(album)
    for hit in hits:
        credits = hit.get("artist-credit", [])
        credited_names = {
            normalized_identity(str(credit.get("artist", {}).get("name", "")))
            for credit in credits if isinstance(credit, dict)
        }
        title = str(hit.get("title", ""))
        score = int(hit.get("score", 0))
        if score < 95 or wanted_artist not in credited_names:
            continue
        if normalized_identity(title) != wanted_album:
            continue
        first_date = str(hit.get("first-release-date", ""))
        year = int(first_date[:4]) if re.match(r"^\d{4}", first_date) else None
        if not year_is_consistent(year):
            continue
        canonical_artist = next(
            (credit.get("artist", {}).get("name") for credit in credits
             if isinstance(credit, dict)
             and normalized_identity(str(credit.get("artist", {}).get("name", ""))) == wanted_artist),
            artist,
        )
        resolved = {
            **candidate,
            "artist": canonical_artist,
            "album": title,
            "year": year,
            "rg_mbid": hit["id"],
            "verification_score": score / 100,
            "identity_source": "musicbrainz_live",
        }
        runtime = runtime_db()
        runtime.execute(
            """INSERT OR REPLACE INTO identity_cache
               (normalized_artist, normalized_album, artist, album, year, rg_mbid,
                verification_score, verified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (normalized_identity(artist), normalized_identity(album), canonical_artist, title,
             year, hit["id"], score / 100, int(time.time())),
        )
        runtime.commit()
        runtime.close()
        return resolved
    return None


def musicbrainz_release_labels(release_group_mbid: str) -> list[str]:
    """Return up to three release labels credited by MusicBrainz editions."""
    if not USER_AGENT or not release_group_mbid:
        return []
    try:
        response = musicbrainz_get(
            "release/",
            {"release-group": release_group_mbid, "inc": "labels",
             "fmt": "json", "limit": 10},
            timeout=12,
        )
        response.raise_for_status()
        names = []
        for release in response.json().get("releases", []):
            for item in release.get("label-info", []):
                name = str((item.get("label") or {}).get("name", "")).strip()
                if name and name.casefold() not in {value.casefold() for value in names}:
                    names.append(name)
                    if len(names) >= 3:
                        return names
        return names
    except Exception:
        return []


def verified_candidate_result(candidate: dict) -> dict:
    """Convert one independently verified candidate into the public recommendation contract."""
    confidence = max(0.0, min(float(candidate["confidence"]), 1.0))
    descriptors = list(dict.fromkeys(candidate["matched_descriptors"]))
    contribution = round(2.4 * confidence + 0.35 * len(descriptors), 3)
    research = candidate.get("research") or {}
    fit_claim = research.get("bridge_summary") or candidate["connection"]
    fit_confidence = confidence
    if research.get("verdict") == "partially_supported":
        fit_confidence = min(fit_confidence, 0.68)
    reasons = [
        {
            "relationship_type": "researched_inferred_fit",
            "claim": fit_claim,
            "provenance": {"source": "llm_inferred", "confidence": fit_confidence},
            "evidence_sources": candidate.get("research_sources", []),
            "rank_contribution": contribution,
        },
        {
            "relationship_type": "entity_verification",
            "claim": "Album identity independently verified by MusicBrainz",
            "provenance": {"source": "musicbrainz",
                           "confidence": candidate["verification_score"]},
            "rank_contribution": 0.0,
        },
    ]
    return {
        "entity": {
            "type": "album",
            "artist": candidate["artist"],
            "title": candidate["album"],
            "year": candidate["year"],
            "rg_mbid": candidate["rg_mbid"],
            "corpus_status": "verified_discovery",
        },
        "match": {
            "score": round(contribution, 2),
            "matched_descriptors": descriptors,
            "novelty_tier": candidate["visibility"],
            "score_breakdown": [{
                "feature": "brain_guided_candidate_fit",
                "detail": ",".join(descriptors),
                "base_weight": 2.4,
                "confidence": confidence,
                "contribution": contribution,
                "source": "llm_inferred",
            }],
            "explanation_fidelity": 1.0,
            "annotation_completeness": {
                "status": "researched_inference" if research else "machine_inferred",
                "note": ("Contextual fit was researched at query time and remains an inference; "
                         "entity identity is independently verified."),
            },
        },
        "context": {"artist_arc": None, "evidence": {"album": [], "track": [], "scene": []}},
        "descriptor_groups": {
            "sound_and_mood": [
                value for value in descriptors if value not in set(candidate.get("scenes", []))
            ][:5],
            "scenes": list(dict.fromkeys(candidate.get("scenes", [])))[:2],
            "genres": list(dict.fromkeys(research.get("genres", [])))[:3],
            "sound_preview": research.get("sound_preview", ""),
        },
        "frontier_context": {
            "genre_family": candidate.get("genre_family", ""),
            "route": candidate.get("frontier_route", ""),
            "provenance": {"source": "llm_inferred", "confidence": confidence},
        } if candidate.get("genre_family") or candidate.get("frontier_route") else None,
        "labels": [],
        "research": research,
        "visual_match": None,
        "reasons": reasons,
    }


def result_visibility(result: dict) -> str:
    """Normalize both curator roles and researched discoveries to one public control."""
    value = str(result.get("match", {}).get("novelty_tier", "unknown")).casefold()
    if value in {"underheard", "deep_cut"}:
        return "underheard"
    if value in {"familiar", "anchor", "bridge", "core"}:
        return "familiar"
    return "unknown"


def normalized_genre_family(value: str) -> str:
    """Collapse genre labels into broad families used only for slate diversity."""
    folded = normalized_identity(value)
    families = (
        ("salsa", ("salsa", "son", "mambo", "timba")),
        ("jazz", ("jazz", "free improvisation", "spiritual jazz")),
        ("soul/funk", ("soul", "funk", "r b", "rhythm and blues")),
        ("reggae/dub", ("reggae", "dub", "dancehall", "ska")),
        ("hip-hop", ("hip hop", "rap", "grime", "trap")),
        ("electronic", ("electronic", "techno", "house", "ambient", "industrial", "trip hop")),
        ("folk/country", ("folk", "country", "americana", "bluegrass")),
        ("metal", ("metal", "doom", "sludge")),
        ("punk", ("punk", "deathrock", "hardcore")),
        ("pop", ("pop", "new wave", "synthpop")),
        ("Latin", ("latin", "cumbia", "bolero", "bossa", "tango")),
        ("rock", ("rock", "blues", "garage", "psychedelic")),
        ("classical/modern composition", ("classical", "chamber", "minimalism", "composition")),
    )
    for family, signals in families:
        if any(signal in folded for signal in signals):
            return family
    return folded or "unknown"


def candidate_genre_family(candidate: dict) -> str:
    return normalized_genre_family(candidate.get("genre_family", ""))


def result_genre_family(result: dict) -> str:
    frontier = result.get("frontier_context") or {}
    explicit = normalized_genre_family(frontier.get("genre_family", ""))
    if explicit != "unknown":
        return explicit
    groups = result.get("descriptor_groups", {})
    genres = groups.get("genres", [])
    return normalized_genre_family(genres[0] if genres else "")


def diversify_frontier_research_pool(candidates: list[dict], limit: int) -> list[dict]:
    """Research distinct Frontier families before spending slots on repeated moves."""
    diverse, remainder, seen = [], [], set()
    for candidate in candidates:
        family = candidate_genre_family(candidate)
        if family not in seen and family != "unknown":
            diverse.append(candidate)
            seen.add(family)
        else:
            remainder.append(candidate)
    return (diverse + remainder)[:limit]


def enforce_frontier_genre_diversity(results: list[dict], pool: list[dict],
                                     preference: str, n_results: int) -> list[dict]:
    """Meet the Frontier family target when verified, evidence-backed options permit it."""
    selected = results[:n_results]
    target = min(3, n_results, len({result_genre_family(item) for item in pool}
                                   - {"unknown"}))
    while len({result_genre_family(item) for item in selected} - {"unknown"}) < target:
        selected_families = {result_genre_family(item) for item in selected}
        replacement = next(
            (item for item in pool
             if item not in selected and result_genre_family(item) not in selected_families
             and result_genre_family(item) != "unknown"),
            None,
        )
        if not replacement:
            break
        counts = {family: sum(result_genre_family(item) == family for item in selected)
                  for family in selected_families}
        replace_index = next(
            (index for index in range(len(selected) - 1, -1, -1)
             if counts.get(result_genre_family(selected[index]), 0) > 1
             and ((preference or "any").casefold() not in {"mixed", "underheard"}
                  or result_visibility(selected[index]) == result_visibility(replacement))),
            None,
        )
        if replace_index is None:
            break
        selected[replace_index] = replacement
    return selected


def enforce_visibility(results: list[dict], pool: list[dict], preference: str,
                       n_results: int) -> list[dict]:
    """Make visibility a slate requirement instead of a small ranking decoration."""
    preference = (preference or "any").casefold()
    if preference == "underheard":
        return [item for item in results if result_visibility(item) == "underheard"][:n_results]
    selected = results[:n_results]
    if preference != "mixed":
        return selected
    for required in ("underheard", "familiar"):
        if any(result_visibility(item) == required for item in selected):
            continue
        replacement = next(
            (item for item in pool if result_visibility(item) == required and item not in selected),
            None,
        )
        if not replacement or not selected:
            continue
        replace_index = len(selected) - 1
        if required == "familiar":
            underheard_indices = [
                index for index, item in enumerate(selected)
                if result_visibility(item) == "underheard"
            ]
            if len(underheard_indices) == 1 and len(selected) > 1:
                replace_index = next(
                    (index for index in range(len(selected) - 1, -1, -1)
                     if index != underheard_indices[0]),
                    replace_index,
                )
        selected[replace_index] = replacement
    return selected


def deterministic_slate(pool: list[dict], preference: str, n_results: int) -> list[dict]:
    """Evidence-only fallback when the comparative model pass is unavailable."""
    def strength(item: dict) -> tuple[float, int, str, str]:
        relevance = [
            reason for reason in item.get("reasons", [])
            if reason.get("relationship_type") != "entity_verification"
        ]
        confidence = max(
            (float(reason.get("provenance", {}).get("confidence", 0)) for reason in relevance),
            default=0.0,
        )
        return (-confidence, -len(item.get("match", {}).get("matched_descriptors", [])),
                item["entity"]["artist"], item["entity"]["title"])

    ranked = sorted(pool, key=strength)
    if (preference or "").casefold() == "underheard":
        ranked = [item for item in ranked if result_visibility(item) == "underheard"]
    return enforce_visibility(ranked, ranked, preference, n_results)


def select_recommendation_slate(req: RecRequest, candidates: list[dict]) -> list[dict]:
    """Run a separate comparative pass; corpus membership never reserves a position."""
    if not candidates:
        return []
    fallback = deterministic_slate(candidates, req.visibility or "any", req.n_results)
    if genre_distance(req) == 4:
        fallback = enforce_frontier_genre_diversity(
            fallback, candidates, req.visibility or "any", req.n_results,
        )
    if not OPENAI_KEY:
        return fallback
    candidate_payload = [{
        "rg_mbid": item["entity"]["rg_mbid"],
        "artist": item["entity"]["artist"],
        "album": item["entity"]["title"],
        "year": item["entity"]["year"],
        "visibility": result_visibility(item),
        "descriptors": item.get("match", {}).get("matched_descriptors", []),
        "genres": item.get("descriptor_groups", {}).get("genres", []),
        "genre_family": result_genre_family(item),
        "frontier_route": (item.get("frontier_context") or {}).get("route", ""),
        "sound_preview": item.get("descriptor_groups", {}).get("sound_preview", ""),
        "evidence": [{
            "claim": reason["claim"],
            "source": reason["provenance"]["source"],
            "confidence": reason["provenance"]["confidence"],
        } for reason in item.get("reasons", [])
         if reason.get("relationship_type") != "entity_verification"],
    } for item in candidates]
    try:
        output = openai_json_response(
            "You are the final comparative selector in a conversational music-discovery process. "
            "Compare every candidate against the exact calibrated bridge. No candidate "
            "receives a place because it came from a curated corpus or from live discovery. Preserve "
            "the requested visibility: underheard means select only underheard artists; mixed means "
            "include at least one underheard and one recognizable artist when evidence-backed examples "
            "of both are available. When genre_distance is 4, select at least three distinct broad "
            "genre families for a five-record slate when the verified evidence supports them, with "
            "no more than two records representing the same move. Select "
            "a varied slate only after intent fidelity. Use only supplied evidence. Think through the "
            "comparison before returning the machine-readable selection.",
            json.dumps({
                "brief": req.brief,
                "reference_record": model_values(req.reference),
                "calibration": model_values(req.calibration),
                "answers": [model_values(answer) for answer in req.calibration_answers],
                "genre_distance": genre_distance(req),
                "visibility": req.visibility or "any",
                "requested_count": req.n_results,
                "candidates": candidate_payload,
            }, ensure_ascii=False, indent=2),
            "final_recommendation_slate",
            {
                "type": "object",
                "properties": {
                    "selected_rg_mbids": {
                        "type": "array", "items": {
                            "type": "string",
                            "enum": [item["entity"]["rg_mbid"] for item in candidates],
                        },
                        "maxItems": req.n_results,
                    },
                },
                "required": ["selected_rg_mbids"],
                "additionalProperties": False,
            },
            1200,
        )
    except Exception as exc:
        print(f"Comparative slate selection failed ({exc}); using evidence fallback")
        return fallback
    by_id = {item["entity"]["rg_mbid"]: item for item in candidates}
    selected = []
    for mbid in output["selected_rg_mbids"]:
        item = by_id.get(mbid)
        if item and item not in selected:
            selected.append(item)
    if len(selected) < req.n_results:
        selected.extend(item for item in fallback if item not in selected)
    selected = enforce_visibility(selected, candidates, req.visibility or "any", req.n_results)
    if genre_distance(req) == 4:
        selected = enforce_frontier_genre_diversity(
            selected, candidates, req.visibility or "any", req.n_results,
        )
    return selected


def apply_freshness(results: list[dict], req: RecRequest, signature: str) -> list[dict]:
    """Prefer unseen records without turning previous exposure into a permanent ban."""
    if not req.listener_id or not results:
        selected = results[:req.n_results]
        discovered = next(
            (item for item in results
             if item["entity"]["corpus_status"] == "verified_discovery"),
            None,
        )
        if discovered and selected and not any(
                item["entity"]["corpus_status"] == "verified_discovery" for item in selected):
            selected[-1] = discovered
        return selected
    runtime = runtime_db()
    rows = runtime.execute(
        """SELECT rg_mbid, intent_signature, journey_id, COUNT(*) AS exposure_count,
                  MAX(shown_at) AS last_shown
           FROM recommendation_exposures WHERE listener_id=?
           GROUP BY rg_mbid, intent_signature, journey_id""",
        (req.listener_id,),
    ).fetchall()
    runtime.close()
    history: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        history.setdefault(row["rg_mbid"], []).append(row)
    ranked = []
    for position, result in enumerate(results):
        mbid = result["entity"].get("rg_mbid") or ""
        exposures = history.get(mbid, [])
        if req.journey_id and any(row["journey_id"] == req.journey_id for row in exposures):
            continue
        same_intent = sum(
            int(row["exposure_count"]) for row in exposures
            if row["intent_signature"] == signature
        )
        other_intent = sum(
            int(row["exposure_count"]) for row in exposures
            if row["intent_signature"] != signature
        )
        penalty = min(8.0, same_intent * 3.0 + other_intent * 0.18)
        adjusted_position = position + penalty
        result["freshness"] = {
            "previously_recommended": bool(exposures),
            "same_intent_exposures": same_intent,
            "other_intent_exposures": other_intent,
            "ranking_penalty": round(penalty, 2),
        }
        ranked.append((adjusted_position, position, result))
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected, returning = [], 0
    for _, _, result in ranked:
        is_returning = result["freshness"]["previously_recommended"]
        if is_returning and returning >= 1:
            continue
        selected.append(result)
        returning += int(is_returning)
        if len(selected) >= req.n_results:
            break
    if len(selected) < req.n_results:
        selected_ids = {item["entity"].get("rg_mbid") for item in selected}
        for _, _, result in ranked:
            if result["entity"].get("rg_mbid") in selected_ids:
                continue
            selected.append(result)
            if len(selected) >= req.n_results:
                break
    discovered = next(
        (item for _, _, item in ranked
         if item["entity"]["corpus_status"] == "verified_discovery"),
        None,
    )
    if discovered and selected and not any(
            item["entity"]["corpus_status"] == "verified_discovery" for item in selected):
        selected[-1] = discovered
    return selected


def record_exposures(results: list[dict], req: RecRequest, signature: str) -> None:
    if not req.listener_id or not req.journey_id:
        return
    runtime = runtime_db()
    now = int(time.time())
    for result in results:
        mbid = result["entity"].get("rg_mbid") or ""
        if not mbid:
            continue
        reason_text = " ".join(reason["claim"] for reason in result.get("reasons", []))
        reason_hash = hashlib.sha256(reason_text.encode("utf-8")).hexdigest()
        runtime.execute(
            """INSERT INTO recommendation_exposures
               (listener_id, journey_id, rg_mbid, intent_signature, reason_signature, shown_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (req.listener_id, req.journey_id, mbid, signature, reason_hash, now),
        )
    runtime.commit()
    runtime.close()


def fallback_intent_title(intent: dict) -> str:
    """Build a compact title without repeating the listener's full request."""
    terms = intent.get("moods", []) + intent.get("sonic_traits", []) + intent.get("scenes", [])
    if not terms:
        return "A new listening path"
    return " · ".join(term.replace("-", " ") for term in terms[:3]).title()


def requires_grounded_reference(req: RecRequest, seeds: list[dict]) -> bool:
    """Identify comparison asks the curated scorer cannot ground on its own."""
    relational = bool(req.reference.album.strip()) or bool(re.search(
        r"\b(similar\s+(?:\w+\s+){0,5}(?:to|as)|like|same\s+(?:\w+\s+){0,5}as|"
        r"reminds?\s+me\s+of)\b",
        req.brief.casefold(),
    ))
    return relational and not any(seed.get("status") == "in_corpus" for seed in seeds)


# ---------------------------------------------------------------------------
# Retrieval + deterministic scoring
# ---------------------------------------------------------------------------
def build_analysis_report(req: RecRequest, intent: dict, coverage: dict, seeds: list[dict],
                          ledger: list[dict], results: list[dict], discovery: dict,
                          scout_payload: Optional[dict] = None) -> dict:
    """Build the reusable, inspectable decision record for one recommendation ask."""
    selected_ids = {
        result["entity"].get("rg_mbid") for result in results
        if result["entity"].get("rg_mbid")
    }
    selected_order = {
        result["entity"].get("rg_mbid"): index
        for index, result in enumerate(results, 1)
    }
    for item in ledger:
        mbid = item.get("rg_mbid")
        if mbid in selected_ids:
            item["disposition"] = "final_selection"
            item["final_rank"] = selected_order[mbid]
        elif item["disposition"] in {"curated_reserve", "verified_discovery_reserve"}:
            item["disposition"] = "displaced_before_final_selection"
        contributions = [
            component for component in item.get("score_breakdown", [])
            if component.get("contribution", 0) > 0
        ]
        relevance_features = {
            "descriptor_match", "label_catalog_match", "seed_bucket", "fan_overlap",
            "brain_guided_candidate_fit",
        }
        relevance = [
            component for component in contributions
            if component.get("feature") in relevance_features
        ]
        direct_intent = [
            component for component in relevance
            if component.get("feature") in {
                "descriptor_match", "label_catalog_match", "brain_guided_candidate_fit"
            }
        ]
        risk_flags = []
        if item["disposition"] not in {
                "excluded_by_hard_constraint", "rejected_no_relevance_evidence"} and not direct_intent:
            risk_flags.append(
                "weak_bridge: qualified without a direct descriptor, label-territory, or researched fit"
            )
        if item.get("matched_descriptors") == [] and item.get("score", 0) and item["score"] > 0:
            risk_flags.append("zero_requested_descriptor_matches")
        item["risk_flags"] = risk_flags
        item["game_comparison"] = {
            "intent_fidelity_runtime_proxy": round(
                sum(c["contribution"] for c in direct_intent), 3
            ),
            "evidence_confidence": (
                round(sum(c.get("confidence", 0) for c in relevance) / len(relevance), 3)
                if relevance else None
            ),
            "discovery_distance": genre_distance(req),
            "visibility": item.get("visibility", "unknown"),
            "bridge_legibility": bool(item.get("decision_reasons")),
            "diversity_contribution": (
                "selected" if item["disposition"] == "final_selection" else "not_measured"
            ),
        }
    dispositions: dict[str, int] = {}
    for item in ledger:
        dispositions[item["disposition"]] = dispositions.get(item["disposition"], 0) + 1
    execution_stages = [
        {
            "stage": "interpret_ask",
            "instruction": (
                "Preserve the raw brief; map only recognized controlled-vocabulary terms; "
                "optionally add only approved external-taxonomy crosswalk mappings."
            ),
            "input": req.brief,
            "output": intent,
        },
        {
            "stage": "pull_initial_corpus_list",
            "instruction": (
                "Read every verified corpus album, apply year/bucket/seed-artist/mood hard constraints, "
                "then require at least one relevance signal: descriptor, curated label territory, "
                "seed bucket, or optional Last.fm fan overlap."
            ),
            "query": (
                "SELECT album identity, year, bucket, role, corpus status, and artist "
                "FROM albums JOIN artists; constraints are applied explicitly and logged per album"
            ),
        },
        {
            "stage": "score_and_select",
            "instruction": (
                "Sum provenance-labeled score components; bonuses cannot create relevance. Sort by "
                "score, year, and title; apply score-preserving slate diversity, one album per artist, "
                "then compare all surviving candidates without reserving positions by inventory source. "
                "Apply the requested visibility as a slate requirement, then listener-history freshness."
            ),
            "scoring_policy": SCORING_POLICY_VERSION,
        },
    ]
    if not req.features.corpus_candidates:
        execution_stages = [execution_stages[0], {
            "stage": "listener_discovery_mode",
            "instruction": (
                "Skip corpus album retrieval and scoring. The calibration corpus supplies no runtime "
                "inventory and reserves no recommendation positions."
            ),
        }]
    if scout_payload is not None:
        execution_stages.extend([
            {"stage": "outside_candidate_generation",
             "instruction": CANDIDATE_SCOUT_INSTRUCTION, "input": scout_payload},
            {"stage": "outside_candidate_research",
             "instruction": RESEARCHER_INSTRUCTION,
             "input": {"proposals_are_provisional": True,
                       "supported_or_partial_required_for_identity_check": True}},
            {"stage": "musicbrainz_identity_verification",
             "instruction": (
                 "Only exact normalized artist/title release-group matches with consistent first-release "
                 "years may enter the displayed slate."
             )},
            {"stage": "comparative_slate_selection",
             "instruction": (
                 "Compare every evidence-backed survivor against the calibrated bridge. Corpus and live "
                 "discovery receive no reserved slots; visibility is enforced at slate level."
             )},
        ])
    return {
        "schema_version": "1.0",
        "purpose": "Explain the complete candidate funnel for this ask, including non-selections.",
        "ask_analysis": {
            "raw_request": model_values(req), "controlled_intent": intent,
            "intent_coverage": coverage, "resolved_seeds": seeds,
        },
        "execution_recipe": execution_stages,
        "candidate_summary": {"total_considered": len(ledger), "by_disposition": dispositions},
        "candidates": ledger,
        "final_selection_logic": {
            "requested_count": req.n_results,
            "selected_count": len(results),
            "selection_order": [
                {"rank": index, "artist": result["entity"]["artist"],
                 "album": result["entity"]["title"], "score": result["match"]["score"],
                 "reasons": result["reasons"]}
                for index, result in enumerate(results, 1)
            ],
            "outside_discovery": discovery,
        },
        "game_comparison_guide": {
            "reference_file": "research/taxonomies/recommendation-calibration-cases.csv",
            "axes": ["intent_fidelity_runtime_proxy", "evidence_confidence", "discovery_distance",
                     "visibility", "bridge_legibility", "diversity_contribution"],
            "warning": (
                "Game cases are calibration evidence, not unseen holdout results. Intent fidelity is "
                "a runtime proxy counting only direct descriptor, label-territory, or researched-fit "
                "contributions; bonuses and broad seed-bucket similarity are excluded. These values "
                "are not curator ratings."
            ),
        },
    }


def recommend(req: RecRequest) -> dict:
    con = db()
    vocab = load_vocab(con)
    intent = parse_brief(req.brief, vocab)
    journey_signature = intent_signature(req, intent)
    external = None
    external_axes = {axis: [] for axis in ("atmosphere", "form", "lyrics", "mood", "style", "technique", "theme", "vocals")}
    crosswalk = {}
    if req.features.external_taxonomy:
        external = load_external_taxonomy(EXTERNAL_TAXONOMY_PATH)
        crosswalk = load_approved_crosswalk(CROSSWALK_PATH, vocab, external)
        if req.features.axis_inference:
            external_axes = infer_external_axes(req.brief, external)
            for values in external_axes.values():
                for assignment in values:
                    for mapped in crosswalk.get(assignment["descriptor_id"], []):
                        key = {"mood": "moods", "sonic_trait": "sonic_traits", "scene": "scenes"}[mapped["kind"]]
                        if mapped["slug"] not in intent[key]:
                            intent[key].append(mapped["slug"])
    coverage_report = intent_coverage(intent)
    hc = req.hard_constraints

    seeds = [resolve_seed(con, s.artist) for s in req.seeds]
    seed_buckets = {b for s in seeds for b in s["buckets"]}
    seed_artist_ids = {s["artist_id"] for s in seeds if s.get("artist_id")}
    candidate_ledger: list[dict] = []
    candidate_audit: dict[int, dict] = {}

    # Last.fm fan-overlap: which corpus artists do listeners of the seeds also play?
    fan_overlap_ids: dict[int, str] = {}
    if req.use_lastfm:
        for s in seeds:
            for name in lastfm_similar_artists(s["artist"]):
                row = con.execute("SELECT id FROM artists WHERE name=? COLLATE NOCASE",
                                  (name,)).fetchone()
                if row:
                    fan_overlap_ids[row["id"]] = s["artist"]

    wanted = set(intent["moods"] + intent["sonic_traits"] + intent["scenes"])

    # Structural filters are evaluated explicitly so rejected albums remain visible
    # in the request analysis report.
    sql = """SELECT albums.id, albums.title, albums.year, albums.bucket, albums.region,
                    albums.role, albums.corpus_status, albums.rg_mbid,
                    artists.name AS artist, artists.id AS artist_id
             FROM albums JOIN artists ON artists.id = albums.artist_id"""
    if not req.features.corpus_candidates:
        sql += " WHERE 1=0"
    params: list = []

    scored = []
    for album in con.execute(sql, params):
        audit = {
            "source_path": "curated_corpus", "artist": album["artist"],
            "album": album["title"], "year": album["year"], "rg_mbid": album["rg_mbid"],
            "bucket": album["bucket"], "corpus_status": album["corpus_status"],
            "visibility": album["role"],
            "disposition": "eligible_for_scoring", "decision_reasons": [],
            "score": None, "base_rank": None, "score_breakdown": [],
            "matched_descriptors": [],
        }
        candidate_ledger.append(audit)
        candidate_audit[album["id"]] = audit
        if hc.year_min and (album["year"] is None or album["year"] < hc.year_min):
            audit.update(disposition="excluded_by_hard_constraint",
                         decision_reasons=[f"year below minimum {hc.year_min}"])
            continue
        if hc.year_max and (album["year"] is None or album["year"] > hc.year_max):
            audit.update(disposition="excluded_by_hard_constraint",
                         decision_reasons=[f"year above maximum {hc.year_max}"])
            continue
        if hc.buckets and album["bucket"] not in hc.buckets:
            audit.update(disposition="excluded_by_hard_constraint",
                         decision_reasons=["bucket not allowed"])
            continue
        if hc.exclude_seed_artists and album["artist_id"] in seed_artist_ids:
            audit.update(disposition="excluded_by_hard_constraint",
                         decision_reasons=["seed artist excluded"])
            continue
        tags = {r["slug"]: r["kind"] for r in con.execute(
            "SELECT tags.slug, tags.kind FROM album_tags JOIN tags ON tags.id=album_tags.tag_id "
            "WHERE album_tags.album_id=?", (album["id"],))}
        if hc.exclude_moods and any(m in tags for m in hc.exclude_moods):
            audit.update(disposition="excluded_by_hard_constraint",
                         decision_reasons=["matched an excluded mood"])
            continue  # hard exclusion

        matched = sorted(wanted & set(tags))
        label_matches = label_matches_for_brief(con, album["id"], req.brief)
        score, reasons, breakdown = 0.0, [], []
        relevance_reasons = 0
        for slug in matched:
            component = score_component("descriptor_match", 0.85, slug)
            score += component["contribution"]
            breakdown.append(component)
            relevance_reasons += 1
            reasons.append({"relationship_type": f"similar_by_{'mood' if tags[slug]=='mood' else tags[slug]}",
                            "claim": f"Curator-tagged '{slug}'",
                            "provenance": {"source": "curator", "confidence": 0.85},
                            "rank_contribution": component["contribution"]})
        for label_match in label_matches:
            confidence = min(label_match["label_confidence"], label_match["link_confidence"])
            detail = f"{label_match['name']}:{label_match['kind']}:{label_match['value']}"
            component = score_component("label_catalog_match", confidence, detail)
            component["source"] = "curator+musicbrainz"
            score += component["contribution"]
            breakdown.append(component)
            relevance_reasons += 1
            reasons.append({
                "relationship_type": "similar_by_label_territory",
                "claim": f"Released by {label_match['name']}, whose curated {label_match['kind']} territory includes '{label_match['value']}'",
                "provenance": {"source": "curator", "confidence": confidence},
                "evidence": [
                    {"claim": f"Release label: {label_match['name']}", "source": "musicbrainz",
                     "confidence": label_match["link_confidence"]},
                    {"claim": f"Label {label_match['kind']}: {label_match['value']}", "source": "curator",
                     "confidence": label_match["label_confidence"]},
                ],
                "rank_contribution": component["contribution"],
            })
        if album["bucket"] in seed_buckets:
            component = score_component("seed_bucket", 0.7, album["bucket"])
            score += component["contribution"]
            breakdown.append(component)
            relevance_reasons += 1
            reasons.append({"relationship_type": "similar_by_scene",
                            "claim": f"Same corpus scene bucket ({album['bucket']}) as a seed artist",
                            "provenance": {"source": "curator", "confidence": 0.7},
                            "rank_contribution": component["contribution"]})
        if album["artist_id"] in fan_overlap_ids:
            component = score_component("fan_overlap", 0.6, fan_overlap_ids[album["artist_id"]])
            score += component["contribution"]
            breakdown.append(component)
            relevance_reasons += 1
            reasons.append({"relationship_type": "similar_by_fan_overlap",
                            "claim": f"Last.fm listeners of {fan_overlap_ids[album['artist_id']]} also play this artist",
                            "provenance": {"source": "last_fm", "confidence": 0.6},
                            "rank_contribution": component["contribution"]})
        if req.novelty == "non_obvious":
            feature = "deep_cut" if album["role"] == "deep_cut" else "obvious_novelty_penalty"
            component = score_component(feature, 1.0, album["role"])
            score += component["contribution"]
            breakdown.append(component)
            if component["contribution"] > 0:
                reasons.append({"relationship_type": "novelty_preference",
                                "claim": "Curator-classified as a deep cut",
                                "provenance": {"source": "curator", "confidence": 1.0},
                                "rank_contribution": component["contribution"]})
        if req.visibility and req.visibility != "any":
            visible_fit = ((req.visibility == "underheard" and album["role"] == "deep_cut") or
                           (req.visibility == "familiar" and album["role"] != "deep_cut") or
                           req.visibility == "mixed")
            contribution = 0.35 if visible_fit else -0.35
            score += contribution
            breakdown.append({"feature": "visibility", "detail": req.visibility,
                              "base_weight": 0.35, "confidence": 0.6, "contribution": contribution,
                              "source": "curator"})
        if album["corpus_status"] == "core":
            component = score_component("core_evidence", 1.0, "core")
            score += component["contribution"]
            breakdown.append(component)
            reasons.append({"relationship_type": "evidence_quality",
                            "claim": "Core corpus album with curator-reviewed descriptors",
                            "provenance": {"source": "curator", "confidence": 1.0},
                            "rank_contribution": component["contribution"]})

        # agent-first rule: no reasons, no recommendation — bonuses alone don't qualify
        if score > 0 and relevance_reasons:
            audit.update({
                "disposition": "ranked_candidate", "score": round(score, 3),
                "score_breakdown": breakdown, "matched_descriptors": matched,
                "decision_reasons": [reason["claim"] for reason in reasons],
            })
            scored.append((round(score, 3), album, reasons, matched, breakdown))
        else:
            audit.update({
                "disposition": "rejected_no_relevance_evidence", "score": round(score, 3),
                "score_breakdown": breakdown,
                "decision_reasons": [
                    "No descriptor, label-territory, seed-bucket, or fan-overlap evidence qualified it"
                ],
            })

    scored.sort(key=lambda x: (-x[0], x[1]["year"] or 9999, x[1]["title"]))  # deterministic
    for rank, (_, album, _, _, _) in enumerate(scored, 1):
        candidate_audit[album["id"]]["base_rank"] = rank

    # diversity: max 1 album per artist in results
    results, seen_artists = [], set()
    selection_strength = 0.08 * max(0, genre_distance(req) - 1)
    selected_pool = (select_pairwise_diverse(scored, req.n_results * 3, selection_strength)
                     if req.features.slate_diversity else select_diverse(scored, req.n_results * 3))
    for _, album, _, _, _ in selected_pool:
        candidate_audit[album["id"]]["disposition"] = "diversity_shortlist"
    for score, album, reasons, matched, breakdown in selected_pool:
        if album["artist_id"] in seen_artists:
            candidate_audit[album["id"]]["disposition"] = "displaced_one_album_per_artist"
            continue
        seen_artists.add(album["artist_id"])
        context = album_context(album["artist"], album["title"])
        image_values = vars(req.image_features) if req.image_features else {}
        candidate_visual = album_visual_features(album["artist"], album["title"])
        by_axis = {axis: [] for axis in external_axes}
        if external:
            album_tag_slugs = {row["slug"] for row in con.execute(
                "SELECT tags.slug FROM album_tags JOIN tags ON tags.id=album_tags.tag_id WHERE album_tags.album_id=?",
                (album["id"],))}
            for external_id, mappings in crosswalk.items():
                if any(mapping["slug"] in album_tag_slugs for mapping in mappings):
                    by_axis[external["by_id"][external_id]["root_dimension"]].append(external_id)
        completeness = annotation_completeness(by_axis, sum(len(v) for v in context["evidence"].values()))
        display_context = album_display_context(con, album["id"], matched)
        results.append({
            "entity": {"type": "album", "artist": album["artist"], "title": album["title"],
                       "year": album["year"], "rg_mbid": album["rg_mbid"],
                       "corpus_status": album["corpus_status"]},
            "match": {"score": round(score, 2), "matched_descriptors": matched,
                      "novelty_tier": album["role"], "score_breakdown": breakdown,
                      "explanation_fidelity": 1.0,
                      "annotation_completeness": completeness},
            "context": context,
            "descriptor_groups": {
                "sound_and_mood": display_context["descriptors"],
                "scenes": display_context["scenes"],
            },
            "labels": display_context["labels"],
            "visual_match": visual_match(image_values, candidate_visual, req.visual_role)
                            if req.features.visual_scoring and image_values else None,
            "reasons": reasons,
        })
        candidate_audit[album["id"]]["disposition"] = "curated_reserve"
        if len(results) >= req.n_results * 3:
            break

    rabbit_holes = {"labels": [], "scenes": [], "sources": []}
    analysis_scout_payload = None
    discovery = {
        "enabled": bool(req.features.outside_discovery),
        "available": bool(OPENAI_KEY and USER_AGENT),
        "status": "not_configured",
        "model": OPENAI_MODEL if OPENAI_KEY else None,
        "proposed": 0,
        "researched": 0,
        "verified": 0,
        "identity_cache_hits": 0,
        "stage": "idle",
    }
    grounded_reference_required = requires_grounded_reference(req, seeds)
    if req.features.outside_discovery and OPENAI_KEY and USER_AGENT:
        discovery["status"] = "running"
        try:
            discovery["stage"] = "candidate_generation"
            label_context = discovery_label_context(con, intent)
            analysis_scout_payload = candidate_scout_payload(
                req, intent, seeds, label_context,
                [result["entity"] for result in results],
            )
            proposed = generate_album_candidates(
                req, intent, seeds, vocab, label_context,
                [result["entity"] for result in results],
            )
            for proposal_index, candidate in enumerate(proposed):
                candidate["_proposal_index"] = proposal_index
            outside_audit = []
            for index, candidate in enumerate(proposed):
                item = {
                    "source_path": "llm_outside_discovery", "proposal_index": index,
                    "artist": candidate["artist"], "album": candidate["album"],
                    "year": candidate.get("year"), "rg_mbid": None, "corpus_status": "provisional",
                    "disposition": "proposed_for_research",
                    "decision_reasons": [candidate["connection"]],
                    "score": None, "base_rank": index + 1,
                    "score_breakdown": [],
                    "matched_descriptors": candidate["matched_descriptors"],
                    "proposal_confidence": candidate["confidence"],
                    "visibility": candidate["visibility"],
                    "genre_family": candidate.get("genre_family", ""),
                    "frontier_route": candidate.get("frontier_route", ""),
                    "frontier_provenance": {
                        "source": "llm_inferred", "confidence": candidate["confidence"],
                    },
                }
                candidate_ledger.append(item)
                outside_audit.append(item)
            discovery["proposed"] = len(proposed)
            discovery["stage"] = "context_research"
            preference = (req.visibility or "any").casefold()
            proposed_underheard = [
                candidate for candidate in proposed if candidate.get("visibility") == "underheard"
            ]
            proposed_other = [candidate for candidate in proposed if candidate not in proposed_underheard]
            if genre_distance(req) == 4:
                proposed_underheard = diversify_frontier_research_pool(
                    proposed_underheard, len(proposed_underheard),
                )
                proposed_other = diversify_frontier_research_pool(
                    proposed_other, len(proposed_other),
                )
            if preference == "mixed":
                provisional_research_pool = (proposed_underheard[:5] + proposed_other[:3])[:8]
            elif preference == "underheard":
                provisional_research_pool = proposed_underheard[:8]
            else:
                provisional_research_pool = proposed[:8]
            if genre_distance(req) == 4:
                provisional_research_pool = diversify_frontier_research_pool(
                    provisional_research_pool, 8,
                )
            research = research_album_candidates(req, provisional_research_pool, label_context)
            findings = {
                item["candidate_index"]: item for item in research["findings"]
                if item["verdict"] in {"supported", "partially_supported"}
                and 0 <= item["candidate_index"] < len(provisional_research_pool)
            }
            for index, audit in enumerate(outside_audit):
                finding = next(
                    (item for item in research["findings"]
                     if 0 <= item["candidate_index"] < len(provisional_research_pool)
                     and provisional_research_pool[item["candidate_index"]].get("_proposal_index") == index),
                    None,
                )
                if finding:
                    audit["research"] = finding
                    audit["decision_reasons"].append(finding["bridge_summary"])
                    audit["disposition"] = (
                        "research_supported" if finding["candidate_index"] in findings
                        else f"research_{finding['verdict']}"
                    )
                else:
                    audit["disposition"] = "not_researched_or_no_finding"
            discovery["researched"] = len(findings)
            rabbit_holes = {
                **research["rabbit_holes"],
                "sources": research.get("sources", []),
            }
            existing = {
                (result["entity"]["artist"].casefold(), result["entity"]["title"].casefold())
                for result in results
            }
            verified = []
            discovery["stage"] = "identity_verification"
            supported_indices = sorted(
                findings,
                key=lambda index: (
                    preference == "mixed"
                    and findings[index].get("visibility") != "underheard",
                    index,
                ),
            )
            shortlist = [
                (index, provisional_research_pool[index]) for index in supported_indices
            ][:max(req.n_results + 2, 6)]
            for candidate_index, candidate in shortlist:
                finding = findings[candidate_index]
                audit = outside_audit[candidate.get("_proposal_index", candidate_index)]
                candidate = {
                    **candidate,
                    "year": finding.get("release_year") or candidate.get("year"),
                    "visibility": finding.get("visibility", candidate.get("visibility", "unknown")),
                    "research": finding,
                    "research_sources": research.get("sources", []),
                }
                audit["visibility"] = candidate["visibility"]
                if (req.visibility or "").casefold() == "underheard" \
                        and candidate["visibility"] != "underheard":
                    audit["disposition"] = "rejected_visibility_mismatch"
                    audit["decision_reasons"].append("Underheard visibility was required")
                    continue
                resolved = verify_release_group(candidate)
                if not resolved:
                    audit["disposition"] = "rejected_identity_unverified"
                    audit["decision_reasons"].append(
                        "MusicBrainz did not verify the proposed artist/album identity"
                    )
                    continue
                audit.update(
                    disposition="identity_verified", year=resolved["year"],
                    rg_mbid=resolved["rg_mbid"], corpus_status="verified_discovery",
                )
                discovery["identity_cache_hits"] += int(
                    resolved.get("identity_source") in {
                        "musicbrainz_cache", "musicbrainz_corpus"
                    }
                )
                identity = (resolved["artist"].casefold(), resolved["album"].casefold())
                if identity in existing:
                    audit["disposition"] = "rejected_duplicate"
                    continue
                if hc.year_min and (resolved["year"] is None or resolved["year"] < hc.year_min):
                    audit["disposition"] = "excluded_by_hard_constraint"
                    continue
                if hc.year_max and (resolved["year"] is None or resolved["year"] > hc.year_max):
                    audit["disposition"] = "excluded_by_hard_constraint"
                    continue
                if hc.exclude_seed_artists and resolved["artist"].casefold() in {
                        seed["artist"].casefold() for seed in seeds}:
                    audit["disposition"] = "excluded_by_hard_constraint"
                    continue
                if set(resolved["matched_descriptors"]) & set(hc.exclude_moods):
                    audit["disposition"] = "excluded_by_hard_constraint"
                    continue
                verified.append(verified_candidate_result(resolved))
                audit["disposition"] = "verified_discovery_reserve"
                existing.add(identity)
                verification_target = max(req.n_results + 2, 5) if preference == "mixed" else req.n_results
                if len(verified) >= verification_target:
                    break
            discovery["verified"] = len(verified)
            discovery["stage"] = "complete"
            discovery["status"] = "verified" if verified else "no_verified_candidates"
            if verified:
                results = results + verified
        except Exception as exc:
            discovery["status"] = "fallback"
            discovery["error"] = type(exc).__name__
            print(f"Outside discovery failed ({exc}); no unverified substitute will be returned")

    bridge_abstention = False
    if grounded_reference_required:
        researched_results = [
            result for result in results
            if result["entity"]["corpus_status"] == "verified_discovery"
        ]
        if researched_results:
            results = researched_results
        else:
            results = []
            bridge_abstention = True
    results = select_recommendation_slate(req, results)
    results = apply_freshness(results, req, journey_signature)
    coverage = "full"
    notes = []
    for s in seeds:
        if s["status"] == "known_outside_corpus":
            coverage = "partial"
            notes.append(f"Seed '{s['artist']}' exists (MusicBrainz-verified) but is outside the curated corpus; "
                         "scene-based reasoning for it is unavailable.")
        elif s["status"] == "unknown":
            coverage = "partial"
            notes.append(f"Seed '{s['artist']}' could not be verified in corpus or MusicBrainz.")
    if (req.visibility or "").casefold() == "mixed" and results:
        represented_visibility = {result_visibility(result) for result in results}
        missing_visibility = {"underheard", "familiar"} - represented_visibility
        if missing_visibility:
            coverage = "partial"
            notes.append(
                "No evidence-backed " + " or ".join(sorted(missing_visibility))
                + " candidate survived research and identity verification; the requested "
                  "mixed-visibility slate is incomplete."
            )
    if not results:
        coverage = "no_match"
        if not req.features.corpus_candidates:
            if discovery["status"] == "fallback":
                failure = (
                    f"Discovery could not complete during {discovery['stage'].replace('_', ' ')}. "
                    "No unverified albums were substituted."
                )
            elif discovery["proposed"] == 0:
                failure = "No candidates were proposed strongly enough to research."
            elif discovery["researched"] == 0:
                failure = (
                    f"Research did not support any of the {discovery['proposed']} proposed candidates."
                )
            else:
                failure = (
                    f"None of the {discovery['researched']} research-supported candidates passed "
                    "identity verification and the selected visibility requirement."
                )
            notes.insert(0, failure + " The calibration corpus remains separate from discovery results.")
        elif bridge_abstention:
            notes.append(
                "The request compares against a record or artist that is not grounded in the curated "
                "corpus, and no researched outside candidate was verified. The honest answer is no "
                "match, not a seed-list substitute."
            )
        else:
            notes.append("No corpus albums satisfied the constraints. The honest answer is none, not a guess.")
    elif coverage_report["status"] in {"partial", "unmapped"}:
        coverage = "partial"
        notes.append("Some brief language is outside the controlled vocabulary; ranking used only mapped dimensions.")

    slate_items = [{"id": f"{r['entity']['artist']}::{r['entity']['title']}",
                    "descriptors": r["match"]["matched_descriptors"],
                    "bucket": next((x["detail"] for x in r["match"]["score_breakdown"] if x["feature"] == "seed_bucket"), ""),
                    "region": "", "decade": (r["entity"]["year"] or 0) // 10} for r in results]
    response = {
        "results": results,
        "intent_title": fallback_intent_title(intent),
        "parsed_intent": intent,
        "intent_coverage": coverage_report,
        "external_intent_by_axis": external_axes,
        "tuning_questions": tuning_questions(req.brief, bool(req.image_features),
                                               genre_distance(req) if req.features.discovery_depth else 3,
                                               req.visibility) if req.features.adaptive_questions else [],
        "seeds": seeds,
        "coverage": {"status": coverage, "notes": notes},
        "discovery": discovery,
        "rabbit_holes": rabbit_holes,
        "slate_diversity": pairwise_slate_diversity(slate_items) if req.features.slate_diversity else None,
        "visual_assessment": {"mode": req.visual_role, "input": vars(req.image_features)}
                             if req.image_features and req.features.visual_scoring else None,
        "meta": {"corpus_version": CORPUS_VERSION, "schema_version": "0.3",
                 "scoring_policy": SCORING_POLICY_VERSION,
                 "diversity_policy": "score-preserving tie diversification",
                 "signals_used": {"curator": True, "musicbrainz": bool(USER_AGENT),
                                  "last_fm": bool(LASTFM_KEY and req.use_lastfm),
                                  "openai_candidate_discovery": bool(
                                      discovery["status"] == "verified"),
                                  "llm_brief_parsing": bool(OPENAI_KEY or ANTHROPIC_KEY)}},
        "feature_toggles": vars(req.features),
    }
    if req.include_analysis_report:
        response["analysis_report"] = build_analysis_report(
            req, intent, coverage_report, seeds, candidate_ledger, results,
            discovery, analysis_scout_payload,
        )
    if OPENAI_KEY and results:
        try:
            listener_copy = compose_listener_copy(req.brief, results, req.calibration)
            response["intent_title"] = listener_copy["intent_title"]
            response["summary"] = listener_copy["summary"]
            explanations = {
                item["rg_mbid"]: item["explanation"]
                for item in listener_copy["explanations"]
            }
            for result in results:
                explanation = explanations.get(result["entity"]["rg_mbid"])
                if explanation:
                    result["editorial_explanation"] = explanation
        except Exception:
            pass
    elif ANTHROPIC_KEY and results:
        try:
            response["summary"] = compose_summary(req.brief, results)
        except Exception:
            pass
    record_exposures(results, req, journey_signature)
    con.close()
    return response


def compose_listener_copy(brief: str, results: list,
                          calibration: Optional[CalibrationContext] = None) -> dict:
    """Compose a short intent title and evidence-bounded editorial copy."""
    evidence = [{
        "rg_mbid": result["entity"]["rg_mbid"],
        "artist": result["entity"]["artist"],
        "album": result["entity"]["title"],
        "descriptors": result.get("descriptor_groups", {}),
        "reasons": [{
            "claim": reason["claim"],
            "source": reason["provenance"]["source"],
            "confidence": reason["provenance"]["confidence"],
        } for reason in result["reasons"]],
    } for result in results]
    output = openai_json_response(
        "You are an incisive music journalist, not a recommendation algorithm or marketing writer. "
        "Write an intent title of eight words or fewer, a concise listening-path introduction, and "
        "one vivid 45-80 word explanation per album. Lead with a musical argument, use concrete "
        "language, and allow some attitude. Use only the supplied evidence. Do not invent facts, "
        "influences, genres, labels, scenes, relationships, or entities. Do not mention confidence "
        "percentages. Distinguish inference from verified or curated evidence without bureaucratic "
        "language. Return plain text without Markdown.",
        json.dumps({
            "brief": brief,
            "calibrated_interpretation": model_values(calibration) if calibration else {},
            "evidence": evidence,
        }, ensure_ascii=False),
        "listener_editorial_copy",
        {
            "type": "object",
            "properties": {
                "intent_title": {"type": "string"},
                "summary": {"type": "string"},
                "explanations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rg_mbid": {"type": "string"},
                            "explanation": {"type": "string"},
                        },
                        "required": ["rg_mbid", "explanation"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["intent_title", "summary", "explanations"],
            "additionalProperties": False,
        },
        1600,
    )
    words = output["intent_title"].strip().split()
    output["intent_title"] = " ".join(words[:8]).strip(" .,:;-") or "A new listening path"
    output["summary"] = output["summary"].strip()
    return output


def compose_summary(brief: str, results: list) -> str:
    """LLM writes prose ONLY over retrieved results — it cannot add albums or facts."""
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    payload = json.dumps([{"artist": r["entity"]["artist"], "title": r["entity"]["title"],
                           "year": r["entity"]["year"],
                           "reasons": [x["claim"] for x in r["reasons"]]} for r in results])
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=400,
        messages=[{"role": "user", "content":
                   f"Brief: {brief}\nRecommendations with evidence: {payload}\n\n"
                   f"Operating policy:\n{RUNTIME_POLICY}\n\n"
                   "Write a 3-4 sentence summary of why this set fits the brief. "
                   "Mention ONLY the albums and reasons given. Do not add facts, "
                   "comparisons, or albums not in the data."}])
    return msg.content[0].text.strip()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/recommendations")
def recommendations(req: RecRequest):
    if not DB_PATH.exists():
        return {"error": "corpus.db not found - run: python build_corpus.py build"}
    return recommend(req)


@app.post("/tuning-questions")
def get_tuning_questions(req: RecRequest):
    orientation = next((
        answer.interpretation for answer in req.calibration_answers
        if answer.question_id == "musical_orientation"
    ), "")
    calibration = analyze_calibration(req.brief, bool(req.image_features), orientation)
    return {**calibration, "schema_version": "2.0"}


@app.get("/labels")
def labels(query: str = "", genre: str = "", mood: str = "", texture: str = "",
           scene: str = "", related_to: str = "", limit: int = 25):
    """Browse label entities by curated territory or graph connection."""
    filters = [("genre", genre), ("mood", mood), ("texture", texture), ("scene", scene)]
    active = [(kind, value) for kind, value in filters if value]
    if len(active) > 1:
        return {"error": "Use one of genre, mood, texture, or scene per request."}
    kind, value = active[0] if active else ("", "")
    con = db()
    results = search_labels(con, query=query, kind=kind, value=value,
                            related_to=related_to, limit=limit)
    return {"results": results, "count": len(results),
            "provenance": {"source": "curator", "dataset": "crate-digger-curated-record-labels"}}


@app.get("/evaluation/state")
def get_evaluation_state(evaluator_id: str = ""):
    return evaluation_state(evaluator_id)


@app.post("/evaluation/briefs")
def create_evaluation_brief(payload: EvaluationBrief):
    try:
        return {"brief": save_brief(model_values(payload))}
    except ValueError as exc:
        return {"error": str(exc)}


@app.post("/evaluation/freeze")
def freeze_evaluation_briefs():
    try:
        payload = freeze_briefs()
        return {"frozen": True, "brief_count": len(payload["cases"])}
    except ValueError as exc:
        return {"error": str(exc)}


@app.post("/evaluation/feedback")
def create_evaluation_feedback(payload: EvaluationFeedback):
    try:
        return {"feedback": save_feedback(model_values(payload))}
    except ValueError as exc:
        return {"error": str(exc)}


@app.get("/evaluation", response_class=HTMLResponse)
def evaluation_home():
    return evaluation_page()


@app.get("/listen", response_class=HTMLResponse)
def listener_home():
    return listener_page()


@app.get("/health")
def health():
    if not DB_PATH.exists():
        return {"ok": False, "error": "corpus.db missing"}
    con = db()
    total = con.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
    core = con.execute("SELECT COUNT(*) FROM albums WHERE corpus_status='core'").fetchone()[0]
    external_count = len(load_external_taxonomy(EXTERNAL_TAXONOMY_PATH)["by_id"])
    label_count = con.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    album_label_links = con.execute("SELECT COUNT(*) FROM album_labels").fetchone()[0]
    corpus_identity_cache = con.execute(
        "SELECT COUNT(*) FROM albums WHERE length(rg_mbid)>0"
    ).fetchone()[0]
    con.close()
    runtime = runtime_db()
    discovered_identity_cache = runtime.execute(
        "SELECT COUNT(*) FROM identity_cache"
    ).fetchone()[0]
    runtime.close()
    return {"ok": True, "albums": total, "core": core, "corpus_version": CORPUS_VERSION,
            "external_taxonomy_terms": external_count, "recommendation_intelligence": True,
            "labels": label_count, "album_label_links": album_label_links,
            "identity_cache": {
                "corpus": corpus_identity_cache,
                "discovered": discovered_identity_cache,
                "total": corpus_identity_cache + discovered_identity_cache,
            },
            "lastfm_enabled": bool(LASTFM_KEY),
            "openai_enabled": bool(OPENAI_KEY),
            "openai_model": OPENAI_MODEL if OPENAI_KEY else None,
            "llm_enabled": bool(OPENAI_KEY or ANTHROPIC_KEY)}


@app.get("/", response_class=HTMLResponse)
def home():
    return """<!doctype html><html><head><title>Music Context Sandbox</title>
<style>body{font-family:system-ui;max-width:720px;margin:2rem auto;padding:0 1rem;background:#111;color:#eee}
input,button{font-size:1rem;padding:.5rem;margin:.25rem 0;width:100%;box-sizing:border-box;
background:#222;color:#eee;border:1px solid #444;border-radius:6px}
button{background:#5b4b8a;cursor:pointer}pre{background:#1a1a1a;padding:1rem;border-radius:8px;
overflow-x:auto;white-space:pre-wrap;font-size:.85rem}</style></head><body>
<h2>Music Context Sandbox</h2>
<p>Brief (moods, textures, scenes):</p>
<input id="brief" placeholder="nocturnal, elegant, reverb-drenched writing music" />
<p>Seed artists (comma-separated):</p>
<input id="seeds" placeholder="The Cure, Portishead" />
<label><input type="checkbox" id="nonobv" style="width:auto"> non-obvious only</label>
<p>Discovery depth (1 familiar to 5 frontier):</p>
<input id="depth" type="range" min="1" max="5" value="3" />
<p>Visibility:</p><select id="visibility"><option>any</option><option>familiar</option>
<option>mixed</option><option>underheard</option></select>
<p>Optional image:</p><input id="image" type="file" accept="image/*" />
<button onclick="go()">Recommend</button>
<pre id="out">results appear here…</pre>
<script>
async function go(){
  const seeds = document.getElementById('seeds').value.split(',')
    .map(s=>s.trim()).filter(Boolean).map(a=>({artist:a}));
  const body = {brief:document.getElementById('brief').value, seeds,
    novelty: document.getElementById('nonobv').checked ? 'non_obvious' : 'any', n_results:5,
    discovery_depth:Number(document.getElementById('depth').value),
    visibility:document.getElementById('visibility').value};
  const file=document.getElementById('image').files[0];
  if(file) body.image_features=await extractImageFeatures(file);
  document.getElementById('out').textContent = 'thinking…';
  const r = await fetch('/recommendations',{method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  document.getElementById('out').textContent = JSON.stringify(await r.json(), null, 2);
}
async function extractImageFeatures(file){
  const bitmap=await createImageBitmap(file); const canvas=document.createElement('canvas');
  canvas.width=64; canvas.height=64; const ctx=canvas.getContext('2d',{willReadFrequently:true});
  ctx.drawImage(bitmap,0,0,64,64); const px=ctx.getImageData(0,0,64,64).data;
  let lum=[],warm=0,sat=0,edges=0;
  for(let i=0;i<px.length;i+=4){const r=px[i]/255,g=px[i+1]/255,b=px[i+2]/255;
    const hi=Math.max(r,g,b),lo=Math.min(r,g,b),y=.2126*r+.7152*g+.0722*b;
    lum.push(y); warm+=Math.max(0,Math.min(1,(r-b+1)/2)); sat+=hi?((hi-lo)/hi):0;
    if(lum.length>1) edges+=Math.abs(y-lum[lum.length-2]);}
  const mean=lum.reduce((a,b)=>a+b,0)/lum.length;
  const variance=lum.reduce((a,b)=>a+(b-mean)**2,0)/lum.length;
  return {brightness:mean,warmth:warm/lum.length,saturation:sat/lum.length,
    contrast:Math.min(1,Math.sqrt(variance)*2),openness:Math.max(0,1-Math.min(1,edges/lum.length*8)),
    depth:null,density:Math.min(1,edges/lum.length*8),texture:'client_pixel_sample',geometry:'unknown',
    human_arrangement:'unknown',motion:'unknown'};
}
</script></body></html>"""
