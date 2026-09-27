"""The "get advice" card of a high-stakes letter: what it is, what to do, the facts code can check,
and who helps for free or little money (SPEC § 21 "Remedies & letters").

Information, not legal advice. The card never says what the person *should* decide; it says what
the law sets, what Ordnung computed (always with its limits) and where to get real advice:

* court orders and a dismissal are ``urgent``: the card always shows, with the public help first
  (the court's *Rechtsantragstelle*, *Beratungshilfe*, debt advice, a union or an employment lawyer);
* a landlord's notice, a rent increase and an operating-cost statement show it as information with
  the tenants' association (*Mieterverein*).

Computed facts, each with the policy that keeps it honest:

* **Time-bar** (§§ 195, 199 BGB): claims from :func:`~ordnung.rules.consumer.latest_barred_year` or
  earlier *may* be time-barred — never "are": the period can be paused, and only a court decides.
* **Rent cap** (§ 558 Abs. 3 BGB): the increase from the amounts the model read, compared exactly (in
  cents) with 15 % and 20 % — the caps are limits in euros, so 15.04 % is above 15 %; the percentage is
  only rounded for display (two decimals near a cap), and a card above a cap names the highest rent it allows. The cap counts from the rent three years ago and without operating costs, so a
  result within the cap is only "within the cap as far as these amounts show".
* **Late statement** (§ 556 Abs. 3 BGB, :func:`~ordnung.rules.tenancy.statement_check`): the billing
  period is read from the letter's text (:func:`billing_period`): every date range in it that ended
  before the statement arrived ("01.07.2024 – 30.06.2025", "vom 1. Januar 2025 bis 31. Dezember 2025",
  "2025-01-01 bis 2025-12-31", "Januar bis Dezember 2025"), and every billing year ("Abrechnungsjahr
  2024", "Abrechnungszeitraum 2023/2024", "Betriebskostenabrechnung für das Jahr 2025", in the reading's
  title "Operating-cost statement 2025"), taken to end on 31 December of its last year. The latest end
  wins, because a later end only makes the deadline later; a billing year gives way to a range that ends
  in it or later (the range says which months the year covers). A range written next to "Vorjahr" or
  "Vergleich" is the previous year's comparison (§ 6a HeizkostenV): when it is the latest, this
  statement's own period was missed, and nothing is claimed. A statement is called late only when it
  certainly is: only a range the letter calls its billing period ("Abrechnungszeitraum", "für den
  Zeitraum vom …") can decide; from any other range or a billing year it is at most "probably late —
  check the billing period", and "on time" is only certain when neither the weekend/holiday shift of the
  deadline nor an unknown Land decided it. Without a period, nothing is claimed. The statement arrived on
  the day the person entered, else on its own date — and when the text dates the statement whose billing
  period it names before the letter's own date ("aus unserer Betriebskostenabrechnung 2023 vom
  15.11.2024": after the period ended, with its year, or with no year in a letter that prints no billing
  period of its own), the letter is a later one about it (a reminder, a reply to objections), so that
  earlier date counts, never confirmed (:func:`statement_arrival`). A letter that prints its own billing
  period is the statement: an earlier date in it for an enclosure (the metering company's heating
  statement) or another year's statement never replaces its arrival.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from ordnung.models import AdviceFact, HelpLink, Item, LetterAdvice
from ordnung.rules import catalog
from ordnung.rules.consumer import latest_barred_year
from ordnung.rules.explain import fmt_date
from ordnung.rules.tenancy import (
    RENT_CAP_PERCENT,
    RENT_CAP_TIGHT_MARKET_PERCENT,
    cap_limit,
    exceeds_cap,
    month_end,
    rent_increase_percent,
    statement_check,
)

# -------------------------------------------------------------------------------------------- help

COURT_DESK = HelpLink(
    name="Rechtsantragstelle at the Amtsgericht",
    what=(
        "Free. Staff write down your objection for you (zu Protokoll) and explain the next steps — bring the "
        "letter and its envelope. Best at the court that issued it: at another Amtsgericht the objection only "
        "counts once their record reaches that court (§ 129a Abs. 3 S. 2 ZPO), so go early."
    ),
    url="https://www.justizadressen.nrw.de/de/justiz/suche",
)
LEGAL_AID = HelpLink(
    name="Beratungshilfe (legal advice on a low income)",
    what="A lawyer's advice for a small fee if you have little money; apply at your local Amtsgericht.",
    url="https://service.justiz.de/beratungshilfe",
)
DEBT_ADVICE = HelpLink(
    name="Schuldnerberatung (free debt advice)",
    what="Recognised debt advice centres check claims and help you answer them, free of charge.",
    url="https://www.meine-schulden.de/",
)
CONSUMER_ADVICE = HelpLink(
    name="Verbraucherzentrale",
    what="Consumer advice centres help with dubious claims, contracts and withdrawals for a small fee.",
    url="https://www.verbraucherzentrale.de/",
)
UNION = HelpLink(
    name="Your trade union",
    what="If you are a member, the union's legal service advises and represents you at the labour court.",
    url="https://www.dgbrechtsschutz.de/",
)
EMPLOYMENT_LAWYER = HelpLink(
    name="A lawyer for employment law (Fachanwalt für Arbeitsrecht)",
    what="At the labour court's first instance each side pays its own lawyer, whatever the outcome.",
    url="https://anwaltauskunft.de/",
)
LABOUR_COURT_OBJECTION = HelpLink(
    name="Office of the labour court (Rechtsantragstelle)",
    what=(
        "Free. Staff take down your objection for you (zu Protokoll) — bring the order and its envelope. Go to "
        "the labour court that issued it, and go at once: you only have one week."
    ),
    url="https://www.justizadressen.nrw.de/de/justiz/suche",
)
LABOUR_COURT_DESK = HelpLink(
    name="Rechtsantragstelle of the labour court",
    what="Free. They take down your court action (Klage) for you — you don't need a lawyer to file it.",
    url="https://www.justizadressen.nrw.de/de/justiz/suche",
)
JOB_AGENCY = HelpLink(
    name="Agentur für Arbeit",
    what=(
        "Register as job-seeking online, by phone (0800 4 5555 00, free) or in person — and, by your first day "
        "without work, as unemployed (online or in person)."
    ),
    url=(
        "https://www.arbeitsagentur.de/arbeitslos-arbeit-finden/arbeitslosengeld/"
        "ihre-schritte-wenn-sie-arbeitslos-werden/wie-sie-sich-arbeitsuchend-melden"
    ),
)
TENANTS = HelpLink(
    name="Mieterverein (tenants' association)",
    what="Members get tenancy advice and help with letters; membership is usually a few euros a month.",
    url="https://www.mieterbund.de/",
)
ONLINE_OBJECTION = HelpLink(
    name="Online objection (online-mahnantrag.de)",
    what="The courts' official site: object online with your ID card, or print a barcode form to sign and post.",
    url="https://www.online-mahnantrag.de/",
)

# ---------------------------------------------------------------------------------------- policies

_MONTHS = {
    **dict.fromkeys(("januar", "jänner", "jan"), 1),
    **dict.fromkeys(("februar", "feb"), 2),
    **dict.fromkeys(("märz", "maerz", "mär", "mrz"), 3),
    **dict.fromkeys(("april", "apr"), 4),
    **dict.fromkeys(("mai",), 5),
    **dict.fromkeys(("juni", "jun"), 6),
    **dict.fromkeys(("juli", "jul"), 7),
    **dict.fromkeys(("august", "aug"), 8),
    **dict.fromkeys(("september", "sept", "sep"), 9),
    **dict.fromkeys(("oktober", "okt"), 10),
    **dict.fromkeys(("november", "nov"), 11),
    **dict.fromkeys(("dezember", "dez"), 12),
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_YEAR4 = r"(?:19|20)\d{2}"
#: A day or a month as a statement writes the ends of its period: ``01.01.2025`` (or ``01.01.``),
#: ``2025-01-01``, ``1. Januar 2025``, ``01/2025``, ``Januar 2025`` (or ``Januar``).
_DATE_TOKEN = re.compile(
    rf"(?<![\d.])(?P<iy>{_YEAR4})-(?P<im>\d{{1,2}})-(?P<id>\d{{1,2}})(?![\d-])"
    rf"|(?<![\d.])(?P<nd>\d{{1,2}})\.(?P<nm>\d{{1,2}})\.(?P<ny>\d{{4}}|\d{{2}}(?!\d))?"
    rf"|(?<![\d.])(?P<wd>\d{{1,2}})\.\s*(?P<wm>{_MONTH})\b\.?(?:\s+(?P<wy>{_YEAR4})(?!\d))?"
    rf"|(?<![\d./])(?P<sm>\d{{1,2}})/(?P<sy>{_YEAR4})(?![\d/])"
    rf"|(?<![\w.])(?P<mm>{_MONTH})\b\.?(?:\s+(?P<my>{_YEAR4})(?!\d))?",
    re.I,
)
_RANGE_SEPARATOR = re.compile(r"\s*(?:-|–|—|bis(?:\s+(?:zum|einschließlich|einschl\.))?)\s*", re.I)
#: What names a range as the billing period, right before it: "Abrechnungszeitraum:", "für den Zeitraum
#: vom", "Abrechnungsjahr 2023/2024 (", "Betriebskostenabrechnung vom" (the comparison below excludes
#: "Vorjahresabrechnung" and the like).
_PERIOD_LABEL = re.compile(
    r"(?:abrechnungs(?:zeitraum|periode|jahr)|\bzeitraum|billing period|abrechnung(?:\s+für\s+die\s+zeit)?)"
    rf"(?:[^\S\n]+{_YEAR4}(?:\s*/\s*(?:19|20)?\d{{2}})?)?[^\S\n]*[:(]?\s*(?:(?:vom|von|from)\s+)?$",
    re.I,
)
#: A previous year's figures, which a statement must show next to its own (§ 6a HeizkostenV).
_COMPARISON = re.compile(r"vorjahr|vergleich|vorperiode|previous|prior|last year", re.I)
#: A billing year: "Abrechnungsjahr 2024", "Abrechnungszeitraum 2023/2024", "Betriebskostenabrechnung für
#: das Jahr 2025", "Heizkostenabrechnung 2025" — or, in the reading's title, "Operating-cost statement 2025".
_YEAR_RE = re.compile(
    rf"(?:abrechnung|statement\b|billing (?:year|period)\b)[^\d\n]{{0,30}}?\b({_YEAR4})(?!\d)"
    r"(?:\s*/\s*((?:19|20)?\d{2})(?!\d))?",
    re.I,
)


@dataclass(frozen=True)
class BillingPeriod:
    """The billing period a statement names (policy above): its last day, whether that day is the
    letter's own (``exact``, a date range) or the end of a billing year assumed to be 31 December, how
    the letter writes it (for a reply's subject), and whether the letter calls the range its billing
    period (``labelled``) — only then can the check be sure."""

    end: date
    exact: bool
    text: str
    labelled: bool = False


@dataclass(frozen=True)
class _Candidate:
    period: BillingPeriod
    comparison: bool  # written next to "Vorjahr", "Vergleich": the previous year's figures


#: What a later letter writes before the date of the statement it is about: "Betriebskostenabrechnung 2023
#: vom 15.11.2024", "Ihre Abrechnung vom 15. November 2024" — not "Abrechnungszeitraum vom …", and a
#: range after it ("Abrechnung vom 01.01.2024 bis 31.12.2024") is a billing period, not a date.
_STATEMENT_OF = re.compile(r"abrechnung\b[^.\n]{0,40}?\bvom\s+", re.I)


def _year(value: str) -> int:
    return int(value) if len(value) == 4 else 2000 + int(value)


def _token_parts(match: re.Match[str]) -> tuple[int | None, int, int | None]:
    """``(day, month, year)`` of a date token; a month without a day has day ``None``."""
    g = match.groupdict()
    if g["iy"]:
        return int(g["id"]), int(g["im"]), int(g["iy"])
    if g["nd"]:
        return int(g["nd"]), int(g["nm"]), _year(g["ny"]) if g["ny"] else None
    if g["wd"]:
        return int(g["wd"]), _MONTHS[g["wm"].casefold()], int(g["wy"]) if g["wy"] else None
    if g["sm"]:
        return None, int(g["sm"]), int(g["sy"])
    return None, _MONTHS[g["mm"].casefold()], int(g["my"]) if g["my"] else None


def _before_range(text: str, start: int) -> str:
    """The text before a range on its line — or the line before, when the range starts a line (a label
    above its value) — at most 60 characters."""
    line = text.rfind("\n", 0, start) + 1
    if not text[line:start].strip():
        line = text.rfind("\n", 0, max(line - 1, 0)) + 1
    return text[max(line, start - 60) : start]


def _ranges(text: str, before: date | None) -> list[_Candidate]:
    """Every date range in ``text`` that ended by ``before``."""
    found: list[_Candidate] = []
    for first, second in pairwise(_DATE_TOKEN.finditer(text)):
        if not _RANGE_SEPARATOR.fullmatch(text, first.end(), second.start()):
            continue
        d1, m1, y1 = _token_parts(first)
        d2, m2, y2 = _token_parts(second)
        if y2 is None:
            continue
        try:
            end = date(y2, m2, d2 if d2 is not None else month_end(date(y2, m2, 1)).day)
            start = date(y1 if y1 is not None else y2, m1, d1 or 1)
        except ValueError:
            continue
        if y1 is None and start > end:
            start = start.replace(year=start.year - 1)
        if start >= end or (before is not None and end > before):
            continue
        context = _before_range(text, first.start())
        period = BillingPeriod(
            end, True, f"{start:%d.%m.%Y} – {end:%d.%m.%Y}", labelled=bool(_PERIOD_LABEL.search(context))
        )
        found.append(_Candidate(period, bool(_COMPARISON.search(context[-45:]))))
    return found


def _years(text: str) -> list[_Candidate]:
    """Every billing year ``text`` names, taken to end on 31 December of its last year."""
    found: list[_Candidate] = []
    for match in _YEAR_RE.finditer(text):
        first, second = match.groups()
        last = _year(second) if second else int(first)
        if second and not int(first) < last <= int(first) + 1:
            continue  # "2024/12" is not a split year
        context = _before_range(text, match.start())[-25:] + match.group()
        period = BillingPeriod(date(last, 12, 31), False, f"{first}/{second}" if second else first)
        found.append(_Candidate(period, bool(_COMPARISON.search(context))))
    return found


def billing_period(text: str, *, before: date | None = None) -> BillingPeriod | None:
    """The billing period an operating-cost statement names (policy above), or ``None``.

    ``before`` is the day the statement arrived (or its date): a range that ends later can't be its
    billing period (a new prepayment period, say) and is left out. ``None`` also when the latest period
    the letter names is the previous year's comparison: then this statement's own period wasn't found.
    """
    ranges = _ranges(text, before)
    years = [
        year
        for year in _years(text)
        if not any(r.period.end.year >= year.period.end.year and not r.comparison for r in ranges)
    ]
    candidates = [*ranges, *years]
    if not candidates:
        return None
    latest = max(
        candidates,
        key=lambda c: (c.period.end, not c.comparison, c.period.labelled, c.period.exact),
    )
    return None if latest.comparison else latest.period


def _dated_statements(text: str) -> list[tuple[date, int | None]]:
    """Every full date ``text`` gives a statement ("… Betriebskostenabrechnung 2023 vom 15.11.2024"), with
    the billing year the words before it name (``2023``; ``None`` for "Ihre Abrechnung vom …") — never the
    start of a billing period ("Abrechnung vom 01.01.2024 bis …")."""
    found: list[tuple[date, int | None]] = []
    for label in _STATEMENT_OF.finditer(text):
        token = _DATE_TOKEN.match(text, label.end())
        if token is None:
            continue
        day, month, year = _token_parts(token)
        separator = _RANGE_SEPARATOR.match(text, token.end())
        if day is None or year is None or (separator and _DATE_TOKEN.match(text, separator.end())):
            continue
        try:
            dated = date(year, month, day)
        except ValueError:
            continue
        named = _YEAR_RE.search(label.group())
        billing_year = None if named is None else _year(named[2]) if named[2] else int(named[1])
        found.append((dated, billing_year))
    return found


def statement_date(text: str) -> date | None:
    """The earliest full date ``text`` gives an operating-cost statement ("… Betriebskostenabrechnung 2023
    vom 15.11.2024"), or ``None`` — never the start of a billing period ("Abrechnung vom 01.01.2024 bis …")."""
    return min((dated for dated, _ in _dated_statements(text)), default=None)


def statement_arrival(
    text: str, arrived: date | None, confirmed: bool, letter_date: date | None
) -> tuple[date | None, bool]:
    """``(arrival, confirmed)`` of the statement a letter is or is about (policy above): the day the letter
    arrived (``arrived``, ``confirmed`` when the person entered it) — unless its text dates *the statement
    whose billing period it names* before the letter's own date (``letter_date``). Then the letter is a
    later one about that statement (a reminder, a reply to objections), and the statement's date is the
    earliest it can have arrived; the day this letter arrived says nothing about it.

    A date is the statement's only when it is after that billing period ended (a statement is written
    after its period; an earlier one is a previous year's) and the words before it name that period's year
    ("Betriebskostenabrechnung 2023 vom …") — or name no year while the letter prints no billing period of
    its own ("Abrechnungszeitraum: …"): a letter that does is the statement itself, and a date in it
    belongs to something it encloses (the metering company's "Heizkostenabrechnung der Techem vom …").
    Another year's statement ("das Guthaben aus der Abrechnung 2023 vom …") never counts. Missed: an
    enclosure dated with the statement's own year ("Heizkostenabrechnung 2024 der Techem vom …")."""
    if letter_date is None:
        return arrived, confirmed
    prints_own_period = any(found.period.labelled for found in _ranges(text, None))
    for dated, billing_year in sorted(_dated_statements(text), key=lambda found: found[0]):
        period = billing_period(text, before=dated)
        if dated >= letter_date or period is None or period.end >= dated:
            continue
        if (billing_year == period.end.year) if billing_year is not None else not prints_own_period:
            return dated, False
    return arrived, confirmed


def _time_bar(today: date) -> AdviceFact:
    year = latest_barred_year(today)
    return AdviceFact(
        title="Old claims may be time-barred",
        text=(
            f"Most claims become time-barred three years after the end of the year they arose. A claim from "
            f"{year} or earlier may be time-barred — but only if you say so (a court doesn't check it), and "
            "steps like this order can pause the period. Get advice before you rely on it."
        ),
        tone="info",
        citation=catalog.citation("bgb_195"),
    )


def _rent_cap(old: float | None, new: float | None) -> AdviceFact:
    percent = rent_increase_percent(old, new) if old is not None and new is not None else None
    citation = catalog.citation("bgb_558_3")
    if percent is None:
        return AdviceFact(
            title="Check the rent cap (Kappungsgrenze)",
            text=(
                f"Within three years the rent may rise by at most {RENT_CAP_PERCENT:.0f} % "
                f"({RENT_CAP_TIGHT_MARKET_PERCENT:.0f} % in many cities), and it must have been unchanged for "
                "15 months. We couldn't read the old and new rent to check it."
            ),
            citation=citation,
        )
    assert old is not None and new is not None  # a percentage needs both
    amounts = f"€{old:,.2f} → €{new:,.2f}"
    basis = (
        "The cap counts from the rent three years ago and without operating costs — if these amounts include "
        "them, or the rent rose in the last three years, the real increase is higher."
    )
    # the caps are limits in euros: compared exactly, the percentage is only rounded for display
    exact = (new - old) / old * 100
    near_a_cap = any(0 < abs(exact - cap) < 0.05 for cap in (RENT_CAP_PERCENT, RENT_CAP_TIGHT_MARKET_PERCENT))
    shown = f"{exact:.2f}" if near_a_cap else f"{percent:.1f}"
    if exceeds_cap(old, new, RENT_CAP_PERCENT):
        tone, verdict = (
            "warn",
            f"more than the {RENT_CAP_PERCENT:.0f} % cap (at most €{cap_limit(old, RENT_CAP_PERCENT):,.2f}) — "
            "this may not be allowed",
        )
    elif exceeds_cap(old, new, RENT_CAP_TIGHT_MARKET_PERCENT):
        tone, verdict = (
            "warn",
            f"within the {RENT_CAP_PERCENT:.0f} % cap, but more than the {RENT_CAP_TIGHT_MARKET_PERCENT:.0f} % cap "
            f"that many cities have (at most €{cap_limit(old, RENT_CAP_TIGHT_MARKET_PERCENT):,.2f}; e.g. Berlin, "
            "Hamburg, Munich) — check whether yours does",
        )
    else:
        tone, verdict = "good", "within both caps as far as these amounts show"
    return AdviceFact(
        title=f"Rent rises by {shown} %",
        text=f"{amounts}: {verdict}. {basis}",
        tone=tone,
        citation=citation,
    )


#: What a late operating-cost statement's back-payment says on its to-do (Ordnung never dismisses it).
LATE_STATEMENT_WARNING = (
    "This back-payment may not be owed: the statement seems to have arrived after its twelve-month deadline "
    "(§ 556 Abs. 3 S. 3 BGB — see the card on the letter). Check before you pay."
)


#: What a rent increase's payment to-dos say (the model often reads the new total as a payment): the higher
#: rent is only owed once the person agrees, and paying it can count as agreeing (§ 558b Abs. 1 BGB). The
#: receipt keeps it after the person decided, so it says what holds either way.
RENT_INCREASE_PAYMENT_WARNING = (
    "The higher rent is only owed once you agree to the increase (§ 558b Abs. 1 BGB), and paying it can count "
    "as agreeing. If you haven't agreed yet, decide first — until then your current rent stays due."
)


def statement_late(text: str, arrived: date | None, confirmed: bool, region: str | None) -> bool:
    """Whether the card calls an operating-cost statement too late, or probably too late (its billing period
    in ``text`` ended more than twelve months before ``arrived``): then its back-payment may not be owed
    (§ 556 Abs. 3 S. 3 BGB), and its payment to-dos say so (:data:`LATE_STATEMENT_WARNING`)."""
    period = billing_period(text, before=arrived) if arrived is not None else None
    if period is None or arrived is None:
        return False
    return statement_check(period.end, arrived, confirmed=confirmed, region=region).late is True


def _statement(text: str, arrived: date | None, confirmed: bool, region: str | None) -> AdviceFact:
    period = billing_period(text, before=arrived) if arrived is not None else None
    citation = catalog.citation("bgb_556_3")
    if period is None or arrived is None:
        return AdviceFact(
            title="Was it on time?",
            text=(
                "A statement must arrive within twelve months after the billing period ends; after that you "
                "usually owe no back-payment. We couldn't find the billing period in the letter to check."
            ),
            citation=citation,
        )
    check = statement_check(period.end, arrived, confirmed=confirmed, region=region)
    deadline = fmt_date(check.deadline)
    if not period.labelled:
        assumed = (
            f"The letter names the period {period.text} but doesn't call it the billing period. If it is, "
            f"the statement had to arrive by {deadline}."
            if period.exact
            else f"The letter names the billing year ({period.text}) but not its dates. If the period ended "
            f"on {fmt_date(period.end)}, the statement had to arrive by {deadline}."
        )
        if check.late:
            return AdviceFact(
                title="Probably too late — check the billing period",
                text=(
                    f"{assumed} It arrived later, so you may owe no back-payment (Nachzahlung). Check the "
                    "period's dates in the statement and ask a tenants' association before you rely on it."
                ),
                tone="warn",
                citation=citation,
            )
        arrival = "It arrived before that" if check.late is False else "Its date is before that"
        return AdviceFact(
            title="Probably on time",
            text=f"{assumed} {arrival}; the billing period's exact dates would tell for sure.",
            citation=citation,
        )
    when = (
        f"The billing period ended on {fmt_date(period.end)}, so the statement had to arrive by {deadline}."
    )
    if check.late:
        return AdviceFact(
            title="This statement came too late",
            text=(
                f"{when} It arrived later, so you probably owe no back-payment (Nachzahlung) — unless the "
                "landlord wasn't responsible for the delay. A credit (Guthaben) is still yours. A tenants' "
                "association can help you reply."
            ),
            tone="warn",
            citation=citation,
        )
    if check.late is None:
        return AdviceFact(
            title="Probably on time",
            text=f"{when} Its date is before that; tell us when it arrived to be sure.",
            citation=citation,
        )
    if check.arrived > check.raw_deadline:
        region_note = (
            " We don't know your Land, so we counted a holiday in any Land."
            if region is None and check.deadline != check.raw_deadline
            else ""
        )
        return AdviceFact(
            title="Probably on time",
            text=(
                f"It arrived after {fmt_date(check.raw_deadline)}, the end of the twelfth month after the billing "
                f"period ({fmt_date(period.end)}). It only counts as on time because that day was a weekend or "
                f"holiday and the deadline moved to {deadline} — whether that rule (§ 193 BGB) applies here is "
                f"disputed.{region_note} Ask a tenants' association if a back-payment is at stake."
            ),
            citation=citation,
        )
    return AdviceFact(title="On time", text=f"{when} It arrived in time.", tone="good", citation=citation)


# -------------------------------------------------------------------------------------------- cards


def _labour_court_order(kind: str, today: date, delivered: str | None, *, handled: bool) -> LetterAdvice:
    """The card of a labour court's order: like a civil court's, but with one week (§ 46a Abs. 3, § 59
    ArbGG) and the labour court's own office — its orders can't be answered at online-mahnantrag.de."""
    step = (
        []
        if handled
        else [
            delivered
            or "Find the delivery date on the yellow envelope and enter it as the day the letter arrived."
        ]
    )
    if kind == "court_payment_order":
        return LetterAdvice(
            kind=kind,
            title="Labour court payment order (Mahnbescheid) — act within one week",
            summary=(
                "A labour court sent this on behalf of someone who says you owe them money, often an employer "
                "reclaiming pay. The court has not checked whether that is true. At a labour court you have only "
                "one week from delivery to pay or object (Widerspruch)."
            ),
            urgent=not handled,
            handled=handled,
            steps=[
                *step,
                "If you don't owe the money, or not all of it, object on the enclosed form and send it to the "
                "labour court at once, or have it taken down at the court's office. You don't have to give reasons.",
                "If you do owe it, pay the claimant — not the court — including the costs listed.",
                "Get advice today: your union, an employment lawyer or the court's office.",
            ],
            facts=[_time_bar(today)],
            help=[LABOUR_COURT_OBJECTION, UNION, EMPLOYMENT_LAWYER, LEGAL_AID],
            rule_ids=["arbgg_46a", "zpo_180", "zpo_222", "bgb_195"],
        )
    return LetterAdvice(
        kind=kind,
        title="Labour court enforcement order (Vollstreckungsbescheid) — one week to object",
        summary=(
            "This order can be enforced right away, like a judgment. At a labour court you have one week from "
            "delivery to object (Einspruch), and this period can't be extended."
        ),
        urgent=not handled,
        handled=handled,
        steps=[
            *step,
            "To object, write to the labour court that issued the order — not by e-mail — or make it for the "
            "record at the court's office.",
            "An objection doesn't stop enforcement by itself; ask for advice about suspending it.",
            "If you do owe the money, paying it stops further enforcement costs.",
        ],
        facts=[_time_bar(today)],
        help=[LABOUR_COURT_OBJECTION, UNION, EMPLOYMENT_LAWYER, LEGAL_AID],
        rule_ids=["arbgg_59", "zpo_180", "zpo_222", "bgb_195"],
    )


#: What paying rent arrears in time undoes (§ 569 Abs. 3 Nr. 2 BGB): only the notice without notice period,
#: and not when that already happened within two years (S. 2) — never a notice with a period given as well
#: (BGH, 19.09.2018, VIII ZR 231/17 and VIII ZR 261/17).
ARREARS_CURE = (
    "paying all of them — at the latest two months after an eviction suit is served — can undo the notice "
    "without notice period (not if that already happened within the last two years), but not a notice with a "
    "notice period given as well"
)
#: § 549 Abs. 2 BGB: no hardship objection (§§ 574–575) and no consent procedure (§§ 557–561) for these.
_SHORT_LET = "a short let or a furnished room in the flat your landlord lives in (§ 549 Abs. 2 BGB)"
#: §§ 574–574b BGB are rules for a home (Wohnraum); other premises follow § 578 BGB, without them.
_NOT_A_HOME = "a garage, parking space or business premises let on its own (§ 578 BGB)"


def _notice_without_period(alternative: bool) -> AdviceFact:
    """What a landlord's notice without notice period means for the hardship objection."""
    if alternative:
        text = (
            "The hardship objection doesn't apply to a notice without notice period, only to the notice the "
            "landlord gives with a notice period in the alternative (hilfsweise) — object to that one in time. "
            f"If it is for rent arrears, {ARREARS_CURE}. Get advice at once."
        )
    else:
        text = (
            "The hardship objection doesn't apply to it, so Ordnung doesn't draft one. If it is for rent "
            f"arrears, {ARREARS_CURE}. Get advice at once."
        )
    return AdviceFact(
        title="This reads as a notice without notice period (fristlos)",
        text=text,
        tone="warn",
        citation="§ 574 Abs. 1 S. 2 BGB; § 569 Abs. 3 Nr. 2 BGB",
    )


def _no_objection_todo(end_unknown: bool, passed: bool) -> str:
    """The step of a landlord's card when no to-do carries the objection (and the notice has a period)."""
    if passed:
        return (
            "Your tenancy would end less than two months after this letter was written, so the day an objection "
            "had to reach the landlord (two months before the end) had already passed: there is no to-do for it. "
            "A notice this short may have the wrong notice period (a landlord's is usually about three months, "
            "§ 573c Abs. 1 BGB). If the landlord didn't tell you in time about your right to object, you can still object "
            "at the first hearing of an eviction suit (§ 574b Abs. 2 S. 2 BGB). Get advice now."
        )
    if end_unknown:
        return (
            "We couldn't read when your tenancy ends, so there is no to-do for the objection. Find the end in "
            "the notice (or ask): an objection must reach the landlord two months before it (§ 574b Abs. 2 BGB)."
        )
    return (
        "There is no to-do for the objection. It must reach the landlord at the latest two months before the "
        "tenancy ends (§ 574b Abs. 2 BGB) — check the end date in the notice."
    )


def _unless(handled: bool, step: str) -> list[str]:
    """A step that asks for the delivery day, left out once the letter is handled."""
    return [] if handled else [step]


#: A to-do still to act on (missed and snoozed ones are not closed).
_OPEN = ("open", "missed", "snoozed")


def settles(card: LetterAdvice, items: Sequence[Item]) -> bool:
    """Whether the person has dealt with a high-stakes letter, for its card's ``handled``: every to-do that
    carries its legal deadline is closed (done or dismissed), and there is one. Those are the to-dos the
    law added (``origin`` "rule") and the ones whose receipt cites a rule of the card (the letter's own
    objection date, a court order's periods, a late statement's back-payment) — never another to-do of the
    letter: paying the arrears a notice without notice period demands, a handover appointment, returning a
    laptop after a dismissal. :func:`letter_advice` adds that a landlord's notice without such a to-do is
    never handled."""
    rules = set(card.rule_ids)
    carrying = [
        item
        for item in items
        if item.origin == "rule" or (item.computation is not None and rules & set(item.computation.rule_ids))
    ]
    return bool(carrying) and not any(item.status in _OPEN for item in carrying)


def letter_advice(
    kind: str | None,
    *,
    today: date,
    arrived: date | None = None,
    arrival_confirmed: bool = False,
    letter_date: date | None = None,
    region: str | None = None,
    old_amount: float | None = None,
    new_amount: float | None = None,
    text: str = "",
    extraordinary: bool = False,
    alternative: bool = False,
    labour_court: bool = False,
    objection_todo: bool = True,
    end_unknown: bool = False,
    objection_passed: bool = False,
    handled: bool = False,
) -> LetterAdvice | None:
    """The card for a letter of ``kind`` (``None`` for kinds without one).

    ``arrived`` is the confirmed arrival day, or else the letter's date; ``arrival_confirmed`` whether
    the person entered it (then the card doesn't ask for it again); ``letter_date`` the letter's own date
    (a statement's text may date the statement earlier, :func:`statement_arrival`); ``region`` the
    person's Land;
    ``old_amount``/``new_amount`` the rent before and after an increase as read; ``text`` the letter's
    text (for the billing period). ``extraordinary``: a landlord's notice reads as one without notice
    period, ``alternative`` with one in the alternative too — only then is a hardship objection offered.
    ``objection_todo``: a to-do carries the objection to a landlord's notice (§ 574b BGB) — the law's, or
    the letter's own objection date. Without one the card is urgent (shown first) and says why:
    ``end_unknown`` (the notice's end wasn't read), ``objection_passed`` (the end is less than two months
    after the letter, so the objection date had passed when it was written), or else no reason Ordnung
    knows. ``handled``: the person has closed every to-do that carries the letter's legal deadline
    (:func:`settles`), so the card is no longer urgent and says so (``LetterAdvice.handled``) — it stays as
    information without asking for the delivery day, and the verdict says the letter is filed instead of
    "get advice now". A landlord's notice that no to-do carries the objection for (``objection_todo``
    false) or that reads as one without notice period is never handled: paying the arrears or a handover
    appointment doesn't deal with it — a notice without notice period is always urgent.
    ``labour_court``: a court order from a labour court, which gives one week (§ 46a Abs. 3, § 59 ArbGG).
    """
    if kind == "landlord_notice" and (extraordinary or not objection_todo):
        handled = False
    delivered = (
        "The period counts from the delivery date you entered, or from an earlier start the letter names "
        "(see “Why this date?”) — check it matches the yellow envelope."
        if arrival_confirmed
        else None
    )
    if kind in ("court_payment_order", "enforcement_order") and labour_court:
        return _labour_court_order(kind, today, delivered, handled=handled)
    if kind == "court_payment_order":
        return LetterAdvice(
            kind=kind,
            title="Court payment order (Mahnbescheid) — act within two weeks",
            summary=(
                "A court sent this on behalf of someone who says you owe them money. The court has not checked "
                "whether that is true. Within two weeks of delivery you either pay or object (Widerspruch); "
                "otherwise the claimant can get an enforcement order and have the money collected."
            ),
            urgent=not handled,
            handled=handled,
            steps=[
                *_unless(
                    handled,
                    delivered
                    or "Find the delivery date on the yellow envelope and enter it as the day the letter arrived.",
                ),
                "If you don't owe the money, or not all of it, object on the enclosed form (or online) and send "
                "it to the court. You don't have to give reasons.",
                "If you do owe it, pay the claimant — not the court — including the costs listed.",
                "Check it's real: a genuine order comes from a court in a yellow envelope, never by e-mail.",
            ],
            facts=[_time_bar(today)],
            help=[COURT_DESK, ONLINE_OBJECTION, DEBT_ADVICE, LEGAL_AID],
            rule_ids=["zpo_692", "zpo_180", "zpo_222", "bgb_195"],
        )
    if kind == "enforcement_order":
        return LetterAdvice(
            kind=kind,
            title="Enforcement order (Vollstreckungsbescheid) — two weeks to object",
            summary=(
                "This court order can be enforced right away, like a judgment. You have two weeks from delivery "
                "to object (Einspruch), and this period can't be extended."
            ),
            urgent=not handled,
            handled=handled,
            steps=[
                *_unless(
                    handled,
                    delivered
                    or "Find the delivery date on the yellow envelope (or the bailiff's papers) and enter it.",
                ),
                "To object, write to the court that issued the order — not by e-mail — or go to its "
                "Rechtsantragstelle. Another Amtsgericht can take it down too, but it only counts once their "
                "record reaches the issuing court, so go early.",
                "An objection doesn't stop enforcement by itself; ask for advice about suspending it.",
                "If you do owe the money, paying it stops further enforcement costs.",
            ],
            facts=[_time_bar(today)],
            help=[COURT_DESK, LEGAL_AID, DEBT_ADVICE],
            rule_ids=["zpo_339", "zpo_180", "zpo_222", "zpo_129a", "bgb_195"],
        )
    if kind == "dismissal":
        return LetterAdvice(
            kind=kind,
            title="Dismissal — three weeks to go to court",
            summary=(
                "If you think this dismissal is wrong, only a court action at the labour court "
                "(Kündigungsschutzklage) within three weeks of receiving it keeps your rights. After that it "
                "counts as valid, even if it wasn't."
            ),
            urgent=not handled,
            handled=handled,
            steps=[
                *_unless(
                    handled,
                    "The three weeks count from the day you received it, which you entered — check it's right."
                    if arrival_confirmed
                    else "Enter the day you received the dismissal — the three weeks count from then.",
                ),
                "Get advice today: your union, an employment lawyer or the labour court's Rechtsantragstelle.",
                "Register as job-seeking at the Agentur für Arbeit in time (see the to-do).",
                "That doesn't replace registering as unemployed (arbeitslos melden): do that too, online or in "
                "person, at the latest on your first day without work — unemployment benefit is only paid from "
                "then (§ 141 SGB III).",
                "Don't sign anything else, like a termination agreement, before you have had advice.",
                "Apprentices: you don't have to register (§ 38 Abs. 1 S. 4 SGB III), and if your chamber has a "
                "conciliation board (Schlichtungsausschuss, § 111 Abs. 2 ArbGG) it must hear the case before the "
                "court — ask your chamber or union at once.",
            ],
            help=[UNION, EMPLOYMENT_LAWYER, LABOUR_COURT_DESK, LEGAL_AID, JOB_AGENCY],
            rule_ids=["kschg_4", "sgb3_38", "sgb3_141"],
        )
    if kind == "landlord_notice":
        steps = [
            "Don't agree to move out or sign anything before you have had advice.",
            "If you object, keep proof that it arrived; a letter is safest, text form is enough since 2025.",
            "If the landlord didn't tell you in time about your right to object, its form and its deadline, "
            "you can still object at the first hearing of an eviction suit (§ 574b Abs. 2 S. 2 BGB).",
            f"There is no hardship objection for {_NOT_A_HOME}, nor for {_SHORT_LET} — ask a tenants' "
            "association.",
        ]
        if not extraordinary:
            steps.append(
                "A notice without notice period (fristlos) can't be met with this objection. If it is for rent "
                f"arrears (§ 569 Abs. 3 Nr. 2 BGB), {ARREARS_CURE}. Get advice at once."
            )
        if not objection_todo and not extraordinary:
            steps.insert(0, _no_objection_todo(end_unknown, objection_passed))
        return LetterAdvice(
            kind=kind,
            title="Notice from your landlord — get advice before you act",
            summary=(
                "A tenants' association can check whether the notice is valid (form, reason, period). If moving "
                "out would be a hardship, you can object and ask to stay; the objection must reach the landlord "
                "at the latest two months before the tenancy ends."
            ),
            urgent=(extraordinary or not objection_todo) and not handled,
            handled=handled,
            steps=steps,
            facts=[_notice_without_period(alternative)] if extraordinary else [],
            help=[TENANTS, LEGAL_AID],
            rule_ids=["bgb_574b", "bgb_549"],
            draft="objection" if alternative or not extraordinary else None,
        )
    if kind == "rent_increase":
        return LetterAdvice(
            kind=kind,
            title="Rent increase request — you decide",
            summary=(
                "Your landlord asks you to agree to a higher rent. You have until the end of the second calendar "
                "month after the month you received the request to decide (received in January: until 31 March), "
                "and the higher rent is only owed if you agree."
            ),
            steps=[
                "Check the new rent against your city's rent index (Mietspiegel), if it has one.",
                "You can agree to all or part of the increase; paying the new rent can count as agreeing.",
                f"These rules don't apply to {_SHORT_LET} or a student hall (§ 549 Abs. 3 BGB) — ask a tenants' "
                "association.",
            ],
            facts=[_rent_cap(old_amount, new_amount)],
            help=[TENANTS],
            handled=handled,
            rule_ids=["bgb_558b", "bgb_558_3", "bgb_549"],
        )
    if kind == "operating_costs":
        # a later letter about an old statement: the statement's own date, not this letter's arrival
        arrived, arrival_confirmed = statement_arrival(text, arrived, arrival_confirmed, letter_date)
        # a late statement's back-payment may not be owed: the card comes first and says so before "pay"
        late = statement_late(text, arrived, arrival_confirmed, region)
        return LetterAdvice(
            kind=kind,
            title="Operating-cost statement (Betriebskostenabrechnung)",
            summary=(
                "You can ask to see the receipts behind the statement, and object to mistakes within twelve "
                "months of receiving it."
            ),
            urgent=late and not handled,
            handled=handled,
            steps=[
                *(
                    ["Don't pay a back-payment before you have checked whether this statement came too late."]
                    if late
                    else []
                ),
                "Compare the costs with last year's statement and your lease.",
                "Ask to see the receipts (Belegeinsicht) if something looks wrong — Ordnung can draft the letter.",
            ],
            facts=[_statement(text, arrived, arrival_confirmed, region)],
            help=[TENANTS, CONSUMER_ADVICE],
            rule_ids=["bgb_556_3"],
            draft="receipts_inspection",
        )
    return None


def billing_period_text(text: str, *, before: date | None = None) -> str | None:
    """The billing period as the letter names it (``01.01.2025 – 31.12.2025``, or a billing year), for
    a reply's subject; ``before`` as in :func:`billing_period`."""
    period = billing_period(text, before=before)
    return period.text if period else None
