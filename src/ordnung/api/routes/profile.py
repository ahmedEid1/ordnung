"""The person's profile, the app settings and the first-run onboarding.

``PUT`` merges the fields sent into the stored values (the web app sends partial objects; ``moved_on``
— the day the person said they moved in — is cleared with ``""``, like the other text fields). A new
holiday region, country or postal buffer recomputes the dates of every letter's to-dos (contracts
are recomputed on read anyway). A move is taken only for a day in the last six months or the next
three (422 otherwise), and a new, changed or cleared move refreshes the Ideas: the moving checklist
(:mod:`ordnung.secretary.moving`) starts, starts over or ends. Settings guard the watched inbox
folder (never the home folder, a file-system root or Ordnung's own data), take the model every call
runs on only as an id or alias Claude Code accepts, and keep the server-controlled ``demo`` and
``simulated_today`` read-only. A new inbox folder restarts the folder watcher; choosing Ordnung's own
inbox folder (``<data>/inbox``) creates it.

A paired phone (:mod:`ordnung.phone`) reads the profile with its IBAN masked to the last 4 characters,
and never changes settings (403, also behind the phone listener's allow-list).
"""

from __future__ import annotations

import asyncio
import re
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ordnung.api.deps import CtxDep, StateDep, StoreDep, TodayDep, is_phone, require_computer
from ordnung.api.routes.common import ledger_changed
from ordnung.api.routes.dates import recompute_all_items
from ordnung.app_context import AppContext
from ordnung.config import Paths, private_dir
from ordnung.db.store import PERSON_WRITE, person_write
from ordnung.ingest.pipeline import ledger_lock
from ordnung.ingest.watcher import folder_chosen
from ordnung.models import AppSettings, DesktopNotifyMode, Profile
from ordnung.phone.mask import mask_profile
from ordnung.rules import normalize_region
from ordnung.secretary.moving import move_problem
from ordnung.secretary.scam import iban_valid, normalize_iban
from ordnung.sync import LOCAL_SETTINGS

router = APIRouter(tags=["profile"])

_READ_ONLY_SETTINGS = ("demo", "simulated_today")
#: The shape the Profile form accepts (``EMAIL`` in ``web/src/features/settings/ProfileSection.tsx``).
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
#: A model id or alias as Claude Code takes it — ``claude-sonnet-5``, ``sonnet[1m]``, a Bedrock id with
#: ``:``, a Vertex id with ``@``, an inference-profile ARN with ``/``: no whitespace, and not starting
#: with a dash, because it follows ``--model`` on the CLI's argv (the static demo's mock API checks the same).
_MODEL = re.compile(r"[^\s-]\S*")
#: Profile fields the rules engine uses for to-do dates (holidays, German rules, send-by buffer).
_DATE_FIELDS = ("region", "country", "postal_buffer_days")


class ProfilePatch(BaseModel):
    """Profile fields to change (all optional)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=1000)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, min_length=2, max_length=10)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = None
    timezone: str | None = None
    reminder_days: dict[str, list[int]] | None = None
    postal_buffer_days: int | None = Field(default=None, ge=0, le=30)
    is_student_visa: bool | None = None
    onboarded: bool | None = None
    iban: str | None = Field(
        default=None, max_length=50, description="your account, for refunds (empty: none)"
    )
    moved_on: str | None = Field(
        default=None, max_length=10, description="the day you moved in (YYYY-MM-DD; empty: no move)"
    )
    old_address: str | None = Field(
        default=None, max_length=1000, description="your address before that move (empty: none)"
    )

    @field_validator("name")
    @classmethod
    def _real_name(cls, value: str | None) -> str | None:
        """The sender on every letter: trimmed, never blank (as the Profile form checks it)."""
        if value is None:
            return None
        name = " ".join(value.split())
        if not name:
            raise ValueError("Enter your name — it's the sender on your letters.")
        return name

    @field_validator("email")
    @classmethod
    def _email_address(cls, value: str | None) -> str | None:
        """Trimmed; empty removes it; anything else must look like an address (name@example.de)."""
        if value is None:
            return None
        email = value.strip()
        if email and not _EMAIL.fullmatch(email):
            raise ValueError("This doesn't look like an email address — like name@example.de.")
        return email

    @field_validator("phone")
    @classmethod
    def _trimmed(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("iban")
    @classmethod
    def _valid_iban(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None if value is None else ""
        iban = normalize_iban(value)
        if not iban_valid(iban):
            raise ValueError("That IBAN isn't valid — check it against your bank card or banking app.")
        return iban

    @field_validator("moved_on")
    @classmethod
    def _move_day(cls, value: str | None) -> str | None:
        """An ISO day, normalised; empty clears the move (stored as no move: ``None``)."""
        if value is None or not value.strip():
            return value if value is None else ""
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError as exc:
            raise ValueError(f"“{value}” is not a date; use the form YYYY-MM-DD.") from exc

    @field_validator("region")
    @classmethod
    def _known_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = normalize_region(value)
        if code is None:
            raise ValueError(f"“{value}” is not a German Bundesland (use a code like NW or BY).")
        return code

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"“{value}” is not a known time zone (e.g. Europe/Berlin).") from exc
        return value


class SettingsPatch(BaseModel):
    """Settings to change (all optional; ``models`` is merged by purpose)."""

    model_config = ConfigDict(extra="forbid")

    models: dict[str, str] | None = None
    model: str | None = Field(
        default=None,
        max_length=200,
        description="the model every call runs on: an id or alias Claude Code accepts (claude-sonnet-5 by default)",
    )
    concurrency: int | None = Field(default=None, ge=1, le=8)
    inbox_dir: str | None = None
    inbox_auto_read: bool | None = Field(
        default=None, description="read new files from the watched folder at once (else they wait for you)"
    )
    llm_brief: bool | None = None
    llm_review: bool | None = None
    desktop_notifications: DesktopNotifyMode | None = None
    desktop_notify_time: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="Local time of day, HH:MM (24 h)"
    )
    demo: bool | None = None
    simulated_today: str | None = None


class OnboardingRequest(BaseModel):
    """The first-run wizard's answers."""

    model_config = ConfigDict(extra="forbid")

    profile: ProfilePatch = Field(default_factory=ProfilePatch)
    skip_ai: bool = Field(
        default=False,
        description="“Continue without AI”: no model-written daily note and no weekly Ideas review",
    )


# --------------------------------------------------------------------------------------------------
# profile
# --------------------------------------------------------------------------------------------------


def _merge_profile(ctx: AppContext, patch: ProfilePatch, **extra: Any) -> Profile:
    current = ctx.store.get_profile()
    changes = {
        name: value for name, value in patch.model_dump(exclude_unset=True).items() if value is not None
    }
    if changes.get("moved_on") == "":
        changes["moved_on"] = None  # "" clears the move
    return ctx.store.save_profile(current.model_dump() | changes | extra)


def _checked_move(patch: ProfilePatch, today: date) -> None:
    """A move told for a day outside the last six months or the next three is refused (422): the checklist
    it starts is for a move being made (:func:`ordnung.secretary.moving.move_problem`)."""
    if not patch.moved_on:
        return
    problem = move_problem(date.fromisoformat(patch.moved_on), today)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)


def _refresh_if_moved(ctx: AppContext, before: Profile, after: Profile) -> None:
    """A new, changed or cleared move starts, restarts or ends the moving checklist: the Ideas are refreshed
    in the background (they publish ``suggestions.updated``; no to-do changed)."""
    if before.moved_on != after.moved_on:
        ctx.worker.refresh_ideas()


@router.get("/profile", response_model=Profile)
def read_profile(store: StoreDep, request: Request) -> Profile:
    """The person's profile (name, address, region, language, reminders …); on a phone the IBAN shows
    only its last 4 characters."""
    profile = store.get_profile()
    return mask_profile(profile) if is_phone(request) else profile


async def _recompute_if_dates_changed(ctx: AppContext, before: Profile, after: Profile, today: date) -> None:
    """Recompute every letter's to-do dates when a fact they depend on changed (the holiday region …)."""
    if all(getattr(before, name) == getattr(after, name) for name in _DATE_FIELDS):
        return
    async with ledger_lock():
        await asyncio.to_thread(recompute_all_items, ctx.store, today)
    await ledger_changed(ctx)


@router.put("/profile", response_model=Profile)
async def update_profile(patch: ProfilePatch, ctx: CtxDep, today: TodayDep) -> Profile:
    """Change profile fields; a new region (country, postal buffer) recomputes the to-dos' dates."""
    _checked_move(patch, today)
    before = ctx.store.get_profile()
    profile = await asyncio.to_thread(_merge_profile, ctx, patch)
    await _recompute_if_dates_changed(ctx, before, profile, today)
    _refresh_if_moved(ctx, before, profile)
    ctx.bus.publish("profile.updated")
    return profile


@router.post("/onboarding", response_model=Profile)
async def onboarding(body: OnboardingRequest, ctx: CtxDep, today: TodayDep) -> Profile:
    """Finish the first-run wizard: save the answers and mark the profile onboarded."""
    _checked_move(body.profile, today)
    before = ctx.store.get_profile()
    profile = await asyncio.to_thread(_merge_profile, ctx, body.profile, onboarded=True)
    await _recompute_if_dates_changed(ctx, before, profile, today)
    _refresh_if_moved(ctx, before, profile)
    if body.skip_ai:
        settings = ctx.store.get_settings().model_copy(update={"llm_brief": False, "llm_review": False})
        await asyncio.to_thread(ctx.store.save_settings, settings)
        ctx.reload_settings()
    ctx.store.log_activity("onboarding.done", "Finished setting up Ordnung", data={"skip_ai": body.skip_ai})
    ctx.bus.publish("profile.updated")
    return profile


# --------------------------------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------------------------------


def inbox_dir_problem(value: str, paths: Paths) -> str | None:
    """Why ``value`` can't be the watched inbox folder (``None`` if it can)."""
    folder = Path(value).expanduser()
    if not folder.is_absolute():
        return "Please choose a full folder path (for example /home/you/Scans)."
    folder = folder.resolve()
    data = paths.data_dir.resolve()
    if folder == Path(folder.anchor):
        return "The inbox can't be the root of a drive."
    if folder == Path.home().resolve():
        return "The inbox can't be your whole home folder — choose a dedicated folder."
    if folder == data or data.is_relative_to(folder):
        return "The inbox can't be Ordnung's data folder or a folder that contains it."
    if any(folder.is_relative_to(inner.resolve()) for inner in (paths.files, paths.derived, paths.drafts)):
        return "The inbox can't be inside Ordnung's own storage folders."
    return None


def model_problem(value: str) -> str | None:
    """Why ``value`` can't be the model every call runs on (``None`` if it can; ``value`` is trimmed)."""
    if not value:
        return "Enter a model id or alias, like claude-sonnet-5 or sonnet."
    if not _MODEL.fullmatch(value):
        return (
            "A model name has no spaces and doesn't start with a dash — like claude-sonnet-5 or sonnet[1m]."
        )
    return None


def _checked_model(value: str) -> str:
    model = value.strip()
    problem = model_problem(model)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    return model


def _checked_inbox(value: str | None, paths: Paths) -> str | None:
    if not value:
        return None
    problem = inbox_dir_problem(value, paths)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    folder = Path(value).expanduser().resolve()
    if folder == paths.inbox.resolve():
        private_dir(folder)  # Ordnung's own inbox folder: ready to save scans into
    return str(folder)


def _merge_settings(ctx: AppContext, patch: SettingsPatch) -> AppSettings:
    current = ctx.store.get_settings()
    changes = {name: value for name, value in patch.model_dump(exclude_unset=True).items()}
    for name in _READ_ONLY_SETTINGS:
        if name in changes and changes.pop(name) != getattr(current, name):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"“{name}” is set by how Ordnung was started."
            )
    if "inbox_dir" in changes:
        changes["inbox_dir"] = _checked_inbox(changes["inbox_dir"], ctx.paths)
    if changes.get("model") is not None:
        changes["model"] = _checked_model(changes["model"])
    if changes.get("models") is not None:
        changes["models"] = current.models.model_dump() | changes["models"]
    before = current.model_dump()
    merged = before | {name: value for name, value in changes.items() if value is not None}
    if "inbox_dir" in changes:
        merged["inbox_dir"] = changes["inbox_dir"]
    # only this computer's own settings changed (its watched folder, its notifications): not a change
    # of the person's data that hand-off sync carries, so it never makes a person version
    synced = any(merged[name] != before[name] for name in merged if name not in LOCAL_SETTINGS)
    with person_write(PERSON_WRITE.get() and synced):
        ctx.store.save_settings(merged)
        if merged["inbox_dir"] != current.inbox_dir:  # chosen now: what is in it waits (also re-chosen)
            folder_chosen(ctx.store)
    return ctx.reload_settings()


@router.get("/settings", response_model=AppSettings)
def read_settings(store: StoreDep) -> AppSettings:
    """App settings: the model every call runs on (and the aliases per purpose), concurrency, inbox
    folder, AI note."""
    return store.get_settings()


@router.put("/settings", response_model=AppSettings, dependencies=[Depends(require_computer)])
async def update_settings(patch: SettingsPatch, state: StateDep) -> AppSettings:
    """Change settings (``demo`` and ``simulated_today`` can't be changed here); a new inbox folder
    restarts the folder watcher, a new model counts from the next call to Claude."""
    settings = await asyncio.to_thread(_merge_settings, state.ctx, patch)
    await state.folder.reconfigure()
    return settings
