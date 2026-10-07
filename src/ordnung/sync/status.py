"""Hand-off sync's status and requests as the API carries them (``GET /api/sync`` and the writes of
:mod:`ordnung.api.routes.sync`), and the words for every problem (policy: :mod:`ordnung.sync`).

The models live here, not in the routes, so the sync agent (:mod:`ordnung.sync.agent`) builds the
status it keeps in memory with them, and the command line prints the same status without a server.
The web shows a problem's ``title`` and ``message`` — never its code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ordnung.sync import (
    NAME_MAX_CHARS,
    CalendarMatch,
    ComputerState,
    SyncActivity,
    SyncMode,
    SyncNoticeCode,
    SyncProblemAction,
    SyncProblemCode,
)

_RESPONSE = ConfigDict(json_schema_serialization_defaults_required=True)
_REQUEST = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------------------------------
# answers
# --------------------------------------------------------------------------------------------------


class SyncLetter(BaseModel):
    """A letter in a side's summary: its title and the calendar date it was added (no clock time)."""

    model_config = _RESPONSE

    label: str
    added_on: str


class SyncSideChange(BaseModel):
    """One of a side's latest changes: what it was made to, its title and the calendar date."""

    model_config = _RESPONSE

    kind: Literal["letter", "date", "to-do", "note", "contract"]
    label: str
    on: str = Field(description="The calendar date of the change (no clock time)")


class SyncProgress(BaseModel):
    """How far a first save, or bringing a version over, has got."""

    model_config = _RESPONSE

    done: int = Field(description="Files done")
    total: int = Field(description="Files in all")
    bytes_done: int
    bytes_total: int


class SyncComputer(BaseModel):
    """A computer of this sync, as this computer sees it (never its id)."""

    model_config = _RESPONSE

    key: int = Field(description="A small number for the UI, stable per computer (``choose``, ``forget``)")
    name: str = Field(description="The name it was given (“anna-thinkpad”)")
    this: bool = Field(description="This computer")
    in_use: bool = Field(description="It is the one in use")
    state: ComputerState = Field(
        description="What its latest head says: ``in_use``, ``standing_by``, ``closed`` (Ordnung was closed "
        "there while in use), ``left`` (it disconnected) or ``unknown`` (its head can't be read now)"
    )
    arrived_at: str | None = Field(
        default=None, description="This computer's clock: when that computer's latest change arrived here"
    )
    has_latest: bool | None = Field(
        default=None,
        description="This computer's latest saved version has fully arrived there (null: can't tell, or "
        "this computer)",
    )
    app_version: str = Field(description="The Ordnung version it runs")
    calendar: CalendarMatch = Field(
        description="Calendar sync there, compared with this computer's: ``none``; ``same`` calendar and "
        "mode; ``different_mode`` (the same calendar in another mode); ``other`` (another calendar, or "
        "none here)"
    )


class SyncArriving(BaseModel):
    """A version still arriving from the sync tool."""

    model_config = _RESPONSE

    from_computer: str = Field(description="The computer it comes from")
    have: int = Field(description="Files already here")
    need: int = Field(description="Files it needs in all")
    have_bytes: int
    need_bytes: int
    since: str = Field(description="This computer's clock: when waiting began")
    stalled: bool = Field(description="Nothing more arrived for 30 minutes")
    online_only: int = Field(
        description="Files the sync tool keeps online-only on this computer (placeholders, dataless files): "
        "they arrive only once the folder is available offline"
    )


class SyncProblem(BaseModel):
    """Why sync is paused or needs the person (the web shows the words, never the code)."""

    model_config = _RESPONSE

    code: SyncProblemCode
    title: str = Field(description="A short title for people")
    message: str = Field(description="What happened and what to do, for people")
    actions: list[SyncProblemAction] = Field(
        description="What the person can do about it, the main action first (none: wait, or the message says)"
    )


class SyncSide(BaseModel):
    """One computer's Ordnung in a choice."""

    model_config = _RESPONSE

    key: int = Field(description="The computer's ``key`` (what ``choose`` takes)")
    computer: str
    this: bool
    letters: int = Field(description="Letters in that Ordnung")
    added: int = Field(description="Letters added there since the two last agreed")
    newest: list[SyncLetter] = Field(description="Up to three letters, newest added first")
    items: int = Field(default=0, description="Dates and to-dos still open in that Ordnung")
    done: int = Field(default=0, description="Dates and to-dos marked done there")
    notes: int = Field(default=0, description="Notes there")
    latest: list[SyncSideChange] = Field(
        default_factory=list,
        description="Its three latest changes (letters, dates, to-dos, notes, contracts), newest first: what tells "
        "two sides apart when their counts are alike",
    )
    saved_at: str | None = Field(
        default=None, description="That computer's clock: when it saved this version"
    )
    arrived_at: str | None = Field(default=None, description="This computer's clock: when it arrived here")
    complete: bool = Field(description="It has fully arrived here (choosing one that hasn't waits for it)")
    arriving: SyncArriving | None = Field(default=None, description="What is still arriving of it")


class SyncChoice(BaseModel):
    """Both computers changed something: which computer's Ordnung to keep (the other is kept as a copy)."""

    model_config = _RESPONSE

    joining: bool = Field(description="This computer is joining and already has its own letters")
    sides: list[SyncSide]
    chosen: int | None = Field(
        default=None,
        description="The side chosen while it still arrives: kept as soon as it is here (``use-here`` with "
        "``cancel`` stops waiting)",
    )


class SyncKept(BaseModel):
    """A kept copy: this computer's data saved before it was replaced (an encrypted backup)."""

    model_config = _RESPONSE

    name: str = Field(description="Its file name (``ordnung-kept-2026-10-07-0912.ordnung-backup``)")
    path: str = Field(description="Where it is on this computer (for ``ordnung restore``)")
    size: int
    created_at: str = Field(description="This computer's clock")
    why: str = Field(description="Why it was kept, for people (“before you kept desktop's Ordnung”)")


class SyncNotice(BaseModel):
    """Something the person should know about once (dismissed with ``PATCH /api/sync``)."""

    model_config = _RESPONSE

    id: str
    code: SyncNoticeCode
    message: str = Field(description="For people")
    kept: str | None = Field(default=None, description="The kept copy it is about (its name)")
    at: str = Field(description="This computer's clock")


class SyncStatus(BaseModel):
    """What Settings → Your computers, the top bar and the standing-by screen show."""

    model_config = _RESPONSE

    available: bool = Field(
        description="Sync can be used on this computer (a password store; never the demo)"
    )
    unavailable: str | None = Field(default=None, description="Why not, in words")
    install_command: str | None = Field(default=None, description="The command that makes it available")
    connected: bool = Field(description="This computer syncs through a folder")
    mode: SyncMode = Field(
        description="``off`` (not connected), ``starting``, ``in_use`` (this computer is the one in use) or "
        "``standing_by`` (another computer is: writes are refused)"
    )
    activity: SyncActivity = Field(
        description="``idle``, ``saving``, ``waiting`` (for the sync tool), ``bringing_over`` (writes are "
        "refused for a moment) or ``keeping`` (writing a kept copy)"
    )
    progress: SyncProgress | None = None
    folder: str | None = Field(default=None, description="The sync folder on this computer")
    this_computer: str | None = Field(default=None, description="This computer's name")
    suggested_name: str = Field(description="The name offered when setting up (this computer's host name)")
    in_use_on: str | None = Field(default=None, description="The computer in use")
    computers: list[SyncComputer] = Field(default_factory=list, description="Every computer, this one too")
    last_saved_at: str | None = Field(
        default=None, description="This computer's clock: its last save into the folder"
    )
    pending_changes: bool = Field(
        default=False, description="This computer has changes that aren't in the sync folder yet"
    )
    others_have_latest: bool = Field(
        default=False,
        description="Another computer has received everything of this computer's (Disconnect and Delete "
        "everything ask twice when not)",
    )
    up_to_date: bool = Field(
        default=False, description="Standing by: the newest version has fully arrived here"
    )
    base_from: str | None = Field(
        default=None, description="Whose version this computer's data is (“the copy this computer has”)"
    )
    base_arrived_at: str | None = Field(default=None, description="This computer's clock: when it arrived")
    arriving: SyncArriving | None = None
    take_over_waiting: bool = Field(
        default=False, description="“Use Ordnung here” waits until everything has arrived"
    )
    choice: SyncChoice | None = Field(default=None, description="Both computers changed: which to keep")
    problem: SyncProblem | None = None
    notices: list[SyncNotice] = Field(default_factory=list)
    kept: list[SyncKept] = Field(default_factory=list, description="Kept copies on this computer")
    kept_warning: bool = Field(default=False, description="The kept copies take more than 2 GB in all")
    data_folder_synced: bool = Field(
        default=False,
        description="Ordnung's data folder itself is inside a synced folder, so the sync tool uploads it "
        "unencrypted",
    )


class SyncFolderInfo(BaseModel):
    """What a folder would be for sync (nothing is written)."""

    model_config = _RESPONSE

    kind: Literal["new", "existing", "refused"] = Field(
        description="``new``: missing or empty (apart from sync-tool files): a new sync starts there; "
        "``existing``: a sync to join; ``refused``: it can't be used (``problem`` says why)"
    )
    folder: str = Field(description="The folder as Ordnung would use it (resolved)")
    problem: str | None = Field(default=None, description="Why it can't be used, for people")
    examples: list[str] = Field(
        default_factory=list, description="Up to three names of other files found in it"
    )
    data_folder_synced: bool = Field(
        description="Ordnung's data folder itself is inside a synced folder (a warning, never a refusal)"
    )
    links_left_out: list[str] = Field(
        default_factory=list,
        description="Symbolic links in the data folder that sync leaves out (it never follows links)",
    )


class SyncConnected(BaseModel):
    """The result of setting up or joining: the status, or the choice to answer first."""

    model_config = _RESPONSE

    status: SyncStatus
    choice: SyncChoice | None = Field(
        default=None,
        description="Joining while this computer has its own letters: send ``keep`` to answer (nothing "
        "is connected yet)",
    )


# --------------------------------------------------------------------------------------------------
# requests
# --------------------------------------------------------------------------------------------------


class SyncInspect(BaseModel):
    """A folder to look at."""

    model_config = _REQUEST

    folder: str = Field(max_length=4096)


class SyncConnect(BaseModel):
    """Set up a new sync folder or join one (the passphrase is checked by the route)."""

    model_config = _REQUEST

    folder: str = Field(max_length=4096)
    name: str = Field(description=f"This computer's name (1 to {NAME_MAX_CHARS} characters)")
    passphrase: str
    keep: Literal["this", "folder"] | None = Field(
        default=None,
        description="Joining while this computer has its own letters: keep this computer's Ordnung, or "
        "the folder's (the other is kept as a copy)",
    )


class SyncChange(BaseModel):
    """Small changes and answers to a problem (each optional)."""

    model_config = _REQUEST

    name: str | None = Field(default=None, description="A new name for this computer")
    confirm_same_computer: bool = Field(
        default=False, description="“This is the same computer” (after the data folder moved or was copied)"
    )
    keep_as_is: bool = Field(
        default=False,
        description="“Keep this computer's data as it is” (after it went back in time and the last saved "
        "state can't be put back)",
    )
    abandon_pull: bool = Field(
        default=False, description="Give up a take-over that couldn't finish (this computer stands by)"
    )
    dismiss_notice: str | None = Field(default=None, description="A notice's ``id``")


class SyncDisconnect(BaseModel):
    """Disconnect this computer."""

    model_config = _REQUEST

    forget_passphrase: bool = Field(default=True, description="Also remove it from the password store")
    unreceived_ok: bool = Field(
        default=False,
        description="Disconnect although no other computer has this computer's latest changes yet (the "
        "second confirmation)",
    )


class SyncUseHere(BaseModel):
    """“Use Ordnung here”."""

    model_config = _REQUEST

    older_copy: bool = Field(
        default=False, description="Use the copy this computer has now instead of waiting for what arrives"
    )
    cancel: bool = Field(default=False, description="Stop a waiting take-over (or a waiting choice)")


class SyncChoose(BaseModel):
    """Which computer's Ordnung to keep."""

    model_config = _REQUEST

    keep: int = Field(description="The chosen side's ``key``")


class SyncSave(BaseModel):
    """Save now."""

    model_config = _REQUEST

    hand_over: bool = Field(default=False, description="Then stand by, so another computer can take over")


class SyncPassphrase(BaseModel):
    """The passphrase typed again (checked against the folder by the route)."""

    model_config = _REQUEST

    passphrase: str


# --------------------------------------------------------------------------------------------------
# problems, in words
# --------------------------------------------------------------------------------------------------

#: Title, message and actions of every problem; ``{name}`` is the other computer meant. The first
#: action is the main one.
PROBLEMS: dict[SyncProblemCode, tuple[str, str, tuple[SyncProblemAction, ...]]] = {
    "folder_missing": (
        "The sync folder isn't there",
        "Ordnung can't find the sync folder — is its drive or network share connected? Ordnung never "
        "creates it again by itself; if you moved it, choose it again. This computer keeps working, and "
        "its changes wait here.",
        ("choose_folder",),
    ),
    "folder_empty": (
        "The sync folder is empty",
        "The sync folder is there, but Ordnung's files are gone (a share that isn't mounted looks like "
        "this too). Once you're sure it is the right folder, fill it again from this computer.",
        ("refill",),
    ),
    "folder_other": (
        "The sync folder holds another sync",
        "This folder now holds a different Ordnung sync, so Ordnung stopped syncing to it. Choose the "
        "right folder again.",
        ("choose_folder",),
    ),
    "folder_full": (
        "The sync folder is full",
        "There's no space left in the sync folder (or in your sync provider's storage). Make some room "
        "there; Ordnung tries again by itself.",
        (),
    ),
    "folder_unreachable": (
        "The sync folder doesn't answer",
        "The sync folder took too long to answer — a network share that hangs, or files your sync tool "
        "keeps online only. Ordnung tries again by itself; this computer keeps working meanwhile.",
        (),
    ),
    "online_only": (
        "Some files are online only",
        "Your sync tool keeps some of the sync folder's files online only on this computer, so they "
        "can't be brought over. Make the folder available offline (in iCloud Drive, Dropbox or OneDrive: "
        "keep it on this device).",
        (),
    ),
    "two_setups": (
        "Two separate syncs started",
        "Another computer started a separate sync in this folder at the same moment. Disconnect this "
        "computer and set it up again to join that one.",
        ("new_computer",),
    ),
    "passphrase_needed": (
        "Type the sync passphrase again",
        "This computer's password store no longer has the sync passphrase (or it no longer opens the "
        "folder). Type it again; Ordnung keeps it there.",
        ("passphrase",),
    ),
    "keyring_unavailable": (
        "No password store",
        "This computer has no password store Ordnung can use, so it can't open the sync folder. On "
        "Linux, GNOME Keyring or KWallet must run and be unlocked.",
        (),
    ),
    "keyring_locked": (
        "The password store is locked",
        "Unlock this computer's password store (it usually unlocks when you log in), so Ordnung can open "
        "the sync folder. This computer keeps working meanwhile.",
        (),
    ),
    "newer_ordnung": (
        "Update Ordnung on this computer",
        "Another of your computers runs a newer Ordnung, so its changes can't be brought here. Update "
        "Ordnung on this computer; it keeps saving its own changes meanwhile.",
        (),
    ),
    "arrival_stalled": (
        "Still waiting for your sync tool",
        "Nothing more has arrived for 30 minutes. Check that your sync tool is running and signed in on "
        "both computers, isn't paused, and has space. If the folder is in iCloud Drive, Dropbox or "
        "OneDrive, make it available offline on this computer.",
        (),
    ),
    "not_received": (
        "Your other computer hasn't received your changes",
        "{name} hasn't received your latest changes for 30 minutes — is your sync tool running there?",
        (),
    ),
    "pull_unfinished": (
        "Bringing Ordnung over didn't finish",
        "Ordnung couldn't finish putting the other computer's data in place here (it tries again each "
        "time it starts). You can give it up: this computer then keeps what it has and stands by.",
        ("abandon",),
    ),
    "no_space": (
        "Not enough space on this computer",
        "This computer needs more free space to bring Ordnung over. Free some space, then try again.",
        (),
    ),
    "damaged": (
        "A file in the sync folder is damaged",
        "A file in the sync folder doesn't open. The computer that saved it writes it again the next time "
        "it runs; nothing is brought over until it does.",
        (),
    ),
    "local_damaged": (
        "A letter's file changed on this computer",
        "The file of a letter on this computer no longer matches what Ordnung stored (a disk problem?), "
        "so it isn't saved to the sync folder. Run “ordnung doctor”, or restore a backup.",
        (),
    ),
    "copied_folder": (
        "This data folder moved or was copied",
        "Ordnung's data folder is in another place, or on another computer, than when sync was set up. "
        "If it is the same computer (renamed, or the folder moved), say so. If it is a copy on a new "
        "computer, set that computer up as a new one.",
        ("same_computer", "new_computer"),
    ),
    "local_rollback": (
        "This computer's data went back in time",
        "Ordnung's data on this computer is older than what it last saved (a power cut?), and the saved "
        "state isn't in the sync folder to put back. You can keep this computer's data as it is.",
        ("keep_as_is",),
    ),
    "save_failing": (
        "Saving to the sync folder keeps failing",
        "Ordnung couldn't save to the sync folder for 30 minutes. It keeps trying; your changes wait on "
        "this computer.",
        (),
    ),
    "forgotten": (
        "This computer was removed from sync",
        "This computer was removed from sync on {name}, so it no longer saves or brings anything over. "
        "To sync it again, disconnect it and set it up again.",
        ("new_computer",),
    ),
}


def problem(
    code: SyncProblemCode, *, name: str | None = None, message: str | None = None, in_use: bool = True
) -> SyncProblem:
    """The problem ``code`` in words (``name``: the other computer meant; ``message`` replaces the
    standard one). "Fill it again" is offered only on the computer in use."""
    title, standard, actions = PROBLEMS[code]
    other = name or "your other computer"
    return SyncProblem(
        code=code,
        title=title,
        message=message if message else standard.format(name=other),
        actions=[action for action in actions if action != "refill" or in_use],
    )
