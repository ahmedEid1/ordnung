import { useCallback, useEffect, useRef, useState } from "react";
import { useBlocker, useSearchParams } from "react-router";
import { RotateCw, Save } from "lucide-react";
import { useHealth, useProfile, useSettings } from "@/api/hooks";
import { Page, PageHeader } from "@/components/shell/Page";
import { cn } from "@/lib/utils";
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
import { SettingsDirtyProvider, type SaveForm } from "@/features/settings/dirty";
import { SettingsNav } from "@/features/settings/SettingsNav";

/** Sections that fill the page column (tables); the others are forms at a readable width. */
const WIDE_SECTIONS = new Set<SectionId>(["privacy"]);

/** `/settings?section=…` — profile, region, reminders, calendar, AI, Claude, privacy, rules, data. */
export default function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const section = parseSection(params.get("section"));
  const profile = useProfile();
  const settings = useSettings();
  const health = useHealth();
  const paneRef = useRef<HTMLDivElement>(null);
  const firstRender = useRef(true);

  // Forms report unsaved edits and how to save them (their SaveBar); switching section or page asks first.
  const [dirtyForms, setDirtyForms] = useState<ReadonlyMap<string, SaveForm>>(() => new Map());
  const reportDirty = useCallback(
    (key: string, save: SaveForm | null) =>
      setDirtyForms((prev) => {
        if (save ? prev.get(key) === save : !prev.has(key)) return prev;
        const next = new Map(prev);
        if (save) next.set(key, save);
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

  // "Save and go": save every unsaved form, then go on. A form with a mistake (or a failed save)
  // stays: the dialog closes and focus goes to the highlighted field (a failed save's toast explains).
  const [savingAll, setSavingAll] = useState(false);
  const focusMistake = useRef(false);
  const saveAndGo = async () => {
    setSavingAll(true);
    try {
      for (const save of dirtyForms.values()) {
        if (await save()) continue;
        focusMistake.current = true;
        blocker.reset?.();
        return;
      }
      blocker.proceed?.();
    } finally {
      setSavingAll(false);
    }
  };
  // once the dialog has closed (and handed focus back to the page — its cleanup runs first)
  useEffect(() => {
    if (blocker.state === "blocked" || !focusMistake.current) return;
    focusMistake.current = false;
    paneRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [blocker.state]);

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
    if (!h.hasAttribute("tabindex")) h.setAttribute("tabindex", "-1");
    h.focus({ preventScroll: true });
    if (paneRef.current && paneRef.current.getBoundingClientRect().top < 64) paneRef.current.scrollIntoView?.({ block: "start" });
  }, [section]);

  const loading = profile.isPending || settings.isPending || health.isPending;
  const failed = profile.isError || settings.isError;

  return (
    <SettingsDirtyProvider value={reportDirty}>
      <Page title="Settings">
        <PageHeader title="Settings" description="Your details, reminders, the AI you use — and exactly what leaves this computer." />
        {/* The side list needs room next to the pane — measured on the page column, not the window (at
            1024 px the app's sidebar takes a quarter of the window): below 56rem the sections are pills on top. */}
        <div className="@container">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-6 @4xl:grid-cols-[220px_minmax(0,1fr)] @4xl:gap-10">
            <div className="min-w-0 @4xl:sticky @4xl:top-20 @4xl:self-start">
              <SettingsNav current={section} hrefFor={hrefFor} onNavigate={go} />
            </div>
            {/* forms keep a readable width in the shell's wide column; the privacy log's table uses all of it */}
            <div ref={paneRef} className={cn("min-w-0", !WIDE_SECTIONS.has(section) && "max-w-3xl")} key={section}>
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
        </div>

        <Dialog
          open={blocker.state === "blocked"}
          onClose={() => blocker.reset?.()}
          // md: three buttons side by side from `sm`
          size="md"
          title="Save your changes?"
          description={
            <>
              You changed something in <span className="font-medium text-ink">{SECTION_LABELS[section]}</span> and haven't saved it
              {leavingSection ? <> — going to {SECTION_LABELS[leavingSection]} without saving throws it away.</> : <> — leaving Settings without saving throws it away.</>}
            </>
          }
          footer={
            <>
              <Button variant="ghost" className="text-danger-ink hover:bg-danger-soft hover:text-danger-ink sm:mr-auto" onClick={() => blocker.proceed?.()} disabled={savingAll}>
                Discard changes
              </Button>
              <Button onClick={() => blocker.reset?.()} disabled={savingAll}>
                Keep editing
              </Button>
              <Button variant="primary" icon={Save} onClick={() => void saveAndGo()} loading={savingAll}>
                Save and go
              </Button>
            </>
          }
        />
      </Page>
    </SettingsDirtyProvider>
  );
}
