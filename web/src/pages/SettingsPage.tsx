import { useCallback, useEffect, useRef, useState } from "react";
import { useBlocker, useLocation, useSearchParams } from "react-router";
import { Save } from "lucide-react";
import { useHealth, useProfile, useSettings } from "@/api/hooks";
import { Page, PageHeader } from "@/components/shell/Page";
import { useStickyError } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel, Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { AiSection } from "@/features/settings/AiSection";
import { CalendarSection } from "@/features/settings/CalendarSection";
import { ClaudeSection } from "@/features/settings/ClaudeSection";
import { ComputersSection } from "@/features/settings/ComputersSection";
import { DataSection } from "@/features/settings/DataSection";
import { FolderSection } from "@/features/settings/FolderSection";
import { leavesSection, parseSection, SECTION_LABELS, type SectionId } from "@/features/settings/logic";
import { PhoneSection } from "@/features/settings/PhoneSection";
import { PhoneSettingsNotice } from "@/features/settings/PhoneSettingsNotice";
import { PrivacySection } from "@/features/settings/PrivacySection";
import { usePhoneCompanion } from "@/features/phone/client";
import { ProfileSection } from "@/features/settings/ProfileSection";
import { RegionSection } from "@/features/settings/RegionSection";
import { RemindersSection } from "@/features/settings/RemindersSection";
import { RulesSection } from "@/features/settings/RulesSection";
import { SettingsDirtyProvider, type SaveForm } from "@/features/settings/dirty";
import { SettingsNav } from "@/features/settings/SettingsNav";

/** Sections that fill the page column (tables); the others are forms at a readable width. */
const WIDE_SECTIONS = new Set<SectionId>(["privacy"]);

/**
 * `/settings?section=…` — profile, region, reminders, calendar, watched folder, phone, AI, Claude, privacy, rules,
 * your computers (hand-off sync), data. On a paired phone: that settings are on the computer (asking for none of
 * them — the phone may not).
 */
export default function SettingsPage() {
  return usePhoneCompanion() ? <PhoneSettings /> : <ComputerSettings />;
}

/** Settings on a paired phone: no section, no settings query (the API refuses them there). */
function PhoneSettings() {
  return (
    <Page title="Settings">
      <PhoneSettingsNotice />
    </Page>
  );
}

function ComputerSettings() {
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
          // the privacy log's "one phone only" belongs to that section
          next.delete("device");
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

  const loaded = Boolean(profile.data && settings.data && health.data);
  // a link to one card (`?section=data#set-data-reset`, Ask's "Start the demo over"): once the section is drawn, the
  // card scrolls into view and its title takes focus, so the keyboard and screen readers start there too
  const { hash } = useLocation();
  const target = loaded ? hash.slice(1) : "";
  useEffect(() => {
    const title = target ? document.getElementById(target) : null;
    if (!title || !paneRef.current?.contains(title)) return;
    if (!title.hasAttribute("tabindex")) title.setAttribute("tabindex", "-1");
    title.focus({ preventScroll: true });
    (title.closest("section") ?? title).scrollIntoView?.({ block: "start" });
  }, [target, section]);
  // a failed load stays on screen, worded the same, while "Try again" runs (the retry of a failed load starts
  // over as "pending"); a background refresh that fails keeps the loaded forms (the app's toast says so)
  const loadError = useStickyError(profile.error ?? settings.error ?? health.error, loaded);
  const failed = !loaded && Boolean(loadError);
  // what "Try again" asks for again (and spins for): the queries with nothing loaded
  const unloaded = [profile, settings, health].filter((q) => !q.data);

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
              {failed ? (
                // the shared error card, as on every other page: a primary "Try again" that spins while it asks
                // again, and the technical details behind a disclosure
                <LoadError
                  what="your settings"
                  error={loadError}
                  onRetry={() => {
                    for (const q of unloaded) void q.refetch();
                  }}
                  retrying={unloaded.some((q) => q.isFetching)}
                />
              ) : !profile.data || !settings.data || !health.data ? (
                <div aria-busy="true">
                  <LoadingLabel>Loading your settings…</LoadingLabel>
                  <Skeleton className="h-7 w-56" />
                  <Skeleton className="mt-3 h-4 w-80 max-w-full" />
                  <div className="card mt-6 p-6">
                    <SkeletonText lines={6} />
                  </div>
                </div>
              ) : section === "profile" ? (
                <ProfileSection profile={profile.data} />
              ) : section === "region" ? (
                <RegionSection profile={profile.data} />
              ) : section === "reminders" ? (
                <RemindersSection profile={profile.data} />
              ) : section === "calendar" ? (
                <CalendarSection />
              ) : section === "folder" ? (
                <FolderSection settings={settings.data} />
              ) : section === "phone" ? (
                <PhoneSection />
              ) : section === "ai" ? (
                <AiSection settings={settings.data} profile={profile.data} />
              ) : section === "claude" ? (
                <ClaudeSection health={health.data} settings={settings.data} />
              ) : section === "privacy" ? (
                <PrivacySection />
              ) : section === "rules" ? (
                <RulesSection />
              ) : section === "computers" ? (
                <ComputersSection />
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
