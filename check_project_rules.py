#!/usr/bin/env python3
"""Lightweight Markdown project checks for book repositories."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {
    ".agent",
    ".git",
    ".github",
    ".idea",
    ".mdpress",
    ".mdpress_temp",
    ".mypy_cache",
    ".obsidian",
    ".playwright-cli",
    ".pytest_cache",
    ".vuepress",
    "__pycache__",
    "_book",
    "dist",
    "mcp_cache",
    "node_modules",
    "output",
}
SKIP_PREFIXES = ("_site",)
HTML_TARGET_RE = re.compile(
    r"\b(?:href|src)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
    re.IGNORECASE,
)
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
SUMMARY_ENTRY_RE = re.compile(
    r"^\s*[-*]\s+\[([^]]+)\]\(([^)#?]+\.md)(?:#[^)]*)?\)"
)
NUMBERED_SECTION_RE = re.compile(r"^##\s+(\d+\.\d+)\b", re.MULTILINE)


def should_skip(path: Path) -> bool:
    return any(
        part in SKIP_DIRS or part.startswith(SKIP_PREFIXES)
        for part in path.relative_to(ROOT).parts
    )


def iter_markdown_files() -> list[Path]:
    return sorted(path for path in ROOT.rglob("*.md") if not should_skip(path))


def strip_fenced_blocks(text: str) -> str:
    output: list[str] = []
    in_fence = False
    fence_marker = ""
    fence_len = 0
    for line in text.splitlines():
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            char = marker[0]
            length = len(marker)
            if not in_fence:
                in_fence = True
                fence_marker = char
                fence_len = length
            elif char == fence_marker and length >= fence_len:
                in_fence = False
            output.append("")
            continue
        output.append("" if in_fence else line)
    return "\n".join(output)


def check_fences(path: Path, text: str) -> list[str]:
    issues: list[str] = []
    open_fence: tuple[str, int, int] | None = None
    for line_no, line in enumerate(text.splitlines(), 1):
        match = FENCE_RE.match(line)
        if not match:
            continue
        marker = match.group(1)
        char = marker[0]
        length = len(marker)
        if open_fence is None:
            open_fence = (char, length, line_no)
            continue
        open_char, open_len, _ = open_fence
        if char == open_char and length >= open_len:
            open_fence = None
    if open_fence is not None:
        _, _, line_no = open_fence
        issues.append(f"{path.relative_to(ROOT)}:{line_no}: unclosed fenced code block")
    return issues


def is_local_target(raw_target: str) -> bool:
    parsed = urlparse(raw_target)
    return not parsed.scheme and not parsed.netloc and not raw_target.startswith("#")


def normalize_target(raw_target: str) -> str:
    target = raw_target.strip()
    target = target.split("?", 1)[0].split("#", 1)[0]
    return unquote(target)


def parse_markdown_target(body: str, start: int) -> tuple[str, int]:
    i = start
    while i < len(body) and body[i].isspace():
        i += 1
    if i >= len(body):
        return "", i
    if body[i] == "<":
        end = body.find(">", i + 1)
        if end == -1:
            return "", i + 1
        return body[i + 1 : end].strip(), end + 1

    target: list[str] = []
    depth = 0
    while i < len(body):
        char = body[i]
        if depth == 0 and (char.isspace() or char == ")"):
            break
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        target.append(char)
        i += 1
    return "".join(target).strip(), i


def iter_markdown_link_targets(body: str):
    pos = 0
    while True:
        start = body.find("](", pos)
        if start == -1:
            break
        target, end = parse_markdown_target(body, start + 2)
        if target:
            yield start, target
        pos = max(end + 1, start + 2)


def check_target(path: Path, raw_target: str, line_no: int) -> list[str]:
    target = normalize_target(raw_target)
    if not target or not is_local_target(raw_target):
        return []
    target_path = (path.parent / target).resolve()
    try:
        target_path.relative_to(ROOT)
    except ValueError:
        return []
    if target_path.exists():
        return []
    return [
        f"{path.relative_to(ROOT)}:{line_no}: missing local link target: {raw_target}"
    ]


def check_links(path: Path, text: str) -> list[str]:
    issues: list[str] = []
    body = strip_fenced_blocks(text)
    for start, raw_target in iter_markdown_link_targets(body):
        line_no = body[:start].count("\n") + 1
        issues.extend(check_target(path, raw_target, line_no))
    for match in HTML_TARGET_RE.finditer(body):
        raw_target = next(group for group in match.groups() if group is not None).strip()
        line_no = body[: match.start()].count("\n") + 1
        issues.extend(check_target(path, raw_target, line_no))
    return issues


def check_summary_links() -> list[str]:
    summary = ROOT / "SUMMARY.md"
    if not summary.exists():
        return []
    return check_links(summary, summary.read_text(encoding="utf-8", errors="ignore"))


def _summary_entries(root: Path, language: str) -> list[tuple[str, str]]:
    summary = root / language / "SUMMARY.md"
    if not summary.is_file():
        return []
    entries: list[tuple[str, str]] = []
    for line in summary.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = SUMMARY_ENTRY_RE.match(line)
        if match:
            entries.append((match.group(1).strip(), match.group(2)))
    return entries


def _summary_paths(root: Path, language: str) -> list[str]:
    return [path for _, path in _summary_entries(root, language)]


def check_bilingual_parity(root: Path = ROOT) -> list[str]:
    """Check the ordered CN/EN book structure without comparing translations."""
    issues: list[str] = []
    cn_paths = _summary_paths(root, "cn")
    en_paths = _summary_paths(root, "en")
    summary_labels = {
        language: dict((path, label) for label, path in _summary_entries(root, language))
        for language in ("cn", "en")
    }
    if len(cn_paths) != 28:
        issues.append(f"cn/SUMMARY.md: expected 28 ordered entries, found {len(cn_paths)}")
    if len(en_paths) != 28:
        issues.append(f"en/SUMMARY.md: expected 28 ordered entries, found {len(en_paths)}")
    if cn_paths != en_paths:
        issues.append("cn/en SUMMARY paths differ in names or order")

    cn_files = {path.name for path in (root / "cn").glob("*.md") if path.name != "SUMMARY.md"}
    en_files = {path.name for path in (root / "en").glob("*.md") if path.name != "SUMMARY.md"}
    if cn_files != en_files:
        issues.append(
            "cn/en Markdown file sets differ: "
            f"cn-only={sorted(cn_files - en_files)}, en-only={sorted(en_files - cn_files)}"
        )

    for rel_path in dict.fromkeys(cn_paths + en_paths):
        cn_path = root / "cn" / rel_path
        en_path = root / "en" / rel_path
        if not cn_path.is_file() or not en_path.is_file():
            issues.append(f"{rel_path}: chapter missing from one language")
            continue
        cn_text = cn_path.read_text(encoding="utf-8", errors="ignore")
        en_text = en_path.read_text(encoding="utf-8", errors="ignore")
        cn_h1 = re.findall(r"^#\s+(.+?)\s*$", cn_text, re.MULTILINE)
        en_h1 = re.findall(r"^#\s+(.+?)\s*$", en_text, re.MULTILINE)
        if len(cn_h1) != 1:
            issues.append(f"cn/{rel_path}: expected exactly one H1")
        elif summary_labels["cn"].get(rel_path) != cn_h1[0]:
            issues.append(
                f"cn/{rel_path}: SUMMARY label differs from H1: "
                f"{summary_labels['cn'].get(rel_path)!r} != {cn_h1[0]!r}"
            )
        if len(en_h1) != 1:
            issues.append(f"en/{rel_path}: expected exactly one H1")
        elif summary_labels["en"].get(rel_path) != en_h1[0]:
            issues.append(
                f"en/{rel_path}: SUMMARY label differs from H1: "
                f"{summary_labels['en'].get(rel_path)!r} != {en_h1[0]!r}"
            )
        cn_ids = NUMBERED_SECTION_RE.findall(cn_text)
        en_ids = NUMBERED_SECTION_RE.findall(en_text)
        if cn_ids != en_ids:
            issues.append(
                f"{rel_path}: numbered section IDs differ: cn={cn_ids}, en={en_ids}"
            )
    return issues


def main() -> int:
    issues: list[str] = []
    files = iter_markdown_files()
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        issues.extend(check_fences(path, text))
        issues.extend(check_links(path, text))
    issues.extend(check_summary_links())
    issues.extend(check_bilingual_parity(ROOT))

    unique_issues = sorted(set(issues))
    if unique_issues:
        print("\n".join(unique_issues))
        print(f"\n{len(unique_issues)} issue(s) found across {len(files)} Markdown files.")
        return 1
    print(f"All {len(files)} Markdown files passed project checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
