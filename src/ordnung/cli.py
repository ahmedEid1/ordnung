"""The ``ordnung`` command line (SPEC §15, §16).

``serve`` runs the local web app (API + UI) on 127.0.0.1 with a session token and advertises it in
``<data>/server.json`` (:mod:`ordnung.server`) so other commands can find it. ``add``, ``brief`` and
``ask`` talk to that server's API when one is running for the data directory; otherwise they run
in-process under an exclusive data-directory lock — refused while hand-off sync has another computer
in use, and saved to the sync folder afterwards (best effort). ``sync`` is hand-off sync between the
person's computers (:mod:`ordnung.sync`): through the running server's API, or in process under the
lock after finishing an interrupted take-over. ``demo`` opens the sample life (prebuilt,
zero tokens), ``doctor`` checks the setup, ``mcp`` is the read-only tool server Ask spawns (stdio —
nothing else may be printed to stdout), ``openapi`` prints the API schema and ``eval`` runs the
benchmark in a source checkout.

Heavy modules are imported inside the commands, so ``python -m ordnung mcp`` starts quickly.
Common problems end with a short explanation and a hint, never a traceback
(``ORDNUNG_DEBUG=1`` shows it).
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import importlib
import json
import os
import re
import signal
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, TypeVar

import typer
from rich.console import Console
from rich.markup import escape as markup_escape
from rich.panel import Panel
from rich.table import Table

from ordnung import __version__
from ordnung.assistant.mcp_install import McpClient
from ordnung.config import REPO_DIR, Paths, default_data_dir, resolve_paths
from ordnung.server import DEFAULT_HOST, DEFAULT_PORT, ServerInfo, advertise, generate_token, running_server

if TYPE_CHECKING:
    import httpx

    from ordnung.app_context import AppContext
    from ordnung.models import Document, DocumentDetail, Item, Job

T = TypeVar("T")

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
FINAL_STATUSES = frozenset({"processed", "needs_review", "failed", "held"})
POLL_S = 0.5
HEALTH_TIMEOUT_S = 2.0
BROWSER_WAIT_S = 15.0
LOGIN_PAGE_NAME = ".ordnung-open.html"
SCHEMA_HINT = "Update Ordnung, or restore a backup made with this version (`ordnung restore FILE --force`)."
# C0/C1 controls except tab and newline, and bidirectional overrides: a letter's title (written by the
# model from an attacker's letter) or a file name must not drive the terminal (e.g. OSC 52 → clipboard)
_TERMINAL_CONTROL_RE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def escape(text: str) -> str:
    """``text`` for the terminal: Rich markup escaped and control sequences removed."""
    return markup_escape(_TERMINAL_CONTROL_RE.sub("", text))


MAX_LISTED_PROBLEMS = 25
STAGE_LABELS = {
    "intake": "Receiving",
    "text": "Reading the text",
    "transcribe": "Reading the photo",
    "extract": "Understanding",
    "verify": "Checking every quote",
    "compute": "Computing dates",
    "link": "Linking to your records",
    "plan": "Planning to-dos",
    "done": "Done",
}
STATUS_ICONS = {"ok": "[green]✓[/]", "warn": "[yellow]![/]", "fail": "[red]✗[/]"}

console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)

app = typer.Typer(
    name="ordnung",
    help="Ordnung — your private AI secretary for life admin. Your files stay on this computer.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
)

DataDirOption = Annotated[
    Path | None,
    typer.Option(
        "--data-dir",
        help="Data folder (default: ORDNUNG_HOME or your user data folder).",
        show_default=False,
    ),
]
DemoDirOption = Annotated[
    Path | None,
    typer.Option(
        "--data-dir",
        help="Demo folder (default: ORDNUNG_DEMO_HOME or a separate ordnung-demo folder — never your data).",
        show_default=False,
    ),
]


@dataclass
class _Options:
    """Global options (``ordnung --data-dir D <command>``)."""

    data_dir: Path | None = None


def _version(value: bool) -> None:
    if value:
        typer.echo(f"ordnung {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    data_dir: DataDirOption = None,
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show the version and exit.")
    ] = False,
) -> None:
    """Ordnung reads your letters with your own Claude, keeps every deadline, and drafts replies."""
    ctx.obj = _Options(data_dir=data_dir)


# --------------------------------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------------------------------


def _fail(message: str, hint: str | None = None, code: int = 1, *, soft_wrap: bool = False) -> typer.Exit:
    """Print an error (and a hint); ``soft_wrap`` for a message with a path, so no line break splits it."""
    err_console.print(f"[red]✗[/] {escape(message)}", soft_wrap=soft_wrap)
    if hint:
        err_console.print(f"  [dim]{escape(hint)}[/]", soft_wrap=soft_wrap)
    return typer.Exit(code)


def _explain(exc: Exception) -> tuple[str, str | None]:
    """A person-readable message and hint for a failure (lazy imports: only on the error path)."""
    import sqlite3

    import httpx

    from ordnung.backup import BackupError
    from ordnung.db.migrate import SchemaError
    from ordnung.demo import DemoError
    from ordnung.ingest.extract import ExtractionError
    from ordnung.ingest.intake import IntakeError
    from ordnung.llm.base import LLMError
    from ordnung.locking import DataDirLocked

    if isinstance(exc, DataDirLocked):
        return str(exc), "If Ordnung's web app is running for this folder, use it — or stop it first."
    if isinstance(exc, LLMError):
        return str(exc), "Run `ordnung doctor` to check Claude."
    if isinstance(exc, SchemaError):
        return str(exc), SCHEMA_HINT
    if isinstance(exc, DemoError | IntakeError | ExtractionError | ApiError | BackupError):
        return str(exc), None
    if isinstance(exc, httpx.HTTPError):
        return f"Couldn't talk to the running Ordnung server: {exc}", "Restart it with `ordnung serve`."
    if isinstance(exc, sqlite3.DatabaseError):
        return f"The database can't be used: {exc}", "Run `ordnung doctor`."
    if isinstance(exc, OSError):
        where = f" ({exc.filename})" if exc.filename else ""
        return f"{exc.strerror or exc}{where}", None
    return f"Unexpected error: {exc}", "Run again with ORDNUNG_DEBUG=1 to see the details."


@contextlib.contextmanager
def _friendly() -> Iterator[None]:
    """Turn common failures into a short message and exit code 1 (130 when interrupted)."""
    try:
        yield
    except (typer.Exit, typer.Abort):
        raise
    except KeyboardInterrupt:
        raise _fail("Stopped.", code=130) from None
    except Exception as exc:
        if os.environ.get("ORDNUNG_DEBUG"):
            raise
        from ordnung.backup import BackupError

        message, hint = _explain(exc)
        # a backup's messages name files and folders: no line break may split a path
        raise _fail(message, hint, soft_wrap=isinstance(exc, BackupError)) from None


# --------------------------------------------------------------------------------------------------
# data folders, the lock and in-process contexts
# --------------------------------------------------------------------------------------------------


def _chosen(ctx: typer.Context, data_dir: Path | None) -> Path | None:
    """The data folder named on the command (wins) or before it; ``None`` if neither."""
    options = ctx.obj if isinstance(ctx.obj, _Options) else _Options()
    chosen = data_dir or options.data_dir
    return chosen.expanduser().resolve() if chosen else None


def _folder(ctx: typer.Context, data_dir: Path | None) -> Path:
    """The data folder without creating it (``--data-dir`` > ``ORDNUNG_HOME`` > user data folder)."""
    return _chosen(ctx, data_dir) or default_data_dir()


def open_context(data_dir: Path) -> AppContext:
    """The in-process application context (demo folders replay recorded answers).

    Tests replace this function to inject a fake model.
    """
    from ordnung.app_context import build_context
    from ordnung.demo.loader import is_demo_dir

    return build_context(data_dir, backend="replay" if is_demo_dir(data_dir) else None)


async def _bound(ctx: AppContext, work: Callable[[AppContext], Awaitable[T]]) -> T:
    ctx.bus.bind_loop(asyncio.get_running_loop())
    return await work(ctx)


def _in_process(paths: Paths, purpose: str, work: Callable[[AppContext], Awaitable[T]]) -> T:
    """Run ``work`` on an in-process context while holding the data folder's exclusive lock.

    With hand-off sync connected, it is refused while another computer is in use (with how to take
    over); otherwise its writes are the person's changes, and the sync folder gets them right after
    (best effort: one line says whether it worked)."""
    from ordnung.db.store import person_write
    from ordnung.locking import DataDirLock

    with DataDirLock(paths.data_dir, purpose=purpose):
        engine = _sync_engine_if_connected(paths)
        _refuse_while_standing_by(engine, paths)
        ctx = open_context(paths.data_dir)
        try:
            with person_write(engine is not None):
                result = asyncio.run(_bound(ctx, work))
        finally:
            ctx.close()
        _save_to_sync_folder(engine, paths)
        return result


def _sync_engine_if_connected(paths: Paths) -> Any:
    """Hand-off sync's engine when sync is connected for this data folder (else ``None``)."""
    from ordnung.app_context import sync_connected
    from ordnung.sync.agent import load_engine

    return load_engine() if sync_connected(paths) else None


SYNC_TAKE_OVER_HINT = "Run “ordnung sync use-here” to use it on this computer."


def _refuse_while_standing_by(engine: Any, paths: Paths) -> None:
    """Writes are refused on a computer standing by (reads only the sync state file)."""
    refused = engine.writes_refused(paths) if engine is not None else None
    if refused:
        raise _fail(str(refused), SYNC_TAKE_OVER_HINT)


def _save_to_sync_folder(engine: Any, paths: Paths) -> None:
    """Save the command's changes to the sync folder now (best effort; skipped without a keyring)."""
    if engine is None:
        return
    from ordnung.sync.agent import default_secrets

    try:
        said = engine.push_once(paths, default_secrets())
    except Exception as exc:  # the change is made here; the server's next start saves it
        said = f"Not saved to the sync folder yet: {exc}"
    if said:
        err_console.print(f"[dim]{escape(str(said))}[/]")


# --------------------------------------------------------------------------------------------------
# server.json and the API client
# --------------------------------------------------------------------------------------------------


def reachable_server(data_dir: Path) -> ServerInfo | None:
    """The server of this data folder, if ``server.json`` names a live process that answers for it."""
    import httpx

    info = running_server(data_dir)
    if info is None:
        return None
    try:
        response = httpx.get(
            info.api_url("health"), headers=info.auth_headers(), timeout=HEALTH_TIMEOUT_S, trust_env=False
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    served = _json_object(response).get("data_dir")
    if served and Path(str(served)).expanduser().resolve() != data_dir.resolve():
        return None
    return info


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _json_list(response: httpx.Response) -> list[Any]:
    try:
        value = response.json()
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def _api(info: ServerInfo, timeout: float | None = 30.0) -> httpx.Client:
    """A client for the local server; never through a proxy (the session token stays on this computer)."""
    import httpx

    return httpx.Client(base_url=info.base_url, headers=info.auth_headers(), timeout=timeout, trust_env=False)


class ApiError(RuntimeError):
    """The running server answered a request with an error (the message is its explanation)."""


def _checked(response: httpx.Response) -> httpx.Response:
    """Raise :class:`ApiError` for an error response of the API."""
    if response.status_code >= 400:
        detail = _json_object(response).get("detail") or response.text[:200]
        raise ApiError(f"The running Ordnung answered {response.status_code}: {detail}")
    return response


# --------------------------------------------------------------------------------------------------
# summaries
# --------------------------------------------------------------------------------------------------


def _day(value: str | None) -> str:
    if not value:
        return ""
    try:
        return date.fromisoformat(value).strftime("%a %d %b %Y")
    except ValueError:
        return value


def next_date(items: Sequence[Item], today: date) -> str:
    """The next open date of a letter (the earliest upcoming one, else the latest past one)."""
    dated = sorted(
        (item for item in items if item.status == "open" and item.due_date), key=lambda i: i.due_date or ""
    )
    if not dated:
        return "—"
    upcoming = [item for item in dated if (item.due_date or "") >= today.isoformat()]
    chosen = upcoming[0] if upcoming else dated[-1]
    return f"{_day(chosen.due_date)} · {chosen.title}"


def _status_text(document: Document, waits: bool = False) -> str:
    if waits:
        return "[yellow]Waiting for Claude[/]"
    if document.status == "failed":
        return f"[red]Failed[/] — {escape(document.error or '')}"
    if document.status == "held":
        return "Not read yet — not sent to Claude"
    if document.ai_private:
        return "Private — not sent to Claude"
    if document.status == "needs_review":
        return "[yellow]Please check[/]"
    if document.status == "processed":
        return "[green]✓[/]"
    return document.status


def summary_table(
    rows: Sequence[tuple[Document, str | None, Sequence[Item]]],
    today: date,
    waiting: Mapping[str, str] | None = None,
) -> Table:
    """One row per letter: title, sender, next date and whether it needs checking (or waits for Claude:
    ``waiting`` maps those letters to why)."""
    table = Table(title="Your letters", title_justify="left", show_lines=False)
    table.add_column("Letter", overflow="fold")
    table.add_column("From", overflow="fold")
    table.add_column("Next date", overflow="fold")
    table.add_column("Please check", overflow="fold")
    for document, sender, items in rows:
        table.add_row(
            escape(document.title or document.filename),
            escape(sender or "—"),
            escape(next_date(items, today)),
            _status_text(document, document.id in (waiting or {})),
        )
    return table


# --------------------------------------------------------------------------------------------------
# serve
# --------------------------------------------------------------------------------------------------


def _port_free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        if sys.platform != "win32":  # on Windows it lets a bind share a port in use
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def login_page(folder: Path, info: ServerInfo) -> Path:
    """A private page (``0600``, in the private data folder) that forwards the browser to the sign-in
    link. The browser is opened with this file instead of the link, so the session token never
    appears on a command line, where other accounts on the computer could read it (``ps``)."""
    path = folder / LOGIN_PAGE_NAME
    target = html.escape(info.login_url, quote=True)
    page = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta http-equiv='refresh' content='0;url={target}'><title>Opening Ordnung</title></head>"
        f"<body><p><a href='{target}'>Open Ordnung</a></p></body></html>\n"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as handle:
        handle.write(page)
    if os.name == "posix":
        path.chmod(0o600)
    return path


def launch_browser(folder: Path, info: ServerInfo) -> None:
    """Open Ordnung in the browser without putting the session token on a command line."""
    webbrowser.open(login_page(folder, info).as_uri() if info.token else info.login_url)


def _open_browser_when_ready(folder: Path, info: ServerInfo) -> None:
    def wait_and_open() -> None:
        deadline = time.monotonic() + BROWSER_WAIT_S
        while time.monotonic() < deadline:
            with contextlib.suppress(OSError), socket.create_connection((info.host, info.port), timeout=0.5):
                launch_browser(folder, info)
                return
            time.sleep(0.2)

    threading.Thread(target=wait_and_open, name="ordnung-open-browser", daemon=True).start()


@contextlib.contextmanager
def _graceful_sigterm() -> Iterator[None]:
    """Let SIGTERM raise ``SystemExit`` so cleanup runs (uvicorn re-raises the signal after shutdown)."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def stop(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _create_app(context: AppContext, *, token: str | None, demo: bool) -> Any:
    try:
        from ordnung.api.app import create_app
    except ModuleNotFoundError as exc:
        raise RuntimeError("The web app is not part of this installation of Ordnung.") from exc
    return create_app(context, token=token, demo=demo)


def _announce(info: ServerInfo, *, demo: bool, data_dir: Path) -> None:
    title = "Ordnung demo" if demo else "Ordnung"
    lines = [
        f"[bold]{escape(info.login_url)}[/]",
        f"[dim]Data: {escape(str(data_dir))}[/]",
        "[dim]Your files stay on this computer. Press Ctrl+C to stop.[/]",
    ]
    if demo:
        lines.insert(1, "[dim]Sample life of Sam Rivera · recorded answers · zero tokens[/]")
    console.print(Panel("\n".join(lines), title=title, expand=False))


def _serve(
    folder: Path,
    *,
    host: str,
    port: int,
    open_browser: bool,
    token_on: bool,
    backend: str | None,
    demo: bool,
    prepare: Callable[[], None] | None = None,
) -> None:
    """Hold the data folder, start the API + UI with uvicorn, and clean up ``server.json`` after."""
    import uvicorn

    from ordnung.app_context import build_context
    from ordnung.doctor import web_ui_check
    from ordnung.locking import DataDirLock

    if host not in LOOPBACK_HOSTS and not token_on:
        raise _fail(
            "--no-token is only allowed on this computer's own address.",
            hint="Leave out --host or --no-token.",
        )
    if host not in LOOPBACK_HOSTS:
        err_console.print(
            f"[yellow]![/] {escape(host)} is not this computer only — anyone on your network could connect."
        )
    already = reachable_server(folder)
    if already is not None:
        console.print(f"Ordnung is already running for this folder: [bold]{escape(already.login_url)}[/]")
        if open_browser:
            launch_browser(folder, already)
        return
    with DataDirLock(folder, purpose="ordnung serve"), _graceful_sigterm():
        if prepare is not None:
            prepare()
        if not _port_free(host, port):
            raise _fail(
                f"Port {port} is already in use.", hint=f"Choose another one, e.g. --port {port + 1}."
            )
        context = build_context(folder, backend=backend)
        token = generate_token() if token_on else None
        try:
            asgi = _create_app(context, token=token, demo=demo)
            web_ui = web_ui_check()
            if web_ui.status != "ok":
                # the API works (add, brief, ask), but the link would only show "web app is missing"
                err_console.print(
                    "[yellow]![/] The web app is not part of this installation: the link below only "
                    f"explains how to get it. {escape(web_ui.fix or '')}"
                )
                open_browser = False
            with advertise(folder, port=port, token=token, host=host) as info:
                _announce(info, demo=demo, data_dir=folder)
                if open_browser:
                    _open_browser_when_ready(folder, info)
                # the plain asyncio loop: uvloop runs Python in the child it forks to start `claude`,
                # where the store's thread cleanup could deadlock (see ordnung.db.store)
                config = uvicorn.Config(asgi, host=host, port=port, log_level="warning", loop="asyncio")
                uvicorn.Server(config).run()
        finally:
            context.close()
            (folder / LOGIN_PAGE_NAME).unlink(missing_ok=True)


@app.command()
def serve(
    ctx: typer.Context,
    data_dir: DataDirOption = None,
    host: Annotated[str, typer.Option(help="Address to listen on (keep 127.0.0.1).")] = DEFAULT_HOST,
    port: Annotated[int, typer.Option(help="Port to listen on.")] = DEFAULT_PORT,
    no_browser: Annotated[bool, typer.Option("--no-browser", help="Don't open the browser.")] = False,
    no_token: Annotated[bool, typer.Option("--no-token", help="No session token (tests only).")] = False,
    demo: Annotated[bool, typer.Option("--demo", help="Serve the demo (sample life).")] = False,
) -> None:
    """Run the web app on this computer and open it in your browser."""
    with _friendly():
        if demo:
            _demo_serve(
                ctx,
                data_dir,
                host=host,
                port=port,
                open_browser=not no_browser,
                token_on=not no_token,
                live=False,
                reset=False,
            )
            return
        from ordnung.demo.loader import is_demo_dir

        folder = resolve_paths(_chosen(ctx, data_dir)).data_dir
        demo_folder = is_demo_dir(folder)
        _serve(
            folder,
            host=host,
            port=port,
            open_browser=not no_browser,
            token_on=not no_token,
            backend="replay" if demo_folder else None,
            demo=demo_folder,
            prepare=None if demo_folder else lambda: _finish_take_over(folder),
        )


def _finish_take_over(folder: Path) -> None:
    """``serve``'s ``prepare`` (under the data folder's lock, before the database opens): finish a
    take-over of hand-off sync that was interrupted — without the passphrase. Never raises: the server
    then starts standing by and shows the problem."""
    engine = _sync_engine_if_connected(Paths(folder))
    if engine is None:
        return
    try:
        engine.resume_interrupted(Paths(folder))
    except Exception as exc:
        err_console.print(
            f"[yellow]![/] Bringing Ordnung over from your other computer didn't finish: {escape(str(exc))}"
        )


# --------------------------------------------------------------------------------------------------
# add
# --------------------------------------------------------------------------------------------------


async def _follow(ctx: AppContext, progress: Any, tasks: Mapping[str, Any], names: Mapping[str, str]) -> None:
    async for event in ctx.bus.subscribe():
        doc_id = str(event.data.get("doc_id"))
        if event.type != "job.progress" or doc_id not in tasks:
            continue
        stage = str(event.data.get("stage") or "")
        label = "[red]failed[/]" if event.data.get("status") == "failed" else STAGE_LABELS.get(stage, stage)
        progress.update(
            tasks[doc_id],
            completed=float(event.data.get("progress") or 0.0),
            description=f"{escape(names[doc_id])} · {label}",
        )


async def _read_with_progress(ctx: AppContext, documents: Sequence[Document]) -> None:
    """Let the worker read the queued letters, showing each one's stage live."""
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    names = {document.id: document.filename for document in documents}
    columns = (SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), TimeElapsedColumn())
    with Progress(*columns, console=console) as progress:
        tasks = {
            doc_id: progress.add_task(f"{escape(name)} · waiting", total=1.0)
            for doc_id, name in names.items()
        }
        follower = asyncio.create_task(_follow(ctx, progress, tasks, names))
        await asyncio.sleep(0)  # let the follower subscribe before the first event
        try:
            await ctx.worker.run_until_idle()
        finally:
            follower.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await follower
        for doc_id, task in tasks.items():
            final = ctx.store.get_document(doc_id)
            if _waits_for_claude(ctx.store.latest_job(doc_id)):
                state = "[yellow]waiting for Claude[/]"
            else:
                state = "done" if final is None or final.status != "failed" else "[red]failed[/]"
            progress.update(task, completed=1.0, description=f"{escape(names[doc_id])} · {state}")


def _waits_for_claude(job: Job | None) -> str | None:
    """Why a letter's reading waits for Claude (a usage limit, Claude not installed or signed out), if
    it does."""
    from ordnung.ingest.worker import WAITING_FOR_CLAUDE

    reason = job.waiting_reason if job is not None and job.status == "queued" else None
    return reason if reason and reason.startswith(WAITING_FOR_CLAUDE) else None


def _uploads(files: Sequence[Path], combine: bool) -> list[list[tuple[str, bytes]]]:
    entries = [(path.name, path.read_bytes()) for path in files]
    return [entries] if combine else [[entry] for entry in entries]


def _add_in_process(paths: Paths, files: Sequence[Path], *, combine: bool, private: bool) -> bool:
    groups = _uploads(files, combine)

    async def work(
        ctx: AppContext,
    ) -> tuple[list[tuple[Document, str | None, list[Item]]], dict[str, str], date]:
        from ordnung.ingest.pipeline import add_file
        from ordnung.tick import local_today

        added = []
        for group in groups:
            (name, data), *rest = group
            combine_with = [body for _, body in rest] or None
            added.append(
                await add_file(
                    ctx,
                    data,
                    name,
                    combine_with=combine_with,
                    private=private,
                    answer_held=True,
                    source="cli",
                )
            )
        await _read_with_progress(ctx, added)
        waiting = {
            document.id: reason
            for document in added
            if (reason := _waits_for_claude(ctx.store.latest_job(document.id)))
        }
        return [_row(ctx, document.id) for document in added], waiting, local_today(ctx.store)

    rows, waiting, today = _in_process(paths, "ordnung add", work)
    return _print_summary(rows, today, waiting)


def _row(ctx: AppContext, doc_id: str) -> tuple[Document, str | None, list[Item]]:
    document = ctx.store.get_document(doc_id)
    if document is None:
        raise RuntimeError(f"The letter {doc_id} disappeared while it was read.")
    party = ctx.store.get_party(document.party_id) if document.party_id else None
    return document, party.name if party else None, ctx.store.list_items(doc_id=doc_id)


def _print_summary(
    rows: Sequence[tuple[Document, str | None, Sequence[Item]]],
    today: date,
    waiting: Mapping[str, str] | None = None,
) -> bool:
    """The letters as a table (and why some wait for Claude); whether every one was read."""
    waiting = waiting or {}
    console.print(summary_table(rows, today, waiting))
    if any(document.status == "needs_review" for document, _, _ in rows):
        console.print(
            "[dim]“Please check”: Ordnung couldn't confirm something it read in the letter — open it to check.[/]"
        )
    for reason in dict.fromkeys(waiting.values()):
        console.print(f"[yellow]{escape(reason)}[/]")
    return not waiting and all(document.status != "failed" for document, _, _ in rows)


def _server_today(client: httpx.Client) -> date:
    """The server's "today" (the person's local or the demo's pinned date)."""
    from ordnung import clock

    try:
        return date.fromisoformat(str(_json_object(_checked(client.get("/api/health"))).get("today")))
    except ValueError:
        return clock.today()


def _add_remote(info: ServerInfo, files: Sequence[Path], *, combine: bool, private: bool) -> bool:
    from ordnung.models import Document, DocumentDetail, Job

    console.print(f"[dim]Sending to the running Ordnung at {escape(info.base_url)}[/]")
    uploads = [("files", (path.name, path.read_bytes())) for path in files]
    form = {"combine": str(combine).lower(), "private": str(private).lower()}
    with _api(info, timeout=120.0) as client:
        result = _json_object(_checked(client.post("/api/documents", files=uploads, data=form)))
        for error in result.get("errors") or []:
            err_console.print(
                f"[red]✗[/] {escape(str(error.get('filename')))}: {escape(str(error.get('detail')))}"
            )
        ids = [Document.model_validate(doc).id for doc in result.get("documents") or []]
        ids += [str(doc_id) for doc_id in result.get("duplicates") or []]
        details: dict[str, DocumentDetail] = {}
        waiting: dict[str, str] = {}
        with console.status("Reading your letters… (Ctrl+C stops waiting; the app keeps reading them)"):
            while True:
                unread: dict[str, DocumentDetail] = {}
                for doc_id in ids:
                    if doc_id in details:
                        continue
                    detail = DocumentDetail.model_validate(
                        _checked(client.get(f"/api/documents/{doc_id}")).json()
                    )
                    if detail.document.status in FINAL_STATUSES:
                        details[doc_id] = detail
                    else:
                        unread[doc_id] = detail
                if unread:  # a letter that waits for Claude is not waited for here: the app reads it later
                    jobs = _json_list(_checked(client.get("/api/jobs", params={"active_only": "true"})))
                    for job in (Job.model_validate(row) for row in jobs):
                        reason = _waits_for_claude(job)
                        if job.doc_id in unread and reason:
                            details[job.doc_id], waiting[job.doc_id] = unread[job.doc_id], reason
                if len(details) == len(ids):
                    break
                time.sleep(POLL_S)
        today = _server_today(client)
    return _print_summary([_detail_row(details[doc_id]) for doc_id in ids], today, waiting)


def _detail_row(detail: DocumentDetail) -> tuple[Document, str | None, list[Item]]:
    party = detail.party
    return detail.document, party.name if party is not None else None, detail.items


@app.command()
def add(
    ctx: typer.Context,
    files: Annotated[
        list[Path],
        typer.Argument(help="Letters to add (PDF, photos, .txt/.eml).", exists=True, dir_okay=False),
    ],
    combine: Annotated[bool, typer.Option("--combine", help="The photos are pages of one letter.")] = False,
    private: Annotated[bool, typer.Option("--private", help="Keep private — never sent to Claude.")] = False,
    data_dir: DataDirOption = None,
) -> None:
    """Add letters: Ordnung reads them and files every date, amount and contract."""
    from ordnung.demo.loader import is_demo_dir

    with _friendly():
        paths = resolve_paths(_chosen(ctx, data_dir))
        if is_demo_dir(paths.data_dir):
            raise _fail(
                "This is the demo folder — it only replays the sample life.",
                hint="Add your own letters to your own data folder (leave out --data-dir, or choose another).",
            )
        info = reachable_server(paths.data_dir)
        if info is not None:
            read = _add_remote(info, files, combine=combine, private=private)
        else:
            read = _add_in_process(paths, files, combine=combine, private=private)
    if not read:
        raise _fail("Not every letter was read (see above).", hint="Run `ordnung doctor` to check Claude.")


# --------------------------------------------------------------------------------------------------
# brief
# --------------------------------------------------------------------------------------------------


def _print_brief(brief: Mapping[str, Any]) -> None:
    source = (
        "written by Claude, checked against your records"
        if brief.get("source") == "llm"
        else "from your records"
    )
    console.print(
        Panel(
            escape(str(brief.get("text") or "")),
            title=f"Your note for {_day(str(brief.get('date') or ''))}",
            subtitle=f"[dim]{source}[/]",
            expand=False,
        )
    )


async def _brief_in_process(ctx: AppContext, use_llm: bool) -> dict[str, Any]:
    from ordnung.demo.loader import OfflineTickContext
    from ordnung.secretary.brief import generate_brief
    from ordnung.tick import DailyTick, local_today, replay_miss_prone

    await DailyTick(OfflineTickContext(ctx.store)).check()
    llm = ctx.llm if use_llm and ctx.settings.llm_brief and not replay_miss_prone(ctx.llm) else None
    return (await generate_brief(ctx.store, llm, local_today(ctx.store))).model_dump()


@app.command()
def brief(
    ctx: typer.Context,
    no_llm: Annotated[
        bool,
        typer.Option(
            "--no-llm",
            help="Write today's note from your records only, without Claude (it replaces today's note).",
        ),
    ] = False,
    data_dir: DataDirOption = None,
) -> None:
    """Today's note from your secretary: what's due, what's coming, new ideas."""
    with _friendly():
        paths = resolve_paths(_chosen(ctx, data_dir))
        info = reachable_server(paths.data_dir)
        if info is not None:
            with _api(info, timeout=180.0) as client:
                response = client.post("/api/brief", params={"llm": "false"} if no_llm else None)
                note = _json_object(_checked(response))
        else:
            note = _in_process(paths, "ordnung brief", lambda context: _brief_in_process(context, not no_llm))
        _print_brief(note)


# --------------------------------------------------------------------------------------------------
# ask
# --------------------------------------------------------------------------------------------------


WRITING_LINE = "Writing the answer — it appears once Ordnung has checked it against your records…"
CHECKED_LINE = "Dates and amounts checked against your records."
CHECKED_LINE_DE = "Daten und Beträge mit Ihren Unterlagen abgeglichen."
"""Under an answer the check did not change (in its language): it says what was checked — dates,
times, amounts and laws, not every claim."""


class _AnswerPrinter:
    """Prints an Ask stream: tool trace lines; one line while the answer is written (its words are not
    streamed: nobody sees them before Ordnung's check, ADR 0008); then the checked answer, the check's
    note under its label in the answer's language (or "Dates and amounts checked against your records."
    when the check changed nothing), and the sources. A stream that ends without a checked answer prints only why."""

    def __init__(self) -> None:
        self.writing = False
        self.failed = False

    def handle(self, event: Mapping[str, Any]) -> None:
        """Print one event (``type``: text, tool_use, tool_result, done or error)."""
        kind, text = event.get("type"), str(event.get("text") or "")
        if kind == "tool_use":
            console.print(f"  [dim]↳ {escape(text or str(event.get('name') or 'tool'))}[/]")
        elif kind == "tool_result":
            console.print(f"    [dim]{escape(text)}[/]")
        elif kind == "text":
            if not self.writing:
                console.print(f"[dim]{escape(WRITING_LINE)}[/]")
            self.writing = True
        elif kind == "done":
            self._done(
                text,
                str(event.get("note") or ""),
                event.get("citations") or [],
                label=str(event.get("note_label") or ""),
                checked=bool(event.get("message_id")),
            )
        elif kind == "error":
            self.failed = True
            err_console.print(f"[red]✗[/] {escape(str(event.get('error') or text or 'The answer stopped.'))}")

    def _done(
        self,
        text: str,
        note: str,
        citations: Sequence[Mapping[str, Any]],
        *,
        label: str = "",
        checked: bool = True,
    ) -> None:
        from ordnung.assistant.support import NOTE_PREFIX_DE, labelled_note

        console.print(escape(text.strip()))
        if note:
            german = (label == NOTE_PREFIX_DE) if label else None
            console.print(f"[dim]{escape(labelled_note(note, german=german))}[/]")
        elif checked and text.strip():  # the demo's "no recording" answer went through no check
            console.print(f"[dim]{escape(CHECKED_LINE_DE if label == NOTE_PREFIX_DE else CHECKED_LINE)}[/]")
        if citations:
            console.print("[bold]Sources[/]")
            for citation in citations:
                ref = f"{citation.get('type')}:{citation.get('id')}"
                console.print(f"  [dim]{escape(ref)}[/] {escape(str(citation.get('label') or ''))}")


def _sse_events(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """JSON ``data:`` payloads of a Server-Sent Events stream (multi-line data joined)."""
    data: list[str] = []
    for line in lines:
        if line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line.strip() and data:
            with contextlib.suppress(ValueError):
                yield json.loads("\n".join(data))
            data = []
    if data:
        with contextlib.suppress(ValueError):
            yield json.loads("\n".join(data))


def _ask_remote(info: ServerInfo, question: str, printer: _AnswerPrinter) -> None:
    with (
        _api(info, timeout=None) as client,
        client.stream("POST", "/api/ask", json={"question": question}) as response,
    ):
        if response.status_code >= 400:
            response.read()
            _checked(response)
        for event in _sse_events(response.iter_lines()):
            printer.handle(event)


async def _ask_in_process(ctx: AppContext, question: str, printer: _AnswerPrinter) -> None:
    from ordnung.assistant.ask import ask_stream
    from ordnung.demo.tour import demo_safe_stream

    events: AsyncIterator[Any] = demo_safe_stream(
        ask_stream(ctx, question), demo=ctx.settings.demo, question=question, ctx=ctx
    )
    async for event in events:
        printer.handle(event.model_dump(exclude={"response"}, mode="json"))


@app.command()
def ask(
    ctx: typer.Context,
    question: Annotated[str, typer.Argument(help="Your question, e.g. “When does my phone contract end?”")],
    data_dir: DataDirOption = None,
) -> None:
    """Ask about your letters; the answer cites the records it comes from."""
    with _friendly():
        paths = resolve_paths(_chosen(ctx, data_dir))
        printer = _AnswerPrinter()
        info = reachable_server(paths.data_dir)
        if info is not None:
            _ask_remote(info, question, printer)
        else:
            _in_process(paths, "ordnung ask", lambda context: _ask_in_process(context, question, printer))
        if printer.failed:
            raise typer.Exit(1)


# --------------------------------------------------------------------------------------------------
# trace
# --------------------------------------------------------------------------------------------------


def _trace_getter(paths: Paths, doc_id: str, stack: contextlib.ExitStack) -> Callable[[str | None], Any]:
    """Fetch a reading of ``doc_id`` (``None``: the newest) from the running server, else from the
    database under the data folder's lock (held until ``stack`` closes)."""
    from urllib.parse import quote

    from ordnung.models import DocumentTrace

    info = reachable_server(paths.data_dir)
    if info is not None:
        client = stack.enter_context(_api(info))
        route = f"/api/documents/{quote(doc_id, safe='')}/trace"
        return lambda run: DocumentTrace.model_validate(
            _json_object(_checked(client.get(route, params={"run": run} if run else None)))
        )
    from ordnung.db.store import Store
    from ordnung.locking import DataDirLock
    from ordnung.trace.view import document_trace

    if not paths.db.is_file():
        raise _fail(f"There is no Ordnung data in {paths.data_dir}.", "Pass the folder with --data-dir.")
    stack.enter_context(DataDirLock(paths.data_dir, purpose="ordnung trace"))
    _refuse_while_standing_by(_sync_engine_if_connected(paths), paths)  # opening it writable migrates
    store = stack.enter_context(Store.open(paths))
    if store.get_document(doc_id) is None:
        raise _fail(
            f"There is no letter {doc_id}.", "A letter's id is in its page's address: /documents/doc_…"
        )
    return lambda run: document_trace(store, doc_id, run)


@app.command()
def trace(
    ctx: typer.Context,
    document_id: Annotated[str, typer.Argument(help="The letter's id (doc_…, in its page's address).")],
    otel: Annotated[
        bool,
        typer.Option(
            "--otel",
            help="OpenTelemetry JSON (OTLP) with the GenAI conventions, for any OpenTelemetry viewer.",
        ),
    ] = False,
    reading: Annotated[
        int | None,
        typer.Option("--reading", min=1, help="Which reading: 1 is the first (default: the newest kept)."),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write to this file instead of the screen.")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Replace the --output file if it exists.")] = False,
    data_dir: DataDirOption = None,
) -> None:
    """How a letter was read: every step, its model calls and what code checked — as JSON.

    The plain JSON is what the letter's "How it was read" tab shows, with the names of the to-dos and organisations it points to.

    With --otel it holds no letter text and no names, and its ids are replaced for this file (docs/privacy.md says what it still shows).

    A letter with no kept reading is an error.
    """
    from ordnung.trace.otel import to_otlp

    with _friendly(), contextlib.ExitStack() as stack:
        get = _trace_getter(resolve_paths(_chosen(ctx, data_dir)), document_id, stack)
        found = get(None)
        if found.run is None:
            raise _fail(
                "This letter has no kept reading yet.",
                "“Read again” on its page records one (it asks Claude again).",
            )
        if reading is not None and found.run.reading != reading:
            kept = [run for run in found.runs if run.reading == reading]
            if not kept:
                numbers = ", ".join(str(run.reading) for run in found.runs) or "none"
                raise _fail(f"Reading {reading} of this letter isn't kept (kept: {numbers}).")
            found = get(kept[0].trace_id)
        payload = to_otlp(found) if otel else found.model_dump(mode="json")
        # ASCII only: names in the plain JSON were written by a model from a letter and must not
        # reach the terminal as control or bidirectional characters
        text = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
    if output is None:
        typer.echo(text, nl=False)
        return
    # the plain JSON names to-dos and organisations: private to this account (0600), never through a
    # link, and never over an existing file unless asked (as the sign-in page is written)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL) | getattr(os, "O_NOFOLLOW", 0)
    with _friendly():
        try:
            fd = os.open(output, flags, 0o600)
        except FileExistsError:
            raise _fail(f"{output} already exists.", "Add --force to replace it.") from None
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if os.name == "posix":
            output.chmod(0o600)
    err_console.print(f"Wrote {escape(str(output))}", soft_wrap=True)


# --------------------------------------------------------------------------------------------------
# demo
# --------------------------------------------------------------------------------------------------


def _demo_folder(ctx: typer.Context, data_dir: Path | None) -> Path:
    from ordnung.demo.loader import default_demo_dir

    return _chosen(ctx, data_dir) or default_demo_dir()


def _demo_prepare(folder: Path, *, reset: bool, rebuild: bool, record: bool) -> Callable[[], None]:
    def prepare() -> None:
        from ordnung.demo.loader import build_demo, prepare_demo

        if rebuild:
            doing = (
                "Recording the demo with your Claude" if record else "Rebuilding the demo from the recordings"
            )
            with console.status(f"{doing}…"):
                built = build_demo(folder, backend="record" if record else "replay", rebuild=True)
            stale = f", {built.pruned} stale recordings removed" if built.pruned else ""
            console.print(
                f"[green]✓[/] Demo rebuilt ({built.documents} letters{stale}); snapshot {escape(str(built.snapshot))}"
            )
            return
        with console.status("Preparing the demo…"):
            prepared = prepare_demo(folder, reset=reset)
        if prepared.source == "fixtures":
            console.print(
                "[dim]Built the demo from the recorded answers (the prebuilt copy was out of date).[/]"
            )

    return prepare


def _refuse_while_running(folder: Path, option: str) -> None:
    """``--reset`` and ``--rebuild`` replace the demo's database: not while the demo runs on it (its
    server holds the folder, and ``demo`` would only point to it with nothing reset)."""
    running = reachable_server(folder)
    if running is not None:
        raise _fail(
            f"The demo is running at {running.base_url}.",
            hint=f"Stop the demo (Ctrl+C where it runs), then run `ordnung demo {option}`.",
        )


def _demo_serve(
    ctx: typer.Context,
    data_dir: Path | None,
    *,
    host: str,
    port: int,
    open_browser: bool,
    live: bool,
    reset: bool,
    token_on: bool = True,
    rebuild: bool = False,
    record: bool = False,
) -> None:
    folder = _demo_folder(ctx, data_dir)
    _serve(
        folder,
        host=host,
        port=port,
        open_browser=open_browser,
        token_on=token_on,
        backend="replay+claude" if live else "replay",
        demo=True,
        prepare=_demo_prepare(folder, reset=reset, rebuild=rebuild, record=record),
    )


def _print_check(report: Any) -> None:
    table = Table(title="Demo check", title_justify="left", show_header=False)
    table.add_column("What")
    table.add_column("Result")
    table.add_row("Letters read", str(report.documents))
    table.add_row("Recorded answers", str(report.fixtures))
    table.add_row("Suggested questions replayed", str(report.asks))
    table.add_row("Ideas", str(report.ideas))
    console.print(table)
    for warning in report.warnings:
        console.print(f"[yellow]![/] {escape(warning)}")
    for problem in report.problems[:MAX_LISTED_PROBLEMS]:
        console.print(f"[red]✗[/] {escape(problem)}")
    if len(report.problems) > MAX_LISTED_PROBLEMS:
        console.print(f"[red]✗[/] … and {len(report.problems) - MAX_LISTED_PROBLEMS} more")
    console.print(
        "[green]✓ The demo is complete and reproducible.[/]"
        if report.ok
        else "[red]✗ The demo check failed.[/]"
    )


@app.command()
def demo(
    ctx: typer.Context,
    data_dir: DemoDirOption = None,
    serve: Annotated[bool, typer.Option("--serve/--no-serve", help="Open the web app (default).")] = True,
    reset: Annotated[bool, typer.Option("--reset", help="Start the demo over.")] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Verify the demo rebuilds identically (CI).")
    ] = False,
    live: Annotated[
        bool, typer.Option("--live", help="Let Claude answer what the demo has no recording for.")
    ] = False,
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Rebuild the prebuilt demo database (maintainers).")
    ] = False,
    no_browser: Annotated[bool, typer.Option("--no-browser", help="Don't open the browser.")] = False,
    host: Annotated[str, typer.Option(help="Address to listen on.")] = DEFAULT_HOST,
    port: Annotated[int, typer.Option(help="Port to listen on.")] = DEFAULT_PORT,
) -> None:
    """Explore the sample life of Sam Rivera — recorded answers, zero tokens."""
    with _friendly():
        if check:
            from ordnung.demo.loader import check_demo

            with console.status("Rebuilding the demo twice from the recordings…"):
                report = check_demo()
            _print_check(report)
            if not report.ok:
                raise typer.Exit(1)
            return
        record = live and rebuild and os.environ.get("ORDNUNG_RECORD") == "1"
        if live and rebuild and not record:
            raise _fail(
                "Recording new demo answers needs ORDNUNG_RECORD=1.",
                hint="ORDNUNG_RECORD=1 ordnung demo --live --rebuild (sends only the sample letters to Claude).",
            )
        if reset or rebuild:
            _refuse_while_running(_demo_folder(ctx, data_dir), "--rebuild" if rebuild else "--reset")
        if serve:
            _demo_serve(
                ctx,
                data_dir,
                host=host,
                port=port,
                open_browser=not no_browser,
                live=live,
                reset=reset,
                rebuild=rebuild,
                record=record,
            )
            return
        from ordnung.locking import DataDirLock

        folder = _demo_folder(ctx, data_dir)
        with DataDirLock(folder, purpose="ordnung demo"):
            _demo_prepare(folder, reset=reset, rebuild=rebuild, record=record)()
        console.print(f"[green]✓[/] The demo is ready in {escape(str(folder))}")


# --------------------------------------------------------------------------------------------------
# doctor, eval, mcp, openapi
# --------------------------------------------------------------------------------------------------


@app.command()
def doctor(
    ctx: typer.Context,
    probe: Annotated[bool, typer.Option("--probe", help="Also make one tiny live call to Claude.")] = False,
    data_dir: DataDirOption = None,
) -> None:
    """Check Claude, search, fonts, the web app and your data folder (zero tokens)."""
    from ordnung.doctor import run_doctor_sync

    folder = _folder(ctx, data_dir)
    with _friendly():
        report = run_doctor_sync(folder, probe=probe, model=_chosen_model(folder) if probe else None)
    table = Table(title="Ordnung doctor", title_justify="left", show_header=False)
    table.add_column("", no_wrap=True)
    table.add_column("Check", no_wrap=True)
    table.add_column("Result", overflow="fold")
    for check in report.checks:
        table.add_row(STATUS_ICONS[check.status], escape(check.label), escape(check.detail))
    console.print(table)
    for check in report.checks:
        if check.fix and check.status in ("warn", "fail"):
            console.print(f"{STATUS_ICONS[check.status]} {escape(check.label)}: {escape(check.fix)}")
    if not report.ok:
        raise typer.Exit(1)


def _chosen_model(folder: Path) -> str:
    """The model every call runs on (Settings → Claude connection), so the probe tries that one and not
    an alias; the default before any data exists (the doctor must not create the folder), or while the
    database can't be read (the doctor's Database check says why)."""
    import sqlite3

    from ordnung.db.store import Store
    from ordnung.llm.base import DEFAULT_MODEL

    paths = Paths(folder)
    if not paths.db.is_file():
        return DEFAULT_MODEL
    try:
        with Store.open(paths, read_only=True) as store:
            return store.get_settings().model
    except (sqlite3.DatabaseError, RuntimeError):
        return DEFAULT_MODEL


def _evals_module() -> Any:
    try:
        return importlib.import_module("evals.run")
    except ModuleNotFoundError:
        if not (REPO_DIR / "evals").is_dir() or str(REPO_DIR) in sys.path:
            return None
    sys.path.insert(0, str(REPO_DIR))
    try:
        return importlib.import_module("evals.run")
    except ModuleNotFoundError:
        return None


@app.command(
    name="eval",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    add_help_option=False,
)
def eval_(ctx: typer.Context) -> None:
    """Run the benchmark (source checkout only); ordnung eval --help lists its options."""
    runner = getattr(_evals_module(), "run_cli", None)
    if not callable(runner):
        raise _fail(
            "The benchmark runner (evals/run.py) is not available here.",
            hint="It lives in a source checkout of Ordnung: clone the repository and run `ordnung eval` there.",
        )
    with _friendly():
        code = runner(list(ctx.args))
    raise typer.Exit(int(code or 0))


mcp_app = typer.Typer(
    name="mcp",
    help="Ordnung's read-only MCP tools: serve them over stdio, or install them into Claude "
    "(the options below are for serving; `install` takes its own).",
    add_completion=False,
    rich_markup_mode="rich",
)
app.add_typer(mcp_app)

RulesOnlyOption = Annotated[
    bool,
    typer.Option(
        "--rules-only",
        help="Serve only the deadline, holiday, working-day and IBAN tools: no data folder, nothing personal.",
    ),
]


@mcp_app.callback(invoke_without_command=True)
def mcp(
    ctx: typer.Context,
    data_dir: DataDirOption = None,
    print_config: Annotated[
        bool, typer.Option("--print-config", help="Print the MCP config JSON and exit.")
    ] = False,
    rules_only: RulesOnlyOption = False,
    ledger_only: Annotated[
        bool,
        typer.Option(
            "--ledger-only",
            hidden=True,
            help="Only the ledger tools, without the rules tools (Ask's server: Ask never computes dates).",
        ),
    ] = False,
) -> None:
    """Serve Ordnung's read-only tools over stdio (Ask starts this; nothing else is printed)."""
    if ctx.invoked_subcommand is not None:
        given = [
            name
            for name, value in (
                ("--data-dir", data_dir),
                ("--print-config", print_config),
                ("--rules-only", rules_only),
                ("--ledger-only", ledger_only),
            )
            if value
        ]
        if given:
            raise _fail(
                f"{', '.join(given)} before “{ctx.invoked_subcommand}” would not be used.",
                hint=f"Put the options after it, e.g. ordnung mcp {ctx.invoked_subcommand} --client "
                "claude-desktop (the rules tools alone), or add --with-ledger --data-dir … for your ledger.",
            )
        return
    if rules_only and ledger_only:
        raise _fail("--rules-only and --ledger-only exclude each other.")
    if rules_only:
        from ordnung.assistant import rules_tools

        if _chosen(ctx, data_dir) is not None:
            raise _fail(
                "The rules tools read no data folder, so --data-dir would not be used.",
                hint="Leave out --data-dir, or leave out --rules-only to serve your ledger too.",
            )

        if print_config:
            typer.echo(json.dumps(rules_tools.rules_server_config(), indent=2))
            return
        rules_tools.run_rules_only()
        return
    from ordnung.assistant import mcp_server

    folder = _folder(ctx, data_dir)
    if print_config:
        typer.echo(json.dumps(mcp_server.server_config(folder, rules_tools=not ledger_only), indent=2))
        return
    try:
        mcp_server.run(folder, rules_tools=not ledger_only)
    except FileNotFoundError as exc:
        raise _fail(
            str(exc), hint="Pass the data folder with --data-dir, or use --rules-only.", soft_wrap=True
        ) from None


@mcp_app.command("install")
def mcp_install(
    ctx: typer.Context,
    client: Annotated[
        McpClient,
        typer.Option("--client", metavar="CLIENT", help="claude-desktop or claude-code.", show_default=False),
    ],
    rules_only: Annotated[
        bool,
        typer.Option(
            "--rules-only/--with-ledger",
            help="The rules tools alone (the default: no data folder, nothing personal), or also your "
            "read-only ledger (--with-ledger), which the client and its other tools can then read.",
        ),
    ] = True,
    write: Annotated[
        bool,
        typer.Option("--write", help="Merge the entry into the config file (the file is backed up first)."),
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config", help="Use this config file instead of the client's usual one.", show_default=False
        ),
    ] = None,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="With --with-ledger: your data folder (default: ORDNUNG_HOME or your user data folder).",
            show_default=False,
        ),
    ] = None,
    remove_ledger: Annotated[
        bool,
        typer.Option(
            "--remove-ledger",
            help="With the rules tools: also take Ordnung with your data (“ordnung”) out of the config.",
        ),
    ] = False,
) -> None:
    """Add Ordnung's rules tools (or, with --with-ledger, your ledger too) to Claude Desktop or Claude Code.

    Prints the entry and where it goes; --write merges it in.
    """
    from ordnung.assistant import mcp_install as install

    folder = None
    if rules_only:
        if _chosen(ctx, data_dir) is not None:  # given after `install` or before `mcp`
            raise _fail(
                "The rules tools read no data folder, so --data-dir would not be used.",
                hint="Add --with-ledger to give the client your ledger, or leave out --data-dir.",
            )
    else:
        if remove_ledger:
            raise _fail(
                "--remove-ledger takes your ledger out, --with-ledger puts it in: they exclude each other.",
                hint="Leave out --with-ledger to install the rules tools alone and remove the ledger.",
            )
        folder = _folder(ctx, data_dir)
        if not Paths(folder).db.is_file():
            raise _fail(
                f"There is no Ordnung database in {folder}.",
                hint="Name your data folder with --data-dir, or leave out --with-ledger for the rules tools alone.",
                soft_wrap=True,
            )
    plan = install.plan_install(client, rules_only=rules_only, data_dir=folder, config=config)
    # What the client will see, before anything is printed to copy or written.
    other = install.other_entry_in(plan)
    note = install.privacy_note(plan, other=other, remove_ledger=remove_ledger)
    if rules_only and (other is None or remove_ledger):
        console.print(f"[dim]{escape(note)}[/]", soft_wrap=True)
    else:
        console.print(f"[yellow]![/] {escape(note)}", soft_wrap=True)
    if not write:
        typer.echo(
            install.instructions(
                plan, data_dir=folder, config=config, remove_ledger=remove_ledger and bool(other)
            )
        )
        return
    try:
        result = install.write_config(plan, remove_ledger=remove_ledger)
    except install.InstallError as exc:
        raise _fail(str(exc), soft_wrap=True) from None
    except OSError as exc:
        raise _fail(f"Couldn't write {plan.path}: {exc.strerror or exc}", soft_wrap=True) from None
    console.print(f"[green]✓[/] {escape(install.written_message(plan, result))}", soft_wrap=True)
    if result.backup is not None:
        console.print(f"  The previous version is saved as {escape(str(result.backup))}", soft_wrap=True)
    if remove_ledger and result.removed is None:
        where = f"There was no “{install.FULL_SERVER_NAME}” entry in {result.path} to take out."
        if plan.client == "claude-code":
            full = install.Plan(
                client=plan.client, name=install.FULL_SERVER_NAME, entry={}, path=plan.path, rules_only=False
            )
            where += f" One added with claude mcp add goes with: {install.claude_code_remove_command(full)}"
        console.print(f"  {escape(where)}", soft_wrap=True)
    if result.status != "unchanged" or result.removed is not None:
        console.print(f"  {install.NEXT_STEP[plan.client]}")


# --------------------------------------------------------------------------------------------------
# autostart
# --------------------------------------------------------------------------------------------------

autostart_app = typer.Typer(
    name="autostart",
    help="Start Ordnung when you log in, so reminders reach you while the browser is closed.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
app.add_typer(autostart_app)


@autostart_app.command("enable")
def autostart_enable(
    ctx: typer.Context,
    data_dir: DataDirOption = None,
    port: Annotated[int, typer.Option(help="Port Ordnung listens on.")] = DEFAULT_PORT,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only print what would be written, and where.")
    ] = False,
) -> None:
    """Start Ordnung (without opening the browser) every time you log in."""
    from ordnung import autostart
    from ordnung.demo.loader import is_demo_dir

    with _friendly():
        folder = _folder(ctx, data_dir)
        if is_demo_dir(folder):
            raise _fail(
                "The demo doesn't start at login.", hint="Start it with `ordnung demo` when you want it."
            )
        try:
            entry = autostart.plan(folder, port=port)
        except autostart.AutostartError as exc:
            raise _fail(str(exc), soft_wrap=True) from None
        console.print(
            f"Ordnung for [bold]{escape(str(folder))}[/] starts at login as a {entry.kind}, from this file:",
            soft_wrap=True,
        )
        console.print(f"  [bold]{escape(str(entry.path))}[/]", soft_wrap=True)
        console.print(escape(entry.content.replace("\r\n", "\n")).rstrip("\n"), style="dim", soft_wrap=True)
        if entry.link is not None:
            console.print(
                f"  and the link {escape(str(entry.link))} (what `systemctl --user enable` makes)",
                soft_wrap=True,
            )
        if dry_run:
            console.print("Nothing was written (--dry-run).")
            return
        status = autostart.enable(entry)
    done = {
        "added": "Written.",
        "updated": "Updated the earlier entry.",
        "unchanged": "Already set up like this.",
    }
    console.print(f"[green]✓[/] {done[status]} Ordnung starts at your next login.")
    console.print(f"  Start it now: {escape(entry.start_now)}", soft_wrap=True)
    console.print("  Open the app any time with: ordnung serve (it finds the running Ordnung)")
    console.print("  Undo with: ordnung autostart disable")
    if _desktop_notifications(folder) == "off":
        console.print(
            "[yellow]![/] The morning desktop notification is off: switch it on in Settings → Reminders "
            "(ordnung serve opens it), or Ordnung runs at login without telling you anything.",
            soft_wrap=True,
        )


def _desktop_notifications(folder: Path) -> str:
    """The folder's saved ``desktop_notifications`` setting, read without creating or changing
    anything (``"off"``, the default, when there is no database yet or it can't be read)."""
    import sqlite3

    from ordnung.models import AppSettings

    db = folder / Paths(folder).db.name
    if not db.is_file():
        return "off"
    try:
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'settings'").fetchone()
        finally:
            conn.close()
        return AppSettings.model_validate_json(row[0]).desktop_notifications if row else "off"
    except (sqlite3.Error, ValueError):
        return "off"


@autostart_app.command("disable")
def autostart_disable() -> None:
    """Stop starting Ordnung at login (removes only the entry `enable` wrote)."""
    from ordnung import autostart

    with _friendly():
        entry = autostart.location()
        removed = autostart.disable(entry)
    if not removed:
        console.print(
            f"Ordnung doesn't start at login: there is no {escape(str(entry.path))}.", soft_wrap=True
        )
        return
    for path in removed:
        console.print(f"[green]✓[/] Removed {escape(str(path))}", soft_wrap=True)
    console.print("  Ordnung won't start at your next login.")
    console.print(f"  If it is running now, stop it with: {escape(entry.stop_now)}", soft_wrap=True)


@autostart_app.command("status")
def autostart_status(ctx: typer.Context, data_dir: DataDirOption = None) -> None:
    """Whether Ordnung starts at login, for which data folder, and whether it is running now."""
    from ordnung import autostart

    with _friendly():
        folder = _folder(ctx, data_dir)
        state = autostart.state(folder)
        running = reachable_server(folder) is not None
    if not state.enabled:
        console.print("Starts at login: [bold]no[/] — turn it on with: ordnung autostart enable")
    else:
        console.print(f"Starts at login: [bold]yes[/] ({state.kind})")
        console.print(f"  {escape(str(state.path))}", soft_wrap=True)
        if state.data_dir is not None:
            console.print(f"  Data folder: {escape(str(state.data_dir))}", soft_wrap=True)
        if not state.current:
            console.print(
                "[yellow]![/] The entry doesn't start this Ordnung for this folder (Ordnung or the folder "
                "moved). Run `ordnung autostart enable` again to update it.",
                soft_wrap=True,
            )
    console.print(f"Running now: [bold]{'yes' if running else 'no'}[/]")


# --------------------------------------------------------------------------------------------------
# hand-off sync
# --------------------------------------------------------------------------------------------------

sync_app = typer.Typer(
    name="sync",
    help="Hand-off sync: use Ordnung on your computers one at a time, through a folder you already sync.",
    invoke_without_command=True,
    add_completion=False,
    rich_markup_mode="rich",
)
app.add_typer(sync_app)

SYNC_PASSPHRASE_WORDING = (
    "Ordnung keeps this passphrase in this computer's password store, and you type it once on each of "
    "your computers. Save it in your password manager too: without it nobody can open the copy in the "
    "sync folder — not your sync provider, not Ordnung's makers, not you."
)
SYNC_WAIT_POLL_S = 2.0


def _sync_folder(ctx: typer.Context, data_dir: Path | None) -> Path:
    """The data folder of a ``sync`` command (the demo never syncs)."""
    from ordnung.demo.loader import is_demo_dir
    from ordnung.sync import DEMO_MESSAGE

    folder = _folder(ctx, data_dir)
    if is_demo_dir(folder):
        raise _fail(DEMO_MESSAGE)
    return folder


def _sync_api(info: ServerInfo, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ask the running server; a refusal becomes the same :class:`~ordnung.sync.SyncError`."""
    from typing import cast

    from ordnung.sync import ERROR_STATUS, SyncError, SyncErrorKind

    with _api(info, timeout=None) as client:
        response = client.request(method, path, json=body)
    found = _json_object(response)
    if response.status_code >= 400:
        code = str(found.get("code") or "")
        detail = str(found.get("detail") or f"The running Ordnung answered {response.status_code}.")
        raise SyncError(cast(SyncErrorKind, code if code in ERROR_STATUS else "folder_problem"), detail)
    return found


def _sync_in_process(folder: Path, work: Callable[[Any], Awaitable[T]], *, look: bool = False) -> T:
    """Run one sync operation here, under the data folder's lock: an interrupted take-over is finished
    first; ``look`` opens the folder (keyring and scrypt) to see what is there."""
    from ordnung.locking import DataDirLock
    from ordnung.sync.agent import NO_ENGINE_MESSAGE, SyncAgent, default_secrets, load_engine

    engine = load_engine()
    if engine is None:
        raise _fail(NO_ENGINE_MESSAGE)
    paths = Paths(folder)
    with DataDirLock(folder, purpose="ordnung sync"):
        if paths.sync.is_dir():
            engine.resume_interrupted(paths)  # never raises (a problem shows in the status)
        context = open_context(folder)
        try:
            agent = SyncAgent(context, engine=engine, secrets=default_secrets())

            async def run() -> T:
                context.bus.bind_loop(asyncio.get_running_loop())
                await agent.load(look=look)
                return await work(agent)

            return asyncio.run(run())
        finally:
            context.close()


def _sync_status(folder: Path, *, look: bool = False) -> Any:
    """The status, from the running server or read here (no keyring unless ``look``)."""
    from ordnung.sync.status import SyncStatus

    info = reachable_server(folder)
    if info is not None:
        return SyncStatus.model_validate(_sync_api(info, "GET", "/api/sync"))

    async def read(agent: Any) -> Any:
        return agent.status()

    return _sync_in_process(folder, read, look=look)


def _ago(moment: str | None) -> str:
    """``2 minutes ago`` for a time of this computer's clock."""
    from datetime import datetime

    if not moment:
        return "never"
    try:
        then = datetime.fromisoformat(moment)
    except ValueError:
        return moment
    seconds = max(0, int((datetime.now(then.tzinfo) - then).total_seconds()))
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return "just now"


def _print_sync_status(status: Any) -> None:
    if not status.connected:
        if not status.available:
            console.print(
                f"Hand-off sync isn't available here: {escape(status.unavailable or '')}", soft_wrap=True
            )
            if status.install_command:
                console.print(f"  Make it available with: {escape(status.install_command)}", soft_wrap=True)
            return
        console.print("This computer doesn't sync. Set it up with: ordnung sync connect FOLDER")
        return
    name = escape(status.this_computer or "this computer")
    others = [computer for computer in status.computers if not computer.this and computer.state != "left"]
    if status.mode == "in_use":
        line = f"In use here ({name}). Saved to {escape(status.folder or '')} {_ago(status.last_saved_at)}."
        received = [computer.name for computer in others if computer.has_latest]
        if received:
            line += f" {escape(', '.join(received))} {'has' if len(received) == 1 else 'have'} it."
        elif others:
            line += " Your other computers haven't received it yet."
        console.print(line, soft_wrap=True)
    elif status.mode == "standing_by":
        line = f"Standing by: in use on {escape(status.in_use_on or 'another computer')}."
        if status.arriving is not None:
            arriving = status.arriving
            line += f" Still arriving: {arriving.have} of {arriving.need} files are here."
        elif status.up_to_date:
            line += " Everything has arrived."
        console.print(line, soft_wrap=True)
        if status.take_over_waiting:
            console.print("  “Use Ordnung here” waits until everything has arrived.")
    else:
        console.print(f"Connected as {name}; looking at the sync folder ({escape(status.folder or '')}).")
    if status.problem is not None:
        console.print(
            f"[yellow]![/] {escape(status.problem.title)}: {escape(status.problem.message)}", soft_wrap=True
        )
    if status.choice is not None:
        _print_sync_choice(status.choice)
    for computer in others:
        state = computer.state.replace("_", " ")
        arrived = f", last change arrived {_ago(computer.arrived_at)}" if computer.arrived_at else ""
        console.print(f"  {computer.key}. {escape(computer.name)} — {state}{arrived}", soft_wrap=True)
    for notice in status.notices:
        console.print(f"[dim]{escape(notice.message)}[/]", soft_wrap=True)
    if status.kept:
        console.print(
            f"{len(status.kept)} kept cop{'y' if len(status.kept) == 1 else 'ies'}: ordnung sync kept"
        )


def _print_sync_choice(choice: Any) -> None:
    console.print("[bold]Which Ordnung do you want to keep?[/] Nothing is lost: the other is kept as a copy.")
    for side in choice.sides:
        who = f"This computer ({escape(side.computer)})" if side.this else escape(side.computer)
        newest = ", ".join(escape(letter.label) for letter in side.newest)
        added = f", {side.added} added since you last switched" + (f": {newest}" if newest else "")
        waiting = "" if side.complete else " (still arriving)"
        console.print(f"  {who}: {side.letters} letters{added}{waiting}", soft_wrap=True)
        console.print(f"    {escape(_side_contents(side))}", soft_wrap=True)
        console.print(f"    ordnung sync choose {'this' if side.this else side.key}", soft_wrap=True)


def _side_contents(side: Any) -> str:
    """ "2 open dates and to-dos, 1 done, 1 note — latest: to-do “Renew the passport” (2026-10-07)"."""
    counts = (
        f"{side.items} open date{'' if side.items == 1 else 's'} and to-dos, {side.done} done, "
        f"{side.notes} note{'' if side.notes == 1 else 's'}"
    )
    latest = "; ".join(f"{change.kind} “{change.label}” ({change.on})" for change in side.latest)
    return f"{counts} — latest: {latest}" if latest else counts


def _sync_passphrase(*, new: bool) -> str:
    """The sync passphrase: ``ORDNUNG_SYNC_PASSPHRASE`` or a hidden prompt (twice for a new folder,
    which must pass :func:`ordnung.sync.passphrase_problem` — a strong one is suggested first, as the
    web app's setup does)."""
    from ordnung.sync import PASSPHRASE_ENV, passphrase_problem, suggested_passphrase

    def problem(value: str) -> str | None:
        if not value:
            return "The passphrase is empty."
        return passphrase_problem(value) if new else None

    given = os.environ.get(PASSPHRASE_ENV)
    if given is not None:
        wrong = problem(given)
        if wrong:
            raise _fail(f"{PASSPHRASE_ENV}: {wrong}")
        return given
    if new:
        err_console.print(
            "A strong passphrase, made up just now — type it below (or one of your own: five or more words "
            "that don't belong together), and save it in your password manager:"
        )
        err_console.print(f"  [bold]{suggested_passphrase()}[/]", soft_wrap=True)
    for _ in range(PASSPHRASE_TRIES):
        value = str(typer.prompt("Passphrase of the sync folder", hide_input=True))
        wrong = problem(value)
        if wrong:
            err_console.print(f"[red]✗[/] {escape(wrong)}")
            continue
        if new and str(typer.prompt("Repeat it", hide_input=True)) != value:
            err_console.print("[red]✗[/] The two passphrases differ. Try again.")
            continue
        return value
    raise _fail("No passphrase was given.")


@sync_app.callback()
def sync_main(ctx: typer.Context, data_dir: DataDirOption = None) -> None:
    """Without a command: the status (as ``ordnung sync status``)."""
    if ctx.invoked_subcommand is None:
        with _friendly():
            _print_sync_status(_sync_status(_sync_folder(ctx, data_dir)))


@sync_app.command("status")
def sync_status(ctx: typer.Context, data_dir: DataDirOption = None) -> None:
    """Whether this computer is in use or standing by, when it last saved, and the other computers."""
    with _friendly():
        _print_sync_status(_sync_status(_sync_folder(ctx, data_dir)))


@sync_app.command("connect")
def sync_connect(
    ctx: typer.Context,
    folder: Annotated[
        str, typer.Argument(help="The folder your sync tool keeps in step (empty, or one to join).")
    ],
    name: Annotated[
        str | None, typer.Option("--name", help="This computer's name (default: its host name).")
    ] = None,
    keep: Annotated[
        str | None,
        typer.Option(
            "--keep",
            help="Joining while this computer has its own letters: keep “this” computer's Ordnung or the "
            "“folder”'s (the other is kept as an encrypted copy).",
        ),
    ] = None,
    data_dir: DataDirOption = None,
) -> None:
    """Set up a new sync folder (the passphrase twice) or join one (once)."""
    from ordnung.sync.agent import suggested_name
    from ordnung.sync.status import SyncChoice, SyncFolderInfo

    with _friendly():
        if keep not in (None, "this", "folder"):
            raise _fail("--keep is “this” or “folder”.")
        data = _sync_folder(ctx, data_dir)
        computer = name or suggested_name()
        info = reachable_server(data)
        if info is not None:
            found = SyncFolderInfo.model_validate(
                _sync_api(info, "POST", "/api/sync/inspect", {"folder": folder})
            )
        else:

            async def inspect(agent: Any) -> Any:
                return await agent.inspect(folder)

            found = _sync_in_process(data, inspect)
        if found.kind == "refused":
            raise _fail(found.problem or "This folder can't be used.", soft_wrap=True)
        if found.data_folder_synced:
            err_console.print(
                "[yellow]![/] Your Ordnung folder itself is inside a synced folder, so your sync tool already "
                "uploads it unencrypted.",
                soft_wrap=True,
            )
        new = found.kind == "new"
        console.print(
            f"{'Setting up a new sync in' if new else 'Joining the sync in'} [bold]{escape(found.folder)}[/] "
            f"as [bold]{escape(computer)}[/].",
            soft_wrap=True,
        )
        if new:
            console.print(SYNC_PASSPHRASE_WORDING)
        passphrase = _sync_passphrase(new=new)
        body = {"folder": folder, "name": computer, "passphrase": passphrase, "keep": keep}
        if info is not None:
            answer = _sync_api(info, "PUT", "/api/sync", body)
            choice = SyncChoice.model_validate(answer["choice"]) if answer.get("choice") else None
            status = _sync_status(data)
        else:

            async def connect(agent: Any) -> tuple[Any, Any]:
                chosen = await agent.connect(folder, computer, passphrase, keep=keep, secrets=agent.secrets)
                return chosen, agent.status()

            choice, status = _sync_in_process(data, connect)
    if choice is not None:
        _print_sync_choice(choice)
        raise _fail(
            "This computer already has its own Ordnung, so nothing was connected yet.",
            "Run the command again with --keep this or --keep folder.",
        )
    console.print("[green]✓[/] " + ("Started syncing." if new else "Joined."))
    _print_sync_status(status)


@sync_app.command("use-here")
def sync_use_here(
    ctx: typer.Context,
    older_copy: Annotated[
        bool, typer.Option("--older-copy", help="Use the copy this computer has now, without waiting.")
    ] = False,
    wait: Annotated[
        float,
        typer.Option(
            "--wait", help="Seconds to wait for your sync tool to bring everything (Ctrl+C cancels)."
        ),
    ] = 600.0,
    data_dir: DataDirOption = None,
) -> None:
    """“Use Ordnung here”: bring everything over from your other computer and use it on this one."""
    with _friendly():
        data = _sync_folder(ctx, data_dir)
        info = reachable_server(data)
        if info is not None:
            status = _use_here_remote(info, data, older_copy=older_copy, wait=wait)
        else:

            async def take_over(agent: Any) -> Any:
                await agent.use_here(older_copy=older_copy)
                deadline = time.monotonic() + wait
                while agent.status().take_over_waiting and time.monotonic() < deadline:
                    await asyncio.sleep(SYNC_WAIT_POLL_S)
                    await agent.wait_round()
                return agent.status()

            status = _sync_in_process(data, take_over)
    if status.mode == "in_use":
        console.print("[green]✓[/] Ordnung is in use here now.")
    elif status.choice is not None:
        _print_sync_choice(status.choice)
    elif status.take_over_waiting:
        console.print("Still waiting for your sync tool to bring everything. Run the command again later.")
    _print_sync_status(status)


def _use_here_remote(info: ServerInfo, folder: Path, *, older_copy: bool, wait: float) -> Any:
    from ordnung.sync.status import SyncStatus

    status = SyncStatus.model_validate(
        _sync_api(info, "POST", "/api/sync/use-here", {"older_copy": older_copy})
    )
    deadline = time.monotonic() + wait
    try:
        while status.take_over_waiting and time.monotonic() < deadline:
            time.sleep(SYNC_WAIT_POLL_S)
            status = SyncStatus.model_validate(_sync_api(info, "GET", "/api/sync"))
    except KeyboardInterrupt:  # nothing is applied before everything has arrived
        _sync_api(info, "POST", "/api/sync/use-here", {"cancel": True})
        raise
    return status


@sync_app.command("choose")
def sync_choose(
    ctx: typer.Context,
    side: Annotated[str, typer.Argument(help="“this”, or the other computer's name or number.")],
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask for confirmation.")] = False,
    data_dir: DataDirOption = None,
) -> None:
    """Both computers changed something: keep one computer's Ordnung (the other is kept as a copy)."""
    with _friendly():
        data = _sync_folder(ctx, data_dir)
        status = _sync_status(data, look=True)
        if status.choice is None:
            raise _fail("There's nothing to choose.")
        _print_sync_choice(status.choice)
        key = _side_key(status.choice, side)
        if not yes and not typer.confirm("Keep this one?", default=False):
            raise typer.Exit(1)
        info = reachable_server(data)
        if info is not None:
            from ordnung.sync.status import SyncStatus

            status = SyncStatus.model_validate(_sync_api(info, "POST", "/api/sync/choose", {"keep": key}))
        else:

            async def choose(agent: Any) -> Any:
                await agent.choose(key)
                return agent.status()

            status = _sync_in_process(data, choose, look=True)
    if status.mode == "in_use":
        console.print("[green]✓[/] Kept. Ordnung is in use here now.")
    _print_kept(status, data)


def _side_key(choice: Any, side: str) -> int:
    if side == "this":
        found = [candidate.key for candidate in choice.sides if candidate.this]
    elif side.isdigit():
        found = [candidate.key for candidate in choice.sides if candidate.key == int(side)]
    else:
        found = [
            candidate.key for candidate in choice.sides if candidate.computer == side and not candidate.this
        ]
    if len(found) != 1:
        raise _fail(
            f"“{side}” isn't one side of the choice." if not found else f"Two computers are called “{side}”.",
            "Name it by its number (ordnung sync choose NUMBER).",
        )
    return found[0]


def _print_kept(status: Any, folder: Path) -> None:
    from ordnung.assistant.mcp_install import shell_join

    for kept in status.kept:
        console.print(f"  Kept copy: {escape(kept.path)} — {escape(kept.why)}", soft_wrap=True)
        restore = shell_join(["ordnung", "restore", kept.path, "--data-dir", str(folder) + "-kept"])
        console.print(f"    Open it with the sync passphrase: {escape(restore)}", soft_wrap=True)


@sync_app.command("save")
def sync_save(
    ctx: typer.Context,
    hand_over: Annotated[
        bool, typer.Option("--hand-over", help="Then stand by, so you can use Ordnung on another computer.")
    ] = False,
    data_dir: DataDirOption = None,
) -> None:
    """Save to the sync folder now."""
    with _friendly():
        data = _sync_folder(ctx, data_dir)
        info = reachable_server(data)
        if info is not None:
            _sync_api(info, "POST", "/api/sync/save", {"hand_over": hand_over})
        else:

            async def save(agent: Any) -> None:
                await agent.save(hand_over=hand_over)

            _sync_in_process(data, save, look=True)
    console.print(
        "[green]✓[/] Handed over. Use Ordnung on your other computer now."
        if hand_over
        else "[green]✓[/] Saved to the sync folder."
    )


@sync_app.command("passphrase")
def sync_set_passphrase(ctx: typer.Context, data_dir: DataDirOption = None) -> None:
    """Type the sync passphrase again (the password store lost it)."""
    with _friendly():
        data = _sync_folder(ctx, data_dir)
        passphrase = _sync_passphrase(new=False)
        info = reachable_server(data)
        if info is not None:
            _sync_api(info, "POST", "/api/sync/passphrase", {"passphrase": passphrase})
        else:

            async def store(agent: Any) -> None:
                await agent.set_passphrase(passphrase, secrets=agent.secrets)

            _sync_in_process(data, store)
    console.print("[green]✓[/] Saved in this computer's password store.")


@sync_app.command("kept")
def sync_kept(
    ctx: typer.Context,
    delete: Annotated[str | None, typer.Option("--delete", help="Delete this kept copy for good.")] = None,
    data_dir: DataDirOption = None,
) -> None:
    """The kept copies on this computer (encrypted backups of data that was replaced)."""
    from urllib.parse import quote

    with _friendly():
        data = _sync_folder(ctx, data_dir)
        if delete is not None:
            info = reachable_server(data)
            if info is not None:
                with _api(info) as client:
                    response = client.delete(f"/api/sync/kept/{quote(delete, safe='')}")
                if response.status_code == 404:
                    raise _fail(f"There's no kept copy “{delete}”.")
                _checked(response)
            else:

                async def remove(agent: Any) -> bool:
                    return bool(await agent.delete_kept(delete))

                if not _sync_in_process(data, remove):
                    raise _fail(f"There's no kept copy “{delete}”.")
            console.print(f"[green]✓[/] Deleted {escape(delete)}.")
            return
        status = _sync_status(data)
    if not status.kept:
        console.print("There are no kept copies on this computer.")
        return
    _print_kept(status, data)


@sync_app.command("forget")
def sync_forget(
    ctx: typer.Context,
    computer: Annotated[str, typer.Argument(help="The lost computer's name or number.")],
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask for confirmation.")] = False,
    data_dir: DataDirOption = None,
) -> None:
    """Remove a lost, stolen or dead computer from sync (its changes nowhere else are kept here first)."""
    with _friendly():
        data = _sync_folder(ctx, data_dir)
        status = _sync_status(data, look=True)
        others = [found for found in status.computers if not found.this]
        matches = [
            found.key
            for found in others
            if (computer.isdigit() and found.key == int(computer)) or found.name == computer
        ]
        if len(matches) != 1:
            raise _fail(
                f"No other computer is called “{computer}”."
                if not matches
                else f"Two computers are called “{computer}”.",
                "Name it by its number (ordnung sync status lists them).",
            )
        console.print(
            f"{escape(computer)} still knows the passphrase. To lock it out of future changes, start a new sync "
            "folder with a new passphrase (disconnect, then set up again).",
            soft_wrap=True,
        )
        if not yes and not typer.confirm("Remove it from sync?", default=False):
            raise typer.Exit(1)
        info = reachable_server(data)
        if info is not None:
            _sync_api(info, "DELETE", f"/api/sync/computers/{matches[0]}")
        else:

            async def forget(agent: Any) -> None:
                await agent.forget(matches[0])

            _sync_in_process(data, forget, look=True)
    console.print(f"[green]✓[/] Removed {escape(computer)} from sync.")


@sync_app.command("disconnect")
def sync_disconnect(
    ctx: typer.Context,
    keep_passphrase: Annotated[
        bool, typer.Option("--keep-passphrase", help="Leave the passphrase in the password store.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask for confirmation.")] = False,
    data_dir: DataDirOption = None,
) -> None:
    """Stop syncing this computer (the folder and your other computers keep everything)."""
    from ordnung.sync import SyncError

    with _friendly():
        data = _sync_folder(ctx, data_dir)
        body = {"forget_passphrase": not keep_passphrase, "unreceived_ok": yes}
        for _ in range(2):
            try:
                _disconnect(data, body)
                break
            except SyncError as exc:
                if exc.kind != "not_received" or not typer.confirm(
                    f"{exc} Disconnect anyway?", default=False
                ):
                    raise
                body["unreceived_ok"] = True
    console.print(
        "[green]✓[/] This computer stopped syncing. The sync folder and your other computers keep everything."
    )


def _disconnect(folder: Path, body: dict[str, Any]) -> None:
    info = reachable_server(folder)
    if info is not None:
        _sync_api(info, "DELETE", "/api/sync", body)
        return

    async def leave(agent: Any) -> None:
        await agent.disconnect(
            forget_passphrase=bool(body["forget_passphrase"]), unreceived_ok=bool(body["unreceived_ok"])
        )

    _sync_in_process(folder, leave, look=True)


# --------------------------------------------------------------------------------------------------
# backup and restore
# --------------------------------------------------------------------------------------------------

PASSPHRASE_ENV = "ORDNUNG_BACKUP_PASSPHRASE"
PASSPHRASE_ENV_WEAK = (
    "Ordnung can't count this passphrase as strong enough for a backup kept on another drive or in the "
    "cloud. The backup is made all the same, so a scheduled one keeps running; for a stronger passphrase, "
    f"run `ordnung backup` without {PASSPHRASE_ENV} once and it suggests one."
)
PASSPHRASE_WARNING = (
    "Choose a passphrase and keep it somewhere safe (a password manager): Ordnung never stores it, and "
    "without it nobody can open this backup — not even you."
)


def human_size(size: int) -> str:
    """``812 bytes`` / ``48.3 KB`` / ``10.6 MB`` / ``1.2 GB`` (powers of 1000, like file managers)."""
    if size < 1000:
        return f"{size} bytes"
    value = float(size)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1000
        if value < 1000 or unit == "TB":
            break
    return f"{value:.1f} {unit}"


PASSPHRASE_TRIES = 3


def _passphrase(*, new: bool) -> str:
    """The backup passphrase: ``ORDNUNG_BACKUP_PASSPHRASE`` (scripts) or a hidden prompt — twice for
    a new backup, which must meet :func:`ordnung.backup.passphrase_problem`'s policy (a strong one is
    suggested first, as the web app's dialog does). A script's passphrase that is long enough but falls
    short of the strength only gets a warning: a scheduled backup set up before the rule keeps running."""
    from ordnung.backup import length_problem, passphrase_problem
    from ordnung.passphrase import suggested_passphrase

    def problem(value: str) -> str | None:
        if not value:
            return "The passphrase is empty."
        return passphrase_problem(value) if new else None

    given = os.environ.get(PASSPHRASE_ENV)
    if given is not None:
        # long enough is required; strong enough only warned about (a script may predate the rule)
        wrong = "The passphrase is empty." if not given else length_problem(given) if new else None
        if wrong:
            raise _fail(f"{PASSPHRASE_ENV}: {wrong}")
        if new and passphrase_problem(given):
            err_console.print(f"[yellow]![/] {PASSPHRASE_ENV}: {PASSPHRASE_ENV_WEAK}", soft_wrap=True)
        return given
    if new:
        err_console.print(
            "A strong passphrase, made up just now — type it below (or one of your own: five or more words "
            "that don't belong together), and save it in your password manager:"
        )
        err_console.print(f"  [bold]{suggested_passphrase()}[/]", soft_wrap=True)
    for _ in range(PASSPHRASE_TRIES):
        value = str(typer.prompt("Passphrase for the backup" if new else "Passphrase", hide_input=True))
        wrong = problem(value)
        if wrong:
            err_console.print(f"[red]✗[/] {escape(wrong)}")
            continue
        if new and str(typer.prompt("Repeat it", hide_input=True)) != value:
            err_console.print("[red]✗[/] The two passphrases differ. Try again.")
            continue
        return value
    raise _fail("No passphrase was given.")


@contextlib.contextmanager
def _read_lock(folder: Path) -> Iterator[bool]:
    """Hold the data folder's lock while backing it up if nothing else does (then the copy is exact);
    when Ordnung is running, read alongside it (the database snapshot is still consistent)."""
    from ordnung.locking import DataDirLock, DataDirLocked

    lock = DataDirLock(folder, purpose="ordnung backup")
    try:
        lock.acquire()
    except DataDirLocked:
        yield False
        return
    try:
        yield True
    finally:
        lock.release()


def _contents_line(contents: Any) -> str:
    letters = contents.letters
    return (
        f"{letters} letter{'s' if letters != 1 else ''}, {contents.files} file{'s' if contents.files != 1 else ''} "
        f"and the database · {human_size(contents.total_bytes)}"
    )


@app.command()
def backup(
    ctx: typer.Context,
    to: Annotated[
        str | None,
        typer.Option(
            "--to",
            help="Folder to save the backup in, or a new file name ending in .ordnung-backup "
            "(default: the current folder).",
            show_default=False,
        ),
    ] = None,
    data_dir: DataDirOption = None,
) -> None:
    """Save everything — database, letters, page images, letter PDFs — as one encrypted file."""
    from ordnung import backup as backups
    from ordnung import clock

    with _friendly():
        folder = _folder(ctx, data_dir)
        if not Paths(folder).db.is_file():
            raise _fail(
                f"There is no Ordnung database in {folder}.",
                hint="Name your data folder with --data-dir.",
                soft_wrap=True,
            )
        target = backups.destination(folder, to, clock.today())
        console.print(
            f"Backing up [bold]{escape(str(folder))}[/] to [bold]{escape(str(target))}[/]", soft_wrap=True
        )
        left_out = backups.links_left_out(folder)
        if left_out:
            shown = ", ".join(left_out[:5]) + (f" and {len(left_out) - 5} more" if len(left_out) > 5 else "")
            one = len(left_out) == 1
            console.print(
                f"[yellow]![/] Not in the backup: {escape(shown)} — {'a link' if one else 'links'} to somewhere "
                f"else, and a backup never follows links. Back {'that' if one else 'those'} up separately, or "
                f"move {'it' if one else 'them'} into the data folder.",
                soft_wrap=True,
            )
        console.print(PASSPHRASE_WARNING)
        passphrase = _passphrase(new=True)
        with _read_lock(folder) as exact:
            if not exact:
                console.print("[dim]Ordnung is running: the backup is taken alongside it.[/]")
            contents = backups.write_backup_file(folder, target, passphrase)
    console.print(
        f"[green]✓[/] Saved an encrypted backup: {escape(_contents_line(contents))}", soft_wrap=True
    )
    console.print(f"  {escape(str(target))}", soft_wrap=True)
    console.print("  Keep the passphrase somewhere safe (a password manager): you need it to restore.")
    console.print(f"  Restore it with: ordnung restore {escape(shell_quoted(str(target)))}", soft_wrap=True)


def shell_quoted(value: str) -> str:
    """``value`` quoted for this platform's shell, for a command the person copies."""
    from ordnung.assistant.mcp_install import shell_join

    return shell_join([value])


@app.command()
def restore(
    ctx: typer.Context,
    backup_file: Annotated[
        Path, typer.Argument(metavar="BACKUP", help="The backup file (.ordnung-backup).", show_default=False)
    ],
    data_dir: DataDirOption = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="If the data folder holds data, move it aside (nothing is deleted) and restore in its place.",
        ),
    ] = False,
    check: Annotated[
        bool,
        typer.Option(
            "--check", help="Only check the backup: decrypt and verify everything, restore nothing."
        ),
    ] = False,
) -> None:
    """Restore an encrypted backup (never over existing data without --force)."""
    from ordnung import backup as backups
    from ordnung.assistant.mcp_install import shell_join
    from ordnung.backup.restore import TargetInUse, check_target

    with _friendly():
        source = backup_file.expanduser()
        if not source.is_file():
            raise _fail(f"There is no file {source}.", soft_wrap=True)
        with source.open("rb") as handle:
            backups.read_header(handle)  # not a backup, or a newer format: say so before asking anything
        folder = _folder(ctx, data_dir)
        if check:
            passphrase = _passphrase(new=False)
            contents = backups.check_backup(source, passphrase)
            console.print(
                f"[green]✓[/] The backup is complete and opens with this passphrase: {escape(_contents_line(contents))}"
            )
            console.print(
                f"  Made on {escape(contents.manifest.created_at)} with Ordnung {escape(contents.manifest.app_version)}."
            )
            return
        try:
            found = check_target(folder, force=force)  # refuse early, before the passphrase
            console.print(f"Restoring into [bold]{escape(str(folder))}[/]", soft_wrap=True)
            if found:
                console.print(
                    "[yellow]![/] It holds data: it will be moved aside first (nothing is deleted)."
                )
            passphrase = _passphrase(new=False)
            result = backups.restore_backup(source, passphrase, folder, force=force)
        except TargetInUse as exc:
            raise _fail(str(exc), _stop_hint(folder), soft_wrap=True) from None
    console.print(f"[green]✓[/] Restored {escape(_contents_line(result.contents))}", soft_wrap=True)
    console.print(f"  into {escape(str(result.target))}", soft_wrap=True)
    if result.moved_aside is not None:
        console.print(
            f"  The data that was there is now in {escape(str(result.moved_aside))} — delete it once you are sure.",
            soft_wrap=True,
        )
    if result.calendar is not None:
        console.print(
            f"[yellow]![/] Calendar sync with “{escape(result.calendar)}” waits in this copy: enter the app "
            "password in Settings → Calendar to sync it again. If the Ordnung this backup came from still "
            "syncs to that calendar, disconnect it there first and leave its events in the calendar — two "
            "Ordnungs would change each other's events.",
            soft_wrap=True,
        )
    if result.folder is not None:
        console.print(
            f"[yellow]![/] The watched folder {escape(result.folder)} starts afresh in this copy: the files in "
            "it wait for you, and “Read new files with Claude straight away” is off until you turn it on "
            "again in Settings → Watched folder.",
            soft_wrap=True,
        )
    if result.moved_aside is not None and (result.moved_aside / Paths(result.moved_aside).sync.name).is_dir():
        console.print(
            "  The restored copy isn't connected to sync. Connect it again in Settings → Your computers.",
            soft_wrap=True,
        )
    serve_command = "ordnung serve"
    if result.target.resolve() != default_data_dir():
        serve_command = shell_join(["ordnung", "serve", "--data-dir", str(result.target)])
    console.print(f"  Start Ordnung with: {escape(serve_command)}", soft_wrap=True)


def _stop_hint(folder: Path) -> str | None:
    """How to stop the Ordnung that holds ``folder`` when it is the one started at login for it."""
    from ordnung import autostart

    try:
        entry = autostart.state(folder)
        started = (
            entry.enabled and entry.data_dir is not None and entry.data_dir.resolve() == folder.resolve()
        )
        stop = autostart.location().stop_now if started else None
    except (autostart.AutostartError, OSError):
        stop = None
    return f"Ordnung starts at login for this folder. To stop it: {stop}" if stop else None


@app.command()
def openapi() -> None:
    """Print the OpenAPI schema of the HTTP API as JSON (make openapi stores it for the web app)."""
    with _friendly():
        try:
            from ordnung.api.app import openapi_json
        except ModuleNotFoundError as exc:
            raise RuntimeError("The web app is not part of this installation of Ordnung.") from exc
        text = openapi_json()
    typer.echo(text, nl=False)
