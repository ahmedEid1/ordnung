/**
 * My numbers: hidden until "Show" (its name says what a press does), Copy works while hidden
 * and is announced, the check-digit result, the tabs, the call-sheet search, and the static demo's data
 * following what the visitor does (a deleted letter takes its numbers along).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/api/endpoints";
import type { MyNumbers } from "@/api/types";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { mockNumbers } from "@/mocks/numbers";
import { MOCK_NUMBERS } from "@/mocks/data/numbers";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { hiddenLabel, maskValue, visibleTail } from "./mask";
import { NumbersView, matchesSheet, sheetMatch } from "./NumbersView";
import { numberTitle, printedLabel } from "./NumberRow";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

async function renderNumbers(route = "/numbers") {
  const user = userEvent.setup();
  renderWithProviders(
    <>
      <NumbersView />
      <Toaster />
    </>,
    { route },
  );
  await screen.findByRole("tablist", { name: "Which numbers" });
  return { user };
}

describe("masking", () => {
  it("keeps the shape and the last few characters", () => {
    expect(maskValue("57 216 480 354")).toBe("•• ••• ••• 354");
    expect(maskValue("65 140300 R 005")).toBe("•• •••••• • 005");
    expect(maskValue("2231847")).toBe("•••••47");
    expect(maskValue("OA-VW-2026-55012")).toBe("••-••-••••-••012");
    expect(maskValue("1234")).toBe("••••");
    expect(visibleTail(8)).toBe(3);
    expect(visibleTail(5)).toBe(2);
    expect(visibleTail(4)).toBe(0);
  });

  it("tells a screen reader it is hidden and how it ends", () => {
    expect(hiddenLabel("57 216 480 354")).toBe("hidden, ends in 3 5 4");
    expect(hiddenLabel("1234")).toBe("hidden");
  });

  it("titles a number by what it is, or by the letter's label where that says more", () => {
    const n = { kind: "tax_id", name: "Tax ID (Steuer-ID)", label: "Steuerliche Identifikationsnummer" } as const;
    expect(numberTitle(n)).toBe("Tax ID (Steuer-ID)");
    expect(printedLabel(n)).toBe("Steuerliche Identifikationsnummer");
    expect(printedLabel({ kind: "tax_id", name: "Tax ID (Steuer-ID)", label: "Steuer-ID" })).toBeNull();
    expect(numberTitle({ kind: "other", name: "Your number", label: "Scholarship ID" })).toBe("Scholarship ID");
  });
});

describe("the page", () => {
  it("hides every number until Show, and says so to screen readers", async () => {
    useMockApi();
    const { user } = await renderNumbers();
    const tax = MOCK_NUMBERS.about_you.find((n) => n.kind === "tax_id")!;
    expect(screen.queryByText(tax.display)).toBeNull();
    expect(screen.getByText(maskValue(tax.display))).toHaveAttribute("aria-hidden");
    expect(screen.getAllByText(hiddenLabel(tax.display)).length).toBeGreaterThan(0);

    // the name says what a press does; no aria-pressed as well ("Hide …, pressed" says it twice)
    const show = screen.getByRole("button", { name: "Show Tax ID (Steuer-ID)" });
    expect(show).not.toHaveAttribute("aria-pressed");
    await user.click(show);
    expect(screen.getByText(tax.display)).toBeInTheDocument();
    const hide = screen.getByRole("button", { name: "Hide Tax ID (Steuer-ID)" });
    expect(hide).not.toHaveAttribute("aria-pressed");
    expect(hide).toHaveTextContent("Hide");
    await user.click(hide);
    expect(screen.queryByText(tax.display)).toBeNull();
  });

  it("copies the form's way (no spaces) while hidden, and announces it", async () => {
    useMockApi();
    const { user } = await renderNumbers();
    await user.click(screen.getByRole("button", { name: "Copy Tax ID (Steuer-ID)" }));
    expect(await navigator.clipboard.readText()).toBe("57216480354");
    expect(screen.getByRole("button", { name: "Tax ID (Steuer-ID) copied" })).toHaveTextContent("Copied");
    const live = screen.getAllByText("Tax ID (Steuer-ID) copied").find((el) => el.getAttribute("aria-live") === "polite");
    expect(live).toBeDefined();
  });

  it("says whether the check digit passes, and what to do when it does not", async () => {
    const { srv } = useMockApi();
    // the demo's numbers all pass: one misread digit, as a scan might give it
    const handle = srv.handle;
    srv.handle = async (method, path, ...rest) => {
      const res = await handle(method, path, ...rest);
      if (method !== "GET" || path !== "/numbers") return res;
      const data = (await res.json()) as MyNumbers;
      const about_you = data.about_you.map((n) =>
        n.kind === "health_insurance"
          ? { ...n, check: "fails" as const, check_note: "Does not pass the Krankenversichertennummer check (§ 290 SGB V): the last digit is not the check digit — compare it with the letter." }
          : n,
      );
      return Response.json({ ...data, about_you });
    };
    await renderNumbers();
    expect(screen.getAllByRole("button", { name: "Check digit OK" }).length).toBeGreaterThanOrEqual(2);
    const fails = screen.getByRole("button", { name: "Does not check — compare with the letter" });
    fireEvent.pointerEnter(fails, { pointerType: "mouse" });
    expect(await screen.findByRole("tooltip")).toHaveTextContent(/Does not pass the Krankenversichertennummer check \(§ 290 SGB V\)/);
    // the letter each came from
    expect(screen.getAllByRole("link", { name: "Payslip August 2026" })[0]).toHaveAttribute("href", "/documents/doc_payslip");
  });

  it("shows documents with their expiry", async () => {
    useMockApi();
    await renderNumbers();
    const docs = screen.getByRole("heading", { name: /Your documents/ }).closest("section")!;
    expect(within(docs).getByRole("heading", { name: "Passport" })).toBeInTheDocument();
    expect(within(docs).getAllByText((_, el) => el?.textContent === "Valid until 10 Feb 2027").length).toBeGreaterThan(0);
    expect(within(docs).getAllByText("Renew soon").length).toBe(2);
    expect(within(docs).getByText(/§ 81 Abs\. 4 S\. 1 AufenthG/)).toBeInTheDocument();
    // the passport's expiry was read by AI from a photo: the card says to compare it
    const passport = within(docs).getByRole("heading", { name: "Passport" }).closest("article")!;
    expect(within(passport).getByText(/Compare this date with the letter/)).toBeInTheDocument();
    // "Valid until" and its date never part at the line's end
    expect(within(passport).getByText("10 Feb 2027")).toHaveClass("whitespace-nowrap");
  });

  it("lists open cases and a searchable call sheet per organisation", async () => {
    useMockApi();
    const { user } = await renderNumbers("/numbers?tab=cases");
    expect(screen.getByRole("tab", { name: /Open cases/ })).toHaveAttribute("aria-selected", "true");
    // references never break at their hyphens (non-breaking hyphens on screen)
    expect(await screen.findByRole("heading", { name: "Parking fine OA\u2011VW\u20112026\u201155012" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Organisations/ }));
    const sheets = screen.getByRole("list", { name: /organisations/ });
    const count = within(sheets).getAllByRole("article").length;
    expect(count).toBe(MOCK_NUMBERS.organisations.length);
    await user.type(screen.getByRole("searchbox", { name: /Find an organisation/ }), "fitwell");
    expect(within(screen.getByRole("list", { name: "1 organisation" })).getByRole("heading", { name: "FitWell Studios" })).toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox", { name: /Find an organisation/ }));
    await user.type(screen.getByRole("searchbox", { name: /Find an organisation/ }), "no such organisation");
    expect(screen.getByRole("heading", { name: "No organisation matches" })).toBeInTheDocument();
  });

  it("opens an organisation's own numbers when only they match the search", async () => {
    useMockApi();
    const { user } = await renderNumbers("/numbers?tab=organisations");
    const beitrag = MOCK_NUMBERS.organisations.find((s) => s.name === "Beitragsservice Musterstadt")!;
    const iban = beitrag.their_numbers.find((n) => n.kind === "iban")!;
    const tail = iban.value.slice(-6);
    expect(sheetMatch(beitrag, tail)).toBe("theirs");
    expect(sheetMatch(beitrag, "beitrag")).toBe("sheet");
    await user.type(screen.getByRole("searchbox", { name: /Find an organisation/ }), tail);
    const card = screen.getByRole("heading", { name: "Beitragsservice Musterstadt" }).closest("article")!;
    expect(card.querySelector("details")).toHaveAttribute("open");
    await user.clear(screen.getByRole("searchbox", { name: /Find an organisation/ }));
    const again = screen.getByRole("heading", { name: "Beitragsservice Musterstadt" }).closest("article")!;
    expect(again.querySelector("details")).not.toHaveAttribute("open");
  });

  it("links each number on a call sheet to its letter when that is not the last letter", async () => {
    useMockApi();
    const stadtwerke = MOCK_NUMBERS.organisations.find((s) => s.name === "Stadtwerke Musterstadt")!;
    const older = { id: "doc_contract", title: "Electricity contract 2024", date: "2024-03-01", kind: "contract" as const };
    const meter = { ...stadtwerke.numbers[0]!, key: "num_meter", kind: "meter" as const, name: "Meter or supply point", label: "Zählernummer", value: "1EMH0012345678", display: "1EMH0012345678", copy_value: "1EMH0012345678", letter: older };
    const data = { ...MOCK_NUMBERS, organisations: MOCK_NUMBERS.organisations.map((s) => (s === stadtwerke ? { ...s, numbers: [...s.numbers, meter] } : s)) };
    vi.spyOn(api, "numbers").mockResolvedValue(data);
    await renderNumbers("/numbers?tab=organisations");
    const card = screen.getByRole("heading", { name: "Stadtwerke Musterstadt" }).closest("article")!;
    expect(within(card).getByRole("link", { name: "Electricity contract 2024" })).toHaveAttribute("href", "/documents/doc_contract");
    // the customer number is from the last letter, which the card names once, at its foot
    expect(within(card).getAllByRole("link", { name: stadtwerke.last_letter!.title })).toHaveLength(1);
  });

  it("names the organisations tab so voice control finds it by its short label too", async () => {
    useMockApi();
    await renderNumbers();
    expect(screen.getByRole("tab", { name: /^Orgs Organisations/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^About you/ })).toBeInTheDocument(); // "You" is in "About you"
  });

  it("finds a call sheet by a number without its spaces", () => {
    const beitrag = MOCK_NUMBERS.organisations.find((s) => s.name.startsWith("Beitragsservice"))!;
    expect(matchesSheet(beitrag, "457812")).toBe(true);
    expect(matchesSheet(beitrag, "Beitragsnummer")).toBe(true);
    expect(matchesSheet(beitrag, "45")).toBe(false); // too short to match a number
  });

  it("offers Add letters when there is nothing yet", async () => {
    const { srv } = useMockApi();
    for (const d of srv.db.state.documents) d.deleted_at = "2026-09-28T08:00:00Z";
    await act(async () => {
      renderWithProviders(
        <AddLettersProvider>
          <NumbersView />
        </AddLettersProvider>,
        { route: "/numbers" },
      );
    });
    expect(await screen.findByRole("heading", { name: "No numbers yet" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add letters" })).toBeInTheDocument();
  });
});

describe("the static demo's numbers follow the visitor", () => {
  it("a deleted letter takes its numbers along", () => {
    const { srv } = useMockApi();
    expect(mockNumbers(srv.db).about_you.some((n) => n.kind === "tax_id")).toBe(true);
    srv.db.state.documents.find((d) => d.id === "doc_payslip")!.deleted_at = "2026-09-28T08:00:00Z";
    const after = mockNumbers(srv.db);
    expect(after.about_you.some((n) => n.kind === "tax_id")).toBe(false);
    // (the demo's data knows each number's latest letter: the payslip's go with it)
    expect(after.organisations.find((s) => s.name === "Muster Tech GmbH")).toBeUndefined();
    expect(after.organisations.find((s) => s.name === "FitWell Studios")?.numbers.map((n) => n.kind)).toEqual(["member"]);
  });
});
