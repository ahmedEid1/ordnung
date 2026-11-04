"""Deemed delivery (Bekanntgabefiktion) — worked examples from the legal research.

Research rules cited in the ids: ``ao122`` = ao_122_post_inland_4_days / ao_bekanntgabefiktion_4_tage,
``aoshift`` = ao_bekanntgabe_weekend_holiday_shift, ``abroad`` = ao_122_post_ausland_one_month,
``ao2a`` = ao_122_2a_electronic_4_days, ``elster`` = ao_122a_elster_datenabruf, ``vwvfg`` =
vwvfg_41_post_4_days_no_shift, ``ozg`` = vwvfg_electronic_abruf_ozg, ``sgbx`` =
sgbx_37_post_electronic_4_days_no_shift, ``vwzg`` = vwzg_zustellung_einschreiben_pzu, ``regime`` =
bekanntgabe_regime_selection.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from ordnung.models import DateSpec
from ordnung.rules.calendar_de import REGION_NAMES
from ordnung.rules.deadlines import RuleContext, compute_due
from ordnung.rules.delivery import (
    LAND_DAYS_UNCONFIRMED,
    LAND_EMAIL_UNCONFIRMED,
    MAY_BE_PUBLIC_KINDS,
    VWVFG_FOUR_DAY_FROM,
    VWVFG_OLD_PROCEDURES,
    VWVFG_THREE_DAYS,
    deemed_delivery,
    fiction_days,
    is_private_sender,
    resolve_delivery,
    scope_for_party_kind,
)

D = date.fromisoformat


@pytest.mark.parametrize(
    ("posted", "scope", "channel", "region", "expected"),
    [
        # AO: 4th day, moved off weekends and holidays (BFH IX R 68/98)
        pytest.param("2026-09-15", "ao", "post", "NW", "2026-09-21", id="hero-tax-assessment-sat-to-mon"),
        pytest.param("2026-09-29", "ao", "post", "NW", "2026-10-05", id="ao122-sat-holiday-to-mon"),
        pytest.param("2026-09-24", "ao", "post", None, "2026-09-28", id="ao122-mon-sep-28"),
        pytest.param("2026-12-22", "ao", "post", "BE", "2026-12-28", id="ao122-christmas-berlin"),
        pytest.param("2025-02-07", "ao", "post", None, "2025-02-11", id="ao122-BFH-IX-B-95-25"),
        pytest.param("2026-09-21", "ao", "post", "NW", "2026-09-25", id="ao122-fri-no-shift"),
        pytest.param("2026-10-28", "ao", "post", "SN", "2026-11-02", id="ao-einspruch-leipzig"),
        pytest.param("2026-02-27", "ao", "post", "HE", "2026-03-03", id="ao-einspruch-hessen"),
        pytest.param("2024-12-30", "ao", "post", "NW", "2025-01-02", id="ao122-transition-3-day-rule"),
        pytest.param("2025-01-02", "ao", "post", "NW", "2025-01-06", id="ao122-transition-nrw"),
        pytest.param("2025-01-02", "ao", "post", "BY", "2025-01-07", id="ao122-transition-bavaria-epiphany"),
        pytest.param("2025-12-31", "ao", "post", None, "2026-01-05", id="ao122-new-year"),
        pytest.param("2025-10-27", "ao", "post", "NI", "2025-11-03", id="aoshift-reformation-day-NI"),
        pytest.param("2025-10-27", "ao", "post", "BY", "2025-10-31", id="aoshift-no-holiday-BY"),
        pytest.param("2026-10-28", "ao", "post", "BY", "2026-11-02", id="aoshift-every-land"),
        pytest.param("2026-09-14", "ao", "post", None, "2026-09-18", id="early-receipt-irrelevant"),
        pytest.param("2026-10-16", "ao", "post", None, "2026-10-20", id="anchor-letter-date"),
        pytest.param("2026-10-19", "ao", "post", None, "2026-10-23", id="anchor-confirmed-posting"),
        pytest.param("2026-09-21", "ao", "post", None, "2026-09-25", id="regime-familienkasse-kindergeld"),
        pytest.param("2026-12-23", "ao", "electronic", None, "2026-12-28", id="ao2a-email-christmas"),
        pytest.param("2026-10-30", "ao", "electronic", None, "2026-11-03", id="ao2a-fax"),
        pytest.param("2026-04-02", "ao", "portal", None, "2026-04-07", id="elster-easter"),
        pytest.param("2026-09-25", "ao", "portal", None, "2026-09-29", id="elster-sep"),
        pytest.param("2025-12-19", "ao", "portal", None, "2025-12-23", id="elster-2025-notification"),
        pytest.param("2026-10-28", "ao", "post", "NW", "2026-11-02", id="vwzg-einschreiben-finanzamt"),
        # VwVfG: 4th day, never moved (prevailing case law)
        pytest.param("2026-09-29", "vwvfg", "post", "NW", "2026-10-03", id="vwvfg-bauamt-sat-holiday"),
        pytest.param("2026-10-27", "vwvfg", "post", "NI", "2026-10-31", id="vwvfg-hannover"),
        pytest.param("2026-12-23", "vwvfg", "post", "NW", "2026-12-27", id="vwvfg-auslaenderbehoerde"),
        pytest.param("2026-09-21", "vwvfg", "post", "NW", "2026-09-25", id="vwgo-stadt-koeln"),
        pytest.param("2026-10-30", "vwvfg", "electronic", "BE", "2026-11-03", id="ozg-federal-email"),
        pytest.param("2026-09-10", "vwvfg", "portal", "NW", "2026-09-11", id="ozg-portal-day-after-download"),
        pytest.param(
            "2026-10-28", "vwvfg", "post", "NW", "2026-11-01", id="vwzg-einschreiben-auslaenderbehoerde"
        ),
        pytest.param(
            "2026-09-21", "vwvfg", "post", "NW", "2026-09-25", id="owig-einschreiben-deemed-zustellung"
        ),
        pytest.param("2026-09-29", "vwvfg", "post", "HE", "2026-10-02", id="vwvfg-hessen-3rd-day"),
        # SGB X: 4th day, never moved (BSG B 14 AS 12/09 R)
        pytest.param("2026-09-29", "sgbx", "post", None, "2026-10-03", id="sgbx-jobcenter"),
        pytest.param("2026-12-23", "sgbx", "post", None, "2026-12-27", id="sgbx-krankenkasse-sunday"),
        pytest.param("2026-11-27", "sgbx", "post", "BE", "2026-12-01", id="sgg-krankenkasse-berlin"),
        pytest.param("2026-11-25", "sgbx", "post", None, "2026-11-29", id="sgbx-jobcenter-nov"),
        pytest.param("2026-10-29", "sgbx", "post", None, "2026-11-02", id="sgbx-drv"),
        pytest.param("2026-09-30", "sgbx", "portal", None, "2026-10-04", id="sgbx-portal-notification"),
        pytest.param("2007-09-26", "sgbx", "post", None, "2007-09-29", id="sgbx-BSG-B-14-AS-12-09-R-3-day"),
        pytest.param("2026-10-28", "sgbx", "post", None, "2026-11-01", id="klage-sgg-berlin"),
    ],
)
def test_deemed_delivery_examples(
    posted: str, scope: str, channel: str, region: str | None, expected: str
) -> None:
    day, steps = deemed_delivery(D(posted), scope=scope, channel=channel, region=region)  # type: ignore[arg-type]
    assert day == D(expected)
    assert steps[-1].date == expected


@pytest.mark.parametrize(
    ("kind", "name", "remedy_type", "remedy_text", "expected"),
    [
        # Social-benefits agencies are usually filed as a plain authority: the name decides.
        ("authority", "Jobcenter Beispielkreis", "widerspruch", None, "sgbx"),
        ("authority", "Muster-Rentenversicherung Bund", "widerspruch", None, "sgbx"),
        ("insurer", "Deutsche Rentenversicherung Westfalen", None, None, "sgbx"),
        ("other", "Agentur für Arbeit Musterstadt", None, None, "sgbx"),
        (
            "university",
            "Studierendenwerk Musterstadt – Amt für Ausbildungsförderung (BAföG)",
            None,
            None,
            "sgbx",
        ),
        (None, "Wohngeldstelle der Stadt Musterstadt", None, None, "sgbx"),
        # … or the remedy notice names the social courts.
        ("authority", "Stadt Musterstadt", "widerspruch", "Klage beim Sozialgericht Musterstadt", "sgbx"),
        ("authority", "Kreis Beispiel", "widerspruch", "Widerspruch nach § 84 SGG", "sgbx"),
        # The Familienkasse: Einspruch (child benefit under the EStG) is tax law, otherwise social law.
        ("authority", "Familienkasse Muster-Mitte", "einspruch", None, "ao"),
        ("authority", "Familienkasse Muster-Mitte", "widerspruch", None, "sgbx"),
        # Everything else keeps the kind's scope.
        (
            "authority",
            "Ausländerbehörde Musterstadt",
            "widerspruch",
            "Klage beim Verwaltungsgericht",
            "vwvfg",
        ),
        ("university", "Hochschule Musterstadt", "widerspruch", None, "vwvfg"),
        ("insurer", "Muster Haftpflicht AG", None, None, None),
        ("company", None, None, None, None),
        (None, None, None, None, None),
        # Kinds that are already specific are never overridden by a name.
        ("tax_office", "Finanzamt Musterstadt (Familienkasse)", "widerspruch", None, "ao"),
        ("health_insurer", "Musterkasse", "widerspruch", None, "sgbx"),
        ("landlord", "Wohngeld-Beratung GmbH", None, None, None),
    ],
)
def test_scope_refined_by_sender_name_and_remedy(
    kind: str | None, name: str | None, remedy_type: str | None, remedy_text: str | None, expected: str | None
) -> None:
    scope = scope_for_party_kind(kind, name=name, remedy_type=remedy_type, remedy_text=remedy_text)
    assert scope == expected


@pytest.mark.parametrize(
    ("posted", "expected"),
    [
        ("2026-09-15", "2026-10-15"),  # abroad: Austria
        ("2026-01-30", "2026-03-02"),  # abroad: France, 28 Feb (Sat) → Mon 2 Mar
    ],
)
def test_ao_abroad_one_month(posted: str, expected: str) -> None:
    day, steps = deemed_delivery(D(posted), scope="ao", abroad=True)
    assert day == D(expected)
    assert steps[0].rule_id == "ao_122_2_2"


def test_abroad_only_changes_tax_letters() -> None:
    day, _ = deemed_delivery(D("2026-09-15"), scope="sgbx", abroad=True)
    assert day == D("2026-09-19")


def test_vwvfg_day_is_not_moved_and_says_so() -> None:
    result = resolve_delivery(D("2026-09-29"), scope="vwvfg", region="NW")
    assert result.day == result.raw_day == D("2026-10-03")
    assert "does not move" in result.steps[-1].label
    assert result.uncertainty is None


def test_ao_shift_step_cites_bfh() -> None:
    result = resolve_delivery(D("2026-09-15"), scope="ao", region="NW")
    assert [s.rule_id for s in result.steps] == ["ao_122_2_1", "ao_fiction_shift"]
    assert result.raw_day == D("2026-09-19")
    assert "Saturday" in result.steps[-1].label


def test_unknown_scope_uses_earliest_plausible_day() -> None:
    # Unknown Land and unknown procedural law: 3rd day, never moved (SPEC § 21).
    result = resolve_delivery(D("2026-09-29"), scope=None, region=None)
    assert result.day == D("2026-10-02")
    assert result.uncertainty
    assert result.steps[0].rule_id == "vwvfg_land_days"
    # Known 4-day Land: 4th day, not moved.
    result = resolve_delivery(D("2026-09-29"), scope=None, region="NW")
    assert result.day == D("2026-10-03")
    assert result.steps[0].rule_id == "delivery_scope_unknown"
    assert "letters from this kind of sender" in result.steps[-1].label


def test_vwvfg_unknown_land_uses_3rd_day_but_not_before_2025_rule() -> None:
    assert resolve_delivery(D("2026-09-29"), scope="vwvfg", region=None).day == D("2026-10-02")
    # Before 2025 every scope used 3 days anyway.
    assert resolve_delivery(D("2024-12-30"), scope="vwvfg", region=None).uncertainty is None


def test_fiction_days_and_scope_mapping() -> None:
    assert fiction_days(D("2024-12-31")) == 3
    assert fiction_days(D("2025-01-01")) == 4
    assert scope_for_party_kind("tax_office") == "ao"
    assert scope_for_party_kind("health_insurer") == "sgbx"
    assert scope_for_party_kind("immigration_office") == "vwvfg"
    assert scope_for_party_kind("authority") == "vwvfg"
    assert scope_for_party_kind("gym") is None
    assert scope_for_party_kind(None) is None
    assert {"NW", "BY", "BE"} <= set(VWVFG_FOUR_DAY_FROM)
    assert "HE" not in VWVFG_FOUR_DAY_FROM


#: Each Land's own delivery day for its authorities' letters (checked against the Länder gazettes on 4 Nov 2026,
#: docs/deadline-rules.md § 5): (Land, posted, channel, day, rule id of the delivery step, warning — or words it
#: holds).
_LAND_DAYS: list[tuple[str | None, str, str, str, str, str | tuple[str, ...] | None]] = [
    # Thüringen: the federal VwVfG by reference (§ 1 ThürVwVfG), the 4th day from 1 January 2025
    ("TH", "2024-12-31", "post", "2025-01-03", "vwvfg_41_2", None),
    ("TH", "2025-01-01", "post", "2025-01-05", "vwvfg_41_2", None),
    ("TH", "2025-01-02", "post", "2025-01-06", "vwvfg_41_2", None),
    ("TH", "2026-09-29", "post", "2026-10-03", "vwvfg_41_2", None),  # a Saturday, not moved
    ("TH", "2026-10-30", "electronic", "2026-11-03", "vwvfg_41_2", None),
    # Schleswig-Holstein: § 110 Abs. 2 LVwG, the 4th day from 1 January 2025
    ("SH", "2024-12-31", "post", "2025-01-03", "vwvfg_41_2", None),
    ("SH", "2025-01-02", "post", "2025-01-06", "vwvfg_41_2", None),
    ("SH", "2025-03-03", "post", "2025-03-07", "vwvfg_41_2", None),
    ("SH", "2025-06-09", "post", "2025-06-13", "vwvfg_41_2", None),
    ("SH", "2025-06-10", "post", "2025-06-14", "vwvfg_41_2", None),
    # Hessen keeps the 3rd day (§ 41 Abs. 2 HVwVfG): its law, not a doubt
    ("HE", "2024-12-30", "post", "2025-01-02", "vwvfg_41_2", None),
    ("HE", "2025-01-02", "post", "2025-01-05", "vwvfg_land_days", None),
    ("HE", "2026-09-29", "post", "2026-10-02", "vwvfg_land_days", None),
    ("HE", "2026-10-30", "electronic", "2026-11-02", "vwvfg_land_days", None),
    # Hamburg: the 3rd day until the law of 5 May 2025 took effect the day after its gazette (Art. 54 HV)
    ("HH", "2025-01-02", "post", "2025-01-05", "vwvfg_land_days", None),
    ("HH", "2025-03-03", "post", "2025-03-06", "vwvfg_land_days", None),
    ("HH", "2025-05-13", "post", "2025-05-16", "vwvfg_land_days", None),
    ("HH", "2025-05-14", "post", "2025-05-18", "vwvfg_41_2", None),
    # Baden-Württemberg switched to the 4th day only on 7 February 2025
    ("BW", "2025-02-03", "post", "2025-02-06", "vwvfg_land_days", None),
    ("BW", "2025-02-06", "post", "2025-02-09", "vwvfg_land_days", None),
    ("BW", "2025-02-07", "post", "2025-02-11", "vwvfg_41_2", None),
    # Bremen and the Saarland (no text could be checked), or no Land: the earlier 3rd day, with the warning
    ("HB", "2026-09-29", "post", "2026-10-02", "vwvfg_land_days", LAND_DAYS_UNCONFIRMED),
    ("SL", "2026-09-29", "post", "2026-10-02", "vwvfg_land_days", LAND_DAYS_UNCONFIRMED),
    (None, "2026-09-29", "post", "2026-10-02", "vwvfg_land_days", LAND_DAYS_UNCONFIRMED),
    ("BE", "2026-10-30", "electronic", "2026-11-03", "vwvfg_41_2", None),
    # Brandenburg: an e-mailed decision counts from the day it arrived (§ 7 VwVfGBbg) — at the earliest the day sent
    ("BB", "2026-10-30", "electronic", "2026-10-30", "vwvfg_bb_7", ("§ 7 VwVfGBbg", "up to 4 days")),
    ("BB", "2024-12-20", "electronic", "2024-12-20", "vwvfg_bb_7", ("§ 7 VwVfGBbg", "up to 3 days")),
    ("BB", "2026-10-30", "post", "2026-11-03", "vwvfg_41_2", None),
    ("BB", "2026-10-30", "portal", "2026-10-31", "vwvfg_41_2a", None),
    # an e-mailed decision whose sender's Land isn't known may be Brandenburg's: from the day it was sent
    (None, "2026-10-30", "electronic", "2026-10-30", "vwvfg_bb_7", LAND_EMAIL_UNCONFIRMED),
]


@pytest.mark.parametrize(
    ("region", "posted", "channel", "expected", "rule_id", "warning"),
    _LAND_DAYS,
    ids=[f"{row[0]}-{row[1]}-{row[2]}" for row in _LAND_DAYS],
)
def test_the_lands_own_delivery_day(
    region: str | None,
    posted: str,
    channel: str,
    expected: str,
    rule_id: str,
    warning: str | tuple[str, ...] | None,
) -> None:
    result = resolve_delivery(D(posted), scope="vwvfg", channel=channel, region=region)  # type: ignore[arg-type]
    assert result.day == D(expected)
    assert result.steps[0].rule_id == rule_id
    if isinstance(warning, tuple):
        assert result.uncertainty is not None and all(words in result.uncertainty for words in warning)
    else:
        assert result.uncertainty == warning


def test_brandenburg_email_counts_from_a_confirmed_arrival_before_the_4th_day() -> None:
    """§ 7 VwVfGBbg: the 4th day does not hold when the decision provably arrived earlier — a later arrival is the
    late-arrival note's (§ 41 Abs. 2 S. 3 VwVfG)."""
    sent = D("2026-10-30")
    arrived = resolve_delivery(
        sent, scope="vwvfg", channel="electronic", region="BB", arrived=D("2026-11-02")
    )
    assert (arrived.day, arrived.steps[0].rule_id, arrived.uncertainty) == (
        D("2026-11-02"),
        "vwvfg_bb_7",
        None,
    )
    assert (
        arrived.steps[0].label == "Counts as delivered on the day it arrived (§ 7 VwVfGBbg): Mon 2 Nov 2026"
    )
    late = resolve_delivery(sent, scope="vwvfg", channel="electronic", region="BB", arrived=D("2026-11-05"))
    assert (late.day, late.steps[0].rule_id, late.uncertainty) == (D("2026-11-03"), "vwvfg_41_2", None)
    # without the sender's Land: from the day it arrived too, which may be Brandenburg's rule
    unknown = resolve_delivery(sent, scope=None, channel="electronic", region=None, arrived=D("2026-11-01"))
    assert (unknown.day, unknown.uncertainty) == (D("2026-11-01"), LAND_EMAIL_UNCONFIRMED)
    assert unknown.steps[0].label == (
        "Counted from the day you said it arrived (in Brandenburg an e-mailed decision counts from that day): "
        "Sun 1 Nov 2026"
    )
    sent_only = resolve_delivery(sent, scope="vwvfg", channel="electronic", region=None)
    assert sent_only.steps[0].label == (
        "Counted from the day it was sent (in Brandenburg an e-mailed decision counts from the day it arrived): "
        "Fri 30 Oct 2026"
    )
    # an arrival day before the day it was sent is no arrival: from the day it was sent
    early = resolve_delivery(sent, scope="vwvfg", channel="electronic", region="BB", arrived=D("2026-10-29"))
    assert early.day == sent and early.steps[0].label.endswith(
        "— at the earliest the day it was sent: Fri 30 Oct 2026"
    )


def test_the_land_tables() -> None:
    """Every Land is in one table: the 4th day from its switch, the 3rd by its own law, or not confirmed."""
    assert VWVFG_FOUR_DAY_FROM["TH"] == VWVFG_FOUR_DAY_FROM["SH"] == date(2025, 1, 1)
    assert VWVFG_THREE_DAYS == frozenset({"HE"})
    assert not VWVFG_THREE_DAYS & set(VWVFG_FOUR_DAY_FROM)
    assert set(VWVFG_FOUR_DAY_FROM) | VWVFG_THREE_DAYS | {"HB", "SL"} == set(REGION_NAMES)


def test_the_web_app_counts_four_days_in_the_same_lands() -> None:
    """The sender's-state question asks about a Land authority's 3-day date only where confirming it counts 4
    (``web/src/features/party/sender-land.ts``): the same Länder as the engine's."""
    source = Path(__file__).resolve().parents[1] / "web" / "src" / "features" / "party" / "sender-land.ts"
    found = re.search(r"FOUR_DAY_LANDS\b[^=]*=\s*new Set\(\[([^\]]*)\]\)", source.read_text("utf-8"))
    assert found is not None
    assert set(re.findall(r'"([A-Z]{2})"', found.group(1))) == set(VWVFG_FOUR_DAY_FROM)


def test_the_web_app_matches_the_engines_warnings() -> None:
    """The web app knows a date waits for the sender's Land by words of the engine's warnings
    (``LAND_UNKNOWN`` in ``web/src/features/document/WhyThisDate.tsx``): they must be the engine's words."""
    source = Path(__file__).resolve().parents[1] / "web" / "src" / "features" / "document" / "WhyThisDate.tsx"
    found = re.search(r"export const LAND_UNKNOWN = \{(.*?)\} as const", source.read_text("utf-8"), re.S)
    assert found is not None
    words = dict(re.findall(r'(\w+): "([^"]*)"', found.group(1)))
    assert words["threeDays"] in LAND_DAYS_UNCONFIRMED
    assert words["email"] in LAND_EMAIL_UNCONFIRMED


_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip


@pytest.mark.parametrize(
    ("region", "posted", "scope", "older"),
    [
        ("MV", "2025-12-09", "vwvfg", ("MV", "2025-12-12")),
        ("MV", "2025-12-09", None, ("MV", "2025-12-12")),
        ("BW", "2025-02-07", "vwvfg", ("BW", "2025-02-10")),
        ("BY", "2025-12-09", "vwvfg", ("BY", "2025-12-12")),
        ("BY", "2026-10-30", None, ("BY", "2026-11-02")),
        # before the switch the old law counts the 3rd day anyway; elsewhere no older matter keeps it
        ("BW", "2025-02-06", "vwvfg", None),
        ("MV", "2024-12-31", "vwvfg", None),
        ("BY", "2024-12-31", "vwvfg", None),
        ("HE", "2025-12-09", "vwvfg", None),
        ("NW", "2025-12-09", "vwvfg", None),
        (None, "2025-12-09", "vwvfg", None),
        ("MV", "2025-12-09", "sgbx", None),
    ],
)
def test_an_older_matter_is_marked_after_the_switch(
    region: str | None, posted: str, scope: str | None, older: tuple[str, str] | None
) -> None:
    """Baden-Württemberg, Bavaria and Mecklenburg-Vorpommern keep the old 3rd day for a matter begun before their
    switch (§ 102b LVwVfG, Art. 98 BayVwVfG, § 120a VwVfG M-V): the 4th day counts, and the older matter's day is
    kept for the deadline's note."""
    result = resolve_delivery(D(posted), scope=scope, region=region)  # type: ignore[arg-type]
    assert result.older_matter == (None if older is None else (older[0], D(older[1])))
    if region in VWVFG_OLD_PROCEDURES and older is not None:
        assert result.day == D(posted) + timedelta(days=4)
        assert result.uncertainty is None


def test_the_older_matter_table_names_each_lands_switch() -> None:
    assert set(VWVFG_OLD_PROCEDURES) == {"BW", "BY", "MV"}
    for land, (_, switch) in VWVFG_OLD_PROCEDURES.items():
        day = VWVFG_FOUR_DAY_FROM[land]
        assert switch == f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def test_delivery_notes_are_not_read_as_doubts_scams_or_injections() -> None:
    """The benchmark reads a warning naming a conflict or an unknown as the letter's own doubt about its date, one
    naming a scam as a false alarm and one naming an AI as an injection flagged: a delivery note says none of them."""
    from evals.metrics import INJECTION_RE, SCAM_RE, UNCERTAINTY_RE

    spec = DateSpec(
        type="relative",
        anchor="deemed_delivery",
        amount=1,
        unit="months",
        delivery_rule="de_admin_post",
        nature="objection",
        legal_basis="§ 70 VwGO",
    )
    notes = [LAND_DAYS_UNCONFIRMED]
    for land in ("BW", "BY", "MV"):
        context = RuleContext(
            today=D("2025-12-01"), region=land, document_date=D("2025-12-09"), delivery_scope="vwvfg"
        )
        found = [
            w
            for w in compute_due(spec, context).warnings
            if w.startswith(f"In {REGION_NAMES[land]} a matter")
        ]
        assert len(found) == 1, land
        notes += found
    notes.append(
        resolve_delivery(D("2026-10-30"), scope="vwvfg", channel="electronic", region="BB").uncertainty or ""
    )
    notes.append(LAND_EMAIL_UNCONFIRMED)
    for note in notes:
        assert note
        for pattern in (UNCERTAINTY_RE, INJECTION_RE, SCAM_RE):
            assert not pattern.search(note), (pattern.pattern[:30], note)


#: A statutory health insurer's remedy notice (§ 37 SGB X, § 84 SGG): an administrative act.
_BESCHEID = "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden."


@pytest.mark.parametrize(
    ("kind", "name", "remedy_type", "notice", "expected"),
    [
        ("company", None, None, None, True),
        ("landlord", "Muster Wohnen GmbH", "none", None, True),
        ("insurer", "Muster Haftpflicht AG", None, None, True),
        # "other" is the app's "don't know", not "no authority"; nor is a missing kind
        ("other", "Stadt Musterstadt", None, None, False),
        (None, None, None, None, False),
        # an authority's decision whatever it was filed as: its remedy notice says so ...
        ("insurer", "AOK Nordost", "widerspruch", _BESCHEID, False),
        ("company", None, "einspruch", "Gegen diesen Bescheid ist der Einspruch gegeben.", False),
        ("company", None, "einspruch", "Einspruch beim Finanzamt, § 347 AO", False),
        ("company", "Familienkasse Muster-Mitte", "einspruch", None, False),  # tax law by its name
        ("employer", "Land Berlin", "klage", "Klage beim Verwaltungsgericht Berlin (§ 74 VwGO)", False),
        ("company", None, "klage", "Klage vor dem Finanzgericht", False),
        ("company", None, "widerspruch", "nach Zustellung des Widerspruchsbescheids", False),
        # ... but Widerspruch and Klage are private-law remedies too: a dismissal, a tenancy, an insurance
        ("employer", "Land Berlin", "klage", None, True),
        ("employer", "Muster GmbH", "klage", "Kündigungsschutzklage beim Arbeitsgericht (§ 4 KSchG)", True),
        ("landlord", None, "widerspruch", "Widerspruch nach § 574 BGB bis zwei Monate vor Ende", True),
        (
            "insurer",
            "Muster Leben AG",
            "widerspruch",
            "innerhalb eines Monats nach Zugang widersprechen (§ 5 VVG)",
            True,
        ),
        # a court's Mahnbescheid is served formally: from its delivery, not a deemed one
        (
            "company",
            "Inkasso GmbH",
            "widerspruch",
            "Widerspruch gegen den Mahnbescheid binnen zwei Wochen",
            True,
        ),
        ("company", None, "widerspruch", "Widerspruch gegen den Vollstreckungsbescheid", True),
        ("company", None, "einspruch", "Einspruch gegen den Vollstreckungsbescheid (§ 700 ZPO)", True),
        # ... and firms call their own complaint window an "Einspruch": a sender filed as private that
        # names one without an administrative route is in doubt, and arrival is the earlier start
        ("company", None, "einspruch", None, True),
        (
            "company",
            "Park & Control GmbH",
            "einspruch",
            "Gegen diese Vertragsstrafe können Sie innerhalb von 14 Tagen Einspruch einlegen.",
            True,
        ),
        # ... in everyday German: "Bescheid geben / sagen" is "let us know", "bekanntgegeben" "announced"
        (
            "company",
            "Park & Control GmbH",
            "einspruch",
            "Wenn Sie Einspruch einlegen möchten, geben Sie uns innerhalb von 14 Tagen nach Zugang Bescheid.",
            True,
        ),
        (
            "company",
            None,
            "einspruch",
            "Wie bereits bekanntgegeben, ist ein Einspruch binnen 14 Tagen möglich.",
            True,
        ),
        ("landlord", None, "widerspruch", "Sagen Sie ihr Bescheid, wenn Sie widersprechen wollen.", True),
        ("company", None, "einspruch", "Einspruch gegen die bescheidene Bearbeitungsgebühr", True),
        # ... while a Bescheid as the decision it is shows an administrative act
        ("utility", "Stadtentwässerung", "widerspruch", "Widerspruch gegen den Gebührenbescheid", False),
        ("company", None, "widerspruch", "Widerspruch gegen den Bescheid vom 1. September", False),
        ("company", None, "klage", "Klage gegen Ihren Bescheid", False),
        # ... or its name makes it a social agency
        ("insurer", "Deutsche Rentenversicherung Bund", None, None, False),
        ("authority", None, None, None, False),
        ("tax_office", None, None, None, False),
    ],
)
def test_private_senders_have_no_deemed_delivery(
    kind: str | None, name: str | None, remedy_type: str | None, notice: str | None, expected: bool
) -> None:
    scope = scope_for_party_kind(kind, name=name, remedy_type=remedy_type, remedy_text=notice)
    assert is_private_sender(kind, scope=scope, remedy_type=remedy_type, remedy_text=notice) is expected


@pytest.mark.parametrize(
    "name",
    [
        "AOK Nordwest – Die Gesundheitskasse",
        "BARMER",
        "DAK-Gesundheit",
        "IKK classic",
        "BKK firmus",
        "Audi BKK",
        "Knappschaft",
        "KKH",
        "hkk",
        "Verband der Ersatzkassen",
        "SVLFG",
        "Die Techniker",
        "TK",
        "Techniker Krankenkasse (TK)",
        "VIACTIV Krankenkasse",
        "Viactiv",
        "BIG direkt gesund",
        "HEK",
        "Hanseatische Krankenkasse (HEK)",
        "SBK",
        "mhplus",
    ],
)
def test_statutory_health_insurers_by_their_brand_are_social_law(name: str) -> None:
    """Statutory health insurers go by names without "Krankenkasse"; filed as an
    ``insurer`` they were private, and a late arrival moved their Bescheid's deadline later."""
    scope = scope_for_party_kind("insurer", name=name)
    assert scope == "sgbx" and is_private_sender("insurer", scope=scope) is False


@pytest.mark.parametrize(
    "name",
    [
        "Allianz Versicherungs-AG",
        "HUK-COBURG",
        "Barmenia Krankenversicherung AG",
        # short brands other firms share count only as the whole name or in brackets
        "TK Maxx",
        "TK Elevator GmbH",
        "SBK Immobilien GmbH",
        "Stark TK Bau",
        "Big Direktvertrieb GmbH",
    ],
)
def test_private_insurers_stay_private(name: str) -> None:
    for kind in ("insurer", "company"):
        scope = scope_for_party_kind(kind, name=name)
        assert scope is None and is_private_sender(kind, scope=scope) is True


def test_the_administrative_route_needs_the_codes_written_as_codes() -> None:
    """ "AO" is the Abgabenordnung only in capitals: the word "ao" in other text is no route."""
    route = is_private_sender("company", scope=None, remedy_type="klage", remedy_text="Klage nach § 40 AO")
    assert route is False
    assert is_private_sender("company", scope=None, remedy_type="klage", remedy_text="ciao ao") is True


def test_the_document_page_knows_which_kinds_may_be_public() -> None:
    """The arrival question (``web/src/features/document/verdict.ts``) says a late arrival may not move
    the date for the kinds a public body may be filed as: the same kinds as the engine's."""
    verdict = Path(__file__).resolve().parents[1] / "web" / "src" / "features" / "document" / "verdict.ts"
    found = re.search(
        r"MAY_BE_PUBLIC_KINDS: readonly PartyKind\[\] = \[([^\]]*)\]", verdict.read_text("utf-8")
    )
    assert found is not None
    assert set(re.findall(r'"([a-z_]+)"', found.group(1))) == MAY_BE_PUBLIC_KINDS
