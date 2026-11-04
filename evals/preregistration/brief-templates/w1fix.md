# Brief W1-fix: correct the dates named in a fix list

## The task

A blind reading of the holdout4 and newkinds letters found slots whose dates, or the day on which the procedure of
an authority's decision began, do not follow from the letter and the statutes. The file `fix-list.md` in your folder
names each one: the entry id, the slot (`i0`, `i1`, ... for an item in the order of the entry's truth, `o0`, ... for an
optional item, `term_end` or `cancel_by` for a contract) and the reason, with the statutes it rests on. You correct
exactly these slots in the generator code, and nothing else.

## The days

- Today, for every letter of holdout4 and newkinds, is {D0}.
- The letters are valid through {L}.
- Every date you change still falls after {L}, as every scored date, end of term, last day to cancel and
  appointment must.

## Your folder

Everything is under `/work`, and there is no network.

- `fix-list.md`: the slots to correct, one per line, with their reasons.
- `evals/gen/`: the generator, with the holdout4 and newkinds modules, `final.py` and the statute arithmetic in
  `law.py`.
- `evals/generate.py`, `evals/verify_labels.py`, `evals/law/` (the statute texts), `evals/dataset/VERIFICATION.md`
  (a shortened copy), `tests/test_eval_dataset.py`, `pyproject.toml` (the tool settings only), `constraints.txt` and
  the fonts under `/work/src`.

Python, with the packages the generator needs, is installed.

## What you write

Only the files under `evals/gen/` that the slots of `fix-list.md` need: the module that builds each named entry, and
`law.py` or `final.py` where the correction needs them. Change no other file.

For each slot in `fix-list.md`:

- make its date follow from the statutes as the reason states, through a function of `law.py` and a new hand-worked
  `check(item, hand)`;
- keep its labelling-convention ids, and the date under the other reading of a disputed one, true to the corrected
  derivation (`with_conventions` in `common.py`);
- change the letter's text only where the correction cannot be made without it.

Where `fix-list.md` marks a slot `ambiguous` and names its candidate dates, the slot is left open between them, and
its letter's text stays as it is. For an item, `expected_due` is `"ambiguous"` and its `candidates` are those dates,
as the earlier modules write such an item with `undated_item` in `common.py`. For a contract date, the slot's key
(`expected_current_term_end` or `expected_cancel_by`) is `"ambiguous"`, and the contract's `candidates` hold those
dates under that key. Each candidate date still comes from a function of `law.py`, with a hand-worked check.

Where `fix-list.md` gives a slot's procedure start, the day the procedure of an authority's decision began
(`procedure began: YYYY-MM-DD` or `procedure began: not stated`), the module that builds the entry passes that day to
`law.py` as `procedure_began`, or passes none, through `objection_item` in `common.py` as the earlier modules do; the
item's `spec` then states that day as its `procedure_began`, or holds no such key. Its date may stay as it is; where
the start changes it, the date follows from `law.py` as for any other slot. The letter's text keeps the day it states.

Every entry that `fix-list.md` does not name comes out of `python -m evals.generate --final-day {D0}` byte for byte as
before your change.

If you find that a reason is wrong in law, change nothing for that slot, and say why, with the statutes, in your last
message.

## Rules

- Work only in `/work`. There is no network. Read and change nothing outside `/work`.
- Every sender, person, address, account, file number and reference you add is made up, as the rest are.
- Write any sentence you add or change in your own words, and copy none from any other file in your folder.
- Never guess, name or write for any software that may later read what you make. Write nothing, in the letters or the
  code, about how the letters will be read, measured or compared.
- Name no AI model or product, your own included, in anything you write.
- The letters that `python -m evals.generate` writes into `evals/dataset/` are yours to look at. They are made again
  outside your folder from your code, and your copy is not kept.

## Checks, and when to stop

Before your first change, run `python -m evals.generate --final-day {D0}` and keep the sha256 of every file it writes
for an entry that `fix-list.md` does not name. Then run these from `/work`, and work until each one passes:

1. `python -m evals.generate --final-day {D0}`
2. `python -m evals.verify_labels`
3. `python -m pytest tests/test_eval_dataset.py -q`
4. `ruff check evals/gen`
5. `ruff format --check evals/gen`
6. `python -m mypy --explicit-package-bases evals/gen evals/generate.py`

and check that every file of an entry not named in `fix-list.md` has its sha256 from before.

When all pass, print the entry ids and slots you corrected and those you left as they were, and stop.
