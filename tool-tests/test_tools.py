"""Tests for the repo tooling. Standard library only.

In this repository the files live in root-level `tool-tests/` and the root suite copies them into
a generated project as `tools/tests/` before running them. Each test works on a throwaway copy of
that project, so nothing touches your real files.
"""
from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
# In a generated project this file is copied to tools/tests/; in this repo it lives in tool-tests/.
ROOT = HERE.parents[1] if HERE.parent.name == "tools" else HERE.parent
sys.path.insert(0, str(ROOT / "tools"))

import _lib  # noqa: E402


_SKIP_ANYWHERE = shutil.ignore_patterns(
    ".git", "__pycache__", ".locks", "*.pyc", "node_modules", ".venv",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".DS_Store",
)
_CODE_FOLDERS = {"src", "apps", "packages", "data", "notebooks", "tests"}  # product code is irrelevant here and may be huge
_VOLATILE = ("items", "archive", "inbox", "research")  # work/ subfolders that hold real project data


def _ignore(directory: str, names: list[str]) -> set[str]:
    skip = set(_SKIP_ANYWHERE(directory, names))
    if Path(directory) == ROOT:
        skip |= _CODE_FOLDERS & set(names)
    return skip


_PRISTINE: Path | None = None


def _build_pristine(repo: Path) -> None:
    """The harness with the project's own data removed and the generated files rebuilt, so a real
    project's work items, open questions and code cannot change what these tests see."""
    shutil.copytree(ROOT, repo, ignore=_ignore)
    for sub in _VOLATILE:
        folder = repo / "work" / sub
        for child in list(folder.iterdir()) if folder.is_dir() else []:
            if child.name.lower() != "readme.md":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    queue = repo / "work" / "HUMAN.md"
    text = queue.read_text(encoding="utf-8")
    queue.write_text(text[: text.index("## Open")] + "## Open\n\n_None._\n\n## Answered\n", encoding="utf-8")
    for tool in ("sync_indexes", "sync_agents"):  # generated files are derived from the tree we just pruned
        r = run(repo, tool)
        if r.returncode != 0:
            raise RuntimeError(f"{tool} failed on the test fixture:\n{r.stdout}\n{r.stderr}")


def _pristine() -> Path:
    """Build the fixture once per process. Every test gets a cheap copy, never the original."""
    global _PRISTINE
    if _PRISTINE is None:
        repo = Path(tempfile.mkdtemp(prefix="repo-tests-")) / "repo"
        _build_pristine(repo)
        atexit.register(shutil.rmtree, repo.parent, ignore_errors=True)
        _PRISTINE = repo
    return _PRISTINE


def clone(dest: Path) -> Path:
    """A throwaway copy of the prepared harness. Copying the fixture is ~4x cheaper than rebuilding
    it, and rebuilding it runs two Python processes per test."""
    repo = dest / "repo"
    shutil.copytree(_pristine(), repo)
    return repo


def run(repo: Path, tool: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "tools" / f"{tool}.py"), *args],
        cwd=repo, env={**os.environ, "REPO_ROOT": str(repo)}, capture_output=True, text=True, timeout=120,
    )


class RepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = clone(Path(self._tmp.name))

    def sh(self, tool: str, *args: str) -> subprocess.CompletedProcess:
        return run(self.repo, tool, *args)

    def ok(self, tool: str, *args: str) -> str:
        r = self.sh(tool, *args)
        self.assertEqual(r.returncode, 0, f"{tool} {args} failed:\n{r.stdout}\n{r.stderr}")
        return r.stdout.strip()

    def fails(self, tool: str, *args: str) -> str:
        r = self.sh(tool, *args)
        self.assertNotEqual(r.returncode, 0, f"{tool} {args} should have failed:\n{r.stdout}")
        return r.stdout + r.stderr

    def new_item(self, slug: str = "login-flow", *extra: str) -> str:
        path = self.ok("new_item", slug, *extra)
        return Path(path).parent.name if path.endswith("handoff.md") else Path(path).stem

    def set_skills(self, role: str, names: list[str]) -> None:
        """Replace a charter's inline `skills:` list, keeping the rest of the file."""
        p = self.repo / "agents" / "roles" / role / "ROLE.md"
        line = "skills: [" + ", ".join(names) + "]"
        p.write_text(re.sub(r"(?m)^skills: .*$", line, p.read_text(encoding="utf-8"), count=1), encoding="utf-8")

    def charter_skills(self, role: str) -> list[str]:
        """A role's `skills:` list, parsed by the repository parser."""
        p = self.repo / "agents" / "roles" / role / "ROLE.md"
        fm, _ = _lib.parse_front_matter(p.read_text(encoding="utf-8"))
        return fm.get("skills") or []


class FrontMatterTests(unittest.TestCase):
    def test_parses_scalars_and_lists(self) -> None:
        fm, body = _lib.parse_front_matter(
            "---\ntitle: \"Hello: world\"\nn: 3\nflag: true\ntags: [a, \"b, c\", d]\nitems:\n- x\n- y\nnote: a # comment\n---\nbody\n"
        )
        self.assertEqual(fm["title"], "Hello: world")
        self.assertEqual(fm["n"], 3)
        self.assertIs(fm["flag"], True)
        self.assertEqual(fm["tags"], ["a", "b, c", "d"])
        self.assertEqual(fm["items"], ["x", "y"])
        self.assertEqual(fm["note"], "a")
        self.assertEqual(body, "body\n")

    def test_apostrophe_inside_a_word_is_not_a_quote(self) -> None:
        fm, _ = _lib.parse_front_matter(
            "---\nnever: [change code, change an accepted ADR's decision, don't guess]\nnote: it's fine # c\n---\n"
        )
        self.assertEqual(fm["never"], ["change code", "change an accepted ADR's decision", "don't guess"])
        self.assertEqual(fm["note"], "it's fine")

    def test_quotes_still_group_at_token_start(self) -> None:
        fm, _ = _lib.parse_front_matter("---\nk: ['a, b', \"c, d\", e's]\n---\n")
        self.assertEqual(fm["k"], ["a, b", "c, d", "e's"])

    def test_rejects_plain_values_that_real_yaml_rejects(self) -> None:
        for bad in ["summary: harness: roles", "summary: ends with colon:", "summary: [unclosed", "summary: `code` first",
                    "summary: *star", "summary: @at", "k: [a, b: c]"]:
            with self.assertRaises(_lib.FrontMatterError, msg=bad):
                _lib.parse_front_matter(f"---\n{bad}\n---\n")

    def test_no_front_matter(self) -> None:
        fm, body = _lib.parse_front_matter("# just a heading\n")
        self.assertIsNone(fm)
        self.assertEqual(body, "# just a heading\n")

    def test_rejects_duplicates_and_nesting(self) -> None:
        with self.assertRaises(_lib.FrontMatterError):
            _lib.parse_front_matter("---\na: 1\na: 2\n---\n")
        with self.assertRaises(_lib.FrontMatterError):
            _lib.parse_front_matter("---\na:\n  b: 1\n---\n")

    def test_parses_a_one_level_metadata_map_for_skills_only(self) -> None:
        text = "---\nname: s\ndescription: d\nmetadata:\n  invocation: user\n  requires: work-tracker\n---\nbody\n"
        fm, body = _lib.parse_front_matter(text, _lib.SKILL_MAP_KEYS)
        self.assertEqual(fm["metadata"], {"invocation": "user", "requires": "work-tracker"})
        self.assertEqual(body, "body\n")
        # charters pass no map keys, so the same shape stays rejected for them
        with self.assertRaises(_lib.FrontMatterError):
            _lib.parse_front_matter("---\nrole: r\nmetadata:\n  invocation: user\n---\n")
        # a one-level map holds strings only: a list value is refused
        with self.assertRaises(_lib.FrontMatterError):
            _lib.parse_front_matter("---\nmetadata:\n  invocation: [user]\n---\n", _lib.SKILL_MAP_KEYS)

    def test_set_value_replaces_and_inserts(self) -> None:
        text = "---\nstatus: draft\nevidence:\n- old\nz: 1\n---\nbody\n"
        text = _lib.set_fm_value(text, "evidence", _lib.yaml_list(["a", "b: c"]))
        text = _lib.set_fm_value(text, "extra", "v")
        fm, _ = _lib.parse_front_matter(text)
        self.assertEqual(fm["evidence"], ["a", "b: c"])
        self.assertEqual(fm["z"], 1)
        self.assertEqual(fm["extra"], "v")

    def test_yaml_scalar_round_trips_awkward_values(self) -> None:
        for value in ["plain", "with: colon", "has # hash", "true", "123", "", "say \"hi\"", "- dash", "a, b"]:
            fm, _ = _lib.parse_front_matter(f"---\nk: {_lib.yaml_scalar(value)}\n---\n")
            self.assertEqual(str(fm["k"]), value, value)

    def test_links_ignore_code(self) -> None:
        text = "[a](x.md)\n`[b](y.md)`\n```\n[c](z.md)\n```\n[d](https://e.com)\n"
        self.assertEqual([t for _, t in _lib.md_links(text)], ["x.md", "https://e.com"])

    def test_bom_front_matter_parses_and_preserves_the_body(self) -> None:
        fm, body = _lib.parse_front_matter("\ufeff---\nname: example-skill\ndescription: Example.\n---\nbody\n")
        self.assertEqual(fm["name"], "example-skill")
        self.assertEqual(fm["description"], "Example.")
        self.assertEqual(body, "body\n")


class HealthTests(RepoTestCase):
    def test_fresh_repo_is_healthy(self) -> None:
        self.assertIn("ok", self.ok("check"))
        self.ok("check", "--strict")

    def test_json_output(self) -> None:
        data = json.loads(self.ok("check", "--json"))
        self.assertIsInstance(data, list)
        self.assertTrue(all({"level", "code", "where", "msg"} <= set(f) for f in data))

    def test_stubs_listing_never_fails(self) -> None:
        self.assertIn("placeholder", self.ok("check", "--stubs"))

    def test_stubs_report_release_placeholders(self) -> None:
        out = self.ok("check", "--stubs")
        # SECURITY.md and CODEOWNERS belong to optional modules: when a project cut the
        # module, the file is gone and --stubs must not report it.
        for where in ("README.md", "SECURITY.md", ".github/CODEOWNERS"):
            if (self.repo / where).is_file():
                self.assertIn(where, out)

    def test_invalid_adapter_targets_report_without_crashing(self) -> None:
        p = self.repo / "agents" / "adapters" / "targets.json"
        p.write_text("{not json\n", encoding="utf-8")
        out = self.fails("check")
        self.assertIn("adapters", out)
        self.assertNotIn("Traceback", out)

        p.write_text("[]\n", encoding="utf-8")
        out = self.fails("check")
        self.assertIn("adapters", out)
        self.assertNotIn("Traceback", out)

    def test_agents_md_over_budget_fails(self) -> None:
        p = self.repo / "AGENTS.md"
        p.write_text(p.read_text() + "\n".join(f"- extra rule {i}" for i in range(120)) + "\n")
        self.assertIn("agents-md-size", self.fails("check"))

    def test_broken_link_fails(self) -> None:
        p = self.repo / "docs" / "dev" / "explanation" / "ownership-and-handoffs.md"
        p.write_text(p.read_text() + "\nSee [nowhere](does-not-exist.md).\n")
        self.assertIn("broken-link", self.fails("check"))

    # An unresolved merge conflict (a `copier update`, an agent merge) must fail the check, not wait for a human search.
    # The markers are built here, so this file never has one at the start of a line.
    START, MID, END = "<" * 7 + " ours", "=" * 7, ">" * 7 + " theirs"

    def conflicted(self) -> str:
        return f"keep\n{self.START}\nours\n{self.MID}\ntheirs\n{self.END}\nafter\n"

    def test_unresolved_conflict_fails_with_path_and_line(self) -> None:
        (self.repo / "config.yml").write_text(self.conflicted(), encoding="utf-8")
        out = self.fails("check")
        self.assertIn("conflict-marker", out)
        self.assertIn("config.yml:2", out)

    def test_unresolved_conflict_in_a_doc_fails(self) -> None:
        p = self.repo / "docs" / "dev" / "reference" / "glossary.md"
        p.write_text(p.read_text() + "\n" + self.conflicted())
        self.assertIn("conflict-marker", self.fails("check"))

    def test_conflict_markers_in_a_fenced_markdown_example_pass(self) -> None:
        p = self.repo / "docs" / "dev" / "reference" / "glossary.md"
        p.write_text(p.read_text() + "\n```\n" + self.conflicted() + "```\n")
        self.ok("check")

    def test_a_shorter_fence_does_not_close_a_longer_markdown_fence(self) -> None:
        p = self.repo / "docs" / "dev" / "reference" / "glossary.md"
        # A doc may show a fenced example (```) inside a longer fence (`````); the markers are still code, not a conflict.
        p.write_text(p.read_text() + "\n`````markdown\n```\n" + self.conflicted() + "```\n`````\n")
        self.ok("check")

    def test_a_heading_underline_or_an_unclosed_marker_is_not_a_conflict(self) -> None:
        (self.repo / "notes.txt").write_text("Title\n" + self.MID + "\n\ntext\n", encoding="utf-8")
        (self.repo / "lone.txt").write_text(f"{self.START}\nnever closed\n", encoding="utf-8")
        self.ok("check")

    def test_binary_and_oversized_files_are_not_scanned(self) -> None:
        (self.repo / "blob.bin").write_bytes(b"\0" + self.conflicted().encode())
        (self.repo / "big.txt").write_text(self.conflicted() + "x" * 1_100_000, encoding="utf-8")
        self.ok("check")

    def test_git_ignored_folders_are_not_scanned(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        ignore = self.repo / ".gitignore"
        ignore.write_text(ignore.read_text(encoding="utf-8") + "\nbuild-output.txt\n", encoding="utf-8")
        (self.repo / "build-output.txt").write_text(self.conflicted(), encoding="utf-8")
        self.ok("check")  # ignored by git, so never read
        (self.repo / "app.txt").write_text(self.conflicted(), encoding="utf-8")
        self.assertIn("app.txt", self.fails("check"))

    def test_a_real_git_merge_conflict_is_reported_once(self) -> None:
        def git(*args: str) -> None:
            subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                           cwd=self.repo, check=True, capture_output=True)

        git("init", "-q", "-b", "main")
        (self.repo / "app.txt").write_text("one\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        git("checkout", "-q", "-b", "other")
        (self.repo / "app.txt").write_text("theirs\n", encoding="utf-8")
        git("commit", "-q", "-am", "theirs")
        git("checkout", "-q", "main")
        (self.repo / "app.txt").write_text("ours\n", encoding="utf-8")
        git("commit", "-q", "-am", "ours")
        merged = subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "merge", "other"],
                                cwd=self.repo, capture_output=True)
        self.assertNotEqual(merged.returncode, 0, "the merge should conflict")  # leaves markers and unmerged index entries
        out = self.fails("check")
        self.assertEqual(out.count("conflict-marker"), 1, out)  # one line per file, not one per index stage
        self.assertIn("app.txt:1", out)

    def test_missing_summary_fails(self) -> None:
        p = self.repo / "docs" / "dev" / "reference" / "glossary.md"
        p.write_text(p.read_text().replace("summary:", "sumary:", 1))
        self.assertIn("front-matter", self.fails("check"))

    def test_wrong_diataxis_folder_fails(self) -> None:
        p = self.repo / "docs" / "dev" / "reference" / "glossary.md"
        p.write_text(p.read_text().replace("type: reference", "type: how-to", 1))
        self.assertIn("diataxis", self.fails("check"))

    def test_hand_edited_generated_file_fails_until_synced(self) -> None:
        p = self.repo / "docs" / "INDEX.md"
        p.write_text(p.read_text() + "\nhand edit\n")
        self.assertIn("generated-drift", self.fails("check"))
        self.ok("sync_indexes")
        self.ok("check")

    def test_role_change_requires_resync(self) -> None:
        p = self.repo / "agents" / "roles" / "builder" / "ROLE.md"
        p.write_text(p.read_text().replace("Implement work items", "Build work items", 1))
        out = self.fails("check")
        self.assertTrue("generated-drift" in out or "adapter-drift" in out)
        self.ok("sync_indexes")
        self.ok("sync_agents")
        self.ok("check")

    def test_duplicate_item_file_ownership_fails(self) -> None:
        p = self.repo / "agents" / "roles" / "builder" / "ROLE.md"
        p.write_text(p.read_text().replace("item_files: []", "item_files: [brief.md]", 1))
        self.ok("sync_indexes")
        self.ok("sync_agents")
        self.assertIn("ownership", self.fails("check"))

    def test_unknown_owner_role_fails(self) -> None:
        p = self.repo / "work" / "inbox" / "README.md"
        p.write_text(p.read_text().replace("owner_role: orchestrator", "owner_role: ghost", 1))
        self.assertIn("ownership", self.fails("check"))

    def test_skill_name_must_match_folder(self) -> None:
        p = self.repo / "agents" / "skills" / "review-work" / "SKILL.md"
        p.write_text(p.read_text().replace("name: review-work", "name: mismatched", 1))
        self.assertIn("skill", self.fails("check"))

    def test_skill_folder_in_the_flat_lane_needs_its_own_skill_md(self) -> None:
        (self.repo / "agents" / "skills" / "empty-skill").mkdir(parents=True)
        self.assertIn("no SKILL.md", self.fails("check"))

    def test_role_must_equal_its_folder_name(self) -> None:
        p = self.repo / "agents" / "roles" / "builder" / "ROLE.md"
        p.write_text(p.read_text().replace("role: builder", "role: constructor", 1))
        self.assertIn("must equal the folder name", self.fails("check"))

    def test_old_flat_role_file_is_rejected_with_the_new_location(self) -> None:
        shutil.copy(self.repo / "agents" / "roles" / "builder" / "ROLE.md", self.repo / "agents" / "roles" / "legacy.md")
        out = self.fails("check")
        self.assertIn("agents/roles/legacy/ROLE.md", out)

    def test_role_folder_without_a_charter_is_an_error(self) -> None:
        (self.repo / "agents" / "roles" / "ghost").mkdir()
        self.assertIn("has no ROLE.md", self.fails("check"))

    def test_role_folders_have_no_role_local_skills_folder(self) -> None:
        for role in sorted(p for p in (self.repo / "agents" / "roles").iterdir() if p.is_dir()):
            self.assertFalse((role / "skills").exists(), f"{role.name} keeps a role-local skills/ folder")
        self.ok("check", "--strict")

    def test_a_skills_folder_under_a_role_is_an_error(self) -> None:
        (self.repo / "agents" / "roles" / "builder" / "skills").mkdir()
        out = self.fails("check")
        self.assertIn("skills live in agents/skills/", out)

    # --- charter `skills:` list (R2) ---------------------------------------------------------
    def test_a_charter_may_list_no_skills_but_must_have_the_key(self) -> None:
        builder = self.repo / "agents" / "roles" / "builder" / "ROLE.md"
        self.set_skills("builder", [])
        self.ok("sync_indexes")
        self.ok("sync_agents")
        self.assertIn("skills: []", builder.read_text())
        self.ok("check", "--strict")
        builder.write_text(re.sub(r"(?m)^skills: \[\]\n", "", builder.read_text(encoding="utf-8"), count=1),
                           encoding="utf-8")
        self.ok("sync_indexes")
        self.ok("sync_agents")
        out = self.fails("check")
        self.assertIn("missing 'skills'", out)

    def test_charter_skills_must_name_a_flat_skill_folder_once(self) -> None:
        self.set_skills("builder", ["ghost-skill"])
        out = self.fails("check")
        self.assertIn("agents/skills/ghost-skill/SKILL.md does not exist", out)
        self.set_skills("builder", ["record-decision", "record-decision"])
        self.assertIn("more than once", self.fails("check"))

    def test_a_skill_must_be_listed_by_a_role_charter(self) -> None:
        folder = self.repo / "agents" / "skills" / "unlisted-skill"
        folder.mkdir()
        (folder / "SKILL.md").write_text(
            "---\nname: unlisted-skill\ndescription: An unlisted test skill. Use when testing charter coverage.\n---\n"
            "## Steps\n\n1. Read the fixture.\n",
            encoding="utf-8",
        )
        self.ok("sync_agents")
        self.assertIn("skill-unlisted", self.fails("check"))
        self.set_skills("builder", [*self.charter_skills("builder"), "unlisted-skill"])
        self.ok("sync_indexes")
        self.ok("sync_agents")
        self.ok("check", "--strict")

    def test_a_skill_folder_without_skill_md_reports_one_error(self) -> None:
        (self.repo / "agents" / "skills" / "empty-skill").mkdir(parents=True)
        out = self.fails("check")
        self.assertIn("skill folder has no SKILL.md", out)
        self.assertNotIn("skill-unlisted", out)

    def test_no_roles_skips_the_unlisted_skill_check(self) -> None:
        shutil.rmtree(self.repo / "agents" / "roles")
        self.assertNotIn("skill-unlisted", self.fails("check"))

    # --- skill front matter and size (R3, R4) ------------------------------------------------
    def test_skill_fields_outside_the_specification_are_rejected(self) -> None:
        p = self.repo / "agents" / "skills" / "review-work" / "SKILL.md"
        p.write_text(p.read_text().replace("\n---\n", "\ndisable-model-invocation: true\n---\n", 1))
        out = self.fails("check")
        self.assertIn("disable-model-invocation", out)
        self.assertIn("metadata.invocation", out)

    def test_skill_metadata_keys_and_values_are_checked(self) -> None:
        p = self.repo / "agents" / "skills" / "review-work" / "SKILL.md"
        original = p.read_text()
        p.write_text(original.replace("metadata:\n  requires: work-tracker\n", "metadata:\n  requires: anything-else\n", 1))
        out = self.fails("check")
        self.assertIn("metadata.requires 'anything-else' is not allowed", out)
        p.write_text(original.replace("metadata:\n  requires: work-tracker\n", "metadata:\n  bogus: x\n", 1))
        self.assertIn("metadata key 'bogus' is not allowed", self.fails("check"))

    def test_non_map_skill_metadata_is_reported_and_never_crashes(self) -> None:
        p = self.repo / "agents" / "skills" / "review-work" / "SKILL.md"
        original = p.read_text()
        for shape in ("metadata:", "metadata: user", "metadata: []"):
            with self.subTest(shape=shape):
                p.write_text(original.replace("metadata:\n  requires: work-tracker\n", f"{shape}\n", 1), encoding="utf-8")
                out = self.fails("check")
                self.assertIn("metadata must hold indented `key: value` lines", out)
                self.assertNotIn("Traceback", out)
                r = self.sh("sync_agents")
                self.assertNotEqual(r.returncode, 0, f"sync_agents accepted {shape}:\n{r.stdout}\n{r.stderr}")
                lines = [line for line in (r.stdout + r.stderr).splitlines() if line.strip()]
                self.assertEqual(len(lines), 1, f"sync_agents: {lines}")
                self.assertIn("agents/skills/review-work/SKILL.md", lines[0])
                self.assertIn("metadata must hold indented `key: value` lines", lines[0])
                self.assertNotIn("Traceback", lines[0])
        p.write_text(original, encoding="utf-8")

    def test_skill_body_over_40_lines_warns_and_40_does_not(self) -> None:
        folder = self.repo / "agents" / "skills" / "line-test"
        folder.mkdir()
        head = ("---\nname: line-test\n"
                "description: A body-size fixture. Use when testing the 40-line warning.\n---\n")
        (folder / "SKILL.md").write_text(head + "\n".join(f"line {i}" for i in range(41)) + "\n", encoding="utf-8")
        self.set_skills("builder", [*self.charter_skills("builder"), "line-test"])
        self.ok("sync_indexes")
        self.ok("sync_agents")
        out = self.ok("check")
        self.assertIn("skill-size", out)
        self.assertIn("41 body lines", out)
        self.fails("check", "--strict")  # a warning fails --strict
        (folder / "SKILL.md").write_text(head + "\n".join(f"line {i}" for i in range(40)) + "\n", encoding="utf-8")
        self.ok("sync_agents")
        self.assertNotIn("skill-size", self.ok("check"))
        self.ok("check", "--strict")

    def test_skill_stubs_warn_in_bodies_and_references_and_strict_fails(self) -> None:
        folder = self.repo / "agents" / "skills" / "stub-test"
        references = folder / "references"
        references.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            "---\nname: stub-test\ndescription: A stub test skill. Use when testing unfinished text.\n---\n"
            "## Steps\n\n- <fill: x>\n\n- TODO: finish this\n\nThe word TODO in prose is fine.\n",
            encoding="utf-8",
        )
        (references / "details.md").write_text("# Details\n\nTODO: finish the details\n", encoding="utf-8")
        self.set_skills("builder", [*self.charter_skills("builder"), "stub-test"])
        self.ok("sync_indexes")
        self.ok("sync_agents")
        out = self.ok("check")
        self.assertIn("skill-stub", out)
        self.assertIn("SKILL.md:7", out)
        self.assertIn("SKILL.md:9", out)
        self.assertIn("references/details.md:3", out)
        self.assertNotIn("The word TODO", out)
        self.assertIn("skill-stub", self.fails("check", "--strict"))

    def test_skill_compatibility_must_be_1_to_500_characters(self) -> None:
        p = self.repo / "agents" / "skills" / "review-work" / "SKILL.md"
        original = p.read_text(encoding="utf-8")
        p.write_text(original.replace("description:", "compatibility: " + "x" * 501 + "\ndescription:", 1),
                     encoding="utf-8")
        self.assertIn("compatibility must be a string of 1-500 chars", self.fails("check"))
        p.write_text(original.replace("description:", "compatibility: " + "x" * 500 + "\ndescription:", 1),
                     encoding="utf-8")
        self.ok("sync_agents")
        self.ok("check", "--strict")

    def test_skill_allowed_tools_must_be_a_space_separated_string(self) -> None:
        p = self.repo / "agents" / "skills" / "review-work" / "SKILL.md"
        original = p.read_text(encoding="utf-8")
        for value in ("[Read, Grep]", "{Read: true}", "\n  Read: true"):
            with self.subTest(value=value):
                p.write_text(original.replace("description:", f"allowed-tools: {value}\ndescription:", 1),
                             encoding="utf-8")
                self.ok("sync_agents")
                r = self.sh("check")
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                out = r.stdout + r.stderr
                self.assertIn("allowed-tools", out)
                self.assertIn("Read Grep", out)
                self.assertNotIn("Traceback", out)
        p.write_text(original.replace("description:", "allowed-tools: Read Grep\ndescription:", 1),
                     encoding="utf-8")
        self.ok("sync_agents")
        self.ok("check", "--strict")

    def test_portable_skills_cannot_link_outside_their_folder(self) -> None:
        p = self.repo / "agents" / "skills" / "write-skill" / "SKILL.md"
        original = p.read_text(encoding="utf-8")
        p.write_text(original + "\n[project](../../../README.md)\n", encoding="utf-8")
        self.ok("sync_agents")
        out = self.fails("check")
        self.assertIn("skill-portable", out)
        self.assertIn("requires: work-tracker", out)

        p.write_text(original, encoding="utf-8")
        p = self.repo / "agents" / "skills" / "review-work" / "SKILL.md"
        original = p.read_text(encoding="utf-8")
        p.write_text(original + "\n[project](../../../README.md)\n", encoding="utf-8")
        self.ok("sync_agents")
        self.assertNotIn("skill-portable", self.ok("check", "--strict"))

    def test_portable_skills_may_link_to_an_existing_reference(self) -> None:
        p = self.repo / "agents" / "skills" / "write-skill" / "SKILL.md"
        original = p.read_text(encoding="utf-8")
        (p.parent / "references").mkdir(exist_ok=True)
        (p.parent / "references" / "x.md").write_text("# Details\n", encoding="utf-8")
        p.write_text(original + "\n[details](references/x.md#example)\n", encoding="utf-8")
        self.ok("sync_agents")
        self.ok("check", "--strict")

    def test_bom_front_matter_is_accepted(self) -> None:
        p = self.repo / "agents" / "skills" / "write-skill" / "SKILL.md"
        p.write_text("\ufeff" + p.read_text(encoding="utf-8"), encoding="utf-8")
        self.ok("sync_agents")
        self.assertNotIn("name must be", self.ok("check", "--strict"))

    # --- roster Skills column (R7) ------------------------------------------------------------
    def test_roster_skills_column_links_the_charter_list(self) -> None:
        self.set_skills("architect", ["record-decision", "write-doc"])
        self.set_skills("builder", [])
        self.set_skills("orchestrator", [*self.charter_skills("orchestrator"), "tailor-template", "write-skill"])
        self.ok("sync_indexes")
        self.ok("sync_agents")
        text = (self.repo / "agents" / "ROSTER.md").read_text(encoding="utf-8")
        row = next(r for r in text.splitlines() if r.startswith("| [`architect`]"))
        self.assertIn("[`record-decision`](skills/record-decision/SKILL.md)", row)
        self.assertIn("[`write-doc`](skills/write-doc/SKILL.md)", row)
        self.assertLess(row.index("record-decision"), row.index("write-doc"), "charter order is kept")
        builder = next(r for r in text.splitlines() if r.startswith("| [`builder`]"))
        self.assertTrue(builder.rstrip().endswith("| — |"), builder)
        self.ok("sync_indexes", "--check")
        self.ok("check", "--strict")

    def test_default_owner_must_be_a_real_role(self) -> None:
        shutil.rmtree(self.repo / "agents" / "roles" / "scribe")
        out = self.fails("check")
        self.assertIn("DEFAULT_OWNER", out)
        self.assertIn("scribe", out)

    def test_core_linking_into_module_is_an_error(self) -> None:
        modules = _lib.load_modules(self.repo)
        target = None
        for m in modules.values():
            for path in m["paths"]:
                full = self.repo / path
                if path.startswith("docs/") and full.is_dir() and (full / "README.md").exists():
                    target = path + "/README.md"
        if not target:
            self.skipTest("no docs module installed")
        p = self.repo / "docs" / "dev" / "explanation" / "ownership-and-handoffs.md"
        p.write_text(p.read_text() + f"\nSee [module](../../../{target}).\n")
        self.assertIn("module-coupling", self.fails("check"))

    def test_workspace_packages_and_boundary_checks(self) -> None:
        apps = self.repo / "apps"
        pkgs = self.repo / "packages"
        apps.mkdir(exist_ok=True)
        pkgs.mkdir(exist_ok=True)
        (apps / "README.md").write_text("---\nsummary: Apps.\nowner_role: builder\n---\n# apps\n")
        (pkgs / "README.md").write_text("---\nsummary: Packages.\nowner_role: builder\n---\n# packages\n")

        # Missing README inside a package subfolder fails
        (pkgs / "core").mkdir()
        self.assertIn("workspace-readme", self.fails("check"))

        # Valid package and app depending on package pass and appear in repo-map.md
        (pkgs / "core" / "README.md").write_text("---\nsummary: Core primitives.\n---\n# core\n")
        (apps / "web").mkdir()
        (apps / "web" / "README.md").write_text("---\nsummary: Web client.\ndepends_on: [core]\n---\n# web\n")
        self.ok("sync_indexes")
        self.ok("sync_agents")
        self.ok("check", "--strict")
        self.assertIn("`apps/web/`", (self.repo / "docs" / "dev" / "reference" / "repo-map.md").read_text())

        # Package depending on app fails with workspace-boundary
        (pkgs / "core" / "README.md").write_text("---\nsummary: Core primitives.\ndepends_on: [apps/web]\n---\n# core\n")
        self.ok("sync_indexes")
        self.assertIn("workspace-boundary", self.fails("check"))

        # Package dependency cycle fails with workspace-cycle
        (pkgs / "auth").mkdir()
        (pkgs / "core" / "README.md").write_text("---\nsummary: Core primitives.\ndepends_on: [auth]\n---\n# core\n")
        (pkgs / "auth" / "README.md").write_text("---\nsummary: Auth package.\ndepends_on: [core]\n---\n# auth\n")
        self.ok("sync_indexes")
        self.assertIn("workspace-cycle", self.fails("check"))


class WorkLifecycleTests(RepoTestCase):
    def test_full_lifecycle_and_guard_rails(self) -> None:
        item = self.new_item("login flow", "--title", "Login: the flow")
        self.assertRegex(item, r"^\d{4}-\d{2}-\d{2}-login-flow$")
        self.assertIn(item, (self.repo / "work" / "ACTIVE.md").read_text())
        self.ok("check")

        self.fails("transition", item, "done")  # draft -> done is illegal
        self.assertIn("--next", self.fails("transition", item, "planned"))
        self.ok("transition", item, "planned", "--next", "builder: start", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "building", "--by", "builder")
        self.assertIn("allowed from in-progress", self.fails("transition", item, "done", "--next", "x"))
        self.assertIn("evidence", self.fails("transition", item, "in-review", "--next", "verify", "--by", "builder"))
        self.ok("transition", item, "in-review", "--next", "verify", "--evidence", "python3 tools/check.py", "--by", "builder")
        self.assertIn("review.md", self.fails("transition", item, "verified", "--next", "docs", "--by", "reviewer"))
        self.ok("item_file", item, "review")
        self.fails("item_file", item, "review")  # never overwrites
        self.ok("transition", item, "verified", "--next", "update docs", "--by", "reviewer")
        self.ok("transition", item, "done", "--by", "scribe")
        self.ok("check")
        self.ok("archive_item", item)
        self.assertFalse((self.repo / "work" / "items" / item).exists())
        self.assertTrue(list((self.repo / "work" / "archive").glob(f"*/{item}")))
        self.assertNotIn(item, (self.repo / "work" / "ACTIVE.md").read_text())
        self.ok("check")

    def test_self_review_is_refused_by_transition_and_check(self) -> None:
        item = self.new_item("self-review-guard")
        self.ok("transition", item, "planned", "--next", "build", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "building", "--by", "builder")
        self.ok("transition", item, "in-review", "--next", "verify", "--evidence", "ran check", "--by", "builder")
        self.ok("item_file", item, "review")
        self.assertIn("independent review required",
                      self.fails("transition", item, "verified", "--next", "docs", "--by", "builder"))
        self.ok("transition", item, "verified", "--next", "docs", "--by", "reviewer")
        h = self.repo / "work" / "items" / item / "handoff.md"
        self.assertEqual(_lib.read_fm(h).get("verified_by"), "reviewer")
        self.ok("check", "--strict")
        # Hand-editing verified_by to match built_by is caught by check.py
        h.write_text(_lib.set_fm_value(h.read_text(), "verified_by", "builder"))
        self.assertIn("self-review", self.fails("check"))

    def test_status_change_requires_by(self) -> None:
        item = self.new_item("needs-actor")
        self.assertIn("--by", self.fails("transition", item, "planned", "--next", "build"))
        self.ok("transition", item, "planned", "--next", "build", "--by", "planner")
        self.assertIn("--by", self.fails("transition", item, "in-progress", "--next", "build"))

    def test_built_by_is_not_overwritten_when_reviewer_sends_back(self) -> None:
        item = self.new_item("provenance")
        self.ok("transition", item, "planned", "--next", "build", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "build", "--by", "builder")
        self.ok("transition", item, "in-review", "--next", "verify", "--evidence", "ran check", "--by", "builder")
        self.ok("transition", item, "in-progress", "--next", "fix findings", "--owner", "builder", "--by", "reviewer")
        h = self.repo / "work" / "items" / item / "handoff.md"
        self.assertEqual(_lib.read_fm(h).get("built_by"), "builder")

    def test_verified_and_done_need_built_by(self) -> None:
        item = self.new_item("missing-builder")
        self.ok("transition", item, "planned", "--next", "build", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "build", "--by", "builder")
        self.ok("transition", item, "in-review", "--next", "verify", "--evidence", "ran check", "--by", "builder")
        self.ok("item_file", item, "review")
        self.ok("transition", item, "verified", "--next", "docs", "--by", "reviewer")
        h = self.repo / "work" / "items" / item / "handoff.md"
        h.write_text(h.read_text().replace("built_by: builder\n", "", 1))
        self.assertIn("built_by", self.fails("check", "--strict"))

    def test_archive_refuses_unfinished_items(self) -> None:
        item = self.new_item("half-done")
        self.assertIn("only done or canceled items", self.fails("archive_item", item))

    def test_canceled_item_and_reviewer_reject_to_draft(self) -> None:
        item = self.new_item("bad-idea")
        self.ok("transition", item, "planned", "--next", "build", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "building", "--by", "builder")
        self.ok("transition", item, "in-review", "--next", "verify", "--evidence", "ran check", "--by", "builder")
        # Reviewer rejects back to draft for re-planning
        self.ok("transition", item, "draft", "--next", "re-plan approach", "--by", "reviewer")
        # Orchestrator cancels and archives
        self.ok("transition", item, "canceled", "--next", "dropped after review rejection", "--by", "orchestrator")
        self.ok("check", "--strict")
        self.ok("archive_item", item)
        self.assertFalse((self.repo / "work" / "items" / item).exists())
        self.ok("check", "--strict")

    def test_verified_item_can_still_be_canceled(self) -> None:
        item = self.new_item("overtaken-by-events")
        self.ok("transition", item, "planned", "--next", "build", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "building", "--by", "builder")
        self.ok("transition", item, "in-review", "--next", "verify", "--evidence", "ran check", "--by", "builder")
        self.ok("item_file", item, "review")
        self.ok("transition", item, "verified", "--next", "update docs", "--evidence", "criterion 1 checked", "--by", "reviewer")
        self.ok("transition", item, "canceled", "--next", "priorities changed before release", "--by", "orchestrator")
        self.assertEqual(_lib.read_fm(_lib.find_item(self.repo, item).handoff)["status"], "canceled")
        self.fails("transition", item, "in-progress", "--next", "reopen", "--by", "builder")  # canceled is final
        self.ok("check", "--strict")

    def test_security_review_item_file(self) -> None:
        if "security" not in _lib.load_modules(self.repo):
            self.skipTest("security module not installed")
        item = self.new_item("auth-change")
        path = self.ok("item_file", item, "security-review")
        self.assertTrue((self.repo / path).is_file())
        self.ok("check", "--strict")

    def _in_review(self, slug: str) -> str:
        item = self.new_item(slug)
        self.ok("transition", item, "planned", "--next", "build", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "build", "--by", "builder")
        self.ok("transition", item, "in-review", "--next", "verify", "--evidence", "ran check", "--by", "builder")
        self.ok("item_file", item, "review")
        return item

    def _set_security_flag(self, item: str, line: str) -> None:
        brief = self.repo / "work" / "items" / item / "brief.md"
        lines = brief.read_text(encoding="utf-8").splitlines()
        out = [line if old.strip().startswith("_required or not needed") else old for old in lines]
        self.assertNotEqual(out, lines, "the brief template no longer has the Security review placeholder")
        brief.write_text("\n".join(out) + "\n", encoding="utf-8")

    def test_verified_refuses_a_missing_security_review_when_the_brief_requires_one(self) -> None:
        if "security" not in _lib.load_modules(self.repo):
            self.skipTest("security module not installed")
        item = self._in_review("auth-gate")
        self._set_security_flag(item, "required: the change adds a sign-in form and stores password hashes.")
        reason = self.fails("transition", item, "verified", "--next", "docs", "--by", "reviewer")
        self.assertIn("security-review.md", reason)
        self.assertEqual(_lib.read_fm(_lib.find_item(self.repo, item).handoff)["status"], "in-review")
        self.ok("item_file", item, "security-review")
        self.ok("transition", item, "verified", "--next", "docs", "--by", "reviewer")
        self.ok("check", "--strict")

    def test_verified_security_gate_ignores_other_flags_and_the_placeholder(self) -> None:
        for name, flag in {
            "not needed": "not needed: a wording change; no input, data or permission is touched.",
            "no section": None,
            "placeholder": "placeholder",
        }.items():
            with self.subTest(flag=name):
                item = self._in_review(f"help-{name.replace(' ', '-')}")
                brief = self.repo / "work" / "items" / item / "brief.md"
                if flag == "placeholder":
                    pass
                elif flag is None:
                    text = brief.read_text(encoding="utf-8")
                    brief.write_text(
                        text[:text.index("## Security review")] + text[text.index("## Open questions"):],
                        encoding="utf-8",
                    )
                else:
                    self._set_security_flag(item, flag)
                self.ok("transition", item, "verified", "--next", "docs", "--by", "reviewer")

    def test_blocked_needs_a_reason_and_can_resume(self) -> None:
        item = self.new_item("waits")
        self.ok("transition", item, "planned", "--next", "go", "--by", "planner")
        self.fails("transition", item, "blocked")
        self.ok("transition", item, "blocked", "--next", "waiting on Q-0001", "--by", "orchestrator")
        self.ok("transition", item, "in-progress", "--next", "resumed", "--by", "builder")

    def test_light_item_has_one_file_and_still_needs_evidence(self) -> None:
        item = self.new_item("quick-fix", "--light")
        self.assertTrue((self.repo / "work" / "items" / f"{item}.md").is_file())
        self.fails("item_file", item, "review")
        self.ok("transition", item, "planned", "--next", "go", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "go", "--by", "builder")
        self.fails("transition", item, "in-review", "--next", "verify", "--by", "builder")
        self.ok("transition", item, "in-review", "--next", "verify", "--evidence", "ran it", "--by", "builder")
        self.ok("transition", item, "verified", "--next", "close", "--by", "reviewer")
        self.ok("transition", item, "done", "--by", "scribe")
        self.ok("check")

    def test_same_slug_twice_gets_unique_ids(self) -> None:
        a, b = self.new_item("same"), self.new_item("same")
        self.assertNotEqual(a, b)
        self.assertTrue(b.endswith("-2"))

    def test_unknown_role_is_rejected(self) -> None:
        self.assertIn("unknown role", self.fails("new_item", "x", "--owner", "wizard"))

    def test_hand_edit_with_bad_status_is_caught(self) -> None:
        item = self.new_item("sloppy")
        h = self.repo / "work" / "items" / item / "handoff.md"
        h.write_text(h.read_text().replace("status: draft", "status: finished", 1))
        self.assertIn("handoff", self.fails("check"))

    def test_done_without_review_is_caught(self) -> None:
        item = self.new_item("skipped-review")
        h = self.repo / "work" / "items" / item / "handoff.md"
        text = h.read_text().replace("status: draft", "status: done", 1).replace("evidence: []", "evidence: [x]", 1)
        h.write_text(text)
        self.assertIn("review.md", self.fails("check"))

    def test_sweep_marks_idle_items_stale_and_they_can_resume(self) -> None:
        item = self.new_item("forgotten")
        h = self.repo / "work" / "items" / item / "handoff.md"
        h.write_text(_lib.set_fm_value(h.read_text(), "updated", "2020-01-01"))
        self.assertIn("item-stale", self.fails("check", "--strict"))
        self.assertIn("stale", self.ok("archive_item", "--sweep"))
        fm = _lib.read_fm(h)
        self.assertEqual((fm["status"], fm["owner_role"]), ("stale", "orchestrator"))
        self.assertNotEqual(fm["updated"], "2020-01-01")  # marking stale resets the re-warn clock
        self.ok("check", "--strict")  # already marked stale: check --strict must not warn again
        self.ok("transition", item, "planned", "--next", "re-triaged", "--by", "orchestrator")

    def test_stale_items_rewarn_after_a_month(self) -> None:
        item = self.new_item("still-forgotten")
        h = self.repo / "work" / "items" / item / "handoff.md"
        h.write_text(_lib.set_fm_value(h.read_text(), "status", "stale"))
        old = (_lib.today() - timedelta(days=_lib.STALE_REWARN_DAYS + 1)).isoformat()
        h.write_text(_lib.set_fm_value(h.read_text(), "updated", old))
        self.assertIn("item-stale", self.fails("check", "--strict"))

    def test_same_status_transition_updates_in_place(self) -> None:
        item = self.new_item("research-handoff")
        self.ok("transition", item, "draft", "--owner", "researcher", "--next", "Investigate API limits")
        self.ok("transition", item, "draft", "--owner", "planner", "--next", "Update brief with API limits")
        fm = _lib.read_fm(_lib.find_item(self.repo, item).handoff)
        self.assertEqual((fm["status"], fm["owner_role"]), ("draft", "planner"))
        self.ok("check", "--strict")

    def test_sweep_archives_old_done_items(self) -> None:
        item = self.new_item("ancient", "--light")
        self.ok("transition", item, "planned", "--next", "g", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "g", "--by", "builder")
        self.ok("transition", item, "in-review", "--next", "g", "--evidence", "e", "--by", "builder")
        self.ok("transition", item, "verified", "--next", "g", "--by", "reviewer")
        self.ok("transition", item, "done", "--by", "scribe")
        f = self.repo / "work" / "items" / f"{item}.md"
        f.write_text(_lib.set_fm_value(f.read_text(), "updated", "2020-01-01"))
        self.ok("archive_item", "--sweep")
        self.assertFalse(f.exists())


    def test_update_next_step_owner_and_evidence_without_moving_status(self) -> None:
        item = self.new_item("handoff-only")
        handoff = _lib.find_item(self.repo, item).handoff
        self.ok("transition", item, "--next", "Planner: write brief.md", "--owner", "planner")
        fm = _lib.read_fm(handoff)
        self.assertEqual((fm["status"], fm["owner_role"], fm["next_action"]), ("draft", "planner", "Planner: write brief.md"))
        self.ok("transition", item, "--evidence", "python3 tools/check.py")
        self.ok("transition", item, "--evidence", "second proof")
        self.assertEqual(_lib.read_fm(handoff)["evidence"], ["python3 tools/check.py", "second proof"])
        self.assertEqual(_lib.read_fm(handoff)["status"], "draft")
        self.assertIn(item, (self.repo / "work" / "ACTIVE.md").read_text())
        self.ok("check")

    def test_in_place_update_guard_rails(self) -> None:
        item = self.new_item("guarded")
        self.assertIn("nothing to change", self.fails("transition", item))
        self.assertIn("unknown role", self.fails("transition", item, "--next", "x", "--owner", "wizard"))
        quick = self.new_item("quick-one", "--light")
        self.ok("transition", quick, "planned", "--next", "go", "--by", "planner")
        self.ok("transition", quick, "in-progress", "--next", "going", "--by", "builder")
        self.ok("transition", quick, "in-review", "--next", "look", "--evidence", "ran it", "--by", "builder")
        self.ok("transition", quick, "verified", "--next", "close", "--evidence", "checked", "--by", "reviewer")
        self.ok("transition", quick, "done", "--by", "scribe")
        self.assertIn("final", self.fails("transition", quick, "--next", "too late"))

    def test_light_item_can_be_handed_straight_to_another_role(self) -> None:
        item = self.new_item("update-vision", "--light", "--status", "planned", "--owner", "planner")
        fm = _lib.read_fm(_lib.find_item(self.repo, item).handoff)
        self.assertEqual((fm["status"], fm["owner_role"]), ("planned", "planner"))
        self.ok("check")


class WorktreeTests(RepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "init"], check=True)

    def test_worktree_create_list_and_remove(self) -> None:
        item = self.new_item("wt-feature", "--worktree")
        wt_path = self.repo.parent / f"{self.repo.name}-{item}"
        self.assertTrue(wt_path.is_dir())
        self.assertTrue((wt_path / "work" / "items" / item / "handoff.md").is_file())
        self.assertFalse((self.repo / "work" / "items" / item).exists())
        self.assertIn(str(wt_path), self.ok("worktree", "list"))
        # Refuses to remove while still in draft without --force
        self.assertIn("only verified, done or canceled", self.fails("worktree", "remove", item))
        self.ok("worktree", "remove", item, "--force")
        self.assertFalse(wt_path.exists())
        self.assertEqual(subprocess.run(
            ["git", "-C", str(self.repo), "branch", "--list", f"item/{item}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip(), "")

    def test_worktree_remove_finds_custom_path(self) -> None:
        item = self.new_item("custom-path")
        custom = self.repo.parent / f"custom-{item}"
        self.ok("worktree", "create", item, "--path", str(custom))
        self.assertTrue(custom.is_dir())
        self.ok("worktree", "remove", item, "--force")
        self.assertFalse(custom.exists())

    def test_worktree_remove_keeps_unmerged_branch(self) -> None:
        item = self.new_item("unmerged")
        wt_path = self.ok("worktree", "create", item)
        (Path(wt_path) / "scratch.txt").write_text("work\n", encoding="utf-8")
        sh = ["git", "-C", wt_path]
        subprocess.run(sh + ["-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], check=True)
        subprocess.run(sh + ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "work"], check=True)
        out = self.ok("worktree", "remove", item, "--force")
        self.assertIn("kept because it is not merged", out)
        self.assertTrue(subprocess.run(
            ["git", "-C", str(self.repo), "branch", "--list", f"item/{item}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip())

    def test_worktree_refuses_path_inside_repo_root(self) -> None:
        item = self.new_item("inside-root")
        self.assertIn("outside the repository root",
                      self.fails("worktree", "create", item, "--path", str(self.repo / "sub")))

    def _other_repo(self, name: str) -> Path:
        """A second git repo in the same folder as the clone, like another project in a shared projects/ folder."""
        other = self.repo.parent / name
        other.mkdir()
        subprocess.run(["git", "-C", str(other), "init", "-q"], check=True)
        return other

    def test_worktree_create_warns_when_the_parent_folder_holds_other_repos(self) -> None:
        self._other_repo("other-project")
        item = self.new_item("crowded")
        res = self.sh("worktree", "create", item)
        self.assertEqual(res.returncode, 0, res.stderr)  # a warning, never a refusal
        wt_path = Path(res.stdout.strip())
        self.assertTrue(wt_path.is_dir())  # the worktree is still created, and stdout is still just the path
        self.assertEqual(wt_path.name, f"{self.repo.name}-{item}")
        self.assertIn("1 other git repo,", res.stderr)
        self.assertIn(f"({self.repo.name}/{self.repo.name})", res.stderr)  # the fix it names
        self.assertIn("Tell the owner", res.stderr)  # the reader is usually an agent: it reports, it does not act
        self.assertIn("do not move the clone yourself", res.stderr)
        self.assertEqual(len(res.stderr.strip().splitlines()), 1)  # one line, as the other tools print

    def test_worktree_warning_counts_every_other_repo(self) -> None:
        self._other_repo("one")
        self._other_repo("two")
        item = self.new_item("two-others")
        self.assertIn("2 other git repos,", self.sh("worktree", "create", item).stderr)

    def test_worktree_create_is_silent_when_nothing_else_shares_the_folder(self) -> None:
        (self.repo.parent / "notes").mkdir()  # a plain folder and a plain file are not repos
        (self.repo.parent / "todo.txt").write_text("x\n", encoding="utf-8")
        item = self.new_item("alone")
        res = self.sh("worktree", "create", item)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stderr, "")

    def test_worktree_warning_ignores_this_repos_own_worktrees(self) -> None:
        first = self.new_item("first-wt")
        second = self.new_item("second-wt")
        self.assertEqual(self.sh("worktree", "create", first).stderr, "")
        # the first worktree now sits beside the clone and has a .git of its own; it is not another project
        self.assertEqual(self.sh("worktree", "create", second).stderr, "")

    def test_worktree_warning_stops_once_the_clone_has_a_worktree(self) -> None:
        self._other_repo("other-project")
        first = self.new_item("first-in-crowd")
        second = self.new_item("second-in-crowd")
        # no worktree yet: moving the clone into its own folder is still a plain mv, so say so
        self.assertIn("1 other git repo,", self.sh("worktree", "create", first).stderr)
        # a worktree exists now: moving the clone would break it, so the advice would be wrong
        res = self.sh("worktree", "create", second)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stderr, "")

    def test_worktree_warning_is_skipped_for_an_explicit_path(self) -> None:
        self._other_repo("other-project")
        item = self.new_item("chosen-path")
        res = self.sh("worktree", "create", item, "--path", str(self.repo.parent / "mine"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stderr, "")  # the person chose the location

    def test_new_item_worktree_warns_in_a_crowded_folder_too(self) -> None:
        self._other_repo("other-project")
        res = self.sh("new_item", "via-new-item", "--worktree")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("1 other git repo,", res.stderr)


class ConditionalScribeTests(RepoTestCase):
    """The scribe runs only when docs or the changelog must change. No tool changes: the reviewer routes with the
    existing `--owner` override, and the charters carry the rule."""

    def test_docs_free_item_goes_from_review_to_done_without_the_scribe(self) -> None:
        item = self.new_item("rename-variable")
        self.ok("transition", item, "planned", "--next", "builder: rename it", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "building", "--by", "builder")
        self.ok("transition", item, "in-review", "--next", "verify", "--evidence", "python3 tools/check.py", "--by", "builder")
        self.ok("item_file", item, "review")
        out = self.ok(
            "transition", item, "verified", "--by", "reviewer", "--owner", "orchestrator",
            "--evidence", "python3 tools/check.py", "--next", "Orchestrator: mark done; no docs or changelog change",
        )
        self.assertIn("owner: orchestrator", out)
        self.ok("transition", item, "done", "--by", "orchestrator")
        self.ok("check")
        self.ok("archive_item", item)
        self.ok("check")

    def test_the_default_owner_after_verified_stays_the_scribe(self) -> None:
        """The skip is a choice the reviewer makes with --owner; the default path is unchanged."""
        self.assertEqual(_lib.DEFAULT_OWNER["verified"], "scribe")
        item = self.new_item("add-json-flag")
        self.ok("transition", item, "planned", "--next", "builder: add it", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "building", "--by", "builder")
        self.ok("transition", item, "in-review", "--next", "verify", "--evidence", "python3 tools/check.py", "--by", "builder")
        self.ok("item_file", item, "review")
        out = self.ok("transition", item, "verified", "--by", "reviewer", "--evidence", "python3 tools/check.py",
                      "--next", "update docs and changelog")
        self.assertIn("owner: scribe", out)

    def test_light_item_can_skip_the_scribe_when_its_line_says_none(self) -> None:
        item = self.new_item("quick-rename", "--light")
        path = self.repo / "work" / "items" / f"{item}.md"
        text = path.read_text(encoding="utf-8")
        placeholder = "Docs for the scribe: _none, behavior unchanged, or the docs to update and the CHANGELOG.md line._"
        self.assertIn(placeholder, text)
        text = text.replace(placeholder, "Docs for the scribe: none, behavior unchanged.")
        review_placeholder = "_Reviewer's verdict and evidence go here (a light item has no separate review.md)._"
        self.assertIn(review_placeholder, text)
        text = text.replace(review_placeholder, "approve: criterion 1 passes; ran `python3 tools/check.py`.")
        path.write_text(text, encoding="utf-8")
        self.ok("transition", item, "planned", "--next", "builder: rename it", "--by", "planner")
        self.ok("transition", item, "in-progress", "--next", "building", "--by", "builder")
        self.ok("transition", item, "in-review", "--next", "verify", "--evidence", "python3 tools/check.py", "--by", "builder")
        out = self.ok(
            "transition", item, "verified", "--by", "reviewer", "--owner", "orchestrator",
            "--evidence", "python3 tools/check.py", "--next", "Orchestrator: mark done; no docs or changelog change",
        )
        self.assertIn("owner: orchestrator", out)
        self.ok("transition", item, "done", "--by", "orchestrator")
        self.ok("check")

    def test_charters_and_protocols_agree_on_the_docs_line_and_the_reviewer_charter_owns_the_routing(self) -> None:
        def read(rel: str) -> str:
            return (self.repo / rel).read_text(encoding="utf-8")

        line = "Docs for the scribe:"
        for rel in (
            "agents/roles/builder/ROLE.md", "agents/roles/reviewer/ROLE.md", "agents/roles/scribe/ROLE.md",
            "agents/roles/orchestrator/ROLE.md",
            "agents/protocols/handoff.md", "agents/protocols/definition-of-done.md", "agents/protocols/review.md",
            "agents/README.md", "work/_templates/review.md", "work/_templates/light-item.md",
            "docs/dev/tutorials/first-work-item.md",
        ):
            self.assertIn(line, read(rel), rel)
        # the reviewer's charter owns the routing: skip with --owner, and a missing line means the scribe
        charter = read("agents/roles/reviewer/ROLE.md")
        self.assertIn("--owner orchestrator", charter)
        self.assertIn("the scribe runs", charter)
        self.assertIn("--owner security", charter)
        # its skill is the method only: no command that moves the item, so nothing is said twice, and it says where
        # the routing is
        skill = read("agents/skills/review-work/SKILL.md")
        self.assertNotIn("transition.py", skill)
        self.assertIn("ROLE.md", skill)
        self.assertIn("review-work", charter)
        self.assertIn("done --by orchestrator", read("agents/roles/orchestrator/ROLE.md"))
        row = next(r for r in read("agents/README.md").splitlines() if r.startswith("| `verified`"))
        self.assertIn("scribe", row)
        # the row must name the override itself: "hand to orchestrator" was already in it before this change
        self.assertIn("--owner orchestrator", row)
        self.assertIn("and the diff agrees", row)
        # the scribe's fallback and the review template must say the same thing as the charters
        self.assertIn("when it needs none", read("agents/roles/scribe/ROLE.md"))
        self.assertIn("skip this step", read("agents/roles/scribe/ROLE.md"))
        self.assertNotIn("docs updated", read("agents/protocols/review.md"))
        self.assertIn("unless this review routes", read("work/_templates/review.md"))
        # a light item carries the line too, and the roles know it
        self.assertIn("## Docs for the scribe", read("work/_templates/light-item.md"))
        for rel in (
            "agents/protocols/handoff.md", "agents/roles/builder/ROLE.md", "agents/roles/reviewer/ROLE.md",
            "agents/roles/scribe/ROLE.md", "agents/roles/orchestrator/ROLE.md",
        ):
            self.assertIn("light item", read(rel), rel)


class QueueTests(RepoTestCase):
    ASK = ["ask", "Delete old backups?", "--asked-by", "orchestrator", "--recommended", "keep them",
           "--if-no-answer", "keep them", "--cost", "high: data loss"]

    def test_ask_answer_list_round_trip(self) -> None:
        self.assertEqual(self.ok("question", *self.ASK), "Q-0001")
        self.assertEqual(self.ok("question", *self.ASK[:1], "Second?", *self.ASK[2:]), "Q-0002")
        self.assertIn("Q-0001", self.ok("question", "list"))
        self.ok("check")
        self.ok("question", "answer", "Q-0001", "keep them")
        listing = self.ok("question", "list")
        self.assertNotIn("Q-0001", listing)
        self.assertIn("Q-0002", listing)
        text = (self.repo / "work" / "HUMAN.md").read_text()
        self.assertIn("- answer: keep them", text)
        self.assertLess(text.index("## Open"), text.index("### Q-0002"))
        self.assertLess(text.index("## Answered"), text.index("### Q-0001"))
        self.ok("check")

    def test_answering_everything_restores_empty_marker(self) -> None:
        self.ok("question", *self.ASK)
        self.ok("question", "answer", "Q-0001", "yes")
        self.assertIn("_None._", (self.repo / "work" / "HUMAN.md").read_text())
        self.assertEqual(self.ok("question", "list"), "no open questions")

    def test_asked_by_must_be_a_known_role(self) -> None:
        args = [a if a != "orchestrator" else "wizard" for a in self.ASK]
        self.assertIn("unknown role", self.fails("question", *args))

    def test_clone_is_isolated_from_project_data(self) -> None:
        self.assertEqual(self.ok("question", "list"), "no open questions")
        self.assertEqual([p.name for p in (self.repo / "work" / "items").iterdir()], ["README.md"])

    def test_ask_requires_recommendation_default_and_cost(self) -> None:
        self.fails("question", "ask", "Title", "--asked-by", "builder")

    def test_answering_unknown_question_fails(self) -> None:
        self.assertIn("not an open question", self.fails("question", "answer", "Q-0099", "x"))

    OLD_ADVICE = "apply its if_no_answer default or re-ask"

    def age_question(self, qid: str, days: int) -> None:
        """Rewrite the `- date:` line of one open question to `days` days ago. The tools read the real clock."""
        path = self.repo / "work" / "HUMAN.md"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        start = next(i for i, line in enumerate(lines) if line.startswith(f"### {qid}:"))
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("#"):
                break
            if lines[i].startswith("- date:"):
                lines[i] = f"- date: {(_lib.today() - timedelta(days=days)).isoformat()}\n"
                path.write_text("".join(lines), encoding="utf-8")
                return
        raise AssertionError(f"{qid} has no date line")

    def test_question_waiting_exactly_seven_days_is_not_flagged(self) -> None:
        self.ok("question", *self.ASK)
        self.age_question("Q-0001", 7)
        self.assertNotIn("human-queue", self.ok("check", "--strict"))

    def test_question_waiting_eight_days_warns_and_strict_fails(self) -> None:
        self.ok("question", *self.ASK)
        self.age_question("Q-0001", 8)
        out = self.ok("check")  # a warning alone does not fail the plain check
        self.assertIn("human-queue", out)
        self.assertIn("Q-0001 has waited 8 days", out)
        self.assertIn("only if the question may default", out)
        self.assertIn("stays open", out)
        self.assertNotIn(self.OLD_ADVICE, out)
        self.assertIn("human-queue", self.fails("check", "--strict"))

    def test_warning_never_tells_an_agent_to_default_a_question_that_must_stay_open(self) -> None:
        args = list(self.ASK)
        args[args.index("--if-no-answer") + 1] = "that part is not done"
        self.ok("question", *args)
        self.age_question("Q-0001", 8)
        before = (self.repo / "work" / "HUMAN.md").read_text(encoding="utf-8")
        out = self.ok("check")
        self.assertIn("only if the question may default", out)
        self.assertNotIn(self.OLD_ADVICE, out)
        self.assertEqual((self.repo / "work" / "HUMAN.md").read_text(encoding="utf-8"), before)  # checks only warn
        self.assertIn("Q-0001", self.ok("question", "list"))

    def test_answering_a_late_question_clears_the_warning(self) -> None:
        self.ok("question", *self.ASK)
        self.age_question("Q-0001", 8)
        self.fails("check", "--strict")
        self.ok("question", "answer", "Q-0001", "keep them")
        self.assertNotIn("human-queue", self.ok("check", "--strict"))


class AdrTests(RepoTestCase):
    def test_numbers_increase_and_supersede_links_both_ways(self) -> None:
        first = self.ok("new_adr", "Use PostgreSQL")
        n1 = Path(first).name[:4]
        second = self.ok("new_adr", "Switch to SQLite", "--supersedes", n1, "--status", "accepted")
        n2 = Path(second).name[:4]
        third = self.ok("new_adr", "Switch to DuckDB", "--supersedes", f"ADR-{int(n2)}", "--status", "accepted")
        n3 = Path(third).name[:4]
        self.assertEqual(int(n2), int(n1) + 1)
        self.assertEqual(int(n3), int(n2) + 1)
        self.assertEqual(_lib.read_fm(self.repo / first)["status"], "superseded")
        self.assertEqual(str(_lib.read_fm(self.repo / first)["superseded_by"]).zfill(4), n2)
        self.assertEqual(_lib.read_fm(self.repo / second)["supersedes"], [n1])
        self.assertEqual(_lib.read_fm(self.repo / third)["supersedes"], [n2])
        self.ok("check", "--strict")

    def test_supersedes_rejects_garbage_instead_of_guessing(self) -> None:
        self.ok("new_adr", "Use PostgreSQL")
        before = sorted(p.name for p in (self.repo / "docs" / "decisions").glob("0*.md"))
        for bad in ("abc5xyz", "ADR-3-and-4", "12345", "3x"):
            self.assertIn("invalid ADR number", self.fails("new_adr", "Switch", "--supersedes", bad))
        self.assertEqual(before, sorted(p.name for p in (self.repo / "docs" / "decisions").glob("0*.md")))

    def test_parallel_agents_never_get_the_same_number(self) -> None:
        procs = [subprocess.Popen(
            [sys.executable, str(self.repo / "tools" / "new_adr.py"), f"Parallel decision {i}"],
            cwd=self.repo, env={**os.environ, "REPO_ROOT": str(self.repo)},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(8)]
        outs = [p.communicate(timeout=120) for p in procs]
        self.assertTrue(all(p.returncode == 0 for p in procs), outs)
        numbers = [Path(o[0].strip()).name[:4] for o in outs]
        self.assertEqual(len(set(numbers)), 8, numbers)
        self.ok("check")

    def test_duplicate_numbers_are_caught(self) -> None:
        d = self.repo / "docs" / "decisions"
        first = self.ok("new_adr", "First decision")
        second = self.ok("new_adr", "Second decision")
        self.assertNotEqual(Path(first).name[:4], Path(second).name[:4])
        shutil.copy(self.repo / second, d / f"{Path(second).name[:4]}-duplicate.md")
        self.assertIn("adr-number", self.fails("check"))


class DocTests(RepoTestCase):
    def test_new_doc_creates_valid_doc_and_updates_index(self) -> None:
        path = self.ok("new_doc", "how-to", "Deploy: to staging", "--summary", "How to deploy to staging.")
        self.assertEqual(path, "docs/dev/how-to/deploy-to-staging.md")
        self.assertIn("deploy-to-staging.md", (self.repo / "docs" / "INDEX.md").read_text())
        self.ok("check")
        self.fails("new_doc", "how-to", "Deploy: to staging")  # exists
        self.fails("new_doc", "poem", "Nope")

    # --- audience layout: docs/<dev|user>/<type>/, decisions shared, optional `audience:` key ---
    def _doc(self, rel: str, doc_type: str, title: str, extra: str = "") -> Path:
        p = self.repo / "docs" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\ntitle: {title}\ntype: {doc_type}\nstatus: active\nsummary: {title} summary.\n{extra}---\n# {title}\n",
                     encoding="utf-8")
        return p

    def _index_section(self, heading: str) -> str:
        """Text of one `## ` section of docs/INDEX.md (up to the next `## `)."""
        text = (self.repo / "docs" / "INDEX.md").read_text(encoding="utf-8")
        parts = text.split("\n## ")
        for part in parts[1:]:
            if part.startswith(heading):
                return part
        self.fail(f"no '## {heading}' section in docs/INDEX.md")

    def test_shipped_layout_has_dev_user_and_shared_decisions(self) -> None:
        docs = self.repo / "docs"
        for folder in ("tutorials", "how-to", "reference", "explanation"):
            self.assertTrue((docs / "dev" / folder).is_dir(), folder)
            self.assertFalse((docs / folder).exists(), f"docs/{folder}/ must not exist at the top level")
        self.assertTrue((docs / "user" / "README.md").exists())
        self.assertTrue((docs / "decisions").is_dir())
        self.assertIn("No documents yet", self._index_section("End users"))

    def test_new_doc_for_users_goes_to_docs_user_and_the_user_section(self) -> None:
        path = self.ok("new_doc", "how-to", "Reset your password", "--audience", "user", "--summary", "How to reset a password.")
        self.assertEqual(path, "docs/user/how-to/reset-your-password.md")
        self.assertIn("reset-your-password.md", self._index_section("End users"))
        self.assertNotIn("reset-your-password.md", self._index_section("Contributors"))
        self.ok("check")

    def test_new_doc_audience_rules(self) -> None:
        self.assertIn("unknown audience", self.fails("new_doc", "how-to", "X", "--audience", "alien"))
        modules = _lib.load_modules(self.repo)
        if "operations" in modules:
            self.assertIn("--audience applies", self.fails("new_doc", "runbook", "Restart", "--audience", "user"))
            self.assertEqual(self.ok("new_doc", "runbook", "Restart the queue"), "docs/operations/runbooks/restart-the-queue.md")

    def test_type_folder_directly_under_docs_is_a_layout_error(self) -> None:
        self._doc("how-to/old-spot.md", "how-to", "Old spot")
        out = self.fails("check")
        self.assertIn("docs-layout", out)
        self.assertIn("docs/dev/how-to/", out)

    def test_type_must_match_folder_under_an_audience(self) -> None:
        self._doc("user/reference/wrong.md", "how-to", "Wrong type")
        self.assertIn("diataxis", self.fails("check"))

    def test_audience_key_regroups_the_index_without_moving_the_file(self) -> None:
        self._doc("dev/how-to/for-users.md", "how-to", "For users", "audience: user\n")
        self.ok("sync_indexes")
        self.assertIn("dev/how-to/for-users.md", self._index_section("End users"))
        self.assertNotIn("for-users.md", self._index_section("Contributors"))
        self.ok("check")

    def test_unknown_audience_value_is_an_error(self) -> None:
        self._doc("dev/how-to/bad-audience.md", "how-to", "Bad audience", "audience: wizards\n")
        self.assertIn("doc-audience", self.fails("check"))

    def test_a_big_folder_gets_its_own_index_and_loses_it_when_small_again(self) -> None:
        import sync_indexes
        for i in range(sync_indexes.SPLIT_THRESHOLD + 1):
            self._doc(f"dev/how-to/bulk-{i:03d}.md", "how-to", f"Bulk {i:03d}")
        self.ok("sync_indexes")
        sub = self.repo / "docs" / "dev" / "how-to" / "INDEX.md"
        self.assertTrue(sub.exists(), "a folder over the threshold needs its own index")
        self.assertIn("see the section index", self._index_section("Contributors"))
        self.assertIn("bulk-000.md", sub.read_text(encoding="utf-8"))
        self.ok("check")
        for p in (self.repo / "docs" / "dev" / "how-to").glob("bulk-*.md"):
            p.unlink()
        self.ok("sync_indexes")
        self.assertFalse(sub.exists(), "the orphan section index must be removed")
        self.ok("check")


class ModuleTests(RepoTestCase):
    def test_every_installed_module_can_be_cut_cleanly(self) -> None:
        modules = _lib.load_modules(self.repo)
        if not modules:
            self.skipTest("no modules installed (lean profile)")
        for name, mod in modules.items():
            with self.subTest(module=name):
                with tempfile.TemporaryDirectory() as tmp:
                    repo = clone(Path(tmp))
                    preview = run(repo, "remove_module", name)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    self.assertIn("dry run", preview.stdout)
                    self.assertTrue(all((repo / p).exists() for p in mod["paths"]), "dry run must not delete")
                    res = run(repo, "remove_module", name, "--apply")
                    self.assertEqual(res.returncode, 0, f"cutting {name} left problems:\n{res.stdout}\n{res.stderr}")
                    self.assertFalse(any((repo / p).exists() for p in mod["paths"]))
                    self.assertNotIn(name, _lib.load_modules(repo))
                    again = run(repo, "check", "--strict")
                    self.assertEqual(again.returncode, 0, again.stdout)

    def test_cutting_security_removes_the_role_and_its_flat_skill(self) -> None:
        if "security" not in _lib.load_modules(self.repo):
            self.skipTest("security module not installed")
        preview = self.ok("remove_module", "security")
        self.assertIn("agents/roles/security", preview)
        self.assertIn("agents/skills/review-security", preview)
        self.ok("remove_module", "security", "--apply")
        self.assertFalse((self.repo / "agents" / "roles" / "security").exists())
        self.assertFalse((self.repo / "agents" / "skills" / "review-security").exists())
        self.assertFalse((self.repo / ".claude" / "agents" / "security.md").exists())
        self.assertFalse((self.repo / ".claude" / "skills" / "review-security").exists())
        self.ok("check", "--strict")

    def test_cutting_every_module_in_turn_leaves_a_healthy_lean_repo(self) -> None:
        modules = list(_lib.load_modules(self.repo))
        for name in modules:
            res = self.sh("remove_module", name, "--apply")
            self.assertEqual(res.returncode, 0, f"{name}:\n{res.stdout}\n{res.stderr}")
        self.assertEqual(_lib.load_modules(self.repo), {})
        self.ok("check", "--strict")

    def test_cut_records_choice_in_copier_answers(self) -> None:
        if "evals" not in _lib.load_modules(self.repo):
            self.skipTest("evals module not installed")
        answers = self.repo / ".copier-answers.yml"
        answers.write_text("_commit: v0\n_src_path: x\nlayout: single\nprofile: full\nproject_name: P\n")
        self.ok("remove_module", "evals", "--apply")
        text = answers.read_text()
        self.assertIn("profile: custom", text)
        self.assertNotIn("profile: full", text)
        self.assertIn("custom_modules:", text)
        self.assertNotIn("- evals", text)
        self.assertIn("- github", text)

    def test_unknown_module_is_rejected(self) -> None:
        self.assertIn("unknown module", self.fails("remove_module", "nope"))


class AdapterTests(RepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        # Every test starts from "Cursor, Copilot and Gemini off", whatever this project has enabled.
        self.enable(cursor=False, copilot=False, gemini=False)
        shutil.rmtree(self.repo / ".cursor", ignore_errors=True)
        shutil.rmtree(self.repo / ".gemini", ignore_errors=True)
        (self.repo / ".github" / "copilot-instructions.md").unlink(missing_ok=True)
        self.ok("sync_agents")
        self.ok("sync_indexes")

    def test_adapters_are_generated_and_removed_with_their_source(self) -> None:
        targets = _lib.load_targets(self.repo)
        if not targets.get("claude", {}).get("enabled"):
            self.skipTest("claude adapter disabled")
        agent = self.repo / ".claude" / "agents" / "builder.md"
        self.assertTrue(agent.is_file())
        self.assertTrue((self.repo / "CLAUDE.md").read_text().strip() == "@AGENTS.md")
        self.assertIn("name: builder", agent.read_text())
        # A skill from the flat lane lands in .claude/skills/.
        self.assertTrue((self.repo / ".claude" / "skills" / "review-work" / "SKILL.md").is_file())
        self.set_skills("reviewer", [])
        self.ok("sync_indexes")
        shutil.rmtree(self.repo / "agents" / "skills" / "review-work")
        self.ok("sync_agents")
        self.assertFalse((self.repo / ".claude" / "skills" / "review-work").exists())
        self.ok("sync_indexes")
        self.ok("check")

    def test_sync_refuses_to_overwrite_a_hand_written_file(self) -> None:
        targets = _lib.load_targets(self.repo)
        if not targets.get("claude", {}).get("enabled"):
            self.skipTest("claude adapter disabled")
        (self.repo / "agents" / "skills" / "review-work" / "extra.md").write_text("x\n")
        (self.repo / ".claude" / "skills" / "review-work" / "extra.md").write_text("mine\n")
        r = self.sh("sync_agents")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.repo / ".claude" / "skills" / "review-work" / "extra.md").read_text(), "mine\n")

    def test_disabling_the_adapter_removes_generated_files(self) -> None:
        t = self.repo / "agents" / "adapters" / "targets.json"
        data = json.loads(t.read_text())
        if not data.get("claude", {}).get("enabled"):
            self.skipTest("claude adapter already disabled")
        data["claude"]["enabled"] = False
        t.write_text(json.dumps(data))
        self.ok("sync_agents")
        self.assertFalse((self.repo / ".claude").exists())
        self.assertFalse((self.repo / "CLAUDE.md").exists())
        self.ok("check")

    def enable(self, **targets: bool) -> None:
        t = self.repo / "agents" / "adapters" / "targets.json"
        data = json.loads(t.read_text())
        for name, on in targets.items():
            data.setdefault(name, {})["enabled"] = on
        t.write_text(json.dumps(data))

    def test_cursor_adapter_writes_role_rules_and_a_short_pointer(self) -> None:
        self.enable(cursor=True)
        self.ok("sync_agents")
        rules = self.repo / ".cursor" / "rules"
        pointer = (rules / "00-repo.mdc").read_text()
        self.assertIn("alwaysApply: true", pointer)
        self.assertIn("`AGENTS.md`", pointer)
        self.assertLess(len(pointer), 600, "the pointer must not copy AGENTS.md (the tool loads that file itself)")
        role = (rules / "role-builder.mdc").read_text()
        self.assertTrue(role.startswith("---\ndescription:"))
        self.assertIn("alwaysApply: false", role)
        self.assertIn("You are the **builder** role", role)
        self.ok("check", "--strict")
        self.ok("sync_agents", "--check")
        charter = self.repo / "agents" / "roles" / "builder" / "ROLE.md"
        charter.write_text(charter.read_text().rstrip() + "\n\nExtra rule.\n")
        self.assertIn("role-builder.mdc", self.fails("sync_agents", "--check"))
        self.ok("sync_agents")
        self.assertIn("Extra rule.", (rules / "role-builder.mdc").read_text())

    def test_claude_and_cursor_share_one_role_text(self) -> None:
        if not _lib.load_targets(self.repo).get("claude", {}).get("enabled"):
            self.skipTest("claude adapter disabled")
        self.enable(cursor=True)
        self.ok("sync_agents")
        claude = (self.repo / ".claude" / "agents" / "builder.md").read_text().split("---\n", 2)[2]
        cursor = (self.repo / ".cursor" / "rules" / "role-builder.mdc").read_text().split("---\n", 2)[2]
        self.assertEqual(claude, cursor)

    def test_copilot_adapter_writes_a_pointer_that_check_accepts(self) -> None:
        self.enable(copilot=True)
        self.ok("sync_agents")
        text = (self.repo / ".github" / "copilot-instructions.md").read_text()
        self.assertIn("`AGENTS.md`", text)
        self.assertNotIn("python3 tools/", text)
        self.ok("check", "--strict")
        self.ok("sync_agents", "--check")

    def test_gemini_adapter_writes_settings_that_check_accepts(self) -> None:
        self.enable(gemini=True)
        self.ok("sync_agents")
        cfg = json.loads((self.repo / ".gemini" / "settings.json").read_text())
        self.assertEqual(cfg["context"]["fileName"], ["AGENTS.md", "GEMINI.md"])
        self.ok("check", "--strict")
        self.ok("sync_agents", "--check")
        self.enable(gemini=False)
        self.ok("sync_agents")
        self.assertFalse((self.repo / ".gemini").exists())
        self.ok("check", "--strict")

    def test_copilot_adapter_does_not_turn_the_github_module_on(self) -> None:
        if "github" in _lib.load_modules(self.repo):
            self.ok("remove_module", "github", "--apply")
        self.enable(copilot=True)
        self.ok("sync_agents")
        self.assertTrue((self.repo / ".github" / "copilot-instructions.md").is_file())
        self.assertNotIn("github", _lib.load_modules(self.repo))
        self.ok("sync_indexes", "--check")
        self.assertNotIn("`.github/`", (self.repo / "docs" / "dev" / "reference" / "repo-map.md").read_text())
        self.ok("check", "--strict")

    def test_cutting_the_github_module_keeps_the_copilot_pointer(self) -> None:
        if "github" not in _lib.load_modules(self.repo):
            self.skipTest("github module not installed")
        self.enable(copilot=True)
        self.ok("sync_agents")
        self.ok("sync_indexes")
        self.ok("remove_module", "github", "--apply")
        self.assertTrue((self.repo / ".github" / "copilot-instructions.md").is_file())
        self.assertFalse((self.repo / ".github" / "workflows").exists())
        self.assertNotIn("github", _lib.load_modules(self.repo))
        self.ok("sync_agents", "--check")
        self.ok("sync_indexes", "--check")
        self.ok("check", "--strict")

    def test_disabling_cursor_and_copilot_removes_what_they_generated(self) -> None:
        self.enable(cursor=True, copilot=True)
        self.ok("sync_agents")
        self.enable(cursor=False, copilot=False)
        self.ok("sync_agents")
        self.assertFalse((self.repo / ".cursor").exists())
        self.assertFalse((self.repo / ".github" / "copilot-instructions.md").exists())
        self.ok("check", "--strict")

    def test_sync_never_overwrites_a_hand_written_copilot_file(self) -> None:
        mine = self.repo / ".github" / "copilot-instructions.md"
        mine.parent.mkdir(exist_ok=True)
        mine.write_text("my own instructions\n")
        self.enable(copilot=True)
        self.assertIn("SKIPPED", self.fails("sync_agents"))
        self.assertEqual(mine.read_text(), "my own instructions\n")

    def test_files_under_dot_cursor_are_not_checked_as_documentation(self) -> None:
        mine = self.repo / ".cursor" / "rules" / "mine.md"
        mine.parent.mkdir(parents=True)
        mine.write_text("# Mine\n\n[broken](does/not/exist.md)\n")
        self.ok("check", "--strict")

    # --- role `access` hint, `use_when` and per-role models -----------------------------------------
    GOOD_CLAUDE_EXTRAS = {"models": {}, "disallowed_tools": {"read-only": ["Edit", "NotebookEdit"]}}

    def set_claude(self, **cfg: object) -> None:
        t = self.repo / "agents" / "adapters" / "targets.json"
        data = json.loads(t.read_text())
        data.setdefault("claude", {})["enabled"] = True
        data["claude"].update(cfg)
        t.write_text(json.dumps(data))

    def add_charter_key(self, role: str, line: str) -> None:
        p = self.repo / "agents" / "roles" / role / "ROLE.md"
        p.write_text(p.read_text().replace("\nreads:", f"\n{line}\nreads:", 1))

    def head(self, path: Path) -> str:
        """The front matter block of a generated file."""
        return path.read_text().split("---\n", 2)[1]

    def claude_head(self, role: str) -> str:
        return self.head(self.repo / ".claude" / "agents" / f"{role}.md")

    def test_read_only_role_gets_a_disallowed_tools_line(self) -> None:
        self.set_claude()
        self.add_charter_key("builder", "access: read-only")
        self.ok("sync_agents")
        self.assertIn("disallowedTools: Edit, NotebookEdit\n", self.claude_head("builder"))
        self.assertNotIn("disallowedTools", self.claude_head("planner"))
        self.ok("sync_agents", "--check")
        self.ok("check", "--strict")

    def test_access_full_adds_no_restriction(self) -> None:
        self.set_claude()
        self.add_charter_key("builder", "access: full")
        self.ok("sync_agents")
        self.assertNotIn("disallowedTools", self.claude_head("builder"))
        self.ok("check", "--strict")

    def test_shipped_read_only_roles_get_the_tool_limit(self) -> None:
        # reviewer and researcher write only their own item file (and, for the researcher, work/research/).
        # security owns docs/security/ and updates threat-model.md in place, so it is not read-only.
        self.set_claude()
        self.ok("sync_agents")
        for role in ("reviewer", "researcher"):
            self.assertIn("disallowedTools: Edit, NotebookEdit\n", self.claude_head(role), role)
        for role in ("builder", "planner", "architect", "scribe", "orchestrator", "security"):
            if not (self.repo / "agents" / "roles" / role / "ROLE.md").exists():
                continue  # the security module may be cut
            self.assertNotIn("disallowedTools", self.claude_head(role), role)

    # --- a role's listed skills are preloaded into its Claude subagent (a subagent preloads only the skills it lists) ---
    def user_invoked(self, skill: str) -> bool:
        meta = _lib.read_skill_fm(self.repo / "agents" / "skills" / skill / "SKILL.md").get("metadata")
        return isinstance(meta, dict) and meta.get("invocation") == "user"

    def preloaded(self, role: str) -> list[str]:
        lines = self.claude_head(role).splitlines()
        if "skills:" not in lines:
            return []
        out: list[str] = []
        for line in lines[lines.index("skills:") + 1:]:
            if not line.startswith("  - "):
                break
            out.append(line[4:])
        return out

    def test_claude_subagent_preloads_the_roles_own_skills(self) -> None:
        # R6: a skill is preloaded for a role only when exactly one charter lists it and it is not
        # `metadata.invocation: user`; the generated list is in name order.
        self.set_claude()
        self.ok("sync_agents")
        roles = sorted(p.name for p in (self.repo / "agents" / "roles").iterdir() if p.is_dir())
        listings: dict[str, list[str]] = {}
        for role in roles:
            for skill in self.charter_skills(role):
                listings.setdefault(skill, []).append(role)
        expected = {
            role: sorted(s for s, owners in listings.items()
                         if owners == [role] and not self.user_invoked(s))
            for role in roles
        }
        actual = {role: self.preloaded(role) for role in roles}
        self.assertEqual(actual, expected)
        all_preloaded = {s for names in actual.values() for s in names}
        merge_meta = _lib.read_skill_fm(self.repo / "agents" / "skills" / "merge-work" / "SKILL.md").get("metadata")
        self.assertIsInstance(merge_meta, dict)
        self.assertEqual(merge_meta.get("invocation"), "user")
        self.assertNotIn("merge-work", all_preloaded, "merge-work is metadata.invocation: user")
        for skill, owners in listings.items():
            if len(owners) > 1:
                self.assertNotIn(skill, all_preloaded, f"{skill} is listed by several roles: {owners}")
        self.ok("sync_agents", "--check")
        self.ok("check", "--strict")

    def test_researcher_subagent_preloads_its_method(self) -> None:
        # the researcher's charter points to research-question; a subagent preloads only the skills it lists
        self.set_claude()
        self.ok("sync_agents")
        self.assertIn("skills:\n  - research-question\n", self.claude_head("researcher"))
        self.ok("sync_agents", "--check")
        self.ok("check", "--strict")

    def test_security_subagent_preloads_its_method(self) -> None:
        if "security" not in _lib.load_modules(self.repo):
            self.skipTest("security module not installed")
        self.set_claude()
        self.ok("sync_agents")
        self.assertIn("skills:\n  - review-security\n", self.claude_head("security"))
        self.ok("sync_agents", "--check")
        self.ok("check", "--strict")

    def test_a_skill_listed_by_two_roles_or_by_none_is_not_preloaded(self) -> None:
        # Preloading repeats the full text in every subagent that lists it, so one owner is the rule.
        # Pick a currently exclusive, non-user skill and make a second role list it; nothing here
        # depends on the P1 skill set, so P2's charters keep the test valid.
        self.set_claude()
        import sync_agents
        roles = sorted(p.name for p in (self.repo / "agents" / "roles").iterdir() if p.is_dir())
        listings: dict[str, list[str]] = {}
        for role in roles:
            for skill in self.charter_skills(role):
                listings.setdefault(skill, []).append(role)
        target, owner = next((s, owners[0]) for s, owners in sorted(listings.items())
                             if len(owners) == 1 and not self.user_invoked(s))
        other = next(role for role in roles if role != owner)
        self.set_skills(other, self.charter_skills(other) + [target])
        # A skill no charter lists is not preloaded either.
        folder = self.repo / "agents" / "skills" / "unlisted-extra"
        folder.mkdir()
        (folder / "SKILL.md").write_text(
            "---\nname: unlisted-extra\ndescription: A skill no charter lists. Use when testing preload exclusivity.\n"
            "---\n# Extra\n")
        self.ok("sync_indexes")
        self.ok("sync_agents")
        preload = sync_agents._preloadable_skills(self.repo)
        listed = {s for names in preload.values() for s in names}
        self.assertNotIn(target, listed, f"{target} is listed by both {owner} and {other}")
        self.assertNotIn("unlisted-extra", listed)
        out = self.fails("check", "--strict")
        self.assertIn("skill-unlisted", out)
        self.assertIn("unlisted-extra", out)

    def test_a_role_with_no_skill_gets_no_skills_line(self) -> None:
        self.set_claude()
        self.set_skills("reviewer", [])
        self.ok("sync_indexes")
        self.ok("sync_agents")
        self.assertNotIn("skills:", self.claude_head("reviewer"))

    def test_several_role_skills_are_listed_in_name_order(self) -> None:
        self.set_claude()
        folder = self.repo / "agents" / "skills" / "aaa-extra"
        folder.mkdir()
        (folder / "SKILL.md").write_text(
            "---\nname: aaa-extra\ndescription: Does a thing. Use when a test needs a second skill.\n---\n# Extra\n")
        self.set_skills("reviewer", ["review-work", "aaa-extra"])
        self.ok("sync_indexes")  # a new skill changes the generated roster
        self.ok("sync_agents")
        self.assertIn("skills:\n  - aaa-extra\n  - review-work\n", self.claude_head("reviewer"))
        self.ok("check", "--strict")

    def test_invocation_user_skill_is_not_preloaded_and_gets_the_claude_line(self) -> None:
        # Claude Code does not preload a user-invoked skill; its generated copy gets the adapter flag.
        self.set_claude()
        p = self.repo / "agents" / "skills" / "review-work" / "SKILL.md"
        p.write_text(p.read_text().replace("metadata:\n  requires: work-tracker\n", "metadata:\n  invocation: user\n  requires: work-tracker\n", 1))
        self.ok("sync_agents")
        self.assertNotIn("skills:", self.claude_head("reviewer"))
        generated = (self.repo / ".claude" / "skills" / "review-work" / "SKILL.md").read_text()
        head = generated.split("---\n", 2)[1]
        self.assertEqual(head.strip().splitlines()[-1], "disable-model-invocation: true")
        self.assertNotIn("disable-model-invocation", p.read_text())
        self.ok("check", "--strict")
        self.ok("sync_agents", "--check")

    def test_a_skill_with_broken_front_matter_does_not_crash_the_sync(self) -> None:
        self.set_claude()
        p = self.repo / "agents" / "skills" / "review-work" / "SKILL.md"
        p.write_text("---\nname: review-work\n  nested: [broken\n---\n# Review work\n")
        r = self.sh("sync_agents")
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertIn("skill", self.fails("check"))

    def test_skills_are_not_copied_to_cursor_rules(self) -> None:
        self.set_claude()
        self.enable(cursor=True)
        self.ok("sync_agents")
        rule = self.head(self.repo / ".cursor" / "rules" / "role-reviewer.mdc")
        self.assertNotIn("skills:", rule)

    def test_access_is_not_copied_to_cursor_rules(self) -> None:
        self.set_claude()
        self.enable(cursor=True)
        self.add_charter_key("builder", "access: read-only")
        self.ok("sync_agents")
        rule = self.head(self.repo / ".cursor" / "rules" / "role-builder.mdc")
        self.assertNotIn("disallowedTools", rule)
        self.assertNotIn("model:", rule)

    def test_unknown_access_value_is_reported_by_check_and_ignored_by_sync(self) -> None:
        self.set_claude()
        self.add_charter_key("builder", "access: read-write")
        r = self.sh("sync_agents")
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertNotIn("disallowedTools", self.claude_head("builder"))
        out = self.fails("check")
        self.assertIn("access", out)
        self.assertNotIn("Traceback", out)

    def test_models_map_writes_a_model_line_for_the_named_role_only(self) -> None:
        self.set_claude(models={"reviewer": "opus"})
        self.ok("sync_agents")
        self.assertIn("model: opus\n", self.claude_head("reviewer"))
        self.assertNotIn("model:", self.claude_head("builder"))
        self.ok("check", "--strict")
        self.set_claude(models={})
        self.assertIn("reviewer.md", self.fails("sync_agents", "--check"))
        self.ok("sync_agents")
        self.assertNotIn("model:", self.claude_head("reviewer"))

    def test_changing_the_tool_mapping_is_drift_until_synced(self) -> None:
        self.set_claude()
        self.add_charter_key("builder", "access: read-only")
        self.ok("sync_agents")
        self.set_claude(disallowed_tools={"read-only": ["Write"]})
        self.assertIn("builder.md", self.fails("sync_agents", "--check"))
        self.ok("sync_agents")
        self.assertIn("disallowedTools: Write\n", self.claude_head("builder"))
        self.ok("check", "--strict")

    def test_bad_adapter_extras_are_reported_without_crashing(self) -> None:
        for bad in (
            {"models": {"ghost": "opus"}},
            {"models": ["opus"]},
            {"models": {"reviewer": ""}},
            {"disallowed_tools": {"read-only": "Edit"}},
            {"disallowed_tools": {"read-only": ["Bash(git push *)"]}},
            {"disallowed_tools": {"read-write": ["Edit"]}},
        ):
            self.set_claude(**{**self.GOOD_CLAUDE_EXTRAS, **bad})
            out = self.fails("check")
            self.assertIn("adapters", out, bad)
            self.assertNotIn("Traceback", out, bad)
            r = self.sh("sync_agents")
            self.assertNotIn("Traceback", r.stdout + r.stderr, bad)

    def test_disallowed_tools_cannot_restrict_full(self) -> None:
        self.set_claude(disallowed_tools={"full": ["Edit"]})
        self.add_charter_key("builder", "access: full")
        out = self.fails("check")
        self.assertIn("full", out)
        self.assertNotIn("Traceback", out)
        self.ok("sync_agents")
        self.assertNotIn("disallowedTools", self.claude_head("builder"))

    def test_use_when_replaces_the_owner_role_sentence(self) -> None:
        self.set_claude()
        self.enable(cursor=True)
        self.add_charter_key("builder", "use_when: a planner asks for a second opinion")
        self.ok("sync_agents")
        for head in (self.claude_head("builder"), self.head(self.repo / ".cursor" / "rules" / "role-builder.mdc")):
            self.assertIn("Use when a planner asks for a second opinion.", head)
            self.assertNotIn("owner_role is builder", head)
        self.assertIn("handoff owner_role is planner", self.claude_head("planner"))

    def test_shipped_researcher_is_not_described_by_ownership(self) -> None:
        # The researcher never owns an item, so "owner_role is researcher" can never match.
        self.set_claude()
        self.ok("sync_agents")
        head = self.claude_head("researcher")
        self.assertIn("Use when", head)
        self.assertNotIn("owner_role is researcher", head)

    def test_empty_use_when_fails_check(self) -> None:
        self.add_charter_key("builder", "use_when:")
        out = self.fails("check")
        self.assertIn("use_when", out)
        self.assertNotIn("Traceback", out)


class TemplateStatusTests(RepoTestCase):
    """tools/template_status.py: is a newer template release available? No network is used: the 'remote' is a local git repo."""

    def setUp(self) -> None:
        super().setUp()
        import template_status
        self.ts = template_status
        self.upstream = Path(self._tmp.name) / "upstream"
        self.upstream.mkdir()
        self.git_in(self.upstream, "init", "-q")
        (self.upstream / "f.txt").write_text("x", encoding="utf-8")
        self.git_in(self.upstream, "add", "-A")
        self.git_in(self.upstream, "commit", "-qm", "c1")
        for tag in ("v0.1.0", "v0.2.0", "v0.10.0", "v1.0.0-rc1", "release-9", "v0.2"):
            self.git_in(self.upstream, "tag", tag)

    def git_in(self, cwd: Path, *args: str) -> None:
        r = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def answers(self, src: str, commit: str) -> None:
        (self.repo / ".copier-answers.yml").write_text(
            f"# Changes here will be overwritten by Copier\n_commit: {commit}\n_src_path: {src}\nproject_name: X\n", encoding="utf-8")

    def status(self, *args: str) -> subprocess.CompletedProcess:
        return run(self.repo, "template_status", *args)

    def test_parses_the_answers_file_and_ignores_comments_and_quotes(self) -> None:
        got = self.ts.parse_answers("# c\n_commit: 'v0.3.0'\n_src_path: \"gh:a/b\"\nname: A: B\nlist:\n  - x\n")
        self.assertEqual((got["_commit"], got["_src_path"], got["name"]), ("v0.3.0", "gh:a/b", "A: B"))

    def test_source_shorthands_become_urls_and_local_paths_have_none(self) -> None:
        url = self.ts.source_url
        self.assertEqual(url("gh:The-Urcydo/Role-Oriented-Agent-Template"), "https://github.com/The-Urcydo/Role-Oriented-Agent-Template.git")
        self.assertEqual(url("gh:The-Urcydo/Role-Oriented-Agent-Template.git"), "https://github.com/The-Urcydo/Role-Oriented-Agent-Template.git")
        self.assertEqual(url("gh:The-Urcydo/Role-Oriented-Agent-Template/"), "https://github.com/The-Urcydo/Role-Oriented-Agent-Template.git")
        self.assertEqual(url("gl:grp/proj"), "https://gitlab.com/grp/proj.git")
        self.assertEqual(url("gl:grp/proj.git"), "https://gitlab.com/grp/proj.git")
        self.assertEqual(url("https://github.com/a/b"), "https://github.com/a/b")
        self.assertEqual(url("git+https://example.com/a/b.git"), "https://example.com/a/b.git")
        self.assertEqual(url("git@github.com:a/b.git"), "git@github.com:a/b.git")
        for local in (".", "/srv/template", "../tpl", "~/tpl", "C:\\tpl"):
            self.assertIsNone(url(local), local)

    def test_only_plain_release_tags_count_and_they_compare_as_numbers(self) -> None:
        self.assertEqual(self.ts.latest_release(["v0.2.0", "v0.10.0", "v0.9.9", "v1.0.0-rc1", "v0.2", "x"]), "v0.10.0")
        self.assertIsNone(self.ts.latest_release(["v1.0.0-rc1", "nightly"]))
        self.assertEqual(self.ts.release_of("v0.3.0-39-ge31e9ee"), "v0.3.0")
        self.assertIsNone(self.ts.release_of("e31e9ee"))

    def test_behind_prints_the_fix_and_only_check_fails(self) -> None:
        self.answers("file://" + str(self.upstream), "v0.1.0")
        r = self.status()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("behind: v0.10.0 available", r.stdout)
        self.assertIn("v0.1.0", r.stdout)
        self.assertIn("copier update --trust", r.stdout)
        self.assertEqual(self.status("--check").returncode, 1)

    def test_up_to_date_including_a_build_ahead_of_its_tag(self) -> None:
        for commit in ("v0.10.0", "v0.10.0-4-gabc1234"):
            self.answers("file://" + str(self.upstream), commit)
            r = self.status("--check")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("up to date", r.stdout)

    def test_unreachable_local_unknown_and_missing_sources_never_fail(self) -> None:
        cases = {
            "unreachable": ("file:///definitely/not/here", "v0.1.0"),
            "local": (str(self.upstream), "v0.1.0"),
            "no release": ("file://" + str(self.upstream), "e31e9ee"),
        }
        for name, (src, commit) in cases.items():
            self.answers(src, commit)
            r = self.status("--check")
            self.assertEqual(r.returncode, 0, f"{name}: {r.stdout}{r.stderr}")
            self.assertIn("unknown", r.stdout, name)
        (self.repo / ".copier-answers.yml").unlink()
        r = self.status("--check")
        self.assertEqual(r.returncode, 0)
        self.assertIn("not generated from a template", r.stdout)

    def test_just_recipe_exists(self) -> None:
        self.assertIn("template-status:\n    python3 tools/template_status.py", (self.repo / "justfile").read_text(encoding="utf-8"))


@unittest.skipUnless(shutil.which("git") and shutil.which("sh"), "needs git and sh")
class PreCommitHookTests(RepoTestCase):
    """The optional hook in .githooks/: the repo health check before every commit, never turned on by itself."""

    def setUp(self) -> None:
        super().setUp()
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-qm", "baseline", "--no-verify")  # the baseline predates the hook
        self.git("config", "core.hooksPath", ".githooks")

    def git(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        base = {k: v for k, v in os.environ.items() if k != "REPO_ROOT"}  # an outer REPO_ROOT would point the hook at another repo
        return subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=self.repo, capture_output=True, text=True,
            env={**base, "PYTHON": sys.executable, **env}, timeout=120,
        )

    def commit(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        (self.repo / "notes.txt").write_text("a change\n", encoding="utf-8")
        self.git("add", "-A")
        return self.git("commit", "-qm", "change", *args, **env)

    def test_hook_is_a_posix_shell_script_and_executable(self) -> None:
        hook = self.repo / ".githooks" / "pre-commit"
        self.assertTrue(hook.read_text(encoding="utf-8").startswith("#!/bin/sh\n"))
        self.assertTrue(os.access(hook, os.X_OK), "the hook must keep its executable bit")

    def test_healthy_repo_commits(self) -> None:
        r = self.commit()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_drifted_generated_file_blocks_the_commit_and_names_the_fix(self) -> None:
        head = self.git("rev-parse", "HEAD").stdout
        index = self.repo / "docs" / "INDEX.md"
        index.write_text(index.read_text(encoding="utf-8") + "\nedited by hand\n", encoding="utf-8")
        r = self.commit()
        self.assertNotEqual(r.returncode, 0, "a drifted generated file must block the commit")
        self.assertIn("generated-drift", r.stdout + r.stderr)
        self.assertIn("tools/sync_indexes.py", r.stdout + r.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, head, "nothing may be committed")
        self.ok("sync_indexes")  # the printed fix works, and then the commit goes through
        self.assertEqual(self.commit().returncode, 0)

    def test_no_verify_skips_the_hook(self) -> None:
        index = self.repo / "docs" / "INDEX.md"
        index.write_text(index.read_text(encoding="utf-8") + "\nedited by hand\n", encoding="utf-8")
        self.assertEqual(self.commit("--no-verify").returncode, 0)

    def test_missing_python_skips_with_a_note_instead_of_blocking(self) -> None:
        r = self.commit(PYTHON="definitely-not-a-python")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("skipping", r.stdout + r.stderr)

    def test_just_hooks_recipe_turns_it_on(self) -> None:
        recipe = (self.repo / "justfile").read_text(encoding="utf-8")
        self.assertIn("hooks:\n    git config core.hooksPath .githooks", recipe)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_library_tool(tool: str, root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / f"{tool}.py"), "--root", str(root), *args],
        cwd=root, env={**os.environ, "REPO_ROOT": str(root)}, capture_output=True, text=True, timeout=120,
    )


def file_bytes(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class InstallSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "library"
        self.project = Path(self._tmp.name) / "project"
        (self.root / "agents" / "skills").mkdir(parents=True)
        self.project.mkdir()

    def skill(self, name: str, metadata: str = "") -> Path:
        folder = self.root / "agents" / "skills" / name
        write(folder / "SKILL.md", f"---\nname: {name}\ndescription: Does a thing. Use when testing.\n{metadata}---\n# Example\n")
        return folder

    def install(self, target: str, *args: str) -> subprocess.CompletedProcess:
        return run_library_tool(
            "install_skills", self.root, "--target", target, "--project", str(self.project), *args,
        )

    def test_copies_the_whole_skill_folder(self) -> None:
        source = self.skill("example-skill")
        write(source / "references" / "notes.md", "note\n")
        write(source / "scripts" / "run.sh", "echo ok\n")
        write(source / "__pycache__" / "cache.pyc", "ignored\n")
        write(source / ".DS_Store", "ignored\n")
        result = self.install("claude", "--skill", "example-skill")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        dest = self.project / ".claude" / "skills" / "example-skill"
        self.assertFalse(dest.is_symlink())
        expected = {
            rel: data for rel, data in file_bytes(source).items()
            if "__pycache__" not in Path(rel).parts and Path(rel).suffix != ".pyc" and Path(rel).name != ".DS_Store"
        }
        self.assertEqual(file_bytes(dest), expected)
        self.assertEqual(result.stdout.strip(), "installed example-skill -> .claude/skills/example-skill")

    def test_three_targets(self) -> None:
        self.skill("example-skill")
        for target, relative in {
            "claude": ".claude/skills",
            "opencode": ".opencode/skills",
            "agents": ".agents/skills",
        }.items():
            with self.subTest(target=target):
                result = self.install(target, "--skill", "example-skill")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue((self.project / relative / "example-skill" / "SKILL.md").is_file())

    def test_all_refuses_existing_until_force(self) -> None:
        self.skill("example-skill")
        first = self.install("claude", "--all")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self.root / "agents" / "skills" / "example-skill" / "SKILL.md"
        source.write_text(source.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        installed = self.project / ".claude" / "skills" / "example-skill" / "SKILL.md"
        skipped = self.install("claude", "--all")
        self.assertEqual(skipped.returncode, 1)
        self.assertIn("skipped example-skill:", skipped.stdout)
        self.assertNotIn("changed", installed.read_text(encoding="utf-8"))
        forced = self.install("claude", "--all", "--force")
        self.assertEqual(forced.returncode, 0, forced.stdout + forced.stderr)
        self.assertIn("changed", installed.read_text(encoding="utf-8"))

    def test_dry_run_writes_nothing(self) -> None:
        self.skill("example-skill")
        result = self.install("claude", "--skill", "example-skill", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("would install example-skill -> .claude/skills/example-skill", result.stdout)
        self.assertFalse((self.project / ".claude").exists())

    def test_dry_run_on_an_existing_destination_fails(self) -> None:
        self.skill("example-skill")
        installed = self.project / ".claude" / "skills" / "example-skill" / "SKILL.md"
        write(installed, "old\n")
        result = self.install("claude", "--skill", "example-skill", "--dry-run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("would skip example-skill:", result.stdout)
        self.assertEqual(installed.read_text(encoding="utf-8"), "old\n")

    def test_all_with_skill_and_include_without_all_are_usage_errors(self) -> None:
        for args in (("--all", "--skill", "example-skill"), ("--skill", "example-skill", "--include-tracker-bound")):
            with self.subTest(args=args):
                result = self.install("claude", *args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("error:", result.stderr)

    def test_all_on_an_empty_or_fully_bound_library_fails(self) -> None:
        empty = self.install("claude", "--all")
        self.assertEqual(empty.returncode, 1)
        self.assertIn("no portable skills to install (use --include-tracker-bound or --skill)", empty.stderr)
        self.skill("bound", "metadata:\n  requires: work-tracker\n")
        bound = self.install("claude", "--all")
        self.assertEqual(bound.returncode, 1)
        self.assertIn("no portable skills to install", bound.stderr)
        self.assertFalse((self.project / ".claude").exists())

    def test_unknown_skill_lists_available_names(self) -> None:
        self.skill("alpha")
        self.skill("beta")
        result = self.install("claude", "--skill", "missing")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown skill(s): missing", result.stderr)
        self.assertIn("available: alpha, beta", result.stderr)

    def test_force_replaces_a_file_destination(self) -> None:
        self.skill("example-skill")
        dest = self.project / ".claude" / "skills" / "example-skill"
        write(dest, "old\n")
        result = self.install("claude", "--skill", "example-skill", "--force")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(dest.is_dir())
        self.assertTrue((dest / "SKILL.md").is_file())

    def test_force_replaces_a_symlink_destination_without_touching_its_target(self) -> None:
        self.skill("example-skill")
        target = Path(self._tmp.name) / "target"
        target.mkdir()
        write(target / "keep.txt", "keep\n")
        dest = self.project / ".claude" / "skills" / "example-skill"
        dest.parent.mkdir(parents=True)
        try:
            dest.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks are not available")
        result = self.install("claude", "--skill", "example-skill", "--force")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(dest.is_symlink())
        self.assertTrue((dest / "SKILL.md").is_file())
        self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "keep\n")

    def test_copy_failure_preserves_the_existing_install(self) -> None:
        source = self.skill("example-skill")
        try:
            (source / "broken-link").symlink_to("/nonexistent/target")
        except OSError:
            self.skipTest("symlinks are not available")
        dest = self.project / ".claude" / "skills" / "example-skill"
        write(dest / "SKILL.md", "old\n")
        result = self.install("claude", "--skill", "example-skill", "--force")
        self.assertEqual(result.returncode, 1)
        self.assertIn("skipped example-skill:", result.stdout)
        self.assertEqual((dest / "SKILL.md").read_text(encoding="utf-8"), "old\n")
        self.assertEqual(list(dest.parent.glob(".example-skill.*")), [])

    def test_all_continues_after_a_copy_failure(self) -> None:
        broken = self.skill("a-broken")
        self.skill("b-good")
        try:
            (broken / "broken-link").symlink_to("/nonexistent/target")
        except OSError:
            self.skipTest("symlinks are not available")
        result = self.install("claude", "--all", "--force")
        self.assertEqual(result.returncode, 1)
        self.assertIn("skipped a-broken:", result.stdout)
        self.assertIn("installed b-good ->", result.stdout)
        self.assertTrue((self.project / ".claude" / "skills" / "b-good" / "SKILL.md").is_file())
        self.assertFalse((self.project / ".claude" / "skills" / "a-broken").exists())
        self.assertEqual(list((self.project / ".claude" / "skills").glob(".*")), [])

    def test_default_all_skips_metadata_requires(self) -> None:
        self.skill("portable")
        self.skill("tracker-bound", "metadata:\n  requires: work-tracker\n")
        result = self.install("agents", "--all")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = self.project / ".agents" / "skills"
        self.assertTrue((installed / "portable" / "SKILL.md").is_file())
        self.assertFalse((installed / "tracker-bound").exists())
        self.assertEqual(result.stderr, "")

    def test_include_tracker_bound_installs_both(self) -> None:
        self.skill("portable")
        self.skill("tracker-bound", "metadata:\n  requires: work-tracker\n")
        result = self.install("agents", "--all", "--include-tracker-bound")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = self.project / ".agents" / "skills"
        self.assertTrue((installed / "portable" / "SKILL.md").is_file())
        self.assertTrue((installed / "tracker-bound" / "SKILL.md").is_file())

    def test_explicit_tracker_bound_skill_installs_with_a_portability_note(self) -> None:
        self.skill("tracker-bound", "metadata:\n  requires: work-tracker\n")
        result = self.install("agents", "--skill", "tracker-bound")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.project / ".agents" / "skills" / "tracker-bound" / "SKILL.md").is_file())
        self.assertEqual(
            result.stderr.strip(),
            "note: tracker-bound needs this repository's work tracker (metadata.requires: work-tracker); it is not portable",
        )

    def test_claude_adds_the_user_invocation_line_and_leaves_other_skills_byte_identical(self) -> None:
        user = self.skill("user-skill", "metadata:\n  invocation: user\n")
        plain = self.skill("plain-skill")
        result = self.install("claude", "--all")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = self.project / ".claude" / "skills"
        user_text = (installed / "user-skill" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("disable-model-invocation: true", user_text)
        self.assertEqual(
            (installed / "user-skill" / "SKILL.md").read_bytes(),
            _lib.claude_skill_text((user / "SKILL.md").read_text(encoding="utf-8")).encode("utf-8"),
        )
        self.assertEqual((installed / "plain-skill" / "SKILL.md").read_bytes(), (plain / "SKILL.md").read_bytes())

    def test_agents_target_is_byte_identical_to_the_source_folder(self) -> None:
        source = self.skill("example-skill")
        write(source / "references" / "notes.md", "note\n")
        (source / "assets").mkdir()
        (source / "assets" / "data.bin").write_bytes(b"\x00\xff\x01")
        result = self.install("agents", "--skill", "example-skill")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        dest = self.project / ".agents" / "skills" / "example-skill"
        self.assertEqual(file_bytes(dest), file_bytes(source))


class NewSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "library"
        (self.root / "agents" / "skills").mkdir(parents=True)

    def scaffold(self, name: str, *args: str) -> subprocess.CompletedProcess:
        return run_library_tool("new_skill", self.root, name, *args)

    def path(self, name: str) -> Path:
        return self.root / "agents" / "skills" / name / "SKILL.md"

    def parse(self, name: str) -> tuple[dict, str]:
        return _lib.parse_front_matter(self.path(name).read_text(encoding="utf-8"), _lib.SKILL_MAP_KEYS)

    def test_scaffolds_with_repository_front_matter_and_next_step(self) -> None:
        result = self.scaffold("example-skill")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, body = self.parse("example-skill")
        self.assertEqual(fm["name"], "example-skill")
        self.assertEqual(fm["description"], "<fill: what this skill does and when to use it>")
        self.assertNotIn("license", fm)
        self.assertNotIn("category", fm)
        self.assertNotIn("metadata", fm)
        self.assertLessEqual(len(body.strip().splitlines()), 40)
        for heading in ("## Steps", "## Verify", "## Stop and ask"):
            self.assertIn(heading, body)
        self.assertIn("<fill:", body)
        self.assertEqual(result.stdout.splitlines()[0], "created agents/skills/example-skill/SKILL.md")
        self.assertEqual(
            result.stdout.splitlines()[1],
            "list example-skill in a role's skills: field (agents/roles/<role>/ROLE.md), then run: "
            "python3 tools/sync_agents.py && python3 tools/sync_indexes.py",
        )

    def test_refuses_an_existing_folder_without_force(self) -> None:
        self.assertEqual(self.scaffold("example-skill").returncode, 0)
        result = self.scaffold("example-skill")
        self.assertEqual(result.returncode, 2)
        self.assertIn("already exists", result.stderr)

    def test_force_overwrites(self) -> None:
        self.assertEqual(self.scaffold("example-skill", "--description", "First description").returncode, 0)
        result = self.scaffold("example-skill", "--description", "Second description", "--force")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = self.parse("example-skill")
        self.assertEqual(fm["description"], "Second description")

    def test_description_with_a_colon_round_trips(self) -> None:
        description = "Use when: testing a colon"
        result = self.scaffold("example-skill", "--description", description)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'description: "{description}"', self.path("example-skill").read_text(encoding="utf-8"))
        fm, _ = self.parse("example-skill")
        self.assertEqual(fm["description"], description)

    def test_description_with_quotes_and_backslashes_round_trips(self) -> None:
        description = 'Say "hi" and use C:\\tmp'
        result = self.scaffold("example-skill", "--description", description)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = self.parse("example-skill")
        self.assertEqual(fm["description"], description)

    def test_force_repairs_broken_front_matter(self) -> None:
        write(self.path("example-skill"), "---\nname: example-skill\ndescription: [unclosed\n---\n")
        result = self.scaffold("example-skill", "--description", "Use when testing repair.", "--force")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = self.parse("example-skill")
        self.assertEqual(fm["description"], "Use when testing repair.")

    def test_empty_and_over_long_descriptions_are_rejected(self) -> None:
        for description, expected in (("", "must not be empty"), ("x" * 1025, "1024")):
            with self.subTest(length=len(description)):
                result = self.scaffold("example-skill", "--description", description)
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)
                self.assertFalse(self.path("example-skill").parent.exists())

    def test_invalid_names_are_rejected(self) -> None:
        for name in ("Bad_Name", "-leading", "trailing-", "double--hyphen", "x" * 65):
            with self.subTest(name=name):
                result = run_library_tool("new_skill", self.root, "--", name)
                self.assertEqual(result.returncode, 2)
                self.assertIn("name must be", result.stderr)
                self.assertFalse((self.root / "agents" / "skills" / name).exists())

    def test_scaffolded_skill_parses_and_its_description_round_trips(self) -> None:
        result = self.scaffold("example-skill")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fm, _ = self.parse("example-skill")
        self.assertEqual(fm["name"], "example-skill")
        self.assertEqual(fm["description"], "<fill: what this skill does and when to use it>")
        for tool in ("check.py", "sync_agents.py", "sync_indexes.py", "_lib.py"):
            (self.root / "tools").mkdir(exist_ok=True)
            shutil.copy(ROOT / "tools" / tool, self.root / "tools" / tool)
        (self.root / "agents" / "roles" / "example").mkdir(parents=True, exist_ok=True)
        write(self.root / "agents" / "roles" / "example" / "ROLE.md",
              "---\nrole: example\nmission: Test scaffolding.\nreads: []\nnever: []\ndone_when: []\n"
              "escalate_when: []\nskills: [example-skill]\n---\n# Example\n")
        check = subprocess.run(
            [sys.executable, str(self.root / "tools" / "check.py"), "--strict"],
            cwd=self.root, env={**os.environ, "REPO_ROOT": str(self.root)},
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(check.returncode, 1, check.stdout + check.stderr)
        self.assertIn("skill-stub", check.stdout + check.stderr)
        self.assertIn("agents/skills/example-skill/SKILL.md", check.stdout + check.stderr)
        self.assertNotIn("skill-unlisted", check.stdout + check.stderr)

    def test_unreadable_front_matter_in_another_skill_refuses_scaffolding(self) -> None:
        write(self.root / "agents" / "skills" / "broken" / "SKILL.md", "---\nname: broken\ndescription: [unclosed\n---\n")
        result = self.scaffold("example-skill")
        self.assertEqual(result.returncode, 2)
        self.assertIn("fix unreadable skills before scaffolding", result.stderr)
        self.assertIn("agents/skills/broken/SKILL.md", result.stderr)
        self.assertFalse(self.path("example-skill").exists())

    def test_metadata_is_written_only_when_requested(self) -> None:
        cases = {
            "plain": ((), None),
            "tracker": (("--requires", "work-tracker"), {"requires": "work-tracker"}),
            "user": (("--invocation", "user"), {"invocation": "user"}),
            "both": (("--requires", "work-tracker", "--invocation", "user"), {"requires": "work-tracker", "invocation": "user"}),
        }
        for name, (args, expected) in cases.items():
            with self.subTest(name=name):
                result = self.scaffold(name, *args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                fm, _ = self.parse(name)
                self.assertEqual(fm.get("metadata"), expected)
                self.assertNotIn("license", fm)
                self.assertNotIn("category", fm)


class FloorTests(unittest.TestCase):
    def test_every_tool_stops_with_one_clear_line_on_an_older_python(self) -> None:
        older = (_lib.MIN_PYTHON[0], _lib.MIN_PYTHON[1] - 1, 0, "final", 0)
        tools = sorted((ROOT / "tools").glob("*.py"))
        self.assertGreater(len(tools), 10)
        for tool in tools:
            code = (f"import sys, runpy; sys.version_info = {older!r}; sys.argv = [{tool.name!r}, '--help']; "
                    f"sys.path.insert(0, {str(tool.parent)!r}); runpy.run_path({str(tool)!r}, run_name='__main__')")
            r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
            with self.subTest(tool=tool.name):
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
                self.assertIn(f"need Python {_lib.MIN_PYTHON[0]}.{_lib.MIN_PYTHON[1]} or newer", r.stderr)


if __name__ == "__main__":
    unittest.main()
