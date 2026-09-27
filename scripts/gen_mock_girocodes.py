"""Write the static demo's GiroCodes from the real gate and payload builder
(``web/src/mocks/data/girocodes.ts``).

The hosted demo runs on hand-written mocks without the backend; its codes must still be exactly
what the app would show. Each payment of the mock world is described here by the facts the gate
reads (:class:`~ordnung.secretary.girocode_gate.TransferFacts`) — its letter's payment details
(``web/src/mocks/data/documents.ts``) and how each value was found on the mock letter
(``letters.ts``: a PDF's text layer is ``verified``, the parking fine's photo ``model_read``).
``web/src/mocks/girocode.test.ts`` checks those facts against the mock data. Run after changing the
gate, the builder or a mock payment::

    .venv/bin/python scripts/gen_mock_girocodes.py > web/src/mocks/data/girocodes.ts
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from ordnung.models import GiroCodeReady
from ordnung.secretary.girocode_gate import (
    DETAILS_CHANGED,
    NOT_A_PAYMENT,
    NOTHING_TO_COMPARE,
    ScamSign,
    TransferFacts,
    decide,
)

WOHNBAU = {"payee": "Wohnbau Musterstadt eG", "iban": "DE05123456000004455660"}
TECHMARKT = {
    "payee": "TechMarkt Online GmbH",
    "iban": "DE70123478000048213000",
    "reference": "RE-2026-084213",
}
TEXT_LAYER: dict[str, Any] = {
    "amount_grounding": "verified",
    "iban_grounding": "verified",
    "reference_grounding": "verified",
}
PHOTO: dict[str, Any] = {
    "amount_grounding": "model_read",
    "iban_grounding": "model_read",
    "reference_grounding": "model_read",
}

#: Every payment of the mock world, as the gate sees it.
PAYMENTS: dict[str, dict[str, Any]] = {
    # the fine is a phone photo: every value was read by AI
    "itm_parking": {
        "payee": "Stadtkasse Musterstadt",
        "iban": "DE51123456000000100017",
        "reference": "OA-VW-2026-55012",
        "amount": 30.0,
        **PHOTO,
    },
    "itm_tm_dunning": {**TECHMARKT, "amount": 94.99, **TEXT_LAYER},
    # replaced by the reminder: the mock files it as set aside
    "itm_tm_invoice": {**TECHMARKT, "amount": 89.99, "status": "dismissed", **TEXT_LAYER},
    # the lease's sentence gives the due day, not the amount; and the lease asked for September's
    # rent too (paid): its reference may be that one's, so the monthly rent gets no code
    "itm_rent_oct": {
        **WOHNBAU,
        "reference": "12-0412-07",
        "amount": 640.0,
        **TEXT_LAYER,
        "amount_grounding": "unverified",
        "other_transfers": 1,
    },
    "itm_rent_sep": {**WOHNBAU, "reference": "12-0412-07", "amount": 640.0, "status": "done", **TEXT_LAYER},
    "itm_nk": {**WOHNBAU, "reference": "MV-2025-0412 NK 2025", "amount": 184.3, **TEXT_LAYER},
    "itm_rundfunk": {
        "payee": "Beitragsservice Musterstadt",
        "iban": "DE57123489000055081836",
        "reference": "457 812 309",
        "amount": 55.08,
        **TEXT_LAYER,
    },
    "itm_semester": {
        "payee": "Hochschule Musterstadt",
        "iban": "DE10123456000007700220",
        "reference": "2231847 SoSe27",
        "amount": 312.4,
        **TEXT_LAYER,
    },
    # the New-mail scam letter: the genuine sender's name, another account
    "itm_scam_demand": {
        "payee": "BS Inkasso Service",
        "iban": "LT717300010123456789",
        "reference": "BS-2026-99812",
        "amount": 210.0,
        "scam": ScamSign("iban_changed", party="Beitragsservice Musterstadt"),
        **TEXT_LAYER,
    },
    # letters that name no account (paid in person, by direct debit, or not said)
    **{
        item_id: {"amount": amount, **TEXT_LAYER}
        for item_id, amount in (
            ("itm_library_fee", 4.5),
            ("itm_abh_fee", 93.0),
            ("itm_power_abschlag", 48.0),
            ("itm_bkk", 142.86),
            ("itm_liability", 59.9),
            ("itm_power_new", 55.0),
        )
    },
}


def facts(item_id: str) -> TransferFacts:
    return TransferFacts(item_id=item_id, **PAYMENTS[item_id])


def amount_changed(item_id: str) -> TransferFacts:
    """The payment with an amount its letter doesn't state (changed by hand): only a photo's stays
    ``model_read``. The amount itself is the mock's to fill in (``web/src/mocks/girocode.ts``)."""
    base = facts(item_id)
    grounding = "model_read" if base.amount_grounding == "model_read" else "unverified"
    return replace(base, amount=1.0, amount_grounding=grounding)


def render() -> str:
    """The TypeScript module (see the module docstring)."""
    codes = {item_id: decide(facts(item_id)).model_dump() for item_id in PAYMENTS}
    checked: dict[str, Any] = {}
    changed: dict[str, Any] = {}
    for item_id, code in codes.items():
        if code["status"] == "blocked" and code["reason"] == "check_letter":
            base = facts(item_id)
            ready = decide(replace(base, checked=base.values))
            assert isinstance(ready, GiroCodeReady)
            checked[item_id] = ready.model_dump()
        if code["status"] == "ready" or code["reason"] == "check_letter":
            asks = decide(amount_changed(item_id)).model_dump()
            assert asks["reason"] == "check_letter" and asks["values"]["amount"] == 1.0
            changed[item_id] = {**asks, "values": {**asks["values"], "amount": None}}
    messages = {
        status: decide(replace(facts("itm_nk"), status=status)).model_dump()["message"]
        for status in ("done", "dismissed")
    }
    messages["no_iban"] = decide(facts("itm_library_fee")).model_dump()["message"]
    messages["no_amount"] = decide(replace(facts("itm_nk"), amount=None)).model_dump()["message"]
    refusals = {
        "not_a_payment": NOT_A_PAYMENT,
        "nothing_to_compare": NOTHING_TO_COMPARE,
        "changed": DETAILS_CHANGED,
    }

    def dump(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2)

    lines = [
        "// Generated by scripts/gen_mock_girocodes.py from the real gate — do not edit by hand.",
        'import type { GiroCode, GiroCodeBlocked, GiroCodeReady } from "@/api/types";',
        "",
        "/** Each payment's GiroCode as the demo starts (or why there is none). */",
        f"export const GIROCODES: Record<string, GiroCode> = {dump(codes)};",
        "",
        "/** The code once the person compared the details with the paper letter. */",
        f"export const GIROCODES_CHECKED: Record<string, GiroCodeReady> = {dump(checked)};",
        "",
        "/**",
        " * What a payment with a code (or waiting for one) asks once its amount was changed by hand: compare",
        " * with the paper letter (`values.amount` is the to-do's new amount, filled in by the mock).",
        " */",
        f"export const GIROCODES_AMOUNT_CHANGED: Record<string, GiroCodeBlocked> = {dump(changed)};",
        "",
        "/** Why a payment marked paid or set aside, or without an account or an amount, has no code. */",
        "export const GIROCODE_MESSAGES: Record<"
        f'"done" | "dismissed" | "no_iban" | "no_amount", string> = {dump(messages)};',
        "",
        "/** Why “These match the letter” is refused (409). */",
        f"export const GIROCODE_REFUSALS = {dump(refusals)} as const;",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    print(render(), end="")


if __name__ == "__main__":
    main()
