# ADR 0021 — A move is said, never guessed

**Status:** accepted · **Date:** 2026-10-09

## Context
A move means telling many places the new address: the citizens' office, where a new home has to be
registered within two weeks of moving in (§ 17 Abs. 1 BMG), and every bank, insurer, employer, landlord,
utility and office that writes to the old one. Ordnung already knows most of them from the person's
contracts and letters, and it has a new-address letter, but it wrote that letter one recipient at a time,
and changing the address in Settings did nothing else.

An address edit is not a move: it may fix a typo, or be entered for the first time. And nothing may be sent
or changed for the person ([ADR 0006](0006-read-only-agent-and-humble-automation.md)).

## Principle
A move exists only once the person says so. Ordnung then lists who needs the new address; the person
writes, sends and ticks off.

## Decision
- **Said in Settings.** Only the person sets `Profile.moved_on`: Settings → Profile offers *I moved* when
  they change an address that was already saved, with the day they moved in. Someone who saved the new
  address first, with no move standing, gets *Moved recently? Start the moving checklist* instead: they type
  the address before and the day, and *Start the checklist* saves the move alone; the address saved stays.
  Either way the profile keeps two keys (`moved_on`, and `old_address`, the address before), which
  `PUT /api/profile` takes only for a move in the last six months or the next three (422 otherwise), with or
  without a new address in the same request. *Stop the checklist* clears both. Ordnung never changes the
  profile, nor the address, by itself.
- **Ideas as rows.** A rule, `moved_house` (`secretary/moving.py`), turns the move and the ledger into one
  Idea per row, which Today shows as its own *Moving checklist* card:
  - register at the citizens' office within two weeks of moving in (§ 17 Abs. 1 BMG). The day comes from
    the rules engine and is never moved off a weekend or holiday: whether that applies to this duty is not
    settled, so the checklist shows the earlier, safe day;
  - *Tell X your new address*, for each organisation with the old address on record: a running contract,
    or a letter of the last three years from a kind of sender that keeps an address (a bank, an insurer, an
    employer, a landlord, a utility, a telecom, a university, a tax office, an immigration office or the
    broadcaster) — never one with scam signs or one kept private, nor a contract read from such a letter —
    each with the new-address letter one click away, filled in with the old address and the day;
  - the broadcasting fee office, when no listed organisation is it.
- **How rows end.** The person ticks a row off or marks it *Not needed* (`PATCH /api/suggestions/{id}`,
  with Undo, also from a paired phone). A sender's row goes once the person marks a new-address letter to
  them as sent: the rule stops producing it and the reconcile expires it, and nothing is ticked off for
  them. Every row's fingerprint holds the move's day, so ticks last and a new move starts a fresh list. The
  checklist ends six months after the move, or at once with *Stop the checklist*.
- **One law.** § 17 Abs. 1 BMG is the only law the checklist states. It joins `IDEA_LAWS`, so Ask's check
  knows it like the rules catalog's. It is no catalog rule: the catalog holds the rules the date engine
  applies, and its texts feed the weekly review's and the daily note's own checks.
- **What stays out.** No row names an address: an organisation's name and the day to register by are what
  reach *Weekly Ideas* and the daily note, like every Idea's title, and a contract named after the flat is
  counted without its name. The old address is never put into a prompt, and Ask's tools return neither
  key.
- **Small on purpose.** There is no route, no column and no migration: two keys in the profile, rows in the
  existing Ideas, and a free `target_type` on an Idea's action. Nothing is sent, paid or cancelled; letters
  stay drafts the person prints and sends.

## Rejected
- **Inferring a move from any address edit:** a typo fix would start a checklist. Asking costs one
  checkbox.
- **Offering the move only next to a changed address:** someone who saved the new address first, and wants
  the checklist later, had no way to start it.
- **To-dos per row:** they would land in Ask's ledger fingerprint, so its recordings would stop replaying,
  and a to-do has no link to an organisation.
- **A checklist stored in the profile**, ticked through `PUT /api/profile`: a computer-only route, so a
  phone couldn't tick, and a second store of "done" next to the Ideas.
- **A new `POST /api/moving` route:** a phone-scope class and a mock route for nothing the Ideas' PATCH
  doesn't do already.
- **A new draft kind for Ideas**, so a row could start the letter itself: it changes the weekly review's
  schema, so its recordings would stop replaying.

## Consequences and known limits
- The checklist knows only the organisations Ordnung has seen. A new landlord or a shop may be listed
  (*Not needed* handles it); a doctor, a car or an online shop Ordnung never saw is missing.
- Moving abroad (deregistering) and the contract rights a move may give are out of scope.
- Changing the day of the move starts the list again.
- A computer still on 0.2.0 that receives the checklist by hand-off sync shows its rows among its Ideas and
  never takes them away, and saving the profile there forgets the move (it ignores keys it doesn't know).
  Update both computers.
