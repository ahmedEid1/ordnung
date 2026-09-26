"""Final round: each test pinned one P0/P1 finding (EMAIL-F1, EMAIL-F2), now fixed."""

from __future__ import annotations

import email.policy as _email_policy
from email.message import EmailMessage as _EmailMessage
from pathlib import Path as _EmailPath

import pytest

from fixtures_llm import ALL_LETTERS as _EMAIL_ALL_LETTERS
from fixtures_llm import TODAY as _EMAIL_TODAY
from fixtures_llm import Letter as _EmailLetter
from fixtures_llm import Router as _EmailRouter
from fixtures_llm import fake_backend as _email_fake_backend
from fixtures_llm import iban as _email_iban

# ==================================================================================================
# HTML e-mails (final round): realistic mails whose bill disappears or turns into a scam alarm
# ==================================================================================================

_EMAIL_SHOP_IBAN = _email_iban("DE", "500105170648489890")
_EMAIL_PAY_QUOTE = "Bitte überweisen Sie 89,97 € bis zum 04.10.2026"

# A shop invoice as Maizzle / React Email / Cerberus templates write it: a preview-text block (what
# the inbox list shows next to the subject, padded with the usual &#8199;&#65279;&#847; spacer),
# then the invoice. Sent HTML-only (nodemailer ``html``, Rails with only an .html.erb view, Spring
# ``setText(html, true)`` …), so Ordnung reads the HTML part.
_EMAIL_SHOP_INVOICE_HTML = f"""<!DOCTYPE html>
<html lang="de" xmlns:v="urn:schemas-microsoft-com:vml">
<head>
  <meta charset="utf-8">
  <meta name="x-apple-disable-message-reformatting">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>Ihre Rechnung RE-2026-0915</title>
  <style>
    .hover-bg-indigo-700:hover {{ background-color: #4338ca !important; }}
    @media (max-width: 600px) {{
      .sm-px-6 {{ padding-left: 24px !important; padding-right: 24px !important; }}
      .sm-w-full {{ width: 100% !important; }}
    }}
  </style>
</head>
<body style="margin: 0; width: 100%; background-color: #f8fafc; padding: 0; word-break: break-word">
  <div style="display: none">
    Ihre Rechnung über 89,97 € ist da
    &#8199;&#65279;&#847; &#8199;&#65279;&#847; &#8199;&#65279;&#847; &#8199;&#65279;&#847; &#8199;&#65279;&#847;
  </div>
  <div role="article" aria-roledescription="email" aria-label="Ihre Rechnung RE-2026-0915" lang="de">
    <table align="center" cellpadding="0" cellspacing="0" role="none"><tr>
      <td class="sm-px-6" style="border-radius: 4px; background-color: #fff; padding: 48px; font-size: 16px; color: #334155">
        <h1 style="margin: 0 0 24px; font-size: 24px; font-weight: 600; color: #000">Danke für Ihre Bestellung!</h1>
        <p style="margin: 0; line-height: 24px">Hallo Maria, anbei Ihre Rechnung RE-2026-0915 vom 20.09.2026.</p>
        <table style="width: 100%" cellpadding="0" cellspacing="0" role="none">
          <tr><td style="padding: 8px 0">2 × Filterkartuschen Classic</td><td style="padding: 8px 0; text-align: right">59,98&nbsp;€</td></tr>
          <tr><td style="padding: 8px 0">1 × Wasserfilter-Kanne 2,4 l</td><td style="padding: 8px 0; text-align: right">24,99&nbsp;€</td></tr>
          <tr><td style="padding: 8px 0">Versand</td><td style="padding: 8px 0; text-align: right">5,00&nbsp;€</td></tr>
          <tr><td style="border-top: 1px solid #e2e8f0; padding-top: 12px; font-weight: 600">Gesamtbetrag</td>
              <td style="border-top: 1px solid #e2e8f0; padding-top: 12px; text-align: right; font-weight: 600">89,97&nbsp;€</td></tr>
        </table>
        <div style="border-radius: 4px; background-color: #eef2ff; padding: 16px; font-size: 14px; color: #3730a3">
          {_EMAIL_PAY_QUOTE} an Beispielshop GmbH, IBAN {_EMAIL_SHOP_IBAN}, Verwendungszweck RE-2026-0915.
        </div>
        <a href="https://shop.example.de/konto/rechnungen/RE-2026-0915" class="hover-bg-indigo-700"
           style="display: inline-block; border-radius: 4px; background-color: #4f46e5; padding: 16px 24px; color: #f8fafc; text-decoration: none">Rechnung als PDF &rarr;</a>
      </td>
    </tr></table>
  </div>
</body>
</html>"""

_EMAIL_SHOP_LETTER = _EmailLetter(
    marker="Danke für Ihre Bestellung",
    pages=(),
    payload={
        "kind": "invoice",
        "area": "money",
        "title": "Beispielshop invoice RE-2026-0915",
        "sender": {"name": "Beispielshop GmbH", "kind": "company"},
        "document_date": "2026-09-20",
        "references": [{"label": "Rechnungsnummer", "value": "RE-2026-0915"}],
        "summary": "Beispielshop bills 89.97 EUR for an order.",
        "explanation": "Pay the invoice by 4 October.",
        "items": [
            {
                "kind": "payment",
                "title": "Pay the Beispielshop invoice",
                "date": {
                    "type": "fixed",
                    "date": "2026-10-04",
                    "nature": "payment",
                    "text": "bis zum 04.10.2026",
                },
                "amount": 89.97,
                "currency": "EUR",
                "direction": "out",
                "quote": _EMAIL_PAY_QUOTE,
            }
        ],
        "payment": {"iban": _EMAIL_SHOP_IBAN, "payee": "Beispielshop GmbH", "reference": "RE-2026-0915"},
        "case_title": "Beispielshop order",
    },
)


def _email_shop_invoice(plain: str | None = None) -> bytes:
    """The invoice as an .eml: HTML-only, or ``multipart/alternative`` with ``plain`` as its text part."""
    message = _EmailMessage(policy=_email_policy.default)
    message["From"] = "Beispielshop <rechnung@shop.example.de>"
    message["To"] = "maria.rivera@example.de"
    message["Subject"] = "Ihre Rechnung RE-2026-0915"
    message["Date"] = "Sun, 20 Sep 2026 10:00:00 +0200"
    if plain is None:
        message.set_content(_EMAIL_SHOP_INVOICE_HTML, subtype="html", cte="quoted-printable")
    else:
        message.set_content(plain)
        message.add_alternative(_EMAIL_SHOP_INVOICE_HTML, subtype="html", cte="quoted-printable")
    return bytes(message)


async def test_email_a_bills_preview_text_is_no_scam_sign(data_dir: _EmailPath) -> None:
    """Nearly every template (Maizzle, React Email ``<Preview>``, MJML, Cerberus, Mailchimp, Brevo …)
    starts with a ``display:none`` preview-text block: the line every mail client shows in the inbox
    list next to the subject, so the reader does see it. html_to_text reports it as hidden text (point
    4: "a preheader is hidden text"); the pipeline then sets ``Document.hidden_text``, and
    ``triggers._scam_reasons`` turns that alone into a scam sign. Result for this ordinary shop
    invoice: a critical "This may be a scam: …" Idea telling the user not to pay, and the 89,97 €
    payment due 04.10.2026 dropped from ``actionable_items`` (never suggested, so it goes unpaid). The
    same happens to an HTML-only payment reminder (it then no longer covers its invoice)."""
    from ordnung import clock
    from ordnung.app_context import build_context
    from ordnung.ingest.pipeline import add_file
    from ordnung.ingest.text import text_document
    from ordnung.secretary.triggers import Ledger, run_triggers

    # the preview line is visible text (its own paragraph before the body), not hidden text
    document_text = text_document(_email_shop_invoice(), "message/rfc822")
    assert document_text.hidden_text == ""
    assert "\n\nIhre Rechnung über 89,97 € ist da\n\nDanke für Ihre Bestellung!\n" in document_text.text
    assert _EMAIL_PAY_QUOTE in " ".join(document_text.text.split())

    clock.set_today(_EMAIL_TODAY)
    context = build_context(
        data_dir, backend_obj=_email_fake_backend(_EmailRouter((_EMAIL_SHOP_LETTER, *_EMAIL_ALL_LETTERS)))
    )
    try:
        added = await add_file(context, _email_shop_invoice(), "rechnung.eml")
        await context.worker.run_until_idle()
        document = context.store.get_document(added.id)
        assert document is not None and document.status in ("processed", "needs_review"), document
        [payment] = [item for item in context.store.list_items(doc_id=document.id) if item.kind == "payment"]
        assert (payment.amount, payment.due_date) == (89.97, "2026-10-04")

        ledger = Ledger(context.store, clock.today())
        assert ledger.scam_reasons(document) == []
        assert payment.id in {item.id for item in ledger.actionable_items()}
        assert run_triggers(context.store, clock.today())["scam_warning"] == []
    finally:
        context.close()
        clock.set_today(None)


@pytest.mark.parametrize("plain", ["", "\r\n", " \n"], ids=["empty", "crlf", "blank-line"])
def test_email_an_empty_text_part_does_not_hide_the_html_bill(plain: str) -> None:
    """``_email_body`` takes the text/plain alternative whenever there is one (``get_body(("plain",
    "html"))``). Senders whose plain-text version is left empty — Spring's ``setText("", html)``,
    Python's ``set_content("")`` + ``add_alternative(html)``, an ESP campaign whose text version was
    cleared — still show the full bill in every mail client (they prefer the HTML part), but Ordnung
    reads only the headers: amount, due date and IBAN are gone from the page and from extraction."""
    from ordnung.ingest.text import text_document

    text = " ".join(text_document(_email_shop_invoice(plain), "message/rfc822").text.split())
    assert "Subject: Ihre Rechnung RE-2026-0915" in text  # the headers are read
    assert "89,97 €" in text and "04.10.2026" in text and _EMAIL_SHOP_IBAN in text, text


def test_email_an_empty_text_part_without_an_html_part_reads_the_headers() -> None:
    """The fallback to the HTML part needs one: an empty mail with only an empty text part is its headers."""
    from ordnung.ingest.text import text_document

    message = _EmailMessage(policy=_email_policy.default)
    message["From"] = "a@example.org"
    message["Subject"] = "Leer"
    message.set_content("\n")
    assert text_document(bytes(message), "message/rfc822").text == "From: a@example.org\nSubject: Leer"


def test_email_a_text_part_with_text_is_still_preferred_over_html() -> None:
    from ordnung.ingest.text import text_document

    text = text_document(
        _email_shop_invoice("Rechnung RE-2026-0915: 89,97 € bis 04.10.2026."), "message/rfc822"
    )
    assert text.text.endswith("\n\nRechnung RE-2026-0915: 89,97 € bis 04.10.2026.") and text.hidden_text == ""
