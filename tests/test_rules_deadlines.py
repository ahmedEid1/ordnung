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

from datetime import date
from typing import Any

import pytest

from ordnung.models import DateSpec
from ordnung.rules.deadlines import (
    ASSUMED_RECEIPT_WARNING,
    PRIVATE_SENDER_WARNING,
    RuleContext,
    compute_due,
    compute_one_year_fallback,
    from_arrival,
    parse_date,
    statute_rule,
)

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


@pytest.mark.parametrize(
    ("doc", "scope", "region", "basis", "expected"),
    [o[1:] for o in OBJECTIONS],
    ids=[o[0] for o in OBJECTIONS],
)
def test_objection_deadlines(doc: str, scope: str, region: str, basis: str, expected: str) -> None:
    context = ctx(region=region, recipient_region=region, document_date=doc, delivery_scope=scope)
    receipt = compute_due(notice_spec(legal_basis=basis), context)
    assert receipt.due_date == expected
    # Hessen may still use the 3-day rule (unverified), which is flagged; court actions (Klage) carry a
    # "get advice" warning (SPEC § 21, audit B4); everything else is certain.
    uncertain = (region == "HE" and scope == "vwvfg") or "klage_1_month" in receipt.rule_ids
    assert receipt.confidence == ("medium" if uncertain else "high"), receipt.warnings


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


def test_hessen_three_day_rule_is_flagged() -> None:
    receipt = compute_due(
        notice_spec(legal_basis="§ 70 VwGO"),
        ctx(region="HE", document_date="2026-09-29", delivery_scope="vwvfg"),
    )
    assert receipt.due_date == "2026-11-02"
    assert receipt.confidence == "medium"
    assert "vwvfg_land_days" in receipt.rule_ids


@pytest.mark.parametrize(
    ("event", "amount", "unit", "region", "basis", "expected"),
    [
        pytest.param(
            "2026-09-07", 1, "months", "NW", "§ 355 AO", "2026-10-07", id="fristbeginn-bekanntgabe-mon"
        ),
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
        pytest.param(
            "2026-10-17", 2, "weeks", "NI", "§ 410 StPO", "2026-11-02", id="stpo410-hannover-saturday"
        ),
        pytest.param(
            "2026-12-18", 2, "weeks", "HH", "§ 410 StPO", "2027-01-04", id="stpo410-hamburg-new-year"
        ),
        pytest.param("2026-09-28", 2, "weeks", "NW", None, "2026-10-12", id="authority-two-weeks-hearing"),
        pytest.param("2026-10-17", 14, "days", "NW", None, "2026-11-02", id="widerruf-193-applies"),
        pytest.param("2026-09-21", 10, "days", "NW", None, "2026-10-01", id="fristende-10-days"),
    ],
)
def test_explicit_event_deadlines(
    event: str, amount: int, unit: str, region: str, basis: str | None, expected: str
) -> None:
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


@pytest.mark.parametrize(
    ("doc", "received", "scope", "expected", "alternative"),
    [
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
    ],
)
def test_late_receipt_keeps_safe_date_and_notes_alternative(
    doc: str, received: str, scope: str, expected: str, alternative: str
) -> None:
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


def test_later_posting_date_is_only_a_note() -> None:
    """anchor: the letter says it was posted Mon 19 Oct (dated Fri 16 Oct). Research: Fri 23 Oct → Mon 23 Nov;
    the verdict keeps the letter's date as the primary (earlier) posting day and notes the later one."""
    receipt = compute_due(
        notice_spec(anchor_date="2026-10-19", legal_basis="§ 355 AO"),
        ctx(region="NW", document_date="2026-10-16", delivery_scope="ao"),
    )
    assert receipt.due_date == "2026-11-20"
    assert any("Mon 19 Oct 2026 as the posting day" in w for w in receipt.warnings)
    assert receipt.confidence == "high"


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


def test_electronic_delivery_rule() -> None:
    """ao2a: Einspruchsentscheidung e-mailed Wed 23 Dec 2026 → Mon 28 Dec → Klage Thu 28 Jan 2027."""
    receipt = compute_due(
        notice_spec(delivery_rule="de_admin_electronic", legal_basis="§ 47 FGO"),
        ctx(document_date="2026-12-23", delivery_scope="ao", region="NW"),
    )
    assert receipt.due_date == "2027-01-28"
    assert "ao_122_2a" in receipt.rule_ids


def test_elster_and_federal_email_examples() -> None:
    # elster: made available Fri 25 Sep 2026 → Tue 29 Sep → Thu 29 Oct; Thu 2 Apr 2026 → Tue 7 Apr → Thu 7 May
    for doc, expected in (("2026-09-25", "2026-10-29"), ("2026-04-02", "2026-05-07")):
        receipt = compute_due(
            notice_spec(delivery_rule="de_admin_electronic", legal_basis="§ 355 AO"),
            ctx(document_date=doc, delivery_scope="ao", region="NW", today=D("2026-04-01")),
        )
        assert receipt.due_date == expected
    # ozg: federal authority e-mails Fri 30 Oct 2026 → Tue 3 Nov → Thu 3 Dec
    receipt = compute_due(
        notice_spec(delivery_rule="de_admin_electronic", legal_basis="§ 70 VwGO"),
        ctx(document_date="2026-10-30", delivery_scope="vwvfg", region="BE"),
    )
    assert receipt.due_date == "2026-12-03"


def test_receipt_anchor_confirmed() -> None:
    spec = DateSpec(type="relative", anchor="receipt", amount=14, unit="days", nature="payment")
    receipt = compute_due(
        spec,
        ctx(region="NW", document_date="2026-09-10", received_date="2026-09-14", received_confirmed=True),
    )
    assert receipt.due_date == "2026-09-28"
    assert receipt.confidence == "high"
    assert receipt.summary == "14 days after the day you received it (Mon 14 Sep 2026) is Mon 28 Sep 2026."


def test_receipt_anchor_unconfirmed_falls_back_to_document_date() -> None:
    spec = DateSpec(type="relative", anchor="receipt", amount=14, unit="days", nature="payment")
    receipt = compute_due(spec, ctx(region="NW", document_date="2026-09-10", received_date="2026-09-14"))
    assert receipt.due_date == "2026-09-24"
    assert receipt.confidence == "low"
    assert ASSUMED_RECEIPT_WARNING in receipt.warnings


def test_receipt_anchor_without_any_date() -> None:
    spec = DateSpec(type="relative", anchor="receipt", amount=14, unit="days", nature="payment")
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.due_date is None
    assert receipt.confidence == "low"


@pytest.mark.parametrize(
    ("spec", "context"),
    [
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
    ],
    ids=[
        "no-document-date",
        "no-posting-date",
        "unreadable-anchor",
        "no-anchor-no-date",
        "no-amount",
        "bad-fixed-date",
    ],
)
def test_missing_inputs_give_no_date_and_low_confidence(spec: DateSpec, context: dict[str, Any]) -> None:
    receipt = compute_due(spec, ctx(**context))
    assert receipt.due_date is None
    assert receipt.confidence == "low"
    assert receipt.warnings
    assert receipt.summary.startswith("No date could be computed")


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


def test_statute_mismatch_keeps_shorter_letter_period() -> None:
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


@pytest.mark.parametrize(
    ("text", "rule"),
    [
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
    ],
)
def test_statute_recognition(text: str, rule: str | None) -> None:
    assert statute_rule(DateSpec(type="relative", legal_basis=text)) == rule


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
    """authority: summons for Sat 10 Oct 2026 10:00 stays on Saturday."""
    spec = DateSpec(
        type="fixed", date="2026-10-10", time="10:00", nature="appointment", shift_rule="next_business_day"
    )
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.due_date == "2026-10-10"
    assert receipt.send_by is None
    assert "authority_deadline" in receipt.rule_ids


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


def test_notice_never_shifts_even_if_asked() -> None:
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


def test_send_by_none_when_date_has_passed() -> None:
    spec = DateSpec(type="fixed", date="2026-09-01", nature="payment")
    receipt = compute_due(spec, ctx(region="NW"))
    assert receipt.send_by is None
    assert any("has already passed" in w for w in receipt.warnings)


def test_custom_postal_buffer() -> None:
    spec = DateSpec(type="fixed", date="2026-10-21", nature="objection")
    assert compute_due(spec, ctx(region="NW"), postal_buffer_days=2).send_by == "2026-10-19"


# ------------------------------------------------------------------------- one-year fallback


@pytest.mark.parametrize(
    ("event", "region", "expected"),
    [
        pytest.param("2025-10-07", "NW", "2026-10-07", id="rbb-steuerbescheid"),
        pytest.param("2025-10-31", "SN", "2026-11-02", id="rbb-leipzig-saturday"),
        pytest.param("2024-02-29", "NW", "2025-02-28", id="rbb-leap-day"),
        pytest.param("2025-10-03", "NW", "2026-10-05", id="rbb-vwvfg-holiday-fiction"),
    ],
)
def test_one_year_fallback(event: str, region: str, expected: str) -> None:
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


def test_a_private_sender_drops_a_delivery_rule_on_the_letters_date() -> None:
    spec = notice_spec(anchor="document_date", amount=14, unit="days", nature="payment")
    receipt = compute_due(spec, ctx(document_date="2026-09-01", private_sender=True))
    assert receipt.due_date == "2026-09-15" and PRIVATE_SENDER_WARNING in receipt.warnings
    assert receipt.confidence == "high"  # the letter's own date, nothing assumed


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
    "a public holiday only in the communities of Bayern with a Catholic majority (Munich among them), which "
    "is not counted here. Where it holds, "
)


def _partial(receipt: Any, name: str) -> list[str]:
    return [w for w in receipt.warnings if name in w]


def test_a_partial_holiday_a_date_is_counted_back_over_is_named_in_the_app_too() -> None:
    """Reviewer repro: a gym's notice deadline on Tue 15 Aug 2028 in Bavaria. The calendar counts only a
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
    """Reviewer repro: counting back from 1 Jan 1 raised OverflowError in the rules tools."""
    first = compute_due(DateSpec(type="fixed", date="0001-01-01", nature="notice"), ctx(region="BY"))
    assert first.due_date == "0001-01-01"
    last = DateSpec(type="fixed", date="9999-12-31", nature="objection", shift_rule="next_business_day")
    assert compute_due(last, ctx(region="SN")).due_date == "9999-12-31"
