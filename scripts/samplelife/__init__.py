"""Generator for Ordnung's fictional "sample life" (the demo persona Sam Rivera).

Every organisation, person, address, phone number and account in here is fictional. The generator is
deterministic: running it twice produces byte-identical PDFs, JPEGs and ``manifest.json``.

Modules:

* :mod:`samplelife.ids` – check digits for IBANs, SEPA creditor IDs, VAT IDs and passport MRZ lines.
* :mod:`samplelife.fmt` – German/English number and date formatting.
* :mod:`samplelife.datecheck` – hand-checked calendar facts used to *assert* the expected dates.
* :mod:`samplelife.persona` – Sam Rivera and his bank account.
* :mod:`samplelife.orgs` – the fictional senders (letterhead, colours, footer, bank details).
* :mod:`samplelife.letter` – a DIN 5008 (Form B) letter engine on top of fpdf2.
* :mod:`samplelife.photo` – "phone photo" simulation with Pillow.
* :mod:`samplelife.passport` – the passport data page drawn with Pillow.
* :mod:`samplelife.truth` – ground-truth records written to the manifest.
* :mod:`samplelife.common` – shared helpers of the document modules (dates, render → PDF/photos).
* :mod:`samplelife.logos` – the invented vector logos.
* ``samplelife.docs_*`` – the documents themselves.
* :mod:`samplelife.build` – orchestration and the command-line entry point.
"""
