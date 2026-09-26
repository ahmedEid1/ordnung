import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Party } from "@/api/types";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { ibanLooksValid, normalizeIban } from "@/lib/format";
import { __clearToasts } from "@/components/ui/Toast";
import LettersPage from "@/pages/LettersPage";
import { followUpDate, objectionCheck } from "./logic";
import { SCHUFA_ADDRESS, TEMPLATES, TEMPLATE_BY_KIND, detailsPayload, fieldError, isTemplateKind, missingFields, parseMoney, sortForTemplate } from "./templates";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

describe("template letter helpers", () => {
  it("reads amounts typed German or English style", () => {
    expect(parseMoney("1.234,50")).toBe(1234.5);
    expect(parseMoney("80")).toBe(80);
    expect(parseMoney("80,5")).toBe(80.5);
    expect(parseMoney("1,234.50")).toBe(1234.5);
    expect(parseMoney(" 50 € ")).toBe(50);
    expect(parseMoney("")).toBeNull();
    expect(parseMoney(undefined)).toBeNull();
    expect(parseMoney("fifty")).toBeNull();
    expect(parseMoney("-5")).toBeNull();
  });

  it("lists the required facts still missing, in form order", () => {
    const plan = TEMPLATE_BY_KIND.payment_plan;
    expect(missingFields(plan, {})).toEqual(["Monthly instalment you can pay", "First instalment on"]);
    expect(missingFields(plan, { instalment: "0" })).toEqual(["Monthly instalment you can pay", "First instalment on"]);
    expect(missingFields(plan, { instalment: "50", first_instalment: "2026-11-01" })).toEqual([]);
    expect(missingFields(TEMPLATE_BY_KIND.data_access, {})).toEqual([]);
    expect(missingFields(TEMPLATE_BY_KIND.withdrawal, { subject_matter: "  " })).toEqual(["What did you order or sign up for?"]);
  });

  it("flags dates on the wrong side of today and unreadable amounts", () => {
    const plan = TEMPLATE_BY_KIND.payment_plan;
    const first = plan.fields.find((f) => f.name === "first_instalment")!;
    const instalment = plan.fields.find((f) => f.name === "instalment")!;
    expect(fieldError(first, { first_instalment: "2026-09-28" }, "2026-09-28")).toBe("Choose a day after today.");
    expect(fieldError(first, { first_instalment: "2026-10-01" }, "2026-09-28")).toBeNull();
    expect(fieldError(instalment, { instalment: "lots" }, "2026-09-28")).toMatch(/Enter an amount/);
    const received = TEMPLATE_BY_KIND.withdrawal.fields.find((f) => f.name === "received_on")!;
    expect(fieldError(received, { received_on: "2026-10-02" }, "2026-09-28")).toBe("This day can't be in the future.");
    const until = TEMPLATE_BY_KIND.extension_request.fields.find((f) => f.name === "until")!;
    expect(fieldError(until, { until: "2026-10-10", deadline: "2026-10-12" }, "2026-09-28")).toBe("Choose a day after the current deadline.");
  });

  it("sends only this template's facts, typed", () => {
    expect(detailsPayload(TEMPLATE_BY_KIND.payment_plan, { instalment: "1.000,00", first_instalment: "2026-11-01", amount: "", defect: "ignored" })).toEqual({
      instalment: 1000,
      first_instalment: "2026-11-01",
    });
    expect(detailsPayload(TEMPLATE_BY_KIND.withdrawal, { subject_matter: " Kaffeemaschine ", instructions_missing: true })).toEqual({
      subject_matter: "Kaffeemaschine",
      instructions_missing: true,
    });
    expect(detailsPayload(TEMPLATE_BY_KIND.data_access, {}, ` ${SCHUFA_ADDRESS} `)).toEqual({ recipient: SCHUFA_ADDRESS });
  });

  it("puts the likely recipients first", () => {
    const parties = [
      { kind: "bank", name: "Bank" },
      { kind: "landlord", name: "Wohnbau" },
      { kind: "person", name: "Anna" },
    ] as Pick<Party, "kind" | "name">[];
    expect(sortForTemplate(parties, TEMPLATE_BY_KIND.deposit_return).map((p) => p.name)).toEqual(["Wohnbau", "Anna", "Bank"]);
    expect(sortForTemplate(parties, null).map((p) => p.name)).toEqual(["Anna", "Bank", "Wohnbau"]);
  });

  it("knows every template kind", () => {
    expect(TEMPLATES).toHaveLength(8);
    expect(isTemplateKind("deposit_return")).toBe(true);
    expect(isTemplateKind("objection")).toBe(false);
    expect(isTemplateKind(null)).toBe(false);
  });
});

describe("statutory objections and follow-ups", () => {
  it("offers the law's remedy against court orders and a landlord's notice, whatever the instructions say", () => {
    expect(objectionCheck({ kind: "court_payment_order", remedy: null, area: "money" })).toMatchObject({ ok: true, term: "Widerspruch", statutory: true, remedy: null });
    expect(objectionCheck({ kind: "enforcement_order", remedy: { type: "none", addressee: null, period_text: null, form_text: null, quote: null }, area: "money" })).toMatchObject({
      ok: true,
      term: "Einspruch",
      statutory: true,
    });
    expect(objectionCheck({ kind: "landlord_notice", remedy: null, area: "home" })).toMatchObject({ ok: true, term: "Widerspruch", statutory: true });
    expect(objectionCheck({ kind: "dismissal", remedy: null, area: "work" })).toMatchObject({ ok: false, reason: "missing" });
  });

  it("gives a data request a month to answer before the follow-up", () => {
    expect(followUpDate("2026-09-28", "data_access")).toBe("2026-11-02");
    expect(followUpDate("2026-09-28", "withdrawal")).toBe("2026-10-19");
  });

  it("checks an IBAN like the server", () => {
    expect(normalizeIban("de89 3704-0044 0532.0130 00")).toBe("DE89370400440532013000");
    expect(ibanLooksValid("DE89 3704 0044 0532 0130 00")).toBe(true);
    expect(ibanLooksValid("DE89 3704 0044 0532 0130 01")).toBe(false);
    expect(ibanLooksValid("not an iban")).toBe(false);
  });
});

describe("composer — template letters", () => {
  it("writes a data request to SCHUFA from a typed address", async () => {
    const { calls } = useMockApi({ full: true });
    const user = userEvent.setup();
    const { router, container } = renderWithProviders(<LettersPage />, { route: "/letters?new=1" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    await user.click(within(dialog).getByRole("radio", { name: /Ask for your data/ }));
    expect(within(dialog).getByText("Which company or office?")).toBeInTheDocument();
    const write = within(dialog).getByRole("button", { name: /Write the letter/ });
    expect(write).toBeDisabled();
    expect(within(dialog).getByText("Choose who the letter is for.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Use SCHUFA's address" }));
    expect(within(dialog).getByLabelText(/Or type their name and address/)).toHaveValue(SCHUFA_ADDRESS);
    expect(write).toBeEnabled();
    assertNoRawEnumsInElement(container);
    await user.click(write);
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/letters\/drf_/));
    const post = calls.find((c) => c.method === "POST" && c.path === "/drafts");
    expect(post?.body).toMatchObject({ kind: "data_access", party_id: null, details: { recipient: SCHUFA_ADDRESS } });
  });

  it("keeps an instalment request disabled until its facts are there, then sends them typed", async () => {
    const { calls } = useMockApi({ full: true });
    const user = userEvent.setup();
    const { router } = renderWithProviders(<LettersPage />, { route: "/letters?new=1" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    await user.click(within(dialog).getByRole("radio", { name: /Pay in instalments/ }));
    await user.selectOptions(within(dialog).getByLabelText(/Or write to someone without a letter/), "pty_finanzamt");
    const write = within(dialog).getByRole("button", { name: /Write the letter/ });
    expect(write).toBeDisabled();
    expect(within(dialog).getByText("Still needed: monthly instalment you can pay, first instalment on.")).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText(/Monthly instalment you can pay/), "50");
    const first = within(dialog).getByLabelText(/First instalment on/);
    await user.type(first, "2026-09-01");
    expect(await within(dialog).findByText("Choose a day after today.")).toBeInTheDocument();
    expect(write).toBeDisabled();
    await user.clear(first);
    await user.type(first, "2026-11-01");
    await waitFor(() => expect(write).toBeEnabled());

    await user.click(write);
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/letters\/drf_/));
    const post = calls.find((c) => c.method === "POST" && c.path === "/drafts");
    expect(post?.body).toMatchObject({ kind: "payment_plan", party_id: "pty_finanzamt", details: { instalment: 50, first_instalment: "2026-11-01" } });
  });
});
