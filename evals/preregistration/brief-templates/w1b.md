# Brief W1b: the newkinds letters

## The task

You write the generator code for a second new set of synthetic German letters, the split `newkinds`: seven kinds of
letter that no earlier split has. Each letter comes with its truth: what the letter asks of the person it is
addressed to, and the dates the law gives for it. For these kinds the statute arithmetic does not exist yet: you add
it to `evals/gen/law.py`, worked out from the statute texts in `evals/law/` alone. You also write down how the two
new splits were made, in `evals/dataset/VERIFICATION.md`, and teach the dataset's tests their composition.

The seven kinds:

1. a court payment order (Mahnbescheid);
2. an enforcement order (Vollstreckungsbescheid);
3. an employer's notice of dismissal (Kündigung eines Arbeitsverhältnisses);
4. a landlord's notice to end a lease (Kündigung eines Mietverhältnisses);
5. a landlord's request to raise the rent (Mieterhöhungsverlangen);
6. a statement of operating costs that comes late (Betriebskostenabrechnung);
7. a contract made at a distance or away from business premises, with its notice of the right of withdrawal
   (Widerrufsbelehrung).

## The days

- Today, for every letter of `newkinds`, is {D0}.
- The letters are valid through {L}: they may be read on any day from {D0} to {L}.
- Every letter is posted between 6 and 2 days before {D0}.
- Every scored date, every end of a contract's term, every last day to cancel and every appointment falls after
  {L}.

## Your folder

Everything is under `/work`, and there is no network.

- `evals/gen/`: the generator, with the `holdout4` modules and `evals/gen/final.py` written in an earlier session.
  `law.py` holds the statute arithmetic, `common.py` cases, items, `SPLIT_VARIANTS` and `DOCUMENT_KINDS`.
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

- `evals/gen/law.py`: new functions for the seven kinds, each worked out from the statute texts in `evals/law/` only,
  with its legal basis (the norms it applies) in its docstring. Change no existing function.
- `evals/gen/newkinds.py` (new): the builders of the seven kinds.
- `evals/gen/final.py`: the `newkinds` builders in `FAMILIES`, and the `newkinds` entries of `CONVENTIONS_FINAL` and
  `KIND_ALSO_ACCEPTED_FINAL`.
- `evals/gen/common.py`: only what `Case.__post_init__` needs to accept a `newkinds` letter. `newkinds` has no
  template variants and stays out of `SPLIT_VARIANTS`.
- `evals/dataset/VERIFICATION.md`: two sections added at its end, "Holdout4 split (variants K–N)" and "Newkinds
  split", each with the parts Method, Legal rules applied, Judgement calls and Not date-scored. Change nothing above
  them: only what you add at the end is kept.
- `tests/test_eval_dataset.py`: the composition of both new splits (holdout4: 126 entries, 22 photos, 24 adversarial,
  112 scored; newkinds: 32 entries, 4 photos, the number of scored items your letters have), and that no sender of
  holdout4 or newkinds appears in any other split.
- `writer-notes-newkinds.md` (new, in `/work`): for each entry id, its kind, scenario and Land, and why each of its
  dates is what it is.

The composition: four one-page letters of each kind and 4 photos of letters, 32 entries, with about 28 scored dated
items.

How a letter's truth is made:

- Each letter's document kind is one of `DOCUMENT_KINDS` in `common.py`. Where a second kind fits it as well, name
  that one in `KIND_ALSO_ACCEPTED_FINAL`.
- Every date of a truth comes from a function of `evals/gen/law.py`, with a hand-worked `check(item, hand)`, as the
  earlier family modules write it.
- Every random draw comes from `rng_for("newkinds", <entry id>)`.
- Every sender is new: no sender name of another split appears in newkinds.
- Each scored item, and each contract, carries the ids of the labelling conventions its dates rest on
  (`with_conventions` in `common.py`). Where one of them is disputed, it also carries the date under the other
  reading, worked out with `law.py`.
- A convention your letters need that neither `CONVENTIONS` nor `CONVENTIONS_FINAL` states goes into
  `CONVENTIONS_FINAL`, with the next free id, `disputed` set when another defensible reading gives another date, and
  a text that cites statutes only.
- The new module imports the generator's modules with relative imports (`from . import law`).
- The holdout4 letters stay exactly as they are.

Do not write facts for the letters (no `facts.json`), and do not change `evals/generate.py` or
`evals/verify_labels.py`.

## Rules

- Work only in `/work`. There is no network. Read and change nothing outside `/work`.
- Every sender, person, address, account, file number and reference is made up, as in the earlier splits.
- Write every sentence of every letter in your own words. Copy no sentence from the earlier splits' letters or from
  any other file in your folder: a check compares the sentences of all splits.
- Never guess, name or write for any software that may later read what you make. Write nothing, in the letters, the
  code, the notes or `VERIFICATION.md`, about how the letters will be read, measured or compared.
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
6. `python -m mypy --explicit-package-bases evals/gen evals/generate.py`

Keep `writer-notes-newkinds.md` up to date as you go. The session has a limited number of turns, and a follow-up
session, given this brief and the word "continue", goes on from your notes.

When all six checks pass, print the numbers of newkinds entries, photos and scored items, and stop.
