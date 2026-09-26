/**
 * States every server-backed target has: the Settings sections, loading skeletons and error
 * states (made deterministic with route interception), and the full-screen shell states.
 */
import { failApi, fakeApi, holdApi, intentional, pinToasts, settle } from "../browser.mjs";

/** `features/settings/logic.ts` SECTION_IDS → SECTION_LABELS */
export const SETTINGS_SECTIONS = {
  profile: "Profile & address",
  region: "Region & language",
  reminders: "Reminders",
  calendar: "Calendar",
  ai: "AI & models",
  claude: "Claude connection",
  privacy: "Privacy & AI usage",
  rules: "How dates are computed",
  data: "Data",
};

export function commonSettingsSections(group, prefix = "settings") {
  return Object.entries(SETTINGS_SECTIONS).map(([id, label]) => ({
    id: `${prefix}-${id}`,
    group,
    route: `/settings?section=${id}`,
    how: `open /settings?section=${id}`,
    description: `Settings → ${label}.`,
    run: (c) => c.goto(`/settings?section=${id}`),
  }));
}

const PAGES = (docId, draftId) =>
  [
    ["today", "/"],
    ["inbox", "/inbox"],
    ["timeline", "/timeline"],
    ["contracts", "/contracts"],
    ["letters", "/letters"],
    ["ask", "/ask"],
    ["settings", "/settings"],
    docId ? ["document", `/documents/${docId}`] : null,
    draftId ? ["letter", `/letters/${draftId}`] : null,
  ].filter(Boolean);

/**
 * `loading-*`: every API request except /api/health (and the event stream) is held → skeletons.
 * `error-*`: every API request except /api/health fails with HTTP 500 (after the app's retries).
 * Plus the full-screen boot / unreachable / no-session / route-error screens and the offline toast.
 */
export function loadingAndErrorStates({ docId, draftId, group = "shell-and-overlays", prefix = "" } = {}) {
  const out = [];
  for (const [name, path] of PAGES(docId, draftId)) {
    out.push({
      id: `${prefix}loading-${name}`,
      group,
      route: path,
      how: `open ${path} with every API request except /api/health held (never answered)`,
      description: `Loading skeleton of ${name}.`,
      idle: false,
      run: async (c) => {
        await holdApi(c.page);
        await c.goto(path, { heading: false, idle: false });
        await c.page.locator("[aria-busy=true], [aria-busy]").first().waitFor({ state: "attached", timeout: 6000 }).catch(() => c.note("no aria-busy element while loading"));
        await c.wait(400);
        await settle(c.page, { idle: false });
      },
    });
    out.push({
      id: `${prefix}error-${name}`,
      group,
      route: path,
      how: `open ${path} with every API request except /api/health answered with HTTP 500 (wait for the app's retries)`,
      description: `Error state of ${name} (server errors).`,
      run: async (c) => {
        await failApi(c.page, { status: 500 });
        await c.goto(path, { heading: false, idle: false });
        await c.wait(4000);
        await settle(c.page);
      },
    });
  }
  out.push({
    id: `${prefix}boot-screen`,
    group,
    route: "/",
    how: "open / with /api/health held",
    description: "The boot splash (health check pending).",
    idle: false,
    run: async (c) => {
      await holdApi(c.page, { only: ["/api/health"], except: [] });
      await c.goto("/", { heading: false, idle: false });
      await c.wait(600);
      await settle(c.page, { idle: false });
    },
  });
  out.push({
    id: `${prefix}unreachable`,
    group,
    route: "/",
    how: "open / with /api/health answered with HTTP 500 (after retries)",
    description: "“Ordnung isn't running” full-screen state.",
    run: async (c) => {
      await failApi(c.page, { status: 500, only: ["/api/health"], except: [] });
      await c.goto("/", { heading: false, idle: false });
      await c.page.getByRole("heading", { level: 1 }).waitFor({ timeout: 15_000 }).catch(() => c.note("no heading on the unreachable screen"));
      await settle(c.page);
    },
  });
  out.push({
    id: `${prefix}no-session`,
    group,
    route: "/",
    how: "open / with /api/health answered with HTTP 401",
    description: "“Please open Ordnung from its link” (no session).",
    run: async (c) => {
      await failApi(c.page, { status: 401, only: ["/api/health"], except: [] });
      await c.goto("/", { heading: false, idle: false });
      await c.page.getByRole("heading", { level: 1 }).waitFor({ timeout: 15_000 }).catch(() => c.note("no heading on the no-session screen"));
      await settle(c.page);
    },
  });
  out.push({
    id: `${prefix}route-error`,
    group,
    route: "/inbox",
    how: "open /inbox with GET /api/documents answered with an object instead of a list (the page crashes)",
    description: "The in-shell “Something went wrong on this page” screen.",
    expectErrorScreen: true,
    run: async (c) => {
      await fakeApi(c.page, "GET", /^\/api\/documents$/, async () => ({ json: { unexpected: "not a list" } }));
      c.expectErrorScreen = true;
      await c.goto("/inbox", { heading: false });
      await c.page.getByRole("heading", { name: /Something went wrong/ }).waitFor({ timeout: 10_000 }).catch(() => c.note("the page didn't crash"));
      await settle(c.page);
    },
  });
  out.push({
    id: `${prefix}offline-toast`,
    group,
    route: "/",
    how: "open /, then the API stops answering (connection refused) and the live-events stream reconnects, which refetches",
    description: "The “Can't reach Ordnung — showing the last known data” toast.",
    pinToasts: true,
    run: async (c) => {
      let offline = false;
      await c.page.route(
        (url) => new URL(url.href).pathname.startsWith("/api/"),
        async (route) => {
          const path = new URL(route.request().url()).pathname;
          if (path === "/api/events") {
            intentional.add(route.request());
            return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: `retry: ${offline ? 3600000 : 1200}\n\n` });
          }
          if (!offline) return route.fallback();
          intentional.add(route.request());
          return route.abort("connectionrefused");
        },
      );
      await c.goto("/");
      offline = true;
      await c.page.getByText("Can't reach Ordnung").first().waitFor({ timeout: 15_000 }).catch(() => c.note("no offline toast appeared"));
      await pinToasts(c.page);
      await settle(c.page, { idle: false });
    },
  });
  return out;
}
