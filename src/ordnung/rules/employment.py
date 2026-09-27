"""Registering as job-seeking after a dismissal or when a job ends (§ 38 Abs. 1 SGB III).

Pure date function; :mod:`ordnung.rules.letters` turns it into a receipt. The dismissal's other
deadline, the three weeks for a court action (§ 4 KSchG), is an ordinary period counted by
:mod:`ordnung.rules.deadlines`.

Policy: register at the latest three months before the job ends; if less than three months are left
when the person learns the end date, within three days of learning it. "Three months before" is
counted backwards from the job's last day (ends 30 September → by 30 June; ends 31 December → by
30 September — some guides say 1 October, the earlier day is used). The three days are calendar days
and are not moved off weekends: § 26 Abs. 3 SGB X may extend them, but registering online or by
phone works on any day, so the earlier date is kept (SPEC § 21). Without a known end date the
three-day rule is used — the earlier of the two.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from ordnung.rules.periods import latest_receipt_for

REGISTRATION_DAYS = 3
REGISTRATION_MONTHS = 3

RegistrationBasis = Literal["before_end", "after_learning"]


def registration_deadline(learned: date, end: date | None) -> tuple[date, RegistrationBasis]:
    """Last day to register as job-seeking, and which of the two rules gave it.

    ``learned`` is the day the person learned when the job ends (the day a dismissal arrived);
    ``end`` is the job's last day, if known.
    """
    if end is not None:
        before_end = latest_receipt_for(end, REGISTRATION_MONTHS, "months")
        if learned <= before_end:
            return before_end, "before_end"
    return learned + timedelta(days=REGISTRATION_DAYS), "after_learning"
