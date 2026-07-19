"""
app.py — barebones recommendation platform over corpus.db

The smallest honest version of the agent-first idea:
  * Your curated corpus (corpus.db) is the trusted foundation.
  * MusicBrainz resolves seed artists at query time (facts, coverage honesty).
  * Last.fm provides similar-artist / tag SIGNALS, always labeled source="last_fm",
    never written into the corpus.
  * An LLM (optional) parses the brief and writes reason prose — but only over
    retrieved data. It cannot introduce albums or facts.

Run it (PowerShell, from the repo root, after build_corpus.py build):
    pip install fastapi uvicorn requests
    # optional extras:
    #   $env:LASTFM_API_KEY = "your-key"        -> enables fan-overlap signals
    #   $env:ANTHROPIC_API_KEY = "sk-ant-..."   -> enables LLM brief parsing + prose reasons
    #   (also: pip install anthropic)
    uvicorn app:app --reload

Then open http://127.0.0.1:8000  (simple form)
       or http://127.0.0.1:8000/docs  (interactive API docs — free with FastAPI)
"""

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from recommendation_logic import (
    SCORING_POLICY_VERSION,
    find_unmapped_terms,
    intent_coverage,
    score_component,
    select_diverse,
)

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "build/corpus.db"
RECOMMENDATION_LOGIC_PATH = PROJECT_ROOT / "brain/recommendation-logic.md"
LASTFM_KEY = os.environ.get("LASTFM_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MUSICBRAINZ_CONTACT = os.environ.get("MUSICBRAINZ_CONTACT", "").strip()
USER_AGENT = os.environ.get(
    "MUSICBRAINZ_USER_AGENT",
    f"MusicCorpusSandbox/0.1 ({MUSICBRAINZ_CONTACT})" if MUSICBRAINZ_CONTACT else "",
)
CORPUS_VERSION = time.strftime("%Y-%m-%d", time.gmtime(DB_PATH.stat().st_mtime)) if DB_PATH.exists() else "missing"

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


# ---------------------------------------------------------------------------
# Request / response contracts (the "agent-first" part: typed, validated)
# ---------------------------------------------------------------------------
class Seed(BaseModel):
    artist: str


class HardConstraints(BaseModel):
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    buckets: Optional[list[str]] = None          # e.g. ["D", "F"]
    exclude_seed_artists: bool = True
    exclude_moods: list[str] = Field(default_factory=list)


class RecRequest(BaseModel):
    brief: str = ""                              # "rainy, cinematic writing music"
    seeds: list[Seed] = Field(default_factory=list)
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    novelty: str = "any"                         # any | non_obvious
    n_results: int = Field(default=5, ge=1, le=25)
    use_lastfm: bool = True


# ---------------------------------------------------------------------------
# Corpus access
# ---------------------------------------------------------------------------
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def load_vocab(con) -> dict[str, set[str]]:
    vocab: dict[str, set[str]] = {"mood": set(), "sonic_trait": set(), "scene": set()}
    for r in con.execute("SELECT kind, slug FROM tags"):
        vocab.setdefault(r["kind"], set()).add(r["slug"])
    return vocab


# ---------------------------------------------------------------------------
# Brief parsing: LLM if available, keyword fallback otherwise.
# Either way, output is CONSTRAINED to your controlled vocabulary.
# ---------------------------------------------------------------------------
def parse_brief(brief: str, vocab: dict[str, set[str]]) -> dict:
    intent = {"moods": [], "sonic_traits": [], "scenes": [], "unmapped_terms": []}
    if not brief.strip():
        return intent
    if ANTHROPIC_KEY:
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
        data = requests.get("https://musicbrainz.org/ws/2/artist/",
                            params={"query": f'artist:"{artist_name}"', "fmt": "json", "limit": 1},
                            headers={"User-Agent": USER_AGENT}, timeout=10).json()
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


# ---------------------------------------------------------------------------
# Retrieval + deterministic scoring
# ---------------------------------------------------------------------------
def recommend(req: RecRequest) -> dict:
    con = db()
    vocab = load_vocab(con)
    intent = parse_brief(req.brief, vocab)
    coverage_report = intent_coverage(intent)
    hc = req.hard_constraints

    seeds = [resolve_seed(con, s.artist) for s in req.seeds]
    seed_buckets = {b for s in seeds for b in s["buckets"]}
    seed_artist_ids = {s["artist_id"] for s in seeds if s.get("artist_id")}

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

    # candidate pool: hard constraints applied structurally, in SQL
    sql = """SELECT albums.id, albums.title, albums.year, albums.bucket, albums.region,
                    albums.role, albums.corpus_status, albums.rg_mbid,
                    artists.name AS artist, artists.id AS artist_id
             FROM albums JOIN artists ON artists.id = albums.artist_id WHERE 1=1"""
    params: list = []
    if hc.year_min:
        sql += " AND albums.year >= ?"; params.append(hc.year_min)
    if hc.year_max:
        sql += " AND albums.year <= ?"; params.append(hc.year_max)
    if hc.buckets:
        sql += f" AND albums.bucket IN ({','.join('?' * len(hc.buckets))})"; params += hc.buckets

    scored = []
    for album in con.execute(sql, params):
        if hc.exclude_seed_artists and album["artist_id"] in seed_artist_ids:
            continue
        tags = {r["slug"]: r["kind"] for r in con.execute(
            "SELECT tags.slug, tags.kind FROM album_tags JOIN tags ON tags.id=album_tags.tag_id "
            "WHERE album_tags.album_id=?", (album["id"],))}
        if hc.exclude_moods and any(m in tags for m in hc.exclude_moods):
            continue  # hard exclusion

        matched = sorted(wanted & set(tags))
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
            scored.append((round(score, 3), album, reasons, matched, breakdown))

    scored.sort(key=lambda x: (-x[0], x[1]["year"] or 9999, x[1]["title"]))  # deterministic

    # diversity: max 1 album per artist in results
    results, seen_artists = [], set()
    for score, album, reasons, matched, breakdown in select_diverse(scored, req.n_results * 3):
        if album["artist_id"] in seen_artists:
            continue
        seen_artists.add(album["artist_id"])
        results.append({
            "entity": {"type": "album", "artist": album["artist"], "title": album["title"],
                       "year": album["year"], "rg_mbid": album["rg_mbid"],
                       "corpus_status": album["corpus_status"]},
            "match": {"score": round(score, 2), "matched_descriptors": matched,
                      "novelty_tier": album["role"], "score_breakdown": breakdown,
                      "explanation_fidelity": 1.0},
            "reasons": reasons,
        })
        if len(results) >= req.n_results:
            break

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
    if not results:
        coverage = "no_match"
        notes.append("No corpus albums satisfied the constraints. The honest answer is none, not a guess.")
    elif coverage_report["status"] in {"partial", "unmapped"}:
        coverage = "partial"
        notes.append("Some brief language is outside the controlled vocabulary; ranking used only mapped dimensions.")

    response = {
        "results": results,
        "parsed_intent": intent,
        "intent_coverage": coverage_report,
        "seeds": seeds,
        "coverage": {"status": coverage, "notes": notes},
        "meta": {"corpus_version": CORPUS_VERSION, "schema_version": "0.2",
                 "scoring_policy": SCORING_POLICY_VERSION,
                 "diversity_policy": "score-preserving tie diversification",
                 "signals_used": {"curator": True, "musicbrainz": bool(USER_AGENT),
                                  "last_fm": bool(LASTFM_KEY and req.use_lastfm),
                                  "llm_brief_parsing": bool(ANTHROPIC_KEY)}},
    }
    if ANTHROPIC_KEY and results:
        try:
            response["summary"] = compose_summary(req.brief, results)
        except Exception:
            pass
    con.close()
    return response


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


@app.get("/health")
def health():
    if not DB_PATH.exists():
        return {"ok": False, "error": "corpus.db missing"}
    con = db()
    total = con.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
    core = con.execute("SELECT COUNT(*) FROM albums WHERE corpus_status='core'").fetchone()[0]
    return {"ok": True, "albums": total, "core": core, "corpus_version": CORPUS_VERSION,
            "lastfm_enabled": bool(LASTFM_KEY), "llm_enabled": bool(ANTHROPIC_KEY)}


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
<button onclick="go()">Recommend</button>
<pre id="out">results appear here…</pre>
<script>
async function go(){
  const seeds = document.getElementById('seeds').value.split(',')
    .map(s=>s.trim()).filter(Boolean).map(a=>({artist:a}));
  const body = {brief:document.getElementById('brief').value, seeds,
    novelty: document.getElementById('nonobv').checked ? 'non_obvious' : 'any', n_results:5};
  document.getElementById('out').textContent = 'thinking…';
  const r = await fetch('/recommendations',{method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  document.getElementById('out').textContent = JSON.stringify(await r.json(), null, 2);
}
</script></body></html>"""
