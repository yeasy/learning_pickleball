#!/usr/bin/env python3
"""Emit per-chapter HTML fragments + externalized images for the pickleballcn portal
multi-page book (/books/learning-pickleball/).

Reuses parse_summary/fix_inline_dollar from build_html_reader.py (the single-file SPA
builder), but instead of one combined SPA it produces:
  - <portal>/src/data/book-learning-pickleball.json   (ordered array, one item per SUMMARY entry)
  - <portal>/public/books/learning-pickleball/img/*    (externalized images + rendered mermaid SVG)

The portal's build_site.py reads the JSON and wraps each fragment in portal chrome.
Data contract per element: slug, kind(index|chapter|appendix), num, title, titleFull, bodyHtml, description
"""
import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_html_reader import parse_summary, fix_inline_dollar  # noqa: E402

BOOK_ROUTE = "/books/learning-pickleball"
LANG_DIR = "cn"
EXPECTED_CHAPTERS = 28
PLACEHOLDER_TOKENS = ("MERMAIDZZ", "PLACEHOLDER", "@@")
# 2026-07-16: 第三方转播截图/档案照片（无授权署名），门户侧按 fail-closed 权利标准
# 不发布：生成 fragment 时直接去引用，也不复制到门户 img/。源文件保留在 _images/ 不动。
THIRD_PARTY_BLOCKED_IMAGES = frozenset({
    "atp-shot.jpg",       # MLP 转播画面
    "erne-shot.jpg",      # 职业赛转播帧
    "foot-fault.jpg",     # Newport Beach 赛事转播截图
    "dink-low.jpg",       # Newport Beach 赛事转播截图
    "serve.jpg",          # Carvana PPA Tour 现场专业照片
    "pickleball-born.png",  # 1960 年代 Bainbridge Island 历史档案照片
})


class BuildError(RuntimeError):
    """A user-actionable portal build failure."""


def slug_and_kind(md_path):
    """cn/06_dink.md -> ('dink','chapter'); README.md -> ('index','index');
    appendix_tao.md -> ('appendix-tao','appendix')."""
    base = os.path.splitext(os.path.basename(md_path))[0]
    if base.lower() == "readme":
        return "index", "index"
    m = re.match(r"^(\d+)_(.+)$", base)
    if m:
        return m.group(2).replace("_", "-"), "chapter"
    return base.replace("_", "-"), "appendix"


def split_num_title(summary_title):
    """'第 6 章 - 前场吊球技术' -> ('第 6 章','前场吊球技术'); '附录一 参考资料' -> ('附录一','参考资料')."""
    m = re.match(r"^(第\s*\d+\s*章|附录[一二三四五六七八九十]+)\s*[-—－]?\s*(.*)$", summary_title.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip() or summary_title.strip()
    return "", summary_title.strip()


def validate_inputs(items, lang_root):
    """Fail before writing output when SUMMARY cannot form a closed portal graph."""
    problems = []
    if len(items) != EXPECTED_CHAPTERS:
        problems.append(
            f"expected {EXPECTED_CHAPTERS} SUMMARY-ordered chapters, found {len(items)}"
        )

    slugs = [slug_and_kind(path)[0] for _, path, _title, _level in items]
    duplicates = sorted({slug for slug in slugs if slugs.count(slug) > 1})
    if duplicates:
        problems.append(f"duplicate slug(s): {duplicates}")

    summary_paths = {posixpath.normpath(path) for _, path, _title, _level in items}
    for _, chapter_path, _title, _level in items:
        source = os.path.join(lang_root, chapter_path)
        try:
            with open(source, encoding="utf-8") as stream:
                text = stream.read()
        except OSError as exc:
            problems.append(f"cannot read {chapter_path}: {exc}")
            continue
        link_targets = re.findall(
            r"(?<!!)\[[^\]]*\]\(([^)]+?\.md(?:[?#][^)]*)?)\)", text
        )
        link_targets += re.findall(
            r"\bhref=[\"']([^\"']+?\.md(?:[?#][^\"']*)?)[\"']", text, re.I
        )
        for raw_target in link_targets:
            parsed = urlparse(raw_target.strip())
            if parsed.scheme or parsed.netloc:
                continue
            target = unquote(parsed.path)
            resolved = posixpath.normpath(
                posixpath.join(posixpath.dirname(chapter_path), target)
            )
            if resolved not in summary_paths:
                problems.append(
                    f"{chapter_path}: unresolved internal Markdown link: {raw_target}"
                )
    if problems:
        raise BuildError("\n".join(problems))


def process_fragment(text, book_root, slug_by_mdname, images_used, mermaid_srcs):
    """Clean one chapter's markdown for portal output:
    - strip external shield/badge images
    - pull mermaid blocks into MERMAIDZZ<idx>ZZ placeholders (idx local to this chapter)
    - rewrite local images ../_images/x.png -> /books/learning-pickleball/img/x.png (record source)
    - rewrite internal .md links -> /books/learning-pickleball/<slug>/
    """
    # mermaid -> placeholder
    def grab(m):
        idx = len(mermaid_srcs)
        mermaid_srcs.append(m.group(1))
        return f"\n\nMERMAIDZZ{idx}ZZ\n\n"

    text = re.sub(r"```mermaid[ \t]*\n(.*?)\n[ \t]*```", grab, text, flags=re.DOTALL)
    text = fix_inline_dollar(text)
    # drop remote badge images / linked badges
    text = re.sub(r"\[!\[[^\]]*\]\(https?://[^)]*\)\]\([^)]*\)", "", text)
    text = re.sub(r"!\[[^\]]*\]\(https?://[^)]*\)", "", text)
    text = re.sub(r"^\s*\[\]\([^)]*\)\s*$", "", text, flags=re.M)

    BLOCKED = object()  # sentinel: third-party image, drop the whole reference

    def _webimg(url):
        url = url.strip()
        if url.startswith(("http://", "https://", "/", "data:")):
            return None
        # resolve relative to the chapter dir (cn/), record source under book root
        norm = posixpath.normpath(posixpath.join(LANG_DIR, url))  # e.g. _images/x.png
        base = os.path.basename(norm)
        if base in THIRD_PARTY_BLOCKED_IMAGES:
            return BLOCKED
        images_used.add(norm)
        return f"{BOOK_ROUTE}/img/{base}"

    def md_img(m):
        web = _webimg(m.group(2))
        if web is BLOCKED:
            return ""
        return f"![{m.group(1)}]({web})" if web else m.group(0)

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", md_img, text)

    def html_img(m):
        src = m.group(1)
        web = _webimg(src)
        if web is BLOCKED:
            return ""
        return m.group(0).replace(f'src="{src}"', f'src="{web}"') if web else m.group(0)

    text = re.sub(r'<img\s+[^>]*src="([^"]+)"[^>]*>', html_img, text)

    def md_link(m):
        label, target = m.group(1), m.group(2).strip()
        if "#" in target:
            target = target.split("#", 1)[0]
        if not target.endswith(".md"):
            return m.group(0)
        name = os.path.basename(posixpath.normpath(posixpath.join(LANG_DIR, target)))
        slug = slug_by_mdname.get(name)
        if not slug:
            return m.group(0)
        route = f"{BOOK_ROUTE}/" if slug == "index" else f"{BOOK_ROUTE}/{slug}/"
        return f"[{label}]({route})"

    text = re.sub(r"(?<!\!)\[([^\]]*)\]\(([^)]+?\.md(?:#[^)]*)?)\)", md_link, text)
    return text


def render_mermaid_svg(src):
    """Render one mermaid source to inline SVG via mmdc; None on failure."""
    try:
        with tempfile.TemporaryDirectory() as td:
            mmd = os.path.join(td, "d.mmd")
            svg = os.path.join(td, "d.svg")
            with open(mmd, "w", encoding="utf-8") as f:
                f.write(src)
            subprocess.run(
                ["mmdc", "-i", mmd, "-o", svg, "-b", "transparent"],
                check=True, capture_output=True,
            )
            with open(svg, encoding="utf-8") as f:
                out = f.read()
            # strip xml prolog / doctype so it inlines cleanly
            out = re.sub(r"^<\?xml[^>]*\?>\s*", "", out)
            out = re.sub(r"<!DOCTYPE[^>]*>\s*", "", out)
            return out.strip()
    except Exception as e:  # noqa: BLE001
        print(f"  WARNING: mermaid render failed: {e}", file=sys.stderr)
        return None


def fallback_diagram(slug, idx):
    """Reuse a committed pre-rendered diagram under tools/mermaid_fallback/ when
    mmdc/Chromium is unavailable: <slug>-<idx>.html (a styled HTML block, used as-is —
    preferred, robust) or <slug>-<idx>.svg (wrapped in figure.diagram)."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mermaid_fallback")
    html_path = os.path.join(d, f"{slug}-{idx}.html")
    svg_path = os.path.join(d, f"{slug}-{idx}.svg")
    if os.path.isfile(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read().strip()
    if os.path.isfile(svg_path):
        with open(svg_path, encoding="utf-8") as f:
            return f'<figure class="diagram">{f.read().strip()}</figure>'
    return None


def pandoc_fragment(md_text):
    p = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "html5", "--wrap=none"],
        input=md_text, capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"pandoc failed: {p.stderr}")
    return p.stdout


def first_paragraph_text(fragment, limit=110):
    m = re.search(r"<p>(.*?)</p>", fragment, flags=re.DOTALL)
    if not m:
        return ""
    txt = re.sub(r"<[^>]+>", "", m.group(1))
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:limit]


def build():
    ap = argparse.ArgumentParser()
    ap.add_argument("--portal", required=True, help="path to portal-src")
    ap.add_argument("--book", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="book repo root (default: parent of tools/)")
    a = ap.parse_args()

    book_root = os.path.abspath(a.book)
    lang_root = os.path.join(book_root, LANG_DIR)
    portal = os.path.abspath(a.portal)
    data_out = os.path.join(portal, "src", "data", "book-learning-pickleball.json")
    img_out = os.path.join(portal, "public", "books", "learning-pickleball", "img")

    items = [it for it in parse_summary(lang_root) if it[0] == "file"]
    validate_inputs(items, lang_root)
    slug_by_mdname = {os.path.basename(path): slug_and_kind(path)[0] for (_, path, _t, _l) in items}

    os.makedirs(img_out, exist_ok=True)
    images_used = set()
    chapters = []

    for (_, path, summary_title, _lvl) in items:
        slug, kind = slug_and_kind(path)
        num, title = split_num_title(summary_title)
        with open(os.path.join(lang_root, path), encoding="utf-8") as f:
            raw = f.read()
        mermaid_srcs = []
        cleaned = process_fragment(raw, book_root, slug_by_mdname, images_used, mermaid_srcs)
        frag = pandoc_fragment(cleaned)
        # swap mermaid placeholders -> rendered SVG (mmdc), else committed HTML/SVG fallback,
        # else visible source. Function replacement avoids re backslash/group interpretation.
        for idx, src in enumerate(mermaid_srcs):
            svg = render_mermaid_svg(src)
            if svg:
                repl = f'<figure class="diagram">{svg}</figure>'
            else:
                repl = fallback_diagram(slug, idx) or f'<pre class="mermaid-src">{src}</pre>'
            frag = re.sub(rf"<p>\s*MERMAIDZZ{idx}ZZ\s*</p>", lambda m: repl, frag)
            frag = frag.replace(f"MERMAIDZZ{idx}ZZ", repl)
        chapters.append({
            "slug": slug,
            "kind": kind,
            "num": num,
            "title": title,
            "titleFull": summary_title.strip(),
            "bodyHtml": frag.strip(),
            "description": first_paragraph_text(frag),
        })

    # copy referenced images by basename
    copied = 0
    missing = []
    for norm in sorted(images_used):
        src = os.path.join(book_root, norm)
        base = os.path.basename(norm)
        if os.path.isfile(src):
            with open(src, "rb") as r, open(os.path.join(img_out, base), "wb") as w:
                w.write(r.read())
            copied += 1
        else:
            missing.append(norm)

    os.makedirs(os.path.dirname(data_out), exist_ok=True)
    with open(data_out, "w", encoding="utf-8") as f:
        json.dump(chapters, f, ensure_ascii=False, indent=2)

    # ---- self-checks ----
    n_summary = len(items)
    problems = []
    if len(chapters) != n_summary:
        problems.append(f"chapter count {len(chapters)} != SUMMARY {n_summary}")
    if missing:
        problems.append(f"missing image sources: {missing}")
    web_imgs = set()
    for c in chapters:
        web_imgs |= set(re.findall(rf'src="{re.escape(BOOK_ROUTE)}/img/([^"]+)"', c["bodyHtml"]))
        if 'class="page"' in c["bodyHtml"]:
            problems.append(f"{c['slug']}: leftover SPA marker class=\"page\"")
        for token in PLACEHOLDER_TOKENS:
            if token in c["bodyHtml"]:
                problems.append(f"{c['slug']}: leftover placeholder token {token}")
    for name in web_imgs:
        if not os.path.isfile(os.path.join(img_out, name)):
            problems.append(f"referenced img not on disk: {name}")

    print(f"chapters: {len(chapters)} (== SUMMARY {n_summary})")
    print(f"images copied: {copied}")
    print(f"data -> {data_out}")
    print(f"img  -> {img_out}")
    if problems:
        raise BuildError("self-check failed:\n" + "\n".join(f"  - {p}" for p in problems))
    print("self-check OK")
    return 0


def main():
    try:
        return build()
    except (BuildError, FileNotFoundError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
