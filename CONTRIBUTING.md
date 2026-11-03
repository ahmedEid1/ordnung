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
git clone --filter=blob:none https://github.com/ahmedEid1/ordnung.git && cd ordnung
make             # lists the targets and what each does
make install     # .venv with the dev extras at the versions in constraints.txt, and web/node_modules (npm ci)
make serve       # the API and the built web app on http://127.0.0.1:8765
make web-dev     # the Vite dev server with hot reload (it sends /api to `make serve`)
make demo        # the sample life with recorded answers: no Claude needed, zero tokens
```

`--filter=blob:none` leaves out the old versions of every file until a command needs one (`git log -p`, an
old checkout): the history keeps every earlier recording of the README's pictures and video, and every earlier
web build.

Reading your own letters needs Claude Code, signed in (see the README). The tests never call Claude:
they use a fake model backend, the end-to-end tests a fake `claude` (`tests/fake_claude.py`), and the
demo and benchmarks replay recorded answers. Once a week CI checks that a freshly installed Claude Code
still takes every flag Ordnung passes (`scripts/check_claude_flags.py`), without signing in.

## Fast loop

CI runs its jobs side by side, and a whole run takes a while. On 31 October 2026 a backend leg took 22–36
minutes (Python 3.14 the fastest), the slow checks 25, the lowest and the newest versions 20–26 (the newest
weekly), the frontend 6–7, Windows 13 and macOS 5 (not on pull requests), the wheel and the dependency audit
under 1. The end-to-end job, 30–39 minutes, starts once every backend leg and the frontend have passed. While
you work, run the tests near your change:

```bash
.venv/bin/pytest tests/test_rules_deadlines.py -k weekend     # one file, only the tests whose names match
cd web && npx vitest run src/features/today                   # one folder or file of the web app's tests (-t "<name>")
cd web && npx playwright test e2e/letter-layout.spec.ts       # one end-to-end spec (-g "<title>" for one test)
```

An end-to-end spec runs against the built web app in `src/ordnung/web/dist`, so after changing `web/` run
`make build-web` first, and `make browser` once for Playwright's Chromium. It starts the demo and two real apps
of its own on ports 8799 to 8802, with throwaway data folders; `web/e2e/env.ts` says how to move both.

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
.venv/bin/python -m evals.ask --min-accuracy 0.85 --min-abstention 0.85 --max-unsupported 0 --max-attack-success 0 --known-attack cite-rent-for-library-overview --min-household 0.8 --min-strict-accuracy 0.86 --max-harmful 6 --check-docs
# the demo rebuilds identically from the samples and recordings
.venv/bin/ordnung demo --check
# Playwright: the demo, then the real app reading with a fake Claude (installs Chromium first)
make e2e
# as CI's end-to-end job, with Tesseract and its German language data installed: the real app also finds a
# private photo by the words Ordnung reads in it (ADR 0024)
ORDNUNG_E2E_OCR=on make e2e
```

These are CI's commands and thresholds (`.github/workflows/ci.yml`). A few more things CI checks:

- **Generated files are committed, and CI fails while one is stale**: the built web app (so an install from
  git needs no Node), the API's types for the web app, the static demo's data, the demo and the evaluation's
  pages. [Generated files](#generated-files) says what writes each. The rebuilt web app goes in a commit of
  its own.
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

## Generated files

These files are written by a command, never by hand: change what they are made from, run the command and
commit what it writes. The last column is what fails while one is stale.

| File | Written by | Fails while it is stale |
|---|---|---|
| `src/ordnung/web/dist/` (the built web app) | `make build-web` | CI's step "Committed web build is up to date" (`node scripts/source-hash.mjs --check ../src/ordnung/web/dist/build-info.json` in `web/`) |
| `web/openapi.json`, `web/src/api/schema.d.ts` | `make openapi` | `tests/test_openapi_contract.py` |
| `web/src/mocks/data/girocodes.ts` | `.venv/bin/python scripts/gen_mock_girocodes.py > web/src/mocks/data/girocodes.ts` | `tests/test_mock_girocodes.py` |
| `web/src/mocks/data/numbers.ts` | `.venv/bin/python scripts/gen_mock_numbers.py > web/src/mocks/data/numbers.ts` | `tests/test_mock_numbers.py` (it skips without Node and the web app's packages from `npm ci`, unless `ORDNUNG_REQUIRE_MOCK_CHECK=1`) |
| `web/src/mocks/data/advice.ts` | `.venv/bin/python scripts/gen_mock_advice.py > web/src/mocks/data/advice.ts` | nothing yet: run it after changing `ordnung.rules.advice` |
| `web/src/mocks/data/highStakes.ts` | `.venv/bin/python scripts/gen_mock_high_stakes.py > web/src/mocks/data/highStakes.ts` | nothing yet: run it after changing `ordnung.rules` |
| `src/ordnung/demo/samples/` (the sample life's letters) | `make samples` | `tests/test_samples.py::test_committed_samples_match_regeneration` (it skips where the libraries differ from the manifest's, unless `ORDNUNG_REQUIRE_SAMPLES=1`) |
| `src/ordnung/rules/data/postcodes_de.tsv` | `make postcodes DE_ZIP=<GeoNames' DE.zip>` | `make postcodes DE_ZIP=<a DE.zip> CHECK=1`, which also fails once GeoNames' data has moved on (the table's header names the day and hash of the data it was made from); a hand edit fails `tests/test_make_postcode_table.py::test_the_committed_table_is_well_formed` |
| `src/ordnung/demo/demo_db/` (the demo's snapshot) | `.venv/bin/ordnung demo --rebuild --no-serve`, from the samples and the recordings (no model call) | `.venv/bin/ordnung demo --check`: the snapshot's `VERSION` is a hash of what it was built from (the app's and the database's versions, the samples' manifest, the suggested questions, the recordings), so the check fails once one of them changes, but not on a hand edit of the database |
| `src/ordnung/demo/fixtures/` (the demo's recorded answers) | recorded only: [Benchmarks and recorded answers](#benchmarks-and-recorded-answers) | `.venv/bin/ordnung demo --check` names the answers a replay misses |
| `evals/recorded/` (the benchmarks' recorded answers, and beside them their prompts lock, requests lock and ledger) | recorded only: [evals/README.md](evals/README.md#record-costs-tokens) | the benchmark steps in [Checks](#checks) (a replay misses, or a prompts lock refuses a changed text), and `.venv/bin/python -m evals.harness lock-requests --check` (`--ask --check` for Ask) |
| `README.md` (its evaluation block), `docs/evals.md`, `docs/evals-history.md`, `docs/assets/eval-*.svg`, `evals/present/presentation.json` | `.venv/bin/python -m evals.present --write` | `tests/test_present.py::test_the_outputs_are_the_committed_files` and `python -m evals.present --check` |
| `docs/evals-ask.md` | `.venv/bin/python -m evals.ask --write --date <the date the gate names>` | the Ask benchmark's step in [Checks](#checks) (`--check-docs`) |
| `evals/results/INDEX.json`, `evals/results/items.csv` | `.venv/bin/python -m evals.reproduce --write` (a date or count it changes then needs its reason in `INDEX.json`, written by a person); `items.csv` alone: `python -m evals.export --write` | `tests/test_results_index.py`, `tests/test_items_export.py` and `make eval-reproduce` |
| `evals/dataset/` (the benchmark's letters) | `.venv/bin/python evals/generate.py` (a changed letter needs new recordings) | `tests/test_eval_dataset.py::test_generation_is_byte_identical` |
| `web/e2e/fixtures/outlook-bill.msg` | `python scripts/make_msg_fixture.py` | `tests/test_outlook.py::test_e2e_fixture_is_rebuilt_byte_for_byte` |
| `web/e2e/fixtures/private-photo.jpg` | `python scripts/make_photo_fixture.py` | `tests/test_photo_fixture.py::test_the_e2e_photo_is_what_the_script_draws` |
| `docs/assets/*.png`, `docs/assets/demo.gif`, `docs/assets/demo.mp4` (the README's pictures and video) | `make capture` (it needs ffmpeg) | nothing: look at them, and commit them as said below |
| `constraints.txt` | `make constraints` | nothing compares it with `pyproject.toml`: run it after changing a dependency ([Dependencies](#dependencies)) |

**The online demo** is the web app built for the browser alone, on the mock world in `web/src/mocks` (no
server, no model); [.github/workflows/demo.yml](.github/workflows/demo.yml) publishes it from `main`. Build it
into a folder of its own, never into `src/ordnung/web/dist`:

```bash
cd web && VITE_STATIC_DEMO=1 npx vite build --base ./ --outDir /tmp/ordnung-static-demo --emptyOutDir
npx vite preview --outDir /tmp/ordnung-static-demo     # then open the address it prints
```

**The README's pictures and video** stay in the history, every version of them. To look at a capture, write it
into a folder of your own (`CAPTURE_OUT=$(mktemp -d) make capture`). Commit media once per release, after the
last fix round: the pictures only of screens that changed (`scripts/capture.sh --only shots` takes the pictures
alone, after `make build-web browser`), and the tour's video and GIF only when the tour changed.

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
  depends on: every Python file of `src/ordnung` and the runner's own `evals/*.py` (and the versions of the
  libraries that read a letter). It keys only your local prediction cache and the fingerprint written into a new results file, so a
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
  the Ask answers that went stale, and `python -m evals.ask --live --allow-another-today` records only what is
  missing (see the recording day below); the demo
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
  refuses them (`python -m evals.ask --set heldout --today <day>` builds the held-out Ask set for that day). The
  development sets (Ask's, pinned to 28 Sep 2026, and the dev and test splits) can only be recorded again on
  another day: `--allow-another-today` does that in the open, and every new recording (`recorded_on`) and results
  file says both days. A held-out or final set takes `--allow-another-today` only for a smoke into a scratch
  `--recorded-dir` outside the checkout, thrown away.

## Tests

- Write the test first and watch it fail, then make the change. The first version's review rounds
  proved every bug and security finding with a failing test before fixing it; keep doing that.
- Name a test by the behaviour it pins, the way the files around it do
  (`test_a_missing_asset_is_a_404_not_the_app_page`).
- A test that replays every recording, times pages or builds the web app is marked `slow`
  (`make check` runs those too).
- A docs test pins a fact the page states (a flag exists, a number is the one its results file holds, a file it
  names is there), not the sentence that states it: rewording a page should not need a test change.

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
