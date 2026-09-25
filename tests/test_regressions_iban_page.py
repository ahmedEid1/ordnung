"""A misread IBAN taken from the letter's text layer (round 2, R2-IBAN-1).

``plan.payment_details`` swaps a model-misread IBAN for the valid one printed on the page, but the scam
check in ``link.check_payment`` used to run on the raw model reading. So the same letter both showed
the printed (valid) IBAN and warned that the misread one "is not a valid account number … may be
fake", and the printed IBAN was never learned as the sender's known account (which the "IBAN changed
since last time" scam check relies on).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import TAX_IBAN, TAX_LETTER
from ordnung import clock
from test_api_support import TODAY, ApiRouter, api_for

MISREAD = TAX_IBAN[:-3] + "1" + TAX_IBAN[-2:]  # one digit misread: fails its checksum


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def test_an_iban_corrected_from_the_page_is_checked_and_learned_as_printed(data_dir: Path) -> None:
    """The scam check and the sender's known IBANs see the page-corrected IBAN the letter stores — no
    'is not a valid account number … fake' warning about an IBAN it no longer shows."""
    assert MISREAD != TAX_IBAN
    router = ApiRouter()
    router.payloads[TAX_LETTER.marker]["payment"]["iban"] = MISREAD
    async with api_for(data_dir, router=router) as api:
        body = await api.upload(("letter.pdf", TAX_LETTER.pdf()))
        await api.read_all()
        detail = (await api.client.get(f"/api/documents/{body['documents'][0]['id']}")).json()

    payment = detail["document"]["payment"]
    assert (payment["iban"], payment["iban_valid"]) == (TAX_IBAN, True)  # the fix itself works
    assert not any("not a valid account number" in warning for warning in detail["document"]["warnings"])
    assert detail["party"]["ibans"] == [TAX_IBAN]
