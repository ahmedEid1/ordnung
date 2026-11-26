/**
 * Settings' buttons that change something take one press at a time: two presses before the button is drawn busy
 * send one request (a second save refused as a conflict, a second backup file, a second notification, a second
 * live call to Claude), and a failed one takes the next press. The save bar every section shares is guarded once.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import SettingsPage from "@/pages/SettingsPage";
import { expectOnePressAtATime } from "@/test/busyButton";
import { holdRequests, useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";

const CALENDAR = "https://cloud.example.org/remote.php/dav/calendars/sam/ordnung/";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

/** Settings at `section`; `installed`: not the demo (Data offers its backup and delete only there). */
function openSettings(section: string, installed = false) {
  const client = makeTestQueryClient();
  if (installed) client.setQueryData(qk.health, { ...TEST_HEALTH, demo: false });
  renderWithProviders(
    <>
      <SettingsPage />
      <Toaster />
    </>,
    { route: `/settings?section=${section}`, client },
  );
}

describe("the save bar every section shares", () => {
  it("“Save changes” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((c) => c.method === "PUT" && c.path === "/profile");
    openSettings("region");
    const user = userEvent.setup();
    const language = await screen.findByLabelText("Language for explanations");
    const other = within(language).getAllByRole("option").find((o) => !(o as HTMLOptionElement).selected)!;
    await user.selectOptions(language, other);
    await expectOnePressAtATime({ user, button: () => screen.getByRole("button", { name: "Save changes" }), held });
  });
});

describe("Settings' own buttons", () => {
  it("“Run check” asks Claude once per press, and again once it failed", async () => {
    useMockApi();
    // the check is the health request that asks Claude (`?probe=true`), not the page's own
    const held = holdRequests((c) => c.method === "GET" && c.path === "/health" && Boolean((c as { url?: URL }).url?.searchParams.has("probe")));
    openSettings("claude");
    await screen.findByRole("button", { name: "Run check" });
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => screen.getByRole("button", { name: "Run check" }), held });
  });

  it("“Stop watching” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((c) => c.method === "PUT" && c.path === "/settings");
    openSettings("folder");
    const status = await screen.findByRole("region", { name: "Status" });
    await within(status).findByRole("button", { name: "Stop watching" });
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => within(status).getByRole("button", { name: "Stop watching" }), held });
  });

  it("“Show a test notification” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((c) => c.method === "POST" && c.path === "/reminders/desktop/test");
    openSettings("reminders");
    const card = await screen.findByRole("region", { name: "Desktop notification each morning" });
    await userEvent.setup().click(within(card).getByRole("switch", { name: /Notify me each morning on this computer/ }));
    await within(card).findByRole("button", { name: "Show a test notification" });
    await expectOnePressAtATime({ user: userEvent.setup(), button: () => within(card).getByRole("button", { name: "Show a test notification" }), held });
  });

  it("“Download backup” makes one backup for two presses in one go, and again once it failed", async () => {
    useMockApi();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:backup", revokeObjectURL: () => {} }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const held = holdRequests((c) => c.method === "POST" && c.path === "/backup");
    openSettings("data");
    const card = await screen.findByRole("region", { name: "Encrypted backup" });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: "Download encrypted backup…" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Suggest a strong one" }));
    // pressed, it says "Encrypting…" and hands focus to "Stop": two presses in one go, then one after the failure
    const download = within(dialog).getByRole("button", { name: "Download backup" });
    act(() => {
      download.click();
      download.click();
    });
    await waitFor(() => expect(held.count).toBe(1));
    await act(async () => {});
    expect(held.count).toBe(1);
    await act(async () => held.fail());
    await user.click(await within(dialog).findByRole("button", { name: "Download backup" }));
    await waitFor(() => expect(held.count).toBe(2));
  });

  it("“Delete everything” takes one press at a time, and the next once it failed", async () => {
    const { srv } = useMockApi();
    srv.db.state.health.demo = false;
    const held = holdRequests((c) => c.method === "DELETE" && c.path === "/data");
    openSettings("data", true);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete everything…" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete everything?" });
    await user.type(within(dialog).getByLabelText("Type DELETE to confirm"), "DELETE");
    await expectOnePressAtATime({ user, button: () => within(dialog).getByRole("button", { name: "Delete everything" }), held });
  });
});

describe("calendar sync", () => {
  const card = async () => {
    openSettings("calendar");
    await screen.findByText("What your calendar gets");
    return screen.getByRole("region", { name: "Sync with your own calendar" });
  };

  it("“Find my calendars” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((c) => c.method === "POST" && c.path === "/calendar/sync/discover");
    const c = await card();
    const user = userEvent.setup();
    await user.type(within(c).getByLabelText("Calendar or server address"), "https://cloud.example.org");
    await user.type(within(c).getByLabelText("User name"), "sam");
    await user.type(within(c).getByLabelText("App password"), "abcd-efgh-ijkl-mnop");
    await expectOnePressAtATime({ user, button: () => within(c).getByRole("button", { name: "Find my calendars" }), held });
  });

  it("“Sync now” and “Disconnect” take one press at a time, and the next once they failed", async () => {
    const { srv } = useMockApi();
    await srv.handle("PUT", "/calendar/sync", new URLSearchParams(), { url: CALENDAR, username: "sam", password: "abcd-efgh-ijkl-mnop", mode: "discreet" }, null);
    const c = await card();
    const user = userEvent.setup();
    const syncing = holdRequests((r) => r.method === "POST" && r.path === "/calendar/sync/run");
    await within(c).findByRole("button", { name: "Sync now" });
    await expectOnePressAtATime({ user, button: () => within(c).getByRole("button", { name: "Sync now" }), held: syncing });
    await act(async () => syncing.release());
    const disconnecting = holdRequests((r) => r.method === "POST" && r.path === "/calendar/sync/disconnect");
    await user.click(within(c).getByRole("button", { name: "Disconnect…" }));
    const dialog = await screen.findByRole("dialog", { name: "Disconnect Ordnung?" });
    await expectOnePressAtATime({ user, button: () => within(dialog).getByRole("button", { name: "Disconnect" }), held: disconnecting });
  });
});
