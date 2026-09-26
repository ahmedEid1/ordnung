"""Job crash recovery and the health-insurance special right (round 2, R2-JOB-1/R2-ZB-1).

* ``Store.requeue_running_jobs`` fails a job after ``MAX_JOB_ATTEMPTS`` interruptions — it used to count
  ``attempts``, i.e. every claim, including the ones the worker gave back because Claude's usage limit
  was reached.
* ``zusatzbeitrag_raised`` decides whether a health insurer's letter opens the special right to cancel
  (§ 175 Abs. 4 S. 5 SGB V); it used to read the letter's sentences (its "unchanged" words matched
  inside ordinary German words) and now reads the rates the extraction states.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ordnung.db.store import MAX_JOB_ATTEMPTS, Store
from ordnung.models import ExtractedChange
from ordnung.secretary.triggers import zusatzbeitrag_raised

RATE_LIMIT_REASON = "Waiting for Claude: the usage limit was reached. Ordnung continues at about 14:00."


def test_rate_limit_pauses_do_not_count_as_crashes(store: Store) -> None:
    """A letter paused twice by the Claude usage limit (worker._pause requeues it, claim_next_job counts
    +1 each time) and interrupted once by an unclean exit used to be failed with 'Reading this letter
    stopped Ordnung several times' and never read."""
    document = store.add_document(sha256="d" * 64, filename="bill.pdf", mime="application/pdf", file_path="d")
    job = store.enqueue_job("ingest", document.id)
    past = datetime.now(UTC) - timedelta(minutes=1)
    for _ in range(MAX_JOB_ATTEMPTS - 1):  # two usage-limit pauses, exactly as Worker._pause records them
        claimed = store.claim_next_job()
        assert claimed is not None and claimed.id == job.id
        store.update_job(job.id, status="queued", waiting_reason=RATE_LIMIT_REASON, not_before=past)
    claimed = store.claim_next_job()  # the limit reset; reading again …
    assert claimed is not None and claimed.status == "running"

    store.requeue_running_jobs()  # … when the process is killed once (the next start recovers)

    recovered = store.get_job(job.id)
    assert recovered is not None and recovered.status == "queued", recovered
    stored = store.get_document(document.id)
    assert stored is not None and stored.status != "failed"

    for _ in range(MAX_JOB_ATTEMPTS - 1):  # it really crashes the process: two more unclean exits
        assert store.claim_next_job() is not None
        store.requeue_running_jobs()
    failed = store.get_job(job.id)
    assert failed is not None and failed.status == "failed"


def test_a_raise_stated_in_ordinary_wording_is_read_from_the_rates() -> None:
    """The model states the rates of "Gleichzeitig erhöhen wir unseren Zusatzbeitrag … von 2,69 % auf
    2,99 %", so the raise no longer depends on which words the sentence uses."""
    change = ExtractedChange(
        type="price_increase", effective_date="2027-01-01", unit_price_old="2,69 %", unit_price_new="2,99 %"
    )
    assert zusatzbeitrag_raised(change)
