# Dependabot at Scale

[![Tests](https://github.com/shashiprakashdubey/dependabot-at-scale/actions/workflows/tests.yml/badge.svg)](https://github.com/shashiprakashdubey/dependabot-at-scale/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)
![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![Dependabot](https://img.shields.io/badge/Dependabot-025E8C?style=flat-square&logo=dependabot&logoColor=white)

**What this is** — four patterns and two tested CI guards for running Dependabot across several
ecosystems and dozens of manifest directories.
**Who it's for** — anyone whose dependency PRs have quietly become a backlog nobody merges, or
who assumes a semver hold in `dependabot.yml` actually holds.
**Start here** — [directory-coverage](directory-coverage/) (~4 min); it covers the failure where
a directory gets **no updates and no CVE alerts**, silently.

---

Dependabot is easy to turn on and surprisingly hard to keep honest. Once you point it at a
monorepo with several ecosystems and dozens of manifest directories, the interesting failures
stop being "it didn't open a PR" and start being **silent**: directories that quietly receive
no updates, holds that don't hold, and PRs whose diff is larger than their own description.

This is a small library of the patterns and CI guards that close those gaps. Each one is
written up as **the failure mode it prevents**, a **minimal generic config or script**, and —
where it applies — the **test that stops the mistake from recurring**.

> Generic and illustrative. All identifiers are placeholders (`*-stack`, `service-a`,
> `example-pkg`). The incident shapes described are real in outline and deliberately stripped
> of any repository, ticket, or organisation detail. These are patterns to adapt, not a
> deployable product.

## The patterns

| Pattern | Prevents |
|---|---|
| **[grouping-that-stays-reviewable](grouping-that-stays-reviewable/)** | The 60-package "bump the dependencies group" PR that mixes routine patches with breaking majors, and is therefore neither reviewable nor mergeable. Batches patch + minor, lets majors fall through individually, and carves out **lockstep families** that are only mergeable together. |
| **[directory-coverage](directory-coverage/)** | Manifest directories silently receiving **no updates and no CVE alerts** because a hand-maintained directory list drifted — on the one branch Dependabot actually reads. Replaces the list with globs and a **CI guard** that requires them to expand to exactly the manifest set. |
| **[manifest-guard](manifest-guard/)** | Dependabot PRs whose manifest edits exceed their own documented payload — undocumented majors, silent downgrades, injected packages — and semver holds that **don't apply to the security channel**. A guard that reads the config's own `ignore` lists and enforces them. |
| **[security-update-scoping](security-update-scoping/)** | One repo-wide security PR spanning every directory at once, which is the blast radius that makes the corruption in the previous pattern possible. Scopes security updates per directory with `applies-to`. |

## Why these four

They share a property that makes them worth writing down: **the failure is invisible at the
moment it happens.**

- **Grouping** fails loudly enough to notice but quietly enough to tolerate — you just stop
  merging the dependency PR, and the backlog rots. The damage is the *absence* of updates.
- **Directory coverage** is the sharpest of the four. Dependabot reads its config only from
  the default branch, so a directory list fixed on a working branch is not fixed at all. A
  directory that isn't listed doesn't error; it simply never appears again.
- **Manifest integrity** is the one that actively costs you. A corrupted manifest value gets
  mistaken for the real baseline later, and the recovery is measured in weeks, not minutes.
- **Security scoping** is the multiplier. Almost every cross-directory corruption is a
  cross-directory *security group* PR, because that's the only thing that routinely spans
  directories.

## The load-bearing idea

Three of these four are **committed CI guards, with committed tests**, not documentation. A
convention written in a comment holds until the next person edits the file in a hurry; a
guard that goes red holds regardless. The corollary matters just as much — a guard needs a
test that fails when the guard is broken, or it's just a slower comment.

## The Dependabot behaviours behind these patterns

Worth knowing even if you adopt none of the code:

- **Config is read from the default branch only.** Fixes on a feature or integration branch
  have no effect until they land there.
- **One invalid key rejects the whole file, silently.** A typo'd `dependancy-type` doesn't
  disable one entry; it disables every directory at once, with no PR and no error surfaced
  in the repo.
- **`ignore` + `update-types` constrains version updates, never security updates.** Every
  semver-major hold is advisory as far as the security channel is concerned. If you need it
  enforced, enforce it in CI.
- **A group with `patterns: ['*']` and no `update-types` sweeps majors in too.** This is the
  single most common cause of the unmergeable mega-PR.
- **`dependency-type: production|development` only works where the manifest declares the
  split.** Poetry and Pipenv do; a bare `requirements.txt` does not, so dependencies there
  match *neither* group and fall through as individual PRs.
- **Dependencies are assigned to the first matching group**, so specific patterns must
  precede any catch-all.
- **`open-pull-requests-limit` is per *entry*, not per directory.** Collapsing dozens of
  directories into one entry with `directories:` collapses the PR budget too.

## Related

Part of a wider platform-engineering portfolio:
[iac-security-patterns](https://github.com/shashiprakashdubey/iac-security-patterns)
(the same "failure mode → generic sample → the test that prevents recurrence" framing, applied
to IAM, keyless CI and supply-chain admission control)
· [fake-green](https://github.com/shashiprakashdubey/fake-green)
(the general discipline behind the two guards here: the ways a check goes green without
looking, and how to prove one can fail)
· [gcp-pulumi-reference-architecture](https://github.com/shashiprakashdubey/gcp-pulumi-reference-architecture)
· [prometheus-grafana-observability](https://github.com/shashiprakashdubey/prometheus-grafana-observability)
· [platform-engineering-case-studies](https://github.com/shashiprakashdubey/platform-engineering-case-studies)

## License

MIT — see [LICENSE](LICENSE).
