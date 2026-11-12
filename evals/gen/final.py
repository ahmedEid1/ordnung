"""The final splits' plug-in (see the module docstring of ``evals/generate.py``): the holdout4 and newkinds splits, read on
one planned day.

``FINAL_DAY`` is the day every holdout4 letter is read, and ``VALID_UNTIL`` the last day of the window in which it may be
read; every scored date, contract date and appointment lies after it. ``FAMILIES`` names the holdout4 builders (variants
K, L, M and N of the twelve template families, and the adversarial letters), ``CONVENTIONS_FINAL`` the labelling
conventions the holdout4 labels rest on that ``CONVENTIONS`` does not state, and ``KIND_ALSO_ACCEPTED_FINAL`` the letters
that fit a second document kind equally well. The newkinds split (``gen/newkinds.py``) has seven families of its own, four
letters each and no template variants; its conventions are f03 to f11.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from . import holdout4_admin as admin
from . import holdout4_adversarial as adversarial
from . import holdout4_private as private
from . import newkinds
from .common import Case

FINAL_DAY = date(2026, 11, 24)
VALID_UNTIL = date(2026, 12, 1)
assert (FINAL_DAY, VALID_UNTIL) == (admin.TODAY, admin.VALID_UNTIL) == (newkinds.TODAY, newkinds.VALID_UNTIL)

FAMILIES: dict[str, tuple[tuple[str, Callable[[], list[Case]]], ...]] = {
    "holdout4": (
        ("tax_assessment", admin.tax_assessment),
        ("municipal_decision", admin.municipal_decision),
        ("social_decision", admin.social_decision),
        ("invoice_relative", private.invoice_relative),
        ("dunning_fixed", private.dunning_fixed),
        ("appointment", private.appointment),
        ("fine_bussgeld", admin.fine_bussgeld),
        ("contract_confirmation", private.contract_confirmation),
        ("price_increase", private.price_increase),
        ("english_letter", private.english_letter),
        ("relative_business_days", private.business_days),
        ("year_boundary", admin.year_boundary),
        ("adversarial", adversarial.adversarial),
    ),
    "newkinds": (
        ("mahnbescheid", newkinds.mahnbescheid),
        ("vollstreckungsbescheid", newkinds.vollstreckungsbescheid),
        ("kuendigung_arbeit", newkinds.kuendigung_arbeit),
        ("kuendigung_miete", newkinds.kuendigung_miete),
        ("mieterhoehung", newkinds.mieterhoehung),
        ("betriebskosten", newkinds.betriebskosten),
        ("widerruf", newkinds.widerruf),
    ),
}

CONVENTIONS_FINAL: list[dict[str, Any]] = [
    {
        "id": "f01",
        "disputed": True,
        "text": "A letter that gives two different dates for the same obligation (two payment dates, or two calendar dates of the same "
        "decision from which its remedy period is counted): the label is the earlier date, the later one is listed among "
        "the candidates, and the item is marked for low assurance. Reading the letter against its drafter (§ 305c Abs. 2 "
        "BGB) or by the date printed in its header or payment box gives the later date.",
    },
    {
        "id": "f02",
        "disputed": False,
        "text": "24 and 31 December are working days: neither is a public holiday under federal law or any Land's holiday "
        "act, so a period that ends on either day stays there (§ 193 BGB, § 108 Abs. 3 AO, § 26 Abs. 3 SGB X, § 222 Abs. 2 "
        "ZPO).",
    },
    {
        "id": "f03",
        "disputed": False,
        "text": "A written declaration of a private sender that the letter says was handed to the addressee in person, or put into "
        "the addressee's letterbox by a messenger on a stated weekday in the morning, reaches the addressee on that day (§ 130 "
        "Abs. 1 S. 1 BGB); a period that runs from its receipt is counted from that day (§ 187 Abs. 1 BGB).",
    },
    {
        "id": "f04",
        "disputed": False,
        "text": "A court order served under the ZPO counts as served on the day the service note printed on it states (§ 180 S. 3, "
        "§ 177 ZPO). Its two-week period is counted by § 222 Abs. 1 ZPO with §§ 187 Abs. 1, 188 Abs. 2 BGB, and an end on a "
        "Saturday, Sunday or general holiday moves to the next working day (§ 222 Abs. 2 ZPO).",
    },
    {
        "id": "f05",
        "disputed": False,
        "text": "Mahnbescheid: the label is the end of the two weeks in which the debtor is asked to pay or to object (§ 692 Abs. 1 "
        "Nr. 3 ZPO). A Widerspruch still counts while no Vollstreckungsbescheid has been issued (§ 694 Abs. 1 ZPO); that "
        "reading gives no fixed date, so no other date is listed.",
    },
    {
        "id": "f06",
        "disputed": False,
        "text": "Dismissal: the action against a written dismissal is due three weeks after its receipt (§ 4 S. 1 KSchG, § 7 KSchG; "
        "§§ 187 Abs. 1, 188 Abs. 2 BGB). These letters are made so that the three weeks end on a working day in every Land, so "
        "no question of moving the end arises. The day the employment ends (§ 622 BGB) is stated, not labelled.",
    },
    {
        "id": "f07",
        "disputed": True,
        "text": "Landlord's notice: the lease ends as § 573c Abs. 1 BGB gives for the day of receipt, and the tenant's Widerspruch "
        "must reach the landlord two months before that end (§ 574b Abs. 2 S. 1 BGB), counted back from the end with §§ 187, "
        "188 Abs. 2, 3 BGB: a lease ending on a month's last day gives the last day of the month two months earlier "
        "(28 February → 31 December). The other reading takes the same day number two months earlier (28 February → "
        "28 December).",
    },
    {
        "id": "f08",
        "disputed": True,
        "text": "Rent increase: the tenant's period to consent ends with the second calendar month after the month of receipt "
        "(§ 558b Abs. 2 S. 1 BGB, § 192 BGB); the consent is a declaration due within a period, so an end on a Saturday, "
        "Sunday or holiday moves to the next working day (§ 193 BGB). The other reading leaves the end where it falls.",
    },
    {
        "id": "f09",
        "disputed": True,
        "text": "Operating-cost statement: the tenant's objections are due by the end of the twelfth month after receipt (§ 556 "
        "Abs. 3 S. 5 BGB), counted by §§ 187 Abs. 1, 188 Abs. 2, 3 BGB to the day with the receipt day's number, moved off a "
        "Saturday, Sunday or holiday (§ 193 BGB). The other reading takes the end of the twelfth calendar month after the "
        "month of receipt (§ 192 BGB).",
    },
    {
        "id": "f10",
        "disputed": False,
        "text": "A statement of operating costs given after the end of the twelfth month after its billing period (§ 556 Abs. 3 S. 2 "
        "BGB) cannot found a Nachforderung unless the landlord is not responsible for the delay (§ 556 Abs. 3 S. 3 BGB). "
        "These statements give no reason for the delay, so the payment they ask for is an optional item.",
    },
    {
        "id": "f11",
        "disputed": False,
        "text": "Withdrawal: 14 days (§ 355 Abs. 2 BGB) from conclusion, or for a sale of goods from receipt of the goods (§ 356 "
        "Abs. 2 Nr. 1 a BGB), where the letter with the withdrawal information was handed over on that day (§ 356 Abs. 3 S. 1 "
        "BGB); sending the withdrawal in time is enough (§ 355 Abs. 1 S. 5 BGB), and an end on a Saturday, Sunday or holiday "
        "moves to the next working day (§ 193 BGB).",
    },
]

KIND_ALSO_ACCEPTED_FINAL: dict[str, list[str]] = {
    "holdout4-year_boundary-K1": [
        "tax_letter"
    ],  # Familienkasse, Kindergeld under the EStG (social_insurance)
    "holdout4-year_boundary-M2": [
        "tax_letter"
    ],  # Familienkasse, Kindergeld under the EStG (social_insurance)
    "holdout4-year_boundary-K2": ["tax_assessment"],  # Finanzamt, Grundsteuerwert fixed (tax_letter)
    "holdout4-social_decision-L1": ["authority_letter"],  # Landkreis Wohngeld decision (social_insurance)
    "holdout4-social_decision-L2": ["authority_letter"],  # Jugendamt UVG decision (social_insurance)
    "holdout4-social_decision-N2": [
        "authority_letter"
    ],  # Sozialamt Grundsicherung decision (social_insurance)
    "holdout4-appointment-K2": ["authority_letter"],  # court summons of a witness (appointment)
    "holdout4-appointment-M2": ["authority_letter"],  # court hearing in a guardianship case (appointment)
    "holdout4-dunning_fixed-L1": ["dunning"],  # Hausverwaltung rent arrears (rent_lease)
    "holdout4-dunning_fixed-M2": ["dunning"],  # Stadtwerke reminder (utility_bill)
    "holdout4-adversarial-injection_visible-4": [
        "invoice"
    ],  # annual electricity statement with a balance (utility_bill)
    "holdout4-adversarial-scam-4": ["other"],  # directory offer laid out as an invoice (invoice)
    "newkinds-mahnbescheid-1": ["authority_letter"],  # court payment order (dunning)
    "newkinds-mahnbescheid-2": ["authority_letter"],  # court payment order (dunning)
    "newkinds-mahnbescheid-3": ["authority_letter"],  # court payment order (dunning)
    "newkinds-mahnbescheid-4": ["authority_letter"],  # court payment order (dunning)
    "newkinds-vollstreckungsbescheid-1": ["dunning"],  # enforcement order on a money claim (authority_letter)
    "newkinds-vollstreckungsbescheid-2": ["dunning"],  # enforcement order on a money claim (authority_letter)
    "newkinds-vollstreckungsbescheid-3": ["dunning"],  # enforcement order on a money claim (authority_letter)
    "newkinds-vollstreckungsbescheid-4": ["dunning"],  # enforcement order on a money claim (authority_letter)
    "newkinds-mieterhoehung-1": ["price_increase"],  # rent increase request (rent_lease)
    "newkinds-mieterhoehung-2": ["price_increase"],  # rent increase request (rent_lease)
    "newkinds-mieterhoehung-3": ["price_increase"],  # rent increase request (rent_lease)
    "newkinds-mieterhoehung-4": ["price_increase"],  # rent increase request (rent_lease)
    "newkinds-betriebskosten-1": ["utility_bill"],  # operating-cost statement (rent_lease)
    "newkinds-betriebskosten-2": ["utility_bill"],  # operating-cost statement (rent_lease)
    "newkinds-betriebskosten-3": ["utility_bill"],  # operating-cost statement (rent_lease)
    "newkinds-betriebskosten-4": ["utility_bill"],  # operating-cost statement (rent_lease)
}


# --- K27 table: generated by tools/k27_tags.py edc14f557004426bb47a1cf73304629e72511010dbc9f1162e85bad14f50fc25 from facts.json 161d0e5de779235420d0db951e2f75266e9dc8f8f7b1f086b72e8787d51c8ec4 81df177f5187b907c1eae08f241fa5cb6428401d9a3b3663a28cf7458e7aa3d6; do not edit ---
#: Amendment K27: each part of each final letter, its items (``i0``…), offered items (``o0``…) and
#: contract, is tagged with the convention ids the blind facts (``<split>/facts.json``) apply to its slots,
#: a contract's two slots together. A photo shares its letter's truth.
TAGS_FROM_FACTS: dict[str, dict[str, list[str]]] = {
    "holdout4-adversarial-conflicting_dates-1": {"i0": ["c06", "f01"]},
    "holdout4-adversarial-conflicting_dates-2": {"i0": ["c02", "c03", "c09", "f01"]},
    "holdout4-adversarial-conflicting_dates-3": {"i0": ["c06", "f01"]},
    "holdout4-adversarial-conflicting_dates-4": {"i0": ["c02", "c03", "c09", "f01"]},
    "holdout4-adversarial-hidden_text-1": {"i0": ["c02", "c03", "f02"]},
    "holdout4-adversarial-hidden_text-2": {"i0": ["c06"]},
    "holdout4-adversarial-hidden_text-3": {"i0": ["c02", "c03"]},
    "holdout4-adversarial-hidden_text-4": {"i0": ["c06"]},
    "holdout4-adversarial-injection_visible-1": {"i0": ["c02", "c03"]},
    "holdout4-adversarial-injection_visible-2": {"i0": ["c06"]},
    "holdout4-adversarial-injection_visible-3": {"i0": ["c02", "c03", "f02"]},
    "holdout4-adversarial-injection_visible-4": {"i0": ["c06"]},
    "holdout4-adversarial-missing_date-1": {"i0": ["c06", "c11", "c13"]},
    "holdout4-adversarial-missing_date-2": {"i0": ["c02", "c03", "c11", "c13"]},
    "holdout4-adversarial-missing_date-3": {"i0": ["c06", "c11", "c13"]},
    "holdout4-adversarial-missing_date-4": {"i0": ["c06", "c11", "c13"]},
    "holdout4-adversarial-scam-1": {"o0": ["c10"]},
    "holdout4-adversarial-scam-2": {"o0": ["c10"]},
    "holdout4-adversarial-scam-3": {"o0": ["c10"]},
    "holdout4-adversarial-scam-4": {"o0": ["c10"]},
    "holdout4-appointment-K1": {"i0": []},
    "holdout4-appointment-K2": {"i0": []},
    "holdout4-appointment-L1": {"i0": []},
    "holdout4-appointment-M1": {"i0": []},
    "holdout4-appointment-M2": {"i0": []},
    "holdout4-appointment-N1": {"i0": []},
    "holdout4-contract_confirmation-K1": {"contract": ["c21", "c22"]},
    "holdout4-contract_confirmation-L1": {"contract": ["c21", "c22"]},
    "holdout4-contract_confirmation-M1": {"contract": ["c22"]},
    "holdout4-contract_confirmation-N1": {"contract": ["c21", "c22"]},
    "holdout4-dunning_fixed-K1": {"i0": ["c06"]},
    "holdout4-dunning_fixed-K2": {"i0": ["c06"]},
    "holdout4-dunning_fixed-L1": {"i0": ["c06"]},
    "holdout4-dunning_fixed-M1": {"i0": ["c06"]},
    "holdout4-dunning_fixed-M2": {"i0": ["c06"]},
    "holdout4-dunning_fixed-N1": {"i0": ["c06"]},
    "holdout4-english_letter-K1": {"i0": []},
    "holdout4-english_letter-K2": {"i0": ["c06"]},
    "holdout4-english_letter-L1": {"i0": []},
    "holdout4-english_letter-L2": {"i0": []},
    "holdout4-english_letter-M1": {"i0": []},
    "holdout4-english_letter-M2": {"i0": ["c06"]},
    "holdout4-english_letter-N1": {"i0": []},
    "holdout4-english_letter-N2": {"i0": []},
    "holdout4-fine_bussgeld-K1": {"i0": ["c03"], "o0": []},
    "holdout4-fine_bussgeld-K2": {"i0": ["c03"], "o0": []},
    "holdout4-fine_bussgeld-L1": {"i0": ["c03"], "o0": []},
    "holdout4-fine_bussgeld-L2": {"i0": ["c03"], "o0": []},
    "holdout4-fine_bussgeld-M1": {"i0": ["c03"], "o0": []},
    "holdout4-fine_bussgeld-M2": {"i0": ["c03"], "o0": []},
    "holdout4-fine_bussgeld-N1": {"i0": ["c03"], "o0": []},
    "holdout4-fine_bussgeld-N2": {"i0": ["c03"], "o0": []},
    "holdout4-invoice_relative-K1": {"i0": ["c06"]},
    "holdout4-invoice_relative-K2": {"i0": ["c06"]},
    "holdout4-invoice_relative-L1": {"i0": ["c06"]},
    "holdout4-invoice_relative-L2": {"i0": ["c06"]},
    "holdout4-invoice_relative-M1": {"i0": ["c06"]},
    "holdout4-invoice_relative-M2": {"i0": ["c06"]},
    "holdout4-invoice_relative-N1": {"i0": ["c06"]},
    "holdout4-invoice_relative-N2": {"i0": ["c06"]},
    "holdout4-municipal_decision-K1": {"i0": ["c02", "c03"]},
    "holdout4-municipal_decision-K2": {"i0": ["c02", "c03"]},
    "holdout4-municipal_decision-L1": {"i0": ["c02", "c03", "c09"], "i1": []},
    "holdout4-municipal_decision-L2": {"i0": ["c02", "c03"]},
    "holdout4-municipal_decision-M1": {"i0": ["c02", "c03"]},
    "holdout4-municipal_decision-M2": {"i0": ["c02", "c03"]},
    "holdout4-municipal_decision-N1": {"i0": ["c02", "c03", "c09"]},
    "holdout4-municipal_decision-N2": {"i0": ["c02", "c03"]},
    "holdout4-price_increase-K1": {"o0": ["c10", "c22"]},
    "holdout4-price_increase-L1": {"o0": []},
    "holdout4-price_increase-M1": {"o0": ["c10", "c22", "f02"]},
    "holdout4-price_increase-N1": {"o0": []},
    "holdout4-relative_business_days-K1": {"i0": []},
    "holdout4-relative_business_days-K2": {"i0": []},
    "holdout4-relative_business_days-L1": {"i0": []},
    "holdout4-relative_business_days-M1": {"i0": []},
    "holdout4-relative_business_days-M2": {"i0": ["c06"]},
    "holdout4-relative_business_days-N1": {"i0": []},
    "holdout4-social_decision-K1": {"i0": ["c02", "c03"]},
    "holdout4-social_decision-K2": {"i0": ["c02", "c03", "f02"]},
    "holdout4-social_decision-L1": {"i0": ["c02", "c03", "f02"], "i1": []},
    "holdout4-social_decision-L2": {"i0": ["c02", "c03"]},
    "holdout4-social_decision-M1": {"i0": ["c02", "c03", "f02"]},
    "holdout4-social_decision-M2": {"i0": ["c02", "c03", "f02"]},
    "holdout4-social_decision-N1": {"i0": ["c02", "c03"], "i1": []},
    "holdout4-social_decision-N2": {"i0": ["c02", "c03", "f02"]},
    "holdout4-tax_assessment-K1": {"i0": ["c02", "c03"]},
    "holdout4-tax_assessment-K2": {"i0": ["c02", "c03"]},
    "holdout4-tax_assessment-L1": {"i0": ["c02", "c03", "f02"], "i1": []},
    "holdout4-tax_assessment-L2": {"i0": ["c02", "c03"]},
    "holdout4-tax_assessment-M1": {"i0": ["c02", "c03", "f02"]},
    "holdout4-tax_assessment-M2": {"i0": ["c02", "c03"]},
    "holdout4-tax_assessment-N1": {"i0": ["c02", "c03"]},
    "holdout4-tax_assessment-N2": {"i0": ["c02", "c03"]},
    "holdout4-year_boundary-K1": {"i0": ["c02", "c03"]},
    "holdout4-year_boundary-K2": {"i0": ["c02", "c03"]},
    "holdout4-year_boundary-K3": {"i0": ["c02", "c03"]},
    "holdout4-year_boundary-L1": {"i0": ["c02", "c03"]},
    "holdout4-year_boundary-L2": {"i0": ["c02", "c03"]},
    "holdout4-year_boundary-M1": {"i0": ["c02", "c03", "f02"]},
    "holdout4-year_boundary-M2": {"i0": ["c02", "c03"]},
    "holdout4-year_boundary-M3": {"i0": ["c02", "c03"]},
    "holdout4-year_boundary-N1": {"i0": ["c02", "c03"]},
    "holdout4-year_boundary-N2": {"i0": ["c02", "c03"]},
    "newkinds-betriebskosten-1": {"i0": ["f03", "f09"], "o0": ["c10", "f10"]},
    "newkinds-betriebskosten-2": {"i0": ["f03", "f09"], "o0": ["c10", "f10"]},
    "newkinds-betriebskosten-3": {"i0": ["f03", "f09"]},
    "newkinds-betriebskosten-4": {"i0": ["f03", "f09"], "o0": ["c10", "f10"]},
    "newkinds-kuendigung_arbeit-1": {"i0": ["f03", "f06"]},
    "newkinds-kuendigung_arbeit-2": {"i0": ["f03", "f06"]},
    "newkinds-kuendigung_arbeit-3": {"i0": ["f03", "f06"]},
    "newkinds-kuendigung_arbeit-4": {"i0": ["f03", "f06"]},
    "newkinds-kuendigung_miete-1": {"i0": ["f02", "f03", "f07"]},
    "newkinds-kuendigung_miete-2": {"i0": ["f03", "f07"]},
    "newkinds-kuendigung_miete-3": {"i0": ["f03", "f07"]},
    "newkinds-kuendigung_miete-4": {"i0": ["f02", "f03", "f07"]},
    "newkinds-mahnbescheid-1": {"i0": ["f04", "f05"]},
    "newkinds-mahnbescheid-2": {"i0": ["f04", "f05"]},
    "newkinds-mahnbescheid-3": {"i0": ["f04", "f05"]},
    "newkinds-mahnbescheid-4": {"i0": ["f04", "f05"]},
    "newkinds-mieterhoehung-1": {"i0": ["f03", "f08"]},
    "newkinds-mieterhoehung-2": {"i0": ["f03", "f08"]},
    "newkinds-mieterhoehung-3": {"i0": ["f03", "f08"]},
    "newkinds-mieterhoehung-4": {"i0": ["f03", "f08"]},
    "newkinds-vollstreckungsbescheid-1": {"i0": ["f04"]},
    "newkinds-vollstreckungsbescheid-2": {"i0": ["f04"]},
    "newkinds-vollstreckungsbescheid-3": {"i0": ["f04"]},
    "newkinds-vollstreckungsbescheid-4": {"i0": ["f04"]},
    "newkinds-widerruf-1": {"o0": ["c10", "f11"]},
    "newkinds-widerruf-2": {"o0": ["c10", "f11"]},
    "newkinds-widerruf-3": {"o0": ["c10", "f11"]},
    "newkinds-widerruf-4": {"o0": ["c10", "f11"]},
}
#: The dated parts that gain c10, or c22 on a day no Land's holidays move, and have no list of other
#: dates: their other reading gives no other date, so their list is empty.
K27_NO_OTHER_DATE: tuple[tuple[str, str], ...] = (
    ("holdout4-adversarial-scam-1", "o0"),
    ("holdout4-adversarial-scam-2", "o0"),
    ("holdout4-adversarial-scam-3", "o0"),
    ("holdout4-adversarial-scam-4", "o0"),
    ("holdout4-price_increase-K1", "o0"),
    ("holdout4-price_increase-M1", "o0"),
)


def _k27_parts(case: Case) -> dict[str, dict[str, Any]]:
    """A letter's parts by name: ``i0``…, ``o0``… and ``contract``."""
    truth = case.truth
    parts: dict[str, dict[str, Any]] = {f"i{n}": item for n, item in enumerate(truth["items"])}
    parts |= {f"o{n}": item for n, item in enumerate(truth.get("optional_items") or [])}
    if truth.get("contract"):
        parts["contract"] = truth["contract"]
    return parts


def _k27_tagged(builder: Callable[[], list[Case]]) -> Callable[[], list[Case]]:
    """``builder``, with each part tagged as TAGS_FROM_FACTS says where the two sets differ, and an empty list of
    other dates on the parts K27_NO_OTHER_DATE names."""

    def build() -> list[Case]:
        cases = builder()
        for case in cases:
            parts, tags = _k27_parts(case), TAGS_FROM_FACTS.get(case.id)
            if tags is None or set(tags) != set(parts):
                raise ValueError(f"{case.id}: TAGS_FROM_FACTS does not list exactly its parts")
            for name, part in parts.items():
                if set(part.get("conventions") or []) != set(tags[name]):
                    part["conventions"] = list(tags[name])
                if (case.id, name) in K27_NO_OTHER_DATE:
                    if "convention_alternatives" in part:
                        raise ValueError(f"{case.id} {name}: already has a list of other dates")
                    part["convention_alternatives"] = []
        return cases

    return build


#: The builders with the tags they were written with (provenance/k27/writer-tags.json).
FAMILIES_AS_WRITTEN = FAMILIES
FAMILIES = {
    split: tuple((family, _k27_tagged(builder)) for family, builder in pairs)
    for split, pairs in FAMILIES.items()
}
# --- end K27 table ---
