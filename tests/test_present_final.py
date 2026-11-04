"""The final run's pre-registered sentences (``evals/present/final.py``, ``evals/present/final_templates.json``).

The templates are written before any final result exists and are frozen with the code: every sentence the README
says about the final run comes from them, filled from the final analysis and the results files it names. These
tests render every code on synthetic finals (results in Ordnung's favour and against it), check that no template
holds a number of its own, that each sentence names every condition it compares and that no sentence contradicts
the interval it prints. The last test holds the README to the sentences once the final analysis is published.
"""

from __future__ import annotations

import copy
import json
import random
import re
import string
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from evals import analysis
from evals.present import BEGIN, END, final
from evals.records import CONDITIONS

ROOT = Path(__file__).resolve().parents[1]
BASELINES = ("llm_only", "llm_rules_text", "llm_rules_tool")
N = 112
LEVEL = 0.95
MARGIN = 0.05


def _pair(baseline: str) -> str:
    return f"ordnung-vs-{baseline}"


# --------------------------------------------------------------------------------------------------
# Synthetic finals: the final analysis's shape, numbers set by hand
# --------------------------------------------------------------------------------------------------


def _rate(k: int, n: int) -> dict[str, Any]:
    value = k / n
    return {"k": k, "n": n, "value": value, "ci": [max(0.0, value - 0.04), min(1.0, value + 0.03)]}


def _condition(right: list[int], harmful: list[int], unstable: int) -> dict[str, Any]:
    reads = len(right)
    mean = sum(right) / (N * reads)
    return {
        "exact_per_read": [_rate(k, N) for k in right],
        "harmful_per_read": [_rate(k, N) for k in harmful],
        "mean_accuracy": {"value": mean, "ci": [mean - 0.03, min(1.0, mean + 0.02)], "method": "percentile"},
        "unstable": {"k": unstable, "n": N, "value": unstable / N, "ci": [0.0, 0.1]},
    }


def _row(diff: float, lo: float, hi: float, holm: float) -> dict[str, Any]:
    return {
        "n": N,
        "diff": diff,
        "signflip": {"p": holm / 2, "method": "exact", "nonzero": 12},
        "bootstrap": {"diff": diff, "lo": lo, "hi": hi, "method": "percentile"},
        "holm": holm,
    }


def _stability(b: int, c: int, holm: float) -> dict[str, Any]:
    return {"n": N, "b": b, "c": c, "diff": (b - c) / N, "midp": holm, "exact_p": holm, "holm": holm}


def good() -> dict[str, Any]:
    """Ordnung ahead of every baseline, no late or missed date of its own: the result the design hopes for."""
    k = 3
    doc: dict[str, Any] = {
        "schema": "ordnung-eval-analysis/1",
        "meta": {
            "kind": "final",
            "model": "claude-sonnet-5",
            "pre_registered": True,
            "prereg": {"file": "evals/preregistration/final-0.4.0.json", "sha256": "0123456789abcdef" * 4},
            "settings": {"level": LEVEL, "alpha": 0.05, "noninferiority_margin": MARGIN},
        },
        "primary": {
            "split": "holdout4",
            "reads": k,
            "items": N,
            "letters": 126,
            "clusters": 104,
            "conditions": {
                "ordnung": _condition([111, 112, 111], [0, 0, 0], 2),
                "llm_only": _condition([90, 92, 91], [12, 11, 13], 17),
                "llm_rules_text": _condition([100, 101, 99], [3, 2, 4], 9),
                "llm_rules_tool": _condition([108, 109, 110], [1, 1, 0], 4),
            },
            "families": {
                "F1_accuracy": {
                    _pair("llm_only"): _row(0.18, 0.11, 0.25, 0.00003),
                    _pair("llm_rules_text"): _row(0.10, 0.04, 0.16, 0.004),
                    _pair("llm_rules_tool"): _row(0.02, -0.01, 0.05, 0.31),
                },
                "F2_harm": {
                    _pair("llm_only"): _row(-0.107, -0.16, -0.06, 0.0002),
                    _pair("llm_rules_text"): _row(-0.027, -0.05, -0.006, 0.03),
                    _pair("llm_rules_tool"): _row(-0.006, -0.02, 0.0, 0.5),
                },
                "F3_stability": {
                    _pair("llm_only"): _stability(1, 16, 0.0003),
                    _pair("llm_rules_text"): _stability(1, 8, 0.04),
                    _pair("llm_rules_tool"): _stability(1, 3, 0.6),
                },
            },
            "noninferiority": {
                _pair("llm_rules_tool"): {
                    "margin": MARGIN,
                    "bound": {"lo": -0.012, "hi": 0.048, "estimate": 0.02, "level": LEVEL},
                    "errors": {"ours": 2, "theirs": 9, "ratio": 2 / 9},
                    "decision": "non_inferior",
                }
            },
            "decisions": {
                "beats_llm_only": "clear",
                "vs_llm_rules_text": "clear",
                "vs_llm_rules_tool": "non_inferior",
                "f2_vs_llm_only": "fewer",
                "f2_vs_llm_rules_text": "fewer",
                "harmful": {"dates": 0, "reads": N * k, "none": True},
                "more_stable_than_llm_only": True,
                "flags_caught": {"caught": 2, "wrong": 3, "caught_reads": 2, "wrong_reads": 4},
            },
        },
        "secondary": {
            "newkinds": {
                "items": 40,
                "letters": 32,
                "clusters": 28,
                "conditions": {
                    "ordnung": {"items": 40, "exact": _rate(38, 40), "harmful": _rate(1, 40)},
                    "llm_only": {"items": 40, "exact": _rate(30, 40), "harmful": _rate(6, 40)},
                    "llm_rules_text": {"items": 40, "exact": _rate(33, 40), "harmful": _rate(4, 40)},
                    "llm_rules_tool": {"items": 40, "exact": _rate(37, 40), "harmful": _rate(2, 40)},
                },
            }
        },
        "sensitivities": {"s_conv": {"tagged_items": 9, "items_changed": 0, "same_as_primary": True}},
        "labels": {
            "ambiguous_slots": {
                "deadline": 3,
                "contract": 1,
                "by_split": {
                    "holdout4": {"deadline": 2, "contract": 1},
                    "newkinds": {"deadline": 1, "contract": 0},
                },
            }
        },
    }
    return doc


def bad() -> dict[str, Any]:
    """Every baseline ahead of Ordnung and Ordnung with late or missed dates: the result the design fears."""
    doc = good()
    primary = doc["primary"]
    primary["conditions"]["ordnung"] = _condition([95, 96, 94], [7, 6, 8], 30)
    families = primary["families"]
    families["F1_accuracy"] = {
        _pair("llm_only"): _row(-0.06, -0.10, -0.02, 0.006),
        _pair("llm_rules_text"): _row(-0.08, -0.12, -0.04, 0.001),
        _pair("llm_rules_tool"): _row(-0.12, -0.17, -0.08, 0.00001),
    }
    families["F2_harm"] = {
        _pair("llm_only"): _row(0.05, 0.02, 0.08, 0.004),
        _pair("llm_rules_text"): _row(0.04, 0.01, 0.07, 0.01),
        _pair("llm_rules_tool"): _row(0.06, 0.03, 0.09, 0.0006),
    }
    families["F3_stability"] = {
        _pair("llm_only"): _stability(20, 7, 0.02),
        _pair("llm_rules_text"): _stability(24, 3, 0.0004),
        _pair("llm_rules_tool"): _stability(27, 1, 0.00001),
    }
    primary["noninferiority"][_pair("llm_rules_tool")].update(
        bound={"lo": -0.17, "hi": -0.08, "estimate": -0.12, "level": LEVEL},
        errors={"ours": 51, "theirs": 9, "ratio": 51 / 9},
        decision="agent_higher",
    )
    primary["decisions"].update(
        beats_llm_only="baseline_ahead",
        vs_llm_rules_text="baseline_ahead",
        vs_llm_rules_tool="agent_higher",
        f2_vs_llm_only="more",
        f2_vs_llm_rules_text="more",
        harmful={"dates": 21, "reads": N * 3, "none": False},
        more_stable_than_llm_only=False,
        flags_caught={"caught": 0, "wrong": 0, "caught_reads": 0, "wrong_reads": 0},
    )
    doc["secondary"]["newkinds"] = {"not_recorded": {"reason": "window_closed"}}
    zero = {"deadline": 0, "contract": 0}
    doc["labels"]["ambiguous_slots"] = {**zero, "by_split": {"holdout4": zero, "newkinds": zero}}
    doc["sensitivities"]["s_conv"] = {
        "tagged_items": 11,
        "items_changed": 14,
        "conditions": {
            "ordnung": {"mean_accuracy": 0.87},
            "llm_only": {"mean_accuracy": 0.86},
            "llm_rules_text": {"mean_accuracy": 0.92},
            "llm_rules_tool": {"mean_accuracy": 0.97},
        },
    }
    return doc


def _set(
    doc: dict[str, Any], family: str, baseline: str, decision_key: str, decision: str, row: dict[str, Any]
) -> None:
    doc["primary"]["families"][family][_pair(baseline)] = row
    doc["primary"]["decisions"][decision_key] = decision


def undecided() -> dict[str, Any]:
    """Nothing decided: every interval includes 0, and the agent comparison cannot be told."""
    doc = good()
    _set(
        doc, "F1_accuracy", "llm_only", "beats_llm_only", "no_clear_difference", _row(0.02, -0.01, 0.05, 0.4)
    )
    _set(
        doc,
        "F1_accuracy",
        "llm_rules_text",
        "vs_llm_rules_text",
        "level_within_noise",
        _row(0.0, -0.03, 0.03, 1.0),
    )
    _set(doc, "F2_harm", "llm_only", "f2_vs_llm_only", "no_clear_difference", _row(-0.01, -0.03, 0.01, 0.6))
    _set(
        doc,
        "F2_harm",
        "llm_rules_text",
        "f2_vs_llm_rules_text",
        "no_clear_difference",
        _row(0.0, -0.02, 0.02, 1.0),
    )
    ni = doc["primary"]["noninferiority"][_pair("llm_rules_tool")]
    ni.update(bound={"lo": -0.07, "hi": 0.01, "estimate": -0.03, "level": LEVEL}, decision="cannot_tell")
    doc["primary"]["decisions"]["vs_llm_rules_tool"] = "cannot_tell"
    doc["primary"]["families"]["F3_stability"][_pair("llm_only")] = _stability(5, 7, 0.8)
    doc["primary"]["decisions"]["more_stable_than_llm_only"] = False
    return doc


def not_confirmed() -> dict[str, Any]:
    """Intervals that exclude 0 while the pre-registered test does not decide (the calibration's rules-text case)."""
    doc = undecided()
    _set(
        doc, "F1_accuracy", "llm_only", "beats_llm_only", "no_clear_difference", _row(0.06, 0.01, 0.11, 0.08)
    )
    # the calibration run: +5.36 points, Holm p 0.127, bootstrap interval +0.58 to +10.40
    _set(
        doc,
        "F1_accuracy",
        "llm_rules_text",
        "vs_llm_rules_text",
        "level_within_noise",
        _row(0.0536, 0.0058, 0.104, 0.127),
    )
    _set(
        doc,
        "F2_harm",
        "llm_only",
        "f2_vs_llm_only",
        "no_clear_difference",
        _row(-0.0595, -0.1084, -0.0123, 0.0888),
    )
    doc["primary"]["families"]["F3_stability"][_pair("llm_only")] = _stability(18, 9, 0.11)
    return doc


def two_reads() -> dict[str, Any]:
    doc = good()
    primary = doc["primary"]
    primary["reads"] = 2
    for summary in primary["conditions"].values():
        summary["exact_per_read"] = summary["exact_per_read"][:2]
        summary["harmful_per_read"] = summary["harmful_per_read"][:2]
    primary["decisions"]["harmful"] = {"dates": 0, "reads": N * 2, "none": True}
    primary["families"]["F3_stability"][_pair("llm_only")] = _stability(1, 4, 0.2)
    primary["decisions"]["more_stable_than_llm_only"] = False
    return doc


def one_read() -> dict[str, Any]:
    doc = bad()
    primary = doc["primary"]
    primary["reads"] = 1
    for summary in primary["conditions"].values():
        summary["exact_per_read"] = summary["exact_per_read"][:1]
        summary["harmful_per_read"] = summary["harmful_per_read"][:1]
    primary["decisions"]["harmful"] = {"dates": 7, "reads": N, "none": False}
    primary["families"]["F3_stability"] = None
    primary["decisions"]["more_stable_than_llm_only"] = None
    doc["sensitivities"]["s_conv"] = {"tagged_items": 0, "items_changed": 0, "same_as_primary": True}
    return doc


def sources(
    *, owner: str = "done", deviations: int = 0, ask_runs: int | None = 3, stress: bool = True
) -> dict[str, Any]:
    power = {
        family: {_pair(b): {"power": 0.21 + 0.1 * i} for i, b in enumerate(BASELINES)}
        for family in ("F1_accuracy", "F2_harm")
    }
    ask = None
    if ask_runs is not None:
        ask = {
            "r1": {
                "strict_accuracy": {"value": 90 / 104, "ci": [0.8, 0.92], "k": 90.0, "n": 104.0, "docs": 30},
                "harmful": {"value": 3 / 164, "ci": [0.0, 0.04], "k": 3.0, "n": 164.0, "docs": 40},
            },
            "consistency": {
                "runs": ask_runs,
                "harmful_any": {"value": 5 / 164, "ci": [0.0, 0.06], "k": 5.0, "n": 164.0, "docs": 40},
                "attack_success_worst": {"value": 1 / 60, "ci": [0.0, 0.09], "k": 1.0, "n": 60.0, "docs": 60},
            },
        }
    labels: dict[str, Any] = {"status": "pending"}
    kappa: dict[str, Any] = {"status": "pending"}
    if owner in ("done", "labels"):
        labels = {"status": "done", "checked": 30, "agree": 29, "source": "an outside deadline calculator"}
    if owner in ("done", "kappa"):
        kappa = {"status": "done", "answers": 40, "kappa": 0.82}
    endpoints = {
        "reference": "ordnung",
        "baseline": "llm_rules_tool",
        "injection_targeted": {"n": 16, "ordnung": 1, "llm_rules_tool": 5, "b": 0, "c": 4, "p": 0.125},
        "distractor_taken": {"n": 16, "ordnung": 0, "llm_rules_tool": 2, "b": 0, "c": 2, "p": 0.5},
        "harmful_unflagged": {"n": 40, "ordnung": 1, "llm_rules_tool": 3, "b": 0, "c": 2, "p": 0.5},
        "holm": {"injection_targeted": 0.375, "distractor_taken": 1.0, "harmful_unflagged": 1.0},
    }
    return {
        "power": {"comparisons": power},
        "ask": ask,
        "stress": {"schema": "ordnung-eval-stress/1", "endpoints": endpoints if stress else None},
        "e2e": {
            "meta": {"splits": ["holdout4", "newkinds"]},
            "metrics": {
                "all": {
                    "obligations": 150,
                    "reminded_in_time": {
                        "value": 0.94,
                        "ci": [0.9, 0.97],
                        "k": 141.0,
                        "n": 150.0,
                        "docs": 140,
                    },
                    "scam": {"set_aside_obligations": 4},
                }
            },
        },
        "owner_labels": labels,
        "owner_kappa": kappa,
        "deviations": _deviations(deviations, ask_runs=ask_runs, stress=stress),
    }


def _deviations(count: int, *, ask_runs: int | None, stress: bool) -> list[dict[str, Any]]:
    """``count`` deviations (more when needed): one recorded at the time for each held-out Ask run not recorded and
    for a stress test not completed, then retakes."""
    found = [
        {"kind": "budget_cut", "applies_to": {"split": final.ASK_SPLIT, "repeat": run}}
        for run in range((ask_runs or 0) + 1, 4)
    ]
    if not stress:
        found.append({"kind": "window_closed", "applies_to": {"split": final.STRESS_SPLIT}})
    found += [{"kind": "retake"} for _ in range(max(0, count - len(found)))]
    return [{"id": f"D{i + 1:03d}", **entry} for i, entry in enumerate(found)]


def prereg() -> dict[str, Any]:
    return {
        "sentences": final.load_templates(),
        "data": {"splits": {"newkinds": {"kinds": [f"kind{i}" for i in range(8)]}}},
    }


def no_set_aside(src: dict[str, Any]) -> dict[str, Any]:
    src = copy.deepcopy(src)
    src["e2e"]["metrics"]["all"]["scam"]["set_aside_obligations"] = 0
    return src


#: (name, final, sources): between them every template code renders.
SCENARIOS: tuple[tuple[str, Callable[[], dict[str, Any]], Callable[[], dict[str, Any]]], ...] = (
    ("good", good, lambda: no_set_aside(sources())),
    ("bad", bad, lambda: sources(owner="pending", deviations=4, ask_runs=1, stress=False)),
    ("undecided", undecided, lambda: sources(owner="labels", deviations=1, ask_runs=None)),
    ("not confirmed", not_confirmed, lambda: sources(owner="kappa")),
    ("two reads", two_reads, lambda: sources(deviations=1)),
    ("one read", one_read, lambda: sources(owner="pending")),
)


def _rendered() -> Iterator[tuple[str, final.Sentence]]:
    for name, make_final, make_sources in SCENARIOS:
        for sentence in final.coded(make_final(), prereg(), sources=make_sources()):
            yield name, sentence


def _fields(text: str) -> list[str]:
    return [field for _, field, _, _ in string.Formatter().parse(text) if field is not None]


def _slots(coded: list[final.Sentence]) -> dict[str, str]:
    """Each slot's sentences, joined (the head and the limitations hold several)."""
    joined: dict[str, list[str]] = {}
    for sentence in coded:
        joined.setdefault(sentence.slot, []).append(sentence.text)
    return {slot: " ".join(texts) for slot, texts in joined.items()}


def _codes(coded: list[final.Sentence]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for sentence in coded:
        found.setdefault(sentence.slot, []).append(sentence.code)
    return found


# --------------------------------------------------------------------------------------------------
# The templates file
# --------------------------------------------------------------------------------------------------


def test_the_templates_file_is_well_formed_and_matches_the_code() -> None:
    templates = final.load_templates()
    assert final.check_templates(templates) == []
    assert set(templates["templates"]) == set(final.CODES)
    assert templates["readme_block"] == [
        "head",
        "rules_text",
        "agent",
        "harm",
        "f2.llm_only",
        "f2.llm_rules_text",
        "f2.llm_rules_tool",
        "stability",
        "flags",
        "newkinds",
        "ask",
        "stress",
        "e2e",
        "limitations",
        "owner",
        "provenance",
    ]
    assert list(templates["conditions"]) == list(CONDITIONS)


def test_a_malformed_template_set_is_refused() -> None:
    templates = final.load_templates()
    broken = copy.deepcopy(templates)
    broken["templates"]["flags.some"]["text"] += " {nowhere}"
    assert any("nowhere" in problem for problem in final.check_templates(broken))
    broken = copy.deepcopy(templates)
    del broken["templates"]["head.clear"]
    assert any("head.clear" in problem for problem in final.check_templates(broken))
    broken = copy.deepcopy(templates)
    broken["readme_block"].append("weather")
    assert any("weather" in problem for problem in final.check_templates(broken))
    broken = copy.deepcopy(templates)
    broken["placeholders"]["unused"] = {"source": "final", "path": "primary.items", "format": "int"}
    assert any("unused" in problem for problem in final.check_templates(broken))
    with pytest.raises(final.FinalSentenceError, match=r"head\.clear"):
        doc = prereg()
        del doc["sentences"]["templates"]["head.clear"]
        final.sentences(good(), doc, sources=sources())


def test_no_template_holds_a_digit_outside_a_placeholder() -> None:
    for code, template in final.load_templates()["templates"].items():
        bare = re.sub(r"\{[^{}]*\}", "", template["text"])
        assert not re.search(r"\d", bare), code


def test_no_template_holds_an_interpretive_clause_or_says_within_noise() -> None:
    """Claims no endpoint measures stay out of the sentences, and "within noise" is never said after a test that
    could not show equivalence."""
    banned = (
        "receipt",
        "checked quote",
        "deterministic",
        "within noise",
        "what the pipeline adds",
        "case rests",
    )
    for code, template in final.load_templates()["templates"].items():
        text = template["text"].lower()
        assert not [word for word in banned if word in text], code


# --------------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------------


def test_every_code_renders_for_good_and_bad_synthetic_finals() -> None:
    seen: dict[str, set[str]] = {}
    for name, sentence in _rendered():
        seen.setdefault(sentence.code, set()).add(name)
        assert "{" not in sentence.text and "}" not in sentence.text, (name, sentence.code)
        assert "n/a" not in sentence.text and "None" not in sentence.text, (name, sentence.code)
    assert set(seen) == set(final.CODES), sorted(set(final.CODES) - set(seen))
    # the good result and the bad one each render a whole block, through different codes
    good_codes = {s.code for s in final.coded(good(), prereg(), sources=no_set_aside(sources()))}
    bad_codes = {
        s.code
        for s in final.coded(
            bad(), prereg(), sources=sources(owner="pending", deviations=4, ask_runs=1, stress=False)
        )
    }
    assert {"head.clear", "rules_text.clear", "agent.non_inferior", "harm.none", "f2.fewer"} <= good_codes
    assert {
        "head.baseline_ahead",
        "rules_text.baseline_ahead",
        "agent.agent_higher",
        "harm.some",
        "f2.more",
    } <= bad_codes


def test_every_placeholder_resolves_and_every_declared_one_is_used() -> None:
    templates = final.load_templates()
    used = {field for template in templates["templates"].values() for field in _fields(template["text"])}
    assert used == set(templates["placeholders"])
    for spec in templates["placeholders"].values():
        assert spec["source"] in final.SOURCES
    # rendering resolves every placeholder a code uses, or refuses: every scenario renders, every code is rendered
    rendered = {sentence.code for _, sentence in _rendered()}
    assert rendered == set(final.CODES)


def test_sentences_come_in_the_registered_readme_order() -> None:
    templates = final.load_templates()
    for name, make_final, make_sources in SCENARIOS:
        coded = final.coded(make_final(), prereg(), sources=make_sources())
        slots = [sentence.slot for sentence in coded]
        assert list(dict.fromkeys(slots)) == templates["readme_block"], name
        assert final.sentences(make_final(), prereg(), sources=make_sources()) == [s.text for s in coded]


def test_every_rendered_sentence_names_every_condition_it_compares() -> None:
    templates = final.load_templates()
    names = templates["conditions"]
    for name, sentence in _rendered():
        compares = templates["templates"][sentence.code]["compares"]
        for condition in compares:
            if condition == "baseline":
                condition = sentence.slot.split(".", 1)[1]
            assert names[condition].lower() in sentence.text.lower(), (name, sentence.code, condition)
    for code in ("harm.none", "harm.some", "newkinds.done", "stability.not_shown", "limitations.s_conv"):
        assert set(templates["templates"][code]["compares"]) == set(CONDITIONS), code
    for code in final.CODES:
        if code.startswith("f2."):
            assert templates["templates"][code]["compares"] == ["ordnung", "baseline"], code


_CI = re.compile(r"CI ([+−-]?\d+\.\d) to ([+−-]?\d+\.\d)")


def _interval(text: str) -> tuple[float, float]:
    found = _CI.search(text)
    assert found, text
    lo, hi = (float(part.replace("−", "-")) for part in found.groups())
    return lo, hi


def test_no_clear_difference_never_prints_with_an_interval_that_excludes_zero() -> None:
    for name, sentence in _rendered():
        if "no clear difference" in sentence.text:
            lo, hi = _interval(sentence.text)
            assert lo <= 0 <= hi, (name, sentence.code, sentence.text)
    # the calibration run: level within noise by the rule, with an interval of +0.6 to +10.4 points
    coded = final.coded(not_confirmed(), prereg(), sources=sources())
    text, codes = _slots(coded), _codes(coded)
    assert codes["rules_text"] == ["rules_text.not_confirmed"]
    assert "not confirmed by the pre-registered test" in text["rules_text"]
    assert "no clear difference" not in text["rules_text"]
    assert "+0.6 to +10.4" in text["rules_text"]
    assert codes["f2.llm_only"] == ["f2.not_confirmed"]


def test_no_clear_difference_holds_on_random_intervals() -> None:
    rng = random.Random(20261029)
    for _ in range(300):
        doc = undecided()
        lo = rng.uniform(-0.2, 0.2)
        hi = lo + rng.uniform(0.0, 0.2)
        diff = (lo + hi) / 2
        _set(doc, "F1_accuracy", "llm_only", "beats_llm_only", "no_clear_difference", _row(diff, lo, hi, 0.3))
        _set(doc, "F2_harm", "llm_only", "f2_vs_llm_only", "no_clear_difference", _row(diff, lo, hi, 0.3))
        for sentence in final.coded(doc, prereg(), sources=sources()):
            if sentence.slot in ("head", "f2.llm_only") and not sentence.code.startswith("head.intro"):
                text = sentence.text
                shown_lo, shown_hi = _interval(text)
                if "no clear difference" in text:
                    assert lo <= 0 <= hi and shown_lo <= 0 <= shown_hi, text
                if "not confirmed" in text:
                    assert not lo <= 0 <= hi, text


def _contradictions() -> Iterator[tuple[str, dict[str, Any]]]:
    doc = good()
    doc["primary"]["families"]["F1_accuracy"][_pair("llm_only")] = _row(0.02, -0.01, 0.05, 0.01)
    yield "clear with an interval that includes 0", doc
    doc = good()
    doc["primary"]["decisions"]["beats_llm_only"] = "baseline_ahead"
    yield "the model alone ahead with an interval above 0", doc
    doc = good()
    doc["primary"]["decisions"]["f2_vs_llm_only"] = "more"
    yield "more harm with an interval below 0", doc
    doc = good()
    doc["primary"]["noninferiority"][_pair("llm_rules_tool")]["bound"]["lo"] = -0.08
    yield "not worse by more than the margin with a bound below it", doc
    doc = bad()
    doc["primary"]["decisions"]["vs_llm_rules_tool"] = "cannot_tell"
    yield "cannot tell with an interval below 0", doc
    doc = good()
    doc["primary"]["decisions"]["harmful"] = {"dates": 0, "reads": N * 3, "none": True}
    doc["primary"]["conditions"]["ordnung"]["harmful_per_read"][1] = _rate(1, N)
    yield "no late or missed date while one read has one", doc
    doc = good()
    doc["primary"]["decisions"]["beats_llm_only"] = "a_code_nobody_wrote"
    yield "a decision code with no template", doc
    doc = bad()
    doc["primary"]["decisions"]["more_stable_than_llm_only"] = True
    yield "more stable while Ordnung changed more often", doc


@pytest.mark.parametrize("label,doc", list(_contradictions()), ids=[label for label, _ in _contradictions()])
def test_a_decision_its_interval_contradicts_is_refused(label: str, doc: dict[str, Any]) -> None:
    with pytest.raises(final.FinalSentenceError):
        final.sentences(doc, prereg(), sources=no_set_aside(sources()))


def test_a_missing_named_result_is_refused_not_left_out() -> None:
    src = sources()
    src["e2e"] = None
    with pytest.raises(final.FinalSentenceError, match="e2e"):
        final.sentences(good(), prereg(), sources=src)
    src = sources()
    src["power"] = None
    with pytest.raises(final.FinalSentenceError, match="power"):
        final.sentences(undecided(), prereg(), sources=src)
    src = sources()
    src["deviations"] = None
    with pytest.raises(final.FinalSentenceError, match="deviations"):
        final.sentences(good(), prereg(), sources=src)
    doc = good()
    del doc["sensitivities"]
    with pytest.raises(final.FinalSentenceError, match="s_conv"):
        final.sentences(doc, prereg(), sources=sources())
    doc = good()
    del doc["labels"]
    with pytest.raises(final.FinalSentenceError, match="left open"):
        final.sentences(doc, prereg(), sources=sources())
    with pytest.raises(final.FinalSentenceError, match="weather"):
        final.sentences(good(), prereg(), sources={**sources(), "weather": {}})


def test_the_reads_change_the_head_and_the_stability_sentence() -> None:
    codes, text = {}, {}
    for make in (good, two_reads, one_read):
        coded = final.coded(make(), prereg(), sources=sources())
        reads = make()["primary"]["reads"]
        codes[reads], text[reads] = _codes(coded), _slots(coded)
    assert codes[3]["head"][0] == "head.intro" and "each read 3 times" in text[3]["head"]
    assert codes[2]["head"][0] == "head.intro.k2" and "each read twice" in text[2]["head"]
    assert codes[1]["head"][0] == "head.intro.k1" and "read once" in text[1]["head"]
    assert codes[2]["stability"] == ["stability.too_few"]
    assert codes[1]["stability"] == ["stability.not_run"]
    assert "limitations.reads" in codes[2]["limitations"]
    assert "limitations.reads" not in codes[1]["limitations"]


def test_the_sentences_carry_the_numbers_of_the_final_analysis() -> None:
    text = _slots(final.coded(good(), prereg(), sources=no_set_aside(sources())))
    assert "On 112 deadlines in 126 synthetic letters" in text["head"]
    assert "Ordnung dates **99.4 %** exactly right (95 % CI 96.4–100.0)" in text["head"]
    assert "(+18.0 points, 95 % CI +11.0 to +25.0; Holm p < 0.001)" in text["head"]
    assert "0 from Ordnung" not in text["harm"] and "none from Ordnung" in text["harm"]
    assert "36 from the model alone" in text["harm"]
    assert "Holm p = 0.004" in text["rules_text"]
    assert "not behind it by more than 5 points" in text["agent"]
    assert "−1.2 to +4.8" in text["agent"]
    assert (
        "described, not tested: a difference of −0.6 points (95 % CI −2.0 to +0.0)"
        in text["f2.llm_rules_tool"]
    )
    assert (
        "Wrong dates from Ordnung over every read: 3; its “please check” flag caught 2 of them."
        == text["flags"]
    )
    assert (
        "deadlines that changed for only one of Ordnung and the model alone: 5, fewer than 10"
        in _slots(final.coded(two_reads(), prereg(), sources=sources()))["stability"]
    )
    assert "On 32 letters of 8 kinds" in text["newkinds"]
    assert "90 of 104 answers strictly right" in text["ask"]
    # the held-out Ask set has one name everywhere, and its scope line names it too
    name = "“Ask: new questions on the demo household”"
    assert text["ask"].startswith(name) and name in text["limitations"]
    for code in ("ask.runs", "ask.one_run", "ask.not_recorded", "limitations.ask_scope"):
        assert final.load_templates()["templates"][code]["text"].startswith(name), code
    assert "1 of 16 letters for Ordnung and 5 for the agent" in text["stress"]
    assert "141 of 150 real deadlines" in text["e2e"]
    assert (
        "Left open between two or more dates by the letter or the law, and so not among the deadlines counted "
        "above: deadlines 3, contract dates 1. Such a deadline counts as handled when no single date is given as "
        "certain or the date is flagged; such a contract date is not scored." in text["limitations"]
    )
    assert (
        "No deadline or contract date of the final letters is left open between two or more dates by the letter "
        "or the law." in _slots(final.coded(bad(), prereg(), sources=sources()))["limitations"]
    )
    assert "hash 0123456789ab" in text["provenance"]
    assert "no deviation was recorded" in text["provenance"]


def test_the_ask_sentence_reads_the_file_of_runs_the_held_out_set_writes(tmp_path: Path) -> None:
    """The Ask sentence takes its numbers from the file ``python -m evals.ask.heldout --final`` writes
    (``evals.ask.heldout.final_payload``), run 1's strict scores and what the runs show together, not from a shape
    of its own."""
    from evals.ask import heldout

    from test_evals_ask_heldout import _three_runs

    payload = json.loads(json.dumps(heldout.final_payload(_three_runs(tmp_path / "runs"), day="2026-12-20")))
    text = _slots(final.coded(good(), prereg(), sources={**no_set_aside(sources()), "ask": payload}))
    strict = payload["r1"]["strict_accuracy"]
    assert f"{int(strict['k'])} of {int(strict['n'])} answers strictly right" in text["ask"]


def test_the_sentences_are_deterministic_and_hold_no_model_id() -> None:
    first = final.sentences(bad(), prereg(), sources=sources(owner="pending", deviations=4))
    assert first == final.sentences(bad(), prereg(), sources=sources(owner="pending", deviations=4))
    # the pinned benchmark model is the only model id; the templates name no model at all
    text = (" ".join(first) + json.dumps(final.load_templates())).replace("claude-sonnet-5", "")
    assert not re.search(r"claude-[a-z]+-\d|sonnet-\d", text, re.IGNORECASE)


# --------------------------------------------------------------------------------------------------
# The real final analysis, on synthetic reads
# --------------------------------------------------------------------------------------------------


def _synthetic_run(split: str, read: int, letters: int) -> dict[str, Any]:
    """A results file of one read: each letter has one scored date; a few conditions get some wrong."""
    entries = []
    for number in range(letters):
        conditions = {}
        for condition in CONDITIONS:
            wrong = (condition == "llm_only" and number % 3 == 0) or (
                condition == "ordnung" and number == 4 and read == 2
            )
            predicted = "2027-03-12" if wrong else "2027-03-10"
            conditions[condition] = {
                "prediction": {"items": [{}], "document_date": "2027-02-24", "sender_kind": "authority"},
                "score": {
                    "cluster": f"L{number}",
                    "items": [
                        {
                            "index": 0,
                            "outcome": "wrong" if wrong else "correct",
                            "direction": "late" if wrong else None,
                            "days_off": 2 if wrong else None,
                            "predicted": predicted,
                            "pred_index": 0,
                            "flagged": False,
                            "confidence": "high",
                            "cause": None,
                        }
                    ],
                    "false_positives": 0,
                    "cost_usd": 0.01,
                    "latency_ms": 1000,
                    "calls": 1,
                    "kind_ok": True,
                    "tool_calls": {"compute_deadline": 1} if condition == "llm_rules_tool" else None,
                    "failed": None,
                    "error": None,
                },
            }
        entries.append(
            {"id": f"{split}-L{number}", "family": "f", "modality": "text", "conditions": conditions}
        )
    return {
        "schema": 1,
        "meta": {
            "date": f"2027-01-0{read}",
            "model": "claude-sonnet-5",
            "split": split,
            "repeat": read,
            "backend": "live",
            "commit": "abc1234",
            "conditions": list(CONDITIONS),
            "partial": False,
            "seed": 20260925,
            "resamples": 2000,
        },
        "entries": entries,
    }


def test_the_final_analysis_itself_renders() -> None:
    section = analysis.default_prereg_analysis()
    section["pool_with"] = []
    registered = analysis.parse_prereg({"analysis": section})
    runs = [analysis.load_run(_synthetic_run("holdout4", read, 12)) for read in (1, 2, 3)]
    runs.append(analysis.load_run(_synthetic_run("newkinds", 1, 6)))
    record = {"file": "evals/preregistration/final-0.4.0.json", "sha256": "ab" * 32}
    left_open = analysis.ambiguous_slots([], ("holdout4", "newkinds"))
    doc = json.loads(
        analysis.render(
            analysis.final_analysis(registered, runs, prereg_record=record, ambiguous_slots=left_open)
        )
    )
    if "noninferiority" not in doc["primary"]:
        pytest.skip("this final analysis gives no non-inferiority bound against the agent yet")
    coded = final.coded(doc, prereg(), sources=sources())
    assert [s.slot for s in coded if not s.slot.startswith("f2.")] == [
        "head",
        "head",
        "rules_text",
        "agent",
        "harm",
        "stability",
        "flags",
        "newkinds",
        "ask",
        "stress",
        "e2e",
        *["limitations"] * 6,
        "owner",
        "provenance",
    ]
    assert all("{" not in s.text for s in coded)


# --------------------------------------------------------------------------------------------------
# The README block
# --------------------------------------------------------------------------------------------------


def _readme(block: str) -> str:
    return f"# Ordnung\n\nIntro.\n\n{BEGIN}\n{block}\n{END}\n\nMore.\n"


def test_the_readme_check_finds_a_missing_reordered_or_added_sentence() -> None:
    said = final.sentences(good(), prereg(), sources=no_set_aside(sources()))
    wrapped = "\n\n".join(said).replace(". ", ".\n")  # the presenter may wrap the lines
    assert final.readme_problems(_readme(wrapped), said) == []
    assert final.readme_problems(_readme("\n\n".join(said[1:])), said)
    assert final.readme_problems(_readme("\n\n".join([said[1], said[0], *said[2:]])), said)
    assert final.readme_problems(_readme("\n\n".join([*said, "Hand-written praise."])), said)
    assert final.readme_problems("# Ordnung\n\nNo block.\n", said)


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_published_finds_the_final_analysis_and_the_files_it_names(tmp_path: Path) -> None:
    results, registered = tmp_path / "evals" / "results", tmp_path / "evals" / "preregistration"
    _write(results / "2026-09-30-claude-sonnet-5-holdout.json", {"meta": {"split": "holdout"}})
    assert final.published(tmp_path) is None  # nothing final yet: the README test waits
    named = no_set_aside(sources())
    _write(results / "2026-12-11-claude-sonnet-5-final.json", good())
    _write(registered / "final-0.4.0.json", prereg())
    _write(registered / "power-0.4.0.json", named["power"])
    _write(registered / "owner-labels-0.4.0.json", named["owner_labels"])
    _write(registered / "owner-kappa-0.4.0.json", named["owner_kappa"])
    _write(registered / "deviations-0.4.0.json", named["deviations"])
    _write(results / "2026-12-09-claude-sonnet-5-ask-heldout-final.json", named["ask"])
    _write(results / "2026-12-08-claude-sonnet-5-stress.json", named["stress"])
    _write(results / "2026-12-11-claude-sonnet-5-e2e.json", named["e2e"])
    # an end-to-end run of earlier splits is not the final one
    _write(results / "2026-10-30-claude-sonnet-5-e2e.json", {"meta": {"splits": ["dev", "holdout"]}})
    found = final.published(tmp_path)
    assert found is not None
    final_doc, registration, files = found
    assert final_doc == good() and registration == prereg() and files == named
    said = final.sentences(final_doc, registration, sources=files)
    assert said == final.sentences(good(), prereg(), sources=named)
    assert final.readme_problems(_readme("\n".join(said)), said) == []
    _write(results / "2026-12-12-claude-sonnet-5-final.json", good())
    with pytest.raises(final.FinalSentenceError, match="more than one"):
        final.published(tmp_path)


def test_the_readme_block_is_the_final_sentences_in_their_registered_order() -> None:
    """Once the final analysis is published, the README's generated block is exactly the registered sentences."""
    found = final.published(ROOT)
    if found is None:
        pytest.skip("the final analysis is not published yet")
    final_doc, registration, named = found
    said = final.sentences(final_doc, registration, sources=named)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert final.readme_problems(readme, said) == []


@pytest.mark.parametrize(
    ("ask_runs", "stress", "what"),
    [(1, True, "ask"), (2, True, "ask"), (None, True, "ask"), (3, False, "stress")],
)
def test_an_ask_run_or_the_stress_test_not_recorded_needs_its_deviation(
    ask_runs: int | None, stress: bool, what: str
) -> None:
    """Every pre-registered endpoint is published: an Ask run left out of the file of runs, a missing file, or a
    stress test not completed is said only when a ``budget_cut`` or ``window_closed`` deviation recorded at the time
    names it; otherwise there is no sentence."""
    src = sources(ask_runs=ask_runs, stress=stress)
    assert final.coded(good(), prereg(), sources=src)  # with the deviations
    src["deviations"] = [d for d in src["deviations"] if d["kind"] == "retake"]
    with pytest.raises(final.FinalSentenceError, match=what):
        final.coded(good(), prereg(), sources=src)
    # a deviation of another kind, or naming another run, does not say why
    src["deviations"] = [
        {"id": "D001", "kind": "retake", "applies_to": {"split": final.ASK_SPLIT, "repeat": 3}},
        {"id": "D002", "kind": "budget_cut", "applies_to": {"split": "holdout4", "repeat": 3}},
    ]
    with pytest.raises(final.FinalSentenceError, match=what):
        final.coded(good(), prereg(), sources=src)


def test_the_ask_runs_planned_are_the_held_out_set_s() -> None:
    from evals.ask import heldout

    assert final.ASK_REGISTERED_RUNS == heldout.REGISTERED_READS


def test_harm_against_the_agent_is_described_never_decided() -> None:
    """The pre-registration describes harm against the agent (no margin for harm could be set before the data): its
    sentence gives the difference and its interval, never fewer, more or a p; a decision taken on it is refused."""
    text = _slots(final.coded(good(), prereg(), sources=no_set_aside(sources())))
    agent = text["f2.llm_rules_tool"]
    assert "described, not tested" in agent and "Holm" not in agent and "power" not in agent
    assert not agent.startswith(("Fewer", "More"))
    doc = good()
    doc["primary"]["decisions"]["f2_vs_llm_rules_tool"] = "no_clear_difference"
    with pytest.raises(final.FinalSentenceError, match="described"):
        final.coded(doc, prereg(), sources=no_set_aside(sources()))
