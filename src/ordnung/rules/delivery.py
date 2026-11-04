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
(3rd day before). Earlier actual receipt never makes the date earlier — except an e-mailed decision of a
Brandenburg authority, which counts from the day it arrived (§ 7 VwVfGBbg); later actual receipt is
handled by the caller (:mod:`ordnung.rules.deadlines`), which keeps the earlier, safe date.
A Postzustellungsurkunde (yellow envelope) has no fiction at all: the date written on the envelope is
the delivery day, which callers pass as an explicit anchor date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final, Literal

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

#: Länder whose own law (or the federal VwVfG it refers to) counts the 4th day, from the first posting day. Checked
#: against the Länder gazettes on 4 Nov 2026 (docs/deadline-rules.md § 5): BY (Art. 41 BayVwVfG), NW (§ 41 VwVfG NRW;
#: § 97 keeps the old law only for a step begun before, and posting is the step), MV, BE (§ 1 VwVfG Bln, dynamic),
#: BB (§ 1 VwVfGBbg), NI (§ 1 NVwVfG), SN (§ 1 SächsVwVfZG, dynamic), SH (§ 110 Abs. 2 LVwG; Art. 2 Abs. 2 of the act
#: of 13 Dec 2024) and TH (§ 1 ThürVwVfG, dynamic, in force 1 Jan 2025) from 1 January 2025. HH from 14 May 2025
#: (HmbGVBl. Nr. 17 of 13 May 2025 S. 338; Art. 54 of its constitution). BW from 7 Feb 2025 (GBl. 2025 Nr. 8). RP and ST
#: are taken to refer to the federal VwVfG (research of 2026-09-25; their gazettes could not be reached). Before a
#: Land's day its old law counts the 3rd day.
VWVFG_FOUR_DAY_FROM: dict[str, date] = {
    **dict.fromkeys(("BY", "NW", "MV", "BE", "BB", "NI", "RP", "SN", "ST", "SH", "TH"), FOUR_DAY_RULE_FROM),
    "HH": date(2025, 5, 14),
    "BW": date(2025, 2, 7),
}

#: Länder whose own law is confirmed to keep the 3rd day (§ 41 Abs. 2 HVwVfG, checked 4 Nov 2026).
VWVFG_THREE_DAYS: Final = frozenset({"HE"})

#: Baden-Württemberg, Bavaria and Mecklenburg-Vorpommern keep the old law's 3rd day for a matter begun before their
#: switch and not finished (§ 102b LVwVfG, Art. 98 BayVwVfG, § 120a VwVfG M-V, checked 4 Nov 2026): the provision,
#: and the switch as a note writes it.
VWVFG_OLD_PROCEDURES: Final[dict[str, tuple[str, str]]] = {
    "BW": ("§ 102b LVwVfG", "7 February 2025"),
    "BY": ("Art. 98 BayVwVfG", "1 January 2025"),
    "MV": ("§ 120a VwVfG M-V", "1 January 2025"),
}


#: Why a general authority's letter counts as delivered on the 3rd day although its Land may count the 4th: Bremen's
#: and the Saarland's rule could not be checked, or the Land isn't known. Receipts carry it as a warning, and
#: :func:`ordnung.rules.deadlines.waits_for_sender_land` reads it back.
LAND_DAYS_UNCONFIRMED: Final = (
    "Some Länder may still use the 3-day rule for their authorities and we couldn't confirm this sender's, "
    "so we counted 3 days (the earlier date)."
)

#: Party kinds a reader may give a social-benefits agency: its name and remedy notice decide.
_REFINABLE_KINDS = frozenset({"authority", "university", "insurer", "company", "other"})

#: Senders that decide under the Social Code, so § 37 SGB X governs delivery (§ 1 SGB X; the benefits
#: of § 68 SGB I such as BAföG, Wohngeld, Elterngeld and Kinderzuschlag included). Letters and readers
#: usually call them just "authority". Statutory health insurers that go by their brand rather than
#: "Krankenkasse" are named for the largest ones (together most of the insured): the AOKs, Die Techniker
#: (TK), BARMER, DAK-Gesundheit, the IKKs and BKKs, KKH, hkk, HEK, SBK, VIACTIV, BIG direkt gesund,
#: mhplus, Knappschaft and SVLFG. The list is not complete: an unlisted one filed as an ``insurer`` or a
#: ``company`` counts as private, but a late arrival never makes its date later than an authority's
#: letter would count as delivered (:data:`MAY_BE_PUBLIC_KINDS`), so it errs early, never late.
_SOCIAL_SENDER = re.compile(
    r"jobcenter|agentur\s+f(?:ü|ue)r\s+arbeit|arbeitsagentur|rentenversicherung|pflegekasse|"
    r"krankenkasse|unfallkasse|berufsgenossenschaft|sozialamt|sozialhilfe|versorgungsamt|"
    r"bafög|bafoeg|ausbildungsförderung|wohngeld|elterngeld|"
    r"\bAOK\b|die\s+techniker\b|\bbarmer\b|\bDAK\b|\bIKK\b|\bBKK\b|\bKKH\b|\bhkk\b|viactiv|"
    r"\bBIG\s+direkt\b|\bmhplus\b|knappschaft|gesundheitskasse|ersatzkasse|\bSVLFG\b|"
    # short brands other firms share (TK Maxx, SBK Immobilien): only as the whole name or in brackets
    r"(?-i:^\s*(?:TK|HEK|SBK)\s*$|\((?:TK|HEK|SBK)\))",
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

#: Private kinds a public body may be filed as: a municipal utility (a Stadtwerk's or Zweckverband's
#: Gebührenbescheid), a statutory insurer whose name gives no sign, a civil servant's Dienstherr as an
#: ``employer``, any ``company``. For them that the sender is no authority is only inferred, so a late
#: arrival never makes a date later than deemed delivery would (``private_sender_late_arrival``,
#: :func:`ordnung.rules.deadlines.may_be_public`). A gym, a landlord, a bank or a shop issues no
#: Bescheid: its letter counts from the day it arrived, unless the period's own words name one.
MAY_BE_PUBLIC_KINDS: frozenset[str] = frozenset({"company", "insurer", "utility", "employer"})

#: *Einspruch*, *Widerspruch* and *Klage* lie against an administrative act (a tax office or a statutory
#: health insurer filed as ``company`` or ``insurer``) but also in private law: a tenant's Widerspruch
#: (§ 574 BGB), an insurance contract's (§ 5 VVG), the Kündigungsschutzklage against an employer
#: (§ 4 KSchG), the Einspruch against a court's Vollstreckungsbescheid (§ 700 ZPO) — and firms such as
#: private parking operators call their own complaint window an "Einspruch". A sender filed as private
#: that names one is in doubt: it shows an authority's decision only with a remedy notice that says so
#: (:data:`_ADMINISTRATIVE_ROUTE`); otherwise the period runs from arrival — for a sender of a kind a
#: public body may be filed as (:data:`MAY_BE_PUBLIC_KINDS`), never later than an authority's letter
#: would count as delivered: the earlier start in either reading.
_ROUTE_REMEDIES = frozenset({"einspruch", "widerspruch", "klage"})
#: Words that show an administrative act: an administrative, social or finance court or the codes they
#: apply, a *Bekanntgabe* or a *Verwaltungsakt*, or a *Bescheid* as the decision it names — a compound
#: (*Gebührenbescheid*, *Widerspruchsbescheid*; not a court's Mahn- or Vollstreckungsbescheid), "diesen
#: Bescheid", "Ihren Bescheid", "Bescheid vom …". Not the everyday "Bescheid geben / sagen / wissen" (let
#: someone know) or "wie bereits bekanntgegeben" (as announced), which any firm writes. Private law says
#: *Zugang*, and its courts are the Amts-, Land- and Arbeitsgericht.
_ADMINISTRATIVE_ROUTE = re.compile(
    r"verwaltungsgericht|sozialgericht|finanzgericht|(?-i:\b(?:VwGO|SGG|FGO|AO|SGB|VwVfG)\b)|"
    r"(?<=\w)(?<!mahn)(?<!vollstreckungs)(?<!un)bescheid(?:e?s|en?)?\b|"
    r"(?:\b(?:diese[nmrs]?|den|der|dem|des)|(?-i:\bIhr(?:e[nmrs])?))\s+bescheid(?:e?s|e)?\b|"
    r"\bbescheid(?:e?s)?\s+vom\b|bekanntgabe|verwaltungsakt",
    re.IGNORECASE,
)


def shows_administrative_act(text: str | None) -> bool:
    """Whether ``text`` (a remedy notice, a period's own sentence) names an administrative route
    (:data:`_ADMINISTRATIVE_ROUTE`). A remedy notice that does makes an *Einspruch*, *Widerspruch* or
    *Klage* an authority's (:func:`is_private_sender`); a period's own words only show that the sender
    may be one (:func:`ordnung.rules.deadlines.may_be_public`) — a firm too may write "Bekanntgabe"."""
    return bool(text and _ADMINISTRATIVE_ROUTE.search(text))


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
    job centres, pension, care and accident insurance, statutory health insurers (a "Krankenkasse", or
    by their brand: AOK, Die Techniker, BARMER, DAK, IKK, BKK …), social welfare and the § 68 SGB I
    benefit offices, or a notice naming the Sozialgericht or the SGB → ``sgbx``; the Familienkasse →
    ``ao`` when the remedy is an *Einspruch*, otherwise ``sgbx``.
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
    A period whose own words show an administrative act still counts from arrival, but a late arrival
    never makes its date later than deemed delivery would (:func:`ordnung.rules.deadlines.may_be_public`).
    """
    if scope is not None or kind not in PRIVATE_KINDS:
        return False
    return remedy_type not in _ROUTE_REMEDIES or not shows_administrative_act(remedy_text)


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
    #: In BW, BY and MV after their switch: the Land and the day a letter of an older matter counts as delivered.
    older_matter: tuple[str, date] | None = None


def _brandenburg_email(posted: date, fiction: date, arrived: date | None) -> tuple[str, str | None]:
    """The step label, and the note when the arrival day isn't known, for an e-mailed decision of a Brandenburg
    authority, which counts from the day it arrived (§ 7 VwVfGBbg): at the earliest the day it was sent."""
    if arrived is not None and arrived >= posted:
        return f"Counts as delivered on the day it arrived (§ 7 VwVfGBbg): {fmt_date(arrived)}", None
    label = (
        "Counts as delivered on the day it arrived (§ 7 VwVfGBbg) — at the earliest the day it was sent: "
        f"{fmt_date(posted)}"
    )
    if arrived is not None:
        return label, None
    return label, (
        "In Brandenburg an e-mailed decision counts from the day it arrived when that can be shown (§ 7 VwVfGBbg), "
        f"so we counted from the day it was sent, {fmt_date(posted)}, the earliest it can have arrived. If the "
        f"authority can't show when it arrived, it counts as delivered on {fmt_date(fiction)}, and the deadline may "
        f"be up to {(fiction - posted).days} days later."
    )


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
    arrived: date | None = None,
) -> Delivery:
    """Deemed delivery day with explanation steps; ``scope=None`` means the sender type is unknown.

    For an unknown scope the conservative variant is used: the day is not moved off weekends. For
    general authorities (and unknown senders) the Land's own day counts: the 4th from its switch
    (:data:`VWVFG_FOUR_DAY_FROM`), the 3rd before it and in Hessen (:data:`VWVFG_THREE_DAYS`); for Bremen, the
    Saarland or an unknown Land the earlier 3rd day, and ``uncertainty`` says why (SPEC § 21). In
    Baden-Württemberg, Bavaria and Mecklenburg-Vorpommern after their switch the 4th day counts, and
    ``older_matter`` gives the 3rd, which a matter begun before the switch keeps (:data:`VWVFG_OLD_PROCEDURES`). Portal
    provision (``channel="portal"``) by a general authority or an unknown sender counts from the day
    after download (§ 41 Abs. 2a VwVfG), taking ``posted`` — the day it was made available — as the
    earliest download; tax (§ 122a Abs. 4 AO) and social-law portals (§ 37 Abs. 2a SGB X) use the 4th day.
    ``region`` is the sender's Land for general authorities; for tax letters it decides which
    holidays move the deemed day (pass it only when it applies at the recipient's place too). An e-mailed
    decision of a Brandenburg authority counts from the day it arrived (§ 7 VwVfGBbg): ``arrived``, the day the
    person confirmed, when it is before the 4th day, else the day it was sent, with a note that says so.
    """
    uncertainty: str | None = None
    older: tuple[str, date] | None = None
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
        land = calendar_de.normalize_region(region)
        land_from = VWVFG_FOUR_DAY_FROM.get(land or "")
        if days == 4 and scope in (None, "vwvfg"):
            if land in VWVFG_THREE_DAYS or (land_from is not None and posted < land_from):
                days, rule_id = 3, "vwvfg_land_days"  # the Land's own law: HE; HH and BW before their day
            elif land_from is None:
                days, rule_id, uncertainty = 3, "vwvfg_land_days", LAND_DAYS_UNCONFIRMED  # HB, SL, unknown
            elif land in VWVFG_OLD_PROCEDURES:
                older = (land, posted + timedelta(days=3))  # the old law's day, for a matter begun before
        raw = posted + timedelta(days=days)
        what = {"post": "posting", "electronic": "sending", "portal": "being made available"}[channel]
        label = f"Counts as delivered on the {_ORDINAL[days]} day after {what}: {fmt_date(raw)}"
        # § 7 VwVfGBbg: an e-mailed decision that arrived before the 4th day counts from the day it arrived
        earliest = posted if arrived is None else max(arrived, posted)
        if scope in (None, "vwvfg") and channel == "electronic" and land == "BB" and earliest < raw:
            label, uncertainty = _brandenburg_email(posted, raw, arrived)
            raw, rule_id = earliest, "vwvfg_bb_7"
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
    return Delivery(day=raw, raw_day=raw, steps=steps, uncertainty=uncertainty, older_matter=older)


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
