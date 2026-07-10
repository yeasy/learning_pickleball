#!/usr/bin/env python3
"""Executable contracts for publication artifact content validation."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/validate_publication_artifacts.py"
HTML_TITLE = "Learning Pickleball | 学打匹克球"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _write_docx_fixture(path: Path, title: str | None) -> None:
    title_xml = f"<dc:title>{title}</dc:title>" if title is not None else ""
    core_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties
    xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    xmlns:dc="http://purl.org/dc/elements/1.1/">
  {title_xml}
</cp:coreProperties>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("docProps/core.xml", core_xml)


class PublicationArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dist = self.root / "dist"
        self.dist.mkdir()
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        _write_executable(
            fake_bin / "pdfinfo",
            """#!/usr/bin/env python3
import sys
print("Pages: 1")
print("Page size: 612 x 792 pts")
raise SystemExit(0)
""",
        )
        _write_executable(
            fake_bin / "pdftotext",
            """#!/usr/bin/env python3
import os
import sys
from pathlib import Path
name = Path(sys.argv[-2]).name
if name.endswith("-cn.pdf"):
    print(os.environ.get("FAKE_CN_PDF_TEXT", "学打匹克球\\n作者 yeasy"))
elif name.endswith("-en.pdf"):
    print(os.environ.get("FAKE_EN_PDF_TEXT", "Learning Pickleball\\nAuthor yeasy"))
else:
    print("unknown PDF", file=sys.stderr)
    raise SystemExit(3)
""",
        )
        self.env = os.environ.copy()
        self.env["PATH"] = f"{fake_bin}{os.pathsep}{self.env['PATH']}"
        (self.dist / "learning_pickleball-v1-cn.pdf").write_bytes(b"%PDF fixture cn")
        (self.dist / "learning_pickleball-v1-en.pdf").write_bytes(b"%PDF fixture en")
        for language, title in (("cn", "学打匹克球"), ("en", "Learning Pickleball")):
            _write_docx_fixture(
                self.dist / f"learning_pickleball-{language}.docx",
                title,
            )
        (self.dist / "learning-pickleball-v1.html").write_text(
            f"<!doctype html><html><head><title>{HTML_TITLE}</title></head><body>book</body></html>",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, *extra: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--dist",
                str(self.dist),
                "--require-docx",
                "--require-html",
                "--html-title",
                HTML_TITLE,
                *extra,
            ],
            cwd=ROOT,
            env=env or self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_complete_bundle_with_expected_pdf_and_html_titles_passes(self) -> None:
        result = self._run()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("validated PDFs: 2", result.stdout)
        self.assertIn("validated HTML title", result.stdout)

    def test_wrong_pdf_first_page_title_fails(self) -> None:
        env = self.env | {"FAKE_EN_PDF_TEXT": "Different Book"}
        result = self._run(env=env)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Learning Pickleball", result.stderr)
        self.assertIn("first page", result.stderr)

    def test_wrong_html_title_fails(self) -> None:
        html = self.dist / "learning-pickleball-v1.html"
        html.write_text(
            "<!doctype html><html><head><title>Wrong title</title></head></html>",
            encoding="utf-8",
        )
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("HTML title mismatch", result.stderr)

    def test_wrong_docx_core_title_fails(self) -> None:
        _write_docx_fixture(
            self.dist / "learning_pickleball-en.docx",
            "Different Book",
        )
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("DOCX title mismatch", result.stderr)
        self.assertIn("Learning Pickleball", result.stderr)

    def test_missing_docx_core_title_fails(self) -> None:
        _write_docx_fixture(self.dist / "learning_pickleball-cn.docx", None)
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("DOCX core title is missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
