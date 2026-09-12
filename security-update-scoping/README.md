# Security-update scoping

## The failure mode

This is the smallest pattern here and the one with the best effort-to-payoff ratio, because
it removes the *blast radius* that makes the [manifest-guard](../manifest-guard/) incidents
possible in the first place.

If the repository has **grouped security updates** enabled (a repo-level setting, on by
default for many setups) and your config declares no security group of its own, Dependabot
builds **one security PR per ecosystem, spanning every directory it covers**.

That single PR:

- touches manifests in directories whose owners have nothing to do with the advisory,
- runs the package manager's resolver across all of them at once, so a resolution decision
  made for one directory is written into the others,
- and is reviewed — realistically — by whoever is on rota, against a description that lists
  advisories, not files.

Every cross-directory manifest corruption worth investigating turns out to be one of these.
That isn't a coincidence: a cross-directory security-group PR is usually the *only* thing in
the repository that routinely spans directories, so it is the only vehicle that can carry a
bad resolution from one manifest into another.

## The pattern

Give **every** entry its own security group, scoped to that entry's directory:

```yaml
- package-ecosystem: 'npm'
  directory: '/service-a'
  schedule:
    interval: 'daily'
  groups:
    production-patches:
      dependency-type: 'production'
      update-types: ['patch']
    # ... your version-update groups ...

    # Scopes security updates to THIS directory. Without it, the repo-level
    # "grouped security updates" default builds ONE npm PR spanning every
    # directory, which is the blast radius behind every cross-directory
    # manifest corruption.
    security:
      applies-to: security-updates
      patterns: ['*']
```

`applies-to` is the whole trick. A group is `applies-to: version-updates` by default; setting
it to `security-updates` makes that group handle the security channel — and because the group
lives inside an entry that already declares a single `directory`, the resulting PR is confined
to it.

The result is one security PR per directory. More PRs, each one small, reviewable by the
people who own that directory, and unable to write into a manifest it has no business
touching.

> It has to be on **every** entry. One entry left without a security group falls back to the
> repo-level grouping for its ecosystem, which is the behaviour you were trying to remove.

## Interaction with the other patterns

- **Version updates are unaffected.** `applies-to: security-updates` is a separate channel
  from the patch/minor/major grouping in
  [grouping-that-stays-reviewable](../grouping-that-stays-reviewable/); the two coexist in the
  same `groups:` block and neither one sees the other's updates.
- **Scoping is not enforcement.** This narrows what a security PR can touch; it does nothing
  about a security PR crossing a semver hold *within* its own directory, because
  `update-types` holds never constrained the security channel to begin with. That still needs
  [manifest-guard](../manifest-guard/). The two are complementary: one bounds the blast
  radius, the other checks the contents.
- **Watch the PR budget.** One security PR per directory means more concurrent PRs. If
  `open-pull-requests-limit` is tight, Dependabot silently stops opening them — see the note
  on PR budgets in [grouping-that-stays-reviewable](../grouping-that-stays-reviewable/).

## Files

- [`dependabot.yml`](dependabot.yml) — a multi-directory config with per-directory security
  scoping on every entry.
