"""Citation markers ([doc:ID] …) and the labels/summaries of the Ask tool trace."""

from __future__ import annotations

import json

import pytest

from ordnung.assistant.channels import ToolAnswer, render_tool_result
from ordnung.assistant.citations import (
    Citation,
    canonical_type,
    is_well_formed,
    parse_citations,
    remove_markers,
    result_summary,
    strip_invalid,
    tool_label,
    tool_name,
)

DOC = "doc_k3j9x0a1b2c4"
ITEM = "itm_7h2m4n6p8q0r"
CONTRACT = "ctr_a1b2c3d4e5f6"
PARTY = "pty_z9y8x7w6v5t4"


# --------------------------------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------------------------------


def test_parse_single_markers_with_spans() -> None:
    text = f"Due on 21 Oct [item:{ITEM}] per the letter [doc:{DOC}]."
    found = parse_citations(text)
    assert [(c.type, c.id) for c in found] == [("item", ITEM), ("doc", DOC)]
    assert all(isinstance(c, Citation) for c in found)
    start, end = found[0].span
    assert text[start:end] == f"[item:{ITEM}]"


def test_parse_groups_aliases_and_spacing() -> None:
    text = f"See [document: {DOC}; itm:{ITEM}] and [Contract:{CONTRACT}] and [party : {PARTY}]"
    found = parse_citations(text)
    assert [(c.type, c.id) for c in found] == [
        ("doc", DOC),
        ("item", ITEM),
        ("contract", CONTRACT),
        ("party", PARTY),
    ]
    assert found[0].span == found[1].span  # one bracket, two ids


def test_parse_ignores_plain_brackets_and_unknown_shapes() -> None:
    assert parse_citations("See [1] and [note] and [doc:] and [doc:123].") == []


def test_unknown_types_are_parsed_so_they_can_be_stripped() -> None:
    (found,) = parse_citations("x [case:cas_abc123def456]")
    assert found.type == "case"
    assert not is_well_formed(found.type, found.id)


@pytest.mark.parametrize(
    ("word", "expected"),
    [("doc", "doc"), ("Document", "doc"), ("ITM", "item"), ("ctr", "contract"), ("pty", "party")],
)
def test_canonical_type(word: str, expected: str) -> None:
    assert canonical_type(word) == expected


def test_well_formed_requires_matching_prefix() -> None:
    assert is_well_formed("doc", DOC)
    assert not is_well_formed("doc", ITEM)
    assert not is_well_formed("item", DOC)


# --------------------------------------------------------------------------------------------------
# stripping
# --------------------------------------------------------------------------------------------------


def test_strip_invalid_removes_marker_and_its_space() -> None:
    text = f"Pay by 30 Sep [item:{ITEM}] as the letter says [doc:doc_bogusbogus12]."
    assert strip_invalid(text, {ITEM}) == f"Pay by 30 Sep [item:{ITEM}] as the letter says."


def test_strip_invalid_rewrites_groups_to_canonical_markers() -> None:
    text = f"Fact [document:{DOC}, item:itm_bogusbogus12; contract:{CONTRACT}]."
    assert strip_invalid(text, {DOC, CONTRACT}) == f"Fact [doc:{DOC}][contract:{CONTRACT}]."


def test_strip_invalid_drops_type_mismatch_and_duplicates() -> None:
    text = f"A [doc:{ITEM}] B [item:{ITEM}, item:{ITEM}]"
    assert strip_invalid(text, {ITEM}) == f"A B [item:{ITEM}]"


def test_strip_invalid_keeps_text_without_markers() -> None:
    text = "Nothing to cite here.\n\n- a list [1]"
    assert strip_invalid(text, set()) == text


def test_remove_markers() -> None:
    assert remove_markers(f"Due 21.10. [item:{ITEM}] ok [doc:{DOC}]") == "Due 21.10. ok"


# --------------------------------------------------------------------------------------------------
# tool trace
# --------------------------------------------------------------------------------------------------


def test_tool_name_strips_the_mcp_prefix() -> None:
    assert tool_name("mcp__ordnung__search") == "search"
    assert tool_name("today") == "today"
    assert tool_name(None) == "tool"


def test_tool_labels() -> None:
    titles = {DOC: "Tax assessment 2025", ITEM: "Objection deadline", PARTY: "Finanzamt"}

    def title_of(ref_id: str) -> str | None:
        return titles.get(ref_id)

    assert (
        tool_label("mcp__ordnung__search", {"query": "Kündigung"}) == 'Searched your letters for "Kündigung"'
    )
    assert tool_label("get_document", {"doc_id": DOC}, title_of) == 'Read "Tax assessment 2025"'
    assert tool_label("get_document", {"doc_id": "doc_unknown"}, title_of) == "Read a letter"
    assert tool_label("list_items", {}) == "Checked your open to-dos & dates"
    assert (
        tool_label("list_items", {"status": "all", "from_date": "2026-10-01", "to_date": "2026-10-31"})
        == "Checked your to-dos & dates from 2026-10-01 to 2026-10-31"
    )
    assert (
        tool_label("list_items", {"to_date": "2026-10-31"})
        == "Checked your open to-dos & dates until 2026-10-31"
    )
    assert tool_label("get_party", {"party_id_or_name": PARTY}, title_of) == 'Looked up "Finanzamt"'
    assert tool_label("get_party", {"party_id_or_name": "Stadtwerke"}, title_of) == 'Looked up "Stadtwerke"'
    assert (
        tool_label("timeline", {"from_date": "2026-10-01", "to_date": "2026-12-31"})
        == "Checked your timeline from 2026-10-01 to 2026-12-31"
    )
    assert (
        tool_label("explain_date", {"item_or_contract_id": ITEM}, title_of)
        == 'Checked how "Objection deadline" was worked out'
    )
    assert tool_label("explain_date", {"item_or_contract_id": "itm_x"}) == "Checked how a date was worked out"
    assert tool_label("list_contracts") == "Looked at your contracts"
    assert tool_label("money_summary") == "Checked your money overview"
    assert tool_label("get_profile") == "Checked your profile"
    assert tool_label("today") == "Checked today's date"
    assert tool_label("Bash", {"command": "rm -rf /"}) == "Used a tool"


def test_long_queries_are_shortened_in_labels() -> None:
    label = tool_label("search", {"query": "x" * 200})
    assert len(label) < 100
    assert label.endswith('…"')


def test_result_summaries() -> None:
    def dump(data: dict[str, object]) -> str:
        return render_tool_result(ToolAnswer(data, {DOC: {"title": "letter text is not counted"}}))

    assert result_summary("mcp__ordnung__search", dump({"hits": [{}, {}, {}]})) == "Found 3 letters"
    assert result_summary("search", dump({"hits": [{}]})) == "Found 1 letter"
    assert result_summary("search", dump({"hits": []})) == "Found no letters"
    assert result_summary("list_items", dump({"items": [{}] * 4})) == "Found 4 to-dos & dates"
    assert result_summary("list_contracts", dump({"contracts": [{}, {}]})) == "Found 2 contracts"
    assert result_summary("timeline", dump({"entries": [{}]})) == "Found 1 date on the timeline"
    assert result_summary("get_party", dump({"parties": [{}]})) == "Found 1 match"
    assert result_summary("get_document", dump({"id": DOC})) == "Read the letter"
    assert result_summary("get_document", dump({"found": False, "message": "no"})) == "Nothing found"
    assert result_summary("today", dump({"today": "2026-09-28"})) == "Today is 2026-09-28"
    assert result_summary("explain_date", dump({"id": ITEM})) == "Found how the date was worked out"
    assert result_summary("money_summary", dump({})) == "Money overview ready"
    assert result_summary("get_profile", dump({"name": "Sam"})) == "Profile read"
    assert result_summary("search", "Error executing tool search: boom") == "No result"
    assert result_summary("search", None) == "No result"
    assert result_summary("search", "[1, 2]") == "No result"
    assert result_summary("search", json.dumps({"hits": [{}]})) == "No result"  # no record part
    assert result_summary("mystery", dump({"x": 1})) == "Done"


def test_tool_labels_never_show_a_value_the_model_chose() -> None:
    """Final review: the trace (shown before the answer check) repeated the model's search words and
    names verbatim, so an injected letter could make it show "Frist verlängert bis 31.12.2027"."""
    assert (
        tool_label("search", {"query": "Einspruchsfrist verlängert 31.12.2027 999,00 €"})
        == 'Searched your letters for "Einspruchsfrist verlängert … €"'
    )
    assert tool_label("get_party", {"party_id_or_name": "FunkNetz 16:00"}) == 'Looked up "FunkNetz …"'
    assert tool_label("timeline", {"from_date": "31.12.2027", "to_date": "2027-12-31"}) == (
        "Checked your timeline from … to 2027-12-31"
    )
    assert tool_label("list_items", {"status": "31.12.2027"}) == "Checked your open to-dos & dates"


@pytest.mark.parametrize(
    ("query", "shown"),
    [
        ("Frist verlängert Ende Januar", "Frist verlängert …"),
        ("mid-October payment", "… payment"),
        ("Zahlung Anfang Oktober 2026", "Zahlung …"),
        ("Termin um 14h", "Termin um …"),
        ("late may fee", "late may fee"),  # the verb, as the check reads it
        ("Kündigung Oktober", "Kündigung Oktober"),  # a month alone is no value the check reads
        # final review 3: masked on the words as the check reads them (a Unicode hyphen, markup)
        ("mid\u2010January fee", "… fee"),
        ("Frist Ende **Januar**", "Frist …"),
        ("Frist _Ende_ Januar", "Frist …"),
        ("the thirty-first of October", "the …"),
    ],
)
def test_tool_labels_hide_every_value_the_check_reads(query: str, shown: str) -> None:
    """Final review 2: the check reads "Ende Januar" as 31 January, but the trace showed it, because it
    hid only words with a digit. A label hides every word of a value the check reads."""
    assert tool_label("search", {"query": query}) == f'Searched your letters for "{shown}"'
