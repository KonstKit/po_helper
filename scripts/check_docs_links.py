#!/usr/bin/env python3
"""Docs cross-reference integrity gate.

Checks that relative links in Markdown docs resolve to files in the
repository. Files carrying the historical-snapshot banner are exempt:
they are preserved as-is and their links may reference removed files.

Handles: inline links [text](target), titled links [text](target "T"),
angle-bracket targets [text](<target>), and reference-style definitions
[label]: target. Links inside fenced code blocks are ignored.

Usage: python3 scripts/check_docs_links.py [--root PATH]
"""

from __future__ import annotations

import argparse
import os
import re
import sys

EXEMPT_MARKER = "> Historical snapshot"
EXEMPT_SCAN_LINES = 12
INLINE_LINK_RE = re.compile(
    r"\[[^\]]*\]\(\s*(?:<([^>]+)>|<?([^)\s>]+)>?)(?:\s+(?:\"[^\"]*\"|\'[^\']*\'|\([^)]*\)))?\s*\)"
)
REFERENCE_DEF_RE = re.compile(r"^\s*\[([^\]]+)\]:\s*(?:<([^>]+)>|([^\s>]+)>?)(?:\s+(?:\"[^\"]*\"|\'[^\']*\'|\([^)]*\)))?\s*$")
REFERENCE_USE_RE = re.compile(r"\[([^\]]*)\]\[([^\]]*)\]")
SHORTCUT_REF_RE = re.compile(r"(?<!\])\[([^\][]+)\](?!\[)")


def collect_md_files(root: str) -> list[str]:
    md: list[str] = []
    skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".zcode"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            if f.endswith(".md"):
                md.append(os.path.relpath(os.path.join(dirpath, f), root))
    return sorted(md)


def fence_delimiter(stripped: str):
    """Return (char, run_len) for a leading fence delimiter run."""
    if not stripped:
        return None
    ch = stripped[0]
    if ch not in ("`", "~"):
        return None
    run_len = len(stripped) - len(stripped.lstrip(ch))
    if run_len < 3:
        return None
    return ch, run_len


def fence_opener(stripped: str):
    """Opener: delimiter run plus optional info string."""
    d = fence_delimiter(stripped)
    if not d:
        return None
    ch, n = d
    info = stripped[n:]
    if ch == "`" and chr(96) in info:
        return None
    return ch, n


def fence_closer(stripped: str, fence) -> bool:
    """Closer: pure same-char run, at least the opener length."""
    if not stripped or set(stripped) != {fence[0]}:
        return False
    return len(stripped) >= fence[1]


def visible_lines(text: str) -> list[str]:
    """Lines with fenced blocks and HTML comments removed.
    Comment state is evaluated before fence markers, so a fence
    inside a comment never opens."""
    out: list[str] = []
    fence = None
    in_comment = False
    for line in text.splitlines():
        if fence:
            if fence_closer(line.strip(), fence):
                fence = None
            continue
        visible, in_comment = strip_html_comments(line, in_comment)
        stripped = visible.strip()
        op = fence_opener(stripped)
        if op:
            fence = op
            continue
        if stripped:
            out.append(stripped)
    return out


def strip_html_comments(line: str, in_comment: bool):
    """Remove comment segments, preserving visible text."""
    out = []
    i = 0
    n = len(line)
    while i < n:
        if in_comment:
            j = line.find("-->", i)
            if j == -1:
                return "".join(out), True
            i = j + 3
            in_comment = False
        else:
            j = line.find("<!--", i)
            if j == -1:
                out.append(line[i:])
                break
            out.append(line[i:j])
            i = j + 4
            in_comment = True
    return "".join(out), in_comment

def referenced_targets(text: str) -> list[str]:
    clean = chr(10).join(visible_lines(text))
    targets: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in INLINE_LINK_RE.finditer(clean):
        targets.append(m.group(1) or m.group(2))
        spans.append((m.start(), m.end()))
    # Mask inline-link spans so their bracket labels are not also
    # scanned as reference uses or shortcut references.
    chars = list(clean)
    for a, b in spans:
        for i in range(a, b):
            if chars[i] != chr(10):
                chars[i] = " "
    masked = "".join(chars)
    defs: dict[str, str] = {}
    for line in clean.splitlines():
        m = REFERENCE_DEF_RE.match(line)
        if m:
            defs[m.group(1).strip().lower()] = m.group(2) or m.group(3)
    for m in REFERENCE_USE_RE.finditer(masked):
        label = (m.group(2) or m.group(1)).strip().lower()
        if label in defs:
            targets.append(defs[label])
    for line in masked.splitlines():
        if REFERENCE_DEF_RE.match(line):
            continue  # definition labels are not shortcut references
        for m in SHORTCUT_REF_RE.finditer(line):
            label = m.group(1).strip().lower()
            if label in defs:
                targets.append(defs[label])
    return targets

def is_exempt(content: str) -> bool:
    """Banner must appear among the first visible content lines."""
    seen = 0
    for line in visible_lines(content):
        seen += 1
        if EXEMPT_SCAN_LINES < seen:
            return False
        if line.startswith(">") and EXEMPT_MARKER in line:
            return True
    return False

def _self_test() -> None:
    nl = chr(10)
    cases = [
        ('[a](guide.md)', ['guide.md']),
        ('[a](guide.md "T")', ['guide.md']),
        ('[a](<path with spaces.md>)', ['path with spaces.md']),
        ('[label]: ../docs/a.md' + nl + '[go][label]', ['../docs/a.md']),
        ('[label]: <b c.md> "T"' + nl + '[go][label]', ['b c.md']),
        ('[collapsed][]' + nl + '[collapsed]: c.md', ['c.md']),
        ('[shortcut] rest' + nl + '[shortcut]: d.md', ['d.md']),
        ('~~~' + nl + '[x](ignored.md)' + nl + '~~~', []),
        ('[a](guide.md ("T"))', ['guide.md']),
        ('[a](good.md)' + nl + '[a]: missing.md', ['good.md']),
    ]
    for doc, expected in cases:
        got = referenced_targets(doc)
        assert got == expected, (doc, got, expected)
    banner = '> [!WARNING]' + nl + '> Historical snapshot: kept as-is'
    assert is_exempt(banner + nl + '[x](gone.md)')
    prose = 'Mentioning the marker ' + "> Historical snapshot" + ' in prose'
    assert not is_exempt(prose + nl + '[x](gone.md)')
    fenced = '~~~' + nl + '> Historical snapshot' + nl + '~~~' + nl + '[x](gone.md)'
    assert not is_exempt(fenced)
    doc = 'text <!-- > Historical snapshot -->' + nl + '[x](gone.md)'
    assert not is_exempt(doc), doc
    doc = '```' + nl + '> Historical snapshot' + nl + '~~~' + nl + '[x](gone.md)'
    assert not is_exempt(doc), doc
    filler = nl.join(['filler line'] * 11)
    doc = filler + nl + '> Historical snapshot'
    assert is_exempt(doc), doc
    filler12 = nl.join(['filler line'] * 12)
    doc = filler12 + nl + '> Historical snapshot'
    assert not is_exempt(doc), doc
    # info-string fence closes with a same-char run of at least that length
    doc = '```python' + nl + '> Historical snapshot' + nl + '```' + nl + '[x](gone.md)'
    assert not is_exempt(doc), doc
    # an inline comment does not consume a content-line slot
    doc = 'visible <!-- > Historical snapshot -->' + nl + ('filler' + nl) * 11 + '> Historical snapshot'
    assert not is_exempt(doc), doc
    # visible text before an inline comment counts toward the banner
    doc = ('filler' + nl) * 10 + '> Historical snapshot <!-- note -->'
    assert is_exempt(doc), doc
    # a shorter nested fence cannot close a longer opener
    doc = '````' + nl + '[x](inside.md)' + nl + '```' + nl + '[y](also-inside.md)' + nl + '````'
    assert referenced_targets(doc) == [], doc
    # a closer with trailing text does not close the fence
    doc = '```' + nl + '> Historical snapshot' + nl + '``` tail' + nl + '[x](gone.md)'
    assert not is_exempt(doc), doc
    assert referenced_targets(doc) == [], doc
    # a commented-out fence opener never opens
    doc = '<!-- ``` -->' + nl + '[x](gone.md)'
    assert referenced_targets(doc) == ['gone.md'], doc
    # commented-out links are not checked
    doc = '<!-- [x](missing.md) -->' + nl + '[ok](real.md)'
    assert referenced_targets(doc) == ['real.md'], doc
    # a fence inside a multiline comment never opens
    doc = '<!--' + nl + '```' + nl + '-->' + nl + '[x](gone.md)'
    assert referenced_targets(doc) == ['gone.md'], doc
    # banner after an invalid closer stays inside the fence: not exempt
    doc = '```' + nl + 'x' + nl + '``` tail' + nl + '> Historical snapshot' + nl + '[x](gone.md)'
    assert not is_exempt(doc), doc
    # exemption scanning goes through the comment pipeline
    doc = '<!--' + nl + '```' + nl + '-->' + nl + '> Historical snapshot' + nl + '[x](gone.md)'
    assert is_exempt(doc), doc
    print('self-test ok')

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root")
    args = parser.parse_args()
    root = os.path.abspath(args.root)

    all_files: set[str] = set()
    skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".zcode"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            all_files.add(os.path.relpath(os.path.join(dirpath, f), root))

    broken: list[tuple[str, str, str]] = []
    checked = exempt = 0
    for name in collect_md_files(root):
        with open(os.path.join(root, name), encoding="utf-8") as fh:
            raw = fh.read()
        if is_exempt(raw):
            exempt += 1
            continue
        checked += 1
        base = os.path.dirname(name)
        for link in referenced_targets(raw):
            if link.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = os.path.normpath(os.path.join(base, link))
            if target not in all_files:
                broken.append((name, link, target))

    print(f"docs link check: {checked} files checked, {exempt} historical snapshots exempt")
    if broken:
        print(f"broken links: {len(broken)}")
        for name, link, target in broken:
            print(f"  - {name} -> {link} (resolved: {target})")
        return 1
    print("all relative links resolve")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _self_test()
        sys.exit(0)
    sys.exit(main())
