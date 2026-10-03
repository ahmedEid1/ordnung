/**
 * Whose words are in which language (UX audit U5, U6, A1, A2): a letter's quotes in the letter's own language,
 * Claude's words in the person's (right to left for Arabic), and the letter's language named as it is.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import type { DocumentDetail, Profile } from "@/api/types";
import { langProps } from "@/components/ui/ModelText";
import { Receipt } from "@/components/ui/Receipt";
import { answerLanguage, CHECK_NOTE_LABEL_DE } from "@/features/ask/AskTurnView";
import { Markdown } from "@/features/ask/Markdown";
import { languageCode, languageName } from "@/lib/format";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { DocumentView } from "./DocumentView";
import { writtenFrom } from "./Explained";
import { makeDetail, makeDoc, makeItem, makeReceipt } from "./fixtures";

beforeEach(() => {
  vi.stubGlobal("fetch", async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
});
afterEach(() => {
  vi.unstubAllGlobals();
});

/** One week from receipt, in words the German word list doesn't know ("innerhalb", "einer", "Woche", "nach"). */
const WEEK_QUOTE = "Zahlung innerhalb einer Woche nach Zugang.";

function clientWith(language: string, detail?: DocumentDetail) {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  qc.setQueryData(qk.profile, { name: "Sam", language } as Profile);
  if (detail) qc.setQueryData(qk.documents.detail(detail.document.id), detail);
  return qc;
}

describe("a letter's language, however its reading named it", () => {
  it("is a two-letter code", () => {
    expect(["de", "DE", "de-DE", "German", "Deutsch", " german "].map(languageCode)).toEqual(["de", "de", "de", "de", "de", "de"]);
    expect(languageCode("Français")).toBe("fr");
    expect(languageCode("Klingon")).toBeNull();
    expect(languageCode(null)).toBeNull();
    expect(languageName("German")).toBe("German");
    expect(languageName("fr")).toBe("French");
  });

  it("is named as it is under the explanation, not 'German' for every letter (A1)", () => {
    expect(writtenFrom("German")).toBe("Written by Claude from the German letter. The letter itself is what counts.");
    expect(writtenFrom("fr")).toBe("Written by Claude from the French letter. The letter itself is what counts.");
    expect(writtenFrom("en")).toBeNull();
    expect(writtenFrom(null)).toBeNull();
  });
});

describe("a quote from a letter (U5)", () => {
  it("is read in the letter's language, also when its words aren't on the German word list", () => {
    renderWithProviders(<Receipt summary="One week after it arrived." confidence="high" quote={{ text: WEEK_QUOTE, language: "German" }} />);
    expect(screen.getByText(WEEK_QUOTE).closest("blockquote")).toHaveAttribute("lang", "de");
    expect(screen.getByText(/What the letter says \(in German/)).toBeInTheDocument();
  });

  it("from an English letter is the page's language, whatever its words look like", () => {
    renderWithProviders(<Receipt summary="By Thu 1 Oct." confidence="high" quote={{ text: "Bitte die Frist beachten: by 1 Oct", language: "en" }} />);
    expect(screen.getByText(/Frist beachten/).closest("blockquote")).not.toHaveAttribute("lang");
    expect(screen.queryByText(/\(in German/)).toBeNull();
  });

  it("on a letter's page takes the language of the letter it is from", async () => {
    const user = userEvent.setup();
    const doc = makeDoc({ language: "German" });
    const item = makeItem({
      kind: "payment",
      title: "Pay the fine",
      due_date: "2026-10-05",
      computation: makeReceipt({ due_date: "2026-10-05", summary: "One week after it arrived." }),
      date_spec: { type: "relative", text: WEEK_QUOTE, nature: "payment" } as never,
    });
    const detail = makeDetail({ document: doc, items: [item] });
    renderWithProviders(<DocumentView detail={detail} />, { client: clientWith("en", detail) });
    const todos = screen.getByRole("region", { name: /To-dos & dates/ });
    await user.click(within(todos).getByRole("button", { name: /Why this date\?/ }));
    const pop = await screen.findByRole("dialog", { name: "Why this date? Pay the fine" });
    expect(within(pop).getByText(WEEK_QUOTE).closest("blockquote")).toHaveAttribute("lang", "de");
  });
});

describe("Claude's words in the person's language (U6)", () => {
  it("are marked with it, right to left for Arabic", () => {
    expect(langProps("ar")).toEqual({ lang: "ar", dir: "rtl" });
    expect(langProps("tr")).toEqual({ lang: "tr" });
    expect(langProps("en")).toEqual({});
    expect(langProps(null)).toEqual({});
  });

  it("on a letter's page: its title, summary, explanation, key-fact labels and to-do titles", () => {
    const doc = makeDoc({
      title: "غرامة وقوف السيارات",
      summary: "عليك دفع 20 يورو.",
      explanation: "ادفع خلال أسبوع.",
      key_facts: [{ label: "المبلغ", value: "20,00 EUR", evidence: null }],
    });
    const detail = makeDetail({ document: doc, items: [makeItem({ title: "ادفع الغرامة", due_date: "2026-10-05" })] });
    renderWithProviders(<DocumentView detail={detail} />, { client: clientWith("ar", detail) });
    const rtl = (el: HTMLElement | null) => expect(el?.closest("[dir]")).toHaveAttribute("dir", "rtl");
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveAttribute("lang", "ar");
    expect(h1).toHaveAttribute("dir", "rtl");
    rtl(screen.getByText("عليك دفع 20 يورو."));
    expect(screen.getByText("عليك دفع 20 يورو.").closest("[lang]")).toHaveAttribute("lang", "ar");
    rtl(screen.getByText("ادفع خلال أسبوع."));
    rtl(within(screen.getByRole("region", { name: "Key facts" })).getByText("المبلغ"));
    rtl(within(screen.getByRole("region", { name: /To-dos & dates/ })).getByText("ادفع الغرامة"));
  });

  it("aren't marked for an English profile, and a file name is no one's words", () => {
    const detail = makeDetail({ document: makeDoc({ title: "Parking fine", summary: "Pay €20." }) });
    const { unmount } = renderWithProviders(<DocumentView detail={detail} />, { client: clientWith("en", detail) });
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveAttribute("lang");
    unmount();
    const unread = makeDetail({ document: makeDoc({ title: null, kind: null, ai_private: true, filename: "scan.pdf" }) });
    renderWithProviders(<DocumentView detail={unread} />, { client: clientWith("tr", unread) });
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveAttribute("lang");
  });

  it("in an Ask answer: in the person's language, German when its check says so", () => {
    expect(answerLanguage(CHECK_NOTE_LABEL_DE, "ar")).toBe("de");
    expect(answerLanguage("Checked by Ordnung:", "ar")).toBe("ar");
    expect(answerLanguage("Checked by Ordnung:", "de")).toBe("en");
    expect(answerLanguage(null, null)).toBe("en");
    const { container } = render(<Markdown text="ادفع قبل الموعد." citations={null} renderCitation={() => null} language="ar" />);
    expect(container.firstElementChild).toHaveAttribute("lang", "ar");
    expect(container.firstElementChild).toHaveAttribute("dir", "rtl");
  });
});
