#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path


DEFAULT_COMPOSE_FILE = "docker-compose.dev.yml"
DEFAULT_SERVICE = "frontend-tooling"
DEFAULT_NODE_VERSION = "v20.19.0"
NODE_DIST_BASE_URL = "https://nodejs.org/dist"
ESLINT_CMD = ["npx", "eslint", "src/**/*.{ts,tsx,js,jsx}", "--no-error-on-unmatched-pattern"]
SHASUMS_FILENAME = "SHASUMS256.txt"


def _repo_root() -> Path:
    return Path(__file__).expanduser().resolve().parent.parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run frontend verification using Docker tooling or local Node.js."
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
    parser.add_argument(
        "--engine",
        choices=("auto", "docker", "local"),
        default="auto",
        help=(
            "Execution engine. auto = prefer Docker, fallback to local Node.js tooling "
            "(default: auto)."
        ),
    )
    parser.add_argument(
        "--node-version",
        default=DEFAULT_NODE_VERSION,
        help="Portable Node.js version to bootstrap for local engine (default: v20.19.0).",
    )
    parser.add_argument(
        "--node-cache-dir",
        default=None,
        help=(
            "Directory where portable Node.js is stored for local runs "
            "(default: %%LOCALAPPDATA%%\\po-helper-node or ~/.cache/po-helper-node)."
        ),
    )
    parser.add_argument(
        "--frontend-dir",
        default="frontend",
        help="Frontend directory relative to repo root (default: frontend).",
    )
    parser.add_argument(
        "--bootstrap-local-node",
        dest="bootstrap_local_node",
        action="store_true",
        default=True,
        help="Auto-download portable Node.js when local engine is selected and node is missing.",
    )
    parser.add_argument(
        "--no-bootstrap-local-node",
        dest="bootstrap_local_node",
        action="store_false",
        help="Disable automatic portable Node.js bootstrap.",
    )
    return parser.parse_args()


def _compose_command(compose_file: Path, mode: str) -> list[str]:
    if mode == "typecheck":
        payload = "npm ci && npm run typecheck -- --pretty false"
    elif mode == "lint":
        payload = 'npm ci && npx eslint "src/**/*.{ts,tsx,js,jsx}" --no-error-on-unmatched-pattern'
    else:
        payload = (
            'npm ci && npm run typecheck -- --pretty false && '
            'npx eslint "src/**/*.{ts,tsx,js,jsx}" --no-error-on-unmatched-pattern'
        )

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


def _local_commands(mode: str) -> list[list[str]]:
    commands: list[list[str]] = [["npm", "ci"]]
    if mode in ("typecheck", "all"):
        commands.append(["npm", "run", "typecheck", "--", "--pretty", "false"])
    if mode in ("lint", "all"):
        commands.append(ESLINT_CMD)
    return commands


def _default_node_cache_dir() -> Path:
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "po-helper-node"
    return Path.home() / ".cache" / "po-helper-node"


def _node_archive_info(node_version: str) -> tuple[str, str]:
    machine = platform.machine().lower()
    is_arm64 = machine in {"arm64", "aarch64"}

    if sys.platform == "win32":
        arch = "arm64" if is_arm64 else "x64"
        folder = f"node-{node_version}-win-{arch}"
        return folder, f"{folder}.zip"

    if sys.platform.startswith("linux"):
        arch = "arm64" if is_arm64 else "x64"
        folder = f"node-{node_version}-linux-{arch}"
        return folder, f"{folder}.tar.xz"

    if sys.platform == "darwin":
        arch = "arm64" if is_arm64 else "x64"
        folder = f"node-{node_version}-darwin-{arch}"
        return folder, f"{folder}.tar.gz"

    raise RuntimeError(
        f"Unsupported platform for local Node.js bootstrap: {sys.platform} ({platform.machine()})"
    )


def _node_binary_paths(install_dir: Path) -> tuple[Path, Path, Path, Path]:
    if sys.platform == "win32":
        return (
            install_dir / "node.exe",
            install_dir / "npm.cmd",
            install_dir / "npx.cmd",
            install_dir,
        )
    bin_dir = install_dir / "bin"
    return (
        bin_dir / "node",
        bin_dir / "npm",
        bin_dir / "npx",
        bin_dir,
    )


def _download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)


def _compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_expected_archive_sha256(
    node_version: str, archive_name: str, cache_dir: Path
) -> str:
    shasums_path = cache_dir / f"{node_version}-{SHASUMS_FILENAME}"
    if not shasums_path.exists():
        shasums_url = f"{NODE_DIST_BASE_URL}/{node_version}/{SHASUMS_FILENAME}"
        print(f"Downloading checksum manifest from {shasums_url}")
        _download(shasums_url, shasums_path)

    for line in shasums_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        checksum, filename = parts
        normalized = filename.lstrip("*")
        if normalized == archive_name:
            return checksum.lower()

    raise RuntimeError(
        f"Checksum for {archive_name} was not found in {shasums_path.name}"
    )


def _ensure_verified_archive(
    node_version: str, archive_name: str, archive_path: Path, cache_dir: Path
) -> None:
    expected_sha = _load_expected_archive_sha256(node_version, archive_name, cache_dir)
    archive_url = f"{NODE_DIST_BASE_URL}/{node_version}/{archive_name}"

    if not archive_path.exists():
        print(f"Downloading portable Node.js from {archive_url}")
        _download(archive_url, archive_path)

    actual_sha = _compute_sha256(archive_path)
    if actual_sha.lower() == expected_sha:
        return

    print(f"Checksum mismatch for {archive_name}; re-downloading archive")
    archive_path.unlink(missing_ok=True)
    _download(archive_url, archive_path)
    actual_sha = _compute_sha256(archive_path)
    if actual_sha.lower() != expected_sha:
        raise RuntimeError(
            f"Checksum validation failed for {archive_name}: "
            f"expected {expected_sha}, got {actual_sha}"
        )


def _safe_extract_target(destination: Path, member_name: str) -> Path:
    if not member_name:
        raise RuntimeError("Archive contains an entry with an empty name")

    normalized_name = member_name.replace("\\", "/")
    candidate = (destination / normalized_name).resolve()
    destination_resolved = destination.resolve()
    try:
        candidate.relative_to(destination_resolved)
    except ValueError as exc:
        raise RuntimeError(
            f"Unsafe archive member path detected: {member_name}"
        ) from exc
    return candidate


def _safe_link_target(link_path: Path, link_name: str, destination: Path) -> Path:
    if not link_name:
        raise RuntimeError("Archive link entry has an empty target")
    normalized = link_name.replace("\\", "/")
    candidate = (link_path.parent / normalized).resolve()
    destination_resolved = destination.resolve()
    try:
        candidate.relative_to(destination_resolved)
    except ValueError as exc:
        raise RuntimeError(
            f"Unsafe archive link target detected: {link_name}"
        ) from exc
    return candidate


def _apply_file_mode(target: Path, mode: int) -> None:
    if os.name == "nt":
        return
    target.chmod(mode & 0o777)


def _extract_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                target = _safe_extract_target(destination, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        return
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        for member in members:
            target = _safe_extract_target(destination, member.name)
            if member.issym():
                if os.name == "nt":
                    raise RuntimeError(
                        "Archive symlink entries are not supported on Windows bootstrap"
                    )
                _safe_link_target(target, member.linkname, destination)
            elif member.islnk():
                raise RuntimeError(
                    f"Archive hardlink entries are not supported: {member.name}"
                )

        for member in members:
            target = _safe_extract_target(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.issym():
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    target.unlink()
                os.symlink(member.linkname, target)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"Unable to extract archive member: {member.name}")
            with extracted, target.open("wb") as output:
                shutil.copyfileobj(extracted, output)
            _apply_file_mode(target, member.mode)


def _ensure_portable_node(
    node_version: str,
    cache_dir: Path,
    allow_bootstrap: bool,
) -> tuple[Path, Path, Path, Path] | None:
    folder_name, archive_name = _node_archive_info(node_version)
    install_dir = cache_dir / folder_name
    node_bin, npm_bin, npx_bin, path_dir = _node_binary_paths(install_dir)
    if node_bin.exists() and npm_bin.exists() and npx_bin.exists():
        return node_bin, npm_bin, npx_bin, path_dir

    if not allow_bootstrap:
        return None

    archive_path = cache_dir / archive_name
    _ensure_verified_archive(
        node_version=node_version,
        archive_name=archive_name,
        archive_path=archive_path,
        cache_dir=cache_dir,
    )

    print(f"Extracting portable Node.js into {cache_dir}")
    _extract_archive(archive_path, cache_dir)

    if node_bin.exists() and npm_bin.exists() and npx_bin.exists():
        return node_bin, npm_bin, npx_bin, path_dir

    raise RuntimeError(
        f"Portable Node.js bootstrap succeeded but binaries were not found under {install_dir}"
    )


def _resolve_local_node(
    node_version: str,
    cache_dir: Path,
    allow_bootstrap: bool,
) -> tuple[Path, Path, Path, dict[str, str]]:
    system_node = shutil.which("node")
    system_npm = shutil.which("npm")
    system_npx = shutil.which("npx")
    if system_node and system_npm and system_npx:
        env = os.environ.copy()
        return Path(system_node), Path(system_npm), Path(system_npx), env

    portable = _ensure_portable_node(node_version, cache_dir, allow_bootstrap)
    if portable is None:
        raise RuntimeError(
            "node/npm were not found in PATH and portable bootstrap is disabled."
        )

    node_bin, npm_bin, npx_bin, path_dir = portable
    env = os.environ.copy()
    env["PATH"] = f"{path_dir}{os.pathsep}{env.get('PATH', '')}"
    return node_bin, npm_bin, npx_bin, env


def _run_local(
    mode: str,
    frontend_dir: Path,
    node_version: str,
    node_cache_dir: Path,
    bootstrap_local_node: bool,
) -> int:
    _node_bin, npm_bin, npx_bin, env = _resolve_local_node(
        node_version=node_version,
        cache_dir=node_cache_dir,
        allow_bootstrap=bootstrap_local_node,
    )

    commands = _local_commands(mode)
    for cmd in commands:
        executable = npm_bin if cmd[0] == "npm" else npx_bin
        local_cmd = [str(executable), *cmd[1:]]
        print("Running:", " ".join(local_cmd))
        completed = subprocess.run(local_cmd, cwd=frontend_dir, env=env, check=False)
        if completed.returncode != 0:
            return completed.returncode

    return 0


def _docker_available() -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    probe = subprocess.run(
        [docker, "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return probe.returncode == 0


def _run_docker(compose_file: Path, mode: str) -> int:
    command = _compose_command(compose_file, mode)
    print("Running:", " ".join(command))
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main() -> int:
    args = _parse_args()
    repo_root = _repo_root()
    compose_file = Path(args.compose_file).expanduser().resolve()
    frontend_dir = (repo_root / args.frontend_dir).resolve()
    node_cache_dir = (
        Path(args.node_cache_dir).expanduser().resolve()
        if args.node_cache_dir
        else _default_node_cache_dir().resolve()
    )

    if not frontend_dir.exists():
        print(f"Frontend directory not found: {frontend_dir}", file=sys.stderr)
        return 2
    if not compose_file.exists():
        print(f"Compose file not found: {compose_file}", file=sys.stderr)
        if args.engine == "docker":
            return 2

    use_docker = args.engine == "docker" or (
        args.engine == "auto" and compose_file.exists() and _docker_available()
    )

    try:
        if use_docker:
            return _run_docker(compose_file=compose_file, mode=args.mode)

        return _run_local(
            mode=args.mode,
            frontend_dir=frontend_dir,
            node_version=args.node_version,
            node_cache_dir=node_cache_dir,
            bootstrap_local_node=args.bootstrap_local_node,
        )
    except FileNotFoundError as exc:
        print(f"Required executable not found: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
