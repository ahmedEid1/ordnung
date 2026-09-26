"""Scam signs after "an invalid IBAN alone is a misprint" (round 2, R2-SCAM-1).

``_scam_reasons`` drops the ``invalid_iban`` finding and only lists the checksum "next to other signs".
``scam.payment_mismatch`` used to return ``invalid_iban`` *first* and never ran the look-alike /
changed-IBAN / changed-payee checks for such an IBAN, so those other signs were never found.
"""

from __future__ import annotations

from helpers_secretary import TODAY, seed_ledger
from ordnung.db.store import Store
from ordnung.models import PaymentDetails
from ordnung.secretary.scam import payment_mismatch
from ordnung.secretary.triggers import Ledger, run_triggers

VALID_ABROAD = "LT121000011101001000"  # valid checksum, not the look-alike's known DE02… account
INVALID_ABROAD = "LT717300010000000000"  # fails its checksum, equally unlike DE02…
MISREAD_KNOWN = "DE02440100460123456788"  # the known DE02 4401 0046 0123 4567 89 with its last digit misread


def _scam_letter(store: Store, ids: dict[str, str], iban: str) -> None:
    """The seeded letter from "Rundfunk Beitragsservice Zahlungszentrale" (a look-alike of the
    Beitragsservice that used DE02 4401 0046 0123 4567 89) with no hidden text and no model warning."""
    store.update_document(
        ids["doc_scam"],
        hidden_text=False,
        warnings=[],
        payment={"iban": iban, "payee": "Beitragsservice Zahlungszentrale"},
    )


def test_control_a_valid_foreign_iban_from_a_look_alike_is_a_scam_sign(store: Store) -> None:
    ids = seed_ledger(store)
    _scam_letter(store, ids, VALID_ABROAD)
    assert [idea.kind for idea in run_triggers(store, TODAY)["scam_warning"]] == ["scam"]


def test_an_invalid_iban_does_not_hide_a_look_alike_sender(store: Store) -> None:
    """An invalid IBAN masked the look-alike-sender check: payment_mismatch returned 'invalid_iban'
    before comparing with the similar organisation's known account, _scam_reasons then dropped that
    finding, so the letter got a calm 'looks misprinted' Info Idea and its payment stayed 'to pay'
    instead of a scam warning."""
    ids = seed_ledger(store)
    _scam_letter(store, ids, INVALID_ABROAD)
    document = store.get_document(ids["doc_scam"])
    assert document is not None

    reasons = Ledger(store, TODAY).scam_reasons(document)
    assert any("similar name" in reason for reason in reasons), reasons
    results = run_triggers(store, TODAY)
    assert [idea.kind for idea in results["scam_warning"]] == ["scam"]
    assert results["iban_misprint"] == []


def test_a_misread_known_iban_stays_a_misprint(store: Store) -> None:
    """The other checks now run for an invalid IBAN too — but one digit off an account the sender (or
    the organisation it resembles) is known to use is that account misread, not a new account."""
    ids = seed_ledger(store)
    _scam_letter(store, ids, MISREAD_KNOWN)
    results = run_triggers(store, TODAY)
    assert results["scam_warning"] == []
    assert [idea.kind for idea in results["iban_misprint"]] == ["info"]

    party = store.get_party(ids["beitrag"])
    assert party is not None
    finding = payment_mismatch(store, party, PaymentDetails(iban=MISREAD_KNOWN))
    assert finding is not None and finding.kind == "invalid_iban"  # not "iban_changed"
