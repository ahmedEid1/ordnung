# ADR 0025 — Ask and the Ideas say whose it is

**Status:** accepted · **Date:** 2026-10-29 · Amends [ADR 0023](0023-letters-for-your-household-are-suggested-never-filed.md)
(its point 9)

## Context
[ADR 0023](0023-letters-for-your-household-are-suggested-never-filed.md) let the person file a letter for
someone of their household, and kept Claude out of it: Ask, the Ideas, My numbers and the reminders went on
treating every letter as the person's, because what Ask's tools return and what the weekly review is given are
recorded, and changing them stops recorded answers from replaying. That left real gaps. A partner's health
insurance number was listed as the person's own on My numbers, and Ask's numbers tool handed it over the same
way, so an answer could give it as the person's. An Idea about a child's passport said "Your passport
expires". The person's own *For taxes* choice (ADR 0023 kept it from Claude by the same rule) didn't reach Ask
or the weekly review either, so a letter the person took off their letters for taxes could still come back as
one for taxes in Ask.

## Principle
Whose a letter is comes only from the person's filing, never from the addressee or a guess (ADR 0023). Claude
may be told what the person decided, as Ordnung's own record, when it helps answer what they asked, and never
more than their own screen shows.

## Decision
- **The rule** (`secretary/household.py` point 10, `filed`): a letter is someone's of the household only when the
  person filed it for them (a link to someone still in the list, the letter outside the trash). Every other
  letter is the person's own: no link, a suggestion, "No, it's mine", or filed for someone since removed. It is
  worked out from the links on every read, so filing, *Undo*, removing someone and *Restore* from the trash
  change it at once.
- **My numbers** (`numbers.py`): the numbers and identity documents of a letter filed for someone go under
  *About Alex Rivera* on the first tab, which is then *People*. A call sheet's number, a case reference or an
  open case all of whose letters are one person's is tagged *For Alex Rivera*; a number letters of two people
  show says "Also on letters for … — check whose it is". The label rule still comes first, and the addressee is
  never read. A phone masks their numbers like the person's.
- **What Ask is given** (`assistant/mcp_server.py`, which reads the household only through
  `household.ask_view` and `Ledger.household_filed`): `get_profile` adds `household` (each person's id and name
  as typed, with the letters the person filed for them, newest first, at most 50) and `household_note`;
  `get_document` adds `filed_for`; `get_my_numbers` puts their numbers under `household`, marks `filed_for` and
  `also_for`, and adds a note that says never to give a household person's number as the person's own. Letters
  the person keeps private are left out, and `household_note` says whose they are isn't known; Ask is told
  never whether someone signs, "mine" or a suggestion.
- ***For taxes*** (`secretary/tax_choice.py` point 4): `get_document` says whether a letter counts for taxes by
  the person's choice, else Claude's mark (`for_taxes`). One of two sentences says when the person chose
  (`tax_choice`: "The person marked this letter for taxes themselves." or "The person took this letter off their
  letters for taxes."), and Claude's tax note is left out of a letter the person took off. The weekly review's
  snapshot (`review._document_row`) flags each letter by the same rule. A private letter's choice reaches
  neither.
- **No tool description, server instruction or prompt changes.** The rule reaches Claude in the record, written
  by code, beside the data it is about. A description goes with every Ask call, so changing one would give
  every recorded Ask answer an input it wasn't recorded with. The Ask prompts lock gains an `ask_tools` entry
  (the digest of the server's instructions, its tools, the allowed tools and the cost cap), written by the next
  recording, which then refuses such a change until the Ask prompt's version moves.
- **Empty means as before.** Without people and without a choice, no tool's answer carries either, byte for byte,
  and Ask's ledger fingerprint hashes as before, so the answers recorded then still replay. With them, the
  fingerprint hashes the choices of the letters Ask may read and what `ask_view` gives, and the store's ledger
  token watches both rows (`LEDGER_META_KEYS`).
- **The Ideas** (`secretary/triggers.py`, `named`): an Idea all of whose letters are filed for one person, none
  of them kept private (its title reaches Claude), starts "For Alex Rivera: …"; the passport and residence permit
  Ideas say it in their own words ("Alex Rivera's passport expires …", "Renew Alex Rivera's passport before
  extending their residence permit"), with the same law (§ 81 Abs. 4 AufenthG) and rationale. A name that doesn't
  end in a letter gets "For Kim 2: Passport expires …". Never named: the tax documents, the calendar file, the
  student permit card, the move, a sender's Land and a contract's cancel window, because a contract's decision is
  the person's. The name is not in the Idea's fingerprint, so filing a letter renames the same Idea and keeps the
  person's *Not relevant* or *Remind me in a week*; household writes refresh the Ideas. `passport_before_permit`
  pairs a passport only with the same person's permit, and the student permit card reads only the person's own
  permit. Claude's own weekly Ideas get no name added.
- **Reminders and the Timeline:** the calendar file and calendar sync *With details* put the name after the
  symbol ("⌛ Alex Rivera: Passport expires"), the morning notification *With details* in front of the title;
  *Discreet* never names anyone, and a contract's dates are never named. On the Timeline a date from their
  letter starts its second line with *For Alex Rivera ·*, as Today's rows do (the web app's; nothing reaches
  Claude for it).

## Rejected
- **Pseudonyms that code swaps back.** The letters' own text names the person anyway, and an answer's names
  would have to be rewritten after the check.
- **An empty `household` section on every answer.** It would change every recorded answer for nothing.
- **Grouping by the addressee.** A guess (ADR 0023), and a wrong one moves a number silently.
- **German possessives ("Alex Riveras").** The app's own text is English.
- **Naming a contract's dates after someone, and a household in the demo.** A contract's decision is the
  person's; a demo household would make every demo answer stale.

## Consequences and known limits
- What reaches Claude grows: names as typed and which letters are filed for whom, through Ask and only when the
  person asks; a name inside an Idea's title, which *Weekly Ideas* and the daily note send like every Idea's
  title. docs/privacy.md says so.
- A dismissed Idea keeps the title it had: one with a name stays among the dismissed titles *Weekly Ideas*
  sends until *Delete everything*. An Idea that stops firing keeps its last title too.
- The dates and to-dos stay the person's to act on: Today, the Timeline and the reminders say whose a date is,
  but nothing is split by person, and the weekly review's letters carry no filing.
- The Ask benchmark has a household group (five questions on a copy of its ledger with two letters filed for
  someone), reported apart from its headline.
- In the demo, filing a letter, adding someone or marking a letter for taxes changes the fingerprint, so the
  suggested questions' recorded answers stop fitting until the demo starts over.
- A computer still on 0.3.0 shows every number as the person's and the Ideas without names; Ideas it refreshes
  lose the name until an updated computer refreshes them.
