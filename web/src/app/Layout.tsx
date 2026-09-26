import { useEffect } from "react";
import { Outlet, ScrollRestoration, useLocation, useNavigate, useNavigation } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { useHealth, useProfile } from "@/api/hooks";
import { useEventsConnection } from "@/api/sse";
import { ApiError } from "@/api/client";
import { Sidebar } from "@/components/shell/Sidebar";
import { TopBar } from "@/components/shell/TopBar";
import { MobileTabBar } from "@/components/shell/MobileTabBar";
import { DropZone } from "@/components/shell/DropZone";
import { UploadCenter } from "@/components/shell/UploadCenter";
import { PausedBanner } from "@/components/shell/PausedBanner";
import { PartyDrawer } from "@/features/party/PartyDrawer";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { PageMetaProvider, useDocumentTitle } from "@/components/shell/page-meta";
import { Toaster } from "@/components/ui/Toast";
import { DemoTour } from "@/features/tour/DemoTour";
import { useBrowserNotifications } from "@/features/notifications/useBrowserNotifications";
import { BootScreen, UnreachableScreen } from "./screens";

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
  const health = useHealth();

  if (health.isPending) return <BootScreen />;
  if (health.isError && !health.data) {
    const status = health.error instanceof ApiError ? health.error.status : undefined;
    return <UnreachableScreen onRetry={() => void health.refetch()} retrying={health.isFetching} status={status} />;
  }

  return (
    <PageMetaProvider>
      <AddLettersProvider>
        <DocumentTitleSync />
        <BrowserNotifications />
        <a
          href="#main"
          className="sr-only z-[100] rounded-lg bg-accent px-3 py-2 text-base font-medium text-on-accent focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
        >
          Skip to content
        </a>
        <NavigationProgress />
        <div className="flex min-h-dvh bg-canvas">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar />
            <PausedBanner />
            <main id="main" tabIndex={-1} className="flex-1 pb-[calc(5rem+env(safe-area-inset-bottom))] outline-none md:pb-0">
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
        <DemoTour />
        <ScrollRestoration getKey={(loc) => loc.pathname} />
      </AddLettersProvider>
    </PageMetaProvider>
  );
}
