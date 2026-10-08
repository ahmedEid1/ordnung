"""ordnung.rules.postcodes: the Land the postcode on a sender's letter suggests — a question for the person,
never an answer (ADR 0019) — and which of their dates confirming it may change (waits_for_sender_land)."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import ordnung
from ordnung.models import DateSpec
from ordnung.rules.calendar_de import REGION_NAMES
from ordnung.rules.deadlines import (
    ASSUMED_RECEIPT_WARNING,
    REGION_EARLIER,
    REGION_UNKNOWN,
    LandWait,
    RuleContext,
    compute_due,
    waits_for_sender_land,
)
from ordnung.rules.delivery import LAND_DAYS_UNCONFIRMED, resolve_delivery
from ordnung.rules.postcodes import (
    TABLE_PATH,
    Home,
    PostcodeLand,
    land_of_postcode,
    looks_foreign,
    postcodes_in,
    suggest_land,
    suggest_land_why,
    table,
)

D = date.fromisoformat
MUNICH = "Marienplatz 8, 80331 München"

# ------------------------------------------------------------------------------------ the table


@pytest.mark.parametrize(
    ("code", "land"),
    [
        ("80331", "BY"),
        ("10115", "BE"),
        ("01067", "SN"),
        pytest.param("21039", None, id="21039-hamburg-and-schleswig-holstein"),
        pytest.param("70790", None, id="70790-two-lands-large-customer"),
        pytest.param("87491", None, id="87491-listed-without-a-land"),
        pytest.param("12346", None, id="12346-not-listed"),
        pytest.param("8033", None, id="4-digits"),
        pytest.param("803311", None, id="6-digits"),
        pytest.param("8O331", None, id="a-letter"),
        pytest.param(" 80331", None, id="a-space"),
        pytest.param("", None, id="empty"),
    ],
)
def test_a_postcode_has_a_land_only_when_geonames_lists_it_in_exactly_one(
    code: str, land: str | None
) -> None:
    assert land_of_postcode(code) == land


def test_the_table_keeps_several_länder_and_none_explicit() -> None:
    assert table()["21039"] == {"HH", "SH"}
    assert table()["87491"] == frozenset()
    assert "12346" not in table()


def test_every_land_in_the_table_is_one_of_ordnung_s() -> None:
    assert TABLE_PATH == Path(ordnung.__file__).parent / "rules" / "data" / "postcodes_de.tsv"
    assert set().union(*table().values()) == set(REGION_NAMES)


def test_the_table_is_read_as_utf_8_whatever_the_locale() -> None:
    """Its header has "©" and "Länder": read with an ASCII locale's encoding, it would not load."""
    assert not TABLE_PATH.read_bytes().isascii()
    env = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONPATH": str(Path(ordnung.__file__).parents[1]),
    }
    code = "from ordnung.rules.postcodes import land_of_postcode; print(land_of_postcode('80331'))"
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False)
    assert (done.returncode, done.stdout.strip()) == (0, "BY"), done.stderr


# ------------------------------------------------------------------------------------ reading an address


@pytest.mark.parametrize(
    ("address", "codes"),
    [
        (MUNICH, ["80331"]),
        ("Marienplatz 8\nD-80331 München", ["80331"]),
        ("Postfach 12345, 80333 München", ["80333"]),
        ("Postfach 10 01 23\n80333 München", ["80333"]),
        ("Postfach 10 01 23 80333 München", ["80333"]),
        ("Postf. 12345 80333 München", ["80333"]),
        ("Postfach: 12345, 80333 München", ["80333"]),
        ("PF 10.01.23, 10115 Berlin", ["10115"]),
        ("Postfach 12345", []),
        ("Postfach\n80287 München", ["80287"]),
        ("Postfach 12345, 80333 München", ["80333"]),
        ("Pfarrgasse 3, 80331 München", ["80331"]),
        ("Marienplatz 8, 80331 München; Postfach 10 01 23, 80333 München", ["80331", "80333"]),
        ("80331 München, Marienplatz 8, 80331 München", ["80331"]),
        ("Kundennummer 1234567, Tel. 089 1234567", []),
    ],
)
def test_postcodes_in_reads_5_digit_codes_never_a_postfach_number(address: str, codes: list[str]) -> None:
    assert postcodes_in(address) == codes


@pytest.mark.parametrize(
    "address",
    [
        "75116 Paris, France",
        "F-75008 Paris",
        "Via Roma 1, 20121 Milano, Italia",
        "Bahnhofstrasse 1\nCH-8001 Zürich",
        "1 Main St, New York, NY 10001, U.S.A.",
        "Rue de la Loi 1, 1000 Bruxelles, BELGIQUE",
        "Istiklal Cad. 1, 34430 Istanbul, Türkiye.",
        "Kärntner Ring 1, 1010 Wien, (Österreich)",
        "10 Downing St, London SW1A 2AA,\nUnited  Kingdom",
    ],
)
def test_an_address_naming_another_country_or_its_postal_prefix_is_foreign(address: str) -> None:
    assert looks_foreign(address)


@pytest.mark.parametrize(
    "address",
    [
        "Markt 12, 01814 Bad Schandau, Sächsische Schweiz",
        "Marienplatz 8, D-80331 München, Germany",
        "Marienplatz 8, DE-80331 München, Deutschland",
        "Holländische Reihe 3, 22765 Hamburg",
        "Frankreichstraße 1, 66111 Saarbrücken",
        "Gebäude 3a-1234, 80331 München",
        "",
    ],
)
def test_a_german_address_is_not_foreign(address: str) -> None:
    assert not looks_foreign(address)


@pytest.mark.parametrize("code", sorted(REGION_NAMES))
def test_a_land_code_is_never_a_country(code: str) -> None:
    assert not looks_foreign(f"Hauptstr. 1\n10115 Berlin\n{code}")
    assert not looks_foreign(f"Hauptstr. 1, 10115 Berlin, {code.lower()}.")


def test_an_e_mail_or_web_address_under_another_country_s_domain_is_foreign() -> None:
    assert looks_foreign(MUNICH, email="info@firma.fr")
    assert looks_foreign(MUNICH, email="mailto:Info@Firma.AT")
    assert looks_foreign(MUNICH, website="https://www.firma.ch/kontakt?lang=de")
    assert looks_foreign(MUNICH, website="firma.co.uk")
    assert looks_foreign(MUNICH, website="http://user@firma.nl:8080")
    assert not looks_foreign(MUNICH, email="info@firma.de", website="https://firma.com:443/fr")
    assert not looks_foreign(MUNICH, email="info@firma.eu", website="www.firma.de/at")
    assert not looks_foreign(MUNICH, email="", website="fr")  # no domain at all
    assert not looks_foreign(MUNICH, website=".fr")


# ------------------------------------------------------------------------------------ the policy


def suggested(region: str, postcode: str) -> tuple[PostcodeLand, str]:
    return PostcodeLand(region, postcode), "suggested"


@pytest.mark.parametrize(
    ("address", "kwargs", "expected"),
    [
        pytest.param(None, {}, (None, "no_address"), id="no-address"),
        pytest.param(" \n ", {}, (None, "no_address"), id="blank-address"),
        pytest.param("75116 Paris, France", {}, (None, "foreign"), id="foreign-country"),
        pytest.param("F-75008 Paris", {}, (None, "foreign"), id="foreign-prefix"),
        pytest.param("Via Roma 1, 20121 Milano, Italia", {}, (None, "foreign"), id="foreign-italia"),
        pytest.param(MUNICH, {"email": "post@firma.fr"}, (None, "foreign"), id="foreign-e-mail"),
        pytest.param(MUNICH, {"website": "www.firma.ch"}, (None, "foreign"), id="foreign-website"),
        pytest.param("Postfach 12345, München", {}, (None, "no_postcode"), id="no-postcode"),
        pytest.param("Hauptstr. 1, 12346 Berlin", {}, (None, "not_listed"), id="not-listed"),
        pytest.param("Dorfstr. 1, 21039 Börnsen", {}, (None, "several_lands"), id="several-lands"),
        pytest.param("Dorfstr. 1, 87491 Jungholz", {}, (None, "no_land"), id="no-land"),
        pytest.param(
            f"{MUNICH}, Postfach 10 01 23, 10115 Berlin",
            {},
            (None, "postcodes_disagree"),
            id="street-and-box-two",
        ),
        pytest.param(
            f"{MUNICH}, Postfach 10 01 23, 80333 München", {}, suggested("BY", "80331"), id="street-and-box"
        ),
        pytest.param(
            "12346 Berlin\nPostfach 12 34, 10115 Berlin", {}, suggested("BE", "10115"), id="unlisted-ignored"
        ),
        pytest.param(
            "Markt 12, 01814 Bad Schandau, Sächsische Schweiz", {}, suggested("SN", "01814"), id="schweiz"
        ),
        pytest.param("Hauptstr. 1, 10115 Berlin, BE", {}, suggested("BE", "10115"), id="be-is-berlin"),
        pytest.param(
            MUNICH, {"email": "info@firma.de", "website": "firma.com"}, suggested("BY", "80331"), id="de"
        ),
        pytest.param(MUNICH, {}, suggested("BY", "80331"), id="suggested"),
    ],
)
def test_the_first_rule_that_applies_decides(
    address: str | None, kwargs: dict[str, Any], expected: Any
) -> None:
    assert suggest_land_why(address, **kwargs) == expected
    assert suggest_land(address, **kwargs) == expected[0]


def test_a_postcode_missing_from_the_visible_text_suggests_nothing() -> None:
    """A reader can take an address from hidden text (white on white, a layer under the scan): only a postcode
    the letter shows asks."""
    shown = "Stadtwerke München\nMarienplatz 8 · 80331 München\n\nSehr geehrte Damen und Herren,"
    assert suggest_land_why(MUNICH, visible_text=shown) == suggested("BY", "80331")
    assert suggest_land_why(MUNICH, visible_text="Kundennummer 1803310") == (None, "not_visible")
    assert suggest_land_why(MUNICH, visible_text="") == (None, "not_visible")
    both = f"{MUNICH}, Postfach 10 01 23, 80333 München"
    assert suggest_land_why(both, visible_text=shown) == (None, "not_visible")
    assert suggest_land_why("12346 Berlin, 10115 Berlin", visible_text="10115 Berlin") == suggested(
        "BE", "10115"
    )


def test_home_of_reads_the_person_s_postcode_and_town() -> None:
    assert Home.of("Musterweg 1\n80331 München", "by") == Home("80331", "münchen", "BY")
    assert Home.of("Postfach 12345, 10115 Berlin-Mitte", "BE") == Home("10115", "berlin", "BE")
    assert Home.of("Musterweg 1, 60311 Frankfurt am Main", None) == Home("60311", "frankfurt", None)
    assert Home.of("Musterweg 1, 80331", "BY") == Home("80331", None, "BY")
    assert Home.of("", "BY") == Home(None, None, "BY")


@pytest.mark.parametrize(
    ("sender", "home", "expected"),
    [
        pytest.param(
            MUNICH, Home.of("Musterweg 1, 80331 München", "BE"), (None, "home_veto"), id="same-postcode"
        ),
        pytest.param(
            "Leopoldstr. 1, 80802 München",
            Home.of("Musterweg 1, 80331 München", "BE"),
            (None, "home_veto"),
            id="town",
        ),
        pytest.param(
            "Leopoldstr. 1, 80802 München",
            Home.of("Musterweg 1, 80331 Muenchen", "BE"),
            suggested("BY", "80802"),
            id="another-town-word",
        ),
        pytest.param(
            "Hauptstr. 1, 81241 München",
            Home.of("Musterweg 1, 80331 München", "BE"),
            suggested("BY", "81241"),
            id="same-town-other-two-digits",
        ),
        pytest.param(
            "Hauptstr. 1, 85221 Dachau",
            Home.of("Musterweg 1, 85354 Freising", "BE"),
            suggested("BY", "85221"),
            id="same-two-digits-other-town",
        ),
        pytest.param(
            "Leopoldstr. 1, 80802",
            Home.of("Musterweg 1, 80331", "BE"),
            suggested("BY", "80802"),
            id="no-towns",
        ),
        pytest.param(
            MUNICH, Home.of("Musterweg 1, 80331 München", "BY"), suggested("BY", "80331"), id="same-land"
        ),
        pytest.param(
            MUNICH, Home.of("Musterweg 1, 80331 München", None), suggested("BY", "80331"), id="no-region"
        ),
        pytest.param(MUNICH, Home.of("", "BE"), suggested("BY", "80331"), id="no-home-postcode"),
    ],
)
def test_no_question_when_the_table_contradicts_the_person_s_own_land(
    sender: str, home: Home, expected: Any
) -> None:
    """The person set their Land and lives at the sender's postcode, or in the sender's town under the same
    first two digits, yet the table puts it elsewhere: the table and the person disagree, so nothing is asked.
    Before onboarding the region is no one's choice (``Profile.known_region`` is None) and never vetoes."""
    assert suggest_land_why(sender, home=home) == expected


# ------------------------------------------------------------------------------------ which dates wait


def relative(anchor_date: str, amount: int, nature: str) -> DateSpec:
    return DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date=anchor_date,
        amount=amount,
        unit="business_days",
        nature=nature,  # type: ignore[arg-type]
    )


def warnings(spec: DateSpec, **kw: Any) -> list[str]:
    """The engine's warnings with the sender's Land unknown, as the app computes them until it is set."""
    kw.setdefault("today", D("2026-09-25"))
    return compute_due(spec, RuleContext(region=None, **kw)).warnings


def test_a_holiday_the_engine_could_not_place_waits_for_the_land() -> None:
    later = warnings(relative("2026-05-29", 5, "other"))  # Fronleichnam, Thu 4 Jun 2026
    assert len(later) == 1 and later[0].startswith(REGION_UNKNOWN) and REGION_EARLIER not in later[0]
    assert waits_for_sender_land(later, "BY") == LandWait(waits=True, may_be_late=False)
    assert waits_for_sender_land(later, "TH") == (True, False)


def test_a_date_counted_backwards_waits_and_may_be_late() -> None:
    earlier = warnings(relative("2025-11-05", -5, "declaration"), today=D("2025-10-01"))  # Reformationstag
    assert len(earlier) == 1 and REGION_EARLIER in earlier[0]
    assert waits_for_sender_land(earlier, "NI") == LandWait(waits=True, may_be_late=True)


def test_the_3_or_4_day_rule_waits_only_for_a_land_that_uses_the_4th_day() -> None:
    """For HB, SL and TH the 4th day isn't confirmed: Ordnung counts 3 days with their Land as without it."""
    spec = DateSpec(
        type="relative",
        anchor="deemed_delivery",
        amount=1,
        unit="months",
        delivery_rule="de_admin_post",
        nature="objection",
        legal_basis="§ 70 VwGO",
    )
    days = warnings(spec, document_date=D("2026-09-29"), delivery_scope="vwvfg")
    assert days == [LAND_DAYS_UNCONFIRMED]
    assert waits_for_sender_land(days, "BY") == LandWait(waits=True, may_be_late=False)
    for land in ("HB", "SL", "TH"):
        assert waits_for_sender_land(days, land) == (False, False)


def test_land_days_unconfirmed_is_what_delivery_says() -> None:
    assert resolve_delivery(D("2026-09-29"), scope="vwvfg", region=None).uncertainty == LAND_DAYS_UNCONFIRMED
    assert resolve_delivery(D("2026-09-29"), scope="vwvfg", region="BY").uncertainty is None


def test_other_warnings_wait_for_nothing() -> None:
    quiet = warnings(relative("2026-09-01", 5, "other"))
    assert quiet == []
    assert waits_for_sender_land(quiet, "BY") == LandWait(waits=False, may_be_late=False)
    assert waits_for_sender_land([ASSUMED_RECEIPT_WARNING], "BY") == (False, False)
