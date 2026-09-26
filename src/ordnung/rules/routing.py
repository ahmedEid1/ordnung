"""Which rules a high-stakes letter's dates follow (ADR 0002, ADR 0007, ADR 0008).

The model reads, code decides. The extraction prompt and schema stay as they were recorded, so the
model never names these letters itself; code recognises them from its reading with the three short
written policies below, and cases they do not decide are documented limitations, not bugs.

**1. The kind of letter** (:func:`classify_letter`), from structured parts of the reading first:

=========================  ============================================================================
``court_payment_order``    three signals, with no list of exceptions: (a) the sender is a court
``enforcement_order``      (:func:`is_court`: a kind of court by name, *Amtsgericht*, *des
                           Arbeitsgerichts*, or its abbreviation before a place of a word or two, *AG
                           Hagen*, from a sender read as an authority (or ``other``) — not a company,
                           *LG Electronics Deutschland GmbH*, *OLG Immobilien*, a bailiff,
                           *Gerichtsvollzieher bei dem Amtsgericht …*, or a court cashier);
                           (b) the letter asks the person to answer it as the respondent: it states a
                           *Widerspruch* or *Einspruch* remedy, or gives an objection date; (c) it names
                           the order: its title names a *Mahnbescheid* or *Vollstreckungsbescheid* (or an
                           English "payment order" / "enforcement order"), which decides which one it is
                           (the order the title names first); else the reading names one and the remedy
                           decides (*Widerspruch* → Mahnbescheid, *Einspruch* → Vollstreckungsbescheid,
                           from the remedy or the objection date's own wording) — never the order some
                           other sentence names. A court's other letters about an order (to the claimant,
                           after an objection, from enforcement) state no remedy of the person's and no
                           objection date, so (b) leaves them out. Limitation: a reading that gives such a
                           letter one anyway, with a title naming the order, files it as that order —
                           the safe side for a two-week Notfrist; the person can change the kind on the
                           letter's page. A labour court's orders are these kinds too, with one week
                           (§ 46a Abs. 3, § 59 ArbGG; :func:`is_labour_court`). A debt collector
                           threatening an order is not a court, so its letter stays a reminder. Anything
                           these signals don't decide keeps the model's kind; the person can file it as a
                           court order on the letter's page. The next extraction prompt should let the
                           model name the order itself (a ``letter_kind`` field); until then (the
                           prompts and their recorded answers stay fixed) code decides as above.
``dismissal``              the reading reports a termination by the other side
                           (``termination_by_provider``) about a job; what it ends is decided by the
                           contract it names first (``employment``; any other category but ``other``, a
                           job ticket, is neither), then the letter's kind (``employment``), and only
                           then the sender's (``employer``)
``landlord_notice``        a termination by the other side about a tenancy, in the same order (a
                           ``rent`` contract, kind ``rent_lease``, sender ``landlord``): an employer
                           ending the lease of a company flat gives a landlord's notice
``rent_increase``          a price increase about a tenancy whose *quoted* wording asks for consent
                           ("Zustimmung", "Vergleichsmiete", "Mietspiegel", § 558 BGB) — never from the
                           model's own prose — unless the increase's own quote or the reading's title
                           names another kind of increase, which needs no consent (graduated or index
                           rent, modernisation, operating-cost prepayments; §§ 557a, 557b, 559, 560 BGB),
                           or a quote says consent isn't needed ("Zustimmung nicht erforderlich"). What
                           happens *without* consent ("Sollten Sie Ihre Zustimmung nicht erteilen …"), a
                           key fact about the prepayment or a Mietspiegel feature ("Bad modernisiert")
                           never vetoes: every § 558 request has them
=========================  ============================================================================

These are the letters whose *dates* depend on their kind, so the kind is filed with the letter. An
operating-cost statement's dates don't (its objection period is an ordinary twelve months), so it
is recognised on read for its card only (:func:`names_statement`: the reading names a Betriebs-, Heiz- or
Nebenkostenabrechnung in its title, or with a tenancy or a billing period; the model didn't read it as a
reminder (``dunning``), which quotes an old statement without being it; and the sender is not a utility
or a public body, which may ask for a statement without sending one). A later letter about a statement
that isn't a reminder (a reply to objections) may still be recognised: its card and its payments count
from the statement's own date when the letter gives one ("Abrechnung … vom 15.11.2024",
:func:`~ordnung.rules.advice.statement_arrival`), never from the later letter's date. The person may
still file a letter as ``operating_costs``.

"The reading names" means its title, summary, quotes, date wordings and legal bases, never the
model's advice prose (``explanation``, ``warnings``), which may mention a Mahnbescheid as a threat.
Missed: a letter whose reading lacks these signals (e.g. no termination recorded) keeps the model's
kind; the person can set the kind on the letter's page, and its dates are then recomputed.

**2. The rule of a date** (:func:`kind_statute`, :func:`special_rule`): a date follows the statute
its ``legal_basis`` or wording cites, if its nature fits that statute (a date that isn't a
declaration is never a registration, an appointment never re-dated); if it cites none, a court
order's objection, payment and declaration dates follow the court rule (two weeks from delivery; one
week at a labour court, :func:`is_labour_court`), a
rent increase's declarations and objections the consent period and a landlord's notice's objections
the § 574b period. Wordings that decide on their own: "Kündigungsschutzklage", "arbeitsuchend
melden" (a declaration, and not an authority's own fixed date), and a consumer "Widerrufsfrist/
-recht/-belehrung" on a declaration (the withdrawal itself — not a cancellation or a payment that
mentions it) from a sender that is not an authority or a court (their *Widerruf* is a revocation)
and that cites no other law's withdrawal right (insurance: VVG).

**3. Dates the law adds** (:func:`derived_deadlines`): these letters rarely state their most
important deadline (a dismissal never mentions the three weeks for a court action), so each kind
brings the deadlines the law sets, which the pipeline files as to-dos unless an extracted objection or
declaration date was computed under that rule (:func:`computed_under`: routed to it, or a period counted
under it — not a date that merely mentions it, like a severance payment "if you don't sue", nor a court
order's payment date, which would turn "pay or object" into "pay"). A landlord's notice
without notice period (:func:`extraordinary_notice`: its own quote or the title says *fristlos*, not
negated ("nicht nur fristlos" is no negation), not only reserved — the reservation must govern the
notice, "eine fristlose Kündigung behalten wir uns vor" — and not "mit der gesetzlichen Frist", and the
tenancy ends within two months) gets no
objection to-do: the hardship objection doesn't apply to it (§ 574 Abs. 1 S. 2 BGB) — unless its own
quote or the title also gives notice with a notice period in the alternative (*hilfsweise fristgemäß*),
which it applies to. Any *hilfsweise* in them counts, even one that only reserves the ordinary notice:
offering an objection that may not be needed is the safe side of missing one (ADR 0008). An ordinary
notice whose objection date had passed when it was written (it ends less than two months later) gets
no to-do either; its card says so (§ 574b Abs. 2 S. 2 BGB, § 573c BGB). The objection is for a home only
(§§ 549, 574 BGB): its to-do and card say it
isn't for a garage, parking space or business premises let on their own (§ 578 BGB) — code doesn't try
to tell those apart.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from ordnung.models import DateNature, DateSpec, DocumentExtraction, HighStakesKind, LetterKind, Priority
from ordnung.rules.explain import fmt_date
from ordnung.rules.tenancy import notice_objection_deadline

#: The kinds of German court, in any case ("des Amtsgerichts"): never just any word ending in "gericht"
#: (a caterer's "Leibgericht").
_COURT_SENDER = re.compile(
    r"\b(?:amts|land|landes|oberlandes|kammer|(?:landes|bundes)?arbeits|(?:landes|bundes)?sozial|"
    r"(?:ober|bundes)?verwaltungs|finanz|mahn|familien|insolvenz|vollstreckungs|nachlass|betreuungs|"
    r"register|bundes)gericht(?:e?s|shofe?s?)?\b|\bbundesfinanzhofe?s?\b",
    re.I,
)
#: … or its usual abbreviation before the place ("AG Hagen", "des ArbG Berlin"), at the start of the
#: name or after an article — never a company's "… AG" (the rest must name a place, :func:`_names_a_place`).
_COURT_ABBREVIATION = re.compile(
    r"(?:^|[(,;/]\s*|\b(?:des|dem|der|beim|vom|am)\s+)(?:AG|LG|OLG|ArbG|LAG|LSG|OVG|VGH|FG)\s+"
    r"(?P<rest>[A-ZÄÖÜ].*)"
)
#: A company's legal form: "LG Electronics Deutschland GmbH", "FG Finanz-Service AG" are no courts.
_LEGAL_FORM = re.compile(
    r"\b(?:GmbH|mbH|AG|SE|KGaA|KG|OHG|UG|GbR|eG|e\.\s?V|Ltd|Inc|LLC|Corp|PLC|S\.?A|B\.?V|N\.?V)(?!\w)"
)
#: Words inside a place's name ("Frankfurt am Main", "Neustadt a. d. Weinstraße", "Berlin II").
_PLACE_JOINER = re.compile(r"am|an|der|im|in|bei|ob|vor|a\.|d\.|i\.|[IVX]+", re.I)
#: Sender kinds a court's abbreviation is read for: a court is a public authority in the model's reading
#: (or of no particular kind); ``None`` when the kind is unknown (a recipient typed in: a court's sending
#: rules are the safe side). Never a retailer, a landlord, a company …
_COURT_KINDS = (None, "authority", "other")
_LABOUR_COURT = re.compile(r"(?i:arbeitsgericht)|\b(?:ArbG|LAG)\s")
#: Senders that name a court without being one: a bailiff ("Gerichtsvollzieher bei dem Amtsgericht …",
#: "Obergerichtsvollzieherin …, Amtsgericht Köln") or a court cashier.
_NOT_A_COURT = re.compile(r"vollzieh|kasse|zahlstelle", re.I)
_COURT_ORDER_NAME = re.compile(r"mahnbescheid|vollstreckungsbescheid", re.I)
#: What a court order's title calls it: German, or the English a reading may use instead.
_ORDER_TITLE = re.compile(
    r"mahnbescheid|vollstreckungsbescheid|payment\s+order|order\s+for\s+payment|enforcement\s+order", re.I
)
_ENFORCEMENT_TITLE = re.compile(r"vollstreckungsbescheid|enforcement", re.I)
#: The remedy an objection date's own wording names (the remedy block may be empty).
_WIDERSPRUCH = re.compile(r"widerspr|\b69[24]\b[^§]{0,20}\bZPO\b", re.I)
_EINSPRUCH = re.compile(r"einspruch|\b(?:339|700)\b[^§]{0,20}\bZPO\b", re.I)
#: A § 558 request asks for consent — in the letter's own (German) wording.
_CONSENT = re.compile(r"zustimm|vergleichsmiete|mietspiegel|\b558[ab]?\b[^§]{0,20}\bBGB\b", re.I)
#: An increase of another kind, in the increase's own quote: graduated or index rent, modernisation,
#: operating-cost prepayments (§§ 557a, 557b, 559, 560 BGB) — none needs consent.
_OTHER_INCREASE = re.compile(
    r"staffelmiete|indexmiete|preisindex|modernisierung|\b55(?:7a|7b|9[a-e]?|60)\b[^§]{0,20}\bBGB\b|"
    r"(?:anpassung|erhöhung)\s+(?:der|ihrer)\s+\S*vorauszahlung|"
    r"vorauszahlung\w*\s+(?:(?:wird|werden)\s+(?:\S+\s+){0,3}(?:angepasst|erhöht)|erhöh|steig)",
    re.I,
)
#: The same as the reading's (English) title may call it.
_OTHER_INCREASE_TITLE = re.compile(
    r"index[- ](?:rent|linked)|indexed rent|price index|graduated|stepped rent|staggered rent|staffel|"
    r"moderni[sz]ation|\b55(?:7a|7b|9|60)\b|(?:prepayment|advance payment)s?\s+(?:adjust|increas|rise)|"
    r"(?:adjust|increas)\w*\s+(?:of\s+)?(?:the\s+|your\s+)?(?:operating[- ]costs?\s+)?(?:prepayment|advance payment)",
    re.I,
)
#: "No consent needed", in the letter's own words anywhere — never "if you don't consent" (every § 558
#: request says what happens then).
_NO_CONSENT_NEEDED = re.compile(
    r"zustimmung\s+(?:ist\s+|wird\s+)?(?:nicht\s+(?:erforderlich|nötig|notwendig)|entbehrlich)|"
    r"zustimmung\s+bedarf\s+es\s+nicht|bedarf\s+(?:es\s+)?(?:keiner|nicht\s+ihrer)\s+zustimmung|"
    r"ohne\s+dass\s+es\s+ihrer\s+zustimmung\s+bedarf",
    re.I,
)
_OPERATING_COSTS = re.compile(
    r"(?:betriebs|neben|heiz(?:ungs)?)kosten-?\s?abrechnung|(?:betriebs|neben)-\s*und\s+heizkostenabrechnung|"
    r"(?:operating|service|ancillary|heating)(?:[- ]and[- ]heating)?[- ]costs?[- ]statement|"
    r"service[- ]charge statement",
    re.I,
)
_BILLING_PERIOD = re.compile(r"abrechnungs(?:zeitraum|periode|jahr)|billing (?:period|year)", re.I)
#: Senders that may ask for a statement but never send one (the Jobcenter wants to see it).
_NOT_A_LANDLORD = (
    "utility",
    "authority",
    "tax_office",
    "immigration_office",
    "health_insurer",
    "public_broadcaster",
)
#: A notice without notice period, in the termination's own quote or the reading's title.
_EXTRAORDINARY = re.compile(
    r"fristlos|außerordentlich|ausserordentlich|ohne\s+einhaltung\s+(?:einer|der)\s+(?:kündigungs)?frist|"
    r"without notice|extraordinar|\b543\b[^§]{0,20}\bBGB\b|\b569\b[^§]{0,20}\bBGB\b",
    re.I,
)
#: … unless it is negated ("nicht fristlos", "keine fristlose Kündigung") in its sentence, or only
#: reserved: a reservation that governs the notice itself — before it ("wir behalten uns eine fristlose
#: Kündigung vor", "… vor, fristlos zu kündigen") or right after it ("eine fristlose Kündigung bleibt
#: vorbehalten") — never one of something else ("wir kündigen fristlos und behalten uns weitere
#: Ansprüche vor").
_NEGATED = re.compile(r"\b(?:nicht|kein\w*|not|no|never)\b(?!\s+(?:nur|only)\b)[^.!?;\n]{0,30}$", re.I)
_NOTICE = re.compile(r"\w*\s+(?:\S+\s+){0,3}?(?:kündigung|zu\s+kündigen)\b", re.I)
_RESERVING = re.compile(r"vorbehalt|\bbehalten\s+(?:wir\s+|ich\s+)?(?:uns|mir)\b", re.I)
_RESERVED_AFTER = re.compile(
    r"\s+(?:(?!und\b|oder\b)[^\s,]+\s+){0,4}?(?:behalten\s+(?:wir|ich)\s+(?:uns|mir)|bleibt|bleiben|ist|wird)"
    r"\s+(?:\S+\s+){0,2}?vor(?:behalten)?\b",
    re.I,
)
_SENTENCE_END = re.compile(r"[!?;\n]|\.(?=\s+[A-ZÄÖÜ]|\s*$)")
#: A special termination with the statutory notice period: the hardship objection applies to it
#: (§ 575a Abs. 2 BGB for § 573d; the buyer at a forced sale, § 57a ZVG; the insolvency administrator,
#: § 111 InsO; heirs, § 564 BGB; the end of a usufruct, § 1056 BGB).
_STATUTORY_PERIOD = re.compile(
    r"(?:mit|unter\s+einhaltung)\s+(?:der\s+|einer\s+)?gesetzlichen\s+(?:kündigungs)?frist|"
    r"statutory notice period|\b57(?:3d|5a)\b[^§]{0,20}\bBGB\b|\b57a\b[^§]{0,20}\bZVG\b|"
    r"\b111\b[^§]{0,20}\bInsO\b|\b564\b[^§]{0,20}\bBGB\b|\b1056\b[^§]{0,20}\bBGB\b",
    re.I,
)

#: A notice without notice period that also gives notice with one "in the alternative".
_ALTERNATIVE_NOTICE = re.compile(
    r"hilfsweise|vorsorglich\s+(?:\S+\s+){0,4}?(?:ordentlich|fristgerecht|fristgemäß)|alternatively|"
    r"in the alternative",
    re.I,
)

_SGB3_38 = re.compile(
    r"\b38\b[^§]{0,20}\bSGB\s*(?:III|3)\b|arbeits?suchend\s+(?:zu\s+)?(?:ge)?meld|"
    r"meld\w*\s+(?:\S+\s+){0,4}arbeits?suchend\b",
    re.I,
)
_BGB_558B = re.compile(r"\b558b\b[^§]{0,20}\bBGB\b", re.I)
_BGB_574B = re.compile(r"\b574b?\b[^§]{0,20}\bBGB\b", re.I)
_WITHDRAWAL = re.compile(
    r"\b35[56]\b[^§]{0,20}\bBGB\b|widerrufs(?:frist|recht|belehrung)|right of withdrawal|withdrawal period",
    re.I,
)
#: Withdrawal rights of other laws, with their own periods (insurance: 14 or 30 days, § 8, § 152 VVG).
_OTHER_WITHDRAWAL_LAW = re.compile(r"\b(?:VVG|FernUSG|KAGB|VermAnlG|WpPG)\b")

_TENANCY = ("rent_lease", "landlord", "rent")
#: What a termination by the other side ends, by the contract's category, the letter's or the sender's kind.
_TERMINATED: dict[str, HighStakesKind] = {
    "employment": "dismissal",
    "employer": "dismissal",
    **dict.fromkeys(_TENANCY, "landlord_notice"),
}
_DECLARING: tuple[DateNature, ...] = ("objection", "payment", "declaration")


def _quoted_text(extraction: DocumentExtraction) -> str:
    """The letter's own wording as the reading quotes it (quotes, date wordings, legal bases)."""
    parts: list[str] = []
    for item in extraction.items:
        parts += [item.quote, item.date.text, item.date.legal_basis or ""]
    for fact in extraction.key_facts:
        parts.append(fact.quote)
    if extraction.remedy is not None:
        remedy = extraction.remedy
        parts += [remedy.quote or "", remedy.period_text or "", remedy.form_text or ""]
    if extraction.change is not None:
        parts.append(extraction.change.quote)
    return "\n".join(part for part in parts if part)


def _reading_text(extraction: DocumentExtraction) -> str:
    """What the letter says according to the reading (not the model's advice prose)."""
    parts = [extraction.title, extraction.summary, _quoted_text(extraction)]
    for item in extraction.items:
        parts.append(item.title)
    for fact in extraction.key_facts:
        parts += [fact.label, fact.value]
    if extraction.remedy is not None:
        parts.append(extraction.remedy.addressee or "")
    return "\n".join(part for part in parts if part)


def _about(extraction: DocumentExtraction, markers: tuple[str, ...]) -> bool:
    """Whether the letter's kind, its sender's kind or its contract's category is one of ``markers``."""
    sender = extraction.sender.kind if extraction.sender else None
    category = extraction.contract.category if extraction.contract else None
    return extraction.kind in markers or sender in markers or category in markers


def _objection_dates(extraction: DocumentExtraction) -> list[str]:
    """The wording of the letter's objection dates (their text, legal basis and quote)."""
    return [
        f"{item.date.legal_basis or ''} {item.date.text} {item.quote}"
        for item in extraction.items
        if item.date.nature == "objection"
    ]


def _respondent(extraction: DocumentExtraction) -> bool:
    """Whether the letter asks the person to answer as the respondent: it states a *Widerspruch* or
    *Einspruch* remedy, or gives an objection date (a court's notice to a claimant does neither)."""
    remedy = extraction.remedy.type if extraction.remedy else None
    return remedy in ("widerspruch", "einspruch") or bool(_objection_dates(extraction))


def _stated_remedy(extraction: DocumentExtraction) -> HighStakesKind | None:
    """The order the letter's remedy belongs to: the remedy block's, else its objection dates' wording
    when it names only one of *Widerspruch* and *Einspruch*."""
    remedy = extraction.remedy.type if extraction.remedy else None
    if remedy == "einspruch":
        return "enforcement_order"
    if remedy == "widerspruch":
        return "court_payment_order"
    wording = "\n".join(_objection_dates(extraction))
    payment_order, enforcement = bool(_WIDERSPRUCH.search(wording)), bool(_EINSPRUCH.search(wording))
    if payment_order == enforcement:
        return None
    return "court_payment_order" if payment_order else "enforcement_order"


def _court_order(extraction: DocumentExtraction) -> HighStakesKind | None:
    """Which court order a court's letter is (policy 1: respondent, then title, else remedy), or ``None``."""
    if not _respondent(extraction):
        return None
    named = _ORDER_TITLE.search(extraction.title)
    if named is not None:
        return "enforcement_order" if _ENFORCEMENT_TITLE.match(named.group()) else "court_payment_order"
    if not _COURT_ORDER_NAME.search(_reading_text(extraction)):
        return None
    return _stated_remedy(extraction)


def _names_a_place(rest: str) -> bool:
    """Whether what follows a court's abbreviation is its place: a word or two before any separator
    (" - ", ",", "(" …; joiners like "am" and a chamber's "II" don't count), and no company's legal form
    anywhere after it ("LG Electronics Deutschland GmbH", "AG Wohnbau GmbH")."""
    place = re.split(r"\s+[-–—]\s+|[,;/(]", rest, maxsplit=1)[0]
    words = [word for word in place.split() if not _PLACE_JOINER.fullmatch(word)]
    return 1 <= len(words) <= 2 and not _LEGAL_FORM.search(rest)


def is_court(name: str, kind: str | None = None) -> bool:
    """Whether a sender's name is a court's (policy 1): it names a kind of court (*Amtsgericht*, also *des
    Amtsgerichts*; *Zentrales Mahngericht*), or abbreviates one before its place (*AG Hagen*, *ArbG
    Berlin*) when the sender's ``kind`` is an authority, ``other`` or unknown — a retailer "LG
    Electronics", a landlord "OLG Immobilien" is no court — and is no bailiff or court cashier. Not
    recognised: a court named only in English."""
    if _NOT_A_COURT.search(name):
        return False
    if _COURT_SENDER.search(name):
        return True
    abbreviation = _COURT_ABBREVIATION.search(name.strip())
    return kind in _COURT_KINDS and abbreviation is not None and _names_a_place(abbreviation.group("rest"))


def is_labour_court(name: str, kind: str | None = None) -> bool:
    """Whether a court is a labour court (Arbeitsgericht, Landesarbeitsgericht): its orders give one week,
    not two (§ 46a Abs. 3, § 59 ArbGG)."""
    return is_court(name, kind) and bool(_LABOUR_COURT.search(name))


def classify_letter(extraction: DocumentExtraction) -> HighStakesKind | None:
    """The high-stakes kind of a letter from the model's reading, or ``None`` (policy 1 above)."""
    sender = extraction.sender
    if sender is not None and is_court(sender.name, sender.kind):
        court_order = _court_order(extraction)
        if court_order is not None:
            return court_order
    change = extraction.change.type if extraction.change else None
    if change == "termination_by_provider":
        return _terminated(extraction)
    if change == "price_increase" and _about(extraction, _TENANCY) and _consent_request(extraction):
        return "rent_increase"
    return None


def _terminated(extraction: DocumentExtraction) -> HighStakesKind | None:
    """What a termination by the other side ends (policy 1): the contract it names decides first, then
    the letter's own kind, and only then the sender's kind — an employer ending the lease of a company
    flat (*Werkmietwohnung*) gives a landlord's notice, and one ending a job ticket neither."""
    category = extraction.contract.category if extraction.contract else None
    if category not in (None, "other"):
        return _TERMINATED.get(category)  # another contract (a gym, a job ticket): neither
    sender = extraction.sender.kind if extraction.sender else None
    return _TERMINATED.get(extraction.kind) or _TERMINATED.get(sender or "")


def _consent_request(extraction: DocumentExtraction) -> bool:
    """Whether a rent increase asks for consent (policy 1): its quoted wording asks for it, its own quote
    and its title name no other kind of increase, and nothing it quotes says no consent is needed."""
    quoted = _quoted_text(extraction)
    own = extraction.change.quote if extraction.change is not None else ""
    return (
        bool(_CONSENT.search(quoted))
        and not _OTHER_INCREASE.search(own)
        and not _OTHER_INCREASE_TITLE.search(extraction.title)
        and not _NO_CONSENT_NEEDED.search(quoted)
    )


def names_statement(extraction: DocumentExtraction) -> bool:
    """Whether a reading is an operating-cost statement (its card is worked out on read, policy 1): it
    names one — in its title, or with a tenancy or a billing period — isn't a reminder (a reminder about
    an old statement's back-payment quotes the statement without being it) and doesn't come from a
    utility or a public body."""
    text = _reading_text(extraction)
    sender = extraction.sender
    if (
        extraction.kind == "dunning"
        or not _OPERATING_COSTS.search(text)
        or (sender is not None and sender.kind in _NOT_A_LANDLORD)
    ):
        return False
    return (
        bool(_OPERATING_COSTS.search(extraction.title))
        or _about(extraction, _TENANCY)
        or bool(_BILLING_PERIOD.search(text))
    )


def _asserted(text: str, match: re.Match[str]) -> bool:
    """Whether a wording in ``text`` is said in its sentence: not negated, and not a notice only reserved
    (:data:`_NOTICE` governed by a reservation before it or right after it)."""
    starts = [end.end() for end in _SENTENCE_END.finditer(text, 0, match.start())]
    after = _SENTENCE_END.search(text, match.end())
    before = text[starts[-1] if starts else 0 : match.start()]
    rest = text[match.end() : after.start() if after else len(text)]
    if _NEGATED.search(before):
        return False
    notice = _NOTICE.match(rest)
    return notice is None or not (_RESERVING.search(before) or _RESERVED_AFTER.match(rest, notice.end()))


def extraordinary_notice(extraction: DocumentExtraction, letter_date: date | None = None) -> bool:
    """Whether a termination is one without notice period (*fristlos*), the only one the hardship
    objection doesn't apply to (§ 574 Abs. 1 S. 2 BGB).

    Only the termination's own quote and the reading's title count — never the model's summary or
    other quotes, which may mention a *fristlose Kündigung* the landlord only reserves. The wording must
    say it (*fristlos*, *außerordentlich*, "ohne Einhaltung einer Kündigungsfrist", § 543 or § 569 BGB),
    not deny or reserve it, and not give the statutory period (*mit der gesetzlichen Frist*: a special
    termination the objection applies to). And the tenancy must end soon: no end stated, or one less
    than two months after the letter's date (``letter_date``, else the reading's) — unless it is the end
    of a notice given in the alternative (*hilfsweise*). When unsure, it is an ordinary notice: its
    objection to-do is kept, and the card says it doesn't apply to a notice without notice period.
    """
    own = extraction.change.quote if extraction.change is not None else ""
    text = f"{extraction.title}\n{own}"
    if _STATUTORY_PERIOD.search(text) or not any(
        _asserted(text, match) for match in _EXTRAORDINARY.finditer(text)
    ):
        return False
    end = announced_end(extraction)
    written = letter_date or _parse_day(extraction.document_date)
    if end is None or alternative_notice(extraction):
        return True
    return written is not None and notice_objection_deadline(end) < written


def alternative_notice(extraction: DocumentExtraction) -> bool:
    """Whether a notice without notice period also gives notice with one in the alternative
    (*hilfsweise fristgemäß*): the hardship objection applies to that one (§ 574 Abs. 1 S. 2 BGB). Like
    :func:`extraordinary_notice`, only the termination's own quote and the reading's title count — never
    the model's summary ("alternatively you may pay the arrears")."""
    own = extraction.change.quote if extraction.change is not None else ""
    return bool(_ALTERNATIVE_NOTICE.search(f"{extraction.title}\n{own}"))


def letter_kind(extraction: DocumentExtraction) -> LetterKind:
    """The kind a letter is filed as: its high-stakes kind, else the model's."""
    return classify_letter(extraction) or extraction.kind


def _parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value.strip()[:10]) if value else None
    except ValueError:
        return None


def announced_end(extraction: DocumentExtraction) -> date | None:
    """The end of the job or tenancy a termination announces (its effective date), if stated."""
    change = extraction.change
    if change is None or change.type != "termination_by_provider":
        return None
    return _parse_day(change.effective_date)


def kind_statute(letter: str | None, spec: DateSpec) -> str | None:
    """The court rule a court order gives its dates when their wording cites no statute."""
    if spec.type == "none" or spec.nature not in _DECLARING:
        return None
    if letter == "court_payment_order":
        return "zpo_692"
    if letter == "enforcement_order" and spec.nature == "objection":
        return "zpo_339"
    return None


def special_rule(spec: DateSpec, letter: str | None, *, authority: bool) -> str | None:
    """The letter rule computed by :mod:`ordnung.rules.letters` for ``spec``, or ``None`` (policy 2).

    ``authority``: the sender is a public authority (its *Widerruf* is a revocation, not a consumer's
    withdrawal, and its own fixed dates are never re-dated). Dates with no date type are never routed,
    and a date is only routed to a rule its nature fits.
    """
    if spec.type == "none":
        return None
    haystack = f"{spec.legal_basis or ''} {spec.text}"
    if (
        spec.nature == "declaration"
        and not (authority and spec.type == "fixed")
        and _SGB3_38.search(haystack)
    ):
        return "sgb3_38"
    if spec.nature in ("declaration", "objection") and (
        _BGB_558B.search(haystack) or letter == "rent_increase"
    ):
        return "bgb_558b"
    if spec.nature == "objection" and (_BGB_574B.search(haystack) or letter == "landlord_notice"):
        return "bgb_574b"
    if (
        not authority
        and spec.nature == "declaration"
        and _WITHDRAWAL.search(haystack)
        and not _OTHER_WITHDRAWAL_LAW.search(haystack)
    ):
        return "bgb_355"
    return None


# --------------------------------------------------------------------------------------------------
# dates the law adds
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DerivedDeadline:
    """A deadline the law sets for a kind of letter, as a to-do the pipeline files (policy 3)."""

    rule_id: str
    title: str
    action: str
    consequence: str
    priority: Priority
    spec: DateSpec


def _relative(amount: int, unit: str, nature: DateNature, legal_basis: str, text: str) -> DateSpec:
    return DateSpec.model_validate(
        {
            "type": "relative",
            "anchor": "receipt",
            "amount": amount,
            "unit": unit,
            "nature": nature,
            "legal_basis": legal_basis,
            "text": text,
        }
    )


_COURT_ORDER = DerivedDeadline(
    rule_id="zpo_692",
    title="Pay or object to the court payment order (Mahnbescheid)",
    action=(
        "If you don't owe the money, or not all of it, object (Widerspruch) on the form that came with "
        "the order, or online. If you owe it, pay the claimant."
    ),
    consequence=(
        "After two weeks the claimant can ask for an enforcement order (Vollstreckungsbescheid), and the "
        "money can then be collected by a bailiff."
    ),
    priority="critical",
    spec=_relative(
        2,
        "weeks",
        "objection",
        "§ 692 Abs. 1 Nr. 3 ZPO",
        "binnen zwei Wochen seit der Zustellung des Mahnbescheids",
    ),
)
_ENFORCEMENT = DerivedDeadline(
    rule_id="zpo_339",
    title="Object to the enforcement order (Einspruch)",
    action="Send your objection (Einspruch) in writing to the court that issued it — get advice first.",
    consequence="After two weeks the order can no longer be challenged and can be enforced for good.",
    priority="critical",
    spec=_relative(
        2, "weeks", "objection", "§ 700 Abs. 1, § 339 Abs. 1 ZPO", "Einspruchsfrist zwei Wochen ab Zustellung"
    ),
)
_LABOUR_COURT_ORDER = DerivedDeadline(
    rule_id="arbgg_46a",
    title="Pay or object to the labour court's payment order (Mahnbescheid)",
    action=(
        "If you don't owe the money, or not all of it, object (Widerspruch) at the labour court that issued "
        "the order, on the form that came with it. If you owe it, pay the claimant."
    ),
    consequence=(
        "At a labour court you have one week, not two. After it the claimant can ask for an enforcement order "
        "(Vollstreckungsbescheid), and the money can then be collected by a bailiff."
    ),
    priority="critical",
    spec=_relative(
        1,
        "weeks",
        "objection",
        "§ 46a Abs. 3 ArbGG, § 692 Abs. 1 Nr. 3 ZPO",
        "binnen einer Woche seit der Zustellung des Mahnbescheids",
    ),
)
_LABOUR_ENFORCEMENT = DerivedDeadline(
    rule_id="arbgg_59",
    title="Object to the labour court's enforcement order (Einspruch)",
    action=(
        "Send your objection (Einspruch) in writing to the labour court that issued it, or make it for the record "
        "at its office — get advice first."
    ),
    consequence="After one week the order can no longer be challenged and can be enforced for good.",
    priority="critical",
    spec=_relative(
        1,
        "weeks",
        "objection",
        "§ 59 S. 1 ArbGG, § 700 Abs. 1 ZPO",
        "Einspruchsfrist eine Woche ab Zustellung",
    ),
)
_COURT_ACTION = DerivedDeadline(
    rule_id="kschg_4",
    title="Get advice now: court action against the dismissal (Kündigungsschutzklage)",
    action=(
        "If you think the dismissal is wrong, talk to your union, an employment lawyer or the labour "
        "court's Rechtsantragstelle today. Only a court action filed in time keeps your rights."
    ),
    consequence="If no court action reaches the labour court in time, the dismissal counts as valid (§ 7 KSchG).",
    priority="critical",
    spec=_relative(
        3, "weeks", "objection", "§ 4 S. 1 KSchG", "innerhalb von drei Wochen nach Zugang der Kündigung"
    ),
)
_REGISTER = DerivedDeadline(
    rule_id="sgb3_38",
    title="Register as job-seeking (arbeitsuchend) at the Agentur für Arbeit",
    action=(
        "Register online, by phone or in person. Your details and the end date of the job are enough for now. "
        "Not needed if this ends an apprenticeship in a company (§ 38 Abs. 1 S. 4 SGB III). Working students "
        "(Werkstudenten) and mini-jobbers are usually not insured against unemployment (§ 27 SGB III): they have "
        "no benefit to lose, but registering still helps."
    ),
    consequence="If you claim unemployment benefit, registering late can cost you one week of it (Sperrzeit).",
    priority="high",
    spec=_relative(3, "days", "declaration", "§ 38 Abs. 1 SGB III", "arbeitsuchend melden"),
)
_CONSENT_DECISION = DerivedDeadline(
    rule_id="bgb_558b",
    title="Decide whether to agree to the rent increase",
    action=(
        "Check the increase (rent index, the rent cap, 15 months since the last one) before you agree — "
        "a tenants' association can help. You don't have to answer earlier."
    ),
    consequence="If you haven't agreed by then, the landlord can take you to court for your consent.",
    priority="high",
    spec=_relative(2, "months", "declaration", "§ 558b Abs. 2 BGB", "Zustimmung zur Mieterhöhung"),
)
_NOTICE_OBJECTION = DerivedDeadline(
    rule_id="bgb_574b",
    title="Decide whether to object to the notice (Widerspruch)",
    action=(
        "Have the notice checked by a tenants' association (form, reason, period). If moving out would be a "
        "hardship for you or your household (illness, old age, no other flat), you can also object and ask to "
        "stay (§ 574 BGB). That objection is only for a home: not for a garage, parking space or business "
        "premises let on their own (§ 578 BGB), a short let or a furnished room in your landlord's own flat "
        "(§ 549 Abs. 2 BGB)."
    ),
    consequence=(
        "After this day the landlord may refuse to continue the tenancy — unless they didn't tell you in time "
        "about this right, its form and its deadline (then you can still object at the first court hearing)."
    ),
    priority="high",
    spec=_relative(
        -2, "months", "objection", "§ 574b Abs. 2 BGB", "spätestens zwei Monate vor der Beendigung"
    ),
)


#: The letter rules (:mod:`ordnung.rules.letters`): a date routed to one was computed under it.
LETTER_RULES = ("sgb3_38", "bgb_558b", "bgb_574b", "bgb_355")


def computed_under(spec: DateSpec, rule_ids: Sequence[str], rule_id: str) -> bool:
    """Whether a letter's own date (its DateSpec, its receipt's ``rule_ids``) was computed under
    ``rule_id``, so the deadline the law adds for that rule would repeat it (policy 3): routed to a
    letter rule, or a period counted under a court rule — and it asks what the law's to-do asks, an
    objection or a declaration. A fixed date that only cites a court rule keeps the letter's day, which
    may not be the law's, so the law's to-do is filed next to it; and a court order's payment date
    ("pay within two weeks") is only half of "pay *or object*", so that to-do is filed next to it too."""
    return (
        rule_id in rule_ids
        and spec.nature in ("objection", "declaration")
        and (rule_id in LETTER_RULES or spec.type == "relative")
    )


def derived_deadlines(
    letter: str | None,
    *,
    end: date | None,
    letter_date: date | None = None,
    extraordinary: bool = False,
    labour_court: bool = False,
) -> list[DerivedDeadline]:
    """The deadlines the law adds to a kind of letter; ``end`` is the end its termination announces.
    A court order from a labour court (``labour_court``) gives one week (§ 46a Abs. 3, § 59 ArbGG).

    The objection to a landlord's notice counts back from the end of the tenancy, so it is only
    added when that end is known — and not for a notice without notice period (``extraordinary``: one
    not also given with a notice period in the alternative, or an end less than two months after the
    letter's date ``letter_date``): the hardship objection doesn't apply to it (§ 574 Abs. 1 S. 2 BGB),
    and its card points to advice instead.
    """
    if letter == "court_payment_order":
        return [_LABOUR_COURT_ORDER if labour_court else _COURT_ORDER]
    if letter == "enforcement_order":
        return [_LABOUR_ENFORCEMENT if labour_court else _ENFORCEMENT]
    if letter == "dismissal":
        return [_COURT_ACTION, _REGISTER]
    if letter == "rent_increase":
        return [_CONSENT_DECISION]
    if letter == "landlord_notice" and end is not None and not extraordinary:
        if letter_date is not None and notice_objection_deadline(end) < letter_date:
            return []
        spec = _NOTICE_OBJECTION.spec.model_copy(
            update={"anchor": "explicit_date", "anchor_date": end.isoformat()}
        )
        action = f"Your tenancy ends on {fmt_date(end)}. {_NOTICE_OBJECTION.action}"
        return [replace(_NOTICE_OBJECTION, spec=spec, action=action)]
    return []
