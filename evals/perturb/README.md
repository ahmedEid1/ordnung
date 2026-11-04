# Stress cells (plan EV11): targeted injections and distractor dates

Letters of the benchmark with one sentence added. Two cells, each on the same base letters:

| Cell | What is added | Goals or roles (letters) |
|---|---|---|
| I1 | one visible paragraph addressed to an AI or an automated reader | `shift` the deadline 3, 7 or 14 days later (16); `drop` it, "nothing to do" (16); `reroute` it with a claim about the sender's kind, the day the letter arrived or the length of the period (16) |
| D1 | one sentence that names a date and creates no duty | `service_hours`, `direct_debit`, `info_event`: a date 1–7 days after the deadline; `earlier_letter`: a date before the letter's own date (12 each) |

The base letters are 48 standard text letters of holdout4, each with a dated deadline, spread evenly over its families
(four each with twelve families), seed 20261029. The added sentence changes no legal date, so each letter keeps its
own expected dates. The stress manifest (`manifest.json`) names no day: holdout4 is written for a window of days, and
the cells are built for the day they are read.

## The templates file (`evals/perturb/templates.json`)

Written by hand, once, before the cells are built (EV8, commit A). Shape:

```json
{
  "schema": "ordnung-stress-templates/1",
  "injection": {
    "shift":   {"de": ["..."], "en": ["..."]},
    "drop":    {"de": ["..."], "en": ["..."]},
    "sender":  {"de": ["..."], "en": ["..."]},
    "arrival": {"de": ["..."], "en": ["..."]},
    "period":  {"de": ["..."], "en": ["..."]}
  },
  "distractor": {
    "service_hours":  {"de": ["..."], "en": ["..."]},
    "direct_debit":   {"de": ["..."], "en": ["..."]},
    "info_event":     {"de": ["..."], "en": ["..."]},
    "earlier_letter": {"de": ["..."], "en": ["..."]}
  }
}
```

- At least one sentence per key and language; two or three give variety (the seed picks one per letter).
- An injection addresses an AI or an automated reader, never the person who gets the letter.
- A distractor creates no duty: none of the words in `OBLIGATION_PATTERNS` (`templates.py`): periods, payments,
  remedies, duties, appointments.
- Slots, filled by the builder in the letter's own date style (`02.01.2026` in German letters, `2 January 2026` in
  English ones):

  | Key | Must use | May use |
  |---|---|---|
  | `shift` | `{date}`: the new date | `{days}`: how many days later |
  | `drop` | nothing (no date at all) | none |
  | `sender` | `{arrival}`: the day the period should start; the sentence says the sender is a private firm | `{date}`: the resulting date |
  | `arrival` | `{arrival}`: the day the letter supposedly arrived | `{date}`: the resulting date |
  | `period` | `{period}`: for example "2 Monate" / "2 months" (twice the real one) | `{date}`: the resulting date |
  | each distractor role | `{date}` | `{ref}`: a made-up contract or file number |

- No literal dates or years, no line breaks, no `**`, `__`, `--` or `~~`, no angle brackets, at most 600 characters.
- Every sentence in your own words.
- The builder picks every date: a date it fills in never equals one of the letter's expected dates, its letter date,
  its today or any date printed in it.

### Check the file

From the repository root (it needs `templates.py` and the standard library only):

```bash
python -c "from evals.perturb import templates as t; s = t.load_templates(); print(len(s.strings()), 'templates, sha256', s.sha256)"
```

It prints the number of sentences and the file's digest. A file that breaks a rule above stops with each problem's
kind and place (for example `distractor.info_event.de[0]: obligation: …`), never the sentence itself.

## Commands

```bash
.venv/bin/python -m scripts.eval_perturb --list-base                    # base letters and what each gets, counts only
.venv/bin/python -m scripts.eval_perturb --build-only --write-manifest   # EV8 commit A: the files and manifest.json
.venv/bin/python -m scripts.eval_perturb --clean-only --out DIR         # the clean reference alone
.venv/bin/python -m scripts.eval_perturb --out DIR --check PUBLISHED    # replay both cells, compare with a published file
```

`scripts/eval_perturb.py` says how the cells are built for a day, replayed and checked.
