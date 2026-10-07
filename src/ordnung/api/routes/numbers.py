"""My numbers: the person's own numbers, identity documents, a call sheet per organisation and the open
cases, sorted by :mod:`ordnung.numbers`. Worked out on read from the letters; nothing is stored. On a
paired phone the person's own numbers show only their last 4 characters (:mod:`ordnung.phone.mask`)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ordnung import views
from ordnung.api.deps import StoreDep, TodayDep, is_phone
from ordnung.models import MyNumbers
from ordnung.phone.mask import mask_numbers

router = APIRouter(tags=["numbers"])


@router.get("/numbers", response_model=MyNumbers)
def my_numbers(store: StoreDep, today: TodayDep, request: Request) -> MyNumbers:
    """About you (Steuer-ID, SV-Nummer …, with their check digits), identity documents with their expiry,
    one call sheet per organisation and the open cases with their references (on a phone, your own
    numbers show only their last 4 characters: ``masked``)."""
    page = views.my_numbers(store, today)
    return mask_numbers(page) if is_phone(request) else page
