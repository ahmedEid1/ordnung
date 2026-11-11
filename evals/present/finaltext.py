"""The final run's parts of docs/evals.md and the report page (standard library only), from ``presentation.json``'s
``final`` alone.

Each part is either a registered sentence (``final.sentences``, coded by :mod:`evals.present.final`'s rules), a view
template (``final.views``, :mod:`evals.present.views`) filled with values, a condition's name, an id or a code, or a
number; nothing here is worded in code. With a final run:

* the report's header names the final analysis, and the evaluation card says how the final run was pre-registered, read
  and analysed;
* section 1 is the README's registered paragraph with the final run's chart, a table of each condition over the reads,
  and the verdict table: each pre-registered comparison with its numbers, its role, the analysis's decision code and
  the code of the registered sentence that says it;
* section 6.1 is every registered page sentence, in its order, between :data:`evals.present.final.PAGE_BEGIN` and
  :data:`~evals.present.final.PAGE_END`, then each read's numbers, how steady the dates are (two reads or more), the
  reads not recorded with the deviations that say why, the sensitivity analyses beside the primary, and the new kinds;
* section 7 is the final run's statistics: the forest of the comparisons with its table, the non-inferiority bound and
  the stability test; the earlier held-out splits' statistics follow under their own heading, not pre-registered;
* section 11 opens with the final run's failures by id, every late or missed date first; section 14 says the
  limitations a final run leaves; sections 16 and 17 list every deviation as recorded and where every number comes
  from;
* the sections that show only the earlier held-out splits carry a note that they are as recorded, not pre-registered.

:mod:`evals.present.text` calls these only when ``doc["final"]`` is set.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from evals.present import PAGES_URL, charts, final, finalcharts, fmt, palette, views
from evals.present.final import PAGE_BEGIN, PAGE_END
from evals.present.finalcharts import NONE, WHERE, code, pair_key, points, shown
from evals.present.text import Block, Chart, Marker, Paragraph, Section, Subheading, Table, slug

#: The evaluation card's rows with a final run, in order: the ones every card has (``text``'s) and the final run's.
CARD = (
    "task",
    "model",
    "data",
    "primary",
    "safety",
    "protocol",
    "prereg",
    "reads",
    "intervals",
    "replay",
    "sources",
    "newest",
)
#: The anchors the final run's parts link to (the report's sections 3, 6 and 7) and the final run's subsection.
DATA_ANCHOR, RESULTS_ANCHOR, STATISTICS_ANCHOR = "#3-data-and-labels", "#6-results", "#7-statistics"
FINAL_SUBSECTION = "6.1"
#: The sections a final run adds after section 15, by number.
DEVIATIONS_SECTION, PROVENANCE_SECTION = 16, 17
#: The comparisons the verdict table shows, by the registered slot that says each: its family (or the agent's
#: non-inferiority bound) and its baseline, in the registered order of the slots.
VERDICTS = {
    "head": ("F1_accuracy", "llm_only"),
    "rules_text": ("F1_accuracy", "llm_rules_text"),
    "agent": ("noninferiority", final.AGENT),
    "f2.llm_only": ("F2_harm", "llm_only"),
    "f2.llm_rules_text": ("F2_harm", "llm_rules_text"),
    "f2.llm_rules_tool": ("F2_harm", final.AGENT),
    "stability": ("F3_stability", "llm_only"),
}
#: The analysis's decision on stability (against the model alone).
STABILITY = "more_stable_than_llm_only"
#: The codes of a slot's sentences that say no decision (the head's opening and its count of deviations).
_NOT_DECISIONS = ("intro", "deviations")
#: Where the report's provenance shows ``presentation.json``.
PRESENTATION = "evals/present/presentation.json"
#: The final analysis's inputs that are the final run's reads (the earlier splits pooled with them are not).
FINAL_INPUTS = ("primary", "secondary", "left_out")


def _final(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    shown: Mapping[str, Any] = doc["final"]
    return shown


def view(doc: Mapping[str, Any], key: str, **values: object) -> views.Filled:
    """The view template ``key`` of ``doc``'s final run, filled."""
    return views.fill(_final(doc)["views"], key, **values)


def lede(doc: Mapping[str, Any]) -> str:
    """The report's header with a final run: it names the final analysis as the headline."""
    return view(doc, "report.lede", source=_final(doc)["source"]["file"], pages=PAGES_URL)


def card_rows(doc: Mapping[str, Any], common: Mapping[str, Sequence[str]]) -> list[list[str]]:
    """The evaluation card of the final run: ``common`` (the rows every card has) and the final run's own."""
    shown = _final(doc)
    reads = [row for row in shown["inputs"] if row["role"] in FINAL_INPUTS]
    registered = shown["prereg"]["registered"]
    if reads:
        newest = max(reads, key=lambda row: str(row["date"]))
        sources = view(
            doc,
            "card.sources",
            source=shown["source"]["file"],
            inputs=fmt.join([f"`{row['file']}`" for row in reads]),
        )
        recorded = view(
            doc, "card.newest", split=newest["split"], date=newest["date"], commit=newest["commit"]
        )
    else:
        sources = view(doc, "card.sources.alone", source=shown["source"]["file"])
        recorded = view(doc, "card.newest.alone", date=shown["date"])
    own = {
        "data": view(
            doc,
            "card.data",
            letters=shown["letters"],
            split=shown["split"],
            items=shown["items"],
            clusters=shown["clusters"],
        ),
        "protocol": view(doc, "card.protocol", anchor=DATA_ANCHOR),
        "prereg": view(
            doc,
            "card.prereg",
            file=shown["prereg"]["file"],
            hash=shown["prereg"]["sha256"][:12],
            freeze=str(registered["freeze_sha"])[:12],
            pr=registered["freeze_pr"],
        ),
        "reads": view(doc, "card.reads", used=len(shown["reads_used"]), registered=shown["reads_registered"]),
        "intervals": view(doc, "card.intervals", anchor=STATISTICS_ANCHOR),
        "sources": sources,
        "newest": recorded,
    }
    return [
        list(common[key]) if key in common else [view(doc, f"card.{key}.label"), own[key]] for key in CARD
    ]


def summary(doc: Mapping[str, Any]) -> list[Block]:
    """Section 1 with a final run: the README's registered paragraph (its sentences, laid out as the registered
    ``readme_layout`` lays out the paragraph) and the final run's chart."""
    shown = _final(doc)
    paragraph = shown["layout"]["readme_layout"]["paragraph"]
    said = shown["sentences"]["readme"]
    texts = [sentence["text"] for slot in paragraph for sentence in said if sentence["slot"] == slot]
    return [Paragraph(" ".join(texts)), Chart("final"), _conditions(doc), _verdicts(doc)]


def _conditions(doc: Mapping[str, Any]) -> Table:
    """Each condition over the final run's reads: the mean of the exact dates right with its interval, each read's,
    the late or missed dates over the reads and the dates right in every read."""
    shown_ = _final(doc)
    rows = []
    for condition in doc["order"]:
        summary = shown_["conditions"][condition]
        mean, harmful = summary["mean_accuracy"], summary["harmful_per_read"]
        rows.append(
            [
                palette.LABELS[condition],
                f"{fmt.pct(mean['value'])} [{fmt.ci(mean['ci'])}]",
                " · ".join(fmt.kn(rate) for rate in summary["exact_per_read"]),
                f"{sum(int(rate['k']) for rate in harmful)}/{sum(int(rate['n']) for rate in harmful)}",
                fmt.kn(summary["pass_all"]),
            ]
        )
    header = [
        view(doc, "summary.col.condition"),
        view(doc, "summary.col.mean", level=_level(doc)),
        view(doc, "summary.col.reads"),
        view(doc, "summary.col.harm"),
        view(doc, "summary.col.all"),
    ]
    return Table(header, rows, view(doc, "summary.caption"))


def _level(doc: Mapping[str, Any]) -> str:
    return final._formatted(_final(doc)["settings"]["level"], "percent_number", WHERE)


def _margin(doc: Mapping[str, Any]) -> str:
    return final._formatted(_final(doc)["settings"]["noninferiority_margin"], "percent_number", WHERE)


def _p(value: float) -> str:
    """A p-value as the registered sentences print it after "Holm p"."""
    return final._formatted(value, "p", WHERE)


def _bound(doc: Mapping[str, Any], low: float, high: float) -> str:
    """An interval in points, ``[lo, hi]``, or the view template that says no deadline differs (never 0 to 0)."""
    if low == 0 and high == 0:
        return view(doc, "interval.none")
    return f"[{points(low)}, {points(high)}]"


def _sentence_code(doc: Mapping[str, Any], slot: str) -> str:
    """The code of the registered sentence that says a slot's decision."""
    codes = [
        sentence["code"]
        for sentence in _final(doc)["sentences"]["page"]
        if sentence["slot"] == slot and sentence["code"].split(".")[1] not in _NOT_DECISIONS
    ]
    return f"`{codes[0]}`"


def _verdicts(doc: Mapping[str, Any]) -> Table:
    """The verdict table: each pre-registered comparison, in the registered order of its slot, with what it compares
    and how it is tested (view templates), its numbers, its role, the analysis's decision and the registered sentence
    that says it."""
    shown_ = _final(doc)
    order = list(dict.fromkeys(sentence["slot"] for sentence in shown_["sentences"]["page"]))
    rows = [_verdict(doc, slot, *VERDICTS[slot]) for slot in order if slot in VERDICTS]
    header = [
        view(doc, f"verdict.col.{name}")
        for name in ("comparison", "test", "result", "role", "decision", "sentence")
    ]
    return Table(header, rows, view(doc, "verdict.caption"))


def _verdict(doc: Mapping[str, Any], slot: str, family: str, baseline: str) -> list[str]:
    shown_ = _final(doc)
    label = palette.LABELS[baseline]
    sentence = _sentence_code(doc, slot)
    decisions, roles = shown_["decisions"], shown_["decision_roles"]
    if family == "noninferiority":
        bound = shown_["noninferiority"][pair_key(baseline)]
        key = finalcharts.DECISIONS[("F1_accuracy", baseline)]
        comparison = view(doc, "verdict.comparison.noninferiority", baseline=label, margin=_margin(doc))
        test = view(doc, "verdict.test.noninferiority", level=_level(doc))
        result: str = view(
            doc,
            "verdict.result.noninferiority",
            d=points(shown_["families"]["F1_accuracy"][pair_key(baseline)]["diff"]),
            level=_level(doc),
            bound=_bound(doc, bound["lo"], bound["hi"]),
            margin=_margin(doc),
        )
    elif family == "F3_stability":
        key = STABILITY
        rows = shown_["families"]["F3_stability"]
        comparison = view(doc, "verdict.comparison.stability", baseline=label)
        test = view(doc, "verdict.test.mcnemar")
        if rows is None:
            result = view(doc, "verdict.result.not_run")
        else:
            row = rows[pair_key(baseline)]
            result = view(doc, "verdict.result.stability", b=row["b"], c=row["c"], p=_p(row["holm"]))
    else:
        row = shown_["families"][family][pair_key(baseline)]
        part = "accuracy" if family == "F1_accuracy" else "harm"
        comparison = view(doc, f"verdict.comparison.{part}", baseline=label)
        if (family, baseline) not in finalcharts.DECISIONS:
            # described, not tested: no decision and no role
            return [comparison, view(doc, "verdict.test.described"), shown(doc, row), NONE, NONE, sentence]
        key = finalcharts.DECISIONS[(family, baseline)]
        test = view(doc, "verdict.test.signflip")
        result = view(doc, "verdict.result", shown=shown(doc, row), p=_p(row["holm"]))
    return [comparison, test, result, code(roles.get(key)), code(decisions.get(key)), sentence]


def final_run(doc: Mapping[str, Any]) -> list[Block]:
    """Subsection 6.1 with a final run: its lead, then every registered page sentence in ``page_block`` order between
    the page's markers, one paragraph per slot, and nothing else between them."""
    blocks: list[Block] = [
        Subheading(view(doc, "results.final.heading", number=FINAL_SUBSECTION)),
        Paragraph(view(doc, "results.final.lead")),
        Marker(PAGE_BEGIN),
    ]
    slots: list[tuple[str, list[str]]] = []
    for sentence in _final(doc)["sentences"]["page"]:
        if slots and slots[-1][0] == sentence["slot"]:
            slots[-1][1].append(sentence["text"])
        else:
            slots.append((sentence["slot"], [sentence["text"]]))
    blocks += [Paragraph(" ".join(texts)) for _, texts in slots]
    blocks.append(Marker(PAGE_END))
    blocks.append(_reads(doc))
    if finalcharts.stable(doc):
        blocks += _chart(doc, "final-stability")
    blocks += _missing(doc)
    blocks += _sensitivities(doc)
    blocks += _newkinds(doc)
    return blocks


def _reads(doc: Mapping[str, Any]) -> Table:
    """Each read of the final run: per condition, the exact dates right and the late or missed ones."""
    shown_ = _final(doc)
    header = [view(doc, "results.final.reads.col.condition")]
    for read in shown_["reads_used"]:
        header += [
            view(doc, "results.final.reads.col.exact", read=read),
            view(doc, "results.final.reads.col.harm", read=read),
        ]
    rows = []
    for condition in doc["order"]:
        summary = shown_["conditions"][condition]
        cells = [palette.LABELS[condition]]
        for exact, harmful in zip(summary["exact_per_read"], summary["harmful_per_read"], strict=True):
            cells += [f"{fmt.kn(exact)} ({fmt.pct(exact['value'])})", fmt.kn(harmful)]
        rows.append(cells)
    return Table(header, rows, view(doc, "results.final.reads.caption"))


def _codes(values: Sequence[Any]) -> str:
    return ", ".join(f"`{value}`" for value in values) or NONE


def _missing(doc: Mapping[str, Any]) -> list[Block]:
    """The pre-registered reads not recorded, each with the kind and id of the deviation recorded at the time."""
    shown_ = _final(doc)
    if not shown_["reads_missing"]:
        return []
    rows = [
        [str(row["read"]), _codes(row["kinds"]), _codes(row["deviations"])] for row in shown_["reads_missing"]
    ]
    header = [view(doc, f"results.final.missing.col.{name}") for name in ("read", "kinds", "deviations")]
    lead = view(
        doc,
        "results.final.missing.lead",
        used=len(shown_["reads_used"]),
        registered=shown_["reads_registered"],
    )
    return [Paragraph(lead), Table(header, rows, view(doc, "results.final.missing.caption"))]


def _stability_cell(doc: Mapping[str, Any], rows: Mapping[str, Any] | None) -> str:
    if rows is None:
        return NONE
    row = rows[pair_key("llm_only")]
    return view(doc, "results.final.sens.stability", b=row["b"], c=row["c"], p=fmt.p_value(row["holm"]))


def _sensitivities(doc: Mapping[str, Any]) -> list[Block]:
    """Each sensitivity analysis under its own label, beside the primary analysis and never in its place: the
    deadlines it changes, each side's exact dates, its decisions and the deviations it applies."""
    shown_ = _final(doc)
    conditions = shown_["conditions"]
    alike = view(doc, "results.final.sens.same")
    rows = [
        [
            view(doc, "results.final.sens.primary"),
            NONE,
            fmt.pct(conditions["ordnung"]["mean_accuracy"]["value"]),
            fmt.pct(conditions["llm_only"]["mean_accuracy"]["value"]),
            code(shown_["decisions"]["beats_llm_only"]),
            _stability_cell(doc, shown_["families"]["F3_stability"]),
            NONE,
        ]
    ]
    for name, block in shown_["sensitivities"].items():
        primary = bool(block.get("same_as_primary"))
        items = block.get("items_changed", block.get("items"))
        if "not_run" in block:
            exact = [view(doc, "results.final.sens.not_run"), NONE]
        elif "conditions" in block:
            exact = [fmt.pct(block["conditions"][c]["mean_accuracy"]) for c in ("ordnung", "llm_only")]
        else:
            exact = [alike, alike] if primary else [NONE, NONE]
        if "decisions" in block:
            accuracy = code(block["decisions"].get("beats_llm_only"))
        else:
            accuracy = alike if primary else NONE
        if "F3_stability" in block:
            stability = _stability_cell(doc, block["F3_stability"])
        else:
            stability = alike if primary else NONE
        rows.append(
            [
                view(doc, f"results.final.sens.{name}"),
                NONE if items is None else str(items),
                *exact,
                accuracy,
                stability,
                _codes(block.get("deviations") or []),
            ]
        )
    header = [
        view(doc, f"results.final.sens.col.{column}")
        for column in ("analysis", "items", "ordnung", "alone", "accuracy", "stability", "deviations")
    ]
    return [
        Paragraph(view(doc, "results.final.sens.lead")),
        Table(header, rows, view(doc, "results.final.sens.caption")),
    ]


def _newkinds(doc: Mapping[str, Any]) -> list[Block]:
    """The letters of new kinds, read once and described: each condition's exact dates and late or missed ones, or
    the read not recorded with its deviation."""
    shown_ = _final(doc)
    newkinds = shown_["newkinds"]
    missing = newkinds.get("not_recorded")
    if missing is not None:
        return [
            Paragraph(
                view(
                    doc,
                    "results.final.newkinds.not_recorded",
                    read=missing["read"],
                    kinds=_codes(missing["kinds"]),
                    deviations=_codes(missing["deviations"]),
                )
            )
        ]
    rows = []
    for condition in doc["order"]:
        exact, harmful = (newkinds["conditions"][condition][key] for key in ("exact", "harmful"))
        rows.append(
            [
                palette.LABELS[condition],
                f"{fmt.kn(exact)} ({fmt.pct(exact['value'])}) [{fmt.ci(exact['ci'])}]",
                fmt.kn(harmful),
            ]
        )
    header = [
        view(doc, "results.final.newkinds.col.condition"),
        view(doc, "results.final.newkinds.col.exact", level=_level(doc)),
        view(doc, "results.final.newkinds.col.harm"),
    ]
    return [
        Paragraph(
            view(doc, "results.final.newkinds.lead", letters=newkinds["letters"], items=newkinds["items"])
        ),
        Table(header, rows, view(doc, "results.final.newkinds.caption")),
    ]


def _chart(doc: Mapping[str, Any], name: str) -> list[Block]:
    """A final chart and its table twin (the page puts the table behind the chart; the Markdown report shows both)."""
    header, rows = charts.table(name, doc)
    return [Chart(name), Table(header, rows, view(doc, f"chart.{name}.table"))]


def statistics(doc: Mapping[str, Any]) -> list[Block]:
    """Section 7's final run: how it was analysed, the forest of the pre-registered comparisons with its table, the
    non-inferiority bound against the agent and the stability test (the earlier held-out splits follow it)."""
    settings = _final(doc)["settings"]
    lead = view(
        doc,
        "stats.lead",
        draws=f"{int(settings['signflip_draws']):,}",
        resamples=f"{int(settings['resamples']):,}",
        seed=settings["seed"],
        margin=_margin(doc),
    )
    return [Paragraph(lead), *_chart(doc, "final-differences"), _noninferiority(doc), *_stability(doc)]


def _noninferiority(doc: Mapping[str, Any]) -> Table:
    rows = [
        [
            palette.LABELS[pair.split("-vs-", 1)[1]],
            _margin(doc),
            points(block["estimate"]),
            _bound(doc, block["lo"], block["hi"]),
            str(block["errors"]["ours"]),
            str(block["errors"]["theirs"]),
            code(block["decision"]),
        ]
        for pair, block in _final(doc)["noninferiority"].items()
    ]
    header = [
        view(doc, "stats.noninferiority.col.bound", level=_level(doc))
        if column == "bound"
        else view(doc, f"stats.noninferiority.col.{column}")
        for column in ("pair", "margin", "estimate", "bound", "ours", "theirs", "decision")
    ]
    return Table(header, rows, view(doc, "stats.noninferiority.caption"))


def _stability(doc: Mapping[str, Any]) -> list[Block]:
    """The stability test, Ordnung against each baseline: the deadlines whose date changed between reads for only one
    of the two, the difference with its Bonett–Price interval, the mid-p and its Holm adjustment."""
    shown_ = _final(doc)
    family = shown_["families"]["F3_stability"]
    if family is None:
        return [Paragraph(view(doc, "stats.stability.not_run"))]
    rows = []
    for baseline in finalcharts.baselines(doc):
        row = family[pair_key(baseline)]
        low, high = row["bonett_price"]
        difference = (
            NONE
            if row["diff"] is None or low is None or high is None
            else f"{points(row['diff'])} {_bound(doc, low, high)}"
        )
        rows.append(
            [
                palette.LABELS[baseline],
                str(row["n"]),
                str(row["b"]),
                str(row["c"]),
                difference,
                finalcharts.p_value(row["midp"]),
                finalcharts.p_value(row["holm"]),
                code(shown_["decisions"].get(STABILITY)) if baseline == "llm_only" else NONE,
            ]
        )
    header = [
        view(doc, "stats.stability.col.diff", level=_level(doc))
        if column == "diff"
        else view(doc, f"stats.stability.col.{column}")
        for column in ("pair", "n", "b", "c", "diff", "midp", "holm", "decision")
    ]
    return [Table(header, rows, view(doc, "stats.stability.caption"))]


def pooled_heading(doc: Mapping[str, Any], key: str) -> Subheading:
    """The heading under which a section shows the earlier held-out splits after the final run."""
    return Subheading(view(doc, key))


def pooled_note(doc: Mapping[str, Any]) -> Paragraph:
    """The note that a section's numbers are the earlier held-out splits', as recorded and not pre-registered."""
    return Paragraph(view(doc, "pooled.note", results=RESULTS_ANCHOR, statistics=STATISTICS_ANCHOR))


def stress(doc: Mapping[str, Any]) -> Paragraph:
    """Where the final run's stress test is said (section 9's place for it)."""
    return Paragraph(view(doc, "robustness.stress", anchor=RESULTS_ANCHOR))


def _harmful(row: Mapping[str, Any]) -> bool:
    return bool(row["outcome"] == "missed" or row["direction"] == "late")


def gallery(doc: Mapping[str, Any]) -> list[Block]:
    """Section 11's final run: every late or missed date first (every condition and read), then Ordnung's other
    wrong dates, in the page's order of conditions; ids, reads and codes only, never a letter's words."""
    shown_ = _final(doc)
    rank = {condition: i for i, condition in enumerate(doc["order"])}
    chosen = sorted(
        (row for row in shown_["errors"] if _harmful(row) or row["condition"] == final.REFERENCE),
        key=lambda row: (
            not _harmful(row),
            rank[row["condition"]],
            row["read"],
            row["split"],
            row["entry_id"],
            row["item"],
        ),
    )
    if not chosen:
        return [Paragraph(view(doc, "gallery.none"))]
    rows = [
        [
            f"`{row['entry_id']}`",
            str(row["read"]),
            palette.LABELS[row["condition"]],
            f"`{row['family']}`",
            f"`{row['modality']}`",
            f"`{row['outcome']}`" + (f" `{row['direction']}`" if row["direction"] else ""),
            NONE if row["days_off"] is None else f"{row['days_off']:+d}".replace("-", fmt.MINUS),
            f"`{row['confidence']}`" if row["confidence"] else NONE,
            f"`{row['tier']}`",
            f"`{row['cause']}`" if row["cause"] else NONE,
        ]
        for row in chosen
    ]
    header = [
        view(doc, f"gallery.col.{column}")
        for column in (
            "letter",
            "read",
            "condition",
            "family",
            "modality",
            "outcome",
            "days",
            "confidence",
            "flag",
            "cause",
        )
    ]
    return [
        Paragraph(view(doc, "gallery.lead", split=shown_["split"])),
        Table(header, rows, view(doc, "gallery.caption")),
    ]


def limitations(doc: Mapping[str, Any]) -> list[str]:
    """Section 14 with a final run: what its numbers cannot say, and what the earlier splits' cannot."""
    shown_ = _final(doc)
    return [
        view(doc, "limitations.synthetic"),
        view(doc, "limitations.pooled", anchor=_anchor(doc, "provenance.title", PROVENANCE_SECTION)),
        view(doc, "limitations.reads", reads=shown_["reads"], registered=shown_["reads_registered"]),
        view(doc, "limitations.labels"),
        view(doc, "limitations.kinds", anchor=RESULTS_ANCHOR),
        view(doc, "limitations.land", anchor=RESULTS_ANCHOR),
        view(doc, "limitations.ask", anchor=RESULTS_ANCHOR),
        view(doc, "limitations.model", model=shown_["model"]),
    ]


def _title(doc: Mapping[str, Any], key: str, number: int) -> str:
    return view(doc, key, number=number)


def _anchor(doc: Mapping[str, Any], key: str, number: int) -> str:
    return f"#{slug(_title(doc, key, number))}"


def appendix(doc: Mapping[str, Any]) -> list[Section]:
    """The sections a final run adds after section 15: its deviations and its provenance."""
    return [
        Section(_title(doc, "deviations.title", DEVIATIONS_SECTION), deviations(doc)),
        Section(_title(doc, "provenance.title", PROVENANCE_SECTION), provenance(doc)),
    ]


def _applies(doc: Mapping[str, Any], entry: Mapping[str, Any]) -> str:
    """What a deviation applies to: its split and read, how many letters or deadlines, or the paths it names."""
    parts: list[str] = []
    if entry["split"] is not None:
        parts.append(f"`{entry['split']}`")
    if entry["repeat"] is not None:
        parts.append(view(doc, "deviations.applies.read", repeat=entry["repeat"]))
    if entry["entries"] is not None:
        parts.append(view(doc, "deviations.applies.entries", count=entry["entries"]))
    if entry["items"] is not None:
        parts.append(view(doc, "deviations.applies.items", count=entry["items"]))
    parts += [f"`{path}`" for path in entry["paths"]]
    return "; ".join(parts) or view(doc, "deviations.not_recorded")


def deviations(doc: Mapping[str, Any]) -> list[Block]:
    """Section 16: every entry of the deviations file, as recorded at the time (never its account of what happened),
    or that there is none."""
    shown_ = _final(doc)
    entries = shown_["deviations"]
    file = shown_["files"]["deviations"]["file"]
    if not entries:
        return [Paragraph(view(doc, "deviations.none", file=file))]
    missing = view(doc, "deviations.not_recorded")
    rows = [
        [
            f"`{entry['id']}`",
            f"`{entry['kind']}`",
            _applies(doc, entry),
            entry["consequence"] or missing,
            entry["created_at"] or missing,
            view(doc, "deviations.comment", url=entry["issue_comment_url"])
            if entry["issue_comment_url"]
            else missing,
            f"`{str(entry['checkpoint_sha'])[:12]}`" if entry["checkpoint_sha"] else missing,
        ]
        for entry in entries
    ]
    header = [
        view(doc, f"deviations.col.{column}")
        for column in ("id", "kind", "applies", "consequence", "recorded", "comment", "checkpoint")
    ]
    return [
        Paragraph(view(doc, "deviations.lead", file=file, count=len(entries))),
        Table(header, rows, view(doc, "deviations.caption")),
    ]


def provenance(doc: Mapping[str, Any]) -> list[Block]:
    """Section 17: where the final run's numbers come from, each value a recorded field (and the hash of
    ``presentation.json`` as rendered, which the renderer computes and never stores)."""
    shown_ = _final(doc)
    prereg, registered, data = shown_["prereg"], shown_["prereg"]["registered"], shown_["prereg"]["data"]
    rows: list[list[str]] = [
        [view(doc, "provenance.prereg"), f"`{prereg['file']}`"],
        [view(doc, "provenance.prereg.hash"), f"`{prereg['sha256']}`"],
        [view(doc, "provenance.freeze"), f"`{registered['freeze_sha']}`"],
        [view(doc, "provenance.freeze_pr"), f"#{registered['freeze_pr']}"],
        [view(doc, "provenance.commit_a"), f"`{registered['commit_a']}`"],
        [view(doc, "provenance.planned_day"), str(registered["planned_day"])],
        [view(doc, "provenance.valid_until"), str(registered["valid_until"])],
        [view(doc, "provenance.manifest"), f"`{data['manifest_sha256']}`"],
        [view(doc, "provenance.tree"), f"`{data['tree_sha256']}`"],
    ]
    rows += [
        [view(doc, "provenance.blind", path=path), f"`{value}`"]
        for path, value in prereg["blind_writing"].items()
    ]
    rows.append(
        [view(doc, "provenance.source", file=shown_["source"]["file"]), f"`{shown_['source']['sha256']}`"]
    )
    for row in shown_["inputs"]:
        value = (
            view(doc, "provenance.input.value", sha=row["sha256"], date=row["date"], commit=row["commit"])
            if row["date"] and row["commit"]
            else f"`{row['sha256']}`"
        )
        rows.append([view(doc, "provenance.input", file=row["file"], role=row["role"]), value])
    rows += [
        [view(doc, "provenance.named", file=named["file"]), f"`{named['sha256']}`"]
        for named in shown_["files"].values()
        if named
    ]
    if shown_["phase2"]:
        rows += [
            [view(doc, "provenance.phase2.head"), f"`{shown_['phase2']['head']}`"],
            [view(doc, "provenance.phase2.tree"), f"`{shown_['phase2']['tree_sha256']}`"],
        ]
    rendered = json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    rows.append([view(doc, "provenance.presentation", file=PRESENTATION), f"`{digest}`"])
    header = [view(doc, "provenance.col.what"), view(doc, "provenance.col.value")]
    return [
        Paragraph(view(doc, "provenance.lead")),
        Table(header, rows, view(doc, "provenance.caption")),
    ]


def kind(doc: Mapping[str, Any], name: str) -> str:
    """What a results file of the final run is, on the history page (``ask-final``, ``stress``)."""
    return view(doc, f"history.kind.{name}")
