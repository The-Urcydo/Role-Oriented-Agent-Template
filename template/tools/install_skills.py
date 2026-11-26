#!/usr/bin/env python3
"""Install skills from this repository into an agent's project skills folder.

Targets:
  claude    .claude/skills/<name>/
  opencode  .opencode/skills/<name>/
  agents    .agents/skills/<name>/

The whole skill folder is copied, never symlinked. By default --all skips skills
whose front matter declares metadata.requires; naming a skill installs it anyway.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _lib  # noqa: E402

import argparse  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

TARGETS = {
    "claude": ".claude/skills",
    "opencode": ".opencode/skills",
    "agents": ".agents/skills",
}
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
NO_PORTABLE = "no portable skills to install (use --include-tracker-bound or --skill)"


def available_skills(root: Path) -> list[str]:
    return [p.name for p in _lib.skill_folders(root) if (p / "SKILL.md").is_file()]


def declares_requires(skill: Path) -> bool:
    metadata = _lib.read_skill_fm(skill / "SKILL.md").get("metadata")
    return isinstance(metadata, dict) and "requires" in metadata


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def install_skill(src: Path, dest: Path, target: str) -> None:
    """Copy to a temporary sibling, then replace dest without losing it on a copy failure."""
    tmp = Path(tempfile.mkdtemp(prefix=f".{dest.name}.new-", dir=dest.parent))
    backup: Path | None = None
    try:
        shutil.copytree(src, tmp, dirs_exist_ok=True, ignore=IGNORE)
        try:
            tmp.chmod(src.stat().st_mode & 0o777)
        except OSError:
            pass
        if target == "claude":
            skill_md = tmp / "SKILL.md"
            text = skill_md.read_bytes().decode("utf-8")
            converted = _lib.claude_skill_text(text)
            if converted != text:
                skill_md.write_bytes(converted.encode("utf-8"))
        if dest.exists() or dest.is_symlink():
            backup = Path(tempfile.mkdtemp(prefix=f".{dest.name}.old-", dir=dest.parent))
            backup.rmdir()
            dest.rename(backup)
        try:
            tmp.rename(dest)
        except BaseException:
            if backup is not None and not (dest.exists() or dest.is_symlink()):
                backup.rename(dest)
                backup = None
            raise
        if backup is not None:
            try:
                remove_path(backup)
            except OSError:
                pass
            backup = None
    finally:
        if tmp.exists() or tmp.is_symlink():
            remove_path(tmp)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, choices=sorted(TARGETS))
    ap.add_argument("--skill", action="append", default=[], help="skill name; repeat for several")
    ap.add_argument("--all", action="store_true", help="install every portable skill")
    ap.add_argument("--include-tracker-bound", action="store_true", help="with --all, also install skills declaring metadata.requires")
    ap.add_argument("--project", type=Path, default=Path("."), help="project root (default: current directory)")
    ap.add_argument("--root", type=Path, default=None, help="library root (default: this checkout)")
    ap.add_argument("--force", action="store_true", help="replace an existing skill folder")
    ap.add_argument("--dry-run", action="store_true", help="show what would be copied; exits 1 when the real run would skip")
    args = ap.parse_args(argv)

    root = (args.root or _lib.repo_root()).expanduser().resolve()
    project = args.project.expanduser().resolve()
    if not project.is_dir():
        print(f"error: project directory does not exist: {project}", file=sys.stderr)
        return 2

    skills = available_skills(root)
    if args.all and args.skill:
        print("error: use either --all or --skill, not both", file=sys.stderr)
        return 2
    if args.include_tracker_bound and not args.all:
        print("error: --include-tracker-bound requires --all", file=sys.stderr)
        return 2
    if not args.all and not args.skill:
        print("error: pass --skill NAME (repeatable) or --all", file=sys.stderr)
        return 2

    if args.all:
        selected = [
            name for name in skills
            if args.include_tracker_bound or not declares_requires(root / _lib.SKILLS_DIR / name)
        ]
        if not selected:
            print(NO_PORTABLE, file=sys.stderr)
            return 1
    else:
        selected = list(dict.fromkeys(args.skill))
        missing = [name for name in selected if name not in skills]
        if missing:
            print(f"error: unknown skill(s): {', '.join(missing)}", file=sys.stderr)
            print(f"available: {', '.join(skills) or '(none)'}", file=sys.stderr)
            return 2
        for name in selected:
            if declares_requires(root / _lib.SKILLS_DIR / name):
                print(
                    f"note: {name} needs this repository's work tracker (metadata.requires: work-tracker); "
                    "it is not portable",
                    file=sys.stderr,
                )

    dest_root = project / TARGETS[args.target]
    if not args.dry_run:
        try:
            dest_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"error: cannot create {dest_root.relative_to(project)}: {exc}", file=sys.stderr)
            return 2

    failed = 0
    for name in selected:
        src = root / _lib.SKILLS_DIR / name
        dest = dest_root / name
        relative = dest.relative_to(project).as_posix()
        exists = dest.exists() or dest.is_symlink()
        if exists and not args.force:
            reason = f"{relative} exists (use --force to replace)"
            print(f"would skip {name}: {reason}" if args.dry_run else f"skipped {name}: {reason}")
            failed += 1
            continue
        if args.dry_run:
            action = "replace" if exists else "install"
            print(f"would {action} {name} -> {relative}")
            continue
        try:
            install_skill(src, dest, args.target)
        except (OSError, UnicodeError) as exc:
            print(f"skipped {name}: {exc}")
            failed += 1
            continue
        print(f"installed {name} -> {relative}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
