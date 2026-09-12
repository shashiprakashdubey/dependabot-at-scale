#!/usr/bin/env python3
"""A Dependabot PR's manifest edits must match what the PR says it did.

Dependabot describes each change in the commit trailer:

    updated-dependencies:
    - dependency-name: "@scope/pkg"
      dependency-type: direct:production

The trailer is not guaranteed to be a complete account of the diff. Grouped
security updates in particular can rewrite manifest entries far beyond their
stated payload -- lowering versions, crossing majors that were deliberately
held, adding packages to a manifest that never depended on them. Every line of
the description is true; the diff simply contains more.

A second problem makes this worse: GitHub's docs state that `ignore` rules with
`update-types` apply to VERSION updates only, not security updates. So every
semver-major hold in dependabot.yml is advisory against the security channel,
and only a CI check can make it real.

This guard reads each changed manifest as JSON at the merge-base and at HEAD,
compares the parsed dependency maps (never the text diff, which misattributes
+/- pairs across files), and reports four kinds of finding:

    DOWNGRADE     the floor version of a dependency went down
    UNDOCUMENTED  a changed entry names a package absent from every trailer
    HELD MAJOR    a major crossing on a package whose major is ignored --
                  reported even when documented, because this is exactly the
                  channel the ignore rule does not reach
    HELD PACKAGE  any movement of a package ignored for all update types

Holds are collected as a union over every entry for the ecosystem: entries only
differ per directory because most directories never declare the package, so
the union adds no noise and spares the guard a directory-to-manifest mapping.

Usage: python3 check_dependabot_manifest_edits.py --repo-root . --base-ref origin/main
Exit:  0 clean, 1 findings, 2 could not look.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import posixpath
import re
import subprocess
import sys

ECOSYSTEM = "npm"
MANIFEST_NAME = "package.json"
SECTIONS = ("dependencies", "devDependencies", "peerDependencies",
            "optionalDependencies", "overrides", "resolutions")
MAJOR_IGNORE = "version-update:semver-major"

EXIT_CLEAN, EXIT_FINDINGS, EXIT_COULD_NOT_LOOK = 0, 1, 2

# Trailer values may be quoted (scoped packages always are) while manifest keys
# never are. Strip the quotes on the way in or every @scope/* package reads as
# undocumented.
_TRAILER = re.compile(r"dependency-name:\s*(?:\"([^\"]+)\"|'([^']+)'|(\S+))")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclasses.dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    section: str
    name: str
    before: str | None
    after: str | None
    why: str


class CouldNotLook(Exception):
    pass


def floor_of(spec) -> tuple[int, int, int] | None:
    """Lowest concrete version a range admits, or None for tags/URLs."""
    if not isinstance(spec, str):
        return None
    m = _VERSION.search(spec)
    return tuple(int(g) for g in m.groups()) if m else None  # type: ignore[return-value]


def flatten(manifest) -> dict[tuple[str, str], str]:
    """{(section, name): spec} over every dependency map. Nested override
    objects are skipped rather than guessed at."""
    flat: dict[tuple[str, str], str] = {}
    if isinstance(manifest, dict):
        for section in SECTIONS:
            block = manifest.get(section)
            if isinstance(block, dict):
                flat.update({(section, k): v for k, v in block.items() if isinstance(v, str)})
    return flat


def trailer_names(messages) -> set[str]:
    names: set[str] = set()
    for msg in messages:
        for q1, q2, bare in _TRAILER.findall(msg or ""):
            names.add((q1 or q2 or bare).strip())
    return names


def holds_from(config_text) -> tuple[set[str], set[str]]:
    """(held for everything, held at major) for ECOSYSTEM entries."""
    import yaml

    doc = yaml.safe_load(config_text) or {}
    total, major = set(), set()
    for entry in doc.get("updates") or []:
        if not isinstance(entry, dict) or entry.get("package-ecosystem") != ECOSYSTEM:
            continue
        for rule in entry.get("ignore") or []:
            name = rule.get("dependency-name") if isinstance(rule, dict) else None
            if not name:
                continue
            kinds = rule.get("update-types")
            (total if not kinds else major if MAJOR_IGNORE in kinds else set()).add(name)
    return total, major


def compare(base, head, documented, held_all, held_major) -> list[Finding]:
    """Diff parsed manifests: {path: manifest-or-None} on each side."""
    out: list[Finding] = []
    for path in sorted(set(base) | set(head)):
        before, after = flatten(base.get(path)), flatten(head.get(path))
        for key in sorted(set(before) | set(after)):
            old, new = before.get(key), after.get(key)
            if old == new:
                continue
            section, name = key
            lo, hi = floor_of(old), floor_of(new)
            add = lambda kind, why: out.append(Finding(kind, path, section, name, old, new, why))  # noqa: E731
            if name in held_all:
                add("HELD PACKAGE", "ignored for every update type; must not move in a Dependabot PR")
            elif lo and hi and hi < lo:
                add("DOWNGRADE", "a dependency update must never lower a version")
            elif lo and hi and hi[0] > lo[0] and name in held_major:
                add("HELD MAJOR", "major is ignored in dependabot.yml; security updates bypass that rule, CI enforces it")
            elif name not in documented:
                verb = "added" if old is None else "removed" if new is None else "changed"
                add("UNDOCUMENTED", f"{verb}, but no updated-dependencies trailer names it")
    return out


# ----- git plumbing (thin; the logic above is what the tests cover) ----------


def _git(root, *args) -> str:
    proc = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
    if proc.returncode:
        raise CouldNotLook(f"git {args[0]}: {proc.stderr.strip()}")
    return proc.stdout


def _manifest_at(root, rev, path):
    proc = subprocess.run(["git", "-C", root, "show", f"{rev}:{path}"], capture_output=True, text=True)
    if proc.returncode:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _changed_manifests(root, base, head) -> list[str]:
    return [
        p for p in _git(root, "diff", "--name-only", base, head).splitlines()
        if posixpath.basename(p) == MANIFEST_NAME and "node_modules" not in p.split("/")
    ]


def _messages(root, base, head) -> list[str]:
    # NUL-delimited: a multi-line body must not bleed into the next commit.
    return [m for m in _git(root, "log", "--format=%B%x00", f"{base}..{head}").split("\0") if m.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--base-ref", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    a = ap.parse_args(argv)
    try:
        base = _git(a.repo_root, "merge-base", a.base_ref, a.head).strip()
        paths = _changed_manifests(a.repo_root, base, a.head)
        if not paths:
            print(f"no {MANIFEST_NAME} changed between {base[:9]} and {a.head}; nothing to check")
            return EXIT_CLEAN
        documented = trailer_names(_messages(a.repo_root, base, a.head))
        # An unparseable config is a defect in its own right, and the state in
        # which every hold is silently off. Fail closed.
        held_all, held_major = holds_from(_git(a.repo_root, "show", f"{a.head}:.github/dependabot.yml"))
    except CouldNotLook as exc:
        print(f"COULD NOT LOOK: {exc}")
        return EXIT_COULD_NOT_LOOK

    findings = compare(
        {p: _manifest_at(a.repo_root, base, p) for p in paths},
        {p: _manifest_at(a.repo_root, a.head, p) for p in paths},
        documented, held_all, held_major,
    )
    print(f"manifests: {', '.join(paths)}")
    print(f"documented: {', '.join(sorted(documented)) or '(none)'}")
    if not findings:
        print("OK: every manifest edit is documented, nothing downgraded, no held package moved.")
        return EXIT_CLEAN
    print(f"\n{len(findings)} finding(s):")
    for f in findings:
        print(f"  [{f.kind}] {f.path} {f.section}.{f.name}: {f.before} -> {f.after}\n      {f.why}")
    print("\nIf an edit above is a deliberate human change on this branch, split it into its own PR.")
    return EXIT_FINDINGS


if __name__ == "__main__":
    sys.exit(main())
