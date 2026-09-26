import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import type { Contract } from "@/api/types";
import { __clearToasts } from "@/components/ui/Toast";
import { CONTRACTS } from "@/mocks/data/contracts";
import { contract } from "@/mocks/data/helpers";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import LettersPage from "@/pages/LettersPage";
import { cancellableContracts } from "@/features/letters/logic";
import { ContractsView } from "./ContractsView";
import { contractHref, endingLetterLabel, offersEndingLetter } from "./links";
import { decideBy } from "./model";

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", RO);
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const card = (name: string) => screen.getAllByRole("article").find((a) => within(a).queryByRole("heading", { name }))!;

describe("which contracts a letter can end", () => {
  const base = contract({ id: "ctr_x", name: "X", category: "gym", computed: null });
  const fee: Contract = { ...base, id: "ctr_fee", cancellable: false, cancel_hint: "Required by law." };
  const job: Contract = { ...base, id: "ctr_job", category: "employment", cancellable: false, cancel_hint: "A resignation." };

  it("offers a cancellation — or, for a job, a resignation — only where one applies", () => {
    expect(offersEndingLetter(base)).toBe(true);
    expect(offersEndingLetter({ ...base, status: "cancelled" })).toBe(false);
    expect(offersEndingLetter(fee)).toBe(false);
    expect(offersEndingLetter(job)).toBe(true);
    expect([endingLetterLabel(base), endingLetterLabel(job)]).toEqual(["Draft cancellation", "Draft resignation"]);
    expect(cancellableContracts([base, fee, job]).map((c) => c.id)).toEqual(["ctr_x", "ctr_job"]);
  });

  it("a contract that can't be cancelled is never a decision to make", () => {
    const phone = CONTRACTS.find((c) => c.id === "ctr_phone")!;
    const soon: Contract = { ...base, computed: { ...phone.computed!, send_by: "2026-10-08" } };
    expect(decideBy([soon], "2026-09-28").map((c) => c.id)).toEqual(["ctr_x"]);
    expect(decideBy([{ ...soon, cancellable: false }], "2026-09-28")).toEqual([]);
  });

  it("every link to a contract uses ?contract=", () => {
    expect(contractHref("ctr_phone")).toBe("/contracts?contract=ctr_phone");
  });
});

describe("Contracts page", () => {
  it("says why the broadcasting fee can't be cancelled and offers a resignation for the job", async () => {
    useMockApi();
    renderWithProviders(<ContractsView />, { route: "/contracts" });
    await screen.findByRole("heading", { name: "Rundfunkbeitrag" });

    const fee = card("Rundfunkbeitrag");
    expect(within(fee).queryByRole("link", { name: /Draft cancellation/ })).not.toBeInTheDocument();
    expect(within(fee).getByTestId("cancel-hint")).toHaveTextContent(/required by law for every household/);

    const job = card("Werkstudent at Muster Tech");
    expect(within(job).getByRole("link", { name: /Draft resignation/ })).toHaveAttribute("href", "/letters?kind=cancellation&contract=ctr_job");
    expect(within(job).queryByTestId("cancel-hint")).not.toBeInTheDocument();

    const phone = card("FunkNetz Allnet L");
    expect(within(phone).getByRole("link", { name: /Draft cancellation/ })).toBeInTheDocument();
    expect(within(phone).queryByTestId("cancel-hint")).not.toBeInTheDocument();
  });

  it("accepts the older ?focus= link and rewrites it to ?contract=", async () => {
    useMockApi();
    const { router } = renderWithProviders(<ContractsView />, { route: "/contracts?focus=ctr_gym" });
    await waitFor(() => expect(router.state.location.search).toBe("?contract=ctr_gym"));
    await screen.findByRole("heading", { name: "FitWell Flex" });
    expect(card("FitWell Flex").className).toMatch(/border-accent/);
  });
});

describe("Letters composer", () => {
  it("doesn't draft a cancellation of the broadcasting fee — and says why", async () => {
    useMockApi();
    renderWithProviders(<LettersPage />, { route: "/letters?kind=cancellation&contract=ctr_rundfunk" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    expect(await within(dialog).findByText("Rundfunkbeitrag can't be cancelled")).toBeInTheDocument();
    expect(within(dialog).getByText(/required by law for every household/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("radio", { name: /Rundfunkbeitrag/ })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Write the letter/ })).toBeDisabled();
  });

  it("drafts a resignation for the job, with the form rule up front", async () => {
    useMockApi();
    renderWithProviders(<LettersPage />, { route: "/letters?kind=cancellation&contract=ctr_job" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    expect(await within(dialog).findByText("This drafts your resignation")).toBeInTheDocument();
    expect(within(dialog).getByText(/§ 623 BGB/)).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: /Werkstudent at Muster Tech/ })).toBeChecked();
    expect(within(dialog).getByRole("button", { name: /Write the letter/ })).toBeEnabled();
  });
});
