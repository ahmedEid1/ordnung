/** Options and fixed wording for the first-run wizard (SPEC §1, §14.9, §21). */

export interface Bundesland {
  code: string;
  /** German name, as on letters */
  name: string;
  /** English name, when it differs */
  en?: string;
}

/** All 16 German states with their official two-letter codes (they decide the public holidays). */
export const BUNDESLAENDER: readonly Bundesland[] = [
  { code: "BW", name: "Baden-Württemberg" },
  { code: "BY", name: "Bayern", en: "Bavaria" },
  { code: "BE", name: "Berlin" },
  { code: "BB", name: "Brandenburg" },
  { code: "HB", name: "Bremen" },
  { code: "HH", name: "Hamburg" },
  { code: "HE", name: "Hessen", en: "Hesse" },
  { code: "MV", name: "Mecklenburg-Vorpommern", en: "Mecklenburg-Western Pomerania" },
  { code: "NI", name: "Niedersachsen", en: "Lower Saxony" },
  { code: "NW", name: "Nordrhein-Westfalen", en: "North Rhine-Westphalia" },
  { code: "RP", name: "Rheinland-Pfalz", en: "Rhineland-Palatinate" },
  { code: "SL", name: "Saarland" },
  { code: "SN", name: "Sachsen", en: "Saxony" },
  { code: "ST", name: "Sachsen-Anhalt", en: "Saxony-Anhalt" },
  { code: "SH", name: "Schleswig-Holstein" },
  { code: "TH", name: "Thüringen", en: "Thuringia" },
];

export interface LanguageOption {
  code: string;
  /** the language's own name */
  label: string;
  /** English name (screen readers, hints) */
  en: string;
  dir?: "rtl";
}

/** Languages for explanations and translations (letters to authorities stay German). */
export const LANGUAGES: readonly LanguageOption[] = [
  { code: "en", label: "English", en: "English" },
  { code: "de", label: "Deutsch", en: "German" },
  { code: "ar", label: "العربية", en: "Arabic", dir: "rtl" },
  { code: "tr", label: "Türkçe", en: "Turkish" },
  { code: "uk", label: "Українська", en: "Ukrainian" },
  { code: "es", label: "Español", en: "Spanish" },
  { code: "fr", label: "Français", en: "French" },
];

/**
 * SPEC §1 — use this wording everywhere. The program is called Claude Code ("the Claude program
 * on this computer"), never "the Claude app" (a different product) or "the claude CLI" (jargon).
 */
export const PRIVACY_STATEMENT =
  "Your files and your database stay on this computer. When Claude reads a letter, that letter's text or image is sent to Anthropic through your own Claude account (Claude Code, the Claude program you installed and signed in to). Ordnung has no server, no telemetry and never sees your credentials.";

export const CLAUDE_INSTALL_CMD = "npm install -g @anthropic-ai/claude-code";
export const CLAUDE_LOGIN_CMD = "claude";
export const DEMO_CMD = "ordnung demo";
