"""The final run's charts (standard library only), drawn with :mod:`evals.present.charts`'s primitives from
``presentation.json``'s ``final`` alone.

* ``final`` is the headline chart once the final run is published (the README's, the summary's and the page's): per
  condition, the mean over the reads of the exact dates right and of the late or missed ones, each with its
  letter-cluster bootstrap interval, and each read alone as a hollow ring.
* ``final-differences`` is the forest of the pre-registered comparisons (the statistics section's): Ordnung minus
  each baseline, for exact dates and for late or missed ones, each difference with the interval its registered
  sentence prints (the letter-cluster bootstrap's; for exact dates against the agent, the non-inferiority test's
  bound) and a line at zero, and how each is tested (a view template). A sign-flip and Holm p stand only beside a
  tested comparison: the non-inferiority bound has none, and harm against the agent is described, not tested. Every
  number is printed as the registered sentences print it; when no deadline differs (an interval of 0 to 0) no interval
  is drawn and the chart says so, never "[+0.0, +0.0]". No decision is worded here: the registered sentences say them.
* ``final-stability`` shows how steady the dates are over the reads (the final run's results section): right in every
  read and changed between reads, each with its Clopper–Pearson interval. It is drawn only when the stability test
  ran, that is with two reads or more; with one read the registered sentence says it was not measured.

Every title, heading, column, tooltip, description, footnote and caption is a view template
(:mod:`evals.present.views`) filled with values; the description (the README picture's alt text for ``final``) names
every condition and value, and the table twin holds the same numbers. The rows follow the page's one order
(``presentation.json``'s ``order``, the final run's mean accuracy).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from evals.present import PresentError, charts, final, fmt, palette, views
from evals.present.charts import Panel, Row

Parts = tuple[list[str], list[list[str]], str]
#: The comparisons' families, each with its view keys' part.
FAMILIES = (("F1_accuracy", "exact"), ("F2_harm", "harm"))
#: The tested comparisons, and the analysis's decision key for each (whose role the verdict table shows; the decision
#: itself is said by the registered sentence). Harm against the agent is described, not tested, and exact dates
#: against the agent are tested by the non-inferiority bound (:data:`BOUNDED`).
DECISIONS = {
    ("F1_accuracy", "llm_only"): "beats_llm_only",
    ("F1_accuracy", "llm_rules_text"): "vs_llm_rules_text",
    ("F1_accuracy", "llm_rules_tool"): "vs_llm_rules_tool",
    ("F2_harm", "llm_only"): "f2_vs_llm_only",
    ("F2_harm", "llm_rules_text"): "f2_vs_llm_rules_text",
}
#: The comparison the pre-registration tests by the non-inferiority bound, which its sentence prints.
BOUNDED = ("F1_accuracy", final.AGENT)
#: The final splits whose part in the timeline a view template words.
SPLITS = ("holdout4", "newkinds")
NONE = "—"
#: Where a value comes from, when the registered formats refuse it.
WHERE = "presentation.final"


def _final(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    shown: Mapping[str, Any] = doc["final"]
    return shown


def _view(doc: Mapping[str, Any], key: str, **values: object) -> views.Filled:
    return views.fill(_final(doc)["views"], key, **values)


def _level(doc: Mapping[str, Any]) -> str:
    return f"{float(_final(doc)['settings']['level']) * 100:g}"


def _each(rates: Sequence[Mapping[str, Any]]) -> str:
    return " · ".join(fmt.num(rate["value"]) for rate in rates)


def points(value: float) -> str:
    """A difference in percentage points, written as the registered sentences write it (``final``'s points)."""
    return final._formatted(value, "points", WHERE)


def p_value(value: float | None) -> str:
    """A p-value as a table cell gives it."""
    return NONE if value is None else fmt.p_value(float(value))


def p_said(value: float) -> str:
    """A p-value as the registered sentences print it after "Holm p" (``= 0.020``, ``< 0.001``): every template that
    prints one after its name uses this, so one p is printed one way."""
    return final._formatted(value, "p", WHERE)


def pair_key(baseline: str) -> str:
    return f"{final.REFERENCE}-vs-{baseline}"


def baselines(doc: Mapping[str, Any]) -> list[str]:
    """The baselines in the page's row order."""
    return [c for c in doc["order"] if c != final.REFERENCE]


def same(row: Mapping[str, Any]) -> bool:
    """Whether no deadline differs between the two sides: a bootstrap interval of 0 to 0."""
    return bool(row["lo"] == 0 and row["hi"] == 0)


def shown(doc: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    """A comparison's difference and interval in points, ``+d [lo, hi]``; when no deadline differs, the view
    template that says so (never an interval of 0 to 0)."""
    if same(row):
        return _view(doc, "chart.final-differences.none", d=points(row["diff"]))
    return f"{points(row['diff'])} [{points(row['lo'])}, {points(row['hi'])}]"


def code(value: Any) -> str:
    """A code as the analysis records it (a role), in backticks (``true``/``false`` for a yes or no), or a dash for
    none."""
    if value is None:
        return NONE
    return f"`{json.dumps(value) if isinstance(value, bool) else value}`"


def compared(doc: Mapping[str, Any], family: str, baseline: str) -> dict[str, Any]:
    """A comparison as its registered sentence prints it: the difference with the bootstrap interval, or for exact dates
    against the agent with the non-inferiority bound (``diff``, ``lo``, ``hi``), and the sign-flip and Holm p only
    when it is tested by them."""
    row = _final(doc)["families"][family][pair_key(baseline)]
    if (family, baseline) == BOUNDED:
        bound = _final(doc)["noninferiority"][pair_key(baseline)]
        return {"diff": row["diff"], "lo": bound["lo"], "hi": bound["hi"], "p": None, "holm": None}
    if (family, baseline) not in DECISIONS:
        return {**row, "p": None, "holm": None}
    return dict(row)


def tested_by(doc: Mapping[str, Any], family: str, baseline: str) -> str:
    """How a comparison is tested, in the verdict table's words: a sign-flip test with Holm, the non-inferiority bound,
    or described, not tested."""
    if (family, baseline) == BOUNDED:
        return _view(doc, "verdict.test.noninferiority", level=_level(doc))
    if (family, baseline) not in DECISIONS:
        return _view(doc, "verdict.test.described")
    return _view(doc, "verdict.test.signflip")


def power(doc: Mapping[str, Any], family: str, baseline: str) -> str:
    """The pre-registered power of a tested comparison (the power file's), or a dash when there is none or the
    comparison is described, not tested."""
    if (family, baseline) not in DECISIONS:
        return NONE
    powers = _final(doc).get("power") or {}
    value = (powers.get(family) or {}).get(pair_key(baseline))
    return NONE if value is None else final._formatted(value, "pct_whole", WHERE)


def stable(doc: Mapping[str, Any]) -> bool:
    """Whether the stability test ran (two reads or more): only then is the stability chart drawn."""
    shown_ = _final(doc)
    return shown_["families"]["F3_stability"] is not None and int(shown_["reads"]) >= 2


def split_short(doc: Mapping[str, Any], split: str) -> str | None:
    """A final split's part in the timeline, in a view template's words (``None`` for any other split)."""
    return _view(doc, f"split.short.{split}") if split in SPLITS else None


# --------------------------------------------------------------------------------------------------
# The final run: exact dates and harm, the mean over the reads and each read
# --------------------------------------------------------------------------------------------------


def _hero_parts(doc: Mapping[str, Any]) -> Parts:
    shown, level = _final(doc), _level(doc)
    header: list[str] = [
        _view(doc, "chart.final.col.condition"),
        _view(doc, "chart.final.col.exact"),
        _view(doc, "chart.final.col.exact_ci", level=level),
        _view(doc, "chart.final.col.exact_reads"),
        _view(doc, "chart.final.col.harm"),
        _view(doc, "chart.final.col.harm_ci", level=level),
        _view(doc, "chart.final.col.harm_reads"),
    ]
    rows: list[list[str]] = []
    said: list[str] = []
    for condition in doc["order"]:
        summary = shown["conditions"][condition]
        exact, harm = summary["mean_accuracy"], summary["mean_harmful"]
        cells = [
            palette.LABELS[condition],
            fmt.pct(exact["value"]),
            fmt.ci(exact["ci"]),
            _each(summary["exact_per_read"]),
            fmt.pct(harm["value"]),
            fmt.ci(harm["ci"]),
            _each(summary["harmful_per_read"]),
        ]
        rows.append(cells)
        said.append(
            _view(
                doc,
                "chart.final.row",
                condition=cells[0],
                exact=cells[1],
                exact_ci=cells[2],
                exact_reads=cells[3],
                harm=cells[4],
                harm_ci=cells[5],
                harm_reads=cells[6],
            )
        )
    description: str = _view(
        doc,
        "chart.final.description",
        items=shown["items"],
        reads=shown["reads"],
        level=level,
        rows=". ".join(said),
    )
    return header, rows, description


def _rings(
    doc: Mapping[str, Any], condition: str, rates: Sequence[Mapping[str, Any]]
) -> list[tuple[float, str]]:
    reads = _final(doc)["reads_used"]
    return [
        (
            float(rate["value"]),
            _view(
                doc,
                "chart.final.tip.read",
                condition=palette.LABELS[condition],
                read=read,
                value=fmt.pct(rate["value"]),
            ),
        )
        for read, rate in zip(reads, rates, strict=True)
        if rate["value"] is not None
    ]


def _hero(doc: Mapping[str, Any], theme: str, narrow: bool, ident: str) -> str:
    shown, level = _final(doc), _level(doc)
    _, _, description = _hero_parts(doc)
    exact_rows: list[Row] = []
    harm_rows: list[Row] = []
    lowest, highest = 1.0, 0.0
    for condition in doc["order"]:
        summary = shown["conditions"][condition]
        label = palette.LABELS[condition]
        exact, harm = summary["mean_accuracy"], summary["mean_harmful"]
        exact_rings = _rings(doc, condition, summary["exact_per_read"])
        harm_rings = _rings(doc, condition, summary["harmful_per_read"])
        lowest = min([lowest, exact["ci"][0], *(value for value, _ in exact_rings)])
        highest = max([highest, harm["ci"][1], *(value for value, _ in harm_rings)])
        for rows, mean, rings, tip in (
            (exact_rows, exact, exact_rings, "chart.final.tip.exact"),
            (harm_rows, harm, harm_rings, "chart.final.tip.harm"),
        ):
            rows.append(
                Row(
                    condition,
                    mean["value"],
                    (mean["ci"][0], mean["ci"][1]),
                    fmt.pct(mean["value"]),
                    _view(
                        doc,
                        tip,
                        condition=label,
                        value=fmt.pct(mean["value"]),
                        level=level,
                        ci=fmt.ci(mean["ci"]),
                    ),
                    rings,
                )
            )
    panels = [
        Panel(
            _view(doc, "chart.final.exact"),
            min(charts._floor(lowest, 0.1), 0.9),
            1.0,
            charts._percent,
            exact_rows,
        ),
        Panel(
            _view(doc, "chart.final.harm"),
            0.0,
            max(charts._ceil(highest, 0.05), 0.05),
            charts._percent,
            harm_rows,
        ),
    ]
    subtitle = _view(
        doc,
        "chart.final.subtitle",
        items=shown["items"],
        letters=shown["letters"],
        reads=shown["reads"],
        split=shown["split"],
        model=shown["model"],
        level=level,
        method=shown["conditions"]["ordnung"]["mean_accuracy"]["method"],
    )
    return charts._dot_chart(
        ident,
        theme,
        narrow,
        _view(doc, "chart.final.title"),
        subtitle,
        description,
        panels,
        _view(doc, "chart.final.footnote"),
    )


def _hero_caption(doc: Mapping[str, Any]) -> str:
    conditions = _final(doc)["conditions"]

    def mean(condition: str, key: str) -> str:
        return fmt.pct(conditions[condition][key]["value"])

    return _view(
        doc,
        "chart.final.caption",
        ordnung_exact=mean("ordnung", "mean_accuracy"),
        ordnung_harm=mean("ordnung", "mean_harmful"),
        alone_exact=mean("llm_only", "mean_accuracy"),
        alone_harm=mean("llm_only", "mean_harmful"),
        text_exact=mean("llm_rules_text", "mean_accuracy"),
        text_harm=mean("llm_rules_text", "mean_harmful"),
        agent_exact=mean("llm_rules_tool", "mean_accuracy"),
        agent_harm=mean("llm_rules_tool", "mean_harmful"),
    )


# --------------------------------------------------------------------------------------------------
# The differences: Ordnung minus each baseline, for exact dates and for late or missed ones
# --------------------------------------------------------------------------------------------------


def _differences_rows(doc: Mapping[str, Any]) -> list[tuple[str, str, list[str]]]:
    """``(family, baseline, cells)`` for each comparison, the accuracy family's first, baselines in the page's
    order: the difference and interval its registered sentence prints, its sign-flip and Holm p when it is tested by
    them, its power and how it is tested."""
    rows: list[tuple[str, str, list[str]]] = []
    for family, part in FAMILIES:
        for baseline in baselines(doc):
            row = compared(doc, family, baseline)
            cells = [
                palette.LABELS[baseline],
                _view(doc, f"chart.final-differences.measure.{part}"),
                shown(doc, row),
                p_value(row["p"]),
                p_value(row["holm"]),
                power(doc, family, baseline),
                tested_by(doc, family, baseline),
            ]
            rows.append((family, baseline, cells))
    return rows


def _said_row(doc: Mapping[str, Any], family: str, baseline: str, cells: Sequence[str]) -> str:
    """A comparison in the forest's description: its numbers and how it is tested, with a p only beside a test."""
    values = {"baseline": cells[0], "measure": cells[1], "shown": cells[2], "test": cells[6]}
    if (family, baseline) == BOUNDED:
        return _view(doc, "chart.final-differences.row.bound", power=cells[5], **values)
    if (family, baseline) not in DECISIONS:
        return _view(doc, "chart.final-differences.row.described", **values)
    row = compared(doc, family, baseline)
    return _view(
        doc,
        "chart.final-differences.row",
        p=p_said(row["p"]),
        holm=p_said(row["holm"]),
        power=cells[5],
        **values,
    )


def _tip(doc: Mapping[str, Any], family: str, baseline: str, cells: Sequence[str]) -> str:
    """A comparison's mark tooltip: its numbers, with the Holm p only beside a test."""
    values = {"baseline": cells[0], "measure": cells[1], "shown": cells[2]}
    if (family, baseline) == BOUNDED:
        return _view(doc, "chart.final-differences.tip.bound", level=_level(doc), **values)
    if (family, baseline) not in DECISIONS:
        return _view(doc, "chart.final-differences.tip.described", **values)
    return _view(
        doc, "chart.final-differences.tip", holm=p_said(compared(doc, family, baseline)["holm"]), **values
    )


def _differences_parts(doc: Mapping[str, Any]) -> Parts:
    shown_, level = _final(doc), _level(doc)
    header: list[str] = [
        _view(doc, "chart.final-differences.col.baseline"),
        _view(doc, "chart.final-differences.col.measure"),
        _view(doc, "chart.final-differences.col.points", level=level),
        _view(doc, "chart.final-differences.col.p"),
        _view(doc, "chart.final-differences.col.holm"),
        _view(doc, "chart.final-differences.col.power"),
        _view(doc, "chart.final-differences.col.test"),
    ]
    found = _differences_rows(doc)
    rows = [cells for _, _, cells in found]
    said = [_said_row(doc, family, baseline, cells) for family, baseline, cells in found]
    description: str = _view(
        doc,
        "chart.final-differences.description",
        reads=shown_["reads"],
        level=level,
        rows=". ".join(said),
    )
    return header, rows, description


def _differences(doc: Mapping[str, Any], theme: str, narrow: bool, ident: str) -> str:
    shown_ = _final(doc)
    _, _, description = _differences_parts(doc)
    by_family: dict[str, list[Row]] = {family: [] for family, _ in FAMILIES}
    ends: dict[str, list[float]] = {family: [0.0] for family, _ in FAMILIES}
    for family, baseline, cells in _differences_rows(doc):
        row = compared(doc, family, baseline)
        ends[family] += [row["lo"], row["hi"], row["diff"]]
        value = _view(doc, "chart.final-differences.same") if same(row) else points(row["diff"])
        by_family[family].append(
            Row(
                baseline,
                row["diff"],
                None if same(row) else (row["lo"], row["hi"]),
                value,
                _tip(doc, family, baseline, cells),
            )
        )
    # each panel's axis takes in its intervals and the zero line, at least 5 points either side of it
    panels = [
        Panel(
            _view(doc, f"chart.final-differences.{part}"),
            min(charts._floor(min(ends[family]), 0.05), -0.05),
            max(charts._ceil(max(ends[family]), 0.05), 0.05),
            charts._signed_points,
            by_family[family],
            zero=True,
        )
        for family, part in FAMILIES
    ]
    first = shown_["families"]["F1_accuracy"][pair_key(final.BASELINES[0])]
    subtitle = _view(
        doc,
        "chart.final-differences.subtitle",
        items=shown_["items"],
        letters=shown_["letters"],
        reads=shown_["reads"],
        split=shown_["split"],
        model=shown_["model"],
        level=_level(doc),
        method=first["method"],
    )
    return charts._dot_chart(
        ident,
        theme,
        narrow,
        _view(doc, "chart.final-differences.title"),
        subtitle,
        description,
        panels,
        _view(doc, "chart.final-differences.footnote", level=_level(doc)),
    )


def _differences_caption(doc: Mapping[str, Any]) -> str:
    families = _final(doc)["families"]

    def diff(family: str, baseline: str) -> str:
        return points(families[family][pair_key(baseline)]["diff"])

    return _view(
        doc,
        "chart.final-differences.caption",
        alone_exact=diff("F1_accuracy", "llm_only"),
        alone_harm=diff("F2_harm", "llm_only"),
        text_exact=diff("F1_accuracy", "llm_rules_text"),
        text_harm=diff("F2_harm", "llm_rules_text"),
        agent_exact=diff("F1_accuracy", "llm_rules_tool"),
        agent_harm=diff("F2_harm", "llm_rules_tool"),
    )


# --------------------------------------------------------------------------------------------------
# How steady the dates are: right in every read, and changed between reads
# --------------------------------------------------------------------------------------------------

#: The stability chart's two rates, each with its view keys' part.
STEADINESS = (("pass_all", "all"), ("unstable", "unstable"))


def _rate_cells(rate: Mapping[str, Any]) -> list[str]:
    return [fmt.pct(rate["value"]), fmt.kn(rate), fmt.ci(rate["ci"])]


def _stability_parts(doc: Mapping[str, Any]) -> Parts:
    shown_, level = _final(doc), _level(doc)
    header: list[str] = [_view(doc, "chart.final-stability.col.condition")]
    for _, part in STEADINESS:
        header += [
            _view(doc, f"chart.final-stability.col.{part}"),
            _view(doc, f"chart.final-stability.col.{part}_kn"),
            _view(doc, f"chart.final-stability.col.{part}_ci", level=level),
        ]
    rows: list[list[str]] = []
    said: list[str] = []
    for condition in doc["order"]:
        summary = shown_["conditions"][condition]
        steady, changed = _rate_cells(summary["pass_all"]), _rate_cells(summary["unstable"])
        cells = [palette.LABELS[condition], *steady, *changed]
        rows.append(cells)
        said.append(
            _view(
                doc,
                "chart.final-stability.row",
                condition=cells[0],
                all=steady[0],
                all_kn=steady[1],
                level=level,
                all_ci=steady[2],
                unstable=changed[0],
                unstable_kn=changed[1],
                unstable_ci=changed[2],
            )
        )
    description: str = _view(
        doc,
        "chart.final-stability.description",
        items=shown_["items"],
        reads=shown_["reads"],
        level=level,
        rows=". ".join(said),
    )
    return header, rows, description


def _stability(doc: Mapping[str, Any], theme: str, narrow: bool, ident: str) -> str:
    if not stable(doc):
        raise PresentError("the stability chart needs the stability test, which needs two reads or more")
    shown_, level = _final(doc), _level(doc)
    _, _, description = _stability_parts(doc)
    rows: dict[str, list[Row]] = {key: [] for key, _ in STEADINESS}
    lowest, highest = 1.0, 0.0
    for condition in doc["order"]:
        summary = shown_["conditions"][condition]
        label = palette.LABELS[condition]
        for key, part in STEADINESS:
            rate = summary[key]
            value, (low, high) = float(rate["value"]), rate["ci"]
            if key == "pass_all":
                lowest = min(lowest, value, low)
            else:
                highest = max(highest, value, high)
            rows[key].append(
                Row(
                    condition,
                    value,
                    (low, high),
                    fmt.pct(value),
                    _view(
                        doc,
                        f"chart.final-stability.tip.{part}",
                        condition=label,
                        value=fmt.pct(value),
                        kn=fmt.kn(rate),
                        level=level,
                        ci=fmt.ci(rate["ci"]),
                    ),
                )
            )
    panels = [
        Panel(
            _view(doc, "chart.final-stability.all"),
            min(charts._floor(lowest, 0.1), 0.9),
            1.0,
            charts._percent,
            rows["pass_all"],
        ),
        Panel(
            _view(doc, "chart.final-stability.unstable"),
            0.0,
            max(charts._ceil(highest, 0.05), 0.05),
            charts._percent,
            rows["unstable"],
        ),
    ]
    subtitle = _view(
        doc,
        "chart.final-stability.subtitle",
        items=shown_["items"],
        letters=shown_["letters"],
        reads=shown_["reads"],
        split=shown_["split"],
        model=shown_["model"],
        level=level,
        method=shown_["methods"]["single_rate"],
    )
    return charts._dot_chart(
        ident,
        theme,
        narrow,
        _view(doc, "chart.final-stability.title"),
        subtitle,
        description,
        panels,
        _view(doc, "chart.final-stability.footnote"),
    )


#: The view keys' part for each condition in a caption that names all four.
_PARTS = {"ordnung": "ordnung", "llm_only": "alone", "llm_rules_text": "text", "llm_rules_tool": "agent"}


def _stability_caption(doc: Mapping[str, Any]) -> str:
    shown_ = _final(doc)
    conditions = shown_["conditions"]
    row = shown_["families"]["F3_stability"][pair_key("llm_only")]
    rates = {
        f"{part}_{name}": fmt.pct(conditions[condition][key]["value"])
        for condition, part in _PARTS.items()
        for key, name in (("pass_all", "all"), ("unstable", "unstable"))
    }
    return _view(doc, "chart.final-stability.caption", b=row["b"], c=row["c"], p=p_said(row["holm"]), **rates)


#: Each chart: how it is drawn, its parts (header, rows, description), its title's view and its caption.
_CHARTS: dict[
    str,
    tuple[
        Callable[[Mapping[str, Any], str, bool, str], str],
        Callable[[Mapping[str, Any]], Parts],
        str,
        Callable[[Mapping[str, Any]], str],
    ],
] = {
    "final": (_hero, _hero_parts, "chart.final.title", _hero_caption),
    "final-differences": (
        _differences,
        _differences_parts,
        "chart.final-differences.title",
        _differences_caption,
    ),
    "final-stability": (_stability, _stability_parts, "chart.final-stability.title", _stability_caption),
}


def names(doc: Mapping[str, Any]) -> tuple[str, ...]:
    """The final run's charts, in the order the report shows them: the headline and the differences, and how steady
    the dates are once there are two reads or more."""
    return tuple(name for name in _CHARTS if name != "final-stability" or stable(doc))


def committed(doc: Mapping[str, Any]) -> tuple[str, ...]:
    """The final run's charts committed as ``docs/assets/eval-<name>-{light,dark}.svg``."""
    return names(doc)


def svg(name: str, doc: Mapping[str, Any], theme: str = "light", *, narrow: bool = False) -> str:
    return _CHARTS[name][0](doc, theme, narrow, f"{name}-{theme}-{'n' if narrow else 'w'}")


def table(name: str, doc: Mapping[str, Any]) -> tuple[list[str], list[list[str]]]:
    header, rows, _ = _CHARTS[name][1](doc)
    return header, rows


def description(name: str, doc: Mapping[str, Any]) -> str:
    return _CHARTS[name][1](doc)[2]


def title(name: str, doc: Mapping[str, Any]) -> str:
    return _view(doc, _CHARTS[name][2])


def caption(name: str, doc: Mapping[str, Any]) -> str:
    """The chart's "What this shows", a view template filled with values only."""
    return _CHARTS[name][3](doc)
