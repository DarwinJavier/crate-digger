"""
Build and inspect the Music Context Sandbox corpus.

Commands:
    python build_corpus.py resolve
    python build_corpus.py enrich-musicbrainz
    python build_corpus.py build
    python build_corpus.py stats

CSV files remain the source of truth. build/ and exports/ are generated.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests


DATA_DIR = Path("data")
BUILD_DIR = Path("build")
EXPORTS_DIR = Path("exports")
SEED_PATH = DATA_DIR / "seed_albums.csv"
VOCAB_PATH = DATA_DIR / "vocab.csv"
DESCRIPTORS_PATH = DATA_DIR / "descriptors.csv"
OVERRIDES_PATH = DATA_DIR / "resolution_overrides.csv"
RESOLVED_PATH = DATA_DIR / "resolved_albums.csv"
UNRESOLVED_PATH = DATA_DIR / "unresolved.csv"
MB_RELEASES_PATH = DATA_DIR / "musicbrainz_releases.csv"
MB_RELATIONSHIPS_PATH = DATA_DIR / "musicbrainz_relationships.csv"
DB_PATH = BUILD_DIR / "corpus.db"
JSONL_PATH = EXPORTS_DIR / "corpus.jsonl"

DEFAULT_USER_AGENT = "MusicCorpusSandbox/0.1"
ALLOWED_SOURCES = {"curator", "musicbrainz", "last_fm", "llm_inferred"}
DESCRIPTOR_KINDS = ("moods", "sonic_traits", "scenes")
KIND_BY_DESCRIPTOR_COLUMN = {
    "moods": "mood",
    "sonic_traits": "sonic_trait",
    "scenes": "scene",
}


@dataclass(frozen=True)
class SeedAlbum:
    artist: str
    album: str
    year: int | None
    bucket: str
    region: str
    role: str
    notes: str


@dataclass(frozen=True)
class ResolvedAlbum:
    artist: str
    album: str
    artist_mbid: str
    release_group_mbid: str
    resolved_artist: str
    resolved_album: str
    status: str


@dataclass(frozen=True)
class ResolutionOverride:
    resolve_artist: str
    resolve_album: str
    notes: str


def normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def album_key(artist: str, album: str) -> tuple[str, str]:
    return normalize(artist), normalize(album)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_year(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid year '{value}' in seed data") from exc


def split_terms(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def load_seeds() -> list[SeedAlbum]:
    rows = read_csv(SEED_PATH)
    seeds: list[SeedAlbum] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        seed = SeedAlbum(
            artist=(row.get("artist") or "").strip(),
            album=(row.get("album") or "").strip(),
            year=parse_year(row.get("year", "")),
            bucket=(row.get("bucket") or "").strip(),
            region=(row.get("region") or "").strip(),
            role=(row.get("role") or "").strip(),
            notes=(row.get("notes") or "").strip(),
        )
        if not seed.artist or not seed.album:
            raise SystemExit("Every seed row must include artist and album")
        key = album_key(seed.artist, seed.album)
        if key in seen:
            raise SystemExit(f"Duplicate seed album: {seed.artist} - {seed.album}")
        seen.add(key)
        seeds.append(seed)
    return seeds


def load_vocab() -> dict[str, dict[str, str]]:
    rows = read_csv(VOCAB_PATH)
    vocab: dict[str, dict[str, str]] = {"mood": {}, "sonic_trait": {}, "scene": {}}
    for row in rows:
        kind = (row.get("kind") or "").strip()
        slug = (row.get("slug") or "").strip()
        definition = (row.get("definition") or "").strip()
        if kind not in vocab:
            raise SystemExit(f"Unknown vocab kind '{kind}' for tag '{slug}'")
        if not slug:
            raise SystemExit("Vocab row has an empty slug")
        if slug in vocab[kind]:
            raise SystemExit(f"Duplicate vocab slug for {kind}: {slug}")
        vocab[kind][slug] = definition
    return vocab


def load_resolved() -> dict[tuple[str, str], ResolvedAlbum]:
    if not RESOLVED_PATH.exists():
        return {}
    resolved: dict[tuple[str, str], ResolvedAlbum] = {}
    for row in read_csv(RESOLVED_PATH):
        artist = (row.get("artist") or "").strip()
        album = (row.get("album") or "").strip()
        if not artist or not album:
            continue
        item = ResolvedAlbum(
            artist=artist,
            album=album,
            artist_mbid=(row.get("artist_mbid") or "").strip(),
            release_group_mbid=(row.get("release_group_mbid") or "").strip(),
            resolved_artist=(row.get("resolved_artist") or "").strip(),
            resolved_album=(row.get("resolved_album") or "").strip(),
            status=(row.get("status") or "").strip(),
        )
        resolved[album_key(artist, album)] = item
    return resolved


def load_resolution_overrides() -> dict[tuple[str, str], ResolutionOverride]:
    if not OVERRIDES_PATH.exists():
        return {}
    overrides: dict[tuple[str, str], ResolutionOverride] = {}
    for row in read_csv(OVERRIDES_PATH):
        artist = (row.get("artist") or "").strip()
        album = (row.get("album") or "").strip()
        resolve_artist = (row.get("resolve_artist") or "").strip()
        resolve_album = (row.get("resolve_album") or "").strip()
        if not artist or not album or not resolve_artist or not resolve_album:
            raise SystemExit(f"Invalid resolution override row for {artist} - {album}")
        overrides[album_key(artist, album)] = ResolutionOverride(
            resolve_artist=resolve_artist,
            resolve_album=resolve_album,
            notes=(row.get("notes") or "").strip(),
        )
    return overrides


def load_descriptors(
    seeds_by_key: dict[tuple[str, str], SeedAlbum],
    vocab: dict[str, dict[str, str]],
) -> dict[tuple[str, str], list[tuple[str, str, str, float]]]:
    rows = read_csv(DESCRIPTORS_PATH)
    descriptors: dict[tuple[str, str], list[tuple[str, str, str, float]]] = {}
    errors: list[str] = []
    for row_number, row in enumerate(rows, start=2):
        if (row.get("approved") or "").strip().lower() != "yes":
            continue
        artist = (row.get("artist") or "").strip()
        album = (row.get("album") or "").strip()
        key = album_key(artist, album)
        if key not in seeds_by_key:
            errors.append(f"row {row_number}: descriptor target not in seed list: {artist} - {album}")
            continue
        source = (row.get("source") or "").strip()
        if source not in ALLOWED_SOURCES:
            errors.append(f"row {row_number}: invalid source '{source}'")
            continue
        try:
            confidence = float((row.get("confidence") or "").strip())
        except ValueError:
            errors.append(f"row {row_number}: invalid confidence")
            continue
        if confidence < 0 or confidence > 1:
            errors.append(f"row {row_number}: confidence must be between 0 and 1")
            continue
        for column in DESCRIPTOR_KINDS:
            kind = KIND_BY_DESCRIPTOR_COLUMN[column]
            for slug in split_terms(row.get(column, "")):
                if slug not in vocab[kind]:
                    errors.append(f"row {row_number}: unknown {kind} tag '{slug}'")
                else:
                    descriptors.setdefault(key, []).append((kind, slug, source, confidence))
    if errors:
        raise SystemExit("Descriptor validation failed:\n" + "\n".join(errors))
    return descriptors


def musicbrainz_user_agent() -> str:
    full = os.environ.get("MUSICBRAINZ_USER_AGENT", "").strip()
    if full:
        return full
    contact = os.environ.get("MUSICBRAINZ_CONTACT", "").strip()
    if contact:
        return f"{DEFAULT_USER_AGENT} ({contact})"
    raise SystemExit(
        "MusicBrainz resolution requires a contact. Set one first, for example:\n"
        '$env:MUSICBRAINZ_CONTACT = "you@example.com"'
    )


def musicbrainz_get(path: str, params: dict[str, object], user_agent: str) -> dict:
    response = requests.get(
        f"https://musicbrainz.org/ws/2/{path}",
        params={**params, "fmt": "json"},
        headers={"User-Agent": user_agent},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def safe_date_sort(value: str) -> tuple[int, str]:
    value = (value or "").strip()
    if not value:
        return (9999, "")
    year = value.split("-", 1)[0]
    try:
        return (int(year), value)
    except ValueError:
        return (9999, value)


def release_sort_key(release: dict) -> tuple[int, tuple[int, str], str]:
    status = str(release.get("status") or "")
    status_rank = 0 if status.casefold() == "official" else 1
    return (status_rank, safe_date_sort(str(release.get("date") or "")), str(release.get("title") or ""))


def choose_primary_release(releases: list[dict]) -> dict | None:
    real_releases = [r for r in releases if str(r.get("status") or "").casefold() != "pseudo-release"]
    candidates = real_releases or releases
    if not candidates:
        return None
    return sorted(candidates, key=release_sort_key)[0]


def flatten_values(values: Iterable[str]) -> str:
    return ";".join(sorted({value.strip() for value in values if value and value.strip()}))


def relationship_target(relation: dict) -> tuple[str, str, str]:
    for target_type in ("artist", "place", "label", "recording", "release", "release-group", "url", "work"):
        entity = relation.get(target_type)
        if isinstance(entity, dict):
            name = entity.get("name") or entity.get("title") or entity.get("resource") or entity.get("id") or ""
            return target_type, str(name), str(entity.get("id") or "")
    target_type = str(relation.get("target-type") or "")
    return target_type, str(relation.get("target") or ""), ""


def relationship_dates(relation: dict) -> tuple[str, str]:
    begin = relation.get("begin")
    end = relation.get("end")
    return str(begin or ""), str(end or "")


def command_enrich_musicbrainz(_args: argparse.Namespace) -> None:
    user_agent = musicbrainz_user_agent()
    rows = read_csv(RESOLVED_PATH)
    release_rows: list[dict[str, object]] = []
    relationship_rows: list[dict[str, object]] = []
    resolved_rows = [row for row in rows if (row.get("release_group_mbid") or "").strip()]

    for index, row in enumerate(resolved_rows, start=1):
        artist = (row.get("artist") or "").strip()
        album = (row.get("album") or "").strip()
        rg_mbid = (row.get("release_group_mbid") or "").strip()
        print(f"[{index}/{len(resolved_rows)}] enriching {artist} - {album}")

        group = musicbrainz_get(
            f"release-group/{rg_mbid}",
            {"inc": "releases+genres+tags"},
            user_agent,
        )
        releases = group.get("releases") or []
        primary = choose_primary_release(releases)
        if not primary:
            release_rows.append({
                "artist": artist,
                "album": album,
                "release_group_mbid": rg_mbid,
                "release_mbid": "",
                "release_title": "",
                "date": "",
                "country": "",
                "status": "",
                "label": "",
                "label_mbid": "",
                "catalog_number": "",
                "barcode": "",
                "format": "",
                "track_count": "",
                "is_primary": "no",
                "source": "musicbrainz",
                "confidence": 0.65,
            })
            time.sleep(1.05)
            continue

        time.sleep(1.05)
        release_mbid = str(primary.get("id") or "")
        release = musicbrainz_get(
            f"release/{release_mbid}",
            {"inc": "labels+media+artist-rels+label-rels+place-rels+url-rels+release-groups"},
            user_agent,
        )

        label_info = release.get("label-info") or []
        labels = [str((info.get("label") or {}).get("name") or "") for info in label_info if isinstance(info, dict)]
        label_mbids = [str((info.get("label") or {}).get("id") or "") for info in label_info if isinstance(info, dict)]
        catalog_numbers = [str(info.get("catalog-number") or "") for info in label_info if isinstance(info, dict)]
        media = release.get("media") or []
        formats = [str(medium.get("format") or "") for medium in media if isinstance(medium, dict)]
        track_count = sum(int(medium.get("track-count") or 0) for medium in media if isinstance(medium, dict))

        release_rows.append({
            "artist": artist,
            "album": album,
            "release_group_mbid": rg_mbid,
            "release_mbid": release_mbid,
            "release_title": str(release.get("title") or primary.get("title") or ""),
            "date": str(release.get("date") or primary.get("date") or ""),
            "country": str(release.get("country") or primary.get("country") or ""),
            "status": str(release.get("status") or primary.get("status") or ""),
            "label": flatten_values(labels),
            "label_mbid": flatten_values(label_mbids),
            "catalog_number": flatten_values(catalog_numbers),
            "barcode": str(release.get("barcode") or ""),
            "format": flatten_values(formats),
            "track_count": track_count or "",
            "is_primary": "yes",
            "source": "musicbrainz",
            "confidence": 0.75,
        })

        for relation in release.get("relations") or []:
            if not isinstance(relation, dict):
                continue
            target_type, target_name, target_mbid = relationship_target(relation)
            begin, end = relationship_dates(relation)
            relationship_rows.append({
                "artist": artist,
                "album": album,
                "release_group_mbid": rg_mbid,
                "release_mbid": release_mbid,
                "scope": "release",
                "relationship_type": str(relation.get("type") or ""),
                "target_type": target_type,
                "target_name": target_name,
                "target_mbid": target_mbid,
                "attributes": flatten_values(str(attr) for attr in relation.get("attributes") or []),
                "begin_date": begin,
                "end_date": end,
                "source": "musicbrainz",
                "confidence": 0.75,
            })

        time.sleep(1.05)

    write_csv(MB_RELEASES_PATH, release_rows, [
        "artist", "album", "release_group_mbid", "release_mbid", "release_title",
        "date", "country", "status", "label", "label_mbid", "catalog_number",
        "barcode", "format", "track_count", "is_primary", "source", "confidence",
    ])
    write_csv(MB_RELATIONSHIPS_PATH, relationship_rows, [
        "artist", "album", "release_group_mbid", "release_mbid", "scope",
        "relationship_type", "target_type", "target_name", "target_mbid",
        "attributes", "begin_date", "end_date", "source", "confidence",
    ])
    print(f"wrote {MB_RELEASES_PATH} ({len(release_rows)} rows)")
    print(f"wrote {MB_RELATIONSHIPS_PATH} ({len(relationship_rows)} rows)")


def resolve_seed(
    seed: SeedAlbum,
    user_agent: str,
    override: ResolutionOverride | None = None,
) -> ResolvedAlbum | str:
    query_artist = override.resolve_artist if override else seed.artist
    query_album = override.resolve_album if override else seed.album
    query = f'artist:"{query_artist}" AND releasegroup:"{query_album}"'
    data = musicbrainz_get(
        "release-group/",
        {"query": query, "limit": 5, "type": "album"},
        user_agent,
    )
    candidates = data.get("release-groups") or []
    if not candidates:
        return "no MusicBrainz release-group match"
    hit = candidates[0]
    score = int(hit.get("score") or 0)
    if score < 80:
        return f"low MusicBrainz score ({score})"
    artist_credit = hit.get("artist-credit") or []
    artist_info = {}
    if artist_credit and isinstance(artist_credit[0], dict):
        artist_info = artist_credit[0].get("artist") or {}
    artist_name = str(artist_info.get("name") or seed.artist)
    artist_mbid = str(artist_info.get("id") or "")
    return ResolvedAlbum(
        artist=seed.artist,
        album=seed.album,
        artist_mbid=artist_mbid,
        release_group_mbid=str(hit.get("id") or ""),
        resolved_artist=artist_name,
        resolved_album=str(hit.get("title") or seed.album),
        status="resolved",
    )


def command_resolve(_args: argparse.Namespace) -> None:
    user_agent = musicbrainz_user_agent()
    seeds = load_seeds()
    overrides = load_resolution_overrides()
    resolved_rows: list[dict[str, object]] = []
    unresolved_rows: list[dict[str, object]] = []
    for index, seed in enumerate(seeds, start=1):
        override = overrides.get(album_key(seed.artist, seed.album))
        lookup_note = "" if override is None else f" via {override.resolve_artist} - {override.resolve_album}"
        print(f"[{index}/{len(seeds)}] resolving {seed.artist} - {seed.album}{lookup_note}")
        try:
            result = resolve_seed(seed, user_agent, override)
        except Exception as exc:
            result = f"MusicBrainz request failed: {exc}"
        if isinstance(result, ResolvedAlbum):
            resolved_rows.append({
                "artist": seed.artist,
                "album": seed.album,
                "year": seed.year or "",
                "bucket": seed.bucket,
                "region": seed.region,
                "role": seed.role,
                "notes": seed.notes,
                "artist_mbid": result.artist_mbid,
                "release_group_mbid": result.release_group_mbid,
                "resolved_artist": result.resolved_artist,
                "resolved_album": result.resolved_album,
                "status": result.status,
            })
        else:
            unresolved_rows.append({
                "artist": seed.artist,
                "album": seed.album,
                "year": seed.year or "",
                "bucket": seed.bucket,
                "region": seed.region,
                "role": seed.role,
                "notes": seed.notes,
                "reason": result,
            })
        if index < len(seeds):
            time.sleep(1.05)
    write_csv(RESOLVED_PATH, resolved_rows, [
        "artist", "album", "year", "bucket", "region", "role", "notes",
        "artist_mbid", "release_group_mbid", "resolved_artist", "resolved_album", "status",
    ])
    write_csv(UNRESOLVED_PATH, unresolved_rows, [
        "artist", "album", "year", "bucket", "region", "role", "notes", "reason",
    ])
    print(f"resolved: {len(resolved_rows)}")
    print(f"unresolved: {len(unresolved_rows)}")


def create_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        DROP TABLE IF EXISTS album_tags;
        DROP TABLE IF EXISTS musicbrainz_relationships;
        DROP TABLE IF EXISTS musicbrainz_releases;
        DROP TABLE IF EXISTS tags;
        DROP TABLE IF EXISTS albums;
        DROP TABLE IF EXISTS artists;

        CREATE TABLE artists (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            mbid TEXT
        );

        CREATE TABLE albums (
            id INTEGER PRIMARY KEY,
            artist_id INTEGER NOT NULL REFERENCES artists(id),
            title TEXT NOT NULL,
            year INTEGER,
            bucket TEXT NOT NULL,
            region TEXT NOT NULL,
            role TEXT NOT NULL,
            corpus_status TEXT NOT NULL,
            rg_mbid TEXT,
            UNIQUE (artist_id, title)
        );

        CREATE TABLE tags (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            slug TEXT NOT NULL,
            definition TEXT NOT NULL,
            UNIQUE (kind, slug)
        );

        CREATE TABLE album_tags (
            album_id INTEGER NOT NULL REFERENCES albums(id),
            tag_id INTEGER NOT NULL REFERENCES tags(id),
            source TEXT NOT NULL,
            confidence REAL NOT NULL,
            PRIMARY KEY (album_id, tag_id)
        );

        CREATE TABLE musicbrainz_releases (
            album_id INTEGER NOT NULL REFERENCES albums(id),
            release_mbid TEXT,
            release_title TEXT,
            date TEXT,
            country TEXT,
            status TEXT,
            label TEXT,
            label_mbid TEXT,
            catalog_number TEXT,
            barcode TEXT,
            format TEXT,
            track_count INTEGER,
            is_primary TEXT,
            source TEXT NOT NULL,
            confidence REAL NOT NULL
        );

        CREATE TABLE musicbrainz_relationships (
            album_id INTEGER NOT NULL REFERENCES albums(id),
            release_mbid TEXT,
            scope TEXT,
            relationship_type TEXT,
            target_type TEXT,
            target_name TEXT,
            target_mbid TEXT,
            attributes TEXT,
            begin_date TEXT,
            end_date TEXT,
            source TEXT NOT NULL,
            confidence REAL NOT NULL
        );
        """
    )


def load_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return read_csv(path)


def insert_musicbrainz_enrichment(
    con: sqlite3.Connection,
    album_ids: dict[tuple[str, str], int],
) -> None:
    for row in load_optional_csv(MB_RELEASES_PATH):
        key = album_key(row.get("artist", ""), row.get("album", ""))
        album_id = album_ids.get(key)
        if not album_id:
            continue
        track_count = (row.get("track_count") or "").strip()
        con.execute(
            """
            INSERT INTO musicbrainz_releases
                (album_id, release_mbid, release_title, date, country, status, label,
                 label_mbid, catalog_number, barcode, format, track_count, is_primary,
                 source, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                album_id,
                row.get("release_mbid") or None,
                row.get("release_title") or "",
                row.get("date") or "",
                row.get("country") or "",
                row.get("status") or "",
                row.get("label") or "",
                row.get("label_mbid") or "",
                row.get("catalog_number") or "",
                row.get("barcode") or "",
                row.get("format") or "",
                int(track_count) if track_count.isdigit() else None,
                row.get("is_primary") or "",
                row.get("source") or "musicbrainz",
                float(row.get("confidence") or 0.75),
            ),
        )

    for row in load_optional_csv(MB_RELATIONSHIPS_PATH):
        key = album_key(row.get("artist", ""), row.get("album", ""))
        album_id = album_ids.get(key)
        if not album_id:
            continue
        con.execute(
            """
            INSERT INTO musicbrainz_relationships
                (album_id, release_mbid, scope, relationship_type, target_type,
                 target_name, target_mbid, attributes, begin_date, end_date,
                 source, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                album_id,
                row.get("release_mbid") or None,
                row.get("scope") or "",
                row.get("relationship_type") or "",
                row.get("target_type") or "",
                row.get("target_name") or "",
                row.get("target_mbid") or "",
                row.get("attributes") or "",
                row.get("begin_date") or "",
                row.get("end_date") or "",
                row.get("source") or "musicbrainz",
                float(row.get("confidence") or 0.75),
            ),
        )


def command_build(_args: argparse.Namespace) -> None:
    seeds = load_seeds()
    seeds_by_key = {album_key(seed.artist, seed.album): seed for seed in seeds}
    vocab = load_vocab()
    resolved = load_resolved()
    descriptors = load_descriptors(seeds_by_key, vocab)

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    create_schema(con)

    tag_ids: dict[tuple[str, str], int] = {}
    for kind in ("mood", "sonic_trait", "scene"):
        for slug, definition in sorted(vocab[kind].items()):
            cur = con.execute(
                "INSERT INTO tags (kind, slug, definition) VALUES (?, ?, ?)",
                (kind, slug, definition),
            )
            tag_ids[(kind, slug)] = int(cur.lastrowid)

    artist_ids: dict[str, int] = {}
    album_ids: dict[tuple[str, str], int] = {}
    for seed in seeds:
        key = album_key(seed.artist, seed.album)
        item = resolved.get(key)
        artist_name = seed.artist
        artist_mbid = item.artist_mbid if item else ""
        artist_norm = normalize(artist_name)
        if artist_norm not in artist_ids:
            cur = con.execute(
                "INSERT INTO artists (name, mbid) VALUES (?, ?)",
                (artist_name, artist_mbid or None),
            )
            artist_ids[artist_norm] = int(cur.lastrowid)
        elif artist_mbid:
            con.execute(
                "UPDATE artists SET mbid = COALESCE(mbid, ?) WHERE id = ?",
                (artist_mbid, artist_ids[artist_norm]),
            )

        album_title = seed.album
        corpus_status = "core" if key in descriptors else "extended"
        cur = con.execute(
            """
            INSERT INTO albums
                (artist_id, title, year, bucket, region, role, corpus_status, rg_mbid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artist_ids[artist_norm],
                album_title,
                seed.year,
                seed.bucket,
                seed.region,
                seed.role,
                corpus_status,
                item.release_group_mbid if item and item.release_group_mbid else None,
            ),
        )
        album_id = int(cur.lastrowid)
        album_ids[key] = album_id
        for kind, slug, source, confidence in descriptors.get(key, []):
            con.execute(
                """
                INSERT OR REPLACE INTO album_tags (album_id, tag_id, source, confidence)
                VALUES (?, ?, ?, ?)
                """,
                (album_id, tag_ids[(kind, slug)], source, confidence),
            )
    insert_musicbrainz_enrichment(con, album_ids)
    con.commit()
    export_jsonl(con)
    con.close()
    unresolved_count = count_unresolved()
    print(f"built {DB_PATH}")
    print(f"exported {JSONL_PATH}")
    if unresolved_count:
        print(f"note: {unresolved_count} unresolved rows remain in {UNRESOLVED_PATH}")


def export_jsonl(con: sqlite3.Connection) -> None:
    with JSONL_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        albums = con.execute(
            """
            SELECT albums.*, artists.name AS artist, artists.mbid AS artist_mbid
            FROM albums JOIN artists ON artists.id = albums.artist_id
            ORDER BY artists.name, albums.year, albums.title
            """
        ).fetchall()
        for album in albums:
            tags = con.execute(
                """
                SELECT tags.kind, tags.slug, album_tags.source, album_tags.confidence
                FROM album_tags JOIN tags ON tags.id = album_tags.tag_id
                WHERE album_tags.album_id = ?
                ORDER BY tags.kind, tags.slug
                """,
                (album["id"],),
            ).fetchall()
            record = {
                "artist": album["artist"],
                "artist_mbid": album["artist_mbid"],
                "album": album["title"],
                "year": album["year"],
                "bucket": album["bucket"],
                "region": album["region"],
                "role": album["role"],
                "corpus_status": album["corpus_status"],
                "release_group_mbid": album["rg_mbid"],
                "descriptors": [
                    {
                        "kind": tag["kind"],
                        "slug": tag["slug"],
                        "source": tag["source"],
                        "confidence": tag["confidence"],
                    }
                    for tag in tags
                ],
            }
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def count_unresolved() -> int:
    if not UNRESOLVED_PATH.exists():
        return 0
    return len(read_csv(UNRESOLVED_PATH))


def decade_label(year: int | None) -> str:
    if year is None:
        return "unknown"
    return f"{(year // 10) * 10}s"


def command_stats(_args: argparse.Namespace) -> None:
    if not DB_PATH.exists():
        raise SystemExit("corpus.db missing. Run: python build_corpus.py build")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    total = con.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
    core = con.execute("SELECT COUNT(*) FROM albums WHERE corpus_status='core'").fetchone()[0]
    tagged = con.execute("SELECT COUNT(DISTINCT album_id) FROM album_tags").fetchone()[0]
    enriched = con.execute("SELECT COUNT(DISTINCT album_id) FROM musicbrainz_releases").fetchone()[0]
    relationships = con.execute("SELECT COUNT(*) FROM musicbrainz_relationships").fetchone()[0]
    year_min, year_max = con.execute("SELECT MIN(year), MAX(year) FROM albums").fetchone()
    unresolved = count_unresolved()
    print(f"albums: {total}")
    print(f"core: {core}")
    print(f"descriptor_coverage: {tagged}/{total}")
    print(f"musicbrainz_release_coverage: {enriched}/{total}")
    print(f"musicbrainz_relationships: {relationships}")
    print(f"years: {year_min}-{year_max}")
    print(f"unresolved_rows: {unresolved}")
    print("buckets:")
    for row in con.execute("SELECT bucket, COUNT(*) AS n FROM albums GROUP BY bucket ORDER BY bucket"):
        print(f"  {row['bucket']}: {row['n']}")
    print("decades:")
    decades: dict[str, int] = {}
    for row in con.execute("SELECT year FROM albums"):
        label = decade_label(row["year"])
        decades[label] = decades.get(label, 0) + 1
    for label in sorted(decades):
        print(f"  {label}: {decades[label]}")
    con.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Music Context Sandbox corpus tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve", help="Resolve seed albums against MusicBrainz")
    resolve.set_defaults(func=command_resolve)

    enrich = subparsers.add_parser("enrich-musicbrainz", help="Fetch MusicBrainz release metadata")
    enrich.set_defaults(func=command_enrich_musicbrainz)

    build = subparsers.add_parser("build", help="Build SQLite corpus and JSONL export")
    build.set_defaults(func=command_build)

    stats = subparsers.add_parser("stats", help="Show corpus coverage statistics")
    stats.set_defaults(func=command_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
