"""The person's profile, the app settings and the first-run onboarding.

``PUT`` merges the fields sent into the stored values (the web app sends partial objects). A new
holiday region, country or postal buffer recomputes the dates of every letter's to-dos (contracts
are recomputed on read anyway). Settings guard the watched inbox folder (never the home folder, a
file-system root or Ordnung's own data) and keep the server-controlled ``demo`` and
``simulated_today`` read-only. A new inbox folder restarts the folder watcher; choosing Ordnung's own
inbox folder (``<data>/inbox``) creates it.
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ordnung.api.deps import CtxDep, StateDep, StoreDep, TodayDep
from ordnung.api.routes.common import ledger_changed
from ordnung.api.routes.dates import recompute_all_items
from ordnung.app_context import AppContext
from ordnung.config import Paths, private_dir
from ordnung.ingest.pipeline import ledger_lock
from ordnung.ingest.watcher import folder_chosen
from ordnung.models import AppSettings, Profile
from ordnung.rules import normalize_region
from ordnung.secretary.scam import iban_valid, normalize_iban

router = APIRouter(tags=["profile"])

_READ_ONLY_SETTINGS = ("demo", "simulated_today")
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

    @field_validator("iban")
    @classmethod
    def _valid_iban(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None if value is None else ""
        iban = normalize_iban(value)
        if not iban_valid(iban):
            raise ValueError("That IBAN isn't valid — check it against your bank card or banking app.")
        return iban

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
    concurrency: int | None = Field(default=None, ge=1, le=8)
    inbox_dir: str | None = None
    inbox_auto_read: bool | None = Field(
        default=None, description="read new files from the watched folder at once (else they wait for you)"
    )
    ocr: bool | None = None
    llm_brief: bool | None = None
    llm_review: bool | None = None
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
    return ctx.store.save_profile(current.model_dump() | changes | extra)


@router.get("/profile", response_model=Profile)
def read_profile(store: StoreDep) -> Profile:
    """The person's profile (name, address, region, language, reminders …)."""
    return store.get_profile()


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
    before = ctx.store.get_profile()
    profile = await asyncio.to_thread(_merge_profile, ctx, patch)
    await _recompute_if_dates_changed(ctx, before, profile, today)
    ctx.bus.publish("profile.updated")
    return profile


@router.post("/onboarding", response_model=Profile)
async def onboarding(body: OnboardingRequest, ctx: CtxDep, today: TodayDep) -> Profile:
    """Finish the first-run wizard: save the answers and mark the profile onboarded."""
    before = ctx.store.get_profile()
    profile = await asyncio.to_thread(_merge_profile, ctx, body.profile, onboarded=True)
    await _recompute_if_dates_changed(ctx, before, profile, today)
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
    if changes.get("models") is not None:
        changes["models"] = current.models.model_dump() | changes["models"]
    merged = current.model_dump() | {name: value for name, value in changes.items() if value is not None}
    if "inbox_dir" in changes:
        merged["inbox_dir"] = changes["inbox_dir"]
    ctx.store.save_settings(merged)
    if merged["inbox_dir"] != current.inbox_dir:  # chosen now: what is in it waits (also re-chosen)
        folder_chosen(ctx.store)
    return ctx.reload_settings()


@router.get("/settings", response_model=AppSettings)
def read_settings(store: StoreDep) -> AppSettings:
    """App settings: models per purpose, concurrency, inbox folder, AI note."""
    return store.get_settings()


@router.put("/settings", response_model=AppSettings)
async def update_settings(patch: SettingsPatch, state: StateDep) -> AppSettings:
    """Change settings (``demo`` and ``simulated_today`` can't be changed here); a new inbox folder
    restarts the folder watcher."""
    settings = await asyncio.to_thread(_merge_settings, state.ctx, patch)
    await state.folder.reconfigure()
    return settings
