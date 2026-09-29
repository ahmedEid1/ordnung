"""Store additions used by the HTTP API."""

from __future__ import annotations

import pytest

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


def test_documents_of_one_source(store: Store) -> None:
    upload = _doc(store, "a")
    attached = store.add_document(
        sha256="c" * 64,
        filename="c.pdf",
        mime="application/pdf",
        file_path="files/c.pdf",
        source=f"email:{upload}",
    ).id
    assert [doc.id for doc in store.list_documents(source=f"email:{upload}")] == [attached]
    assert [doc.id for doc in store.list_documents(source="upload")] == [upload]
    assert store.list_documents(source="folder") == []


def test_activity_by_kind_and_data(store: Store) -> None:
    store.log_activity("document.added", "Added a", data={"source": "folder"})
    store.log_activity("document.added", "Added b", data={"source": "upload"})
    store.log_activity("folder.refused", "Refused c", data={"source": "folder"})
    store.log_activity("calendar.exported", "Exported", data={"source": "folder"})
    kinds = ["document.added", "folder.refused"]
    found = store.list_activity(10, kinds=kinds, data={"source": "folder"})
    assert [entry.message for entry in found] == ["Refused c", "Added a"]
    assert [entry.message for entry in store.list_activity(1, kinds=kinds)] == ["Refused c"]
    with pytest.raises(ValueError, match="not a data key"):
        store.list_activity(10, data={"source') OR 1=1 --": "x"})
