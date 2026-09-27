"""The ledger-free rules tools (``ordnung.assistant.rules_tools``): the deadline engine, the holiday
calendar, working days and the IBAN check as MCP tools — their answers, strict validation and
readable errors, the "information, not legal advice" framing, the rules-only server (no ledger tools,
no data folder, over a real stdio handshake) and the same tools inside the full ledger server."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime, tzinfo
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver.exceptions import ToolError
from typer.testing import CliRunner

from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.assistant import rules_tools
from ordnung.assistant.mcp_server import build_server, server_config
from ordnung.assistant.rules_tools import (
    DISCLAIMER_TEMPLATE,
    FORMAL_SERVICE_HINT,
    FORMAL_SERVICE_WARNING,
    INSTRUCTIONS,
    SERVER_NAME,
    RulesToolError,
    RulesTools,
    build_rules_server,
    compact,
    render,
    rules_server_config,
    tool_definitions,
)
from ordnung.cli import app
from ordnung.db.store import Store
from ordnung.ingest.extract import unwrap_untrusted
from ordnung.models import DateSpec
from ordnung.money.iban import INVALID_IBAN_ADVICE
from ordnung.rules import LAST_CHECKED, calendar_de
from ordnung.rules.deadlines import (
    DECLARATION_ARRIVAL_WARNING,
    HOME_HOLIDAY,
    PRIVATE_SENDER_DATED_WARNING,
    PRIVATE_SENDER_WARNING,
    REGION_EARLIER,
    REGION_UNKNOWN,
    TAX_OFFICE_HOLIDAY,
)
from ordnung.secretary.scam import invalid_iban_message

RULES_TOOLS = {"compute_deadline", "german_holidays", "add_working_days", "check_iban"}
LEDGER_TOOLS = {
    "search",
    "get_document",
    "list_items",
    "list_contracts",
    "get_party",
    "timeline",
    "money_summary",
    "explain_date",
    "get_profile",
    "today",
}
READ_TODAY = date(2026, 9, 20)
#: The README's tax assessment: "one month after this notice is announced to you".
TAX_SPEC: dict[str, Any] = {
    "type": "relative",
    "anchor": "deemed_delivery",
    "amount": 1,
    "unit": "months",
    "delivery_rule": "de_admin_post",
    "nature": "objection",
    "text": "Die Frist für die Einlegung des Einspruchs beträgt einen Monat.",
}
DISCLAIMER = DISCLAIMER_TEMPLATE.format(checked=LAST_CHECKED)


@pytest.fixture
def tools() -> RulesTools:
    return RulesTools(today=lambda: READ_TODAY)


def at(day: str) -> RulesTools:
    """The tools on a server whose today is ``day`` (a caller's today far off is only a what-if)."""
    return RulesTools(today=lambda: date.fromisoformat(day))


def _json(text: str) -> dict[str, Any]:
    data = json.loads(text)
    assert isinstance(data, dict)
    return data


# --------------------------------------------------------------------------------------------------
# compute_deadline
# --------------------------------------------------------------------------------------------------


def test_a_tax_assessment_gets_the_engines_date_with_its_receipt(tools: RulesTools) -> None:
    result = tools.compute_deadline(TAX_SPEC, document_date="2026-09-15", sender_kind="tax_office")
    assert (result["due_date"], result["weekday"], result["send_by"]) == (
        "2026-10-21",
        "Wednesday",
        "2026-10-15",
    )
    # a yellow envelope would count from its date: the warning says so, the hint says what to pass
    assert result["confidence"] == "high" and result["hints"] == [FORMAL_SERVICE_HINT]
    assert result["warnings"] == [FORMAL_SERVICE_WARNING]
    assert "spec." not in FORMAL_SERVICE_WARNING and "spec.anchor receipt" in FORMAL_SERVICE_HINT
    assert "moved to Mon 21 Sep" in result["summary"]
    assert [step["rule_id"] for step in result["steps"]][:3] == [
        "posting_day",
        "ao_122_2_1",
        "ao_fiction_shift",
    ]
    assert all(step["citation"] for step in result["steps"])
    rules = {rule["id"]: rule for rule in result["rules"]}
    assert "§ 122 Abs. 2 Nr. 1 AO" in rules["ao_122_2_1"]["citation"] and rules["ao_122_2_1"]["url"]
    assert compact(result["assumed"]) == {
        "today": "2026-09-20",
        "letter_date": "2026-09-15",
        "delivery_law": "tax law (§ 122 AO)",
        "holiday_calendar": "Germany (nationwide holidays only)",
        "holidays_from": "region: the Land where the deadline is met (the sender's seat)",
    }
    assert result["disclaimer"] == DISCLAIMER and "not legal advice" in DISCLAIMER
    assert "Einspruchs" not in json.dumps(result, ensure_ascii=False)  # the letter's words are not echoed


def test_the_sender_selects_the_delivery_law_as_in_the_app(tools: RulesTools) -> None:
    """The same sentence from a city office: the delivery day does not move off a Saturday (§ 41 VwVfG)."""
    city = tools.compute_deadline(TAX_SPEC, document_date="2026-09-15", sender_kind="authority", region="NW")
    assert city["due_date"] == "2026-10-19"
    assert city["assumed"]["delivery_law"] == "general administrative law (§ 41 VwVfG)"
    job_centre = tools.compute_deadline(
        TAX_SPEC, document_date="2026-09-15", sender_kind="authority", sender_name="Jobcenter Musterstadt"
    )
    assert job_centre["assumed"]["delivery_law"] == "social law (§ 37 SGB X)"
    family = {"document_date": "2026-09-15", "sender_kind": "authority", "sender_name": "Familienkasse NRW"}
    assert tools.compute_deadline(TAX_SPEC, remedy_type="einspruch", **family)["assumed"]["delivery_law"] == (
        "tax law (§ 122 AO)"
    )
    assert tools.compute_deadline(TAX_SPEC, **family)["assumed"]["delivery_law"] == "social law (§ 37 SGB X)"


def test_a_fixed_date_and_the_region_that_moves_it(tools: RulesTools) -> None:
    spec = {"type": "fixed", "date": "2026-11-01", "nature": "payment", "shift_rule": "next_business_day"}
    assert tools.compute_deadline(spec)["due_date"] == "2026-11-02"  # a Sunday
    assert tools.compute_deadline(DateSpec.model_validate(spec), region="Bayern")["due_date"] == "2026-11-02"


def test_hints_name_the_missing_argument(tools: RulesTools) -> None:
    missing = tools.compute_deadline(TAX_SPEC)
    assert missing["due_date"] is None and missing["confidence"] == "low"
    assert any(hint.startswith("Pass document_date") for hint in missing["hints"])
    assert any(hint.startswith("Pass sender_kind") for hint in missing["hints"])

    receipt = {"type": "relative", "anchor": "receipt", "amount": 14, "unit": "days", "nature": "payment"}
    assumed = tools.compute_deadline(receipt, document_date="2026-09-15")
    assert assumed["due_date"] == "2026-09-29" and any("received_date" in h for h in assumed["hints"])
    confirmed = tools.compute_deadline(receipt, document_date="2026-09-15", received_date="2026-09-17")
    assert confirmed["due_date"] == "2026-10-01" and confirmed["hints"] == []
    assert confirmed["assumed"]["received_date"] == "2026-09-17" and confirmed["confidence"] == "high"

    explicit = tools.compute_deadline(
        {"type": "relative", "anchor": "explicit_date", "amount": 2, "unit": "weeks"}
    )
    assert explicit["hints"] == ["Set spec.anchor_date to the day the period runs from."]

    # Corpus Christi (Thu 4 Jun 2026) is a holiday in some Länder only: without a region, say so.
    month = {
        "type": "relative",
        "anchor": "document_date",
        "amount": 1,
        "unit": "months",
        "nature": "objection",
    }
    unknown = tools.compute_deadline(month, document_date="2026-05-04")
    assert unknown["due_date"] == "2026-06-04"
    assert any(hint.startswith("Pass region") for hint in unknown["hints"])
    known = tools.compute_deadline(month, document_date="2026-05-04", region="NW")
    assert known["due_date"] == "2026-06-05" and known["hints"] == []
    assert known["assumed"]["holiday_calendar"] == "Nordrhein-Westfalen"


OBJECTION = {
    "type": "relative",
    "anchor": "deemed_delivery",
    "amount": 1,
    "unit": "months",
    "nature": "objection",
}
POSTED = {**OBJECTION, "delivery_rule": "de_admin_post"}


def _hint(result: dict[str, Any], start: str) -> bool:
    return any(hint.startswith(start) for hint in result["hints"])


def test_hints_for_deemed_delivery_name_the_sender_even_without_a_delivery_rule(tools: RulesTools) -> None:
    result = tools.compute_deadline(OBJECTION, document_date="2026-09-10")
    assert any("which law governs this sender" in warning for warning in result["warnings"])
    assert _hint(result, "Pass sender_kind")


def test_hints_for_a_letter_counting_from_today_without_its_date(tools: RulesTools) -> None:
    spec = {"type": "relative", "anchor": "today", "amount": 1, "unit": "months", "nature": "payment"}
    result = tools.compute_deadline(spec)
    assert "the real deadline may be earlier" in result["warnings"][0]
    assert _hint(result, "Pass document_date") and "the day it was written" in result["hints"][0]
    assert tools.compute_deadline(spec, document_date="2026-09-15")["hints"] == []


def test_hints_name_the_authoritys_land_where_the_4_day_rule_is_unconfirmed(tools: RulesTools) -> None:
    unknown = tools.compute_deadline(POSTED, document_date="2026-09-10", sender_kind="immigration_office")
    assert unknown["due_date"] == "2026-10-13" and _hint(unknown, "Pass region — the Land of the authority")
    confirmed = tools.compute_deadline(
        POSTED, document_date="2026-09-10", sender_kind="immigration_office", region="NW"
    )
    assert confirmed["due_date"] == "2026-10-14" and confirmed["hints"] == [FORMAL_SERVICE_HINT]
    # Hessen's own law is not confirmed: the region is given, so there is nothing to ask for
    hesse = tools.compute_deadline(POSTED, document_date="2026-09-10", sender_kind="authority", region="HE")
    assert hesse["due_date"] == "2026-10-13" and hesse["hints"] == [FORMAL_SERVICE_HINT]


def test_hints_for_a_tax_letter_name_the_other_place() -> None:
    """Epiphany (Tue 6 Jan 2026) moves a Bavarian tax letter's delivery day only if the person lives there too."""
    tools = at("2026-01-05")
    tax = {"document_date": "2026-01-02", "sender_kind": "tax_office"}
    office_only = tools.compute_deadline(POSTED, region="BY", **tax)
    assert office_only["due_date"] == "2026-02-06" and _hint(office_only, "Pass recipient_region")
    home_only = tools.compute_deadline(POSTED, recipient_region="BY", **tax)
    assert home_only["due_date"] == "2026-02-06" and _hint(home_only, "Pass region — the tax office's Land")
    both = tools.compute_deadline(POSTED, region="BY", recipient_region="BY", **tax)
    assert both["due_date"] == "2026-02-09" and both["hints"] == [FORMAL_SERVICE_HINT]


def test_hints_never_ask_again_for_a_sender_that_was_given(tools: RulesTools) -> None:
    result = tools.compute_deadline(
        POSTED, document_date="2026-09-10", sender_kind="utility", sender_name="Stadtwerke Musterstadt"
    )
    assert not _hint(result, "Pass sender_kind") and not _hint(result, "Pass region")
    assert _hint(result, "If the letter is an authority's decision after all (a Bescheid), pass its kind")


RECEIPT = {"type": "relative", "anchor": "receipt", "amount": 2, "unit": "weeks", "nature": "objection"}


def test_an_arrival_day_after_today_is_refused(tools: RulesTools) -> None:
    with pytest.raises(RulesToolError, match=r"received_date \(2027-08-01\) is after today \(2026-09-20\)"):
        tools.compute_deadline(RECEIPT, document_date="2026-09-01", received_date="2027-08-01")
    # a caller's later today is only a what-if: the letter has not arrived yet on the real today
    with pytest.raises(RulesToolError, match=r"received_date \(2026-10-02\) is after today \(2026-09-20\)"):
        tools.compute_deadline(
            RECEIPT, document_date="2026-09-01", received_date="2026-10-02", today="2026-10-05"
        )
    a_zone_ahead = tools.compute_deadline(
        RECEIPT, document_date="2026-09-01", received_date="2026-09-21", today="2026-09-21"
    )
    assert a_zone_ahead["due_date"] == "2026-10-05"


def test_an_arrival_day_before_the_letters_date_is_flagged_not_trusted(tools: RulesTools) -> None:
    """A swapped digit (1 Sep for 10 Sep) must not quietly tell the person their deadline has passed."""
    swapped = tools.compute_deadline(RECEIPT, document_date="2026-09-10", received_date="2026-09-01")
    assert swapped["due_date"] == "2026-09-15" and swapped["confidence"] == "medium"
    assert any("is before the letter's date (Thu 10 Sep 2026)" in w for w in swapped["warnings"])
    usual = tools.compute_deadline(RECEIPT, document_date="2026-09-10", received_date="2026-09-19")
    assert usual["due_date"] == "2026-10-05" and usual["confidence"] == "high" and usual["warnings"] == []


def test_an_arrival_day_weeks_after_the_letter_is_flagged(tools: RulesTools) -> None:
    late = tools.compute_deadline(RECEIPT, document_date="2026-08-01", received_date="2026-09-18")
    assert late["due_date"] == "2026-10-02" and late["confidence"] == "medium"
    assert any("48 days after the letter's date" in w and "keep the envelope" in w for w in late["warnings"])
    # deemed delivery already keeps the earlier, safe day for a late arrival: no second warning
    deemed = tools.compute_deadline(
        POSTED, document_date="2026-08-03", received_date="2026-09-18", sender_kind="tax_office"
    )
    assert not any("unusually late" in w for w in deemed["warnings"])


def test_a_delivery_day_the_letter_states_is_checked_like_an_arrival_day(tools: RulesTools) -> None:
    """With anchor receipt the engine counts from spec.anchor_date: the checks must look at that day."""
    stated = {**RECEIPT, "anchor_date": "2027-08-01"}
    with pytest.raises(
        RulesToolError, match=r"spec.anchor_date \(2027-08-01\) is after today \(2026-09-20\)"
    ):
        tools.compute_deadline(stated, document_date="2026-09-01")
    with pytest.raises(RulesToolError, match=r"spec\.anchor_date"):  # no letter date: still a future day
        tools.compute_deadline(stated)

    late = tools.compute_deadline({**RECEIPT, "anchor_date": "2026-09-19"}, document_date="2026-08-01")
    assert late["due_date"] == "2026-10-05" and late["confidence"] == "medium"
    assert any(
        w.startswith("The delivery day in spec.anchor_date (Sat 19 Sep 2026) is 49 days after")
        for w in late["warnings"]
    )
    # the hint must not claim the letter's date was used, and assumed names the day that was
    assert late["hints"] == []
    assert (late["assumed"]["received_date"], late["assumed"]["received_date_from"]) == (
        "2026-09-19",
        "spec.anchor_date: the delivery day the letter states",
    )

    usual = tools.compute_deadline({**RECEIPT, "anchor_date": "2026-09-17"}, document_date="2026-09-14")
    assert usual["due_date"] == "2026-10-01" and usual["confidence"] == "high"
    assert usual["warnings"] == [] and usual["hints"] == []


def test_an_arrival_day_the_engine_did_not_use_is_named(tools: RulesTools) -> None:
    both = tools.compute_deadline(
        {**RECEIPT, "anchor_date": "2026-09-17"}, document_date="2026-09-14", received_date="2026-09-18"
    )
    assert both["due_date"] == "2026-10-01" and both["assumed"]["received_date"] == "2026-09-17"
    assert any(w.startswith("received_date (Fri 18 Sep 2026) was not used") for w in both["warnings"])
    # a stated day before the letter's date is no delivery day: the engine counts from the letter's date
    before = tools.compute_deadline({**RECEIPT, "anchor_date": "2026-09-10"}, document_date="2026-09-14")
    assert before["due_date"] == "2026-09-28"
    assert any(
        w.startswith("spec.anchor_date (Thu 10 Sep 2026) is before the letter's date")
        and "the letter's date." in w
        for w in before["warnings"]
    )
    assert _hint(before, "Pass received_date")
    assert before["assumed"]["received_date_from"] == "document_date: assumed, the earliest plausible arrival"
    given = tools.compute_deadline(
        {**RECEIPT, "anchor_date": "2026-09-10"}, document_date="2026-09-14", received_date="2026-09-16"
    )
    assert given["due_date"] == "2026-09-30" and not _hint(given, "Pass received_date")
    assert any("counted from the arrival day given (Wed 16 Sep 2026)" in w for w in given["warnings"])


def test_a_letter_dated_after_today_is_flagged(tools: RulesTools) -> None:
    month = {"type": "relative", "anchor": "document_date", "amount": 1, "unit": "months"}
    future = tools.compute_deadline(month, document_date="2027-09-14")
    assert future["due_date"] == "2027-10-14" and future["confidence"] == "medium"
    assert any(
        "is after today (Sun 20 Sep 2026)" in w and "the year above all" in w for w in future["warnings"]
    )
    assert tools.compute_deadline(month, document_date="2026-09-14")["confidence"] == "high"
    # "today" in a letter dated later: the engine's own warning is enough
    from_today = tools.compute_deadline({**month, "anchor": "today"}, document_date="2027-09-14")
    assert not any("the year above all" in w for w in from_today["warnings"])


def test_a_sender_without_deemed_delivery_counts_from_arrival(tools: RulesTools) -> None:
    """A company's letter has no deemed delivery: 3 added days would make its date late. The rule is the
    engine's (the app gives the same date), and the tool names the day it counted from."""
    payment = {**POSTED, "amount": 14, "unit": "days", "nature": "payment"}
    company = tools.compute_deadline(payment, document_date="2026-09-14", sender_kind="company")
    assert company["due_date"] == "2026-09-28"  # not 1 Oct (letter + 3 days + 14)
    assert not any("posting_day" == step["rule_id"] for step in company["steps"])
    assert PRIVATE_SENDER_WARNING in company["warnings"] and FORMAL_SERVICE_WARNING not in company["warnings"]
    assert company["steps"][0]["rule_id"] == "private_sender_arrival"
    assert "the letter's date (Mon 14 Sep 2026)" in company["steps"][0]["label"]
    assert (
        company["assumed"]["received_date_from"] == "document_date: assumed, the earliest plausible arrival"
    )
    assert _hint(company, "Pass received_date") and _hint(company, "If the letter is an authority's decision")
    arrived = tools.compute_deadline(
        payment, document_date="2026-09-14", sender_kind="landlord", received_date="2026-09-16"
    )
    assert arrived["due_date"] == "2026-09-30" and arrived["confidence"] == "high"
    # a delivery rule on a period counted from the letter's date is dropped too — and that period keeps
    # the letter's date: it never claims to run from arrival, and an arrival day given is not used
    dated = {**payment, "anchor": "document_date"}
    for received in (None, "2026-09-16"):
        invoice = tools.compute_deadline(
            dated, document_date="2026-09-14", sender_kind="company", received_date=received
        )
        assert invoice["due_date"] == "2026-09-28"
        assert PRIVATE_SENDER_DATED_WARNING in invoice["warnings"]
        assert PRIVATE_SENDER_WARNING not in invoice["warnings"]
        assert invoice["steps"][0]["rule_id"] == "private_sender_no_delivery"
        assert invoice["assumed"]["received_date_not_used"] == received
        assert not _hint(invoice, "Pass received_date")
    # an unknown sender keeps the engine's deemed delivery and is asked for — "other" is the app's
    # "don't know", not "no authority"
    unknown = tools.compute_deadline(payment, document_date="2026-09-14")
    assert unknown["due_date"] == "2026-10-01" and _hint(unknown, "Pass sender_kind")
    other = tools.compute_deadline(payment, document_date="2026-09-14", sender_kind="other")
    assert other["due_date"] == "2026-10-01" and _hint(other, "Pass sender_kind")
    assert PRIVATE_SENDER_WARNING not in other["warnings"]
    assert tools.compute_deadline(payment, document_date="2026-09-14", sender_kind="tax_office")[
        "due_date"
    ] == ("2026-10-02")


def test_an_unknown_or_misfiled_sender_gets_the_apps_date_not_a_later_one() -> None:
    """Reviewer repro: "other" is the app's "don't know" and an AOK filed as "insurer" with a Widerspruch
    is an authority — both keep the earliest plausible deemed delivery, exactly as the app computes it,
    and saying "I don't know the sender" never makes the answer later or more confident than saying nothing."""
    from ordnung.rules import RuleContext, compute_due, is_private_sender, scope_for_party_kind

    tools = at("2026-04-01")
    spec = {
        **POSTED,
        "text": "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
    }
    args = {"document_date": "2026-03-02", "remedy_type": "widerspruch", "received_date": "2026-03-12"}
    nothing = tools.compute_deadline(spec, **args)
    assert nothing["due_date"] == "2026-04-07" and nothing["confidence"] == "low"
    for kind, name in (
        ("other", None),
        ("other", "Stadt Musterstadt"),
        ("insurer", "Muster Versicherung AG"),
    ):
        result = tools.compute_deadline(spec, sender_kind=kind, sender_name=name, **args)
        assert (result["due_date"], result["confidence"]) == ("2026-04-07", "low"), kind
        assert PRIVATE_SENDER_WARNING not in result["warnings"]
        assert any("keep the envelope" in w for w in result["warnings"])  # the later arrival: only if shown
    # a statutory health insurer is known by its name: social law, the same date
    aok = tools.compute_deadline(spec, sender_kind="insurer", sender_name="AOK Nordost", **args)
    assert aok["due_date"] == "2026-04-07" and aok["assumed"]["delivery_law"] == "social law (§ 37 SGB X)"
    assert PRIVATE_SENDER_WARNING not in aok["warnings"]
    assert _hint(tools.compute_deadline(spec, sender_kind="other", **args), "Pass sender_kind")
    # the app: a party of kind "other" (the default) gives the same date
    scope = scope_for_party_kind("other", remedy_type="widerspruch")
    context = RuleContext(
        today=date(2026, 4, 1),
        document_date=date(2026, 3, 2),
        received_date=date(2026, 3, 12),
        received_confirmed=True,
        delivery_scope=scope,
        private_sender=is_private_sender("other", scope=scope, remedy_type="widerspruch"),
    )
    assert compute_due(DateSpec.model_validate(spec), context).due_date == "2026-04-07"
    # a company named with an administrative remedy is an authority's decision too
    company = tools.compute_deadline(spec, sender_kind="company", **args)
    assert company["due_date"] == "2026-04-07" and PRIVATE_SENDER_WARNING not in company["warnings"]


def test_a_firms_own_einspruch_window_counts_from_arrival() -> None:
    """Reviewer repro: a parking firm filed as a company calls its complaint window an "Einspruch". Kind
    and remedy word disagree; without a notice naming an administrative route the period runs from
    arrival — the earlier start in either reading — not from a deemed delivery 3 days after the letter."""
    tools = at("2026-09-20")
    spec = {
        **POSTED,
        "amount": 14,
        "unit": "days",
        "text": "Gegen diese Vertragsstrafe können Sie innerhalb von 14 Tagen Einspruch einlegen.",
    }
    args = {
        "document_date": "2026-09-14",
        "sender_kind": "company",
        "sender_name": "Park & Control GmbH",
        "remedy_type": "einspruch",
        "region": "NW",
    }
    fine = tools.compute_deadline(spec, **args)
    assert fine["due_date"] == "2026-09-28"  # not Fri 2 Oct (the letter + 3 days + 14)
    assert (
        PRIVATE_SENDER_WARNING in fine["warnings"] and fine["steps"][0]["rule_id"] == "private_sender_arrival"
    )
    assert "a firm's own 'Einspruch' window" in " ".join(fine["hints"])
    assert fine == tools.compute_deadline(spec, **{k: v for k, v in args.items() if k != "remedy_type"})
    # an Einspruch whose notice names an administrative act keeps the deemed delivery
    tax = tools.compute_deadline(
        {
            **spec,
            "text": "Gegen diesen Bescheid ist der Einspruch innerhalb eines Monats nach Bekanntgabe gegeben.",
        },
        **args,
    )
    assert PRIVATE_SENDER_WARNING not in tax["warnings"]
    assert any(step["rule_id"] == "posting_day" for step in tax["steps"])


def test_a_firms_let_us_know_is_no_bescheid() -> None:
    """Reviewer repro: "geben Sie uns … Bescheid" is everyday German for "let us know", not an
    authority's decision. The firm's Einspruch window runs from the arrival day given (Tue 29 Sep), not
    from a deemed delivery (Thu 1 Oct, two days late) that reports the arrival day as unused."""
    tools = at("2026-09-26")
    text = "Wenn Sie Einspruch einlegen möchten, geben Sie uns innerhalb von 14 Tagen nach Zugang Bescheid."
    fine = tools.compute_deadline(
        {**POSTED, "amount": 14, "unit": "days", "text": text},
        document_date="2026-09-14",
        sender_kind="company",
        sender_name="Park & Control GmbH",
        remedy_type="einspruch",
        received_date="2026-09-15",
    )
    assert fine["due_date"] == "2026-09-29"
    assert fine["steps"][0]["rule_id"] == "private_sender_arrival"
    assert not any(step["rule_id"] in ("posting_day", "early_receipt") for step in fine["steps"])
    assumed = fine["assumed"]
    assert (assumed["received_date"], assumed["received_date_from"]) == ("2026-09-15", "received_date")
    assert assumed["received_date_not_used"] is None and not _hint(fine, "Pass region")


def test_a_private_senders_bekanntgabe_counts_from_the_day_it_arrived() -> None:
    """Reviewer repro: a gym's "nach Bekanntgabe der Beitragserhöhung", an employer's "§ 38 Abs. 1 SGB III".
    Such words are no proof of an authority's decision: the period still runs from the day the letter
    arrived (§ 130 Abs. 1 BGB), the earliest plausible start — deemed delivery would give Thu 8 Oct, the
    arrival day given would be reported as unused and the hints would ask for "the Land of the authority"."""
    tools = at("2026-09-08")
    spec = {
        **POSTED,
        "amount": 4,
        "unit": "weeks",
        "text": "Sie können der Beitragserhöhung innerhalb von vier Wochen nach Bekanntgabe widersprechen.",
    }
    for kind in ("gym", "landlord", "bank", "telecom", "company"):
        arrived = tools.compute_deadline(
            spec, document_date="2026-09-07", sender_kind=kind, received_date="2026-09-08"
        )
        assert arrived["due_date"] == "2026-10-06", kind
        assert arrived["steps"][0]["rule_id"] == "private_sender_arrival"
        assert not any(step["rule_id"] in ("posting_day", "early_receipt") for step in arrived["steps"])
        assert arrived["assumed"]["received_date"] == "2026-09-08"
        assert arrived["assumed"]["received_date_not_used"] is None and not _hint(arrived, "Pass region")
        undated = tools.compute_deadline(spec, document_date="2026-09-07", sender_kind=kind)
        assert undated["due_date"] == "2026-10-05" and _hint(undated, "Pass received_date")
    certificate = tools.compute_deadline(
        {**spec, "amount": 2, "legal_basis": "§ 38 Abs. 1 SGB III", "text": "innerhalb von zwei Wochen"},
        document_date="2026-09-07",
        sender_kind="employer",
        received_date="2026-09-08",
    )
    assert certificate["due_date"] == "2026-09-22"  # not Thu 24 Sep


def test_a_late_arrival_never_makes_a_private_senders_date_later() -> None:
    """Reviewer repro: that a sender is private is read from its kind — a statutory insurer or a
    municipal utility may be filed as a company. A late arrival must not move the date past the one an
    authority's letter gives (Mon 5 Oct); the warning names the date from arrival, which the law gives
    either kind of sender once the arrival is shown, and the confidence is one level lower."""
    tools = at("2026-09-26")
    spec = {**POSTED, "text": "Einspruch innerhalb eines Monats"}
    args = {
        "document_date": "2026-09-01",
        "remedy_type": "einspruch",
        "received_date": "2026-09-15",
        "region": "NW",
    }
    company = tools.compute_deadline(spec, sender_kind="company", **args)
    authority = tools.compute_deadline(spec, sender_kind="authority", **args)
    assert company["due_date"] == authority["due_date"] == "2026-10-05"  # not Thu 15 Oct
    assert (company["confidence"], authority["confidence"]) == ("medium", "high")
    assert company["warnings"][0] == (
        "The letter arrived on Tue 15 Sep 2026, later than a letter dated Tue 1 Sep 2026 usually counts as "
        "delivered (Sat 5 Sep 2026). If you can show that (keep the envelope), the deadline may be Thu 15 Oct "
        "2026, whether or not the sender is an authority; we show the earlier, safe date."
    )
    assert PRIVATE_SENDER_WARNING not in company["warnings"]
    assert [step["rule_id"] for step in company["steps"]][:2] == ["private_sender_late_arrival", "bgb_187_1"]
    # the period did not run from the arrival day given
    assert company["assumed"]["received_date"] is None
    assert company["assumed"]["received_date_not_used"] == "2026-09-15"
    # nor does a later one move it, so it costs no confidence; but the note's later date counts from
    # it, so an implausible one is flagged all the same (below)
    later = tools.compute_deadline(spec, sender_kind="company", **{**args, "received_date": "2026-09-25"})
    assert (later["due_date"], later["confidence"]) == ("2026-10-05", company["confidence"])
    assert later["warnings"][-1] == (
        "The arrival day given (Fri 25 Sep 2026) is 24 days after the letter's date (Tue 1 Sep 2026), which "
        "is unusually late for post. Check it before relying on the later date counted from it. If it is "
        "right, keep the envelope as proof."
    )
    # a gym issues no Bescheid: its letter counts from the day it arrived (§ 130 BGB)
    gym = tools.compute_deadline(spec, sender_kind="gym", **args)
    assert gym["due_date"] == "2026-10-15" and gym["assumed"]["received_date"] == "2026-09-15"
    # a municipal utility's Gebührenbescheid counts no later than an authority's letter either
    fee = {
        **POSTED,
        "nature": "payment",
        "text": "Die Gebühr ist innerhalb eines Monats nach Bekanntgabe dieses Bescheides zu zahlen.",
    }
    utility = tools.compute_deadline(
        fee, sender_kind="utility", document_date="2026-09-01", received_date="2026-09-14", region="NW"
    )
    assert utility["due_date"] == "2026-10-05" and PRIVATE_SENDER_WARNING not in utility["warnings"]
    assert any("keep the envelope" in w for w in utility["warnings"])


def test_a_capped_late_arrival_day_is_still_checked() -> None:
    """Reviewer repro: a company's letter dated Sat 1 Aug, arrival given as Sun 20 Sep — 50 days later.
    The date shown counts from the usual delivery day, but the note says the deadline "may be Tue 20
    Oct" and "may still be open", from that arrival day: a model must not relay that unchecked. The
    arrival day was not used, and is reported so."""
    tools = at("2026-09-27")
    spec = {**POSTED, "nature": "payment", "text": "innerhalb eines Monats"}
    args = {"document_date": "2026-08-01", "received_date": "2026-09-20"}
    company = tools.compute_deadline(spec, sender_kind="company", **args)
    assert (company["due_date"], company["confidence"]) == ("2026-09-04", "medium")
    assert "may still be open" in company["warnings"][0]
    assert company["warnings"][-1] == (
        "The arrival day given (Sun 20 Sep 2026) is 50 days after the letter's date (Sat 1 Aug 2026), which "
        "is unusually late for post. Check it before relying on the later date counted from it. If it is "
        "right, keep the envelope as proof."
    )
    assert company["assumed"]["received_date"] is None
    assert company["assumed"]["received_date_not_used"] == "2026-09-20"
    # a gym's letter runs from that day: the same check, and one level less confidence in the date
    gym = tools.compute_deadline(spec, sender_kind="gym", **args)
    assert (gym["due_date"], gym["confidence"]) == ("2026-10-20", "medium")
    assert any("Check it: a later arrival day moves the deadline later." in w for w in gym["warnings"])


def test_a_late_arrival_giving_the_same_date_is_the_day_counted_from() -> None:
    """Reviewer repro: a company's payment letter dated Tue 1 Sep (NW) usually counts as delivered Sat 5
    Sep; it arrived Mon 7 Sep, and 14 days from either day end on Mon 21 Sep. Nothing is capped: the
    result is a gym's — from the arrival day, at full confidence, with no "may be Mon 21 Sep" note."""
    tools = at("2026-09-10")
    spec = {**POSTED, "amount": 14, "unit": "days", "nature": "payment", "text": "zahlbar in 14 Tagen"}
    args = {"document_date": "2026-09-01", "received_date": "2026-09-07", "region": "NW"}
    company = tools.compute_deadline(spec, sender_kind="company", **args)
    gym = tools.compute_deadline(spec, sender_kind="gym", **args)
    assert (company["due_date"], company["confidence"]) == ("2026-09-21", "high")
    assert company["warnings"] == gym["warnings"] == [PRIVATE_SENDER_WARNING]
    assert company["assumed"]["received_date"] == "2026-09-07"
    assert company["steps"][0]["rule_id"] == "private_sender_arrival"


@pytest.mark.parametrize(
    "spec",
    [
        {k: v for k, v in POSTED.items() if k != "amount"},
        {"type": "relative", "anchor": "receipt", "unit": "days", "nature": "payment"},
        {**POSTED, "amount": 5000, "unit": "years"},
    ],
)
def test_an_unreadable_period_reports_no_arrival_day(spec: dict[str, Any]) -> None:
    """Reviewer repro: without a readable period nothing is computed — no arrival day was assumed, and
    no hint asks for one or for the sender; the only hint is how to fix the period."""
    tools = at("2026-09-26")
    for kind, received in (("bank", None), ("company", "2026-09-03"), (None, None)):
        result = tools.compute_deadline(
            spec, document_date="2026-09-01", sender_kind=kind, received_date=received
        )
        assert result["due_date"] is None and result["confidence"] == "low"
        assert len(result["warnings"]) == 1 and PRIVATE_SENDER_WARNING not in result["warnings"]
        assumed = result["assumed"]
        assert (assumed["received_date"], assumed["received_date_from"]) == (None, None)
        assert assumed["received_date_not_used"] == received
        assert result["hints"] == [
            "Set spec.amount and spec.unit to the period the letter gives (e.g. 1 and months for "
            "'innerhalb eines Monats'), then call again."
        ]


def test_a_private_law_klage_or_widerspruch_keeps_a_private_sender_private() -> None:
    """Reviewer repro: an employer's dismissal names the Kündigungsschutzklage (§ 4 KSchG, labour court).
    Its three weeks run from the letter's arrival (§ 130 BGB) — deemed delivery would make them 3 days
    late, and the loss of that deadline makes the dismissal effective (§ 7 KSchG)."""
    tools = at("2026-09-26")
    spec = {
        **POSTED,
        "amount": 3,
        "unit": "weeks",
        "legal_basis": "§ 4 KSchG",
        "text": "Eine Klage muss innerhalb von drei Wochen nach Zugang der Kündigung erhoben werden.",
    }
    args = {"document_date": "2026-09-01", "sender_kind": "employer", "remedy_type": "klage"}
    dismissal = tools.compute_deadline(spec, **args)
    assert dismissal["due_date"] == "2026-09-22"  # not 25 Sep (the letter + 3 days + 3 weeks)
    assert (
        DECLARATION_ARRIVAL_WARNING in dismissal["warnings"]
        and FORMAL_SERVICE_WARNING not in dismissal["warnings"]
    )
    assert dismissal["steps"][0]["rule_id"] == "private_sender_arrival"
    assert _hint(dismissal, "If the letter is an authority's decision after all (a Bescheid)")
    assert "labour or civil court" in " ".join(dismissal["hints"])
    assert dismissal == tools.compute_deadline(spec, **{**args, "sender_name": "Land Berlin"})
    # an insurer's contract change (§ 5 VVG) is private too
    policy = tools.compute_deadline(
        {
            **spec,
            "legal_basis": "§ 5 VVG",
            "text": "Sie können innerhalb eines Monats nach Zugang widersprechen.",
        },
        **{**args, "sender_kind": "insurer", "remedy_type": "widerspruch"},
    )
    assert PRIVATE_SENDER_WARNING in policy["warnings"]
    # a Klage to the administrative court is an authority's decision (a civil servant's dismissal)
    official = tools.compute_deadline(
        {**spec, "legal_basis": "§ 74 VwGO", "text": "Klage beim Verwaltungsgericht Berlin"}, **args
    )
    assert PRIVATE_SENDER_WARNING not in official["warnings"]
    assert any(step["rule_id"] == "posting_day" for step in official["steps"])


def test_the_delivery_law_is_named_only_when_deemed_delivery_was_applied() -> None:
    """Review round 2 of phase 2: a § 4 KSchG period from a city as employer counts from arrival
    (kschg_4, no posting day), but the result named "general administrative law (§ 41 VwVfG)"."""
    tools = at("2026-09-26")
    spec = {
        **POSTED,
        "amount": 3,
        "unit": "weeks",
        "legal_basis": "§ 4 KSchG",
        "text": "Eine Klage muss innerhalb von drei Wochen nach Zugang der Kündigung erhoben werden.",
    }
    for kind in ("authority", "university"):
        dismissal = tools.compute_deadline(
            spec, document_date="2026-09-01", sender_kind=kind, sender_name="Stadt Musterstadt"
        )
        assert "posting_day" not in {step["rule_id"] for step in dismissal["steps"]}
        assert dismissal["assumed"]["delivery_law"] is None
        # review round 3 of phase 2: a public employer is an authority — a dismissal is no administrative act
        assert DECLARATION_ARRIVAL_WARNING in dismissal["warnings"]
        assert not any("not an authority" in warning for warning in dismissal["warnings"])
        assert dismissal["steps"][0]["label"].startswith("A dismissal takes effect when it arrives, whoever")
    # an authority's Bescheid still names the law its deemed delivery follows
    notice = tools.compute_deadline(
        {**POSTED, "amount": 1, "unit": "months", "text": "Widerspruch innerhalb eines Monats"},
        document_date="2026-09-01",
        sender_kind="authority",
    )
    assert notice["assumed"]["delivery_law"] == "general administrative law (§ 41 VwVfG)"


def test_a_courts_fixed_date_names_no_delivery_law() -> None:
    """Review round 3 of phase 2: every court letter named formal service (§ 180 ZPO) as its delivery law,
    also a fixed date or a period from a date the letter names, where no delivery rule was applied."""
    tools = at("2026-09-28")
    court = {"sender_kind": "authority", "sender_name": "Amtsgericht Köln", "document_date": "2026-09-15"}
    fixed = tools.compute_deadline({"type": "fixed", "date": "2026-10-20", "nature": "objection"}, **court)
    assert "zpo_180" not in {rule["id"] for rule in fixed["rules"]}
    assert fixed["assumed"]["delivery_law"] is None
    named = tools.compute_deadline(
        {**RECEIPT, "anchor": "explicit_date", "anchor_date": "2026-09-20", "delivery_rule": "none"}, **court
    )
    assert "zpo_180" not in {rule["id"] for rule in named["rules"]}
    assert named["assumed"]["delivery_law"] is None


def test_holidays_from_follows_the_rule_applied() -> None:
    """Review round 3 of phase 2: a withdrawal is shifted by the consumer's Land (§ 193 BGB) and a
    Kündigungsschutzklage keeps only a holiday both Länder have, but ``holidays_from`` named the sender's."""
    tools = at("2026-12-28")
    withdrawal = tools.compute_deadline(
        {
            "type": "relative",
            "anchor": "receipt",
            "amount": 14,
            "unit": "days",
            "nature": "declaration",
            "legal_basis": "§ 355 BGB",
            "text": "Widerrufsfrist 14 Tage ab Erhalt der Ware",
        },
        sender_kind="retailer",
        region="NW",
        recipient_region="BY",
        received_date="2026-12-23",
    )
    assert withdrawal["due_date"] == "2027-01-07" and withdrawal["assumed"]["holiday_calendar"] == "Bayern"
    assert withdrawal["assumed"]["holidays_from"].startswith(
        "recipient_region: a withdrawal is declared where"
    )
    dismissal = tools.compute_deadline(
        {
            **RECEIPT,
            "amount": 3,
            "unit": "weeks",
            "legal_basis": "§ 4 KSchG",
            "text": "Klage binnen drei Wochen",
        },
        sender_kind="employer",
        region="NW",
        recipient_region="BY",
        received_date="2026-12-16",
    )
    assert "kschg_4" in {rule["id"] for rule in dismissal["rules"]}
    assert dismissal["assumed"]["holidays_from"].startswith("region and recipient_region: the action may be")


def test_a_stated_posting_day_without_the_letters_date_is_not_trusted_blindly() -> None:
    """Reviewer repro (benchmark letter test-tax_assessment-D1): the engine counts from the letter's date
    when a stated posting day is later. Leaving the letter's date out must not lift that check silently:
    the result says it could not check, asks for the date and is less confident."""
    tools = at("2026-01-12")
    spec = {**POSTED, "anchor_date": "2026-01-02", "legal_basis": "§ 355 AO"}
    args = {"sender_kind": "tax_office", "region": "BY", "recipient_region": "BY"}
    dated = tools.compute_deadline(spec, document_date="2025-12-31", **args)
    assert dated["due_date"] == "2026-02-05" and not _hint(dated, "Pass document_date")
    assert any("later than its date" in w for w in dated["warnings"])
    undated = tools.compute_deadline(spec, **args)
    assert undated["due_date"] == "2026-02-09" and undated["confidence"] == "medium"
    assert undated["hints"][0] == rules_tools.UNCHECKED_DAY_HINT
    assert any("posting day stated (Fri 2 Jan 2026) could not be checked" in w for w in undated["warnings"])
    # a delivery day the letter states is checked against the letter's date too
    served = {**RECEIPT, "anchor_date": "2026-01-05", "delivery_rule": "none"}
    alone = tools.compute_deadline(served)
    assert alone["confidence"] == "medium" and _hint(alone, "Pass document_date: the engine checks")
    assert any("delivery day stated (Mon 5 Jan 2026)" in w for w in alone["warnings"])
    assert tools.compute_deadline(served, document_date="2026-01-02")["confidence"] == "high"
    # an explicit start day is no posting or delivery day: nothing to check
    explicit = {**RECEIPT, "anchor": "explicit_date", "anchor_date": "2026-01-05"}
    assert tools.compute_deadline(explicit)["hints"] == []


def test_warnings_speak_to_the_person_and_hints_to_the_caller() -> None:
    """The engine speaks to the app's person ("tell us", "enter the envelope date"); a model relays the
    tools' warnings, and there is no app to tell. The facts stay, the argument to pass is a hint."""
    tools = at("2026-09-26")
    unknown_arrival = tools.compute_deadline(RECEIPT, document_date="2026-09-14")
    missing = tools.compute_deadline(RECEIPT)
    late = tools.compute_deadline(
        POSTED, document_date="2026-09-01", sender_kind="authority", received_date="2026-09-15"
    )
    fine = {**RECEIPT, "anchor": "document_date", "legal_basis": "§ 67 OWiG", "nature": "objection"}
    fined = tools.compute_deadline(fine, document_date="2026-09-14", sender_kind="authority")
    results = (unknown_arrival, missing, late, fined)
    for result in results:
        text = " ".join(result["warnings"])
        assert "tell us" not in text and "told us" not in text and "enter the" not in text, text
        assert "spec." not in text and "pass " not in text.lower(), text
    assert rules_tools.TOOL_VOICE["assumed_receipt"] in unknown_arrival["warnings"]
    assert _hint(unknown_arrival, "Pass received_date")
    assert rules_tools.TOOL_VOICE["needs_arrival"] in missing["warnings"]
    assert _hint(missing, "Pass document_date") and _hint(missing, "Pass received_date")
    assert any(w.startswith("The letter arrived on Tue 15 Sep 2026, after the day") for w in late["warnings"])
    assert any("the envelope's date gives the exact deadline" in w for w in fined["warnings"])
    # the app keeps its own words
    assert rules_tools.tool_voice("Something else — tell us.") == "Something else — tell us."


def test_the_hints_follow_the_engines_own_words_for_each_situation() -> None:
    """The hints recognise a situation by words the engine shares (ordnung.rules.deadlines): each one is
    in the engine's warning, so rewording it there cannot drop the hint silently."""
    region_later = at("2026-05-01").compute_deadline(
        {**RECEIPT, "anchor": "document_date", "amount": 3, "unit": "business_days"},
        document_date="2026-06-01",
    )
    assert any(w.startswith(REGION_UNKNOWN) and REGION_EARLIER not in w for w in region_later["warnings"])
    assert _hint(region_later, "Pass region") and region_later["hints"][-1].endswith("this date later.")
    region_earlier = at("2025-10-01").compute_deadline(
        {
            **RECEIPT,
            "anchor": "explicit_date",
            "anchor_date": "2025-11-05",
            "amount": -5,
            "unit": "business_days",
        }
    )
    assert any(REGION_EARLIER in w for w in region_earlier["warnings"])
    assert region_earlier["hints"][-1].endswith("this date earlier.")
    tax = {"document_date": "2026-01-02", "sender_kind": "tax_office"}
    office = at("2026-01-05").compute_deadline(POSTED, region="BY", **tax)
    assert any(TAX_OFFICE_HOLIDAY in w for w in office["warnings"]) and _hint(office, "Pass recipient_region")
    home = at("2026-01-05").compute_deadline(POSTED, recipient_region="BY", **tax)
    assert any(HOME_HOLIDAY in w for w in home["warnings"]) and _hint(
        home, "Pass region — the tax office's Land"
    )


def test_a_date_at_the_end_of_the_calendar_is_answered_not_crashed() -> None:
    """Reviewer repro: the partial-holiday check counted a day back from 1 Jan 1 (OverflowError)."""
    for region in ("BY", "SN", "TH", None):
        result = at("2026-09-26").compute_deadline(
            {"type": "fixed", "date": "0001-01-01", "nature": "notice"}, region=region
        )
        assert result["due_date"] == "0001-01-01", region
    backward = at("2026-09-26").compute_deadline(
        {**RECEIPT, "anchor": "explicit_date", "anchor_date": "9999-12-31", "amount": -3, "unit": "werktage"},
        region="BY",
    )
    assert backward["due_date"] == "9999-12-27"


def test_the_region_hint_names_the_argument_the_engine_reads() -> None:
    """A payment to a company is made where the payer lives (§ 270 BGB): region does not decide it."""
    tools = at("2027-10-20")
    spec = {"type": "relative", "anchor": "document_date", "amount": 14, "unit": "days", "nature": "payment"}
    args = {"document_date": "2027-10-18", "sender_kind": "company"}
    payer = tools.compute_deadline(spec, region="HH", **args)
    assert payer["due_date"] == "2027-11-01" and payer["confidence"] == "medium"  # All Saints' Day elsewhere
    assert _hint(payer, "Pass recipient_region — the Land where the payer lives") and not _hint(
        payer, "Pass region"
    )
    assert payer["assumed"]["holidays_from"].startswith("recipient_region: a payment to a company or person")
    home = tools.compute_deadline(spec, region="HH", recipient_region="NW", **args)
    assert home["due_date"] == "2027-11-02" and home["hints"] == []
    # an objection to an office: its seat decides
    office = tools.compute_deadline(
        {**spec, "nature": "objection"},
        sender_kind="authority",
        **{k: v for k, v in args.items() if k != "sender_kind"},
    )
    assert _hint(office, "Pass region — the Land of the office or company") and "recipient_region" not in (
        " ".join(office["hints"])
    )
    # a tax letter delivered on a regional holiday (Epiphany, Tue 6 Jan 2026) depends on both places
    tax = at("2026-01-05").compute_deadline(POSTED, document_date="2026-01-02", sender_kind="tax_office")
    assert _hint(
        tax, "Pass region — the Land of the office or company where the deadline is met, and recipient_region"
    )


def test_a_partial_holiday_before_the_deadline_is_flagged() -> None:
    """15 Aug is a holiday in most of Bavaria (Munich too) but not in all of it: a send-by date counted
    back over it comes out a day late. The warning names that holiday and where it holds only."""
    tools = at("2025-08-01")
    spec = {"type": "fixed", "date": "2025-08-18", "nature": "payment"}
    bavaria = tools.compute_deadline(spec, sender_kind="company", region="BY", recipient_region="BY")
    assert (bavaria["due_date"], bavaria["send_by"]) == ("2025-08-18", "2025-08-15")
    assert [w for w in bavaria["warnings"] if "Mariä Himmelfahrt" in w] == [
        "Fri 15 Aug 2025 is Mariä Himmelfahrt, a public holiday only in the communities of Bayern with more "
        "Catholic than Protestant residents (as the Landesamt für Statistik lists them; Munich among them), "
        "which is not counted here. Where it holds, the send-by or safe date, counted back over it, is a "
        "working day earlier: act a working day before it to be safe."
    ]
    assert not any("Augsburg" in w for w in bavaria["warnings"])
    hamburg = tools.compute_deadline(spec, sender_kind="company", recipient_region="HH")
    assert not any("Mariä Himmelfahrt" in w for w in hamburg["warnings"])
    # Augsburg's own holiday, and Corpus Christi in parts of Saxony
    augsburg = tools.compute_deadline(
        {**spec, "date": "2025-08-11"}, sender_kind="company", recipient_region="BY"
    )
    assert [w for w in augsburg["warnings"] if "Friedensfest" in w] == [
        "Fri 8 Aug 2025 is Augsburger Hohes Friedensfest, a public holiday only in the city of Augsburg (Bayern), "
        "which is not counted here. Where it holds, the send-by or safe date, counted back over it, is a working "
        "day earlier: act a working day before it to be safe."
    ]
    saxony = at("2026-05-01").compute_deadline(
        {"type": "fixed", "date": "2026-06-04", "nature": "objection", "shift_rule": "next_business_day"},
        region="SN",
    )
    assert [w for w in saxony["warnings"] if "Fronleichnam" in w] == [
        "Thu 4 Jun 2026 is Fronleichnam, a public holiday only in some communities of the Sorbian area of "
        "Sachsen, which is not counted here. Where it holds, the due date moves to the next working day; the "
        "date shown is the earlier one."
    ]


def test_a_partial_holiday_between_the_due_date_and_a_later_event_is_flagged() -> None:
    """Counting 5 working days back from Wed 20 Aug 2025 passes Mariä Himmelfahrt (Fri 15 Aug): where it
    holds, the date is Mon 11 Aug, not Tue 12 Aug — the warning must say "earlier", not "later"."""
    spec = {
        "type": "relative",
        "amount": -5,
        "unit": "business_days",
        "anchor": "explicit_date",
        "anchor_date": "2025-08-20",
        "nature": "declaration",
    }
    result = at("2025-07-01").compute_deadline(spec, region="BY")
    assert result["due_date"] == "2025-08-12"
    assert [w for w in result["warnings"] if "Mariä Himmelfahrt" in w] == [
        "Fri 15 Aug 2025 is Mariä Himmelfahrt, a public holiday only in the communities of Bayern with more "
        "Catholic than Protestant residents (as the Landesamt für Statistik lists them; Munich among them), "
        "which is not counted here. Where it holds, this date, counted backwards over it, is a working day "
        "earlier: act a working day before it to be safe."
    ]
    assert not any("later" in w for w in result["warnings"])
    # a notice deadline on the holiday itself does not move: its safe date is a working day earlier there
    notice = at("2025-07-01").compute_deadline(
        {"type": "fixed", "date": "2025-08-15", "nature": "notice"}, region="BY", sender_kind="company"
    )
    assert any(
        w.startswith("Fri 15 Aug 2025 is Mariä Himmelfahrt")
        and "this deadline does not move off it, so the safe date is a working day earlier" in w
        for w in notice["warnings"]
    )
    # a date that neither moves nor has a safe date is not moved by it
    other = at("2025-07-01").compute_deadline(
        {"type": "fixed", "date": "2025-08-15", "nature": "other"}, region="BY"
    )
    assert not any("Mariä Himmelfahrt" in w for w in other["warnings"])
    # a partial holiday on a weekend moves nothing
    assert calendar_de.partial_holidays("BY", date(2026, 8, 10), date(2026, 8, 20)) == []  # Sat 15 Aug
    assert calendar_de.partial_holidays("NW", date(2026, 1, 1), date(2026, 12, 31)) == []


def test_a_backward_count_without_a_region_says_it_may_be_a_day_late() -> None:
    """5 business days before Wed 5 Nov 2025: Tue 28 Oct nationwide, Mon 27 Oct where Fri 31 Oct is
    Reformationstag (9 Länder). No region must not mean a late date with high confidence and no word."""
    spec = {
        "type": "relative",
        "amount": -5,
        "unit": "business_days",
        "anchor": "explicit_date",
        "anchor_date": "2025-11-05",
        "nature": "declaration",
    }
    tools = at("2025-10-01")
    unknown = tools.compute_deadline(spec, sender_kind="authority")
    assert unknown["due_date"] == "2025-10-28" and unknown["confidence"] == "medium"
    assert any("where the deadline would be earlier" in w for w in unknown["warnings"])
    assert unknown["hints"] == [
        "Pass region — the Land of the office or company where the deadline is met. A regional holiday may make "
        "this date earlier."
    ]
    lower_saxony = tools.compute_deadline(spec, sender_kind="authority", region="NI")
    assert lower_saxony["due_date"] == "2025-10-27" and lower_saxony["hints"] == []

    back = tools.add_working_days("2025-11-03", -1)
    assert back["date"] == "2025-10-31"
    assert back["note"] == (
        "Nationwide holidays only: Fri 31 Oct 2025, counted here as a working day, is a public holiday in some "
        "Länder (e.g. Brandenburg, Bremen, Hamburg) — the result is a working day earlier there, so this date "
        "may be a day late. Pass region for a Land's own holidays."
    )
    forward = tools.add_working_days("2025-10-30", 1)
    assert forward["date"] == "2025-10-31" and "a working day later there" in forward["note"]
    assert "note" not in compact(tools.add_working_days("2025-10-20", -3))  # no regional holiday counted
    assert tools.add_working_days("2025-11-03", -1, region="NI")["date"] == "2025-10-30"


def test_assumed_names_an_arrival_day_only_when_the_period_ran_from_it() -> None:
    """An invoice counted from its date or a tax letter's deemed delivery does not run from the arrival
    day given: ``assumed`` must not say it did."""
    tools = at("2026-09-25")
    invoice = {
        "type": "relative",
        "anchor": "document_date",
        "amount": 14,
        "unit": "days",
        "nature": "payment",
    }
    dated = tools.compute_deadline(
        invoice, document_date="2026-09-01", received_date="2026-09-20", sender_kind="company"
    )
    assert dated["due_date"] == "2026-09-15"
    assert (dated["assumed"]["received_date"], dated["assumed"]["received_date_from"]) == (None, None)
    assert dated["assumed"]["received_date_not_used"] == "2026-09-20"
    deemed = tools.compute_deadline(
        TAX_SPEC, document_date="2026-09-01", received_date="2026-09-03", sender_kind="tax_office"
    )
    assert deemed["due_date"] == "2026-10-07"  # from the deemed day, Mon 7 Sep (Sat 5 Sep moved)
    assert deemed["assumed"]["received_date"] is None and deemed["assumed"]["received_date_not_used"] == (
        "2026-09-03"
    )
    # arrived before the letter's date: the engine counts from that day, and assumed says so
    early = tools.compute_deadline(
        TAX_SPEC, document_date="2026-09-10", received_date="2026-09-08", sender_kind="tax_office"
    )
    assert early["due_date"] == "2026-10-08"
    assert early["assumed"]["received_date"] == "2026-09-08"
    assert early["assumed"]["received_date_from"].startswith(
        "received_date: it arrived before the letter's date"
    )
    assert early["assumed"]["received_date_not_used"] is None
    arrival = tools.compute_deadline(RECEIPT, document_date="2026-09-01", received_date="2026-09-03")
    assert (arrival["assumed"]["received_date"], arrival["assumed"]["received_date_from"]) == (
        "2026-09-03",
        "received_date",
    )


def test_formal_service_is_explained_and_flagged_where_deemed_delivery_ran() -> None:
    """A yellow envelope has no 4-day rule: the help says how to pass its date, and a deemed-delivery
    result for a posted letter says the real date may be earlier (the reviewer's repro: 6 Jul vs 3 Jul)."""
    compute = next(d for d in tool_definitions() if d["name"] == "compute_deadline")
    help_text = compute["input_schema"]["properties"]["spec"]["description"]
    assert "yellow envelope (Postzustellungsurkunde)" in help_text and "use anchor receipt" in help_text
    assert "Anhörungsbogen" in help_text
    tools = at("2026-06-10")
    args = {"document_date": "2026-06-02", "sender_kind": "immigration_office", "region": "NW"}
    deemed = tools.compute_deadline(POSTED, **args)
    assert deemed["due_date"] == "2026-07-06" and FORMAL_SERVICE_WARNING in deemed["warnings"]
    assert deemed["confidence"] == "high"  # most letters come by ordinary post: a note, not a doubt
    served = tools.compute_deadline(
        {**RECEIPT, "amount": 1, "unit": "months", "anchor_date": "2026-06-03"}, **args
    )
    assert served["due_date"] == "2026-07-03" and FORMAL_SERVICE_WARNING not in served["warnings"]
    online = tools.compute_deadline({**POSTED, "delivery_rule": "de_admin_electronic"}, **args)
    assert FORMAL_SERVICE_WARNING not in online["warnings"]


def test_a_callers_today_far_from_the_servers_is_flagged(tools: RulesTools) -> None:
    """A model's own idea of the date can be stale: a wrong today must never make a live deadline look
    missed. The result stays for the server's today; the caller's day only gets its own small block."""
    spec = {"type": "fixed", "date": "2026-10-15", "nature": "objection"}
    stale = tools.compute_deadline(spec, today="2026-11-02")
    assert stale["send_by"] == "2026-10-09" and not any("has already passed" in w for w in stale["warnings"])
    assert stale["warnings"] == [
        "The today given (Mon 2 Nov 2026) is 43 days after this server's today (Sun 20 Sep 2026). The result is "
        "for the server's today — whether the deadline has passed and the send-by date included; for_today_given "
        "shows them for the day given. Leave today out unless you mean another day."
    ]
    assert stale["for_today_given"] == {
        "today": "2026-11-02",
        "due_date": None,
        "send_by": None,
        "passed": True,
    }
    assert (stale["assumed"]["today"], stale["assumed"]["today_given"]) == ("2026-09-20", "2026-11-02")
    earlier = tools.compute_deadline(spec, today="2026-09-01")["for_today_given"]
    assert earlier == {"today": "2026-09-01", "due_date": None, "send_by": "2026-10-09", "passed": False}
    a_zone_apart = tools.compute_deadline(spec, today="2026-09-19")
    assert a_zone_apart["assumed"]["today"] == "2026-09-20"
    assert a_zone_apart["for_today_given"] == {
        "today": "2026-09-19",
        "due_date": None,
        "send_by": "2026-10-09",
        "passed": False,
    }
    assert a_zone_apart["warnings"] == [
        "The today given (Sat 19 Sep 2026) is 1 day before this server's today (Sun 20 Sep 2026). The result is "
        "for the server's today — whether the deadline has passed and the send-by date included; for_today_given "
        "shows them for the day given. Leave today out unless you mean another day."
    ]
    same = compact(tools.compute_deadline(spec, today="2026-09-20"))
    assert "today_given" not in same["assumed"] and "for_today_given" not in same


def test_a_callers_today_a_day_ahead_never_makes_a_live_deadline_look_missed() -> None:
    """Review round 2 of phase 2: a caller's today one day after the server's German day was used, so a
    deadline that runs to midnight German time read as "has already passed"."""
    server = at("2026-09-28")
    spec = {"type": "fixed", "date": "2026-09-28", "nature": "objection"}
    ahead = server.compute_deadline(spec, today="2026-09-29")
    same = server.compute_deadline(spec)
    assert not any("has already passed" in warning for warning in ahead["warnings"])
    assert ahead["send_by"] == same["send_by"] and ahead["due_date"] == same["due_date"]
    # the caller's day only gets its own view, next to a warning that the result is for the server's day
    assert ahead["for_today_given"]["today"] == "2026-09-29"
    assert any("1 day after this server's today" in warning for warning in ahead["warnings"])
    assert (ahead["assumed"]["today"], ahead["assumed"]["today_given"]) == ("2026-09-28", "2026-09-29")
    # an arrival day on the caller's day a time zone ahead is still accepted
    received = {"type": "relative", "anchor": "receipt", "amount": 2, "unit": "weeks", "nature": "objection"}
    assert server.compute_deadline(received, received_date="2026-09-29", today="2026-09-29")["due_date"]


def test_a_callers_today_a_day_behind_never_makes_an_expired_deadline_look_live() -> None:
    """Review round 3 of phase 2: a caller's today one day before the server's German day (a stale
    conversation date, a UTC machine shortly after German midnight) replaced it, so a deadline that ended
    yesterday read "send it today" with no warning that it had passed."""
    server = at("2026-09-27")
    spec = {"type": "fixed", "date": "2026-09-26", "nature": "objection"}
    behind = server.compute_deadline(spec, today="2026-09-26", sender_kind="company")
    alone = server.compute_deadline(spec, sender_kind="company")
    assert any("has already passed" in warning for warning in behind["warnings"])
    assert behind["send_by"] == alone["send_by"] and behind["due_date"] == alone["due_date"]
    assert not any("send it today" in warning for warning in behind["warnings"])
    assert behind["assumed"]["today"] == "2026-09-27" and behind["assumed"]["today_given"] == "2026-09-26"
    assert behind["for_today_given"]["passed"] is False  # only the caller's day's view says otherwise
    assert any("1 day before this server's today" in warning for warning in behind["warnings"])
    tax = {
        "type": "relative",
        "anchor": "deemed_delivery",
        "amount": 1,
        "unit": "months",
        "nature": "objection",
        "delivery_rule": "de_admin_post",
        "legal_basis": "§ 355 AO",
    }
    objection = server.compute_deadline(
        tax, document_date="2026-08-22", sender_kind="tax_office", region="NW", today="2026-09-26"
    )
    assert objection["send_by"] is None or objection["send_by"] >= "2026-09-27"


def test_a_pinned_server_does_not_use_a_callers_today() -> None:
    pinned = RulesTools(today=lambda: date(2026, 4, 14), pin_today=True)
    spec = {"type": "fixed", "date": "2026-05-15", "nature": "objection"}
    result = pinned.compute_deadline(spec, today="2026-09-26")
    assert result["send_by"] == "2026-05-08" and not any("already passed" in w for w in result["warnings"])
    assert result["warnings"] == [
        "The today given (Sat 26 Sep 2026) was not used: this server counts from Tue 14 Apr 2026, the day it "
        "is set to."
    ]
    assert (result["assumed"]["today"], result["assumed"]["today_given"]) == ("2026-04-14", "2026-09-26")
    with pytest.raises(RulesToolError, match="is after today"):  # arrival days are checked against it too
        pinned.compute_deadline(RECEIPT, received_date="2026-09-01", today="2026-09-26")


def test_today_defaults_to_the_day_in_germany(monkeypatch: pytest.MonkeyPatch) -> None:
    """At 01:30 in Berlin a UTC machine still says yesterday; the tools count from the German day."""

    class LateEvening(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
            return datetime(2026, 9, 25, 23, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.delenv("ORDNUNG_TODAY", raising=False)
    clock.set_today(None)
    monkeypatch.setattr(rules_tools, "datetime", LateEvening)
    assert RulesTools().current_day() == date(2026, 9, 26)
    monkeypatch.setenv("ORDNUNG_TODAY", "2026-01-02")  # a pinned day still wins
    assert RulesTools().current_day() == date(2026, 1, 2)


def test_today_defaults_to_the_servers_day_and_can_be_given(tools: RulesTools) -> None:
    spec = {"type": "relative", "anchor": "today", "amount": 10, "unit": "days", "nature": "payment"}
    assert tools.compute_deadline(spec)["due_date"] == "2026-09-30"
    other_day = tools.compute_deadline(spec, today="2026-10-01")
    assert other_day["due_date"] == "2026-09-30"
    assert other_day["for_today_given"]["due_date"] == "2026-10-12"  # the 11th is a Sunday
    # a time zone behind or ahead: always the server's day (review rounds 2 and 3 of phase 2)
    behind = tools.compute_deadline(spec, today="2026-09-19")
    assert behind["due_date"] == "2026-09-30" and behind["for_today_given"]["due_date"] == "2026-09-29"
    assert tools.compute_deadline(spec, today="2026-09-21")["due_date"] == "2026-09-30"


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"type": "relative", "amout": 1}, "spec.amout: unknown field (a DateSpec has: type, date,"),
        ({"type": "relative", "unit": "month"}, "spec.unit: Input should be 'days'"),
        ({"type": "soon"}, "spec.type: Input should be 'fixed', 'relative' or 'none'"),
        ({"amount": 1}, "spec.type: Field required"),
        ("in a month", "spec must be an object"),
        # a date the engine could not read would silently count from the letter's date instead
        (
            {"type": "relative", "anchor": "deemed_delivery", "anchor_date": "02.01.2026"},
            "spec.anchor_date: must be a date written YYYY-MM-DD, or null (got '02.01.2026')",
        ),
        ({"type": "fixed", "date": "2026-02-30"}, "spec.date: must be a date written YYYY-MM-DD"),
        ({"type": "fixed", "date": "20260131"}, "spec.date: must be a date written YYYY-MM-DD"),
        (
            {"type": "fixed", "date": 20260131},
            "spec.date: must be a date written YYYY-MM-DD, or null (got int)",
        ),
        (
            {"type": "relative", "anchor": "document_date", "amount": True, "unit": "months"},
            "spec.amount: must be a whole number (got true)",
        ),
    ],
)
def test_invalid_specs_are_refused_with_readable_errors(tools: RulesTools, spec: Any, message: str) -> None:
    with pytest.raises(RulesToolError, match="spec") as raised:
        tools.compute_deadline(spec)
    assert message in str(raised.value)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"document_date": "15.09.2026"}, "document_date must be a date written YYYY-MM-DD"),
        # other ISO forms Python would read are refused as well: they are not what the argument says
        ({"document_date": "20260901"}, "document_date must be a date written YYYY-MM-DD (got '20260901')"),
        ({"document_date": "2026-W36-1"}, "document_date must be a date written YYYY-MM-DD"),
        ({"received_date": "2026-09-01T10:00"}, "received_date must be a date written YYYY-MM-DD"),
        ({"received_date": "yesterday"}, "received_date must be a date"),
        ({"today": "2026-02-30"}, "today must be a date"),
        ({"region": "Narnia"}, "region must be a German Land: one of BB, BE, BW"),
        ({"recipient_region": "Texas"}, "recipient_region must be a German Land"),
        ({"sender_kind": "bank robber"}, "sender_kind must be one of: authority, tax_office"),
        ({"remedy_type": "appeal"}, "remedy_type must be one of: einspruch, widerspruch"),
    ],
)
def test_invalid_arguments_are_refused(tools: RulesTools, arguments: dict[str, Any], message: str) -> None:
    with pytest.raises(RulesToolError) as raised:
        tools.compute_deadline(TAX_SPEC, **arguments)
    assert message in str(raised.value)


def test_blank_spec_dates_mean_none(tools: RulesTools) -> None:
    spec = {**TAX_SPEC, "anchor_date": " ", "date": ""}
    assert tools.compute_deadline(spec, document_date="2026-09-15", sender_kind="tax_office")["due_date"] == (
        "2026-10-21"
    )


def test_regions_accept_codes_and_names(tools: RulesTools) -> None:
    for name in ("NW", "nw", "DE-NW", "Nordrhein-Westfalen", "NRW", "  "):
        tools.compute_deadline(TAX_SPEC, document_date="2026-09-15", region=name)
    with pytest.raises(RulesToolError, match="region must be a German Land code"):
        tools.compute_deadline(TAX_SPEC, region=5)  # type: ignore[arg-type]


def test_an_out_of_range_date_is_a_receipt_not_a_crash(tools: RulesTools) -> None:
    result = tools.compute_deadline(
        {"type": "relative", "amount": 100, "unit": "years"}, document_date="9999-01-01"
    )
    assert result["due_date"] is None and "out of range" in result["summary"]


# --------------------------------------------------------------------------------------------------
# german_holidays, add_working_days, check_iban
# --------------------------------------------------------------------------------------------------


def test_nationwide_holidays_and_a_lands_own(tools: RulesTools) -> None:
    nationwide = tools.german_holidays(2026)
    assert [row["name"] for row in nationwide["holidays"]] == [
        "Neujahr",
        "Karfreitag",
        "Ostermontag",
        "Erster Mai",
        "Christi Himmelfahrt",
        "Pfingstmontag",
        "Tag der Deutschen Einheit",
        "Erster Weihnachtstag",
        "Zweiter Weihnachtstag",
    ]
    assert all(row["nationwide"] for row in nationwide["holidays"])
    assert (
        nationwide["calendar"] == "Germany (nationwide holidays only)" and "pass region" in nationwide["note"]
    )
    bavaria = tools.german_holidays(2026, "BY")
    own = {row["date"]: row for row in bavaria["holidays"] if not row["nationwide"]}
    assert own["2026-01-06"]["name"] == "Heilige Drei Könige" and own["2026-01-06"]["weekday"] == "Tuesday"
    assert "Left out because they hold only in parts of it: Assumption Day" in bavaria["note"]
    # leaving a holiday out makes a date counted forward earlier, but one counted backwards later
    assert (
        "counted backwards (a send-by date, negative working days) can come out a day late" in bavaria["note"]
    )
    assert "note" not in compact(tools.german_holidays(2026, "NW"))  # no partial holidays to explain
    assert bavaria["disclaimer"].startswith("Information, not legal advice: the public holidays")
    assert (
        LAST_CHECKED in bavaria["disclaimer"]
        and "Check the result against the letter" not in bavaria["disclaimer"]
    )


@pytest.mark.parametrize("year", [1990, 2101, True, "2026"])
def test_holiday_years_are_bounded(tools: RulesTools, year: Any) -> None:
    with pytest.raises(RulesToolError, match="year must be a whole number from 1991 to 2100"):
        tools.german_holidays(year)


def test_working_days_skip_weekends_and_holidays(tools: RulesTools) -> None:
    result = tools.add_working_days("2026-12-22", 5, region="NW")
    assert (result["date"], result["weekday"]) == ("2026-12-30", "Wednesday")
    assert [(row["date"], row["reason"]) for row in result["skipped"]] == [
        ("2026-12-25", "Erster Weihnachtstag"),
        ("2026-12-26", "Zweiter Weihnachtstag"),
        ("2026-12-27", "Sunday"),
    ]
    assert "start day itself is not counted" in result["counting"]
    werktage = tools.add_working_days("2026-09-25", 2, "werktage")  # Fri → Sat counts, Sun does not
    assert werktage["date"] == "2026-09-28" and [row["reason"] for row in werktage["skipped"]] == ["Sunday"]
    back = tools.add_working_days("2026-09-28", -1)
    assert back["date"] == "2026-09-25" and [row["weekday"] for row in back["skipped"]] == [
        "Sunday",
        "Saturday",
    ]
    assert tools.add_working_days("2026-09-27", 0)["date"] == "2026-09-27"
    assert "note" not in compact(result)  # NW has no partial holidays
    assert "can come out a day late" in tools.add_working_days("2026-08-20", -5, region="BY")["note"]
    long = tools.add_working_days("2026-01-01", 200)
    assert len(long["skipped"]) == rules_tools.MAX_LISTED_SKIPS and long["skipped_more"] > 0
    # a count on the calendar, not a deadline computed from a letter's facts: its own disclaimer
    assert result["disclaimer"] == rules_tools.calendar_disclaimer() and LAST_CHECKED in result["disclaimer"]
    assert "from the facts given" not in result["disclaimer"] and "not legal advice" in result["disclaimer"]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"start": "tomorrow", "days": 1}, "start must be a date"),
        ({"start": "2026-01-01", "days": 1001}, "days must be a whole number from -1000 to 1000"),
        ({"start": "2026-01-01", "days": 1.5}, "days must be a whole number"),
        ({"start": "2026-01-01", "days": 1, "day_type": "arbeitstage"}, "day_type must be one of"),
        ({"start": "9999-12-30", "days": 5}, "outside the calendar"),
    ],
)
def test_invalid_working_day_arguments(tools: RulesTools, arguments: dict[str, Any], message: str) -> None:
    with pytest.raises(RulesToolError, match=message):
        tools.add_working_days(**arguments)


def test_check_iban(tools: RulesTools) -> None:
    good = tools.check_iban("de89 3704 0044 0532 0130 00")
    assert good["iban"] == "DE89 3704 0044 0532 0130 00" and good["valid"] is True
    assert good["country"] == {"code": "DE", "name": "Germany"} and good["account_number"] == "0532013000"
    assert good["bank_code"] == {"label": "Bankleitzahl (BLZ)", "value": "37040044"}
    assert (
        "says nothing about who owns the account" in good["note"] and "Empfängerüberprüfung" in good["note"]
    )
    # a checksum is no deadline: its disclaimer says what the check can and cannot tell
    assert (
        good["disclaimer"] == rules_tools.IBAN_DISCLAIMER
        and "not legal or financial advice" in good["disclaimer"]
    )
    assert (
        "rules engine" not in good["disclaimer"]
        and "Check the result against the letter" not in good["disclaimer"]
    )
    bad = compact(tools.check_iban("DE89 3704 0044 0532 0130 01"))
    assert bad["valid"] is False and bad["checksum_ok"] is False and "bank_code" not in bad
    assert bad["problems"] == ["The check digits do not match: a character is wrong, missing or swapped."]
    # the app's advice for an invalid IBAN, not the note on who owns a valid one
    assert bad["note"] == INVALID_IBAN_ADVICE and "ask the sender before paying" in bad["note"]
    assert INVALID_IBAN_ADVICE in invalid_iban_message("DE89 3704 0044 0532 0130 01")
    assert "if a letter or e-mail says the account has changed" in good["note"]
    foreign = tools.check_iban("BR15 0000 0000 0000 1093 2840 814P 2")
    assert foreign["valid"] is True and foreign["country"] == {"code": "BR", "name": "Brazil"}
    assert good["note"] == rules_tools.IBAN_NOTE and tools.check_iban("FR14 2004 1010 0505 0001 3M02 606")[
        "note"
    ] == (rules_tools.IBAN_NOTE)
    # the check may come back "not possible": that is no all-clear either
    assert "or says the check was not possible, do not pay" in good["note"]


@pytest.mark.parametrize(
    ("iban", "country", "since"),
    [
        ("SE45 5000 0000 0583 9825 7466", "Sweden", "9 July 2027"),
        ("PL61 1090 1014 0000 0712 1981 2874", "Poland", "9 July 2027"),
        ("BG80 BNBG 9661 1020 3456 78", "Bulgaria", "1 January 2027"),
    ],
)
def test_check_iban_says_when_a_non_euro_banks_name_check_starts(
    tools: RulesTools, iban: str, country: str, since: str
) -> None:
    """Reviewer repro: banks outside the euro area have to answer the payee-name check only from
    9 July 2027 (Art. 5c(9) Reg. (EU) No 260/2012 as amended by 2024/886), Bulgaria's, in the euro since
    1 January 2026, a year later (Art. 16(9)). Until then the note must not promise the check."""
    from ordnung.money.iban import PAYEE_CHECK_FROM

    result = tools.check_iban(iban)
    assert result["valid"] is True and result["country"]["name"] == country
    assert "the bank also checks" not in result["note"]
    assert (
        f"This IBAN is from {country}, whose banks have to answer the check of the payee's name before a "
        f"euro transfer (Empfängerüberprüfung) only from {since}: until then your bank may say the check was "
        "not possible"
    ) in result["note"]
    # from that day the check is the law there too
    on_the_day = RulesTools(today=lambda: PAYEE_CHECK_FROM[iban[:2]]).check_iban(iban)
    assert on_the_day["note"] == rules_tools.IBAN_NOTE
    assert len(PAYEE_CHECK_FROM) == 27 and {"CZ", "DK", "HU", "RO"} <= PAYEE_CHECK_FROM.keys()  # the EU


@pytest.mark.parametrize(
    ("iban", "country"),
    [
        ("GB82 WEST 1234 5698 7654 32", "United Kingdom"),
        ("AE07 0331 2345 6789 0123 456", "United Arab Emirates"),
        ("CH93 0076 2011 6238 5295 7", "Switzerland"),
        ("NO93 8601 1117 947", "Norway"),
        ("BR15 0000 0000 0000 1093 2840 814P 2", "Brazil"),
    ],
)
def test_check_iban_promises_no_name_check_outside_the_eu(tools: RulesTools, iban: str, country: str) -> None:
    """Reviewer repro: the payee-name check (Empfängerüberprüfung) is EU law for EU accounts. For a UK or
    UAE account — where scams often route money — the note must not suggest the bank will warn."""
    result = tools.check_iban(iban)
    assert result["valid"] is True and result["country"]["name"] == country
    assert "the bank also checks" not in result["note"]
    assert f"This IBAN is from a country outside the EU ({country})" in result["note"]
    assert "may not happen" in result["note"] and "says nothing about who owns the account" in result["note"]
    assert "your bank may say it was not possible" in result["note"]
    # two letters that are no IBAN country are not "well-formed", however the checksum adds up
    for made_up in ("ZZ22 3704 0044 0532 0130 00", "US88 3704 0044 0532 0130 00"):
        result = compact(tools.check_iban(made_up))
        assert result["valid"] is False and "country" not in result
        assert result["problems"] == [
            f"{made_up[:2]} is not a country that issues IBANs, so this is not an IBAN."
        ]
    # what German letters print, and what copying from a PDF leaves behind
    labelled = tools.check_iban("IBAN: DE89 3704 0044 0532 0130 00\u200b")
    assert labelled["valid"] is True and labelled["country"] == {"code": "DE", "name": "Germany"}
    for value, message in (("", "iban must be the IBAN as printed"), ("D" * 65, "iban is too long")):
        with pytest.raises(RulesToolError, match=message):
            tools.check_iban(value)


def test_render_is_compact_but_keeps_a_missing_due_date() -> None:
    text = render({"due_date": None, "send_by": None, "warnings": [], "steps": [{"a": None}], "x": ""})
    assert text == '{"due_date":null,"warnings":[],"steps":[{}]}'


# --------------------------------------------------------------------------------------------------
# the servers
# --------------------------------------------------------------------------------------------------


async def test_the_rules_only_server_lists_exactly_the_rules_tools() -> None:
    listed = await build_rules_server().list_tools()
    assert {tool.name for tool in listed} == RULES_TOOLS
    assert not {tool.name for tool in listed} & LEDGER_TOOLS  # nothing about the person
    for tool in listed:
        assert tool.description and "\n" not in tool.description
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False and tool.annotations.open_world_hint is False
    schemas = {tool.name: tool.input_schema for tool in listed}
    spec = schemas["compute_deadline"]["properties"]["spec"]
    assert spec["additionalProperties"] is False and spec["required"] == ["type"]
    assert spec["properties"]["unit"]["anyOf"][0]["enum"] == [
        "days",
        "weeks",
        "months",
        "years",
        "business_days",
        "werktage",
    ]
    assert "What the letter SAYS" in spec["description"]
    assert schemas["compute_deadline"]["required"] == ["spec"]
    assert all(schema["additionalProperties"] is False for schema in schemas.values())
    assert "tax_office" in json.dumps(schemas["compute_deadline"]["properties"]["sender_kind"])
    assert schemas["german_holidays"]["properties"]["year"]["minimum"] == 1991
    definitions = {d["name"]: d for d in tool_definitions()}
    assert {name: d["input_schema"] for name, d in definitions.items()} == schemas


async def test_tools_answer_through_an_mcp_client() -> None:
    async with Client(build_rules_server(today=lambda: READ_TODAY)) as client:
        result = await client.call_tool(
            "compute_deadline", {"spec": TAX_SPEC, "document_date": "2026-09-15", "sender_kind": "tax_office"}
        )
        assert result.is_error is False
        text = result.content[0].text
        assert not text.startswith("<untrusted_document>")  # computed by code, no letter text
        assert _json(text)["due_date"] == "2026-10-21"

        as_string = await client.call_tool("compute_deadline", {"spec": json.dumps(TAX_SPEC)})
        assert as_string.is_error is False  # clients that send nested objects as JSON strings

        refused = await client.call_tool("compute_deadline", {"spec": {"type": "relative", "amout": 1}})
        assert refused.is_error is True
        assert "invalid spec — spec.amout: unknown field" in refused.content[0].text

        bounded = await client.call_tool("german_holidays", {"year": 1800})
        assert bounded.is_error is True and "greater than or equal to 1991" in bounded.content[0].text

        # a misspelt argument must not vanish and change the date
        misspelt = await client.call_tool(
            "compute_deadline", {"spec": TAX_SPEC, "letter_date": "2026-09-15", "recieved_date": "2026-09-17"}
        )
        assert misspelt.is_error is True
        assert misspelt.content[0].text == (
            "Error executing tool compute_deadline: invalid arguments — letter_date: unknown argument "
            "(compute_deadline takes: spec, document_date, sender_kind, sender_name, remedy_type, region, "
            "recipient_region, received_date, today); recieved_date: unknown argument (compute_deadline "
            "takes: spec, document_date, sender_kind, sender_name, remedy_type, region, recipient_region, "
            "received_date, today)"
        )
        kind = await client.call_tool("compute_deadline", {"spec": TAX_SPEC, "sender_kind": "bank robber"})
        assert kind.is_error is True
        assert (
            "invalid arguments — sender_kind: Input should be 'authority', 'tax_office'"
            in kind.content[0].text
        )
        assert "pydantic" not in kind.content[0].text and "type=" not in kind.content[0].text
        missing = await client.call_tool("add_working_days", {"days": 2})
        assert missing.content[0].text.endswith("invalid arguments — start: required")
        # pydantic would read true as 1 before the tool's own check: refused on the way in
        flag = await client.call_tool("add_working_days", {"start": "2026-09-20", "days": True})
        assert flag.is_error is True
        assert flag.content[0].text.endswith("invalid arguments — days: must be a whole number (got true)")
        year = await client.call_tool("german_holidays", {"year": True})
        assert year.is_error is True and "year: must be a whole number (got true)" in year.content[0].text
        assert (
            _json(
                (await client.call_tool("add_working_days", {"start": "2026-09-20", "days": 5}))
                .content[0]
                .text
            )["date"]
            == "2026-09-25"
        )

        iban = await client.call_tool("check_iban", {"iban": "GB29 NWBK 6016 1331 9268 19"})
        assert _json(iban.content[0].text)["branch_code"] == {"label": "Sort code", "value": "601613"}


async def test_server_call_tool_raises_tool_errors() -> None:
    server = build_rules_server()
    with pytest.raises(
        ToolError, match=r"invalid arguments — day_type: Input should be 'business_days' or 'werktage'$"
    ):
        await server.call_tool(
            "add_working_days", {"start": "2026-01-01", "days": 1, "day_type": "sometimes"}
        )
    with pytest.raises(ToolError, match="region must be a German Land"):
        await server.call_tool("add_working_days", {"start": "2026-01-01", "days": 1, "region": "Mars"})


async def test_the_full_server_has_the_rules_tools_counting_from_the_ledgers_day(store: Store) -> None:
    seed_ledger(store)
    server = build_server(store, today=TODAY)
    assert {tool.name for tool in await server.list_tools()} == LEDGER_TOOLS | RULES_TOOLS
    spec = {"type": "relative", "anchor": "today", "amount": 1, "unit": "days", "nature": "payment"}
    result = await server.call_tool("compute_deadline", {"spec": spec})
    data = _json(unwrap_untrusted(result.content[0].text))
    assert data["due_date"] == "2026-09-29" and data["assumed"]["today"] == TODAY.isoformat()


async def test_asks_server_has_no_rules_tools(store: Store, tmp_path: Path) -> None:
    """Ask never computes dates: a rules tool would echo any date back and ground it for Ask's fact check."""
    seed_ledger(store)
    assert {tool.name for tool in await build_server(store, rules_tools=False).list_tools()} == LEDGER_TOOLS
    config = server_config(store.data_dir, today="2026-09-28", rules_tools=False)["mcpServers"]["ordnung"]
    assert config["args"][-1] == "--ledger-only"
    params = StdioServerParameters(command=config["command"], args=config["args"], env=config["env"])
    async with Client(params, mode="legacy") as client:  # exactly what Ask's claude process starts
        assert {tool.name for tool in (await client.list_tools()).tools} == LEDGER_TOOLS


async def test_the_full_server_says_the_ledgers_date_wins_for_its_letters(store: Store) -> None:
    """Next to explain_date ("never recalculate"), compute_deadline must not contradict a stored date that
    rests on facts the model cannot see (a confirmed arrival day, a corrected sender)."""
    from ordnung.assistant.mcp_server import INSTRUCTIONS as LEDGER_INSTRUCTIONS

    seed_ledger(store)
    full = build_server(store, today=TODAY)
    assert "compute_deadline is for letters that are not in the ledger" in (full.instructions or "")
    listed = {tool.name: tool for tool in await full.list_tools()}
    assert "Not for a letter already in the ledger" in (listed["compute_deadline"].description or "")
    ask = build_server(store, rules_tools=False)
    assert ask.instructions == LEDGER_INSTRUCTIONS
    rules_only = {tool.name: tool for tool in await build_rules_server().list_tools()}
    assert "ledger" not in (rules_only["compute_deadline"].description or "")


def test_the_today_argument_says_to_leave_it_out() -> None:
    compute = next(d for d in tool_definitions() if d["name"] == "compute_deadline")
    today = compute["input_schema"]["properties"]["today"]["description"]
    assert today.startswith("Leave null: the server knows today's date in Germany.")


def test_the_tools_do_not_claim_exact_dates() -> None:
    """The engine returns the earliest plausible date where facts are missing, not "the exact date"."""
    compute = next(d for d in tool_definitions() if d["name"] == "compute_deadline")
    for text in (INSTRUCTIONS, compute["description"]):
        assert "exact" not in text.casefold() and "earliest plausible" in text
    assert "3 where a Land's own law is not confirmed" in compute["description"]


async def test_rules_only_stdio_handshake_through_the_cli() -> None:
    """``python -m ordnung mcp --rules-only`` — what Claude Desktop starts — with no data folder at all."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ordnung", "mcp", "--rules-only"],
        env={"ORDNUNG_TODAY": "2026-09-20", "ORDNUNG_HOME": "/nonexistent/ordnung-home"},
    )
    async with Client(params, mode="legacy") as client:
        assert client.server_info is not None and client.server_info.name == SERVER_NAME
        assert {tool.name for tool in (await client.list_tools()).tools} == RULES_TOOLS
        spec = {"type": "relative", "anchor": "today", "amount": 1, "unit": "weeks", "nature": "payment"}
        result = await client.call_tool("compute_deadline", {"spec": spec})
        assert _json(result.content[0].text)["due_date"] == "2026-09-28"
        unpinned = _json(
            (await client.call_tool("compute_deadline", {"spec": spec, "today": "2026-10-01"}))
            .content[0]
            .text
        )
        assert (
            unpinned["assumed"]["today"] == "2026-09-20"
            and unpinned["assumed"]["today_given"] == "2026-10-01"
        )
        assert unpinned["for_today_given"]["due_date"] == "2026-10-08"


async def test_the_benchmarks_rules_server_keeps_the_letters_today() -> None:
    """The claude CLI tells the model the real date; the server it starts for a letter must not use it."""
    config = rules_server_config(today="2026-04-14")["mcpServers"][SERVER_NAME]
    params = StdioServerParameters(command=config["command"], args=config["args"], env=config["env"])
    async with Client(params, mode="legacy") as client:
        spec = {"type": "fixed", "date": "2026-05-15", "nature": "objection"}
        result = _json(
            (await client.call_tool("compute_deadline", {"spec": spec, "today": "2026-09-26"}))
            .content[0]
            .text
        )
        assert result["assumed"] == {
            "today": "2026-04-14",
            "today_given": "2026-09-26",
            "holiday_calendar": "Germany (nationwide holidays only)",
            "holidays_from": "region: the Land where the deadline is met (the sender's seat)",
        }
        assert result["send_by"] == "2026-05-08" and "was not used" in result["warnings"][0]


def test_rules_server_config_and_print_config() -> None:
    config = rules_server_config()
    assert config == {
        "mcpServers": {
            SERVER_NAME: {"command": sys.executable, "args": ["-m", "ordnung", "mcp", "--rules-only"]}
        }
    }
    assert rules_server_config(today="2026-09-20")["mcpServers"][SERVER_NAME]["env"] == {
        "ORDNUNG_TODAY": "2026-09-20",
        "ORDNUNG_PIN_TODAY": "1",
    }
    result = CliRunner().invoke(app, ["mcp", "--rules-only", "--print-config"])
    assert result.exit_code == 0 and json.loads(result.output) == config
    both = CliRunner().invoke(app, ["mcp", "--rules-only", "--ledger-only"])
    assert both.exit_code == 1 and "exclude each other" in both.output


def test_importing_the_rules_tools_stays_light() -> None:
    probe = (
        "import sys; import ordnung.assistant.rules_tools; "
        "heavy = [m for m in ('mcp', 'ordnung.rules', 'ordnung.db.store', 'holidays') if m in sys.modules]; "
        "print(heavy)"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


# --------------------------------------------------------------------------------------------------
# a court's letter: the same date, confidence and rules as the app
# --------------------------------------------------------------------------------------------------

COURT_NAMES = (
    "Amtsgericht Hünfeld - Zentrales Mahngericht",
    "Amtsgericht Coburg",
    "AG Hagen",
    "Arbeitsgericht Berlin",
    "ArbG Berlin",
    "Sozialgericht Berlin",
    # a court whose place contains "kasse" (review round 2: the cashier exclusion matched "Kassel")
    "Amtsgericht Kassel",
    "Arbeitsgericht Kassel",
    "SG Kassel",
)
COURT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "type": "relative",
        "anchor": "deemed_delivery",
        "amount": 2,
        "unit": "weeks",
        "delivery_rule": "de_admin_post",
        "nature": "objection",
        "text": "Sie können gegen den Anspruch innerhalb von zwei Wochen ab Zustellung Widerspruch erheben.",
    },
    {**RECEIPT, "legal_basis": "§ 692 ZPO", "text": "Widerspruch binnen zwei Wochen"},
    {**RECEIPT, "legal_basis": "§ 700 ZPO", "text": "Einspruch binnen zwei Wochen"},
    {**RECEIPT, "text": "Einspruch gegen den Vollstreckungsbescheid binnen zwei Wochen"},
    {
        **RECEIPT,
        "anchor": "document_date",
        "text": "Stellungnahme binnen zwei Wochen ab dem Datum dieses Schreibens",
    },
)


def _app_receipt(
    spec: dict[str, Any], name: str, kind: str | None, remedy: str | None, received: str | None
) -> Any:
    """What the app computes for the same facts (``ingest.plan.rule_context`` over the same reading)."""
    from ordnung.ingest.plan import rule_context
    from ordnung.models import Document, DocumentExtraction, ExtractedItem, ExtractedParty, Remedy
    from ordnung.rules import compute_due

    parsed = DateSpec.model_validate(spec)
    reading = DocumentExtraction(
        kind="other",
        title="",
        summary="",
        explanation="",
        document_date="2026-09-15",
        sender=ExtractedParty(name=name, kind=kind or "other"),  # type: ignore[arg-type]
        items=[ExtractedItem(kind="deadline", title="", date=parsed, quote="")],
        remedy=Remedy(type=remedy) if remedy else None,  # type: ignore[arg-type]
    )
    document = Document.model_construct(received_date=received)
    return compute_due(parsed, rule_context(None, document, reading, date(2026, 9, 28)))


@pytest.mark.parametrize("name", COURT_NAMES)
def test_a_courts_period_gets_the_apps_date_confidence_and_rules(name: str) -> None:
    """ADR 0009: a tool and the app give the same date for the same facts — a court is a court by its
    name, whatever kind the model passed it as (a court is no PartyKind: ``authority`` or ``other``)."""
    tools = RulesTools(today=lambda: date(2026, 9, 28))
    for kind in ("authority", "other"):
        for spec in COURT_SPECS:
            for remedy in ("widerspruch", "einspruch", None):
                for received in (None, "2026-09-16"):
                    got = tools.compute_deadline(
                        spec,
                        document_date="2026-09-15",
                        sender_kind=kind,
                        sender_name=name,
                        remedy_type=remedy,
                        received_date=received,
                    )
                    app = _app_receipt(spec, name, kind, remedy, received)
                    case = (kind, spec["text"], remedy, received)
                    assert got["due_date"] == app.due_date, case
                    assert got["confidence"] == app.confidence != "high", case
                    assert [rule["id"] for rule in got["rules"]] == app.rule_ids, case
                    assert "posting_day" not in app.rule_ids, case  # never a delivery fiction


def test_a_court_order_never_gets_an_administrative_delivery_fiction(tools: RulesTools) -> None:
    """The review's cases: a Mahnbescheid read with deemed delivery, and a labour court's enforcement
    order (one week, § 59 ArbGG) — the tool's date was days late on a Notfrist."""
    at_court = RulesTools(today=lambda: date(2026, 9, 28))
    order = at_court.compute_deadline(
        COURT_SPECS[0],
        document_date="2026-09-15",
        sender_kind="authority",
        sender_name="Amtsgericht Coburg",
        remedy_type="widerspruch",
        received_date="2026-09-16",
    )
    assert order["due_date"] == "2026-09-30" and order["confidence"] == "medium"
    assert (
        order["assumed"]["delivery_law"] == "a court's letter: formal service (§ 180 ZPO), no deemed delivery"
    )
    assert order["assumed"]["received_date"] == "2026-09-16"  # the delivery day the period ran from
    assert {"zpo_180", "zpo_222"} <= {rule["id"] for rule in order["rules"]}
    assert not {"posting_day", "vwvfg_31_3"} & {rule["id"] for rule in order["rules"]}
    labour = at_court.compute_deadline(
        COURT_SPECS[2],
        document_date="2026-09-15",
        sender_kind="authority",
        sender_name="Arbeitsgericht Berlin",
        remedy_type="einspruch",
        received_date="2026-09-16",
    )
    assert labour["due_date"] == "2026-09-23" and labour["confidence"] != "high"
    assert "arbgg_59" in {rule["id"] for rule in labour["rules"]}
    # without the envelope date the hint asks for it, never for the sender's kind
    unknown = tools.compute_deadline(
        COURT_SPECS[0], document_date="2026-09-14", sender_kind="other", sender_name="AG Hagen"
    )
    assert unknown["due_date"] == "2026-09-28" and unknown["confidence"] != "high"
    assert any("yellow envelope" in hint for hint in unknown["hints"])
    assert not any("sender_kind" in hint for hint in unknown["hints"])
    # a named Mahnbescheid gets the court rule and its note (§ 694 ZPO) though no § is cited
    named = tools.compute_deadline(
        {**RECEIPT, "text": "Widerspruch gegen diesen Mahnbescheid binnen zwei Wochen"},
        document_date="2026-09-14",
        sender_kind="authority",
        sender_name="Amtsgericht Hagen",
        remedy_type="widerspruch",
        received_date="2026-09-15",
    )
    assert "zpo_692" in {rule["id"] for rule in named["rules"]} and named["confidence"] != "high"
    assert any("§ 694 ZPO" in warning for warning in named["warnings"])


def test_a_pinned_server_ignores_a_callers_today_one_day_off() -> None:
    """The benchmark's server keeps its letter's day even for a today a time zone apart, and gives no view
    for it (an unpinned server gives that day's view too)."""
    pinned = RulesTools(today=lambda: date(2026, 4, 14), pin_today=True)
    spec = {"type": "relative", "anchor": "today", "amount": 10, "unit": "days", "nature": "payment"}
    for given in ("2026-04-13", "2026-04-15"):
        result = pinned.compute_deadline(spec, document_date="2026-04-14", today=given)
        assert result["assumed"]["today"] == "2026-04-14" and result["for_today_given"] is None
        assert result["assumed"]["today_given"] == given
    unpinned = RulesTools(today=lambda: date(2026, 4, 14)).compute_deadline(
        spec, document_date="2026-04-14", today="2026-04-13"
    )
    assert unpinned["assumed"]["today"] == "2026-04-14"
    assert unpinned["for_today_given"]["today"] == "2026-04-13"
