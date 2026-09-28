/**
 * Settings → Watched folder (mock API): the folder's status and last files, the server's reason under
 * the path field (focused, nothing saved), Ordnung's own inbox folder in one click, the auto-read
 * switch with its honest caveat, and stopping.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import SettingsPage from "@/pages/SettingsPage";
import { SECTION_IDS, SECTION_LABELS } from "./logic";

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

const renderFolder = () => renderWithProviders(<SettingsPage />, { route: "/settings?section=folder" });

describe("Settings → Watched folder", () => {
  it("is a section of its own, next to Calendar", () => {
    expect(SECTION_IDS.indexOf("folder")).toBe(SECTION_IDS.indexOf("calendar") + 1);
    expect(SECTION_LABELS.folder).toBe("Watched folder");
  });

  it("shows the folder, that it is watched, the letters waiting and what became of the last files", async () => {
    useMockApi();
    renderFolder();
    expect(await screen.findByRole("heading", { level: 2, name: "Watched folder" })).toBeInTheDocument();
    expect(screen.getByLabelText("Folder")).toHaveValue("/home/sam/Scans");
    const status = await screen.findByRole("region", { name: "Status" });
    expect(await within(status).findByText("Watching")).toBeInTheDocument();
    expect(within(status).getByRole("link", { name: /3 letters not read yet in the Inbox/ })).toHaveAttribute("href", "/inbox");
    const recent = within(status).getByRole("list", { name: "Last files from the folder" });
    const rows = within(recent).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(within(rows[0]!).getByRole("link", { name: "Scan_2026-09-28_0914.pdf" })).toHaveAttribute("href", "/documents/doc_folder_scan");
    expect(within(rows[0]!).getByText("Not read yet")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Already in Ordnung")).toBeInTheDocument();
    expect(within(rows[3]!).getByText(/^Not added — this PDF could not be opened/)).toBeInTheDocument();
    expect(within(rows[3]!).queryByRole("link")).toBeNull();
  });

  it("says honestly what reading at once means, including a cloud-synced folder", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderFolder();
    const auto = await screen.findByRole("switch", { name: /Read new files with Claude straight away/ });
    expect(auto).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText(/nothing is sent to Claude before that/)).toBeInTheDocument();
    // only later arrivals are read at once: the files already there still wait
    expect(screen.getByText(/files that arrive in the folder from now on are sent to Claude.*The files already in the folder when you choose it.*still wait unread/)).toBeInTheDocument();
    expect(screen.getByText("A cloud-synced folder is already shared")).toBeInTheDocument();
    const status = await screen.findByRole("region", { name: "Status" });
    expect(await within(status).findByText("New files wait unread before anything is sent to Claude.")).toBeInTheDocument();
    await user.click(auto);
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    // the note says what changed: only the switch
    expect(await screen.findByText(/New files from the folder are read with Claude from now on\./)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT" && c.path === "/settings")?.body).toEqual({ inbox_dir: "/home/sam/Scans", inbox_auto_read: true });
    expect(await within(status).findByText("New files are read with Claude as soon as they arrive.")).toBeInTheDocument();
  });

  it("in the online demo, says files always wait whatever the switch says", async () => {
    useMockApi({ staticDemo: true });
    renderFolder();
    const auto = await screen.findByRole("switch", { name: /Read new files with Claude straight away/ });
    expect(auto).toBeInTheDocument();
    expect(await screen.findByText(/This demo reads no new letters with Claude: files from the folder always wait/)).toBeInTheDocument();
    const status = await screen.findByRole("region", { name: "Status" });
    expect(await within(status).findByText("New files wait unread — this demo reads nothing with Claude.")).toBeInTheDocument();
  });

  it("the status's load error sits in its card as a plain level-3 message", async () => {
    const { srv } = useMockApi();
    const handle = srv.handle.bind(srv);
    vi.spyOn(srv, "handle").mockImplementation((method, path, ...rest) =>
      path === "/folder" ? Promise.resolve(new Response(JSON.stringify({ detail: "boom" }), { status: 500 })) : handle(method, path, ...rest),
    );
    renderFolder();
    const status = await screen.findByRole("region", { name: "Status" });
    const heading = await within(status).findByRole("heading", { name: "Couldn't load the folder's status" }, { timeout: 5000 });
    expect(heading.tagName).toBe("H3");
  });

  it("shows the server's reason under the field, focuses it, and saves nothing", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    renderFolder();
    const field = await screen.findByLabelText("Folder");
    await user.clear(field);
    await user.type(field, "Scans");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
    expect(field).toHaveAccessibleDescription("Please choose a full folder path (for example /home/you/Scans).");
    await waitFor(() => expect(field).toHaveFocus());
    expect(srv.db.state.settings.inbox_dir).toBe("/home/sam/Scans");
    // typing again clears the reason
    await user.type(field, "/");
    expect(field).not.toHaveAttribute("aria-invalid");
  });

  it("offers Ordnung's own inbox folder in one click", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderFolder();
    expect(await screen.findByRole("button", { name: "Copy the inbox folder's path" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /Use Ordnung's own inbox folder/ }));
    const field = screen.getByLabelText("Folder");
    expect(field).toHaveValue("/home/sam/.local/share/ordnung-demo/inbox");
    expect(screen.queryByRole("button", { name: /Use Ordnung's own inbox folder/ })).toBeNull();
    // the button went: focus is on the field it filled, not lost to the page
    await waitFor(() => expect(field).toHaveFocus());
    expect(screen.getByText(/File pickers often hide this folder/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && (c.body as { inbox_dir?: string }).inbox_dir === "/home/sam/.local/share/ordnung-demo/inbox")).toBe(true));
  });

  it("stops watching: the status says so and the folder's files stay where they are", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderFolder();
    const status = await screen.findByRole("region", { name: "Status" });
    await user.click(await within(status).findByRole("button", { name: "Stop watching" }));
    expect(await within(status).findByText(/No folder is watched/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ inbox_dir: null });
    await waitFor(() => expect(screen.getByLabelText("Folder")).toHaveValue(""));
    // the button went: focus is on the (now empty) folder field, not lost to the page
    await waitFor(() => expect(screen.getByLabelText("Folder")).toHaveFocus());
  });

  it("with no folder and nothing picked up, the list says what it will show", async () => {
    const { srv } = useMockApi();
    srv.db.state.settings.inbox_dir = null;
    srv.db.state.folderRecent = [];
    renderFolder();
    const status = await screen.findByRole("region", { name: "Status" });
    expect(await within(status).findByText("Nothing picked up yet. Once a folder is watched, the files it brings in are listed here.")).toBeInTheDocument();
  });
});
