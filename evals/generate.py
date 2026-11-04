"""Generate the Ordnung benchmark documents and their ground truth.

    .venv/bin/python evals/generate.py                 # writes evals/dataset/<split>/ + manifest.json
    .venv/bin/python evals/generate.py --out /tmp/x    # same, elsewhere (used by the determinism test)
    .venv/bin/python -m evals.generate --final-day D   # same, naming the final splits' day (refused unless theirs)

Everything is deterministic: fixed seeds, fixed PDF metadata and creation dates, no clock reads.
Labels come from the small, commented date arithmetic in ``evals/gen/law.py`` — never from
``ordnung.rules`` — and every dated label is additionally asserted against a date worked out by hand
(``check(..., hand)`` in the family modules).

Template families have ten wording/layout variants each: A and B go to ``dev`` (the only split
anything may be tuned on), C and D to ``test`` (the published run), E and F to ``holdout``, G and H to
``holdout2``, I and J to ``holdout3``. Adversarial letters are one-offs in ``test``, ``holdout``, ``holdout2``
and ``holdout3``; dev has none.

The test split was meant to be held out, but it was tuned on, so it no longer is. The ``holdout``
split is a fresh sample of the same families, written from scratch (``gen/holdout_*.py``: new senders,
recipients, wording, layout, dates and amounts) before its first run. It is run once and never tuned
on. No deadline-bearing sentence of one split recurs in another (``evals/verify_labels.py``).

The ``holdout2`` split is another fresh sample of the same families and attack classes
(``gen/holdout2_*.py``), written after the release's last code change from the law and from how such
letters read (new senders, recipients, wording, layout, dates, amounts and regions), so that the
benchmark has letters that no code change was informed by. It is run once, and nothing is tuned on it.

The ``holdout3`` split is a third fresh sample of the same families and attack classes
(``gen/holdout3_*.py``), written after the code freeze for this release, when the holdout2 split had been
run and later code had been informed by that run. It was written from the law and from how such
letters read (new senders, recipients, wording, layout, dates, amounts and regions, among them Länder the
earlier splits used little), is audited blind before its one run, and nothing is tuned on it.

The final splits (``holdout4`` and ``newkinds``) come from a plug-in, ``gen/final.py``, written after the
code freeze for one planned day, ``FINAL_DAY``, and a window of valid days that ends on ``VALID_UNTIL``.
When that module exists it adds its splits (``FAMILIES``), its labelling conventions
(``CONVENTIONS_FINAL``) and its letters with a second fitting document kind (``KIND_ALSO_ACCEPTED_FINAL``);
``--final-day``, when given, must be its ``FINAL_DAY``. Every final letter is read on ``FINAL_DAY``,
every final entry records ``final_day`` and ``valid_until``, every scored date, contract date and
appointment lies after ``VALID_UNTIL``, and every scored item names the conventions its label rests on
(:func:`check_final_case`). Without the module the output is the five splits above, byte for byte.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:  # allow `python evals/generate.py` from the repo root
    sys.path.insert(0, str(HERE))

# mypy reads evals/ as a package, where the generators are evals.gen; run as a script, they are gen (the
# folder put on sys.path above). The same files and names either way.
if TYPE_CHECKING:
    from evals.gen import law
    from evals.gen.adversarial import adversarial
    from evals.gen.common import DOCUMENT_KINDS, SPLIT_VARIANTS, Case
    from evals.gen.families_admin import (
        fine_bussgeld,
        municipal_decision,
        social_decision,
        tax_assessment,
        year_boundary,
    )
    from evals.gen.families_private import (
        appointment,
        business_days,
        contract_confirmation,
        dunning_fixed,
        english_letter,
        invoice_relative,
        price_increase,
    )
    from evals.gen.holdout2_admin import fine_bussgeld as holdout2_fine_bussgeld
    from evals.gen.holdout2_admin import municipal_decision as holdout2_municipal_decision
    from evals.gen.holdout2_admin import social_decision as holdout2_social_decision
    from evals.gen.holdout2_admin import tax_assessment as holdout2_tax_assessment
    from evals.gen.holdout2_admin import year_boundary as holdout2_year_boundary
    from evals.gen.holdout2_adversarial import adversarial as holdout2_adversarial
    from evals.gen.holdout2_private import appointment as holdout2_appointment
    from evals.gen.holdout2_private import business_days as holdout2_business_days
    from evals.gen.holdout2_private import contract_confirmation as holdout2_contract_confirmation
    from evals.gen.holdout2_private import dunning_fixed as holdout2_dunning_fixed
    from evals.gen.holdout2_private import english_letter as holdout2_english_letter
    from evals.gen.holdout2_private import invoice_relative as holdout2_invoice_relative
    from evals.gen.holdout2_private import price_increase as holdout2_price_increase
    from evals.gen.holdout3_admin import fine_bussgeld as holdout3_fine_bussgeld
    from evals.gen.holdout3_admin import municipal_decision as holdout3_municipal_decision
    from evals.gen.holdout3_admin import social_decision as holdout3_social_decision
    from evals.gen.holdout3_admin import tax_assessment as holdout3_tax_assessment
    from evals.gen.holdout3_admin import year_boundary as holdout3_year_boundary
    from evals.gen.holdout3_adversarial import adversarial as holdout3_adversarial
    from evals.gen.holdout3_private import appointment as holdout3_appointment
    from evals.gen.holdout3_private import business_days as holdout3_business_days
    from evals.gen.holdout3_private import contract_confirmation as holdout3_contract_confirmation
    from evals.gen.holdout3_private import dunning_fixed as holdout3_dunning_fixed
    from evals.gen.holdout3_private import english_letter as holdout3_english_letter
    from evals.gen.holdout3_private import invoice_relative as holdout3_invoice_relative
    from evals.gen.holdout3_private import price_increase as holdout3_price_increase
    from evals.gen.holdout_admin import fine_bussgeld as holdout_fine_bussgeld
    from evals.gen.holdout_admin import municipal_decision as holdout_municipal_decision
    from evals.gen.holdout_admin import social_decision as holdout_social_decision
    from evals.gen.holdout_admin import tax_assessment as holdout_tax_assessment
    from evals.gen.holdout_admin import year_boundary as holdout_year_boundary
    from evals.gen.holdout_adversarial import adversarial as holdout_adversarial
    from evals.gen.holdout_private import appointment as holdout_appointment
    from evals.gen.holdout_private import business_days as holdout_business_days
    from evals.gen.holdout_private import contract_confirmation as holdout_contract_confirmation
    from evals.gen.holdout_private import dunning_fixed as holdout_dunning_fixed
    from evals.gen.holdout_private import english_letter as holdout_english_letter
    from evals.gen.holdout_private import invoice_relative as holdout_invoice_relative
    from evals.gen.holdout_private import price_increase as holdout_price_increase
    from evals.gen.pdf import render_letter
    from evals.gen.photo import phone_photo
    from evals.gen.text import seed_for
else:
    from gen import law
    from gen.adversarial import adversarial
    from gen.common import DOCUMENT_KINDS, SPLIT_VARIANTS, Case
    from gen.families_admin import (
        fine_bussgeld,
        municipal_decision,
        social_decision,
        tax_assessment,
        year_boundary,
    )
    from gen.families_private import (
        appointment,
        business_days,
        contract_confirmation,
        dunning_fixed,
        english_letter,
        invoice_relative,
        price_increase,
    )
    from gen.holdout2_admin import fine_bussgeld as holdout2_fine_bussgeld
    from gen.holdout2_admin import municipal_decision as holdout2_municipal_decision
    from gen.holdout2_admin import social_decision as holdout2_social_decision
    from gen.holdout2_admin import tax_assessment as holdout2_tax_assessment
    from gen.holdout2_admin import year_boundary as holdout2_year_boundary
    from gen.holdout2_adversarial import adversarial as holdout2_adversarial
    from gen.holdout2_private import appointment as holdout2_appointment
    from gen.holdout2_private import business_days as holdout2_business_days
    from gen.holdout2_private import contract_confirmation as holdout2_contract_confirmation
    from gen.holdout2_private import dunning_fixed as holdout2_dunning_fixed
    from gen.holdout2_private import english_letter as holdout2_english_letter
    from gen.holdout2_private import invoice_relative as holdout2_invoice_relative
    from gen.holdout2_private import price_increase as holdout2_price_increase
    from gen.holdout3_admin import fine_bussgeld as holdout3_fine_bussgeld
    from gen.holdout3_admin import municipal_decision as holdout3_municipal_decision
    from gen.holdout3_admin import social_decision as holdout3_social_decision
    from gen.holdout3_admin import tax_assessment as holdout3_tax_assessment
    from gen.holdout3_admin import year_boundary as holdout3_year_boundary
    from gen.holdout3_adversarial import adversarial as holdout3_adversarial
    from gen.holdout3_private import appointment as holdout3_appointment
    from gen.holdout3_private import business_days as holdout3_business_days
    from gen.holdout3_private import contract_confirmation as holdout3_contract_confirmation
    from gen.holdout3_private import dunning_fixed as holdout3_dunning_fixed
    from gen.holdout3_private import english_letter as holdout3_english_letter
    from gen.holdout3_private import invoice_relative as holdout3_invoice_relative
    from gen.holdout3_private import price_increase as holdout3_price_increase
    from gen.holdout_admin import fine_bussgeld as holdout_fine_bussgeld
    from gen.holdout_admin import municipal_decision as holdout_municipal_decision
    from gen.holdout_admin import social_decision as holdout_social_decision
    from gen.holdout_admin import tax_assessment as holdout_tax_assessment
    from gen.holdout_admin import year_boundary as holdout_year_boundary
    from gen.holdout_adversarial import adversarial as holdout_adversarial
    from gen.holdout_private import appointment as holdout_appointment
    from gen.holdout_private import business_days as holdout_business_days
    from gen.holdout_private import contract_confirmation as holdout_contract_confirmation
    from gen.holdout_private import dunning_fixed as holdout_dunning_fixed
    from gen.holdout_private import english_letter as holdout_english_letter
    from gen.holdout_private import invoice_relative as holdout_invoice_relative
    from gen.holdout_private import price_increase as holdout_price_increase
    from gen.pdf import render_letter
    from gen.photo import phone_photo
    from gen.text import seed_for

DEFAULT_OUT = HERE / "dataset"
#: The whole dataset's cap: the five splits below take about 20 MB, the final splits about 11 MB more.
MAX_TOTAL_BYTES = 40 * 1024 * 1024
#: The splits this module's own builders write (a final split comes from the plug-in, ``gen/final.py``).
SPLITS: tuple[str, ...] = ("dev", "test", "holdout", "holdout2", "holdout3")
assert set(SPLITS) <= set(SPLIT_VARIANTS), SPLITS
#: The years whose holidays ``law``'s tables are checked for against the ``holidays`` package (contracts reach 2028).
HOLIDAY_YEARS = range(2024, 2030)

FAMILIES = (
    ("tax_assessment", tax_assessment),
    ("municipal_decision", municipal_decision),
    ("social_decision", social_decision),
    ("invoice_relative", invoice_relative),
    ("dunning_fixed", dunning_fixed),
    ("appointment", appointment),
    ("fine_bussgeld", fine_bussgeld),
    ("contract_confirmation", contract_confirmation),
    ("price_increase", price_increase),
    ("english_letter", english_letter),
    ("relative_business_days", business_days),
    ("year_boundary", year_boundary),
    ("adversarial", adversarial),
)
# The holdout split's letters (variants E, F and new adversarial letters), one builder per family.
HOLDOUT_FAMILIES = (
    ("tax_assessment", holdout_tax_assessment),
    ("municipal_decision", holdout_municipal_decision),
    ("social_decision", holdout_social_decision),
    ("invoice_relative", holdout_invoice_relative),
    ("dunning_fixed", holdout_dunning_fixed),
    ("appointment", holdout_appointment),
    ("fine_bussgeld", holdout_fine_bussgeld),
    ("contract_confirmation", holdout_contract_confirmation),
    ("price_increase", holdout_price_increase),
    ("english_letter", holdout_english_letter),
    ("relative_business_days", holdout_business_days),
    ("year_boundary", holdout_year_boundary),
    ("adversarial", holdout_adversarial),
)
# The holdout2 split's letters (variants G, H and new adversarial letters), one builder per family.
HOLDOUT2_FAMILIES = (
    ("tax_assessment", holdout2_tax_assessment),
    ("municipal_decision", holdout2_municipal_decision),
    ("social_decision", holdout2_social_decision),
    ("invoice_relative", holdout2_invoice_relative),
    ("dunning_fixed", holdout2_dunning_fixed),
    ("appointment", holdout2_appointment),
    ("fine_bussgeld", holdout2_fine_bussgeld),
    ("contract_confirmation", holdout2_contract_confirmation),
    ("price_increase", holdout2_price_increase),
    ("english_letter", holdout2_english_letter),
    ("relative_business_days", holdout2_business_days),
    ("year_boundary", holdout2_year_boundary),
    ("adversarial", holdout2_adversarial),
)
# The holdout3 split's letters (variants I, J and new adversarial letters), one builder per family.
HOLDOUT3_FAMILIES = (
    ("tax_assessment", holdout3_tax_assessment),
    ("municipal_decision", holdout3_municipal_decision),
    ("social_decision", holdout3_social_decision),
    ("invoice_relative", holdout3_invoice_relative),
    ("dunning_fixed", holdout3_dunning_fixed),
    ("appointment", holdout3_appointment),
    ("fine_bussgeld", holdout3_fine_bussgeld),
    ("contract_confirmation", holdout3_contract_confirmation),
    ("price_increase", holdout3_price_increase),
    ("english_letter", holdout3_english_letter),
    ("relative_business_days", holdout3_business_days),
    ("year_boundary", holdout3_year_boundary),
    ("adversarial", holdout3_adversarial),
)


class Convention(TypedDict):
    """One labelling convention: a stable id (``c01``…; a final split's own are ``f01``…), whether another defensible
    reading contests it (``disputed``: here, exactly the conventions that the "Judgement calls kept on purpose"
    sections of evals/dataset/VERIFICATION.md name), and its text."""

    id: str
    disputed: bool
    text: str


def _conventions(*entries: tuple[str, bool, str]) -> list[Convention]:
    return [Convention(id=id_, disputed=disputed, text=text) for id_, disputed, text in entries]


CONVENTIONS = _conventions(
    ("c01", False, "Labels are computed from the statutes by evals/gen/law.py and asserted against dates worked out by hand."),
    ("c02", True, "Posting date for the deemed-delivery fiction = the letter date, unless the letter states a separate posting date (spec.posted_on)."),
    ("c03", True, "Deemed delivery: 3rd day after posting for items posted up to 2024-12-31, 4th day from 2025-01-01 (federal law and SGB X). "
     "A Land authority's letter counts its own Land's day (evals/law/laender.txt): Hessen the 3rd day; Hamburg the 4th from 2025-05-14 and "
     "Baden-Württemberg from 2025-02-07, the 3rd before; the other Länder with a text the 4th from 2025-01-01; in Baden-Württemberg, Bayern "
     "and Mecklenburg-Vorpommern a procedure begun before that Land's switch keeps the 3rd day when the letter states that start; a letter "
     "that states none is labelled as a procedure begun on or after the switch (the 4th day). AO moves a Sat/Sun/holiday fiction day to "
     "the next working day, VwVfG and SGB X do not. Remedy periods: one month (§§ 187 Abs. 1, 188 Abs. 2, 3 BGB), end moved off "
     "Sat/Sun/holidays; Bußgeld: two weeks after the Zustellung date on the envelope."),
    ("c04", False, "authority_region is set only when the letterhead names the Land; then expected_due uses that Land's holidays. When it is null, "
     "every dated item was verified to have the same date under all 16 Land calendars (so nationwide-only == legally correct)."),
    ("c05", False, "No label depends on municipal-only holidays (Mariä Himmelfahrt in parts of BY, Fronleichnam in parts of SN/TH, Augsburg) — asserted."),
    ("c06", False, "Private-law payment/declaration deadlines are generated region-independent (place of performance is debatable); fixed dates in "
     "dunning and English letters fall on working days; Werktage periods never end on a Saturday — so no § 193 BGB edge case is labelled."),
    ("c07", True, "Municipal (Land VwVfG) letters come only from Länder whose delivery rule was checked against the Land's own published "
     "law (evals/law/laender.txt); never from Bremen, Rheinland-Pfalz, Saarland or Sachsen-Anhalt, whose text could not be read "
     "(evals/gen/law.py refuses them)."),
    ("c08", False, "region_sensitive=true marks items whose date differs if the Land's holidays are ignored (due_if_region_ignored)."),
    ("c09", True, "Remedy 'klage' (no Vorverfahren): the label is the end of the one-month Klage period (§ 74 Abs. 1 S. 2 VwGO), counted like "
     "the other remedy periods."),
    ("c10", True, "optional_items are dates a letter offers that the reader need not act on (e.g. special-cancellation windows, payments after "
     "Rechtskraft, scam demands); no label requires them."),
    ("c11", False, "expected_due 'ambiguous' (with candidates) marks a slot the letter leaves open between two or more dates; null marks one "
     "the letter gives no date for."),
    ("c12", False, "Photo entries are phone-photo renderings of page 1 of a one-page PDF entry (source_id) and share its truth."),
    ("c13", False, "today = the day the person reads the letter (posting/letter date + 2..6 days); it is not a receipt date."),
    ("c14", False, "Template wording: the test variants (C, D) and the adversarial letters repeat no deadline-bearing sentence of the dev "
     "variants (A, B); only short statutory phrases (e.g. 'vierten Tag nach Aufgabe zur Post') recur."),
    ("c15", False, "Holdout split: variants E, F and the holdout adversarial letters were written from scratch (new senders, recipients, "
     "wording, layout, dates and amounts) before the split's first run; they repeat no deadline-bearing sentence of the dev or test "
     "letters."),
    ("c16", False, "Holdout2 split: variants G, H and the holdout2 adversarial letters were written from scratch (new senders, recipients, "
     "wording, layout, dates, amounts and regions) after the release's last code change; they repeat no deadline-bearing "
     "sentence of the dev, test or holdout letters."),
    ("c17", False, "Holdout3 split: variants I, J and the holdout3 adversarial letters were written from scratch (new senders, recipients, "
     "wording, layout, dates, amounts and regions) after the code freeze; they repeat no deadline-bearing sentence of the dev, "
     "test, holdout or holdout2 letters."),
    ("c18", False, "references list identifiers only; info-block lines holding a dash, a date or a billing month are printed but not labelled."),
    ("c19", False, "amounts = the sums the reader must pay, will receive, or that the decision sets (old/new price for price changes, fees to "
     "bring to an appointment); line items, sums insured and merely threatened penalties are not listed."),
    ("c20", True, "remedy_type follows the letter's own Rechtsbehelfsbelehrung; kind_also_accepted names a second document kind that fits "
     "the letter equally well."),
    ("c21", False, "Consumer contracts under § 309 Nr. 9 BGB / § 56 TKG are generated so that the written minimum term also fits into 24 months "
     "from conclusion — the open question whether the cap counts from conclusion or from the start of service never matters."),
    ("c22", True, "A notice deadline (cancel-by) stays on a Saturday, Sunday or holiday: § 193 BGB does not apply to notice periods "
     "(BGH III ZR 172/04)."),
)  # fmt: skip

# Letters that honestly fit two DocumentKinds (checked by hand in evals/dataset/VERIFICATION.md).
KIND_ALSO_ACCEPTED: dict[str, list[str]] = {
    "test-dunning_fixed-D1": ["dunning"],  # Hausverwaltung payment reminder (labelled rent_lease)
    "test-english_letter-C2": ["utility_bill"],  # serviced-apartment utility statement (rent_lease)
    "test-invoice_relative-D1": ["invoice"],  # Stadtwerke final bill (utility_bill)
    "test-appointment-C1": ["appointment"],  # immigration-office invitation (residence_permit)
    "test-appointment-C2": ["appointment"],  # Jobcenter Meldeaufforderung (social_insurance)
    "test-adversarial-scam-2": ["other"],  # fake Stadtwerke letter (utility_bill)
    "holdout-social_decision-E2": ["social_insurance"],  # Pflegekasse decision (health_insurance)
    "holdout-invoice_relative-F1": ["invoice"],  # annual gas bill with a balance to pay (utility_bill)
    "holdout-appointment-F1": ["appointment"],  # landlord's move-out inspection (rent_lease)
    "holdout-adversarial-scam-2": ["other"],  # fake parcel 'customs fee' demand (invoice)
    "holdout2-social_decision-H1": ["authority_letter"],  # Bezirksamt Wohngeld decision (social_insurance)
    "holdout2-social_decision-H2": ["authority_letter"],  # Jugendamt UVG decision (social_insurance)
    "holdout2-dunning_fixed-H1": ["utility_bill"],  # electricity reminder, disconnection notice (dunning)
    "holdout2-appointment-G1": ["health_insurance"],  # Medizinischer Dienst home visit (appointment)
    "holdout2-appointment-G2": ["authority_letter"],  # police summons of a witness (appointment)
    "holdout2-appointment-H1": ["utility_bill"],  # meter-reading service's visit (appointment)
    "holdout2-year_boundary-G2": ["tax_letter"],  # Familienkasse Kindergeld, EStG (social_insurance)
    "holdout2-year_boundary-H1": ["authority_letter"],  # Versorgungsamt GdB decision (social_insurance)
    "holdout2-adversarial-scam-1": ["other"],  # fake 'data protection register' fee (invoice)
    "holdout2-adversarial-scam-2": ["other"],  # directory 'offer' dressed as an invoice (invoice)
    "holdout3-social_decision-I2": [
        "authority_letter"
    ],  # Amt für Ausbildungsförderung BAföG decision (social_insurance)
    "holdout3-appointment-I2": ["authority_letter"],  # court summons of a witness (appointment)
    "holdout3-english_letter-J2": ["contract"],  # school place offer, sign the enrolment agreement (other)
    "holdout3-year_boundary-I2": ["tax_letter"],  # Familienkasse Kindergeld, EStG (social_insurance)
    "holdout3-year_boundary-I3": [
        "tax_assessment"
    ],  # Arbeitnehmer-Sparzulage set by the Finanzamt (tax_letter)
    "holdout3-adversarial-scam-1": [
        "other"
    ],  # fake debt collector for a lottery-entry 'subscription' (dunning)
    "holdout3-adversarial-scam-2": [
        "other",
        "authority_letter",
    ],  # forged 'Mahnbescheid' from a court-styled sender that is no Amtsgericht (dunning)
    "holdout3-adversarial-missing_date-2": ["social_insurance"],  # Pflegekasse refusal (health_insurance)
}


#: The twelve template families (adversarial letters are one-offs, not a template family).
TEMPLATE_FAMILIES = frozenset(name for name, _ in FAMILIES if name != "adversarial")
_FINAL_CONVENTION_ID = re.compile(r"f\d{2}")
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
#: A contract's scored dates.
CONTRACT_SLOTS = ("expected_current_term_end", "expected_cancel_by")

Builder = Callable[[], "list[Case]"]


class FinalSplitError(ValueError):
    """A final split, or the plug-in that builds it, breaks a rule of the final run (the message names ids, slots
    and dates only)."""


@dataclass(frozen=True)
class FinalPlugin:
    """The final splits' plug-in, ``gen/final.py``, with its tables checked (:func:`final_plugin`)."""

    final_day: date
    valid_until: date
    families: dict[str, tuple[tuple[str, Builder], ...]]
    conventions: list[Convention]
    kind_also_accepted: dict[str, list[str]]

    @property
    def splits(self) -> tuple[str, ...]:
        return tuple(self.families)


def final_plugin(module: Any) -> FinalPlugin:
    """The plug-in's tables from ``module`` (``gen/final.py``), checked: ``FINAL_DAY`` and ``VALID_UNTIL`` (dates,
    in that order), ``FAMILIES`` (each new split's ``(family, builder)`` pairs; a split without template variants
    names no template family), ``CONVENTIONS_FINAL`` (ids ``f01``…) and ``KIND_ALSO_ACCEPTED_FINAL``."""

    def need(name: str) -> Any:
        if not hasattr(module, name):
            raise FinalSplitError(f"the final plug-in defines no {name}")
        return getattr(module, name)

    final_day, valid_until = need("FINAL_DAY"), need("VALID_UNTIL")
    for name, value in (("FINAL_DAY", final_day), ("VALID_UNTIL", valid_until)):
        if type(value) is not date:
            raise FinalSplitError(f"{name} must be a date, not {type(value).__name__}")
    if valid_until < final_day:
        raise FinalSplitError(f"VALID_UNTIL {valid_until} is before FINAL_DAY {final_day}")
    listed = need("FAMILIES")
    if not isinstance(listed, Mapping) or not listed:
        raise FinalSplitError("FAMILIES must map each final split to its (family, builder) pairs")
    families: dict[str, tuple[tuple[str, Builder], ...]] = {}
    for split, pairs in listed.items():
        if split in SPLITS:
            raise FinalSplitError(f"FAMILIES: {split} is a split this module builds itself")
        built = tuple((str(family), builder) for family, builder in pairs)
        names = [family for family, _ in built]
        if not built or len(names) != len(set(names)) or not all(callable(b) for _, b in built):
            raise FinalSplitError(f"FAMILIES[{split!r}]: each family once, each with its builder")
        reused = sorted(set(names) & TEMPLATE_FAMILIES)
        if split not in SPLIT_VARIANTS and reused:
            raise FinalSplitError(
                f"FAMILIES[{split!r}]: {', '.join(reused)} is a template family, and {split} has no template variants"
            )
        families[str(split)] = built
    conventions: list[Convention] = []
    for entry in need("CONVENTIONS_FINAL"):
        if not isinstance(entry, Mapping) or list(entry) != ["id", "disputed", "text"]:
            raise FinalSplitError("CONVENTIONS_FINAL: each entry has an id, disputed and text, in that order")
        id_, disputed, text = entry["id"], entry["disputed"], entry["text"]
        if not isinstance(id_, str) or not _FINAL_CONVENTION_ID.fullmatch(id_):
            raise FinalSplitError(f"CONVENTIONS_FINAL: {id_!r} is not an id like f01")
        if not isinstance(disputed, bool):
            raise FinalSplitError(f"CONVENTIONS_FINAL {id_}: disputed must be true or false")
        if not isinstance(text, str) or not text.strip():
            raise FinalSplitError(f"CONVENTIONS_FINAL {id_}: no text")
        if any(c["id"] == id_ for c in conventions):
            raise FinalSplitError(f"CONVENTIONS_FINAL: {id_} twice")
        conventions.append(Convention(id=id_, disputed=disputed, text=text))
    also = need("KIND_ALSO_ACCEPTED_FINAL")
    if not isinstance(also, Mapping) or not all(
        isinstance(kinds, list) and all(isinstance(kind, str) for kind in kinds) for kinds in also.values()
    ):
        raise FinalSplitError("KIND_ALSO_ACCEPTED_FINAL must map case ids to lists of document kinds")
    return FinalPlugin(
        final_day=final_day,
        valid_until=valid_until,
        families=families,
        conventions=conventions,
        kind_also_accepted={str(case_id): list(kinds) for case_id, kinds in also.items()},
    )


def load_final() -> FinalPlugin | None:
    """The plug-in ``gen/final.py`` when that module exists (it is written after the code freeze), checked; else
    None. It is imported, not named in an import statement, so this file reads the same before and after."""
    name = f"{law.__name__.rpartition('.')[0]}.final"
    if importlib.util.find_spec(name) is None:
        return None
    return final_plugin(importlib.import_module(name))


def all_conventions(final: FinalPlugin | None) -> list[Convention]:
    """The manifest's conventions: :data:`CONVENTIONS`, then the plug-in's own."""
    return [*CONVENTIONS, *(final.conventions if final else [])]


def _day(value: Any) -> date | None:
    """A date the truth states (``YYYY-MM-DD``); None for a missing, null or 'ambiguous' one."""
    return date.fromisoformat(value) if isinstance(value, str) and _ISO_DAY.fullmatch(value) else None


def check_final_case(case: Case, final: FinalPlugin, conventions: Mapping[str, Convention]) -> None:
    """Refuse a final letter that breaks the window: it is read on ``FINAL_DAY``; every scored date (``items``),
    contract term end and cancel-by date, and appointment lies after ``VALID_UNTIL``; every scored item and every
    dated contract names the conventions (``conventions``, ids of ``conventions``) its label rests on, and for a
    disputed one the dates under its other reading (``convention_alternatives``: after the window, never the label
    itself; empty when the other reading gives no other date)."""
    if case.today != final.final_day:
        raise FinalSplitError(f"{case.id}: today is {case.today}, not the final day {final.final_day}")
    first = final.valid_until + timedelta(days=1)

    def after(where: str, day: date) -> None:
        if day < first:
            raise FinalSplitError(
                f"{case.id} {where}: {day} is not after the window (valid until {final.valid_until})"
            )

    truth = case.truth
    for n, item in enumerate(truth["items"]):
        due = _day(item.get("expected_due"))
        if due is not None:
            after(f"items[{n}]", due)
            _check_tags(case.id, f"items[{n}]", item, {"": due}, conventions, after)
    for n, item in enumerate(truth.get("optional_items") or []):
        due = _day(item.get("expected_due"))
        if due is not None and item.get("kind") == "appointment":
            after(f"optional_items[{n}]", due)
    contract = truth.get("contract")
    if contract:
        dates = {slot: day for slot in CONTRACT_SLOTS if (day := _day(contract.get(slot))) is not None}
        for slot, day in dates.items():
            after(f"contract.{slot}", day)
        if dates:
            _check_tags(case.id, "contract", contract, dates, conventions, after)


def _check_tags(
    case_id: str,
    where: str,
    part: Mapping[str, Any],
    labels: Mapping[str, date],
    conventions: Mapping[str, Convention],
    after: Callable[[str, date], None],
) -> None:
    """The convention tags of one scored item (``labels`` keyed "") or one contract (keyed by its slots)."""
    ids = part.get("conventions")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise FinalSplitError(
            f"{case_id} {where}: no list of the conventions its label rests on ('conventions')"
        )
    unknown = [i for i in ids if i not in conventions]
    if unknown:
        raise FinalSplitError(f"{case_id} {where}: unknown conventions {', '.join(unknown)}")
    disputed = [i for i in ids if conventions[i]["disputed"]]
    alternatives = part.get("convention_alternatives")
    if not disputed:
        if alternatives is not None:
            raise FinalSplitError(f"{case_id} {where}: convention_alternatives, but no disputed convention")
        return
    need = f"{case_id} {where}: {', '.join(disputed)} disputed, so convention_alternatives gives the dates under the other reading"
    if "" in labels:
        if not isinstance(alternatives, list):
            raise FinalSplitError(f"{need} (a list)")
        per_slot: Mapping[str, Any] = {"": alternatives}
    else:
        if not isinstance(alternatives, Mapping) or not set(alternatives) <= set(labels):
            raise FinalSplitError(f"{need} (a list per dated slot: {', '.join(labels)})")
        per_slot = alternatives
    for slot, days in per_slot.items():
        if not isinstance(days, list):
            raise FinalSplitError(f"{need} (a list for {slot})")
        seen: set[date] = set()
        for value in days:
            day = _day(value)
            if day is None or day in seen:
                raise FinalSplitError(
                    f"{case_id} {where}: convention_alternatives holds {value!r} (no date, or twice)"
                )
            if day == labels[slot]:
                raise FinalSplitError(
                    f"{case_id} {where}: convention_alternatives holds the label itself ({day})"
                )
            seen.add(day)
            after(f"{where} alternative", day)


def build_cases(final: FinalPlugin | Literal["installed"] | None = "installed") -> list[Case]:
    """Every case: the five splits this module builds and a final plug-in's splits (the installed ``gen/final.py``
    by default, the given one, or none). The twelve template families are complete in every split with template
    variants, and no variant is in two splits; a final split without variants has its own families."""
    plugin = load_final() if isinstance(final, str) else final
    cases: list[Case] = []
    with law.earlier_splits_words():  # their letters keep the words they were written with
        for family, builder in (*FAMILIES, *HOLDOUT_FAMILIES, *HOLDOUT2_FAMILIES, *HOLDOUT3_FAMILIES):
            built = builder()
            assert built, family
            for case in built:
                assert case.family == family, (case.id, family)
            cases.extend(built)
    final_splits = plugin.splits if plugin else ()
    final_ids: set[str] = set()
    for split, pairs in (plugin.families if plugin else {}).items():
        for family, builder in pairs:
            built = builder()
            if not built:
                raise FinalSplitError(f"{split}: the {family} builder made no letter")
            for case in built:
                if (case.split, case.family) != (split, family):
                    raise FinalSplitError(
                        f"{case.id}: built as {split}/{family}, not {case.split}/{case.family}"
                    )
            cases.extend(built)
            final_ids |= {case.id for case in built}
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    kinds = dict(KIND_ALSO_ACCEPTED)
    if plugin:
        stray = sorted(set(plugin.kind_also_accepted) - final_ids)
        if stray:
            raise FinalSplitError(
                f"KIND_ALSO_ACCEPTED_FINAL names no letter of a final split: {', '.join(stray)}"
            )
        kinds |= plugin.kind_also_accepted
    assert set(KIND_ALSO_ACCEPTED) <= set(ids), set(KIND_ALSO_ACCEPTED) - set(ids)
    for case in cases:
        also = kinds.get(case.id, [])
        assert case.truth["kind"] not in also and set(also) <= DOCUMENT_KINDS, case.id
        case.truth["kind_also_accepted"] = also
    assert {c.split for c in cases} == {*SPLITS, *final_splits}
    assert all(c.split != "dev" for c in cases if c.family == "adversarial")
    with_variants = [split for split in (*SPLITS, *final_splits) if split in SPLIT_VARIANTS]
    variants = {
        split: {(c.family, c.variant) for c in cases if c.split == split and c.family != "adversarial"}
        for split in with_variants
    }
    assert {c.family for c in cases if c.family != "adversarial" and c.split in SPLITS} == TEMPLATE_FAMILIES
    for i, split in enumerate(with_variants):
        assert {f for f, _ in variants[split]} == TEMPLATE_FAMILIES, f"{split}: a template family is missing"
        assert {v for _, v in variants[split]} == set(SPLIT_VARIANTS[split]), split
        for other in with_variants[i + 1 :]:
            assert not variants[split] & variants[other], (
                f"a template variant appears in both {split} and {other}"
            )
    if plugin:
        known = {c["id"]: c for c in all_conventions(plugin)}
        for case in cases:
            if case.split in final_splits:
                check_final_case(case, plugin, known)
    return cases


def _entry(
    case: Case,
    file: str,
    data: bytes,
    *,
    pages: int,
    photo: bool,
    source_id: str | None,
    window: tuple[date, date] | None,
) -> dict[str, Any]:
    head = {
        "id": f"{case.id}-photo" if photo else case.id,
        "split": case.split,
        "family": case.family,
        "variant": case.variant,
        "file": file,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "media_type": "image/jpeg" if photo else "application/pdf",
        "photo": photo,
        "source_id": source_id,
        "pages": pages,
        "language": case.truth["language"],
        "today": case.today.isoformat(),
    }
    if window is not None:  # a final split's letter: its planned day and the last day of its window
        head |= {"final_day": window[0].isoformat(), "valid_until": window[1].isoformat()}
    return head | {
        "authority_region": case.authority_region,
        "recipient_region": case.recipient_region,
        "key_phrases": [] if photo else case.key_phrases,
        "hidden_phrases": [] if photo else case.hidden_phrases,
        "notes": case.notes,
        "truth": case.truth,
    }


def environment() -> dict[str, str]:
    """Library versions that determine the output bytes (PDF streams, rasterised photos)."""
    import zlib

    import fontTools
    import fpdf
    import PIL
    import pypdfium2.version as pdfium_version
    from holidays.version import __version__ as holidays_version

    return {
        "fpdf2": fpdf.__version__,
        "pypdfium2": str(pdfium_version.PYPDFIUM_INFO),
        "pdfium": str(pdfium_version.PDFIUM_INFO),
        "pillow": PIL.__version__,
        "zlib": zlib.ZLIB_RUNTIME_VERSION,
        "holidays": holidays_version,
        "fonttools": str(fontTools.version),  # fpdf2 subsets the embedded fonts with it
    }


def write_case(case: Case, out: Path, final: FinalPlugin | None = None) -> list[dict[str, Any]]:
    """Render one case (and its phone photo) into ``out/<split>/`` and return its manifest entries; a letter of
    ``final``'s splits records the planned day and the end of its window."""
    window = (final.final_day, final.valid_until) if final and case.split in final.families else None
    (out / case.split).mkdir(parents=True, exist_ok=True)
    pdf, pages = render_letter(case.letter)
    stem = case.id.removeprefix(f"{case.split}-")
    rel = f"{case.split}/{stem}.pdf"
    (out / rel).write_bytes(pdf)
    entries = [_entry(case, rel, pdf, pages=pages, photo=False, source_id=None, window=window)]
    if case.photo:
        assert pages == 1, f"{case.id}: photos are only taken of one-page letters"
        jpg = phone_photo(pdf, seed_for("photo", case.id))
        rel_photo = f"{case.split}/{stem}-photo.jpg"
        (out / rel_photo).write_bytes(jpg)
        entries.append(_entry(case, rel_photo, jpg, pages=1, photo=True, source_id=case.id, window=window))
    return entries


def generate(out: Path, final: FinalPlugin | Literal["installed"] | None = "installed") -> dict[str, Any]:
    """Write every split's letters and the manifest into ``out``: the five splits above and a final plug-in's (the
    installed ``gen/final.py`` by default, the given one, or none)."""
    plugin = load_final() if isinstance(final, str) else final
    law.cross_check_with_holidays_package(HOLIDAY_YEARS)
    cases = build_cases(plugin)
    splits = (*SPLITS, *(plugin.splits if plugin else ()))
    for split in splits:
        folder = out / split
        folder.mkdir(parents=True, exist_ok=True)
        for stale in [*folder.glob("*.pdf"), *folder.glob("*.jpg")]:
            stale.unlink()
    entries = [entry for case in cases for entry in write_case(case, out, plugin)]
    entries.sort(key=lambda e: (e["split"], e["family"], e["id"]))
    total = sum(e["bytes"] for e in entries)
    assert total < MAX_TOTAL_BYTES, f"dataset too large: {total} bytes"
    counts: dict[str, dict[str, int]] = {}
    for split in splits:
        per_family = Counter(e["family"] for e in entries if e["split"] == split)
        counts[split] = {
            "entries": sum(per_family.values()),
            "photos": sum(1 for e in entries if e["split"] == split and e["photo"]),
            **dict(sorted(per_family.items())),
        }
    manifest = {
        "name": "ordnung-deadline-benchmark",
        "version": 1,
        "generator": "evals/generate.py",
        "environment": environment(),
        "conventions": all_conventions(plugin),
        "counts": counts,
        "total_bytes": total,
        "entries": entries,
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (out / "manifest.json").write_text(text, encoding="utf-8")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="output directory (default: evals/dataset)"
    )
    parser.add_argument(
        "--final-day",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="the final splits' planned day: refused unless it is the plug-in's FINAL_DAY (default: that day)",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    try:
        final = load_final()
    except FinalSplitError as exc:
        parser.exit(1, f"{parser.prog}: the final-split plug-in (gen/final.py): {exc}\n")
    if args.final_day is not None and final is None:
        parser.error("--final-day: there is no final-split plug-in (gen/final.py) to build for that day")
    if final is not None and args.final_day not in (None, final.final_day):
        parser.error(f"--final-day {args.final_day} is not the plug-in's FINAL_DAY {final.final_day}")
    try:
        manifest = generate(args.out, final)
    except FinalSplitError as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")
    if not args.quiet:
        splits = list(manifest["counts"])
        families = sorted({e["family"] for e in manifest["entries"]})
        print(f"{'family':<24}" + "".join(f" {split:>8}" for split in splits) + "   (photos included)")
        for family in families:
            row = [
                sum(1 for e in manifest["entries"] if e["family"] == family and e["split"] == split)
                for split in splits
            ]
            print(f"{family:<24}" + "".join(f" {n:>8}" for n in row))
        c = manifest["counts"]
        print(
            f"{'total':<24}"
            + "".join(f" {c[split]['entries']:>8}" for split in splits)
            + "   photos: "
            + ", ".join(f"{split} {c[split]['photos']}" for split in splits)
        )
        if final is not None:
            print(
                f"final splits {', '.join(final.splits)}: read on {final.final_day}, valid until {final.valid_until}"
            )
        print(f"size: {manifest['total_bytes'] / 1e6:.1f} MB → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
