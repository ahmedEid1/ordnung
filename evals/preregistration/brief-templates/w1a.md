# Brief W1a: the holdout4 letters

## The task

You write the generator code for a new set of synthetic German letters, the split `holdout4`. Each letter comes with
its truth: what the letter asks of the person it is addressed to, and the dates the law gives for it, worked out with
the statute arithmetic in `evals/gen/law.py`. The generator in your folder already writes five earlier splits.
`holdout4` covers the same twelve families of letters in four new template variants, `K`, `L`, `M` and `N`, plus new
adversarial letters and photos of letters. Your code is a plug-in module that `evals/generate.py` loads, so
`evals/generate.py` itself stays as it is.

## The days

- Today, for every letter of `holdout4`, is {D0}.
- The letters are valid through {L}: they may be read on any day from {D0} to {L}.
- Every letter is posted between 6 and 2 days before {D0}.
- A notice of a fine is served between 7 days before {D0} and {D0}; one whose period is two weeks is served no
  earlier than 6 days before {D0}.
- Every scored date, every end of a contract's term, every last day to cancel and every appointment falls after
  {L}. Only the unscored dates of an adversarial letter may lie earlier.

## Your folder

Everything is under `/work`, and there is no network.

- `evals/gen/`: the generator. The family modules (`families_admin.py`, `families_private.py`), one module set per
  earlier split (`holdout_*.py`, `holdout2_*.py`, `holdout3_*.py`, `adversarial.py`), `law.py` (the statute
  arithmetic every date comes from), `common.py` (cases, items, `SPLIT_VARIANTS`, `DOCUMENT_KINDS`), `pdf.py`,
  `photo.py`, `text.py` (`rng_for`) and `orgs.py`.
- `evals/generate.py`: writes every split's letters and `evals/dataset/manifest.json`. Its module docstring says what
  the plug-in `evals/gen/final.py` defines and which rules it checks. `CONVENTIONS` there lists the labelling
  conventions of the earlier splits, each with an id and a `disputed` flag.
- `evals/verify_labels.py`: checks the labels of the splits.
- `evals/law/`: the statute texts, with `SOURCES.md`.
- `evals/dataset/VERIFICATION.md`: how the earlier splits were written and checked (a shortened copy).
- `tests/test_eval_dataset.py`: the dataset's tests.
- `pyproject.toml` (the tool settings only) and `constraints.txt`.
- The fonts the letters are set in, under `/work/src`.

Python, with the packages the generator needs, is installed.

## What you write

Write these files, and change no other:

- `evals/gen/common.py`: only the line `SPLIT_VARIANTS["holdout4"] = ("K", "L", "M", "N")` (in the dictionary).
- `evals/gen/final.py` (new): the plug-in, as the docstring of `evals/generate.py` describes it: `FINAL_DAY` =
  {D0}, `VALID_UNTIL` = {L}, `FAMILIES` with the `holdout4` builders, `CONVENTIONS_FINAL` and
  `KIND_ALSO_ACCEPTED_FINAL`.
- `evals/gen/holdout4_admin.py`, `evals/gen/holdout4_private.py` and `evals/gen/holdout4_adversarial.py` (new): the
  builders, made the way the `holdout3_*.py` modules are made.
- `writer-notes-holdout4.md` (new, in `/work`): for each entry id, its family, scenario and Land, and why each of its
  dates is what it is; and the two-page share and the Land mix you measured from holdout3's generator.

The composition:

- 126 entries: 84 template letters as PDFs (the twelve families in variants K, L, M and N), 20 adversarial PDFs (two
  of each of the five kinds of adversarial letter that `holdout3_adversarial.py` writes) and 22 photos of letters;
  24 of them adversarial; 112 scored dated items.
- The same share of two-page letters and the same mix of Länder as holdout3. Measure both from holdout3's generator,
  and state them in your notes.

How a letter's truth is made:

- Every date of a truth comes from a function of `evals/gen/law.py`, with a hand-worked `check(item, hand)`, as the
  earlier family modules write it.
- Every random draw comes from `rng_for("holdout4", <entry id>)`.
- Every sender is new: no sender name of an earlier split appears in holdout4.
- Each scored item, and each contract, carries the ids of the labelling conventions its dates rest on
  (`with_conventions` in `common.py`). Where one of them is disputed, it also carries the date under the other
  reading, worked out with `law.py`.
- A convention your letters need that `CONVENTIONS` does not state goes into `CONVENTIONS_FINAL`, with an id `f01`,
  `f02` and so on, `disputed` set when another defensible reading gives another date, and a text that cites statutes
  only.
- The new modules import each other and the generator's modules with relative imports (`from . import law`).

Do not write facts for the letters (no `facts.json`), and do not change `evals/generate.py` or
`evals/verify_labels.py`.

## Rules

- Work only in `/work`. There is no network. Read and change nothing outside `/work`.
- Every sender, person, address, account, file number and reference is made up, as in the earlier splits.
- Write every sentence of every letter in your own words. Copy no sentence from the earlier splits' letters or from
  any other file in your folder: a check compares the sentences of all splits.
- Never guess, name or write for any software that may later read what you make. Write nothing, in the letters, the
  code or the notes, about how the letters will be read, measured or compared.
- Name no AI model or product, your own included, in anything you write.
- The letters that `python -m evals.generate` writes into `evals/dataset/` are yours to look at. They are made again
  outside your folder from your code, and your copy is not kept.

## Checks, and when to stop

Run these from `/work`, and work until each one passes:

1. `python -m evals.generate --final-day {D0}`
2. `python -m evals.verify_labels`
3. `python -m pytest tests/test_eval_dataset.py -q`
4. `ruff check evals/gen`
5. `ruff format --check evals/gen`
6. `mypy evals/gen evals/generate.py`

`tests/test_eval_dataset.py` learns holdout4's composition in the next session. Until then, a failure that comes only
from a count it does not know yet is written in your notes, and every other test passes.

Keep `writer-notes-holdout4.md` up to date as you go. The session has a limited number of turns, and a follow-up
session, given this brief and the word "continue", goes on from your notes.

When all six checks pass, print the numbers of holdout4 entries, photos, adversarial entries and scored items, and
stop.
