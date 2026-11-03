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
.venv/bin/ordnung eval                                                      # the test split, all four conditions
.venv/bin/ordnung eval --split holdout3 --results-dir /tmp/ordnung-replay   # any other split, into a folder of its own
.venv/bin/python -m evals.ask                                               # the Ask benchmark
make eval-reproduce                                                         # every published number, against results/INDEX.json
```

The first writes `results/<today>-claude-sonnet-5-test.json` into the checkout (keep it out of your commits) and a
prediction cache under results/cache, which git ignores. A held-out split's replay is never written beside its
recording, so it needs `--results-dir`. CI's gates are these commands with thresholds (CONTRIBUTING.md, *Checks*).
`make eval-reproduce` writes nothing into the checkout; [docs/evals.md](../docs/evals.md#15-reproduce) lists its
parts, one command each.

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
.venv/bin/python -m evals.harness ledger                                          # what the recordings cost
```

Right after, replay what you recorded and check that nothing is stale or missing.

## Where results go

- A live run writes its answers into `recorded/`, each under a key made from what was sent
  ([ADR 0004](../docs/decisions/0004-replay-fixtures-and-deterministic-ids.md)), its requests into
  `requests.lock.json`, and a line per call into the `ledger.jsonl` beside them.
- Its results file goes into `results/`, named `<date>-claude-sonnet-5-<split>.json` (a repeat ends in `-rN`).
- `python -m evals.reproduce --write` gives that file its row in `results/INDEX.json` and its items in `items.csv`.
- The presenter renders every page and chart from `results/` (`python -m evals.present --write`): no number in a
  doc is typed by hand.
