"""Tests for the coverage checker.

Each failure mode is provoked by materialising a tree that exhibits it, and the
integration is exercised through main() rather than only through the helpers --
a check that has been unplugged from the pipeline passes every helper test.

Runs under pytest and standalone (`python3 test_check_coverage.py`).
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import check_coverage as cc  # noqa: E402

BASE_CONFIG = """\
version: 2
updates:
  - package-ecosystem: pip
    directories: ["/*-svc"]
    schedule: {interval: weekly}
"""


def make_tree(config: str, manifests=(), bare_dirs=()) -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp())
    cfg = root / cc.CONFIG_PATH
    cfg.parent.mkdir(parents=True)
    cfg.write_text(config)
    for rel in manifests:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    for rel in bare_dirs:
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


# ----- matches(): the one hand-rolled primitive -----------------------------


def test_glob_star_stays_within_one_segment() -> None:
    assert cc.matches("/api-svc", "/*-svc")
    assert not cc.matches("/api-svc/tests", "/*-svc")


def test_depth_must_agree() -> None:
    assert not cc.matches("/a/b", "/a")
    assert not cc.matches("/a", "/a/b")


def test_nested_glob_matches_only_at_its_depth() -> None:
    assert cc.matches("/fn/worker-x", "/fn/worker-*")
    assert not cc.matches("/fn", "/fn/worker-*")


# ----- the four properties, each provoked ------------------------------------


def test_clean_tree_passes() -> None:
    assert cc.main(make_tree(BASE_CONFIG, ["api-svc/poetry.lock"])) == 0


def test_uncovered_manifest_directory_fails() -> None:
    root = make_tree(BASE_CONFIG, ["api-svc/poetry.lock", "orphan/poetry.lock"])
    assert cc.audit(root).uncovered == ("/orphan",)
    assert cc.main(root) == 1


def test_glob_landing_on_manifestless_directory_fails() -> None:
    root = make_tree(BASE_CONFIG, ["api-svc/poetry.lock"], bare_dirs=["docs-svc"])
    assert cc.audit(root).overmatched == ("/docs-svc",)
    assert cc.main(root) == 1


def test_nested_directory_is_not_swallowed_by_a_top_level_glob() -> None:
    """End-to-end form of the segment rule: a nested dir ending in `-svc` must
    not count as an over-match for `/*-svc`."""
    root = make_tree(BASE_CONFIG, ["api-svc/poetry.lock"], bare_dirs=["api-svc/inner-svc"])
    assert cc.audit(root).overmatched == ()
    assert cc.main(root) == 0


def test_entry_matching_nothing_fails() -> None:
    cfg = BASE_CONFIG.replace('["/*-svc"]', '["/*-svc", "/retired"]')
    root = make_tree(cfg, ["api-svc/poetry.lock"])
    assert cc.audit(root).dead == ("/retired",)
    assert cc.main(root) == 1


def test_unknown_entry_key_fails() -> None:
    cfg = BASE_CONFIG + "    open_pull_requests_limit: 5\n"
    root = make_tree(cfg, ["api-svc/poetry.lock"])
    assert cc.audit(root).unknown_keys
    assert cc.main(root) == 1


def test_unknown_group_key_fails() -> None:
    cfg = BASE_CONFIG + "    groups:\n      all:\n        dependancy-type: production\n"
    root = make_tree(cfg, ["api-svc/poetry.lock"])
    assert any("group" in k for k in cc.audit(root).unknown_keys)
    assert cc.main(root) == 1


def test_unknown_top_level_key_fails() -> None:
    root = make_tree("updatez: []\n" + BASE_CONFIG, ["api-svc/poetry.lock"])
    assert any("top level" in k for k in cc.audit(root).unknown_keys)
    assert cc.main(root) == 1


def test_every_documented_key_is_accepted() -> None:
    cfg = BASE_CONFIG + (
        "    versioning-strategy: increase-if-necessary\n"
        "    labels: [deps]\n"
        "    groups:\n      all:\n        applies-to: version-updates\n"
        "        patterns: ['*']\n        exclude-patterns: ['x/*']\n"
        "        update-types: [patch, minor]\n"
        "  - package-ecosystem: github-actions\n    directory: /\n"
        "    schedule: {interval: weekly}\n"
    )
    assert cc.main(make_tree(cfg, ["api-svc/poetry.lock"])) == 0


def test_key_check_is_wired_through_main() -> None:
    """Directory set is correct; only the key check can fail this run."""
    cfg = BASE_CONFIG + "    rebase_strategy: auto\n"
    root = make_tree(cfg, ["api-svc/poetry.lock"])
    assert cc.audit(root).uncovered == () and cc.audit(root).overmatched == ()
    assert cc.main(root) == 1


def test_vendored_manifests_are_ignored() -> None:
    root = make_tree(BASE_CONFIG, ["api-svc/poetry.lock", "node_modules/x/requirements.txt"])
    assert cc.main(root) == 0


def test_other_ecosystem_entries_do_not_claim_coverage() -> None:
    cfg = BASE_CONFIG.replace("package-ecosystem: pip", "package-ecosystem: npm")
    root = make_tree(cfg, ["api-svc/poetry.lock"])
    assert cc.audit(root).uncovered == ("/api-svc",)


# ----- runner ----------------------------------------------------------------


def _run() -> int:
    import contextlib
    import io
    import traceback

    failed = 0
    tests = sorted((n, f) for n, f in globals().items() if n.startswith("test_"))
    for name, fn in tests:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                fn()
            print(f"  ok   {name}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
