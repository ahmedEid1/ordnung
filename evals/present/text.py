"""The words around the numbers (standard library only): the README block, the report and the history page.

The report's content is written once, as :class:`Section` blocks, and rendered twice: Markdown for
``docs/evals.md`` (:func:`report`) and HTML for the report page (:mod:`evals.present.site`). Inline markup is a small
subset of Markdown: ``**bold**``, ```code```, and ``[text](target)`` where a target is ``#anchor``, ``https://…`` or
``repo:path`` (a file of the repository: relative on GitHub, a link to it from the page).

Every sentence that judges a result is chosen by rule from the numbers (:func:`headline`), so a bad result is said in
the same place and at the same size as a good one. Nothing here is typed by hand that a results file holds.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from evals.present import BEGIN, END, MODEL, PAGES_URL, REPO_URL, charts, fmt, palette

REPORT_TITLE = "Evaluation: reading German letters for deadlines"
HISTORY_TITLE = "Evaluation history: every run, in the order it happened"
WIDTH = 116
_REFERENCE = "ordnung"
#: How a set-aside cause of the end-to-end run reads.
_CAUSES = {"set_aside:scam_signs": "set aside as a scam"}
_OUTCOMES = {"wrong": "wrong date", "missed": "missed", "declined": "found, no date"}


# --------------------------------------------------------------------------------------------------
# The content model
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Paragraph:
    text: str


@dataclass(frozen=True)
class Bullets:
    items: Sequence[str]


@dataclass(frozen=True)
class Table:
    header: Sequence[str]
    rows: Sequence[Sequence[str]]
    caption: str


@dataclass(frozen=True)
class Chart:
    name: str


@dataclass(frozen=True)
class Code:
    lines: Sequence[str]


@dataclass(frozen=True)
class Subheading:
    text: str


Block = Paragraph | Bullets | Table | Chart | Code | Subheading


@dataclass(frozen=True)
class Section:
    title: str
    blocks: Sequence[Block] = field(default_factory=tuple)

    @property
    def anchor(self) -> str:
        return slug(self.title)


def slug(title: str) -> str:
    """The id GitHub gives a heading: lower case, punctuation dropped, spaces as hyphens."""
    kept = re.sub(r"[^\w\- ]", "", title.lower())
    return kept.replace(" ", "-")


# --------------------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------------------


def _headline(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    headline: Mapping[str, Any] = doc["headline"]
    return headline


def _c(doc: Mapping[str, Any], condition: str) -> Mapping[str, Any]:
    summary: Mapping[str, Any] = _headline(doc)["conditions"][condition]
    return summary


def _pair(doc: Mapping[str, Any], family: str, baseline: str) -> Mapping[str, Any]:
    pair: Mapping[str, Any] = _headline(doc)["paired"][family][f"{_REFERENCE}-vs-{baseline}"]
    return pair


def _label(condition: str) -> str:
    return palette.LABELS[condition]


def _discordant(pair: Mapping[str, Any]) -> str:
    return f"{pair['b']} vs {pair['c']} discordant"


def _exact_p(pair: Mapping[str, Any]) -> str:
    return f"exact p {fmt.p_value(pair['exact_p'])}"


def fill(value: str, width: int = WIDTH, first: str = "", rest: str = "") -> str:
    """``value`` in lines of at most ``width`` characters, broken at spaces only, never before a ``%``."""
    words: list[str] = []
    for word in value.split():
        if word.startswith("%") and words:
            words[-1] += " " + word
        else:
            words.append(word)
    lines: list[str] = []
    line = ""
    for word in words:
        prefix = rest if lines else first
        if line and len(prefix) + len(line) + 1 + len(word) > width:
            lines.append(prefix + line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    lines.append((rest if lines else first) + line)
    return "\n".join(lines)


def _wrap(value: str) -> str:
    return fill(value)


def verdict(pair: Mapping[str, Any], *, harm: bool = False) -> str:
    """A one-read comparison in words: ``clear`` and ``suggestive`` say which side; ``none`` says so. For harm
    (``harm=True``) fewer is better, so the verdict names the side with fewer harmful dates."""
    if pair["verdict"] == "none" or pair["diff"] == 0:
        return "no clear difference"
    if harm:
        side = "fewer with Ordnung" if pair["diff"] < 0 else "fewer with the baseline"
    else:
        side = "Ordnung ahead" if pair["diff"] > 0 else "the baseline ahead"
    return f"{side}, clearly" if pair["verdict"] == "clear" else f"{side}, suggestive, not settled"


# --------------------------------------------------------------------------------------------------
# The headline sentence and the README block
# --------------------------------------------------------------------------------------------------


def headline(doc: Mapping[str, Any]) -> str:
    """The headline paragraph, chosen by rule (Markdown): the same place and size for a good and a bad result."""
    h = _headline(doc)
    ordnung, alone, agent = (_c(doc, c) for c in ("ordnung", "llm_only", "llm_rules_tool"))
    n = ordnung["exact"]["n"]
    harmful = ordnung["harmful"]["k"]
    harm = f"**none of {n}**" if harmful == 0 else f"**{harmful} of {n}**"
    first = (
        f"**{h['label']}.** On {h['items']} deadlines in {h['letters']} synthetic letters that nothing was tuned on, "
        f"Ordnung dates **{fmt.pct(ordnung['exact']['value'])}** exactly right (95 % CI "
        f"{fmt.ci(ordnung['exact']['ci'])}), with {harm} late or missed."
    )
    pair = _pair(doc, "accuracy", "llm_only")
    # the accuracy test sits with the accuracy it tests, before the harm count
    tail = f"({_discordant(pair)}, {_exact_p(pair)})"
    if pair["verdict"] == "clear" and pair["diff"] > 0:
        judged = f" {tail}"
    elif pair["verdict"] == "clear":
        judged = f": **the model alone is ahead** {tail}"
    else:
        judged = f": **no clear difference** {tail}"
    second = (
        f"The same model doing the date arithmetic itself gets **{fmt.pct(alone['exact']['value'])}**{judged}, "
        f"with **{alone['harmful']['k']}** late or missed."
    )
    pair = _pair(doc, "accuracy", "llm_rules_tool")
    shown = f"{fmt.pct(agent['exact']['value'])}, {_discordant(pair)}"
    agent_text = "An agent given Ordnung's engine as a tool"
    # "level" only when Ordnung minus the agent is above −margin at the interval's lower bound (the pre-registered
    # non-inferiority rule, on the letter-cluster bootstrap); otherwise we cannot tell
    margin = float(h["settings"]["noninferiority_margin"])
    within = f"within {margin * 100:g} points"
    low = pair["bootstrap"][0]
    interval = f"{fmt.points(pair['diff'])} points, 95 % CI {fmt.interval_points(pair['bootstrap'])}"
    if pair["verdict"] == "clear" and pair["diff"] < 0:
        third = (
            f"{agent_text} scores higher ({shown}, {_exact_p(pair)}): the pipeline's case rests on receipts and "
            "checked quotes, not accuracy."
        )
    elif pair["verdict"] == "clear":
        third = f"{agent_text} scores lower ({shown}, {_exact_p(pair)})."
    elif pair["verdict"] == "suggestive":
        side = "higher" if pair["diff"] < 0 else "lower"
        third = f"{agent_text} scores {side}, not settled ({shown}, {_exact_p(pair)})."
    elif low is not None and low > -margin:
        third = (
            f"{agent_text} is level {within} ({shown}; {interval}): what the pipeline adds is a receipt and a "
            "checked quote for every date."
        )
    else:
        third = (
            f"{agent_text} scores {fmt.pct(agent['exact']['value'])} ({_discordant(pair)}): we cannot tell whether "
            f"Ordnung is {within} of it ({interval})."
        )
    return " ".join((first, second, third))


def shortfall(doc: Mapping[str, Any]) -> str:
    """What the flags caught, always; and the real obligations the app set aside, once the end-to-end run exists."""
    flags = _headline(doc)["flags"]
    caught = f"“Please check” caught {flags['caught']} of Ordnung's {flags['wrong']} wrong dates"
    parts = [caught]
    e2e = doc.get("e2e")
    if e2e and e2e["set_aside"]:
        parts.append(
            f"{e2e['set_aside']} of {e2e['obligations']} real obligations got no reminder because their letter was set "
            "aside as a scam"
        )
    in_calendar = len(e2e["scam"]["in_the_calendar"]) if e2e and e2e.get("scam") else 0
    if e2e and in_calendar:
        parts.append(
            f"{in_calendar} of {e2e['scam']['letters']} scam letters still put their demands in the calendar"
        )
    short = flags["caught"] < flags["wrong"] or bool(e2e and e2e["set_aside"]) or bool(in_calendar)
    lead = "**Where it falls short:**" if short else "**Flags:**"
    return f"{lead} " + "; ".join(parts) + "."


#: What a wrong Ask answer is (singular, plural), in the order the line names them.
WRONG_ANSWERS = (
    ("leak", "calls a date that is still open passed", "call a date that is still open passed"),
    ("gap", "is a gap in the ledger", "are gaps in the ledger"),
    ("other", "leaves out a value Ordnung's record holds", "leave out a value Ordnung's record holds"),
)
LEAK = "the recording day leaking in as today"


def _wrong_clause(wrong: Mapping[str, int]) -> str:
    total = wrong["total"]
    noun = f"{fmt.words(total)} wrong answer{'s' if total > 1 else ''}"
    kinds = [(kind, wrong[kind], one, many) for kind, one, many in WRONG_ANSWERS if wrong.get(kind)]
    if len(kinds) == 1:
        kind, _, one, many = kinds[0]
        clause = f"the {noun} {many if total > 1 else one}"
        return clause + (f", {LEAK}" if kind == "leak" else "")
    parts = [
        f"{fmt.words(n)} {many if n > 1 else one}" + (f" ({LEAK})" if kind == "leak" else "")
        for kind, n, one, many in kinds
    ]
    return f"of the {noun}, {fmt.join(parts)}"


def ask_line(doc: Mapping[str, Any]) -> str | None:
    """The README's Ask line: answers right and what the wrong ones are, injected claims that reach the person, the
    household group, and which set it is."""
    ask = doc.get("ask")
    if not ask:
        return None
    final, raw = ask["attack_success"], ask["attack_success_raw"]
    held = "held out" if ask["set"] == "heldout" else "a development set, not held out"
    right = f"{fmt.of(ask['accuracy'])} answers right"
    wrong = ask.get("wrong") or {}
    if wrong.get("total"):
        right += ": " + _wrong_clause(wrong)
    parts = [right, f"{fmt.of(final)} injected claims reach you ({fmt.of(raw)} without the answer check)"]
    if ask.get("household"):
        parts.append(f"{fmt.of(ask['household'])} household answers say whose a number is")
    return "**Ask:** " + "; ".join([*parts, held]) + "."


def readme_block(doc: Mapping[str, Any]) -> str:
    """The README's generated block, markers included (Markdown, relative links)."""
    alt = charts.description("held-out", doc).replace('"', "'")
    picture = (
        '<picture><source media="(prefers-color-scheme: dark)" srcset="docs/assets/eval-held-out-dark.svg">'
        f'<img src="docs/assets/eval-held-out-light.svg" width="{charts.WIDE}" alt="{alt}"></picture>'
    )
    lines = [shortfall(doc) + "<br>"]
    ask = ask_line(doc)
    if ask:
        lines.append(ask + "<br>")
    lines.append(
        f"**[Full evaluation report →]({PAGES_URL})** statistics, baselines, safety, failures and cost · "
        "[as Markdown](docs/evals.md) · [reproduce it with no API key](docs/evals.md#15-reproduce)"
    )
    return "\n".join([BEGIN, _wrap(headline(doc)), "", picture, "", *lines, END]) + "\n"


# --------------------------------------------------------------------------------------------------
# The report's sections
# --------------------------------------------------------------------------------------------------


def _card(doc: Mapping[str, Any]) -> Section:
    h = _headline(doc)
    newest = max(h["inputs"], key=lambda row: row["date"])
    inputs = fmt.join([f"`{row['file']}`" for row in h["inputs"]])
    rows = [
        ["Task", "Find each deadline in a German letter and give its exact date"],
        ["Model", f"`{doc['model']}`, the same pinned model in every condition"],
        [
            "Data",
            f"{h['letters']} synthetic letters ({h['photos']} phone photos, {h['adversarial']} adversarial) in "
            f"{len(h['splits'])} held-out splits: {h['items']} dated deadlines",
        ],
        ["Primary metric", "Exact date right: the deadline's date exactly, no tolerance"],
        ["Safety metric", "Harmful: late or missed (the person would act too late, or never)"],
        [
            "Held-out protocol",
            "Each split written before any recording on it, recorded once, nothing tuned on it "
            "([Data and labels](#3-data-and-labels))",
        ],
        [
            "Pre-registration",
            "Not yet: these statistics were chosen after the results were known (**not pre-registered**). The final "
            "run on the version that ships will be pre-registered before it is recorded",
        ],
        ["Reads", "One read per letter"],
        [
            "Intervals",
            "Clopper–Pearson for a rate; for paired comparisons, exact McNemar and a sign-flip test over letter "
            "clusters, each with Holm ([Statistics](#7-statistics))",
        ],
        [
            "Replay",
            "Every number is checked against a replay of the recorded answers with no model call; where today's code "
            "gives another value, the results index pins it and names the change ([Reproduce](#15-reproduce))",
        ],
        ["Sources", f"`{h['source']['file']}`, from {inputs}"],
        ["Newest recording", f"{newest['split']}, {newest['date']}, commit `{newest['commit']}`"],
    ]
    return Section(
        "Evaluation card",
        [Table(["About", "This evaluation"], rows, "The evaluation card")],
    )


def _summary(doc: Mapping[str, Any]) -> Section:
    rows = []
    for condition in doc["order"]:
        c = _c(doc, condition)
        name = f"**{_label(condition)}**" if condition == _REFERENCE else _label(condition)
        rows.append(
            [
                name,
                f"{fmt.pct(c['exact']['value'])} [{fmt.ci(c['exact']['ci'])}]",
                fmt.kn(c["exact"]),
                fmt.kn(c["harmful"]),
                fmt.kn(c["letters_fully_right"]),
                str(c["spurious_dated_items"]),
                fmt.usd(c["cost"]["usd_per_letter"]),
                fmt.seconds(c["latency_ms"]["p50"]),
            ]
        )
    table = Table(
        [
            "Condition",
            "Exact date right [95 % CI]",
            "Exact",
            "Late or missed",
            "Letters fully right",
            "Spurious dated items",
            "$ per letter",
            "Latency p50",
        ],
        rows,
        "The four conditions on the held-out deadlines",
    )
    alone = _pair(doc, "accuracy", "llm_only")
    tool = _pair(doc, "accuracy", "llm_rules_tool")
    claim = _headline(doc).get("rules_text_claim")
    flags = _headline(doc)["flags"]
    findings = [
        f"Against the model alone: {_discordant(alone)}, {_exact_p(alone)}: {verdict(alone)}.",
    ]
    if claim:
        findings.append(f"Against the rules-text prompt: {claim['text']}.")
    findings.append(
        f"Against the agent with the engine as a tool: {_discordant(tool)}, {_exact_p(tool)}: "
        f"{verdict(tool)}."
    )
    findings.append(
        f"“Please check” caught {flags['caught']} of Ordnung's {flags['wrong']} wrong dates "
        "([Safety and selective prediction](#10-safety-and-selective-prediction))."
    )
    return Section(
        "1. Summary",
        [
            Paragraph(headline(doc)),
            Chart("held-out"),
            table,
            Paragraph("Four findings, each with its paired test on the same deadlines:"),
            Bullets(findings),
        ],
    )


def _task(doc: Mapping[str, Any]) -> Section:
    blocks: list[Block] = [
        Paragraph(
            "A German letter rarely prints its deadline. It says *one month after this notice is announced to you*, "
            "and the date depends on rules a reader has to know:"
        ),
        Bullets(
            [
                "A posted notice counts as delivered on the fourth day after posting since 2025 (the third before). "
                "Tax law moves that day off a weekend or a holiday; administrative law does not.",
                "A period that ends on a weekend or a public holiday ends on the next working day (§ 193 BGB), but a "
                "notice period does not move.",
                "Public holidays differ by federal state (Land).",
            ]
        ),
    ]
    fact = doc.get("llm_only_first_run")
    if fact:
        shifted = (
            f"all {fact['late']} late answers"
            if fact["late_shifted"] == fact["late"]
            else f"{fact['late_shifted']} of the {fact['late']} late answers"
        )
        blocks.append(
            Paragraph(
                f"On the test split's first run ({fact['date']}), asked to work out the deadlines itself, the model "
                f"got {fact['wrong']} of {fact['n']} wrong: {fact['three_day']} of those used the 3-day delivery rule "
                f"that became 4 days in 2025, and {shifted} moved a deemed delivery day off a weekend or holiday, "
                "which only tax law allows (from the explanations stored with each answer)."
            )
        )
    blocks.append(
        Paragraph(
            "Ordnung's design bet ([ADR 0002](repo:docs/decisions/0002-llm-reads-code-computes.md)): the model "
            "**reads** the letter, what it says about a date, and tested code **computes** the date, with a "
            "receipt for every step ([the rules](repo:docs/deadline-rules.md))."
        )
    )
    return Section("2. The task, and why it is hard", blocks)


def _data(doc: Mapping[str, Any]) -> Section:
    header, rows = charts.table("timeline", doc)
    return Section(
        "3. Data and labels",
        [
            Paragraph(
                "The letters are synthetic: code writes them (`evals/gen/`) from templates with a known answer, as "
                "PDFs and as phone photos of them. Each label is the generator's own arithmetic, checked again by "
                "`evals/verify_labels.py`; each split has template variants of its own. A photo repeats the dated "
                "deadlines of the PDF it was made from, so a letter and its photo are one cluster in the statistics."
            ),
            Chart("timeline"),
            Table(header, rows, "The splits, in the order they were written"),
            Paragraph(
                "The held-out splits were written before any recording on them, by agents that saw neither the "
                "reading code nor the prompts nor any result; holdout2's labels were audited blind, and holdout3's "
                "dates were derived by two more agents before they saw the labels. Each was recorded once, with the "
                "code and prompts of its day. Changes informed by a held-out split came after it, and the replays "
                "with them are re-scored rows on the [history page](repo:docs/evals-history.md), never held-out "
                "numbers."
            ),
            Paragraph(
                "What the letters are not: real post. They are one or two clean pages in a fixed set of letter "
                "families, and the rarer high-stakes kinds the engine covers (court orders, dismissals, a landlord's "
                "notice) are not among them yet."
            ),
        ],
    )


def _conditions(doc: Mapping[str, Any]) -> Section:
    rows = [
        [
            "Ordnung",
            "the rules engine",
            "the model reads the letter into a structured reading; code finds each quote on the page",
        ],
        [
            "LLM only",
            "the model",
            "not at all: it is told today's date, the region and to apply current German law",
        ],
        ["LLM + rules text", "the model", "a verified summary of the rules, pasted into the prompt"],
        [
            "LLM + rules tool",
            "the model, calling the engine",
            "Ordnung's engine as MCP tools: an agent with a "
            "calculator, which decides when to call it and whether "
            "to trust it",
        ],
    ]
    return Section(
        "4. Conditions and baselines",
        [
            Paragraph(
                f"The same model (`{doc['model']}`) reads the same letters under four conditions; each letter's "
                "“today” and holiday region are the same in all four. Read as an ablation, they cross who computes "
                "the date with how the rules reach the model:"
            ),
            Table(
                ["Condition", "Who computes the date", "How the rules reach the model"],
                rows,
                "The four conditions",
            ),
            Paragraph(
                "*LLM only* is a floor; the rules-text prompt and the agent are the competitors. The tuning effort is "
                "unequal, in Ordnung's favour: its extraction prompt went through several versions on the dev and "
                "test splits (the [history page](repo:docs/evals-history.md) lists them), the baselines' prompts were "
                "tuned on the dev split."
            ),
        ],
    )


def _metrics(_doc: Mapping[str, Any]) -> Section:
    return Section(
        "5. Metrics",
        [
            Bullets(
                [
                    "**Exact date right** (primary): the share of dated deadlines whose final date is exactly the "
                    "labelled one. A day off is wrong: a day late can miss a deadline and a day early asks for "
                    "needless haste, and a tolerance would hide both.",
                    "**Late** (after the real date), **missed** (not found) and **harmful = late or missed**, the "
                    "safety metric: the person would act too late, or never. The scorer's *dangerously late* leaves "
                    "a missed deadline out; it is still reported, as the CI gates use it. **Early**: before the real "
                    "date, safe but wrong.",
                    "**Letter fully right**: every dated deadline of the letter right and no spurious dated item. "
                    "**Spurious dated items**: dated items the letter does not have.",
                    "**$ per letter** and **per right date**: the API-equivalent price the Claude CLI reports. "
                    "**Latency**: the model's time per letter, p50 and p95.",
                    "**Flags**: what the person sees with a date: *Please check* (low confidence, or no date), "
                    "*worth a second look* (medium confidence), or nothing.",
                ]
            )
        ],
    )


def _results(doc: Mapping[str, Any]) -> Section:
    h = _headline(doc)
    blocks: list[Block] = [
        Subheading("6.1 The final run (three reads)"),
        Paragraph(
            "The final run on the version that ships has not been recorded yet: its split, holdout4, is written after "
            "the code freeze, and the run will be pre-registered before it is recorded. When it is recorded, its "
            "numbers take the headline by the rule the pre-registration sets, whatever they show."
        ),
        Subheading("6.2 The held-out splits pooled, as recorded"),
    ]
    rows = []
    for condition in doc["order"]:
        c = _c(doc, condition)
        rows.append(
            [
                _label(condition),
                f"{fmt.kn(c['exact'])} ({fmt.pct(c['exact']['value'])}) [{fmt.ci(c['exact']['ci'])}]",
                str(c["late"]["k"]),
                str(c["missed"]["k"]),
                str(c["early"]["k"]),
                f"{fmt.kn(c['harmful'])} [{fmt.ci(c['harmful']['ci'])}]",
            ]
        )
    blocks.append(
        Table(
            [
                "Condition",
                "Exact date right [95 % CI]",
                "Late",
                "Missed",
                "Early",
                "Late or missed [95 % CI]",
            ],
            rows,
            "The held-out splits pooled",
        )
    )
    dates = fmt.join([f"{row['split']} on {row['date']}" for row in h["inputs"]])
    blocks.append(
        Paragraph(
            f"Each split was recorded once, with the code and prompts of its day ({dates}): pooled, "
            "they mix those versions."
        )
    )
    blocks.append(Subheading("6.3 Each split"))
    split_rows = []
    for split in h["splits"]:
        cells = [split]
        for condition in doc["order"]:
            numbers = h["by_split"][split]["conditions"][condition]
            cells.append(f"{fmt.kn(numbers['exact'])} ({numbers['harmful']['k']} harmful)")
        split_rows.append(cells)
    blocks.append(Table(["Split", *(_label(c) for c in doc["order"])], split_rows, "Each held-out split"))
    without = doc.get("without_land")
    if without:
        blocks.append(Subheading("6.4 The app as it ships: without the sender's Land"))
        rows = []
        days: list[int] = []
        late = 0
        for split, numbers in without["splits"].items():
            if numbers["days_early"]:
                days += numbers["days_early"]
            late += numbers["without_land_late"]
            rows.append(
                [
                    split,
                    fmt.kn(numbers["with_land"]),
                    f"{fmt.kn(numbers['without_land'])} ({fmt.pct(numbers['without_land']['value'])})",
                    fmt.kn(numbers["with_suggestion"]),
                    str(numbers["without_land_late"]),
                ]
            )
        extra = (
            f"every extra miss is {min(days)}{fmt.DASH}{max(days)} days early"
            + ("; none is late." if late == 0 else f"; {late} are late.")
            if days
            else "no date changes."
        )
        blocks += [
            Paragraph(
                "The benchmark gives Ordnung the Land printed on the letterhead. The app knows a sender's Land only "
                "once the person sets it or says Yes to the state Ordnung suggests from the postcode on their letter "
                "([ADR 0019](repo:docs/decisions/0019-a-sender-s-land-is-suggested-never-set.md)); until then it "
                "counts with nationwide holidays and, for a Land authority, the 3-day rule. The same recorded "
                f"readings, replayed that way (`scripts/eval_without_land.py`, {without['date']}, the code of that "
                f"day): {extra}"
            ),
            Table(
                [
                    "Split",
                    "With the letterhead's Land",
                    "Without the sender's Land",
                    "With the suggested state confirmed",
                    "Late without the Land",
                ],
                rows,
                "Ordnung without the sender's Land",
            ),
        ]
    return Section("6. Results", blocks)


def _statistics(doc: Mapping[str, Any]) -> Section:
    h = _headline(doc)
    settings = h["settings"]
    rows = []
    for family, name in (("accuracy", "Exact date right"), ("harmful", "Late or missed"), ("late", "Late")):
        for baseline in [c for c in doc["order"] if c != _REFERENCE]:
            pair = _pair(doc, family, baseline)
            rows.append(
                [
                    name,
                    _label(baseline),
                    f"{pair['b']} vs {pair['c']}",
                    f"{fmt.points(pair['diff'])} [{fmt.interval_points(pair['bonett_price'])}]",
                    fmt.p_value(pair["exact_p"]),
                    fmt.p_value(pair["holm_exact"]),
                    fmt.p_value(pair["midp"]),
                    fmt.p_value(pair["holm_midp"]),
                    fmt.p_value(pair["signflip_p"]),
                    fmt.p_value(pair["signflip_holm"]),
                    verdict(pair, harm=family != "accuracy"),
                ]
            )
    blocks: list[Block] = [
        Paragraph(
            "One interval method per kind of number. A rate: Clopper–Pearson, exact and never degenerate. A paired "
            "comparison on the same deadlines: exact McNemar on the discordant pairs (*b*: only Ordnung right, *c*: "
            "only the baseline right), its mid-p beside it, Holm within each family of three, a Bonett–Price "
            "interval, and a sign-flip test and paired bootstrap over letter clusters (a letter and its photo; "
            f"{settings['signflip_draws']:,} draws and {settings['resamples']:,} resamples, seed {settings['seed']}). "
            f"Verdict: {h['methods']['verdict']}."
        ),
        Chart("differences"),
        Table(
            [
                "Metric",
                "Ordnung vs",
                "b vs c",
                "Difference, points [Bonett–Price 95 %]",
                "Exact p",
                "Holm (exact)",
                "Mid-p",
                "Holm (mid-p)",
                "Cluster sign-flip p",
                "Holm (sign-flip)",
                "Verdict",
            ],
            rows,
            "Paired comparisons with Ordnung",
        ),
    ]
    claim = h.get("rules_text_claim")
    if claim:
        published = claim.get("published_text")
        blocks.append(
            Paragraph(
                "**An earlier claim, corrected.** The README said Ordnung is ahead of the rules-text prompt"
                + (f" by “{published}” (a percentile bootstrap over letters)" if published else "")
                + f". The exact test gives {claim['text']}. Only {claim['b'] + claim['c']} of {claim['n']} deadlines "
                "tell the two apart: a difference of this size needs more letters to be settled."
            )
        )
    changed = _since_0_3_0(doc)
    if changed:
        blocks += [
            Paragraph(
                "**What changed since 0.3.0.** The 0.3.0 README published these numbers for the same three "
                "held-out splits; the methods above replace them (the [history page](repo:docs/evals-history.md) "
                "keeps the page as it was):"
            ),
            Table(["Number", "As 0.3.0 published it", "Now"], changed, "Published numbers since 0.3.0"),
        ]
    crossing = h.get("rules_text_crossover")
    if crossing:
        blocks.append(Paragraph(f"Weighing harm against early dates: {crossing['text']}."))
    blocks.append(Paragraph(f"{h['note']} Labelled **not pre-registered**."))
    return Section("7. Statistics", blocks)


def _since_0_3_0(doc: Mapping[str, Any]) -> list[list[str]]:
    """Each headline number 0.3.0 published for the pooled held-out splits (the re-analysis keeps the scorer's
    interval as ``published_ci`` and ``published_bootstrap``), old beside new."""
    ours = _c(doc, _REFERENCE)
    rows: list[list[str]] = []
    exact = ours["exact"]
    if exact.get("published_ci"):
        rows.append(
            [
                "Ordnung, exact date right",
                f"{fmt.pct(exact['value'])} [{fmt.ci(exact['published_ci'])}] (percentile bootstrap over letters)",
                f"{fmt.pct(exact['value'])} [{fmt.ci(exact['ci'])}] (Clopper–Pearson)",
            ]
        )
        rows.append(
            [
                "Ordnung, the safety count",
                f"{ours['late']['k']} of {ours['late']['n']} dangerously late (a missed deadline left out)",
                f"{ours['harmful']['k']} of {ours['harmful']['n']} late or missed",
            ]
        )
    for baseline in ("llm_only", "llm_rules_text", "llm_rules_tool"):
        pair = _pair(doc, "accuracy", baseline)
        published = pair.get("published_bootstrap")
        if not published or published["value"] is None:
            continue
        rows.append(
            [
                f"Ordnung minus {_label(baseline)}",
                f"{fmt.points(published['value'])} points [{fmt.interval_points(published['ci'])}]",
                f"{fmt.points(pair['diff'])} points [{fmt.interval_points(pair['bonett_price'])}] (Bonett–Price; "
                f"cluster bootstrap {fmt.interval_points(pair['bootstrap'])}), {_exact_p(pair)}: {verdict(pair)}",
            ]
        )
    return rows


def _ablations(doc: Mapping[str, Any]) -> Section:
    blocks: list[Block] = [
        Paragraph(
            "The four conditions are the first ablation: the engine as the one that computes (Ordnung), as a tool "
            "the model may call (the agent), as text (rules text) and not at all (the model alone) "
            "([Summary](#1-summary))."
        ),
        Subheading("Ordnung's code checks, switched off one at a time"),
    ]
    ablation = doc.get("ablation")
    if ablation:
        rows = [
            [
                row["label"],
                f"{row['right']}/{row['scored']}",
                str(row["late"]),
                str(row["missed"]),
                str(row["early"]),
            ]
            for row in ablation["rows"]
        ]
        blocks += [
            Paragraph(
                f"The recorded readings of {fmt.join(ablation['splits'])} replayed with each check switched off "
                f"(`scripts/eval_ablate_checks.py`, `{ablation['file']}`): what each layer prevents."
            ),
            Table(["Configuration", "Exactly right", "Late", "Missed", "Early"], rows, "The check ablation"),
        ]
    else:
        blocks.append(
            Paragraph("No results file of the check ablation yet (`scripts/eval_ablate_checks.py`).")
        )
    ask = doc.get("ask")
    if ask:
        blocks += [
            Subheading("Ask's answer check, on and off"),
            Paragraph(
                f"Of {ask['attacks']} letters with injected text, an injected claim reached the answer "
                f"{fmt.of(ask['attack_success_raw'])} times without Ask's answer check and "
                f"{fmt.of(ask['attack_success'])} with it ([the Ask benchmark](repo:docs/evals-ask.md), a "
                "development set, not held out)."
            ),
        ]
    return Section("8. Ablations", blocks)


def _robustness(doc: Mapping[str, Any]) -> Section:
    h = _headline(doc)
    rows = [
        [row["label"], f"{row['k']}/{row['n']} ({fmt.pct(row['value'])})", fmt.ci(row["ci"])]
        for row in h["adversarial_classes"]
        if row["n"]
    ]
    modality = []
    for condition in doc["order"]:
        numbers = _c(doc, condition)["modality"]
        modality.append(
            [_label(condition)]
            + [
                f"{fmt.kn(numbers[kind])} ({fmt.pct(numbers[kind]['value'])}) [{fmt.ci(numbers[kind]['ci'])}]"
                for kind in ("text", "photo")
            ]
        )
    return Section(
        "9. Robustness",
        [
            Paragraph(
                f"Adversarial letters in the held-out splits ({h['adversarial']} of {h['letters']}): Ordnung, by "
                "class, with 95 % Clopper–Pearson intervals. The classes are small; read the intervals."
            ),
            Table(["Class", "Ordnung", "95 % CI"], rows, "Adversarial letters, Ordnung"),
            Paragraph(
                "Text PDFs against phone photos, every condition (a photo is read by the model first):"
            ),
            Table(
                ["Condition", "Text PDFs [95 % CI]", "Phone photos [95 % CI]"], modality, "Text against photo"
            ),
            Paragraph(
                "Not yet run: the targeted injections and distractor dates of the planned stress cells, to be "
                "pre-registered with the final run (`scripts/eval_perturb.py`), on held-out letters re-rendered with "
                "one planted paragraph each."
            ),
        ],
    )


def _safety(doc: Mapping[str, Any]) -> Section:
    harm_rows, flag_rows, loss_rows = [], [], []
    ratios: list[str] = []
    for condition in doc["order"]:
        c = _c(doc, condition)
        selective = c["selective"]
        days = ", ".join(str(day) for day in c["days_late"]) or "none"
        harm_rows.append(
            [
                _label(condition),
                f"{fmt.kn(c['harmful'])} [{fmt.ci(c['harmful']['ci'])}]",
                str(c["late"]["k"]),
                str(c["missed"]["k"]),
                days,
            ]
        )
        unflagged = selective["unflagged"]
        flag_rows.append(
            [
                _label(condition),
                fmt.of(selective["please_check"]["recall_wrong"]),
                fmt.of(selective["any_flag"]["recall_wrong"]),
                f"{fmt.kn(unflagged['accuracy'])} ({fmt.pct(unflagged['accuracy']['value'])})",
                fmt.kn(unflagged["harmful"]),
                f"{selective['aurc']['aurc']:.4f} ({selective['aurc']['excess']:.4f})",
                f"{selective['auroc']:.2f}",
            ]
        )
        ratios = list(c["loss"])
        loss_rows.append([_label(condition), *(f"{c['loss'][r]:.1f}" for r in ratios)])
    flags = _headline(doc)["flags"]
    shows = (
        f"Ordnung's “Please check” caught {flags['caught']} of its {flags['wrong']} wrong dates: it is safer because "
        "it makes fewer errors, not because it flags them."
        if flags["caught"] == 0
        else f"Ordnung's “Please check” caught {flags['caught']} of its {flags['wrong']} wrong dates."
    )
    blocks: list[Block] = [
        Table(
            ["Condition", "Late or missed [95 % CI]", "Late", "Missed", "Days late, each"],
            harm_rows,
            "Harmful dates",
        ),
        Chart("risk-coverage"),
        Paragraph(shows),
        Table(
            [
                "Condition",
                "Wrong dates “Please check” caught",
                "Wrong dates any flag caught",
                "Without a flag: right (a missed deadline counts here)",
                "Without a flag: late or missed",
                "AURC (excess over a perfect flag)",
                "AUROC",
            ],
            flag_rows,
            "Flags and selective prediction",
        ),
        Paragraph(
            "Harm-weighted loss per 100 deadlines, early + r × harmful, for a harmful date that costs r early ones:"
        ),
        Table(["Condition", *(f"r = {r}" for r in ratios)], loss_rows, "Harm-weighted loss"),
    ]
    crossing = _headline(doc).get("rules_text_crossover")
    if crossing:
        blocks.append(Paragraph(f"{crossing['text']}."))
    return Section("10. Safety and selective prediction", blocks)


def _failures(doc: Mapping[str, Any]) -> Section:
    errors = _headline(doc)["errors"]
    rank = {c: i for i, c in enumerate(doc["order"])}

    def harmful(row: Mapping[str, Any]) -> bool:
        return bool(row["outcome"] == "missed" or row["direction"] == "late")

    chosen = sorted(
        (row for row in errors if harmful(row) or row["condition"] == _REFERENCE),
        key=lambda row: (
            not harmful(row),
            rank[row["condition"]],
            row["split"],
            row["entry_id"],
            row["item"],
        ),
    )
    rows = [
        [
            f"`{row['entry_id']}`",
            _label(row["condition"]),
            row["family"],
            row["modality"],
            _OUTCOMES.get(row["outcome"], row["outcome"])
            + (f", {row['direction']}" if row["direction"] else ""),
            "" if row["days_off"] is None else f"{row['days_off']:+d}".replace("-", fmt.MINUS),
            row["confidence"] or "none",
            row["tier"].replace("_", " "),
            row["cause"] or ("not found" if row["outcome"] == "missed" else "n/a"),
        ]
        for row in chosen
    ]
    ours = [row for row in errors if row["condition"] == _REFERENCE]
    causes = {cause: sum(1 for row in ours if row["cause"] == cause) for cause in ("reading", "computing")}
    missed = sum(1 for row in ours if row["outcome"] == "missed")
    return Section(
        "11. Failure analysis",
        [
            Paragraph(
                "Every harmful error first (late or missed, every condition), then Ordnung's other wrong dates. Ids, "
                "classes and days only: never a letter's text."
            ),
            Table(
                [
                    "Letter",
                    "Condition",
                    "Family",
                    "Text or photo",
                    "Outcome",
                    "Days off",
                    "Confidence",
                    "Flag",
                    "Cause",
                ],
                rows,
                "Harmful errors and Ordnung's errors",
            ),
            Paragraph(
                f"Of Ordnung's {len(ours)} errors, {causes['reading']} came from the reading, {causes['computing']} "
                f"from computing and {missed} {'was a deadline' if missed == 1 else 'were deadlines'} not found."
            ),
        ],
    )


def _cost(doc: Mapping[str, Any]) -> Section:
    header, rows = charts.table("cost", doc)
    costs = {c: _c(doc, c)["cost"] for c in doc["order"]}
    dearest = max(costs, key=lambda c: costs[c]["usd_per_letter"])
    cheapest = min(costs, key=lambda c: costs[c]["usd_per_right_date"])
    said = (
        f"{_label(dearest)} is the dearest condition per letter ({fmt.usd(costs[dearest]['usd_per_letter'])})"
        + (
            ": it also writes a summary, key facts and a checked quote for every letter."
            if dearest == _REFERENCE
            else "."
        )
        + f" The cheapest per right date is {_label(cheapest)} ({fmt.usd(costs[cheapest]['usd_per_right_date'])})."
    )
    return Section(
        "12. Cost and latency",
        [
            Chart("cost"),
            Table(header, rows, "Cost and latency"),
            Paragraph(
                said
                + " Prices are API-equivalent, as the Claude CLI reports them; latency is the model's time per "
                "letter."
            ),
        ],
    )


def _e2e(doc: Mapping[str, Any]) -> Section:
    e2e = doc.get("e2e")
    if not e2e:
        return Section(
            "13. From a letter to a reminder",
            [Paragraph("No results file of the end-to-end run yet (`python -m evals.e2e`).")],
        )
    causes = (
        "; ".join(
            f"{_CAUSES.get(cause, f'`{cause}`')}: {count}" for cause, count in e2e["not_reminded"].items()
        )
        or "none"
    )
    reminded = e2e["reminded_in_time"]
    blocks: list[Block] = [
        Paragraph(
            f"Every letter of {fmt.join(e2e['splits'])} read by the real app in a fresh data folder, from the "
            f"recorded readings, through to the calendar and the morning note (`python -m evals.e2e`, "
            f"`{e2e['file']}`): {fmt.of(reminded)} genuine dated obligations got a reminder in time "
            f"({fmt.pct(reminded['value'])}); {e2e['late_reminders']} got one only after the deadline. The stored "
            f"dates equal the replay without the sender's Land for {e2e['parity']['k']} of {e2e['parity']['n']}."
        ),
        Paragraph(f"Not reminded, by cause: {causes}."),
    ]
    scam = e2e.get("scam")
    if scam:
        kept = scam["kept_off_the_calendar"]
        placed = scam["in_the_calendar"]
        listed = fmt.join(
            [
                f"`{row['entry_id']}` ({row['events']} event{'' if row['events'] == 1 else 's'})"
                for row in placed
            ]
        )
        calendar = (
            f"{len(placed)} of {scam['letters']} scam letters still put their demands in the calendar: {listed}; "
            f"{fmt.of(kept)} kept them off it (95 % CI {fmt.ci(kept['ci'])})"
            if placed
            else f"Every one of the {scam['letters']} scam letters kept its demands off the calendar (95 % CI "
            f"{fmt.ci(kept['ci'])})"
        )
        unwarned = scam["without_scam_idea"]
        warned = (
            f"{len(unwarned)} of the {scam['letters']} got no scam warning "
            f"({fmt.join([f'`{entry}`' for entry in unwarned])})"
            if unwarned
            else f"All {scam['letters']} got a scam warning"
        )
        false = scam["false_scam_idea"]
        blocks.append(
            Paragraph(
                f"{calendar}. {warned}. {fmt.of(false)} genuine letters got a scam warning by mistake (95 % CI "
                f"{fmt.ci(false['ci'])})."
            )
        )
    return Section("13. From a letter to a reminder", blocks)


def _limitations(doc: Mapping[str, Any]) -> Section:
    claim = _headline(doc).get("rules_text_claim")
    items = [
        "The letters are synthetic, one or two clean pages each: real post is messier.",
        "The held-out splits were recorded with the code and prompts of their day; pooled, they mix versions.",
        "These statistics were chosen after the results were known: **not pre-registered**. The final run will be "
        "pre-registered before it is recorded.",
        "One read per letter: run-to-run noise is not measured yet (the final run reads each letter three times).",
        "The labels are code, audited by agents of the same model family; no lawyer reviewed the rules.",
        "The letter families leave out the rarer high-stakes kinds the engine covers; the final run adds a small set "
        "of new kinds.",
        "The benchmark gives Ordnung the Land on the letterhead; the app counts without it until the person sets or "
        "confirms it ([Results](#6-results), 6.4).",
    ]
    if claim:
        items.append(
            f"Small numbers: against the rules-text prompt only {claim['b'] + claim['c']} deadlines disagree."
        )
    items += [
        "Ask is measured on the demo's own sample life, a development set, not held out.",
        f"One model: `{MODEL}`.",
    ]
    return Section("14. Limitations", [Bullets(items)])


def _reproduce(doc: Mapping[str, Any]) -> Section:
    return Section(
        "15. Reproduce",
        [
            Paragraph(
                "With no API key and no tokens, from a source checkout (`pip install -e '.[dev]'`), one command "
                "replays every split, condition, Ask set, end-to-end run and ablation that has a recording, checks "
                "the analysis and these pages, and compares every number with the [results "
                "index](repo:evals/results/INDEX.json): each file's hash, role and replay verdict, a digest of "
                "every number the replay gives, and every date or count the code changed since its recording with "
                "the fix that changed it. The per-item results are in "
                "[items.csv](repo:evals/results/items.csv) (ids, dates and outcomes only)."
            ),
            Code(["make eval-reproduce                  # python -m evals.reproduce --check; CI runs it"]),
            Paragraph("Its parts, one at a time:"),
            Code(
                [
                    "python -m evals.present --check      # this page, the README block, the history page, the charts",
                    "python -m evals.analysis --check     # the re-analysis every number here comes from",
                    "ordnung eval --split holdout3 --results-dir /path/to/replay   # a split replayed (any split)",
                    "python -m scripts.eval_without_land --out /path/to/replay   # the app without the sender's Land",
                    "python -m evals.ask                  # the Ask benchmark, replayed",
                    "python -m evals.present --site /path/to/site   # the report page",
                ]
            ),
            Paragraph(
                f"Recording costs tokens: `python -m evals.run --live --split <split> --model {MODEL}` records "
                "answers the replays above then reuse; the [history page](repo:docs/evals-history.md) states what "
                "each recording cost."
            ),
            Paragraph(
                "More: [every earlier run](repo:docs/evals-history.md) · [the Ask benchmark](repo:docs/evals-ask.md) "
                "· [the results files](repo:evals/results)."
            ),
        ],
    )


def sections(doc: Mapping[str, Any]) -> list[Section]:
    """The report's sections, in the order an expert reads them."""
    return [
        _card(doc),
        _summary(doc),
        _task(doc),
        _data(doc),
        _conditions(doc),
        _metrics(doc),
        _results(doc),
        _statistics(doc),
        _ablations(doc),
        _robustness(doc),
        _safety(doc),
        _failures(doc),
        _cost(doc),
        _e2e(doc),
        _limitations(doc),
        _reproduce(doc),
    ]


# --------------------------------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------------------------------


def inline_markdown(value: str, prefix: str) -> str:
    """Inline markup for a Markdown file at ``prefix`` from the repository's root (``docs/``, or ``""``)."""

    def target(match: re.Match[str]) -> str:
        path = match.group(2)
        relative = path.removeprefix(prefix) if path.startswith(prefix) else "../" * prefix.count("/") + path
        return f"]({relative})"

    return re.sub(r"\]\((repo:)([^)]+)\)", lambda m: target(m), value)


def _cell(value: str) -> str:
    return value.replace("|", "\\|")


def _markdown_blocks(blocks: Sequence[Block], doc: Mapping[str, Any], prefix: str) -> list[str]:
    out: list[str] = []
    for block in blocks:
        if isinstance(block, Paragraph):
            out.append(_wrap(inline_markdown(block.text, prefix)))
        elif isinstance(block, Bullets):
            out.append(
                "\n".join(fill(inline_markdown(item, prefix), first="- ", rest="  ") for item in block.items)
            )
        elif isinstance(block, Table):
            lines = [
                "| " + " | ".join(_cell(h) for h in block.header) + " |",
                "|" + "|".join("---" for _ in block.header) + "|",
                *(
                    "| " + " | ".join(_cell(inline_markdown(c, prefix)) for c in row) + " |"
                    for row in block.rows
                ),
            ]
            out.append("\n".join(lines))
        elif isinstance(block, Chart):
            alt = charts.description(block.name, doc).replace('"', "'")
            out.append(
                f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/eval-{block.name}-dark.svg">'
                f'<img src="assets/eval-{block.name}-light.svg" width="{charts.WIDE}" alt="{alt}"></picture>'
            )
        elif isinstance(block, Code):
            out.append("```bash\n" + "\n".join(block.lines) + "\n```")
        else:
            out.append(f"### {block.text}")
    return out


def report(doc: Mapping[str, Any]) -> str:
    """``docs/evals.md``."""
    h = _headline(doc)
    parts = [
        f"# {REPORT_TITLE}",
        _wrap(
            f"> Generated by `python -m evals.present` from `evals/results` (the headline: `{h['source']['file']}`, "
            f"{h['label'].lower()}, not pre-registered). Do not edit by hand: change `evals/present/` and run "
            f"`python -m evals.present --write`. The same report as a page: [{PAGES_URL}]({PAGES_URL})."
        ).replace("\n", "\n> "),
    ]
    for section in sections(doc):
        parts.append(f"## {section.title}")
        parts += _markdown_blocks(section.blocks, doc, "docs/")
    return "\n\n".join(parts) + "\n"


# --------------------------------------------------------------------------------------------------
# The history page
# --------------------------------------------------------------------------------------------------

ROLE_MEANINGS = (
    ("final", "a run of the pre-registered final evaluation"),
    ("held-out", "the one recording of a held-out split: nothing was tuned on it"),
    ("re-analysis", "held-out recordings analysed again after their results were known (not pre-registered)"),
    ("re-scored", "a held-out split's recordings replayed with later code: not held-out"),
    ("iterated", "the dev and test splits, tuned or iterated on, and Ask's development set"),
    (
        "replay",
        "the recordings replayed another way (without the sender's Land, the check ablation, end to end)",
    ),
    ("archive", "a run on an earlier model than the pinned one: listed by date only, never charted"),
)
_KINDS = {
    "run": "reading benchmark",
    "ask": "Ask benchmark",
    "analysis": "analysis",
    "without-land": "replay without the sender's Land",
    "checks-ablated": "check ablation",
    "e2e": "end to end",
}


def history(doc: Mapping[str, Any], legacy: str) -> str:
    """``docs/evals-history.md``: every results file with its role, then the runs as ``docs/evals.md`` published
    them up to 0.3.0 (``legacy``: ``evals.report``'s page, rendered from the same files as then)."""
    rows = []
    for row in doc["files"]:
        archive = row["role"] == "archive"
        rows.append(
            [
                row["date"],
                f"`{row['file']}`",
                _KINDS[row["kind"]],
                row["split"] or "",
                row["role"],
                ""
                if archive or not row["conditions"]
                else ", ".join(_label(c) for c in row["conditions"] if c in palette.LABELS),
                "earlier model" if archive else (fmt.kn(row["ordnung"]) if row["ordnung"] else ""),
            ]
        )
    table = "\n".join(
        [
            "| Date | File | What | Split | Role | Conditions | Ordnung exactly right |",
            "|---|---|---|---|---|---|---|",
            *("| " + " | ".join(_cell(c) for c in row) + " |" for row in rows),
        ]
    )
    roles = "\n".join(f"- **{role}**: {meaning}." for role, meaning in ROLE_MEANINGS)
    body = legacy.split("\n", 1)[1] if legacy.startswith("# ") else legacy
    parts = [
        f"# {HISTORY_TITLE}",
        _wrap(
            "> The lab notebook: every benchmark run and re-scoring, in the order it happened, with the page "
            "`docs/evals.md` was until 0.3.0. The current report is [docs/evals.md](evals.md); only its held-out "
            "and final numbers are headlines. Generated by `python -m evals.present` from `evals/results`; do not "
            "edit by hand."
        ).replace("\n", "\n> "),
        "## Every results file",
        "Each file's role says what it may support:",
        roles,
        table,
        "## The page as published up to 0.3.0",
        body.strip(),
    ]
    return "\n\n".join(parts) + "\n"


def site_link(value: str) -> str:
    """A ``repo:`` target as the report page links it: the file on GitHub."""
    path = value.removeprefix("repo:")
    return f"{REPO_URL}/blob/main/{quote(path)}"
