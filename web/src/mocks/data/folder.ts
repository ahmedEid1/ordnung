/**
 * Sam's watched folder (`~/Scans`): what it brought in and what waits for Sam's answer — a scan from
 * the building management and an e-mailed phone bill with its PDF (both *held*: stored in the demo,
 * not read by Claude until Sam says so), a scan that was already in Ordnung and a file it refused.
 */
import type { Document, EmailAttachment, FolderPickup } from "@/api/types";
import type { LetterSpec } from "../pages";
import { RECIPIENT, SAM, ts } from "./constants";
import { doc } from "./helpers";

export const FOLDER_PATH = "/home/sam/Scans";
export const SUGGESTED_INBOX = "/home/sam/.local/share/ordnung-demo/inbox";

/** A held letter as the server stores it: private, titled by its file name, read on this computer only. */
function held(d: Pick<Document, "id" | "filename" | "mime" | "source" | "created_at"> & Partial<Document>): Document {
  return doc({
    title: d.filename,
    status: "held",
    ai_private: true,
    kind: null,
    area: null,
    language: null,
    urgency: null,
    ai_processed_at: null,
    processed_at: d.created_at,
    updated_at: d.created_at,
    ...d,
  });
}

export const FOLDER_DOCUMENTS: Document[] = [
  held({
    id: "doc_folder_scan",
    filename: "Scan_2026-09-28_0914.pdf",
    mime: "application/pdf",
    source: "folder",
    created_at: ts("2026-09-28", "09:14"),
  }),
  held({
    id: "doc_folder_mail",
    filename: "Ihre Rechnung September 2026.eml",
    mime: "message/rfc822",
    source: "folder",
    created_at: ts("2026-09-27", "18:02"),
  }),
  held({
    id: "doc_folder_invoice",
    filename: "Rechnung_2026-09_FunkNetz.pdf",
    mime: "application/pdf",
    source: "email:doc_folder_mail",
    created_at: ts("2026-09-27", "18:02"),
  }),
];

/** What became of the e-mail's attachments (as the server lists them on the e-mail). */
export const EMAIL_ATTACHMENTS: Record<string, EmailAttachment[]> = {
  doc_folder_mail: [
    {
      filename: "Rechnung_2026-09_FunkNetz.pdf",
      outcome: "added",
      detail: "Added as its own letter",
      doc_id: "doc_folder_invoice",
    },
    {
      filename: "funknetz-logo.png",
      outcome: "inline",
      detail: "A picture inside the e-mail (a logo or similar) — not read",
      doc_id: null,
    },
    {
      filename: "Preisliste_Tarife_2026.docx",
      outcome: "not_read",
      detail: "Ordnung reads PDFs and photos from e-mails — this file is listed only",
      doc_id: null,
    },
  ],
};

/** The last files the folder brought in, newest first (their letters' status is looked up live). */
export const FOLDER_RECENT: FolderPickup[] = [
  {
    at: ts("2026-09-28", "09:14"),
    filename: "Scan_2026-09-28_0914.pdf",
    outcome: "added",
    detail: "",
    doc_id: "doc_folder_scan",
    status: "held",
  },
  {
    at: ts("2026-09-27", "18:02"),
    filename: "Ihre Rechnung September 2026.eml",
    outcome: "added",
    detail: "",
    doc_id: "doc_folder_mail",
    status: "held",
  },
  {
    at: ts("2026-09-26", "11:39"),
    filename: "Scan_2026-09-26_1139.pdf",
    outcome: "known",
    detail: "",
    doc_id: "doc_library",
    status: "processed",
  },
  {
    at: ts("2026-09-25", "08:03"),
    filename: "Kontoauszug_2026_Q3_passwortgeschuetzt.pdf",
    outcome: "refused",
    detail: "This PDF could not be opened. It may be damaged or password-protected.",
    doc_id: null,
    status: null,
  },
];

/** Page images of the waiting letters (all fictional, marked SPECIMEN like the rest of Sam's life). */
export const FOLDER_LETTERS: Record<string, LetterSpec> = {
  doc_folder_scan: {
    brand: {
      name: "Hausverwaltung Kramer",
      color: "#44617b",
      tagline: "Verwaltung · Vermietung",
      mark: "bars",
    },
    senderLine: "Hausverwaltung Kramer · Lindenallee 12 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "24.09.2026"],
      ["Objekt", "Beispielweg 5"],
    ],
    pages: [
      {
        subject: "Ablesung der Wasserzähler",
        blocks: [
          `Guten Tag ${SAM.name},`,
          "am 14.10.2026 zwischen 8:00 und 12:00 Uhr lesen wir in Ihrer Wohnung die Wasserzähler ab.",
          "Bitte sorgen Sie dafür, dass die Zähler in Bad und Küche frei zugänglich sind. Passt Ihnen der Termin nicht, rufen Sie uns bitte bis zum 07.10.2026 an.",
          "SPECIMEN — Musterbrief",
          "Mit freundlichen Grüßen",
          "Ihre Hausverwaltung Kramer",
        ],
      },
    ],
    footer: ["Hausverwaltung Kramer · Telefon 0123 45 67 89"],
  },
  doc_folder_mail: {
    brand: {
      name: "E-Mail",
      color: "#6b675f",
      tagline: "rechnung@funknetz.example",
      mark: "none",
    },
    info: [["Datum", "27.09.2026"]],
    pages: [
      {
        subject: "Ihre Rechnung September 2026",
        blocks: [
          "Von: FunkNetz Kundenservice <rechnung@funknetz.example>",
          `An: ${SAM.name} <${SAM.email}>`,
          "Anhänge: Rechnung_2026-09_FunkNetz.pdf, Preisliste_Tarife_2026.docx",
          { gap: 12 },
          `Guten Tag ${SAM.name},`,
          "Ihre Rechnung für September 2026 finden Sie im Anhang dieser E-Mail. Der Betrag wird wie gewohnt per Lastschrift eingezogen.",
          "SPECIMEN — Muster-E-Mail",
          "Ihr FunkNetz Team",
        ],
      },
    ],
  },
  doc_folder_invoice: {
    brand: {
      name: "FunkNetz",
      color: "#7a3fb0",
      tagline: "Mobilfunk",
      mark: "wave",
    },
    senderLine: "FunkNetz GmbH · Antennenweg 3 · 12347 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "27.09.2026"],
      ["Rechnungsnummer", "FN-2026-09-4471"],
      ["Kundennummer", "FN-5521904"],
    ],
    pages: [
      {
        subject: "Rechnung September 2026",
        blocks: [
          {
            rows: [
              ["Grundpreis Tarif Smart 10 GB", "34,99 EUR"],
              ["Rechnungsbetrag", "34,99 EUR"],
            ],
            boldLast: true,
          },
          "Der Rechnungsbetrag wird am 05.10.2026 von Ihrem Konto abgebucht.",
          "SPECIMEN — Musterrechnung",
        ],
      },
    ],
    footer: ["FunkNetz GmbH · Gläubiger-ID DE98ZZZ09999999999"],
  },
};
