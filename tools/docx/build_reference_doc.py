#!/usr/bin/env python3
"""Build the Word style reference used by tools/build_docx.py."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor


PAGE_WIDTH_TWIPS = 10488
PAGE_HEIGHT_TWIPS = 14740


def _set_font(style, western: str, east_asia: str, size: float) -> None:
    style.font.name = western
    style.font.size = Pt(size)
    style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), east_asia)


def _add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend((begin, instruction, separate, end))


def create_reference_doc(language: str, output: Path) -> None:
    if language not in {"cn", "en"}:
        raise ValueError(f"unsupported language: {language}")
    source_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_epoch and source_epoch.isdigit() and int(source_epoch) < 315532800:
        os.environ["SOURCE_DATE_EPOCH"] = "315532800"
    title = "学打匹克球" if language == "cn" else "Learning Pickleball"
    body_font = "Songti SC" if language == "cn" else "Georgia"
    heading_font = "PingFang SC" if language == "cn" else "Helvetica Neue"
    east_asia = "Songti SC" if language == "cn" else "Arial"

    document = Document()
    section = document.sections[0]
    section.page_width = Mm(185)
    section.page_height = Mm(260)
    section.top_margin = Mm(22)
    section.bottom_margin = Mm(22)
    section.left_margin = Mm(22)
    section.right_margin = Mm(18)
    section.gutter = Mm(4)
    section.different_first_page_header_footer = True

    normal = document.styles["Normal"]
    _set_font(normal, body_font, east_asia, 10.5 if language == "cn" else 11)
    normal.paragraph_format.line_spacing = 1.35
    normal.paragraph_format.space_after = Pt(5)

    for level, size in ((1, 22), (2, 16), (3, 13), (4, 11)):
        style = document.styles[f"Heading {level}"]
        _set_font(style, heading_font, heading_font, size)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.space_before = Pt(12 if level == 1 else 8)
        style.paragraph_format.space_after = Pt(6)
        if level == 1:
            style.paragraph_format.page_break_before = True

    _set_font(document.styles["Title"], heading_font, heading_font, 28)
    document.styles["Title"].paragraph_format.space_after = Pt(18)

    toc_entry = document.styles.add_style("TOC 1", WD_STYLE_TYPE.PARAGRAPH)
    _set_font(toc_entry, body_font, east_asia, 10.5 if language == "cn" else 11)
    toc_entry.paragraph_format.left_indent = Mm(4)
    toc_entry.paragraph_format.space_after = Pt(2)

    first_paragraph = document.styles.add_style("First Paragraph", WD_STYLE_TYPE.PARAGRAPH)
    first_paragraph.base_style = normal
    compact = document.styles.add_style("Compact", WD_STYLE_TYPE.PARAGRAPH)
    compact.base_style = normal
    compact.paragraph_format.space_after = Pt(1)
    block_text = document.styles.add_style("Block Text", WD_STYLE_TYPE.PARAGRAPH)
    block_text.base_style = normal
    block_text.paragraph_format.left_indent = Mm(6)
    block_text.paragraph_format.right_indent = Mm(6)

    table = document.styles.add_style("Table", WD_STYLE_TYPE.TABLE)
    table.base_style = document.styles["Normal Table"]
    verbatim = document.styles.add_style("Verbatim Char", WD_STYLE_TYPE.CHARACTER)
    _set_font(verbatim, "Menlo", "Arial", 9)
    hyperlink = document.styles.add_style("Hyperlink", WD_STYLE_TYPE.CHARACTER)
    hyperlink.font.color.rgb = RGBColor(0x05, 0x63, 0xC1)
    hyperlink.font.underline = True

    header = section.header.paragraphs[0]
    header.text = title
    header.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_font(header.style, body_font, east_asia, 9)
    _add_page_number(section.footer.paragraphs[0])

    document.core_properties.title = title
    document.core_properties.author = "yeasy"
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=("cn", "en"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    create_reference_doc(args.lang, args.output.resolve())
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
