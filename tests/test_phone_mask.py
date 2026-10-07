"""What a paired phone sees of the person's own numbers: the last 4 characters, in *My numbers*, the
profile and Ask's tools; an organisation's own numbers stay whole, and a masked number's key can't be
traced back to it. Also: the privacy log's attribution ends with the phone's request."""

from __future__ import annotations

import asyncio

from helpers_secretary import TODAY, seed_ledger
from ordnung.assistant.channels import render_tool_result
from ordnung.assistant.mcp_server import MASKED_NUMBERS_ENV, LedgerTools, server_config
from ordnung.db.store import Store
from ordnung.models import Profile
from ordnung.phone.actor import DeviceRef, acting, attribute, current
from ordnung.phone.mask import mask_numbers, mask_profile, mask_value
from ordnung.views import my_numbers
from test_mcp_server import _numbers_ledger

OWN = ("86095742719", "65 140300 R 004", "FN-123456", "X1234567")


def test_a_value_shows_its_last_four_characters() -> None:
    assert mask_value("DE89 3704 0044 0532 0130 00") == "•••• 3000"
    assert mask_value("86095742719") == "•••• 2719"
    assert mask_value("4711") == "4711"
    assert mask_profile(Profile(iban="DE89370400440532013000", address="Musterweg 1")).model_dump() == {
        **Profile(iban="DE89370400440532013000", address="Musterweg 1").model_dump(),
        "iban": "•••• 3000",
    }
    assert mask_profile(Profile()).iban == ""


def test_my_numbers_on_a_phone_shows_the_person_s_numbers_masked(store: Store) -> None:
    ids = seed_ledger(store)
    _numbers_ledger(store, ids)
    page = my_numbers(store, TODAY)
    masked = mask_numbers(page)
    assert masked.masked is True and page.masked is False
    text = masked.model_dump_json()
    for value in OWN:
        assert value not in text and value.replace(" ", "") not in text, value
    assert "•••• 2719" in text
    original_keys = {n.key for n in page.about_you}
    assert not original_keys & {n.key for n in masked.about_you}
    # an organisation's own numbers stay whole (the phone pays with them)
    theirs = [n.value for sheet in masked.organisations for n in sheet.their_numbers]
    assert theirs == [n.value for sheet in page.organisations for n in sheet.their_numbers] and theirs


def test_ask_s_tools_mask_the_person_s_numbers_for_a_phone(store: Store) -> None:
    ids = seed_ledger(store)
    _numbers_ledger(store, ids)
    full = render_tool_result(LedgerTools(store, today=TODAY).get_my_numbers())
    masked = render_tool_result(LedgerTools(store, today=TODAY, masked_numbers=True).get_my_numbers())
    assert "86095742719" in full and "86095742719" not in masked and "•••• 2719" in masked
    config = server_config("/data", masked_numbers=True)
    assert config["mcpServers"]["ordnung"]["env"] == {MASKED_NUMBERS_ENV: "1"}
    assert "env" not in server_config("/data")["mcpServers"]["ordnung"]


async def test_attribution_ends_with_the_phone_s_request() -> None:
    phone = DeviceRef("phn_000000000001", "Sam's iPhone")
    seen: list[object] = []

    async def later() -> None:
        await asyncio.sleep(0.01)
        seen.append(current())

    with acting(phone):
        assert attribute("Added a to-do", None) == ("Added a to-do (on Sam's iPhone)", {"device": phone.id})
        assert attribute("Added “x”", {"source": "phone"}) == (
            "Added “x”",
            {"source": "phone", "device": phone.id},
        )
        assert await asyncio.to_thread(current) == phone  # work in a thread is the request's too
        task = asyncio.create_task(later())
    await task
    assert seen == [None]  # a task the request started, running on after it ended, is not the phone's
    assert current() is None and attribute("x", {"a": 1}) == ("x", {"a": 1})
