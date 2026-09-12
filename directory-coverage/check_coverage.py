#!/usr/bin/env python3
"""Does dependabot.yml cover exactly the directories that hold a manifest?

Dependabot reads its config from the default branch only, and a directory it
does not cover produces no update PR, no warning and no security alert. The
outcome of a missing entry is silence -- which is also what "nothing to update"
looks like. So coverage has to be proved by a machine, not maintained by hand.

Coverage here is declared as globs under `directories:`. This script expands
those globs against the real tree and requires the result to equal the set of
manifest directories exactly. Four properties, all required:

    covered   every manifest directory is matched by some entry
    exact     no entry matches a directory without a manifest
    alive     every configured entry still matches something on disk
    spelled   every key is one Dependabot recognises

"exact" is stricter than Dependabot demands. GitHub says globs are supported and
says nothing about a glob that lands on a manifest-less directory; rather than
lean on undocumented behaviour, the globs are held to the manifest set.

"spelled" guards a different failure: GitHub discards the WHOLE file on one
unknown key, silently, so a typo does not break one entry -- it switches every
directory off at once while the directory list still reads as correct. Only key
names are checked, not values.

Exit 0 when all four hold, 1 otherwise. Set ECOSYSTEM / MANIFEST_PATTERNS for
your stack.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import pathlib
import sys

import yaml

CONFIG_PATH = ".github/dependabot.yml"
ECOSYSTEM = "pip"
MANIFEST_PATTERNS = ("*/poetry.lock", "*/requirements.txt", "*/*/requirements.txt")
IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "site-packages", "__pycache__"}

TOP_LEVEL_KEYS = {"version", "updates", "registries", "enable-beta-ecosystems"}
ENTRY_KEYS = {
    "package-ecosystem", "directory", "directories", "schedule", "allow", "assignees",
    "commit-message", "cooldown", "groups", "ignore", "insecure-external-code-execution",
    "labels", "milestone", "open-pull-requests-limit", "patterns",
    "pull-request-branch-name", "rebase-strategy", "registries", "reviewers",
    "target-branch", "vendor", "versioning-strategy",
}
GROUP_KEYS = {"applies-to", "dependency-type", "patterns", "exclude-patterns", "update-types"}


@dataclasses.dataclass(frozen=True)
class Report:
    uncovered: tuple[str, ...]   # manifest dirs no entry matches
    overmatched: tuple[str, ...]  # matched dirs with no manifest
    dead: tuple[str, ...]        # entries matching nothing on disk
    unknown_keys: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not (self.uncovered or self.overmatched or self.dead or self.unknown_keys)


def matches(path: str, pattern: str) -> bool:
    """Segment-wise glob: `*` never crosses a `/`.

    Plain fnmatch treats `/` as an ordinary character, so `/*` would swallow
    `/svc/tests` and report a false over-match on a correct tree.
    """
    want, have = pattern.strip("/").split("/"), path.strip("/").split("/")
    return len(want) == len(have) and all(
        fnmatch.fnmatchcase(seg, glob) for seg, glob in zip(have, want)
    )


def _rel(root: pathlib.Path, path: pathlib.Path) -> str:
    return "/" + path.relative_to(root).as_posix()


def _skipped(path: pathlib.Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def manifest_dirs(root: pathlib.Path) -> set[str]:
    out = set()
    for pattern in MANIFEST_PATTERNS:
        out.update(_rel(root, p.parent) for p in root.glob(pattern) if not _skipped(p))
    return out


def all_dirs(root: pathlib.Path) -> set[str]:
    """Every directory in the tree. Globs expand against THIS, so an over-broad
    pattern is visible instead of silently collapsing onto the manifest set."""
    return {
        _rel(root, p) for p in root.rglob("*")
        if p.is_dir() and not _skipped(p.relative_to(root))
    }


def _entries(update: dict) -> list[str]:
    items = list(update.get("directories") or [])
    if update.get("directory") is not None:
        items.insert(0, update["directory"])
    return items


def expand(config: dict, tree: set[str]) -> tuple[set[str], list[str]]:
    """(dirs covered for ECOSYSTEM, every configured path across all entries)."""
    covered, declared = set(), []
    for update in config.get("updates") or []:
        if not isinstance(update, dict):
            continue
        items = _entries(update)
        declared.extend(items)
        if update.get("package-ecosystem") == ECOSYSTEM:
            for item in items:
                covered.update(d for d in tree if matches(d, item))
    return covered, declared


def unknown_keys(config: dict) -> list[str]:
    bad = [f"{k} (top level)" for k in config if k not in TOP_LEVEL_KEYS]
    for i, update in enumerate(config.get("updates") or []):
        if not isinstance(update, dict):
            continue
        where = update.get("package-ecosystem") or f"updates[{i}]"
        bad += [f"{k} (in {where} entry)" for k in update if k not in ENTRY_KEYS]
        for gname, group in (update.get("groups") or {}).items():
            if isinstance(group, dict):
                bad += [f"{k} (in group {gname!r})" for k in group if k not in GROUP_KEYS]
    return sorted(bad)


def audit(root: pathlib.Path) -> Report:
    config = yaml.safe_load((root / CONFIG_PATH).read_text()) or {}
    tree = all_dirs(root)
    have = manifest_dirs(root)
    covered, declared = expand(config, tree)
    return Report(
        uncovered=tuple(sorted(have - covered)),
        overmatched=tuple(sorted(covered - have)),
        dead=tuple(sorted(e for e in declared if e != "/" and not any(matches(d, e) for d in tree))),
        unknown_keys=tuple(unknown_keys(config)),
    )


def _section(title: str, items: tuple[str, ...], advice: str) -> None:
    if not items:
        return
    print(f"{title} ({len(items)}):")
    for item in items:
        print(f"    {item}")
    print(f"  -> {advice}\n")


def locate_root() -> pathlib.Path:
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / CONFIG_PATH).exists():
            return parent
    sys.exit(f"no {CONFIG_PATH} found above {__file__}")


def main(root: pathlib.Path | None = None) -> int:
    # `root` is a parameter so the whole pipeline is testable end to end. If a
    # check is ever unplugged from audit(), a helper-level test stays green; only
    # an integration test through main() can notice.
    report = audit(root or locate_root())
    _section("manifest directories with no covering entry", report.uncovered,
             "extend the `directories:` globs")
    _section("matched directories that hold no manifest", report.overmatched,
             "narrow the pattern; behaviour on such matches is undocumented")
    _section("configured entries matching nothing on disk", report.dead,
             "delete the entry or fix the path")
    _section("keys Dependabot will not recognise", report.unknown_keys,
             "one unknown key disables the entire file")
    if report.ok:
        print(f"OK: {ECOSYSTEM} globs cover exactly the manifest set; no dead entries; keys valid.")
        return 0
    print(f"FAIL: {CONFIG_PATH} does not match the tree.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
