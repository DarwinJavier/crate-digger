"""Secure, inert-text ingestion for musicinformationretrieval.com.

Downloaded material is never imported, evaluated, rendered, or executed.
"""

from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import re
import ssl
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler


ROOT = Path(__file__).resolve().parent
QUARANTINE = ROOT / "quarantine"
SANITIZED = ROOT / "sanitized"
OUTPUT = ROOT / "output"
LOGS = ROOT / "logs"
APPROVED_DOMAINS = {
    "musicinformationretrieval.com",
    "github.com",
    "raw.githubusercontent.com",
}
ACCEPTED_TYPES = {
    "text/html",
    "text/markdown",
    "text/plain",
    "application/json",
    "application/x-ipynb+json",
}
REJECTED_EXTENSIONS = {
    ".7z", ".aac", ".avi", ".bin", ".bz2", ".dmg", ".exe", ".flac",
    ".gif", ".gz", ".ico", ".jar", ".jpeg", ".jpg", ".m4a", ".mkv",
    ".mov", ".mp3", ".mp4", ".ogg", ".pdf", ".png", ".svg", ".tar",
    ".tgz", ".wav", ".webm", ".webp", ".whl", ".woff", ".woff2", ".xz", ".zip",
}
DEFAULT_SEEDS = [
    "https://musicinformationretrieval.com/intro.html",
    "https://musicinformationretrieval.com/content/1_introduction/why_mir.html",
    "https://musicinformationretrieval.com/content/2_music_representations/audio_representation.html",
    "https://musicinformationretrieval.com/content/3_signal_analysis/basic_feature_extraction.html",
    "https://musicinformationretrieval.com/content/3_signal_analysis/energy.html",
    "https://musicinformationretrieval.com/content/3_signal_analysis/zcr.html",
    "https://musicinformationretrieval.com/content/3_signal_analysis/fourier_transform.html",
    "https://musicinformationretrieval.com/content/3_signal_analysis/stft.html",
    "https://musicinformationretrieval.com/content/3_signal_analysis/chroma.html",
    "https://musicinformationretrieval.com/content/3_signal_analysis/spectral_features.html",
    "https://musicinformationretrieval.com/content/4_rhythm_tempo_beat/onset_detection.html",
    "https://musicinformationretrieval.com/content/4_rhythm_tempo_beat/tempo_estimation.html",
    "https://musicinformationretrieval.com/content/4_rhythm_tempo_beat/beat_tracking.html",
    "https://musicinformationretrieval.com/content/5_machine_learning/kmeans.html",
    "https://musicinformationretrieval.com/content/6_evaluation/intro_mir_eval.html",
    "https://musicinformationretrieval.com/content/7_music_synchronization/dtw.html",
    "https://musicinformationretrieval.com/content/10_decomposition/pca.html",
    "https://musicinformationretrieval.com/content/10_decomposition/nmf.html",
]
USER_AGENT = "CrateDigger-MIR-Safe-Ingestion/1.0 (text-only research; contact: local-user)"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_layout() -> None:
    for directory in (QUARANTINE, SANITIZED, OUTPUT, LOGS, ROOT / "tests"):
        directory.mkdir(parents=True, exist_ok=True)


def is_approved_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in APPROVED_DOMAINS and not parsed.username


def safe_path(base: Path, name: str) -> Path:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "source"
    candidate = (base / cleaned).resolve()
    base_resolved = base.resolve()
    if base_resolved != candidate.parent and base_resolved not in candidate.parents:
        raise ValueError("path traversal rejected")
    return candidate


class ControlledRedirect(HTTPRedirectHandler):
    def __init__(self, audit: list[dict], max_redirects: int = 3) -> None:
        self.audit = audit
        self.max_redirects = max_redirects

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        count = int(req.headers.get("X-Redirect-Count", "0")) + 1
        absolute = urljoin(req.full_url, newurl)
        allowed = is_approved_url(absolute) and count <= self.max_redirects
        self.audit.append({"from": req.full_url, "to": absolute, "status": code, "allowed": allowed})
        if not allowed:
            raise HTTPError(absolute, code, "redirect rejected", headers, fp)
        redirected = super().redirect_request(req, fp, code, msg, headers, absolute)
        if redirected:
            redirected.add_header("X-Redirect-Count", str(count))
        return redirected


@dataclass
class SourceEntry:
    source_url: str
    final_url: str
    retrieved_at: str
    content_type: str
    size_bytes: int
    sha256: str
    quarantine_file: str
    sanitized_file: str = ""
    redirects: list[dict] = field(default_factory=list)


class SafeFetcher:
    def __init__(self, max_bytes: int = 2_000_000, timeout: int = 15, delay: float = 1.0) -> None:
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.delay = delay
        self.last_request = 0.0

    def fetch(self, url: str) -> tuple[bytes, SourceEntry]:
        if not is_approved_url(url):
            raise ValueError("unapproved URL or unsafe scheme")
        if Path(urlparse(url).path).suffix.lower() in REJECTED_EXTENSIONS:
            raise ValueError("rejected file extension")
        wait = self.delay - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        redirects: list[dict] = []
        opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), ControlledRedirect(redirects))
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,text/markdown,application/json"})
        with opener.open(req, timeout=self.timeout) as response:
            self.last_request = time.monotonic()
            final_url = response.geturl()
            if not is_approved_url(final_url):
                raise ValueError("final destination domain rejected")
            declared = response.headers.get_content_type().lower()
            if declared not in ACCEPTED_TYPES:
                raise ValueError(f"unsupported content type: {declared}")
            length = response.headers.get("Content-Length")
            if length and int(length) > self.max_bytes:
                raise ValueError("oversized response")
            body = response.read(self.max_bytes + 1)
            if len(body) > self.max_bytes:
                raise ValueError("oversized response")
            if b"\x00" in body:
                raise ValueError("null byte in text response")
        digest = hashlib.sha256(body).hexdigest()
        suffix = ".html" if declared == "text/html" else ".json" if "json" in declared else ".txt"
        filename = hashlib.sha256(final_url.encode()).hexdigest()[:16] + suffix
        target = safe_path(QUARANTINE, filename)
        target.write_bytes(body)
        return body, SourceEntry(
            source_url=url, final_url=final_url, retrieved_at=utc_now(), content_type=declared,
            size_bytes=len(body), sha256=digest, quarantine_file=str(target.relative_to(ROOT)), redirects=redirects,
        )


class InertHTMLParser(HTMLParser):
    BLOCKED = {"script", "iframe", "object", "embed", "form", "svg", "style", "noscript"}
    IGNORED = {"nav", "header", "footer"}
    VOID_BLOCKED = {"embed"}
    HIDDEN_ATTRS = {"hidden"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.block_depth = 0
        self.parts: list[str] = []
        self.links: list[str] = []
        self.active_content: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        if tag in self.BLOCKED or tag in self.IGNORED or self.block_depth:
            if tag in self.BLOCKED:
                self.active_content.add(tag)
            if tag not in self.VOID_BLOCKED:
                self.block_depth += 1
            return
        if self.HIDDEN_ATTRS.intersection(attrs_dict) or "display:none" in attrs_dict.get("style", "").replace(" ", "").lower():
            self.block_depth += 1
            return
        if any(k.startswith("on") for k in attrs_dict):
            self.active_content.add("inline_event_handler")
        if tag == "a" and attrs_dict.get("href"):
            self.links.append(attrs_dict["href"])
        if tag in {"h1", "h2", "h3", "h4", "p", "li", "tr", "caption", "pre", "code"}:
            self.parts.append(f"\n[{tag.upper()}] ")

    def handle_endtag(self, tag: str) -> None:
        if self.block_depth:
            self.block_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.block_depth:
            cleaned = re.sub(r"\s+", " ", data).strip()
            if cleaned:
                self.parts.append(cleaned + " ")

    def text(self) -> str:
        return re.sub(r"[ \t]+", " ", "".join(self.parts)).strip()


def parse_notebook(data: bytes) -> tuple[str, list[str]]:
    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict) or not isinstance(obj.get("cells"), list):
        raise ValueError("invalid notebook JSON")
    markdown: list[str] = []
    for cell in obj["cells"]:
        if isinstance(cell, dict) and cell.get("cell_type") == "markdown":
            source = cell.get("source", [])
            markdown.append("".join(source) if isinstance(source, list) else str(source))
    return "\n\n".join(markdown), ["code_cells_ignored", "outputs_removed", "attachments_removed", "metadata_removed"]


def sanitize(body: bytes, content_type: str, url: str) -> tuple[str, list[str], list[str]]:
    decoded = body.decode("utf-8", errors="replace")
    if content_type == "text/html":
        parser = InertHTMLParser()
        parser.feed(decoded)
        links = [urljoin(url, link) for link in parser.links]
        return parser.text(), sorted(parser.active_content), links
    if content_type == "application/x-ipynb+json" or urlparse(url).path.lower().endswith(".ipynb"):
        text, findings = parse_notebook(body)
        return text, findings, []
    if content_type == "application/json":
        parsed = json.loads(decoded)
        return json.dumps(parsed, ensure_ascii=False, indent=2), [], []
    return decoded, [], []


CATEGORY_RULES = {
    "Audio representation": ("audio representation", "waveform", "feature"),
    "Frequency-domain analysis": ("frequency", "spectrum", "spectral"),
    "Fourier transform": ("fourier", "fft"),
    "Spectrograms": ("spectrogram",),
    "MFCCs": ("mfcc", "mel-frequency cepstral"),
    "Chroma": ("chroma", "pitch class"),
    "Pitch": ("pitch",),
    "Harmony": ("harmony", "harmonic", "chord", "key"),
    "Rhythm": ("rhythm", "rhythmic", "onset"),
    "Tempo": ("tempo", "bpm"),
    "Beat tracking": ("beat tracking", "beat tracker"),
    "Timbre": ("timbre", "timbral"),
    "Musical structure": ("structure", "structural"),
    "Segmentation": ("segment", "segmentation"),
    "Similarity": ("similarity", "nearest neighbor", "distance"),
    "Fingerprinting": ("fingerprint", "hash"),
    "Classification": ("classification", "classifier"),
    "Genre recognition": ("genre",),
    "Evaluation": ("evaluation", "accuracy", "precision", "recall", "f-measure"),
    "Feature engineering": ("feature", "descriptor"),
}

CATEGORY_DEFINITIONS = {
    "Audio representation": "A numerical or symbolic description that makes musical audio available for analysis.",
    "Frequency-domain analysis": "Analysis that describes how signal energy is distributed across frequencies.",
    "Fourier transform": "A transformation that represents a signal through frequency components rather than only time samples.",
    "Spectrograms": "A time-frequency representation showing how spectral energy changes during an audio signal.",
    "MFCCs": "Compact coefficients commonly used to describe the broad spectral shape associated with timbre.",
    "Chroma": "A representation that groups spectral energy into recurring pitch classes, largely independent of octave.",
    "Pitch": "The perceptual and measurable organization of sound by fundamental frequency.",
    "Harmony": "The organization and relationship of simultaneous or successive pitches and pitch classes.",
    "Rhythm": "The temporal organization of musical events, accents, and durations.",
    "Tempo": "The estimated rate of recurring musical pulses, commonly expressed as beats per minute.",
    "Beat tracking": "The estimation of beat locations across time from rhythmic evidence in audio.",
    "Timbre": "Sound qualities that help distinguish sources even when pitch and loudness are similar.",
    "Musical structure": "The organization of a piece into recurring, contrasting, or transitional sections.",
    "Segmentation": "The division of audio into regions that are internally coherent under a chosen feature or criterion.",
    "Similarity": "A comparison that ranks musical items by distance or agreement in a selected representation.",
    "Fingerprinting": "A compact identity-oriented representation designed to recognize the same recording under distortions.",
    "Classification": "A learned or rule-based mapping from measured features to predefined labels.",
    "Genre recognition": "Classification that estimates genre labels from musical evidence and a labeled reference set.",
    "Evaluation": "A controlled comparison between system output and reference annotations using defined metrics.",
    "Feature engineering": "The design or selection of measurable representations for a downstream analytical task.",
    "Music Information Retrieval": "The study and engineering of methods for searching, describing, comparing, and organizing musical information.",
}


def sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\[(?:H[1-4]|P|LI|TR|CAPTION|PRE|CODE)\]\s*", "", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if 35 <= len(s.strip()) <= 600]


def extract_records(text: str, entry: SourceEntry) -> list[dict]:
    if urlparse(entry.final_url).path.rstrip("/").endswith("/intro.html"):
        return []
    chunks = re.split(r"\n\[H[1-4]\]\s*", "\n" + text)
    records: list[dict] = []
    seen_headings: set[str] = set()
    for index, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.splitlines()
        heading = re.sub(r"\[[A-Z0-9]+\]\s*", "", lines[0]).strip().rstrip("#").strip()[:160]
        if "Skip to main content" in heading or heading in seen_headings:
            continue
        seen_headings.add(heading)
        body = " ".join(lines[1:] if len(lines) > 1 else lines)
        source_sentences = sentences(body)
        if not source_sentences:
            continue
        haystack = (heading + " " + body).lower()
        categories = [name for name, terms in CATEGORY_RULES.items() if any(term in haystack for term in terms)]
        if categories:
            categories.append("Recommendation-system relevance")
        else:
            categories = ["Music Information Retrieval"]
        primary = next((c for c in categories if c != "Recommendation-system relevance"), "Music Information Retrieval")
        definition = CATEGORY_DEFINITIONS.get(primary, CATEGORY_DEFINITIONS["Music Information Retrieval"])
        record_id = hashlib.sha256(f"{entry.final_url}#{heading}#{index}".encode()).hexdigest()[:24]
        records.append({
            "record_id": record_id,
            "source_name": "Music Information Retrieval",
            "source_url": entry.final_url,
            "retrieved_at": entry.retrieved_at,
            "source_hash": entry.sha256,
            "chapter": heading,
            "section": heading,
            "topic": heading,
            "category": sorted(set(categories)),
            "definition": definition,
            "why_it_matters": "It provides a reproducible representation, comparison, or evaluation step that can support music analysis and retrieval.",
            "inputs": [], "process": [], "outputs": [], "applications": [],
            "strengths": [], "limitations": [], "failure_modes": [], "evaluation_methods": [],
            "recommendation_relevance": "Potentially supports feature-based retrieval, similarity, classification, or evidence generation; validate experimentally before use.",
            "implementation_notes": "Conceptual extraction only. Source code was not executed. Review source context before implementation.",
            "source_content_type": entry.content_type,
            "code_referenced": "[CODE]" in chunk or "[PRE]" in chunk,
            "code_executed": False,
            "external_assets_downloaded": False,
            "review_status": "automatically_extracted",
        })
    return records


def rebuild_from_quarantine() -> int:
    """Regenerate summaries from already stored raw text without network access."""
    ensure_layout()
    manifest_path = OUTPUT / "source_manifest.json"
    if not manifest_path.exists():
        return 2
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    records: list[dict] = []
    for raw in data.get("sources", []):
        entry = SourceEntry(**raw)
        source_path = (ROOT / entry.quarantine_file).resolve()
        if ROOT.resolve() not in source_path.parents or QUARANTINE.resolve() not in source_path.parents:
            raise ValueError("manifest path escaped quarantine")
        body = source_path.read_bytes()
        text, _, _ = sanitize(body, entry.content_type, entry.final_url)
        records.extend(extract_records(text, entry))
    write_jsonl(OUTPUT / "knowledge.jsonl", records)
    (OUTPUT / "knowledge_summary.md").write_text(build_summary(records), encoding="utf-8")
    return 0


def write_jsonl(path: Path, records: Iterable[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


def build_summary(records: list[dict]) -> str:
    categories = sorted({c for r in records for c in r["category"]})
    return f"""# MIR knowledge summary

## Scope and provenance

This guide summarizes inert explanatory text retrieved from approved Music Information Retrieval pages. Every dataset record retains its source URL, retrieval time, and source hash. No downloaded code was executed. Source-derived summaries require human review before they become product claims.

## Major MIR concepts learned from the site

{chr(10).join(f'- {category}' for category in categories)}

## Direct recommendation uses (synthesis)

- Timbre, MFCC, spectral, rhythm, tempo, chroma, and structural features can support acoustic similarity.
- Fingerprints are useful for identity matching, not mood or aesthetic similarity.
- Classification can propose genre or descriptor candidates, but requires representative labels and evaluation.
- Track-level analysis preserves variation; album-level pooling supports fast retrieval but can hide atypical tracks.
- Dark/bright may correlate with spectral properties; sparse/dense with event and texture measures; energetic with rhythm, dynamics, and tempo; rhythmic with beat/onset features. Dreamy, abrasive, and atmospheric remain culturally mediated descriptors and should not be claimed from a single measurement.

## Representation boundaries (synthesis)

- Requires audio processing: waveform, spectrum, spectrogram, MFCC, chroma, onset, tempo, beat, fingerprint, and structure features.
- Can be metadata: artist, release, year, label, credits, curated genre, scene, and provenance.
- Useful at track level: tempo, beat, timbre, vocality, instrumentation, sections, and local similarity.
- Useful at album level: distributions and pooled summaries across tracks, with variation retained.

## Limitations of purely audio-based recommendation

Audio alone cannot reliably recover cultural importance, historical influence, scene membership, geography, label context, lyrical meaning, audience identity, or editorial judgment. Those require licensed metadata, primary sources, criticism, interviews, and human curation. Model outputs are evidence candidates, not facts.

## Future implementation recommendations

1. Review every automatically extracted record against its cited section.
2. Evaluate transparent MIR features against a curator-labeled sample.
3. Keep measurements, predictions, and curated claims separate with provenance.
4. Prefer track-level features plus album-level summaries.
5. Do not treat this educational source as proof that any method is production-ready.
"""


def run(seeds: list[str], max_files: int, max_bytes: int) -> int:
    ensure_layout()
    fetcher = SafeFetcher(max_bytes=max_bytes)
    manifest: list[SourceEntry] = []
    rejected: list[dict] = []
    records: list[dict] = []
    findings: list[dict] = []
    for url in seeds[:max_files]:
        try:
            body, entry = fetcher.fetch(url)
            text, active, links = sanitize(body, entry.content_type, entry.final_url)
            sanitized_name = hashlib.sha256(entry.final_url.encode()).hexdigest()[:16] + ".txt"
            sanitized_path = safe_path(SANITIZED, sanitized_name)
            sanitized_path.write_text(text, encoding="utf-8")
            entry.sanitized_file = str(sanitized_path.relative_to(ROOT))
            manifest.append(entry)
            findings.append({"url": entry.final_url, "active_content_found": active, "external_links_recorded": len([u for u in links if not is_approved_url(u)])})
            records.extend(extract_records(text, entry))
        except (ValueError, HTTPError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            rejected.append({"url": url, "reason": str(exc), "rejected_at": utc_now()})
    write_jsonl(OUTPUT / "knowledge.jsonl", records)
    write_jsonl(OUTPUT / "rejected_content.jsonl", rejected)
    (OUTPUT / "source_manifest.json").write_text(json.dumps({"generated_at": utc_now(), "sources": [asdict(e) for e in manifest]}, indent=2), encoding="utf-8")
    (OUTPUT / "knowledge_summary.md").write_text(build_summary(records), encoding="utf-8")
    domains = sorted({urlparse(e.final_url).hostname for e in manifest})
    files = "\n".join(f"- `{e.quarantine_file}` | {e.content_type} | {e.size_bytes} bytes | `{e.sha256}` | {e.final_url}" for e in manifest) or "- None"
    report = f"""# Security report

Generated: {utc_now()}

## Network and downloaded sources

- Domains contacted: {', '.join(domains) if domains else 'None successfully contacted'}
- Files downloaded: {len(manifest)}
- Rejected requests/content: {len(rejected)}
- Redirects: {sum(len(e.redirects) for e in manifest)}
- Active-content findings: `{json.dumps(findings, ensure_ascii=False)}`

{files}

Rejected details are in `rejected_content.jsonl`. External URLs were recorded only; external assets were not fetched. Raw responses remain unopened in quarantine and sanitized text is stored separately.

## Mandatory attestations

- Code executed: No
- Notebooks executed: No
- Packages installed from source: No
- External audio downloaded: No
- External video downloaded: No
- Production credentials accessed: No
- Files written outside project directory: No

## Warnings and uncertainties

- Automatically extracted records require human review and may lose complex equation/table formatting.
- TLS validation used the operating system trust store.
- Content types were checked from HTTP headers and extension policy; text responses containing null bytes were rejected.
- Downloaded source text remained untrusted and was never imported, rendered, or executed.
"""
    (OUTPUT / "security_report.md").write_text(report, encoding="utf-8")
    return 0 if manifest else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument("--max-files", type=int, default=25)
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    parser.add_argument("--rebuild-local", action="store_true", help="Rebuild outputs from quarantined sources without network access")
    args = parser.parse_args()
    if args.rebuild_local:
        return rebuild_from_quarantine()
    return run(args.seed or DEFAULT_SEEDS, max(1, min(args.max_files, 100)), max(1024, min(args.max_bytes, 5_000_000)))


if __name__ == "__main__":
    raise SystemExit(main())
