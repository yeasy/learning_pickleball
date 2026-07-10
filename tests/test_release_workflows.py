#!/usr/bin/env python3
"""Structural security and artifact contracts for GitHub Actions workflows."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github/workflows"
WORKFLOWS = sorted((*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")))


class ReleaseWorkflowTests(unittest.TestCase):
    def test_all_actions_are_full_sha_pinned_with_version_comments(self) -> None:
        uses_re = re.compile(r"^\s*-?\s*uses:\s*([^\s@]+)@([^\s#]+)(?:\s+#\s*(\S+))?", re.M)
        for workflow in WORKFLOWS:
            text = workflow.read_text(encoding="utf-8")
            matches = uses_re.findall(text)
            self.assertTrue(matches, workflow)
            for action, ref, comment in matches:
                with self.subTest(workflow=workflow.name, action=action):
                    self.assertRegex(ref, r"^[0-9a-f]{40}$")
                    self.assertRegex(comment, r"^v\d")

    def test_checkout_never_persists_credentials(self) -> None:
        for workflow in WORKFLOWS:
            text = workflow.read_text(encoding="utf-8")
            for match in re.finditer(r"(?m)^\s*-\s+uses:\s+actions/checkout@[^\n]+", text):
                block_end = re.search(r"(?m)^\s{6}-\s+(?:name|uses):", text[match.end():])
                end = match.end() + (block_end.start() if block_end else len(text[match.end():]))
                block = text[match.start():end]
                self.assertRegex(block, r"persist-credentials:\s*false", workflow)

    def test_downloads_and_mermaid_dependencies_are_locked(self) -> None:
        for name in ("auto-release.yml", "ci.yaml", "preview-pdf.yml"):
            text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
            self.assertIn("MDPRESS_SHA256", text)
            self.assertIn("sha256sum -c -", text)
            self.assertIn('tar xzf "$archive" -C /tmp mdpress', text)
        for name in ("auto-release.yml", "ci.yaml"):
            text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
            self.assertIn("PANDOC_SHA256", text)
            self.assertIn('echo "${PANDOC_SHA256}  /tmp/pandoc.deb" | sha256sum -c -', text)

        package = json.loads((ROOT / "tools/mermaid/package.json").read_text(encoding="utf-8"))
        self.assertEqual("10.9.1", package["dependencies"]["@mermaid-js/mermaid-cli"])
        lock = json.loads((ROOT / "tools/mermaid/package-lock.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(lock["lockfileVersion"], 3)
        self.assertEqual("10.9.1", lock["packages"][""]["dependencies"]["@mermaid-js/mermaid-cli"])
        release = (WORKFLOW_DIR / "auto-release.yml").read_text(encoding="utf-8")
        self.assertIn("npm ci --prefix tools/mermaid", release)
        self.assertNotIn("npm install -g", release)

    def test_dependabot_has_no_invalid_root_npm_target(self) -> None:
        text = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        npm_blocks = re.findall(
            r'- package-ecosystem:\s*["\']npm["\'](.*?)(?=\n\s*- package-ecosystem:|\Z)',
            text,
            re.S,
        )
        for block in npm_blocks:
            self.assertNotRegex(block, r'directory:\s*["\']/["\']')
            self.assertRegex(block, r'directory:\s*["\']/tools/mermaid["\']')

    def test_artifacts_have_smoke_checks_checksums_and_hard_fail_uploads(self) -> None:
        for name in ("auto-release.yml", "ci.yaml", "preview-pdf.yml"):
            text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
            self.assertIn("pdfinfo", text, name)
            self.assertIn("SHA256SUMS", text, name)
            self.assertIn("sha256sum -c", text, name)
        auto = (WORKFLOW_DIR / "auto-release.yml").read_text(encoding="utf-8")
        self.assertIn("zipfile.ZipFile", auto)
        self.assertIn('grep -qi "<!doctype html"', auto)
        self.assertIn("python3 tools/build_docx.py", auto)
        ci = (WORKFLOW_DIR / "ci.yaml").read_text(encoding="utf-8")
        self.assertIn("python3 -m unittest discover", ci)
        self.assertIn("python3 tools/build_docx.py", ci)

        upload_re = re.compile(
            r"(?ms)^\s*-\s+name:.*?\n\s+uses:\s+actions/upload-artifact@[0-9a-f]{40}.*?(?=^\s{6}-\s+(?:name|uses):|\Z)"
        )
        for workflow in WORKFLOWS:
            for block in upload_re.findall(workflow.read_text(encoding="utf-8")):
                self.assertIn("if-no-files-found: error", block, workflow)

    def test_permissions_are_scoped_and_errors_are_not_suppressed(self) -> None:
        for workflow in WORKFLOWS:
            text = workflow.read_text(encoding="utf-8")
            for forbidden in ("actions: write", "packages: write", "id-token: write"):
                self.assertNotIn(forbidden, text, workflow)
            self.assertNotIn("continue-on-error", text, workflow)


if __name__ == "__main__":
    unittest.main()
