# Brief A1c: apply the labelling conventions to a sealed reading

## The task

Earlier readers read a set of synthetic German letters and derived, from German law alone, what each letter requires
and by when. Their findings are sealed in `sealed/`, one file per batch. The set has labelling conventions: fixed
choices for points where a letter or the law leaves room, listed in `conventions.md`, each with an id. You apply
those conventions to the sealed findings, without the letters: for each slot of each letter, the date under the
conventions, the ids of the conventions you applied, and whether they change the earlier reader's date.

## The days

- Today, for every letter, is {D0}.
- {L} is the last day the letters are meant to be read.

## Your folder

Everything is under `/work`, and there is no network.

- `sealed/`: the earlier readers' files, `derived-<batch>.json`, in the format `"ev8-derived/1"`: per letter its
  slots (each with `status`, `date` or `candidates`, `steps`, `citations` and `why`), its facts in the grammar of
  `FACTS.md`, and its notes.
- `conventions.md`: the labelling conventions, each with its id and whether it is disputed.
- `law/`: the texts of the statutes, one file per law, with `SOURCES.md`.
- `FACTS.md`: the grammar of the facts.

Python is installed, with the `holidays` package.

## What you write

One file, and no other file:

- `audit/derived-conv.json`, written again after every letter you finish.

It has this shape:

    {"format": "ev8-derived-conv/1",
     "letters": {"L001": {"slots": {"i0": SLOT, "term_end": SLOT},
                          "facts": [FACT, FACT]}}}

- Every letter and every slot of the sealed files appears, with the same names; none is added and none is dropped.
- A SLOT is the sealed slot's keys, with the date under the conventions (`status`, `date` or `candidates`, `steps`,
  `citations`, `why`), and two more keys:
  - `ids_applied`: the ids of every convention that bears on the slot, for example `["c03"]`, or `[]`;
  - `changed`: `true` when the conventions give another date, set of candidates or status than the sealed slot,
    else `false`.
- A FACT, one per slot: the sealed fact for the slot with the conventions applied. Its `from`, `steps` or `land`
  change only where a convention changes them; the ids go into `conventions`; `slot` and `source` stay as the sealed
  file gives them.

## Rules

- Work only in `/work`. There is no network. Read and change nothing outside `/work`, change nothing in `sealed/`,
  and write nothing but the file above: run any calculation with `python -c` or from standard input, and save no
  script or scratch file.
- You have no letters: work from the sealed findings and `conventions.md`. Where a convention needs a fact the sealed
  findings do not give, keep the sealed date, set `changed` to `false`, and say in `why` what is missing.
- Apply a convention only where its text covers the slot. Where the sealed reading already agrees with a convention,
  name its id and keep the date.
- Do not judge whether a convention is right in law; apply it as written. If you think one is wrong in law, say so in
  `why`, with the statute.
- Public holidays come from the `holidays` package; check its holidays that depend on Easter against your own
  computation of Easter Sunday.
- Never guess, name or write for any software that may later read what you make, and write nothing about how anything
  will be measured or compared.
- Name no AI model or product, your own included, in anything you write.

## Checks, and when to stop

Before you stop, check that:

- `python -m json.tool audit/derived-conv.json` reads the file without an error;
- its letters and slots are exactly those of the files in `sealed/`;
- each slot has `ids_applied` and `changed`, and the keys its `status` needs.

Then print the number of letters, of slots, and of slots with `changed` true, and stop.
