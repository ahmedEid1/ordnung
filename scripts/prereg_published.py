"""After publication, the final run's pre-registration is checked at the commit that published it (zero tokens).

Until the final run is published, ``tests/test_preregistration.py`` holds HEAD to the freeze: the frozen paths, the
code map, the paths allowed to change. CI ran it on every pull request and every push to main from the freeze on, and
the publication rests on the run at the publish commit: there its own copy passes whole. The checks cannot hold after
it: the pre-registration itself plans later changes (a scorer bug fixed in ``-rescored`` files, a label error from the
blind review or from an owner's finding sent through it, and the owner's checks published per id), and the code goes
on. So once :data:`RECORD` names the publish commit, the checks that hold HEAD to the freeze verify that commit, read
from git, for good; HEAD may move on. The record is committed after the publish commit, never in it, with the URL of
the amendment on the pre-registration issue that says so, and the sha256 of the files that check the
pre-registration after publication (:data:`CHECKED_BY`).

* :func:`record_problems`: the record names a commit on HEAD's first-parent line (main's own history) after the
  freeze, a comment on the pre-registration issue, and the files that check it; :func:`first_publication_problems`
  asks that commit to be the first on that line after the freeze that holds a final analysis of the registered
  pre-registration, so neither a commit before publication nor a later one (not even one that adds the analysis
  back after a removal) can be named; :func:`checked_by_problems` holds those files to the record, and
  :func:`record_history_problems` holds the record's history: once written it stays, and a change of its commit or
  of those files names an amendment no earlier version named. :func:`record_check` runs them all on a record about
  to be written (``--write-record``) or committed (``--check-record``).
* :func:`run_frozen_tests` runs that commit's own ``tests/test_preregistration.py``, every test, the slow ones too,
  in a temporary detached worktree of it, with its own first-party code first on ``sys.path``; this checkout's own
  folders (its editable install's ``src``) are taken off ``sys.path`` and pytest's plugin autoload is off, so neither
  its packages nor its plugins run there. The interpreter and the libraries installed in it are this checkout's.
  :func:`outcome_problems` asks every test to pass, none skipped, every first-party module imported from the
  worktree and no module from this checkout. The run is stopped and the worktree removed whatever happens (a
  timeout, Ctrl-C, SIGTERM).
* What was published stays at HEAD: :func:`unchanged_problems` (the registered files, and the results files the final
  run added, :func:`added_results`), :func:`final_analysis_problems` (the final analysis, byte for byte until a
  deviation is recorded after publication; then rendered again with only its list of deviations, the deviations
  file's sha256 and count and, for a label error, the label-corrected sensitivity changed),
  :func:`deviations_kept_problems` (the deviations file only grows, by ``label_error`` and ``scorer_bug`` entries) and
  :func:`deviations_history_problems` (at every commit after the publish commit the file is there, and an entry
  stays as it was recorded), :func:`stress_fingerprint_problems` (the stress run was recorded with the registered
  code) and :func:`readme_problems` (the README's generated block, for every 0.4.x release, with only its count of
  deviations growing with the file).

Only the files in :data:`CHECKED_BY` are held; what runs them (``tests/conftest.py``, pyproject.toml's pytest
settings, ``.github/workflows/ci.yml``) is not, so a change there shows in review, not in these checks. The checks
guard against changes made by mistake; a change made on purpose shows in the history and on the issue.

It prints and returns paths, ids, commits and counts, never a letter, a label or a prompt.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
import xml.etree.ElementTree as ElementTree
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.prereg_hashes import AFTER_PUBLICATION, COMMENT_URL, COMMIT, DEVIATIONS_PATH, bound_issue

ROOT = Path(__file__).resolve().parents[1]

#: The record of the publication, committed after the publish commit (``evals/preregistration/**`` may change).
RECORD = "evals/preregistration/published-0.4.0.json"
#: The registered pre-registration, whose final analysis the record's commit published.
PREREG_PATH = "evals/preregistration/final-0.4.0.json"
SCHEMA = "ordnung-prereg-published/1"
#: The record's keys: its schema, the publish commit's full sha, the amendment's comment URL and the sha256 of each
#: file in :data:`CHECKED_BY`; ``about`` may say in words what it is.
RECORD_KEYS = ("schema", "commit", "amendment", "checked_by")
OPTIONAL_RECORD_KEYS = ("about",)
#: The test the publish commit runs on itself, frozen with the pre-registration.
FROZEN_TEST = "tests/test_preregistration.py"
#: The files that check the pre-registration after publication. Once the freeze checks skip at HEAD nothing else holds
#: them, so the record names each one's sha256 as merged, and the amendment does too: changing one is a new amendment
#: on the pre-registration issue, which the record then names (:func:`record_history_problems`).
CHECKED_BY = (FROZEN_TEST, "scripts/prereg_published.py", "scripts/prereg_hashes.py")
ABOUT = (
    "The commit on main that published the final run of 0.4.0, the amendment on the pre-registration issue that moves "
    "the freeze checks of tests/test_preregistration.py to it, and the sha256 of the files that check the "
    "pre-registration after publication."
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
#: Where the final run's results files land at publish (``evals/results/pending/`` holds the checkpoints until then).
RESULTS = ("evals/results", "evals/retakes")
PENDING = "evals/results/pending/"
#: The packages whose modules the publish commit's test must import from its own worktree.
FIRST_PARTY = ("ordnung", "evals", "scripts")
#: Long enough for the slow build of the planned day (about two minutes on a laptop) on a slow runner.
TIMEOUT = 1500.0
_BEGIN = "<!-- evals:begin"
_END = "<!-- evals:end"
_VERSION = re.compile(r"""^__version__\s*(?::[^=\n]+)?=\s*["']([^"']+)["']""", re.MULTILINE)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)


def _is_commit(root: Path, sha: str) -> bool:
    return _git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def _ancestor(root: Path, older: str, newer: str) -> bool:
    return _git(root, "merge-base", "--is-ancestor", older, newer).returncode == 0


def at_commit(root: Path, commit: str, path: str) -> bytes | None:
    """The bytes of ``path`` at ``commit`` (``None`` when it holds no such file)."""
    done = _git(root, "cat-file", "blob", f"{commit}:{path}")
    return done.stdout if done.returncode == 0 else None


def load_record(root: Path) -> Any:
    """The record :data:`RECORD` holds (``None`` until it is committed, that is until the final run is published)."""
    path = root / RECORD
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


# --------------------------------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------------------------------


def _first_parents(root: Path) -> set[str]:
    """The commits of HEAD's first-parent line: on main, main's own commits (a merged PR's commits are not)."""
    return set(_git(root, "rev-list", "--first-parent", "HEAD").stdout.decode().split())


def record_problems(record: Any, root: Path, *, freeze: str, issue: str | None) -> list[str]:
    """Why ``record`` does not name a commit that can end the freeze (empty: it does): its keys and schema; its
    ``commit`` a full sha of this repository, on HEAD's first-parent line and after ``freeze``; its ``amendment`` a
    comment on ``issue``, the pre-registration issue (the first checkpoint commit names it,
    ``prereg_hashes.bound_issue``); its ``checked_by`` a sha256 for each of :data:`CHECKED_BY`."""
    if not isinstance(record, Mapping):
        return [f"{RECORD} is not a JSON object"]
    out = [f"{RECORD}: {key} missing" for key in RECORD_KEYS if key not in record]
    checks = record.get("checked_by")
    if "checked_by" in record and (
        not isinstance(checks, Mapping)
        or sorted(checks) != sorted(CHECKED_BY)
        or not all(isinstance(value, str) and _SHA256.fullmatch(value) for value in checks.values())
    ):
        out.append(f"{RECORD}: checked_by is not the sha256 of each of {', '.join(CHECKED_BY)}")
    out += [
        f"{RECORD}: unknown key {key}" for key in sorted(set(record) - {*RECORD_KEYS, *OPTIONAL_RECORD_KEYS})
    ]
    if "schema" in record and record["schema"] != SCHEMA:
        out.append(f"{RECORD}: schema is not {SCHEMA}")
    commit = record.get("commit")
    if "commit" in record:
        if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            out.append(f"{RECORD}: commit is not a full commit sha")
        elif not _is_commit(root, commit):
            out.append(f"{RECORD}: {commit} is not a commit of this repository (a shallow clone?)")
        elif not _ancestor(root, commit, "HEAD"):
            out.append(f"{RECORD}: {commit} is not in HEAD's history")
        elif commit not in _first_parents(root):
            out.append(
                f"{RECORD}: {commit} is not on HEAD's first-parent line (main's own history): name the commit on main "
                "that published the final run (the publish PR's merge commit), not one main reached through a merge; "
                "if a push moved main so that this commit left its first-parent line, a merge with the last good "
                "main as first parent puts it back (docs/releasing.md)"
            )
        elif not _ancestor(root, freeze, commit):
            out.append(f"{RECORD}: {commit} does not descend from the freeze {freeze}")
    amendment = record.get("amendment")
    if "amendment" in record:
        if issue is None:
            out.append(f"{RECORD}: no pre-registration issue in the history to hold the amendment to")
        elif (
            not isinstance(amendment, str)
            or not COMMENT_URL.fullmatch(amendment)
            or amendment.split("#", 1)[0] != issue.rstrip("/")
        ):
            out.append(f"{RECORD}: the amendment is not a comment on {issue}")
    return out


def final_analyses_at(root: Path, commit: str, pattern: str, prereg: Mapping[str, str]) -> list[str]:
    """The final analyses ``commit`` holds that read the registered pre-registration: each file matching ``pattern``
    (the templates' ``files.final``) whose ``meta.kind`` is ``final`` and whose ``meta.prereg`` is ``prereg`` (its
    path and sha256). None at a commit before publication."""
    folder = pattern.rsplit("/", 1)[0]
    listed = _git(root, "ls-tree", "-z", "--name-only", commit, f"{folder}/")
    names = sorted(name for name in listed.stdout.decode().split("\0") if fnmatch.fnmatchcase(name, pattern))
    found = []
    for name in names:
        try:
            meta = json.loads(at_commit(root, commit, name) or b"null")["meta"]
        except (ValueError, TypeError, KeyError):
            continue
        if isinstance(meta, Mapping) and meta.get("kind") == "final" and meta.get("prereg") == dict(prereg):
            found.append(name)
    return found


def first_publication_problems(
    root: Path, commit: str, pattern: str, prereg: Mapping[str, str], *, freeze: str
) -> list[str]:
    """Why ``commit`` is not the commit that published the final run (empty: it is): it holds a final analysis of the
    registered pre-registration (:func:`final_analyses_at`), and it is the first commit on HEAD's first-parent line
    after ``freeze`` that holds one. A later commit holds the analysis too, even one that adds it back after a commit
    that removed it, and may have changed what its own frozen test allows to change (the README's block, a results
    file other than the final reads); naming it would hold HEAD to that version."""
    if not final_analyses_at(root, commit, pattern, prereg):
        return [f"{commit} published no final analysis of the registered pre-registration"]
    line = (
        _git(root, "rev-list", "--first-parent", "--reverse", "HEAD", "--not", freeze).stdout.decode().split()
    )
    first = next((sha for sha in line if final_analyses_at(root, sha, pattern, prereg)), None)
    if first != commit:
        return [
            f"{commit}: not the first commit on HEAD's first-parent line after the freeze that holds a final analysis "
            f"of the registered pre-registration ({first[:12] if first else 'none'} is): name that one"
        ]
    return []


def checked_by(root: Path) -> dict[str, str]:
    """The sha256 of each file in :data:`CHECKED_BY`, as this checkout holds it."""
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in CHECKED_BY}


def checked_by_problems(record: Mapping[str, Any], root: Path) -> list[str]:
    """Each file in :data:`CHECKED_BY` that is not the one the record names by its sha256."""
    given = record.get("checked_by")
    named: Mapping[str, Any] = given if isinstance(given, Mapping) else {}
    out = []
    for path in CHECKED_BY:
        file = root / path
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != named.get(path):
            out.append(
                f"{path}: not the file the record names (its sha256 differs): a change to the checks after "
                "publication is an amendment on the pre-registration issue, and the record names it"
            )
    return out


#: What a commit holds of a JSON file when it holds no JSON: no file, or one that is not JSON (:func:`_states`).
_ABSENT, _INVALID = object(), object()
#: The checkout itself, after HEAD, in :func:`record_history_problems`.
_CHECKOUT = "the checkout"


def _graph(root: Path, *span: str) -> list[tuple[str, tuple[str, ...]]]:
    """The commits of ``span`` (``git rev-list`` arguments; HEAD's whole history by default), parents before
    children, each with its parents."""
    done = _git(root, "rev-list", "--topo-order", "--reverse", "--parents", *(span or ("HEAD",)))
    rows = [line.split() for line in done.stdout.decode().splitlines() if line.strip()]
    return [(row[0], tuple(row[1:])) for row in rows]


def _states(root: Path, commits: Iterable[str], path: str) -> dict[str, Any]:
    """What ``path`` holds at each of ``commits``: its JSON, :data:`_INVALID` or :data:`_ABSENT` (one ``git cat-file
    --batch-check`` for them all, and one read for each distinct file)."""
    shas = list(dict.fromkeys(commits))
    if not shas:
        return {}
    done = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        input="".join(f"{sha}:{path}\n" for sha in shas).encode(),
        capture_output=True,
        check=False,
    )
    lines = done.stdout.decode().splitlines()
    if len(lines) != len(shas):
        raise RuntimeError(f"git cat-file --batch-check answered {len(lines)} lines for {len(shas)} commits")
    files: dict[str, Any] = {}
    out: dict[str, Any] = {}
    for sha, line in zip(shas, lines, strict=True):
        oid, _, kind = line.partition(" ")
        if kind != "blob":
            out[sha] = _ABSENT
            continue
        if oid not in files:
            try:
                files[oid] = json.loads(_git(root, "cat-file", "blob", oid).stdout)
            except ValueError:
                files[oid] = _INVALID
        out[sha] = files[oid]
    return out


def _deviation_comments(root: Path) -> set[str]:
    """The comment URLs the deviations file in the checkout names (``issue_comment_url``)."""
    path = root / DEVIATIONS_PATH
    try:
        entries = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    except ValueError:
        return set()
    if not isinstance(entries, list):
        return set()
    return {
        str(entry["issue_comment_url"])
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("issue_comment_url")
    }


def record_history_problems(root: Path, *, current: Any = None) -> list[str]:
    """Why the record's history, over every commit of HEAD's history and the checkout, does not keep the amendment
    rule (empty: it does). Once a commit holds the record, every commit after it holds it as a JSON object (a commit
    that removed it, or broke it, is reported, and the next version is compared with the last one that held). Each
    version that changed the ``commit`` or ``checked_by`` of the version before it names a new amendment: one no
    earlier version named. No version names a deviation's comment as its amendment, and none goes back to an
    amendment an earlier version named. Merges compare with each parent. ``current`` stands for the checkout's record
    (one about to be written)."""
    graph = _graph(root)
    states = _states(root, (sha for sha, _ in graph), RECORD)
    path = root / RECORD
    if current is not None or path.is_file():
        try:
            states[_CHECKOUT] = (
                current if current is not None else json.loads(path.read_text(encoding="utf-8"))
            )
        except ValueError:
            states[_CHECKOUT] = _INVALID
        head = graph[-1][0] if graph else None
        if head is None or states[_CHECKOUT] != states.get(head):
            graph.append((_CHECKOUT, (head,) if head else ()))
    deviations = _deviation_comments(root)
    #: per commit: the last version that held along its history, and every amendment its history named
    last: dict[str, Mapping[str, Any] | None] = {}
    named: dict[str, frozenset[str]] = {}
    out: list[str] = []

    def note(problem: str) -> None:
        if problem not in out:
            out.append(problem)

    for sha, parents in graph:
        known = [p for p in parents if p in last]
        state = states.get(sha, _ABSENT)
        before = [last[p] for p in known if last[p] is not None]
        seen = frozenset().union(*(named[p] for p in known)) if known else frozenset()
        where = sha if sha == _CHECKOUT else sha[:12]
        if not isinstance(state, Mapping):
            if before:
                what = "missing" if state is _ABSENT else "not a JSON object"
                note(
                    f"{RECORD}: {what} at {where}, after an earlier commit held it (once written, the record stays)"
                )
            last[sha] = before[0] if before else None
            named[sha] = seen
            continue
        amendment = state.get("amendment")
        if isinstance(amendment, str) and amendment in deviations:
            note(
                f"{RECORD}: its amendment {amendment} is a deviation's comment on the issue, not an amendment"
            )
        for parent in known:
            previous = last[parent]
            if previous is None or previous == state:
                continue
            if previous.get("amendment") == amendment:
                for key in ("commit", "checked_by"):
                    if previous.get(key) != state.get(key):
                        note(f"{RECORD}: its {key} changed without a new amendment")
            elif amendment in named[parent]:
                note(
                    f"{RECORD}: it names the amendment {amendment} again, which an earlier version named: each "
                    "change names a new amendment"
                )
        last[sha] = state
        named[sha] = (seen | {amendment}) if isinstance(amendment, str) else seen
    return out


def new_record(root: Path, commit: str, amendment: str) -> dict[str, Any]:
    """The record :func:`write_record` writes: the publish commit, the amendment and the sha256 of the files that
    check after publication, as this checkout holds them."""
    return {
        "schema": SCHEMA,
        "commit": commit,
        "amendment": amendment,
        "checked_by": checked_by(root),
        "about": ABOUT,
    }


def _registered_prereg(root: Path) -> dict[str, Any]:
    data = json.loads((root / PREREG_PATH).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def record_check(root: Path, record: Any, prereg: Mapping[str, Any], *, issue: str | None) -> list[str]:
    """Every reason ``record`` cannot be the record, by the checks the tests make (empty: it can):
    :func:`record_problems`, :func:`first_publication_problems`, :func:`checked_by_problems` and
    :func:`record_history_problems` with ``record`` as the checkout's. ``prereg`` is the registered
    pre-registration (its freeze and the final analysis' file pattern), ``issue`` the issue it is bound to."""
    freeze = str(prereg["registered"]["freeze_sha"])
    out = record_problems(record, root, freeze=freeze, issue=issue)
    if not isinstance(record, Mapping):
        return out
    if not out:
        registered = {
            "file": PREREG_PATH,
            "sha256": hashlib.sha256((root / PREREG_PATH).read_bytes()).hexdigest(),
        }
        pattern = str(prereg["sentences"]["files"]["final"])
        out += first_publication_problems(root, str(record["commit"]), pattern, registered, freeze=freeze)
    out += checked_by_problems(record, root)
    out += record_history_problems(root, current=record)
    return out


def write_record(root: Path, commit: str, amendment: str) -> dict[str, Any]:
    """Write :data:`RECORD`: the publish commit, the amendment and the sha256 of the files that check after
    publication, as this checkout holds them (run it on the after-publish branch as it will be merged)."""
    record = new_record(root, commit, amendment)
    path = root / RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


# --------------------------------------------------------------------------------------------------
# What was published stays
# --------------------------------------------------------------------------------------------------


def added_results(root: Path, freeze: str, commit: str) -> list[str]:
    """The results files the history from ``freeze`` to ``commit`` added: under :data:`RESULTS`, the checkpoints'
    :data:`PENDING` aside (they leave it at publish). Files it changed (``INDEX.json``, ``items.csv``) are not the final
    run's and may change again."""
    done = _git(
        root, "diff", "--name-only", "--no-renames", "--diff-filter=A", "-z", freeze, commit, "--", *RESULTS
    )
    return sorted(name for name in done.stdout.decode().split("\0") if name and not name.startswith(PENDING))


def unchanged_problems(root: Path, commit: str, paths: Iterable[str]) -> list[str]:
    """Each of ``paths`` whose file in the checkout is not byte for byte the one ``commit`` holds."""
    out = []
    for path in paths:
        then = at_commit(root, commit, path)
        file = root / path
        if then is None:
            out.append(f"{path}: not at the publish commit")
        elif not file.is_file():
            out.append(f"{path}: removed since the publish commit {commit[:12]}")
        elif file.read_bytes() != then:
            out.append(f"{path}: changed since the publish commit {commit[:12]}")
    return out


#: What a deviation recorded after publication changes in the final analysis rendered again: the deviations it lists
#: (:func:`deviations_kept_problems` holds them) and the deviations file it read, its sha256 and count; a label error
#: also changes the label-corrected sensitivity (§17: "the primary stays; label-corrected sensitivity").
_REDRAWN = (("meta", "deviations"), ("meta", "frozen_check", "deviations_file", "sha256"))
_REDRAWN_COUNT = ("meta", "frozen_check", "deviations_file", "entries")
_LABEL_CORRECTED = ("sensitivities", "label_corrected")
_MISSING = object()


def _differences(
    then: Any, now: Any, path: tuple[str, ...], allowed: Collection[tuple[str, ...]]
) -> Iterator[tuple[str, ...]]:
    if path in allowed:
        return
    if isinstance(then, Mapping) and isinstance(now, Mapping):
        for key in sorted({*then, *now}, key=str):
            yield from _differences(
                then.get(key, _MISSING), now.get(key, _MISSING), (*path, str(key)), allowed
            )
    elif isinstance(then, list) and isinstance(now, list) and len(then) == len(now):
        for index, (old, new) in enumerate(zip(then, now, strict=True)):
            yield from _differences(old, new, (*path, str(index)), allowed)
    elif then is _MISSING or now is _MISSING or then != now or type(then) is not type(now):
        yield path


def final_analysis_problems(path: str, now: bytes, published: bytes) -> list[str]:
    """Why the final analysis ``now`` is not the one published (empty: it is). Byte for byte, until a deviation is
    recorded after publication: the analysis reads the deviations file, so it is rendered again then (§10, §17), and
    only its list of deviations (the published ones unchanged and first; only label errors and scorer bugs after
    them), the file's sha256 and count and, for a label error, the label-corrected sensitivity may change. The
    primary, secondary and exploratory results stay what was published."""
    if now == published:
        return []
    changed = [f"{path}: changed since the publish commit"]
    try:
        then_doc, now_doc = json.loads(published), json.loads(now)
    except ValueError:
        return changed
    if not isinstance(then_doc, Mapping) or not isinstance(now_doc, Mapping):
        return changed
    then_list = (then_doc.get("meta") or {}).get("deviations")
    now_list = (now_doc.get("meta") or {}).get("deviations")
    if not isinstance(then_list, list) or not isinstance(now_list, list) or len(now_list) == len(then_list):
        return changed
    out = [f"{path}: meta.deviations: {problem}" for problem in deviations_kept_problems(now_list, then_list)]
    allowed = {*_REDRAWN, _REDRAWN_COUNT}
    added = now_list[len(then_list) :]
    if any(isinstance(entry, Mapping) and entry.get("kind") == "label_error" for entry in added):
        allowed.add(_LABEL_CORRECTED)
    out += [
        f"{path}: {'.'.join(where)} differs from the publish commit's"
        for where in _differences(then_doc, now_doc, (), allowed)
    ]
    return out


def stress_fingerprint_problems(
    doc: Any, registered: Mapping[str, str], deviations: Sequence[Any]
) -> list[str]:
    """Why the stress results file ``doc`` was not recorded with the registered code (empty: it was): every
    fingerprint it holds, the run's and each read's (``meta.runs``), is the pre-registration's for its condition, or
    one a runner fix's ``code_hash_changed`` deviation names (``applies_to.fingerprints``). The stress replay compares
    numbers, not fingerprints, which the code of a later commit changes; this holds the recording to the registration
    instead."""
    allowed: dict[str, set[str]] = {condition: {value} for condition, value in registered.items()}
    for entry in deviations:
        if not isinstance(entry, Mapping) or entry.get("kind") != "code_hash_changed":
            continue
        fixed = (entry.get("applies_to") or {}).get("fingerprints")
        if isinstance(fixed, Mapping):
            for condition, value in fixed.items():
                allowed.setdefault(str(condition), set()).add(str(value))
    meta = doc.get("meta") if isinstance(doc, Mapping) else None
    if not isinstance(meta, Mapping):
        return ["the stress results file has no meta"]
    runs = meta.get("runs")
    places: list[tuple[str, Any]] = [("meta.fingerprints", meta.get("fingerprints"))]
    if isinstance(runs, Mapping):
        places += [
            (f"meta.runs.{name}.fingerprints", (run or {}).get("fingerprints"))
            for name, run in sorted(runs.items())
        ]
    else:
        places.append(("meta.runs", None))
    out = []
    for place, prints in places:
        if not isinstance(prints, Mapping) or not prints:
            out.append(f"{place}: no fingerprints")
            continue
        out += [
            f"{place}.{condition}: not the registered fingerprint"
            for condition, value in sorted(prints.items())
            if value not in allowed.get(str(condition), set())
        ]
    return out


def deviations_kept_problems(now: Any, published: Any) -> list[str]:
    """Why the deviations file ``now`` is not the published one ``published`` with entries appended (empty: it is),
    and each appended entry whose kind may not be recorded after publication (``prereg_hashes.AFTER_PUBLICATION``:
    a label error from the blind review, a scorer bug)."""
    if not isinstance(now, list) or not isinstance(published, list):
        return ["the deviations file is not a JSON list (now or at the publish commit)"]
    if now[: len(published)] != published:
        return [
            "the deviations file is append-only after publication: an entry the publish commit holds was changed, "
            "removed or moved"
        ]
    out = []
    for entry in now[len(published) :]:
        kind = entry.get("kind") if isinstance(entry, Mapping) else None
        if kind not in AFTER_PUBLICATION:
            ident = entry.get("id") if isinstance(entry, Mapping) else entry
            out.append(
                f"{ident}: a {kind} deviation recorded after publication "
                f"(only {' and '.join(AFTER_PUBLICATION)} can be)"
            )
    return out


def _entry_key(entry: Any) -> str:
    ident = entry.get("id") if isinstance(entry, Mapping) else None
    return ident if isinstance(ident, str) else json.dumps(entry, sort_keys=True)


def _kept(before: Any, after: Any) -> bool:
    """``after`` is the entry ``before`` was, but for a ``checkpoint_sha`` filled in where it was empty."""
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return bool(before == after)
    rest = {key: value for key, value in before.items() if key != "checkpoint_sha"}
    if rest != {key: value for key, value in after.items() if key != "checkpoint_sha"}:
        return False
    return not before.get("checkpoint_sha") or before.get("checkpoint_sha") == after.get("checkpoint_sha")


def deviations_history_problems(root: Path, commit: str) -> list[str]:
    """Why the deviations file's history after the publish commit ``commit`` does not keep what it recorded (empty:
    it does). At every commit that descends from ``commit`` (``git rev-list --ancestry-path``) and in the checkout the
    file is there and a JSON list, and each entry the commit's parent held (the publish commit, or a commit after it)
    is still there, unchanged but for a ``checkpoint_sha`` filled in once. A commit that removes or breaks the file is
    reported, and the next version is compared with the last one that held, so an entry cannot be rewritten through a
    gap. Entries are matched by id, so a merge of two branches that each added one is fine."""
    path = DEVIATIONS_PATH
    graph = _graph(root, "--ancestry-path", f"{commit}..HEAD")
    states = _states(root, [commit, *(sha for sha, _ in graph)], path)
    file = root / path
    try:
        checkout: Any = json.loads(file.read_text(encoding="utf-8")) if file.is_file() else _ABSENT
    except ValueError:
        checkout = _INVALID
    head = graph[-1][0] if graph else commit
    graph.append((_CHECKOUT, (head,)))
    states[_CHECKOUT] = checkout
    last: dict[str, dict[str, Any] | None] = {
        commit: {_entry_key(e): e for e in states[commit]} if isinstance(states[commit], list) else None
    }
    out: list[str] = []
    for sha, parents in graph:
        held = [entries for p in parents if (entries := last.get(p)) is not None]
        state = states.get(sha, _ABSENT)
        where = "in the checkout" if sha == _CHECKOUT else f"at {sha[:12]}"
        if not isinstance(state, list):
            if state is _ABSENT:
                out.append(f"{path}: missing {where}, after the publish commit (it stays for good)")
            else:
                out.append(f"{path}: not a JSON list {where}")
            last[sha] = held[0] if held else None
            continue
        now = {_entry_key(e): e for e in state}
        for entries in held:
            for key, entry in entries.items():
                if key not in now or not _kept(entry, now[key]):
                    problem = (
                        f"{path}: {key} changed or removed {where} (an entry stays as it was recorded; only its "
                        "checkpoint_sha is filled in, once)"
                    )
                    if problem not in out:
                        out.append(problem)
        last[sha] = now
    return out


def readme_block(text: str) -> list[str] | None:
    """The README's generated block, its two marker lines included (``None`` without them)."""
    lines = text.splitlines()
    begins = [i for i, line in enumerate(lines) if line.startswith(_BEGIN)]
    if len(begins) != 1:
        return None
    ends = [i for i, line in enumerate(lines) if i > begins[0] and line.startswith(_END)]
    return lines[begins[0] : ends[0] + 1] if ends else None


def _words(lines: Sequence[str]) -> str:
    return " ".join(" ".join(lines).split())


def readme_problems(
    now: str, published: str, *, template: str, deviations_file: str, deviations: int
) -> list[str]:
    """Why the README ``now`` does not keep the generated block the publish commit's README ``published`` holds (empty:
    it does). Word for word the same, laid out in lines as the presenter likes, but for the number the registered
    ``head.deviations`` sentence (``template``) counts: the deviations file's entries, ``deviations`` now, never fewer
    than at publication."""
    then_block, now_block = readme_block(published), readme_block(now)
    if then_block is None:
        return ["the README at the publish commit has no generated block"]
    if now_block is None:
        return [
            "the README has no generated block: the pledge keeps the published one for every 0.4.x release"
        ]
    counted = re.compile(
        re.escape(" ".join(template.split()))
        .replace(re.escape("{deviations_file}"), re.escape(deviations_file))
        .replace(re.escape("{deviations}"), r"(\d+)")
    )
    then_text, now_text = _words(then_block), _words(now_block)
    then_counts, now_counts = counted.findall(then_text), counted.findall(now_text)
    out = []
    if len(then_counts) != len(now_counts):
        out.append(
            "the README's generated block does not say the count of deviations as the published one does"
        )
    for before, after in zip(then_counts, now_counts, strict=False):
        if int(after) != deviations:
            out.append(
                f"the README's block counts {after} deviations; the deviations file holds {deviations}"
            )
        if int(after) < int(before):
            out.append(f"the README's block counts fewer deviations ({after}) than at publication ({before})")
    if counted.sub("#", then_text) != counted.sub("#", now_text):
        out.append(
            "the README's generated block differs from the one published: the pledge keeps it for every 0.4.x release "
            "(only its count of deviations recorded at the time may grow)"
        )
    return out


def version(root: Path) -> str | None:
    """The package's version, read without importing it: ``__version__`` in ``src/ordnung/__init__.py`` (annotated
    or not), else ``pyproject.toml``'s ``[project] version``; ``None`` when neither names one (the pledge's check then
    fails, it does not skip)."""
    path = root / "src" / "ordnung" / "__init__.py"
    found = _VERSION.search(path.read_text(encoding="utf-8")) if path.is_file() else None
    if found:
        return found.group(1)
    pyproject = root / "pyproject.toml"
    try:
        project = (
            tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project")
            if pyproject.is_file()
            else None
        )
    except tomllib.TOMLDecodeError:
        return None
    named = project.get("version") if isinstance(project, Mapping) else None
    return named if isinstance(named, str) else None


# --------------------------------------------------------------------------------------------------
# The publish commit's own test
# --------------------------------------------------------------------------------------------------

#: Where a path is this checkout's but neither the worktree's nor the interpreter's (whose venv may sit in the
#: checkout): the inner run's ``sitecustomize`` and probe both use it.
_OUTSIDE = """
import os
import sys


def _under(path, top):
    return bool(top) and (path == top or path.startswith(top.rstrip(os.sep) + os.sep))


def _outside(path):
    real = os.path.realpath(path or os.curdir)
    keep = [os.environ.get("PREREG_INNER_TREE", ""), sys.prefix, sys.base_prefix, sys.exec_prefix]
    outer = os.path.realpath(os.environ.get("PREREG_OUTER_ROOT", "")) if os.environ.get("PREREG_OUTER_ROOT") else ""
    return _under(real, outer) and not any(_under(real, os.path.realpath(top)) for top in keep if top)
"""
#: The inner run's ``sitecustomize`` (first on ``PYTHONPATH`` after the worktree, so the checkout's own one never
#: runs): it takes this checkout's folders (its editable install's ``src``) off ``sys.path`` before anything else is
#: imported. It stands in for the interpreter's own ``sitecustomize``, which Debian's Python ships for apport only.
_SITECUSTOMIZE = (
    _OUTSIDE
    + """

sys.path[:] = [entry for entry in sys.path if not _outside(entry)]
"""
)
#: A pytest plugin for the inner run: at the end it writes where every first-party module and every test module came
#: from (``__file__``, or a namespace package's folders), and every module of any name that came from this checkout, to
#: the file ``PREREG_INNER_PROBE`` names.
_PROBE = (
    _OUTSIDE
    + """
import importlib
import json


def _files(module):
    file = getattr(module, "__file__", None)
    files = [file] if file else list(getattr(module, "__path__", None) or [])
    return [os.path.realpath(path) for path in files]


def pytest_sessionfinish(session, exitstatus):
    for name in FIRST_PARTY:
        try:
            importlib.import_module(name)
        except Exception:
            pass
    loaded = sorted((name, module) for name, module in list(sys.modules.items()) if module is not None)
    modules = {name: _files(module) for name, module in loaded if name.split(".")[0] in FIRST_PARTY}
    outside = {
        name: files for name, module in loaded if (files := [f for f in _files(module) if _outside(f)])
    }
    tests = sorted({os.path.realpath(item.module.__file__) for item in session.items if getattr(item, "module", None)})
    with open(os.environ["PREREG_INNER_PROBE"], "w", encoding="utf-8") as out:
        json.dump({"modules": modules, "outside": outside, "tests": tests}, out)
"""
)
_PROBE_MODULE = "prereg_inner_probe"


@dataclass
class Outcome:
    """What the publish commit's own test did: each test function's name and result (``passed``, ``failed``,
    ``error``, ``skipped``), the test functions its file defines, where the first-party and test modules came from,
    the modules of any name that came from the checkout that runs it, pytest's exit code and output, and the seconds
    it took."""

    tree: Path
    returncode: int
    tests: list[tuple[str, str]]
    defined: list[str]
    modules: dict[str, list[str]] = field(default_factory=dict)
    test_files: list[str] = field(default_factory=list)
    outside: dict[str, list[str]] = field(default_factory=dict)
    output: str = ""
    seconds: float = 0.0


def inner_environment(
    tree: Path, probe: Path, outer: Mapping[str, str], *, checkout: Path | None = None
) -> dict[str, str]:
    """The inner run's environment: the outer one without its Python and pytest settings (``PYTHON*``, ``PYTEST_*``)
    and coverage's subprocess hooks; ``PYTHONPATH`` the worktree's ``src``, the worktree, then the probe's folder,
    joined with ``os.pathsep``, before the site folder; pytest's plugin autoload off, so no plugin of this checkout's
    environment loads (the publish commit's test needs none); and, for the probe's ``sitecustomize``, where the
    worktree and this ``checkout`` are, so the checkout's folders (its editable install's ``src``) leave ``sys.path``."""
    dropped = ("PYTHON", "PYTEST", "COV_CORE", "COVERAGE", "PREREG_")
    env = {key: value for key, value in outer.items() if not key.upper().startswith(dropped)}
    env["PYTHONPATH"] = os.pathsep.join([str(tree / "src"), str(tree), str(probe)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PREREG_INNER_TREE"] = str(tree)
    if checkout is not None:
        env["PREREG_OUTER_ROOT"] = str(checkout.resolve())
    return env


def _defined(source: str) -> list[str]:
    """The test functions a test file defines at its top level."""
    return sorted(
        node.name
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test")
    )


def _results(report: Path) -> list[tuple[str, str]]:
    """Each test case of a JUnit XML report: its name and how it ended."""
    if not report.is_file():
        return []
    out = []
    for case in ElementTree.parse(report).getroot().iter("testcase"):
        tags = {child.tag for child in case}
        result = next((tag for tag in ("failure", "error", "skipped") if tag in tags), "passed")
        out.append((str(case.get("name")), {"failure": "failed"}.get(result, result)))
    return out


def _stop(process: subprocess.Popen[str]) -> None:
    """Stop the inner run and what it started (its own process group on POSIX)."""
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()


class _Terminated(BaseException):
    """SIGTERM while the publish commit's test runs (:func:`_sigterm_stops_the_run`)."""


@contextlib.contextmanager
def _sigterm_stops_the_run() -> Iterator[None]:
    """While the block runs, SIGTERM raises :class:`_Terminated` instead of ending the process at once, so the inner
    run is stopped and its worktree removed as for Ctrl-C; then the signal is delivered again with the handler that
    was there before (by default the process ends by it). Only in the main thread of a POSIX process, and not where
    SIGTERM is ignored."""
    if os.name != "posix" or threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)
    if previous is signal.SIG_IGN:
        yield
        return

    def terminated(signum: int, frame: Any) -> None:
        raise _Terminated

    signal.signal(signal.SIGTERM, terminated)
    try:
        yield
    except _Terminated:
        signal.signal(signal.SIGTERM, previous)
        signal.raise_signal(signal.SIGTERM)
        raise SystemExit(128 + signal.SIGTERM) from None
    finally:
        signal.signal(signal.SIGTERM, previous)


def run_frozen_tests(
    root: Path,
    commit: str,
    scratch: Path,
    *,
    python: str = sys.executable,
    test_file: str = FROZEN_TEST,
    timeout: float = TIMEOUT,
    extra_args: Sequence[str] = (),
) -> Outcome:
    """Run ``commit``'s own ``test_file`` in a temporary detached worktree of it (``scratch/published``), with that
    commit's first-party code first on ``sys.path`` and pytest's options its own, and report every test case (JUnit
    XML). The interpreter and the libraries installed in it are ``python``'s, this checkout's; the checkout's own
    folders and plugins are kept out (:func:`inner_environment`). The worktree is removed whatever happens, and
    worktrees left by a run that was killed are pruned; a run longer than ``timeout`` seconds is stopped and raises
    ``subprocess.TimeoutExpired``, and a run interrupted otherwise (Ctrl-C, SIGTERM) is stopped too before the
    exception or the signal goes on."""
    with _sigterm_stops_the_run():
        return _run_frozen_tests(
            root, commit, scratch, python=python, test_file=test_file, timeout=timeout, extra_args=extra_args
        )


def _run_frozen_tests(
    root: Path,
    commit: str,
    scratch: Path,
    *,
    python: str,
    test_file: str,
    timeout: float,
    extra_args: Sequence[str],
) -> Outcome:
    scratch.mkdir(parents=True, exist_ok=True)
    tree, probe, report = scratch / "published", scratch / "probe", scratch / "junit.xml"
    probe.mkdir(exist_ok=True)
    (probe / f"{_PROBE_MODULE}.py").write_text(f"FIRST_PARTY = {FIRST_PARTY!r}\n{_PROBE}", encoding="utf-8")
    (probe / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    _git(root, "worktree", "prune")
    added = _git(root, "worktree", "add", "--detach", "--quiet", str(tree), commit)
    if added.returncode != 0:
        raise RuntimeError(
            f"git worktree add {commit} failed: {added.stderr.decode(errors='replace').strip()}"
        )
    try:
        tree = tree.resolve()
        defined = _defined((tree / test_file).read_text(encoding="utf-8"))
        env = inner_environment(tree, probe, os.environ, checkout=root)
        env["PREREG_INNER_PROBE"] = str(scratch / "probe.json")
        command = [python, "-m", "pytest", test_file, "-p", "no:cacheprovider", "-p", _PROBE_MODULE]
        command += ["-rA", f"--junitxml={report}", *extra_args]
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=tree,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=os.name == "posix",
        )
        try:
            output, _ = process.communicate(timeout=timeout)
        except BaseException:
            # the timeout, Ctrl-C, SIGTERM or anything else: the run is in a process group of its own, which the
            # terminal's interrupt never reaches, so it is stopped here, before the worktree it runs in goes
            _stop(process)
            process.communicate()
            raise
        seconds = time.monotonic() - started
        probed = (
            json.loads((scratch / "probe.json").read_text(encoding="utf-8"))
            if (scratch / "probe.json").is_file()
            else {}
        )
        return Outcome(
            tree=tree,
            returncode=process.returncode,
            tests=_results(report),
            defined=defined,
            modules=dict(probed.get("modules") or {}),
            test_files=list(probed.get("tests") or []),
            outside=dict(probed.get("outside") or {}),
            output=output,
            seconds=seconds,
        )
    finally:
        removed = _git(root, "worktree", "remove", "--force", "--force", str(tree))
        if removed.returncode != 0 and tree.exists():
            shutil.rmtree(tree, ignore_errors=True)
        _git(root, "worktree", "prune")


def outcome_problems(outcome: Outcome) -> list[str]:
    """Why the publish commit's own test did not pass whole (empty: it did): pytest's exit code, each test case that
    failed, errored or was skipped (every check must run at the publish commit), each test function of the file that
    did not run, and each first-party or test module imported from outside the worktree."""
    out = []
    if outcome.returncode != 0:
        tail = "\n".join(outcome.output.splitlines()[-30:])
        out.append(f"pytest exited {outcome.returncode}:\n{tail}")
    if not outcome.tests:
        out.append("no test ran")
    for name, result in outcome.tests:
        if result == "skipped":
            out.append(f"{name}: skipped (every check must run at the publish commit)")
        elif result != "passed":
            out.append(f"{name}: {result}")
    ran = {name.split("[", 1)[0] for name, _ in outcome.tests}
    out += [f"{name}: not run" for name in outcome.defined if name not in ran]
    if not outcome.modules or not outcome.test_files:
        out.append("the run did not say where its modules came from")
    for name, files in sorted(outcome.modules.items()):
        outside = [path for path in files if not Path(path).is_relative_to(outcome.tree)]
        if not files or outside:
            out.append(f"{name}: imported from outside the publish commit's worktree ({', '.join(outside)})")
    out += [
        f"{path}: a test module from outside the publish commit's worktree"
        for path in outcome.test_files
        if not Path(path).is_relative_to(outcome.tree)
    ]
    out += [
        f"{name}: imported from this checkout, not the publish commit's worktree ({', '.join(files)})"
        for name, files in sorted(outcome.outside.items())
    ]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.prereg_published",
        description="After publication: print or write the record that names the publish commit.",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--checked-by",
        action="store_true",
        help="print the sha256 of each file that checks the pre-registration after publication (for the amendment)",
    )
    action.add_argument(
        "--write-record",
        nargs=2,
        metavar=("COMMIT", "AMENDMENT"),
        help=(
            f"write {RECORD}: the publish commit on main (40 hex) and the amendment's comment URL; nothing is "
            "written, and it exits 1, unless the record passes the checks the tests make"
        ),
    )
    action.add_argument(
        "--check-record",
        action="store_true",
        help=f"run the checks the tests make on the {RECORD} this checkout holds (exit 1 on a problem)",
    )
    args = parser.parse_args(argv)
    if args.checked_by:
        print(json.dumps(checked_by(ROOT), indent=2))
        return 0
    prereg = _registered_prereg(ROOT)
    issue = bound_issue(ROOT, str(prereg["registered"]["freeze_sha"]))
    if args.check_record:
        record = load_record(ROOT)
        problems = record_check(ROOT, record, prereg, issue=issue) if record is not None else [f"no {RECORD}"]
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{RECORD}: {'holds' if not problems else f'{len(problems)} problem(s)'}")
        return 1 if problems else 0
    commit, amendment = args.write_record
    record = new_record(ROOT, commit, amendment)
    problems = record_check(ROOT, record, prereg, issue=issue)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{RECORD} not written: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    write_record(ROOT, commit, amendment)
    print(f"wrote {RECORD}: {record['commit']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
