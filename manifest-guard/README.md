# Manifest guard: make the PR's diff match its own paper trail

## The failure mode

A Dependabot PR carries a title, a body, and `updated-dependencies:` commit trailers that
describe what it changed. It is very easy — and almost universal — to review the description
and skim the diff, because the description is *supposed* to be generated from the diff.

It is not always a complete account of it. Three real incidents, all **cross-directory
security-group PRs**:

- A PR documented five transitive bumps. It also wrote **2–3 major downgrades** of three
  runtime SDKs into a service manifest, and **injected two unrelated packages** into that
  manifest that had never been dependencies of it.
- A PR documented a single package. It also carried an **undocumented major** of a compiler
  toolchain, across two workspaces.
- A commit carried an **undocumented three-major jump** of a test utility, sitting beside a
  documented downgrade of something else.

The second-order damage is worse than the first. In the first incident the corrupted version
values were later read as the real baseline, and scoped an entire upgrade project around
recovering ground that had never actually been lost — roughly two months of work on an SDK
version the repo had already been past.

### And your version holds do not apply here

GitHub documents that `ignore` entries with `update-types` **"only affect version updates,
not security updates"**.

Read that carefully, because it is the part people miss: every `version-update:semver-major`
hold in your `dependabot.yml` is **advisory** as far as the security channel is concerned.
The security updater can and will open a PR that crosses a major you have explicitly held —
the hold you wrote to protect a peer-dependency cap simply does not apply to it.

The naive fix is a blanket `- dependency-name: x` with no `update-types`. Don't: that also
stops minors, patches and security fixes for the package, which is usually the opposite of
what you want. Keep the narrow hold, and **enforce it in CI**.

## The pattern

A workflow that runs only on Dependabot's own PRs, parses the config's `ignore` lists at the
PR head, and fails on four things:

| Finding | Meaning |
|---|---|
| `DOWNGRADE` | A dependency's floor version decreased. A dependency update should never lower a version. |
| `UNDOCUMENTED` | A manifest entry was changed, added or removed whose package name appears in **no** `updated-dependencies:` trailer on the PR. |
| `HELD MAJOR` | A major crossing for a package whose major is held in the config — **even if documented**, since this is the channel the hold doesn't reach. |
| `HELD PACKAGE` | Any change at all to a package held for *all* update types (the lockstep case). |

### Implementation choices that matter

**Parse the manifests; never diff the text.** The guard reads each changed manifest as JSON at
the merge-base and at the head, and compares the parsed dependency maps. A textual diff of a
multi-manifest PR misattributes `-`/`+` pairs across files and produces confident nonsense.

**Trailer names are quoted; manifest keys are not.** Scoped packages appear in the trailer as
`dependency-name: "@scope/pkg"` but as bare keys in the manifest. A naive `\S+` capture leaves
the quote attached and marks **every scoped package** undocumented — on a typical frontend
manifest that is most of the dependency list, which is more than enough to get the guard
switched off. So the capture handles both quote styles and the bare form explicitly:

```python
_TRAILER = re.compile(r"dependency-name:\s*(?:\"([^\"]+)\"|'([^']+)'|(\S+))")
```

**Hold sets are the union across all entries.** Holds differ per directory only because most
directories don't declare the package at all, so a union adds no false positives — and it
keeps the script free of any directory-to-manifest mapping, which is fuzzy anyway (a root
entry legitimately edits workspace manifests).

**Fail closed on an unparseable config.** A broken `dependabot.yml` is itself a defect worth
stopping on — and it's the exact state in which every hold is silently inactive.

**Read commit messages NUL-separated** (`git log --format=%B%x00`), so a multi-line commit
body can't bleed into the next one and accidentally "document" a package it never mentioned.

## Signal, not necessarily a block

Whether this can be merged past depends on your branch protection. It's worth being
deliberate about which you want:

- As a **required check**, it blocks the corruption outright, but a human pushing a legitimate
  manifest fix onto a Dependabot branch is stuck until they split it out.
- As a **signal**, a red result is visible and reviewable, and a reviewer can approve past it.

Either way the output has to explain itself well enough to act on, because the person reading
it did not write the PR. The failure text names the file, the section, the old and new values,
and what to do about it.

## Wiring

```yaml
if: github.event.pull_request.user.login == 'dependabot[bot]'
```

Human PRs skip it entirely. Lock-only Dependabot PRs pass trivially, since they change no
manifest.

Two details in [`dependabot-manifest-guard.yml`](dependabot-manifest-guard.yml) that are easy
to get wrong:

- **`fetch-depth: 0`.** The guard diffs against the merge-base with the target branch and
  reads every commit message on the PR. A shallow clone has neither.
- **The guard's own tests run first, in the same job.** An untested guard on a branch where
  someone has edited it is not evidence of anything.

## A note on the tests

The fixtures replay the incident shapes above — a documented bump beside an undocumented
major, a downgrade, a held-major crossing, an injected package.

They deliberately do **not** pin the repository's current holds. Holds get lifted when
migrations land, and a test that asserts "package X is held" goes red on exactly those
transitions — training everyone to edit the test until it passes, which is how a guard dies.
The tests pin the *logic*, with holds supplied as fixture input.

## Files

- [`check_dependabot_manifest_edits.py`](check_dependabot_manifest_edits.py) — the guard
- [`test_check_dependabot_manifest_edits.py`](test_check_dependabot_manifest_edits.py) — tests
  for the pure functions, with fixtures replaying each incident shape
- [`dependabot-manifest-guard.yml`](dependabot-manifest-guard.yml) — the workflow
