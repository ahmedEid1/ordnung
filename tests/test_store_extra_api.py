"""Store additions used by the HTTP API."""

from __future__ import annotations

from ordnung.db.store import Store


def _doc(store: Store, label: str) -> str:
    sha = (label * 64)[:64]
    return store.add_document(
        sha256=sha, filename=f"{label}.pdf", mime="application/pdf", file_path=f"files/{label}.pdf"
    ).id


def test_latest_job_is_the_newest_job_of_the_document(store: Store) -> None:
    first, other = _doc(store, "a"), _doc(store, "b")
    assert store.latest_job(first) is None

    store.enqueue_job("ingest", first)
    store.enqueue_job("ingest", other)
    newest = store.enqueue_job("reprocess", first, force=True)

    found = store.latest_job(first)
    assert found is not None
    assert found.id == newest.id
    assert found.kind == "reprocess"
    assert store.latest_job("doc_missing") is None
