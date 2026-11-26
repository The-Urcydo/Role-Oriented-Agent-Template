#!/usr/bin/env python3
"""Scaffold a new skill in agents/skills/ with valid front matter and fill-in steps.

Usage:
  python3 tools/new_skill.py NAME [--description TEXT] [--requires work-tracker]
                             [--invocation user] [--force] [--root DIR]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _lib  # noqa: E402

import argparse  # noqa: E402
import re  # noqa: E402

NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DEFAULT_DESCRIPTION = "<fill: what this skill does and when to use it>"
TEMPLATE = """---
name: {name}
description: "{description}"
{metadata}---
# {title}

<fill: one-line purpose: what this skill does and when to use it>

## Steps

1. <fill: first step>

## Verify

<fill: command or observable result that proves it worked>

## Stop and ask

<fill: conditions that require the owner or user to answer>
"""


def unreadable_skills(root: Path, target: Path) -> list[Path]:
    bad = []
    for folder in _lib.skill_folders(root):
        path = folder / "SKILL.md"
        if path == target:
            continue
        try:
            fm, _ = _lib.parse_front_matter(_lib.read_text(path), _lib.SKILL_MAP_KEYS)
            if fm is None:
                raise _lib.FrontMatterError("missing front matter")
        except (_lib.FrontMatterError, OSError, UnicodeDecodeError):
            bad.append(path)
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="skill name and folder name")
    ap.add_argument("--description", default=DEFAULT_DESCRIPTION, help="what the skill does and when to use it")
    ap.add_argument("--requires", choices=("work-tracker",), help="declare a dependency on this repository's work tracker")
    ap.add_argument("--invocation", choices=("user",), help="mark the skill as user-invoked")
    ap.add_argument("--force", action="store_true", help="overwrite an existing SKILL.md")
    ap.add_argument("--root", type=Path, default=None, help="repository root")
    args = ap.parse_args(argv)

    root = (args.root or _lib.repo_root()).expanduser().resolve()
    if not NAME_RE.fullmatch(args.name) or len(args.name) > 64:
        print("error: name must be 1-64 chars: lowercase letters, digits and single hyphens", file=sys.stderr)
        return 2

    description = " ".join(args.description.split())
    if not description:
        print("error: description must not be empty", file=sys.stderr)
        return 2
    if len(description) > 1024:
        print("error: description must be 1024 characters or fewer", file=sys.stderr)
        return 2

    folder = root / _lib.SKILLS_DIR / args.name
    target = folder / "SKILL.md"
    if (folder.exists() or folder.is_symlink()) and not args.force:
        print(f"error: {folder.relative_to(root)} already exists (use --force to overwrite)", file=sys.stderr)
        return 2

    bad = unreadable_skills(root, target)
    if bad:
        print("error: fix unreadable skills before scaffolding:", file=sys.stderr)
        for path in bad:
            print(f"  {path.relative_to(root).as_posix()}", file=sys.stderr)
        return 2

    metadata = []
    if args.requires:
        metadata.append(f"  requires: {args.requires}")
    if args.invocation:
        metadata.append(f"  invocation: {args.invocation}")
    metadata_text = "metadata:\n" + "\n".join(metadata) + "\n" if metadata else ""
    escaped = description.replace("\\", "\\\\").replace('"', '\\"')
    content = TEMPLATE.format(
        name=args.name,
        description=escaped,
        metadata=metadata_text,
        title=args.name.replace("-", " ").title(),
    )
    try:
        if folder.is_symlink() or folder.is_file():
            folder.unlink()
        folder.mkdir(parents=True, exist_ok=True)
        _lib.write_text(target, content)
    except OSError as exc:
        print(f"error: cannot write {target.relative_to(root)}: {exc}", file=sys.stderr)
        return 2

    print(f"created {target.relative_to(root).as_posix()}")
    print(
        f"list {args.name} in a role's skills: field (agents/roles/<role>/ROLE.md), then run: "
        "python3 tools/sync_agents.py && python3 tools/sync_indexes.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
