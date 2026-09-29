/**
 * The letters of Sam Rivera's sample life (all fictional, marked SPECIMEN). Each spec renders to
 * page images; evidence quotes (`Q`) are located on these pages to produce highlight boxes.
 * Keep quotes verbatim — a quote that cannot be found becomes "Couldn't find this — please check".
 */
import type { LetterSpec } from "../pages";
import { RECIPIENT, SAM } from "./constants";

/** Verbatim evidence quotes per document. */
export const Q = {
  lease: {
    rent: "Die Gesamtmiete beträgt monatlich 640,00 EUR",
    due: "spätestens am dritten Werktag des Monats",
    start: "Das Mietverhältnis beginnt am 01.10.2025 und läuft auf unbestimmte Zeit.",
    notice: "Für den Mieter gilt die gesetzliche Kündigungsfrist von drei Monaten (§ 573c BGB).",
    deposit: "Die Mietsicherheit beträgt 1.440,00 EUR.",
  },
  nk: {
    pay: "Bitte überweisen Sie den Nachzahlungsbetrag von 184,30 EUR bis zum 09.10.2026",
    period: "Abrechnungszeitraum 01.10.2025 bis 31.12.2025",
    total: "Nachzahlung",
    receipts: "Die Belege können Sie nach vorheriger Terminvereinbarung in unserer Geschäftsstelle einsehen.",
  },
  phone: {
    start: "Vertragsbeginn: 15.11.2024",
    term: "Mindestvertragslaufzeit: 24 Monate",
    price: "Monatlicher Grundpreis: 34,99 EUR",
    notice: "Kündigungsfrist: 1 Monat zum Ende der Mindestvertragslaufzeit, danach jederzeit mit einer Frist von einem Monat.",
    concluded: "Vertragsschluss: 15.10.2024",
  },
  gymPrice: {
    change: "Ab dem 01.11.2026 beträgt Ihr Monatsbeitrag 32,90 EUR statt bisher 29,90 EUR.",
    objection: "Sie können der Anpassung innerhalb von vier Wochen nach Zugang dieses Schreibens widersprechen.",
  },
  gym: {
    start: "Beginn der Mitgliedschaft: 01.03.2025",
    fee: "Monatsbeitrag: 29,90 EUR",
    renewal: "verlängert sich die Mitgliedschaft auf unbestimmte Zeit und ist jederzeit mit einer Frist von einem Monat kündbar",
  },
  power: {
    start: "Lieferbeginn: 01.10.2025",
    term: "Erstlaufzeit: 12 Monate",
    abschlag: "Monatlicher Abschlag: 48,00 EUR, fällig jeweils zum 15. des Monats",
    notice: "Nach Ablauf der Erstlaufzeit ist der Vertrag mit einer Frist von einem Monat kündbar.",
  },
  liability: {
    renew: "verlängert sich der Vertrag um jeweils ein Jahr, wenn er nicht spätestens drei Monate vor Ablauf gekündigt wird",
    premium: "Jahresbeitrag: 59,90 EUR, fällig jeweils zum 01.12.",
    start: "Versicherungsbeginn: 01.12.2024",
  },
  bkk: {
    amount: "Ab dem 01.10.2026 beträgt Ihr monatlicher Beitrag zur Kranken- und Pflegeversicherung 142,86 EUR.",
    due: "Der Beitrag ist jeweils bis zum 15. des Monats zu zahlen.",
  },
  rundfunk: {
    due: "Für den Zeitraum 01.10.2026 bis 31.12.2026 wird ein Betrag von 55,08 EUR am 15.11.2026 fällig.",
    iban: "IBAN: DE57 1234 8900 0055 0818 36",
  },
  abh: {
    valid: "Ihre Aufenthaltserlaubnis nach § 16b AufenthG ist gültig bis zum 30.11.2026.",
    appt: "Mittwoch, 14.10.2026, 10:30 Uhr",
    bring: "Bitte bringen Sie mit: gültigen Reisepass, ein aktuelles biometrisches Lichtbild, Immatrikulationsbescheinigung, Nachweis über die Krankenversicherung und Nachweis über die Sicherung des Lebensunterhalts.",
    fee: "Die Gebühr beträgt 93,00 EUR und ist bei der Vorsprache zu zahlen.",
  },
  passport: {
    expiry: "10 FEB 2027",
  },
  uni: {
    amount: "Der Semesterbeitrag für das Sommersemester 2027 beträgt 312,40 EUR",
    due: "Bitte überweisen Sie den Betrag bis spätestens 15.01.2027.",
    ticket: "davon Deutschlandsemesterticket 176,40 EUR",
    late: "wird eine Säumnisgebühr von 20,00 EUR erhoben",
  },
  job: {
    term: "Das Arbeitsverhältnis beginnt am 01.04.2025 und ist befristet bis zum 31.03.2027.",
    hours: "Die regelmäßige wöchentliche Arbeitszeit beträgt 20 Stunden.",
    wage: "Stundenlohn: 16,50 EUR brutto",
  },
  payslip: {
    net: "Auszahlungsbetrag 1.262,14 EUR",
    gross: "Gesamtbrutto 1.386,00 EUR",
  },
  tmInvoice: {
    due: "Zahlbar ohne Abzug bis zum 03.09.2026.",
    total: "Rechnungsbetrag 89,99 EUR",
  },
  tmDunning: {
    pay: "Bitte überweisen Sie den Gesamtbetrag von 94,99 EUR bis zum 30.09.2026.",
    threat: "Andernfalls müssen wir die Forderung an ein Inkassounternehmen übergeben.",
    fee: "Mahngebühr 5,00 EUR",
  },
  dentist: {
    appt: "am Donnerstag, 08.10.2026 um 09:15 Uhr",
    cancel: "sagen Sie bitte mindestens 24 Stunden vorher ab",
  },
  library: {
    pay: "Bitte geben Sie die Medien zurück und begleichen Sie die Gebühr von 4,50 EUR bis zum 02.10.2026.",
  },
  dticket: {
    price: "Preis: 63,00 EUR monatlich",
    cancel: "Die Kündigung muss bis zum 10. eines Monats zum Monatsende bei uns eingehen.",
  },
  parking: {
    pay: "Bitte zahlen Sie das Verwarnungsgeld innerhalb einer Woche nach Zugang dieses Schreibens.",
    amount: "Verwarnungsgeld: 30,00 EUR",
    when: "am 17.09.2026 um 14:42 Uhr",
  },
  scholarship: {
    report: "Please submit your progress report (max. 2 pages) and your transcript of records by 15 December 2026",
    stipend: "Your monthly stipend of EUR 450 will continue until 31 August 2027.",
    consequence: "Missing the deadline may lead to a suspension of payments.",
  },
  bank: {
    fee: "beträgt der monatliche Kontoführungspreis für Ihr Girokonto 6,90 EUR (bisher 4,90 EUR)",
    consent: "benötigen wir Ihre ausdrückliche Zustimmung bis zum 30.11.2026",
  },
  // New-mail tray
  court: {
    title: "Mahnbescheid",
    claim: "Hauptforderung: Abonnement-Entgelte 01/2022 – 12/2022 · 59,88 EUR",
    period: "Sie können binnen zwei Wochen seit der Zustellung dieses Bescheids Widerspruch erheben.",
    warning: "Nach Ablauf dieser Frist kann der Antragsteller einen Vollstreckungsbescheid erwirken und aus diesem die Zwangsvollstreckung betreiben.",
    unchecked: "Das Gericht hat nicht geprüft, ob dem Antragsteller der geltend gemachte Anspruch zusteht.",
    total: "Gesamtbetrag 111,88 EUR",
  },
  dismissal: {
    notice: "hiermit kündigen wir das mit Ihnen bestehende Arbeitsverhältnis fristgerecht zum 31.10.2026.",
    register: "Wir weisen Sie darauf hin, dass Sie verpflichtet sind, sich unverzüglich bei der Agentur für Arbeit arbeitsuchend zu melden (§ 38 Abs. 1 SGB III).",
  },
  power2: {
    price: "Ihr Arbeitspreis steigt von 32,10 Cent/kWh auf 34,90 Cent/kWh (brutto).",
    abschlag: "Ihr monatlicher Abschlag erhöht sich damit ab November von 48,00 EUR auf 55,00 EUR.",
    right: "Die Kündigung muss bis zum 31.10.2026 in Textform bei uns eingehen.",
    effective: "zum 01.11.2026",
  },
  tax: {
    date: "Datum 15.09.2026",
    refund: "Erstattung 324,00 EUR",
    laptop: "Die geltend gemachten Aufwendungen für Arbeitsmittel (Laptop, 1.049,00 EUR) wurden nicht berücksichtigt",
    remedy: "Der Bescheid kann mit dem Einspruch angefochten werden.",
    period: "Die Frist für die Einlegung des Einspruchs beträgt einen Monat.",
    delivery: "gilt die Bekanntgabe mit dem vierten Tag nach Aufgabe zur Post als bewirkt",
    form: "Der Einspruch ist beim Finanzamt Musterstadt schriftlich einzureichen, diesem elektronisch zu übermitteln oder dort zur Niederschrift zu erklären.",
  },
  scam: {
    pay: "Zahlen Sie den Betrag innerhalb von 3 Tagen",
    iban: "IBAN: LT71 7300 0101 2345 6789",
    threat: "Andernfalls wird die Zwangsvollstreckung eingeleitet und Ihr Konto gepfändet.",
    amount: "mit 210,00 EUR im Rückstand",
  },
} as const;

const sender = (s: string) => `${s}`;

export const LETTERS: Record<string, LetterSpec> = {
  doc_lease: {
    brand: { name: "Wohnbau Musterstadt eG", color: "#1f5f8b", tagline: "Genossenschaftlich wohnen seit 1921", mark: "square" },
    senderLine: sender("Wohnbau Musterstadt eG · Hafenstraße 4 · 12345 Musterstadt"),
    recipient: RECIPIENT,
    info: [
      ["Datum", "15.09.2025"],
      ["Mieternummer", "12-0412-07"],
      ["Objekt", "Beispielweg 5, Whg. 12"],
    ],
    pages: [
      {
        subject: "Mietvertrag über Wohnraum",
        blocks: [
          { text: "§ 1 Mietsache", bold: true },
          "Vermietet wird die Wohnung Nr. 12, 2. OG links, Beispielweg 5, 12345 Musterstadt (1 Zimmer, Küche, Bad, ca. 34 m²).",
          { text: "§ 2 Mietzeit", bold: true },
          Q.lease.start,
          { text: "§ 3 Miete", bold: true },
          `${Q.lease.rent} (Grundmiete 480,00 EUR, Vorauszahlung Betriebskosten 160,00 EUR).`,
          { text: "§ 4 Zahlung", bold: true },
          `Die Miete ist monatlich im Voraus, ${Q.lease.due}, auf das unten genannte Konto zu zahlen.`,
          { text: "§ 5 Kündigung", bold: true },
          `Die Kündigung bedarf der Schriftform. ${Q.lease.notice}`,
          { text: "§ 6 Mietsicherheit", bold: true },
          Q.lease.deposit,
        ],
      },
    ],
    footer: ["Wohnbau Musterstadt eG · Genossenschaftsregister GnR 118 · IBAN DE05 1234 5600 0004 4556 60"],
  },

  doc_nebenkosten: {
    brand: { name: "Wohnbau Musterstadt eG", color: "#1f5f8b", tagline: "Genossenschaftlich wohnen seit 1921", mark: "square" },
    senderLine: "Wohnbau Musterstadt eG · Hafenstraße 4 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "09.09.2026"],
      ["Mieternummer", "12-0412-07"],
      ["Ansprechpartnerin", "Frau Beispiel"],
    ],
    pages: [
      {
        subject: "Betriebskostenabrechnung 2025 – Wohnung Nr. 12",
        blocks: [
          "Sehr geehrte Frau Rivera, sehr geehrter Herr Rivera,",
          `anbei erhalten Sie die Betriebskostenabrechnung für den ${Q.nk.period}. Ihre Kosten übersteigen die geleisteten Vorauszahlungen.`,
          {
            rows: [
              ["Summe Ihrer Kosten", "664,30 EUR"],
              ["abzüglich Vorauszahlungen (3 × 160,00 EUR)", "480,00 EUR"],
              ["Nachzahlung", "184,30 EUR"],
            ],
            boldLast: true,
          },
          `${Q.nk.pay} auf unser Konto. Verwendungszweck: MV-2025-0412 NK 2025`,
          Q.nk.receipts,
          "Die Aufstellung der einzelnen Kostenarten finden Sie auf Seite 2.",
          "Mit freundlichen Grüßen",
          "Ihre Wohnbau Musterstadt eG",
        ],
      },
      {
        subject: "Aufstellung der Betriebskosten 01.10.2025 – 31.12.2025",
        blocks: [
          {
            rows: [
              ["Heizkosten (verbrauchsabhängig)", "298,40 EUR"],
              ["Wasser / Abwasser", "112,70 EUR"],
              ["Müllabfuhr", "48,20 EUR"],
              ["Hausreinigung", "61,00 EUR"],
              ["Grundsteuer", "54,80 EUR"],
              ["Gebäudeversicherung", "39,60 EUR"],
              ["Allgemeinstrom", "18,40 EUR"],
              ["Hauswart", "31,20 EUR"],
              ["Summe", "664,30 EUR"],
            ],
            boldLast: true,
          },
          "Verteilerschlüssel: Wohnfläche 34,0 m² von 1.020,0 m²; Heizkosten nach Verbrauch (Heizkostenverordnung).",
        ],
      },
    ],
    footer: ["Wohnbau Musterstadt eG · IBAN DE05 1234 5600 0004 4556 60 · BIC MUSTDEXX"],
  },

  doc_phone: {
    brand: { name: "FunkNetz Mobil", color: "#d4145a", tagline: "Netz, das mitdenkt.", mark: "wave" },
    senderLine: "FunkNetz Mobil GmbH · Postfach 10 20 30 · 12340 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "15.10.2024"],
      ["Kundennummer", "7700 4412 09"],
      ["Tarif", "FunkNetz Allnet L"],
    ],
    pages: [
      {
        subject: "Ihre Vertragszusammenfassung",
        blocks: [
          "Hallo Sam Rivera, willkommen bei FunkNetz! Hier finden Sie die wichtigsten Daten Ihres Vertrags.",
          {
            rows: [
              ["Tarif", "Allnet L – 20 GB"],
              ["Vertragsschluss", "15.10.2024"],
              ["Vertragsbeginn", "15.11.2024"],
            ],
          },
          Q.phone.concluded,
          Q.phone.start,
          Q.phone.term,
          Q.phone.price,
          Q.phone.notice,
          "Sie können Ihren Vertrag jederzeit bequem über den Kündigungsbutton in „Mein FunkNetz“ kündigen.",
        ],
      },
    ],
    footer: ["FunkNetz Mobil GmbH · Amtsgericht Musterstadt HRB 55123"],
  },

  doc_gym: {
    brand: { name: "FitWell Studios", color: "#e4572e", tagline: "Stark in Musterstadt", mark: "bars" },
    senderLine: "FitWell Studios · Lindenallee 22 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "01.03.2025"],
      ["Mitgliedsnummer", "FW-20931"],
    ],
    pages: [
      {
        subject: "Mitgliedschaftsvertrag „Flex“",
        blocks: [
          Q.gym.start,
          "Erstlaufzeit: 12 Monate",
          Q.gym.fee,
          `Nach Ablauf der Erstlaufzeit ${Q.gym.renewal}.`,
          "Die Kündigung ist in Textform (z. B. E-Mail) oder über unsere Website möglich.",
        ],
      },
    ],
  },

  doc_power: {
    brand: { name: "Stadtwerke Musterstadt", color: "#0b7a53", tagline: "Energie für Musterstadt", mark: "circle" },
    senderLine: "Stadtwerke Musterstadt · Energieplatz 1 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "20.09.2025"],
      ["Kundennummer", "300 512 877"],
      ["Zählernummer", "1ESY1160 4471"],
    ],
    pages: [
      {
        subject: "Vertragsbestätigung – MusterStrom Natur",
        blocks: [
          "Vielen Dank für Ihren Auftrag. Wir bestätigen Ihren Stromliefervertrag:",
          Q.power.start,
          Q.power.term,
          "Arbeitspreis: 32,10 Cent/kWh · Grundpreis: 11,90 EUR/Monat",
          Q.power.abschlag,
          Q.power.notice,
        ],
      },
    ],
    footer: ["Stadtwerke Musterstadt GmbH · IBAN DE15 3705 0198 0001 2345 67"],
  },

  doc_liability: {
    brand: { name: "Muster Versicherung", color: "#243b6b", tagline: "Sicher. Seit 1899.", mark: "shield" },
    senderLine: "Muster Versicherung AG · Versicherungsallee 9 · 12349 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "20.11.2024"],
      ["Versicherungsnummer", "PHV-4471-2290"],
    ],
    pages: [
      {
        subject: "Versicherungsschein – Privathaftpflicht Single",
        blocks: [
          Q.liability.start,
          "Versicherungsdauer: 1 Jahr. Danach",
          `${Q.liability.renew}.`,
          "Deckungssumme: 10.000.000 EUR pauschal für Personen-, Sach- und Vermögensschäden.",
          Q.liability.premium,
        ],
      },
    ],
    footer: ["Muster Versicherung AG · IBAN DE84 5205 0353 0000 5544 33"],
  },

  doc_bkk: {
    brand: { name: "Muster BKK", color: "#0096a0", tagline: "Die Krankenkasse für Musterstadt", mark: "circle" },
    senderLine: "Muster BKK · Gesundheitsweg 5 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "10.09.2026"],
      ["Versichertennummer", "R482019379"],
    ],
    pages: [
      {
        subject: "Ihre Beiträge als Studentin / Student ab 01.10.2026",
        blocks: [
          "Guten Tag Sam Rivera,",
          "zum Wintersemester 2026/27 ändern sich die Beiträge für die studentische Kranken- und Pflegeversicherung.",
          Q.bkk.amount,
          Q.bkk.due,
          "Wenn Sie uns ein SEPA-Lastschriftmandat erteilen, buchen wir den Beitrag automatisch ab.",
        ],
      },
    ],
    footer: ["Muster BKK · Körperschaft des öffentlichen Rechts · IBAN DE46 2004 0000 0628 3746 50"],
  },

  doc_rundfunk: {
    brand: { name: "Beitragsservice Musterstadt", color: "#5a5a5a", tagline: "Rundfunkbeitrag", mark: "eagle" },
    senderLine: "Beitragsservice Musterstadt · 12340 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "01.09.2026"],
      ["Beitragsnummer", "457 812 309"],
    ],
    pages: [
      {
        subject: "Zahlungsaufforderung Rundfunkbeitrag",
        blocks: [
          "Guten Tag Sam Rivera,",
          Q.rundfunk.due,
          "Bitte überweisen Sie den Betrag unter Angabe Ihrer Beitragsnummer.",
          { text: `Empfänger: Beitragsservice Musterstadt · ${Q.rundfunk.iban}`, size: 20 },
          "Tipp: Mit einem SEPA-Lastschriftmandat müssen Sie an nichts mehr denken.",
        ],
      },
    ],
  },

  doc_abh: {
    brand: { name: "Stadt Musterstadt", color: "#7a1f2b", tagline: "Ausländerbehörde", mark: "eagle", serif: true },
    senderLine: "Stadt Musterstadt · Ausländerbehörde · Rathausplatz 1 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "21.09.2026"],
      ["Aktenzeichen", "ABH-2026-18841"],
      ["Zimmer", "2.14"],
    ],
    pages: [
      {
        subject: "Verlängerung Ihrer Aufenthaltserlaubnis – Einladung zur Vorsprache",
        blocks: [
          "Sehr geehrte Frau Rivera, sehr geehrter Herr Rivera,",
          Q.abh.valid,
          "Für die Verlängerung haben wir für Sie folgenden Termin reserviert:",
          { text: `${Q.abh.appt}, Rathausplatz 1, Raum 2.14`, bold: true },
          Q.abh.bring,
          Q.abh.fee,
          "Sollten Sie den Termin nicht wahrnehmen können, teilen Sie uns dies bitte rechtzeitig mit.",
          "Mit freundlichen Grüßen · Im Auftrag",
        ],
      },
    ],
  },

  doc_passport: {
    brand: { name: "Republic of Examplia", color: "#3d5a80" },
    photo: true,
    pages: [],
    idCard: {
      title: "REPUBLIC OF EXAMPLIA",
      subtitle: "PASSPORT · PASSEPORT · SPECIMEN",
      fields: [
        ["Surname", "RIVERA"],
        ["Given names", "SAM"],
        ["Nationality", "EXAMPLIAN"],
        ["Date of birth", "03 MAR 2000"],
        ["Date of issue", "11 FEB 2017"],
        ["Date of expiry", Q.passport.expiry],
        ["Passport no.", "X1234567"],
        ["Authority", "MINISTRY OF INTERIOR"],
      ],
    },
  },

  doc_uni: {
    brand: { name: "Hochschule Musterstadt", color: "#4b2e83", tagline: "University of Applied Sciences", mark: "square", serif: true },
    senderLine: "Hochschule Musterstadt · Studierendenservice · Campusallee 1 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "22.09.2026"],
      ["Matrikelnummer", "2231847"],
    ],
    pages: [
      {
        subject: "Rückmeldung zum Sommersemester 2027",
        blocks: [
          "Liebe Studierende, lieber Studierender,",
          `${Q.uni.amount} (${Q.uni.ticket}, Studierendenwerk 96,00 EUR, Studierendenschaft 40,00 EUR).`,
          Q.uni.due,
          `Erfolgt die Zahlung nicht fristgerecht, ${Q.uni.late}; ohne Rückmeldung droht die Exmatrikulation.`,
          { text: "Empfänger: Hochschule Musterstadt · IBAN DE10 1234 5600 0007 7002 20 · Verwendungszweck: 2231847 SoSe27", size: 19 },
        ],
      },
    ],
  },

  doc_job: {
    brand: { name: "Muster Tech GmbH", color: "#1d6fe0", tagline: "Software für Menschen", mark: "square" },
    senderLine: "Muster Tech GmbH · Innovationsring 17 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "15.03.2025"],
      ["Personalnummer", "WS-0417"],
    ],
    pages: [
      {
        subject: "Arbeitsvertrag für Werkstudierende",
        blocks: [
          Q.job.term,
          Q.job.hours,
          Q.job.wage,
          "Die Tätigkeit erfolgt im Bereich Softwareentwicklung (Frontend).",
          "Kündigung: Beide Seiten können mit einer Frist von vier Wochen zum 15. oder zum Ende eines Kalendermonats kündigen.",
        ],
      },
    ],
  },

  doc_payslip: {
    brand: { name: "Muster Tech GmbH", color: "#1d6fe0", tagline: "Entgeltabrechnung", mark: "square" },
    recipient: RECIPIENT,
    info: [
      ["Abrechnungsmonat", "August 2026"],
      ["Personalnummer", "WS-0417"],
      ["Steuer-ID", "57 216 480 354"],
      ["SV-Nummer", "65 140300 R 005"],
    ],
    pages: [
      {
        subject: "Entgeltabrechnung August 2026",
        blocks: [
          {
            rows: [
              ["84,0 Std. × 16,50 EUR", "1.386,00 EUR"],
              ["Gesamtbrutto 1.386,00 EUR", ""],
              ["Lohnsteuer", "0,00 EUR"],
              ["Rentenversicherung (9,3 %)", "−128,90 EUR"],
              ["Kranken-/Pflegeversicherung", "0,00 EUR"],
              ["Auszahlungsbetrag 1.262,14 EUR", ""],
            ],
          },
          "Überweisung auf DE31 7601 0085 0234 5678 12 am 31.08.2026.",
        ],
      },
    ],
  },

  doc_tm_invoice: {
    brand: { name: "TechMarkt", color: "#f28c00", tagline: "Online-Shop für Technik", mark: "square" },
    senderLine: "TechMarkt Online GmbH · Handelsstraße 50 · 12341 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "20.08.2026"],
      ["Rechnungsnummer", "RE-2026-084213"],
      ["Bestellnummer", "4711-2026"],
    ],
    pages: [
      {
        subject: "Rechnung RE-2026-084213",
        blocks: [
          {
            rows: [
              ["1 × USB-C Dockingstation Pro", "89,99 EUR"],
              ["Versand", "0,00 EUR"],
              ["Rechnungsbetrag 89,99 EUR", ""],
            ],
          },
          "Enthaltene MwSt. (19 %): 14,37 EUR",
          Q.tmInvoice.due,
          "Bitte geben Sie die Rechnungsnummer als Verwendungszweck an.",
        ],
      },
    ],
    footer: ["TechMarkt Online GmbH · IBAN DE70 1234 7800 0048 2130 00"],
  },

  doc_tm_dunning: {
    brand: { name: "TechMarkt", color: "#f28c00", tagline: "Online-Shop für Technik", mark: "square" },
    senderLine: "TechMarkt Online GmbH · Handelsstraße 50 · 12341 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "18.09.2026"],
      ["Rechnungsnummer", "RE-2026-084213"],
      ["Kundennummer", "TM-883120"],
    ],
    pages: [
      {
        subject: "Zahlungserinnerung",
        blocks: [
          "Guten Tag Sam Rivera,",
          "sicherlich haben Sie übersehen, dass unsere Rechnung RE-2026-084213 vom 20.08.2026 noch offen ist.",
          {
            rows: [
              ["Offener Rechnungsbetrag", "89,99 EUR"],
              [Q.tmDunning.fee, ""],
              ["Gesamtbetrag", "94,99 EUR"],
            ],
            boldLast: true,
          },
          Q.tmDunning.pay,
          Q.tmDunning.threat,
          "Sollten Sie die Zahlung bereits veranlasst haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.",
        ],
      },
    ],
    footer: ["TechMarkt Online GmbH · IBAN DE70 1234 7800 0048 2130 00"],
  },

  doc_dentist: {
    brand: { name: "Zahnarztpraxis Dr. Muster", color: "#2a9d8f", tagline: "Lindenallee 3 · Musterstadt", mark: "circle" },
    recipient: RECIPIENT,
    info: [["Datum", "24.09.2026"]],
    pages: [
      {
        subject: "Terminerinnerung",
        blocks: [
          "Liebe Patientin, lieber Patient,",
          `wir erinnern Sie an Ihren Termin zur Kontrolle und professionellen Zahnreinigung ${Q.dentist.appt}.`,
          "Bitte bringen Sie Ihre Versichertenkarte mit.",
          `Falls Sie den Termin nicht wahrnehmen können, ${Q.dentist.cancel}.`,
          "Ihr Praxisteam",
        ],
      },
    ],
  },

  doc_library: {
    brand: { name: "Stadtbibliothek Musterstadt", color: "#8a5a00", tagline: "Lesen · Lernen · Treffen", mark: "bars" },
    senderLine: "Stadtbibliothek Musterstadt · Marktplatz 2 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "25.09.2026"],
      ["Ausweisnummer", "BIB-0098812"],
    ],
    pages: [
      {
        subject: "Mahnung – Leihfrist überschritten",
        blocks: [
          "Die Leihfrist für folgende Medien ist abgelaufen:",
          { text: "„Deutsch im Alltag B2“ · „Steuern leicht gemacht“", indent: 20 },
          Q.library.pay,
          "Solange Gebühren offen sind, ist Ihr Ausweis für weitere Ausleihen gesperrt.",
        ],
      },
    ],
  },

  doc_dticket: {
    brand: { name: "Musterstadt Verkehrsbetriebe", color: "#c1121f", tagline: "Bus & Bahn", mark: "wave" },
    senderLine: "MSV · Bahnhofsplatz 3 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "20.01.2026"],
      ["Kundennummer", "D-448120"],
    ],
    pages: [
      {
        subject: "Ihr Deutschlandticket-Abo",
        blocks: [
          "Abo-Beginn: 01.02.2026",
          Q.dticket.price,
          `Das Abonnement ist monatlich kündbar. ${Q.dticket.cancel}`,
          "Der Betrag wird jeweils zum Monatsanfang per SEPA-Lastschrift eingezogen.",
        ],
      },
    ],
  },

  doc_parking: {
    brand: { name: "Stadt Musterstadt", color: "#7a1f2b", tagline: "Ordnungsamt · Verkehrsüberwachung", mark: "eagle", serif: true },
    photo: true,
    senderLine: "Stadt Musterstadt · Ordnungsamt · Rathausplatz 1 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "22.09.2026"],
      ["Aktenzeichen", "OA-VW-2026-55012"],
    ],
    pages: [
      {
        subject: "Verwarnung mit Verwarnungsgeld",
        blocks: [
          `Ihnen wird zur Last gelegt, ${Q.parking.when} in Musterstadt, Bahnhofstraße 8, mit dem Carsharing-Fahrzeug MS-CS 2026 im eingeschränkten Halteverbot geparkt zu haben.`,
          { text: Q.parking.amount, bold: true },
          Q.parking.pay,
          "Wenn Sie nicht fristgerecht zahlen, wird ein Bußgeldverfahren eingeleitet. Dabei entstehen zusätzliche Gebühren und Auslagen.",
          { text: "Empfänger: Stadtkasse Musterstadt · IBAN DE51 1234 5600 0000 1000 17", size: 19 },
        ],
      },
    ],
  },

  doc_gym_price: {
    brand: { name: "FitWell Studios", color: "#e4572e", tagline: "Stark in Musterstadt", mark: "bars" },
    senderLine: "FitWell Studios · Lindenallee 22 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "14.09.2026"],
      ["Mitgliedsnummer", "FW-20931"],
    ],
    pages: [
      {
        subject: "Anpassung Ihres Monatsbeitrags",
        blocks: [
          "Liebes Mitglied,",
          `wir modernisieren unsere Geräte und verlängern die Öffnungszeiten. ${Q.gymPrice.change}`,
          Q.gymPrice.objection,
          "Ihr FitWell-Team",
        ],
      },
    ],
  },

  doc_scholarship: {
    brand: { name: "Global Futures", color: "#0f766e", tagline: "Scholarship Programme", mark: "circle" },
    recipient: RECIPIENT,
    info: [
      ["Date", "14 September 2026"],
      ["Scholar ID", "GF-2025-0311"],
    ],
    pages: [
      {
        subject: "Renewal of your scholarship 2026/27",
        blocks: [
          "Dear Sam Rivera,",
          "Congratulations on the renewal of your scholarship for the academic year 2026/27.",
          Q.scholarship.stipend,
          `${Q.scholarship.report} via the scholar portal.`,
          Q.scholarship.consequence,
          "Kind regards, The Global Futures team",
        ],
      },
    ],
  },

  doc_bank: {
    brand: { name: "Musterbank", color: "#0a3d62", tagline: "Ihre Bank in Musterstadt", mark: "square" },
    senderLine: "Musterbank AG · Bankplatz 1 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "16.09.2026"],
      ["Konto", SAM.iban],
    ],
    pages: [
      {
        subject: "Neue Preise für Ihr Girokonto ab 01.12.2026",
        blocks: [
          "Guten Tag Sam Rivera,",
          `ab dem 01.12.2026 ${Q.bank.fee}.`,
          `Damit die Änderung wirksam wird, ${Q.bank.consent}. Sie können der Änderung bequem im Online-Banking zustimmen.`,
          "Stimmen Sie nicht zu, können wir den Kontovertrag unter Einhaltung einer Frist von zwei Monaten kündigen.",
        ],
      },
    ],
  },

  // ---------------------------------------------------------------- New-mail tray
  doc_mahnbescheid: {
    brand: { name: "Amtsgericht Hagen", color: "#8a6d1f", tagline: "Zentrales Mahngericht · 58084 Hagen", mark: "eagle", serif: true },
    senderLine: "Amtsgericht Hagen · Zentrales Mahngericht · 58084 Hagen",
    recipient: RECIPIENT,
    info: [
      ["Geschäftsnummer", "26-4471902-0-3"],
      ["Datum", "23.09.2026"],
    ],
    pages: [
      {
        subject: Q.court.title,
        blocks: [
          "Antragsteller: Streamline Media GmbH, Medienallee 4, 50667 Köln",
          {
            rows: [
              [Q.court.claim, ""],
              ["Zinsen und Nebenforderungen", "16,00 EUR"],
              ["Kosten dieses Verfahrens", "36,00 EUR"],
              [Q.court.total, ""],
            ],
            boldLast: true,
          },
          Q.court.unchecked,
          `${Q.court.period} Soweit Sie den Anspruch für begründet halten, zahlen Sie den Gesamtbetrag an den Antragsteller.`,
          Q.court.warning,
          "Für den Widerspruch soll der beigefügte Vordruck verwendet werden; er ist auch online unter www.online-mahnantrag.de möglich.",
        ],
      },
    ],
    footer: ["Zugestellt durch die Post – bitte das Datum auf dem gelben Umschlag beachten."],
  },

  doc_dismissal: {
    brand: { name: "Muster Tech GmbH", color: "#3056d3", tagline: "Software für Musterstadt", mark: "bars" },
    senderLine: "Muster Tech GmbH · Innovationsring 17 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "25.09.2026"],
      ["Personalnummer", "WS-0417"],
    ],
    pages: [
      {
        subject: "Kündigung Ihres Arbeitsverhältnisses",
        blocks: [
          "Sehr geehrte*r Sam Rivera,",
          Q.dismissal.notice,
          "Ihren restlichen Urlaub gewähren wir Ihnen bis zum Ende des Arbeitsverhältnisses. Ein Arbeitszeugnis erhalten Sie mit gesonderter Post.",
          Q.dismissal.register,
          "Mit freundlichen Grüßen",
          "Muster Tech GmbH · Personalabteilung",
        ],
      },
    ],
  },

  doc_power_price: {
    brand: { name: "Stadtwerke Musterstadt", color: "#0b7a53", tagline: "Energie für Musterstadt", mark: "circle" },
    senderLine: "Stadtwerke Musterstadt · Energieplatz 1 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "24.09.2026"],
      ["Kundennummer", "300 512 877"],
    ],
    pages: [
      {
        subject: "Preisanpassung zum 01.11.2026 – MusterStrom Natur",
        blocks: [
          "Guten Tag Sam Rivera,",
          `gestiegene Netzentgelte und Beschaffungskosten machen eine Anpassung unserer Preise ${Q.power2.effective} erforderlich. ${Q.power2.price} Der Grundpreis bleibt unverändert.`,
          Q.power2.abschlag,
          `Sie haben das Recht, den Vertrag ohne Einhaltung einer Kündigungsfrist zum Zeitpunkt des Wirksamwerdens der Preisänderung zu kündigen. ${Q.power2.right}`,
          "Wir würden uns freuen, Sie weiterhin mit Energie zu versorgen.",
        ],
      },
    ],
    footer: ["Stadtwerke Musterstadt GmbH · IBAN DE15 3705 0198 0001 2345 67"],
  },

  doc_tax: {
    brand: { name: "Finanzamt Musterstadt", color: "#1b3a5c", tagline: "Steuerring 10 · 12345 Musterstadt", mark: "eagle", serif: true },
    photo: true,
    senderLine: "Finanzamt Musterstadt · Steuerring 10 · 12345 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Steuernummer", "331/5012/4471"],
      ["Datum", "15.09.2026"],
    ],
    pages: [
      {
        subject: "Bescheid für 2025 über Einkommensteuer",
        blocks: [
          `${Q.tax.date} · Festsetzung`,
          {
            rows: [
              ["Einkommensteuer", "412,00 EUR"],
              ["Solidaritätszuschlag", "0,00 EUR"],
              ["abzüglich Steuerabzug vom Lohn", "736,00 EUR"],
              [Q.tax.refund, ""],
            ],
            boldLast: true,
          },
          "Der Erstattungsbetrag wird auf das Konto DE31 7601 0085 0234 5678 12 überwiesen.",
          { text: "Erläuterungen", bold: true },
          `${Q.tax.laptop}, da ein Nachweis der beruflichen Nutzung fehlt.`,
        ],
      },
      {
        subject: "Rechtsbehelfsbelehrung",
        blocks: [
          `${Q.tax.remedy} ${Q.tax.form}`,
          `${Q.tax.period} Sie beginnt mit Ablauf des Tages, an dem Ihnen dieser Bescheid bekannt gegeben worden ist. Bei Zusendung durch einfachen Brief ${Q.tax.delivery}, es sei denn, dass der Bescheid zu einem späteren Zeitpunkt zugegangen ist.`,
        ],
      },
    ],
    footer: ["Finanzamt Musterstadt · Öffnungszeiten Mo–Fr 8–12 Uhr"],
  },

  doc_scam: {
    brand: { name: "Beitragsservice Musterstadt", color: "#5a5a5a", tagline: "Rundfunkbeitrag · Inkasso", mark: "eagle" },
    senderLine: "BS Inkasso Service · Postfach 4410 · 12340 Musterstadt",
    recipient: RECIPIENT,
    info: [
      ["Datum", "25.09.2026"],
      ["Vorgang", "BS-2026-99812"],
    ],
    pages: [
      {
        subject: "LETZTE MAHNUNG – Rundfunkbeitrag",
        blocks: [
          `Trotz mehrfacher Aufforderung ist Ihr Beitragskonto ${Q.scam.amount}.`,
          `${Q.scam.pay} auf das folgende Konto:`,
          { text: `Empfänger: BS Inkasso Service · ${Q.scam.iban}`, bold: true, size: 20 },
          Q.scam.threat,
          "Eine Ratenzahlung ist ausgeschlossen.",
        ],
      },
    ],
  },
};
