#!/usr/bin/env python3
"""Contracts for bilingual structure and official-source provenance."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

import check_project_rules


ROOT = Path(__file__).resolve().parents[1]


class BilingualParityTests(unittest.TestCase):
    def test_checker_exposes_bilingual_parity(self) -> None:
        self.assertTrue(
            callable(getattr(check_project_rules, "check_bilingual_parity", None)),
            "check_project_rules.py must expose check_bilingual_parity(root)",
        )

    def test_repository_summaries_and_numbered_sections_are_in_parity(self) -> None:
        checker = getattr(check_project_rules, "check_bilingual_parity", None)
        if checker is None:
            self.fail("check_bilingual_parity is missing")
        self.assertEqual([], checker(ROOT))

    def test_checker_reports_numbered_section_drift(self) -> None:
        checker = getattr(check_project_rules, "check_bilingual_parity", None)
        if checker is None:
            self.fail("check_bilingual_parity is missing")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for language in ("cn", "en"):
                (root / language).mkdir()
                (root / language / "SUMMARY.md").write_text(
                    "# Book\n\n* [Book](README.md)\n* [Chapter](01_one.md)\n",
                    encoding="utf-8",
                )
                (root / language / "README.md").write_text("# Book\n", encoding="utf-8")
            (root / "cn/01_one.md").write_text("# 第 1 章\n\n## 1.1 甲\n", encoding="utf-8")
            (root / "en/01_one.md").write_text("# Chapter 1\n\n## 1.2 B\n", encoding="utf-8")
            issues = checker(root)
        self.assertTrue(any("numbered section IDs differ" in issue for issue in issues), issues)

    def test_checker_reports_summary_label_drift_from_h1(self) -> None:
        checker = getattr(check_project_rules, "check_bilingual_parity", None)
        if checker is None:
            self.fail("check_bilingual_parity is missing")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for language in ("cn", "en"):
                (root / language).mkdir()
                (root / language / "SUMMARY.md").write_text(
                    "# Book\n\n* [Listed title](README.md)\n",
                    encoding="utf-8",
                )
                (root / language / "README.md").write_text(
                    "# Actual title\n",
                    encoding="utf-8",
                )
            issues = checker(root)
        self.assertTrue(any("SUMMARY label differs from H1" in issue for issue in issues), issues)

    def test_official_source_provenance_is_complete_and_linked(self) -> None:
        path = ROOT / "sources/provenance.json"
        self.assertTrue(path.is_file(), "sources/provenance.json must be committed")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(1, data["schema_version"])
        sources = {entry["id"]: entry for entry in data["sources"]}
        required = {
            "usap_2026_rulebook",
            "usap_equipment_standards",
            "usap_approved_paddles",
            "usap_approved_balls",
        }
        self.assertTrue(required <= sources.keys())
        for source_id in required:
            entry = sources[source_id]
            self.assertEqual("USA Pickleball", entry["publisher"])
            self.assertEqual("official", entry["authority"])
            self.assertEqual("https", urlparse(entry["url"]).scheme)
            self.assertIn(urlparse(entry["url"]).hostname, {
                "usapickleball.org",
                "equipment.usapickleball.org",
                "ebooks.usapickleball.org",
            })
            self.assertRegex(entry["verified_at"], r"^\d{4}-\d{2}-\d{2}$")
        for appendix in (ROOT / "cn/appendix.md", ROOT / "en/appendix.md"):
            self.assertIn("../sources/provenance.json", appendix.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
