/**
 * Settings → Claude connection → Model (mock API): the field shows the model every call runs on,
 * Sonnet 5 by default; an edit is unsaved until Save (trimmed) or Discard; a name the server refuses
 * is shown under the field, focused, and nothing is saved.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import SettingsPage from "@/pages/SettingsPage";
import { DEFAULT_MODEL } from "./ClaudeSection";

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

const renderClaude = () => renderWithProviders(<SettingsPage />, { route: "/settings?section=claude" });

describe("Settings → Claude → Model", () => {
  it("shows the model every call runs on — Sonnet 5 by default — and what else it may be", async () => {
    useMockApi();
    renderClaude();
    const field = await screen.findByRole("textbox", { name: "Model" });
    expect(DEFAULT_MODEL).toBe("claude-sonnet-5");
    expect(field).toHaveValue("claude-sonnet-5");
    expect(field).toHaveAttribute("placeholder", DEFAULT_MODEL);
    expect(field).toHaveAccessibleDescription("Sonnet 5 by default: claude-sonnet-5. Any model id or alias Claude Code accepts, for example claude-opus-5-5 or sonnet.");
    expect(screen.getByText("The demo and the benchmarks keep the model they were recorded with.")).toBeInTheDocument();
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });

  it("an edit is unsaved until Save, and Discard puts the saved model back", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderClaude();
    const field = await screen.findByRole("textbox", { name: "Model" });
    await user.clear(field);
    await user.type(field, "claude-opus-5-5");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(field).toHaveValue("claude-sonnet-5");
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    expect(calls.find((c) => c.method === "PUT" && c.path === "/settings")).toBeUndefined();
  });

  it("saves the model trimmed and says every call runs on it from now on", async () => {
    const { srv, calls } = useMockApi();
    const user = userEvent.setup();
    renderClaude();
    const field = await screen.findByRole("textbox", { name: "Model" });
    await user.clear(field);
    await user.type(field, "  claude-opus-5-5 ");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Every call to Claude runs on claude-opus-5-5 from now on\./)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT" && c.path === "/settings")?.body).toEqual({ model: "claude-opus-5-5" });
    expect(srv.db.state.settings.model).toBe("claude-opus-5-5");
    expect(field).toHaveValue("claude-opus-5-5");
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });

  it("a name Claude Code can't take is refused under the field, focused, and nothing is saved", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    renderClaude();
    const field = await screen.findByRole("textbox", { name: "Model" });
    await user.clear(field);
    await user.type(field, "claude opus 5 5");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
    expect(field).toHaveAccessibleDescription("A model is named with letters, digits, dots and dashes only — no spaces — like claude-sonnet-5.");
    await waitFor(() => expect(field).toHaveFocus());
    expect(screen.getByText("Fix the highlighted field to save")).toBeInTheDocument();
    expect(srv.db.state.settings.model).toBe("claude-sonnet-5");
    // typing again clears the reason; an empty name is refused too
    await user.clear(field);
    expect(field).not.toHaveAttribute("aria-invalid");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(field).toHaveAccessibleDescription("Enter a model id or alias, like claude-sonnet-5 or sonnet."));
    expect(srv.db.state.settings.model).toBe("claude-sonnet-5");
  });
});
