import { useCallback, useEffect, useRef, useState } from "react";
import { useBlocker, useSearchParams } from "react-router";
import { RotateCw } from "lucide-react";
import { useHealth, useProfile, useSettings } from "@/api/hooks";
import { Page, PageHeader } from "@/components/shell/Page";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { AiSection } from "@/features/settings/AiSection";
import { CalendarSection } from "@/features/settings/CalendarSection";
import { ClaudeSection } from "@/features/settings/ClaudeSection";
import { DataSection } from "@/features/settings/DataSection";
import { leavesSection, parseSection, SECTION_LABELS, type SectionId } from "@/features/settings/logic";
import { PrivacySection } from "@/features/settings/PrivacySection";
import { ProfileSection } from "@/features/settings/ProfileSection";
import { RegionSection } from "@/features/settings/RegionSection";
import { RemindersSection } from "@/features/settings/RemindersSection";
import { RulesSection } from "@/features/settings/RulesSection";
import { SettingsDirtyProvider } from "@/features/settings/dirty";
import { SettingsNav } from "@/features/settings/SettingsNav";

/** `/settings?section=…` — profile, region, reminders, calendar, AI, Claude, privacy, rules, data. */
export default function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const section = parseSection(params.get("section"));
  const profile = useProfile();
  const settings = useSettings();
  const health = useHealth();
  const paneRef = useRef<HTMLDivElement>(null);
  const firstRender = useRef(true);

  // Forms report unsaved edits (their SaveBar); switching section or page asks first.
  const [dirtyForms, setDirtyForms] = useState<ReadonlySet<string>>(() => new Set());
  const reportDirty = useCallback(
    (key: string, dirty: boolean) =>
      setDirtyForms((prev) => {
        if (prev.has(key) === dirty) return prev;
        const next = new Set(prev);
        if (dirty) next.add(key);
        else next.delete(key);
        return next;
      }),
    [],
  );
  const dirty = dirtyForms.size > 0;
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && leavesSection(currentLocation, nextLocation));
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);
  const leavingTo = blocker.state === "blocked" ? blocker.location : null;
  const leavingSection = leavingTo && leavingTo.pathname === "/settings" ? parseSection(new URLSearchParams(leavingTo.search).get("section")) : null;

  const hrefFor = useCallback((id: SectionId) => `/settings?section=${id}`, []);
  const go = useCallback(
    (id: SectionId) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("section", id);
          return next;
        },
        { preventScrollReset: true },
      ),
    [setParams],
  );

  // moving to another section: focus its heading (keyboard / screen readers) without jumping
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    const h = paneRef.current?.querySelector<HTMLElement>("h2");
    if (!h) return;
    h.setAttribute("tabindex", "-1");
    h.focus({ preventScroll: true });
    if (paneRef.current && paneRef.current.getBoundingClientRect().top < 64) paneRef.current.scrollIntoView?.({ block: "start" });
  }, [section]);

  const loading = profile.isPending || settings.isPending || health.isPending;
  const failed = profile.isError || settings.isError;

  return (
    <SettingsDirtyProvider value={reportDirty}>
      <Page title="Settings" width="default">
        <PageHeader title="Settings" description="Your details, reminders, the AI you use — and exactly what leaves this computer." />
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[220px_minmax(0,1fr)] lg:gap-10">
          <div className="min-w-0 lg:sticky lg:top-20 lg:self-start">
            <SettingsNav current={section} hrefFor={hrefFor} onNavigate={go} />
          </div>
          <div ref={paneRef} className="min-w-0 scroll-mt-20" key={section}>
            {loading ? (
              <div aria-busy="true">
                <LoadingLabel>Loading your settings…</LoadingLabel>
                <Skeleton className="h-7 w-56" />
                <Skeleton className="mt-3 h-4 w-80 max-w-full" />
                <div className="card mt-6 p-6">
                  <SkeletonText lines={6} />
                </div>
              </div>
            ) : failed || !profile.data || !settings.data || !health.data ? (
              <EmptyState
                illustration="error"
                title="Couldn't load your settings"
                description="Is Ordnung still running on this computer?"
                action={
                  <Button
                    icon={RotateCw}
                    onClick={() => {
                      void profile.refetch();
                      void settings.refetch();
                    }}
                  >
                    Try again
                  </Button>
                }
              />
            ) : section === "profile" ? (
              <ProfileSection profile={profile.data} />
            ) : section === "region" ? (
              <RegionSection profile={profile.data} />
            ) : section === "reminders" ? (
              <RemindersSection profile={profile.data} />
            ) : section === "calendar" ? (
              <CalendarSection />
            ) : section === "ai" ? (
              <AiSection settings={settings.data} profile={profile.data} />
            ) : section === "claude" ? (
              <ClaudeSection health={health.data} />
            ) : section === "privacy" ? (
              <PrivacySection />
            ) : section === "rules" ? (
              <RulesSection />
            ) : (
              <DataSection health={health.data} />
            )}
          </div>
        </div>

        <Dialog
          open={blocker.state === "blocked"}
          onClose={() => blocker.reset?.()}
          size="sm"
          title="Discard your changes?"
          description={
            <>
              You changed something in <span className="font-medium text-ink">{SECTION_LABELS[section]}</span> and haven't saved it
              {leavingSection ? <> — going to {SECTION_LABELS[leavingSection]} throws it away.</> : <> — leaving Settings throws it away.</>}
            </>
          }
          footer={
            <>
              <Button onClick={() => blocker.reset?.()}>Keep editing</Button>
              <Button variant="danger" onClick={() => blocker.proceed?.()}>
                Discard changes
              </Button>
            </>
          }
        />
      </Page>
    </SettingsDirtyProvider>
  );
}
