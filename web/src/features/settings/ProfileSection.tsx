import { useId, useRef, useState } from "react";
import { Link } from "react-router";
import { Lock, MapPinHouse } from "lucide-react";
import { useDashboard, useUpdateProfile } from "@/api/hooks";
import type { Profile } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Checkbox, Field, Input, Textarea } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { formatIban, ibanLooksValid, normalizeIban } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { focusWhenReady } from "@/features/today/focus";
import { MOVING_CHECKLIST_ID, moveDayError, moveDayRange, movedLine, movingRows, moveStanding } from "@/features/today/moving";
import { SaveBar, SectionHeading, SettingsCard } from "./SettingsCard";

type ProfileForm = Pick<Profile, "name" | "address" | "email" | "phone" | "iban">;

// the IBAN is shown in blocks of four and compared (and saved) without spaces
const pick = (p: Profile): ProfileForm => ({ name: p.name, address: p.address, email: p.email, phone: p.phone, iban: p.iban ? formatIban(p.iban) : "" });
const same = (k: keyof ProfileForm, a: ProfileForm, b: ProfileForm) => (k === "iban" ? normalizeIban(a.iban) === normalizeIban(b.iban) : a[k] === b[k]);

/** What gets saved: no stray spaces around the values (the address keeps its lines), the IBAN without any. */
export function cleanProfile(f: ProfileForm): ProfileForm {
  return {
    name: f.name.trim().replace(/\s+/g, " "),
    address: f.address
      .split("\n")
      .map((l) => l.trim())
      .join("\n")
      .trim(),
    email: f.email.trim(),
    phone: f.phone.trim(),
    iban: normalizeIban(f.iban),
  };
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** The profile's mistakes, per field (none: it can be saved). */
export function profileErrors(f: ProfileForm): Partial<Record<keyof ProfileForm, string>> {
  const clean = cleanProfile(f);
  const errors: Partial<Record<keyof ProfileForm, string>> = {};
  if (!clean.name) errors.name = "Enter your name — it's the sender on your letters.";
  if (clean.email && !EMAIL.test(clean.email)) errors.email = "This doesn't look like an email address — like name@example.de.";
  if (clean.iban && !ibanLooksValid(clean.iban)) errors.iban = "That IBAN isn't valid — check it against your bank card or banking app.";
  return errors;
}

/** The stored move's link and button: text-sized, in the line's flow. */
const MOVE_ACTION =
  "inline-flex min-h-6 items-center rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60";

/** An address as it is saved: each line trimmed, no empty lines around it. */
const cleanAddress = (address: string) => cleanProfile({ name: "", address, email: "", phone: "", iban: "" }).address;

/**
 * Whether the "I moved" box is offered: the person changed an address that was already saved (the first
 * address ever entered is no move, and neither is any other field).
 */
export function offersMove(savedAddress: string, form: Pick<ProfileForm, "address">): boolean {
  const before = cleanAddress(savedAddress);
  return before !== "" && cleanAddress(form.address) !== before;
}

/**
 * Whether "Moved recently? Start the moving checklist" is offered: for someone who saved the new address first.
 * An address is saved, the field still shows it, and no move stands.
 */
export function offersLateMove(savedAddress: string, form: Pick<ProfileForm, "address">, standing: boolean): boolean {
  const saved = cleanAddress(savedAddress);
  return !standing && saved !== "" && cleanAddress(form.address) === saved;
}

/** What is wrong with the address before the move (`null`: nothing). */
export function oldAddressError(oldAddress: string, savedAddress: string): string | null {
  const old = cleanAddress(oldAddress);
  if (!old) return "Enter the address you moved from.";
  if (old === cleanAddress(savedAddress)) return "That's the address saved above. If it's still your old one, change it to your new address and tick “I moved”.";
  return null;
}

/**
 * "Moved recently? Start the moving checklist", for someone who saved the new address first: the address before
 * and the day moved in, then "Start the checklist". The address saved stays. Nothing starts without that click,
 * and a mistake shows only once it was pressed.
 */
function StartMove({
  savedAddress,
  today,
  busy,
  onStart,
}: {
  savedAddress: string;
  today: string;
  busy: boolean;
  /** Saves the move (rejects when the save failed: the mutation's error toast says why). */
  onStart: (move: { moved_on: string; old_address: string }) => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [oldAddress, setOldAddress] = useState("");
  const [movedOn, setMovedOn] = useState("");
  const [attempted, setAttempted] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const oldRef = useRef<HTMLTextAreaElement>(null);
  const dayRef = useRef<HTMLInputElement>(null);
  const panelId = useId();
  const addressError = oldAddressError(oldAddress, savedAddress);
  const dayError = moveDayError(movedOn, today);

  const close = () => {
    setOpen(false);
    setOldAddress("");
    setMovedOn("");
    setAttempted(false);
  };
  const toggle = () => {
    if (open) {
      close();
      return;
    }
    setOpen(true);
    requestAnimationFrame(() => oldRef.current?.focus());
  };
  const start = () => {
    setAttempted(true);
    if (addressError || dayError) {
      const first = addressError ? oldRef : dayRef;
      requestAnimationFrame(() => first.current?.focus());
      return;
    }
    // once saved the move stands, and its line takes this one's place
    onStart({ moved_on: movedOn, old_address: cleanAddress(oldAddress) }).then(close, () => undefined);
  };

  return (
    <div className="-mt-2 flex flex-col gap-3 sm:col-span-2">
      {/* a wrapped label stays left-aligned, its icon by the first line */}
      <p className="flex items-start gap-1.5 text-[13px] leading-5 text-muted">
        <MapPinHouse className="mt-[5px] size-3.5 shrink-0" aria-hidden />
        <button ref={toggleRef} type="button" aria-expanded={open} aria-controls={open ? panelId : undefined} onClick={toggle} className={`${MOVE_ACTION} text-left`}>
          Moved recently? Start the moving checklist
        </button>
      </p>
      {open ? (
        <div id={panelId} className="flex flex-col gap-4 rounded-xl bg-surface-2/60 px-3.5 py-3">
          <p className="text-sm leading-5 text-pretty text-muted">
            For when your new address is saved above — it stays as it is. Today then lists who to tell, starting with registering at the{" "}
            <span lang="de">Bürgeramt</span> within two weeks.
          </p>
          <Field label="Your previous address" hint="Street and house number, then postcode and town — one per line." error={attempted ? (addressError ?? undefined) : undefined}>
            <Textarea ref={oldRef} value={oldAddress} onChange={(e) => setOldAddress(e.target.value)} rows={3} required autoComplete="off" className="min-h-20" />
          </Field>
          <Field label="Moved in on" hint="Up to six months back, or three months ahead." error={attempted ? (dayError ?? undefined) : undefined} className="sm:max-w-56">
            <Input ref={dayRef} type="date" value={movedOn} onChange={(e) => setMovedOn(e.target.value)} required {...moveDayRange(today)} />
          </Field>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" size="sm" loading={busy} onClick={start}>
              Start the checklist
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => {
                close();
                toggleRef.current?.focus();
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** "Profile & address": the sender block of every letter, the account refunds go to, and "I moved" (or "Moved recently?"). */
export function ProfileSection({ profile }: { profile: Profile }) {
  const update = useUpdateProfile();
  const today = useTodayISO();
  const [form, setForm] = useState<ProfileForm>(() => pick(profile));
  const saved = pick(profile);
  const dirty = (Object.keys(saved) as (keyof ProfileForm)[]).some((k) => !same(k, saved, form));
  // "I moved": offered only next to a changed address; the day starts as today
  const [moved, setMoved] = useState(false);
  const [movedOn, setMovedOn] = useState(today);
  const moveOffered = offersMove(profile.address, form);
  const telling = moveOffered && moved;
  // a mistake shows once you leave the field (or try to save), not while you type
  const [touched, setTouched] = useState<ReadonlySet<keyof ProfileForm>>(() => new Set());
  const [attempted, setAttempted] = useState(false);
  const errors = profileErrors(form);
  const dayError = telling ? moveDayError(movedOn, today) : null;
  const invalid = Object.keys(errors).length > 0 || dayError !== null;
  const shown = (k: keyof ProfileForm) => (attempted || touched.has(k) ? errors[k] : undefined);
  const nameRef = useRef<HTMLInputElement>(null);
  const addressRef = useRef<HTMLTextAreaElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const ibanRef = useRef<HTMLInputElement>(null);
  const dayRef = useRef<HTMLInputElement>(null);

  const set = (k: keyof ProfileForm) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const leave = (k: keyof ProfileForm) => () => setTouched((t) => (t.has(k) ? t : new Set(t).add(k)));

  const save = () =>
    // a move goes with the new address in one save: the day, and the address before it
    update.mutateAsync({ ...cleanProfile(form), ...(telling ? { moved_on: movedOn, old_address: profile.address } : {}) }).then((p) => {
      setForm(pick(p));
      setTouched(new Set());
      setAttempted(false);
      setMoved(false);
      return telling ? "Today lists who needs your new address." : "New letters use this name and address.";
    });

  const showErrors = () => {
    setAttempted(true);
    const first = errors.name ? nameRef : errors.email ? emailRef : errors.iban ? ibanRef : dayRef;
    requestAnimationFrame(() => first.current?.focus());
  };

  // the off switch for a move told by mistake (or done with): the rows still open expire; Undo puts it back
  const standing = moveStanding(profile, today);
  // Today's checklist rows still open (null while unknown, or being fetched after a move was saved): with none
  // left there is no card to go to
  const dashboard = useDashboard({ enabled: standing });
  const rowsLeft = dashboard.data && !dashboard.isFetching ? movingRows(dashboard.data.suggestions).length : null;
  const stopChecklist = () => {
    const back = { moved_on: profile.moved_on ?? "", old_address: profile.old_address };
    update.mutateAsync({ moved_on: "", old_address: "" }).then(
      () => {
        focusWhenReady(() => addressRef.current);
        toast({ title: "Moving checklist stopped", undo: () => update.mutateAsync(back).then(() => undefined) });
      },
      () => undefined, // the error toast comes from the mutation's meta
    );
  };
  // "Moved recently?": the new address was saved first, so the move goes alone (the address stays); once it
  // stands, focus goes on to its line. Undo clears it again
  const lateOffered = offersLateMove(profile.address, form, standing);
  const lineRef = useRef<HTMLParagraphElement>(null);
  const startMove = (move: { moved_on: string; old_address: string }) =>
    update.mutateAsync(move).then(() => {
      focusWhenReady(() => lineRef.current?.querySelector<HTMLElement>("a, button") ?? null);
      toast({
        title: "Moving checklist started",
        description: "Today lists who needs your new address.",
        undo: () => update.mutateAsync({ moved_on: "", old_address: "" }).then(() => undefined),
      });
    });

  return (
    <section aria-labelledby="set-profile">
      <SectionHeading id="set-profile" title="Profile & address" description="Your name and address appear as the sender on letters Ordnung drafts for you." />
      <SettingsCard
        footer={
          <SaveBar
            dirty={dirty}
            saving={update.isPending}
            onSave={save}
            invalid={invalid}
            onInvalid={showErrors}
            onDiscard={() => {
              setForm(saved);
              setTouched(new Set());
              setAttempted(false);
              setMoved(false);
            }}
          />
        }
      >
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Full name" hint="As on your ID and contracts." error={shown("name")} className="sm:col-span-2">
            <Input ref={nameRef} value={form.name} onChange={set("name")} onBlur={leave("name")} autoComplete="name" />
          </Field>
          <Field label="Postal address" hint="Street and house number, then postcode and town — one per line." className="sm:col-span-2">
            <Textarea
              ref={addressRef}
              value={form.address}
              onChange={set("address")}
              // the browser only scrolls the caret into view: bring the whole field clear of the phone's tab bar
              onFocus={(e) => e.currentTarget.scrollIntoView?.({ block: "nearest" })}
              rows={3}
              autoComplete="street-address"
              className="min-h-20"
            />
          </Field>
          {moveOffered ? (
            <div className="-mt-2 flex flex-col gap-3 rounded-xl bg-surface-2/60 px-3.5 py-3 sm:col-span-2">
              <Checkbox
                checked={moved}
                onChange={(e) => {
                  setMoved(e.target.checked);
                  if (e.target.checked && !movedOn) setMovedOn(today);
                }}
                label="I moved — list who needs my new address"
                description={
                  <>
                    Today then lists who to tell, starting with registering at the <span lang="de">Bürgeramt</span> within two weeks.
                  </>
                }
              />
              {moved ? (
                <Field label="Moved in on" hint="Up to six months back, or three months ahead." error={attempted || movedOn !== today ? (dayError ?? undefined) : undefined} className="ml-[30px] sm:max-w-56">
                  <Input ref={dayRef} type="date" value={movedOn} onChange={(e) => setMovedOn(e.target.value)} {...moveDayRange(today)} />
                </Field>
              ) : null}
            </div>
          ) : standing && profile.moved_on ? (
            <p ref={lineRef} className="-mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px] leading-5 text-muted sm:col-span-2">
              <MapPinHouse className="size-3.5 shrink-0" aria-hidden />
              <span>{movedLine(profile.moved_on, today)}</span>
              {/* text-sized, but 24 px tall targets (WCAG 2.5.8) */}
              {rowsLeft === 0 ? (
                <span>Everyone on your moving checklist has your new address.</span>
              ) : (
                <Link to={`/#${MOVING_CHECKLIST_ID}`} className={MOVE_ACTION}>
                  Open your moving checklist
                </Link>
              )}
              <span aria-hidden>·</span>
              <button
                type="button"
                onClick={stopChecklist}
                disabled={update.isPending}
                className={MOVE_ACTION}
              >
                Stop the checklist
              </button>
            </p>
          ) : lateOffered ? (
            <StartMove savedAddress={profile.address} today={today} busy={update.isPending} onStart={startMove} />
          ) : null}
          <Field label="Email" optional error={shown("email")}>
            <Input ref={emailRef} type="email" value={form.email} onChange={set("email")} onBlur={leave("email")} autoComplete="email" />
          </Field>
          <Field label="Phone" optional>
            <Input type="tel" value={form.phone} onChange={set("phone")} autoComplete="tel" />
          </Field>
          <Field label="IBAN for refunds" optional className="sm:col-span-2" hint="Printed only in letters that ask for money back, like your deposit." error={shown("iban")}>
            <Input
              ref={ibanRef}
              value={form.iban}
              onChange={set("iban")}
              onBlur={() => {
                leave("iban")();
                // a valid IBAN is shown in blocks of four once you leave the field
                if (form.iban.trim() && ibanLooksValid(form.iban)) setForm((f) => ({ ...f, iban: formatIban(normalizeIban(f.iban)) }));
              }}
              placeholder="DE00 0000 0000 0000 0000 00"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              className="font-ident sm:max-w-sm"
            />
          </Field>
        </div>
        <p className="mt-5 flex items-start gap-2 text-[12.5px] leading-5 text-muted">
          <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden /> Stored only on this computer and printed on your letters. Ordnung never puts
          the address and IBAN you enter here into its requests to Claude — letters you add are read as they are printed.
        </p>
      </SettingsCard>
    </section>
  );
}
