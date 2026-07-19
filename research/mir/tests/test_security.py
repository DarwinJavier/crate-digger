import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mir_ingest


class SecurityTests(unittest.TestCase):
    def test_html_active_content_is_stripped(self):
        payload = b'<h1>Safe</h1><script>alert(1)</script><iframe src="https://evil.invalid"></iframe><embed src=x><p onclick="x()">Useful text.</p>'
        text, findings, _ = mir_ingest.sanitize(payload, "text/html", "https://musicinformationretrieval.com/x.html")
        self.assertIn("Useful text", text)
        self.assertNotIn("alert", text)
        self.assertTrue({"script", "iframe", "embed"}.issubset(set(findings)))

    def test_notebook_markdown_only(self):
        notebook = {"metadata": {"payload": "ignore"}, "cells": [
            {"cell_type": "markdown", "source": ["# Safe knowledge"], "attachments": {"x": "data"}},
            {"cell_type": "code", "source": ["__import__('os').system('bad')"], "outputs": [{"data": "bad"}]},
        ]}
        text, findings = mir_ingest.parse_notebook(json.dumps(notebook).encode())
        self.assertIn("Safe knowledge", text)
        self.assertNotIn("__import__", text)
        self.assertIn("outputs_removed", findings)

    def test_unsafe_schemes_and_domains_rejected(self):
        for url in ("file:///etc/passwd", "javascript:alert(1)", "data:text/plain,x", "ftp://musicinformationretrieval.com/x", "https://evil.invalid/x"):
            self.assertFalse(mir_ingest.is_approved_url(url))

    def test_path_traversal_rejected_or_normalized_inside(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            result = mir_ingest.safe_path(base, "../../evil.txt")
            self.assertEqual(result.parent, base.resolve())

    def test_oversized_fetch_rejection_logic(self):
        self.assertLess(mir_ingest.SafeFetcher(max_bytes=10).max_bytes, len(b"01234567890"))

    def test_redirect_handler_rejects_external(self):
        audit = []
        handler = mir_ingest.ControlledRedirect(audit)
        class Req:
            full_url = "https://musicinformationretrieval.com/x"
            headers = {}
        with self.assertRaises(Exception):
            handler.redirect_request(Req(), None, 302, "", {}, "https://evil.invalid/x")
        self.assertFalse(audit[0]["allowed"])

    def test_no_execution_or_subprocess_primitives(self):
        tree = ast.parse(Path(mir_ingest.__file__).read_text(encoding="utf-8"))
        banned_calls = {"eval", "exec", "compile", "__import__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, banned_calls)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {alias.name.split(".")[0] for alias in node.names}
                self.assertFalse(names.intersection({"subprocess", "pickle", "marshal", "importlib"}))

    def test_hash_and_provenance_are_preserved(self):
        body = b"A meaningful explanatory sentence about rhythm and musical similarity."
        entry = mir_ingest.SourceEntry("https://musicinformationretrieval.com/x", "https://musicinformationretrieval.com/x", "2026-01-01T00:00:00+00:00", "text/plain", len(body), hashlib.sha256(body).hexdigest(), "quarantine/x.txt")
        records = mir_ingest.extract_records(body.decode(), entry)
        self.assertTrue(records)
        self.assertEqual(records[0]["source_url"], entry.final_url)
        self.assertEqual(records[0]["source_hash"], entry.sha256)
        self.assertFalse(records[0]["code_executed"])

    def test_project_outputs_resolve_inside_root(self):
        for path in (mir_ingest.QUARANTINE, mir_ingest.SANITIZED, mir_ingest.OUTPUT, mir_ingest.LOGS):
            self.assertIn(mir_ingest.ROOT.resolve(), path.resolve().parents)


if __name__ == "__main__":
    unittest.main()
