# Releasing

How a version of Ordnung is released, and the owner's one-time setup for PyPI. Only the repository's owner
makes releases; nothing here is needed to use Ordnung or to change it.

## In one minute

- **A release is a pushed tag.** `vX.Y.Z` on the release pull request's merge commit runs `release.yml`: it checks
  the tag, builds, publishes a GitHub Release and, once you turn it on, uploads to PyPI
  ([what a release does](#what-a-release-does)).
- **Five steps:** raise the version, name the changelog's section, merge once CI passes (on `main` too), tag the
  merge commit, watch the run ([making a release](#making-a-release)).
- **A wrong tag stops before anything is built or published.** Once the GitHub Release exists, keep the tag
  ([step 5](#making-a-release)).
- **PyPI never takes the same version twice:** once the upload has worked, a mistake is fixed in the next version.
- **Once, by the owner:** GitHub Pages for the online demo, the repository's settings, and PyPI
  ([online demo](#the-online-demo-turned-on-once-by-the-owner),
  [settings](#repository-settings-once-by-the-owner), [PyPI](#turning-on-pypi-once-by-the-owner)).

[What a release does](#what-a-release-does) · [Making a release](#making-a-release) ·
[The online demo](#the-online-demo-turned-on-once-by-the-owner) ·
[Repository settings](#repository-settings-once-by-the-owner) · [Turning on PyPI](#turning-on-pypi-once-by-the-owner)

## What a release does

Pushing a version tag such as `vX.Y.Z` runs [`.github/workflows/release.yml`](../.github/workflows/release.yml):

1. **It checks the tag.** The tag must be `v` + `__version__` from `src/ordnung/__init__.py`, written the way
   PyPI shows versions (`X.Y.Z`, `X.Y.Zrc1`). CHANGELOG.md must have one section for that version, headed
   `## X.Y.Z — YYYY-MM-DD`, and it must be the newest: above it there may be only an empty `## Unreleased`.
   Anything else there means the tagged commit holds changes the notes leave out. The tagged commit must be on
   `main`, and CI must have passed on it there. `scripts/release_notes.py` does the first checks. The tests
   don't run again: CI ran them on `main`.
2. **It builds the sdist and the wheel** from the tagged commit and checks them as CI's wheel job does. The
   committed web build must be the one its sources make (a job of its own rebuilds it and compares it byte
   for byte, so the npm packages that build runs never run where the files PyPI gets are built), and the
   wheel must carry the web app and the demo.
   The wheel is installed into a clean venv outside the checkout, where it must report the version and rebuild
   the demo identically (`ordnung demo --check`). `twine check --strict` checks that the description renders on
   PyPI.
3. **It publishes a GitHub Release** named "Ordnung X.Y.Z", with the changelog's section as its notes and both
   files attached. A version like `X.Y.Zrc1` is marked as a pre-release.
4. **It uploads the same two files to PyPI**, but only once you have turned that on (below). The upload uses
   Trusted Publishing: PyPI trusts this workflow, so no token is stored in the repository or anywhere else.

A wrong tag stops at the first step, before anything is built or published.

<details>
<summary>What stops a tag pushed on purpose from somewhere else, and each job's rights</summary>

These checks run from the
tagged commit's own copy of the workflow, so they catch honest mistakes; the reviewer and the tag ruleset
below stop a tag pushed on purpose from somewhere else. Each job gets only the rights it
needs: the build only reads the code, the GitHub Release is written with the run's own token, which ends with
the run, and only the PyPI job may ask for the short-lived token PyPI checks. A pull request never starts the
workflow, and a fork never uploads to PyPI.

</details>

On PyPI the project page shows the README, with its links and pictures pointing to GitHub (`pyproject.toml`,
`[tool.hatch.metadata.hooks.fancy-pypi-readme]`). They point to `main`, not to the release's tag, so a later
change to the README also changes what that page links to.

## Making a release

1. **On a branch, raise the version and its copies.** `tests/test_regressions_install.py` checks that they
   agree:
   - `__version__` in `src/ordnung/__init__.py`;
   - `npm version X.Y.Z --no-git-tag-version` in `web/` (`package.json` and `package-lock.json`);
   - `version` in the static demo's health answer, `HEALTH` in `web/src/mocks/data/system.ts`;
   - the version in the bug report template's placeholder (`.github/ISSUE_TEMPLATE/bug_report.yml`);
   - then `make openapi`, `ordnung demo --rebuild --no-serve` and `make build-web`.

   If a screen or the tour changed since the last release, capture the README's media on this branch, once,
   after the last fix round: `make capture` writes them into `docs/assets` and names the contact sheets to
   look at before you commit them (`scripts/capture.sh --only shots` takes the pictures alone; CONTRIBUTING.md
   says which to commit).
2. **Name the changelog's section.** In CHANGELOG.md, rename `## Unreleased` to `## X.Y.Z — YYYY-MM-DD`, with
   the day of the release. `python3 scripts/release_notes.py` prints the notes as the release will show them
   (`python3 scripts/release_notes.py Unreleased` shows them before the rename).
3. **Open a pull request** and merge it once CI passes. Wait until CI has passed on `main` too. If its run
   there was cancelled because another merge followed, run it again (*Re-run jobs*); if it failed only because
   its macOS job was cancelled while no runner came, run that job again (*Re-run failed jobs*).
4. **Tag the merge commit by its hash and push the tag.** Tag that commit, not `main`'s newest one: a pull
   request merged after it holds changes the notes don't list, and the check in step 1 refuses that.

   ```bash
   git fetch origin
   # the release PR's merge commit
   git log --oneline origin/main
   git tag -a vX.Y.Z <merge commit> \
     -m "Ordnung X.Y.Z"
   git push origin vX.Y.Z
   ```

5. **Watch Actions → Release.**
   - **Before the GitHub Release exists.** If the build job stops, or the GitHub Release job fails before the
     Release exists, nothing is published yet: delete the tag (`git push origin :refs/tags/vX.Y.Z`, then
     `git tag -d vX.Y.Z`), remove the cause and tag again.
     - **A fix that needs a commit** is merged into `main` and its merge commit tagged, as in step 4 (the fix's
       changelog line goes in the version's section, not under `## Unreleased`), but only while `main` lists
       nothing under `## Unreleased`.
     - **Once `main` lists something under `## Unreleased`,** the tag can go back only on the same commit, which
       mends only a cause outside that commit (CI not yet passed there, say).
     - **For that case** the run itself can also be run again (*Re-run all jobs*) once CI has passed, as its
       message says.
   - **Once the GitHub Release exists, keep the tag:** the Release belongs to it (deleting the tag turns a
     published Release into a draft), and the PyPI job is run again on the same run, not from a new tag. If only
     the PyPI job failed or its review was rejected, fix the cause and run it again on the same run (*Re-run
     failed jobs*). A re-run uploads the artifact `dist` the build job stored, and the jobs before it don't run
     again. A review still waiting is given on the run's page (GitHub fails the job after 30 days).
   - **Time limits.** GitHub re-runs a run only within 30 days of its start, and keeps that artifact 90 days
     unless the repository or organisation keeps artifacts for less. After either limit the version reaches PyPI
     only as the next one.
   - **PyPI off, and never twice.** A version tagged while PyPI was off stays on GitHub only (its PyPI job is
     skipped, and the run counts as passed): turn PyPI on before you tag a version meant for PyPI. PyPI never
     takes the same version twice: once the upload has worked, a mistake is fixed in the next version.

The next change goes under a new `## Unreleased` heading again (CONTRIBUTING.md).

<details>
<summary>A version named before its tag (as 0.4.0 was), and <code>main</code>'s first-parent line</summary>

- A version can be named a while before it is tagged, as 0.4.0 was at the freeze of the pre-registered
  evaluation, whose publication its tag waited for. Its section then says so ("The `vX.Y.Z` tag and its GitHub
  release follow once …; until then, install this version by its commit"), and until the pull request whose
  merge gets the tag is merged, every change goes under `## X.Y.Z`, not under `## Unreleased`, which stays
  empty: step 1 refuses a tag with anything listed above the version. A change merged after that merge goes
  under `## Unreleased` again, even while the tag is still to be pushed: the tag goes on that merge commit, not
  on `main`'s newest one.
- The pull request whose merge is tagged sets the section's date to the day of the release and drops that
  sentence: `scripts/release_notes.py --tag` refuses a section that still has it.
- For 0.4.0 that is not the pull request that publishes the evaluation but the one after it, which adds
  `evals/preregistration/published-0.4.0.json`: its merge gets the `v0.4.0` tag. The publishing pull request is
  merged with a merge commit, never squashed or rebased (the deviations name its checkpoint commits), and the
  record names that merge commit on `main`. Once the amendment is posted on the pre-registration issue,
  `python -m scripts.prereg_published --write-record <merge commit> <the amendment's URL>` writes it, with the
  sha256 of the files that check the pre-registration from then on, on a branch made from `main` after that
  merge; it runs the record's checks first and writes nothing if one fails (`--check-record` runs them on the
  committed record).
- From that merge on, `main` moves only through pull requests merged on GitHub, never by a direct push: the
  record's checks need the publish commit on `main`'s first-parent line. If a push ever moves `main` so that it
  leaves that line (a `git pull` merge pushed from an old branch), a merge with the last good `main` as first
  parent puts it back, pushed as a fast-forward; the record and the amendment stay as they are.

</details>

A pre-release works the same way, with a version such as `X.Y.Zrc1`, its own changelog section and the tag
`vX.Y.Zrc1`. Once PyPI is on (below), `pipx install ordnung` skips it and `pipx install "ordnung==X.Y.Zrc1"`
installs it; until then it is installed by its tag, as any release is
([the guide's *Updating*](guide.md#updating)).

## The online demo (turned on once, by the owner)

The online demo at <https://ahmedeid1.github.io/ordnung/> is the web app's browser-only build on the static
demo's letters. [`.github/workflows/demo.yml`](../.github/workflows/demo.yml) builds it for each pull request
that changes `web/` and publishes it on GitHub Pages from `main`. So a release's version shows there once its
pull request is merged, with no step of its own. Anyone can open it; it needs no account.

GitHub Pages has to be turned on once. Under *Settings → Pages → Build and deployment*, choose
*Source: GitHub Actions*. Then run *Actions → Online demo → Run workflow* on `main`, or merge a change to
`web/`. Until then the workflow's deploy job fails, and the link shows GitHub's "404" page.

## Repository settings (once, by the owner)

What only the owner can set on GitHub, written down so that it can be checked or set again:

- *About* (the gear beside it on the repository's page):
  - *Description*: "Local-first AI secretary for paperwork in Germany: Claude reads your letters, tested code
    computes each deadline with the law behind it, and a held-out benchmark against LLM baselines replays with
    zero tokens." (209 characters; GitHub allows 350.)
  - *Website*: `https://ahmedeid1.github.io/ordnung/`, the online demo.
  - *Topics*: `claude`, `llm`, `llm-evaluation`, `ai-agents`, `mcp`, `local-first`, `privacy`, `germany`,
    `paperwork`, `fastapi`, `react`, `sqlite`; no rag topic, since Ordnung has no vector database
    ([ADR 0005](decisions/0005-sqlite-fts-local-first.md)), and none for Python or TypeScript, which GitHub's
    language bar shows.
  - *Include in the home page*: *Releases* on, *Packages* off while there are none.
- *Social preview* (*Settings → General*): a picture of 1280 × 640 px that shows the app, so a link shared in a
  chat or a post shows it instead of GitHub's own card.
- *Pull Requests* (*Settings → General*): merge commits take the default message *Pull request title and
  description*, so `main`'s history reads as the pull requests' titles; and *Automatically delete head
  branches* is on (pushing to a deleted branch again creates it anew).
- *Branch protection* for `main` (*Settings → Branches*): require a pull request before merging, and allow
  neither direct pushes nor force pushes, so `main`'s first-parent line keeps the commit that published the final
  run (see *Making a release* above).
- *Private vulnerability reporting*, in the repository's security settings: on. SECURITY.md sends reporters to
  it, and to the *Security contact* issue form only while it is off.

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
5. **Try it with a pre-release** if you like (the next version's, such as `X.Y.Zrc1`, above): it reaches PyPI,
   but `pipx install ordnung` doesn't install it.

If PyPI refuses the upload as an untrusted publisher, compare the pending publisher's fields with the list
above: the workflow's file name and the environment's name must match exactly.

### After the first upload

Then the README and the guide (`docs/guide.md`) can install from PyPI, in a commit of its own:

- the README's first two code lines become `uv tool install ordnung` and `# or: pipx install ordnung`, and the
  guide's *Install and run* line becomes `uv tool install ordnung   # or: pipx install ordnung`, with its note on
  the built web app;
- the guide's *Updating* says that `pipx upgrade ordnung` (or `uv tool upgrade ordnung`) installs the newest
  release from PyPI, and going back becomes `pipx install --force "ordnung==X.Y.Z"`;
- the test of *Updating* in `tests/test_regressions_install.py` then expects `pipx upgrade ordnung`.
