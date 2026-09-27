"""The sending advice names each channel as the web app does (UI audit R1-backend-10: "e-mail" and
"E-mail" next to the app's "Email", "Online cancellation button" next to "Cancel button on their website",
"Letter by normal post" next to "Letter by post")."""

from __future__ import annotations

import itertools
import re
from datetime import date
from pathlib import Path
from typing import get_args

from ordnung.models import ContractCategory, DraftKind, SendGuidance
from ordnung.rules.send import send_guidance

COPY = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "copy.ts"
TODAY = date(2026, 9, 28)


def _every_guidance() -> list[SendGuidance]:
    found = []
    for kind, category, party, letter in itertools.product(
        get_args(DraftKind),
        (None, *get_args(ContractCategory)),
        (None, "tax_office", "health_insurer", "landlord", "insurer"),
        (None, "court_payment_order", "enforcement_order", "landlord_notice", "rent_increase"),
    ):
        found.append(
            send_guidance(kind, contract_category=category, party_kind=party, letter_kind=letter, today=TODAY)
        )
    for court, labour, unsure in itertools.product((False, True), repeat=3):
        found.append(
            send_guidance("general_reply", court=court, labour_court=labour, court_unsure=unsure, today=TODAY)
        )
    return found


def _web_label(channel: str) -> str:
    found = re.search(rf'^\s*{channel}: \{{ label: "([^"]+)"', COPY.read_text(encoding="utf-8"), re.M)
    assert found, channel
    return found.group(1)


def test_email_is_spelled_as_the_app_spells_it() -> None:
    for guidance in _every_guidance():
        texts = [
            guidance.form_note,
            *guidance.tips,
            *(t for c in guidance.channels for t in (c.label, c.note)),
        ]
        assert not [text for text in texts if text and re.search(r"e-mail", text, re.I)], guidance


def test_plain_channels_carry_the_apps_names() -> None:
    labels = {(c.channel, c.label) for guidance in _every_guidance() for c in guidance.channels}
    button = {label for channel, label in labels if channel == "online_button"}
    # the cancellation button as the app names it; a withdrawal has a button of its own
    assert button == {_web_label("online_button"), "The withdrawal button (contracts made online)"}
    post = {label for channel, label in labels if channel == "letter"}
    assert _web_label("letter") in post and "Letter by normal post" not in post
    assert post <= {"Letter by post", "Signed letter by post"}
    assert {label for channel, label in labels if channel == "email"} <= {"Email", "Plain email"}
