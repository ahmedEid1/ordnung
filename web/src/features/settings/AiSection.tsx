import { useState } from "react";
import { Link } from "react-router";
import { ChevronRight, Cpu, Languages } from "lucide-react";
import { useUpdateSettings } from "@/api/hooks";
import type { AppSettings, Profile } from "@/api/types";
import { Field, Select, Switch } from "@/components/ui/Field";
import { LANGUAGES } from "@/features/onboarding/options";
import { FIELD_WIDTH, SaveBar, SectionHeading, SettingsCard } from "./SettingsCard";

/** What the language setting is called everywhere in Settings. */
export const LANGUAGE_SETTING = "Language for explanations";

type AiForm = Pick<AppSettings, "concurrency" | "llm_brief" | "llm_review">;
const pick = (s: AppSettings): AiForm => ({ concurrency: s.concurrency, llm_brief: s.llm_brief, llm_review: s.llm_review });
const same = (a: AiForm, b: AiForm) => a.concurrency === b.concurrency && a.llm_brief === b.llm_brief && a.llm_review === b.llm_review;

/** A row that leads to a setting kept elsewhere (the model, the language): its name and its current value. */
function ElsewhereLink({ to, icon: Icon, label, value }: { to: string; icon: typeof Cpu; label: string; value: string }) {
  return (
    <Link to={to} preventScrollReset className="card flex items-center gap-3 p-4 transition-colors hover:border-line-strong sm:px-6">
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
        <Icon className="size-4" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-medium text-ink">{label}</span>
        <span className="block text-[12.5px] text-muted">{value}</span>
      </span>
      <ChevronRight className="size-4 shrink-0 text-faint" aria-hidden />
    </Link>
  );
}

/**
 * "AI & models": how many letters at once, the daily note and the weekly Ideas. One model does every
 * job — the one under Claude connection → Model — so no job offers a model of its own here.
 */
export function AiSection({ settings, profile }: { settings: AppSettings; profile: Profile }) {
  const update = useUpdateSettings();
  const saved = pick(settings);
  const [form, setForm] = useState<AiForm>(() => pick(settings));
  const dirty = !same(form, saved);
  const lang = LANGUAGES.find((l) => l.code === profile.language);

  const save = () =>
    update.mutateAsync(form).then((s) => {
      setForm(pick(s));
      return "They apply to the next letter or question.";
    });

  return (
    <section aria-labelledby="set-ai">
      <SectionHeading
        id="set-ai"
        title="AI & models"
        description="Ordnung uses your own Claude account. One model does every job — Sonnet 5 unless you choose another under Claude connection → Model."
      />
      <div className="space-y-5">
        <SettingsCard footer={<SaveBar dirty={dirty} saving={update.isPending} onSave={save} onDiscard={() => setForm(saved)} />}>
          <div className="grid gap-5">
            <Field label="Letters read at the same time" hint="More is faster when you add a pile of letters, but uses your plan's limits sooner.">
              <Select value={String(form.concurrency)} onChange={(e) => setForm((f) => ({ ...f, concurrency: Number(e.target.value) }))} className={FIELD_WIDTH}>
                {[1, 2, 3, 4].map((n) => (
                  <option key={n} value={n}>
                    {n} {n === 1 ? "letter" : "letters"}
                  </option>
                ))}
              </Select>
            </Field>
            <Switch
              checked={form.llm_brief}
              onCheckedChange={(v) => setForm((f) => ({ ...f, llm_brief: v }))}
              label="Let Claude write the daily note"
              description="When off, Today shows a plain note built from your dates — no AI call."
            />
            <Switch
              checked={form.llm_review}
              onCheckedChange={(v) => setForm((f) => ({ ...f, llm_review: v }))}
              label="Let Claude look for Ideas once a week"
              description="Sends a short summary of your open to-dos, contracts and recent letters. When off, Ideas come from Ordnung's own rules only."
            />
          </div>
        </SettingsCard>

        <ElsewhereLink to="/settings?section=claude" icon={Cpu} label="Model" value={`${settings.model} — change it in Claude connection`} />
        <ElsewhereLink
          to="/settings?section=region"
          icon={Languages}
          label={LANGUAGE_SETTING}
          value={`${lang ? `${lang.label}${lang.label !== lang.en ? ` (${lang.en})` : ""}` : profile.language} — change it in Region & language`}
        />
      </div>
    </section>
  );
}
