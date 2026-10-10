# Releasing

How a version of Ordnung is released, and the owner's one-time setup for PyPI. Only the repository's owner
makes releases; nothing here is needed to use Ordnung or to change it.

## What a release does

Pushing a version tag such as `v0.3.0` runs [`.github/workflows/release.yml`](../.github/workflows/release.yml):

1. **It checks the tag.** The tag must be `v` + `__version__` from `src/ordnung/__init__.py`, written the way
   PyPI shows versions (`0.3.0`, `0.3.0rc1`). CHANGELOG.md must have one section for that version, headed
   `## 0.3.0 — YYYY-MM-DD`, and it must be the newest: above it there may be only an empty `## Unreleased`.
   Anything else there means the tagged commit holds changes the notes leave out. The tagged commit must be on
   `main`, and CI must have passed on it there. `scripts/release_notes.py` does the first checks. The tests
   don't run again: CI ran them on `main`.
2. **It builds the sdist and the wheel** from the tagged commit and checks them as CI's wheel job does. The
   committed web build must be the one its sources make, and the wheel must carry the web app and the demo.
   The wheel is installed into a clean venv outside the checkout, where it must report the version and rebuild
   the demo identically (`ordnung demo --check`). `twine check --strict` checks that the description renders on
   PyPI.
3. **It publishes a GitHub Release** named "Ordnung 0.3.0", with the changelog's section as its notes and both
   files attached. A version like `0.3.0rc1` is marked as a pre-release.
4. **It uploads the same two files to PyPI**, but only once you have turned that on (below). The upload uses
   Trusted Publishing: PyPI trusts this workflow, so no token is stored in the repository or anywhere else.

A wrong tag stops at the first step, before anything is built or published. These checks run from the
tagged commit's own copy of the workflow, so they catch honest mistakes; the reviewer and the tag ruleset
below stop a tag pushed on purpose from somewhere else. Each job gets only the rights it
needs: the build only reads the code, the GitHub Release is written with the run's own token, which ends with
the run, and only the PyPI job may ask for the short-lived token PyPI checks. A pull request never starts the
workflow, and a fork never uploads to PyPI.

On PyPI the project page shows the README, with its links and pictures pointing to GitHub (`pyproject.toml`,
`[tool.hatch.metadata.hooks.fancy-pypi-readme]`). They point to `main`, not to the release's tag, so a later
change to the README also changes what that page links to.

## Making a release

1. **On a branch, raise the version and its copies.** `tests/test_regressions_install.py` checks that they
   agree:
   - `__version__` in `src/ordnung/__init__.py`;
   - `npm version X.Y.Z --no-git-tag-version` in `web/` (`package.json` and `package-lock.json`);
   - `version` in the static demo's health answer, `HEALTH` in `web/src/mocks/data/system.ts`;
   - then `make openapi`, `ordnung demo --rebuild` and `make build-web`.
2. **Name the changelog's section.** In CHANGELOG.md, rename `## Unreleased` to `## X.Y.Z — YYYY-MM-DD`, with
   the day of the release. `python3 scripts/release_notes.py` prints the notes as the release will show them
   (`python3 scripts/release_notes.py Unreleased` shows them before the rename).
3. **Open a pull request** and merge it once CI passes. Wait until CI has passed on `main` too. If its run
   there was cancelled because another merge followed, run it again (*Re-run jobs*).
4. **Tag the merge commit by its hash and push the tag.** Tag that commit, not `main`'s newest one: a pull
   request merged after it holds changes the notes don't list, and the check in step 1 refuses that.

   ```bash
   git fetch origin
   git log --oneline origin/main    # the release pull request's merge commit
   git tag -a vX.Y.Z <merge commit> -m "Ordnung X.Y.Z"
   git push origin vX.Y.Z
   ```

5. **Watch Actions → Release.** If a check stops it, fix the cause on `main`, delete the tag
   (`git push origin :refs/tags/vX.Y.Z`, then `git tag -d vX.Y.Z`) and tag again. PyPI never takes the same
   version twice: once the upload has worked, a mistake is fixed in the next version.

The next change goes under a new `## Unreleased` heading again (CONTRIBUTING.md).

A pre-release works the same way, with a version such as `X.Y.Zrc1`, its own changelog section and the tag
`vX.Y.Zrc1`. `pipx install ordnung` skips it; `pipx install "ordnung==X.Y.Zrc1"` installs it.

## Turning on PyPI (once, by the owner)

You need a PyPI account with two-factor authentication. No token is ever needed.

1. **Add a pending publisher on PyPI.** On pypi.org, go to *Your account → Publishing*, add a new pending
   publisher for GitHub, and fill in:
   - PyPI project name: `ordnung`
   - Owner: `ahmedEid1`
   - Repository name: `ordnung`, the repository's name on GitHub. An older clone's remote may still say
     `new-project`, but GitHub's token names the repository as it is called now.
   - Workflow name: `release.yml`
   - Environment name: `pypi`

   A pending publisher doesn't reserve the name `ordnung`, so publish the first release soon after.
2. **Create the `pypi` environment on GitHub, before step 4.** GitHub creates an environment a job names if
   it doesn't exist yet, but without any rules. In the repository, go to *Settings → Environments → New
   environment* and name it `pypi`. Under *Deployment branches and tags*, choose *Selected branches and tags*
   and add the tag rule `v*`. Add yourself under *Required reviewers*: each upload then waits for your click,
   the last check before a version that can never be replaced. The tag rule admits any `v*` tag, wherever it
   points, and PyPI checks only the workflow's file name and the environment, so this click is what stops a
   tag that shouldn't be released.
3. **Limit who can push version tags.** Under *Settings → Rules → Rulesets*, add a tag ruleset for `v*` that
   restricts creations, updates and deletions, with only you allowed to bypass it.
4. **Turn the upload on.** Under *Settings → Secrets and variables → Actions → Variables*, add the repository
   variable `PYPI_PUBLISH` with the value `true`. Until then the PyPI job is skipped and a release goes to
   GitHub only; any other value turns uploads off again.
5. **Try it with a pre-release** if you like (`0.3.0rc1`, above): it reaches PyPI, but `pipx install ordnung`
   doesn't install it.

If PyPI refuses the upload as an untrusted publisher, compare the pending publisher's fields with the list
above: the workflow's file name and the environment's name must match exactly.

### After the first upload

Then the README can install from PyPI, in a commit of its own:

- the install lines become `pipx install ordnung   # or: uv tool install ordnung`;
- *Updating* says that `pipx upgrade ordnung` (or `uv tool upgrade ordnung`) installs the newest release from
  PyPI, and going back becomes `pipx install --force "ordnung==X.Y.Z"`;
- `test_the_readme_says_how_to_update` in `tests/test_regressions_install.py` then expects
  `pipx upgrade ordnung`.
