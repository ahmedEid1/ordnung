"""Which rules a high-stakes letter's dates follow (ADR 0002, ADR 0007, ADR 0010).

The model reads, code decides. Since extraction prompt version 9 the model names a high-stakes letter
itself (``high_stakes_kind``, ADR 0010 point 5), and code checks that answer against the rest of the
reading; the kind and the dates follow the three short written policies below, and cases they do not
decide are documented limitations, not bugs. Readings recorded before version 9 name no kind, and code
decides alone, as it always did.

**1. The kind of letter** (:func:`classify_letter`): the kind code reads from the reading (the table
below) weighed against the one the model names:

* the model names none (every reading recorded before version 9): code's kind, or none;
* code reads one: code's kind, whether the model names the same one or another — code's is the structured
  decision the review rounds checked;
* only the model names one: the model's, unless the rest of the reading rules it out (:func:`_vetoed`) — a
  court order whose sender is clearly no court (read as a company, a landlord, a bank … under a name that
  names no court, or a bailiff or a court cashier) or that is a European order for payment; a dismissal or
  a landlord's notice whose contract is of another category (a gym, a job ticket; a tenancy for a
  dismissal, a job for a landlord's notice), decided by the contract first as below; a rent increase whose
  own quote or title names another kind of increase, or that a quote says needs no consent (the vetoes of
  ``rent_increase`` below). The model's ``operating_costs`` is never filed: a statement is recognised on
  read (below).

A veto only takes the model's kind away when the reading says the letter is something else: a court named
only in English, a court order whose reading has no remedy and no objection date, or a termination the
reading doesn't record is filed under the kind the model names (misses ADR 0010 had accepted), and a kind
that brings the law's deadlines is the safe side. The kind the person chose on the letter's page wins over
both (:func:`ordnung.ingest.plan.filed_kind`).

Code's own kind, from structured parts of the reading first:

=========================  ============================================================================
``court_payment_order``    three signals, with no list of exceptions: (a) the sender is a court
``enforcement_order``      (:func:`is_court`: a kind of court by name, *Amtsgericht*, *des
                           Arbeitsgerichts*, or its abbreviation before a place of a word or two, *AG
                           Hagen*, *SG Berlin*, *VG Minden*, or a federal court's alone, *BGH*, from a
                           sender read as an authority (or ``other``: a club "SG …" or "VG Wort" of that
                           kind counts as one, the safe side) — not a company,
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
                           threatening an order is not a court, so its letter stays a reminder, and a
                           European order for payment (EuMahnVO: 30 days, an Einspruch, no enforcement
                           order) is no Mahnbescheid: it keeps the model's ordinary kind, whatever
                           ``high_stakes_kind`` says. Anything else these signals don't decide is left to
                           the kind the model names (above); the person can file it as a court order on
                           the letter's page.
``dismissal``              the reading reports a termination by the other side
                           (``termination_by_provider``) about a job; what it ends is decided by the
                           contract it names first (``employment``; any other category but ``other``, a
                           job ticket, is neither), then the letter's kind (``employment``), and only
                           then the sender's (``employer``)
``landlord_notice``        a termination by the other side about a tenancy, in the same order (a
                           ``rent`` contract, kind ``rent_lease``, sender ``landlord``): an employer
                           ending the lease of a company flat gives a landlord's notice
``rent_increase``          a price increase about a tenancy whose *quoted* wording asks for consent
                           ("Zustimmung", "Vergleichsmiete", "Mietspiegel", § 558 BGB; the increase's own
                           quote "um Zustimmung", "Bitte stimmen Sie … zu", "verlangen … Zustimmung") — never from the
                           model's own prose — unless the increase's own quote or the reading's title
                           names another kind of increase, which needs no consent (graduated or index
                           rent, operating-cost prepayments, §§ 557a, 557b, 559, 560 BGB; a modernisation
                           only when the increase's own quote doesn't ask for consent itself), or a quote
                           says consent isn't needed ("Zustimmung nicht erforderlich"). What happens
                           *without* consent ("Sollten Sie Ihre Zustimmung nicht erteilen …"), a key fact
                           about the prepayment or a Mietspiegel feature ("Bad modernisiert", "nach der
                           Modernisierung des Bades … zuzustimmen") never vetoes: every § 558 request has
                           them
=========================  ============================================================================

These are the letters whose *dates* depend on their kind, so the kind is filed with the letter. An
operating-cost statement's dates don't (its objection period is an ordinary twelve months), so it
is recognised on read for its card only (:func:`names_statement`: the model names it one
(``operating_costs``), or the reading names a Betriebs-, Heiz- or Nebenkostenabrechnung in its title, or
with a tenancy or a billing period; either way the model didn't read it as a reminder (``dunning``), which
quotes an old statement without being it, and the sender is not a utility or a public body, which may ask
for a statement without sending one). A later letter about a statement
that isn't a reminder (a reply to objections) may still be recognised: its card and its payments count
from the statement's own date when the letter gives one with its year ("Abrechnung 2023 vom 15.11.2024" —
the statement whose billing period it names, :func:`~ordnung.rules.advice.statement_arrival`), never from
the later letter's date alone; a date without the year ("unsere Abrechnung vom 15.11.2024") may be that or
an enclosure's, so it never lets the statement be called late when it would make it on time. The person
may still file a letter as ``operating_costs``.

"The reading names" means its title, summary, quotes, date wordings and legal bases, never the
model's advice prose (``explanation``, ``warnings``), which may mention a Mahnbescheid as a threat.
Missed by code: a letter whose reading lacks these signals (e.g. no termination recorded) gets the kind
the model names, if any, else keeps the model's ordinary kind; the person can set the kind on the letter's
page, and its dates are then recomputed.

**2. The rule of a date** (:func:`kind_statute`, :func:`special_rule`): a date follows the statute
its ``legal_basis`` or wording cites, if its nature fits that statute (a date that isn't a
declaration is never a registration, an appointment never re-dated); if it cites none, a court
order's objection, payment and declaration dates follow the court rule (two weeks from delivery; one
week at a labour court, :func:`is_labour_court`), a
rent increase's declarations and objections the consent period and a landlord's notice's objections
the § 574b period, and a rent increase's payments (the new rent) the start of the third month after the
request arrived (§ 558b Abs. 1 BGB) at the earliest. Wordings that decide on their own:
"Kündigungsschutzklage", "arbeitsuchend melden" (a declaration, and not an authority's own fixed date), and a consumer "Widerrufsfrist/
-recht/-belehrung" on a declaration (the withdrawal itself — not a cancellation or a payment that
mentions it) from a sender that is not an authority or a court (their *Widerruf* is a revocation)
and that cites no other law's withdrawal right (insurance: VVG).

**3. Dates the law adds** (:func:`derived_deadlines`): these letters rarely state their most
important deadline (a dismissal never mentions the three weeks for a court action), so each kind
brings the deadlines the law sets, which the pipeline files as to-dos unless an extracted objection or
declaration date was computed under that rule (:func:`computed_under`: routed to it, or a period counted
under it — not a date that merely mentions it, like a severance payment "if you don't sue", nor a court
order's payment date, which would turn "pay or object" into "pay"). A landlord's notice
certainly without notice period (:func:`notice_without_period`: its own quote or the title says
*fristlos* or "ohne Einhaltung einer Kündigungsfrist" — § 543, § 569 or § 626 BGB alone only probably, and
not with any reservation in its sentence —, not refused ("sehen wir ab", "verzichten"), not negated before it
or at the end of its clause ("nicht nur fristlos" is no negation; "eine fristlose Kündigung ist damit nicht
verbunden" is one), not only reserved — the reservation must govern the notice, "eine fristlose Kündigung
behalten wir uns vor" — the notice itself not called *ordentlich*/*fristgerecht*, and not "mit (der)
gesetzlichen Frist" or "mit gesetzlicher Kündigungsfrist" (§ 573d BGB; "with statutory notice") said of the
notice itself: not denied ("without statutory notice"), not after *hilfsweise* (the notice given in the
alternative's period); and the tenancy ends within two months) gets no objection to-do: the hardship
objection doesn't apply to it (§ 574 Abs. 1 S. 2 BGB) — unless its own quote or the title also gives
notice with a notice period in the alternative (*hilfsweise fristgemäß*, "zugleich ordentlich", "gilt sie
als ordentliche Kündigung", "vorsorglich zum …") or names any later end ("spätestens zum Ablauf des
31.12.2026", "zum nächsten zulässigen Termin", "Ende Januar 2027"). A dismissal without notice period ends the
job when it arrives: its § 38 SGB III registration counts from then (``RuleContext.ends_on_arrival``). A notice only called *außerordentlich* ("außerordentliche Kündigung", never an
adverb of something else: "wegen Ihres außerordentlich störenden Verhaltens") is only probably one — a
special termination with the statutory period is called that too (§ 573d BGB) — so its to-do and letter
are kept and its card says it may be one.
The objection is excluded against that one too when the grounds for the notice without notice period
existed, even once the arrears are paid (BGH, 01.07.2020, VIII ZR 323/18), but they may not have: its
to-do and letter are kept (the card says when it is excluded). Any *hilfsweise* in them counts, even one
that only reserves the ordinary notice: offering an objection that may not be needed is the safe side of
missing one (ADR 0010). An ordinary
notice whose objection date had passed when it was written (it ends less than two months later), that ends
before the earliest end a notice arriving when it did can have (:func:`short_notice`), or whose
end wasn't read ("zum nächstmöglichen Termin"), gets the objection counted back from the earliest end a
notice with a notice period can have (§ 573c Abs. 1 BGB), with less confidence; the card of a short notice
says why (§ 574b Abs. 2 S. 2 BGB). The objection is for a home only
(§§ 549, 574 BGB): its to-do and card say it
isn't for a garage, parking space or business premises let on their own (§ 578 BGB) — code doesn't try
to tell those apart.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from ordnung.ingest.verify import parse_dates
from ordnung.models import (
    DateNature,
    DateSpec,
    DocumentExtraction,
    ExtractedParty,
    HighStakesKind,
    LetterKind,
    Priority,
)
from ordnung.rules.explain import fmt_date
from ordnung.rules.tenancy import month_end, next_permissible_end, notice_objection_deadline

#: The kinds of German court, in any case ("des Amtsgerichts"): never just any word ending in "gericht"
#: (a caterer's "Leibgericht").
_COURT_SENDER = re.compile(
    r"\b(?:amts|land|landes|oberlandes|kammer|(?:landes|bundes)?arbeits|(?:landes|bundes)?sozial|"
    r"(?:ober|bundes)?verwaltungs|finanz|mahn|familien|insolvenz|vollstreckungs|nachlass|betreuungs|"
    r"register|(?:landes|bundes)?verfassungs|staats|bundes)gericht(?:e?s|shofe?s?)?\b|\bbundesfinanzhofe?s?\b",
    re.I,
)
#: Where a court's abbreviation starts: the start of the name, after a separator or after an article.
_ABBREVIATION_START = r"(?:^|[(,;/]\s*|\b(?:des|dem|der|beim|vom|am)\s+)"
#: … or its usual abbreviation before the place ("AG Hagen", "SG Berlin", "des ArbG Berlin") — never a
#: company's "… AG" (the rest must name a place, :func:`_names_a_place`).
_COURT_ABBREVIATION = re.compile(
    rf"{_ABBREVIATION_START}(?:AG|LG|OLG|ArbG|LAG|SG|LSG|VG|OVG|VGH|FG)\s+(?P<rest>[A-ZÄÖÜ].*)"
)
#: A federal court's abbreviation, which needs no place (there is one of each): "BGH", "BSG, 1. Senat".
_FEDERAL_COURT_ABBREVIATION = re.compile(
    rf"{_ABBREVIATION_START}(?:BGH|BFH|BSG|BAG|BVerwG|BVerfG)(?:\s*$|\s*[-–—,;/(]|\s+(?P<rest>[A-ZÄÖÜ].*))"
)
#: A company's legal form: "LG Electronics Deutschland GmbH", "FG Finanz-Service AG" are no courts.
_LEGAL_FORM = re.compile(
    r"\b(?:GmbH|mbH|AG|SE|KGaA|KG|OHG|UG|GbR|eG|e\.\s?V|Ltd|Inc|LLC|Corp|PLC|S\.?A|B\.?V|N\.?V)(?!\w)"
)
#: Words inside a place's name ("Frankfurt am Main", "Neustadt a. d. Weinstraße", "Berlin II").
_PLACE_JOINER = re.compile(r"am|an|der|im|in|bei|ob|vor|a\.|d\.|i\.|[IVX]+", re.I)
#: Sender kinds a court's abbreviation is read for: a court is a public authority in the model's reading
#: (or of no particular kind). Never a retailer, a landlord, a company … — nor a name of unknown kind (a
#: recipient typed in: "LG Electronics", "AG Hausverwaltung Müller" are no courts; only a court's full
#: name makes one).
_COURT_KINDS = ("authority", "other")
_LABOUR_COURT = re.compile(r"(?i:arbeitsgericht)|\b(?:ArbG|LAG)\s|\bBAG\b")
_SOCIAL_COURT = re.compile(r"(?i:sozialgericht)|\b(?:SG|LSG)\s|\bBSG\b")
#: Senders that name a court without being one: a bailiff ("Gerichtsvollzieher bei dem Amtsgericht …",
#: "Obergerichtsvollzieherin …, Amtsgericht Köln") or a court cashier ("Gerichtskasse", "Landesjustizkasse",
#: "Kasse des Amtsgerichts") — a word ending in "kasse", never a place such as Kassel (review round 2: every
#: court in Kassel was an ordinary authority, its dates late).
_NOT_A_COURT = re.compile(r"vollzieh|kasse(?:n(?:stelle)?)?\b|zahlstelle", re.I)
_COURT_ORDER_NAME = re.compile(r"mahnbescheid|vollstreckungsbescheid", re.I)
#: What a court order's title calls it: German, or the English a reading may use instead.
_ORDER_TITLE = re.compile(
    r"mahnbescheid|vollstreckungsbescheid|payment\s+order|order\s+for\s+payment|enforcement\s+order", re.I
)
_ENFORCEMENT_TITLE = re.compile(r"vollstreckungsbescheid|enforcement", re.I)
#: A European order for payment (Regulation (EC) No 1896/2006): an Einspruch within 30 days at the issuing
#: court (Art. 16), no Vollstreckungsbescheid, a late one only by review (Art. 20) — none of the German
#: Mahnbescheid's rules, so it keeps the model's kind (review round 4 of phase 2).
_EUROPEAN_ORDER = re.compile(
    r"eumahnvo|europäische[nrs]?\s+zahlungsbefehl|european\s+(?:order\s+for\s+payment|payment\s+order)|"
    r"\b1896/2006\b",
    re.I,
)
#: The remedy an objection date's own wording names (the remedy block may be empty).
_WIDERSPRUCH = re.compile(r"widerspr|\b69[24]\b[^§]{0,20}\bZPO\b", re.I)
_EINSPRUCH = re.compile(r"einspruch|\b(?:339|700)\b[^§]{0,20}\bZPO\b", re.I)
#: A § 558 request asks for consent — in the letter's own (German) wording.
_CONSENT = re.compile(r"zustimm|vergleichsmiete|mietspiegel|\b558[ab]?\b[^§]{0,20}\bBGB\b", re.I)
#: An increase of another kind, in the increase's own quote: graduated or index rent (§§ 557a, 557b BGB) —
#: which needs no consent, whatever else the quote says …
_OTHER_INCREASE = re.compile(r"staffelmiete|indexmiete|preisindex|\b557[ab]\b[^§]{0,20}\bBGB\b", re.I)
#: … or operating-cost prepayments or the statute of a modernisation or cost increase (§§ 559, 560 BGB), which
#: a § 558 request names too — its first sentence quotes § 558 Abs. 1 S. 3 ("Erhöhungen nach den §§ 559 bis 560
#: bleiben unberücksichtigt"), a letter may adjust the prepayments at the same time, and the new total rent
#: includes them — so these veto only when the quote doesn't ask for consent itself (:data:`_ASKS_CONSENT`;
#: review round 3 of phase 2).
_COST_INCREASE = re.compile(
    r"\b(?:559[a-e]?|560)\b[^§]{0,20}\bBGB\b|"
    r"(?:anpassung|erhöhung)\s+(?:der|ihrer)\s+\S*vorauszahlung|"
    r"vorauszahlung\w*\s+(?:(?:wird|werden)\s+(?:(?!nicht\b|keine?\b)\S+\s+){0,3}(?:angepasst|erhöht)|erhöh|steig)",
    re.I,
)
#: The increase's own quote asking for consent: "um (Ihre) Zustimmung", "zuzustimmen", "Bitte stimmen Sie … zu",
#: "(wir) verlangen/bitten … Zustimmung", "Zustimmung zur … erhöhung", a Zustimmungserklärung, or § 558 BGB
#: named — not "Vergleichsmiete" or "Mietspiegel" alone, which a § 559 letter may mention too (review round 4
#: of phase 2: the usual imperative and "verlangen wir Ihre Zustimmung" were not read as asking).
_ASKS_CONSENT = re.compile(
    r"\bum\s+(?:ihre\s+)?zustimmung|zuzustimmen|zustimmungserklärung|\b558[ab]?\b[^§]{0,20}\bBGB\b|"
    r"\bstimmen\s+sie\b(?:[^.!?\n]|\.(?=\s?\d)){0,150}?\bzu\b|zustimmung\s+(?:zur|zu\s+der)\s+\S*erhöhung|"
    r"\b(?:verlangen|erbitten|bitten|fordern|ersuchen)\b(?:[^.!?\n]|\.(?=\s?\d)){0,40}\bzustimmung",
    re.I,
)
#: The same as the reading's (English) title may call it: another kind of increase …
_OTHER_INCREASE_TITLE = re.compile(
    r"index[- ](?:rent|linked)|indexed rent|price index|graduated|stepped rent|staggered rent|staffel|"
    r"\b55(?:7a|7b|9|60)\b",
    re.I,
)
#: … or an adjustment of the prepayments next to it, which vetoes only when the quote doesn't ask for consent.
_PREPAYMENT_TITLE = re.compile(
    r"(?:prepayment|advance payment)s?\s+(?:adjust|increas|rise)|"
    r"(?:adjust|increas)\w*\s+(?:of\s+)?(?:the\s+|your\s+)?(?:operating[- ]costs?\s+)?(?:prepayment|advance payment)",
    re.I,
)
#: A modernisation, in the increase's own quote or the title: a § 559 increase ("Mieterhöhung nach
#: Modernisierung") — or a modernised bathroom a § 558 request names as a feature of the flat, so it vetoes
#: only when the increase's own quote doesn't ask for consent (review round 2 of phase 2).
_MODERNISATION = re.compile(r"modernisierung|moderni[sz]ation", re.I)
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
#: A notice without notice period, in the termination's own quote or the reading's title: *fristlos*, "ohne
#: Einhaltung einer Kündigungsfrist", "without notice" …
_EXTRAORDINARY = re.compile(
    r"fristlos|ohne\s+einhaltung\s+(?:einer|der)\s+(?:kündigungs)?frist|without notice",
    re.I,
)
#: … or only its statute (§§ 543, 569 BGB for a tenancy, § 626 BGB for a job), which makes it only *probably*
#: one: a citation is named in a reservation ("eine fristlose Kündigung nach § 543 BGB behalten wir uns vor"),
#: a threat or a refusal as often as in the notice itself (review round 4 of phase 2: an ordinary notice that
#: reserved one lost its objection to-do).
_EXTRAORDINARY_STATUTE = re.compile(r"\b(?:543|569|626)\b[^§]{0,20}\bBGB\b", re.I)
#: … or only probably one: "außerordentlich" (extraordinary) said of the notice itself ("außerordentliche
#: Kündigung", "außerordentlich (und fristlos) kündigen", "kündigen … außerordentlich") — never the adverb of
#: something else ("wegen Ihres außerordentlich störenden Verhaltens", review round 2 of phase 2). An
#: extraordinary notice may also have the statutory period (§ 573d BGB), which the objection applies to.
_WORDS_BETWEEN = r"(?:[^\s.,;:!?]+\s+){0,6}?"
_PREPOSITION = r"(?:und|oder|sowie|bzw\.?|gemäß|gem\.|nach|wegen|aufgrund|aus|mit|zum|zur|per|mangels)\b"
_EXTRAORDINARY_ONLY = re.compile(
    r"au(?:ß|ss)erordentlich\w*(?:\s*,?\s*(?:und\s+|sowie\s+)?fristlos\w*)?\s+(?:kündig|gekündigt|zu\s+kündigen)"
    rf"|kündig\w*\s+{_WORDS_BETWEEN}au(?:ß|ss)erordentlich\b(?!\s+(?!{_PREPOSITION})[a-zäöüß])"
    r"|extraordinar\w*\s+(?:\w+\s+){0,2}?(?:termination|notice|cancell?ation)"
    rf"|terminat\w*\s+{_WORDS_BETWEEN}extraordinarily\b",
    re.I,
)
#: … unless the notice itself is ordinary (*ordentlich*, *fristgerecht*, *fristgemäß* — not inside
#: "außerordentlich"), said before any notice given in the alternative.
_ORDINARY = re.compile(
    r"(?<![^\W\d_])(?:ordentlich\w*|fristgerecht\w*|fristgemä(?:ß|ss)\w*)|\bordinary\s+(?:notice|termination)|"
    r"\bunter\s+(?:einhaltung|wahrung)\s+der\s+(?:\w+\s+)?kündigungsfrist",
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
    r",?\s+(?:(?!und\b|oder\b)[^\s,]+\s+){0,8}?(?:behalten\s+(?:wir|ich)\s+(?:uns|mir)|bleibt|bleiben|ist|wird)"
    r"\s+(?:\S+\s+){0,2}?vor(?:behalten)?\b",
    re.I,
)
#: … or refused, in its sentence: "von einer fristlosen Kündigung sehen wir ab", "auf eine fristlose Kündigung
#: verzichten wir", "wir wären zur fristlosen Kündigung berechtigt" (review round 4 of phase 2). A refusal of
#: something else in the same sentence counts too: the notice is then read as an ordinary one, the safe side.
_REFUSED = re.compile(
    r"\b(?:verzicht\w*|absehen|abzusehen|abgesehen)\b|\b(?:sehen|sehe|sieht)\s+(?:\S+\s+){0,4}?ab\b|"
    r"\bwären?\s+(?:\S+\s+){0,5}?(?:berechtigt|befugt)\b",
    re.I,
)
_SENTENCE_END = re.compile(r"[!?;\n]|\.(?=\s+[A-ZÄÖÜ]|\s*$)")
#: A special termination with the statutory notice period ("mit der gesetzlichen Frist", "mit gesetzlicher
#: Kündigungsfrist" as § 573d BGB is headed, "with statutory notice"): the hardship objection applies to it
#: (§ 574 Abs. 1 BGB excludes only a notice without notice period; § 575a Abs. 2 BGB for a fixed term; the
#: buyer at a forced sale, § 57a ZVG; the insolvency administrator, § 111 InsO; heirs, § 564 BGB; the end
#: of a usufruct, § 1056 BGB).
_STATUTORY_PERIOD = re.compile(
    r"(?:mit|unter\s+(?:einhaltung|wahrung))\s+(?:der\s+|einer\s+)?gesetzliche[nr]?\s+(?:kündigungs)?frist|"
    r"statutory\s+(?:notice(?:\s+period)?|period)|\b57(?:3d|5a)\b[^§]{0,20}\bBGB\b|\b57a\b[^§]{0,20}\bZVG\b|"
    r"\b111\b[^§]{0,20}\bInsO\b|\b564\b[^§]{0,20}\bBGB\b|\b1056\b[^§]{0,20}\bBGB\b",
    re.I,
)

#: … which only counts when it is said of the notice itself: not denied before it in its sentence ("without
#: statutory notice", "nicht mit der gesetzlichen Frist") — "ohne" and "without" deny it too.
_STATUTORY_DENIED = re.compile(r"\b(?:nicht|kein\w*|ohne|not|no|without)\b[^.!?;\n]{0,30}$", re.I)

#: A notice without notice period that also gives notice with one "in the alternative": *hilfsweise*,
#: "vorsorglich (auch) ordentlich", "zugleich ordentlich", or what it becomes if it fails ("gilt sie als
#: ordentliche Kündigung", "in eine ordentliche Kündigung umgedeutet" — review round 2 of phase 2).
_ORDINARILY = r"(?:ordentlich|fristgerecht|fristgemä(?:ß|ss))"
_ALTERNATIVE_NOTICE = re.compile(
    rf"hilfsweise|(?:vorsorglich|zugleich|gleichzeitig|jedenfalls)\s+(?:\S+\s+){{0,4}}?{_ORDINARILY}|"
    r"\bvorsorglich\s+(?:\S+\s+){0,4}?(?:zum|per|mit\s+ablauf|auf\s+den)\b|"
    rf"\bgilt\s+(?:\S+\s+){{0,4}}?als\s+(?:\S+\s+)?{_ORDINARILY}|"
    rf"\bals\s+{_ORDINARILY}\w*\s+kündigung\s+(?:\S+\s+){{0,2}}?(?:gelten|werten|verstehen|behandeln)|"
    rf"(?:umgedeutet|umdeutung)\s+(?:\S+\s+){{0,3}}?{_ORDINARILY}|"
    rf"{_ORDINARILY}\w*\s+kündigung\s+(?:\S+\s+){{0,2}}?(?:umgedeutet|umzudeuten|umdeuten)|"
    r"\bersatzweise|\bander(?:e)?nfalls\b|\bfür\s+den\s+fall\W+(?:\S+\s+){0,5}?(?:der\s+)?(?:unwirksam|nicht\s+wirksam|ungültig)|"
    r"\bsollte\s+(?:\S+\s+){0,6}?(?:unwirksam|nicht\s+wirksam|ungültig)|"
    r"alternatively|in the alternative",
    re.I,
)
#: … and, said of a notice certainly without notice period, a later end it also names: the next permissible
#: date ("fristlos, spätestens zum nächstmöglichen Zeitpunkt", "zum nächsten zulässigen Termin", "zum Ende der
#: gesetzlichen Kündigungsfrist") or any day at least two months after the letter's date ("fristlos, zugleich
#: vorsorglich zum 31.01.2027", "mit Ablauf des 31. Jan. 2027", "Ende Januar 2027") — a notice without notice
#: period ends the tenancy at once, so a later end can only be that of a notice with one (review rounds 3 and 4
#: of phase 2: "when unsure, it is an ordinary notice").
_NEXT_END_WORDS = re.compile(
    r"nächst(?:möglich|zulässig)|nächste[nmrs]?\s+(?:zulässig|möglich|erlaubt)\w*|"
    r"(?:zum|mit|per)\s+(?:ende|ablauf)\s+der\s+(?:\w+\s+)?kündigungsfrist|"
    r"next\s+(?:possible|permissible)",
    re.I,
)
_GERMAN_MONTHS = (
    "januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november",
    "dezember",
)  # fmt: skip
#: A month's end without its day: "Ende Januar 2027", "Monatsende Januar 2027", "Ende des Monats Januar 2027".
_MONTH_END = re.compile(
    rf"\b(?:monats)?ende\s+(?:des\s+monats\s+)?(?P<name>{'|'.join(_GERMAN_MONTHS)})\s+(?P<y>\d{{4}})\b",
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


def _european_order(extraction: DocumentExtraction) -> bool:
    """Whether the reading names a European order for payment (:data:`_EUROPEAN_ORDER`): no German court
    order, whatever the model calls it."""
    return bool(_EUROPEAN_ORDER.search(_reading_text(extraction)))


def _court_order(extraction: DocumentExtraction) -> HighStakesKind | None:
    """Which court order a court's letter is (policy 1: respondent, then title, else remedy), or ``None``."""
    if not _respondent(extraction) or _european_order(extraction):
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


def _abbreviates_court(name: str) -> bool:
    """Whether ``name`` abbreviates a court before its place (*AG Hagen*, *ArbG Berlin*, *SG Berlin*,
    *VG Minden*): no company's legal form, and a place of a word or two (:func:`_names_a_place`) — or a
    federal court's, whose place may be left out (*BGH*, *BSG, 1. Senat*)."""
    abbreviation = _COURT_ABBREVIATION.search(name.strip())
    if abbreviation is not None and _names_a_place(abbreviation.group("rest")):
        return True
    federal = _FEDERAL_COURT_ABBREVIATION.search(name.strip())
    if federal is None or _LEGAL_FORM.search(name):
        return False
    return federal.group("rest") is None or _names_a_place(federal.group("rest"))


def is_court(name: str, kind: str | None = None) -> bool:
    """Whether a sender's name is a court's (policy 1): it names a kind of court (*Amtsgericht*, also *des
    Amtsgerichts*; *Zentrales Mahngericht*, *Verfassungsgerichtshof*), or abbreviates one before its place
    (*AG Hagen*, *ArbG Berlin*, *SG Berlin*, *VG Minden*; a federal court's needs none, *BGH*) when the
    sender's ``kind`` is an authority or ``other`` — a retailer "LG Electronics", a
    landlord "OLG Immobilien", or a name of unknown kind (``None``: a recipient typed in, see
    :func:`may_be_court`) is no court — and is no bailiff or court cashier. Not recognised: a court named
    only in English (the kind the model names covers its orders, policy 1)."""
    if _NOT_A_COURT.search(name):
        return False
    if _COURT_SENDER.search(name):
        return True
    return kind in _COURT_KINDS and _abbreviates_court(name)


def may_be_court(name: str) -> bool:
    """Whether a name of unknown kind (a recipient typed into a template letter) may be a court's: it
    abbreviates one before a place (*AG Hagen*, *LG Köln*, *AG Hagen – Abteilung 12*) and is no bailiff or
    court cashier. A company whose name starts like one without a legal form (*LG Electronics*) can't be
    told apart, so such a recipient gets a court's sending advice with a note that e-mail is fine if it
    isn't one: a request sent to a court by plain e-mail isn't validly filed, and a letter is always fine
    (the safe side, ADR 0010)."""
    return not _NOT_A_COURT.search(name) and (bool(_COURT_SENDER.search(name)) or _abbreviates_court(name))


def is_labour_court(name: str, kind: str | None = None) -> bool:
    """Whether a court is a labour court (Arbeitsgericht, Landesarbeitsgericht): its orders give one week,
    not two (§ 46a Abs. 3, § 59 ArbGG)."""
    return is_court(name, kind) and bool(_LABOUR_COURT.search(name))


def is_social_court(name: str, kind: str | None = None) -> bool:
    """Whether a court is a social court (Sozialgericht, Landes-, Bundessozialgericht): its periods count
    under § 64 SGG, not § 222 ZPO."""
    return is_court(name, kind) and bool(_SOCIAL_COURT.search(name))


def classify_letter(extraction: DocumentExtraction) -> HighStakesKind | None:
    """The high-stakes kind a letter is filed under, or ``None`` (policy 1 above): the kind code reads
    (:func:`_classify_by_reading`) when it reads one or the model names none, else the one the model names
    (``high_stakes_kind``) unless the rest of the reading rules it out (:func:`_vetoed`). The model's
    ``operating_costs`` is never filed: a statement is recognised on read (:func:`names_statement`)."""
    code = _classify_by_reading(extraction)
    model = extraction.high_stakes_kind
    if code is not None or model is None or model == "operating_costs" or _vetoed(extraction, model):
        return code
    return model


def _classify_by_reading(extraction: DocumentExtraction) -> HighStakesKind | None:
    """The high-stakes kind code reads from the model's reading, or ``None`` (the table of policy 1)."""
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


def _vetoed(extraction: DocumentExtraction, kind: HighStakesKind) -> bool:
    """Whether the rest of the reading rules out the kind the model names (policy 1): a court order from a
    sender that is clearly no court (:func:`_no_court`) or a European order for payment; a rent increase of
    a kind that needs no consent (:func:`_needs_no_consent`); a dismissal or a landlord's notice about a
    contract of another category (:func:`_other_contract`)."""
    if kind in ("court_payment_order", "enforcement_order"):
        return _no_court(extraction.sender) or _european_order(extraction)
    if kind == "rent_increase":
        return _needs_no_consent(extraction)
    return _other_contract(extraction, kind)


def _no_court(sender: ExtractedParty | None) -> bool:
    """Whether a letter's sender is clearly no court: a bailiff or a court cashier (:data:`_NOT_A_COURT`),
    or a sender read as something no court is read as — a company (a debt collector), a landlord, a bank … —
    under a name that names no court (:func:`is_court`). A sender read as an authority or ``other`` may be a
    court whose name code doesn't recognise (one named only in English), and a letter without a sender may
    be a court's."""
    if sender is None:
        return False
    return not is_court(sender.name, sender.kind) and (
        sender.kind not in _COURT_KINDS or bool(_NOT_A_COURT.search(sender.name))
    )


def _other_contract(extraction: DocumentExtraction, kind: HighStakesKind) -> bool:
    """Whether the contract the reading names ends something other than ``kind`` (a dismissal or a
    landlord's notice): the contract decides first, as in :func:`_terminated` — a gym or a job ticket ends
    neither, a tenancy no job, a job no tenancy; a contract of category ``other`` says nothing."""
    category = extraction.contract.category if extraction.contract else None
    return category not in (None, "other") and _TERMINATED.get(category) != kind


def _consent_request(extraction: DocumentExtraction) -> bool:
    """Whether a rent increase asks for consent (policy 1): its quoted wording asks for it, and it is of no
    kind that needs none (:func:`_needs_no_consent`)."""
    return bool(_CONSENT.search(_quoted_text(extraction))) and not _needs_no_consent(extraction)


def _needs_no_consent(extraction: DocumentExtraction) -> bool:
    """Whether a rent increase is of a kind that needs no consent (policy 1): its own quote or its title
    names another kind of increase — graduated or index rent, or a § 559 or § 560 increase in the title;
    operating-cost prepayments or §§ 559–560 in its own quote, a prepayment adjustment in the title or a
    modernisation only when the increase's own quote doesn't ask for consent itself (a § 558 request names a
    modernised bathroom as a feature, quotes § 558 Abs. 1 S. 3 BGB on §§ 559–560 and may adjust the
    prepayments at the same time) — or something it quotes says no consent is needed."""
    quoted = _quoted_text(extraction)
    own = extraction.change.quote if extraction.change is not None else ""
    modernisation = bool(_MODERNISATION.search(f"{own}\n{extraction.title}")) and not _CONSENT.search(own)
    asks = bool(_ASKS_CONSENT.search(own))
    costs = bool(_COST_INCREASE.search(own) or _PREPAYMENT_TITLE.search(extraction.title))
    return bool(
        _OTHER_INCREASE.search(own)
        or _OTHER_INCREASE_TITLE.search(extraction.title)
        or (costs and not asks)
        or modernisation
        or _NO_CONSENT_NEEDED.search(quoted)
    )


def names_statement(extraction: DocumentExtraction) -> bool:
    """Whether a reading is an operating-cost statement (its card is worked out on read, policy 1): the
    model names it one (``high_stakes_kind``) or the reading does — in its title, or with a tenancy or a
    billing period —, and either way it isn't a reminder (a reminder about an old statement's back-payment
    quotes the statement without being it) and doesn't come from a utility or a public body."""
    sender = extraction.sender
    if extraction.kind == "dunning" or (sender is not None and sender.kind in _NOT_A_LANDLORD):
        return False
    if extraction.high_stakes_kind == "operating_costs":
        return True
    text = _reading_text(extraction)
    if not _OPERATING_COSTS.search(text):
        return False
    return (
        bool(_OPERATING_COSTS.search(extraction.title))
        or _about(extraction, _TENANCY)
        or bool(_BILLING_PERIOD.search(text))
    )


#: A negation that ends the clause after a wording: "Eine außerordentliche Kündigung sprechen wir nicht
#: aus", "eine fristlose Kündigung ist damit nicht verbunden" — not "wegen nicht gezahlter Miete".
_NEGATED_AFTER = re.compile(r"\b(?:nicht|nie|niemals|keinesfalls|not|never)(?:\s+[^\s,]+)?\s*$", re.I)


def _asserted(text: str, match: re.Match[str], *, statute: bool = False) -> bool:
    """Whether a wording in ``text`` is said in its sentence: not negated (before it, or at the end of its
    clause), not refused (:data:`_REFUSED`), and not a notice only reserved (:data:`_NOTICE` governed by a
    reservation before it or right after it; a wording without :data:`_NOTICE` after it by a reservation right
    after it). A ``statute`` (:data:`_EXTRAORDINARY_STATUTE`) is only reserved with any reservation in its
    sentence: "eine Kündigung nach § 543 BGB behalten wir uns vor"."""
    starts = [end.end() for end in _SENTENCE_END.finditer(text, 0, match.start())]
    after = _SENTENCE_END.search(text, match.end())
    before = text[starts[-1] if starts else 0 : match.start()]
    rest = text[match.end() : after.start() if after else len(text)]
    if _NEGATED.search(before) or _NEGATED_AFTER.search(rest.split(",", 1)[0]):
        return False
    if _REFUSED.search(f"{before} {rest}"):
        return False
    if statute and _RESERVING.search(f"{before} {rest}"):
        return False
    notice = _NOTICE.match(rest)
    if notice is None:
        return not _RESERVED_AFTER.match(rest)
    return not (_RESERVING.search(before) or _RESERVED_AFTER.match(rest, notice.end()))


def _gives_statutory_period(text: str) -> bool:
    """Whether ``text`` (the title, or the termination's own quote) gives the notice itself the statutory
    period (:data:`_STATUTORY_PERIOD`): not denied in its sentence ("without statutory notice"), and not in
    the notice given in the alternative — anything after *hilfsweise* ("fristlos, hilfsweise ordentlich
    unter Einhaltung der gesetzlichen Kündigungsfrist") is that notice's period, not this one's."""
    alternative = _ALTERNATIVE_NOTICE.search(text)
    for match in _STATUTORY_PERIOD.finditer(text):
        if alternative is not None and alternative.start() < match.start():
            return False  # the rest of the text is the notice given in the alternative
        starts = [end.end() for end in _SENTENCE_END.finditer(text, 0, match.start())]
        if not _STATUTORY_DENIED.search(text[starts[-1] if starts else 0 : match.start()]):
            return True
    return False


def _gives_ordinary(text: str) -> bool:
    """Whether ``text`` (the title, or the termination's own quote) calls the notice itself ordinary
    (:data:`_ORDINARY`): said, not negated or only reserved, and before any notice given in the alternative
    ("fristlos, hilfsweise ordentlich" is still a notice without notice period)."""
    alternative = _ALTERNATIVE_NOTICE.search(text)
    for match in _ORDINARY.finditer(text):
        if alternative is not None and alternative.start() <= match.start():
            return False
        if _asserted(text, match):
            return True
    return False


NoticeWithoutPeriod = Literal["certain", "probable"]


def notice_without_period(
    extraction: DocumentExtraction, letter_date: date | None = None
) -> NoticeWithoutPeriod | None:
    """Whether a termination is one without notice period (*fristlos*), the only one the hardship
    objection doesn't apply to (§ 574 Abs. 1 S. 2 BGB): ``"certain"``, ``"probable"`` or ``None``.

    Only the termination's own quote and the reading's title count — never the model's summary or
    other quotes, which may mention a *fristlose Kündigung* the landlord only reserves. The wording must
    say it — *fristlos*, "ohne Einhaltung einer Kündigungsfrist", "without notice", § 543 or § 569 BGB
    (``"certain"``), or only "außerordentlich"/"extraordinary" said of the notice itself ("außerordentliche
    Kündigung", "kündigen … außerordentlich" — never an adverb of something else, "wegen Ihres
    außerordentlich störenden Verhaltens"), which may also be a special termination with the statutory
    period (§ 573d BGB; ``"probable"``) — and not deny it (before it, or at the end of its clause: "eine
    fristlose Kündigung ist damit nicht verbunden") or only reserve it. The notice itself must not be called
    ordinary (*ordentlich*, *fristgerecht*, *fristgemäß* before any notice given in the alternative), nor be
    given the statutory period (*mit der gesetzlichen Frist*, *mit gesetzlicher Kündigungsfrist*, "with
    statutory notice": a special termination the objection applies to) — a statutory period that is denied
    ("without statutory notice") or belongs to the notice given in the alternative ("fristlos, hilfsweise
    ordentlich unter Einhaltung der gesetzlichen Kündigungsfrist") doesn't count (:func:`_gives_statutory_period`).
    And the tenancy must end soon: no end stated, or one less than two months after the letter's date
    (``letter_date``, else the reading's) — unless it is the end of a notice given in the alternative
    (*hilfsweise*). When unsure, it is an ordinary notice: its objection to-do is kept, and the card says it
    doesn't apply to a notice without notice period.
    """
    own = extraction.change.quote if extraction.change is not None else ""
    text = f"{extraction.title}\n{own}"
    if any(_gives_statutory_period(part) or _gives_ordinary(part) for part in (extraction.title, own)):
        return None
    if any(_asserted(text, match) for match in _EXTRAORDINARY.finditer(text)):
        strength: NoticeWithoutPeriod = "certain"
    elif _states_statute(text) or any(_asserted(text, match) for match in _EXTRAORDINARY_ONLY.finditer(text)):
        strength = "probable"
    else:
        return None
    end = announced_end(extraction)
    written = letter_date or _parse_day(extraction.document_date)
    # a later end the reading gives may be the notice's own (an ordinary notice); one given by a word such
    # as "hilfsweise" is the notice's in the alternative
    if end is None or _ALTERNATIVE_NOTICE.search(text):
        return strength
    return strength if written is not None and notice_objection_deadline(end) < written else None


def extraordinary_notice(extraction: DocumentExtraction, letter_date: date | None = None) -> bool:
    """Whether a termination reads as one without notice period, certainly or probably
    (:func:`notice_without_period`): its card says what that means for the hardship objection."""
    return notice_without_period(extraction, letter_date) is not None


def objection_excluded(extraction: DocumentExtraction, letter_date: date | None = None) -> bool:
    """Whether the hardship objection is out of the question for a termination: it is certainly one
    without notice period (:func:`notice_without_period`) and gives no notice with one in the alternative
    (:func:`alternative_notice`). Then no objection to-do is filed and none is drafted; for a notice only
    probably without notice period ("außerordentlich") both are kept, the safe side (ADR 0010)."""
    return notice_without_period(extraction, letter_date) == "certain" and not alternative_notice(extraction)


def alternative_notice(extraction: DocumentExtraction) -> bool:
    """Whether a notice without notice period also gives notice with one in the alternative
    (*hilfsweise fristgemäß*, *ersatzweise*, *andernfalls*, "sollte die fristlose Kündigung unwirksam sein"):
    its objection to-do and letter are kept — the hardship objection is excluded against it too if the
    grounds for the notice without notice period existed (§ 574 Abs. 1 S. 2 BGB; BGH VIII ZR 323/18), but
    they may not have, and the card says so. A notice certainly without notice period that also names a later
    end (:data:`_NEXT_END_WORDS`, a day at least two months after the letter's date: :func:`_later_end`) gives
    one too, whatever connects them. Like :func:`extraordinary_notice`, only the termination's own quote and
    the reading's title count — never the model's summary ("alternatively you may pay the arrears")."""
    own = extraction.change.quote if extraction.change is not None else ""
    text = f"{extraction.title}\n{own}"
    if _ALTERNATIVE_NOTICE.search(text):
        return True
    if not (any(_asserted(text, match) for match in _EXTRAORDINARY.finditer(text)) or _states_statute(text)):
        return False
    return bool(_NEXT_END_WORDS.search(text)) or _later_end(text, _parse_day(extraction.document_date))


def _states_statute(text: str) -> bool:
    """Whether ``text`` gives the notice under a statute of a notice without notice period, not reserved,
    refused or negated (:data:`_EXTRAORDINARY_STATUTE`)."""
    return any(_asserted(text, match, statute=True) for match in _EXTRAORDINARY_STATUTE.finditer(text))


def _later_end(text: str, letter_date: date | None) -> bool:
    """Whether ``text`` names any day (``zum 31.01.2027``, ``mit Ablauf des 31. Jan. 2027``, ``2027-01-31``;
    a month's end, ``Ende Januar 2027``) the hardship objection could still be raised against: two months
    before it is not before the letter's date (unknown: any day counts — the safe side)."""
    ends = [mention.as_date() for mention in parse_dates(text)]
    ends += [
        month_end(date(int(found.group("y")), _GERMAN_MONTHS.index(found.group("name").lower()) + 1, 1))
        for found in _MONTH_END.finditer(text)
    ]
    return any(
        end is not None and (letter_date is None or notice_objection_deadline(end) >= letter_date)
        for end in ends
    )


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
    if spec.nature == "payment" and letter == "rent_increase":
        return (
            "bgb_558b"  # the new rent is owed from the third month after the request arrived at the earliest
        )
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


#: A notice whose own end is too early for an objection (a notice too short for its period), or that has no
#: end read (given in the alternative, "zum nächstmöglichen Termin"): it usually ends the tenancy at the next
#: permissible date (§ 573c Abs. 1 BGB), so the objection counts back from the earliest one
#: (:mod:`ordnung.rules.letters`), with less confidence.
_NEXT_END_OBJECTION = replace(
    _NOTICE_OBJECTION,
    action=(
        "The notice's own end is too early for its notice period, or it gives none: it usually ends your tenancy "
        "at the next date the law allows, so the objection deadline counts back two months from the earliest "
        f"possible end. {_NOTICE_OBJECTION.action}"
    ),
    spec=_relative(
        -2,
        "months",
        "objection",
        "§ 574b Abs. 2, § 573c Abs. 1 BGB",
        "spätestens zwei Monate vor dem nächstmöglichen Kündigungstermin",
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


def objection_dated(spec: DateSpec) -> bool:
    """Whether a letter's own objection date can be computed without the end of the tenancy
    (``dated`` of :func:`derived_deadlines`): a date written in it, or a period counted back from a date it
    names. The statutory hint every notice carries — "Widerspruch spätestens zwei Monate vor der Beendigung
    des Mietverhältnisses", read as a period from an end it doesn't give — names none, so a notice "zum
    nächstmöglichen Termin" keeps the law's objection to-do (review round 3 of phase 2)."""
    if spec.nature != "objection":
        return False
    if spec.type == "fixed":
        return _parse_day(spec.date) is not None
    return spec.type == "relative" and _parse_day(spec.anchor_date) is not None


ShortNotice = Literal["passed", "short"]


def short_notice(
    end: date | None, *, letter_date: date | None, arrived: date | None = None, region: str | None = None
) -> ShortNotice | None:
    """Whether a landlord's notice ending on ``end`` is too short for its notice period: ``"passed"`` when the
    objection's day (two months before the end) had passed before the letter was written (``letter_date``);
    ``"short"`` when the end is earlier than the earliest end a notice with a notice period that arrived on
    ``arrived`` (else the letter's date) can have (§ 573c Abs. 1 BGB, :func:`~ordnung.rules.tenancy.next_permissible_end`;
    ``region``: the tenant's Land) — then the stated end's objection date may have passed while the one of the
    end the notice usually has instead is still open (review round 4 of phase 2); else ``None``."""
    if end is None:
        return None
    if letter_date is not None and notice_objection_deadline(end) < letter_date:
        return "passed"
    arrival = arrived or letter_date
    if arrival is not None and end < next_permissible_end(arrival, region):
        return "short"
    return None


def derived_deadlines(
    letter: str | None,
    *,
    end: date | None,
    letter_date: date | None = None,
    arrived: date | None = None,
    region: str | None = None,
    extraordinary: bool = False,
    labour_court: bool = False,
    alternative: bool = False,
    dated: bool = False,
) -> list[DerivedDeadline]:
    """The deadlines the law adds to a kind of letter; ``end`` is the end its termination announces.
    A court order from a labour court (``labour_court``) gives one week (§ 46a Abs. 3, § 59 ArbGG).

    The objection to a landlord's notice counts back from the end of the tenancy — not for a notice
    certainly without notice period that gives none in the alternative (``extraordinary``,
    :func:`objection_excluded`): the hardship objection doesn't apply to it (§ 574 Abs. 1 S. 2 BGB), and its
    card points to advice instead. When the end is too early for the notice's period (:func:`short_notice`:
    less than two months after the letter's date ``letter_date``, or before the earliest end a notice that
    arrived on ``arrived`` can have in the tenant's Land ``region``) or none was read (a notice "zum
    nächstmöglichen Termin", one given in the ``alternative``, or an end the reading missed), the objection
    counts back from the earliest end a notice with a notice period can have (§ 573c Abs. 1 BGB) — such a
    notice usually ends the tenancy at the next permissible date, and a later real end only makes the
    objection's deadline later (the earliest plausible date; review round 2 of phase 2) — unless an ordinary
    notice without an end gives an objection date of its own that can be computed (``dated``,
    :func:`objection_dated`): that date counts from the end the landlord knows.
    """
    if letter == "court_payment_order":
        return [_LABOUR_COURT_ORDER if labour_court else _COURT_ORDER]
    if letter == "enforcement_order":
        return [_LABOUR_ENFORCEMENT if labour_court else _ENFORCEMENT]
    if letter == "dismissal":
        return [_COURT_ACTION, _REGISTER]
    if letter == "rent_increase":
        return [_CONSENT_DECISION]
    if letter == "landlord_notice" and not extraordinary:
        if end is None and dated and not alternative:
            return []
        if end is None or short_notice(end, letter_date=letter_date, arrived=arrived, region=region):
            return [_NEXT_END_OBJECTION]
        spec = _NOTICE_OBJECTION.spec.model_copy(
            update={"anchor": "explicit_date", "anchor_date": end.isoformat()}
        )
        action = f"Your tenancy ends on {fmt_date(end)}. {_NOTICE_OBJECTION.action}"
        return [replace(_NOTICE_OBJECTION, spec=spec, action=action)]
    return []
