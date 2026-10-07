"""The first review of the dropped-date check's looser path (ADR 0015, 2026-10-07): each confirmed finding's repro, as a
regression test, updated for the path as its re-review narrowed it.

The looser path files its low "Please check" to-do only for a request that asks the person in its own words at its
sentence's start ("Senden Sie uns …", "Bitte gleichen Sie … aus", "Bitte lassen Sie uns … zukommen", "Wir bitten Sie
um Zahlung …", "Bitte bis … überweisen", "Kindly pay …", "Please ensure …"), never beside a third party, the sender's
own act, a condition, something done, an offer, survey, contest, tender or event, a holiday or opening hours; a label
line or labelled sentence only on a page that asks the person for its kind. A date without its year files nothing
(re-review: ``test_reading_gaps_looser_rereview.py``). Where a test below once showed a wording the re-review
dropped, it now shows that wording filing nothing. The strict path is the base's (0ff51e3) for every date with its
year: its results here were read from the base code and are pinned as they were. Invented letters only.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pytest

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
# Finding 0: a day-month long before the letter's date is an old line, never next year's date
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Offene Posten: Rechnung 4711 vom 02.03., fällig am 16.03., 120,00 €",
        "Rechnung vom 01.03., zahlbar bis 31.03.",
        "Die Unterlagen hätten uns bis zum 31.03. vorliegen müssen.",
        "Offene Posten: Rechnung 4711 vom 02.03.2026, fällig am 16.03.2026, 120,00 €",
        # an issue date after the letter's: its sentence's dates are another year's
        "Ihre Rechnung vom 10.10. ist bis zum 24.10. zu bezahlen.",
    ],
)
def test_an_old_line_without_its_year_is_never_next_year_s_date(sentence: str) -> None:
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
    """The re-review dropped dates without their year: a next-year roll-over is never read again."""
    assert (
        filed("Bitte überweisen Sie den Betrag bis zum 15.01.", date(2026, 12, 10), today=date(2026, 12, 11))
        == []
    )
    assert filed(
        "Bitte überweisen Sie den Betrag bis zum 15.01.2027.", date(2026, 12, 10), today=date(2026, 12, 11)
    ) == [("2027-01-15", "payment")]


# --------------------------------------------------------------------------------------------------
# Findings 1, 20, 21: the strict path files as on base 0ff51e3 (results read from the base code)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lang", "expected"),
    [
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
        # finding 21: a condition after "und" / "oder" silences the strict path, as before
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
    ],
)  # fmt: skip
def test_the_strict_path_files_as_on_base(sentence: str, lang: str, expected: list[tuple[str, str]]) -> None:
    assert filed(sentence, W, lang) == expected


def test_a_looser_condition_after_und_or_oder_is_still_a_condition() -> None:
    assert (
        filed(
            "Senden Sie uns die Unterlagen bis zum 23.10.2026 und sollten Sie Fragen haben, rufen Sie an.", W
        )
        == []
    )
    assert filed("Senden Sie uns die Unterlagen bis zum 23.10.2026.", W) == SENDS


# --------------------------------------------------------------------------------------------------
# Findings 2 and 17: the kind from the verb, else from the head noun (whole words, a compound by its last word)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lang", "expected"),
    [
        ("Bitte senden Sie uns Ihren Steuerbescheid bis zum 20.11.2026.", "de", "declaration"),
        (
            "Bitte lassen Sie uns den Nachweis über Ihre Zahlung bis zum 20.11.2026 zukommen.",
            "de",
            "declaration",
        ),
        ("Bitte lassen Sie uns Ihre Nebenkostenabrechnung bis zum 20.11.2026 zukommen.", "de", "declaration"),
        ("Bitte gleichen Sie die Gebühr für Ihren Antrag bis zum 20.11.2026 aus.", "de", "payment"),
        ("Bitte lassen Sie uns Ihre Mietbescheinigung bis zum 20.11.2026 zukommen.", "de", "declaration"),
    ],
)
def test_the_kind_is_the_head_noun_s(sentence: str, lang: str, expected: str) -> None:
    assert filed(sentence, W, lang) == [("2026-11-20", expected)]


@pytest.mark.parametrize(
    ("sentence", "lang"),
    [
        # the first review's head-noun repros, in wordings the re-review dropped: nothing
        ("Wir benötigen Ihren Steuerbescheid bis zum 20.11.2026.", "de"),
        ("Den Nachweis über Ihre Zahlung des Beitrags benötigen wir bis zum 20.11.2026.", "de"),
        ("We need your proof of payment by 20 November 2026.", "en"),
        ("We need your evidence of rent payments by 20 November 2026.", "en"),
        ("Ihre Nebenkostenabrechnung muss uns bis zum 20.11.2026 vorliegen.", "de"),
        ("Die Gebühr für Ihren Antrag muss bis zum 20.11.2026 bei uns eingegangen sein.", "de"),
    ],
)
def test_the_dropped_wordings_file_nothing(sentence: str, lang: str) -> None:
    assert filed(sentence, W, lang) == []


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


@pytest.mark.parametrize(
    "sentence",
    [
        # finding 17: a real request, but beside a third party — the looser path stays silent
        "Bitte lassen Sie uns die Bescheinigung Ihres Vermieters bis zum 23.10.2026 zukommen.",
        "Wir benötigen die Mietbescheinigung Ihres Vermieters bis zum 23.10.2026.",
        # a label alone, on a page that asks for nothing
        "Abgabe der Nebenkostenabrechnung bis: 31.12.2026",
        # finding 2's sentences as written name no one: not addressed
        "Den Nachweis über die Zahlung des Beitrags benötigen wir bis zum 20.11.2026.",
        "Die Nebenkostenabrechnung muss uns bis zum 20.11.2026 vorliegen.",
        "Die Gebühr für den Antrag muss bis zum 20.11.2026 bei uns eingegangen sein.",
    ],
)
def test_a_third_party_s_paper_or_an_unaddressed_sentence_files_nothing(sentence: str) -> None:
    assert filed(sentence, W) == []


def test_a_label_on_a_page_that_asks_for_its_kind_files() -> None:
    assert filed(
        "Bitte senden Sie uns die Unterlagen zu.\nAbgabe der Nebenkostenabrechnung bis: 31.12.2026", W
    ) == [("2026-12-31", "declaration")]


# --------------------------------------------------------------------------------------------------
# Finding 3: payment participles and nouns (a wording the re-review dropped: nothing now)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lang", "expected"),
    [
        # "… muss bis … bezahlt werden", "must be received by": wordings the re-review dropped
        ("Ihre Rechnung muss bis zum 20.11.2026 bezahlt werden.", "de", []),
        ("Ihre Kaution muss bis zum 20.11.2026 überwiesen werden.", "de", []),
        ("Ihre Rechnung muss bis zum 20.11. beglichen sein.", "de", []),
        ("Ihre Prämie muss bis zum 20.11.2026 bei uns eingegangen sein.", "de", []),
        ("Your deposit must be received by 20 November 2026.", "en", []),
        ("Ihre Unterlagen müssen bis zum 20.11.2026 bei uns eingereicht werden.", "de", []),
        # as written, they name no one: not addressed
        ("Die Rechnung muss bis zum 20.11.2026 bezahlt werden.", "de", []),
        ("Die Kaution muss bis zum 20.11.2026 überwiesen werden.", "de", []),
        ("Der Betrag muss bis zum 20.11.2026 gezahlt werden.", "de", []),
    ],
)  # fmt: skip
def test_a_payment_s_participle_and_nouns_tell_the_kind(
    sentence: str, lang: str, expected: list[tuple[str, str]]
) -> None:
    assert filed(sentence, W, lang) == expected


# --------------------------------------------------------------------------------------------------
# Finding 4: a deadline's own sentence and a paid letter (the strict path's gate, read once for both paths)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lang"),
    [
        # the re-review dropped these wordings (and with them the looser path's own reading of a paid letter)
        ("Bis spätestens 20.11.2026 muss Ihre Zahlung bei uns eingegangen sein.", "de"),
        ("Bis zum 20.11.2026 muss Ihr Betrag bei uns eingegangen sein.", "de"),
        ("Your balance must be paid in full by 20 November 2026.", "en"),
        ("Ihr Betrag muss bis spätestens 20.11.2026 bei uns eingegangen sein.", "de"),
    ],
)
def test_a_deadline_s_own_eingegangen_or_paid_in_full_files_nothing_now(sentence: str, lang: str) -> None:
    assert filed(sentence, W, lang) == []


def test_a_letter_that_says_it_is_paid_still_gates_a_looser_payment() -> None:
    sentence = (
        "Der Rechnungsbetrag wurde bereits beglichen.\nBitte gleichen Sie den Betrag bis zum 20.11.2026 aus."
    )
    assert filed(sentence, W) == []
    assert filed("Bitte gleichen Sie den Betrag bis zum 20.11.2026 aus.", W) == [("2026-11-20", "payment")]


# --------------------------------------------------------------------------------------------------
# Findings 5 and 12: the year a sentence names (dates without their year: nothing since the re-review)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "written", "lang"),
    [
        # the re-review dropped dates without their year: none of these files, whatever year the sentence names
        ("Bitte reichen Sie die Unterlagen bis zum 31.03. des Folgejahres ein.", date(2026, 1, 10), "de"),
        ("Bitte reichen Sie die Unterlagen bis zum 31. März des nächsten Jahres ein.", date(2026, 1, 10), "de"),
        ("Please submit your return by 31 March next year.", date(2026, 1, 10), "en"),
        ("Ihre Steuererklärung 2025 ist bis zum 31.07. des Folgejahres einzureichen.", date(2026, 1, 10), "de"),
        ("Ihre Steuererklärung 2026 ist bis zum 31.12. des Jahres 2027 einzureichen.", W, "de"),
        ("Die Unterlagen müssen bis zum 31.12. des Folgejahres bei uns vorliegen.", W, "de"),
        ("Ihre Zahlung wird bis zum 31.12. des kommenden Jahres erwartet.", W, "de"),
        ("Der Beitrag für das Jahr 2027 wird zum 15.11. fällig.", W, "de"),
        ("Zahlungsplan 2027: erste Rate fällig am 15.11.", W, "de"),
        ("Die Jahresabrechnung 2027 ist bis zum 30.11. zu begleichen.", W, "de"),
        ("Für das Jahr 2028 ist der Beitrag bis zum 15.01. zu zahlen.", W, "de"),
        # two years named: ambiguous
        ("Die Beiträge 2026 und 2027 sind bis zum 15.11. zu zahlen.", W, "de"),
        # a rule of every year names no deadline of this letter's
        ("Ab 2027 ist der Jahresbeitrag jeweils bis zum 31.12. zu zahlen.", W, "de"),
        ("Laut Satzung ist der Beitrag jeweils zum 01.12. fällig.", W, "de"),
    ],
)  # fmt: skip
def test_a_date_without_its_year_files_nothing_whatever_year_its_sentence_names(
    sentence: str, written: date, lang: str
) -> None:
    today = written + timedelta(days=2)
    assert filed(sentence, written, lang, today=today) == []


# --------------------------------------------------------------------------------------------------
# Finding 6: a second date of one obligation, without its year or in looser words, is no second to-do
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
# Findings 7, 9, 19: what the sender waits for, the sender's own act, a third party mid-sentence
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lang"),
    [
        ("Wir erwarten die Entscheidung über Ihren Antrag bis zum 23.10.2026.", "de"),
        ("Wir erwarten die Antwort der Versicherung bis zum 23.10.2026.", "de"),
        ("Wir erwarten die Zahlung der Versicherung bis zum 23.10.2026.", "de"),
        (
            "Wir benötigen für die Prüfung Ihrer Unterlagen etwa zwei Wochen und melden uns bis zum 23.10.2026.",
            "de",
        ),
        ("Bis zum 23.10.2026 erwarten wir die Rückmeldung der Versicherung.", "de"),
        ("Die Entscheidung über Ihren Antrag wird bis zum 30.10.2026 erwartet.", "de"),
        ("Die Antwort der Versicherung wird bis zum 23.10.2026 erwartet.", "de"),
        (
            "Unsere Stellungnahme an das Gericht muss bis zum 23.10.2026 erfolgen; wir halten Sie auf dem Laufenden.",
            "de",
        ),
        ("Unser Bericht an die Behörde muss bis zum 23.10.2026 vorliegen.", "de"),
        ("Die Unterlagen müssen von uns bis zum 23.10.2026 beim Gericht eingereicht werden.", "de"),
        ("Die Zahlung an den Lieferanten muss bis zum 23.10.2026 erfolgen; das erledigen wir.", "de"),
        ("Der Bericht des Gutachters muss bis zum 23.10.2026 vorliegen.", "de"),
        ("Die Zahlung der Miete durch das Jobcenter muss bis zum 23.10.2026 erfolgen.", "de"),
        ("The form must be submitted by your employer by 23 October 2026.", "en"),
        ("The balance must be paid by your insurer by 23 October 2026.", "en"),
        ("Employers are required to submit the forms by 23 October 2026.", "en"),
        ("We are required to send you the annual statement of your premium by 23 October 2026.", "en"),
        ("Für die Bearbeitung Ihres Antrags benötigen wir voraussichtlich bis zum 23.10.2026.", "de"),
        ("Eine Entscheidung über Ihren Antrag wird bis zum 23.10.2026 erwartet.", "de"),
        ("Wir erwarten den Abschluss der Prüfung Ihrer Unterlagen bis zum 23.10.2026.", "de"),
        ("We expect to make a decision on your application by 23 October 2026.", "en"),
        ("Your application is expected to be processed by 23 October 2026.", "en"),
        ("We expect to issue your certificate by 23 October 2026.", "en"),
        ("A response from your insurer is expected by 23 October 2026.", "en"),
        ("Die Rückmeldung Ihrer Krankenkasse wird bis zum 23.10.2026 erwartet.", "de"),
        ("Das Gutachten zu Ihrem Antrag muss bis zum 23.10.2026 vorliegen.", "de"),
        ("We expect to complete the repair of your application by 23 October 2026.", "en"),
        ("Die Rückmeldung zu Ihrem Antrag erwarten wir bis zum 23.10.2026.", "de"),
        ("We expect your certificate to be issued by 23 October 2026.", "en"),
        ("Your new contract documents are expected by 23 October 2026.", "en"),
        ("Your first benefit payment is expected by 23 October 2026.", "en"),
    ],
)
def test_what_the_sender_or_another_does_files_nothing(sentence: str, lang: str) -> None:
    assert filed(sentence, W, lang) == []


def test_a_request_for_the_person_s_papers_in_a_dropped_wording_is_missed() -> None:
    """Real requests, but in the "benötigen wir" / "we expect" wordings the re-review dropped (they filed what the
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
# Finding 8: money or papers that come to the person
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Das Geld sollte bis zum 23.10.2026 bei Ihnen eingegangen sein.",
        "Der Betrag sollte bis zum 23.10.2026 bei Ihnen eingehen.",
        "Ihre Rückzahlung muss bis zum 23.10.2026 bei Ihnen eingegangen sein.",
        "Die Unterlagen sollten Ihnen bis zum 23.10.2026 vorliegen.",
        "Die Beitragsbescheinigung sollte Ihnen bis zum 23.10.2026 vorliegen.",
        "Die Abrechnung des Vermieters muss bis zum 31.12.2026 bei Ihnen eingegangen sein.",
    ],
)
def test_money_or_papers_coming_to_the_person_file_nothing(sentence: str) -> None:
    assert filed(sentence, W) == []


# --------------------------------------------------------------------------------------------------
# Finding 10: another party's Frist, or the sender's
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Wir haben der Gegenseite zur Zahlung des Schadensersatzes eine Frist bis zum 23.10.2026 gesetzt.",
        "Wir haben dem Vermieter zur Rückzahlung der Kaution eine Frist bis zum 23.10.2026 gesetzt.",
        "Wir haben die Versicherung zur Zahlung aufgefordert und ihr eine Frist bis zum 23.10.2026 gesetzt.",
        "Die Frist für die Stellungnahme der Gegenseite endet am 23.10.2026.",
        "Die Frist zur Stellungnahme für den Beklagten läuft am 23.10.2026 ab.",
        "Die Frist für die Prüfung Ihres Antrags endet am 23.10.2026.",
        "Die Zahlungsfrist für Ihren Mieter endet am 23.10.2026.",
    ],
)
def test_another_s_frist_files_nothing(sentence: str) -> None:
    assert filed(sentence, W) == []


def test_a_table_of_the_other_side_s_fristen_files_nothing() -> None:
    lines = (
        *HEAD,
        "Fristen der Gegenseite im Überblick:",
        "Zahlungsfrist: 23.10.2026",
        "Mit freundlichen Grüßen",
    )
    assert in_letter(*lines) == []


def test_a_frist_set_for_the_person_is_missed() -> None:
    """The re-review dropped the Frist wordings (another party's Frist filed through "Ihnen" or "Ihr…"): missed."""
    assert (
        filed("Zur Zahlung des offenen Betrags setzen wir Ihnen eine letzte Frist bis zum 23.10.2026.", W)
        == []
    )
    assert filed("Ihre Zahlungsfrist endet am 23.10.2026.", W) == []


# --------------------------------------------------------------------------------------------------
# Finding 11: conditions
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lang"),
    [
        ("Bei Bedarf senden Sie uns weitere Unterlagen bis zum 23.10.2026.", "de"),
        ("Gegebenenfalls benötigen wir weitere Unterlagen von Ihnen bis zum 23.10.2026.", "de"),
        ("Ggf. erforderliche Nachweise müssen Sie uns bis zum 23.10.2026 vorlegen.", "de"),
        ("Im Falle einer Nachforderung muss Ihre Zahlung bis zum 23.10.2026 bei uns eingegangen sein.", "de"),
        ("Ändert sich Ihr Einkommen, müssen Ihre Nachweise bis zum 23.10.2026 bei uns vorliegen.", "de"),
        ("Für Selbstständige müssen Ihre Einkommensnachweise bis zum 23.10.2026 bei uns vorliegen.", "de"),
        ("Where applicable, your documents must be submitted by 23 October 2026.", "en"),
        ("In the event of a change of address, your new details must be received by 23 October 2026.", "en"),
        ("In case of a claim, your documents must be received by 23 October 2026.", "en"),
        ("Sollten Sie Fragen haben, senden Sie uns Ihre Unterlagen bis zum 23.10.2026.", "de"),
    ],
)
def test_a_condition_files_nothing(sentence: str, lang: str) -> None:
    assert filed(sentence, W, lang) == []


# --------------------------------------------------------------------------------------------------
# Finding 13: done, paid, stated
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lang"),
    [
        (
            "Ihre Zahlung muss bis zum 23.10.2026 erfolgen – das hat sich durch Ihre Überweisung erledigt.",
            "de",
        ),
        (
            "Ihre angeforderten Unterlagen müssen uns bis zum 23.10.2026 vorliegen; sie liegen uns inzwischen vor.",
            "de",
        ),
        (
            "Statement period 1 September 2026 to 30 September 2026. Your payments must be received by 23 October "
            "2026 to appear on your next statement.",
            "en",
        ),
        ("Your account is in credit. We expect the balance to reach your bank by 23 October 2026.", "en"),
        (
            "You do not need to do anything. The forms must be received by us from your bank by 23 October 2026.",
            "en",
        ),
        (
            "Thank you, your documents are complete. A decision on your application is expected by 23 October 2026.",
            "en",
        ),
        ("There is nothing you need to send us; we expect the court's documents by 23 October 2026.", "en"),
    ],
)
def test_something_done_or_stated_files_nothing(sentence: str, lang: str) -> None:
    assert filed(sentence, W, lang) == []


@pytest.mark.parametrize(
    "lines",
    [
        ("Ihr Zahlungsplan", "Rate 1: 100,00 € – Zahlung bis: 23.10.2026 – erledigt"),
        ("hier Ihre Übersicht der bezahlten Rechnungen:", "Rechnung | Betrag | Zahlung bis | Bezahlt am",
         "R-17 | 50,00 € | Zahlung bis: 23.10.2026 | 01.10.2026"),
        ("Ihr Ratenplan (alle Raten werden per Dauerauftrag beglichen):", "Rate 1 · Zahlung bis: 23.10.2026 · 100,00 €",
         "Rate 2 · Zahlung bis: 23.11.2026 · 100,00 €"),
        ("Übersicht Ihrer Beiträge", "Zahlung bis: 23.10.2026 · Betrag: 45,00 € · Status: offen"),
    ],
)  # fmt: skip
def test_a_paid_or_stated_table_files_nothing(lines: tuple[str, ...]) -> None:
    assert in_letter(*HEAD, *lines, "Mit freundlichen Grüßen") == []


# --------------------------------------------------------------------------------------------------
# Finding 14: offers, surveys, contests, tenders, events
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lang"),
    [
        (
            "Senden Sie uns den ausgefüllten Fragebogen bis zum 23.10.2026 und erhalten Sie einen 10-€-Gutschein.",
            "de",
        ),
        ("Senden Sie uns Ihren Beitrag zum Fotowettbewerb bis zum 23.10.2026.", "de"),
        ("Einsendeschluss für Beiträge zur Mieterzeitung: 23.10.2026", "de"),
        ("Ihre Anträge zur Tagesordnung erbitten wir bis zum 23.10.2026.", "de"),
        ("Abgabetermin für die Angebote der Handwerker: 23.10.2026", "de"),
        ("Unsere Kundenumfrage: Wir erbitten Ihre Antwort bis zum 23.10.2026.", "de"),
        ("Für die Planung des Sommerfests erbitten wir Ihre Rückmeldung bis zum 23.10.2026.", "de"),
        (
            "Wir bitten Sie um Rückmeldung bis zum 23.10.2026, ob Sie an unserer Jubiläumsfeier teilnehmen.",
            "de",
        ),
        ("Early-bird offer for the 2027 course – payment deadline: 23 October 2026", "en"),
        ("We would appreciate your response to our short survey by 23 October 2026.", "en"),
        ("The deadline for the scholarship application is 23 October 2026.", "en"),
        (
            "Please make sure your entry form reaches us by 23 October 2026 to be in with a chance of winning.",
            "en",
        ),
        ("We look forward to receiving your nomination form by 23 October 2026.", "en"),
    ],
)
def test_an_offer_survey_contest_or_event_files_nothing(sentence: str, lang: str) -> None:
    assert filed(sentence, W, lang) == []


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
# Finding 15: holidays and opening hours
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Wichtiger Hinweis zu den Feiertagen: Überweisungen müssen bis 30.12. bei der Bank eingegangen sein, damit sie "
        "noch im alten Jahr gebucht werden.",
        "Öffnungszeiten der Kasse: Zahlbar bis 23.12. in bar, danach nur per Überweisung.",
        "Letzter Abgabetag für Weihnachtspäckchen: 19.12.",
        "Abgabeschluss für Fundsachen: 23.10.",
        "Fällig am: 15.11. (nur für Kunden mit Jahreszahlung)",
    ],
)
def test_a_holiday_or_opening_hours_notice_files_nothing(sentence: str) -> None:
    assert filed(sentence, W) == []


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
# Finding 16: the review's shapes as positives — the families that stay file, the dropped ones file nothing
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lang", "expected"),
    [
        # wordings the re-review dropped: nothing
        ("Wir erwarten Ihre Zahlung bis zum 23.10.2026.", "de", []),
        ("Ihre Stellungnahme erwarten wir bis 23.10.2026.", "de", []),
        ("Bis zum 23.10.2026 erwarten wir Ihre Rückmeldung.", "de", []),
        ("Ihre Zahlung wird bis zum 23.10.2026 erwartet.", "de", []),
        ("Bitte beachten Sie, dass Ihre Zahlung bis zum 23.10.2026 bei uns eingegangen sein muss.", "de", []),
        ("Your payment must be received by 23 October 2026.", "en", []),
        ("You are required to pay the balance by 23 October 2026.", "en", []),
        ("The deadline for your reply is 23 October 2026.", "en", []),
        # dates without their year: nothing
        ("Spätestens am 23.10. sollte Ihre Zahlung bei uns eingegangen sein.", "de", []),
        ("Bitte bis 23.10. unterschrieben zurücksenden.", "de", []),
        ("Laut Ihrem Antrag vom 20.09. benötigen wir Ihre Unterlagen bis zum 23.10.", "de", []),
        ("Please ensure your payment reaches us by 23 October.", "en", []),
        # the wordings that stay
        ("Bitte gleichen Sie den offenen Betrag bis zum 23.10.2026 aus.", "de", PAYS),
        ("Senden Sie uns die Unterlagen bis zum 23.10.2026.", "de", SENDS),
        ("Bitte bis zum 23.10.2026 überweisen.", "de", PAYS),
        ("Bitte bis 23.10.2026 unterschrieben zurücksenden.", "de", SENDS),
        ("Kindly pay the outstanding amount by 23 October 2026.", "en", PAYS),
        ("Please ensure your payment reaches us by 23 October 2026.", "en", PAYS),
        ("Bitte überweisen Sie den offenen Betrag auf unser Konto.\nZahlungsfrist: 23.10.2026", "de", PAYS),
        ("Please return the signed form to us.\nReply by: 23 October 2026", "en", SENDS),
    ],
)
def test_each_family_files_when_the_person_is_asked(
    sentence: str, lang: str, expected: list[tuple[str, str]]
) -> None:
    assert filed(sentence, W, lang) == expected


# --------------------------------------------------------------------------------------------------
# Finding 18: no line is read once per date
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["Zahlung bis:", "Zahlungsfrist:", "Zahlbar bis:"])
def test_a_line_of_many_distinct_dates_stays_fast(label: str) -> None:
    line = " · ".join(f"{label} {date(2026, 10, 10) + timedelta(days=i):%d.%m.%Y}" for i in range(1600))
    started = time.monotonic()
    found = deadline_items(reading(W), [letter("Bitte überweisen Sie den Betrag.\n" + line, W)], today=TODAY)
    assert len(found) <= 3
    assert time.monotonic() - started < 10


# --------------------------------------------------------------------------------------------------
# Finding 22: a window's first day is no deadline
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lang"),
    [
        ("Bitte überweisen Sie den Betrag.\nZahlungsfrist: 01.11.2026 bis 15.11.2026", "de"),
        ("Bitte senden Sie uns die Unterlagen zu.\nAbgabefrist: 01.11.2026 – 15.11.2026", "de"),
        ("Please pay the balance.\nPayment deadline: 1 November 2026 to 15 November 2026", "en"),
        ("Bitte überweisen Sie den Betrag.\nZahlungsfrist: 1.11. – 15.11.", "de"),
        ("Ihre Unterlagen werden vom 01.11. bis 15.11. bei uns benötigt.", "de"),
    ],
)
def test_a_window_s_first_day_files_nothing(sentence: str, lang: str) -> None:
    assert filed(sentence, W, lang) == []
    # nor beside the reading's to-do on its last day
    assert filed(sentence, W, lang, items=[due("2026-11-15", "Frist")]) == []
