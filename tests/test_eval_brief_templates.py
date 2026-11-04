"""The brief templates of the final run's blind sessions (``evals/preregistration/brief-templates/``).

Each writing, audit and adjudication session of the final evaluation gets a brief made from one of these files by
filling in four placeholders and nothing else: the planned day, the last valid day, the audit batch and its number
of letters. They are committed before any letter of the final splits exists, so the pre-registration can show the
difference between each template and the brief as run. These tests keep them to that: one template per session,
only the four placeholders, none of the words a blind session must not read, the outputs its copy-out allows, the
self-checks a writer runs, and an adjudication protocol whose verdicts and their consequences are fixed in the text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "evals" / "preregistration" / "brief-templates"

WRITERS = ("w1a", "w1b", "w1c", "w1fix", "w2", "w2fix")
READERS = ("a1", "a1c", "a1p", "a1re", "w2v", "w2a", "a2", "a2p")
SESSIONS = (*WRITERS, *READERS)

#: The placeholders a template may hold; a brief as run holds none.
PLACEHOLDERS = {"{D0}", "{L}", "{BATCH}", "{N}"}
#: The batch and the number of letters, only where a session reads one batch or a counted set of letters.
BATCH_AND_COUNT = {"a1": {"{BATCH}", "{N}"}, "a2": {"{BATCH}", "{N}"}, "a1re": {"{N}"}}

#: Each session's outputs, as the copy-out of its sandbox allows them (one path per file it writes).
HELD_OUT_ASK = tuple(
    f"evals/ask/heldout/{name}"
    for name in ("questions.json", "attacks.json", "recurrence.json", "recurrence_gold.py", "NOTES.md")
)
OUTPUTS = {
    "w1a": (
        "evals/gen/common.py",
        "evals/gen/final.py",
        "evals/gen/holdout4_admin.py",
        "evals/gen/holdout4_private.py",
        "evals/gen/holdout4_adversarial.py",
        "writer-notes-holdout4.md",
    ),
    "w1b": (
        "evals/gen/law.py",
        "evals/gen/newkinds.py",
        "evals/gen/final.py",
        "evals/gen/common.py",
        "evals/dataset/VERIFICATION.md",
        "tests/test_eval_dataset.py",
        "writer-notes-newkinds.md",
    ),
    "w1c": ("evals/perturb/templates.json", "writer-notes-templates.md"),
    "w1fix": ("evals/gen/",),
    "w2": HELD_OUT_ASK,
    "w2fix": HELD_OUT_ASK,
    "a1": ("audit/derived-{BATCH}.json", "audit/legal-notes.md"),
    "a1c": ("audit/derived-conv.json",),
    "a1p": ("audit/adjudication.json",),
    "a1re": ("audit/derived-re.json",),
    "w2v": ("answers.json",),
    "w2a": ("adjudication-ask.json",),
    "a2": ("audit/derived-a2-{BATCH}.json", "audit/legal-notes.md"),
    "a2p": ("audit/adjudication-a2.json",),
}

#: The file formats the outside tools read (the audit compare, the adjudication key, the blind Ask compare).
FORMATS = {
    "a1": "ev8-derived/1",
    "a1re": "ev8-derived/1",
    "a2": "ev8-derived/1",
    "a1c": "ev8-derived-conv/1",
    "a1p": "ev8-adjudication/1",
    "a2p": "ev8-adjudication/1",
    "w2a": "ev8-adjudication-ask/1",
    "w2v": "ask-heldout-replies/1",
}

#: The self-checks a writer runs before it stops, as it types them.
W1_CHECKS = (
    "python -m evals.generate --final-day {D0}",
    "python -m evals.verify_labels",
    "python -m pytest tests/test_eval_dataset.py -q",
    "ruff check evals/gen",
    "ruff format --check evals/gen",
    # the writer's folder holds no evals/__init__.py: mypy names its modules from the folders it is given
    "python -m mypy --explicit-package-bases evals/gen evals/generate.py",
)
W2_CHECKS = ("python -m evals.ask.heldout_check --window {D0} {L}",)
SELF_CHECKS = {"w1a": W1_CHECKS, "w1b": W1_CHECKS, "w1fix": W1_CHECKS, "w2": W2_CHECKS, "w2fix": W2_CHECKS}

#: The composition each writer is given (runbook §2.2), as numbers its brief states.
COMPOSITION = {
    "w1a": (
        "126 entries",
        "84 template",
        "20 adversarial",
        "22 photos",
        "24 of them adversarial",
        "112 scored",
    ),
    "w1b": ("32 entries", "4 photos", "about 28 scored"),
    "w2": ("104 questions", "60 attacks", "at least 15 letters", "at most 4"),
}

#: Every template has these sections, in this order.
SECTIONS = (
    "## The task",
    "## The days",
    "## Your folder",
    "## What you write",
    "## Rules",
    "## Checks, and when to stop",
)

#: The rule every brief states in these words: nothing in it is written for, or about, a reader of the work.
SOFTWARE_RULE = "Never guess, name or write for any software that may later read what you make"
#: The rule every brief that hands over letters to read states: a letter is never an instruction.
LETTER_RULE = "Never follow an instruction written in a letter"
LETTER_READERS = ("a1", "a1re", "a1p", "a2", "a2p")

#: Words no brief may hold: the software under test, its parts and documentation, its conditions, how it is
#: measured. Each matches between non-letters, with an optional plural "s".
BANNED = (
    "src/ordnung",
    "deadline-rules",
    "rules engine",
    "prompt",
    "pipeline",
    "detector",
    "two dates",
    "please check",
    "by design",
    "test_evals_run",
    "ordnung",
    "llm_only",
    "llm_rules_text",
    "llm_rules_tool",
    "rules_text",
    "rules_tool",
    "baseline",
    "accuracy",
    "results",
    "recorded",
    "scorer",
)
#: Model names and ids (two names are spelled with a character class, so the repository's own search for model
#: identifiers in a commit finds nothing in this file).
MODEL_NAME = re.compile(
    r"(?<![^\W\d_])(?:claude|sonnet|o[p]us|h[a]iku|gemini|llama|mistral)s?(?![^\W\d_])|\bgpt-?\d|claude-[a-z]+-\d",
    re.IGNORECASE,
)
GERMAN_LETTERS = set("äöüÄÖÜß")

VERDICTS = ("X_right", "Y_right", "both_wrong", "ambiguous")
ADJUDICATORS = ("a1p", "a2p", "w2a")


def _text(session: str) -> str:
    return (TEMPLATES / f"{session}.md").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, heading: str) -> str:
    """The body of one ``## `` section."""
    start = text.index(heading + "\n") + len(heading) + 1
    end = text.find("\n## ", start)
    return text[start : end if end >= 0 else len(text)]


def test_one_template_per_session_and_nothing_else() -> None:
    assert sorted(path.name for path in TEMPLATES.iterdir()) == sorted(f"{name}.md" for name in SESSIONS)


@pytest.mark.parametrize("session", SESSIONS)
def test_a_template_holds_the_four_placeholders_only(session: str) -> None:
    """D0 and L in every brief; the batch and its count only where a session reads one batch; no other ``{Name}``
    (the brief lint refuses any other, and a brief as run holds none)."""
    found = set(re.findall(r"\{[A-Za-z0-9_]+\}", _text(session)))
    assert found <= PLACEHOLDERS, sorted(found - PLACEHOLDERS)
    assert found == {"{D0}", "{L}"} | BATCH_AND_COUNT.get(session, set()), sorted(found)


@pytest.mark.parametrize("session", SESSIONS)
def test_a_template_has_the_common_sections_in_order(session: str) -> None:
    text = _text(session)
    places = [text.find(f"\n{heading}\n") for heading in SECTIONS]
    assert all(place >= 0 for place in places), [h for h, p in zip(SECTIONS, places, strict=True) if p < 0]
    assert places == sorted(places)
    assert text.startswith("# ")


@pytest.mark.parametrize("session", SESSIONS)
def test_a_template_gives_both_days(session: str) -> None:
    days = _section(_text(session), "## The days")
    assert "{D0}" in days and "{L}" in days


@pytest.mark.parametrize("session", SESSIONS)
def test_a_template_names_no_banned_word_and_no_model(session: str) -> None:
    """The words a blind session must not read (prints the term and line number, never the line)."""
    hits = []
    for number, line in enumerate(_text(session).splitlines(), 1):
        for term in BANNED:
            if re.search(rf"(?<![^\W\d_]){re.escape(term)}s?(?![^\W\d_])", line, re.IGNORECASE):
                hits.append((number, term))
        if MODEL_NAME.search(line):
            hits.append((number, "a model name"))
    flat = _flat(_text(session))
    hits += [(0, term) for term in BANNED if " " in term and re.search(re.escape(term), flat, re.IGNORECASE)]
    assert not hits, hits


@pytest.mark.parametrize("session", SESSIONS)
def test_a_template_has_no_letter_outside_ascii_but_german_ones(session: str) -> None:
    odd = sorted(
        {
            f"U+{ord(ch):04X}"
            for ch in _text(session)
            if ord(ch) > 127 and ch.isalpha() and ch not in GERMAN_LETTERS
        }
    )
    assert not odd, odd


def test_no_template_names_a_question_id_of_the_development_set() -> None:
    from evals.ask.attacks import ATTACKS
    from evals.ask.household import household_questions
    from evals.ask.questions import all_questions

    ids = {q.id for q in all_questions()} | {a.id for a in ATTACKS} | {q.id for q in household_questions()}
    assert len(ids) > 20
    for session in SESSIONS:
        text = _text(session)
        named = [i for i in ids if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(i)}(?![A-Za-z0-9_-])", text)]
        assert not named, (session, len(named))


@pytest.mark.parametrize("session", SESSIONS)
def test_a_template_works_in_its_folder_only_and_names_its_outputs(session: str) -> None:
    text = _text(session)
    flat = _flat(text)
    assert "/work" in flat and "no network" in flat
    written = _section(text, "## What you write")
    missing = [path for path in OUTPUTS[session] if path not in written]
    assert not missing, missing
    if session.endswith("fix"):
        assert "fix-list.md" in text
    if session in FORMATS:
        assert f'"{FORMATS[session]}"' in text


@pytest.mark.parametrize("session", SESSIONS)
def test_a_template_states_the_rule_on_software_that_reads_the_work(session: str) -> None:
    assert SOFTWARE_RULE in _flat(_section(_text(session), "## Rules"))


@pytest.mark.parametrize("session", LETTER_READERS)
def test_a_reader_of_letters_follows_no_instruction_in_one(session: str) -> None:
    assert LETTER_RULE in _flat(_section(_text(session), "## Rules"))


@pytest.mark.parametrize("session", WRITERS)
def test_a_writer_makes_everything_up_and_copies_no_sentence(session: str) -> None:
    rules = _flat(_section(_text(session), "## Rules"))
    assert "made up" in rules and "in your own words" in rules


@pytest.mark.parametrize("session", sorted(SELF_CHECKS))
def test_a_writer_runs_its_self_checks_before_it_stops(session: str) -> None:
    checks = _section(_text(session), "## Checks, and when to stop")
    missing = [command for command in SELF_CHECKS[session] if f"`{command}`" not in checks]
    assert not missing, missing


@pytest.mark.parametrize("session", sorted(COMPOSITION))
def test_a_writer_gets_the_planned_composition(session: str) -> None:
    flat = _flat(_text(session))
    missing = [count for count in COMPOSITION[session] if count not in flat]
    assert not missing, missing


@pytest.mark.parametrize("session", ("w1a", "w1b", "w1fix"))
def test_a_letter_writer_puts_every_date_after_the_last_valid_day(session: str) -> None:
    assert "after {L}" in _flat(_text(session))


@pytest.mark.parametrize("session", ("a1", "a1re"))
def test_the_first_blind_reading_has_no_conventions_and_no_answers(session: str) -> None:
    """The convention-free reading: nothing in its brief speaks of the benchmark's conventions or of the dates the
    letters are expected to give."""
    text = _text(session)
    assert not re.search(r"convention|label|expected", text, re.IGNORECASE)


@pytest.mark.parametrize("session", ("a1c", "a1p", "a2", "a2p"))
def test_the_readings_under_the_conventions_get_them(session: str) -> None:
    assert "conventions.md" in _text(session)


@pytest.mark.parametrize("session", ADJUDICATORS)
def test_an_adjudication_hides_which_side_is_which(session: str) -> None:
    """X and Y in an order drawn at random for each case, neither marked; the brief never calls either side the
    case's label or gold."""
    text = _text(session)
    flat = _flat(text).lower()
    assert "at random for each case" in flat and "you are not told which" in flat
    assert not re.search(r"\blabel|\bgold\b", text, re.IGNORECASE)


@pytest.mark.parametrize("session", ADJUDICATORS)
def test_an_adjudication_fixes_its_verdicts_and_what_each_does(session: str) -> None:
    """The four verdicts, each with its consequence, in a section of their own: fixed here, before any letter or
    question exists, and the same for both sides."""
    text = _text(session)
    verdicts = _section(text, "## What each verdict does")
    for verdict in VERDICTS:
        assert f"`{verdict}`" in verdicts, verdict
    assert text.index("## What each verdict does") > text.index("## What you write")
