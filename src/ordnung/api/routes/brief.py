"""The secretary's note on Today: ``GET`` serves today's stored note by Claude, else the code-written
agenda as it stands now (without storing it — GETs have no side effects); ``POST`` writes a new one (by
Claude when enabled, checked against the agenda, else by code) and stores it. Where Claude is only replayed
(the demo), no new note by Claude can be written: ``POST`` keeps the recorded one while the agenda it was
written from is unchanged, and writes the code's note once it has changed."""

from __future__ import annotations

from fastapi import APIRouter

from ordnung.api.deps import CtxDep, StoreDep, TodayDep
from ordnung.secretary.brief import Brief, current_brief, generate_brief
from ordnung.tick import replay_miss_prone

router = APIRouter(tags=["brief"])


@router.get("/brief", response_model=Brief)
def read_brief(store: StoreDep, today: TodayDep) -> Brief:
    """Today's note: the stored one Claude wrote, else the agenda written by code as it stands now."""
    return current_brief(store, today)


@router.post("/brief", response_model=Brief)
async def regenerate_brief(ctx: CtxDep, today: TodayDep, llm: bool = True) -> Brief:
    """Write today's note again (Claude when "AI note" is on and available, else code; ``llm=false``: code
    only, from the records — ``ordnung brief --no-llm``)."""
    wanted = llm and ctx.store.get_settings().llm_brief
    replays_only = replay_miss_prone(ctx.llm)
    if wanted and replays_only:
        kept = current_brief(ctx.store, today)
        if kept.source == "llm":  # Claude's recorded note, and the agenda it was written from is unchanged
            return kept
    brief = await generate_brief(ctx.store, ctx.llm if wanted and not replays_only else None, today)
    ctx.bus.publish("brief.updated", date=brief.date, source=brief.source)
    return brief
