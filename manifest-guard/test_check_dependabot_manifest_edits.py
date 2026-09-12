"""Tests for the manifest guard's pure logic.

Holds are supplied as inputs, never read from a real config: pinning "package X
is held" would go red on the day the hold is legitimately lifted, and a test
that is edited until it passes is not a test.

Runs under pytest and standalone.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import check_dependabot_manifest_edits as g  # noqa: E402

P = "app/package.json"


def m(deps=None, dev=None):
    doc = {}
    if deps is not None:
        doc["dependencies"] = deps
    if dev is not None:
        doc["devDependencies"] = dev
    return doc


def run(before, after, documented=(), held_all=(), held_major=()):
    return g.compare({P: before}, {P: after}, set(documented), set(held_all), set(held_major))


def kinds(findings):
    return sorted(f.kind for f in findings)


# ----- versions --------------------------------------------------------------


def test_floor_ignores_range_operators() -> None:
    assert g.floor_of("^2.3.4") == (2, 3, 4)
    assert g.floor_of(">=1.0.0 <2") == (1, 0, 0)


def test_floor_of_non_version_is_none() -> None:
    for spec in ("workspace:*", "latest", "git+https://x/y", None, 3):
        assert g.floor_of(spec) is None


# ----- trailers --------------------------------------------------------------


def test_double_quoted_scoped_name_is_unquoted() -> None:
    assert g.trailer_names(['updated-dependencies:\n- dependency-name: "@s/pkg"\n']) == {"@s/pkg"}


def test_single_quoted_and_bare_names_are_read() -> None:
    msgs = ["- dependency-name: 'quoted'\n", "- dependency-name: bare\n"]
    assert g.trailer_names(msgs) == {"quoted", "bare"}


def test_names_accumulate_over_commits() -> None:
    assert g.trailer_names(["- dependency-name: a", "- dependency-name: b"]) == {"a", "b"}


def test_no_trailer_documents_nothing() -> None:
    assert g.trailer_names(["chore: tidy"]) == set()


# ----- holds -----------------------------------------------------------------


CFG = """
version: 2
updates:
  - package-ecosystem: npm
    directory: /
    ignore:
      - dependency-name: major-held
        update-types: [version-update:semver-major]
      - dependency-name: frozen
      - dependency-name: minor-only
        update-types: [version-update:semver-minor]
  - package-ecosystem: pip
    directory: /
    ignore:
      - dependency-name: other-eco
"""


def test_holds_are_split_by_kind() -> None:
    assert g.holds_from(CFG) == ({"frozen"}, {"major-held"})


def test_minor_only_hold_is_neither() -> None:
    total, major = g.holds_from(CFG)
    assert "minor-only" not in total | major


def test_other_ecosystems_are_ignored() -> None:
    total, major = g.holds_from(CFG)
    assert "other-eco" not in total | major


def test_empty_config_has_no_holds() -> None:
    assert g.holds_from("version: 2\nupdates: []\n") == (set(), set())


# ----- compare: the four findings, each provoked alone -----------------------


def test_documented_bump_is_clean() -> None:
    assert run(m({"a": "^1.0.0"}), m({"a": "^1.2.0"}), documented=["a"]) == []


def test_unchanged_manifest_is_clean() -> None:
    doc = m({"a": "^1.0.0"})
    assert run(doc, doc) == []


def test_undocumented_change_is_found() -> None:
    f = run(m({"a": "^1.0.0", "b": "^7.0.0"}), m({"a": "^1.1.0", "b": "^8.0.0"}), documented=["a"])
    assert kinds(f) == ["UNDOCUMENTED"] and f[0].name == "b"


def test_added_package_is_undocumented() -> None:
    f = run(m({"a": "^1.0.0"}), m({"a": "^1.0.0", "injected": "^0.1.0"}), documented=["a"])
    assert kinds(f) == ["UNDOCUMENTED"] and f[0].before is None


def test_removed_package_is_undocumented() -> None:
    f = run(m({"a": "^1.0.0", "gone": "^2.0.0"}), m({"a": "^1.0.0"}), documented=["a"])
    assert kinds(f) == ["UNDOCUMENTED"] and f[0].after is None


def test_downgrade_is_found_even_when_documented() -> None:
    assert kinds(run(m({"sdk": "^13.0.0"}), m({"sdk": "^10.1.0"}), documented=["sdk"])) == ["DOWNGRADE"]


def test_held_major_crossing_is_found_even_when_documented() -> None:
    f = run(m({"h": "^7.2.0"}), m({"h": "^8.0.0"}), documented=["h"], held_major=["h"])
    assert kinds(f) == ["HELD MAJOR"]


def test_minor_of_a_held_major_package_flows() -> None:
    assert run(m({"h": "^7.2.0"}), m({"h": "^7.3.0"}), documented=["h"], held_major=["h"]) == []


def test_fully_held_package_may_not_move() -> None:
    f = run(m({"f": "5.4.1"}), m({"f": "5.4.2"}), documented=["f"], held_all=["f"])
    assert kinds(f) == ["HELD PACKAGE"]


def test_full_hold_outranks_downgrade() -> None:
    f = run(m({"f": "^5.0.0"}), m({"f": "^4.0.0"}), documented=["f"], held_all=["f"])
    assert kinds(f) == ["HELD PACKAGE"]


def test_dev_dependencies_are_compared() -> None:
    f = run(m(dev={"t": "^3.0.0"}), m(dev={"t": "^6.0.0"}))
    assert kinds(f) == ["UNDOCUMENTED"] and f[0].section == "devDependencies"


def test_multiple_findings_all_surface() -> None:
    f = run(m({"sdk": "^13.0.0", "a": "^1.0.0"}), m({"sdk": "^10.0.0", "a": "^1.0.0", "x": "^1.0.0"}), documented=["a"])
    assert kinds(f) == ["DOWNGRADE", "UNDOCUMENTED"]


def test_brand_new_manifest_is_handled() -> None:
    f = g.compare({P: None}, {P: m({"a": "^1.0.0"})}, set(), set(), set())
    assert kinds(f) == ["UNDOCUMENTED"]


def test_non_version_specs_do_not_crash() -> None:
    assert run(m({"w": "workspace:*"}), m({"w": "workspace:^"}), documented=["w"]) == []


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
