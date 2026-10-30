"""Whether a letter counts "for taxes" (module policy, ADR 0007).

Claude marks a letter for taxes when it reads it (``Document.tax_relevant``, with ``tax_note``). The person can
mark any letter themselves, or take one Claude marked off, with *For taxes* on the letter's page.

1. **The person's choice wins, both ways.** A letter counts for taxes when the person marked it, never when
   they took it off, and otherwise when Claude marked it (:func:`for_taxes`).
2. **The choice is kept apart from Claude's reading**, in one ``meta`` row
   (:data:`ordnung.db.store.TAX_CHOICES_META_KEY`, no migration). *Read again* overwrites Claude's mark and
   never the choice, and nothing Claude is asked changes.
3. **What follows it:** the Tax year page, *Export letters* with *Only letters for taxes* (the ZIP and its
   ``index.csv``), the tax-season Idea and the weekly session's "Keep it with your tax papers".
4. **Ask and the weekly review follow it too** (ADR 0025), for the letters they may read: Ask's
   ``get_document`` (with a sentence saying the person chose, and without Claude's note on a letter they took
   off) and the review's snapshot. A private letter's choice reaches neither. Without a choice both read as
   Claude marked the letter, so their recorded answers still replay. The tax-season Idea follows the choice
   (point 3), and its title, like every Idea's, is part of what the weekly review and the daily note send: in
   tax season a choice can make it appear there or go away.
5. **Only a press sets it:** the toggle or its Undo. Readings, sync and Ideas never do. Deleting a letter for
   good drops its choice; the trash keeps it. A letter just added has none, even when one was left under its
   id (:meth:`ordnung.db.store.Store.add_document`).
"""

from __future__ import annotations

from collections.abc import Mapping

from ordnung.models import Document


def for_taxes(doc: Document, choices: Mapping[str, bool]) -> bool:
    """Whether a letter counts for taxes: the person's own choice if they made one, else Claude's mark."""
    choice = choices.get(doc.id)
    return doc.tax_relevant if choice is None else choice
