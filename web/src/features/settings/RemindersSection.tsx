import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { BellRing, Plus, X } from "lucide-react";
import { useUpdateProfile } from "@/api/hooks";
import type { ItemKind, Profile } from "@/api/types";
import { KindIcon } from "@/components/ui/KindBadge";
import { Button } from "@/components/ui/Button";
import { Field, Select, Switch } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { setBrowserNotifications, showNotification, useNotifyState } from "@/features/notifications/useBrowserNotifications";
import { isStaticDemo } from "@/mocks/mode";
import { DesktopNotificationsCard } from "./DesktopNotificationsCard";
import { completeReminderDays, leadDaysError, leadLabel, normalizeLeadDays, REMINDER_KINDS, sameReminderDays } from "./logic";
import { FIELD_WIDTH, SaveBar, SectionHeading, SettingsCard } from "./SettingsCard";

/** The recommended head start for letters by post (working days). */
const POSTAL_BUFFER_RECOMMENDED = 4;

/**
 * "+ Add" → a small "days" field. A number that can't be added (not a number, over 365, already in
 * the list) keeps the field open with the reason; Enter adds, Escape cancels — both hand focus back
 * to "+ Add".
 */
function AddLead({ kind, label, existing, onAdd }: { kind: ItemKind; label: string; existing: readonly number[]; onAdd: (d: number) => void }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const refocus = useRef(false);
  const id = useId();
  const what = label.toLowerCase();

  useEffect(() => {
    if (open || !refocus.current) return;
    refocus.current = false;
    addRef.current?.focus();
  }, [open]);

  const close = (focusAdd: boolean) => {
    refocus.current = focusAdd;
    setOpen(false);
    setValue("");
    setError(null);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const why = leadDaysError(value, existing);
    if (why) {
      setError(why);
      return;
    }
    onAdd(Number(value.trim()));
    close(true);
  };

  if (!open) {
    return (
      <button
        ref={addRef}
        type="button"
        data-add={kind}
        onClick={() => setOpen(true)}
        className="inline-flex h-7 items-center gap-1 rounded-full border border-dashed border-line-strong px-2.5 text-[12.5px] font-medium text-muted transition-colors hover:border-accent/60 hover:text-accent"
        aria-label={`Add a reminder for ${what}`}
      >
        <Plus className="size-3.5" aria-hidden /> Add
      </button>
    );
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-wrap items-center gap-1">
      <label className="sr-only" htmlFor={`lead-${kind}`}>
        Days before, for {what}
      </label>
      <span className="relative inline-flex">
        <input
          id={`lead-${kind}`}
          autoFocus
          type="text"
          inputMode="numeric"
          autoComplete="off"
          maxLength={3}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key !== "Escape") return;
            e.preventDefault();
            e.stopPropagation();
            close(true);
          }}
          // leaving an empty field puts "+ Add" back (focus stays where you went)
          onBlur={() => !value.trim() && close(false)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-err` : undefined}
          className="h-7 w-20 rounded-full border border-control-border bg-surface pl-3 pr-10 text-[12.5px] tabular-nums text-ink outline-none transition-[border-color,box-shadow] focus-visible:border-accent focus-visible:ring-3 focus-visible:ring-accent/20 aria-invalid:border-danger aria-invalid:ring-danger/15"
        />
        <span aria-hidden className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[12px] text-muted">
          days
        </span>
      </span>
      <button
        type="submit"
        className="h-7 rounded-full bg-accent px-3 text-[12.5px] font-medium text-on-accent transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        Add
      </button>
      {error ? (
        <p id={`${id}-err`} role="alert" className="w-full text-xs font-medium text-danger-ink">
          {error}
        </p>
      ) : null}
    </form>
  );
}

const TEST_NOTIFICATION = {
  key: "test",
  title: "Ordnung can notify you",
  body: "You'll see dates due today or tomorrow here while Ordnung is open.",
  href: "/settings?section=reminders",
};

/** Opt-in browser notifications (SPEC §12): a per-browser switch that asks for permission. */
function BrowserNotificationsCard() {
  const state = useNotifyState();
  const [busy, setBusy] = useState(false);

  const toggle = async (on: boolean) => {
    setBusy(true);
    try {
      const next = await setBrowserNotifications(on);
      if (on && next.enabled) showNotification(TEST_NOTIFICATION);
      else if (on && next.permission === "denied")
        toast.warn("Your browser blocked notifications", { description: "Allow notifications for this site in your browser's site settings, then turn this on again." });
    } finally {
      setBusy(false);
    }
  };

  const note = !state.available
    ? isStaticDemo()
      ? "Not available in the online demo — install Ordnung to get notifications."
      : "This browser can't show notifications. Your calendar file still has alarms."
    : state.permission === "denied"
      ? "Notifications are blocked for this site. Allow them in your browser's site settings (the icon next to the address), then turn this on."
      : null;

  return (
    <SettingsCard
      title="Notifications in this browser"
      id="set-notify"
      description="A gentle nudge on this computer — Ordnung has no server and sends nothing anywhere; your browser shows it."
    >
      <Switch
        checked={state.enabled}
        onCheckedChange={(on) => void toggle(on)}
        disabled={busy || !state.available || (state.permission === "denied" && !state.enabled)}
        label="Notify me in this browser while Ordnung is open"
        description="Dates due today or tomorrow, and urgent Ideas that are overdue — each at most once a day."
      />
      {note ? (
        <p className="mt-3 rounded-lg bg-surface-2/70 px-3 py-2 text-[12.5px] leading-5 text-muted" role="note">
          {note}
        </p>
      ) : null}
      {state.enabled ? (
        <div className="mt-3">
          <Button size="sm" variant="ghost" icon={BellRing} onClick={() => showNotification(TEST_NOTIFICATION)}>
            Send a test notification
          </Button>
        </div>
      ) : null}
    </SettingsCard>
  );
}

/** "Reminders": how many days before each kind of date you want a nudge (and calendar alarms). */
export function RemindersSection({ profile }: { profile: Profile }) {
  const update = useUpdateProfile();
  const saved = completeReminderDays(profile.reminder_days);
  const [days, setDays] = useState(saved);
  const [buffer, setBuffer] = useState(profile.postal_buffer_days);
  const dirty = !sameReminderDays(days, saved) || buffer !== profile.postal_buffer_days;
  const listRef = useRef<HTMLUListElement>(null);
  // after a removal: the next chip's remove button (or the previous one, or "+ Add") gets focus
  const focusAfter = useRef<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    const target = focusAfter.current;
    if (!target) return;
    focusAfter.current = null;
    listRef.current?.querySelector<HTMLElement>(target)?.focus();
  }, [days]);

  const setKind = (k: ItemKind, list: number[]) => setDays((d) => ({ ...d, [k]: normalizeLeadDays(list) }));
  const add = (k: ItemKind, label: string, list: number[], d: number) => {
    setKind(k, [...list, d]);
    setAnnouncement(`Added: ${leadLabel(d).toLowerCase()}, for ${label.toLowerCase()}`);
  };
  const remove = (k: ItemKind, label: string, list: number[], d: number) => {
    const i = list.indexOf(d);
    const next = list[i + 1] ?? list[i - 1];
    focusAfter.current = next === undefined ? `[data-add="${k}"]` : `[data-remove="${k}:${next}"]`;
    setKind(
      k,
      list.filter((x) => x !== d),
    );
    setAnnouncement(`Removed: ${leadLabel(d).toLowerCase()}, for ${label.toLowerCase()}`);
  };

  const save = () =>
    update.mutateAsync({ reminder_days: days, postal_buffer_days: buffer }).then((p) => {
      setDays(completeReminderDays(p.reminder_days));
      setBuffer(p.postal_buffer_days);
      return (
        <>
          Download your{" "}
          <Link to="/settings?section=calendar" preventScrollReset className="font-medium text-accent underline underline-offset-2 hover:no-underline">
            calendar file
          </Link>{" "}
          again so its alarms match.
        </>
      );
    });

  return (
    <section aria-labelledby="set-reminders">
      <SectionHeading
        id="set-reminders"
        title="Reminders"
        description="When Ordnung nudges you before a date — in the app, on your desktop and as alarms in your calendar file."
      />
      <p role="status" className="sr-only">
        {announcement}
      </p>
      <div className="space-y-5">
        <SettingsCard
          footer={
            <SaveBar
              dirty={dirty}
              saving={update.isPending}
              onSave={save}
              onDiscard={() => {
                setDays(saved);
                setBuffer(profile.postal_buffer_days);
              }}
            />
          }
        >
          <ul ref={listRef} className="-my-3 divide-y divide-line">
            {REMINDER_KINDS.map(({ kind, label, hint }) => {
              const list = days[kind] ?? [];
              return (
                <li key={kind} className="flex flex-col gap-2.5 py-3.5 sm:flex-row sm:items-center sm:gap-4">
                  <div className="flex min-w-0 items-center gap-3 sm:w-60 sm:shrink-0">
                    <KindIcon kind={kind} size="sm" />
                    <div className="min-w-0">
                      <p className="text-[14px] font-medium text-ink">{label}</p>
                      <p className="text-[12.5px] leading-snug text-muted">{hint}</p>
                    </div>
                  </div>
                  {/* the chips are the list; "+ Add" follows them in the same wrapping row */}
                  <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
                    {list.length ? (
                      <ul className="contents" aria-label={`Reminders for ${label.toLowerCase()}`}>
                        {list.map((d) => (
                          <li key={d} className="inline-flex h-7 items-center gap-0.5 rounded-full bg-surface-2 pl-2.5 pr-0.5 text-[12.5px] font-medium text-ink">
                            {leadLabel(d)}
                            <button
                              type="button"
                              data-remove={`${kind}:${d}`}
                              onClick={() => remove(kind, label, list, d)}
                              className="grid size-6 place-items-center rounded-full text-muted transition-colors hover:bg-surface-3 hover:text-ink"
                              aria-label={`Remove reminder ${leadLabel(d).toLowerCase()} for ${label.toLowerCase()}`}
                            >
                              <X className="size-3.5" aria-hidden />
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-[12.5px] text-muted">No reminders</p>
                    )}
                    <AddLead kind={kind} label={label} existing={list} onAdd={(d) => add(kind, label, list, d)} />
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="mt-6 border-t border-line pt-5">
            <h3 className="text-[14px] font-semibold text-ink">Head start for letters by post</h3>
            <p className="mt-1 text-[13px] leading-relaxed text-muted">
              Letters that must arrive by a deadline get an earlier “send by” date, so the post has time. Online forms, email and fax need no head start.
            </p>
            <Field
              id="postal-buffer"
              label="Time to allow for the post"
              className="mt-4"
              hint={
                <>
                  Recommended: {POSTAL_BUFFER_RECOMMENDED} working days. Since 2025 Deutsche Post only has to deliver most letters within 3 working days, so
                  less is risky.
                  {buffer < POSTAL_BUFFER_RECOMMENDED ? (
                    <strong className="font-medium text-warn-ink"> Less than {POSTAL_BUFFER_RECOMMENDED} days may be too short.</strong>
                  ) : null}
                </>
              }
            >
              <Select value={String(buffer)} onChange={(e) => setBuffer(Number(e.target.value))} className={FIELD_WIDTH}>
                {[2, 3, 4, 5, 6, 7].map((n) => (
                  <option key={n} value={n}>
                    {n} working days
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        </SettingsCard>
        <BrowserNotificationsCard />
        <DesktopNotificationsCard />
      </div>
    </section>
  );
}
