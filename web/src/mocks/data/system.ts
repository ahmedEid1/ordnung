import type { Activity, AppSettings, DoctorCheck, Health, LLMCallRecord, MailTrayItem, Profile, RuleInfo, TourState, UsageStats } from "@/api/types";
import { SAM, TODAY, ts } from "./constants";

export const HEALTH: Health = {
  version: "0.1.0",
  data_dir: "~/.local/share/ordnung-demo",
  demo: true,
  simulated_today: TODAY,
  today: TODAY,
  backend: "replay",
  claude: { installed: true, version: "2.1.4 (Claude Code)", path: "/usr/local/bin/claude", ok: true, detail: "Signed in with your Claude subscription." },
  rules_last_checked: "2026-09-25",
  checks: [],
};

/** What `GET /api/health?probe=1` ("Run check") lists: the `ordnung doctor` checks. */
export const DEMO_CHECKS: DoctorCheck[] = [
  { id: "claude_cli", label: "Claude Code installed", status: "ok", detail: "/usr/local/bin/claude", fix: null },
  { id: "claude_version", label: "Claude Code version", status: "ok", detail: "2.1.4", fix: null },
  { id: "claude_auth", label: "Claude sign-in", status: "ok", detail: "Signed in (claude.ai)", fix: null },
  { id: "claude_probe", label: "Live test call", status: "ok", detail: "Claude answered.", fix: null },
  { id: "api_key", label: "ANTHROPIC_API_KEY", status: "ok", detail: "Not set — your own Claude login is used.", fix: null },
  { id: "sqlite_fts", label: "Search (SQLite FTS5 + trigram)", status: "ok", detail: "SQLite 3.46.1", fix: null },
  { id: "fonts", label: "Letter fonts", status: "ok", detail: "DejaVu Sans", fix: null },
  { id: "web_ui", label: "Web app", status: "ok", detail: "Built", fix: null },
  { id: "data_dir", label: "Data folder", status: "ok", detail: "~/.local/share/ordnung-demo", fix: null },
  { id: "disk", label: "Disk space", status: "ok", detail: "48.2 GB free", fix: null },
];

export const PROFILE: Profile = {
  name: SAM.name,
  address: `${SAM.street}\n${SAM.city}`,
  email: SAM.email,
  phone: SAM.phone,
  language: "en",
  country: "DE",
  region: "NW",
  timezone: "Europe/Berlin",
  reminder_days: { deadline: [14, 7, 3, 1], payment: [7, 2], appointment: [2, 0], expiry: [90, 30, 7], task: [3], reminder: [0], milestone: [7] },
  postal_buffer_days: 4,
  is_student_visa: true,
  onboarded: true,
};

export const SETTINGS: AppSettings = {
  models: { transcribe: "sonnet", extract: "sonnet", review: "sonnet", ask: "sonnet", draft: "sonnet", brief: "haiku", capture: "haiku", bank: "haiku" },
  concurrency: 2,
  inbox_dir: null,
  ocr: true,
  llm_brief: true,
  llm_review: true,
  demo: true,
  simulated_today: TODAY,
};

export const TOUR: TourState = { active: true, step: 0, completed: false };

export const MAIL_TRAY: MailTrayItem[] = [
  { id: "mail_stadtwerke", filename: "Stadtwerke_Preisanpassung.pdf", sender: "Stadtwerke Musterstadt", subject: "Preisanpassung zum 01.11.2026", kind_hint: "Price change", photo: false, opened: false, doc_id: null },
  { id: "mail_finanzamt", filename: "IMG_2044.jpg", sender: "Finanzamt Musterstadt", subject: "Bescheid für 2025 über Einkommensteuer", kind_hint: "Tax assessment (phone photo)", photo: true, opened: false, doc_id: null },
  { id: "mail_scam", filename: "Letzte_Mahnung_Rundfunk.pdf", sender: "Beitragsservice Musterstadt?", subject: "LETZTE MAHNUNG – Rundfunkbeitrag", kind_hint: "Payment demand", photo: false, opened: false, doc_id: null },
];

/** Which document each tray letter becomes. */
export const TRAY_DOC: Record<string, string> = {
  mail_stadtwerke: "doc_power_price",
  mail_finanzamt: "doc_tax",
  mail_scam: "doc_scam",
};

export const RULES: RuleInfo[] = [
  { id: "ao122_2_4days", title: "Tax letters count as delivered 4 days after posting", citation: "§ 122 Abs. 2 Nr. 1 AO", summary: "A tax decision sent by post counts as delivered on the fourth day after it was posted (three days until 2024), unless it arrived later.", url: "https://www.gesetze-im-internet.de/ao_1977/__122.html", effective_from: "2025-01-01" },
  { id: "ao108_3", title: "Deadlines ending on a weekend or holiday move to the next working day", citation: "§ 108 Abs. 3 AO", summary: "If the end of a period — including the deemed delivery date — falls on a Saturday, Sunday or public holiday, it moves to the next working day.", url: "https://www.gesetze-im-internet.de/ao_1977/__108.html", effective_from: null },
  { id: "ao355_1", title: "Tax objection: one month", citation: "§ 355 Abs. 1 AO", summary: "An Einspruch against a tax decision must be filed within one month after it was delivered.", url: "https://www.gesetze-im-internet.de/ao_1977/__355.html", effective_from: null },
  { id: "vwvfg41", title: "Federal authority letters: 4-day delivery rule", citation: "§ 41 Abs. 2 VwVfG", summary: "Administrative acts sent by post count as delivered on the fourth day after posting.", url: "https://www.gesetze-im-internet.de/vwvfg/__41.html", effective_from: "2025-01-01" },
  { id: "sgbx37", title: "Social-law letters: 4-day delivery rule", citation: "§ 37 Abs. 2 SGB X", summary: "Decisions of social insurers sent by post count as delivered on the fourth day after posting.", url: "https://www.gesetze-im-internet.de/sgb_10/__37.html", effective_from: "2025-01-01" },
  // the engine's ids (ordnung.rules.catalog) for the rules the static demo's receipts share with the app
  { id: "bgb_187_1", title: "The day of the event is not counted", citation: "§ 187 Abs. 1 BGB; § 108 Abs. 1 AO; § 31 Abs. 1 VwVfG; § 26 Abs. 1 SGB X", summary: "When a period starts with an event (a letter arriving, a delivery), that day is not counted; counting starts the next day.", url: "https://www.gesetze-im-internet.de/bgb/__187.html", effective_from: null },
  { id: "bgb_188", title: "When a period ends", citation: "§ 188 Abs. 1, 2 BGB; § 43 Abs. 1 StPO; § 64 Abs. 2 SGG", summary: "A period in days ends on its last day. A period in weeks, months or years ends on the day with the same weekday name or day number as the event day (or, for periods starting at the beginning of a day, on the day before it).", url: "https://www.gesetze-im-internet.de/bgb/__188.html", effective_from: null },
  { id: "bgb_193", title: "Weekend and holiday shift (private law)", citation: "§ 193 BGB", summary: "If a deadline for a declaration or a payment ends on a Saturday, Sunday or public holiday at the place of performance, it moves to the next working day.", url: "https://www.gesetze-im-internet.de/bgb/__193.html", effective_from: null },
  { id: "private_sender_arrival", title: "Letters from companies count from arrival", citation: "§ 130 Abs. 1 BGB", summary: "Deemed delivery (the 4-day rule) applies only to letters from authorities. A letter from a company, landlord, bank or other private sender takes effect when it arrives, so a period in it runs from that day. Without the day it arrived, Ordnung counts from the letter's date, the earliest plausible start.", url: "https://www.gesetze-im-internet.de/bgb/__130.html", effective_from: null },
  { id: "bgb309_9", title: "Consumer contracts since March 2022", citation: "§ 309 Nr. 9 BGB", summary: "Max. 24 months initial term; afterwards the contract runs indefinitely and can be cancelled with at most one month's notice.", url: "https://www.gesetze-im-internet.de/bgb/__309.html", effective_from: "2022-03-01" },
  { id: "tkg56", title: "Phone & internet contracts", citation: "§ 56 TKG", summary: "Max. 24 months minimum term; afterwards cancellable at any time with one month's notice.", url: "https://www.gesetze-im-internet.de/tkg_2021/__56.html", effective_from: "2021-12-01" },
  { id: "bgb312k", title: "Online cancel button", citation: "§ 312k BGB", summary: "Businesses that sell contracts online must offer a cancel button on their website.", url: "https://www.gesetze-im-internet.de/bgb/__312k.html", effective_from: "2022-07-01" },
  { id: "vvg11", title: "Insurance renewals", citation: "§ 11 VVG", summary: "Insurance contracts renew as agreed (usually yearly); notice as written, typically 3 months before the end of the insurance year.", url: "https://www.gesetze-im-internet.de/vvg_2008/__11.html", effective_from: null },
  { id: "sgbv175", title: "Switching statutory health insurance", citation: "§ 175 SGB V", summary: "Minimum membership 12 months; a switch takes effect at the end of the second following month.", url: "https://www.gesetze-im-internet.de/sgb_5/__175.html", effective_from: "2021-01-01" },
  { id: "enwg41_5", title: "Special right to cancel energy contracts after a price change", citation: "§ 41 Abs. 5 EnWG", summary: "When the supplier changes prices, you may cancel without notice with effect from the date of the change.", url: "https://www.gesetze-im-internet.de/enwg_2005/__41.html", effective_from: null },
  { id: "rent573c", title: "Tenant's notice", citation: "§ 573c Abs. 1 BGB", summary: "Notice by the 3rd working day of a month ends the tenancy at the end of the month after next.", url: "https://www.gesetze-im-internet.de/bgb/__573c.html", effective_from: null },
  { id: "bgb556b", title: "Rent is due by the 3rd working day", citation: "§ 556b Abs. 1 BGB", summary: "Rent must be paid in advance, at the latest by the third working day of each month.", url: "https://www.gesetze-im-internet.de/bgb/__556b.html", effective_from: null },
  { id: "aufenthg81_4", title: "Apply for an extension before your permit expires", citation: "§ 81 Abs. 4 AufenthG", summary: "If you apply for an extension before your permit expires, it continues to count as valid until the office decides (Fiktionsbescheinigung).", url: "https://www.gesetze-im-internet.de/aufenthg_2004/__81.html", effective_from: null },
  { id: "postal_buffer", title: "Send-by date", citation: "Ordnung safety policy; § 18 PostG (delivery targets)", summary: "Deadlines are about when a letter arrives, not when it is sent. The post must deliver 95 % of letters by the 3rd and 99 % by the 4th working day after posting, so Ordnung suggests posting 4 business days before the last business day on or before the deadline (0 for online buttons, portals, fax and e-mail where allowed).", url: null, effective_from: null },
];

const d = (date: string, time: string) => ts(date, time);

export const ACTIVITY: Activity[] = [
  { id: 119, ts: d("2026-09-27", "19:02"), kind: "review", message: "Weekly review: 2 new Ideas", ref_type: null, ref_id: null, data: { model: "sonnet", tokens: 9120 } },
  { id: 118, ts: d("2026-09-26", "09:49"), kind: "document.processed", message: "Read “Library: overdue books” (1 page)", ref_type: "document", ref_id: "doc_library", data: { pages: 1, model: "sonnet" } },
  { id: 117, ts: d("2026-09-25", "13:06"), kind: "document.processed", message: "Read “Dentist appointment reminder” (1 page)", ref_type: "document", ref_id: "doc_dentist", data: { pages: 1 } },
  { id: 116, ts: d("2026-09-24", "20:15"), kind: "document.needs_review", message: "“Parking fine” needs you: when did it arrive?", ref_type: "document", ref_id: "doc_parking", data: {} },
  { id: 115, ts: d("2026-09-23", "17:16"), kind: "document.processed", message: "Read “Re-registration for summer semester 2027” (1 page)", ref_type: "document", ref_id: "doc_uni", data: { pages: 1 } },
  { id: 114, ts: d("2026-09-22", "18:06"), kind: "document.processed", message: "Read “Residence permit extension — appointment 14 Oct” (1 page)", ref_type: "document", ref_id: "doc_abh", data: { pages: 1 } },
  { id: 113, ts: d("2026-09-20", "18:00"), kind: "calendar.exported", message: "Exported 14 dates to your calendar", ref_type: null, ref_id: null, data: { count: 14 } },
  { id: 112, ts: d("2026-09-19", "10:33"), kind: "document.processed", message: "Read “TechMarkt payment reminder” — linked to invoice RE-2026-084213", ref_type: "document", ref_id: "doc_tm_dunning", data: { pages: 1 } },
  { id: 111, ts: d("2026-09-17", "18:03"), kind: "document.processed", message: "Read “Musterbank: new account fee” (1 page)", ref_type: "document", ref_id: "doc_bank", data: { pages: 1 } },
  { id: 110, ts: d("2026-09-15", "19:03"), kind: "document.processed", message: "Read “Gym price increase — FitWell” (1 page)", ref_type: "document", ref_id: "doc_gym_price", data: { pages: 1 } },
  { id: 109, ts: d("2026-09-15", "19:00"), kind: "draft.sent", message: "You sent “Bitte um Belegeinsicht” to Wohnbau Musterstadt eG by email", ref_type: "draft", ref_id: "drf_wohnbau", data: {} },
  { id: 108, ts: d("2026-09-12", "11:31"), kind: "document.processed", message: "Read “Health insurance contributions from 1 Oct” (1 page)", ref_type: "document", ref_id: "doc_bkk", data: { pages: 1 } },
  { id: 107, ts: d("2026-09-11", "19:23"), kind: "document.processed", message: "Read “Utility cost statement 2025” (2 pages)", ref_type: "document", ref_id: "doc_nebenkosten", data: { pages: 2 } },
  { id: 106, ts: d("2026-09-03", "08:13"), kind: "document.private", message: "Stored “Payslip August 2026” — read with Claude, marked tax-relevant", ref_type: "document", ref_id: "doc_payslip", data: {} },
];

function call(id: number, date: string, time: string, purpose: string, model: string, inp: number, out: number, cost: number, extra: Partial<LLMCallRecord> = {}): LLMCallRecord {
  return {
    id,
    ts: ts(date, time),
    purpose,
    model,
    backend: "claude_cli",
    duration_ms: Math.round(2000 + out * 18),
    input_tokens: inp,
    output_tokens: out,
    cache_read_tokens: extra.cache_hit ? inp : Math.round(inp * 0.35),
    cache_creation_tokens: 0,
    cost_usd: cost,
    ok: true,
    error: null,
    cache_hit: false,
    doc_ids: [],
    pages_sent: 0,
    bytes_sent: 0,
    ...extra,
  };
}

export const USAGE: UsageStats = {
  calls: 64,
  cache_hits: 13,
  input_tokens: 438_900,
  output_tokens: 41_260,
  cost_usd: 2.91,
  by_purpose: {
    extract: { calls: 26, cache_hits: 9, errors: 0, input_tokens: 281_400, output_tokens: 23_900, cost_usd: 1.72 },
    transcribe: { calls: 6, cache_hits: 0, errors: 0, input_tokens: 51_200, output_tokens: 5_480, cost_usd: 0.44 },
    review: { calls: 4, cache_hits: 0, errors: 0, input_tokens: 36_800, output_tokens: 4_120, cost_usd: 0.23 },
    ask: { calls: 11, cache_hits: 2, errors: 0, input_tokens: 52_600, output_tokens: 4_310, cost_usd: 0.35 },
    draft: { calls: 3, cache_hits: 0, errors: 0, input_tokens: 9_700, output_tokens: 2_050, cost_usd: 0.1 },
    brief: { calls: 14, cache_hits: 2, errors: 0, input_tokens: 7_200, output_tokens: 1_400, cost_usd: 0.07 },
  },
  recent: [
    call(64, "2026-09-27", "19:02", "review", "claude-sonnet-4-6", 9120, 1040, 0.06),
    call(63, "2026-09-27", "07:00", "brief", "claude-haiku-4-5", 520, 96, 0.004),
    call(62, "2026-09-26", "09:49", "extract", "claude-sonnet-4-6", 10_880, 912, 0.066, { doc_ids: ["doc_library"], pages_sent: 1, bytes_sent: 2_140 }),
    call(61, "2026-09-25", "13:06", "extract", "claude-sonnet-4-6", 10_410, 868, 0.061, { doc_ids: ["doc_dentist"], pages_sent: 1, bytes_sent: 1_890 }),
    call(60, "2026-09-24", "20:14", "extract", "claude-sonnet-4-6", 11_020, 1_120, 0.07, { doc_ids: ["doc_parking"], pages_sent: 1, bytes_sent: 2_410 }),
    call(59, "2026-09-24", "18:30", "ask", "claude-sonnet-4-6", 6_900, 420, 0.04, { doc_ids: ["doc_phone"] }),
    call(58, "2026-09-23", "17:15", "extract", "claude-sonnet-4-6", 10_950, 990, 0.067, { doc_ids: ["doc_uni"], pages_sent: 1, bytes_sent: 2_300 }),
    call(57, "2026-09-22", "18:05", "extract", "claude-sonnet-4-6", 11_600, 1_240, 0.074, { doc_ids: ["doc_abh"], pages_sent: 1, bytes_sent: 2_780 }),
    call(56, "2026-09-22", "18:05", "extract", "claude-sonnet-4-6", 11_600, 1_240, 0, { doc_ids: ["doc_abh"], cache_hit: true }),
    call(55, "2026-09-19", "10:31", "extract", "claude-sonnet-4-6", 10_700, 930, 0.064, { doc_ids: ["doc_tm_dunning"], pages_sent: 1, bytes_sent: 2_050 }),
  ],
};

export const BRIEF_TEXT =
  "Good morning, Sam. Two small payments this week: TechMarkt's reminder (94,99 €) is due Wednesday and the library wants 4,50 € by Friday. Please tell me when the parking fine arrived — until then I count from the letter date, so pay by tomorrow to be safe. Next week: FitWell's price increase (object by Tue 6 Oct if you post it), the dentist on Thursday, your phone-contract decision (post by Thu 8 Oct) and the Nebenkosten back payment (184,30 € by Fri 9 Oct).";
