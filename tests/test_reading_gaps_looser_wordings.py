"""The dropped-date check's looser path (ADR 0015, 2026-10-07): each confirmed false alarm or lost date, as a
regression test, updated for the path as it was narrowed.

The looser path files its low "Please check" to-do only for a request that asks the person in its own words at its
sentence's start ("Senden Sie uns …", "Bitte gleichen Sie … aus", "Bitte lassen Sie uns … zukommen", "Wir bitten Sie
um Zahlung …", "Bitte bis … überweisen", "Kindly pay …", "Please ensure …"), never beside a third party, the sender's
own act, a condition, something done, an offer, survey, contest, tender or event, a holiday or opening hours; a label
line or labelled sentence only on a page that asks the person for its kind. A date without its year files nothing
(``test_reading_gaps_looser_false_alarms.py``). Where a test below once showed a wording the narrowing
dropped, it now shows that wording filing nothing. The strict path is the base's (0ff51e3) for every date with its
year: its results here were read from the base code and are pinned as they were. Invented letters only.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

from helpers_tables import check_rows
from ordnung.ingest.gaps import _noun_kind, _nouns_kind, deadline_items
from ordnung.models import ExtractedItem
from test_reading_gaps import page
from test_reading_gaps_looser import TODAY, filed, letter, reading

W = date(2026, 10, 5)  # the letters' date
PAYS = [("2026-10-23", "payment")]
SENDS = [("2026-10-23", "declaration")]
HEAD = (
    "Stadtwerke Beispielhausen · Postfach 10 · 12345 Beispielhausen",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Datum: 05.10.2026",
    "Sehr geehrte Frau Probe,",
)


def in_letter(
    *lines: str, written: date = W, items: list[ExtractedItem] | None = None
) -> list[tuple[str | None, str]]:
    """The dates filed for a whole letter's lines (its header and close included by the caller)."""
    found = deadline_items(reading(written, items), [page(*lines)], today=TODAY)
    return [(item.date.date, item.date.nature) for item in found]


def due(on: str, quote: str = "Rechnung", nature: str = "payment") -> ExtractedItem:
    return ExtractedItem.model_validate(
        {
            "kind": "payment" if nature == "payment" else "deadline",
            "title": "Pay" if nature == "payment" else "Send",
            "date": {"type": "fixed", "date": on, "nature": nature},
            "quote": quote,
        }
    )


# --------------------------------------------------------------------------------------------------
# A day-month long before the letter's date is an old line, never next year's date
# --------------------------------------------------------------------------------------------------


def test_an_old_line_with_its_year_files_nothing() -> None:
    sentence = "Offene Posten: Rechnung 4711 vom 02.03.2026, fällig am 16.03.2026, 120,00 €"
    assert filed(sentence, W) == []


def test_a_reminder_s_old_line_files_nothing_beside_the_reading_s_new_date() -> None:
    lines = (
        *HEAD,
        "Bitte überweisen Sie den Betrag bis zum 20.10.2026.",
        "Offene Posten: Rechnung 4711 vom 02.03., fällig am 16.03., 120,00 €",
        "Mit freundlichen Grüßen",
    )
    reading_due = due("2026-10-20", "Bitte überweisen Sie den Betrag bis zum 20.10.2026.")
    assert in_letter(*lines, items=[reading_due]) == []


def test_a_december_letter_s_january_date_without_its_year_files_nothing() -> None:
    """The narrowing dropped dates without their year: a next-year roll-over is never read again."""
    assert (
        filed("Bitte überweisen Sie den Betrag bis zum 15.01.", date(2026, 12, 10), today=date(2026, 12, 11))
        == []
    )
    assert filed(
        "Bitte überweisen Sie den Betrag bis zum 15.01.2027.", date(2026, 12, 10), today=date(2026, 12, 11)
    ) == [("2027-01-15", "payment")]


# --------------------------------------------------------------------------------------------------
# The strict path files as on base 0ff51e3 (results read from the base code)
# --------------------------------------------------------------------------------------------------


STRICT_PATH_AS_ON_BASE = [
    ("Der Mieter hat die Nachzahlung bis zum 20.11.2026 zu zahlen.", "de", [("2026-11-20", "payment")]),
    ("Die Mieterin hat die Nachzahlung bis zum 20.11.2026 zu zahlen.", "de", [("2026-11-20", "payment")]),
    ("Bitte zahlen Sie den Rückstand auf Ihrem Konto bis zum 20.11.2026.", "de", [("2026-11-20", "payment")]),
    (
        "Wir verweisen auf die an Sie gerichtete Zahlungsaufforderung und bitten Sie, den Betrag bis zum "
        "20.11.2026 zu überweisen.",
        "de",
        [("2026-11-20", "payment")],
    ),
    ("Please pay the arrears into your account by 20 November 2026.", "en", [("2026-11-20", "payment")]),
    (
        "Please pay the outstanding amount by 23 October 2026 to avoid further charges to your account.",
        "en",
        PAYS,
    ),
    ("Bitte überweisen Sie den zu viel an Sie überwiesenen Betrag bis zum 23.10.2026.", "de", PAYS),
    (
        "Wir wenden uns an Sie wegen der Zahlung Ihrer Rechnung Nr. 4711; bitte überweisen Sie den Betrag bis "
        "zum 23.10.2026.",
        "de",
        PAYS,
    ),
    ("Die Bank hat uns mitgeteilt: Bitte überweisen Sie den Betrag bis zum 23.10.2026.", "de", PAYS),
    (
        "Ihr Arbeitgeber hat uns Ihre Lohndaten übermittelt; bitte reichen Sie die fehlenden Belege bis zum "
        "23.10.2026 ein.",
        "de",
        SENDS,
    ),
    (
        "Please pay the outstanding balance by 23 October 2026 to avoid a late fee being added to your account.",
        "en",
        PAYS,
    ),
    ("Please pay 120.00 EUR by 23 October 2026; otherwise interest will be charged to your account.", "en", PAYS),
    (
        "Bitte überweisen Sie den Betrag bis zum 23.10.2026; die Bank wird Ihnen dann eine Bestätigung senden.",
        "de",
        PAYS,
    ),
    ("Ihre Krankenkasse hat uns informiert: Bitte reichen Sie die Belege bis zum 23.10.2026 ein.", "de", SENDS),
    # a condition after "und" / "oder" silences the strict path, as before
    (
        "Bitte prüfen Sie die Abrechnung und sollten Sie Einwände haben, teilen Sie uns diese bis zum 23.10.2026 "
        "mit.",
        "de",
        [],
    ),
    (
        "Bitte prüfen Sie die Angaben, oder sollten Sie Fragen haben, teilen Sie uns diese bis zum 23.10.2026 mit.",
        "de",
        [],
    ),
    # the base's own false alarms stay, documented (a third party's strict request)
    ("Der Arbeitgeber hat die Unterlagen bis 30.10.2026 bei der Krankenkasse einzureichen.", "de",
     [("2026-10-30", "declaration")]),
    ("Der Schuldner hat den Betrag bis spätestens 26.10.2026 an Sie zu überweisen.", "de",
     [("2026-10-26", "payment")]),
]  # fmt: skip


def test_the_strict_path_files_as_on_base() -> None:
    def check(sentence: str, lang: str, expected: list[tuple[str, str]]) -> None:
        assert filed(sentence, W, lang) == expected

    check_rows(STRICT_PATH_AS_ON_BASE, check)


def test_a_looser_condition_after_und_or_oder_is_still_a_condition() -> None:
    assert (
        filed(
            "Senden Sie uns die Unterlagen bis zum 23.10.2026 und sollten Sie Fragen haben, rufen Sie an.", W
        )
        == []
    )
    assert filed("Senden Sie uns die Unterlagen bis zum 23.10.2026.", W) == SENDS


# --------------------------------------------------------------------------------------------------
# The kind from the verb, else from the head noun (whole words, a compound by its last word)
# --------------------------------------------------------------------------------------------------


HEAD_NOUN_KINDS = [
    ("Bitte senden Sie uns Ihren Steuerbescheid bis zum 20.11.2026.", "de", "declaration"),
    (
        "Bitte lassen Sie uns den Nachweis über Ihre Zahlung bis zum 20.11.2026 zukommen.",
        "de",
        "declaration",
    ),
    ("Bitte lassen Sie uns Ihre Nebenkostenabrechnung bis zum 20.11.2026 zukommen.", "de", "declaration"),
    ("Bitte gleichen Sie die Gebühr für Ihren Antrag bis zum 20.11.2026 aus.", "de", "payment"),
    ("Bitte lassen Sie uns Ihre Mietbescheinigung bis zum 20.11.2026 zukommen.", "de", "declaration"),
]


def test_the_kind_is_the_head_noun_s() -> None:
    def check(sentence: str, lang: str, expected: str) -> None:
        assert filed(sentence, W, lang) == [("2026-11-20", expected)]

    check_rows(HEAD_NOUN_KINDS, check)


DROPPED_WORDINGS = [
    # head-noun cases, in wordings the narrowing dropped: nothing
    ("Den Nachweis über Ihre Zahlung des Beitrags benötigen wir bis zum 20.11.2026.", "de"),
    ("We need your evidence of rent payments by 20 November 2026.", "en"),
    ("Die Gebühr für Ihren Antrag muss bis zum 20.11.2026 bei uns eingegangen sein.", "de"),
]


def test_the_dropped_wordings_file_nothing() -> None:
    def check(sentence: str, lang: str) -> None:
        assert filed(sentence, W, lang) == []

    check_rows(DROPPED_WORDINGS, check)


def test_a_noun_s_kind_is_a_whole_word_s() -> None:
    assert _noun_kind("Vermieters") is None  # no "Miete"
    assert _noun_kind("Nebenkostenabrechnung") == ("declaration", False)  # an Abrechnung, not "Kosten"
    assert _noun_kind("Steuerbescheid") == ("declaration", False)
    assert _noun_kind("Zahlungsnachweis") == ("declaration", False)
    assert _noun_kind("Antragsgebühr") == ("payment", False)
    assert _noun_kind("Kaltmiete") == ("payment", False)
    assert _noun_kind("Beitrag") == ("payment", True)  # only beside an amount or a payment's verb
    assert _nouns_kind("Ihren Beitrag zum Wettbewerb") is None
    assert _nouns_kind("den Kostenbeitrag von 35 €") == "payment"
    # both kinds, neither the other's topic: unclear, no to-do
    assert _nouns_kind("die Unterlagen und den Betrag") is None


def test_a_fee_named_beside_a_document_goes_through_the_debit_gate() -> None:
    lines = (
        *HEAD,
        "Die Jahresgebühr wird per SEPA-Lastschrift eingezogen.",
        "Bitte gleichen Sie die Gebühr für Ihren Antrag bis zum 25.11.2026 aus.",
        "Mit freundlichen Grüßen",
    )
    assert in_letter(*lines) == []
    assert in_letter(*lines[:-3], *lines[-2:]) == [("2026-11-25", "payment")]  # without the debit's line


THIRD_PARTY_OR_UNADDRESSED = [
    # a label alone, on a page that asks for nothing
    "Abgabe der Nebenkostenabrechnung bis: 31.12.2026",
    # the same sentences as written name no one: not addressed
    "Den Nachweis über die Zahlung des Beitrags benötigen wir bis zum 20.11.2026.",
    "Die Nebenkostenabrechnung muss uns bis zum 20.11.2026 vorliegen.",
    "Die Gebühr für den Antrag muss bis zum 20.11.2026 bei uns eingegangen sein.",
]


def test_a_third_party_s_paper_or_an_unaddressed_sentence_files_nothing() -> None:
    def check(sentence: str) -> None:
        assert filed(sentence, W) == []

    check_rows(THIRD_PARTY_OR_UNADDRESSED, check)


def test_a_label_on_a_page_that_asks_for_its_kind_files() -> None:
    assert filed(
        "Bitte senden Sie uns die Unterlagen zu.\nAbgabe der Nebenkostenabrechnung bis: 31.12.2026", W
    ) == [("2026-12-31", "declaration")]


# --------------------------------------------------------------------------------------------------
# Payment participles and nouns (a wording the narrowing dropped: nothing now)
# --------------------------------------------------------------------------------------------------


MUST_BE_PAID_OR_SENT = [
    # "… muss bis … bezahlt werden", "must be received by": wordings the narrowing dropped
    ("Ihre Rechnung muss bis zum 20.11. beglichen sein.", "de", []),
    ("Ihre Prämie muss bis zum 20.11.2026 bei uns eingegangen sein.", "de", []),
    ("Ihre Unterlagen müssen bis zum 20.11.2026 bei uns eingereicht werden.", "de", []),
    # as written, they name no one: not addressed
    ("Die Rechnung muss bis zum 20.11.2026 bezahlt werden.", "de", []),
    ("Die Kaution muss bis zum 20.11.2026 überwiesen werden.", "de", []),
    ("Der Betrag muss bis zum 20.11.2026 gezahlt werden.", "de", []),
]  # fmt: skip


def test_a_must_be_paid_or_sent_wording_files_nothing() -> None:
    def check(sentence: str, lang: str, expected: list[tuple[str, str]]) -> None:
        assert filed(sentence, W, lang) == expected

    check_rows(MUST_BE_PAID_OR_SENT, check)


# --------------------------------------------------------------------------------------------------
# A deadline's own sentence and a paid letter (the strict path's gate, read once for both paths)
# --------------------------------------------------------------------------------------------------


EINGEGANGEN_OR_PAID_IN_FULL = [
    # the narrowing dropped these wordings (and with them the looser path's own reading of a paid letter)
    ("Bis zum 20.11.2026 muss Ihr Betrag bei uns eingegangen sein.", "de"),
    ("Ihr Betrag muss bis spätestens 20.11.2026 bei uns eingegangen sein.", "de"),
]


def test_a_deadline_s_own_eingegangen_or_paid_in_full_files_nothing_now() -> None:
    def check(sentence: str, lang: str) -> None:
        assert filed(sentence, W, lang) == []

    check_rows(EINGEGANGEN_OR_PAID_IN_FULL, check)


# --------------------------------------------------------------------------------------------------
# The year a sentence names (dates without their year: nothing since the narrowing)
# --------------------------------------------------------------------------------------------------


YEARLESS_WITH_A_YEAR_NAMED = [
    # the narrowing dropped dates without their year: none of these files, whatever year the sentence names
    ("Bitte reichen Sie die Unterlagen bis zum 31.03. des Folgejahres ein.", date(2026, 1, 10), "de"),
    ("Bitte reichen Sie die Unterlagen bis zum 31. März des nächsten Jahres ein.", date(2026, 1, 10), "de"),
    ("Please submit your return by 31 March next year.", date(2026, 1, 10), "en"),
    ("Ihre Steuererklärung 2025 ist bis zum 31.07. des Folgejahres einzureichen.", date(2026, 1, 10), "de"),
    ("Der Beitrag für das Jahr 2027 wird zum 15.11. fällig.", W, "de"),
    ("Zahlungsplan 2027: erste Rate fällig am 15.11.", W, "de"),
    ("Die Jahresabrechnung 2027 ist bis zum 30.11. zu begleichen.", W, "de"),
    ("Für das Jahr 2028 ist der Beitrag bis zum 15.01. zu zahlen.", W, "de"),
    # a rule of every year names no deadline of this letter's
    ("Ab 2027 ist der Jahresbeitrag jeweils bis zum 31.12. zu zahlen.", W, "de"),
]  # fmt: skip


def test_a_date_without_its_year_files_nothing_whatever_year_its_sentence_names() -> None:
    def check(sentence: str, written: date, lang: str) -> None:
        today = written + timedelta(days=2)
        assert filed(sentence, written, lang, today=today) == []

    check_rows(YEARLESS_WITH_A_YEAR_NAMED, check)


# --------------------------------------------------------------------------------------------------
# A second date of one obligation, without its year or in looser words, is no second to-do
# --------------------------------------------------------------------------------------------------


def test_a_second_date_of_the_reading_s_payment_files_nothing() -> None:
    box = "Zahlbar bis: 20.11.2026"
    reading_due = due("2026-11-20", box)
    assert (
        filed(f"{box}\nBitte überweisen Sie den Rechnungsbetrag bis zum 27.11.", W, items=[reading_due]) == []
    )
    assert (
        filed(f"{box}\nBitte überweisen Sie den Rechnungsbetrag bis zum 27.11.2026.", W, items=[reading_due])
        == []
    )
    assert (
        filed(
            f"{box}\nWir bitten Sie um Zahlung des Rechnungsbetrags bis zum 27.11.2026.",
            W,
            items=[reading_due],
        )
        == []
    )


def test_two_dates_of_one_obligation_file_the_strict_one() -> None:
    assert filed("Fällig am: 13.11.\nBitte überweisen Sie den Rechnungsbetrag bis zum 20.11.", W) == []
    # beside a strict date with its year still to come, a looser one of its kind files nothing
    looser = "Bitte gleichen Sie den Rechnungsbetrag bis zum 27.11.2026 aus."
    assert filed(f"Zahlbar bis: 20.11.2026.\n{looser}", W) == [("2026-11-20", "payment")]
    assert filed(looser, W) == [("2026-11-27", "payment")]


# --------------------------------------------------------------------------------------------------
# What the sender waits for, the sender's own act, a third party mid-sentence
# --------------------------------------------------------------------------------------------------


SENDER_OR_ANOTHER_ACTS = [
    ("Die Antwort der Versicherung wird bis zum 23.10.2026 erwartet.", "de"),
    ("Unser Bericht an die Behörde muss bis zum 23.10.2026 vorliegen.", "de"),
    ("Die Zahlung an den Lieferanten muss bis zum 23.10.2026 erfolgen; das erledigen wir.", "de"),
    ("Employers are required to submit the forms by 23 October 2026.", "en"),
    ("Eine Entscheidung über Ihren Antrag wird bis zum 23.10.2026 erwartet.", "de"),
    ("We expect to complete the repair of your application by 23 October 2026.", "en"),
]


def test_what_the_sender_or_another_does_files_nothing() -> None:
    def check(sentence: str, lang: str) -> None:
        assert filed(sentence, W, lang) == []

    check_rows(SENDER_OR_ANOTHER_ACTS, check)


def test_a_request_for_the_person_s_papers_in_a_dropped_wording_is_missed() -> None:
    """Real requests, but in the "benötigen wir" / "we expect" wordings the narrowing dropped (they filed what the
    sender waits for from others): a documented miss, never a false alarm."""
    assert filed("Für die weitere Bearbeitung benötigen wir Ihre Unterschrift bis zum 23.10.2026.", W) == []
    assert (
        filed(
            "Damit wir Ihren Antrag bearbeiten können, benötigen wir Ihre Unterlagen bis zum 23.10.2026.", W
        )
        == []
    )
    assert filed("We expect to receive your documents by 23 October 2026.", W, "en") == []
    # asked in the person's own words, the same request files
    assert filed("Bitte senden Sie uns Ihre Unterschrift bis zum 23.10.2026.", W) == SENDS


# --------------------------------------------------------------------------------------------------
# Money or papers that come to the person
# --------------------------------------------------------------------------------------------------


def test_money_or_papers_coming_to_the_person_file_nothing() -> None:
    sentence = "Die Abrechnung des Vermieters muss bis zum 31.12.2026 bei Ihnen eingegangen sein."
    assert filed(sentence, W) == []


# --------------------------------------------------------------------------------------------------
# Another party's Frist, or the sender's
# --------------------------------------------------------------------------------------------------


def test_a_table_of_the_other_side_s_fristen_files_nothing() -> None:
    lines = (
        *HEAD,
        "Fristen der Gegenseite im Überblick:",
        "Zahlungsfrist: 23.10.2026",
        "Mit freundlichen Grüßen",
    )
    assert in_letter(*lines) == []


def test_a_frist_set_for_the_person_is_missed() -> None:
    """The narrowing dropped the Frist wordings (another party's Frist filed through "Ihnen" or "Ihr…"): missed."""
    assert (
        filed("Zur Zahlung des offenen Betrags setzen wir Ihnen eine letzte Frist bis zum 23.10.2026.", W)
        == []
    )
    assert filed("Ihre Zahlungsfrist endet am 23.10.2026.", W) == []


# --------------------------------------------------------------------------------------------------
# Conditions
# --------------------------------------------------------------------------------------------------


CONDITIONS = [
    ("Ggf. erforderliche Nachweise müssen Sie uns bis zum 23.10.2026 vorlegen.", "de"),
    ("Für Selbstständige müssen Ihre Einkommensnachweise bis zum 23.10.2026 bei uns vorliegen.", "de"),
    ("Sollten Sie Fragen haben, senden Sie uns Ihre Unterlagen bis zum 23.10.2026.", "de"),
]


def test_a_condition_files_nothing() -> None:
    def check(sentence: str, lang: str) -> None:
        assert filed(sentence, W, lang) == []

    check_rows(CONDITIONS, check)


# --------------------------------------------------------------------------------------------------
# Done, paid, stated
# --------------------------------------------------------------------------------------------------


DONE_OR_STATED = [
    (
        "Thank you, your documents are complete. A decision on your application is expected by 23 October 2026.",
        "en",
    ),
    ("There is nothing you need to send us; we expect the court's documents by 23 October 2026.", "en"),
]


def test_something_done_or_stated_files_nothing() -> None:
    def check(sentence: str, lang: str) -> None:
        assert filed(sentence, W, lang) == []

    check_rows(DONE_OR_STATED, check)


PAID_OR_STATED_TABLES = [
    ("Ihr Zahlungsplan", "Rate 1: 100,00 € – Zahlung bis: 23.10.2026 – erledigt"),
    ("hier Ihre Übersicht der bezahlten Rechnungen:", "Rechnung | Betrag | Zahlung bis | Bezahlt am",
     "R-17 | 50,00 € | Zahlung bis: 23.10.2026 | 01.10.2026"),
    ("Ihr Ratenplan (alle Raten werden per Dauerauftrag beglichen):", "Rate 1 · Zahlung bis: 23.10.2026 · 100,00 €",
     "Rate 2 · Zahlung bis: 23.11.2026 · 100,00 €"),
    ("Übersicht Ihrer Beiträge", "Zahlung bis: 23.10.2026 · Betrag: 45,00 € · Status: offen"),
]  # fmt: skip


def test_a_paid_or_stated_table_files_nothing() -> None:
    def check(*lines: str) -> None:
        assert in_letter(*HEAD, *lines, "Mit freundlichen Grüßen") == []

    check_rows(PAID_OR_STATED_TABLES, check)


# --------------------------------------------------------------------------------------------------
# Offers, surveys, contests, tenders, events
# --------------------------------------------------------------------------------------------------


OFFERS_SURVEYS_CONTESTS_EVENTS = [
    (
        "Wir bitten Sie um Rückmeldung bis zum 23.10.2026, ob Sie an unserer Jubiläumsfeier teilnehmen.",
        "de",
    ),
    ("We look forward to receiving your nomination form by 23 October 2026.", "en"),
]


def test_an_offer_survey_contest_or_event_files_nothing() -> None:
    def check(sentence: str, lang: str) -> None:
        assert filed(sentence, W, lang) == []

    check_rows(OFFERS_SURVEYS_CONTESTS_EVENTS, check)


def test_an_offer_s_return_label_files_nothing() -> None:
    lines = (
        *HEAD,
        "Unser Angebot für Ihren neuen Stromtarif",
        "Arbeitspreis: 32,5 ct/kWh",
        "Rücksendung des Angebots bis: 23.10.2026",
        "Mit freundlichen Grüßen",
    )
    assert in_letter(*lines) == []


# --------------------------------------------------------------------------------------------------
# Holidays and opening hours
# --------------------------------------------------------------------------------------------------


HOLIDAY_OR_OPENING_HOURS_NOTICES = [
    "Abgabeschluss für Fundsachen: 23.10.",
    "Fällig am: 15.11. (nur für Kunden mit Jahreszahlung)",
]


def test_a_holiday_or_opening_hours_notice_files_nothing() -> None:
    def check(sentence: str) -> None:
        assert filed(sentence, W) == []

    check_rows(HOLIDAY_OR_OPENING_HOURS_NOTICES, check)


def test_a_bank_s_year_end_letter_files_nothing() -> None:
    lines = (
        "Sparkasse Beispielhausen · Markt 1 · 12345 Beispielhausen",
        "Frau Mara Probe",
        "Probeweg 2",
        "12345 Beispielhausen",
        "Datum: 05.10.2026",
        "Unsere Öffnungszeiten zum Jahreswechsel",
        "Sehr geehrte Frau Probe,",
        "zwischen den Jahren gelten geänderte Öffnungszeiten. Am 24.12. und 31.12. bleiben alle Filialen geschlossen.",
        "Überweisungen müssen bis 30.12. bei uns eingegangen sein, damit sie noch im alten Jahr gebucht werden.",
        "Wir wünschen Ihnen schöne Feiertage.",
        "Mit freundlichen Grüßen",
        "Ihre Sparkasse",
    )
    assert in_letter(*lines) == []


# --------------------------------------------------------------------------------------------------
# The reported shapes as positives — the families that stay file, the dropped ones file nothing
# --------------------------------------------------------------------------------------------------


FAMILY_EXAMPLES = [
    # wordings the narrowing dropped: nothing
    ("Wir erwarten Ihre Zahlung bis zum 23.10.2026.", "de", []),
    ("Ihre Stellungnahme erwarten wir bis 23.10.2026.", "de", []),
    ("Bis zum 23.10.2026 erwarten wir Ihre Rückmeldung.", "de", []),
    ("Ihre Zahlung wird bis zum 23.10.2026 erwartet.", "de", []),
    ("Bitte beachten Sie, dass Ihre Zahlung bis zum 23.10.2026 bei uns eingegangen sein muss.", "de", []),
    ("You are required to pay the balance by 23 October 2026.", "en", []),
    ("The deadline for your reply is 23 October 2026.", "en", []),
    # dates without their year: nothing
    ("Spätestens am 23.10. sollte Ihre Zahlung bei uns eingegangen sein.", "de", []),
    ("Bitte bis 23.10. unterschrieben zurücksenden.", "de", []),
    ("Laut Ihrem Antrag vom 20.09. benötigen wir Ihre Unterlagen bis zum 23.10.", "de", []),
    ("Please ensure your payment reaches us by 23 October.", "en", []),
    # the wordings that stay
    ("Bitte bis 23.10.2026 unterschrieben zurücksenden.", "de", SENDS),
    ("Please ensure your payment reaches us by 23 October 2026.", "en", PAYS),
    ("Bitte überweisen Sie den offenen Betrag auf unser Konto.\nZahlungsfrist: 23.10.2026", "de", PAYS),
]


def test_each_family_files_when_the_person_is_asked() -> None:
    def check(sentence: str, lang: str, expected: list[tuple[str, str]]) -> None:
        assert filed(sentence, W, lang) == expected

    check_rows(FAMILY_EXAMPLES, check)


# --------------------------------------------------------------------------------------------------
# No line is read once per date
# --------------------------------------------------------------------------------------------------


DATE_LABELS = ["Zahlung bis:", "Zahlungsfrist:", "Zahlbar bis:"]


def test_a_line_of_many_distinct_dates_stays_fast() -> None:
    def check(label: str) -> None:
        line = " · ".join(f"{label} {date(2026, 10, 10) + timedelta(days=i):%d.%m.%Y}" for i in range(1600))
        # CPU seconds, not the wall clock: on a busy machine the scheduler's pauses would count
        started = time.process_time()
        found = deadline_items(
            reading(W), [letter("Bitte überweisen Sie den Betrag.\n" + line, W)], today=TODAY
        )
        assert len(found) <= 3
        assert time.process_time() - started < 10

    check_rows(DATE_LABELS, check)


# --------------------------------------------------------------------------------------------------
# A window's first day is no deadline
# --------------------------------------------------------------------------------------------------


WINDOWS = [
    ("Bitte überweisen Sie den Betrag.\nZahlungsfrist: 01.11.2026 bis 15.11.2026", "de"),
    ("Bitte senden Sie uns die Unterlagen zu.\nAbgabefrist: 01.11.2026 – 15.11.2026", "de"),
    ("Please pay the balance.\nPayment deadline: 1 November 2026 to 15 November 2026", "en"),
    ("Bitte überweisen Sie den Betrag.\nZahlungsfrist: 1.11. – 15.11.", "de"),
    ("Ihre Unterlagen werden vom 01.11. bis 15.11. bei uns benötigt.", "de"),
]


def test_a_window_s_first_day_files_nothing() -> None:
    def check(sentence: str, lang: str) -> None:
        assert filed(sentence, W, lang) == []
        # nor beside the reading's to-do on its last day
        assert filed(sentence, W, lang, items=[due("2026-11-15", "Frist")]) == []

    check_rows(WINDOWS, check)
