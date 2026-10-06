import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { CalendarCheck, CalendarSearch, Check, ChevronDown, ChevronUp, Link2Off, OctagonAlert, RefreshCw, Unplug } from "lucide-react";
import { ApiError } from "@/api/client";
import { useCalendarSync, useCalendarSyncPreview, useConnectCalendarSync, useDisconnectCalendarSync, useDiscoverCalendars, useRunCalendarSync } from "@/api/hooks";
import type { CalendarChoice, CalendarSyncMode, CalendarSyncStatus } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Dialog } from "@/components/ui/Dialog";
import { Checkbox, Field, Input } from "@/components/ui/Field";
import { LoadError } from "@/components/ui/LoadError";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { CopyCommand } from "@/features/onboarding/CopyCommand";
import { focusWhenReady } from "@/features/today/focus";
import { useTodayISO } from "@/lib/today";
import { cn } from "@/lib/utils";
import { BreakablePath } from "./DataSection";
import {
  eventWhen,
  fieldFor,
  foundLine,
  hostOf,
  alarmsLine,
  isPastEvent,
  lastSyncLine,
  modeLabel,
  preferredCalendar,
  previewOrder,
  PROVIDER_HINTS,
  SYNC_MODE_HINTS,
  SYNC_MODES,
  syncFormProblem,
  type SyncField,
} from "./calendarSync";
import { SaveBar, SettingsCard } from "./SettingsCard";

const TITLE = "Sync with your own calendar";
const DESCRIPTION =
  "Optional: Ordnung puts your dates into a calendar you already use — Nextcloud, iCloud, mailbox.org or another CalDAV calendar — and keeps them current while it runs. Your calendar provider then stores what the events say.";
const PREVIEW_COUNT = 4;
/** The card's heading (both states), the connected line and the form's own error: where focus goes. */
const HEADING_ID = "set-cal-sync";
const CONNECTED_ID = "cal-sync-connected";
const FORM_ERROR_ID = "cal-sync-form-error";

type Errors = Partial<Record<SyncField, string>>;

/**
 * Focus what a problem belongs to: its field, or — for the form's own error, which sits next to the
 * button in the footer — that error, so it is on screen and read out wherever the form was sent from.
 */
function focusField(field: SyncField) {
  document.getElementById(field === "form" ? FORM_ERROR_ID : `cal-sync-${field}`)?.focus();
}

function errorsFrom(err: unknown): Errors {
  if (err instanceof ApiError) return { [fieldFor(err.code)]: err.message };
  return { form: "Ordnung didn't answer. Is it still running?" };
}

/** "What your calendar gets": the choice of mode and every event exactly as it would be sent. */
function EventPreview({ mode, onModeChange, headingId }: { mode: CalendarSyncMode; onModeChange: (m: CalendarSyncMode) => void; headingId: string }) {
  const preview = useCalendarSyncPreview(mode);
  const today = useTodayISO();
  const [all, setAll] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  // what is still to come first: a preview that opens on last year's dates looks broken
  const { events, past } = previewOrder(preview.data?.events ?? [], today);
  const shown = all ? events : events.slice(0, PREVIEW_COUNT);
  const listId = useId();
  const toggle = () => {
    const collapsing = all;
    setAll(!all);
    // the list shrinks by thousands of pixels: the toggle, which keeps focus, comes back into view
    if (collapsing) requestAnimationFrame(() => toggleRef.current?.scrollIntoView?.({ block: "nearest" }));
  };
  return (
    <div>
      <h4 id={headingId} className="mb-2 text-sm font-medium text-ink">
        What your calendar gets
      </h4>
      <SegmentedControl label="What the calendar events show" value={mode} onChange={onModeChange} options={SYNC_MODES} fill="phone" />
      <p className="mt-2 text-sm leading-5 text-muted">{SYNC_MODE_HINTS[mode]}</p>
      {preview.isPending ? (
        <div aria-busy="true" className="mt-3 space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : preview.isError ? (
        <LoadError
          what="the preview"
          description="Nothing was sent — Ordnung didn't answer. Is it still running?"
          error={preview.error}
          onRetry={() => void preview.refetch()}
          retrying={preview.isFetching}
          headingLevel={4}
          variant="plain"
          size="sm"
          className="mt-3"
        />
      ) : events.length === 0 ? (
        <p className="mt-3 rounded-2xl border border-dashed border-line-strong px-3.5 py-3 text-[13px] leading-5 text-muted">
          No open dates yet — once letters bring dates, they go to your calendar.
        </p>
      ) : (
        <>
          <ul id={listId} aria-label={`Events, ${modeLabel(mode).toLowerCase()}`} className="mt-3 divide-y divide-line rounded-2xl border border-line bg-surface">
            {shown.map((e) => {
              // a date that has passed — "Overdue" said too much of money that came in or a date already
              // dealt with (walkthrough of phase 2)
              const passed = isPastEvent(e, today);
              return (
                <li key={e.uid} className="min-w-0 px-3.5 py-3">
                  <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] font-medium leading-5 text-muted tabular-nums">
                    {eventWhen(e, today)}
                    {passed ? (
                      <Badge tone="neutral" size="sm">
                        Date passed
                      </Badge>
                    ) : null}
                  </p>
                  <p className="text-[14px] font-semibold leading-5 text-ink [overflow-wrap:anywhere]">{e.summary}</p>
                  <p className="mt-0.5 whitespace-pre-line text-[13px] leading-5 text-ink/80 [overflow-wrap:anywhere]">{e.description}</p>
                  {e.location ? <p className="mt-0.5 text-[13px] leading-5 text-ink/80 [overflow-wrap:anywhere]">Where: {e.location}</p> : null}
                  {passed ? (
                    <p className="mt-1 text-[12.5px] leading-5 text-muted">The date has passed: it shows in the calendar without an alarm to come.</p>
                  ) : e.alarms.length ? (
                    <p className="mt-1 text-[12.5px] leading-5 text-muted">{alarmsLine(e)}</p>
                  ) : null}
                </li>
              );
            })}
          </ul>
          {events.length > PREVIEW_COUNT ? (
            <Button ref={toggleRef} size="sm" variant="ghost" icon={all ? ChevronUp : ChevronDown} className="mt-1.5" aria-expanded={all} aria-controls={listId} onClick={toggle}>
              {all ? "Show fewer" : past ? `Show all ${events.length} events (${past} passed)` : `Show all ${events.length} events`}
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}

/** Where to find the address and an app password, per provider (a disclosure under the fields). */
function ProviderHints() {
  return (
    <details className="group rounded-xl border border-line bg-surface-2/50 px-3.5 py-2.5 text-[13px] leading-5 text-muted">
      <summary className="flex min-h-6 cursor-pointer list-none items-center gap-1.5 font-medium text-ink marker:hidden">
        <ChevronDown className="size-4 shrink-0 transition-transform group-open:rotate-180" aria-hidden /> Where do I find these?
      </summary>
      <ul className="mt-2 space-y-2">
        {PROVIDER_HINTS.map((p) => (
          <li key={p.name} className="min-w-0 [overflow-wrap:anywhere]">
            <span className="font-medium text-ink">{p.name}</span> — address: {p.address}. App password: {p.password}.
          </li>
        ))}
        <li>Other providers: the CalDAV address from the calendar's settings or help pages. Use an app password where your provider offers one — not your main password.</li>
      </ul>
    </details>
  );
}

/** The calendars the server offered: one radio each (name, then its address). */
function CalendarChoices({ calendars, chosen, onChoose }: { calendars: CalendarChoice[]; chosen: string | null; onChoose: (url: string) => void }) {
  const named = calendars.some((c) => c.name?.trim().toLowerCase() === "ordnung");
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium text-ink">Which calendar should Ordnung write into?</legend>
      <div className="space-y-1.5">
        {calendars.map((c) => {
          const selected = chosen === c.url;
          return (
            <label
              key={c.url}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors",
                "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                selected ? "border-accent/60 bg-accent-soft/50 shadow-[0_0_0_1px_var(--color-accent)]" : "border-line hover:border-line-strong",
              )}
            >
              {/* the row is the target (like the other pickers): the radio itself is for assistive tech */}
              <input type="radio" name="calendar-sync-calendar" value={c.url} checked={selected} onChange={() => onChoose(c.url)} className="sr-only" />
              <span
                className={cn(
                  "mt-px grid size-5 shrink-0 place-items-center rounded-full border transition-colors",
                  selected ? "border-accent bg-accent text-on-accent" : "border-line-strong bg-surface",
                )}
                aria-hidden
              >
                {selected ? <Check className="size-3" strokeWidth={3} /> : null}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[14px] font-medium text-ink [overflow-wrap:anywhere]">{c.name ?? "A calendar without a name"}</span>
                <span className="block font-mono text-[12px] leading-5 text-muted [overflow-wrap:anywhere]">
                  <BreakablePath path={c.url} />
                </span>
              </span>
            </label>
          );
        })}
      </div>
      {!named ? (
        <p className="mt-2 text-[12.5px] leading-5 text-muted">Tip: a calendar of its own, named “Ordnung”, keeps Ordnung's events apart from yours — create one in your calendar app, then find calendars again.</p>
      ) : null}
    </fieldset>
  );
}

function Unavailable({ status }: { status: CalendarSyncStatus }) {
  if (status.install_command)
    return (
      <Callout tone="warn" title="One more package, then this works" className="mb-5">
        <p>{status.unavailable}</p>
        <CopyCommand command={status.install_command} label="install calendar sync" className="mt-2" />
        <p className="mt-2">Then restart Ordnung.</p>
      </Callout>
    );
  return (
    <p className="mb-5 rounded-lg bg-surface-2/70 px-3 py-2 text-[12.5px] leading-5 text-muted" role="note">
      {status.unavailable}
    </p>
  );
}

/** Not connected: the account, finding its calendars, the choice, the preview, then connect. */
function Connect({ status }: { status: CalendarSyncStatus }) {
  const discover = useDiscoverCalendars();
  const connect = useConnectCalendarSync();
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<CalendarSyncMode>(status.mode);
  const [calendars, setCalendars] = useState<CalendarChoice[] | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [errors, setErrors] = useState<Errors>({});
  const [found, setFound] = useState("");
  const previewId = useId();
  const busy = discover.isPending || connect.isPending;
  // a refusal's field gets focus once the fields are enabled again (they are disabled while asking)
  const focusNext = useRef<SyncField | null>(null);
  useEffect(() => {
    if (busy || !focusNext.current) return;
    focusField(focusNext.current);
    focusNext.current = null;
  }, [busy, errors]);

  const edit = (set: (v: string) => void) => (v: string) => {
    set(v);
    setCalendars(null);
    setChosen(null);
    setErrors({});
  };


  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (busy || !status.available) return;
    const problem = syncFormProblem({ url, username, password });
    if (problem) {
      setErrors({ [problem.field]: problem.message });
      focusField(problem.field);
      return;
    }
    setErrors({});
    if (!calendars || !chosen) {
      discover.mutate(
        { url: url.trim(), username: username.trim(), password },
        {
          onSuccess: ({ calendars: list }) => {
            setCalendars(list);
            setChosen(preferredCalendar(list));
            setFound(foundLine(list));
            // on to the choice (it scrolls into view): the next step is there, not at the button
            focusWhenReady(() => document.querySelector<HTMLElement>('input[name="calendar-sync-calendar"]:checked'), 5000, { always: true });
          },
          onError: (err) => {
            const next = errorsFrom(err);
            focusNext.current = (Object.keys(next)[0] ?? "form") as SyncField;
            setErrors(next);
          },
        },
      );
      return;
    }
    connect.mutate(
      { url: chosen, username: username.trim(), password, mode },
      {
        onSuccess: (s) => {
          const r = s.last_sync;
          const where = s.calendar_name ?? hostOf(s.url);
          // the card is now the connected one: its "Connected to …" line takes the focus the button had
          focusWhenReady(() => document.getElementById(CONNECTED_ID));
          if (r?.error) toast.warn(`Connected to ${where}, but not everything was sent`, { description: r.error });
          else toast.success(`Connected to ${where}`, { description: `${r?.sent ?? 0} ${r?.sent === 1 ? "event" : "events"} sent. Ordnung keeps them current while it runs.` });
        },
        onError: (err) => {
          const next = errorsFrom(err);
          focusNext.current = (Object.keys(next)[0] ?? "form") as SyncField;
          setErrors(next);
        },
      },
    );
  };

  return (
    <SettingsCard
      title={TITLE}
      id={HEADING_ID}
      description={DESCRIPTION}
      footer={
        status.available ? (
          <>
            {/* the form's own error sits next to the button that was pressed (the fields are far above) */}
            {errors.form ? (
              <p
                id={FORM_ERROR_ID}
                role="alert"
                tabIndex={-1}
                className="mr-auto flex min-w-0 basis-full items-start gap-1.5 rounded-sm text-sm leading-5 text-danger-ink sm:basis-0 sm:flex-1"
              >
                <OctagonAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span className="min-w-0 [overflow-wrap:anywhere]">{errors.form}</span>
              </p>
            ) : found && calendars ? (
              <p role="status" className="mr-auto min-w-0 text-sm leading-5 text-muted [overflow-wrap:anywhere]">
                {found}
              </p>
            ) : (
              <span role="status" className="sr-only">
                {found}
              </span>
            )}
            <Button type="submit" form="calendar-sync-form" variant="primary" icon={calendars ? CalendarCheck : CalendarSearch} loading={busy}>
              {calendars ? "Connect and sync" : "Find my calendars"}
            </Button>
          </>
        ) : undefined
      }
    >
      {!status.available ? <Unavailable status={status} /> : null}
      {status.available ? (
        <form id="calendar-sync-form" onSubmit={submit} noValidate className="space-y-4">
          <Field id="cal-sync-url" label="Calendar or server address" hint="A calendar's CalDAV address, or just your provider's (Ordnung finds your calendars)." error={errors.url}>
            {/* read-only (not disabled) while asking: a field that holds focus keeps it */}
            <Input type="url" inputMode="url" value={url} onChange={(e) => edit(setUrl)(e.target.value)} placeholder="https://cloud.example.org" autoComplete="url" autoCapitalize="none" autoCorrect="off" spellCheck={false} readOnly={busy} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="cal-sync-username" label="User name" error={errors.username}>
              <Input value={username} onChange={(e) => edit(setUsername)(e.target.value)} autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false} readOnly={busy} />
            </Field>
            <Field id="cal-sync-password" label="App password" hint="Kept in this computer's password store — never in Ordnung's files." error={errors.password}>
              <Input type="password" value={password} onChange={(e) => edit(setPassword)(e.target.value)} autoComplete="new-password" readOnly={busy} />
            </Field>
          </div>
          <ProviderHints />
          {calendars ? <CalendarChoices calendars={calendars} chosen={chosen} onChoose={setChosen} /> : null}
        </form>
      ) : null}
      <div className={cn(status.available && "mt-6 border-t border-line pt-5")}>
        <EventPreview mode={mode} onModeChange={setMode} headingId={previewId} />
      </div>
    </SettingsCard>
  );
}

/** Enter the app password again (after a refused one, or on a computer that doesn't have it). */
function PasswordAgain({ status, reason }: { status: CalendarSyncStatus; reason: string }) {
  const connect = useConnectCalendarSync();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!password) {
      setError("Enter the app password for this calendar.");
      document.getElementById("cal-sync-again")?.focus();
      return;
    }
    connect.mutate(
      { url: status.url!, username: status.username!, password, mode: status.mode },
      {
        onSuccess: (s) => {
          setPassword("");
          setError(null);
          toast.success("Calendar sync is running again", { description: lastSyncLine(s.last_sync).text });
        },
        onError: (err) => setError(err instanceof ApiError ? err.message : "Ordnung didn't answer. Is it still running?"),
      },
    );
  };
  return (
    <Callout tone="warn" title={reason} className="mt-4">
      <form onSubmit={submit} noValidate className="mt-2 flex flex-wrap items-end gap-2">
        <Field id="cal-sync-again" label="App password" error={error ?? undefined} className="min-w-0 flex-1 basis-56">
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" readOnly={connect.isPending} />
        </Field>
        <Button type="submit" variant="primary" icon={RefreshCw} loading={connect.isPending}>
          Save and sync
        </Button>
      </form>
    </Callout>
  );
}

/** "Disconnect…": forget the calendar, removing Ordnung's events from it first unless asked not to. */
function DisconnectDialog({ open, onClose, status }: { open: boolean; onClose: () => void; status: CalendarSyncStatus }) {
  const disconnect = useDisconnectCalendarSync();
  const [remove, setRemove] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const where = status.calendar_name ?? hostOf(status.url);
  // the next opening starts as the first did
  const close = () => {
    setRemove(true);
    setError(null);
    onClose();
  };
  const confirm = () =>
    disconnect.mutate(remove, {
      onSuccess: ({ removed }) => {
        close();
        // the card becomes the form to connect: its heading takes the focus of the gone "Disconnect…"
        focusWhenReady(() => (document.getElementById("calendar-sync-form") ? document.getElementById(HEADING_ID) : null));
        toast.success(`Disconnected ${where}`, {
          description: remove ? `${removed} ${removed === 1 ? "event was" : "events were"} removed from the calendar. The app password was forgotten.` : "Ordnung's events stay in the calendar. The app password was forgotten.",
        });
      },
      onError: (err) => {
        setError(err instanceof ApiError ? err.message : "Ordnung didn't answer. Is it still running?");
        focusWhenReady(() => document.getElementById("cal-sync-disconnect-error"));
      },
    });
  return (
    <Dialog
      open={open}
      onClose={close}
      size="sm"
      title={`Disconnect ${where}?`}
      description="Ordnung stops sending dates there and forgets the app password. Your dates stay in Ordnung."
      dismissible={!disconnect.isPending}
      footer={
        <>
          <Button onClick={close} disabled={disconnect.isPending}>
            Cancel
          </Button>
          <Button variant="danger" icon={Unplug} loading={disconnect.isPending} onClick={confirm}>
            Disconnect
          </Button>
        </>
      }
    >
      <Checkbox
        checked={remove}
        onChange={(e) => {
          setRemove(e.target.checked);
          setError(null);
        }}
        label={`Also remove Ordnung's ${status.synced} ${status.synced === 1 ? "event" : "events"} from the calendar`}
        description="Only the events Ordnung put there — nothing else in the calendar is touched."
      />
      {error ? (
        <div id="cal-sync-disconnect-error" tabIndex={-1} className="mt-4 rounded-xl">
          <Callout tone="danger" title={remove ? "The events couldn't be removed" : "Couldn't disconnect"} alert>
            {error} {remove ? "Untick the box to disconnect and leave them there." : null}
          </Callout>
        </div>
      ) : null}
    </Dialog>
  );
}

/** Connected: where, the last sync, sync now, the mode (saved like other settings), disconnect. */
function Connected({ status }: { status: CalendarSyncStatus }) {
  const run = useRunCalendarSync();
  const update = useConnectCalendarSync();
  const [mode, setMode] = useState<CalendarSyncMode>(status.mode);
  const [disconnecting, setDisconnecting] = useState(false);
  const previewId = useId();
  // how many events the calendar gets now: the saved mode's preview (the status never builds them)
  const current = useCalendarSyncPreview(status.mode);
  const events = current.data?.events.length;
  const where = status.calendar_name ?? hostOf(status.url);
  const last = lastSyncLine(status.last_sync);
  const needsPassword = !status.password_saved || status.paused;

  const saveMode = () =>
    update.mutateAsync({ url: status.url!, username: status.username!, password: null, mode }).then(
      (s) => (s.last_sync?.error ? `Saved — but ${s.last_sync.error}` : `Events now go ${mode === "discreet" ? "discreetly" : "with details"} — ${s.last_sync?.sent ?? 0} updated.`),
      (err: unknown) => {
        toast.error("Couldn't change what the calendar gets", { description: err instanceof ApiError ? err.message : undefined });
        throw err;
      },
    );

  const syncNow = () =>
    run.mutate(undefined, {
      onSuccess: (s) => {
        const line = lastSyncLine(s.last_sync);
        if (line.tone === "warn") toast.warn("Calendar sync didn't finish", { description: s.last_sync?.error ?? undefined });
        else toast.success("Calendar synced", { description: line.text });
      },
    });

  return (
    <SettingsCard
      title={TITLE}
      id={HEADING_ID}
      description={DESCRIPTION}
      footer={<SaveBar dirty={mode !== status.mode} saving={update.isPending} onSave={saveMode} onDiscard={() => setMode(status.mode)} />}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <span className="grid size-11 shrink-0 place-items-center rounded-2xl bg-accent-soft text-accent">
          <CalendarCheck className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p id={CONNECTED_ID} tabIndex={-1} className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-sm text-[15px] font-semibold text-ink">
            <span className="min-w-0 [overflow-wrap:anywhere]">Connected to {where}</span>
            <Badge tone={status.mode === "discreet" ? "ok" : "neutral"} dot>
              {modeLabel(status.mode)}
            </Badge>
          </p>
          <p className="mt-0.5 text-[13px] leading-5 text-muted [overflow-wrap:anywhere]">
            {status.username} · <span className="font-mono text-[12.5px]"><BreakablePath path={status.url ?? ""} /></span>
          </p>
          <p role="status" className={cn("mt-2 text-[13px] leading-5", last.tone === "warn" ? "text-warn-ink" : "text-ink/85")}>
            {last.text}
            {events === undefined ? null : ` ${status.synced} of ${events} ${events === 1 ? "event is" : "events are"} in the calendar.`}
          </p>
        </div>
      </div>
      {needsPassword ? (
        <PasswordAgain status={status} reason={!status.password_saved ? "The app password isn't saved on this computer" : "Paused: the server refused the app password"} />
      ) : null}
      <div className="mt-4 flex flex-wrap gap-2">
        {/* paused: the refused password would be tried again — "Save and sync" above is the way on */}
        <Button size="sm" variant="secondary" icon={RefreshCw} onClick={syncNow} loading={run.isPending} disabled={needsPassword}>
          Sync now
        </Button>
        <Button size="sm" variant="ghost" icon={Link2Off} onClick={() => setDisconnecting(true)}>
          Disconnect…
        </Button>
      </div>
      <div className="mt-6 border-t border-line pt-5">
        <EventPreview mode={mode} onModeChange={setMode} headingId={previewId} />
      </div>
      <DisconnectDialog open={disconnecting} onClose={() => setDisconnecting(false)} status={status} />
    </SettingsCard>
  );
}

/** Settings → Calendar → "Sync with your own calendar" (CalDAV): opt-in, discreet by default. */
export function CalendarSyncCard() {
  const status = useCalendarSync();
  if (status.isPending)
    return (
      <SettingsCard title={TITLE} id={HEADING_ID} description={DESCRIPTION}>
        <div aria-busy="true" className="space-y-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-2/3" />
        </div>
      </SettingsCard>
    );
  if (status.isError)
    return (
      <SettingsCard title={TITLE} id={HEADING_ID} description={DESCRIPTION}>
        <LoadError
          what="calendar sync"
          description="Nothing was sent or changed — Ordnung didn't answer. Is it still running?"
          error={status.error}
          onRetry={() => void status.refetch()}
          retrying={status.isFetching}
          headingLevel={4}
          variant="plain"
          size="sm"
        />
      </SettingsCard>
    );
  // a fresh editor after connecting or disconnecting (its fields belong to one state)
  return status.data.connected ? <Connected key="connected" status={status.data} /> : <Connect key="connect" status={status.data} />;
}
