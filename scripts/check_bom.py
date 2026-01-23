#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import sys

BOM = b"\xef\xbb\xbf"

DEFAULT_EXCLUDES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "dist",
    "build",
    "target",
    ".build",
    "Pods",
    "Carthage",
    "DerivedData",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    "vendor",
    "bin",
    "obj",
    ".gradle",
    ".idea",
    ".vscode",
    "coverage",
    ".nyc_output",
    ".cache",
    ".pytest_cache",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".terraform",
    ".serverless",
    ".dart_tool",
    ".pub-cache",
    "analysis_output",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail if UTF-8 BOM is found.")
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (defaults to script parent dir).",
    )
    return parser.parse_args()


def find_bom_files(root: Path) -> list[Path]:
    bom_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDES]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                with path.open("rb") as handle:
                    if handle.read(3) == BOM:
                        bom_files.append(path)
            except OSError:
                continue
    return sorted(bom_files)


def main() -> int:
    args = parse_args()
    repo_root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    if not repo_root.exists():
        print(f"Root not found: {repo_root}", file=sys.stderr)
        return 2

    bom_files = find_bom_files(repo_root)
    if not bom_files:
        print("BOM check: OK")
        return 0

    print("BOM check: FAIL")
    for path in bom_files:
        print(path.relative_to(repo_root).as_posix())
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
