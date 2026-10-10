/**
 * The Export letters dialog: how many letters the ZIP will hold, the download link that carries the choice, the
 * early statements' box only where it applies, the warning that the ZIP isn't encrypted — and nothing happens until
 * the person clicks Download.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Document, Party } from "@/api/types";
import { makeDoc } from "@/features/document/fixtures";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import type { MockServer } from "@/mocks/server";
import { ExportLettersDialog, type ExportPreset } from "./ExportLettersDialog";

const letter = (id: string, fields: Partial<Document> = {}): Document => makeDoc({ id, title: id, doc_date: null, received_date: null, party_id: null, ...fields });
const party = (id: string, name: string): Party => ({ id, name, kind: "other", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }) as Party;

function seed(srv: MockServer) {
  srv.db.state.documents = [
    letter("payslip", { tax_relevant: true, doc_date: "2025-08-31", party_id: "pty_work" }),
    letter("rent", { doc_date: "2025-03-01", party_id: "pty_home" }),
    letter("statement", { tax_relevant: true, doc_date: "2026-02-10", party_id: "pty_work" }),
    letter("june", { tax_relevant: true, doc_date: "2026-06-10" }),
    letter("waiting", { doc_date: "2025-05-05", status: "held", ai_private: true, tax_relevant: true }),
  ];
  srv.db.state.parties = [party("pty_work", "Mustertech GmbH"), party("pty_home", "Hausverwaltung Kurz")];
}

function renderDialog(preset?: ExportPreset) {
  const onClose = vi.fn();
  renderWithProviders(
    <>
      <ExportLettersDialog open onClose={onClose} preset={preset} />
      <Toaster />
    </>,
  );
  return { onClose };
}

const query = (link: HTMLElement) => Object.fromEntries(new URL(link.getAttribute("href")!, "http://x").searchParams);

afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

describe("ExportLettersDialog", () => {
  it("counts every letter that can be exported, and warns that the ZIP isn't encrypted", async () => {
    const { srv, calls } = useMockApi();
    seed(srv);
    renderDialog();
    const dialog = await screen.findByRole("dialog", { name: "Export letters" });
    expect(await within(dialog).findByText("4 letters will be in the ZIP.")).toHaveAttribute("role", "status");
    expect(within(dialog).getByText(/The ZIP isn't encrypted\. Anyone who has it can read these letters/)).toBeInTheDocument();
    expect(within(dialog).getByText("Letters you wrote in Ordnung aren't included — download each one's PDF under Letters.")).toBeInTheDocument();
    const link = within(dialog).getByRole("link", { name: "Download ZIP" });
    expect(link).toHaveAttribute("download", "ordnung-letters-2026-09-28.zip");
    expect(query(link)).toEqual({});
    // only a link: nothing was asked for the ZIP until the person clicks it
    expect(calls.some((c) => c.path.startsWith("/documents.zip"))).toBe(false);
  });

  it("narrows the ZIP by year, sender and taxes, and the link carries the choice", async () => {
    const { srv } = useMockApi();
    seed(srv);
    renderDialog();
    const dialog = await screen.findByRole("dialog", { name: "Export letters" });
    await within(dialog).findByText("4 letters will be in the ZIP.");
    const year = within(dialog).getByRole("combobox", { name: "Year" });
    expect(within(year).getAllByRole("option").map((o) => o.textContent)).toEqual(["All years", "2026 · 2 letters", "2025 · 2 letters"]);
    await userEvent.selectOptions(year, "2025");
    expect(within(dialog).getByRole("status")).toHaveTextContent("2 letters will be in the ZIP.");
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Sender" }), "pty_work");
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Only letters for taxes" }));
    expect(within(dialog).getByRole("status")).toHaveTextContent("1 letter will be in the ZIP.");
    const link = within(dialog).getByRole("link", { name: "Download ZIP" });
    expect(query(link)).toEqual({ year: "2025", tax: "true", party_id: "pty_work" });
    expect(link).toHaveAttribute("download", "ordnung-letters-for-taxes-2025.zip");
  });

  it("offers the next year's early statements only for a year's letters for taxes that has them", async () => {
    const { srv } = useMockApi();
    seed(srv);
    renderDialog();
    const dialog = await screen.findByRole("dialog", { name: "Export letters" });
    await within(dialog).findByText("4 letters will be in the ZIP.");
    expect(within(dialog).queryByRole("checkbox", { name: /dated January–May/ })).toBeNull();
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Year" }), "2025");
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Only letters for taxes" }));
    const early = within(dialog).getByRole("checkbox", { name: /^Also the letter for taxes dated January–May 2026/ });
    expect(early).not.toBeChecked();
    expect(within(dialog).getByText("Yearly statements for 2025 often arrive then.")).toBeInTheDocument();
    await userEvent.click(early);
    expect(within(dialog).getByRole("status")).toHaveTextContent("2 letters will be in the ZIP.");
    expect(query(within(dialog).getByRole("link", { name: "Download ZIP" }))).toEqual({ year: "2025", until: "2026-05-31", tax: "true" });
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Year" }), "2026");
    expect(within(dialog).queryByRole("checkbox", { name: /dated January–May/ })).toBeNull();
  });

  it("starts from a preset: the tax year with its early statements", async () => {
    const { srv } = useMockApi();
    seed(srv);
    renderDialog({ year: 2025, tax: true, early: true });
    const dialog = await screen.findByRole("dialog", { name: "Export letters" });
    expect(await within(dialog).findByText("2 letters will be in the ZIP.")).toBeInTheDocument();
    expect(within(dialog).getByRole("checkbox", { name: "Only letters for taxes" })).toBeChecked();
    expect(within(dialog).getByRole("checkbox", { name: /dated January–May 2026/ })).toBeChecked();
  });

  it("counts each year under the rest of the choice, so the year shown matches the ZIP", async () => {
    const { srv } = useMockApi();
    seed(srv);
    renderDialog({ year: 2025, tax: true, early: true });
    const dialog = await screen.findByRole("dialog", { name: "Export letters" });
    await within(dialog).findByText("2 letters will be in the ZIP.");
    const year = within(dialog).getByRole("combobox", { name: "Year" });
    expect(within(year).getAllByRole("option").map((o) => o.textContent)).toEqual(["All years", "2026 · 2 letters", "2025 · 1 letter"]);
    expect(within(year).getByRole("option", { selected: true })).toHaveTextContent("2025 · 1 letter");
    // the early statement is the other one, named on its own box
    expect(within(dialog).getByRole("checkbox", { name: /^Also the letter for taxes dated January–May 2026/ })).toBeChecked();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /dated January–May 2026/ }));
    expect(within(dialog).getByRole("status")).toHaveTextContent("1 letter will be in the ZIP.");
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Sender" }), "pty_home");
    expect(within(dialog).getByRole("status")).toHaveTextContent("No letters match.");
    expect(within(year).getByRole("option", { selected: true })).toHaveTextContent("2025 · 0 letters");
  });

  it("can't download when no letter matches", async () => {
    const { srv } = useMockApi();
    seed(srv);
    renderDialog({ year: 2026, tax: true, party_id: "pty_home" });
    const dialog = await screen.findByRole("dialog", { name: "Export letters" });
    expect(await within(dialog).findByText("No letters match. Choose another year or sender.")).toBeInTheDocument();
    expect(within(dialog).queryByRole("link", { name: "Download ZIP" })).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Download ZIP" })).toBeDisabled();
  });

  it("downloads only on a click: the dialog closes and a toast says the ZIP isn't encrypted", async () => {
    const { srv } = useMockApi();
    seed(srv);
    const { onClose } = renderDialog({ year: 2025, tax: true });
    const dialog = await screen.findByRole("dialog", { name: "Export letters" });
    const link = await within(dialog).findByRole("link", { name: "Download ZIP" });
    // reachable from the keyboard like any link
    link.focus();
    expect(link).toHaveFocus();
    link.addEventListener("click", (e) => e.preventDefault()); // jsdom can't navigate
    await userEvent.click(link);
    expect(onClose).toHaveBeenCalled();
    expect(await screen.findByText("Your letters are downloading")).toBeInTheDocument();
    expect(screen.getByText("Your browser saves ordnung-letters-for-taxes-2025.zip. It isn't encrypted.")).toBeInTheDocument();
  });
});
