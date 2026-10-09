import { useState } from "react";
import { Clock, Globe2 } from "lucide-react";
import { useUpdateProfile } from "@/api/hooks";
import type { Profile } from "@/api/types";
import { Field, Select, Switch } from "@/components/ui/Field";
import { Glossary } from "@/components/ui/Glossary";
import { BUNDESLAENDER, LANGUAGES } from "@/features/onboarding/options";
import { LANGUAGE_SETTING } from "./AiSection";
import { FIELD_WIDTH, SaveBar, SectionHeading, SettingsCard } from "./SettingsCard";

type RegionForm = Pick<Profile, "region" | "language" | "is_student_visa">;
const pick = (p: Profile): RegionForm => ({ region: p.region, language: p.language, is_student_visa: p.is_student_visa });

/** "Region & language": the Bundesland (public holidays), explanation language, student permit. */
export function RegionSection({ profile }: { profile: Profile }) {
  const update = useUpdateProfile();
  const [form, setForm] = useState<RegionForm>(() => pick(profile));
  const saved = pick(profile);
  const dirty = form.region !== saved.region || form.language !== saved.language || form.is_student_visa !== saved.is_student_visa;
  const state = BUNDESLAENDER.find((b) => b.code === form.region);

  const save = () => {
    const regionChanged = form.region !== saved.region;
    const language = form.language !== saved.language ? LANGUAGES.find((l) => l.code === form.language) : undefined;
    return update.mutateAsync(form).then((p) => {
      setForm(pick(p));
      if (regionChanged && state) return `Your dates were recalculated: payments you make now count the holidays of ${state.name}.`;
      if (language) return `New explanations are written in ${language.label}.`;
      return undefined;
    });
  };

  return (
    <section aria-labelledby="set-region">
      <SectionHeading
        id="set-region"
        title="Region & language"
        description="Where you live decides the holidays for payments you make. Letters from authorities use their own state's holidays, or nationwide ones until you set the sender's state or answer Ordnung's question about it."
      />
      <SettingsCard footer={<SaveBar dirty={dirty} saving={update.isPending} onSave={save} onDiscard={() => setForm(saved)} />}>
        <div className="grid gap-6">
          <Field
            label="Your federal state (Bundesland)"
            hint={
              <>
                A deadline that ends on a public holiday moves to the next working day — and holidays differ between states.
                {state ? ` Payments you make count the holidays of ${state.name}${state.en ? ` (${state.en})` : ""}.` : ""}
              </>
            }
          >
            {/* German names only: "Mecklenburg-Vorpommern (Mecklenburg-Western Pomerania)" doesn't fit a phone; the hint has the English */}
            <Select value={form.region} onChange={(e) => setForm((f) => ({ ...f, region: e.target.value }))} className={FIELD_WIDTH}>
              {BUNDESLAENDER.map((b) => (
                <option key={b.code} value={b.code}>
                  {b.name}
                </option>
              ))}
            </Select>
          </Field>

          <Field label={LANGUAGE_SETTING} hint="Explanations, translations and answers are written in this language. Letters to German offices stay in German.">
            <Select value={form.language} onChange={(e) => setForm((f) => ({ ...f, language: e.target.value }))} className={FIELD_WIDTH}>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                  {l.label !== l.en ? ` — ${l.en}` : ""}
                </option>
              ))}
            </Select>
          </Field>

          {/* a framed row where there is room; on phones the switch's text gets the card's whole width */}
          <div className="sm:rounded-xl sm:border sm:border-line sm:p-4">
            <Switch
              checked={form.is_student_visa}
              onCheckedChange={(v) => setForm((f) => ({ ...f, is_student_visa: v }))}
              label="I live in Germany on a residence permit"
              description={
                <>
                  Ordnung then reminds you early to extend your <Glossary term="Aufenthaltstitel" plain /> and checks that your passport stays valid long enough.
                </>
              }
            />
          </div>

          <dl className="grid gap-3 text-[13px] sm:grid-cols-2">
            <div className="flex items-center gap-2.5 rounded-lg bg-surface-2/60 px-3 py-2.5">
              <Globe2 className="size-4 shrink-0 text-muted" aria-hidden />
              <dt className="text-muted">Country</dt>
              <dd className="ml-auto font-medium text-ink">Germany</dd>
            </div>
            <div className="flex items-center gap-2.5 rounded-lg bg-surface-2/60 px-3 py-2.5">
              <Clock className="size-4 shrink-0 text-muted" aria-hidden />
              <dt className="whitespace-nowrap text-muted">Time zone</dt>
              <dd className="ml-auto min-w-0 text-right font-medium text-ink">{profile.timezone === "Europe/Berlin" ? "Berlin (CET/CEST)" : profile.timezone}</dd>
            </div>
          </dl>
        </div>
      </SettingsCard>
    </section>
  );
}
