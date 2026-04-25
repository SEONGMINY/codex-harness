#!/usr/bin/env python3
"""Install codex-harness into another Codex project."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


INSTALL_PATHS = [
    (Path(".agents") / "skills" / "codex-harness", Path(".agents") / "skills" / "codex-harness"),
    (Path("scripts") / "harness", Path("scripts") / "harness"),
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def copy_tree(source: Path, target: Path, force: bool) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Missing source path: {source}")
    if target.exists():
        if not force:
            raise FileExistsError(f"Target already exists: {target}. Re-run with --force.")
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="Target Codex project or repository root.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing harness files.")
    args = parser.parse_args()

    source_root = repo_root()
    target_root = Path(args.target).expanduser().resolve()
    if not target_root.exists() or not target_root.is_dir():
        print(f"[ERROR] Target directory does not exist: {target_root}", file=sys.stderr)
        return 1

    for source_rel, target_rel in INSTALL_PATHS:
        copy_tree(source_root / source_rel, target_root / target_rel, args.force)
        print(f"installed {target_rel}")

    print(f"codex-harness installed into {target_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
