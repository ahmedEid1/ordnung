"""Export letters over HTTP (``GET /api/documents.zip``): the choice is checked before anything is read,
the letters come as a ZIP named after the choice, and the export changes nothing."""

from __future__ import annotations

import contextlib
import io
import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from helpers_secretary import add_doc
from ordnung import clock
from ordnung.db.store import Store
from test_api_support import TODAY, api_for

ZIP = "/api/documents.zip"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.mark.parametrize(
    "params",
    [
        {"year": "1899"},
        {"year": "2101"},
        {"year": "last"},
        {"until": "2026-05-31"},  # "until" goes with a year
        {"year": "2025", "until": "2025-12-31"},  # … and is a day of the next year
        {"year": "2025", "until": "2027-01-01"},
        {"year": "2025", "until": "2026-02-30"},
        {"tax": "maybe"},
    ],
)
async def test_a_choice_outside_the_rules_is_refused(data_dir: Path, params: dict[str, str]) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.get(ZIP, params=params)
        assert response.status_code == 422, response.text


async def test_until_says_what_it_needs(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.get(ZIP, params={"until": "2026-05-31"})
        assert response.json()["detail"] == "“until” goes with “year” and must be a day of the next year."


async def test_an_unknown_sender_is_not_found(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.get(ZIP, params={"party_id": "pty_gone"})
        assert response.status_code == 404
        assert response.json()["detail"] == "This sender doesn't exist (any more)."


def letter(store: Store, label: str, data: bytes, **fields: Any) -> str:
    """A letter with its original stored in the data folder."""
    doc_id = add_doc(store, label, **fields)
    path = store.get_document_file(doc_id)
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return doc_id


def everything_in(data_dir: Path) -> tuple[list[str], list[tuple[str, int]]]:
    """Every row of the database and every file of the data folder (the database's own files aside)."""
    with contextlib.closing(sqlite3.connect(f"file:{data_dir / 'ordnung.db'}?mode=ro", uri=True)) as conn:
        rows = list(conn.iterdump())
    files = sorted(
        (path.relative_to(data_dir).as_posix(), path.stat().st_size)
        for path in data_dir.rglob("*")
        if path.is_file() and not path.name.startswith("ordnung.db")
    )
    return rows, files


async def test_a_year_for_taxes_downloads_as_a_zip(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        store = api.ctx.store
        office = store.add_party(name="Finanzamt Musterstadt", kind="tax_office")
        letter(
            store, "payslip", b"%PDF payslip", title="Payslip May", doc_date="2026-05-31", tax_relevant=True
        )
        letter(
            store,
            "assessment",
            b"%PDF assessment",
            title="Steuerbescheid 2025",
            doc_date="2026-03-14",
            party_id=office.id,
            tax_relevant=True,
        )
        letter(store, "rent", b"%PDF rent", title="Rent", doc_date="2026-02-01")
        letter(store, "older", b"%PDF older", title="Older", doc_date="2025-11-01", tax_relevant=True)
        response = await api.client.get(ZIP, params={"year": "2026", "tax": "true"})
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/zip"
        assert (
            response.headers["content-disposition"]
            == 'attachment; filename="ordnung-letters-for-taxes-2026.zip"'
        )
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        assert archive.namelist() == [
            "2026/Finanzamt Musterstadt/2026-03-14 Steuerbescheid 2025.pdf",
            "2026/Sender unknown/2026-05-31 Payslip May.pdf",
            "index.csv",
        ]
        assert (
            archive.read("2026/Finanzamt Musterstadt/2026-03-14 Steuerbescheid 2025.pdf")
            == b"%PDF assessment"
        )
        header = archive.read("index.csv").decode("utf-8-sig").split("\r\n")[0]
        assert header.startswith("file;letter_date;arrived;sender;title;")


async def test_the_next_years_early_letters_and_one_sender_narrow_the_zip(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        store = api.ctx.store
        insurer = store.add_party(name="Allianz", kind="insurer")
        letter(
            store, "statement", b"%PDF 1", title="Statement 2025", doc_date="2026-02-10", party_id=insurer.id
        )
        letter(store, "june", b"%PDF 2", title="June", doc_date="2026-06-10", party_id=insurer.id)
        letter(store, "policy", b"%PDF 3", title="Policy", doc_date="2025-01-10", party_id=insurer.id)
        letter(store, "other", b"%PDF 4", title="Other", doc_date="2025-01-11")
        response = await api.client.get(
            ZIP, params={"year": "2025", "until": "2026-05-31", "party_id": insurer.id}
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-disposition"] == 'attachment; filename="ordnung-letters-2025.zip"'
        assert zipfile.ZipFile(io.BytesIO(response.content)).namelist() == [
            "2025/Allianz/2025-01-10 Policy.pdf",
            "2026/Allianz/2026-02-10 Statement 2025.pdf",
            "index.csv",
        ]


async def test_without_a_year_every_letter_goes_in_and_the_zip_is_named_after_today(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        store = api.ctx.store
        letter(store, "dated", b"%PDF dated", title="Dated", doc_date="2024-07-01")
        letter(store, "undated", b"%PDF undated", title="Undated letter")
        response = await api.client.get(ZIP)
        assert response.status_code == 200, response.text
        assert (
            response.headers["content-disposition"] == f'attachment; filename="ordnung-letters-{TODAY}.zip"'
        )
        assert zipfile.ZipFile(io.BytesIO(response.content)).namelist() == [
            "2024/Sender unknown/2024-07-01 Dated.pdf",
            "Undated/Sender unknown/Undated letter.pdf",
            "index.csv",
        ]


async def test_an_export_changes_nothing(data_dir: Path) -> None:
    """A pure read: no row (not even in the privacy log) and no file is written."""
    async with api_for(data_dir) as api:
        store = api.ctx.store
        party = store.add_party(name="Finanzamt Musterstadt", kind="tax_office")
        letter(
            store,
            "tax",
            b"%PDF tax",
            title="Tax assessment",
            doc_date="2026-03-14",
            party_id=party.id,
            tax_relevant=True,
        )
        before = everything_in(data_dir)
        response = await api.client.get(
            ZIP, params={"year": "2025", "until": "2026-05-31", "tax": "true", "party_id": party.id}
        )
        assert response.status_code == 200, response.text
        assert len(zipfile.ZipFile(io.BytesIO(response.content)).namelist()) == 2
        assert everything_in(data_dir) == before
