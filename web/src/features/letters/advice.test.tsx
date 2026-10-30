/**
 * "Unsure? Get independent advice": one rule for the letter page, "Why this date?", the composer's objection check
 * and an objection's disclaimer. It reads the letter's kind and its sender's kind before the area the letter was
 * read under: a landlord's notice is the tenants' association's wherever it was filed, the broadcasting fee is a
 * consumer matter, never the tenants' association's.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { Draft, LetterAdvice } from "@/api/types";
import { ADVICE_LINKS, adviceFor, objectionAdvice } from "@/components/ui/Disclaimer";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import LetterPage from "@/pages/LetterPage";
import LettersPage from "@/pages/LettersPage";
import { objectionCheck } from "./logic";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

/** A landlord's notice without notice period: its card offers no hardship objection. */
const FRISTLOS: LetterAdvice = {
  kind: "landlord_notice",
  title: "Notice from your landlord — get advice before you act",
  summary: "",
  urgent: false,
  steps: [],
  facts: [{ title: "This reads as a notice without notice period (fristlos)", text: "The hardship objection doesn't apply to it.", tone: "warn", citation: "§ 574 Abs. 1 S. 2 BGB" }],
  help: [],
  rule_ids: [],
  draft: null,
  handled: false,
  closable: true,
};
const NONE = { type: "none" as const, addressee: null, period_text: null, form_text: null, quote: null };

describe("the advice rule", () => {
  it("gives a landlord's letter tenancy advice, whatever area it was read under", () => {
    expect(adviceFor("residence", "landlord_notice", null)).toBe(ADVICE_LINKS.rent);
    expect(adviceFor("residence", "operating_costs", "landlord")).toBe(ADVICE_LINKS.rent);
    expect(adviceFor("residence", "utility_bill", "landlord")).toBe(ADVICE_LINKS.rent);
  });

  it("gives the broadcasting fee consumer advice, never the tenants' association's", () => {
    expect(adviceFor("home", "broadcasting_fee", null)).toBe(ADVICE_LINKS.consumer);
    expect(adviceFor("home", "dunning", "public_broadcaster")).toBe(ADVICE_LINKS.consumer);
    expect(adviceFor("home", "broadcasting_fee", "public_broadcaster")).toBe(ADVICE_LINKS.consumer);
  });

  it("follows a high-stakes letter's card: the tenants' association for a tenancy letter, none for the others", () => {
    expect(adviceFor("residence", "operating_costs", null, { kind: "operating_costs" })).toBe(ADVICE_LINKS.rent);
    // the card lists its own help (a union, a court's desk)
    expect(adviceFor("work", "dismissal", "employer", { kind: "dismissal" })).toBeUndefined();
    expect(adviceFor("money", "court_payment_order", null, { kind: "court_payment_order" })).toBeUndefined();
  });

  it("keeps the rest as the letter page had it", () => {
    expect(adviceFor("residence", "residence_permit", "immigration_office")).toBe(ADVICE_LINKS.residence);
    expect(adviceFor("home", "contract", "utility")).toBe(ADVICE_LINKS.consumer);
    expect(adviceFor("tax")).toBe(ADVICE_LINKS.tax);
    expect(adviceFor("money", "dunning", "retailer")).toBeUndefined();
  });
});

describe("the composer's objection check", () => {
  it("points a landlord's notice read under 'residence' to the tenants' association", () => {
    const check = objectionCheck({ kind: "landlord_notice", remedy: null, area: "residence" }, FRISTLOS);
    expect(check).toMatchObject({ ok: false, reason: "no_hardship" });
    if (!check.ok) expect(check.advice).toBe(ADVICE_LINKS.rent);
  });

  it("points the broadcasting fee filed under 'home' to consumer advice", () => {
    const byKind = objectionCheck({ kind: "broadcasting_fee", remedy: NONE, area: "home" });
    expect(byKind).toMatchObject({ ok: false, reason: "none" });
    if (!byKind.ok) expect(byKind.advice).toBe(ADVICE_LINKS.consumer);
    // a reminder from the Beitragsservice: its sender says it
    const bySender = objectionCheck({ kind: "dunning", remedy: NONE, area: "home" }, null, "public_broadcaster");
    if (!bySender.ok) expect(bySender.advice).toBe(ADVICE_LINKS.consumer);
  });

  it("always names somewhere to get advice: the letter page's rule, else student services or consumer advice", () => {
    const areas = ["study", "health", "money", "work", "insurance", "leisure", "family", "other", null] as const;
    for (const area of areas) {
      for (const remedy of [null, { ...NONE, type: "klage" as const }, NONE]) {
        const check = objectionCheck({ kind: "other", remedy, area });
        expect(check.ok).toBe(false);
        if (!check.ok) expect(check.advice, `${area} ${remedy?.type}`).toBe(area === "study" ? ADVICE_LINKS.residence : ADVICE_LINKS.consumer);
      }
    }
    // a high-stakes letter's card lists its own help on the letter page; the composer still names a place to start
    const dismissal = objectionCheck({ kind: "dismissal", remedy: null, area: "work" }, { ...FRISTLOS, kind: "dismissal", draft: null }, "employer");
    if (!dismissal.ok) expect(dismissal.advice).toBe(ADVICE_LINKS.consumer);
    // the letter page's rule first
    expect(objectionAdvice("home", "broadcasting_fee", null)).toBe(ADVICE_LINKS.consumer);
    expect(objectionAdvice("residence", "landlord_notice", null)).toBe(ADVICE_LINKS.rent);
    expect(objectionAdvice("tax")).toBe(ADVICE_LINKS.tax);
  });

  it("names consumer advice in the composer for a health insurer's letter without instructions", async () => {
    useMockApi({ full: true });
    renderWithProviders(<LettersPage />, { route: "/letters?kind=objection&doc=doc_bkk" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    expect(await within(dialog).findByText("This letter doesn't explain how to object")).toBeInTheDocument();
    expect(within(dialog).getByText(/Unsure\? Get independent advice/)).toHaveTextContent("Verbraucherzentrale");
  });

  it("says it in the composer: the broadcasting fee's objection gets consumer advice", async () => {
    useMockApi({ full: true });
    renderWithProviders(<LettersPage />, { route: "/letters?kind=objection&doc=doc_rundfunk" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    expect(await within(dialog).findByText("This letter doesn't explain how to object")).toBeInTheDocument();
    const callout = within(dialog).getByText(/Unsure\? Get independent advice/);
    expect(callout).toHaveTextContent("Verbraucherzentrale");
    expect(callout).not.toHaveTextContent("Mieterverein");
  });
});

describe("an objection's disclaimer", () => {
  function renderLetter(id: string) {
    const router = createMemoryRouter([{ path: "/letters/:id", element: <LetterPage /> }], { initialEntries: [`/letters/${id}`] });
    render(
      <QueryClientProvider client={makeTestQueryClient()}>
        <RouterProvider router={router} />
        <Toaster />
      </QueryClientProvider>,
    );
  }

  it("names consumer advice under an objection to the broadcasting fee, never the tenants' association", async () => {
    const { srv } = useMockApi({ full: true });
    const base = srv.db.state.drafts[0]!;
    const objection: Draft = { ...base, id: "drf_obj_rundfunk", kind: "objection", status: "draft", doc_id: "doc_rundfunk", party_id: "pty_beitrag", contract_id: null };
    srv.db.state.drafts.push(objection);
    renderLetter(objection.id);
    // once the letter it objects to is known (its kind, its sender)
    await screen.findByRole("link", { name: /Broadcasting fee due 15 Nov/ });
    const disclaimer = screen.getByText(/Not legal advice/).closest("p")!;
    expect(within(disclaimer).getByRole("link", { name: /Verbraucherzentrale/ })).toBeInTheDocument();
    expect(within(disclaimer).queryByRole("link", { name: /Mieterverein/ })).toBeNull();
  });
});
