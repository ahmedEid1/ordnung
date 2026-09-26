import { useState } from "react";
import { Lock } from "lucide-react";
import { useUpdateProfile } from "@/api/hooks";
import type { Profile } from "@/api/types";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { formatIban, ibanLooksValid, normalizeIban } from "@/lib/format";
import { SaveBar, SectionHeading, SettingsCard } from "./SettingsCard";

type ProfileForm = Pick<Profile, "name" | "address" | "email" | "phone" | "iban">;

// the IBAN is shown in blocks of four and compared (and sent) without spaces
const pick = (p: Profile): ProfileForm => ({ name: p.name, address: p.address, email: p.email, phone: p.phone, iban: p.iban ? formatIban(p.iban) : "" });
const same = (k: keyof ProfileForm, a: ProfileForm, b: ProfileForm) => (k === "iban" ? normalizeIban(a.iban) === normalizeIban(b.iban) : a[k] === b[k]);

/** "Profile & address": the sender block of every letter, and the account refunds go to. */
export function ProfileSection({ profile }: { profile: Profile }) {
  const update = useUpdateProfile();
  const [form, setForm] = useState<ProfileForm>(() => pick(profile));
  const saved = pick(profile);
  const dirty = (Object.keys(saved) as (keyof ProfileForm)[]).some((k) => !same(k, saved, form));
  const emailInvalid = Boolean(form.email) && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email);
  const ibanInvalid = Boolean(form.iban.trim()) && !ibanLooksValid(form.iban);
  const set = (k: keyof ProfileForm) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = () => {
    if (ibanInvalid) return;
    update.mutate(
      { ...form, iban: normalizeIban(form.iban) },
      {
        onSuccess: (p) => {
          setForm(pick(p));
          toast.success("Profile saved", { description: "New letters use this name and address." });
        },
      },
    );
  };

  return (
    <section aria-labelledby="set-profile">
      <SectionHeading id="set-profile" title="Profile & address" description="Your name and address appear as the sender on letters Ordnung drafts for you." />
      <SettingsCard footer={<SaveBar dirty={dirty} invalid={ibanInvalid} saving={update.isPending} onSave={save} onDiscard={() => setForm(saved)} />}>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Full name" hint="As on your ID and contracts." className="sm:col-span-2">
            <Input value={form.name} onChange={set("name")} autoComplete="name" />
          </Field>
          <Field label="Postal address" hint="Street and house number, then postcode and town — one per line." className="sm:col-span-2">
            <Textarea value={form.address} onChange={set("address")} rows={3} autoComplete="street-address" className="min-h-20" />
          </Field>
          <Field label="Email" optional error={emailInvalid ? "This doesn't look like an email address." : undefined}>
            <Input type="email" value={form.email} onChange={set("email")} autoComplete="email" />
          </Field>
          <Field label="Phone" optional>
            <Input type="tel" value={form.phone} onChange={set("phone")} autoComplete="tel" />
          </Field>
          <Field
            label="IBAN for refunds"
            optional
            className="sm:col-span-2"
            hint="Printed only in letters that ask for money back, like your deposit."
            error={ibanInvalid ? "That IBAN isn't valid — check it against your bank card or banking app." : undefined}
          >
            <Input
              value={form.iban}
              onChange={set("iban")}
              onBlur={() => !ibanInvalid && form.iban.trim() && setForm((f) => ({ ...f, iban: formatIban(normalizeIban(f.iban)) }))}
              placeholder="DE00 0000 0000 0000 0000 00"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              className="font-mono tracking-wide sm:max-w-sm"
            />
          </Field>
        </div>
        <p className="mt-5 flex items-center gap-2 text-[12.5px] text-muted">
          <Lock className="size-3.5 shrink-0" aria-hidden /> Stored only on this computer and printed on your letters. Your address and IBAN are never sent to Claude.
        </p>
      </SettingsCard>
    </section>
  );
}
