"""The generator's own Länder table (``evals/gen/law.py``): the day a posted decision of a Land authority counts as
delivered, as each Land's text in ``evals/law/laender.txt`` gives it.

The table is the generator's, written from those texts. These tests read each Land's block and hold the table to
it: the day count (the 3rd or the 4th day after posting), the day the 4th day starts, the Länder that keep the 3rd
day for a procedure begun before their switch, and the Länder with no text, from which no letter may come. They
also check what ``deemed_delivery`` does with each, that tax and social-law decisions are untouched, and that
the label check's own table (``evals/verify_labels.py``, separate code) gives the same days.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

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
#: An act that applies the federal Verwaltungsverfahrensgesetz instead of a § 41 of its own.
APPLIES_FEDERAL = re.compile(
    r"(?:gilt|gelten) (?:dieses Gesetz und )?(?:die Vorschriften )?(?:das|des) Verwaltungsverfahrensgesetz(?:es)?"
    r"(?: \(VwVfG\))?"
)
#: The sections of the federal act such an act leaves out, read from where :data:`APPLIES_FEDERAL` ends to the end of
#: the list (its "des Verwaltungsverfahrensgesetzes." or "VwVfG.", or Niedersachsen's "sowie die Vorschriften dieses
#: Gesetzes"); a list's own "Abs." does not end it.
EXCEPTED = re.compile(
    r"\s+mit Ausnahme der (?P<except>.+?)"
    r"(?:(?:des Verwaltungsverfahrensgesetzes|VwVfG)\.|sowie die Vorschriften dieses Gesetzes)",
    re.DOTALL,
)
#: The Länder whose act applies the federal one with a list of sections left out.
WITH_EXCEPTIONS = frozenset({"BB", "NI", "TH"})
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


@dataclass(frozen=True)
class Table:
    """One Länder table: the generator's (``evals/gen/law.py``) or the label check's own (``evals/verify_labels.py``),
    which is separate code. Both are held to the texts the same way."""

    fourth_from: Mapping[str, date]
    third_day: frozenset[str]
    old_procedures: Mapping[str, date]
    unverified: frozenset[str]


def table(name: str) -> Table:
    if name == "evals/gen/law.py":
        return Table(
            law.LAND_VWVFG_FOURTH_DAY_FROM,
            law.LAND_VWVFG_THIRD_DAY,
            law.LAND_VWVFG_OLD_PROCEDURES,
            law.LAND_VWVFG_UNVERIFIED,
        )
    assert name == "evals/verify_labels.py", name
    return Table(vl.LAND_FOUR_DAY_START, vl.LAND_THIRD_DAY, vl.LAND_OLD_PROCEDURES, vl.LAND_UNVERIFIED)


TABLES = ("evals/gen/law.py", "evals/verify_labels.py")


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


@pytest.mark.parametrize("name", TABLES)
def test_the_table_names_exactly_the_laender_with_a_verified_text(name: str) -> None:
    mine = table(name)
    texts = blocks()
    assert set(texts) == set(law.LAENDER)
    with_text = set(verified())
    assert len(with_text) == 12
    assert set(mine.fourth_from) | mine.third_day == with_text
    assert not set(mine.fourth_from) & mine.third_day
    assert mine.unverified == set(law.LAENDER) - with_text == {"HB", "RP", "SL", "ST"}
    for code in mine.unverified:
        assert texts[code] == f"{law.LAND_NAMES[code]}\n{NOT_RETRIEVED_LINE}\n", code
    assert set(law.LAND_VWVFG_PROVISION) == with_text


@pytest.mark.parametrize("name", TABLES)
@pytest.mark.parametrize("code", sorted(verified()))
def test_each_land_s_day_count_and_start_are_its_text_s(code: str, name: str) -> None:
    """A Land whose own § 41 (or the amendment of it) says the 3rd day keeps it; one that says the 4th, or that
    applies the federal act (whose § 41 says the 4th) without leaving out its § 41, counts the 4th from the day its
    block gives. Each table, the generator's and the label check's, is held to the block on its own."""
    mine = table(name)
    block = verified()[code]
    if OWN_THIRD in block and not OWN_FOURTH.search(block):
        assert code in mine.third_day
        assert code not in mine.fourth_from
        return
    assert code in mine.fourth_from, code
    if OWN_FOURTH.search(block):
        pattern, plus = START[code]
        found = re.search(pattern, block)
        assert found, code
        start = german_date(found.group(1)) + timedelta(days=plus)
    else:
        federal = APPLIES_FEDERAL.search(block)
        assert federal, code
        excepted = EXCEPTED.match(block, federal.end())
        assert (excepted is not None) == (code in WITH_EXCEPTIONS), (code, "its list of sections left out")
        exceptions = excepted.group("except") if excepted else ""
        assert not re.search(r"(?<![\d.])41(?![\d])", exceptions), (code, "the federal § 41 is not excepted")
        assert "am vierten Tag nach der Aufgabe zur Post" in VWVFG_TXT.read_text(encoding="utf-8")
        start = FEDERAL_START
        if code in START:  # an act of its own that applies the federal one from a later day (TH)
            found = re.search(START[code][0], block)
            assert found, code
            start = max(start, german_date(found.group(1)))
    assert mine.fourth_from[code] == start, code


def test_the_exception_lists_are_read_whole() -> None:
    """The list of federal sections an act leaves out is read to its end, past the "Abs." inside it: Brandenburg's
    ends with §§ 100 and 101, Niedersachsen's with §§ 100 bis 101, Thüringen's with § 103."""
    ends = {"BB": "100 und 101 ", "NI": "§§ 100 bis 101 ", "TH": "102a und 103 "}
    for code, end in ends.items():
        block = verified()[code]
        federal = APPLIES_FEDERAL.search(block)
        assert federal, code
        excepted = EXCEPTED.match(block, federal.end())
        assert excepted and excepted.group("except").endswith(end), code


def test_hamburg_s_act_takes_effect_the_day_after_its_gazette() -> None:
    block = verified()["HH"]
    assert "am vierten Tag" in block
    assert (
        "mit dem auf die Ausgabe des Hamburgischen Gesetz- und Verordnungsblattes folgenden Tag in Kraft"
        in block
    )


@pytest.mark.parametrize("name", TABLES)
def test_the_laender_that_keep_the_3rd_day_for_an_older_procedure(name: str) -> None:
    """Baden-Württemberg's § 102b, Bavaria's Art. 98 and Mecklenburg-Vorpommern's § 120a keep the old wording for a
    procedure begun before their switch; Nordrhein-Westfalen's § 97 and Thüringen's § 8 do not (the new law applies
    to a procedure under way, a posting being a step of its own)."""
    mine = table(name)
    kept = {
        code: german_date(found.group("day"))
        for code, block in verified().items()
        if (found := OLD_LAW_KEPT.search(block))
    }
    assert kept == mine.old_procedures
    assert kept == {code: mine.fourth_from[code] for code in kept}
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


#: The step every Land 4th-day label of the five earlier splits carries, word for word.
EARLIER_FOURTH_DAY_STEP = (
    "Posted Tue 2026-09-29; § 41 Abs. 2 S. 1 VwVfG (Land VwVfG) (4-day rule for items posted from 2025-01-01 "
    "(PostModG)): day 4 after posting = Sat 2026-10-03."
)


def step(posted: date, land: str, began: date | None = None) -> str:
    why = law.Derivation()
    law.deemed_delivery(posted, "vwvfg", land, why, land=land, procedure_began=began)
    return why.steps[0]


def test_the_earlier_splits_keep_the_words_of_their_4th_day_step() -> None:
    """While the five earlier splits are built (:func:`law.earlier_splits_words`) a Land's 4th-day step reads as it
    always has, so their letters stay byte for byte; the switch is off again afterwards."""
    with law.earlier_splits_words():
        assert step(date(2026, 9, 29), "NW") == EARLIER_FOURTH_DAY_STEP
        bw = step(date(2026, 9, 29), "BW")
    assert bw == EARLIER_FOURTH_DAY_STEP
    assert step(date(2026, 9, 29), "NW") != EARLIER_FOURTH_DAY_STEP


@pytest.mark.parametrize(
    ("land", "posted", "began", "words"),
    [
        (
            "NW",
            date(2026, 9, 29),
            None,
            "§ 41 Abs. 2 S. 1 VwVfG NRW (Nordrhein-Westfalen counts the 4th day for items "
            "posted from 2025-01-01): day 4 after posting = Sat 2026-10-03.",
        ),
        (
            "HH",
            date(2025, 5, 14),
            None,
            "§ 41 Abs. 2 S. 1 HmbVwVfG (Hamburg counts the 4th day for items posted "
            "from 2025-05-14): day 4 after posting = Sun 2025-05-18.",
        ),
        (
            "BW",
            date(2025, 2, 7),
            None,
            "§ 41 Abs. 2 S. 1 LVwVfG (Baden-Württemberg counts the 4th day for items "
            "posted from 2025-02-07; the letter states no procedure begun before 2025-02-07): day 4 after posting = "
            "Tue 2025-02-11.",
        ),
        (
            "BY",
            date(2026, 9, 29),
            None,
            "Art. 41 Abs. 2 S. 1 BayVwVfG (Bayern counts the 4th day for items posted "
            "from 2025-01-01; the letter states no procedure begun before 2025-01-01): day 4",
        ),
        (
            "MV",
            date(2025, 12, 9),
            date(2025, 3, 1),
            "§ 41 Abs. 2 S. 1 VwVfG M-V (Mecklenburg-Vorpommern counts the "
            "4th day for items posted from 2025-01-01; the procedure began Sat 2025-03-01, not before 2025-01-01)",
        ),
        (
            "NI",
            date(2026, 9, 29),
            None,
            "§ 1 Abs. 1 NVwVfG with § 41 Abs. 2 S. 1 VwVfG (Niedersachsen counts the "
            "4th day for items posted from 2025-01-01)",
        ),
    ],
)
def test_a_land_s_4th_day_step_names_its_own_provision_and_start(
    land: str, posted: date, began: date | None, words: str
) -> None:
    """Outside the earlier splits a Land's 4th-day step cites the Land's provision and the day its 4th day starts,
    not the federal rule's start (PostModG); in BW, BY and MV it also says that the label rests on a procedure begun
    on or after the switch."""
    text = step(posted, land, began)
    assert words in text and "PostModG" not in text and "(Land VwVfG)" not in text, text


def test_a_final_letter_s_land_step_is_its_land_s_own() -> None:
    """``build_cases`` builds the five earlier splits with their words and a final plug-in's letters without them. The
    plug-in's builder uses the generator's own modules (``gen.*`` when ``evals/generate.py`` runs), as ``gen/final.py``
    does."""
    from evals import generate

    common = importlib.import_module(f"{generate.law.__name__.rpartition('.')[0]}.common")
    seen: list[str] = []

    class Built(Exception):
        pass

    def builder() -> list[Any]:
        made = common.objection_item(
            posted=date(2026, 12, 1), scope="vwvfg", remedy="widerspruch", region="NW", title="t"
        )
        seen.append(made["derivation"])
        raise Built

    earlier = [c for c in generate.build_cases(None) if c.id == "dev-municipal_decision-A1"]
    assert earlier
    assert "(Land VwVfG) (4-day rule for items posted from 2025-01-01 (PostModG))" in str(earlier[0].truth)
    assert "Land VwVfG 4-day fiction without shift." in str(earlier[0].truth)
    plugin = generate.FinalPlugin(
        final_day=date(2026, 12, 8),
        valid_until=date(2026, 12, 15),
        families={"holdout4": (("municipal_decision", builder),)},
        conventions=[],
        kind_also_accepted={},
    )
    with pytest.raises(Built):
        generate.build_cases(plugin)
    assert "§ 41 Abs. 2 S. 1 VwVfG NRW (Nordrhein-Westfalen counts the 4th day" in seen[0]
    assert "PostModG" not in seen[0] and "4-day fiction" not in seen[0]
    assert "the Land's own delivery day (evals/law/laender.txt), without shift." in seen[0]


def test_the_3rd_day_names_the_land_s_provision() -> None:
    """A 3rd-day step names the Land's own provision, and an older procedure its start and the provision that keeps
    the old day."""
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
    # the start the label rests on is written with it, and only where it was given (the earlier splits have none)
    assert older["spec"]["procedure_began"] == "2024-11-01"
    assert "procedure_began" not in newer["spec"] and "procedure_began" not in hessen["spec"]
    for region in (None, "RP"):
        with pytest.raises(ValueError):
            objection_item(
                posted=date(2026, 9, 29), scope="vwvfg", remedy="widerspruch", region=region, title="t"
            )


# --------------------------------------------------------------------------------------------------
# the label check's own table gives the same days
# --------------------------------------------------------------------------------------------------


#: Every posting day from the last days of the old rule to past Hamburg's switch, so every switch day (1 January,
#: 7 February, 14 May 2025) and the days on either side of it are among them, and one day of the final run's time.
AGREEMENT_DAYS = [date(2024, 12, 25) + timedelta(days=n) for n in range(147)] + [date(2026, 11, 3)]
#: Procedure starts on either side of each older-procedure switch (1 January and 7 February 2025).
AGREEMENT_STARTS = (
    None,
    date(2024, 11, 1),
    date(2024, 12, 31),
    date(2025, 1, 1),
    date(2025, 2, 6),
    date(2025, 2, 7),
)


def test_the_agreement_covers_every_switch_day_and_its_neighbours() -> None:
    for start in {*law.LAND_VWVFG_FOURTH_DAY_FROM.values(), *law.LAND_VWVFG_OLD_PROCEDURES.values()}:
        for day in (start - timedelta(days=1), start, start + timedelta(days=1)):
            assert day in AGREEMENT_DAYS, day
    for switch in law.LAND_VWVFG_OLD_PROCEDURES.values():
        assert {switch - timedelta(days=1), switch} <= set(AGREEMENT_STARTS), switch


def test_the_label_check_s_table_agrees_with_the_generator_s() -> None:
    """``evals/verify_labels.py`` keeps its own table and arithmetic; for every Land, posting day and procedure start
    it gives the generator's day, and refuses where the generator refuses."""
    for land in law.LAENDER:
        for posted in AGREEMENT_DAYS:
            for began in AGREEMENT_STARTS:
                if began is not None and began > posted:
                    continue
                try:
                    mine = (fiction(posted, land, began) - posted).days
                except ValueError:
                    mine = None
                assert vl.land_fiction_days(land, posted, began) == mine, (land, posted, began)
    assert vl.land_fiction_days(None, date(2026, 11, 3)) is None
