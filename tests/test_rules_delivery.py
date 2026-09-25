"""Deemed delivery (Bekanntgabefiktion) — worked examples from the legal research.

Research rules cited in the ids: ``ao122`` = ao_122_post_inland_4_days / ao_bekanntgabefiktion_4_tage,
``aoshift`` = ao_bekanntgabe_weekend_holiday_shift, ``abroad`` = ao_122_post_ausland_one_month,
``ao2a`` = ao_122_2a_electronic_4_days, ``elster`` = ao_122a_elster_datenabruf, ``vwvfg`` =
vwvfg_41_post_4_days_no_shift, ``ozg`` = vwvfg_electronic_abruf_ozg, ``sgbx`` =
sgbx_37_post_electronic_4_days_no_shift, ``vwzg`` = vwzg_zustellung_einschreiben_pzu, ``regime`` =
bekanntgabe_regime_selection.
"""

from __future__ import annotations

from datetime import date

import pytest

from ordnung.rules.delivery import (
    VWVFG_FOUR_DAY_FROM,
    deemed_delivery,
    fiction_days,
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


@pytest.mark.parametrize(
    ("posted", "expected"),
    [
        ("2025-02-03", "2025-02-06"),  # vwvfg verdict: BW switched to 4 days only on 7 Feb 2025
        ("2025-02-07", "2025-02-11"),
    ],
)
def test_baden_wuerttemberg_switch_date(posted: str, expected: str) -> None:
    assert deemed_delivery(D(posted), scope="vwvfg", region="BW")[0] == D(expected)


def test_schleswig_holstein_confirmed_from_june_2025() -> None:
    """vwvfg verdict: § 110 LVwG SH shows the 4th day in the text as of 10 Jun 2025."""
    assert deemed_delivery(D("2025-03-03"), scope="vwvfg", region="SH")[0] == D("2025-03-06")
    assert deemed_delivery(D("2026-09-29"), scope="vwvfg", region="SH")[0] == D("2026-10-03")
