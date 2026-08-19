# Releasing

Merging `develop` into `master` is the release. That push builds everything,
tags the commit, and publishes one GitHub Release carrying every artifact.

Nothing else releases. There is no separate "publish the extension" branch and
no manual tag.

---

## The two branches

| Branch    | What it is                                                     |
| --------- | -------------------------------------------------------------- |
| `develop` | where work lands. Every push runs the test workflow.           |
| `master`  | what is released. Every push runs the release workflow.        |

Work always starts on `develop`. Nothing is committed straight to `master`, so
there is never anything to backport.

## The version numbers

Every component owns its own number, and it moves **only when that component
changed**:

| Component   | Number lives in           | Published to      |
| ----------- | ------------------------- | ----------------- |
| `core`      | `core/pyproject.toml`     | PyPI              |
| `js`        | `js/package.json`         | npm               |
| `extension` | `extension/manifest.json` | Chrome / Firefox  |
| `host`      | `host/Cargo.toml`         | the release page  |
| `release`   | `VERSION`                 | the git tag       |

`VERSION` numbers the **release** — the page all of them are attached to — so it
moves every time. The desktop app has no number of its own: it is a bundle of
core and host, so it ships as the release.

> **Why not one number for everything?** Because a version that moves for
> nothing means an extension store review, a PyPI upload and an npm release
> whose changelog is empty. A user who sees a new number should find something
> new in it.

See what they all are:

```bash
python scripts/bump_version.py
```

Move one:

```bash
python scripts/bump_version.py core          # 0.1.0 -> 0.1.1  (a fix)
python scripts/bump_version.py core minor    # 0.1.0 -> 0.2.0  (a feature)
python scripts/bump_version.py core major    # 0.1.0 -> 1.0.0  (a break)
python scripts/bump_version.py core 2.0.0    # or say the number
```

---

## Releasing, step by step

### 1. Run the manual checks

[release-checklist.md](release-checklist.md) — the parts no CI can do, because
they need a real token in a real machine. Do this while there is still time to
fix something.

### 2. Bump what changed

Work out what actually moved since the last release:

```bash
git diff --stat $(git describe --tags --abbrev=0) -- core/ js/ extension/ host/
```

Bump each of those, then the release number, which always moves:

```bash
python scripts/bump_version.py core
python scripts/bump_version.py release
```

> **Note:** you cannot forget this. The `prepare` job compares every folder
> against the last tag and fails the release if one changed without its number
> moving.

### 3. Commit on `develop`

```bash
git commit -am "chore(release): v0.1.1"
git push
```

### 4. Merge `develop` into `master`

Open a PR from `develop` to `master` and merge it. **That merge is the
release.**

### 5. Watch it

```bash
gh run watch
```

| Stage       | What happens                                                        |
| ----------- | -------------------------------------------------------------------- |
| `prepare`   | reads every version, refuses a tag that exists or a missed bump      |
| builds      | host, desktop, extension, core, js — in parallel                     |
| `publish`   | checksums, Homebrew files, `latest.json`, the tag, the Release       |

A failed build leaves **no tag behind**, because the tag is created last. Fix
and merge again.

### 6. Upload what changed

CI builds and attaches everything. It uploads to **no registry** — that is still
a person's decision. Take the files off the release page:

| Changed     | Upload                                    | Where                    |
| ----------- | ----------------------------------------- | ------------------------ |
| `core/`     | `docsigner_core-….whl` and `.tar.gz`      | PyPI                     |
| `js/`       | `docsigner-….tgz`                         | npm                      |
| `extension/`| `docsigner-extension-…-chrome.zip`        | Chrome Web Store         |
|             | `docsigner-extension-…-firefox.zip`       | Firefox Add-ons          |
| macOS       | `docsigner.rb`, `docsigner-host.rb`       | the Homebrew tap         |

**Only upload what changed.** If core's number did not move, its file is the
same build as last time and PyPI will refuse it anyway.

---

## Building without releasing

Actions tab → **Release** → **Run workflow**. Builds every artifact and
publishes nothing, so you can look at the files first.

---

## Two things that bite

**A version only ever goes up.** Two components can never be re-aligned once
one has passed the other. Settle a number before it is first published, not
after.

**A published number is spent forever.** PyPI and npm refuse a second upload of
the same version, even after unpublishing. A bad `0.1.1` costs you `0.1.1`.

**Published versions will have gaps** — `core` may go `0.1.0` then `0.4.0`
because it did not change in between. That is intended, not a mistake. Semver
never required them to be contiguous. The cost is that the number alone does not
say what changed, so the release notes have to.
