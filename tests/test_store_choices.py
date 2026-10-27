"""The person's own choices kept in ``meta`` beside the letters (D3): "For taxes" (``tax_choices``) and the
household (``household``). No migration: both are one row each, synced like the profile, and Ask's ledger
token never moves for them (it watches only the profile row of ``meta``)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from ordnung.db.store import (
    HOUSEHOLD_META_KEY,
    PERSON_META_KEY,
    TAX_CHOICES_META_KEY,
    NotFoundError,
    Store,
    person_write,
)
from ordnung.ids import PREFIXES, new_id, prefix_of
from ordnung.models import PROOF_SOURCE, Direction, DocumentExtraction
from ordnung.secretary.tax_choice import for_taxes


def _letter(
    store: Store,
    name: str,
    *,
    id: str | None = None,
    recipient: str | None = None,
    read: bool = True,
    direction: Direction = "incoming",
    source: str = "upload",
) -> str:
    """A letter (no file on disk); with ``read`` a reading that names ``recipient``."""
    sha = name.encode().hex().ljust(64, "0")[:64]
    document = store.add_document(
        id=id,
        sha256=sha,
        filename=f"{name}.pdf",
        mime="application/pdf",
        file_path=f"files/{name}.pdf",
        direction=direction,
        source=source,
        status="processed",
    )
    if read:
        extraction = DocumentExtraction(
            kind="invoice", title=name, summary="s", explanation="e", recipient_name=recipient
        )
        store.update_document(document.id, extraction=extraction)
    return document.id


def _raw(store: Store, key: str) -> str | None:
    return store.get_meta(key)


def _household(links: dict[str, str]) -> str:
    member = {"id": "hhm_0123456789ab", "name": "Alex Rivera", "signs": True}
    return json.dumps({"format": 1, "members": [member], "links": links}, separators=(",", ":"))


@contextmanager
def _statements(store: Store) -> Iterator[list[str]]:
    """The SQL this thread's connection runs inside the block."""
    seen: list[str] = []
    conn = store._conn()
    conn.set_trace_callback(seen.append)
    try:
        yield seen
    finally:
        conn.set_trace_callback(None)


def _state(store: Store) -> tuple[int, int]:
    """What moves when this connection or another writes: ``total_changes`` and ``data_version``."""
    conn = store._conn()
    return conn.total_changes, int(conn.execute("PRAGMA data_version").fetchone()[0])


# --------------------------------------------------------------------------------------------------
# the keys and the id prefix
# --------------------------------------------------------------------------------------------------


def test_the_keys_and_the_household_id_prefix() -> None:
    assert TAX_CHOICES_META_KEY == "tax_choices"
    assert HOUSEHOLD_META_KEY == "household"
    assert "hhm" in PREFIXES
    member = new_id("hhm")
    assert prefix_of(member) == "hhm" and len(member) == len("hhm_") + 12


# --------------------------------------------------------------------------------------------------
# tax choices
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("marked", "choice", "counts"),
    [(False, None, False), (True, None, True), (False, True, True), (True, False, False), (True, True, True)],
)
def test_for_taxes_is_the_persons_choice_else_claudes_mark(
    store: Store, marked: bool, choice: bool | None, counts: bool
) -> None:
    letter = _letter(store, "letter")
    document = store.update_document(letter, tax_relevant=marked)
    choices = {} if choice is None else {letter: choice}
    assert for_taxes(document, choices) is counts
    assert for_taxes(document, {"doc_another": not counts}) is marked


def test_a_tax_choice_is_set_changed_and_cleared(store: Store) -> None:
    first, second = _letter(store, "first"), _letter(store, "second")
    assert store.tax_choices() == {}
    assert _raw(store, TAX_CHOICES_META_KEY) is None
    assert store.set_tax_choice(first, True) is True
    assert store.set_tax_choice(second, False) is True
    assert store.tax_choices() == {first: True, second: False}
    # canonical JSON: sorted keys, compact
    assert _raw(store, TAX_CHOICES_META_KEY) == json.dumps(
        {first: True, second: False}, sort_keys=True, separators=(",", ":")
    )
    assert store.set_tax_choice(first, False) is True
    assert store.tax_choices() == {first: False, second: False}
    assert store.set_tax_choice(first, None) is True
    assert store.tax_choices() == {second: False}
    assert store.set_tax_choice(second, None) is True
    # no row while there are no choices: a library that never uses them is as before
    assert _raw(store, TAX_CHOICES_META_KEY) is None


def test_an_unchanged_tax_choice_writes_nothing(store: Store) -> None:
    letter = _letter(store, "letter")
    with person_write():
        assert store.set_tax_choice(letter, True) is True
    counted = store.get_meta(PERSON_META_KEY)
    assert counted == "1"
    before = _state(store)
    with person_write():
        assert store.set_tax_choice(letter, True) is False
        other = _letter(store, "other", read=False)
    # the letter added above wrote; the unchanged choice did not
    assert int(store.get_meta(PERSON_META_KEY) or 0) == 2
    before = _state(store)
    with person_write():
        assert store.set_tax_choice(other, None) is False  # clearing what isn't there
        assert store.set_tax_choice(letter, True) is False
    assert _state(store) == before
    assert int(store.get_meta(PERSON_META_KEY) or 0) == 2


def test_a_tax_choice_is_a_person_change(store: Store) -> None:
    letter = _letter(store, "letter")
    assert store.get_meta(PERSON_META_KEY) is None
    with person_write():
        store.set_tax_choice(letter, False)
        store.set_tax_choice(letter, None)
    assert store.get_meta(PERSON_META_KEY) == "2"


@pytest.mark.parametrize(
    "raw",
    ["not json", "[true]", '"tax"', "null", '{"doc_x": "yes", "doc_y": 1, "doc_z": null}'],
)
def test_an_unreadable_tax_choices_row_counts_as_no_choice(store: Store, raw: str) -> None:
    letter = _letter(store, "letter")
    store.set_meta(TAX_CHOICES_META_KEY, raw)
    assert store.tax_choices() == {}
    # clearing a choice that isn't there leaves the row as it is
    assert store.set_tax_choice(letter, None) is False
    assert _raw(store, TAX_CHOICES_META_KEY) == raw
    # a new choice replaces it with what can be read
    assert store.set_tax_choice(letter, True) is True
    assert store.tax_choices() == {letter: True}


def test_readable_choices_are_kept_beside_unreadable_ones(store: Store) -> None:
    kept, odd = _letter(store, "kept"), _letter(store, "odd")
    store.set_meta(TAX_CHOICES_META_KEY, json.dumps({kept: False, odd: "yes"}))
    assert store.tax_choices() == {kept: False}


def test_setting_a_choice_drops_choices_of_letters_gone(store: Store) -> None:
    """A computer still on 0.2.x deletes a letter for good without knowing the row: the next choice set
    here forgets it. A letter in the trash keeps its choice."""
    letter, trashed = _letter(store, "letter"), _letter(store, "trashed")
    store.set_meta(TAX_CHOICES_META_KEY, json.dumps({"doc_gonegonegone": True, trashed: False}))
    store.trash_document(trashed)
    assert store.tax_choices() == {"doc_gonegonegone": True, trashed: False}
    assert store.set_tax_choice(letter, True) is True
    assert store.tax_choices() == {letter: True, trashed: False}
    # only a pruning to do is a change too
    store.set_meta(TAX_CHOICES_META_KEY, json.dumps({"doc_gonegonegone": True, letter: True}))
    assert store.set_tax_choice(letter, True) is True
    assert store.tax_choices() == {letter: True}


def test_a_choice_for_a_letter_that_doesnt_exist_is_refused(store: Store) -> None:
    with pytest.raises(NotFoundError):
        store.set_tax_choice("doc_nothinghere", True)
    assert _raw(store, TAX_CHOICES_META_KEY) is None


def test_a_letter_in_the_trash_keeps_its_choice_and_its_filing(store: Store) -> None:
    letter = _letter(store, "letter")
    store.set_tax_choice(letter, True)
    store.set_meta(HOUSEHOLD_META_KEY, _household({letter: "hhm_0123456789ab"}))
    household = _raw(store, HOUSEHOLD_META_KEY)
    store.trash_document(letter)
    assert store.tax_choices() == {letter: True}
    assert _raw(store, HOUSEHOLD_META_KEY) == household
    store.restore_document(letter)
    assert store.tax_choices() == {letter: True}
    assert _raw(store, HOUSEHOLD_META_KEY) == household


def test_deleting_a_letter_for_good_drops_it_from_both_rows(store: Store) -> None:
    gone, kept = _letter(store, "gone"), _letter(store, "kept")
    store.set_tax_choice(gone, True)
    store.set_tax_choice(kept, False)
    store.set_meta(HOUSEHOLD_META_KEY, _household({gone: "hhm_0123456789ab", kept: "me"}))
    assert store.delete_document(gone) is True
    assert store.tax_choices() == {kept: False}
    household = json.loads(_raw(store, HOUSEHOLD_META_KEY) or "{}")
    assert household["links"] == {kept: "me"}
    assert household["members"] == [{"id": "hhm_0123456789ab", "name": "Alex Rivera", "signs": True}]
    values = [value for (value,) in store._conn().execute("SELECT value FROM meta")]
    assert not any(gone in value for value in values)
    # the last choice going takes the row with it
    assert store.delete_document(kept) is True
    assert _raw(store, TAX_CHOICES_META_KEY) is None
    assert json.loads(_raw(store, HOUSEHOLD_META_KEY) or "{}")["links"] == {}


def test_the_purge_removes_exactly_the_letter_s_key(store: Store) -> None:
    """The JSON path names the id quoted: an id with path characters (``.``, ``[``, ``$``) is one key,
    never a path into another letter's entry."""
    plain = _letter(store, "plain", id="doc_a")
    dotted = _letter(store, "dotted", id="doc_a.b")
    bracket = _letter(store, "bracket", id="doc_a[0]")
    store.set_tax_choice(plain, True)
    store.set_tax_choice(dotted, False)
    store.set_tax_choice(bracket, True)
    links = {plain: "me", dotted: "hhm_0123456789ab", bracket: "me"}
    store.set_meta(HOUSEHOLD_META_KEY, _household(links))
    store.delete_document(dotted)
    assert store.tax_choices() == {plain: True, bracket: True}
    assert json.loads(_raw(store, HOUSEHOLD_META_KEY) or "{}")["links"] == {plain: "me", bracket: "me"}
    store.delete_document(plain)
    assert store.tax_choices() == {bracket: True}
    assert json.loads(_raw(store, HOUSEHOLD_META_KEY) or "{}")["links"] == {bracket: "me"}


@pytest.mark.parametrize("raw", ["not json", '{"format": 1, "links": []}', "[]"])
def test_a_purge_never_fails_on_a_row_it_can_t_read(store: Store, raw: str) -> None:
    letter = _letter(store, "letter")
    store.set_meta(HOUSEHOLD_META_KEY, raw)
    store.set_meta(TAX_CHOICES_META_KEY, raw)
    assert store.delete_document(letter) is True
    assert store.get_document(letter) is None
    assert _raw(store, HOUSEHOLD_META_KEY) == raw


def test_a_purge_without_either_row_writes_neither(store: Store) -> None:
    letter = _letter(store, "letter")
    store.delete_document(letter)
    assert _raw(store, TAX_CHOICES_META_KEY) is None
    assert _raw(store, HOUSEHOLD_META_KEY) is None


def test_neither_row_moves_asks_ledger_token(store: Store) -> None:
    """Ask's fingerprint reads only the profile row of ``meta``: a choice or a household write leaves its
    token as it was."""
    letter = _letter(store, "letter")
    token = store.ledger_token()
    store.set_tax_choice(letter, True)
    store.set_meta(HOUSEHOLD_META_KEY, _household({letter: "me"}))
    store.set_tax_choice(letter, None)
    store.set_meta(HOUSEHOLD_META_KEY, None)
    assert store.ledger_token() == token


# --------------------------------------------------------------------------------------------------
# the addressee of every letter (the household's suggestions)
# --------------------------------------------------------------------------------------------------


def test_recipient_names_reads_one_query_of_live_letters(store: Store) -> None:
    """Every letter in the Inbox: the name its reading says it is addressed to — only for an incoming
    letter with a reading; never a letter in the trash or a proof file."""
    alex = _letter(store, "alex", recipient="Alex Rivera")
    nobody = _letter(store, "nobody", recipient=None)
    unread = _letter(store, "unread", read=False)
    sent = _letter(store, "sent", recipient="Stadtwerke", direction="outgoing")
    trashed = _letter(store, "trashed", recipient="Mia Rivera")
    proof = _letter(store, "proof", recipient="Alex Rivera", source=PROOF_SOURCE)
    store.trash_document(trashed)
    with _statements(store) as seen:
        names = store.recipient_names()
    assert names == {alex: "Alex Rivera", nobody: None, unread: None, sent: None}
    assert trashed not in names and proof not in names
    assert len([sql for sql in seen if sql.lstrip().upper().startswith("SELECT")]) == 1


def test_recipient_names_of_an_empty_library(store: Store) -> None:
    assert store.recipient_names() == {}
