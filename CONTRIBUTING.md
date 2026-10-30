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
picks the one in `.nvmrc`; `web/package.json` says the same). Use 22.12+ for the browser checks
(`make e2e`, `make ui-audit`): their accessibility checker (`@axe-core/playwright`) asks for it.

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

`make check` runs what most changes need: ruff (lint and format) and mypy (strict, over the package and
`evals/`), the backend tests (the fast ones with coverage, then the slow ones), and the web app's ESLint,
type check and Vitest tests. CI runs more; run the ones near your change before you open a pull request:

```bash
make check
# the rules engine keeps 100 % line and branch coverage
.venv/bin/pytest tests/test_rules_*.py --cov=ordnung.rules --cov-branch --cov-report=term-missing:skip-covered --cov-fail-under=100
# both benchmarks, replayed (deterministic, zero tokens, no results file written); CI also replays the
# holdout, holdout2 and dev splits and the numbers without the sender's Land
.venv/bin/ordnung eval --min-accuracy 0.98 --max-dangerous-late 0
.venv/bin/python -m evals.ask --min-accuracy 0.85 --min-abstention 0.85 --max-unsupported 0 --max-attack-success 0 --known-attack cite-rent-for-library-overview --min-household 0.8 --check-docs
# the demo rebuilds identically from the samples and recordings
.venv/bin/ordnung demo --check
# Playwright: the demo, then the real app reading with a fake Claude (installs Chromium first)
make e2e
# as CI's end-to-end job, with Tesseract and its German language data installed: the real app also finds a
# private photo by the words Ordnung reads in it (ADR 0024)
ORDNUNG_E2E_OCR=on make e2e
```

These are CI's commands and thresholds (`.github/workflows/ci.yml`). A few more things CI checks:

- **The built web app is committed** (`src/ordnung/web/dist`), so an install from git needs no Node.
  After changing `web/`, run `make build-web` and commit the rebuilt folder in a commit of its own;
  CI fails while it is older than the sources (`web/scripts/source-hash.mjs`).
- **The API and the web app's types match.** After changing a route or a schema, `make openapi`
  writes `web/openapi.json` and `web/src/api/schema.d.ts` again.
- **The docs say what the code does.** `tests/test_docs_claims.py` checks the README's and docs'
  numbers and statements against the code; change the docs in the same pull request.
- **Text in pictures stays off in tests.** Every test runs with `ORDNUNG_OCR=off` (`tests/conftest.py`), so a
  Tesseract installed on your computer reads none of their letters; the engine's tests use a fake one
  (`tests/fake_tesseract.py`). A test that needs it on unsets the variable itself (`monkeypatch.delenv`), as the
  tests of the Settings switch do (`tests/test_picture_text_switch.py`).

**Writing an end-to-end test.** Before the next key press or click, wait for what the person sees (a toast,
a status line, a button that is enabled again), not only for focus. Read the API with `apiGet`, or pass
`READ` to `page.request.get`: it retries a connection the server dropped, and a change is never retried.
Run the tests with Playwright's own Chromium (`make browser` installs it): an older build moves focus off a
disabled button at once and hides this kind of race.

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
- **Digest files and recordings.** `_code_digest` in `evals/conditions.py` hashes the code a benchmark prediction
  depends on: every Python file of `src/ordnung` and `evals/` (and the versions of the libraries that read a
  letter). It keys only your local prediction cache and the fingerprint written into a new results file, so a
  code change moves it and needs no recording by itself. A recording is needed only
  when what is sent changes: a prompt's text or version, a schema Claude is given, what a request's key holds
  (a letter's text, the date, the ledger Ask reads) or what Ask's tools return. A replay shows which: it misses
  the recordings whose requests changed, the prompts locks (`prompts.lock.json`: each prompt's and schema's
  hash, and for Ask also its tools, server instructions and cost cap) refuse a changed text under the same
  version, and the Ask benchmark and `ordnung demo --check` answer every recorded tool call again and name the
  answers whose tool results changed.
- **Recording, when it is time.** Record from a checkout with its own virtual environment (`uv venv` and `uv pip
  install -e ".[dev,eval]" -c constraints.txt` in it), never through `PYTHONPATH`: Ask's MCP server is started
  with that environment's Python and runs whatever it has installed. Keep `ORDNUNG_CLAUDE_MODEL` unset, so every
  call runs on the recorded model, and run one recorder at a time. `python -m evals.ask --prune-stale` deletes
  the Ask answers that went stale, and `python -m evals.ask --live` records only what is missing; the demo
  records with `ORDNUNG_RECORD=1 ordnung demo --live --rebuild --no-serve`, and a benchmark run of the test
  split takes `--no-docs` so it leaves `docs/evals.md` alone. Right after, replay what you recorded and check
  that nothing is stale or missing, then say in the pull request what was recorded and what it cost.
- **The recording harness** (`evals/harness.py`, the same for `python -m evals.run` and `python -m evals.ask`).
  `--max-cost-usd` starts no new call once a step's calls cost that much (counting what its ledger says earlier
  runs of the same command spent), `--wait-on-limit` waits through a usage limit for up to that many hours instead
  of stopping, and `--repeat N` records run N (2 and up) of the same requests under keys of its own. Every live
  call adds a line to `ledger.jsonl` beside the recordings (commit it with them), every recording's request is
  locked in `requests.lock.json` (`python -m evals.harness lock-requests --check`, and `diff-requests <ref>` says
  what changed), and one recorder runs at a time: a recorder that died leaves its lock, which `python -m
  evals.harness unlock` frees once its process is gone. A replay recomputes every prediction; it reads the
  prediction cache only with `--resume`. A recording is built for the day it is recorded: the claude CLI tells the
  model the computer's date, so letters or a ledger pinned to another day would show it two todays, and a live run
  refuses them (`python -m evals.ask --set heldout --today <day>` builds the held-out Ask set for that day); only a
  smoke into a scratch `--recorded-dir`, thrown away, passes `--allow-another-today`.

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
  (`.github/dependabot.yml`): minor and patch updates together, each major on its own. One for `web/`
  changes `package-lock.json`, so CI passes only once `make build-web` has run and `src/ordnung/web/dist`
  is committed on its branch; or fold the updates into a pull request of your own. TypeScript majors are
  skipped until the packages that need TypeScript (openapi-typescript, typescript-eslint) take them: a test
  in `tests/test_repo_hygiene.py` fails then, saying to remove the rule. `ci.yml` names actions by their
  major version (`actions/checkout@v7`), and `release.yml` pins each to a commit with its version beside it;
  keep both on the same major (`tests/test_release_workflow.py` compares them). `demo.yml`, which publishes
  the online demo, names them as `ci.yml` does (`tests/test_demo_workflow.py`).
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
- The owner makes releases from a version tag on `main`; [docs/releasing.md](docs/releasing.md) says how.
