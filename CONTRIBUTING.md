# Contributing to Ordnung

Thank you for helping. This page is for anyone changing Ordnung's code, tests or docs: how to set up a checkout,
which checks to run, and how changes are written here. A security problem goes to [SECURITY.md](SECURITY.md),
never to an issue.

## In one minute

- **Never commit real letters or personal data**, yours included: everything here is made up
  ([why and how](#real-letters-stay-out)).
- **Set up** with Python 3.11+, uv and Node.js, then `make install`; `make demo` runs without Claude
  ([setting up](#setting-up)).
- **While you work**, run the tests near your change, and the fast suite before you push ([fast loop](#fast-loop)).
- **Before a pull request**, run `make check` and the CI checks near your change ([checks](#checks)).
- **Generated files are written by a command, never by hand**, and committed; the rebuilt web app goes in a commit
  of its own ([generated files](#generated-files)).
- **Docs and the changelog move with the code:** tests check the docs against the code, and a change people
  notice gets a line in CHANGELOG.md ([commits and pull requests](#commits-and-pull-requests)).

## Contents

[Real letters stay out](#real-letters-stay-out) · [Setting up](#setting-up) ·
[Where things live](#where-things-live) · [Fast loop](#fast-loop) · [Checks](#checks) ·
[Generated files](#generated-files) · [Benchmarks and recorded answers](#benchmarks-and-recorded-answers) ·
[Tests](#tests) · [Dependencies](#dependencies) · [Commits and pull requests](#commits-and-pull-requests)

## Real letters stay out

**Never commit, attach or paste real letters or personal data**: not in code, tests, fixtures, issues,
pull requests, screenshots or logs, and not your own either. Everything in this repository is made
up: the sample life the demo shows (`src/ordnung/demo/samples/`, every page marked SPECIMEN), the
benchmark's letters (`evals/dataset/`) and the text in the tests. Show a problem with `ordnung demo`
or a letter you write yourself, and describe a real letter in your own words.

## Setting up

You need Python 3.11 or newer, [uv](https://docs.astral.sh/uv/) and Node.js 22.22.2+, 24.15+ or 26+
(`nvm use` picks the one in `.nvmrc`; `web/package.json` says the same): the web app's router asks for 22.22+,
and jsdom, under the unit tests, for 22.22.2+ or 24.15+.

```bash
git clone --filter=blob:none \
  https://github.com/ahmedEid1/ordnung.git
cd ordnung
# list the targets and what each does
make
# .venv and web/node_modules
make install
# the API and the built web app
make serve
# the Vite dev server, hot reload
make web-dev
# the sample life: no Claude needed
make demo
```

- `make install` makes .venv with the dev extras at the versions in `constraints.txt`, and web/node_modules
  (`npm ci`).
- `make serve` serves on port 8765; `make web-dev` sends `/api` to `make serve`.
- `make demo` replays recorded answers: no Claude needed, zero tokens.
- `--filter=blob:none` leaves out the old versions of every file until a command needs one (`git log -p`, an
  old checkout): the history keeps every earlier recording of the README's pictures and video, and every earlier
  web build.

Reading your own letters needs Claude Code, signed in (see [the guide](docs/guide.md#install-and-run)). The
tests never call Claude: they use a fake model backend, the end-to-end tests a fake `claude`
(`tests/fake_claude.py`), and the demo and benchmarks replay recorded answers. Once a week CI checks that a
freshly installed Claude Code still takes every flag Ordnung passes (`scripts/check_claude_flags.py`), without
signing in.

## Where things live

| Folder | What is in it |
|---|---|
| `src/ordnung/` | The Python app: the CLI (`cli.py`), the API (`api/`), reading a letter (`ingest/`, `llm/`), the rules engine (`rules/`), *Ask* (`assistant/`), the Ideas and the daily note (`secretary/`), letters you write (`drafts/`) |
| `src/ordnung/web/dist/` | The built web app, committed, so an install from git needs no Node |
| `web/` | The React web app's source (`web/src/`) and its end-to-end tests (`web/e2e/`) |
| `tests/` | The Python tests |
| `evals/` | The benchmarks; [evals/README.md](evals/README.md#layout) lays out every folder |
| `docs/` | The guide, privacy, architecture and SPEC; design decisions in `docs/decisions/`; [docs/README.md](docs/README.md) lists every page |
| `scripts/` | The commands that write generated files, and tools for the evaluation and releases |

[docs/architecture.md](docs/architecture.md) says how the parts fit together.

## Fast loop

While you work, run the tests near your change, and the fast suite in parallel processes before you push:

```bash
# one file, tests whose names match
.venv/bin/pytest tests/test_rules_deadlines.py -k weekend
# web app tests: a folder or a file
# (-t "<name>" for one test)
cd web && npx vitest run src/features/today
# one end-to-end spec
# (-g "<title>" for one test)
cd web && npx playwright test e2e/letter-layout.spec.ts
# the fast suite: a process per core,
# each taking whole files
.venv/bin/pytest -m "not slow" -n auto --dist loadfile
```

The fast suite takes about 10 to 11 minutes in two processes on a busy 4-core computer (measured in two halves).

An end-to-end spec runs against the built web app in `src/ordnung/web/dist`, so after changing `web/` run
`make build-web` first, and `make browser` once for Playwright's Chromium. It starts the demo and two real apps
of its own on ports 8799 to 8802, with throwaway data folders; `web/e2e/env.ts` says how to move both.
`E2E_GROUP=<name>` runs one group of its projects (`E2E_GROUPS` in `web/e2e/env.ts`) on fresh servers of its own,
only the ones that group uses; CI runs the groups side by side.

<details>
<summary>How long CI takes, job by job</summary>

CI runs its jobs side by side, none waiting for another.

- **The whole run.** A whole run took 40 to 50 minutes with each suite in one process and 13 to 16 once the
  suites ran in parallel; with every published number replayed in a job of its own and the slow tests in two, a
  pull request's run takes 10 to 12 (the runs of 19 November 2026, on which the minutes here were measured; where
  two are given, they are the shortest and the longest of that day, and the same job can take half as long again
  on another runner).
- **The slow tests.** The slow tests took 10 as one job, and 15 on a slower runner, where every test ran about
  1.6 times as long (three runs of five that day): they run as two jobs side by side, each with about half the
  work, the seven files with the longest tests in one (5 to 6 minutes, most of it the kill test of
  `tests/test_sync_pull_process.py`) and every other slow test in the other (4 to 5 minutes).
- **End to end.** The end-to-end job waits for no other job: its legs, one for each group of Playwright's
  projects or part of one, took 7 to 12 as four legs; the layout guards took 23 as one leg and up to 12 as the
  first of two halves, so they run in four parts (Playwright's `--shard`, each part on a demo of its own: a layout
  file sets up what it needs and relies on no file before it), and the layout sweep and the evaluation's report
  page have groups of their own.
- **The other jobs.** The backend's 3.12 leg, which measures the coverage, took 7 to 12 as one leg: it runs as
  two halves side by side, each on half of the test files, and a short job adds up their coverage and holds the
  sum to the floors. The backend's other legs (Python 3.11, 3.13 and 3.14) take 4 to 6, the lowest versions (and,
  weekly, the newest) 5 to 8, the replayed benchmarks 5 to 8, the replay of every published number (`make
  eval-reproduce`) 6 to 9, the frontend 4 to 7; lint and types, the wheel and the dependency audit take under a
  minute each.
- **Windows and macOS.** Windows (7 to 9 minutes) runs on every pull request too, with the tests of the code that
  differs per system (`PER_SYSTEM_TESTS` in `tests/test_ci_workflow.py`), and has to pass, as Linux does. macOS
  (3 to 6 minutes) runs the same tests on `main`, weekly and when the workflow is started by hand, not on a pull
  request: on one pull request of three its runner was 10 minutes in coming, and on another none came in 15
  minutes, the job was cancelled and the run failed with every other job passed.

</details>

## Checks

`make check` runs what most changes need: ruff (lint and format) and mypy (strict, over the package,
`evals/` and `scripts/`), the backend tests in parallel processes (the fast ones with coverage, then the slow
ones), and the web app's ESLint, type check and Vitest tests. CI runs more; run the ones near your change before
you open a pull request. These are CI's commands and thresholds (`.github/workflows/ci.yml`):

```bash
make check
```

**Coverage floors.** Hand-off sync and phone access keep their coverage floors, read from what make check's fast
tests measured (so before the next command, which measures only the rules engine); the rules engine keeps 100 %
line and branch coverage:

```bash
.venv/bin/coverage report \
  --include='*/ordnung/sync/*' \
  --skip-covered --fail-under=85
.venv/bin/coverage report \
  --include='*/ordnung/phone/*' \
  --skip-covered --fail-under=89
.venv/bin/pytest tests/test_rules_*.py \
  --cov=ordnung.rules --cov-branch \
  --cov-report=term-missing:skip-covered \
  --cov-fail-under=100
```

**Both benchmarks, replayed** (deterministic, zero tokens, no results file written). CI also replays the
holdout, holdout2 and dev splits, the final run (holdout4 r1-r3, newkinds and Ask's new questions on the demo
household r1-r3, each against its own gate) and the numbers without the sender's Land:

```bash
.venv/bin/ordnung eval \
  --min-accuracy 0.98 \
  --max-dangerous-late 0
.venv/bin/python \
  -m evals.ask \
  --min-accuracy 0.85 \
  --min-abstention 0.85 \
  --max-unsupported 0 \
  --max-attack-success 0 \
  --known-attack \
    cite-rent-for-library-overview \
  --min-household 0.8 \
  --min-strict-accuracy 0.86 \
  --max-harmful 6 --check-docs
```

**What is generated matches what it is made from.** The demo rebuilds identically from the samples and
recordings; the evaluation's README block, report, history page and charts are what the results files render;
every published number is replayed (no model call, no API key) and compared with `evals/results/INDEX.json`:

```bash
.venv/bin/ordnung demo --check
.venv/bin/python -m evals.present --check
make eval-reproduce
```

**Browser tests.** Playwright runs the demo, then the real app reading with a fake Claude (`make e2e` installs
Chromium first). CI's end-to-end job also has Tesseract and its German language data installed: the real app then
also finds a private photo by the words Ordnung reads in it (ADR 0024).

```bash
make e2e
# with Tesseract, as CI
ORDNUNG_E2E_OCR=on make e2e
```

A few more things CI checks:

- **Generated files are committed, and CI fails while most of them are stale**: the built web app (so an
  install from git needs no Node), the API's types for the web app, the static demo's GiroCodes, My numbers,
  advice cards and high-stakes dates, the demo, and the evaluation's analysis and pages.
  [Generated files](#generated-files) says what writes each, and which ones nothing checks yet. The rebuilt web
  app goes in a commit of its own.
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
commit what it writes. The ones most changes touch: the built web app (`make build-web`, in a commit of its own),
the API's types (`make openapi`) and the demo's snapshot (`.venv/bin/ordnung demo --rebuild --no-serve`). The
table lists every one; its last column is what fails while one is stale.

<details>
<summary>Every generated file: what writes it, and what fails while it is stale</summary>

| File | Written by | Fails while it is stale |
|---|---|---|
| `src/ordnung/web/dist/` (the built web app) | `make build-web` | CI's step "Committed web build is up to date" (`node scripts/source-hash.mjs --check ../src/ordnung/web/dist/build-info.json` in `web/`) |
| `web/openapi.json`, `web/src/api/schema.d.ts` | `make openapi` | `tests/test_openapi_contract.py` |
| `web/src/mocks/data/girocodes.ts` | `.venv/bin/python scripts/gen_mock_girocodes.py > web/src/mocks/data/girocodes.ts` | `tests/test_mock_girocodes.py` |
| `web/src/mocks/data/numbers.ts` | `.venv/bin/python scripts/gen_mock_numbers.py > web/src/mocks/data/numbers.ts` | `tests/test_mock_numbers.py` (it skips without Node and the web app's packages from `npm ci`, unless `ORDNUNG_REQUIRE_MOCK_CHECK=1`) |
| `web/src/mocks/data/advice.ts` | `.venv/bin/python scripts/gen_mock_advice.py > web/src/mocks/data/advice.ts` | `tests/test_mock_advice.py` |
| `web/src/mocks/data/highStakes.ts` | `.venv/bin/python scripts/gen_mock_high_stakes.py > web/src/mocks/data/highStakes.ts` | `tests/test_mock_high_stakes.py` |
| `src/ordnung/demo/samples/` (the sample life's letters) | `make samples` | `tests/test_samples.py::test_committed_samples_match_regeneration` (it skips where the libraries differ from the manifest's, unless `ORDNUNG_REQUIRE_SAMPLES=1`) |
| `src/ordnung/rules/data/postcodes_de.tsv` | `make postcodes DE_ZIP=<GeoNames' DE.zip>` | `make postcodes DE_ZIP=<a DE.zip> CHECK=1` (not in CI: it needs GeoNames' file), which also fails once GeoNames' data has moved on (the table's header names the day and hash of the data it was made from). `tests/test_make_postcode_table.py::test_the_committed_table_is_well_formed` catches only a broken layout or counts that don't add up, not a postcode given another Land by hand |
| `src/ordnung/demo/demo_db/` (the demo's snapshot) | `.venv/bin/ordnung demo --rebuild --no-serve`, from the samples and the recordings (no model call) | `.venv/bin/ordnung demo --check`: the snapshot's `VERSION` is a hash of what it was built from (the app's and the database's versions, the samples' manifest, the suggested questions, the recordings), so the check fails once one of them changes; and its content must be what they build (the database row for row, the cached answers, the originals, and the page images byte for byte where its `RENDERER` names the renderer the check runs with), so a hand edit fails too |
| `src/ordnung/demo/fixtures/` (the demo's recorded answers) | recorded only: [Benchmarks and recorded answers](#benchmarks-and-recorded-answers) | `.venv/bin/ordnung demo --check` names the answers a replay misses |
| `evals/recorded/` (the benchmarks' recorded answers, and beside them their prompts lock and requests lock; a live run adds its ledger there, and a final split's live run the day index, final-days.json, with the day each letter was recorded on) | recorded only: [evals/README.md](evals/README.md#record-costs-tokens) | the benchmark steps in [Checks](#checks) (a replay misses, or a prompts lock refuses a changed text), and `.venv/bin/python -m evals.harness lock-requests --check` (`--ask --check` for Ask) |
| `evals/results/*-heldout-reanalysis.json` (the held-out splits analysed again from their results files as recorded) | `.venv/bin/python -m evals.analysis --write --date <day>`, with the date in the file's name; without `--date` it writes a new file for today, which `evals/results/INDEX.json` doesn't list, and leaves the old one stale | `python -m evals.analysis --check` and `make eval-reproduce` |
| `README.md` (its evaluation block), `docs/evals.md`, `docs/evals-history.md`, `docs/assets/eval-*.svg`, `evals/present/presentation.json` | `.venv/bin/python -m evals.present --write` | `tests/test_present.py::test_the_outputs_are_the_committed_files` and `python -m evals.present --check` |
| `docs/evals-ask.md` | `.venv/bin/python -m evals.ask --write --date <day>`, with the day the page's header says it was re-scored on (the date in the name of the newest `evals/results/*-ask-rescored.json`); without `--date` it writes a new results file for today | the Ask benchmark's step in [Checks](#checks) (`--check-docs`) |
| `evals/ask/heldout/household-facts.json` (what the blind writer of “Ask: new questions on the demo household” is told of the household ledger) | `.venv/bin/python -m scripts.export_household_facts` (`scripts/export_household_facts.py`), from the household group's constants and the sample life's truth | `tests/test_evals_ask_heldout.py::test_the_household_facts_are_the_household_groups` and `python -m scripts.export_household_facts --check` |
| `evals/results/INDEX.json`, `evals/results/items.csv` | `.venv/bin/python -m evals.reproduce --write` (a date or count it changes then needs its reason in `INDEX.json`, written by a person); `items.csv` alone: `python -m evals.export --write` | `tests/test_results_index.py`, `tests/test_items_export.py` and `make eval-reproduce` |
| `evals/dataset/` (the benchmark's letters) | `.venv/bin/python evals/generate.py` (a changed letter needs new recordings) | `tests/test_eval_dataset.py::test_generation_is_byte_identical` |
| `evals/dataset/*/facts.json` (a final split's facts, which `evals/verify_labels.py` re-derives its labels from) | `.venv/bin/python -m scripts.build_final_facts` (`scripts/build_final_facts.py`), from the sealed blind audit: the readings, the opaque-name map and the adjudications, which stay outside the repository (its `--help` names them) | `.venv/bin/python -m scripts.build_final_facts --check` with the same files (not in CI, which has none of them), and `.venv/bin/python -m evals.verify_labels --require-facts`, which re-derives every label of a final split from them |
| `web/e2e/fixtures/outlook-bill.msg` | `python scripts/make_msg_fixture.py` | `tests/test_outlook.py::test_e2e_fixture_is_rebuilt_byte_for_byte` |
| `web/e2e/fixtures/private-photo.jpg` | `python scripts/make_photo_fixture.py` | `tests/test_photo_fixture.py::test_the_e2e_photo_is_what_the_script_draws` |
| `docs/assets/*.png`, `docs/assets/demo.webp`, `docs/assets/demo.gif`, `docs/assets/demo.mp4` (the README's pictures at twice their window (a desktop's 2880×1800, a phone's 780×1688), its animation as WebP with the GIF for browsers without it, and the video at 1920×1440) | `make capture` (it needs ffmpeg) | `tests/test_media_budget.py` checks their sizes, settings, lengths and budgets; look at them, and commit them as said below |
| `constraints.txt` | `make constraints` | nothing compares it with `pyproject.toml`: run it after changing a dependency ([Dependencies](#dependencies)) |

</details>

**The online demo** is the web app built for the browser alone, on the mock world in `web/src/mocks` (no
server, no model); [.github/workflows/demo.yml](.github/workflows/demo.yml) publishes it from `main`. Build it
into a folder of its own, never into `src/ordnung/web/dist`:

```bash
cd web
VITE_STATIC_DEMO=1 npx vite build \
  --base ./ \
  --outDir /tmp/ordnung-static-demo \
  --emptyOutDir
# then open the address it prints
npx vite preview \
  --outDir /tmp/ordnung-static-demo
```

**The README's pictures and video** stay in the history, every version of them. To look at a capture, write it
into a folder of your own (`CAPTURE_OUT=$(mktemp -d) make capture`). Commit media once per release, after the
last fix round: the pictures only of screens that changed (`scripts/capture.sh --only shots` takes the pictures
alone, after `make build-web browser`), and the tour's video, WebP and GIF only when the tour changed.

**The README's diagram** (`docs/assets/pipeline-light.svg` and `pipeline-dark.svg`) is two SVG files kept by hand;
no script writes them. Change both the same way: they differ only in their colours and ids, and
`tests/test_readme.py` checks that they carry the same words and that the README's alt text is their description.
They are shown as pictures, so they load no font: leave each line of text room to spare in its box, and keep the
smallest text at 13 of the 400 units wide, which is about 10 px on a phone.

## Benchmarks and recorded answers

The model answers the demo and both benchmarks show are recordings of real runs (`evals/recorded/`,
`src/ordnung/demo/fixtures/`). Each is stored under a key made from what the call is for, the
prompt's version, the model and what was sent
([ADR 0004](docs/decisions/0004-replay-fixtures-and-deterministic-ids.md)). CI replays them: a
replay scores the recorded answers with the checked-out code, so a change to the rules engine or to a
check shows in the numbers at once, and costs nothing.

- **Numbers are never typed.** The numbers in the README and in `docs/` come from the results files a run or
  replay writes (`evals/results/`), never typed by hand; tests compare the docs with those files. Outside its
  generated block the README types no rate or "k of n" of a results file:
  `tests/test_docs_claims.py::test_the_readme_types_no_benchmark_number_by_hand` fails when it does.
- **Recording is not part of an ordinary change.** Recording new answers calls Claude with your own account and
  costs tokens. It is done on purpose, when a prompt or what is sent to Claude changes, never as part of an
  ordinary change. If a replay misses a recording after your change, say so in the pull request instead of
  recording.

<details>
<summary>When a recording is needed, how to record, and the recording harness</summary>

- **Digest files and recordings.** `_code_digest` in `evals/conditions.py` hashes the code a benchmark prediction
  depends on: every Python file of `src/ordnung` and the runner's own `evals/*.py` (and the versions of the
  libraries that read a letter). It keys only your local prediction cache and the fingerprint written into a new
  results file, so a code change moves it and needs no recording by itself. A recording is needed only
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
  - `--max-cost-usd` starts no new call once a step's calls cost that much (counting what its ledger says earlier
    runs of the same command spent), `--wait-on-limit` waits through a usage limit for up to that many hours
    instead of stopping, and `--repeat N` records run N (2 and up) of the same requests under keys of its own.
  - Every live call adds a line to `ledger.jsonl` beside the recordings (commit it with them), every recording's
    request is locked in `requests.lock.json` (`python -m evals.harness lock-requests --check`, and
    `diff-requests <ref>` says what changed), and one recorder runs at a time: a recorder that died leaves its
    lock, which `python -m evals.harness unlock` frees once its process is gone.
  - A replay recomputes every prediction; it reads the prediction cache only with `--resume`.
  - A recording is built for the day it is recorded: the claude CLI tells the model the computer's date, so
    letters or a ledger pinned to another day would show it two todays, and a live run refuses them
    (`python -m evals.ask --set heldout --today <day>` builds “Ask: new questions on the demo household” for that
    day). The development sets (Ask's, pinned to 28 Sep 2026, and the dev and test splits) can only be recorded
    again on another day: `--allow-another-today` does that in the open, and every new recording (`recorded_on`)
    and results file says both days. A held-out or final set takes `--allow-another-today` only for a smoke into
    a scratch `--recorded-dir` outside the checkout, thrown away.
  - An Ask run cut short (by its `--max-cost-usd`, a usage limit not waited out, or midnight UTC), or with a turn
    that failed part-way (a usage limit met after the turn's first request, a timeout, a CLI error), writes no
    results file: resume it the same day (a higher cap, or the same command once the limit resets), or retake it
    whole. A turn still without an answer after the final run's three resumes is scored as no answer by the same
    command with `--allow-errors` (as `evals.run`'s; it keeps the turn beside the recordings, so a replay gives
    the same failure), with an `unanswered` deviation; it is refused until the ledger shows the turn's first
    attempt and three resumes failed, and a cut run is never written.

</details>

## Tests

- **Test first.** Write the test first and watch it fail, then make the change. The first version's review rounds
  proved every bug and security finding with a failing test before fixing it; keep doing that.
- **Names.** Name a test by the behaviour it pins, the way the files around it do
  (`test_a_missing_asset_is_a_404_not_the_app_page`).
- **One test for one behaviour.** The examples of one rule (thirty wordings that must all read as a deadline) are
  the rows of one table test: `check_rows` in `tests/helpers_tables.py` runs the check on every row and names
  every row that fails (`check_rows_async` where the check is awaited). Parametrise only when the cases are
  different behaviours a reader wants to see fail apart (different routes, commands or file formats), or when
  each case needs a fresh fixture that it changes.
- **Slow tests and parallel processes.** A test that replays every recording, times pages or its own growth,
  explores at length (a long fuzz or model run), regenerates or re-reads a whole dataset, or builds the web app is
  marked `slow` (`make check` runs those too). The tests run in parallel processes, a file to a process (`-n auto
  --dist loadfile`): a test takes its files from `tmp_path` and a port for a server from `tests/helpers_net.py`,
  never a fixed one.
- **A test's database.** A test's store starts from a copy of one migrated, empty database
  (`tests/helpers_store.py`; the `store` fixture and `api_for` copy it), because migrating a new one for every
  test cost more than the tests themselves. A test about creating a database (a migration, the first start on an
  empty folder, the mode of a new file, a lock) opens its own folder instead: `api_for(..., first_start=True)`, or
  `Store.open` on a path of its own. A test that only reads the API's schema takes `api_schema()` from
  `tests/test_api_support.py`, built once per process.
- **Docs tests.** A docs test pins a fact the page states (a flag exists, a number is the one its results file
  holds, a file it names is there), not the sentence that states it: rewording a page should not need a test
  change.
- **The layers are pinned.** `tests/test_import_layout.py` reads the backend's imports from the source, a lazy one
  inside a function included, one only for type checking not: no circle of modules imports each other, so an
  import that closes one fails it. In the web app, `npm run lint` refuses an import of a feature, a page, the
  shell or the mocks from `lib/`, `api/` or `components/ui` (`web/eslint.config.js`).

## Dependencies

- **Python**: CI and `make install` install the versions in `constraints.txt`, which
  `make constraints` writes from `pyproject.toml`. To move every package to its newest version, run
  `make constraints CONSTRAINTS_ARGS=--upgrade`, then `make install` and the checks, and commit
  `constraints.txt`. The samples' libraries (fpdf2, fonttools, pillow, pypdfium2) stay at the versions
  in the samples' manifest, because the sample letters regenerate byte for byte only with those;
  `make constraints` keeps them. The floors in `pyproject.toml` are what CI's "lowest" job installs.
  What builds the sdist and the wheel (`pyproject.toml`'s build-system and what it needs) is pinned with
  hashes in `build-constraints.txt`: run `make build-constraints` after changing the build-system's pins.
- **Web packages and GitHub Actions**: Dependabot opens update pull requests every week
  (`.github/dependabot.yml`): minor and patch updates together, each major on its own. One for `web/`
  changes `package-lock.json`, so CI passes only once `make build-web` has run and `src/ordnung/web/dist`
  is committed on its branch; or fold the updates into a pull request of your own. TypeScript majors are
  skipped until the packages that need TypeScript (openapi-typescript, typescript-eslint) take them: a test
  in `tests/test_repo_hygiene.py` fails then, saying to remove the rule. `ci.yml` names actions by their
  major version (`actions/checkout@v7`), and `release.yml` pins each to a commit with its version beside it;
  keep both on the same major (`tests/test_release_workflow.py` compares them). `demo.yml`, which publishes
  the online demo, names them as `ci.yml` does (`tests/test_demo_workflow.py`).
- **Weekly**: CI's weekly "latest" job tests every Python package at its newest version, and its dependency audit
  checks `constraints.txt` and the web app's packages for known vulnerabilities.

## Commits and pull requests

- **Commit messages.** A commit message is one plain English line saying what changed, as someone using or
  reading the app would put it: "Read again never queues a second reading of the same letter". An area and a
  colon may come first: "Windows: the lock message names the process holding the data folder",
  "Docs: …". The rebuilt web app goes in a commit of its own: "Rebuild the web app for …".
- **The changelog and decisions.** A change people will notice gets a line under "Unreleased" in
  [CHANGELOG.md](CHANGELOG.md), or, while a version named before its tag waits for the pull request whose merge
  gets that tag, under that version ([docs/releasing.md](docs/releasing.md)). A design decision gets a short
  record in [docs/decisions/](docs/decisions/).
- **Pull requests.** Pull requests go to `main`, and CI must pass. Say what changed and how you checked it, and
  keep real letters and personal data out of the description too.
- **Releases.** The owner makes releases from a version tag on `main`; [docs/releasing.md](docs/releasing.md) says
  how.
