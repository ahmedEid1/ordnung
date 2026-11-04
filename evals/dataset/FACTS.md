# Facts of a final split

The letters of the final splits (holdout4 and newkinds) are read by an auditor who does not see their labels. What
the auditor reads off each letter is written down as facts: the date of an event the letter names, and the
arithmetic that turns it into a deadline. `evals/verify_labels.py` recomputes every date from these facts with a
calendar of its own (Python's `datetime` and the `holidays` package) and compares it with the letter's label.

The facts are arithmetic only. Which event counts, which period applies and whether its end moves off a weekend are
readings of the law. The auditor makes them; the facts write them down.

The earlier splits (dev, test, holdout, holdout2, holdout3) keep their facts in `evals/verify_labels.py` itself,
read by hand.

## The file

One file per final split, in the split's folder: `evals/dataset/<split>/facts.json`.

```json
{
  "split": "holdout4",
  "letters": {
    "<letter id>": {
      "slots": {
        "i0": { "...": "a fact" },
        "o0": { "...": "a fact" }
      },
      "price_change": { "...": "only for a price increase" }
    }
  }
}
```

A slot names one of the letter's obligations, in the order its entry in `manifest.json` lists them:

- `i0`, `i1`, … the obligations that are scored;
- `o0`, `o1`, … the optional ones;
- `term_end` and `cancel_by`: a contract's end of term and the last day a notice to cancel can arrive.

Any other slot name is refused.

## A fact

A slot holds one of three kinds of fact: dated, undatable or ambiguous. Every fact names its `source`:

- `A1`: the first blind reading of the letter;
- `A1p`: an adjudication of a slot where two readings disagreed. It saw both derivations, so for such a slot the
  recomputation is not an independent check;
- `A1re`: a fresh blind reading of a letter whose bytes changed after the first reading.

### A dated fact

```json
{
  "source": "A1",
  "land": "BW",
  "from": "2031-03-03",
  "event": "posting day",
  "steps": [
    {"op": "forward", "n": 4, "unit": "days", "shift": false},
    {"op": "forward", "n": 1, "unit": "months", "shift": true}
  ],
  "conventions": []
}
```

Posted on Monday 3 March 2031, the fourth day is Friday 7 March 2031. One month later is Monday 7 April 2031, a
working day, so the end shift moves nothing.

- `source`: see above.
- `land`: the Land whose public holidays count, as its code (`BW`, `BY`, `BE`, `BB`, `HB`, `HH`, `HE`, `MV`, `NI`,
  `NW`, `RP`, `SL`, `SN`, `ST`, `SH`, `TH`), or `null` when the letter names no Land. With `null` only nationwide
  holidays count, and the date must come out the same under every Land's holidays. Always stated.
- `from`: the event's date, `YYYY-MM-DD`: a posting day, a day of delivery, the letter's date, the start of a
  service, or a date the letter states.
- `event`: optional, the event in a few words.
- `steps`: the arithmetic, applied in order. An empty list for a date the letter states.
- `conventions`: optional, the ids of the benchmark's labelling conventions the derivation applies (`manifest.json`
  lists them).
- `conflicting`: optional, for a letter that gives more than one date for the same obligation: the other dates,
  each as a derivation (`from`, `steps`, optional `event`).
- `procedure_began`: optional, in a fact whose date runs from the notification of a Land authority's decision, in a
  Land whose administrative procedure act keeps its earlier rule for a procedure begun before that act changed: the
  day the administrative procedure it decides began, `YYYY-MM-DD`, when the letter states it (an application, a
  hearing, an objection). Leave it out of every other fact, even where the letter names such a day (a tax office's
  decision that names the day a return was filed, for example).

### Steps

Each step has `op`, `n` and `shift`, and a `unit` unless it is a `month_end`.

| `op` | `n` | `unit` | The step gives |
|---|---|---|---|
| `forward` | 1 or more | any unit | the day n units after the date |
| `back` | 1 or more | any unit | the latest day from which n units `forward` end on or before the date |
| `month_end` | 0 or more | none | the last day of the n-th calendar month after the date's month (0: its own month) |

Units:

- `days`: calendar days;
- `weeks`: seven days each, so the same weekday (§ 188 Abs. 2 BGB);
- `months`: the same day number n months later, or that month's last day when it has no such day (§ 188 Abs. 2
  and 3 BGB);
- `werktage`: Monday to Saturday, public holidays of the Land not counted; the date itself is not counted;
- `arbeitstage`: Monday to Friday, public holidays of the Land not counted; the date itself is not counted.

`shift` is `true` or `false`, and always stated. With `true`, a step that ends on a Saturday, Sunday or public
holiday of the Land moves to the next working day (Monday to Friday, not a holiday). A `back` step moves to the
working day before instead. Whether a step shifts is a reading of the law; the fact only states it.

More worked examples:

- A contract from Wednesday 1 October 2031 for 12 months, cancellable with one month's notice to the end of the term:
  - `term_end`: from `2031-10-01`, `forward` 12 `months`, then `back` 1 `days`: Thursday 30 September 2032;
  - `cancel_by`: the same two steps, then `back` 1 `months`: Tuesday 31 August 2032 (one month forward from it ends
    on 30 September, September having no 31st).

  Both are working days, so `shift` moves neither.
- The end of the second calendar month after Monday 14 July 2031: `month_end` with n 2 gives Tuesday 30 September
  2031.
- Three `werktage` after Tuesday 23 December 2031 in NW: 24 December counts, 25 and 26 December are holidays,
  Saturday 27 December counts, and Monday 29 December 2031 is the third.

### An undatable slot

```json
{"source": "A1", "undatable": true}
```

For an obligation the letter gives no date for, such as a period that starts on a day of receipt the letter does
not name. `undatable` is `true` when it is there.

### An ambiguous slot

```json
{
  "source": "A1",
  "land": null,
  "ambiguous": [
    {"from": "2031-07-08", "steps": []},
    {"from": "2031-08-07", "steps": []}
  ]
}
```

`ambiguous` lists two or more readings the letter leaves open, each a derivation.

## A price change

```json
"price_change": {
  "source": "A1",
  "effective_date": "2031-04-01",
  "letter_date": "2031-02-10",
  "basis": "§ 41 Abs. 5 EnWG",
  "old_amount": 72.0,
  "new_amount": 81.0
}
```

A letter's `price_change` gives the date the new price applies from, the letter's date, the legal basis and the old
and new monthly amounts, as the letter prints them. The recomputation checks the price change's dates and amounts
from these.

## What the check refuses

`python -m evals.verify_labels` reports a problem, and exits 1, for these among others:

- a key, `op`, `unit`, `source`, Land or slot name this grammar does not name, a step without `shift`, or a date that
  is not `YYYY-MM-DD`;
- a file whose `split` is not its folder, or facts for a letter that is not in that split;
- a slot the label does not have, or a dated label without a fact;
- a date that differs from the label, or that depends on the Land when `land` is `null`;
- conventions that do not exist, or that differ from the label's tags.

Before a final split has its facts file, its dates are not re-derived; the check says so. With `--require-facts`
that is a problem too.
