"""The real demo and the sender's Land the postcode on their letter suggests (ADR 0019): which senders it asks
about, and why it raises no Idea there."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.demo.loader import DEFAULT_SNAPSHOT
from ordnung.secretary.sender_land import RULE_ID, region_suggestion, sender_land_ideas
from ordnung.secretary.triggers import Ledger, run_triggers
from ordnung.tick import local_today


@pytest.fixture
def demo(tmp_path: Path) -> Iterator[Store]:
    if not (DEFAULT_SNAPSHOT / "ordnung.db").is_file():
        pytest.skip("no demo snapshot in this checkout")
    data = tmp_path / "demo"
    shutil.copytree(DEFAULT_SNAPSHOT, data)
    store = Store.open(Paths(data))
    yield store
    store.close()


def test_the_demo_has_no_sender_land_idea(demo: Store) -> None:
    """No demo date waits for a sender's Land — not a to-do, not a contract decision worked out on read — so
    the rule adds no Idea. One would change what the recorded review and brief requests were made from (they
    send the Ideas' titles), and the demo would no longer replay."""
    today = local_today(demo)
    assert sender_land_ideas(Ledger(demo, today)) == []
    assert run_triggers(demo, today)[RULE_ID] == []


def test_the_demo_asks_two_senders_in_berlin(demo: Store) -> None:
    """Sam's town, 12345 Musterstadt, is a Berlin postcode while Sam set North Rhine-Westphalia, so the senders
    in that town are not asked (the own-Land check); the two Berlin senders elsewhere are, in their details.
    The others' postcodes aren't listed, or they have none."""
    ledger = Ledger(demo, local_today(demo))
    asked = {
        party.name: (found.region, found.postcode, found.waiting)
        for party in ledger.parties.values()
        if (found := region_suggestion(ledger, party)) is not None
    }
    assert asked == {
        "FunkNetz Mobil GmbH": ("BE", "12351", 0),
        "TechMarkt Online GmbH": ("BE", "12353", 0),
    }
    assert all(party.region is None for party in ledger.parties.values())
