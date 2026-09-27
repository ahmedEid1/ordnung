"""My numbers: the person's own numbers, identity documents, a call sheet per organisation and the open
cases, sorted by :mod:`ordnung.numbers`. Worked out on read from the letters; nothing is stored."""

from __future__ import annotations

from fastapi import APIRouter

from ordnung import views
from ordnung.api.deps import StoreDep, TodayDep
from ordnung.models import MyNumbers

router = APIRouter(tags=["numbers"])


@router.get("/numbers", response_model=MyNumbers)
def my_numbers(store: StoreDep, today: TodayDep) -> MyNumbers:
    """About you (Steuer-ID, SV-Nummer …, with their check digits), identity documents with their expiry,
    one call sheet per organisation and the open cases with their references."""
    return views.my_numbers(store, today)
