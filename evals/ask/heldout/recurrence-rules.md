# To-dos that repeat: the recurrence ledger

The recurrence ledger is the sample life's base ledger in which the to-dos you name in `recurrence.json` repeat by
the rules you give them, as a person sets a to-do to repeat. Questions on it (`"ledger": "recurrence"`) ask about
those to-dos: when the next one is due, which ones fall in a window, what they come to in a year.

## `recurrence.json`

```json
{"schema": "ask-heldout-recurrence/1",
 "todos": [{"id": "ho-rec-…", "letter": "<slug>", "item": 0,
            "rule": {"interval": 1, "unit": "months"}, "first": "YYYY-MM-DD"}]}
```

- `letter` and `item` name one to-do of the truth: `item` is its place in that letter's `items` in `manifest.json`
  (0 for the first).
- `rule` is how it repeats (below).
- `first` is its first occurrence as its letter gives it, before any move for a weekend or a holiday.

## Which to-dos may repeat

Six to-dos, each of a letter's truth, each with a date (`expected_due`) and without a `recurrence` of its own (a to-do
whose letter already makes it repeat keeps its letter's rule). Choose payments and appointments a person could
sensibly make repeat. Leave out the rent and every payment of the tenancy (the lease, a rent increase, a
service-charge statement): the law dates those itself (§ 556b BGB).

## The rule

| Field | Values | Meaning |
|---|---|---|
| `interval` | 1 to 120 | every `interval` units |
| `unit` | `days`, `weeks`, `months`, `years` | the unit |
| `day_of_month` | 1 to 31, or absent | in each month (a rule in months or years only): that day; a day past a month's end is that month's last day, so 31 is always the month's end |
| `working_day` | 1 to 10, or -1, or absent | in each month (a rule in months or years only): the Nth working day (Werktag) counted from the month's first; -1 is the month's last working day. It wins over `day_of_month` |

- Every year is every 12 months, every week every 7 days.
- A rule in months keeps the first occurrence's day, cut to a shorter month's last day (31 Jan, 28 Feb, 31 Mar).
- Use each of these at least once: monthly on a fixed day, quarterly, yearly, every two weeks, a working-day rule.

## Weekends and holidays

Decide from the statute (§ 193 BGB) whether an occurrence that falls on a Saturday, a Sunday or a public holiday
moves, and to which day; say why in `NOTES.md`; apply it in `recurrence_gold.py`. Its calendar is your own: a
hand-written table of the public holidays of North Rhine-Westphalia for 2026 and 2027, no calendar package.

## `recurrence_gold.py`

The standard library only. It defines three functions; each gets a to-do as `recurrence.json` gives it, with the
`kind`, `amount` and `direction` of its truth item added:

```python
def next_occurrence(todo: dict, today: datetime.date) -> datetime.date:
    """The first occurrence on or after today, moved as a weekend or holiday moves it."""


def occurrences(todo: dict, start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """Every occurrence from start to end (both included), each moved the same way."""


def year_total(todo: dict, year: int) -> float:
    """The to-do's amount summed over its occurrences that fall in that year."""
```

## A question about a repeating to-do

```json
{"id": "ho-…", "group": "recurrence", "category": "recurrence", "fact": "…", "phrasing": "en",
 "ledger": "recurrence", "text": "…", "gold": null, "list": null,
 "recurrence": {"todo": "ho-rec-…", "ask": "next", "with_amount": true}}
```

- `"ask": "next"`: the next occurrence (and with `"with_amount": true` its amount too);
- `"ask": "window", "from": "today", "to": "today+N"`: every occurrence in the window (`"state": "amount"` when the
  answer states each one's amount rather than its date);
- `"ask": "year_total", "year": 2027`: the amount over that year.

Its gold is computed for the day the set is asked on, so it too must be the same on every day from D0 to L: a next
occurrence must not fall inside the window, nor an occurrence on a window's edge. The self-check computes it for each
day and names any question whose answer changes.
