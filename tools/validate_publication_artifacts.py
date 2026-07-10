#!/usr/bin/env python3
"""Validate publication bundles by inspecting artifact structure and reader-facing titles."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path


PDF_TITLES = {"cn": "学打匹克球", "en": "Learning Pickleball"}
DEFAULT_HTML_TITLE = "Learning Pickleball | 学打匹克球"
DC_TITLE = "{http://purl.org/dc/elements/1.1/}title"


class ArtifactError(RuntimeError):
    """A publication artifact is missing, corrupt, or mislabeled."""


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.casefold() == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)

    @property
    def title(self) -> str:
        return "".join(self.parts).strip()


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _run(command: list[str], artifact: Path) -> str:
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError as exc:
        raise ArtifactError(f"cannot inspect {artifact}: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise ArtifactError(f"inspection failed for {artifact}: {detail}")
    return result.stdout


def validate_pdfs(dist: Path) -> list[Path]:
    validated = []
    for language, expected_title in PDF_TITLES.items():
        matches = sorted(dist.glob(f"*-{language}.pdf"))
        if len(matches) != 1:
            raise ArtifactError(
                f"expected exactly one {language.upper()} PDF in {dist}, found {len(matches)}"
            )
        path = matches[0]
        if path.stat().st_size == 0:
            raise ArtifactError(f"empty PDF: {path}")
        info = _run(["pdfinfo", str(path)], path)
        if not re.search(r"(?m)^Pages:\s*[1-9]\d*\s*$", info):
            raise ArtifactError(f"PDF has no positive page count: {path}")
        first_page = _run(
            ["pdftotext", "-f", "1", "-l", "1", str(path), "-"],
            path,
        )
        if _normalized(expected_title).casefold() not in _normalized(first_page).casefold():
            raise ArtifactError(
                f"{path.name} first page does not contain expected title {expected_title!r}"
            )
        validated.append(path)
    return validated


def validate_docx(dist: Path) -> list[Path]:
    validated = []
    required = {"[Content_Types].xml", "word/document.xml", "docProps/core.xml"}
    for language, expected_title in PDF_TITLES.items():
        matches = sorted(dist.glob(f"*-{language}.docx"))
        if len(matches) != 1:
            raise ArtifactError(
                f"expected exactly one {language.upper()} DOCX in {dist}, found {len(matches)}"
            )
        path = matches[0]
        if not zipfile.is_zipfile(path):
            raise ArtifactError(f"invalid DOCX ZIP: {path}")
        with zipfile.ZipFile(path) as archive:
            missing = required - set(archive.namelist())
            if missing:
                raise ArtifactError(f"DOCX is missing required members {sorted(missing)}: {path}")
            bad = archive.testzip()
            if bad:
                raise ArtifactError(f"corrupt DOCX member: {path}:{bad}")
            try:
                core = ET.fromstring(archive.read("docProps/core.xml"))
            except ET.ParseError as exc:
                raise ArtifactError(f"invalid DOCX core properties XML: {path}: {exc}") from exc
            title = core.findtext(DC_TITLE)
            if title is None or title == "":
                raise ArtifactError(f"DOCX core title is missing: {path}")
            if title != expected_title:
                raise ArtifactError(
                    f"DOCX title mismatch for {path.name}: {title!r} != {expected_title!r}"
                )
        validated.append(path)
    return validated


def validate_html(dist: Path, expected_title: str) -> Path:
    matches = sorted(dist.glob("*.html"))
    if len(matches) != 1:
        raise ArtifactError(f"expected exactly one HTML publication in {dist}, found {len(matches)}")
    path = matches[0]
    text = path.read_text(encoding="utf-8")
    if not re.match(r"\s*<!doctype\s+html\b", text, re.IGNORECASE):
        raise ArtifactError(f"HTML publication has no doctype: {path}")
    parser = _TitleParser()
    parser.feed(text)
    if _normalized(parser.title) != _normalized(expected_title):
        raise ArtifactError(
            f"HTML title mismatch for {path.name}: {parser.title!r} != {expected_title!r}"
        )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--require-docx", action="store_true")
    parser.add_argument("--require-html", action="store_true")
    parser.add_argument("--html-title", default=DEFAULT_HTML_TITLE)
    args = parser.parse_args()
    dist = args.dist.resolve()
    try:
        if not dist.is_dir():
            raise ArtifactError(f"artifact directory does not exist: {dist}")
        pdfs = validate_pdfs(dist)
        print(f"validated PDFs: {len(pdfs)}")
        if args.require_docx:
            docx = validate_docx(dist)
            print(f"validated DOCX: {len(docx)}")
        if args.require_html:
            html = validate_html(dist, args.html_title)
            print(f"validated HTML title: {html.name}")
    except (ArtifactError, OSError, UnicodeError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
