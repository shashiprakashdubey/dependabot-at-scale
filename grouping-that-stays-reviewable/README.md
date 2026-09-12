# Grouping that stays reviewable

## The failure mode

The default advice is "group your Dependabot updates so you get fewer PRs". Taken literally,
you write this:

```yaml
groups:
  dependencies:
    patterns: ['*']
```

and eventually you get a single PR titled *"bump the dependencies group with 63 updates"*.

That PR is unreviewable — nobody reads 63 changelogs — and usually unmergeable, because
somewhere in those 63 is a major version with a breaking change that fails CI. So it sits.
The next week's PR supersedes it. The backlog compounds, and the repo ends up *less* current
than it was before grouping was switched on. The damage from a bad grouping policy is not a
bad merge; it's the **absence of merges**.

The cause is that `patterns: ['*']` with no `update-types` sweeps **majors into the batch**.

## The pattern

Group by *risk class*, not by "everything":

- **patch** and **minor** batch together — high volume, low individual risk, one review.
- **majors are in no group at all**, so they fall through as individual PRs and each gets a
  deliberate look at its breaking changes.
- **dev dependencies** batch separately from runtime, so a linter bump never waits on a
  review of a runtime SDK.

```yaml
groups:
  production-patches:
    dependency-type: 'production'
    update-types: ['patch']
  production-minors:
    dependency-type: 'production'
    update-types: ['minor']
  development-deps:
    dependency-type: 'development'
    update-types: ['minor', 'patch']
```

Separating patches from minors is a judgement call — it's worth it once the volume is high
enough that you want to merge patches on sight and read minors properly.

### The exception: lockstep families

Isolating every major is right *except* for package families that must cross a major
together. A toolchain like Babel is the classic case: `@babel/core` and every preset share a
version line, and Dependabot's individual per-package major PRs are each an unmergeable
mixed-major install. Four broken PRs is a worse signal than one coherent one.

So those families get a **dedicated major group**:

```yaml
  babel-major:
    patterns: ['@babel/*']
    update-types: ['major']
```

One PR, one CI run, one reviewable answer to "does the toolchain still build".

### The routing gotcha: `dependency-type` vs `patterns`

`dependency-type: production|development` only works where the **manifest declares the
split**. Poetry (`[tool.poetry.dependencies]` vs `[tool.poetry.group.*.dependencies]`) and
Pipenv do. A bare `requirements.txt` does **not**.

This bites in a mixed repo. If some directories are Poetry and others are plain
`requirements.txt`, a `dependency-type`-based policy leaves every dependency in the
`requirements.txt` directories matching **neither** group — so they fall through as
individual PRs and burn the whole PR budget. Where manifest shapes are mixed, route on
`patterns` instead, with a true catch-all:

```yaml
groups:
  toolkit:
    patterns: ['pulumi', 'pulumi-*']
    update-types: ['patch', 'minor']
  everything-else:
    patterns: ['*']          # true catch-all: nothing can end up unrouted
    update-types: ['patch', 'minor']
```

**Order matters.** A dependency joins the *first* group it matches, so the specific pattern
must precede the catch-all.

Note what is still absent from both groups: `major`. The fall-through is the point.

### Raise the PR limit when you split majors out

Splitting majors out of the batch means more concurrent PRs, so the cap has to leave room for
them alongside the grouped ones. A limit left at the old value doesn't error — Dependabot
just stops opening PRs, which is the same under-delivery you were trying to fix, relocated
from the grouping policy to the PR budget.

> `open-pull-requests-limit` is **per updates entry**, not per directory. If you use
> `directories:` to collapse a few dozen directories into one entry (see
> [directory-coverage](../directory-coverage/)), that one limit is the aggregate across all of
> them. A limit of 10 across forty directories is a quarter of a PR each.

## Holds belong next to the thing they hold

An `ignore` entry with no comment becomes permanent. Every hold should record **why**, and
**what lifts it**:

```yaml
ignore:
  # Hold the base image on the current runtime major until the deliberate
  # migration; lift as part of that work. Patch/digest refreshes still flow,
  # so security fixes for the current major are unaffected.
  - dependency-name: 'python'
    update-types:
      - 'version-update:semver-minor'
      - 'version-update:semver-major'

  # Type packages that describe a runtime must track the DEPLOYED runtime
  # major, not the newest published one — otherwise the compiler type-checks
  # against APIs that do not exist at runtime and passes code that crashes in
  # production. The trigger to bump is upgrading the runtime itself.
  - dependency-name: '@types/node'
    update-types: ['version-update:semver-major']
```

Two properties of `ignore` that decide how you write these:

1. **Keep the `update-types`.** A blanket `- dependency-name: x` with no `update-types` holds
   *everything* — including patches and security fixes. Hold the major, not the package,
   unless the package genuinely may only move in lockstep with something else.
2. **`update-types` does not constrain security updates.** GitHub documents this explicitly.
   Every semver hold in your config is advisory against the security channel — which is what
   [manifest-guard](../manifest-guard/) exists to fix.

## Files

- [`dependabot.yml`](dependabot.yml) — a complete, commented config showing all of the above.
