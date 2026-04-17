#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


DEFAULT_COMPOSE_FILE = "docker-compose.dev.yml"
DEFAULT_SERVICE = "frontend-tooling"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run frontend verification inside the repo's Node tooling container."
    )
    parser.add_argument(
        "--compose-file",
        default=DEFAULT_COMPOSE_FILE,
        help="Docker Compose file to use (default: docker-compose.dev.yml).",
    )
    parser.add_argument(
        "--mode",
        choices=("typecheck", "lint", "all"),
        default="all",
        help="Which frontend verification command to run.",
    )
    return parser.parse_args()


def _compose_command(compose_file: Path, mode: str) -> list[str]:
    eslint_cmd = 'npx eslint "src/**/*.{ts,tsx,js,jsx}" --no-error-on-unmatched-pattern'
    if mode == "typecheck":
        payload = "npm ci && npm run typecheck"
    elif mode == "lint":
        payload = f"npm ci && {eslint_cmd}"
    else:
        payload = f"npm ci && npm run typecheck && {eslint_cmd}"

    return [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "run",
        "--rm",
        DEFAULT_SERVICE,
        "sh",
        "-lc",
        payload,
    ]


def main() -> int:
    args = _parse_args()
    compose_file = Path(args.compose_file).expanduser().resolve()
    if not compose_file.exists():
        print(f"Compose file not found: {compose_file}", file=sys.stderr)
        return 2

    command = _compose_command(compose_file, args.mode)
    print("Running:", " ".join(command))

    try:
        completed = subprocess.run(command, check=False)
    except FileNotFoundError:
        print("docker executable not found in PATH.", file=sys.stderr)
        return 2

    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
