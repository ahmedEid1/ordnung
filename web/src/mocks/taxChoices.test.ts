/**
 * The person's "For taxes" choices in the mock backend (the static demo and `?mock=1`): kept apart from the
 * letters as the API keeps them apart from Claude's reading, with the API's answers and refusals.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DocumentDetail, DocumentRow } from "@/api/types";
import { createMockServer } from "./server";
import { RECEIPT_DOC_ID } from "./data/proof";
import { HELD_MESSAGE, IN_TRASH, NOT_A_LETTER, PROOF_FOR_TAXES } from "./taxChoices";

/** The mock with the New-mail letters opened too (the tax assessment, which Claude marked without a note, among them). */
const srv = () => {
  const s = createMockServer({ staticDemo: false, latency: 0 });
  s.openAllMail();
  return s;
};
type Server = ReturnType<typeof srv>;

afterEach(() => vi.useRealTimers());

const patch = (s: Server, id: string, body: unknown) => s.handle("PATCH", `/documents/${id}`, new URLSearchParams(), body);
const detail = async (s: Server, id: string) => (await (await s.handle("GET", `/documents/${id}`, new URLSearchParams(), undefined)).json()) as DocumentDetail;
const refusal = async (res: Response) => [res.status, ((await res.json()) as { detail: string }).detail];

describe("For taxes in the mock backend", () => {
  it("the mock keeps a tax choice apart from the letter, refuses a waiting letter, and Read again keeps it", async () => {
    const s = srv();
    const before = JSON.stringify(s.db.document("doc_tax"));
    const res = await patch(s, "doc_tax", { tax_choice: false });
    expect(res.status).toBe(200);
    // the answer is the letter as stored: Claude's mark, no choice on it, not even updated_at moved
    expect(JSON.stringify(await res.json())).toBe(before);
    expect(JSON.stringify(s.db.document("doc_tax"))).toBe(before);
    expect(s.db.state.taxChoices).toEqual({ doc_tax: false });
    expect((await detail(s, "doc_tax")).tax_choice).toBe(false);
    const rows = (await (await s.handle("GET", "/documents", new URLSearchParams(), undefined)).json()) as DocumentRow[];
    expect(rows.find((r) => r.id === "doc_tax")!.tax_choice).toBe(false);

    // a waiting letter, a proof file, a letter in the trash, one that isn't there: the API's refusals, nothing set
    expect(await refusal(await patch(s, "doc_folder_scan", { tax_choice: true }))).toEqual([409, HELD_MESSAGE]);
    expect(await refusal(await patch(s, RECEIPT_DOC_ID, { tax_choice: true }))).toEqual([409, PROOF_FOR_TAXES]);
    expect((await s.handle("DELETE", "/documents/doc_dentist", new URLSearchParams(), undefined)).ok).toBe(true);
    expect(await refusal(await patch(s, "doc_dentist", { tax_choice: true, title: "x" }))).toEqual([409, IN_TRASH]);
    expect(s.db.state.documents.find((d) => d.id === "doc_dentist")!.title).not.toBe("x");
    expect(await refusal(await patch(s, "doc_nothing", { tax_choice: true }))).toEqual([404, NOT_A_LETTER]);
    for (const bad of ["yes", 1, [true]]) expect((await patch(s, "doc_payslip", { tax_choice: bad })).status, String(bad)).toBe(422);
    expect(s.db.state.taxChoices).toEqual({ doc_tax: false });

    // Read again: Claude's mark is read again, the person's choice stays
    vi.useFakeTimers();
    const job = await s.handle("POST", "/documents/doc_tax/reprocess", new URLSearchParams(), undefined);
    expect(job.status).toBe(202);
    await vi.runAllTimersAsync();
    vi.useRealTimers();
    const again = await detail(s, "doc_tax");
    expect([again.document.status, again.document.tax_relevant, again.tax_choice]).toEqual(["processed", true, false]);

    // null goes back to Claude's mark
    expect((await patch(s, "doc_tax", { tax_choice: null })).status).toBe(200);
    expect(s.db.state.taxChoices).toEqual({});
    expect((await detail(s, "doc_tax")).tax_choice).toBeNull();
  });

  it("works in the online demo too, only in the browser's own copy", async () => {
    const demo = createMockServer({ staticDemo: true, latency: 0 });
    expect((await patch(demo, "doc_payslip", { tax_choice: false })).status).toBe(200);
    expect((await detail(demo, "doc_payslip")).tax_choice).toBe(false);
    expect((await patch(demo, "doc_payslip", { tax_choice: null })).status).toBe(200);
    expect(demo.db.state.taxChoices).toEqual({});
    // a new demo starts over without any
    demo.db.state.taxChoices.doc_payslip = true;
    expect(createMockServer({ staticDemo: true, latency: 0 }).db.state.taxChoices).toEqual({});
  });

  it("sets a choice with the letter's own fields in one PATCH, and marks a private letter too", async () => {
    const s = srv();
    s.db.document("doc_dentist")!.ai_private = true;
    const res = await patch(s, "doc_dentist", { tax_choice: true, title: "Dentist" });
    expect(res.status).toBe(200);
    expect(((await res.json()) as { title: string }).title).toBe("Dentist");
    expect(s.db.state.taxChoices).toEqual({ doc_dentist: true });
  });
});
