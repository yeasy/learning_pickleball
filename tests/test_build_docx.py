#!/usr/bin/env python3
"""Standard-library validation for reproducible DOCX builds."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/build_docx.py"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DC = "{http://purl.org/dc/elements/1.1/}"


def _summary_paths(language: str) -> list[Path]:
    text = (ROOT / language / "SUMMARY.md").read_text(encoding="utf-8")
    paths = re.findall(r"^\s*[-*]\s+\[[^]]+\]\(([^)#?]+\.md)", text, re.M)
    return [ROOT / language / path for path in paths]


def _expected_h1(language: str) -> list[str]:
    titles = []
    for path in _summary_paths(language):
        match = re.search(r"^#\s+(.+?)\s*$", path.read_text(encoding="utf-8"), re.M)
        if not match:
            raise AssertionError(f"missing H1: {path}")
        titles.append(match.group(1))
    return titles


def _read_xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    return ET.fromstring(archive.read(name))


def _heading1_texts(document: ET.Element) -> list[str]:
    headings = []
    for paragraph in document.iter(W + "p"):
        style = paragraph.find(f"{W}pPr/{W}pStyle")
        if style is None or style.get(W + "val") not in {"Heading1", "1"}:
            continue
        headings.append("".join(node.text or "" for node in paragraph.iter(W + "t")))
    return headings


def _styled_paragraph_texts(document: ET.Element, style_name: str) -> list[str]:
    texts = []
    for paragraph in document.iter(W + "p"):
        style = paragraph.find(f"{W}pPr/{W}pStyle")
        if style is None or style.get(W + "val") != style_name:
            continue
        texts.append("".join(node.text or "" for node in paragraph.iter(W + "t")))
    return texts


class DocxBuildTests(unittest.TestCase):
    def test_builds_both_languages_from_summary_order_and_replaces_old_outputs(self) -> None:
        self.assertTrue(SCRIPT.is_file(), "tools/build_docx.py is required")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            for language in ("cn", "en"):
                (output / f"learning_pickleball-{language}.docx").write_bytes(b"stale")
            env = os.environ.copy()
            env["SOURCE_DATE_EPOCH"] = "0"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--output-dir", str(output)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("DeprecationWarning", result.stderr)

            for language, title in (("cn", "学打匹克球"), ("en", "Learning Pickleball")):
                path = output / f"learning_pickleball-{language}.docx"
                self.assertTrue(zipfile.is_zipfile(path), path)
                with zipfile.ZipFile(path) as archive:
                    names = set(archive.namelist())
                    required = {
                        "[Content_Types].xml",
                        "word/document.xml",
                        "word/styles.xml",
                        "word/settings.xml",
                        "word/numbering.xml",
                        "word/_rels/document.xml.rels",
                        "docProps/core.xml",
                    }
                    self.assertTrue(required <= names, required - names)
                    document = _read_xml(archive, "word/document.xml")
                    self.assertEqual(_expected_h1(language), _heading1_texts(document))
                    paragraph_texts = [
                        "".join(node.text or "" for node in paragraph.iter(W + "t"))
                        for paragraph in document.iter(W + "p")
                    ]
                    self.assertNotIn("English Version", paragraph_texts)
                    self.assertNotIn("中文版", paragraph_texts)
                    self.assertEqual(_expected_h1(language), _styled_paragraph_texts(document, "TOC1"))
                    expected_toc_heading = "目录" if language == "cn" else "Table of Contents"
                    self.assertEqual(
                        [expected_toc_heading],
                        _styled_paragraph_texts(document, "TOCHeading"),
                    )
                    toc = document.find(f".//{W}sdt")
                    self.assertIsNotNone(toc)
                    page_breaks = [
                        node for node in toc.iter(W + "br") if node.get(W + "type") == "page"
                    ]
                    self.assertFalse(page_breaks, "TOC must rely on the following Heading 1 page break")
                    styles = _read_xml(archive, "word/styles.xml")
                    defined_styles = {
                        style.get(W + "styleId") for style in styles.iter(W + "style")
                    }
                    used_styles = {
                        node.get(W + "val")
                        for tag in ("pStyle", "rStyle", "tblStyle")
                        for node in document.iter(W + tag)
                    }
                    self.assertFalse(used_styles - defined_styles, used_styles - defined_styles)
                    numbering = archive.read("word/numbering.xml").decode("utf-8")
                    self.assertNotIn("\uf0b7", numbering)
                    self.assertIn('w:val="•"', numbering)
                    settings = _read_xml(archive, "word/settings.xml")
                    self.assertIsNotNone(settings.find(W + "updateFields"))
                    core = _read_xml(archive, "docProps/core.xml")
                    self.assertEqual(title, core.findtext(DC + "title"))
                    media = [name for name in names if name.startswith("word/media/")]
                    self.assertGreater(len(media), 1, "cover and chapter images must be embedded")

            replay = output / "replay"
            replay_result = subprocess.run(
                [sys.executable, str(SCRIPT), "--output-dir", str(replay)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, replay_result.returncode, replay_result.stderr)
            for language in ("cn", "en"):
                name = f"learning_pickleball-{language}.docx"
                self.assertEqual((output / name).read_bytes(), (replay / name).read_bytes())

    def test_ooxml_zip_is_byte_identical_across_clock_ticks_with_normalized_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            second = root / "second"
            env = os.environ.copy()
            env["SOURCE_DATE_EPOCH"] = "0"
            command = [sys.executable, str(SCRIPT)]

            first_result = subprocess.run(
                [*command, "--output-dir", str(first)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, first_result.returncode, first_result.stderr)
            time.sleep(3.1)
            second_result = subprocess.run(
                [*command, "--output-dir", str(second)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, second_result.returncode, second_result.stderr)

            for language in ("cn", "en"):
                name = f"learning_pickleball-{language}.docx"
                first_path = first / name
                second_path = second / name
                self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
                with zipfile.ZipFile(first_path) as archive:
                    infos = archive.infolist()
                    self.assertEqual(sorted(info.filename for info in infos), archive.namelist())
                    self.assertEqual(
                        {(1980, 1, 1, 0, 0, 0)},
                        {info.date_time for info in infos},
                    )
                    self.assertEqual({0}, {info.create_system for info in infos})
                    self.assertEqual({0o600 << 16}, {info.external_attr for info in infos})
                    self.assertEqual({0}, {info.internal_attr for info in infos})
                    self.assertEqual({b""}, {info.extra for info in infos})
                    self.assertEqual({b""}, {info.comment for info in infos})
                    self.assertEqual(
                        {zipfile.ZIP_DEFLATED},
                        {info.compress_type for info in infos},
                    )
                    self.assertEqual(b"", archive.comment)

    def test_reference_builder_sets_book_page_and_heading_breaks(self) -> None:
        script = ROOT / "tools/docx/build_reference_doc.py"
        self.assertTrue(script.is_file(), "reference builder is required")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "reference.docx"
            result = subprocess.run(
                [sys.executable, str(script), "--lang", "en", "--output", str(target)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            with zipfile.ZipFile(target) as archive:
                styles = _read_xml(archive, "word/styles.xml")
                heading = next(
                    style for style in styles.findall(W + "style")
                    if style.get(W + "styleId") == "Heading1"
                )
                self.assertIsNotNone(heading.find(f"{W}pPr/{W}pageBreakBefore"))
                section = _read_xml(archive, "word/document.xml").find(f".//{W}sectPr")
                page_size = section.find(W + "pgSz")
                self.assertEqual("10488", page_size.get(W + "w"))
                self.assertEqual("14740", page_size.get(W + "h"))

    def test_dependencies_are_pinned_and_only_generated_root_docx_are_ignored(self) -> None:
        requirements_path = ROOT / "requirements-docx.txt"
        self.assertTrue(requirements_path.is_file(), "requirements-docx.txt is required")
        requirements = requirements_path.read_text(encoding="utf-8").splitlines()
        packages = [line for line in requirements if line and not line.startswith("#")]
        self.assertTrue(packages)
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.-]+", line) for line in packages))
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/learning_pickleball-*.docx", ignore)
        self.assertNotIn("*.docx", ignore)
        design = (ROOT / "tools/docx/DESIGN.md").read_text(encoding="utf-8")
        self.assertIn("python3 tools/build_docx.py", design)
        self.assertIn("requirements-docx.txt", design)


if __name__ == "__main__":
    unittest.main()
