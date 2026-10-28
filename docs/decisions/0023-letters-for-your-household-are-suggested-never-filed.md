# ADR 0023 — Letters for your household are suggested, never filed

**Status:** accepted · **Date:** 2026-10-27

## Context
Many people get letters for a partner or their children: the same address, often the same surname. Since the
first step (`secretary/addressee.py`), a letter whose addressee isn't the person says *Addressed to …* on its
page, and a reply to it can go out in that name; everything else about it stays the person's. People want to
say whose letter it is, find one person's letters, and answer them in that person's name only when that person
signs their own letters (a child doesn't).

Who a letter is for is easy to guess wrongly. A reading's addressee is a line of text: "Familie Rivera", "Sam
und Alex Rivera", "A. Rivera", a child's name followed by "c/o" and a parent's. Two people of a household can
share a surname and an initial. And a wrong filing is quiet: the letter leaves the person's own view, and a
reply may go out in the wrong name.

## Principle
The addressee suggests, the person decides ([ADR 0006](0006-read-only-agent-and-humble-automation.md)), as for
a sender's Land ([ADR 0019](0019-a-sender-s-land-is-suggested-never-set.md)). Nothing Ordnung reads files a
letter for someone.

## Decision
**The policy** is written in `secretary/household.py`'s docstring
([ADR 0007](0007-short-written-policies-over-growing-heuristics.md)):

1. **Suggest, never file.** A letter is filed for someone only by the person's press: *Yes* to *Is this letter
   for Alex Rivera?*, a choice under *Change*, *File these N* in the Inbox, or the ticked *Also file this
   letter for …* when they add the person from the letter (`PUT /api/household` with `also_file`,
   `PATCH /api/household`). Readings, the daily check, sync and the phone file nothing by themselves.
2. **Who a letter could be for** is worked out only for a letter whose addressee isn't the person (step 1's
   `addressed_to`): the addressee's name is compared with each person's by step 1's own rule (case, accents,
   umlauts, titles, word order and initials don't count; "c/o" ends the name). Exactly one person who matches
   is suggested; none, several, or an addressee naming several people ("Familie Rivera") give no suggestion.
3. **An answered letter** (filed for someone, or "No, it's mine") is never suggested again. A filing for a
   person who was removed counts as unanswered.
4. **Add … to your household** is offered on the computer for an unanswered letter whose addressee names one
   person nobody of the household could be, while there is room.
5. **The list:** names as typed, on one line of at most 120 characters, with a letter in them; never the
   person's own name, several people in one, or a name already there spelled otherwise; at most 12 people.
6. **A rename keeps the id** (`hhm_…`), so filed letters stay filed.
7. **A removal leaves the person's filings dormant**: *Undo* (the same id) brings them back; any other next
   change of the list drops them.
8. **Letters:** a filing of a letter in the trash is dormant and returns with the letter; deleting a letter for
   good removes its filing in the same transaction; the daily check removes filings of letters that no longer
   exist at all (left by a computer still on 0.2.0).
9. **Never seen by Claude.** Nothing of the household goes into a prompt, a draft request, Ask or a
   notification. Dates, reminders, numbers, Ask and Ideas keep treating every letter as the person's.

**Where it shows.** Settings → Profile & address → *Your household* (computer only). On a letter's page, after
*Addressed to …*: *For Alex Rivera* or *For you* with *Change* (*Who is this letter for?*), or the question
with *Yes*, *No, it's mine* and, with two people or more, *Someone else…*. In the Inbox, a *Whose letters*
choice and *File these N* for the letters addressed to one person; Inbox and Today rows say whose letter it
is (no Today filter). In the composer, a letter filed for someone who signs offers *Reply in Alex Rivera's
name* (the name as typed in Settings, not as read); for someone who doesn't sign, the letter goes out in the
person's own name. The field always starts with the person's own name. Every filing has *Undo*, which puts
back exactly the answer before. *Download a copy of your records* holds the people, the letters filed for each
and the ones the person said are theirs, never the suggestions.

**The phone.** A paired phone may file a letter, as it may correct one, but never change the list, as it never
changes the profile: `GET` and `PATCH /api/household` are a phone's (its filing is logged "Changed who a letter
is for on …"), `PUT /api/household` is computer-only ("household edits").

## Why a `meta` row
- **One row, `household`, no migration.** The schema stays at version 5, so a computer still on 0.2.0 accepts
  the synced versions and backups that carry the row and keeps it untouched (its scrub deletes only its own
  local keys); it just doesn't show it. A table or a column would raise the schema version, and 0.2.0 would
  refuse the newer database in hand-off sync and in a backup.
- **Ask's inputs don't change.** `Document`, the profile and Ask's tools stay as they are: Ask's ledger
  fingerprint and the store's ledger token read no `household` row, so recorded answers still replay.
  `models.py` is a benchmark digest file, so the household's models live in `secretary/household.py` and
  `api/routes/household.py`, and the letter's page answers a route-local `LetterDetail` with `household` (a
  `LetterFor`: `filed_for`, `mine`, `suggested`, `add`).
- **Writes publish `profile.updated`.** The live events are listed in `models.py`, so the household refreshes
  with the profile instead of an event of its own.
- **The *For taxes* choices follow the same rule:** the person's own choices about letters live in `meta`
  (`tax_choices`), not in `models.py`, and Ask keeps seeing Claude's own mark
  ([architecture](../architecture.md#data-model-simplified)).

## Rejected or deferred
- **Filing by itself, with an Undo.** Silent, and a wrong guess takes a letter out of the person's own view.
- **Asking Claude who a letter is for.** A model call per letter, open to injection; the reading's addressee
  is already there.
- **Ask knowing the household, My numbers' "About" groups, Ideas or reminders naming a person.** They change
  what Claude is given or Ask's tools, so their recordings would stop replaying; they wait for a paid
  recording.
- **Filters on Timeline, Letters or the Tax year page, a ZIP per person, Today's "See X's dates" and *Write in
  X's name* for a letter that answers none.** Left out to keep the step small.
- **A table or a column**, and **a new live event**: see above.

## Consequences and known limits
- A letter filed for someone is still the person's for everything Ordnung counts: its dates, reminders and
  numbers, and Ask and the Ideas treat it as theirs (README, Limitations).
- A suggestion can be wrong; it is only a question. Similar names ("Kim" and "Kim Rivera") are allowed, but a
  letter addressed to either then gets no suggestion.
- The household has at most 12 people, each name at most 120 characters; one `PATCH` files at most 1,000
  letters (the web app sends more in parts, with one *Undo*).
- Each filing rewrites the row (about 40 bytes per filed letter), so hand-off sync saves it like a profile
  edit.
- A computer still on 0.2.0 keeps the row but doesn't show it: every letter is the person's there. A letter
  deleted for good there leaves its filing (an id, nothing of the letter) until an updated computer in use runs
  its daily check. A letter's id comes from its file, so the same file added again gets that id: on an updated
  computer it starts unfiled (adding a letter drops a filing left under its id), on 0.2.0 it is filed as before.
