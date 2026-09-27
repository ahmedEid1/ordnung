import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import SettingsPage from "@/pages/SettingsPage";
import { NOTIFY_ENABLED_KEY } from "@/features/notifications/notify";
import { leavesSection } from "./logic";

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

class FakeNotification {
  static permission: NotificationPermission = "default";
  static requestPermission = vi.fn(async () => FakeNotification.permission);
  static shown: string[] = [];
  onclick: (() => void) | null = null;
  constructor(public title: string) {
    FakeNotification.shown.push(title);
  }
  close() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", RO);
  vi.stubGlobal("scrollTo", () => {});
  localStorage.clear();
  FakeNotification.permission = "default";
  FakeNotification.shown = [];
  vi.stubGlobal("Notification", FakeNotification);
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  act(() => __clearToasts());
});

describe("unsaved edits", () => {
  it("only switching section or page leaves them behind", () => {
    const at = (pathname: string, search = "") => ({ pathname, search });
    expect(leavesSection(at("/settings", "?section=profile"), at("/settings", "?section=data"))).toBe(true);
    expect(leavesSection(at("/settings"), at("/settings", "?section=profile"))).toBe(false);
    expect(leavesSection(at("/settings", "?section=profile"), at("/settings", "?section=profile&party=pty_x"))).toBe(false);
    expect(leavesSection(at("/settings", "?section=profile"), at("/inbox"))).toBe(true);
  });

  it("warns before switching sections, keeps the edit or throws it away", async () => {
    useMockApi();
    const user = userEvent.setup();
    const { router } = renderWithProviders(<SettingsPage />, { route: "/settings?section=profile" });
    const name = await screen.findByLabelText("Full name");
    await user.clear(name);
    await user.type(name, "Sam R.");
    const nav = screen.getByRole("navigation", { name: "Settings sections" });

    await user.click(within(nav).getByRole("link", { name: "Reminders" }));
    const dialog = await screen.findByRole("dialog", { name: "Save your changes?" });
    expect(dialog).toHaveTextContent("You changed something in Profile & address and haven't saved it — going to Reminders without saving throws it away.");
    await user.click(within(dialog).getByRole("button", { name: "Keep editing" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument(), { timeout: 3000 });
    expect(router.state.location.search).toBe("?section=profile");
    expect(screen.getByLabelText("Full name")).toHaveValue("Sam R.");

    await user.click(within(nav).getByRole("link", { name: "Reminders" }));
    await user.click(within(await screen.findByRole("dialog", { name: "Save your changes?" })).getByRole("button", { name: "Discard changes" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Reminders" })).toBeInTheDocument();
    expect(router.state.location.search).toBe("?section=reminders");

    // nothing unsaved any more: no question asked
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument(), { timeout: 3000 });
    await user.click(within(nav).getByRole("link", { name: "Data" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Data" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("saving clears the warning", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=profile" });
    await user.type(await screen.findByLabelText(/^Phone/), "1");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByText("Saved.");
    await user.click(within(screen.getByRole("navigation", { name: "Settings sections" })).getByRole("link", { name: "Calendar" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Calendar" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Reminders → notifications in this browser", () => {
  it("asks the browser, confirms with a test notification and can be turned off", async () => {
    useMockApi();
    FakeNotification.requestPermission.mockImplementationOnce(async () => {
      FakeNotification.permission = "granted";
      return "granted";
    });
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=reminders" });
    const toggle = await screen.findByRole("switch", { name: /^Notify me in this browser while Ordnung is open/ });
    expect(toggle).toHaveAttribute("aria-checked", "false");

    await user.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(localStorage.getItem(NOTIFY_ENABLED_KEY)).toBe("true");
    expect(FakeNotification.shown).toEqual(["Ordnung can notify you"]);
    await user.click(screen.getByRole("button", { name: "Send a test notification" }));
    expect(FakeNotification.shown).toHaveLength(2);

    await user.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    expect(localStorage.getItem(NOTIFY_ENABLED_KEY)).toBeNull();
  });

  it("explains a browser that blocks them", async () => {
    useMockApi();
    FakeNotification.permission = "denied";
    renderWithProviders(<SettingsPage />, { route: "/settings?section=reminders" });
    expect(await screen.findByRole("switch", { name: /^Notify me in this browser while Ordnung is open/ })).toBeDisabled();
    expect(screen.getByRole("note")).toHaveTextContent("Notifications are blocked for this site");
  });
});

describe("Data → delete everything", () => {
  it("needs the typed word, then wipes everything and starts over", async () => {
    const { srv, calls } = useMockApi();
    srv.db.state.health.demo = false;
    const client = makeTestQueryClient();
    client.setQueryData(qk.health, { ...TEST_HEALTH, demo: false });
    const user = userEvent.setup();
    const { router } = renderWithProviders(
      <>
        <SettingsPage />
        <Toaster />
      </>,
      { route: "/settings?section=data", client },
    );

    await user.click(await screen.findByRole("button", { name: "Delete everything…" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete everything?" });
    const confirm = within(dialog).getByRole("button", { name: "Delete everything" });
    expect(confirm).toBeDisabled();
    const input = within(dialog).getByLabelText("Type DELETE to confirm");
    await user.type(input, "delet");
    expect(confirm).toBeDisabled();
    // the word in any case (a keyboard types "delete"); the API still gets "DELETE"
    await user.type(input, "e");
    expect(confirm).toBeEnabled();
    await user.clear(input);
    await user.type(input, "DELETE");
    expect(confirm).toBeEnabled();

    await user.click(confirm);

    await waitFor(() => expect(router.state.location.pathname).toBe("/welcome"));
    expect(calls.find((c) => c.method === "DELETE" && c.path === "/data")?.body).toEqual({ confirm: "DELETE" });
    expect(await screen.findByText("Everything was deleted")).toBeInTheDocument();
    expect(srv.db.state.documents).toEqual([]);
    expect(srv.db.state.profile.onboarded).toBe(false);
  });

  it("the demo offers a calm “Start over” instead of a danger zone", async () => {
    useMockApi();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=data" });
    const reset = await screen.findByRole("region", { name: "Start over" });
    expect(reset).toHaveTextContent(/This is the demo, so there is nothing of yours to delete/);
    expect(within(reset).getByRole("button", { name: /Copy command to reset the demo/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Delete everything" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete everything…" })).not.toBeInTheDocument();
  });

  it("the online demo starts over by reloading", async () => {
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    useMockApi({ staticDemo: true });
    renderWithProviders(<SettingsPage />, { route: "/settings?section=data" });
    const reset = await screen.findByRole("region", { name: "Start over" });
    expect(reset).toHaveTextContent("This online demo keeps nothing you do in it.");
    expect(within(reset).getByRole("button", { name: "Start over" })).toBeInTheDocument();
    expect(within(reset).queryByRole("button", { name: /Copy command/ })).not.toBeInTheDocument();
    vi.unstubAllEnvs();
  });

  it("shows the whole data folder path, wrapping after each “/”", async () => {
    const { srv } = useMockApi();
    const path = "/Users/samantha-rivera-musterfrau/Library/Application Support/Ordnung/data";
    srv.db.state.health.data_dir = path;
    const client = makeTestQueryClient();
    client.setQueryData(qk.health, { ...TEST_HEALTH, data_dir: path });
    renderWithProviders(<SettingsPage />, { route: "/settings?section=data", client });
    const where = await screen.findByRole("region", { name: "Where your data lives" });
    const code = within(where).getByText((_, el) => el?.tagName === "CODE");
    expect(code.textContent).toBe(path);
    expect(code.querySelectorAll("wbr")).toHaveLength(path.split("/").length - 1);
    // no sideways scrolling box that cuts the path off
    expect(code.className).not.toMatch(/overflow-x-auto|whitespace-nowrap/);
    expect(within(where).getByRole("button", { name: "Copy the folder path" })).toBeInTheDocument();
  });
});

describe("refund IBAN", () => {
  it("flags a wrong IBAN once you leave it, won't save it, and saves a right one without spaces", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />, { route: "/settings?section=profile" });
    const iban = await screen.findByLabelText(/IBAN for refunds/);
    await user.type(iban, "DE89 3704 0044 0532 0130 01");
    expect(iban).not.toHaveAttribute("aria-invalid");
    await user.tab();
    expect(iban).toHaveAttribute("aria-invalid", "true");
    expect(iban).toHaveAccessibleDescription(/That IBAN isn't valid/);
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByText("Fix the highlighted field to save")).toBeInTheDocument();
    await waitFor(() => expect(iban).toHaveFocus());
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
    await user.clear(iban);
    await user.type(iban, "de89 3704 0044 0532 0130 00");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === "/profile")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ iban: "DE89370400440532013000" });
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(iban).toHaveValue("DE89 3704 0044 0532 0130 00");
  });
});
