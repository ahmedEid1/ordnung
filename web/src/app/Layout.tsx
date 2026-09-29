import { useEffect } from "react";
import { Outlet, ScrollRestoration, useLocation, useNavigate, useNavigation } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { useHealth, useProfile } from "@/api/hooks";
import { useEventsConnection } from "@/api/sse";
import { Sidebar } from "@/components/shell/Sidebar";
import { TopBar } from "@/components/shell/TopBar";
import { MobileTabBar } from "@/components/shell/MobileTabBar";
import { DropZone } from "@/components/shell/DropZone";
import { UploadCenter } from "@/components/shell/UploadCenter";
import { PausedBanner } from "@/components/shell/PausedBanner";
import { MockBanner } from "@/components/shell/MockBanner";
import { PartyDrawer } from "@/features/party/PartyDrawer";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { PageMetaProvider, useDocumentTitle } from "@/components/shell/page-meta";
import { useRecordOrigin } from "@/components/shell/origin";
import { Toaster } from "@/components/ui/Toast";
import { DemoTour } from "@/features/tour/DemoTour";
import { useBrowserNotifications } from "@/features/notifications/useBrowserNotifications";
import { BootScreen, HealthUnreachable } from "./screens";

/** Thin progress line while a lazy route loads. */
function NavigationProgress() {
  const navigation = useNavigation();
  const busy = navigation.state !== "idle";
  return (
    <AnimatePresence>
      {busy ? (
        <motion.div
          key="nav-progress"
          className="fixed inset-x-0 top-0 z-[95] h-0.5 origin-left bg-accent"
          initial={{ scaleX: 0, opacity: 1 }}
          animate={{ scaleX: 0.85, transition: { duration: 1.2, ease: "easeOut" } }}
          exit={{ scaleX: 1, opacity: 0, transition: { duration: 0.25 } }}
          aria-hidden
        />
      ) : null}
    </AnimatePresence>
  );
}

/**
 * "Skip to content": off screen until focused, then a pill over the top-left corner (moved with a
 * transform, not `sr-only`, so it keeps its padding). It moves focus itself — the static demo's
 * hash router would read `#main` as a page.
 */
function SkipLink() {
  return (
    <a
      href="#main"
      onClick={(e) => {
        e.preventDefault();
        document.getElementById("main")?.focus();
      }}
      className="fixed left-3 top-3 z-[100] -translate-y-[150%] whitespace-nowrap rounded-lg bg-accent px-3 py-2 text-base font-medium text-on-accent transition-transform focus:translate-y-0 focus:shadow-[var(--shadow-pop)] motion-reduce:transition-none"
    >
      Skip to content
    </a>
  );
}

function DocumentTitleSync() {
  useDocumentTitle();
  return null;
}

/** Opt-in browser notifications for dates due today/tomorrow (Settings → Reminders). */
function BrowserNotifications() {
  useBrowserNotifications();
  return null;
}

/** Redirect first-run users (not onboarded, not demo) to the welcome wizard. */
function useOnboardingRedirect() {
  const { data: health } = useHealth();
  const { data: profile } = useProfile();
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    if (!health || !profile) return;
    if (!health.demo && !profile.onboarded && location.pathname !== "/welcome") navigate("/welcome", { replace: true });
  }, [health, profile, location.pathname, navigate]);
}

/**
 * The app shell: sidebar (tab bar on phones), sticky top bar, "Claude paused" banner, page
 * outlet, global drop zone, upload progress + toasts, the People & organisations drawer and the
 * opt-in browser notifications.
 * Waits for `/api/health` so relative dates use the app's today (demo-safe).
 */
export function AppLayout() {
  useEventsConnection();
  useOnboardingRedirect();
  useRecordOrigin();
  const health = useHealth();

  // the splash only for the first load: a retry after a failure keeps the "isn't running" card
  // (TanStack resets a query without data to `pending` while it refetches)
  if (health.isPending && health.errorUpdateCount === 0) return <BootScreen />;
  if (!health.data) {
    return <HealthUnreachable error={health.error} retrying={health.isFetching} failures={health.errorUpdateCount} onRetry={() => void health.refetch()} />;
  }

  return (
    <PageMetaProvider>
      <AddLettersProvider>
        <DocumentTitleSync />
        <BrowserNotifications />
        <SkipLink />
        <NavigationProgress />
        <div className="flex min-h-dvh bg-canvas">
          <Sidebar />
          {/* fixed over the page, but here in the tab order: after the navigation, before the page */}
          <DemoTour />
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar />
            <MockBanner />
            <PausedBanner />
            <main id="main" tabIndex={-1} className="room-for-overlays flex flex-1 flex-col outline-none">
              <Outlet />
            </main>
          </div>
        </div>
        <MobileTabBar />
        <DropZone />
        <Toaster>
          <UploadCenter />
        </Toaster>
        <PartyDrawer />
        <ScrollRestoration getKey={(loc) => loc.pathname} />
      </AddLettersProvider>
    </PageMetaProvider>
  );
}
