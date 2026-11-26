/**
 * The GiroCode's "These match the letter" and "Read the letter again", and a contract's "Save notice period", take
 * one press at a time: a second press before the button is drawn busy was refused right after the first worked (or
 * asked again), and a failed one takes the next press.
 */
import { afterEach, describe, it, vi } from "vitest";
import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useDocument } from "@/api/hooks";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { NoticePeriodForm } from "@/features/contracts/NoticePeriodForm";
import { GIROCODES } from "@/mocks/data/girocodes";
import { expectOnePressAtATime } from "@/test/busyButton";
import { holdRequests, useMockApi } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/render";
import { GiroCodeSection } from "./GiroCode";

afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

function LiveParkingCode() {
  const detail = useDocument("doc_parking");
  return <GiroCodeSection code={detail.data?.girocodes.find((g) => g.item_id === "itm_parking")} docId="doc_parking" collapsible />;
}

describe("the GiroCode", () => {
  it("“These match the letter” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/items/itm_parking/girocode/confirm");
    renderWithProviders(<LiveParkingCode />);
    const section = await screen.findByRole("region", { name: "GiroCode (EPC-QR)" });
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => within(section).getByRole("button", { name: "These match the letter" }), held });
  });

  it("“Read the letter again” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/documents/doc_parking/reprocess");
    renderWithProviders(<GiroCodeSection code={GIROCODES.itm_parking} docId="doc_parking" canReadAgain />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "They don't match" }));
    await expectOnePressAtATime({ user, button: () => screen.getByRole("button", { name: "Read the letter again" }), held });
  });
});

describe("a contract's notice period", () => {
  it("“Save notice period” takes one press at a time, and the next once it failed", async () => {
    const { srv } = useMockApi();
    const bank = srv.db.state.contracts.find((c) => c.id === "ctr_bank")!;
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/contracts/ctr_bank");
    renderWithProviders(
      <>
        <NoticePeriodForm contract={bank} onClose={() => {}} onUndone={() => {}} />
        <Toaster />
      </>,
    );
    fireEvent.change(screen.getByLabelText("Notice period"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Can be cancelled"), { target: { value: "any_time" } });
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => screen.getByRole("button", { name: "Save notice period" }), held });
  });
});
