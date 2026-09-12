# Directory coverage, as globs with a guard

## The failure mode

A monorepo with many manifest directories usually ends up with a hand-written block per
directory:

```yaml
updates:
  - package-ecosystem: 'pip'
    directory: '/service-a'
    ...
  - package-ecosystem: 'pip'
    directory: '/service-b'
    ...
  # ...30 more
```

Two properties of Dependabot turn that list into a silent outage:

1. **The config is read only from the default branch.** Not from your integration branch, not
   from the branch where someone fixed the list.
2. **A missing directory is not an error.** It produces no PR, no warning, and no CVE alert.
   It looks exactly like a directory with nothing to update.

Put those together and you get the real incident shape: the list is corrected on a working
branch, the correction never reaches the default branch, and a handful of directories receive
**no dependency updates and no security alerts** for as long as the drift lasts. Nobody
notices, because the symptom of the failure is silence — and silence is also what "everything
is up to date" looks like.

Fixing the list again is not a fix. It leaves the mechanism — a long list maintained by hand,
whose correctness nobody can see — fully intact.

## The pattern

Express coverage as **globs**, and make CI prove the globs are exact.

```yaml
- package-ecosystem: 'pip'
  directories:
    - '/*-stack'                  # every directory following the convention
    - '/legacy-service'           # predates the convention
    - '/functions/handler-*'      # nested manifests
  schedule:
    interval: 'weekly'
```

A new directory that follows the naming convention is picked up automatically. Anything that
doesn't follow it still has to be listed — and that's exactly what the guard catches.

### Why a guard is required, not optional

GitHub documents that `directories` supports globbing. It does **not** document what happens
when a glob matches a directory that holds no manifest for that ecosystem. Rather than depend
on undocumented behaviour, require the globs to be **exact**, and hold them to it in CI.

[`check_coverage.py`](check_coverage.py) expands the globs itself and fails unless **all four**
hold:

| Check | Catches |
|---|---|
| Every manifest directory is matched | The original silent-drift failure — a directory nobody is updating |
| Nothing without a manifest is matched | Over-broad globs relying on undocumented behaviour |
| Every configured path still matches something | Dead entries left behind when a directory is renamed or retired |
| Every key is one Dependabot accepts | **A typo that disables the entire file** |

That last check is a different failure class from the other three, and the sharpest one.

### One bad key disables everything

GitHub rejects the **whole config file** on a single unrecognised key — silently. A typo'd
`dependancy-type` or `update_types` doesn't disable one entry; it disables **every directory
at once**, which is the same silent-drift outcome with a much larger blast radius and an even
weaker signal.

A pure directory-set comparison passes that cleanly, because the directories in the file are
still correct — the file just isn't being used. So the guard checks key *names* against the
documented set as well.

> This is a **typo guard, not schema validation**. It checks key names, not value shapes: a
> bogus `interval: fortnightly` still gets through. Worth knowing what it does and does not
> buy you.

### Glob semantics: `*` must not cross a `/`

The one genuinely subtle piece of the implementation. `fnmatch` alone treats `/` as an
ordinary character, so `/*` matches `/service-a/tests` — and the guard reports a false
over-match on a tree that is actually correct.

`matches()` therefore splits on `/` and compares segment by segment, requiring the segment
counts to agree. `test_glob_star_stays_within_one_segment` pins that behaviour directly, and
`test_nested_directory_is_not_swallowed_by_a_top_level_glob` pins it again end-to-end through
`main()`, because it is the defect the function exists to prevent.

## Running it

```console
$ python3 check_coverage.py
OK: pip globs cover exactly the manifest set; no dead entries; keys valid.
```

On failure it names each directory or key and says what to do about it. Exit code 1, so it
drops straight into a workflow:

```yaml
- name: Dependabot covers every manifest directory
  run: python3 scripts/dependabot-coverage/check_coverage.py
```

Run it in a job that is **unconditional within the workflow**. If your CI selects jobs by
changed-path prefix, a guard gated behind one of those prefixes will not run on a PR that
changes only the guard or only the config — precisely when it is needed.

## A note on the tests

The guard ships with committed tests, and they are shaped around two rules:

- **Every failure mode is asserted by building a tree that trips it**, not by reading the
  source. A guard test that only exercises the happy path is the same failure class the guard
  exists to prevent, one level up.
- **`main()` takes an injectable root** so the *integration* is testable, not just each helper
  in isolation. Without that, deleting the unknown-key wiring from `main()` leaves every unit
  test green — a guard that has been silently disconnected still reports OK.

## Files

- [`check_coverage.py`](check_coverage.py) — the guard
- [`test_check_coverage.py`](test_check_coverage.py) — runs under pytest, and standalone
  (`python3 test_check_coverage.py`) so it stays usable on a runner without pytest
- [`dependabot.yml`](dependabot.yml) — the glob-based config it checks
