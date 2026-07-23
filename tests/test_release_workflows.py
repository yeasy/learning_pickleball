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
TEST_REPOSITORY = "owner/repo"
TEST_SHA = "a" * 40
GET_REF_COMMAND = [
    "api",
    "--include",
    "--method",
    "GET",
    f"repos/{TEST_REPOSITORY}/git/ref/tags/preview-pdf",
]
PATCH_REF_COMMAND = [
    "api",
    "--silent",
    "--method",
    "PATCH",
    f"repos/{TEST_REPOSITORY}/git/refs/tags/preview-pdf",
    "--raw-field",
    f"sha={TEST_SHA}",
    "--field",
    "force=true",
]
POST_REF_COMMAND = [
    "api",
    "--silent",
    "--method",
    "POST",
    f"repos/{TEST_REPOSITORY}/git/refs",
    "--raw-field",
    "ref=refs/tags/preview-pdf",
    "--raw-field",
    f"sha={TEST_SHA}",
]
VIEW_RELEASE_COMMAND = ["release", "view", "preview-pdf"]
EDIT_RELEASE_COMMAND = [
    "release",
    "edit",
    "preview-pdf",
    "--title",
    "Latest Preview PDFs",
    "--notes-file",
    "dist/release-notes.md",
    "--prerelease",
]
CREATE_RELEASE_COMMAND = [
    "release",
    "create",
    "preview-pdf",
    "--title",
    "Latest Preview PDFs",
    "--notes-file",
    "dist/release-notes.md",
    "--prerelease",
    "--latest=false",
    "--verify-tag",
]

FAKE_GH = r'''#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(args) + "\n")

scenario = os.environ["GH_SCENARIO"]
repository = "owner/repo"
sha = "a" * 40
reasons = {
    "401": "Unauthorized",
    "403": "Forbidden",
    "404": "Not Found",
    "429": "Too Many Requests",
    "503": "Service Unavailable",
}

def fail_http(code):
    print(f"HTTP/2.0 {code} {reasons[code]}")
    print(f"fake gh HTTP {code}", file=sys.stderr)
    raise SystemExit(1)

get_ref = ["api", "--include", "--method", "GET", f"repos/{repository}/git/ref/tags/preview-pdf"]
patch_ref = [
    "api", "--silent", "--method", "PATCH",
    f"repos/{repository}/git/refs/tags/preview-pdf",
    "--raw-field", f"sha={sha}", "--field", "force=true",
]
post_ref = [
    "api", "--silent", "--method", "POST", f"repos/{repository}/git/refs",
    "--raw-field", "ref=refs/tags/preview-pdf", "--raw-field", f"sha={sha}",
]
view_release = ["release", "view", "preview-pdf"]
edit_release = [
    "release", "edit", "preview-pdf", "--title", "Latest Preview PDFs",
    "--notes-file", "dist/release-notes.md", "--prerelease",
]
create_release = [
    "release", "create", "preview-pdf", "--title", "Latest Preview PDFs",
    "--notes-file", "dist/release-notes.md", "--prerelease",
    "--latest=false", "--verify-tag",
]

if os.environ.get("GH_REPO") != repository:
    print("fake gh requires explicit GH_REPO", file=sys.stderr)
    raise SystemExit(2)

if args == get_ref:
    if scenario.startswith("ref_network"):
        print("fake gh network failure", file=sys.stderr)
        raise SystemExit(1)
    for code in reasons:
        if scenario.startswith(f"ref_{code}"):
            fail_http(code)
    print("HTTP/2.0 200 OK")
    print('Content-Type: application/json\n\n{"ref":"refs/tags/preview-pdf"}')
    raise SystemExit(0)

if args in (patch_ref, post_ref, edit_release, create_release):
    raise SystemExit(0)

if args == view_release:
    if "release_missing" in scenario:
        print("release not found", file=sys.stderr)
        raise SystemExit(1)
    if "release_network" in scenario:
        print("fake release network failure", file=sys.stderr)
        raise SystemExit(1)
    for code in reasons:
        if f"release_{code}" in scenario:
            print(f"fake release HTTP {code}", file=sys.stderr)
            raise SystemExit(1)
    raise SystemExit(0)

print(f"unexpected gh argv: {args!r}", file=sys.stderr)
raise SystemExit(2)
'''


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


def _step_scripts_in_order(text: str, names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        _step_script(text, name)
        for name in sorted(names, key=lambda value: text.index(f"      - name: {value}\n"))
    )


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
        self.assertEqual("11.16.0", package["dependencies"]["@mermaid-js/mermaid-cli"])
        lock = json.loads((ROOT / "tools/mermaid/package-lock.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(lock["lockfileVersion"], 3)
        self.assertEqual("11.16.0", lock["packages"][""]["dependencies"]["@mermaid-js/mermaid-cli"])
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

    def _run_preview_scripts(
        self,
        scenario: str,
        *,
        repository: str = TEST_REPOSITORY,
        sha: str = TEST_SHA,
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        text = (WORKFLOW_DIR / "preview-pdf.yml").read_text(encoding="utf-8")
        scripts = _step_scripts_in_order(
            text,
            ("Synchronize mutable preview tag", "Create or update preview release"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gh = root / "gh"
            gh.write_text(FAKE_GH, encoding="utf-8")
            gh.chmod(0o755)
            log = root / "commands.jsonl"
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{root}{os.pathsep}{env.get('PATH', '')}",
                    "GH_LOG": str(log),
                    "GH_SCENARIO": scenario,
                    "GH_TOKEN": "test-token",
                    "GH_REPO": repository,
                    "GITHUB_REPOSITORY": repository,
                    "GITHUB_SHA": sha,
                }
            )
            result: subprocess.CompletedProcess[str] | None = None
            for script in scripts:
                result = subprocess.run(
                    ["/bin/bash", "-c", script],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    break
            assert result is not None
            commands = (
                [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
                if log.exists()
                else []
            )
            return result, commands

    def test_preview_updates_existing_tag_then_release_with_exact_argv(self) -> None:
        result, commands = self._run_preview_scripts("ref_200_release_exists")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            [GET_REF_COMMAND, PATCH_REF_COMMAND, VIEW_RELEASE_COMMAND, EDIT_RELEASE_COMMAND],
            commands,
        )

    def test_preview_creates_tag_and_release_only_on_explicit_not_found(self) -> None:
        result, commands = self._run_preview_scripts("ref_404_release_missing")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            [GET_REF_COMMAND, POST_REF_COMMAND, VIEW_RELEASE_COMMAND, CREATE_RELEASE_COMMAND],
            commands,
        )
        self.assertNotIn("--target", [argument for command in commands for argument in command])

    def test_preview_rejects_invalid_repository_and_sha_before_gh(self) -> None:
        cases = (
            ("owner/repo/extra", TEST_SHA, "Invalid GITHUB_REPOSITORY"),
            (TEST_REPOSITORY, "a" * 39, "Invalid GITHUB_SHA"),
        )
        for repository, sha, message in cases:
            with self.subTest(repository=repository, sha=sha):
                result, commands = self._run_preview_scripts(
                    "ref_200_release_exists", repository=repository, sha=sha
                )
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], commands)
                self.assertIn(message, result.stderr)

    def test_preview_tag_lookup_fails_closed_on_non_404_errors(self) -> None:
        for scenario in ("ref_401", "ref_403", "ref_429", "ref_503", "ref_network"):
            with self.subTest(scenario=scenario):
                result, commands = self._run_preview_scripts(scenario)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([GET_REF_COMMAND], commands)
                expected = "network failure" if scenario.endswith("network") else scenario[4:]
                self.assertIn(expected, result.stderr)

    def test_preview_release_lookup_fails_closed_except_exact_not_found(self) -> None:
        scenarios = (
            "ref_200_release_401",
            "ref_200_release_403",
            "ref_200_release_404",
            "ref_200_release_429",
            "ref_200_release_503",
            "ref_200_release_network",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                result, commands = self._run_preview_scripts(scenario)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(
                    [GET_REF_COMMAND, PATCH_REF_COMMAND, VIEW_RELEASE_COMMAND], commands
                )
                expected = (
                    "network failure"
                    if scenario.endswith("network")
                    else scenario.rsplit("release_", 1)[1]
                )
                self.assertIn(expected, result.stderr)

    def test_preview_publish_has_explicit_repo_context_only_in_write_job(self) -> None:
        text = (WORKFLOW_DIR / "preview-pdf.yml").read_text(encoding="utf-8")
        build, publish = text.split("\n  publish:\n", 1)
        self.assertNotIn("GH_REPO", build)
        self.assertIn("GH_REPO: ${{ github.repository }}", publish)
        self.assertNotIn("--target", publish)

    def test_permissions_are_scoped_and_errors_are_not_suppressed(self) -> None:
        for workflow in WORKFLOWS:
            text = workflow.read_text(encoding="utf-8")
            for forbidden in ("actions: write", "packages: write", "id-token: write"):
                self.assertNotIn(forbidden, text, workflow)
            self.assertNotIn("continue-on-error", text, workflow)


if __name__ == "__main__":
    unittest.main()
