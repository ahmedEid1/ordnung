"""A small, realistic ledger for the secretary and view tests (Sam Rivera, SPEC §1.3).

``seed_ledger(store)`` writes profile, parties, documents, contracts, items and a sent letter and
returns a label → id map. The reference day is :data:`TODAY` (Mon 28 Sep 2026). Seeded rows carry
fixed timestamps (:data:`SEED_STAMP`) so "changed since the last calendar export" is deterministic.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from ordnung.db.store import Store
from ordnung.models import (
    ComputationReceipt,
    DateSpec,
    DocumentExtraction,
    Evidence,
    ExtractedChange,
    PaymentDetails,
    Remedy,
)

TODAY = date(2026, 9, 28)
SEED_STAMP = "2026-01-01T08:00:00Z"
EXPORTED_AT = "2026-02-01T08:00:00Z"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def add_doc(store: Store, label: str, **fields: Any) -> str:
    """Insert a processed document with the given model fields (extraction via ``extraction=``)."""
    doc = store.add_document(
        sha256=_sha(label), filename=f"{label}.pdf", mime="application/pdf", file_path=f"files/{label}.pdf"
    )
    fields.setdefault("status", "processed")
    store.update_document(doc.id, **fields)
    return doc.id


def add_item(store: Store, **fields: Any) -> str:
    """Insert an item with seed timestamps (unless given)."""
    fields.setdefault("created_at", SEED_STAMP)
    fields.setdefault("updated_at", SEED_STAMP)
    fields.setdefault("grounding", "verified")
    return store.add_item(**fields).id


def _evidence(doc_id: str, quote: str, grounding: str = "verified") -> list[Evidence]:
    return [Evidence.model_validate({"doc_id": doc_id, "page": 1, "quote": quote, "grounding": grounding})]


def _extraction(kind: str, title: str, **fields: Any) -> DocumentExtraction:
    return DocumentExtraction.model_validate(
        {"kind": kind, "title": title, "summary": title, "explanation": title, **fields}
    )


def seed_ledger(store: Store) -> dict[str, str]:
    """Write the ledger; returns ids by label."""
    ids: dict[str, str] = {}
    store.save_profile(
        {"name": "Sam Rivera", "language": "en", "region": "NW", "is_student_visa": True, "onboarded": True}
    )
    store.set_meta("last_calendar_export_at", EXPORTED_AT)

    def party(label: str, name: str, kind: str, **extra: Any) -> str:
        ids[label] = store.add_party(
            name=name, kind=kind, created_at=SEED_STAMP, updated_at=SEED_STAMP, **extra
        ).id
        return ids[label]

    funk = party("funknetz", "FunkNetz Mobile", "telecom")
    fa = party("finanzamt", "Finanzamt Musterstadt", "tax_office", region="NW")
    abh = party("abh", "Ausländerbehörde Musterstadt", "immigration_office", region="NW")
    tech = party("techmarkt", "TechMarkt", "retailer")
    stadtwerke = party("stadtwerke", "Stadtwerke Musterstadt", "utility", region="NW")
    party("beitrag", "Beitragsservice Musterstadt", "public_broadcaster", ibans=["DE02440100460123456789"])
    fake = party("fake_beitrag", "Rundfunk Beitragsservice Zahlungszentrale", "public_broadcaster")
    gym = party("gym", "FitMuster Studio", "gym")
    uni = party("uni", "Hochschule Musterstadt", "university")
    employer = party("employer", "Muster Tech GmbH", "employer")

    # ---------------------------------------------------------------- documents
    ids["doc_phone"] = add_doc(
        store,
        "phone",
        kind="contract",
        area="home",
        title="FunkNetz mobile contract",
        doc_date="2024-11-15",
        party_id=funk,
        summary="Mobile contract, 24 months, €29.99 a month.",
    )
    ids["doc_tax"] = add_doc(
        store,
        "tax",
        kind="tax_assessment",
        area="tax",
        title="Income tax assessment 2025",
        doc_date="2026-09-15",
        party_id=fa,
        tax_relevant=True,
        summary="Tax assessment 2025: refund of €412.00; the laptop was not accepted.",
        remedy=Remedy(type="einspruch", addressee="Finanzamt Musterstadt"),
    )
    ids["doc_permit"] = add_doc(
        store,
        "permit",
        kind="residence_permit",
        area="residence",
        title="Residence permit (student)",
        doc_date="2025-01-10",
        party_id=abh,
    )
    ids["doc_passport"] = add_doc(
        store, "passport", kind="identity_document", area="residence", title="Passport", doc_date="2021-02-10"
    )
    ids["doc_invoice"] = add_doc(
        store,
        "invoice",
        kind="invoice",
        area="money",
        title="TechMarkt invoice USB-C dock",
        doc_date="2026-08-20",
        party_id=tech,
    )
    ids["doc_dunning"] = add_doc(
        store,
        "dunning",
        kind="dunning",
        area="money",
        title="TechMarkt payment reminder",
        doc_date="2026-09-18",
        party_id=tech,
    )
    ids["doc_scam"] = add_doc(
        store,
        "scam",
        kind="other",
        area="money",
        title="Urgent: outstanding broadcasting fee",
        doc_date="2026-09-25",
        party_id=fake,
        hidden_text=True,
        warnings=[
            "Payee IBAN is abroad although the sender claims to be a German authority — possible scam."
        ],
        payment=PaymentDetails(iban="LT121000011101001000", payee="Beitragsservice Zahlungszentrale"),
    )
    ids["doc_power"] = add_doc(
        store,
        "power",
        kind="price_increase",
        area="home",
        title="Stadtwerke price change",
        doc_date="2026-09-24",
        party_id=stadtwerke,
        extraction=_extraction(
            "price_increase",
            "Stadtwerke price change",
            change=ExtractedChange(
                type="price_increase",
                effective_date="2026-11-01",
                old_amount=48.0,
                new_amount=55.0,
                cost_interval="monthly",
            ),
        ),
    )
    ids["doc_gym_confirm"] = add_doc(
        store,
        "gym-confirm",
        kind="cancellation_confirmation",
        area="leisure",
        title="FitMuster cancellation confirmation",
        doc_date="2026-09-20",
        party_id=gym,
        extraction=_extraction(
            "cancellation_confirmation",
            "FitMuster cancellation confirmation",
            change=ExtractedChange(type="cancellation_confirmation", effective_date="2026-12-31"),
        ),
    )
    ids["doc_parking"] = add_doc(
        store,
        "parking",
        kind="fine",
        area="mobility",
        title="Parking fine",
        doc_date="2026-09-22",
        status="needs_review",
    )
    ids["doc_payslip"] = add_doc(
        store,
        "payslip",
        kind="payslip",
        area="work",
        title="Payslip December 2025",
        doc_date="2025-12-28",
        party_id=employer,
        tax_relevant=True,
    )
    ids["doc_private"] = add_doc(
        store,
        "private",
        kind="personal",
        area="health",
        title="Therapy invoice",
        doc_date="2026-09-10",
        ai_private=True,
        summary="Private note.",
    )

    # ---------------------------------------------------------------- contracts
    def contract(label: str, **fields: Any) -> str:
        fields.setdefault("created_at", SEED_STAMP)
        fields.setdefault("updated_at", SEED_STAMP)
        ids[label] = store.add_contract(**fields).id
        return ids[label]

    contract(
        "phone",
        name="FunkNetz mobile",
        category="mobile",
        party_id=funk,
        concluded_date="2024-11-15",
        start_date="2024-11-15",
        initial_term_months=24,
        notice_value=1,
        notice_unit="months",
        notice_basis="end_of_term",
        cost_amount=29.99,
        cost_interval="monthly",
        source_doc_id=ids["doc_phone"],
        customer_number="FN-123456",
    )
    contract(
        "power",
        name="Stadtwerke electricity",
        category="energy",
        party_id=stadtwerke,
        concluded_date="2023-01-01",
        start_date="2023-01-01",
        initial_term_months=12,
        notice_value=1,
        notice_unit="months",
        cost_amount=48.0,
        cost_interval="monthly",
    )
    contract(
        "gym_contract",
        name="FitMuster membership",
        category="gym",
        party_id=gym,
        concluded_date="2025-01-01",
        start_date="2025-01-01",
        initial_term_months=24,
        notice_value=1,
        notice_unit="months",
        notice_basis="end_of_term",
        cost_amount=24.90,
        cost_interval="monthly",
    )
    contract(
        "ticket",
        name="Deutschlandticket",
        category="transport",
        concluded_date="2025-05-01",
        start_date="2025-05-01",
        notice_value=1,
        notice_unit="months",
        notice_basis="end_of_month",
        cost_amount=63.0,
        cost_interval="monthly",
    )
    contract(
        "job",
        name="Working student contract",
        category="employment",
        party_id=employer,
        start_date="2025-10-01",
        end_date="2027-03-31",
        area="work",
    )

    # ---------------------------------------------------------------- items
    ids["tax_objection"] = add_item(
        store,
        kind="deadline",
        title="Objection deadline (Einspruch)",
        doc_id=ids["doc_tax"],
        party_id=fa,
        area="tax",
        due_date="2026-10-21",
        send_by="2026-10-15",
        priority="high",
        due_date_source="computed",
        date_spec=DateSpec(
            type="relative",
            anchor="deemed_delivery",
            amount=1,
            unit="months",
            delivery_rule="de_admin_post",
            nature="objection",
        ),
        computation=ComputationReceipt(
            due_date="2026-10-21",
            send_by="2026-10-15",
            summary="Letter dated 15 Sep counts as delivered on Sat 19 Sep → moved to Mon 21 Sep; one month later is Wed 21 Oct.",
        ),
        evidence=_evidence(ids["doc_tax"], "innerhalb eines Monats nach Bekanntgabe"),
    )
    ids["tax_refund"] = add_item(
        store,
        kind="payment",
        title="Tax refund",
        doc_id=ids["doc_tax"],
        party_id=fa,
        area="tax",
        due_date="2026-10-05",
        amount=412.0,
        currency="EUR",
        direction="in",
    )
    ids["semester_fee"] = add_item(
        store,
        kind="payment",
        title="Semester fee",
        party_id=uni,
        area="study",
        due_date="2026-10-02",
        amount=320.5,
        currency="EUR",
        direction="out",
        origin="manual",
        grounding="user",
    )
    ids["library_task"] = add_item(
        store,
        kind="task",
        title="Return library books",
        party_id=uni,
        area="study",
        due_date="2026-09-20",
        origin="manual",
        grounding="user",
    )
    ids["invoice_payment"] = add_item(
        store,
        kind="payment",
        title="Pay TechMarkt invoice",
        doc_id=ids["doc_invoice"],
        party_id=tech,
        area="money",
        due_date="2026-09-03",
        amount=89.99,
        currency="EUR",
        direction="out",
        status="done",
    )
    ids["dunning_payment"] = add_item(
        store,
        kind="payment",
        title="Pay TechMarkt reminder",
        doc_id=ids["doc_dunning"],
        party_id=tech,
        area="money",
        due_date="2026-09-30",
        amount=94.99,
        currency="EUR",
        direction="out",
        priority="high",
    )
    ids["scam_payment"] = add_item(
        store,
        kind="payment",
        title="Pay broadcasting fee",
        doc_id=ids["doc_scam"],
        area="money",
        due_date="2026-10-01",
        amount=210.0,
        currency="EUR",
        direction="out",
        grounding="unverified",
    )
    ids["parking_payment"] = add_item(
        store,
        kind="payment",
        title="Pay parking fine",
        doc_id=ids["doc_parking"],
        area="mobility",
        due_date="2026-09-29",
        amount=25.0,
        currency="EUR",
        direction="out",
        grounding="unverified",
        evidence=_evidence(ids["doc_parking"], "zahlbar binnen einer Woche", "unverified"),
    )
    ids["permit_expiry"] = add_item(
        store,
        kind="expiry",
        title="Residence permit expires",
        doc_id=ids["doc_permit"],
        party_id=abh,
        area="residence",
        due_date="2026-12-15",
    )
    ids["passport_expiry"] = add_item(
        store,
        kind="expiry",
        title="Passport expires",
        doc_id=ids["doc_passport"],
        area="residence",
        due_date="2027-02-10",
    )
    ids["abh_appointment"] = add_item(
        store,
        kind="appointment",
        title="Appointment at the Ausländerbehörde",
        party_id=abh,
        area="residence",
        due_date="2026-10-14",
        due_time="10:00",
        origin="manual",
        grounding="user",
    )
    ids["followup"] = add_item(
        store,
        kind="reminder",
        title="Enrolment question to Hochschule",
        party_id=uni,
        area="study",
        due_date="2026-09-26",
        origin="draft",
        grounding="user",
    )
    ids["private_item"] = add_item(
        store,
        kind="payment",
        title="Therapy invoice",
        doc_id=ids["doc_private"],
        area="health",
        due_date="2026-10-20",
        amount=80.0,
        currency="EUR",
        direction="out",
        origin="manual",
        grounding="user",
    )
    ids["draft_uni"] = store.add_draft(
        kind="general_reply",
        party_id=uni,
        subject="Question about my enrolment",
        status="sent",
        sent_at="2026-09-05T10:00:00Z",
        sent_channel="email",
    ).id
    return ids


def add_emailed_bill(
    store: Store, *, due: str, amount: float = 49.99, party_id: str | None = None, label: str = "phone-bill"
) -> dict[str, str]:
    """An e-mail that repeats the payment of the bill attached to it (the one inbox's most common case):
    the e-mail's payment to-do is set aside for the bill's. Returns the ids by label (``email``,
    ``bill``, ``email_payment``, ``bill_payment``)."""
    email = store.add_document(
        sha256=_sha(f"{label}-email"),
        filename=f"{label}.eml",
        mime="message/rfc822",
        file_path=f"files/{label}.eml",
        status="processed",
    )
    store.update_document(email.id, kind="invoice", title="Your phone bill is here", party_id=party_id)
    bill = store.add_document(
        sha256=_sha(f"{label}-pdf"),
        filename=f"{label}.pdf",
        mime="application/pdf",
        file_path=f"files/{label}.pdf",
        source=f"email:{email.id}",
        status="processed",
    )
    store.update_document(bill.id, kind="invoice", title="Phone bill September", party_id=party_id)
    common = {
        "kind": "payment",
        "title": "Pay the phone bill",
        "party_id": party_id,
        "area": "money",
        "due_date": due,
        "amount": amount,
        "currency": "EUR",
        "direction": "out",
    }
    return {
        "email": email.id,
        "bill": bill.id,
        "email_payment": add_item(store, doc_id=email.id, **common),
        "bill_payment": add_item(store, doc_id=bill.id, **common),
    }
