#!/usr/bin/env python3
"""Structural security and artifact contracts for GitHub Actions workflows."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github/workflows"
WORKFLOWS = sorted((*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")))
DOWNLOAD_ARTIFACT_SHA = "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"


def _job_block(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n.*?(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        text,
    )
    if not match:
        raise AssertionError(f"missing job: {name}")
    return match.group(0)


def _step_script(text: str, name: str) -> str:
    lines = text.splitlines()
    marker = f"      - name: {name}"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise AssertionError(f"missing step: {name}") from exc
    run_line = next(
        (index for index in range(start + 1, len(lines)) if lines[index] == "        run: |"),
        None,
    )
    if run_line is None:
        raise AssertionError(f"step has no run block: {name}")
    body = []
    for line in lines[run_line + 1 :]:
        if line.startswith("      - "):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)) + "\n"


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
            self.assertIn("tools/validate_publication_artifacts.py", text, name)
            self.assertIn("SHA256SUMS", text, name)
            self.assertIn("sha256sum -c", text, name)
        auto = (WORKFLOW_DIR / "auto-release.yml").read_text(encoding="utf-8")
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

    def test_release_workflows_use_deny_by_default_and_isolated_write_jobs(self) -> None:
        contracts = {
            "auto-release.yml": (
                "build",
                "release",
                "learning-pickleball-release-bundle",
                "sha256sum -- *.pdf *.docx *.html > SHA256SUMS",
            ),
            "preview-pdf.yml": (
                "build",
                "publish",
                "learning-pickleball-preview-bundle",
                "sha256sum -- *.pdf > SHA256SUMS",
            ),
        }
        for name, (build_name, write_name, artifact_name, checksum_command) in contracts.items():
            text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
            header = text.split("jobs:", 1)[0]
            self.assertRegex(header, r"(?m)^permissions:\s*\{\}\s*$", name)
            build = _job_block(text, build_name)
            write = _job_block(text, write_name)
            self.assertRegex(build, r"(?m)^    permissions:\n      contents: read$", name)
            self.assertRegex(write, r"(?m)^    needs: build$", name)
            self.assertRegex(write, r"(?m)^    permissions:\n      contents: write$", name)
            self.assertIn("actions/checkout@", build)
            self.assertIn("actions/upload-artifact@", build)
            self.assertIn(f"name: {artifact_name}", build)
            self.assertIn(checksum_command, build)
            self.assertIn(
                f"actions/download-artifact@{DOWNLOAD_ARTIFACT_SHA} # v8.0.1",
                write,
            )
            self.assertIn(f"name: {artifact_name}", write)
            self.assertNotIn("actions/checkout@", write)
            for forbidden in (
                "tools/",
                "mdpress",
                "pandoc",
                "npm ",
                "pip install",
                "python3",
            ):
                self.assertNotIn(forbidden, write, f"{name}: {forbidden}")
            publish_markers = [
                position
                for marker in ("uses: softprops/action-gh-release@", "gh release")
                if (position := write.find(marker)) >= 0
            ]
            self.assertTrue(publish_markers, name)
            self.assertLess(write.index("sha256sum -c"), min(publish_markers), name)

    def test_publication_smoke_checks_validate_pdf_text_and_html_title(self) -> None:
        auto = (WORKFLOW_DIR / "auto-release.yml").read_text(encoding="utf-8")
        preview = (WORKFLOW_DIR / "preview-pdf.yml").read_text(encoding="utf-8")
        ci = (WORKFLOW_DIR / "ci.yaml").read_text(encoding="utf-8")
        for name, text in (
            ("auto-release.yml", auto),
            ("preview-pdf.yml", preview),
            ("ci.yaml", ci),
        ):
            self.assertIn("python3 tools/validate_publication_artifacts.py", text, name)
        self.assertIn("--require-docx", auto)
        self.assertIn("--require-html", auto)
        self.assertIn('--html-title "$TITLE"', auto)
        self.assertIn("--require-docx", ci)

    def test_preview_release_creation_only_handles_explicit_404(self) -> None:
        text = (WORKFLOW_DIR / "preview-pdf.yml").read_text(encoding="utf-8")
        script = _step_script(text, "Ensure preview release exists")
        self.assertIn("gh api --include", script)
        self.assertIn('[[ "$status" == "404" ]]', script)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            record = root / "created"
            gh = fake_bin / "gh"
            gh.write_text(
                """#!/usr/bin/env bash
set -eu
if [[ "$1" == "api" ]]; then
  case "$FAKE_GH_MODE" in
    404) printf 'HTTP/2.0 404 Not Found\\ncontent-type: application/json\\n\\n{}\\n'; exit 1 ;;
    200) printf 'HTTP/2.0 200 OK\\ncontent-type: application/json\\n\\n{}\\n'; exit 0 ;;
    failure) printf 'network timeout while contacting api.github.com\\n' >&2; exit 2 ;;
  esac
fi
if [[ "$1" == "release" && "$2" == "create" ]]; then
  : > "$FAKE_GH_RECORD"
  exit 0
fi
printf 'unexpected fake gh invocation: %s\\n' "$*" >&2
exit 64
""",
                encoding="utf-8",
            )
            gh.chmod(0o755)
            base_env = os.environ.copy()
            base_env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{base_env['PATH']}",
                    "FAKE_GH_RECORD": str(record),
                    "GITHUB_REPOSITORY": "yeasy/learning_pickleball",
                    "GITHUB_SHA": "0123456789abcdef",
                }
            )

            for mode, expected_code, should_create in (
                ("404", 0, True),
                ("200", 0, False),
                ("failure", 2, False),
            ):
                record.unlink(missing_ok=True)
                env = base_env | {"FAKE_GH_MODE": mode}
                result = subprocess.run(
                    ["bash", "-euo", "pipefail", "-c", script],
                    cwd=root,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(expected_code, result.returncode, result.stderr)
                self.assertEqual(should_create, record.exists(), mode)
                if mode == "failure":
                    self.assertIn("network timeout", result.stderr)

    def test_permissions_are_scoped_and_errors_are_not_suppressed(self) -> None:
        for workflow in WORKFLOWS:
            text = workflow.read_text(encoding="utf-8")
            for forbidden in ("actions: write", "packages: write", "id-token: write"):
                self.assertNotIn(forbidden, text, workflow)
            self.assertNotIn("continue-on-error", text, workflow)


if __name__ == "__main__":
    unittest.main()
