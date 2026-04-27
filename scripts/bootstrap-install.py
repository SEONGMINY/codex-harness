#!/usr/bin/env python3
"""Download and install codex-harness into a target repository."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_REPO = "https://github.com/SEONGMINY/codex-harness.git"


def run(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Target Codex project. Defaults to current directory.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="codex-harness git repository URL.")
    parser.add_argument("--ref", help="Git ref to install.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing harness files.")
    parser.add_argument(
        "--with-hooks",
        action="store_true",
        help="Install repo-local Codex hook config and hook scripts.",
    )
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        print(f"[ERROR] Target directory does not exist: {target}", file=sys.stderr)
        return 1

    if not shutil.which("git"):
        print("[ERROR] git is required.", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="codex-harness-") as tmp:
        source = Path(tmp) / "codex-harness"
        run(["git", "clone", "--depth", "1", args.repo, str(source)])
        if args.ref:
            run(["git", "fetch", "--depth", "1", "origin", args.ref], cwd=source)
            run(["git", "checkout", "FETCH_HEAD"], cwd=source)

        install_script = source / "scripts" / "install-codex-harness.py"
        command = [sys.executable, str(install_script), str(target)]
        if args.force:
            command.append("--force")
        if args.with_hooks:
            command.append("--with-hooks")
        run(command)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
