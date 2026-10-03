/**
 * Words Claude wrote for the person — a letter's title, summary and explanation, its key-fact labels, its to-dos'
 * titles, Ask's answers — come in the language chosen in Settings (`Profile.language`: Arabic, Turkish, Ukrainian …),
 * inside a page that is `lang="en"`, left to right. Marked with that language's `lang`, a screen reader reads them
 * with its voice and the browser hyphenates them by its rules; Arabic runs right to left (UX audit U6). English
 * needs nothing: it is the page's own language.
 */
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/endpoints";
import { qk } from "@/api/hooks";
import { languageCode } from "@/lib/format";

const RIGHT_TO_LEFT: ReadonlySet<string> = new Set(["ar", "fa", "he", "ur"]);

export interface LangProps {
  lang?: string;
  dir?: "rtl";
}

/** `lang` (and `dir="rtl"` for a right-to-left language) for words written in `language`; nothing for English or none. */
export function langProps(language: string | null | undefined): LangProps {
  const code = languageCode(language);
  if (!code || code === "en") return {};
  return RIGHT_TO_LEFT.has(code) ? { lang: code, dir: "rtl" } : { lang: code };
}

/**
 * The profile's language as a code ("ar"). It never asks for the profile: the app shell has loaded it — until then
 * (and in a test without one) it is `null`.
 */
export function useProfileLanguage(): string | null {
  const { data } = useQuery({ queryKey: qk.profile, queryFn: api.profile, enabled: false });
  return languageCode(data?.language);
}

/** {@link langProps} of the profile's language, to spread on an element that holds only the model's words (`<p {...lang}>`). */
export function useModelLang(): LangProps {
  return langProps(useProfileLanguage());
}

/**
 * The model's words inline, marked with the profile's language ({@link useModelLang}); in English, the page's own,
 * they go in as they are. Wrap only what the model wrote — never the app's own English around it ("For your tax
 * return:"). A block that holds only the model's words takes {@link useModelLang} itself.
 *
 * @example <ModelText>{fact.label}</ModelText>
 */
export function ModelText({ children }: { children: ReactNode }) {
  const lang = useModelLang();
  return lang.lang ? <span {...lang}>{children}</span> : <>{children}</>;
}
