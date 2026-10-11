"""Build ``web/e2e/fixtures/outlook-bill.msg``: a fictional Outlook e-mail with a bill attached, made with
the tests' compound-file writer (``tests/helpers_msg.py``), so no binary file comes from anywhere else.
Every name, address and amount in it is invented. The same code gives the same bytes;
``tests/test_outlook.py`` rebuilds it and compares.

The attached PDF is larger than 4 KB, so its first bytes sit in the file's first kilobyte, as in real
Outlook files: the case where Ordnung once called the whole e-mail a broken PDF.

Run it from the repository root::

    python scripts/make_msg_fixture.py            # write the fixture
    python scripts/make_msg_fixture.py --check    # exit 1 if the committed file differs
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "web" / "e2e" / "fixtures" / "outlook-bill.msg"
sys.path.insert(0, str(ROOT / "tests"))

from helpers_msg import Attachment, Message, Recipient, build_msg, simple_pdf  # noqa: E402

BILL = (
    "Stadtwerke Musterstadt GmbH - SPECIMEN",
    "Sam Rivera, Musterweg 5, 12345 Musterstadt",
    "Stromrechnung Nr. 2026-0927 vom 27.09.2026",
    "Strom September 2026: 84,20 EUR",
    "Bitte zahlen Sie bis zum 15.10.2026.",
)
TEXT = (
    "Guten Tag Sam Rivera,\n\n"
    "anbei erhalten Sie Ihre Stromrechnung für September 2026 als PDF.\n\n"
    "Freundliche Grüße\nIhre Stadtwerke Musterstadt\n"
)
HTML = (
    "<html><body><p>Guten Tag Sam Rivera,</p>"
    "<p>anbei erhalten Sie Ihre Stromrechnung für September 2026 als PDF.</p>"
    "<p>Freundliche Grüße<br>Ihre Stadtwerke Musterstadt</p></body></html>"
)


def outlook_bill() -> bytes:
    """The fixture's bytes."""
    return build_msg(
        Message(
            subject="Ihre Stromrechnung September 2026",
            sender_name="Stadtwerke Musterstadt",
            sender_smtp="rechnung@stadtwerke-musterstadt.example",
            body=TEXT,
            html=HTML.encode(),
            message_id="<stromrechnung-2026-09@stadtwerke-musterstadt.example>",
            sent=datetime(2026, 9, 27, 8, 15, tzinfo=UTC),
            recipients=[Recipient("Sam Rivera", "sam@example.org")],
            attachments=[
                Attachment("Stromrechnung_2026-09.pdf", simple_pdf(BILL, at_least=6000), "application/pdf")
            ],
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed fixture differs")
    args = parser.parse_args(argv)
    data = outlook_bill()
    if args.check:
        if not FIXTURE.is_file() or FIXTURE.read_bytes() != data:
            print(f"{FIXTURE.relative_to(ROOT)} is out of date: run python scripts/make_msg_fixture.py")
            return 1
        print(f"{FIXTURE.relative_to(ROOT)} is current ({len(data)} bytes)")
        return 0
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_bytes(data)
    print(f"wrote {FIXTURE.relative_to(ROOT)} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
