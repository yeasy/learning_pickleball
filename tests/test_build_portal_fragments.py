#!/usr/bin/env python3
"""End-to-end contracts for the portal fragment emitter."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.build_html_reader import parse_summary
from tools.build_portal_fragments import BOOK_ROUTE, slug_and_kind


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/build_portal_fragments.py"


def _run_build(book: Path, portal: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), "--book", str(book), "--portal", str(portal)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _make_book(root: Path, *, duplicate_slug: bool = False, bad_link: bool = False) -> None:
    language = root / "cn"
    language.mkdir(parents=True)
    entries = [("README.md", "Index")]
    for number in range(1, 28):
        suffix = "same" if duplicate_slug and number in (26, 27) else f"chapter-{number:02d}"
        entries.append((f"{number:02d}_{suffix}.md", f"Chapter {number}"))
    summary = ["# Fixture", ""]
    for path, title in entries:
        summary.append(f"* [{title}]({path})")
        body = f"# {title}\n\nFixture paragraph.\n"
        if bad_link and path == "README.md":
            body += "\n[Missing chapter](missing.md)\n"
        (language / path).write_text(body, encoding="utf-8")
    (language / "SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")


class PortalFragmentTests(unittest.TestCase):
    def test_build_emits_28_summary_ordered_unique_chapters_with_valid_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            portal = Path(tmp) / "portal"
            result = _run_build(ROOT, portal)
            self.assertEqual(0, result.returncode, result.stderr)
            data_path = portal / "src/data/book-learning-pickleball.json"
            chapters = json.loads(data_path.read_text(encoding="utf-8"))
            expected = [
                slug_and_kind(path)[0]
                for kind, path, _title, _level in parse_summary(str(ROOT / "cn"))
                if kind == "file"
            ]
            slugs = [chapter["slug"] for chapter in chapters]
            self.assertEqual(28, len(chapters))
            self.assertEqual(expected, slugs)
            self.assertEqual(len(slugs), len(set(slugs)))

            all_html = "\n".join(chapter["bodyHtml"] for chapter in chapters)
            for token in ("MERMAIDZZ", "PLACEHOLDER", "@@"):
                self.assertNotIn(token, all_html)

            image_names = set(re.findall(rf'{re.escape(BOOK_ROUTE)}/img/([^"\s<]+)', all_html))
            self.assertTrue(image_names)
            image_root = portal / "public/books/learning-pickleball/img"
            self.assertTrue(all((image_root / name).is_file() for name in image_names))

            valid_routes = {f"{BOOK_ROUTE}/"}
            valid_routes.update(f"{BOOK_ROUTE}/{slug}/" for slug in slugs if slug != "index")
            internal_routes = set(re.findall(r'href="(/books/learning-pickleball/[^"#?]*)"', all_html))
            self.assertTrue(internal_routes)
            self.assertTrue(internal_routes <= valid_routes, internal_routes - valid_routes)

    def test_mermaid_uses_committed_fallback_when_renderer_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            mmdc = fake_bin / "mmdc"
            mmdc.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
            mmdc.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            portal = tmp_path / "portal"
            result = _run_build(ROOT, portal, env)
            self.assertEqual(0, result.returncode, result.stderr)
            chapters = json.loads(
                (portal / "src/data/book-learning-pickleball.json").read_text(encoding="utf-8")
            )
            index = next(chapter for chapter in chapters if chapter["slug"] == "index")
            self.assertIn('class="book-paths"', index["bodyHtml"])
            self.assertNotIn("MERMAIDZZ", index["bodyHtml"])

    def test_duplicate_slugs_fail_explicitly_with_nonzero_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            book = tmp_path / "book"
            _make_book(book, duplicate_slug=True)
            result = _run_build(book, tmp_path / "portal")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("duplicate slug", result.stderr.lower())

    def test_unresolved_internal_markdown_link_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            book = tmp_path / "book"
            _make_book(book, bad_link=True)
            result = _run_build(book, tmp_path / "portal")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("unresolved internal markdown link", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
