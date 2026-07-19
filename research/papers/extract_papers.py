from pathlib import Path
import json

from pypdf import PdfReader


root = Path(__file__).resolve().parents[2]
source = root / "research" / "papers"
output = source / "extracted"
output.mkdir(parents=True, exist_ok=True)
manifest = []
for path in sorted(source.glob("*.pdf")):
    reader = PdfReader(path)
    text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    stem = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in path.stem)
    text_path = output / f"{stem}.txt"
    text_path.write_text(text, encoding="utf-8")
    manifest.append({
        "file": path.name,
        "pages": len(reader.pages),
        "title": str((reader.metadata or {}).get("/Title", "")),
        "author": str((reader.metadata or {}).get("/Author", "")),
        "text_characters": len(text),
        "text_file": str(text_path.relative_to(root)),
    })
(output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
