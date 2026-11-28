"""compute_due end to end — every worked example from the legal research, plus the engine's policies.

Research rules cited in ids: ``ao355`` = ao_einspruch_steuerbescheid_1_monat, ``vwgo70`` =
vwgo_widerspruch_1_monat, ``sgg84`` = sgg_widerspruch_1_monat, ``rbb`` =
rechtsbehelfsbelehrung_fehlerhaft_1_jahr, ``owig67`` = owig_einspruch_bussgeldbescheid_2_wochen,
``stpo410`` = stpo_einspruch_strafbefehl_2_wochen, ``owig55`` = owig_anhoerungsbogen_keine_gesetzliche_frist,
``authority`` = behoerdlich_gesetzte_frist_und_termine, ``klage`` = klagefrist_nach_vorverfahren_1_monat,
``link`` = bekanntgabe_to_one_month_deadline_linkage, ``anchor`` = bekanntgabe_anchor_posting_date,
``early``/``late`` = bekanntgabe_early_receipt_irrelevant / bekanntgabe_late_or_non_receipt.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from helpers_tables import check_rows
from ordnung.models import DateSpec, Profile
from ordnung.rules.calendar_de import REGION_NAMES
from ordnung.rules.catalog import get_rule
from ordnung.rules.deadlines import (
    ASSUMED_RECEIPT_WARNING,
    DECLARATION_ARRIVAL_WARNING,
    DECLARATION_DATED_WARNING,
    NEEDS_ARRIVAL_WARNING,
    OLDER_MATTER_RULE,
    POSTAL_BUFFER_DAYS,
    POSTED_ON_LETTER,
    PRIVATE_SENDER_DATED_WARNING,
    PRIVATE_SENDER_WARNING,
    TWO_POSTING_DAYS,
    PostingStatement,
    RuleContext,
    from_arrival,
    older_matter_note,
    older_matter_switch,
    parse_date,
    period_problem,
    postal_buffer,
    sending_time_passed,
    statute_rule,
)
from ordnung.rules.due import compute_due, compute_one_year_fallback

D = date.fromisoformat
TODAY = D("2026-09-25")


def ctx(**kw: Any) -> RuleContext:
    kw.setdefault("today", TODAY)
    for key in ("today", "document_date", "received_date"):
        if isinstance(kw.get(key), str):
            kw[key] = D(kw[key])
    return RuleContext(**kw)


def notice_spec(**kw: Any) -> DateSpec:
    base: dict[str, Any] = {"type": "relative", "anchor": "deemed_delivery", "amount": 1, "unit": "months"}
    base.update({"delivery_rule": "de_admin_post", "nature": "objection"})
    base.update(kw)
    return DateSpec(**base)


# ------------------------------------------------------------------------------------ the hero case


def test_hero_tax_assessment() -> None:
    """Tax assessment posted Tue 15 Sep 2026 → delivered Sat 19 Sep → Mon 21 Sep → Einspruch Wed 21 Oct."""
    receipt = compute_due(
        notice_spec(legal_basis="§ 355 Abs. 1 AO"),
        ctx(region="NW", document_date="2026-09-15", delivery_scope="ao"),
    )
    assert receipt.due_date == "2026-10-21"
    assert receipt.summary == (
        "Letter dated Tue 15 Sep 2026 counts as delivered on Sat 19 Sep, moved to Mon 21 Sep; "
        "one month later is Wed 21 Oct 2026."
    )
    assert receipt.send_by == "2026-10-15"
    assert receipt.holiday_calendar == "Nordrhein-Westfalen"
    assert receipt.confidence == "high"
    assert receipt.warnings == []
    assert {"ao_122_2_1", "ao_fiction_shift", "ao_355", "ao_108_3", "bgb_187_1", "bgb_188"} <= set(
        receipt.rule_ids
    )
    assert all(step.citation for step in receipt.steps)


# ------------------------------------------------------------------------------ objection deadlines

OBJECTIONS = [
    # (id, document/posting date, scope, region, legal basis, expected due)
    ("ao355-posted-2026-09-21-NRW", "2026-09-21", "ao", "NW", "§ 355 AO", "2026-10-26"),
    ("ao355-leipzig", "2026-10-28", "ao", "SN", "§ 355 AO", "2026-12-02"),
    ("ao355-hessen-easter", "2026-02-27", "ao", "HE", "§ 355 AO", "2026-04-07"),
    ("ao122-posted-2026-09-29-NRW", "2026-09-29", "ao", "NW", "§ 355 AO", "2026-11-05"),
    ("ao122-posted-2026-09-24", "2026-09-24", "ao", "NW", "§ 355 AO", "2026-10-28"),
    ("ao122-berlin-christmas", "2026-12-22", "ao", "BE", "§ 355 AO", "2027-01-28"),
    ("aoshift-NI-2025", "2025-10-27", "ao", "NI", "§ 355 AO", "2025-12-03"),
    ("aoshift-BY-2025", "2025-10-27", "ao", "BY", "§ 355 AO", "2025-12-01"),
    ("anchor-letter-date", "2026-10-16", "ao", "NW", "§ 355 AO", "2026-11-20"),
    ("regime-grundsteuer-widerspruch", "2026-09-29", "ao", "NW", "§ 70 VwGO", "2026-11-05"),
    ("regime-kindergeld", "2026-09-21", "ao", "NW", "§ 355 AO", "2026-10-26"),
    ("klage-fgo-einspruchsentscheidung", "2026-09-29", "ao", "NW", "§ 47 FGO", "2026-11-05"),
    ("vwgo70-stadt-koeln", "2026-09-21", "vwvfg", "NW", "§ 70 VwGO", "2026-10-26"),
    ("vwgo70-nrw-klage-no-vorverfahren", "2026-09-29", "vwvfg", "NW", "§ 74 VwGO", "2026-11-03"),
    ("vwvfg-bauamt-no-fiction-shift", "2026-09-29", "vwvfg", "NW", "§ 70 VwGO", "2026-11-03"),
    ("vwvfg-hannover", "2026-10-27", "vwvfg", "NI", "§ 70 VwGO", "2026-11-30"),
    ("vwvfg-auslaenderbehoerde", "2026-12-23", "vwvfg", "NW", "§ 70 VwGO", "2027-01-27"),
    ("vwvfg-hessen-3rd-day", "2026-09-29", "vwvfg", "HE", "§ 70 VwGO", "2026-11-02"),
    ("sgg84-jobcenter", "2026-09-29", "sgbx", "NW", "§ 84 SGG", "2026-11-03"),
    ("sgg84-krankenkasse-berlin", "2026-11-27", "sgbx", "BE", "§ 84 SGG", "2027-01-04"),
    ("sgbx-krankenkasse-sunday", "2026-12-23", "sgbx", "NW", "§ 84 SGG", "2027-01-27"),
    ("sgbx-jobcenter-nov", "2026-11-25", "sgbx", "NW", "§ 84 SGG", "2026-12-29"),
    ("sgbx-drv", "2026-10-29", "sgbx", "NW", "§ 84 SGG", "2026-12-02"),
    ("klage-sgg-berlin", "2026-10-28", "sgbx", "BE", "§ 87 SGG", "2026-12-01"),
]


def test_objection_deadlines() -> None:
    def check(_id: str, doc: str, scope: str, region: str, basis: str, expected: str) -> None:
        context = ctx(region=region, recipient_region=region, document_date=doc, delivery_scope=scope)
        receipt = compute_due(notice_spec(legal_basis=basis), context)
        assert receipt.due_date == expected
        # Court actions (Klage) carry a "get advice" warning (SPEC § 21); everything else is certain — Hessen's
        # 3rd day too, which is its own law (§ 41 Abs. 2 HVwVfG).
        uncertain = "klage_1_month" in receipt.rule_ids
        assert receipt.confidence == ("medium" if uncertain else "high"), receipt.warnings

    check_rows(OBJECTIONS, check)


def test_vwvfg_no_shift_summary_mentions_it() -> None:
    receipt = compute_due(
        notice_spec(legal_basis="§ 70 VwGO"),
        ctx(region="NW", document_date="2026-09-29", delivery_scope="vwvfg"),
    )
    assert receipt.summary == (
        "Letter dated Tue 29 Sep 2026 counts as delivered on Sat 3 Oct (this day does not move for this kind "
        "of letter); one month later is Tue 3 Nov 2026."
    )
    assert "ao_fiction_shift" not in receipt.rule_ids
    assert "vwvfg_31_3" in receipt.rule_ids


def test_hessen_three_day_rule_is_its_law() -> None:
    receipt = compute_due(
        notice_spec(legal_basis="§ 70 VwGO"),
        ctx(region="HE", document_date="2026-09-29", delivery_scope="vwvfg"),
    )
    assert receipt.due_date == "2026-11-02"
    assert (receipt.confidence, receipt.warnings) == ("high", [])
    assert "vwvfg_land_days" in receipt.rule_ids


#: A Land authority's one-month objection period (§ 70 VwGO) from a letter posted (or e-mailed) on its date: (Land,
#: posted, how it was sent, due, confidence).
_LAND_DEADLINES = [
    ("TH", "2026-09-29", "de_admin_post", "2026-11-03", "high"),
    ("TH", "2025-01-02", "de_admin_post", "2025-02-06", "high"),
    ("SH", "2025-01-02", "de_admin_post", "2025-02-06", "high"),
    ("SH", "2025-03-03", "de_admin_post", "2025-04-07", "high"),
    ("HH", "2025-05-13", "de_admin_post", "2025-06-16", "high"),
    ("HE", "2026-09-29", "de_admin_post", "2026-11-02", "high"),
    ("HB", "2026-09-29", "de_admin_post", "2026-11-03", "high"),
    # posted before Bremen's switch, the 3rd day: Thu 2 Jan, a month on Sun 2 Feb
    ("HB", "2024-12-30", "de_admin_post", "2025-02-03", "high"),
    ("SL", "2026-09-29", "de_admin_post", "2026-11-02", "medium"),
    ("BB", "2026-10-30", "de_admin_electronic", "2026-11-30", "medium"),
    ("BB", "2026-10-30", "de_admin_post", "2026-12-03", "high"),
    (None, "2026-10-30", "de_admin_electronic", "2026-11-30", "medium"),
]


def test_a_lands_delivery_day_in_the_deadline() -> None:
    def check(region: str | None, posted: str, rule: str, expected: str, confidence: str) -> None:
        receipt = compute_due(
            notice_spec(legal_basis="§ 70 VwGO", delivery_rule=rule),
            ctx(region=region, document_date=posted, delivery_scope="vwvfg"),
        )
        assert (receipt.due_date, receipt.confidence) == (expected, confidence), receipt.warnings

    check_rows(_LAND_DEADLINES, check)


BRANDENBURG_EMAIL_ARRIVALS = [("2026-11-02", "2026-12-02", False), ("2026-11-05", "2026-12-03", True)]


def test_brandenburg_email_with_its_arrival_day() -> None:
    """An e-mailed decision of a Brandenburg authority counts from the day it arrived, before the 4th day
    (§ 7 VwVfGBbg); after it, the 4th day and the late-arrival note (§ 41 Abs. 2 S. 3 VwVfG)."""

    def check(arrived: str, expected: str, late: bool) -> None:
        receipt = compute_due(
            notice_spec(legal_basis="§ 70 VwGO", delivery_rule="de_admin_electronic"),
            ctx(
                today="2026-11-06",
                region="BB",
                document_date="2026-10-30",
                received_date=arrived,
                received_confirmed=True,
                delivery_scope="vwvfg",
            ),
        )
        assert (receipt.due_date, receipt.confidence) == (expected, "high"), receipt.warnings
        assert ("late_receipt" in receipt.rule_ids) is late
        assert ("vwvfg_bb_7" in receipt.rule_ids) is not late

    check_rows(BRANDENBURG_EMAIL_ARRIVALS, check)


#: The note on a date where a matter begun before the Land's switch keeps the 3rd day: how it starts.
_OLDER = "In {} a matter begun before"

#: How the note begins: the provision binds only the Land's own procedure law (a federal authority, or a
#: Widerspruchsbescheid served under the VwZG, has no such transition).
_MV_RULE = (
    "In Mecklenburg-Vorpommern a matter begun before 1 January 2025 keeps the old 3-day rule (§ 120a VwVfG M-V) "
    "when an authority of the Land or a municipality there decides it under the Land's own procedure law. If so, "
    "and this matter began earlier (you applied or were heard before that day), the letter counts as delivered on "
    "Fri 12 Dec 2025 and the deadline is Mon 12 Jan 2026"
)
#: ... and how it ends: the earlier deadline's own send-by date, counted as the receipt's (4 business days by post)
_MV_NOTE = _MV_RULE + ": it must arrive by then, so send it by Tue 6 Jan 2026."


OLDER_MATTER_EARLIER_DEADLINES = [
    pytest.param("MV", "2025-12-09", "2026-01-13", "medium", (_MV_NOTE,), id="MV"),
    pytest.param(
        "BW",
        "2025-02-07",
        "2025-03-11",
        "medium",
        ("Mon 10 Feb 2025", "Mon 10 Mar 2025", "send it by Tue 4 Mar 2025."),
        id="BW",
    ),
    pytest.param(
        "BY",
        "2026-02-10",
        "2026-03-16",
        "medium",
        ("Fri 13 Feb 2026", "Fri 13 Mar 2026", "send it by Mon 9 Mar 2026."),
        id="BY",
    ),
    # Easter: the 3rd day gives the same deadline
    pytest.param("BW", "2026-03-02", "2026-04-07", "high", None, id="BW-easter"),
    # before the switch the old law's 3rd day is counted anyway
    pytest.param("BW", "2025-02-06", "2025-03-10", "high", None, id="BW-old-law"),
    pytest.param("MV", "2024-12-31", "2025-02-03", "high", None, id="MV-old-law"),
    pytest.param("BY", "2024-12-31", "2025-02-03", "high", None, id="BY-old-law"),
    # without the Land: the 3rd day and the warning that it isn't confirmed, as before
    pytest.param(None, "2025-12-09", "2026-01-12", "medium", None, id="no-land"),
]


def test_an_older_matter_in_bw_by_or_mv_names_the_earlier_deadline() -> None:
    def check(
        region: str | None, posted: str, expected: str, confidence: str, names: tuple[str, ...] | None
    ) -> None:
        receipt = compute_due(
            notice_spec(legal_basis="§ 70 VwGO"),
            ctx(today="2024-12-01", region=region, document_date=posted, delivery_scope="vwvfg"),
        )
        assert (receipt.due_date, receipt.confidence) == (expected, confidence), receipt.warnings
        notes = [w for w in receipt.warnings if region and w.startswith(_OLDER.format(REGION_NAMES[region]))]
        assert ("vwvfg_land_old_procedures" in receipt.rule_ids) is (names is not None)
        if names is None:
            assert notes == []
        else:
            assert len(notes) == 1 and all(name in notes[0] for name in names), notes

    check_rows(OLDER_MATTER_EARLIER_DEADLINES, check)


OLDER_MATTER_SEND_BY_ENDINGS = [
    # the receipt's own send-by for the later date is Wed 7 Jan: a day short of the earlier deadline
    ("2025-12-01", "objection", ": it must arrive by then, so send it by Tue 6 Jan 2026."),
    # a bank transfer needs one bank business day, as on the receipt
    ("2025-12-01", "payment", ": it must arrive by then, so send it by Fri 9 Jan 2026."),
    # past the earlier send-by day, as the receipt says once its own has passed
    (
        "2026-01-08",
        "objection",
        ": it must arrive by then, so send it today by the fastest channel allowed (online, fax or in person).",
    ),
    ("2026-01-13", "objection", ", which has already passed."),
    # nothing to send: no send-by date on the receipt either
    ("2025-12-01", "other", ": act by then to be safe."),
]


def test_an_older_matter_s_note_says_when_to_send() -> None:
    """The earlier deadline is the day it must arrive: the note gives its own send-by date, the way the receipt
    counts one for the later date, so posting on the receipt's send-by day is never a day short."""

    def check(today: str, nature: str, ending: str) -> None:
        receipt = compute_due(
            notice_spec(legal_basis="§ 70 VwGO", nature=nature),
            ctx(today=today, region="MV", document_date="2025-12-09", delivery_scope="vwvfg"),
        )
        assert receipt.due_date == "2026-01-13"
        assert _MV_RULE + ending in receipt.warnings, receipt.warnings

    check_rows(OLDER_MATTER_SEND_BY_ENDINGS, check)


def test_an_older_matter_s_note_counts_the_period_the_deadline_uses() -> None:
    """When the law's shorter period replaces the letter's, the older matter's deadline runs with the law's
    too: the note names it (and the date is one level less confident than with the period warning alone)."""
    receipt = compute_due(
        notice_spec(legal_basis="§ 70 VwGO", amount=2),
        ctx(today="2024-12-01", region="BW", document_date="2025-02-07", delivery_scope="vwvfg"),
    )
    assert (receipt.due_date, receipt.confidence) == ("2025-03-11", "low"), receipt.warnings
    assert "vwvfg_land_old_procedures" in receipt.rule_ids
    notes = [w for w in receipt.warnings if w.startswith(_OLDER.format("Baden-Württemberg"))]
    assert len(notes) == 1 and "Mon 10 Feb 2025" in notes[0] and "the deadline is Mon 10 Mar 2025" in notes[0]


OLDER_MATTER_SWITCH_DAYS = [
    ("MV", "2025-12-09", "1 January 2025"),
    ("BW", "2025-02-07", "7 February 2025"),
    ("BY", "2026-02-10", "1 January 2025"),
]


def test_an_older_matter_s_note_is_found_by_its_rule() -> None:
    """The calendar file, the morning notification and the web app's Today find the note by its rule id (the web
    app reads the same id): the note itself and the Land's switch day; none on a receipt without the rule, or whose
    rule's note isn't there (never another warning instead)."""

    def check(region: str, posted: str, switch: str) -> None:
        receipt = compute_due(
            notice_spec(legal_basis="§ 70 VwGO"),
            ctx(today="2024-12-01", region=region, document_date=posted, delivery_scope="vwvfg"),
        )
        note = older_matter_note(receipt)
        assert OLDER_MATTER_RULE in receipt.rule_ids
        assert (
            note is not None
            and note in receipt.warnings
            and note.startswith(_OLDER.format(REGION_NAMES[region]))
        )
        assert older_matter_switch(receipt) == switch
        other = [w for w in receipt.warnings if w != note] + ["The letter's period is longer than the law's."]
        without = receipt.model_copy(update={"warnings": other})
        assert older_matter_note(without) is None and older_matter_switch(without) is None
        plain = compute_due(
            notice_spec(legal_basis="§ 70 VwGO"),
            ctx(today="2024-12-01", region="NW", document_date=posted, delivery_scope="vwvfg"),
        )
        assert OLDER_MATTER_RULE not in plain.rule_ids
        assert older_matter_note(plain) is None and older_matter_switch(plain) is None
        assert older_matter_note(None) is None and older_matter_switch(None) is None
        web = Path(__file__).resolve().parents[1] / "web" / "src" / "features" / "today" / "selection.ts"
        assert f'OLDER_MATTER_RULE = "{OLDER_MATTER_RULE}"' in web.read_text(encoding="utf-8")

    check_rows(OLDER_MATTER_SWITCH_DAYS, check)


def test_an_older_matter_s_note_only_on_a_period_counted_forward() -> None:
    receipt = compute_due(
        notice_spec(legal_basis=None, amount=-1, nature="notice"),
        ctx(today="2024-12-01", region="MV", document_date="2025-12-09", delivery_scope="vwvfg"),
    )
    assert receipt.due_date is not None
    assert "vwvfg_land_old_procedures" not in receipt.rule_ids
    assert not any(w.startswith(_OLDER.format("Mecklenburg-Vorpommern")) for w in receipt.warnings)


EXPLICIT_EVENT_DEADLINES = [
    pytest.param("2026-09-07", 1, "months", "NW", "§ 355 AO", "2026-10-07", id="fristbeginn-bekanntgabe-mon"),
    pytest.param("2026-10-31", 1, "months", "HE", "§ 70 VwGO", "2026-11-30", id="vwgo70-pzu-saturday"),
    pytest.param("2026-10-12", 1, "months", "NW", "§ 70 VwGO", "2026-11-12", id="vwzg-pzu-envelope"),
    pytest.param("2026-10-15", 1, "months", "NW", "§ 70 VwGO", "2026-11-16", id="vwzg-rueckschein"),
    pytest.param("2026-10-16", 1, "months", "HE", "§ 74 VwGO", "2026-11-16", id="klage-vg-frankfurt-pzu"),
    pytest.param("2026-09-10", 1, "months", "NW", "§ 355 AO", "2026-10-12", id="ao355-steueranmeldung"),
    pytest.param("2026-10-15", 3, "months", "NW", "§ 84 SGG", "2027-01-15", id="sgg84-abroad-3-months"),
    pytest.param("2026-10-03", 1, "months", "NW", "§ 70 VwGO", "2026-11-03", id="link-sat-oct-3"),
    pytest.param("2025-10-31", 1, "months", "BY", "§ 355 AO", "2025-12-01", id="link-bavaria"),
    pytest.param("2026-09-18", 1, "months", "NW", "§ 355 AO", "2026-10-19", id="link-fri-sep-18"),
    pytest.param("2026-09-17", 2, "weeks", "BY", "§ 67 OWiG", "2026-10-01", id="owig67-thursday"),
    pytest.param(
        "2026-09-19", 2, "weeks", "NW", "§ 67 OWiG", "2026-10-05", id="owig67-substitute-delivery-sat"
    ),
    pytest.param("2026-12-11", 2, "weeks", "BE", "§ 67 OWiG", "2026-12-28", id="owig67-christmas"),
    pytest.param(
        "2026-10-16", 2, "weeks", "NI", "§ 67 OWiG", "2026-10-30", id="owig55-later-bussgeldbescheid"
    ),
    pytest.param("2026-09-23", 2, "weeks", "BW", "§ 410 StPO", "2026-10-07", id="stpo410-stuttgart"),
    pytest.param(
        "2026-11-04", 2, "weeks", "SN", "§ 410 StPO", "2026-11-19", id="stpo410-dresden-buss-und-bettag"
    ),
    pytest.param("2026-11-04", 2, "weeks", "BY", "§ 410 StPO", "2026-11-18", id="stpo410-muenchen"),
    pytest.param("2026-10-17", 2, "weeks", "NI", "§ 410 StPO", "2026-11-02", id="stpo410-hannover-saturday"),
    pytest.param("2026-12-18", 2, "weeks", "HH", "§ 410 StPO", "2027-01-04", id="stpo410-hamburg-new-year"),
    pytest.param("2026-09-28", 2, "weeks", "NW", None, "2026-10-12", id="authority-two-weeks-hearing"),
    pytest.param("2026-10-17", 14, "days", "NW", None, "2026-11-02", id="widerruf-193-applies"),
    pytest.param("2026-09-21", 10, "days", "NW", None, "2026-10-01", id="fristende-10-days"),
]


def test_explicit_event_deadlines() -> None:
    def check(event: str, amount: int, unit: str, region: str, basis: str | None, expected: str) -> None:
        spec = DateSpec(
            type="relative",
            anchor="explicit_date",
            anchor_date=event,
            amount=amount,
            unit=unit,  # type: ignore[arg-type]
            nature="objection" if basis else "declaration",
            legal_basis=basis,
        )
        receipt = compute_due(spec, ctx(region=region))
        assert receipt.due_date == expected
        klage = "klage_1_month" in receipt.rule_ids
        assert receipt.confidence == ("medium" if klage else "high"), receipt.warnings

    check_rows(EXPLICIT_EVENT_DEADLINES, check)


def test_owig_week_period_uses_stpo_43() -> None:
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2026-09-19",
        amount=2,
        unit="weeks",
        nature="objection",
        legal_basis="§ 67 Abs. 1 OWiG",
    )
    receipt = compute_due(spec, ctx(region="NW"))
    assert "stpo_43" in receipt.rule_ids and "owig_67" in receipt.rule_ids
    assert receipt.summary == (
        "Two weeks after Sat 19 Sep 2026 is Sat 3 Oct 2026, a public holiday, Tag der Deutschen Einheit, "
        "so the deadline moves to Mon 5 Oct 2026."
    )


def test_fine_sent_by_uebergabe_einschreiben() -> None:
    """owig67: Übergabe-Einschreiben posted Mon 21 Sep 2026 → delivered Fri 25 Sep → Fri 9 Oct 2026.

    A DateSpec cannot tell an Übergabe-Einschreiben (4th day, § 4 Abs. 2 VwZG) from a yellow envelope or
    a Rückschein, which are usually delivered earlier. So the 4th-day fiction is not applied to fines:
    counted from the letter's date the deadline is Mon 5 Oct, the earliest plausible date (research
    correction: "Einschreiben = 4th day could give a later date than the true Zustellung").
    """
    spec = notice_spec(amount=2, unit="weeks", legal_basis="§ 67 OWiG")
    receipt = compute_due(spec, ctx(region="NW", document_date="2026-09-21", delivery_scope="vwvfg"))
    assert receipt.due_date == "2026-10-05"
    assert receipt.confidence == "medium"  # counted from the letter's date, not the envelope
    assert receipt.summary == "Two weeks after the letter's date (Mon 21 Sep 2026) is Mon 5 Oct 2026."
    assert "vwvfg_41_2" not in receipt.rule_ids
    assert not any(step.rule_id in ("vwvfg_41_2", "vwvfg_land_days") for step in receipt.steps)
    assert any("Übergabe-Einschreiben the 4th day" in w and "yellow envelope" in w for w in receipt.warnings)
    # With the envelope date as an explicit anchor the week period runs from it (§ 43 StPO).
    served = compute_due(
        DateSpec(**{**spec.model_dump(), "anchor": "explicit_date", "anchor_date": "2026-09-25"}),
        ctx(region="NW", document_date="2026-09-21", delivery_scope="vwvfg"),
    )
    assert served.due_date == "2026-10-09" and served.confidence == "high"


def test_owig_counted_from_letter_date_warns() -> None:
    spec = DateSpec(
        type="relative",
        anchor="document_date",
        amount=2,
        unit="weeks",
        nature="objection",
        legal_basis="§ 67 OWiG",
    )
    receipt = compute_due(spec, ctx(region="NW", document_date="2026-09-17"))
    assert receipt.due_date == "2026-10-01"
    assert receipt.confidence == "medium"
    assert any("yellow envelope" in w for w in receipt.warnings)


# --------------------------------------------------------------------------- receipt & anchors


def test_early_receipt_is_irrelevant() -> None:
    """early: Finanzamt posted Mon 14 Sep, found Wed 16 Sep → Bekanntgabe Fri 18 Sep → Mon 19 Oct."""
    receipt = compute_due(
        notice_spec(legal_basis="§ 355 AO"),
        ctx(
            region="NW",
            document_date="2026-09-14",
            received_date="2026-09-16",
            received_confirmed=True,
            delivery_scope="ao",
        ),
    )
    assert receipt.due_date == "2026-10-19"
    assert "early_receipt" in receipt.rule_ids
    assert receipt.confidence == "high"


def test_bsg_three_day_era_early_receipt() -> None:
    """early/sgbx: posted Wed 26 Sep 2007, received Fri 28 Sep → Sat 29 Sep → Klage Mon 29 Oct 2007."""
    receipt = compute_due(
        notice_spec(legal_basis="§ 87 SGG"),
        ctx(
            today=D("2007-09-28"),
            document_date="2007-09-26",
            received_date="2007-09-28",
            received_confirmed=True,
            delivery_scope="sgbx",
            region="NW",
        ),
    )
    assert receipt.due_date == "2007-10-29"


def test_pre_dated_letter_counts_from_arrival() -> None:
    """early: dated Fri 16 Oct but received Thu 15 Oct → safe Bekanntgabe 15 Oct → Mon 16 Nov."""
    receipt = compute_due(
        notice_spec(legal_basis="§ 355 AO"),
        ctx(
            region="NW",
            document_date="2026-10-16",
            received_date="2026-10-15",
            received_confirmed=True,
            delivery_scope="ao",
        ),
    )
    assert receipt.due_date == "2026-11-16"
    assert receipt.confidence == "medium"
    assert receipt.summary.startswith("The letter arrived on Thu 15 Oct, before its printed date")


LATE_RECEIPTS = [
    pytest.param("2026-09-14", "2026-09-22", "ao", "2026-10-19", "Thu 22 Oct 2026", id="late-imprint"),
    pytest.param(
        "2026-09-21",
        "2026-09-28",
        "vwvfg",
        "2026-10-26",
        "Wed 28 Oct 2026",
        id="vwvfg-koeln-late-receipt",
    ),
    pytest.param(
        "2026-10-16", "2026-11-04", "ao", "2026-11-20", "Fri 4 Dec 2026", id="anchor-received-weeks-later"
    ),
]


def test_late_receipt_keeps_safe_date_and_notes_alternative() -> None:
    def check(doc: str, received: str, scope: str, expected: str, alternative: str) -> None:
        receipt = compute_due(
            notice_spec(legal_basis="§ 355 AO" if scope == "ao" else "§ 70 VwGO"),
            ctx(
                region="NW",
                document_date=doc,
                received_date=received,
                received_confirmed=True,
                delivery_scope=scope,
                today=D("2026-09-14"),
            ),
        )
        assert receipt.due_date == expected
        assert "late_receipt" in receipt.rule_ids
        assert any(alternative in w for w in receipt.warnings)

    check_rows(LATE_RECEIPTS, check)


def test_late_receipt_without_shift() -> None:
    spec = notice_spec(nature="other", legal_basis=None)
    receipt = compute_due(
        spec,
        ctx(
            region="NW",
            document_date="2026-09-14",
            received_date="2026-10-01",
            received_confirmed=True,
            delivery_scope="ao",
        ),
    )
    assert receipt.due_date == "2026-10-18"  # Fri 18 Sep + 1 month, a Sunday: no shift for "other"
    assert any("Sun 1 Nov 2026 instead" in w for w in receipt.warnings)


def test_unconfirmed_received_date_is_ignored() -> None:
    receipt = compute_due(
        notice_spec(legal_basis="§ 355 AO"),
        ctx(region="NW", document_date="2026-09-14", received_date="2026-09-22", delivery_scope="ao"),
    )
    assert receipt.due_date == "2026-10-19"
    assert "late_receipt" not in receipt.rule_ids


def test_later_posting_date_without_a_page_is_only_a_note() -> None:
    """anchor: a later posting day with no page read (the rules tools, ``RuleContext.posting`` unset) stays a note:
    the letter's date is the start and the confidence stays (the tools' callers have no page to check it on)."""
    receipt = compute_due(
        notice_spec(anchor_date="2026-10-19", legal_basis="§ 355 AO"),
        ctx(region="NW", document_date="2026-10-16", delivery_scope="ao"),
    )
    assert receipt.due_date == "2026-11-20"
    assert any("Mon 19 Oct 2026 as the posting day" in w for w in receipt.warnings)
    assert receipt.confidence == "high"
    assert POSTED_ON_LETTER not in receipt.rule_ids


def test_later_posting_date_on_the_page_starts_the_period() -> None:
    """anchor: the letter says it was posted Mon 19 Oct (dated Fri 16 Oct). Research: Fri 23 Oct → Mon 23 Nov.

    This replaces the old policy ("the verdict keeps the letter's date as the primary posting day and notes the
    later one", pinned here until ADR 0026): the law counts from "Aufgabe zur Post" (§ 122 Abs. 2 Nr. 1 AO), and
    a posting day the authority prints on its own letter, found there by code, is its record of that day. The
    letter's date gives the safe date (Fri 20 Nov) and the receipt names it."""
    stated = PostingStatement(day=D("2026-10-19"), quote="Tag der Aufgabe zur Post: 19.10.2026")
    receipt = compute_due(
        notice_spec(legal_basis="§ 355 AO"),
        ctx(
            today=D("2026-10-22"),
            region="NW",
            document_date="2026-10-16",
            delivery_scope="ao",
            posting=stated,
        ),
    )
    assert receipt.due_date == "2026-11-23"
    assert receipt.safe_date == "2026-11-20"
    assert receipt.confidence == "high"
    assert receipt.rule_ids[:2] == [POSTED_ON_LETTER, "posting_day"]
    assert receipt.summary.startswith("Letter sent Mon 19 Oct 2026 counts as delivered on Fri 23 Oct")
    where, *_, instead = (step for step in receipt.steps if step.rule_id == POSTED_ON_LETTER)
    assert "Mon 19 Oct 2026 (“Tag der Aufgabe zur Post: 19.10.2026”)" in where.label
    assert where.citation == "§ 122 Abs. 2 Nr. 1 AO; § 41 Abs. 2 S. 1 VwVfG; § 37 Abs. 2 S. 1 SGB X"
    assert (
        instead.date == "2026-11-20" and "Counted from the letter's date (Fri 16 Oct 2026)" in instead.label
    )
    assert receipt.warnings == [
        "The letter says it was posted on Mon 19 Oct 2026, after its date (Fri 16 Oct 2026), so the deadline "
        "counts from that day: Mon 23 Nov 2026. Counted from the letter's date it would be Fri 20 Nov 2026 — act "
        "by then if you want to be safe whatever the posting day."
    ]


#: (id, scope, Land, letter's date, posting day on the page, today, due, safe date). Worked by hand: posting
#: day + 4 (3 before 2025, and in Hessen) → the AO moves the delivery day off a weekend or holiday, SGB X and
#: VwVfG do not → one month → off a weekend or holiday; the safe date the same from the letter's date.
STATED_POSTING_DAYS = [
    # posted Mon 19 Oct → Fri 23 Oct → Mon 23 Nov; from Fri 16 Oct: Tue 20 Oct → Fri 20 Nov
    ("ao-nw", "ao", "NW", "2026-10-16", "2026-10-19", "2026-10-22", "2026-11-23", "2026-11-20"),
    # over the year's turn: posted Sat 19 Dec → Wed 23 Dec → Sat 23 Jan, moved to Mon 25 Jan; from Thu 17 Dec:
    # Mon 21 Dec → Thu 21 Jan
    ("ao-year-turn", "ao", "BE", "2026-12-17", "2026-12-19", "2026-12-22", "2027-01-25", "2027-01-21"),
    # SGB X: posted Sat 19 Dec → Wed 23 Dec → Sat 23 Jan → Mon 25 Jan; from Wed 16 Dec: Sun 20 Dec (stays) →
    # Wed 20 Jan
    ("sgbx-year-turn", "sgbx", "NW", "2026-12-16", "2026-12-19", "2026-12-21", "2027-01-25", "2027-01-20"),
    # VwVfG: posted Mon 22 Nov 2027 → Fri 26 Nov → Sun 26 Dec (a holiday) → Mon 27 Dec; from Thu 18 Nov:
    # Mon 22 Nov → Wed 22 Dec
    ("vwvfg-christmas", "vwvfg", "NW", "2027-11-18", "2027-11-22", "2027-11-26", "2027-12-27", "2027-12-22"),
    # the 3rd day before 2025 (AO): posted Mon 16 Dec 2024 → Thu 19 Dec → Sun 19 Jan → Mon 20 Jan; from Thu
    # 12 Dec: Sun 15 Dec, moved to Mon 16 Dec → Thu 16 Jan
    ("ao-third-day", "ao", "NW", "2024-12-12", "2024-12-16", "2024-12-20", "2025-01-20", "2025-01-16"),
    # Hessen keeps the 3rd day (§ 41 Abs. 2 HVwVfG): posted Wed 7 Oct → Sat 10 Oct (stays) → Tue 10 Nov; from
    # Mon 5 Oct: Thu 8 Oct → Sun 8 Nov → Mon 9 Nov
    (
        "vwvfg-hessen-third-day",
        "vwvfg",
        "HE",
        "2026-10-05",
        "2026-10-07",
        "2026-10-09",
        "2026-11-10",
        "2026-11-09",
    ),
    # a week after the letter's date is the last day that counts (POSTING_REACH): posted Fri 23 Oct → Tue 27 Oct
    # → Fri 27 Nov
    ("ao-a-week-on", "ao", "NW", "2026-10-16", "2026-10-23", "2026-10-26", "2026-11-27", "2026-11-20"),
    # posted the day it is read: still a day the letter can have been posted
    ("ao-posted-today", "ao", "NW", "2026-10-16", "2026-10-19", "2026-10-19", "2026-11-23", "2026-11-20"),
]


def test_a_posting_day_the_page_states_starts_the_deemed_delivery() -> None:
    def check(
        _id: str, scope: str, land: str, letter: str, posted: str, today: str, due: str, safe: str
    ) -> None:
        stated = PostingStatement(day=D(posted), quote="Tag der Aufgabe zur Post")
        context = ctx(today=D(today), region=land, document_date=letter, delivery_scope=scope, posting=stated)
        receipt = compute_due(notice_spec(), context)
        assert (receipt.due_date, receipt.safe_date) == (due, safe)
        assert POSTED_ON_LETTER in receipt.rule_ids and receipt.confidence == "high", receipt.warnings
        # without the page, the same reading counts from the letter's date: the safe date
        assert compute_due(notice_spec(), replace(context, posting=None)).due_date == safe

    check_rows(STATED_POSTING_DAYS, check)


def test_a_stated_posting_day_that_gives_the_same_date_says_so() -> None:
    """Posted Wed 30 Dec 2026 → Sun 3 Jan, moved to Mon 4 Jan (AO); from Mon 28 Dec: Fri 1 Jan (a holiday) → Mon
    4 Jan too — the same deadline (Thu 4 Feb 2027), no safe date and no warning."""
    receipt = compute_due(
        notice_spec(),
        ctx(
            today=D("2027-01-02"),
            region="NW",
            document_date="2026-12-28",
            delivery_scope="ao",
            posting=PostingStatement(day=D("2026-12-30"), quote="Aufgabe zur Post: 30.12.2026"),
        ),
    )
    assert (receipt.due_date, receipt.safe_date, receipt.warnings) == ("2027-02-04", None, [])
    assert receipt.steps[-2].label == "Counted from the letter's date the deadline is the same"


#: Guards: a posting day the page states that does NOT start the period (the letter's date does: Fri 20 Nov),
#: (id, posting day, today, the context's other facts, the note: none, one naming the later deadline, or one that
#: says the day is after today and names no deadline).
POSTING_GUARDS = [
    # before the letter's date: the reading's anchor_date path, never this one
    ("before-the-letter", "2026-10-14", "2026-10-22", {}, None),
    ("on-the-letter-s-date", "2026-10-16", "2026-10-22", {}, None),
    # a letter can't have been posted after the day it is read: no deadline from that day can apply
    ("after-today", "2026-10-19", "2026-10-18", {}, "after today"),
    # more than a week after the letter's date: more likely another date than this posting
    ("beyond-a-week", "2026-10-24", "2026-10-26", {}, "deadline"),
    # not an authority's deemed delivery: a private sender's period runs from arrival
    ("private-sender", "2026-10-19", "2026-10-22", {"private_sender": True, "delivery_scope": None}, None),
    # the sender's procedure law unknown: the earliest plausible date
    ("scope-unknown", "2026-10-19", "2026-10-22", {"delivery_scope": None}, None),
    # served with a yellow envelope: the envelope's date counts, never a posting day
    ("formal-service", "2026-10-19", "2026-10-22", {"formal_service": True}, None),
    # a fine is served formally (§ 51 OWiG), also when the reading cites no § 67 OWiG
    ("fine-without-statute", "2026-10-19", "2026-10-22", {"letter_kind": "fine"}, None),
]


def test_a_posting_day_the_page_states_is_held_to_its_guards() -> None:
    def check(_id: str, posted: str, today: str, extra: dict[str, Any], noted: str | None) -> None:
        context = ctx(
            today=D(today),
            region="NW",
            document_date="2026-10-16",
            delivery_scope="ao",
            posting=PostingStatement(day=D(posted), quote="Tag der Aufgabe zur Post"),
        )
        receipt = compute_due(notice_spec(), replace(context, **extra))
        plain = compute_due(notice_spec(), replace(context, posting=None, **extra))
        assert receipt.due_date == plain.due_date, receipt.steps
        assert POSTED_ON_LETTER not in receipt.rule_ids and receipt.safe_date == plain.safe_date
        named = [w for w in receipt.warnings if w.startswith(f"{D(posted):%a} {D(posted).day} Oct 2026 ")]
        assert bool(named) == bool(noted), receipt.warnings
        if noted:
            assert receipt.confidence == "medium"
            assert ("If it was posted then, the deadline is" in named[0]) == (noted == "deadline"), named
        if noted == "after today":
            assert named == [
                "Mon 19 Oct 2026 is named as the day the letter was posted (the letter states it), but that is after "
                "today (Sun 18 Oct 2026), so it can't be the posting day. We count from the letter's date (Fri 16 "
                "Oct 2026). Check the posting day on the letter."
            ]

    check_rows(POSTING_GUARDS, check)


def test_a_posting_day_the_page_states_never_moves_another_kind_of_period() -> None:
    """Only an authority's deemed delivery by post, counted forward: an e-mailed decision, a fine (formal service,
    § 67 OWiG), a period from the letter's own date and one counted back from delivery (a week before it: the
    posting day would move that date later too) keep their start."""
    stated = PostingStatement(day=D("2026-10-19"), quote="Tag der Aufgabe zur Post")
    context = ctx(today=D("2026-10-22"), region="NW", document_date="2026-10-16", delivery_scope="vwvfg")
    for spec in (
        notice_spec(delivery_rule="de_admin_electronic"),
        notice_spec(amount=2, unit="weeks", legal_basis="§ 67 OWiG"),
        notice_spec(anchor="document_date", delivery_rule="none"),
        notice_spec(amount=-1, unit="weeks"),
    ):
        receipt = compute_due(spec, replace(context, posting=stated))
        assert receipt.due_date == compute_due(spec, context).due_date
        assert POSTED_ON_LETTER not in receipt.rule_ids


#: (id, letter's date, posting day on the page, due, safe date) for a notice, which never moves off a weekend.
#: Worked by hand (AO, NW): the 4th day after posting, off a weekend; one month on; the safe date is the earliest
#: of the working day before a due date on a weekend and the letter's date's own count (and its safe date).
NOTICE_SAFE_DATES = [
    # posted Wed 9 Sep → Sun 13 Sep → Mon 14 Sep → Wed 14 Oct; from Sun 6 Sep: Thu 10 Sep → Sat 10 Oct, whose own
    # safe date is Fri 9 Oct — never the Saturday
    ("letter-s-count-on-a-saturday", "2026-09-06", "2026-09-09", "2026-10-14", "2026-10-09"),
    # posted Mon 7 Sep → Fri 11 Sep → Sun 11 Oct (safe: Fri 9 Oct); from Fri 4 Sep: Tue 8 Sep → Thu 8 Oct, the
    # earlier of the two safe dates
    ("both-safe-dates", "2026-09-04", "2026-09-07", "2026-10-11", "2026-10-08"),
]


def test_a_stated_posting_day_s_safe_date_is_a_working_day_and_the_earliest() -> None:
    def check(_id: str, letter: str, posted: str, due: str, safe: str) -> None:
        stated = PostingStatement(day=D(posted), quote="Tag der Aufgabe zur Post")
        context = ctx(
            today=D(posted) + timedelta(days=2),
            region="NW",
            document_date=letter,
            delivery_scope="ao",
            posting=stated,
        )
        receipt = compute_due(notice_spec(nature="notice"), context)
        assert (receipt.due_date, receipt.safe_date) == (due, safe), receipt.steps
        assert D(safe).weekday() < 5

    check_rows(NOTICE_SAFE_DATES, check)


def test_two_posting_days_on_the_page_count_from_the_earlier() -> None:
    """The letter contradicts itself: the earlier posting day counts, both are named, ``low`` (the to-do is
    "Please check", ``ingest.plan.compute_item``) — and when the earlier is not after the letter's date, the
    letter's date."""
    two = PostingStatement(
        day=D("2026-10-19"),
        quote="Aufgabe zur Post: 19.10.2026",
        other=D("2026-10-21"),
        other_quote="am 21.10.",
    )
    context = ctx(
        today=D("2026-10-26"), region="NW", document_date="2026-10-16", delivery_scope="ao", posting=two
    )
    receipt = compute_due(notice_spec(), context)
    assert (receipt.due_date, receipt.confidence) == ("2026-11-23", "low")
    assert TWO_POSTING_DAYS in receipt.rule_ids
    assert (
        "The letter gives two posting days for itself: Mon 19 Oct 2026 (“Aufgabe zur Post: 19.10.2026”) and "
        "Wed 21 Oct 2026 (“am 21.10.”). We count from Mon 19 Oct 2026, the earlier — please check which day it "
        "was posted."
    ) in receipt.warnings
    on_the_letter = compute_due(notice_spec(), replace(context, posting=replace(two, day=D("2026-10-16"))))
    assert (on_the_letter.due_date, on_the_letter.confidence) == ("2026-11-20", "low")
    assert any(
        "We count from the letter's date (Fri 16 Oct 2026), the earlier" in w for w in on_the_letter.warnings
    )


def test_a_posting_day_read_from_a_photo_is_at_most_medium() -> None:
    """Found only in a photo's transcription (``model_read``): the date counts from it, at most ``medium``, as
    every fact read from a photo — a cap, not one more failure: with one soft failure it stays ``medium``, with
    two it is ``low`` as always."""
    photo = PostingStatement(day=D("2026-10-19"), quote="Tag der Aufgabe zur Post", grounding="model_read")
    context = ctx(
        today=D("2026-10-22"), region="NW", document_date="2026-10-16", delivery_scope="ao", posting=photo
    )
    receipt = compute_due(notice_spec(), context)
    assert (receipt.due_date, receipt.confidence) == ("2026-11-23", "medium")
    assert compute_due(notice_spec(delivery_rule="none"), context).confidence == "medium"
    unknown_land = replace(
        context, region=None, delivery_scope="vwvfg"
    )  # the 3rd day, uncertain: a 2nd soft one
    assert compute_due(notice_spec(delivery_rule="none"), unknown_land).confidence == "low"


def test_a_later_posting_day_only_the_reading_names_lowers_the_confidence() -> None:
    """The pages were read and state no posting day; only the reading names a later one (``anchor_date``): the
    date stays the letter's date's (Fri 20 Nov), the receipt names the deadline from the later day (Mon 23 Nov),
    one level less sure — the later date may be the right one ("Please check" catches it no more than before)."""
    receipt = compute_due(
        notice_spec(anchor_date="2026-10-19"),
        ctx(
            today=D("2026-10-22"),
            region="NW",
            document_date="2026-10-16",
            delivery_scope="ao",
            posting=PostingStatement(),
        ),
    )
    assert (receipt.due_date, receipt.safe_date, receipt.confidence) == ("2026-11-20", None, "medium")
    assert receipt.warnings == [
        "Mon 19 Oct 2026 may be the day the letter was posted, later than its date (Fri 16 Oct 2026): Claude's "
        "reading of the letter names it, but we didn't find it on the letter. If it was posted then, the deadline "
        "is Mon 23 Nov 2026 — we count from the letter's date to be safe (Fri 20 Nov 2026). Check the posting day "
        "on the letter."
    ]
    # a later day that gives the same deadline is only named (Wed 30 Dec 2026 against Mon 28 Dec, both 4 Feb)
    same = compute_due(
        notice_spec(anchor_date="2026-12-30"),
        ctx(
            today=D("2027-01-02"),
            region="NW",
            document_date="2026-12-28",
            delivery_scope="ao",
            posting=PostingStatement(),
        ),
    )
    assert (same.due_date, same.confidence) == ("2027-02-04", "high")
    assert same.warnings[0].endswith("Counted from that day the deadline is the same.")


def test_a_later_posting_day_after_today_names_no_deadline() -> None:
    """The reading names Tue 1 Dec as the posting day of a letter dated Fri 16 Oct, read on Sun 25 Oct: it can't have
    been posted then, so no deadline from that day is named; still one level less sure, and checked."""
    receipt = compute_due(
        notice_spec(anchor_date="2026-12-01"),
        ctx(
            today=D("2026-10-25"),
            region="NW",
            document_date="2026-10-16",
            delivery_scope="ao",
            posting=PostingStatement(),
        ),
    )
    assert (receipt.due_date, receipt.confidence) == ("2026-11-20", "medium")
    assert receipt.warnings == [
        "Tue 1 Dec 2026 is named as the day the letter was posted (Claude's reading of the letter names it, but we "
        "didn't find it on the letter), but that is after today (Sun 25 Oct 2026), so it can't be the posting day. "
        "We count from the letter's date (Fri 16 Oct 2026). Check the posting day on the letter."
    ]


def test_a_later_posting_day_the_page_contradicts_says_so() -> None:
    """The page states the letter's own date (Fri 16 Oct) as its posting day, the reading a later one (Mon 19 Oct):
    the date stays the letter's date's, and the note says the letter states another day, not that it says none."""
    receipt = compute_due(
        notice_spec(anchor_date="2026-10-19"),
        ctx(
            today=D("2026-10-22"),
            region="NW",
            document_date="2026-10-16",
            delivery_scope="ao",
            posting=PostingStatement(day=D("2026-10-16"), quote="Tag der Aufgabe zur Post: 16.10.2026"),
        ),
    )
    assert (receipt.due_date, receipt.confidence) == ("2026-11-20", "medium")
    assert receipt.warnings[0].startswith(
        "Mon 19 Oct 2026 may be the day the letter was posted, later than its date (Fri 16 Oct 2026): Claude's "
        "reading of the letter names it, but the letter states Fri 16 Oct 2026 as its posting day. If it was posted "
        "then, the deadline is Mon 23 Nov 2026"
    )


def test_a_later_posting_day_among_the_reading_s_key_facts_is_named_too() -> None:
    """The reading names the later posting day only among its key facts (``RuleContext.posting_read``), not as the
    period's start: the same note as for ``anchor_date``, one level less sure. Without pages read (the rules tools)
    nothing changes."""
    context = ctx(
        today=D("2026-10-22"),
        region="NW",
        document_date="2026-10-16",
        delivery_scope="ao",
        posting=PostingStatement(),
        posting_read=D("2026-10-19"),
    )
    receipt = compute_due(notice_spec(), context)
    assert (receipt.due_date, receipt.confidence) == ("2026-11-20", "medium")
    assert receipt.warnings[0].startswith("Mon 19 Oct 2026 may be the day the letter was posted")
    assert "the deadline is Mon 23 Nov 2026" in receipt.warnings[0]
    tools = compute_due(notice_spec(), replace(context, posting=None))
    assert (tools.due_date, tools.confidence, tools.warnings) == ("2026-11-20", "high", [])


def test_the_catalog_s_posting_day_says_what_the_engine_does() -> None:
    """The person-facing catalog says one thing with the engine (ADR 0026): the letter's date is the start unless
    the letter's page states a later posting day — not "unless a posting date is stated", which a posting day only
    the reading names, or one beyond the guards, is too, and still leaves the letter's date as the start."""
    text = get_rule("posting_day").summary
    assert "Unless the letter's page states a later posting day" in text
    assert get_rule(POSTED_ON_LETTER).title in text


def test_earlier_posting_date_is_used() -> None:
    receipt = compute_due(
        notice_spec(anchor_date="2026-10-19", legal_basis="§ 355 AO"),
        ctx(region="NW", document_date="2026-10-20", delivery_scope="ao"),
    )
    assert receipt.due_date == "2026-11-23"
    assert receipt.summary.startswith("Letter sent Mon 19 Oct 2026 counts as delivered on Fri 23 Oct")
    posted_only = compute_due(notice_spec(anchor_date="2026-10-19"), ctx(region="NW", delivery_scope="ao"))
    assert posted_only.due_date == "2026-11-23"


def test_tax_fiction_day_needs_holiday_at_both_places() -> None:
    """feiertage verdict: the fiction day moves for a regional holiday only if it applies at both places.
    Posted Thu 28 Oct 2027 → Mon 1 Nov 2027 (Allerheiligen in NW)."""
    both = compute_due(
        notice_spec(legal_basis="§ 355 AO"),
        ctx(
            today=D("2027-10-28"),
            region="NW",
            recipient_region="NW",
            document_date="2027-10-28",
            delivery_scope="ao",
        ),
    )
    assert both.due_date == "2027-12-02"  # delivered Tue 2 Nov
    assert both.confidence == "high"
    unknown = compute_due(
        notice_spec(legal_basis="§ 355 AO"),
        ctx(today=D("2027-10-28"), region="NW", document_date="2027-10-28", delivery_scope="ao"),
    )
    assert unknown.due_date == "2027-12-01"  # delivered Mon 1 Nov (earlier, safe)
    assert unknown.confidence == "medium"
    assert any("if you live in the same Land" in w for w in unknown.warnings)


def test_bfh_vi_r_18_22_three_day_era() -> None:
    """late: posted Fri 15 Jun 2018 → Mon 18 Jun → Einspruch deadline Wed 18 Jul 2018."""
    receipt = compute_due(
        notice_spec(legal_basis="§ 355 AO"),
        ctx(today=D("2018-06-15"), document_date="2018-06-15", delivery_scope="ao", region="NW"),
    )
    assert receipt.due_date == "2018-07-18"


def test_bfh_ix_b_95_25_without_rebuttal() -> None:
    """ao: Bescheid posted Fri 7 Feb 2025 → Tue 11 Feb → Klagefrist Tue 11 Mar 2025 without rebuttal."""
    receipt = compute_due(
        notice_spec(legal_basis="§ 47 FGO"),
        ctx(today=D("2025-02-07"), document_date="2025-02-07", delivery_scope="ao", region="NW"),
    )
    assert receipt.due_date == "2025-03-11"


#: An authority's letter sent electronically: (letter's date, scope, region, legal basis, today or None for TODAY,
#: due, a rule the receipt must cite or None).
ELECTRONIC_DELIVERIES = [
    # elster: made available Fri 25 Sep 2026 → Tue 29 Sep → Thu 29 Oct; Thu 2 Apr 2026 → Tue 7 Apr → Thu 7 May
    ("2026-09-25", "ao", "NW", "§ 355 AO", "2026-04-01", "2026-10-29", None),
    ("2026-04-02", "ao", "NW", "§ 355 AO", "2026-04-01", "2026-05-07", None),
    # ozg: federal authority e-mails Fri 30 Oct 2026 → Tue 3 Nov → Thu 3 Dec
    ("2026-10-30", "vwvfg", "BE", "§ 70 VwGO", None, "2026-12-03", None),
    # ao2a: Einspruchsentscheidung e-mailed Wed 23 Dec 2026 → Mon 28 Dec → Klage Thu 28 Jan 2027
    ("2026-12-23", "ao", "NW", "§ 47 FGO", None, "2027-01-28", "ao_122_2a"),
]


def test_elster_and_federal_email_examples() -> None:
    def check(
        doc: str, scope: str, region: str, basis: str, today: str | None, expected: str, rule: str | None
    ) -> None:
        on = {"today": D(today)} if today else {}
        receipt = compute_due(
            notice_spec(delivery_rule="de_admin_electronic", legal_basis=basis),
            ctx(document_date=doc, delivery_scope=scope, region=region, **on),
        )
        assert receipt.due_date == expected
        if rule is not None:
            assert rule in receipt.rule_ids

    check_rows(ELECTRONIC_DELIVERIES, check)


def test_a_period_from_receipt_counts_from_the_confirmed_arrival_or_falls_back() -> None:
    spec = DateSpec(type="relative", anchor="receipt", amount=14, unit="days", nature="payment")
    # a confirmed arrival day: counted from it
    receipt = compute_due(
        spec,
        ctx(region="NW", document_date="2026-09-10", received_date="2026-09-14", received_confirmed=True),
    )
    assert receipt.due_date == "2026-09-28"
    assert receipt.confidence == "high"
    assert receipt.summary == "14 days after the day you received it (Mon 14 Sep 2026) is Mon 28 Sep 2026."
    # an unconfirmed arrival day: counted from the letter's date, and said so
    receipt = compute_due(spec, ctx(region="NW", document_date="2026-09-10", received_date="2026-09-14"))
    assert receipt.due_date == "2026-09-24"
    assert receipt.confidence == "low"
    assert ASSUMED_RECEIPT_WARNING in receipt.warnings
    # no date at all: no due date
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.due_date is None
    assert receipt.confidence == "low"


MISSING_INPUTS = [
    (DateSpec(type="relative", anchor="document_date", amount=1, unit="months"), {}),
    (
        DateSpec(
            type="relative",
            anchor="deemed_delivery",
            amount=1,
            unit="months",
            delivery_rule="de_admin_post",
        ),
        {},
    ),
    (DateSpec(type="relative", anchor="explicit_date", anchor_date="soon", amount=1, unit="months"), {}),
    (DateSpec(type="relative", amount=1, unit="months"), {}),
    (DateSpec(type="relative", anchor="document_date", unit="months"), {"document_date": "2026-09-01"}),
    (DateSpec(type="fixed", date="31.10.2026"), {}),
]
MISSING_INPUT_IDS = [
    "no-document-date",
    "no-posting-date",
    "unreadable-anchor",
    "no-anchor-no-date",
    "no-amount",
    "bad-fixed-date",
]


def test_missing_inputs_give_no_date_and_low_confidence() -> None:
    def check(spec: DateSpec, context: dict[str, Any]) -> None:
        receipt = compute_due(spec, ctx(**context))
        assert receipt.due_date is None
        assert receipt.confidence == "low"
        assert receipt.warnings
        assert receipt.summary.startswith("No date could be computed")

    check_rows(
        [pytest.param(*row, id=name) for row, name in zip(MISSING_INPUTS, MISSING_INPUT_IDS, strict=True)],
        check,
    )


def test_missing_anchor_counts_from_document_date() -> None:
    spec = DateSpec(type="relative", amount=14, unit="days", nature="payment")
    receipt = compute_due(spec, ctx(region="NW", document_date="2026-09-10"))
    assert receipt.due_date == "2026-09-24"
    assert receipt.confidence == "medium"


def test_today_anchor() -> None:
    spec = DateSpec(type="relative", anchor="today", amount=2, unit="weeks", nature="other")
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.due_date == "2026-10-09"
    assert receipt.send_by is None
    assert receipt.summary == "Two weeks after today (Fri 25 Sep 2026) is Fri 9 Oct 2026."


def test_deemed_delivery_without_rule_assumes_post_and_unknown_scope() -> None:
    spec = DateSpec(type="relative", anchor="deemed_delivery", amount=1, unit="months", nature="objection")
    receipt = compute_due(spec, ctx(region="NW", document_date="2026-09-15"))
    # Unknown sender: 4th day (NW confirmed), never moved → Sat 19 Sep → Mon 19 Oct.
    assert receipt.due_date == "2026-10-19"
    assert receipt.confidence == "low"  # two soft reasons: channel assumed, law unknown
    assert len(receipt.warnings) == 2


def test_delivery_rule_on_document_date_anchor() -> None:
    spec = DateSpec(
        type="relative",
        anchor="document_date",
        amount=1,
        unit="months",
        delivery_rule="de_admin_post",
        nature="objection",
    )
    receipt = compute_due(spec, ctx(region="NW", document_date="2026-09-15", delivery_scope="ao"))
    assert receipt.due_date == "2026-10-21"


# ----------------------------------------------------------------------- statutes & confidence


def test_statute_mismatch_uses_earlier_date() -> None:
    receipt = compute_due(
        notice_spec(amount=6, unit="weeks", legal_basis="§ 355 AO"),
        ctx(region="NW", document_date="2026-09-15", delivery_scope="ao"),
    )
    assert receipt.due_date == "2026-10-21"  # one month (statutory) is earlier than six weeks
    assert receipt.confidence == "medium"
    assert any("the law (§ 355 Abs. 1 AO; § 357 AO) gives one month" in w for w in receipt.warnings)
    # the other way round: the letter's shorter period is kept
    receipt = compute_due(
        notice_spec(amount=2, unit="weeks", legal_basis="§ 355 AO"),
        ctx(region="NW", document_date="2026-09-15", delivery_scope="ao"),
    )
    assert receipt.due_date == "2026-10-05"  # Mon 21 Sep + 2 weeks, earlier than the statute
    assert receipt.confidence == "medium"


def test_three_months_only_accepted_where_the_law_allows_it() -> None:
    """linkage verdict: three months only for SGG remedies after delivery abroad."""
    base = {
        "type": "relative",
        "anchor": "explicit_date",
        "anchor_date": "2026-10-15",
        "amount": 3,
        "unit": "months",
        "nature": "objection",
    }
    sgg = compute_due(DateSpec(**base, legal_basis="§ 84 SGG"), ctx(region="NW"))
    assert sgg.due_date == "2027-01-15" and sgg.confidence == "high"
    klage = compute_due(DateSpec(**base, legal_basis="§ 87 SGG"), ctx(region="NW"))
    assert klage.due_date == "2027-01-15" and klage.confidence == "medium"  # get-advice warning
    vwgo = compute_due(DateSpec(**base, legal_basis="§ 74 VwGO"), ctx(region="NW"))
    assert vwgo.due_date == "2026-11-16" and vwgo.confidence == "low"  # period ≠ statute, and a Klage


def test_fourteen_days_equals_two_weeks_for_owig() -> None:
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2026-09-17",
        amount=14,
        unit="days",
        nature="objection",
        legal_basis="§ 67 OWiG",
    )
    receipt = compute_due(spec, ctx(region="BY"))
    assert receipt.due_date == "2026-10-01"
    assert receipt.confidence == "high"


STATUTE_NAMES = [
    ("§ 355 Abs. 1 AO", "ao_355"),
    ("§70 VwGO", "vwgo_70"),
    ("§ 84 Abs. 1 SGG", "sgg_84"),
    ("§ 67 OWiG", "owig_67"),
    ("§ 55 OWiG", "owig_55"),
    ("Anhörungsbogen", "owig_55"),
    ("§ 410 StPO", "stpo_410"),
    ("§ 74 VwGO", "klage_1_month"),
    ("§ 87 Abs. 1 SGG", "klage_1_month"),
    ("§ 193 BGB", None),
]


def test_statute_recognition() -> None:
    def check(text: str, rule: str | None) -> None:
        assert statute_rule(DateSpec(type="relative", legal_basis=text)) == rule

    check_rows(STATUTE_NAMES, check)


def test_anhoerungsbogen_is_a_soft_deadline() -> None:
    """owig55: dated Mon 21 Sep 2026, 'within one week' → soft reminder Mon 28 Sep, medium confidence."""
    spec = DateSpec(
        type="relative",
        anchor="document_date",
        amount=1,
        unit="weeks",
        nature="declaration",
        legal_basis="§ 55 OWiG",
    )
    receipt = compute_due(spec, ctx(region="NW", document_date="2026-09-21"))
    assert receipt.due_date == "2026-09-28"
    assert receipt.confidence == "medium"
    assert "owig_55" in receipt.rule_ids
    assert any("not a legal deadline" in w for w in receipt.warnings)


def test_region_unknown_lowers_confidence_only_when_it_matters() -> None:
    # Fronleichnam (Thu 4 Jun 2026) is a holiday in some Länder: region matters.
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2026-05-04",
        amount=1,
        unit="months",
        nature="objection",
    )
    receipt = compute_due(spec, ctx())
    assert receipt.due_date == "2026-06-04"
    assert receipt.confidence == "medium"
    assert receipt.holiday_calendar == "Germany (nationwide holidays only)"
    # No regional holiday nearby: region does not matter.
    spec = spec.model_copy(update={"anchor_date": "2026-09-01"})
    assert compute_due(spec, ctx()).confidence == "high"


def test_region_unknown_business_days_and_ao_fiction() -> None:
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2026-05-29",
        amount=5,
        unit="business_days",
        nature="other",
    )
    receipt = compute_due(spec, ctx())
    assert receipt.due_date == "2026-06-05"  # 1, 2, 3, 4 (Fronleichnam ignored), 5 Jun
    assert receipt.confidence == "medium"
    # AO fiction day on a regional holiday (Allerheiligen falls on Sunday in 2026 → use 2027: Mon 1 Nov).
    receipt = compute_due(
        notice_spec(legal_basis="§ 355 AO"),
        ctx(today=D("2027-10-25"), document_date="2027-10-28", delivery_scope="ao"),
    )
    assert receipt.due_date == "2027-12-01"
    assert receipt.confidence == "medium"
    assert len([w for w in receipt.warnings if "Holiday region unknown" in w]) == 1


def test_foreign_country_is_low_confidence() -> None:
    spec = DateSpec(type="fixed", date="2026-10-15", nature="payment")
    receipt = compute_due(spec, ctx(country="AT"))
    assert receipt.due_date == "2026-10-15"
    assert receipt.confidence == "low"


# ------------------------------------------------------------------------------- fixed dates


def test_type_none() -> None:
    receipt = compute_due(DateSpec(type="none"), ctx())
    assert receipt.due_date is None
    assert receipt.summary == "This letter doesn't set a date."


def test_tax_payment_one_business_day_early() -> None:
    """money_tax: income tax back payment, notice posted Tue 15 Sep 2026 → due Wed 21 Oct; order by Tue 20 Oct."""
    receipt = compute_due(
        notice_spec(nature="payment", legal_basis="§ 36 Abs. 4 EStG"),
        ctx(region="NW", document_date="2026-09-15", delivery_scope="ao"),
    )
    assert receipt.due_date == "2026-10-21"
    assert receipt.send_by == "2026-10-20"


def test_payment_send_by_skips_bank_closing_days() -> None:
    """money_tax verdict: banks don't process transfers on 24 and 31 December."""
    receipt = compute_due(DateSpec(type="fixed", date="2027-01-04", nature="payment"), ctx(region="NW"))
    assert receipt.send_by == "2026-12-30"
    letter = compute_due(DateSpec(type="fixed", date="2027-01-04", nature="declaration"), ctx(region="NW"))
    assert letter.send_by == "2026-12-28"  # 31, 30, 29, 28 Dec: post still counts those days


def test_fixed_date_as_written() -> None:
    receipt = compute_due(DateSpec(type="fixed", date="2026-10-15", nature="payment"), ctx(region="NW"))
    assert receipt.due_date == "2026-10-15"
    assert receipt.send_by == "2026-10-14"  # one business day for a bank transfer (§ 675s BGB)
    assert "bgb_675s" in receipt.rule_ids
    assert receipt.summary == "The date given is Thu 15 Oct 2026."


def test_a_payment_made_in_person_gets_no_send_by() -> None:
    """The residence permit's fee, paid by girocard at the appointment, carried a bank
    transfer's send-by day (§ 675s BGB). Paid in person, the due day is the day."""
    spec = DateSpec(type="fixed", date="2026-10-14", time="10:30", nature="payment")
    receipt = compute_due(spec, replace(ctx(region="NW"), in_person=True))
    assert (receipt.due_date, receipt.send_by) == ("2026-10-14", None)
    assert "bgb_675s" not in receipt.rule_ids
    assert receipt.summary == "The date given is Wed 14 Oct 2026."
    # a period counted to a payment made in person has no transfer day either
    relative = notice_spec(nature="payment")
    counted = compute_due(relative, replace(ctx(region="NW", document_date="2026-09-15"), in_person=True))
    assert counted.due_date is not None and counted.send_by is None
    # a deadline to declare something keeps its posting day: only the transfer's is left out
    letter = DateSpec(type="fixed", date="2026-10-14", nature="declaration")
    assert compute_due(letter, replace(ctx(region="NW"), in_person=True)).send_by is not None


def test_a_collected_payment_gets_no_send_by() -> None:
    """A direct debit (or money coming in) got a bank transfer's send-by day. The
    sender collects it — nothing to transfer ahead, so no send-by day and no § 675s BGB step."""
    spec = DateSpec(type="fixed", date="2026-10-01", nature="payment")
    receipt = compute_due(spec, replace(ctx(region="NW"), collected=True))
    assert (receipt.due_date, receipt.send_by) == ("2026-10-01", None)
    assert "bgb_675s" not in receipt.rule_ids
    assert compute_due(spec, ctx(region="NW")).send_by == "2026-09-30"


# the Deutschlandticket's sentence on the university's re-registration letter
_UNI = "Falls Sie ein Deutschlandticket im Abonnement besitzen, denken Sie bitte daran, dieses rechtzeitig zum 31.03.2027 zu kündigen."


def test_a_notice_for_a_named_end_is_not_a_receive_by_date() -> None:
    """The words "rechtzeitig zum 31.03.2027 zu kündigen" name the day the subscription
    should END; it was filed as "must arrive by Wed 31 Mar 2027" with high confidence, three weeks after the
    contract's real deadline (the 10th). The engine counts back one month — the most a consumer contract may
    ask (§ 309 Nr. 9 BGB) —, never moves that day later and says to check the contract (low)."""
    spec = DateSpec(
        type="fixed", date="2027-03-31", nature="notice", text="rechtzeitig zum 31.03.2027", shift_rule="none"
    )
    receipt = compute_due(spec, replace(ctx(today=D("2026-09-28")), quote=_UNI))
    assert receipt.due_date == "2027-02-28"  # one month before 31 Mar (§ 188 BGB counted back)
    assert receipt.safe_date == "2027-02-26"  # a Sunday: notice deadlines never move later
    assert receipt.send_by == "2027-02-22"
    assert receipt.confidence == "low"
    assert receipt.warnings[0].startswith(
        "The letter gives the day the contract should end (Wed 31 Mar 2027), not the day your cancellation"
    )
    assert "up to three months" in receipt.warnings[0]
    assert {"date_as_written", "bgb_309_9_new", "notice_no_shift", "safe_date"} <= set(receipt.rule_ids)
    assert receipt.summary.startswith(
        "To end the contract on Wed 31 Mar 2027, the cancellation must arrive by"
    )
    # the day before the end: the end is always later than the day it must arrive
    assert D(receipt.due_date) < D(spec.date or "")
    # region unknown: a regional holiday could make the day before it earlier; with the region, it's known
    nw = compute_due(spec, replace(ctx(today=D("2026-09-28"), region="NW"), quote=_UNI))
    assert nw.due_date == "2027-02-28" and nw.holiday_calendar == "Nordrhein-Westfalen"


NOTICE_WORDS = [
    ("rechtzeitig zum 31.03.2027", _UNI, True),
    ("zum 31.12.2026", "Eine Kündigung ist zum 31.12.2026 möglich.", True),
    ("zum Ablauf des 31.12.2026", "Sie können zum Ablauf des 31.12.2026 kündigen.", True),
    ("mit Wirkung zum 31.12.2026", None, True),
    ("effective 31 March 2027", "Please cancel effective 31 March 2027.", True),
    # the day the notice must arrive, whatever else the sentence says
    ("bis zum 31.03.2027", "Die Kündigung muss bis zum 31.03.2027 bei uns eingehen.", False),
    ("zum 30.09.2026", "Ihre Kündigung muss uns spätestens zum 30.09.2026 vorliegen.", False),
    ("zum 30.09.2026", "Die Kündigung muss zum 30.09.2026 bei uns sein.", False),
    ("31 March 2027", "Your cancellation must reach us by 31 March 2027.", False),
    ("31.08.2026", "Kündigen Sie bis spätestens 31.08.2026.", False),
]


def test_which_notice_words_name_an_end() -> None:
    def check(text: str, quote: str | None, end: bool) -> None:
        spec = DateSpec(type="fixed", date="2027-03-31", nature="notice", text=text, shift_rule="none")
        receipt = compute_due(spec, replace(ctx(today=D("2026-09-28")), quote=quote))
        assert (receipt.due_date != "2027-03-31") is end
        assert (receipt.confidence == "low") is end

    check_rows(NOTICE_WORDS, check)


def test_only_a_notice_names_an_end() -> None:
    """A payment "zum 01.10." is due that day: only a cancellation is counted back from an end."""
    spec = DateSpec(type="fixed", date="2026-10-01", nature="payment", text="zum 01.10.2026")
    assert compute_due(spec, ctx(region="NW")).due_date == "2026-10-01"


def test_fixed_authority_deadline_shift_only_when_asked() -> None:
    """authority: 'Belege bis zum 10.10.2026' → Mon 12 Oct 2026 (§ 108 Abs. 3 AO)."""
    spec = DateSpec(type="fixed", date="2026-10-10", nature="declaration", shift_rule="next_business_day")
    receipt = compute_due(spec, ctx(region="NW", delivery_scope="ao"))
    assert receipt.due_date == "2026-10-12"
    assert "ao_108_3" in receipt.rule_ids
    assert (
        receipt.summary
        == "The date given is Sat 10 Oct 2026, a Saturday, so the deadline moves to Mon 12 Oct 2026."
    )
    # With the default shift rule the date stays as written and a warning explains the possible shift.
    receipt = compute_due(
        spec.model_copy(update={"shift_rule": "auto"}), ctx(region="NW", delivery_scope="ao")
    )
    assert receipt.due_date == "2026-10-10"
    assert any("may legally move to Mon 12 Oct 2026" in w for w in receipt.warnings)
    assert "authority_deadline" in receipt.rule_ids


def test_a_private_senders_weekend_date_is_kept_without_citing_an_authoritys_law() -> None:
    """A payment to a private sender due Sat 10 Oct 2026 stays as written with the same warning, but its
    receipt cites no authority's procedure law (§ 108 AO, § 31 VwVfG, § 26 SGB X)."""
    spec = DateSpec(type="fixed", date="2026-10-10", nature="payment")
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.due_date == "2026-10-10"
    assert any("may legally move to Mon 12 Oct 2026" in w for w in receipt.warnings)
    assert "authority_deadline" not in receipt.rule_ids


def test_fixed_shift_without_scope_and_region() -> None:
    spec = DateSpec(type="fixed", date="2026-06-03", nature="payment", shift_rule="next_business_day")
    receipt = compute_due(spec, ctx())
    assert receipt.due_date == "2026-06-03"
    assert "bgb_193" in receipt.rule_ids
    spec = DateSpec(type="fixed", date="2026-06-04", nature="payment", shift_rule="next_business_day")
    assert compute_due(spec, ctx()).confidence == "medium"  # Fronleichnam somewhere


def test_fixed_date_expressly_not_shifted() -> None:
    """authority: 'Die Frist endet am Samstag, 10.10.2026; § 31 Abs. 3 VwVfG findet keine Anwendung'."""
    spec = DateSpec(type="fixed", date="2026-10-10", nature="declaration", shift_rule="none")
    receipt = compute_due(spec, ctx(region="NW", delivery_scope="vwvfg"))
    assert receipt.due_date == "2026-10-10"


def test_appointments_never_shift() -> None:
    """authority: summons for Sat 10 Oct 2026 10:00 stays on Saturday. Its receipt cites the authority's
    procedure law (Termine keep their day) only for an authority, never for a court or a private sender."""
    spec = DateSpec(
        type="fixed", date="2026-10-10", time="10:00", nature="appointment", shift_rule="next_business_day"
    )
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.due_date == "2026-10-10"
    assert receipt.send_by is None
    assert "authority_deadline" not in receipt.rule_ids
    assert "authority_deadline" in compute_due(spec, ctx(region="NW", delivery_scope="vwvfg")).rule_ids
    court = compute_due(spec, ctx(region="NW", delivery_scope="vwvfg", court=True))
    assert court.due_date == "2026-10-10" and "authority_deadline" not in court.rule_ids


def test_fixed_other_nature_on_weekend_is_kept() -> None:
    receipt = compute_due(DateSpec(type="fixed", date="2026-10-10", nature="other"), ctx(region="NW"))
    assert receipt.due_date == "2026-10-10"
    assert receipt.warnings == []


def test_fixed_notice_on_weekend_gets_safe_date() -> None:
    """bgb_193_nicht: contract ends 31 Jan 2027, 3 months → notice by Sat 31 Oct 2026, no shift."""
    spec = DateSpec(type="fixed", date="2026-10-31", nature="notice")
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.due_date == "2026-10-31"
    assert receipt.safe_date == "2026-10-30"
    assert receipt.send_by == "2026-10-26"
    assert "notice_no_shift" in receipt.rule_ids
    assert receipt.summary == (
        "The notice must arrive by Sat 31 Oct 2026, a Saturday; notice deadlines don't move, so aim for Fri 30 Oct 2026."
    )


# --------------------------------------------------------------------------- notice & backwards


def test_relative_notice_backwards_from_contract_end() -> None:
    """bgb_193_nicht: 'three months to the end of the term (31.01.2027)' → Sat 31 Oct 2026."""
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2027-01-31",
        amount=-3,
        unit="months",
        nature="notice",
    )
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.due_date == "2026-10-31"
    assert receipt.safe_date == "2026-10-30"
    assert receipt.summary.startswith("Three months before Sun 31 Jan 2027 is Sat 31 Oct 2026, a Saturday")
    # a notice never shifts, even if asked to
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2027-01-31",
        amount=-3,
        unit="months",
        nature="notice",
        shift_rule="next_business_day",
    )
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.due_date == "2026-10-31"
    assert receipt.safe_date == "2026-10-30"


def test_relative_deadline_expressly_not_shifted() -> None:
    """authority: § 31 Abs. 3 S. 2 VwVfG lets an authority exclude the shift (shift_rule "none")."""
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2026-09-26",
        amount=2,
        unit="weeks",
        nature="declaration",
        shift_rule="none",
    )
    receipt = compute_due(spec, ctx(region="NW", delivery_scope="vwvfg"))
    assert receipt.due_date == "2026-10-10"  # a Saturday, kept


def test_relative_backwards_before_an_appointment() -> None:
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2026-10-15",
        amount=-14,
        unit="days",
        nature="other",
    )
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.due_date == "2026-09-30"  # the full 14 days must lie before the appointment day


def test_notice_period_forward_on_business_day() -> None:
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2026-09-29",
        amount=2,
        unit="weeks",
        nature="notice",
    )
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.due_date == receipt.safe_date == "2026-10-13"


# --------------------------------------------------------------------------------- send-by


def test_send_by_clamped_to_today_with_warning() -> None:
    spec = DateSpec(type="fixed", date="2026-09-28", nature="declaration")
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.send_by == "2026-09-25"
    assert any("usual sending time has passed" in w for w in receipt.warnings)
    assert sending_time_passed(receipt)


def test_only_a_passed_sending_time_makes_the_due_date_the_one_that_counts() -> None:
    in_time = compute_due(DateSpec(type="fixed", date="2026-10-21", nature="objection"), ctx(region="NW"))
    assert in_time.send_by == "2026-10-15"
    assert not sending_time_passed(in_time)
    assert not sending_time_passed(None)


def test_send_by_none_when_date_has_passed() -> None:
    spec = DateSpec(type="fixed", date="2026-09-01", nature="payment")
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.send_by is None
    assert any("has already passed" in w for w in receipt.warnings)


def test_custom_postal_buffer() -> None:
    spec = DateSpec(type="fixed", date="2026-10-21", nature="objection")
    assert compute_due(spec, ctx(region="NW"), postal_buffer_days=2).send_by == "2026-10-19"
    assert postal_buffer(Profile(postal_buffer_days=2)) == POSTAL_BUFFER_DAYS
    assert postal_buffer(Profile(postal_buffer_days=6)) == 6


# ------------------------------------------------------------------------- one-year fallback


ONE_YEAR_FALLBACKS = [
    pytest.param("2025-10-07", "NW", "2026-10-07", id="rbb-steuerbescheid"),
    pytest.param("2025-10-31", "SN", "2026-11-02", id="rbb-leipzig-saturday"),
    pytest.param("2024-02-29", "NW", "2025-02-28", id="rbb-leap-day"),
    pytest.param("2025-10-03", "NW", "2026-10-05", id="rbb-vwvfg-holiday-fiction"),
]


def test_one_year_fallback() -> None:
    def check(event: str, region: str, expected: str) -> None:
        spec = DateSpec(
            type="relative",
            anchor="explicit_date",
            anchor_date=event,
            amount=1,
            unit="months",
            nature="objection",
            legal_basis="§ 355 AO",
        )
        receipt = compute_one_year_fallback(spec, ctx(region=region, today=D(event)))
        assert receipt.due_date == expected
        assert receipt.confidence == "low"
        assert "rbb_one_year" in receipt.rule_ids
        assert receipt.warnings[0].startswith("Only if the instructions on how to object")
        assert receipt.summary.startswith("If the instructions on how to object were missing or wrong: ")

    check_rows(ONE_YEAR_FALLBACKS, check)


def test_one_year_fallback_from_deemed_delivery() -> None:
    receipt = compute_one_year_fallback(
        notice_spec(), ctx(region="NW", document_date="2026-09-15", delivery_scope="ao")
    )
    assert receipt.due_date == "2027-09-21"


def test_one_year_fallback_without_anchor() -> None:
    receipt = compute_one_year_fallback(notice_spec(), ctx(region="NW", delivery_scope="ao"))
    assert receipt.due_date is None
    assert receipt.summary.startswith("No date could be computed")


def test_parse_date() -> None:
    assert parse_date("2026-10-21") == D("2026-10-21")
    assert parse_date("2026-10-21T10:00:00") == D("2026-10-21")
    assert parse_date("21.10.2026") is None
    assert parse_date(None) is None


def test_a_delivery_date_stated_on_the_letter_is_the_anchor_for_a_fine() -> None:
    """Dev-benchmark regression: 'zugestellt am 17.09.2026' on a Bußgeldbescheid starts the two weeks."""
    from datetime import date

    from ordnung.models import DateSpec
    from ordnung.rules import RuleContext, compute_due

    spec = DateSpec(
        type="relative",
        anchor="receipt",
        anchor_date="2026-09-17",
        amount=2,
        unit="weeks",
        nature="objection",
        legal_basis="§ 67 Abs. 1 OWiG",
        text="innerhalb von zwei Wochen nach Zustellung",
    )
    ctx = RuleContext(today=date(2026, 9, 20), document_date=date(2026, 9, 14))
    receipt = compute_due(spec, ctx)
    assert receipt.due_date == "2026-10-01"
    assert "as stated on the letter" in receipt.summary
    # a stated date earlier than the letter itself can't be a delivery date: fall back to the safe start
    earlier = spec.model_copy(update={"anchor_date": "2026-09-10"})
    assert compute_due(earlier, ctx).due_date == "2026-09-28"


# ------------------------------------------------------------------ private senders: no deemed delivery


def test_a_private_senders_letter_counts_from_its_arrival() -> None:
    """Deemed delivery is a rule for authorities: a company's "14 days after delivery" runs from the day
    the letter arrived (§ 130 BGB) — the letter's date until the person says when, never 3 days later."""
    spec = notice_spec(amount=14, unit="days", nature="payment")
    company = compute_due(spec, ctx(document_date="2026-09-01", private_sender=True))
    assert company.due_date == "2026-09-15" and company.confidence == "low"  # not Fri 18 Sep
    assert "posting_day" not in company.rule_ids and "private_sender_arrival" in company.rule_ids
    assert company.warnings[:2] == [PRIVATE_SENDER_WARNING, ASSUMED_RECEIPT_WARNING]
    assert company.steps[0].label == (
        "Not an authority's letter, so no delivery days: the period runs from the letter's date (Tue 1 Sep 2026)"
    )
    arrived = compute_due(
        spec,
        ctx(
            document_date="2026-09-01",
            received_date="2026-09-04",
            received_confirmed=True,
            private_sender=True,
        ),
    )
    assert arrived.due_date == "2026-09-18" and arrived.confidence == "high"
    assert "the day you received it (Fri 4 Sep 2026)" in arrived.steps[0].label
    # the same letter from an unknown sender keeps the earliest plausible deemed delivery
    assert compute_due(spec, ctx(document_date="2026-09-01")).due_date == "2026-09-18"


PRIVATE_SENDER_ARRIVALS = [None, "2026-09-16"]


def test_a_private_senders_period_from_a_date_it_gives_never_claims_to_count_from_arrival() -> None:
    """The words "14 days from the invoice date" read with a delivery rule. The rule goes and the
    invoice date stays, so the receipt must not say the period runs from arrival, nor carry the rule id
    that makes the app ask for the arrival day — an answer it would then ignore."""

    def check(received: str | None) -> None:
        spec = DateSpec(
            type="relative",
            anchor="document_date",
            amount=14,
            unit="days",
            delivery_rule="de_admin_post",
            nature="payment",
            text="Bitte zahlen Sie innerhalb von 14 Tagen ab Rechnungsdatum.",
        )
        arrival = {"received_date": received, "received_confirmed": True} if received else {}
        receipt = compute_due(
            spec, ctx(today="2026-09-20", document_date="2026-09-14", private_sender=True, **arrival)
        )
        assert receipt.due_date == "2026-09-28" and receipt.confidence == "high"
        assert receipt.warnings == [PRIVATE_SENDER_DATED_WARNING]
        assert (
            "private_sender_no_delivery" in receipt.rule_ids
            and "private_sender_arrival" not in receipt.rule_ids
        )
        assert receipt.steps[0].label == (
            "Not an authority's letter, so no delivery days: the period runs from the letter's date (Mon 14 Sep 2026)"
        )
        assert receipt.steps[0].citation == "§ 187 Abs. 1 BGB"
        # a period from another date the letter names: that date, whenever the letter arrived
        named = spec.model_copy(update={"anchor": "explicit_date", "anchor_date": "2026-09-10"})
        other = compute_due(
            named, ctx(today="2026-09-20", document_date="2026-09-14", private_sender=True, **arrival)
        )
        assert other.due_date == "2026-09-24" and other.warnings == [PRIVATE_SENDER_DATED_WARNING]
        assert other.steps[0].rule_id == "private_sender_no_delivery"

    check_rows(PRIVATE_SENDER_ARRIVALS, check)


def test_a_remedy_statute_keeps_deemed_delivery_for_a_sender_filed_as_private() -> None:
    """A letter naming § 70 VwGO is an authority's decision, whatever its sender was filed as."""
    spec = notice_spec(legal_basis="§ 70 VwGO")
    receipt = compute_due(spec, ctx(document_date="2026-09-01", private_sender=True))
    assert "posting_day" in receipt.rule_ids and PRIVATE_SENDER_WARNING not in receipt.warnings
    assert from_arrival(spec, ctx(private_sender=True)) is spec


def test_from_arrival_leaves_other_specs_alone() -> None:
    private = ctx(private_sender=True)
    for spec in (
        DateSpec(type="fixed", date="2026-10-01", delivery_rule="de_admin_post", anchor="document_date"),
        DateSpec(type="relative", anchor="receipt", amount=14, unit="days"),
        DateSpec(type="relative", anchor="document_date", amount=14, unit="days"),
        notice_spec(),  # not a private sender
    ):
        context = ctx() if spec.anchor == "deemed_delivery" else private
        assert from_arrival(spec, context) is spec
    missing = compute_due(notice_spec(), ctx(private_sender=True))  # no date to count from at all
    assert missing.due_date is None and PRIVATE_SENDER_WARNING in missing.warnings


def test_a_private_senders_letter_without_a_date_still_asks_for_the_arrival_day() -> None:
    """The engine needs the arrival day, and the app asks for it by the rule id
    ``private_sender_arrival`` — which must be there even when no date could be computed."""
    spec = notice_spec(amount=4, unit="weeks")
    receipt = compute_due(spec, ctx(today="2026-09-26", private_sender=True))
    assert receipt.due_date is None and receipt.confidence == "low"
    assert receipt.warnings == [PRIVATE_SENDER_WARNING, NEEDS_ARRIVAL_WARNING]
    assert receipt.rule_ids == ["private_sender_arrival"]
    assert [(step.rule_id, step.date) for step in receipt.steps] == [("private_sender_arrival", None)]
    assert receipt.steps[0].citation == "§ 130 Abs. 1 BGB"


def test_the_periods_own_words_never_bring_deemed_delivery_back() -> None:
    """Words that may name an administrative act are no proof — a gym writes "nach
    Bekanntgabe der Preiserhöhung", an employer's certificate cites "§ 312 Abs. 1 SGB III". A sender filed
    as private keeps counting from the day it arrived, the earliest plausible start: deemed delivery
    would make these dates 3 days late (Mon 19 Oct)."""
    arrived = {"received_date": D("2026-10-02"), "received_confirmed": True}
    gym = notice_spec(
        amount=2,
        unit="weeks",
        nature="declaration",
        delivery_rule="none",
        text="innerhalb von zwei Wochen nach Bekanntgabe der Preiserhöhung",
    )
    context = ctx(today="2026-10-05", document_date="2026-10-01", private_sender=True, sender_kind="gym")
    assert from_arrival(gym, context) is not gym
    receipt = compute_due(gym, replace(context, **arrived))
    assert receipt.due_date == "2026-10-16" and receipt.warnings == [PRIVATE_SENDER_WARNING]
    assert receipt.steps[0].rule_id == "private_sender_arrival"
    assert not {"posting_day", "early_receipt"} & set(receipt.rule_ids)
    assert compute_due(gym, context).due_date == "2026-10-15"  # the letter's date until it is given
    # (§ 38 Abs. 1 SGB III itself is routed to the job-seeking registration's own rule, rules.letters)
    employer = gym.model_copy(
        update={"legal_basis": "§ 312 Abs. 1 SGB III", "text": "innerhalb von zwei Wochen"}
    )
    certificate = compute_due(employer, replace(context, sender_kind="employer", **arrived))
    assert certificate.due_date == "2026-10-16" and "private_sender_arrival" in certificate.rule_ids
    # a remedy statute is more than a word: it names the authority's own procedure, which keeps its rule
    statute = notice_spec(legal_basis="§ 70 VwGO")
    assert from_arrival(statute, context) is statute


def test_the_private_sender_rule_and_the_court_rules_meet() -> None:
    """Integration of the private-sender rule (a company's letter counts from arrival) with the court
    rules: a court's letter, and a court order filed by its kind, is never re-anchored as a private
    sender's, even from a sender filed under a private kind — its periods run from formal service
    (§ 180 ZPO). A private-law period a private sender's letter names — the Kündigungsschutzklage's
    three weeks from the dismissal's receipt (§ 4 S. 1 KSchG) — still runs from arrival, never 3 days
    late from a delivery fiction."""
    spec = notice_spec(amount=2, unit="weeks")
    company = ctx(today="2026-09-28", document_date="2026-09-23", private_sender=True, sender_kind="company")
    assert from_arrival(spec, company) is not spec
    assert from_arrival(spec, replace(company, court=True)) is spec
    assert from_arrival(spec, replace(company, letter_kind="court_payment_order")) is spec
    court = compute_due(spec, replace(company, court=True))
    assert "private_sender_arrival" not in court.rule_ids and "zpo_180" in court.rule_ids
    kschg = notice_spec(amount=3, unit="weeks", legal_basis="§ 4 KSchG")
    employer = ctx(
        today="2026-09-26", document_date="2026-09-01", private_sender=True, sender_kind="employer"
    )
    counted = from_arrival(kschg, employer)
    assert counted is not kschg and counted.anchor == "receipt"
    dismissal = compute_due(kschg, employer)
    assert dismissal.due_date == "2026-09-22" and {"kschg_4", "private_sender_arrival"} <= set(
        dismissal.rule_ids
    )
    # from a public employer too, and never "not an authority's letter"
    city = ctx(today="2026-09-26", document_date="2026-09-01", sender_kind="authority")
    public = compute_due(kschg, city)
    assert public.due_date == "2026-09-22" and DECLARATION_ARRIVAL_WARNING in public.warnings
    assert public.steps[0].label.startswith("A dismissal takes effect when it arrives, whoever sends it")
    assert not any(
        "not an authority" in text for text in (*public.warnings, *(s.label for s in public.steps))
    )
    dated = compute_due(kschg.model_copy(update={"anchor": "document_date"}), city)
    assert DECLARATION_DATED_WARNING in dated.warnings
    missing = compute_due(kschg, ctx(today="2026-09-26", sender_kind="authority"))
    assert missing.due_date is None and missing.steps[0].label.startswith("A dismissal takes effect")


BESCHEID_WORDS = [
    ("Die Gebühr ist innerhalb eines Monats nach Bekanntgabe dieses Bescheides zu zahlen.", None),
    (
        "innerhalb eines Monats",
        "Gegen den Gebührenbescheid vom 1. September kann Widerspruch erhoben werden.",
    ),
]


def test_words_naming_a_bescheid_keep_a_late_arrival_from_moving_the_date() -> None:
    """A municipal office's Gebührenbescheid filed under a kind no public body goes by (a ``landlord``):
    it counts from the day it arrived, but its words — the spec's, or the sentence it was read from
    (``quote``) — show it may be an authority's, so an arrival after the day it would usually count as
    delivered does not make the date later (Mon 5 Oct, not Wed 14 Oct)."""

    def check(words: str, quote: str | None) -> None:
        spec = notice_spec(nature="payment", text=words)
        late = ctx(
            today="2026-09-20",
            document_date="2026-09-01",
            received_date="2026-09-14",
            received_confirmed=True,
            region="NW",
            private_sender=True,
            sender_kind="landlord",
            quote=quote,
        )
        receipt = compute_due(spec, late)
        assert receipt.due_date == "2026-10-05"  # usually delivered Sat 5 Sep (4th day, NW)
        assert "private_sender_late_arrival" in receipt.rule_ids and "posting_day" not in receipt.rule_ids
        # arriving by then, it counts from the day it arrived: the earlier start
        early = compute_due(spec, replace(late, received_date=D("2026-09-02")))
        assert early.due_date == "2026-10-02" and "private_sender_arrival" in early.rule_ids
        # without such words a landlord's letter counts from the day it arrived, however late
        plain = compute_due(
            notice_spec(nature="payment", text="innerhalb eines Monats"), replace(late, quote=None)
        )
        assert plain.due_date == "2026-10-14" and "private_sender_late_arrival" not in plain.rule_ids

    check_rows(BESCHEID_WORDS, check)


def _late(received: str, **kw: Any) -> RuleContext:
    kw.setdefault("document_date", "2026-09-14")
    return ctx(today="2026-10-01", received_date=received, received_confirmed=True, private_sender=True, **kw)


def test_a_private_senders_late_arrival_never_makes_the_date_later() -> None:
    """Whether a sender is an authority is read, not known (a statutory insurer or a
    municipal utility filed as ``company``). An arrival after the day an authority's letter would count as
    delivered must not move the date past the deemed-delivery one; the note gives the date from arrival."""
    spec = notice_spec(amount=14, unit="days", text="Einspruch innerhalb von 14 Tagen")
    authority = compute_due(spec, ctx(today="2026-10-01", document_date="2026-09-14"))
    assert authority.due_date == "2026-10-01"  # delivered Thu 17 Sep (3rd day, the Land unknown)
    late = compute_due(spec, _late("2026-09-25"))
    assert late.due_date == authority.due_date and late.confidence == "medium"
    assert "private_sender_late_arrival" in late.rule_ids and "late_receipt" not in late.rule_ids
    # one step, in place of "runs from the day you received it" — the period does not run from there
    assert "private_sender_arrival" not in late.rule_ids
    assert late.steps[0].label == (
        "It arrived on Fri 25 Sep 2026, later than a letter dated Mon 14 Sep 2026 usually counts as "
        "delivered (Thu 17 Sep 2026): we count from that earlier, safe day"
    )
    assert late.steps[0].date == "2026-09-17"
    assert late.summary.startswith("14 days after the day it would usually count as delivered (Thu 17 Sep")
    # the law counts a later arrival for an authority's letter too, once it is shown (§ 41 Abs. 2 S. 3
    # VwVfG): the note says so instead of "the period runs from the day the letter arrived"
    assert late.warnings[0] == (
        "You told us it arrived on Fri 25 Sep 2026, later than a letter dated Mon 14 Sep 2026 usually counts "
        "as delivered (Thu 17 Sep 2026). If you can show that (keep the envelope), the deadline may be Fri 9 "
        "Oct 2026, whether or not the sender is an authority; we show the earlier, safe date."
    )
    assert PRIVATE_SENDER_WARNING not in late.warnings
    # a posting day the letter states is named as such
    posted = compute_due(spec.model_copy(update={"anchor_date": "2026-09-11"}), _late("2026-09-25"))
    assert posted.steps[0].label.startswith(
        "It arrived on Fri 25 Sep 2026, later than a letter posted on Fri 11"
    )
    # arriving by the deemed day, the letter counts from the day it arrived: the earlier start
    for received, due in (("2026-09-15", "2026-09-29"), ("2026-09-17", "2026-10-01")):
        early = compute_due(spec, _late(received))
        assert early.due_date == due and "private_sender_late_arrival" not in early.rule_ids
    # a confirmed Land using the 4-day rule gives the authority's letter a day more, and so the cap
    assert compute_due(spec, _late("2026-09-25", region="NW")).due_date == "2026-10-02"
    # without the letter's date there is no deemed day to compare with: the arrival day it is
    undated = compute_due(spec, _late("2026-09-25", document_date=None))
    assert undated.due_date == "2026-10-09" and "private_sender_late_arrival" not in undated.rule_ids
    # a period counted back from delivery is capped too, with no date from arrival to name
    back = compute_due(spec.model_copy(update={"amount": -3}), _late("2026-09-25"))
    assert "private_sender_late_arrival" in back.rule_ids and back.confidence == "medium"
    assert any(
        "the deadline may be later, whether or not the sender is an authority" in w for w in back.warnings
    )
    # a company, insurer, utility or employer may be a public body filed so: capped too
    assert compute_due(spec, _late("2026-09-25", sender_kind="company")).due_date == "2026-10-01"
    # a gym, a landlord or a bank issues no Bescheid: its letter counts from the day it arrived
    for kind in ("gym", "landlord", "bank"):
        plain = compute_due(spec, _late("2026-09-25", sender_kind=kind))
        assert plain.due_date == "2026-10-09" and "private_sender_late_arrival" not in plain.rule_ids
    # a notice deadline does not move off a weekend, from the arrival day either (Sat 10 Oct)
    notice = compute_due(spec.model_copy(update={"nature": "notice"}), _late("2026-09-26"))
    assert any("the deadline may be Sat 10 Oct 2026, whether" in w for w in notice.warnings)


def test_a_late_arrival_note_says_when_the_later_date_may_still_be_open() -> None:
    """A company's letter dated Tue 1 Sep arrived Fri 25 Sep; on Thu 1 Oct the date
    shown (Fri 18 Sep, from the usual delivery day) has passed, the one from arrival (Fri 9 Oct) has
    not. The note must not let a probably live deadline read as missed."""
    spec = notice_spec(amount=14, unit="days")
    open_ = compute_due(spec, _late("2026-09-25", document_date="2026-09-01", sender_kind="company"))
    assert open_.due_date == "2026-09-18" and open_.confidence == "medium"
    assert open_.warnings[0].endswith(
        "we show the earlier, safe date. The earlier date has passed, the later one has not: the deadline "
        "may still be open."
    )
    assert "This date (Fri 18 Sep 2026) has already passed." in open_.warnings
    # both passed, or neither: nothing to add
    for today in ("2026-10-10", "2026-09-17"):
        received = "2026-09-17" if today == "2026-09-17" else "2026-09-25"
        context = replace(_late(received, document_date="2026-09-01"), today=D(today))
        assert not any("may still be open" in w for w in compute_due(spec, context).warnings)
    # an authority's letter shown to have arrived late says the same
    authority = ctx(
        today="2026-10-01", document_date="2026-09-01", received_date="2026-09-25", received_confirmed=True
    )
    assert any(
        w.startswith("You told us it arrived on Fri 25 Sep 2026")
        and w.endswith("the deadline may still be open.")
        for w in compute_due(spec, authority).warnings
    )


def test_a_late_arrival_giving_the_same_date_counts_from_the_arrival() -> None:
    """A company's payment letter dated Tue 1 Sep (NW) usually counts as delivered on
    Sat 5 Sep; it arrived Mon 7 Sep. 14 days from either day end on Mon 21 Sep (Sat 19 Sep moves), so
    there is nothing to cap: it counts from the arrival as any private sender's letter, with no note
    that the deadline "may be" the date already shown and no confidence lost."""
    spec = notice_spec(amount=14, unit="days", nature="payment")
    context = _late("2026-09-07", document_date="2026-09-01", sender_kind="company", region="NW")
    same = compute_due(spec, context)
    assert (same.due_date, same.confidence) == ("2026-09-21", "high")
    assert same.steps[0].rule_id == "private_sender_arrival"
    assert "private_sender_late_arrival" not in same.rule_ids
    assert same.summary == "14 days after the day you received it (Mon 7 Sep 2026) is Mon 21 Sep 2026."
    assert PRIVATE_SENDER_WARNING in same.warnings and not any("may be" in w for w in same.warnings)
    # the same as a gym's letter, which is never capped
    gym = compute_due(spec, replace(context, sender_kind="gym"))
    assert (gym.due_date, gym.confidence, gym.warnings) == (same.due_date, "high", same.warnings)
    # a day later the dates differ (Mon 21 Sep, Tue 22 Sep): capped, with the note
    later = compute_due(spec, replace(context, received_date=D("2026-09-08")))
    assert (later.due_date, later.confidence) == ("2026-09-21", "medium")
    assert "private_sender_late_arrival" in later.rule_ids
    assert any("the deadline may be Tue 22 Sep 2026, whether" in w for w in later.warnings)
    # a utility's one-month objection dated Tue 27 Jan, arrived Sat 31 Jan: Mon 2 Mar either way
    utility = compute_due(
        notice_spec(),
        replace(
            _late("2026-01-31", document_date="2026-01-27", sender_kind="utility"), today=D("2026-02-05")
        ),
    )
    assert (utility.due_date, utility.confidence) == ("2026-03-02", "high")
    assert "private_sender_late_arrival" not in utility.rule_ids
    # a period counted back gives no date from arrival to compare with: capped as before
    back = compute_due(spec.model_copy(update={"amount": -3}), context)
    assert "private_sender_late_arrival" in back.rule_ids


def test_an_authoritys_late_arrival_giving_the_same_date_needs_no_note() -> None:
    """A VwVfG letter dated Tue 1 Sep (NW) counts as delivered on Sat 5 Sep; it arrived Mon 7 Sep. 14
    days from either day end on Mon 21 Sep: no note that it "may be Mon 21 Sep instead"."""
    spec = notice_spec(amount=14, unit="days", legal_basis=None)
    context = ctx(
        region="NW",
        document_date="2026-09-01",
        received_date="2026-09-07",
        received_confirmed=True,
        delivery_scope="vwvfg",
        today=D("2026-09-10"),
    )
    same = compute_due(spec, context)
    assert same.due_date == "2026-09-21" and same.confidence == "high"
    assert "late_receipt" not in same.rule_ids and not any("instead" in w for w in same.warnings)
    later = compute_due(spec, replace(context, received_date=D("2026-09-08")))
    assert later.due_date == "2026-09-21" and "late_receipt" in later.rule_ids
    assert any("the deadline may be Tue 22 Sep 2026 instead" in w for w in later.warnings)


SENDING_CHANNELS = [
    ("de_admin_post", "posted on"),
    ("de_admin_electronic", "sent on"),
    ("de_admin_portal", "made available on"),
]


def test_a_capped_start_names_how_the_letter_was_sent() -> None:
    """A stated posting day reads by channel: a letter is posted, sent electronically, or made
    available in a portal (where it usually counts as delivered the day after); its own date is its date."""

    def check(rule: str, sent: str) -> None:
        spec = notice_spec(amount=14, unit="days", delivery_rule=rule, anchor_date="2026-09-01")
        late = compute_due(spec, _late("2026-09-10", document_date=None, sender_kind="company"))
        deemed = "Wed 2 Sep 2026" if rule == "de_admin_portal" else "Fri 4 Sep 2026"
        assert late.steps[0].label == (
            f"It arrived on Thu 10 Sep 2026, later than a letter {sent} Tue 1 Sep 2026 usually counts as "
            f"delivered ({deemed}): we count from that earlier, safe day"
        )
        dated = compute_due(
            spec.model_copy(update={"anchor_date": None}),
            _late("2026-09-10", document_date="2026-09-01", sender_kind="company"),
        )
        assert dated.steps[0].label.startswith(
            "It arrived on Thu 10 Sep 2026, later than a letter dated Tue 1"
        )

    check_rows(SENDING_CHANNELS, check)


def test_period_problem_says_why_nothing_was_computed() -> None:
    """The rules tools ask it before reporting an arrival day: an unreadable period computes nothing."""
    assert period_problem(notice_spec()) is None
    assert period_problem(notice_spec(amount=None)) == "The length of the period could not be read."
    assert period_problem(notice_spec(amount=200, unit="years")) == (
        "A period of 200 years can't be right — please check the letter."
    )
    receipt = compute_due(notice_spec(amount=None), ctx(document_date="2026-09-01", private_sender=True))
    assert (
        receipt.due_date is None and receipt.rule_ids == [] and PRIVATE_SENDER_WARNING not in receipt.warnings
    )


# ------------------------------------------------ region unknown: dates counted back can be too late


def test_a_backward_count_over_a_regional_holiday_is_flagged_earlier() -> None:
    """5 working days before Wed 5 Nov 2025 is Tue 28 Oct with nationwide holidays — but Mon 27 Oct in
    the nine Länder where Fri 31 Oct is Reformationstag: the date shown would be a day late there."""
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2025-11-05",
        amount=-5,
        unit="business_days",
        nature="declaration",
    )
    unknown = compute_due(spec, ctx(today=D("2025-10-01")))
    assert unknown.due_date == "2025-10-28" and unknown.confidence == "medium"
    assert unknown.warnings == [
        "Holiday region unknown — Fri 31 Oct 2025 is a public holiday in some Länder (e.g. Brandenburg, Bremen, "
        "Hamburg), where the deadline would be earlier — act a working day before it to be safe. We used "
        "nationwide holidays only."
    ]
    lower_saxony = compute_due(spec, ctx(today=D("2025-10-01"), region="NI"))
    assert lower_saxony.due_date == "2025-10-27" and lower_saxony.confidence == "high"
    # Werktage count Saturdays: the holiday still counts; a span without one is not flagged
    werktage = compute_due(spec.model_copy(update={"unit": "werktage"}), ctx(today=D("2025-10-01")))
    assert werktage.confidence == "medium"
    quiet = compute_due(spec.model_copy(update={"anchor_date": "2025-09-20"}), ctx(today=D("2025-08-01")))
    assert quiet.confidence == "high" and quiet.warnings == []


def test_a_safe_date_on_a_regional_holiday_is_flagged_earlier() -> None:
    """A notice deadline never moves: on Reformationstag its safe date is the Thursday before there."""
    fixed = compute_due(
        DateSpec(type="fixed", date="2025-10-31", nature="notice"), ctx(today=D("2025-10-01"))
    )
    assert fixed.safe_date == "2025-10-31" and fixed.confidence == "medium"
    assert "where the deadline would be earlier" in fixed.warnings[0]
    assert (
        compute_due(
            DateSpec(type="fixed", date="2025-10-31", nature="notice"),
            ctx(today=D("2025-10-01"), region="NW"),
        ).warnings
        == []
    )  # not a holiday there
    backward = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2025-12-01",
        amount=-1,
        unit="months",
        nature="payment",
    )
    receipt = compute_due(backward, ctx(today=D("2025-10-01")))  # one month before: Fri 31 Oct
    assert receipt.due_date == "2025-10-31" and receipt.confidence == "medium"
    assert "where the deadline would be earlier" in receipt.warnings[0]


# ------------------------------------------------------------------------------ partial holidays

_MUNICH = (
    "a public holiday only in the communities of Bayern with more Catholic than Protestant residents (as the "
    "Landesamt für Statistik lists them; Munich among them), which is not counted here. Where it holds, "
)


def _partial(receipt: Any, name: str) -> list[str]:
    return [w for w in receipt.warnings if name in w]


def test_a_partial_holiday_a_date_is_counted_back_over_is_named_in_the_app_too() -> None:
    """A gym's notice deadline on Tue 15 Aug 2028 in Bavaria. The calendar counts only a
    whole Land's holidays; in Munich that day is one, so the safe date there is a working day earlier.
    The engine says so (the app and the rules tools alike); the Land's calendar stays the rule."""
    notice = DateSpec(type="fixed", date="2028-08-15", nature="notice")
    gym = compute_due(notice, ctx(today=D("2028-07-01"), region="BY", private_sender=True))
    assert (gym.due_date, gym.safe_date, gym.confidence) == ("2028-08-15", "2028-08-15", "high")
    assert _partial(gym, "Mariä Himmelfahrt") == [
        f"Tue 15 Aug 2028 is Mariä Himmelfahrt, {_MUNICH}this deadline does not move off it, so the safe "
        "date is a working day earlier: act a working day before it to be safe."
    ]
    assert compute_due(notice, ctx(today=D("2028-07-01"), region="NW")).warnings == []
    # a payment to a company: the payer's Land decides, and its send-by date is counted back over it
    payment = DateSpec(type="fixed", date="2025-08-18", nature="payment")
    bavaria = compute_due(payment, ctx(today=D("2025-08-01"), recipient_region="BY", private_sender=True))
    assert (bavaria.due_date, bavaria.send_by) == ("2025-08-18", "2025-08-15")
    assert _partial(bavaria, "Mariä Himmelfahrt") == [
        f"Fri 15 Aug 2025 is Mariä Himmelfahrt, {_MUNICH}the send-by or safe date, counted back over it, is "
        "a working day earlier: act a working day before it to be safe."
    ]
    augsburg = compute_due(
        payment.model_copy(update={"date": "2025-08-11"}), ctx(today=D("2025-08-01"), recipient_region="BY")
    )
    assert _partial(augsburg, "Friedensfest") == [
        "Fri 8 Aug 2025 is Augsburger Hohes Friedensfest, a public holiday only in the city of Augsburg "
        "(Bayern), which is not counted here. Where it holds, the send-by or safe date, counted back over it, "
        "is a working day earlier: act a working day before it to be safe."
    ]
    # a due date on one that moves to the next working day is only later there
    moving = DateSpec(type="fixed", date="2026-06-04", nature="objection", shift_rule="next_business_day")
    saxony = compute_due(moving, ctx(today=D("2026-05-01"), region="SN"))
    assert _partial(saxony, "Fronleichnam") == [
        "Thu 4 Jun 2026 is Fronleichnam, a public holiday only in some communities of the Sorbian area of "
        "Sachsen, which is not counted here. Where it holds, the due date moves to the next working day; the "
        "date shown is the earlier one."
    ]
    thuringia = compute_due(
        DateSpec(type="relative", anchor="document_date", amount=3, unit="days", nature="payment"),
        ctx(today=D("2026-05-01"), region="TH", document_date="2026-06-01", delivery_scope="vwvfg"),
    )
    assert thuringia.due_date == "2026-06-04" and _partial(thuringia, "Fronleichnam")
    # a date that neither moves nor has a safe date is not moved by it
    other = DateSpec(type="fixed", date="2025-08-15", nature="other")
    assert compute_due(other, ctx(today=D("2025-07-01"), region="BY")).warnings == []


def test_a_period_counted_back_over_a_partial_holiday_is_named() -> None:
    """5 working days before Wed 20 Aug 2025 is Tue 12 Aug, but Mon 11 Aug where 15 Aug is a holiday; 3
    Werktage before Tue 18 Aug 2026 pass Saturday 15 Aug, which is a Werktag only where it is no holiday."""
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date="2025-08-20",
        amount=-5,
        unit="business_days",
        nature="declaration",
    )
    receipt = compute_due(spec, ctx(today=D("2025-07-01"), region="BY"))
    assert receipt.due_date == "2025-08-12"
    assert _partial(receipt, "Mariä Himmelfahrt") == [
        f"Fri 15 Aug 2025 is Mariä Himmelfahrt, {_MUNICH}this date, counted backwards over it, is a working "
        "day earlier: act a working day before it to be safe."
    ]
    werktage = spec.model_copy(
        update={"anchor_date": "2026-08-18", "amount": -3, "unit": "werktage", "nature": "other"}
    )
    saturday = compute_due(werktage, ctx(today=D("2026-07-01"), region="BY"))
    assert saturday.due_date == "2026-08-13"
    assert _partial(saturday, "Sat 15 Aug 2026 is Mariä Himmelfahrt")
    # a count that ends on the holiday itself does not pass over it
    ends_on_it = werktage.model_copy(update={"anchor_date": "2025-08-19", "amount": -2})
    on_it = compute_due(ends_on_it, ctx(today=D("2025-07-01"), region="BY"))
    assert on_it.due_date == "2025-08-15" and not _partial(on_it, "Mariä Himmelfahrt")
    # counted back in months, no working day is skipped: nothing to name
    months = spec.model_copy(update={"amount": -1, "unit": "months", "nature": "other"})
    assert not _partial(compute_due(months, ctx(today=D("2025-06-01"), region="BY")), "Mariä Himmelfahrt")


def test_the_partial_holiday_check_stays_inside_the_calendar() -> None:
    """Counting back from 1 Jan 1 raised OverflowError in the rules tools."""
    first = compute_due(DateSpec(type="fixed", date="0001-01-01", nature="notice"), ctx(region="BY"))
    assert first.due_date == "0001-01-01"
    last = DateSpec(type="fixed", date="9999-12-31", nature="objection", shift_rule="next_business_day")
    assert compute_due(last, ctx(region="SN")).due_date == "9999-12-31"


# --------------------------------------------------------------------------------------------------
# A letter served with a Postzustellungsurkunde (RuleContext.formal_service, ingest.gaps.formally_served)
# --------------------------------------------------------------------------------------------------


def test_a_period_from_arrival_on_a_letter_served_with_a_pzu_runs_from_the_envelope_date() -> None:
    """Cited as ``pzu`` (the app asks for the date on the yellow envelope); from the letter's date until it is
    entered, then from it."""
    spec = DateSpec(type="relative", amount=1, unit="months", anchor="receipt", nature="objection")
    served = ctx(today=date(2026, 11, 25), document_date=date(2026, 11, 6), formal_service=True)
    receipt = compute_due(spec, served)
    assert "pzu" in receipt.rule_ids and receipt.due_date == "2026-12-07"
    entered = compute_due(spec, replace(served, received_date=date(2026, 11, 10), received_confirmed=True))
    assert entered.due_date == "2026-12-10" and "pzu" in entered.rule_ids


PZU_SPECS = [
    DateSpec(
        type="relative",
        amount=1,
        unit="months",
        anchor="deemed_delivery",
        delivery_rule="de_admin_post",
        shift_rule="auto",
        nature="objection",
    ),
    DateSpec(
        type="relative",
        amount=1,
        unit="months",
        anchor="document_date",
        delivery_rule="de_admin_post",
        shift_rule="auto",
        nature="objection",
    ),
]
PZU_SPEC_IDS = ["deemed", "document-date"]


def test_a_letter_served_with_a_pzu_gets_no_delivery_days() -> None:
    """Served formally, it is notified on the day it is served (§ 41 Abs. 5 VwVfG): a reading's deemed delivery
    never moves its date past the letter's own (Fri 6 Nov 2026: one month is Sun 6 Dec → Mon 7 Dec)."""

    def check(spec: DateSpec) -> None:
        served = ctx(today=date(2026, 11, 25), document_date=date(2026, 11, 6), formal_service=True)
        assert compute_due(spec, served).due_date == "2026-12-07"
        assert compute_due(spec, replace(served, formal_service=False)).due_date > "2026-12-07"

    check_rows([pytest.param(row, id=name) for row, name in zip(PZU_SPECS, PZU_SPEC_IDS, strict=True)], check)
