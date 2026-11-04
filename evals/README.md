# The evaluation

How far Ordnung can be trusted with a letter's deadlines, measured on letters made up for it, with the recorded
answers of the pinned model (`claude-sonnet-5`): every number replays with no model call and no tokens. The
numbers, their intervals and how to read them are in [docs/evals.md](../docs/evals.md); Ask's in
[docs/evals-ask.md](../docs/evals-ask.md), and every earlier run in [docs/evals-history.md](../docs/evals-history.md).

What is measured:

- **Reading letters** (`run.py`, `ordnung eval`): whether each deadline of a letter is found and its due date is
  right, and how often one comes out too late, in four conditions with the same model: Ordnung (Claude reads, the
  rules engine computes), the model alone, the model with the rules in its prompt, and the model with the rules
  engine as a tool.
- **From the letter to the reminder** (`e2e/`): each benchmark letter's file through the real app, to its to-do,
  its calendar alarm, the morning note and, where the law gives one, the objection letter.
- **Ask** (`ask/`): questions about the demo's sample life, with answers worked out from its truth: is the answer
  right, does it cite the letters it rests on, does it say so when they don't tell, does it say whose a number is,
  and does a letter with text written to steer it change the answer.
- **Ablations** (`scripts/eval_ablate_checks.py`, `scripts/eval_without_land.py`): the same recordings with each
  of Ordnung's checks switched off in turn, and the app without the sender's Land.
- **Stress** (`perturb/`): held-out letters with one sentence added, aimed at the deadline or naming a date that is
  not one; not recorded yet.

## Layout

| Path | What it holds |
|---|---|
| `dataset/` | the letters, as PDFs and phone photos, split by split, and `manifest.json` with each letter's truth; `VERIFICATION.md` says how the labels were checked |
| `generate.py`, `gen/` | the generator of `dataset/` (the labels' date arithmetic is `gen/law.py`, never `ordnung.rules`) |
| `verify_labels.py` | a re-check of the labels that shares no code with the generator or the app |
| `splits.py` | the splits: their role, their letters' variants, and which are recorded yet |
| `conditions.py`, `prompts/` | the four conditions, and the prompts of the three that are not Ordnung's pipeline (Ordnung's own are in `src/ordnung/llm/prompts/`) |
| `run.py`, `records.py`, `metrics.py`, `report.py` | the runner, the manifest's and the answers' types, the scoring, and the results files |
| `stats.py`, `analysis.py` | the statistics, and the analysis of the held-out splits (and of the final run, once it is recorded) |
| `harness.py` | recording: a cost cap, waiting through a usage limit, repeats, one recorder at a time, the ledger and the request lock |
| `ask/`, `e2e/`, `perturb/` | the Ask benchmark, the run through the real app, and the stress cells ([their own README](perturb/README.md)) |
| `recorded/` | the recorded answers: `recorded/claude-sonnet-5/` by what each call is for, `recorded/ask/claude-sonnet-5/` for Ask; beside each, `prompts.lock.json` and `requests.lock.json` |
| `results/` | the results files, `INDEX.json` (each file's role, and how its numbers replay) and `items.csv` (each item's ids, dates and outcome) |
| `present/` | the presenter: the README's evaluation block, the pages in `docs/`, their charts and the report page, from `results/` alone |
| `reproduce.py`, `export.py` | `make eval-reproduce`, and `items.csv` |

## Replay (no model call, no tokens)

```bash
.venv/bin/ordnung eval --results-dir /tmp/ordnung-replay                    # the test split, all four conditions
.venv/bin/ordnung eval --split holdout3 --results-dir /tmp/ordnung-replay   # any other split
.venv/bin/python -m evals.ask                                               # the Ask benchmark
make eval-reproduce                                                         # every published number, against results/INDEX.json
```

The two benchmark replays write their results file into a folder of their own, and a prediction cache into
cache/ there; the Ask replay writes nothing. Without `--results-dir`, `ordnung eval` (and `make eval`) writes
`results/<today>-claude-sonnet-5-test.json` into the checkout: INDEX.json doesn't list it, so `make eval-reproduce`
and `make check` fail until you delete it. Delete it, and never run the `--write` commands their errors suggest
for it: they would publish the throwaway replay. A held-out split's replay is never written beside its
recording, so it needs `--results-dir`. CI's gates are these commands with thresholds, which write no results
file (CONTRIBUTING.md, *Checks*). `make eval-reproduce` writes nothing into the checkout;
[docs/evals.md](../docs/evals.md#15-reproduce) lists its parts, one command each.

Whether a change needs new recordings (each says which request changed, if one did):

```bash
.venv/bin/python -m evals.harness lock-requests --check          # reading letters, against recorded/claude-sonnet-5/requests.lock.json
.venv/bin/python -m evals.harness lock-requests --ask --check    # Ask
```

## Record (costs tokens)

Recording calls Claude with your own account, and it is never part of an ordinary change: *Recording, when it is
time* in [CONTRIBUTING.md](../CONTRIBUTING.md#benchmarks-and-recorded-answers) says when, and how (a virtual
environment of the checkout's own, `ORDNUNG_CLAUDE_MODEL` unset, one recorder at a time). These are the commands,
for then:

```bash
.venv/bin/python -m evals.run --live --split test --allow-another-today --no-docs   # the test split's answers again (its letters keep their own days)
.venv/bin/python -m evals.ask --prune-stale                                       # delete the Ask answers whose tool results changed
.venv/bin/python -m evals.ask --live --allow-another-today                        # record the Ask answers that are missing
ORDNUNG_RECORD=1 .venv/bin/ordnung demo --live --rebuild --no-serve               # the demo's answers
.venv/bin/python -m evals.harness ledger                                          # what the live runs it logged cost
```

Right after, replay what you recorded and check that nothing is stale or missing. The committed recordings were
made with code from before the ledger, so it lists none of them; what the reading benchmark's recordings cost
is on [docs/evals-history.md](../docs/evals-history.md).

## The final run (pre-registered)

The final splits (`holdout4` and `newkinds`, written after the code freeze) and "Ask: new questions on the demo
household" are recorded in the one pre-registered run, on the days their letters are written for, with the flags
below; the recording commands, with each step's budget and stop, are pre-registered with it.

- **A unit at a time.** A unit is one letter in one read, with all its conditions; an Ask run, and a stress
  invocation, is one unit. When a unit completes, its day and the `claude` version go into the day index beside the
  recordings, `final-days.json`, so a read may span several days.
- **`--today YYYY-MM-DD`.** On `evals.run --live` (a final split only): the day the new units are recorded on, which
  is their today; it must be the UTC day and inside the letters' window. A replay takes no `--today`: it reads each
  letter's day from the day index, and so do `--check` and the request lock's capture. On `evals.ask --set heldout`
  and `scripts.eval_perturb`: the day the set or the stress cells are built for, the day they are recorded on.
- **`--stop-file PATH` and `--stop-at HH:MM`** (UTC), with `--live`, on all three: no new unit starts once the file
  exists or the clock has passed that time; the units under way finish, and the run exits 4. The same command goes
  on where it stopped, on another day with that day's `--today`. A unit of `evals.run` begun on an earlier day and
  not complete is refused, with its ids, until it is retaken; a stopped Ask run or stress invocation is retaken whole.
- **`--check FILE`.** Replay, then exit 1 unless the replay gives what FILE, a live results file, holds. `evals.run`
  and `evals.ask` write no results file then and name what differs on stdout; `scripts.eval_perturb` writes its
  replay into its `--out` folder, as every stress replay does, and names what differs on stderr.
- **`python -m evals.harness retake`** moves recordings aside with their request-lock entries, so what they belong to
  is recorded again whole, and prints each recording's path, sha256, outcome and cost: an incomplete unit
  (`--split`, `--repeat`, `--ids`), a whole Ask run or stress invocation (`--whole-run` with its own
  `--recorded-dir`, never the benchmark's), or every unit of a read a recorded deviation made invalid (`--invalid`,
  from the deviations file). A complete unit is retaken only that way; a retaken unit leaves the day index.

```bash
.venv/bin/python -m evals.run --split holdout4 --repeat 2 --check evals/results/pending/2026-12-08-claude-sonnet-5-holdout4-r2.json   # read 2 against its live file
.venv/bin/python -m evals.ask --set heldout --today 2026-12-08 --check evals/results/pending/2026-12-08-claude-sonnet-5-ask-heldout.json   # an Ask run, on its day
.venv/bin/python -m scripts.eval_perturb --today 2026-12-08 --out /tmp/stress-replay --check evals/results/pending/2026-12-08-claude-sonnet-5-stress.json   # the stress cells
.venv/bin/python -m evals.harness retake --split holdout4 --repeat 2 --ids holdout4-tax_assessment-K1 --to /tmp/retakes   # an incomplete unit
.venv/bin/python -m evals.harness retake --whole-run --recorded-dir evals/recorded/ask-heldout --repeat 2 --to /tmp/retakes   # a stopped Ask run
.venv/bin/python -m evals.harness retake --invalid D003 --to /tmp/retakes   # a read a recorded deviation made invalid
```

## Where results go

- A live run writes its answers into `recorded/`, each under a key made from what was sent
  ([ADR 0004](../docs/decisions/0004-replay-fixtures-and-deterministic-ids.md)), its requests into
  `requests.lock.json`, and a line per call into the `ledger.jsonl` beside them.
- Its results file goes into `results/`, named `<date>-claude-sonnet-5-<split>.json` (a repeat ends in `-rN`).
- `python -m evals.reproduce --write` gives that file its row in `results/INDEX.json` and its items in `items.csv`.
- The presenter renders every page and chart from `results/` (`python -m evals.present --write`): no number in a
  doc is typed by hand.
