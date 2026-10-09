# Contributing to Ordnung

Thank you for helping. This page says how to set up a checkout, which checks to run, and how changes
are written here. A security problem goes to [SECURITY.md](SECURITY.md), never to an issue.

## Real letters stay out

**Never commit, attach or paste real letters or personal data**: not in code, tests, fixtures, issues,
pull requests, screenshots or logs, and not your own either. Everything in this repository is made
up: the sample life the demo shows (`src/ordnung/demo/samples/`, every page marked SPECIMEN), the
benchmark's letters (`evals/dataset/`) and the text in the tests. Show a problem with `ordnung demo`
or a letter you write yourself, and describe a real letter in your own words.

## Setting up

You need Python 3.11 or newer, [uv](https://docs.astral.sh/uv/) and Node.js 20.19+ or 22.12+ (`nvm use`
picks the one in `.nvmrc`; `web/package.json` says the same).

```bash
make install     # .venv with the dev extras at the versions in constraints.txt, and web/node_modules (npm ci)
make serve       # the API and the built web app on http://127.0.0.1:8765
make web-dev     # the Vite dev server with hot reload (it sends /api to `make serve`)
make demo        # the sample life with recorded answers: no Claude needed, zero tokens
```

Reading your own letters needs Claude Code, signed in (see the README). The tests never call Claude:
they use a fake model backend, the end-to-end tests a fake `claude` (`tests/fake_claude.py`), and the
demo and benchmarks replay recorded answers. Once a week CI checks that a freshly installed Claude Code
still takes every flag Ordnung passes (`scripts/check_claude_flags.py`), without signing in.

## Checks

`make check` runs what most changes need: ruff (lint and format) and mypy, the backend tests (the fast
ones with coverage, then the slow ones), and the web app's ESLint, type check and Vitest tests. CI runs
more; run the ones near your change before you open a pull request:

```bash
make check
# the rules engine keeps 100 % line and branch coverage
.venv/bin/pytest tests/test_rules_*.py --cov=ordnung.rules --cov-branch --cov-report=term-missing:skip-covered --cov-fail-under=100
# both benchmarks, replayed (deterministic, zero tokens, no results file written); CI also replays the
# holdout, holdout2 and dev splits and the numbers without the sender's Land
.venv/bin/ordnung eval --min-accuracy 0.98 --max-dangerous-late 0
.venv/bin/python -m evals.ask --min-accuracy 0.85 --min-abstention 0.85 --max-unsupported 0 --max-attack-success 0 --known-attack cite-rent-for-library-overview --check-docs
# the demo rebuilds identically from the samples and recordings
.venv/bin/ordnung demo --check
# Playwright: the demo, then the real app reading with a fake Claude (installs Chromium first)
make e2e
```

These are CI's commands and thresholds (`.github/workflows/ci.yml`). A few more things CI checks:

- **The built web app is committed** (`src/ordnung/web/dist`), so an install from git needs no Node.
  After changing `web/`, run `make build-web` and commit the rebuilt folder in a commit of its own;
  CI fails while it is older than the sources (`web/scripts/source-hash.mjs`).
- **The API and the web app's types match.** After changing a route or a schema, `make openapi`
  writes `web/openapi.json` and `web/src/api/schema.d.ts` again.
- **The docs say what the code does.** `tests/test_docs_claims.py` checks the README's and docs'
  numbers and statements against the code; change the docs in the same pull request.

## Benchmarks and recorded answers

The model answers the demo and both benchmarks show are recordings of real runs (`evals/recorded/`,
`src/ordnung/demo/fixtures/`). Each is stored under a key made from what the call is for, the
prompt's version, the model and what was sent
([ADR 0004](docs/decisions/0004-replay-fixtures-and-deterministic-ids.md)). CI replays them: a
replay scores the recorded answers with the checked-out code, so a change to the rules engine or to a
check shows in the numbers at once, and costs nothing.

- The numbers in the README and in `docs/` come from the results files a run or replay writes
  (`evals/results/`), never typed by hand; tests compare the docs with those files.
- Recording new answers calls Claude with your own account and costs tokens. It is done on purpose,
  when a prompt or what is sent to Claude changes, never as part of an ordinary change. If a replay
  misses a recording after your change, say so in the pull request instead of recording.

## Tests

- Write the test first and watch it fail, then make the change. The first version's review rounds
  proved every bug and security finding with a failing test before fixing it; keep doing that.
- Name a test by the behaviour it pins, the way the files around it do
  (`test_a_missing_asset_is_a_404_not_the_app_page`).
- A test that replays every recording, times pages or builds the web app is marked `slow`
  (`make check` runs those too).

## Dependencies

- **Python**: CI and `make install` install the versions in `constraints.txt`, which
  `make constraints` writes from `pyproject.toml`. To move every package to its newest version, run
  `make constraints CONSTRAINTS_ARGS=--upgrade`, then `make install` and the checks, and commit
  `constraints.txt`. The samples' libraries (fpdf2, fonttools, pillow, pypdfium2) stay at the versions
  in the samples' manifest, because the sample letters regenerate byte for byte only with those;
  `make constraints` keeps them. The floors in `pyproject.toml` are what CI's "lowest" job installs.
- **Web packages and GitHub Actions**: Dependabot opens update pull requests every week
  (`.github/dependabot.yml`). One for `web/` changes `package-lock.json`, so run `make build-web` and
  commit `src/ordnung/web/dist` on its branch before CI passes.
- CI's weekly "latest" job tests every Python package at its newest version, and its dependency audit
  checks `constraints.txt` and the web app's packages for known vulnerabilities.

## Commits and pull requests

- A commit message is one plain English line saying what changed, as someone using or reading the
  app would put it: "Read again never queues a second reading of the same letter". An area and a
  colon may come first: "Windows: the lock message names the process holding the data folder",
  "Docs: …". The rebuilt web app goes in a commit of its own: "Rebuild the web app for …".
- A change people will notice gets a line under "Unreleased" in [CHANGELOG.md](CHANGELOG.md). A design
  decision gets a short record in [docs/decisions/](docs/decisions/).
- Pull requests go to `main`, and CI must pass. Say what changed and how you checked it, and keep
  real letters and personal data out of the description too.
