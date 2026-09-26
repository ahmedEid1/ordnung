"""Deemed delivery (*Bekanntgabefiktion*) of letters from German authorities.

Which law applies depends on the sender (``scope``):

* ``ao`` — tax offices and other tax authorities (§ 122 Abs. 2, 2a, § 122a Abs. 4 AO). The deemed day
  moves to the next working day if it is a Saturday, Sunday or holiday (§ 108 Abs. 3 AO,
  BFH IX R 68/98, AEAO zu § 108 Nr. 2).
* ``vwvfg`` — general authorities such as the immigration office (§ 41 Abs. 2, 2a VwVfG and the
  Länder VwVfGs). The deemed day does **not** move (prevailing case law); only the end of the
  following period shifts.
* ``sgbx`` — social authorities and statutory health insurers (§ 37 Abs. 2, 2a SGB X). No shift of
  the deemed day (BSG B 14 AS 12/09 R).

Since the PostModG, items posted from 1 January 2025 count as delivered on the 4th day after posting
(3rd day before). Earlier actual receipt never makes the date earlier; later actual receipt is
handled by the caller (:mod:`ordnung.rules.deadlines`), which keeps the earlier, safe date.
A Postzustellungsurkunde (yellow envelope) has no fiction at all: the date written on the envelope is
the delivery day, which callers pass as an explicit anchor date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from ordnung.models import ComputationStep
from ordnung.rules import calendar_de, catalog
from ordnung.rules.explain import fmt_date, reason_phrase
from ordnung.rules.periods import add_months

DeliveryScope = Literal["ao", "vwvfg", "sgbx"]
DeliveryChannel = Literal["post", "electronic", "portal"]

#: First posting day under the 4-day rule (PostModG, Art. 97 § 1 Abs. 15 EGAO).
FOUR_DAY_RULE_FROM = date(2025, 1, 1)

_SCOPE_BY_PARTY_KIND: dict[str, DeliveryScope] = {
    "tax_office": "ao",
    "health_insurer": "sgbx",
    "immigration_office": "vwvfg",
    "authority": "vwvfg",
    "university": "vwvfg",
    "public_broadcaster": "vwvfg",
}

_SCOPE_LABEL: dict[DeliveryScope, str] = {
    "ao": "tax",
    "vwvfg": "general administrative",
    "sgbx": "social-law",
}

_RULE_BY_SCOPE_CHANNEL: dict[tuple[DeliveryScope, DeliveryChannel], str] = {
    ("ao", "post"): "ao_122_2_1",
    ("ao", "electronic"): "ao_122_2a",
    ("ao", "portal"): "ao_122a_4",
    ("vwvfg", "post"): "vwvfg_41_2",
    ("vwvfg", "electronic"): "vwvfg_41_2",
    ("vwvfg", "portal"): "vwvfg_41_2a",
    ("sgbx", "post"): "sgbx_37_2",
    ("sgbx", "electronic"): "sgbx_37_2",
    ("sgbx", "portal"): "sgbx_37_2a",
}

_ORDINAL = {3: "3rd", 4: "4th"}

#: Länder whose own VwVfG uses the 4-day rule, with the first posting day it is confirmed for (legal
#: research checked 2026-09-25): BY, NW, HH and MV amended their laws for 1 Jan 2025, BW only from
#: 7 Feb 2025 (GBl. 2025 Nr. 8; § 102b LVwVfG keeps 3 days for procedures begun earlier); BE, BB, NI,
#: RP, SN and ST refer to the federal VwVfG. For SH (§ 110 LVwG) the 4th day is confirmed in the text
#: as of 10 Jun 2025 but not its start date, so earlier postings keep the 3rd day. Hessen still showed
#: the 3rd day; HB, SL and TH were not confirmed — for them (and when the Land is unknown) the
#: conservative 3rd day is used (SPEC § 21).
VWVFG_FOUR_DAY_FROM: dict[str, date] = {
    **dict.fromkeys(("BY", "NW", "HH", "MV", "BE", "BB", "NI", "RP", "SN", "ST"), FOUR_DAY_RULE_FROM),
    "BW": date(2025, 2, 7),
    "SH": date(2025, 6, 10),
}


#: Party kinds a reader may give a social-benefits agency: its name and remedy notice decide.
_REFINABLE_KINDS = frozenset({"authority", "university", "insurer", "company", "other"})

#: Senders that decide under the Social Code, so § 37 SGB X governs delivery (§ 1 SGB X; the benefits
#: of § 68 SGB I such as BAföG, Wohngeld, Elterngeld and Kinderzuschlag included). Letters and readers
#: usually call them just "authority".
_SOCIAL_SENDER = re.compile(
    r"jobcenter|agentur\s+f(?:ü|ue)r\s+arbeit|arbeitsagentur|rentenversicherung|pflegekasse|"
    r"krankenkasse|unfallkasse|berufsgenossenschaft|sozialamt|sozialhilfe|versorgungsamt|"
    r"bafög|bafoeg|ausbildungsförderung|wohngeld|elterngeld",
    re.IGNORECASE,
)

#: A remedy notice that names the social courts or the Social Code.
_SOCIAL_REMEDY = re.compile(r"sozialgericht|\bSGG\b|\bSGB\b", re.IGNORECASE)

#: The Familienkasse decides child benefit under the EStG (tax law: *Einspruch*, AO) and under the
#: BKGG, e.g. Kinderzuschlag (social law: *Widerspruch*, SGB X); the remedy tells them apart.
_FAMILY_BENEFITS_OFFICE = re.compile(r"familienkasse", re.IGNORECASE)

#: Party kinds that are never a German authority. ``other`` (the kind of an unknown sender) is not
#: one of them, nor are the kinds with a delivery law.
PRIVATE_KINDS: frozenset[str] = frozenset(
    {
        "insurer",
        "bank",
        "landlord",
        "employer",
        "utility",
        "telecom",
        "retailer",
        "doctor",
        "gym",
        "transport",
        "person",
        "company",
    }
)

#: *Einspruch*, *Widerspruch* and *Klage* lie against an administrative act (a tax office or a statutory
#: health insurer filed as ``company`` or ``insurer``) but also in private law: a tenant's Widerspruch
#: (§ 574 BGB), an insurance contract's (§ 5 VVG), the Kündigungsschutzklage against an employer
#: (§ 4 KSchG), the Einspruch against a court's Vollstreckungsbescheid (§ 700 ZPO) — and firms such as
#: private parking operators call their own complaint window an "Einspruch". A sender filed as private
#: that names one is in doubt: it shows an authority's decision only with a remedy notice that says so
#: (:data:`_ADMINISTRATIVE_ROUTE`); otherwise the period runs from arrival, the earlier start.
_ROUTE_REMEDIES = frozenset({"einspruch", "widerspruch", "klage"})
#: A remedy notice that shows an administrative act: it names an administrative, social or finance
#: court or the codes they apply, a *Bescheid* (not a court's Mahn- or Vollstreckungsbescheid), its
#: *Bekanntgabe* or a *Verwaltungsakt*. Private law says *Zugang*, and its courts are the Amts-,
#: Land- and Arbeitsgericht.
_ADMINISTRATIVE_ROUTE = re.compile(
    r"verwaltungsgericht|sozialgericht|finanzgericht|(?-i:\b(?:VwGO|SGG|FGO|AO|SGB|VwVfG)\b)|"
    r"(?<!mahn)(?<!vollstreckungs)bescheid|bekanntgabe|bekanntgegeben|verwaltungsakt",
    re.IGNORECASE,
)


def scope_for_party_kind(
    kind: str | None,
    *,
    name: str | None = None,
    remedy_type: str | None = None,
    remedy_text: str | None = None,
) -> DeliveryScope | None:
    """Delivery scope for a sender (``Party.kind``, ``Party.name``), or ``None`` if not an authority.

    ``tax_office`` → ``ao``; ``health_insurer`` → ``sgbx``; ``immigration_office``, ``authority``,
    ``university`` and ``public_broadcaster`` → ``vwvfg``. A sender filed as an ``authority`` (or a
    ``university``, ``insurer``, ``company``, ``other``) is refined by its name and the letter's remedy
    notice:
    job centres, pension, care and accident insurance, social welfare and the § 68 SGB I benefit
    offices, or a notice naming the Sozialgericht or the SGB → ``sgbx``; the Familienkasse → ``ao``
    when the remedy is an *Einspruch*, otherwise ``sgbx``.
    """
    if kind in _REFINABLE_KINDS or kind is None:
        sender = name or ""
        if _FAMILY_BENEFITS_OFFICE.search(sender):
            return "ao" if remedy_type == "einspruch" else "sgbx"
        if _SOCIAL_SENDER.search(sender) or _SOCIAL_REMEDY.search(remedy_text or ""):
            return "sgbx"
    return _SCOPE_BY_PARTY_KIND.get(kind) if kind else None


def is_private_sender(
    kind: str | None,
    *,
    scope: DeliveryScope | None,
    remedy_type: str | None = None,
    remedy_text: str | None = None,
) -> bool:
    """Whether a letter's sender is known not to be a German authority, so no deemed delivery applies.

    Deemed delivery (§ 122 AO, § 41 VwVfG, § 37 SGB X) is a rule for authorities' letters; a letter
    from a company, a landlord, a bank or an employer takes effect when it arrives (§ 130 Abs. 1 BGB).
    True only for a :data:`PRIVATE_KINDS` sender that ``scope`` (:func:`scope_for_party_kind`, from
    its kind, name and remedy notice) does not make an authority and whose letter shows no
    administrative act: it names an *Einspruch*, *Widerspruch* or *Klage* only without a remedy
    notice (``remedy_text``) naming an administrative route — an employer's letter naming the
    Kündigungsschutzklage, or a parking firm's "Einspruch" window, stays private. An unknown sender
    (``None``, ``other``) is not known to be private: it keeps the earliest plausible deemed delivery.
    """
    if scope is not None or kind not in PRIVATE_KINDS:
        return False
    return remedy_type not in _ROUTE_REMEDIES or not _ADMINISTRATIVE_ROUTE.search(remedy_text or "")


def fiction_days(posted: date) -> int:
    """4 for items posted from 1 January 2025 (PostModG), 3 before."""
    return 4 if posted >= FOUR_DAY_RULE_FROM else 3


@dataclass(frozen=True)
class Delivery:
    """Result of :func:`resolve_delivery`: the deemed delivery day and how it was found."""

    day: date
    raw_day: date
    steps: list[ComputationStep]
    uncertainty: str | None = None


def _step(label: str, d: date, rule_id: str) -> ComputationStep:
    return ComputationStep(
        label=label, date=d.isoformat(), rule_id=rule_id, citation=catalog.citation(rule_id)
    )


def resolve_delivery(
    posted: date,
    *,
    scope: DeliveryScope | None,
    channel: DeliveryChannel = "post",
    region: str | None = None,
    abroad: bool = False,
) -> Delivery:
    """Deemed delivery day with explanation steps; ``scope=None`` means the sender type is unknown.

    For an unknown scope the conservative variant is used: the day is not moved off weekends. For
    general authorities (and unknown senders) the 3rd day is used unless the Land's own law is known to
    use the 4th (:data:`VWVFG_FOUR_DAY_FROM`, SPEC § 21); ``uncertainty`` then explains why. Portal
    provision (``channel="portal"``) by a general authority or an unknown sender counts from the day
    after download (§ 41 Abs. 2a VwVfG), taking ``posted`` — the day it was made available — as the
    earliest download; tax (§ 122a Abs. 4 AO) and social-law portals (§ 37 Abs. 2a SGB X) use the 4th day.
    ``region`` is the sender's Land for general authorities; for tax letters it decides which
    holidays move the deemed day (pass it only when it applies at the recipient's place too).
    """
    uncertainty: str | None = None
    if scope == "ao" and abroad:
        raw = add_months(posted, 1)
        rule_id = "ao_122_2_2"
        label = f"Sent abroad: counts as delivered one month after posting, on {fmt_date(raw)}"
    elif scope in ("vwvfg", None) and channel == "portal":
        # § 41 Abs. 2a VwVfG: the day after download; the earliest download is the day of provision.
        raw = posted + timedelta(days=1)
        rule_id = "vwvfg_41_2a"
        label = f"Counts as delivered the day after it was downloaded — at the earliest {fmt_date(raw)}"
    else:
        days = fiction_days(posted)
        rule_id = _RULE_BY_SCOPE_CHANNEL[(scope, channel)] if scope else "delivery_scope_unknown"
        land_from = VWVFG_FOUR_DAY_FROM.get(calendar_de.normalize_region(region) or "")
        if days == 4 and scope in (None, "vwvfg") and (land_from is None or posted < land_from):
            days, rule_id = 3, "vwvfg_land_days"
            uncertainty = (
                "Some Länder may still use the 3-day rule for their authorities and we couldn't confirm this "
                "sender's, so we counted 3 days (the earlier date)."
            )
        raw = posted + timedelta(days=days)
        what = {"post": "posting", "electronic": "sending", "portal": "being made available"}[channel]
        label = f"Counts as delivered on the {_ORDINAL[days]} day after {what}: {fmt_date(raw)}"
    steps = [_step(label, raw, rule_id)]
    if scope == "ao":
        day = calendar_de.next_business_day(raw, region)
        if day != raw:
            why = reason_phrase(calendar_de.day_kind(raw, region))
            steps.append(
                _step(
                    f"{fmt_date(raw)} is {why}, so delivery moves to {fmt_date(day)}",
                    day,
                    "ao_fiction_shift",
                )
            )
        return Delivery(day=day, raw_day=raw, steps=steps)
    if not calendar_de.is_business_day(raw, region):
        kind = f"{_SCOPE_LABEL[scope]} letters" if scope else "letters from this kind of sender"
        steps.append(
            _step(
                f"For {kind} this day does not move, even though it is "
                f"{reason_phrase(calendar_de.day_kind(raw, region))}",
                raw,
                rule_id,
            )
        )
    return Delivery(day=raw, raw_day=raw, steps=steps, uncertainty=uncertainty)


def deemed_delivery(
    posted: date,
    *,
    scope: DeliveryScope,
    channel: DeliveryChannel = "post",
    region: str | None = None,
    abroad: bool = False,
) -> tuple[date, list[ComputationStep]]:
    """Day a letter from an authority legally counts as delivered, with explanation steps.

    ``posted`` is the day it was posted, sent or made available (the letter's date is the
    conservative stand-in). ``region`` is the recipient's Land for the tax-law weekend/holiday shift
    (``None`` → nationwide holidays only). ``abroad`` only changes tax letters (one month,
    § 122 Abs. 2 Nr. 2 AO); for other senders there is no statutory rule for letters sent abroad, so
    the domestic count is used as an estimate.
    """
    result = resolve_delivery(posted, scope=scope, channel=channel, region=region, abroad=abroad)
    return result.day, result.steps
