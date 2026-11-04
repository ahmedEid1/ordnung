"""The generator's own Länder table (``evals/gen/law.py``): the day a posted decision of a Land authority counts as
delivered, as each Land's text in ``evals/law/laender.txt`` gives it.

The table is the generator's, written from those texts. These tests read each Land's block and hold the table to
it: the day count (the 3rd or the 4th day after posting), the day the 4th day starts, the Länder that keep the 3rd
day for a procedure begun before their switch, and the Länder with no text, from which no letter may come. They
also check what ``deemed_delivery`` does with each, that tax and social-law decisions are untouched, and that
the label check's own table (``evals/verify_labels.py``, separate code) gives the same days.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from evals import verify_labels as vl
from evals.gen import law
from evals.gen.common import objection_item

ROOT = Path(__file__).resolve().parents[1]
LAENDER_TXT = ROOT / "evals" / "law" / "laender.txt"
VWVFG_TXT = ROOT / "evals" / "law" / "vwvfg.txt"
NOT_RETRIEVED_LINE = "Not retrieved (see SOURCES.md)."
CODE = {name: code for code, name in law.LAND_NAMES.items()}
MONTHS = ("Januar Februar März April Mai Juni Juli August September Oktober November Dezember").split()
DATE = rf"\d{{1,2}}\. (?:{'|'.join(MONTHS)}) \d{{4}}"

#: The 4th day after posting, as a Land's own § 41 says it or as the amendment that put it there says it.
OWN_FOURTH = re.compile(
    r"am vierten Tag nach der Aufgabe zur Post"
    r"|„am dritten Tag“ durch die Wörter „am vierten Tag“"
    r"|das Wort „dritten“ durch das Wort „vierten“"
)
OWN_THIRD = "am dritten Tag nach der Aufgabe zur Post"
#: An act that applies the federal Verwaltungsverfahrensgesetz instead of a § 41 of its own, and its exceptions.
APPLIES_FEDERAL = re.compile(
    r"(?:gilt|gelten) (?:dieses Gesetz und )?(?:die Vorschriften )?(?:das|des) Verwaltungsverfahrensgesetz"
    r"[^.]*?(?:mit Ausnahme der (?P<except>[^.]*?(?:VwVfG|Verwaltungsverfahrensgesetzes|101)))?"
)
#: A provision that keeps the old wording of the act for a procedure begun before the switch.
OLD_LAW_KEPT = re.compile(
    rf"Auf alle vor dem (?P<day>{DATE}) begonnenen, aber nicht abgeschlossenen Verwaltungsverfahren sind dieses "
    r"Gesetz in der bis zu"
)
#: Where a block names the day its Land's 4th day starts: a pattern with one German date, and the days to add to it.
START: dict[str, tuple[str, int]] = {
    "BW": (rf"§ 102b [^\n]*\n\nAuf alle vor dem ({DATE}) begonnenen", 0),
    "BY": (rf"Art\. 98 [^\n]*\n\nAuf alle vor dem ({DATE}) begonnenen", 0),
    # Art. 54 of the constitution: in force on the day after the gazette's issue
    "HH": (rf"HmbGVBl\. Nr\. 17, \w+, den ({DATE})", 1),
    "MV": (
        rf"Artikel 4 Inkrafttreten\n\n\(1\) Dieses Gesetz tritt vorbehaltlich des Absatzes 2 am ({DATE}) in Kraft",
        0,
    ),
    "NW": (rf"§ 41 zuletzt geändert [^\n]* in Kraft getreten am ({DATE})\.", 0),
    "SH": (rf"Artikel 1 Nummer 2 tritt am ({DATE}) in Kraft", 0),
    "TH": (rf"Artikel 90 [^\n]*\n\n\(1\) Dieses Gesetz tritt am ({DATE}) in Kraft", 0),
}
#: The day the federal § 41 Abs. 2 VwVfG counts the 4th day from, as the generator has it.
FEDERAL_START = law.OLD_FICTION_LAST_DAY + timedelta(days=1)


def german_date(text: str) -> date:
    day, month, year = text.split()
    return date(int(year), MONTHS.index(month) + 1, int(day.rstrip(".")))


def blocks() -> dict[str, str]:
    """laender.txt by Land code: a block runs from a line naming a Land, after a blank line, to the next one."""
    lines = LAENDER_TXT.read_text(encoding="utf-8").split("\n")
    starts = [i for i, line in enumerate(lines) if line in CODE and i > 0 and lines[i - 1] == ""]
    out = {}
    for n, start in enumerate(starts):
        end = starts[n + 1] - 1 if n + 1 < len(starts) else len(lines)
        out[CODE[lines[start]]] = "\n".join(lines[start:end]).rstrip("\n") + "\n"
    return out


def verified() -> dict[str, str]:
    return {code: block for code, block in blocks().items() if NOT_RETRIEVED_LINE not in block}


def fiction(posted: date, land: str | None, began: date | None = None, *, scope: str = "vwvfg") -> date:
    return law.deemed_delivery(posted, scope, land, law.Derivation(), land=land, procedure_began=began)


# --------------------------------------------------------------------------------------------------
# the table against the texts
# --------------------------------------------------------------------------------------------------


def test_the_table_names_exactly_the_laender_with_a_verified_text() -> None:
    texts = blocks()
    assert set(texts) == set(law.LAENDER)
    with_text = set(verified())
    assert len(with_text) == 12
    assert set(law.LAND_VWVFG_FOURTH_DAY_FROM) | law.LAND_VWVFG_THIRD_DAY == with_text
    assert not set(law.LAND_VWVFG_FOURTH_DAY_FROM) & law.LAND_VWVFG_THIRD_DAY
    assert law.LAND_VWVFG_UNVERIFIED == set(law.LAENDER) - with_text == {"HB", "RP", "SL", "ST"}
    for code in law.LAND_VWVFG_UNVERIFIED:
        assert texts[code] == f"{law.LAND_NAMES[code]}\n{NOT_RETRIEVED_LINE}\n", code
    assert set(law.LAND_VWVFG_PROVISION) == with_text


@pytest.mark.parametrize("code", sorted(verified()))
def test_each_land_s_day_count_and_start_are_its_text_s(code: str) -> None:
    """A Land whose own § 41 (or the amendment of it) says the 3rd day keeps it; one that says the 4th, or that
    applies the federal act (whose § 41 says the 4th), counts the 4th from the day its block gives."""
    block = verified()[code]
    if OWN_THIRD in block and not OWN_FOURTH.search(block):
        assert code in law.LAND_VWVFG_THIRD_DAY
        assert code not in law.LAND_VWVFG_FOURTH_DAY_FROM
        return
    assert code in law.LAND_VWVFG_FOURTH_DAY_FROM, code
    if OWN_FOURTH.search(block):
        pattern, plus = START[code]
        found = re.search(pattern, block)
        assert found, code
        start = german_date(found.group(1)) + timedelta(days=plus)
    else:
        federal = APPLIES_FEDERAL.search(block)
        assert federal, code
        exceptions = federal.group("except") or ""
        assert not re.search(r"(?<![\d.])41(?![\d])", exceptions), (code, "the federal § 41 is not excepted")
        assert "am vierten Tag nach der Aufgabe zur Post" in VWVFG_TXT.read_text(encoding="utf-8")
        start = FEDERAL_START
        if code in START:  # an act of its own that applies the federal one from a later day (TH)
            found = re.search(START[code][0], block)
            assert found, code
            start = max(start, german_date(found.group(1)))
    assert law.LAND_VWVFG_FOURTH_DAY_FROM[code] == start, code


def test_hamburg_s_act_takes_effect_the_day_after_its_gazette() -> None:
    block = verified()["HH"]
    assert "am vierten Tag" in block
    assert (
        "mit dem auf die Ausgabe des Hamburgischen Gesetz- und Verordnungsblattes folgenden Tag in Kraft"
        in block
    )


def test_the_laender_that_keep_the_3rd_day_for_an_older_procedure() -> None:
    """Baden-Württemberg's § 102b, Bavaria's Art. 98 and Mecklenburg-Vorpommern's § 120a keep the old wording for a
    procedure begun before their switch; Nordrhein-Westfalen's § 97 and Thüringen's § 8 do not (the new law applies
    to a procedure under way, a posting being a step of its own)."""
    kept = {
        code: german_date(found.group("day"))
        for code, block in verified().items()
        if (found := OLD_LAW_KEPT.search(block))
    }
    assert kept == law.LAND_VWVFG_OLD_PROCEDURES
    assert kept == {code: law.LAND_VWVFG_FOURTH_DAY_FROM[code] for code in kept}
    assert set(law.LAND_VWVFG_OLD_PROCEDURE_RULE) == set(kept)
    for code, rule in law.LAND_VWVFG_OLD_PROCEDURE_RULE.items():
        number = rule.split()[1]
        assert re.search(rf"(?:§|Art\.) {re.escape(number)}\b", verified()[code]), (code, rule)


def test_brandenburg_s_e_mail_rule_is_held_and_refused() -> None:
    """§ 7 VwVfGBbg: an e-mailed decision counts from the day it arrived when that can be shown. law.py dates
    decisions sent by post only, so it refuses one sent otherwise and names the rule."""
    assert "§ 7 Bekanntgabe des Verwaltungsaktes" in verified()["BB"]
    with pytest.raises(ValueError, match="§ 7 VwVfGBbg"):
        law.deemed_delivery(
            date(2026, 10, 30), "vwvfg", "BB", law.Derivation(), land="BB", channel="electronic"
        )
    with pytest.raises(ValueError, match="by post"):
        law.deemed_delivery(
            date(2026, 10, 30), "vwvfg", "NW", law.Derivation(), land="NW", channel="electronic"
        )


# --------------------------------------------------------------------------------------------------
# what deemed_delivery gives
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("land", "posted", "began", "day"),
    [
        ("HE", date(2026, 9, 29), None, 3),  # § 41 Abs. 2 HVwVfG: the 3rd day
        ("HE", date(2025, 1, 2), None, 3),
        ("HE", date(2024, 12, 30), None, 3),
        ("HH", date(2025, 5, 13), None, 3),  # before the HmbVwVfG change took effect
        ("HH", date(2025, 5, 14), None, 4),
        ("BW", date(2025, 2, 6), None, 3),
        ("BW", date(2025, 2, 7), None, 4),
        ("SH", date(2025, 3, 3), None, 4),  # § 110 Abs. 2 LVwG from 1 January 2025
        ("TH", date(2025, 1, 2), None, 4),
        ("TH", date(2024, 12, 31), None, 3),
        ("NW", date(2025, 1, 2), date(2024, 11, 1), 4),  # § 97 VwVfG NRW: the posting decides
        ("MV", date(2025, 12, 9), date(2024, 11, 1), 3),  # § 120a VwVfG M-V
        ("MV", date(2025, 12, 9), None, 4),
        ("MV", date(2025, 12, 9), date(2025, 3, 1), 4),
        ("BY", date(2025, 12, 2), date(2024, 12, 31), 3),  # Art. 98 BayVwVfG
        ("BY", date(2025, 12, 2), date(2025, 1, 1), 4),
        ("BW", date(2025, 3, 3), date(2025, 2, 6), 3),  # § 102b LVwVfG
        ("BW", date(2025, 3, 3), date(2025, 2, 7), 4),
        ("BE", date(2026, 10, 27), None, 4),
        ("BB", date(2026, 10, 27), None, 4),
        ("NI", date(2026, 10, 27), None, 4),
        ("SN", date(2026, 10, 27), None, 4),
    ],
)
def test_a_land_authority_s_letter_counts_its_land_s_day(
    land: str, posted: date, began: date | None, day: int
) -> None:
    assert fiction(posted, land, began) == posted + timedelta(days=day)


@pytest.mark.parametrize("land", ["HB", "RP", "SL", "ST"])
def test_a_land_without_a_verified_text_is_refused(land: str) -> None:
    with pytest.raises(ValueError, match="no verified text") as refused:
        fiction(date(2026, 11, 3), land)
    assert law.LAND_NAMES[land] in str(refused.value) and "evals/law/laender.txt" in str(refused.value)


def test_a_land_authority_s_letter_names_its_land() -> None:
    with pytest.raises(ValueError, match="authority's Land"):
        law.deemed_delivery(date(2026, 11, 3), "vwvfg", "NW", law.Derivation())
    with pytest.raises(ValueError, match="unknown Land"):
        fiction(date(2026, 11, 3), "XX")


def test_a_procedure_s_start_is_checked() -> None:
    with pytest.raises(ValueError, match="after the decision was posted"):
        fiction(date(2026, 11, 3), "MV", date(2026, 11, 4))
    with pytest.raises(ValueError, match="Land authority"):
        fiction(date(2026, 11, 3), "MV", date(2024, 11, 4), scope="ao")


@pytest.mark.parametrize("scope", ["ao", "sgbx"])
@pytest.mark.parametrize(
    "posted", [date(2024, 12, 30), date(2025, 1, 2), date(2025, 5, 13), date(2026, 9, 29)]
)
def test_tax_and_social_law_decisions_are_the_same_in_every_land(scope: str, posted: date) -> None:
    """Under the AO and SGB X the Land changes nothing but the holidays: with or without the authority's Land, the
    same day and the same words."""
    for region in (None, *law.LAENDER):
        plain, with_land = law.Derivation(), law.Derivation()
        day = law.deemed_delivery(posted, scope, region, plain)
        for land in (None, *law.LAENDER):
            assert law.deemed_delivery(posted, scope, region, with_land, land=land) == day
            assert with_land.steps == plain.steps
            with_land = law.Derivation()
        assert (day - posted).days >= (3 if posted <= law.OLD_FICTION_LAST_DAY else 4)


def test_the_4th_day_keeps_its_words_and_the_3rd_names_the_land_s_provision() -> None:
    """Every earlier letter takes the 4th-day path, whose step reads as before; a 3rd-day step names the Land's
    own provision, and an older procedure its start and the provision that keeps the old day."""
    why = law.Derivation()
    fiction_ = law.deemed_delivery(date(2026, 9, 29), "vwvfg", "NW", why, land="NW")
    assert fiction_ == date(2026, 10, 3)
    assert why.steps[0] == (
        "Posted Tue 2026-09-29; § 41 Abs. 2 S. 1 VwVfG (Land VwVfG) (4-day rule for items posted from 2025-01-01 "
        "(PostModG)): day 4 after posting = Sat 2026-10-03."
    )
    hessen = law.Derivation()
    law.deemed_delivery(date(2026, 9, 29), "vwvfg", "HE", hessen, land="HE")
    assert (
        "§ 41 Abs. 2 S. 1 HVwVfG" in hessen.steps[0]
        and "day 3 after posting = Fri 2026-10-02" in hessen.steps[0]
    )
    hamburg = law.Derivation()
    law.deemed_delivery(date(2025, 5, 13), "vwvfg", "HH", hamburg, land="HH")
    assert "HmbVwVfG" in hamburg.steps[0] and "2025-05-14" in hamburg.steps[0]
    older = law.Derivation()
    law.deemed_delivery(date(2025, 12, 9), "vwvfg", "MV", older, land="MV", procedure_began=date(2024, 11, 1))
    assert "§ 120a VwVfG M-V" in older.steps[0] and "Fri 2024-11-01" in older.steps[0]
    assert "day 3 after posting = Fri 2025-12-12" in older.steps[0]


def test_an_objection_item_counts_the_authority_s_land() -> None:
    """``objection_item`` hands its Land to the fiction as the authority's: Hessen's 3rd day, an older MV matter's
    3rd day, and no letter without a Land or from a Land with no text."""
    hessen = objection_item(
        posted=date(2026, 9, 29), scope="vwvfg", remedy="widerspruch", region="HE", title="t"
    )
    assert hessen["expected_due"] == "2026-11-02"  # Fri 02.10. + 1 month = Mon 02.11.
    older = objection_item(posted=date(2025, 12, 9), scope="vwvfg", remedy="widerspruch", region="MV", title="t",
                           procedure_began=date(2024, 11, 1))  # fmt: skip
    assert older["expected_due"] == "2026-01-12"
    newer = objection_item(
        posted=date(2025, 12, 9), scope="vwvfg", remedy="widerspruch", region="MV", title="t"
    )
    assert newer["expected_due"] == "2026-01-13"
    for region in (None, "RP"):
        with pytest.raises(ValueError):
            objection_item(
                posted=date(2026, 9, 29), scope="vwvfg", remedy="widerspruch", region=region, title="t"
            )


# --------------------------------------------------------------------------------------------------
# the label check's own table gives the same days
# --------------------------------------------------------------------------------------------------


def test_the_label_check_s_table_agrees_with_the_generator_s() -> None:
    """``evals/verify_labels.py`` keeps its own table and arithmetic; for every Land, posting day and procedure start
    it gives the generator's day, and refuses where the generator refuses."""
    days = [date(2024, 12, 28) + timedelta(days=n) for n in range(0, 170, 3)] + [date(2026, 11, 3)]
    for land in law.LAENDER:
        for posted in days:
            for began in (None, date(2024, 11, 1), date(2025, 1, 1), date(2025, 2, 6), date(2025, 2, 7)):
                if began is not None and began > posted:
                    continue
                try:
                    mine = (fiction(posted, land, began) - posted).days
                except ValueError:
                    mine = None
                assert vl.land_fiction_days(land, posted, began) == mine, (land, posted, began)
    assert vl.land_fiction_days(None, date(2026, 11, 3)) is None
