/**
 * Words Claude wrote for the person — a letter's title, summary and explanation, its key-fact labels, its to-dos'
 * titles, Ask's answers — come in the language chosen in Settings (`Profile.language`: Arabic, Turkish, Ukrainian …),
 * inside a page that is `lang="en"`, left to right. Marked with that language's `lang`, a screen reader reads them
 * with its voice and the browser hyphenates them by its rules; Arabic runs right to left (UX audit U6). English
 * needs nothing: it is the page's own language.
 *
 * Words read before the language was changed stay in the old one (Settings: "New explanations are written in …"), and
 * which language a letter was read in isn't stored. So the text itself is asked: words with none of the letters of
 * the language's own script (Arabic, Cyrillic) weren't written in it and get no mark — English read before a change
 * to Arabic stays left to right, its full stop at its end (final check of the fix wave). Right-to-left words take
 * `dir="auto"`: the browser sets their direction from their own first letters.
 */
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/endpoints";
import { qk } from "@/api/hooks";
import { languageCode } from "@/lib/format";

const RIGHT_TO_LEFT: ReadonlySet<string> = new Set(["ar", "fa", "he", "ur"]);

const ARABIC = /\p{Script=Arabic}/u;
const CYRILLIC = /\p{Script=Cyrillic}/u;

/** The letters of a language's own script, where it isn't the Latin one: text with none of them isn't in that language. */
const OWN_SCRIPT: Readonly<Record<string, RegExp>> = {
  ar: ARABIC,
  fa: ARABIC,
  ur: ARABIC,
  he: /\p{Script=Hebrew}/u,
  uk: CYRILLIC,
  ru: CYRILLIC,
};

export interface LangProps {
  lang?: string;
  dir?: "auto";
}

/**
 * `lang` (and `dir="auto"` for a right-to-left language) for `text`, words the model wrote in `language`; nothing for
 * English or none, or when `text` has none of the letters of the language's own script (read before a change of
 * language).
 */
export function langProps(language: string | null | undefined, text: string | null | undefined): LangProps {
  const code = languageCode(language);
  if (!code || code === "en") return {};
  const script = OWN_SCRIPT[code];
  if (script && !script.test(text ?? "")) return {};
  return RIGHT_TO_LEFT.has(code) ? { lang: code, dir: "auto" } : { lang: code };
}

/**
 * The profile's language as a code ("ar"). It never asks for the profile: the app shell has loaded it — until then
 * (and in a test without one) it is `null`.
 */
export function useProfileLanguage(): string | null {
  const { data } = useQuery({ queryKey: qk.profile, queryFn: api.profile, enabled: false });
  return languageCode(data?.language);
}

/** {@link langProps} of the profile's language for `text`, to spread on an element that holds only the model's words (`<p {...lang}>`). */
export function useModelLang(text: string | null | undefined): LangProps {
  return langProps(useProfileLanguage(), text);
}

/**
 * The model's words `text` inline, marked with the profile's language ({@link useModelLang}); in English, the page's
 * own, they go in as they are. `children` show them another way (glossary terms explained); by default as written.
 * Wrap only what the model wrote — never the app's own English around it ("For your tax return:"). A block that
 * holds only the model's words takes {@link useModelLang} itself.
 *
 * @example <ModelText text={fact.label} />
 */
export function ModelText({ text, children = text }: { text: string; children?: ReactNode }) {
  const lang = useModelLang(text);
  return lang.lang ? <span {...lang}>{children}</span> : <>{children}</>;
}
