"""The ledger-free rules tools (``ordnung.assistant.rules_tools``): the deadline engine, the holiday
calendar, working days and the IBAN check as MCP tools — their answers, strict validation and
readable errors, the "information, not legal advice" framing, the rules-only server (no ledger tools,
no data folder, over a real stdio handshake) and the same tools inside the full ledger server."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from typing import Any

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver.exceptions import ToolError
from typer.testing import CliRunner

from helpers_secretary import TODAY, seed_ledger
from ordnung.assistant import rules_tools
from ordnung.assistant.mcp_server import build_server
from ordnung.assistant.rules_tools import (
    DISCLAIMER_TEMPLATE,
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
from ordnung.rules import LAST_CHECKED

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
    assert result["confidence"] == "high" and result["warnings"] == [] and result["hints"] == []
    assert "moved to Mon 21 Sep" in result["summary"]
    assert [step["rule_id"] for step in result["steps"]][:3] == [
        "posting_day",
        "ao_122_2_1",
        "ao_fiction_shift",
    ]
    assert all(step["citation"] for step in result["steps"])
    rules = {rule["id"]: rule for rule in result["rules"]}
    assert "§ 122 Abs. 2 Nr. 1 AO" in rules["ao_122_2_1"]["citation"] and rules["ao_122_2_1"]["url"]
    assert result["assumed"] == {
        "today": "2026-09-20",
        "letter_date": "2026-09-15",
        "received_date": None,
        "delivery_law": "tax law (§ 122 AO)",
        "holiday_calendar": "Germany (nationwide holidays only)",
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


def test_today_defaults_to_the_servers_day_and_can_be_given(tools: RulesTools) -> None:
    spec = {"type": "relative", "anchor": "today", "amount": 10, "unit": "days", "nature": "payment"}
    assert tools.compute_deadline(spec)["due_date"] == "2026-09-30"
    assert (
        tools.compute_deadline(spec, today="2026-10-01")["due_date"] == "2026-10-12"
    )  # the 11th is a Sunday


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"type": "relative", "amout": 1}, "spec.amout: unknown field (a DateSpec has: type, date,"),
        ({"type": "relative", "unit": "month"}, "spec.unit: Input should be 'days'"),
        ({"type": "soon"}, "spec.type: Input should be 'fixed', 'relative' or 'none'"),
        ({"amount": 1}, "spec.type: Field required"),
        ("in a month", "spec must be an object"),
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
    assert "Assumption Day" in bavaria["note"] and "earlier, never later" in bavaria["note"]
    assert "note" not in compact(tools.german_holidays(2026, "NW"))  # no partial holidays to explain
    assert bavaria["disclaimer"] == DISCLAIMER


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
    long = tools.add_working_days("2026-01-01", 200)
    assert len(long["skipped"]) == rules_tools.MAX_LISTED_SKIPS and long["skipped_more"] > 0


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
    assert "says nothing about who owns the account" in good["note"] and good["disclaimer"] == DISCLAIMER
    bad = compact(tools.check_iban("DE89 3704 0044 0532 0130 01"))
    assert bad["valid"] is False and bad["checksum_ok"] is False and "bank_code" not in bad
    assert bad["problems"] == ["The check digits do not match: a character is wrong, missing or swapped."]
    foreign = tools.check_iban("BR15 0000 0000 0000 1093 2840 814P 2")
    assert foreign["note"].startswith("This country's IBAN length is not in Ordnung's table")
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

        iban = await client.call_tool("check_iban", {"iban": "GB29 NWBK 6016 1331 9268 19"})
        assert _json(iban.content[0].text)["branch_code"] == {"label": "Sort code", "value": "601613"}


async def test_server_call_tool_raises_tool_errors() -> None:
    server = build_rules_server()
    with pytest.raises(ToolError, match=r"Input should be 'business_days' or 'werktage'"):
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


def test_rules_server_config_and_print_config() -> None:
    config = rules_server_config()
    assert config == {
        "mcpServers": {
            SERVER_NAME: {"command": sys.executable, "args": ["-m", "ordnung", "mcp", "--rules-only"]}
        }
    }
    assert rules_server_config(today="2026-09-20")["mcpServers"][SERVER_NAME]["env"] == {
        "ORDNUNG_TODAY": "2026-09-20"
    }
    result = CliRunner().invoke(app, ["mcp", "--rules-only", "--print-config"])
    assert result.exit_code == 0 and json.loads(result.output) == config


def test_importing_the_rules_tools_stays_light() -> None:
    probe = (
        "import sys; import ordnung.assistant.rules_tools; "
        "heavy = [m for m in ('mcp', 'ordnung.rules', 'ordnung.db.store', 'holidays') if m in sys.modules]; "
        "print(heavy)"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
