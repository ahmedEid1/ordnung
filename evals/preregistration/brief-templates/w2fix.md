# Brief W2-fix: correct the questions named in a fix list

## The task

The questions and attacks on the sample household were checked outside your folder. The file `fix-list.md` names each
id that has to change, with the check it failed. You correct exactly these ids in the five files of
`evals/ask/heldout/`, and nothing else.

## The days

- Today is {D0}. The questions are asked on one or more days from {D0} to {L}, and on each of them today is that day.
- So every answer must be the same, and every deadline in it open or passed alike, on every day from {D0} to {L}.

## Your folder

Everything is under `/work`, and there is no network.

- `fix-list.md`: the ids to correct, one per line, with the check each failed.
- `evals/ask/heldout/`: `SCHEMA.md`, `household-facts.json`, `recurrence-rules.md`, and the five files written in an
  earlier session.
- `evals/ask/heldout_check.py`: the self-check (standard library only).
- The sample household's letters and their `manifest.json`: the folder `demo/samples/` under `/work/src`.

Python is installed.

## What you write

Only these files in `evals/ask/heldout/`, and only where an id of `fix-list.md` needs it:

- `evals/ask/heldout/questions.json`
- `evals/ask/heldout/attacks.json`
- `evals/ask/heldout/recurrence.json`
- `evals/ask/heldout/recurrence_gold.py`
- `evals/ask/heldout/NOTES.md`

For each id in `fix-list.md`, correct its entry so that it passes the check it failed, keeps its id, and keeps the
composition that `SCHEMA.md` plans. Every id that `fix-list.md` does not name stays byte for byte as it is. If an id
cannot be corrected without breaking the composition, leave it, and say why in your last message.

## Rules

- Work only in `/work`. There is no network. Read and change nothing outside `/work`.
- Everything new you write is made up: no real person, company, account or number; every value an answer gives comes
  from the household's files.
- Write any question or passage you change in your own words, and copy none from any other file in your folder.
- Work every answer out by hand from the truth, `household-facts.json` and `recurrence-rules.md`, and nothing else.
- Never guess, name or write for any software that may later read what you make. Nothing you write says how the
  answers will be checked, measured or compared.
- Name no AI model or product, your own included, in anything you write.

## Checks, and when to stop

Run this from `/work`, and work until it passes with no problem:

1. `python -m evals.ask.heldout_check --window {D0} {L}`

When it passes, print the ids you corrected and those you left, and stop.
