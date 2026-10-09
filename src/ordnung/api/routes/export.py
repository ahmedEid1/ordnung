"""Export letters: ``GET /api/documents.zip``, the letters' original files as one ZIP download.

The choice (``year``, ``until``, ``tax``, ``party_id``) is checked before anything is read: a ``year``
outside 1900–2100 or an ``until`` that isn't a day of the year after ``year`` is refused (422), an unknown
sender is not found (404). The export only reads — it writes nothing, not even a privacy-log row, so a
computer standing by for hand-off sync can export its copy — and it runs only when the person clicks it.
The ZIP is not encrypted. A paired phone never gets it (403, also behind the phone listener's allow-list):
it holds every original, like a letter's own file.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ordnung.api.deps import StoreDep, TodayDep, require_computer
from ordnung.api.routes.common import IsoDate, require

router = APIRouter(tags=["export"])

ZIP_TYPE = "application/zip"
UNTIL_PROBLEM = "“until” goes with “year” and must be a day of the next year."
UNKNOWN_SENDER = "This sender doesn't exist (any more)."


def _checked_until(year: int | None, until: str | None) -> None:
    if until is None:
        return
    if year is None or date.fromisoformat(until).year != year + 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, UNTIL_PROBLEM)


@router.get(
    "/documents.zip",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {ZIP_TYPE: {}},
            "description": "The letters' original files and index.csv, as a ZIP",
        },
        404: {"description": "The sender doesn't exist (any more)"},
        422: {"description": "A year outside 1900–2100, or “until” without a year or outside the next year"},
    },
    dependencies=[Depends(require_computer)],
)
async def export_letters(
    store: StoreDep,
    today: TodayDep,
    year: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="only letters of that year, by the letter's date (else the day it arrived); undated "
            "letters are left out",
        ),
    ] = None,
    until: Annotated[
        IsoDate | None,
        Query(description="with “year”: also letters dated in the next year up to this day (YYYY-MM-DD)"),
    ] = None,
    tax: Annotated[bool, Query(description="only letters marked as mattering for taxes")] = False,
    party_id: Annotated[
        str | None, Query(description="only this sender's letters (for a letter you sent: its recipient's)")
    ] = None,
) -> StreamingResponse:
    """The letters' original files as a ZIP, in folders by year and sender
    (``<year>/<sender>/<date> <title>.<ext>``), with ``index.csv`` listing them (UTF-8 with a BOM,
    semicolons, opens in a spreadsheet). Every letter counts that isn't in the trash, waiting to be read
    or a proof file — private letters too, as they are the person's own files — narrowed by the choice.
    Sent as it is made (``Content-Disposition: attachment``, named
    ``ordnung-letters[-for-taxes][-<year>|-<today>].zip``; ``Cache-Control: no-store``). Writes nothing.
    """
    _checked_until(year, until)
    if party_id is not None:
        require(store.get_party(party_id), UNKNOWN_SENDER)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Exporting letters isn't ready yet.")
