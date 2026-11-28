"""Repository-level reference checks; this file is not shipped to generated projects.

Two guards live here. The decision checks run in CI and make sure every citation anywhere in the
repository names a record that exists at the repo root. The old-name scan is opt-in so it cannot
turn CI red during the merge; W6 runs it with ROAT_ACCEPTANCE=1 and a later one-line pull request
turns it on for good. The neighbouring guard in ``tests/test_template.py`` owns ``template/`` for
citations, so the decision checks below do not duplicate that work.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "docs" / "decisions"
THIS_FILE = Path(__file__).resolve().relative_to(ROOT).as_posix()

# --- constants that W4 and W6 can change without reading the rest of this file --------------------

# Citation shapes that name a record; capture group 1 is the four-digit number.
DECISION_CITATIONS = (
    re.compile(r"\bADR[- ]?(\d{4})\b"),
    re.compile(r"decisions/(\d{4})-[a-z0-9-]+\.md"),
    re.compile(r"\b[Dd]ecision (\d{4})\b"),
)
# Front-matter key a consolidated record uses for the old records it replaces (W4 to confirm).
REPLACES_KEY = "replaces"
# One replacement entry: an old repository's full name, one space, its four-digit number.
# The names are assembled from two string pieces so the old-name scan cannot match this file.
_OLD_A = "Repo-" "Template"
_OLD_B = "Agents-" "Skills-Roles-Oriented"
REPLACES_ENTRY = re.compile(rf"^({_OLD_A}|{_OLD_B}) \d{{4}}$")
# Patterns for the acceptance scan. Each is built from pieces so this file does not match itself.
OLD_NAMES = (
    re.compile(_OLD_A.replace("-", "[-_ ]"), re.IGNORECASE),
    re.compile(_OLD_B.replace("-", "[-_ ]"), re.IGNORECASE),
    re.compile(r"\b" + "R" "T" + r"\b"),
    re.compile(r"\b" + "A" "SRO" + r"\b"),
    re.compile(r"github\.com/[A-Za-z0-9_.-]+/" + _OLD_A.replace("-", "[-_ ]"), re.IGNORECASE),
    re.compile(r"github\.com/[A-Za-z0-9_.-]+/" + _OLD_B.replace("-", "[-_ ]"), re.IGNORECASE),
    re.compile(r"verify-" + "work", re.IGNORECASE),
    re.compile(r"review-" + "change", re.IGNORECASE),
    re.compile(r"roles/" + r"[^/\s]+/skills"),
)
# True while the scan is opt-in; W6 flips this one line in the follow-up pull request.
ACCEPTANCE_GATE = True

# The decision checks skip template/ (the existing guard owns it), tests/ (they spell the patterns)
# and binary assets. The old-name scan sees every tracked UTF-8 file, template/ included.
_DECISION_SKIP = ("template/", "tests/", ".github/assets/")


def _tracked_files() -> list[tuple[str, str]]:
    """(path, UTF-8 text) for every tracked file; unreadable and binary files are skipped."""
    try:
        proc = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"cannot list tracked files with git: {exc}")
    files = []
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "surrogateescape")
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        files.append((rel, text))
    return files


def _front_matter(text: str) -> dict[str, str]:
    """Simple ``key: value`` front-matter reader, like the neighbouring root tests use."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            fm[key.strip()] = value.strip()
    return fm


def _inline_list(value: str) -> list[str]:
    """Entries of an inline list, or ValueError when the value is not a list of strings."""
    if not (value.startswith("[") and value.endswith("]")):
        raise ValueError(f"{REPLACES_KEY} is not a list: {value!r}")
    inner = value[1:-1].strip()
    if not inner:
        return []
    quoted = r'"[^"]*"|\'[^\']*\''
    entries = [a if a is not None else b for a, b in re.findall(r'"([^"]*)"|\'([^\']*)\'', inner)]
    leftover = re.sub(quoted, "", inner).strip(" ,\t")
    if leftover:
        raise ValueError(f"{REPLACES_KEY} has a non-string entry: {value!r}")
    return entries


def _record_numbers() -> list[str]:
    return [p.name[:4] for p in DECISIONS.glob("[0-9][0-9][0-9][0-9]-*.md")]


def test_every_decision_citation_resolves():
    files = _tracked_files()
    # An empty or failed `git ls-files` scan must not pass vacuously.
    assert len(files) > 50, f"the scan saw only {len(files)} tracked UTF-8 files"
    numbers = set(_record_numbers())
    checked = 0
    bad = []
    for rel, text in files:
        if rel.startswith(_DECISION_SKIP):
            continue
        checked += 1
        for pattern in DECISION_CITATIONS:
            for match in pattern.finditer(text):
                if match.group(1) not in numbers:
                    line = text.count("\n", 0, match.start()) + 1
                    bad.append(f"{rel}:{line}: {match.group(0)}")
    assert checked > 0, "no file was checked outside template/, tests/ and .github/assets/"
    assert not bad, "unresolved decision citations:\n" + "\n".join(sorted(bad))


def test_decision_numbers_are_unique_and_start_at_0000():
    numbers = _record_numbers()
    assert numbers, "no decision records at the repo root"
    assert len(numbers) == len(set(numbers)), f"duplicate decision numbers: {numbers}"
    assert min(numbers) == "0000", f"the consolidated sequence starts at {min(numbers)}, not 0000"


def test_replaces_entries_are_well_formed():
    records = sorted(DECISIONS.glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert records, "no decision records at the repo root"
    # No record has the key yet, so guard the validator itself against a vacuous pass.
    try:
        accepted = _inline_list("not a list")
    except ValueError:
        pass
    else:
        pytest.fail(f"the {REPLACES_KEY} validator accepted {accepted!r}")
    problems = []
    for path in records:
        fm = _front_matter(path.read_text(encoding="utf-8"))
        if REPLACES_KEY not in fm:
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            entries = _inline_list(fm[REPLACES_KEY])
        except ValueError as exc:
            problems.append(f"{rel}: front matter: {exc}")
            continue
        for entry in entries:
            if not REPLACES_ENTRY.fullmatch(entry):
                problems.append(f"{rel}: front matter: malformed {REPLACES_KEY} entry {entry!r}")
    assert not problems, "\n".join(problems)


@pytest.mark.skipif(
    os.environ.get("ROAT_ACCEPTANCE") != "1" and ACCEPTANCE_GATE,
    reason="acceptance scan: set ROAT_ACCEPTANCE=1",
)
def test_no_file_mentions_the_old_repositories():
    problems = set()
    for rel, text in _tracked_files():
        if rel == THIS_FILE:
            continue
        lines = text.splitlines()
        fm_end = None
        if lines and lines[0].strip() == "---":
            fm_end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        for lineno, line in enumerate(lines, 1):
            if (rel.startswith("docs/decisions/") and rel.endswith(".md") and fm_end is not None
                    and lineno <= fm_end + 1 and line.lstrip().startswith(REPLACES_KEY + ":")):
                continue  # a record is allowed to name what it replaces
            for pattern in OLD_NAMES:
                for match in pattern.finditer(line):
                    problems.add(f"{rel}:{lineno}: {match.group(0)}")
    assert not problems, "leftover mentions of the old repositories:\n" + "\n".join(sorted(problems))
