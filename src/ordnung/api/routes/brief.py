"""The secretary's note on Today: ``GET`` serves today's stored note (or the code-written agenda,
without storing it — GETs have no side effects); ``POST`` writes a new one (by Claude when enabled,
checked against the agenda, else by code) and stores it."""

from __future__ import annotations

from fastapi import APIRouter

from ordnung.api.deps import CtxDep, StoreDep, TodayDep
from ordnung.secretary.brief import Brief, agenda_text, build_agenda, generate_brief, get_brief
from ordnung.tick import replay_miss_prone

router = APIRouter(tags=["brief"])


@router.get("/brief", response_model=Brief)
def read_brief(store: StoreDep, today: TodayDep) -> Brief:
    """Today's note: the stored one, else the agenda written by code."""
    stored = get_brief(store, today)
    if stored is not None:
        return stored
    agenda = build_agenda(store, today)
    return Brief(date=agenda.date, text=agenda_text(agenda), source="template")


@router.post("/brief", response_model=Brief)
async def regenerate_brief(ctx: CtxDep, today: TodayDep) -> Brief:
    """Write today's note again (Claude when "AI note" is on and available, else code)."""
    use_llm = ctx.store.get_settings().llm_brief and not replay_miss_prone(ctx.llm)
    brief = await generate_brief(ctx.store, ctx.llm if use_llm else None, today)
    ctx.bus.publish("brief.updated", date=brief.date, source=brief.source)
    return brief
