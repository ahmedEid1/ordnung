import { useState } from "react";
import { BellRing, CircleCheck, MonitorSmartphone, Power, RotateCw, TriangleAlert } from "lucide-react";
import { useDesktopReminders, useSettings, useTestDesktopNotification, useUpdateSettings } from "@/api/hooks";
import type { AppSettings, DesktopReminders, NotificationText } from "@/api/types";
import { LogoMark } from "@/components/shell/Logo";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Field, Input, Switch } from "@/components/ui/Field";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { cn } from "@/lib/utils";
import { isStaticDemo } from "@/mocks/mode";
import { BreakablePath } from "./DataSection";
import { autostartLabel, DESKTOP_MODES, MODE_HINTS, previewFor, testMode, testOutcome, timeError, type DesktopSetting } from "./desktop";
import { SaveBar, SettingsCard } from "./SettingsCard";

const TOOL_NAMES: Record<string, string> = { "notify-send": "notify-send", osascript: "macOS notifications", powershell: "Windows notifications" };

/**
 * How today's notification will look — a stand-in for the system's own, drawn with the real text.
 * Text only (no live region): it changes with the choice above it, which already says what changed.
 */
function NotificationPreview({ text, loading }: { text: NotificationText | null; loading: boolean }) {
  return (
    <figure className="min-w-0">
      <figcaption className="text-sm font-medium text-ink">Today it would say</figcaption>
      {loading ? (
        <div aria-busy="true" className="mt-1.5 rounded-2xl border border-line bg-surface-2/60 p-3.5">
          <Skeleton className="h-4 w-40 max-w-full" />
          <Skeleton className="mt-2 h-3.5 w-full" />
        </div>
      ) : text ? (
        <div className="mt-1.5 flex gap-2.5 rounded-2xl border border-line bg-surface p-3 shadow-[var(--shadow-card)] sm:gap-3 sm:p-3.5">
          <LogoMark className="size-6 rounded-md sm:size-8 sm:rounded-lg" />
          <div className="min-w-0 flex-1">
            <p className="text-[13.5px] font-semibold leading-5 text-ink [overflow-wrap:anywhere]">{text.title}</p>
            <p className="mt-0.5 text-[13px] leading-5 text-ink/85 [overflow-wrap:anywhere]">{text.body}</p>
          </div>
        </div>
      ) : (
        <p className="mt-1.5 rounded-2xl border border-dashed border-line-strong px-3.5 py-3 text-[13px] leading-5 text-muted">
          Nothing is due this week, so there would be no notification today.
        </p>
      )}
    </figure>
  );
}

/** "Start Ordnung when you log in": notifications only come while Ordnung runs. */
function StartAtLogin({ status }: { status: DesktopReminders | undefined }) {
  const info = status?.autostart;
  const label = autostartLabel(info);
  const here = Boolean(info?.enabled && info.points_here);
  const code = "font-mono text-[12.5px] text-ink";
  return (
    <div className="mt-6 border-t border-line pt-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h4 className="flex items-center gap-2 text-[14px] font-semibold text-ink">
          <Power className="size-4 shrink-0 text-muted" aria-hidden /> Start Ordnung when you log in
        </h4>
        {info ? (
          <Badge tone={label.tone} dot>
            {label.text}
          </Badge>
        ) : null}
      </div>
      {here && info ? (
        <p className="mt-1.5 flex gap-1.5 text-[13px] leading-5 text-muted">
          <CircleCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
          <span className="min-w-0">
            Ordnung starts in the background each time you log in, so the notification comes with the browser closed. Open the app with{" "}
            <code className={code}>ordnung serve</code>. Set up as a {info.kind}:{" "}
            <span className={cn(code, "[overflow-wrap:anywhere]")}>
              <BreakablePath path={info.path} />
            </span>{" "}
            — <code className={code}>ordnung autostart disable</code> undoes it.
          </span>
        </p>
      ) : (
        <>
          <p className="mt-1 text-[13px] leading-relaxed text-muted">
            The morning notification — like every reminder — only comes while Ordnung is running. Run this once in a terminal and Ordnung starts in the
            background each time you log in (you open the app with <code className={code}>ordnung serve</code>):
          </p>
          <CopyCommand command={info?.command ?? "ordnung autostart enable"} label="start Ordnung when you log in" className="mt-3" />
          {info?.enabled ? (
            <p className="mt-2.5 flex gap-1.5 text-[13px] leading-5 text-warn-ink">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span>It is set up for another data folder. Run the command again to start this one instead.</span>
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

function Editor({ settings }: { settings: AppSettings }) {
  const status = useDesktopReminders();
  const update = useUpdateSettings();
  const test = useTestDesktopNotification();
  const staticDemo = isStaticDemo();
  const saved = { mode: settings.desktop_notifications, time: settings.desktop_notify_time };
  const [mode, setMode] = useState<DesktopSetting>(saved.mode);
  const [time, setTime] = useState(saved.time);
  const [showError, setShowError] = useState(false);
  const error = mode === "off" ? null : timeError(time);
  const dirty = mode !== saved.mode || (mode !== "off" && time !== saved.time);

  const save = () =>
    update.mutateAsync({ desktop_notifications: mode, desktop_notify_time: mode === "off" ? saved.time : time }).then((s) => {
      setMode(s.desktop_notifications);
      setTime(s.desktop_notify_time);
      setShowError(false);
      return s.desktop_notifications === "off" ? "No desktop notification from now on." : `Once a day from ${s.desktop_notify_time}, while Ordnung runs.`;
    });

  const sendTest = () =>
    test.mutate(testMode(mode), {
      onSuccess: (result) => {
        const outcome = testOutcome(result.shown, result.detail);
        toast[outcome.tone](outcome.title, { description: outcome.description });
      },
    });

  const data = status.data;
  const tool = data?.tool ? (TOOL_NAMES[data.tool] ?? data.tool) : null;

  return (
    <SettingsCard
      title="Desktop notification each morning"
      id="set-desktop"
      description="Ordnung writes it from your dates on this computer — no AI, and nothing is sent anywhere."
      footer={
        <SaveBar
          dirty={dirty}
          saving={update.isPending}
          onSave={save}
          onDiscard={() => {
            setMode(saved.mode);
            setTime(saved.time);
            setShowError(false);
          }}
          invalid={Boolean(error)}
          onInvalid={() => {
            setShowError(true);
            document.getElementById("desktop-time")?.focus();
          }}
        />
      }
    >
      <Switch
        checked={mode !== "off"}
        // switched on, it starts discreet: nothing private on a lock screen unless chosen
        onCheckedChange={(on) => setMode(on ? "discreet" : "off")}
        label="Notify me each morning on this computer"
        description="One short note a day, also with the browser closed — as long as Ordnung runs."
      />

      {mode !== "off" ? (
        <>
          <p aria-hidden className="mb-2 mt-5 text-sm font-medium text-ink">
            What it shows
          </p>
          <SegmentedControl label="What the desktop notification shows" value={mode} onChange={setMode} options={DESKTOP_MODES} fill="phone" />
          <p className="mt-2 text-sm leading-5 text-muted">{MODE_HINTS[mode]}</p>
          <div className="mt-5 grid gap-5 sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)]">
            <Field id="desktop-time" label="Show it from" hint="Within 15 minutes of this time — or when Ordnung starts, if later." error={showError ? error : undefined}>
              <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} step={60} required className="tabular-nums" />
            </Field>
            {status.isError ? (
              <div role="alert" className="min-w-0">
                <p className="text-sm font-medium text-ink">Today it would say</p>
                <p className="mt-1.5 text-[13px] leading-5 text-danger-ink">Couldn't load the preview — is Ordnung still running?</p>
                <Button size="sm" variant="ghost" icon={RotateCw} className="mt-1" onClick={() => void status.refetch()} loading={status.isFetching}>
                  Try again
                </Button>
              </div>
            ) : (
              <NotificationPreview text={previewFor(data, mode)} loading={status.isPending} />
            )}
          </div>
        </>
      ) : null}

      {staticDemo ? (
        <p className="mt-5 rounded-lg bg-surface-2/70 px-3 py-2 text-[12.5px] leading-5 text-muted" role="note">
          Not available in the online demo — install Ordnung to get the morning notification on your computer.
        </p>
      ) : data?.missing ? (
        <Callout tone="warn" title="This computer can't show it yet" className="mt-5">
          {data.missing} Your calendar alarms still work.
        </Callout>
      ) : mode === "off" ? null : (
        <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button size="sm" variant="secondary" icon={BellRing} onClick={sendTest} loading={test.isPending} disabled={status.isPending}>
            Show a test notification
          </Button>
          {tool ? (
            <span className="flex items-center gap-1.5 text-[12.5px] leading-5 text-muted">
              <MonitorSmartphone className="size-3.5 shrink-0" aria-hidden /> Shown with {tool}
            </span>
          ) : null}
        </div>
      )}

      <StartAtLogin status={data} />
    </SettingsCard>
  );
}

/** Settings → Reminders: the morning desktop notification, its time, a preview, a test and start at login. */
export function DesktopNotificationsCard() {
  const settings = useSettings();
  if (!settings.data) return null; // the Settings page shows its own loading and error states
  return <Editor settings={settings.data} />;
}
