/**
 * Routes. Pages are lazy-loaded from `src/pages/*` — each page file default-exports its
 * component. Route `handle.title` is the default top-bar title (pages can override it with
 * `<Page title>` / `usePageTitle`). The People & organisations drawer is URL state
 * (`?party=pty_x`, see `lib/party-drawer.ts`) and works on every route.
 */
import { createBrowserRouter, createHashRouter, type RouteObject } from "react-router";
import { isStaticDemo } from "@/mocks/mode";
import type { ComponentType } from "react";
import { AppLayout } from "./Layout";
import { BootScreen, NotFound, RouteError } from "./screens";
import type { RouteHandle } from "@/components/shell/page-meta";

type PageModule = { default: ComponentType };
const page = (load: () => Promise<PageModule>) => async () => ({ Component: (await load()).default });

export const routes: RouteObject[] = [
  {
    path: "/welcome",
    lazy: page(() => import("@/pages/WelcomePage")),
    errorElement: <RouteError fullScreen />,
    hydrateFallbackElement: <BootScreen />,
    handle: { title: "Welcome" } satisfies RouteHandle,
  },
  {
    // hand-off sync: bring Ordnung over from another computer instead of setting up a new one (outside the shell,
    // like /welcome: the onboarding redirect would bounce a computer that has nothing yet)
    path: "/join",
    lazy: page(() => import("@/pages/JoinPage")),
    errorElement: <RouteError fullScreen />,
    hydrateFallbackElement: <BootScreen />,
    handle: { title: "Bring Ordnung over" } satisfies RouteHandle,
  },
  {
    // a phone pairs here (the QR code's link, or the address typed): outside the shell, which needs a paired phone
    path: "/pair",
    lazy: page(() => import("@/pages/PairPage")),
    errorElement: <RouteError fullScreen />,
    hydrateFallbackElement: <BootScreen />,
    handle: { title: "Pair this phone" } satisfies RouteHandle,
  },
  {
    path: "/",
    element: <AppLayout />,
    errorElement: <RouteError fullScreen />,
    hydrateFallbackElement: <BootScreen />,
    children: [
      {
        // pathless boundary: a crashing page keeps the shell (sidebar, top bar) visible
        errorElement: <RouteError />,
        children: [
          { index: true, lazy: page(() => import("@/pages/TodayPage")), handle: { title: "Today" } satisfies RouteHandle },
          { path: "inbox", lazy: page(() => import("@/pages/InboxPage")), handle: { title: "Inbox" } satisfies RouteHandle },
          {
            path: "documents/:id",
            lazy: page(() => import("@/pages/DocumentPage")),
            handle: { title: "Letter", parent: { to: "/inbox", label: "Inbox" } } satisfies RouteHandle,
          },
          { path: "timeline", lazy: page(() => import("@/pages/TimelinePage")), handle: { title: "Timeline" } satisfies RouteHandle },
          { path: "contracts", lazy: page(() => import("@/pages/ContractsPage")), handle: { title: "Contracts" } satisfies RouteHandle },
          { path: "numbers", lazy: page(() => import("@/pages/NumbersPage")), handle: { title: "My numbers" } satisfies RouteHandle },
          {
            path: "week",
            lazy: page(() => import("@/pages/WeekPage")),
            handle: { title: "Weekly review", parent: { to: "/", label: "Today" } } satisfies RouteHandle,
          },
          { path: "letters", lazy: page(() => import("@/pages/LettersPage")), handle: { title: "Letters" } satisfies RouteHandle },
          {
            path: "letters/waiting",
            lazy: page(() => import("@/pages/WaitingPage")),
            handle: { title: "Waiting for", parent: { to: "/letters", label: "Letters" } } satisfies RouteHandle,
          },
          {
            path: "letters/:id",
            lazy: page(() => import("@/pages/LetterPage")),
            handle: { title: "Letter draft", parent: { to: "/letters", label: "Letters" } } satisfies RouteHandle,
          },
          {
            path: "letters/:id/proofs/:docId",
            lazy: page(() => import("@/pages/ProofFilePage")),
            handle: { title: "Proof", parent: { to: "/letters", label: "Letters" } } satisfies RouteHandle,
          },
          { path: "ask", lazy: page(() => import("@/pages/AskPage")), handle: { title: "Ask" } satisfies RouteHandle },
          { path: "settings", lazy: page(() => import("@/pages/SettingsPage")), handle: { title: "Settings" } satisfies RouteHandle },
          { path: "dev/ui", lazy: page(() => import("./DevUiPage")), handle: { title: "Design system" } satisfies RouteHandle },
          { path: "*", element: <NotFound />, handle: { title: "Not found" } satisfies RouteHandle },
        ],
      },
    ],
  },
];

/** The hosted static demo is a single file on a static host: routes live in the URL hash there. */
export function createAppRouter() {
  return isStaticDemo() ? createHashRouter(routes) : createBrowserRouter(routes);
}
