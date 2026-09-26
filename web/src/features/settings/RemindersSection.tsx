import { useState, type FormEvent } from "react";
import { BellRing, Mailbox, Plus, X } from "lucide-react";
import { useUpdateProfile } from "@/api/hooks";
import type { ItemKind, Profile } from "@/api/types";
import { KindIcon } from "@/components/ui/KindBadge";
import { Button } from "@/components/ui/Button";
import { Select, Switch } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { setBrowserNotifications, showNotification, useNotifyState } from "@/features/notifications/useBrowserNotifications";
import { isStaticDemo } from "@/mocks/mode";
import { completeReminderDays, leadLabel, MAX_LEAD_DAYS, normalizeLeadDays, REMINDER_KINDS, sameReminderDays } from "./logic";
import { SaveBar, SectionHeading, SettingsCard } from "./SettingsCard";

function AddLead({ kind, label, onAdd }: { kind: ItemKind; label: string; onAdd: (d: number) => void }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const n = Number(value);
  const valid = value !== "" && Number.isInteger(n) && n >= 0 && n <= MAX_LEAD_DAYS;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    onAdd(n);
    setValue("");
    setOpen(false);
  };
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex h-7 items-center gap-1 rounded-full border border-dashed border-line-strong px-2.5 text-[12.5px] font-medium text-muted transition-colors hover:border-accent/60 hover:text-accent"
        aria-label={`Add a reminder for ${label.toLowerCase()}`}
      >
        <Plus className="size-3.5" aria-hidden /> Add
      </button>
    );
  }
  return (
    <form onSubmit={submit} className="inline-flex items-center gap-1">
      <label className="sr-only" htmlFor={`lead-${kind}`}>
        Days before, for {label.toLowerCase()}
      </label>
      <input
        id={`lead-${kind}`}
        autoFocus
        type="number"
        inputMode="numeric"
        min={0}
        max={MAX_LEAD_DAYS}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        onBlur={() => !value && setOpen(false)}
        placeholder="days"
        className="h-7 w-16 rounded-full border border-accent/60 bg-surface px-2.5 text-[12.5px] text-ink outline-none ring-3 ring-accent/15"
      />
      <button type="submit" disabled={!valid} className="h-7 rounded-full bg-accent px-2.5 text-[12.5px] font-medium text-on-accent disabled:opacity-50">
        Add
      </button>
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

  const setKind = (k: ItemKind, list: number[]) => setDays((d) => ({ ...d, [k]: normalizeLeadDays(list) }));

  const save = () =>
    update.mutate(
      { reminder_days: days, postal_buffer_days: buffer },
      {
        onSuccess: (p) => {
          setDays(completeReminderDays(p.reminder_days));
          setBuffer(p.postal_buffer_days);
          toast.success("Reminders saved", { description: "Download your calendar file again so its alarms match." });
        },
      },
    );

  return (
    <section aria-labelledby="set-reminders">
      <SectionHeading
        id="set-reminders"
        title="Reminders"
        description="When Ordnung nudges you before a date — in the app and as alarms in your calendar file."
      />
      <div className="space-y-5">
        <SettingsCard footer={<SaveBar dirty={dirty} saving={update.isPending} onSave={save} onDiscard={() => { setDays(saved); setBuffer(profile.postal_buffer_days); }} />}>
          <ul className="-my-3 divide-y divide-line">
            {REMINDER_KINDS.map(({ kind, label, hint }) => {
              const list = days[kind] ?? [];
              return (
                <li key={kind} className="flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center">
                  <div className="flex min-w-0 items-center gap-3 sm:w-60 sm:shrink-0">
                    <KindIcon kind={kind} size="sm" />
                    <div className="min-w-0">
                      <p className="text-[14px] font-medium text-ink">{label}</p>
                      <p className="truncate text-[12.5px] text-muted">{hint}</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 sm:justify-end sm:flex-1" role="list" aria-label={`Reminders for ${label.toLowerCase()}`}>
                    {list.length ? (
                      list.map((d) => (
                        <span key={d} role="listitem" className="inline-flex h-7 items-center gap-1 rounded-full bg-surface-2 pl-2.5 pr-1 text-[12.5px] font-medium text-ink">
                          {leadLabel(d)}
                          <button
                            type="button"
                            onClick={() => setKind(kind, list.filter((x) => x !== d))}
                            className="grid size-5 place-items-center rounded-full text-muted transition-colors hover:bg-surface-3 hover:text-ink"
                            aria-label={`Remove reminder ${leadLabel(d).toLowerCase()} for ${label.toLowerCase()}`}
                          >
                            <X className="size-3" aria-hidden />
                          </button>
                        </span>
                      ))
                    ) : (
                      <span role="listitem" className="text-[12.5px] text-muted">
                        No reminders
                      </span>
                    )}
                    <AddLead kind={kind} label={label} onAdd={(d) => setKind(kind, [...list, d])} />
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
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className="grid size-9 place-items-center rounded-lg bg-surface-2 text-muted">
                <Mailbox className="size-4" aria-hidden />
              </span>
              <label htmlFor="postal-buffer" className="text-[14px] text-ink">
                Send letters
              </label>
              <Select id="postal-buffer" value={String(buffer)} onChange={(e) => setBuffer(Number(e.target.value))} className="w-44">
                {[2, 3, 4, 5, 6, 7].map((n) => (
                  <option key={n} value={n}>
                    {n} working days
                  </option>
                ))}
              </Select>
              <span className="text-[14px] text-ink">before they must arrive</span>
            </div>
            <p className="mt-3 text-[12.5px] leading-5 text-muted">
              Recommended: 4 working days. Since 2025 Deutsche Post only has to deliver most letters within three working days, so less is risky.
              {buffer < 4 ? <strong className="font-medium text-warn-ink"> Less than 4 days may be too short.</strong> : null}
            </p>
          </div>
        </SettingsCard>
        <BrowserNotificationsCard />
      </div>
    </section>
  );
}
