import { useRef, useState } from "react";
import { Lock } from "lucide-react";
import { useUpdateProfile } from "@/api/hooks";
import type { Profile } from "@/api/types";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { SaveBar, SectionHeading, SettingsCard } from "./SettingsCard";

type ProfileForm = Pick<Profile, "name" | "address" | "email" | "phone">;

const pick = (p: Profile): ProfileForm => ({ name: p.name, address: p.address, email: p.email, phone: p.phone });

/** What gets saved: no stray spaces around the values (the address keeps its lines). */
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
  };
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** The profile's mistakes, per field (none: it can be saved). */
export function profileErrors(f: ProfileForm): Partial<Record<keyof ProfileForm, string>> {
  const clean = cleanProfile(f);
  const errors: Partial<Record<keyof ProfileForm, string>> = {};
  if (!clean.name) errors.name = "Enter your name — it's the sender on your letters.";
  if (clean.email && !EMAIL.test(clean.email)) errors.email = "This doesn't look like an email address — like name@example.de.";
  return errors;
}

/** "Profile & address": the sender block of every letter. */
export function ProfileSection({ profile }: { profile: Profile }) {
  const update = useUpdateProfile();
  const [form, setForm] = useState<ProfileForm>(() => pick(profile));
  const saved = pick(profile);
  const dirty = (Object.keys(saved) as (keyof ProfileForm)[]).some((k) => saved[k] !== form[k]);
  // a mistake shows once you leave the field (or try to save), not while you type
  const [touched, setTouched] = useState<ReadonlySet<keyof ProfileForm>>(() => new Set());
  const [attempted, setAttempted] = useState(false);
  const errors = profileErrors(form);
  const invalid = Object.keys(errors).length > 0;
  const shown = (k: keyof ProfileForm) => (attempted || touched.has(k) ? errors[k] : undefined);
  const nameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  const set = (k: keyof ProfileForm) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const leave = (k: keyof ProfileForm) => () => setTouched((t) => (t.has(k) ? t : new Set(t).add(k)));

  const save = () =>
    update.mutateAsync(cleanProfile(form)).then((p) => {
      setForm(pick(p));
      setTouched(new Set());
      setAttempted(false);
      return "New letters use this name and address.";
    });

  const showErrors = () => {
    setAttempted(true);
    const first = errors.name ? nameRef : emailRef;
    requestAnimationFrame(() => first.current?.focus());
  };

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
              value={form.address}
              onChange={set("address")}
              // the browser only scrolls the caret into view: bring the whole field clear of the phone's tab bar
              onFocus={(e) => e.currentTarget.scrollIntoView?.({ block: "nearest" })}
              rows={3}
              autoComplete="street-address"
              className="min-h-20"
            />
          </Field>
          <Field label="Email" optional error={shown("email")}>
            <Input ref={emailRef} type="email" value={form.email} onChange={set("email")} onBlur={leave("email")} autoComplete="email" />
          </Field>
          <Field label="Phone" optional>
            <Input type="tel" value={form.phone} onChange={set("phone")} autoComplete="tel" />
          </Field>
        </div>
        <p className="mt-5 flex items-start gap-2 text-[12.5px] leading-5 text-muted">
          <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden /> Stored only on this computer and printed on your letters.
        </p>
      </SettingsCard>
    </section>
  );
}
