import { useState } from "react";
import { Link } from "react-router";
import { ChevronRight, Languages } from "lucide-react";
import { useUpdateSettings } from "@/api/hooks";
import type { AppSettings, ModelSettings, Profile } from "@/api/types";
import { Field, Select, Switch } from "@/components/ui/Field";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { LANGUAGES } from "@/features/onboarding/options";
import { cn } from "@/lib/utils";
import { FIELD_WIDTH, SaveBar, SectionHeading, SettingsCard } from "./SettingsCard";

type Model = "haiku" | "sonnet" | "opus";

/** What the language setting is called everywhere in Settings. */
export const LANGUAGE_SETTING = "Language for explanations";

/** Jobs that only run when their switch below is on: the row says so instead of offering a model. */
type Optional = { flag: "llm_brief" | "llm_review"; off: string };

const PURPOSES: { key: keyof ModelSettings; label: string; hint: string; optional?: Optional }[] = [
  { key: "extract", label: "Understanding letters", hint: "Reads each letter and finds dates, amounts and what to do" },
  { key: "transcribe", label: "Reading photos", hint: "Turns phone photos and scans into text" },
  { key: "ask", label: "Answering questions", hint: "Ask — looks things up in your records" },
  { key: "draft", label: "Drafting letters", hint: "Polite wording and the translation" },
  {
    key: "review",
    // not "Weekly review": that names the weekly session (/week); this is the model job that suggests Ideas
    label: "Weekly Ideas",
    hint: "Suggests Ideas once a week",
    optional: { flag: "llm_review", off: "Off — Ideas come from Ordnung's own rules (switch below)" },
  },
  {
    key: "brief",
    label: "Daily note",
    hint: "The short note on Today",
    optional: { flag: "llm_brief", off: "Off — Today shows a plain note built from your dates (switch below)" },
  },
];

const MODEL_OPTIONS: { value: Model; label: string }[] = [
  { value: "haiku", label: "Haiku" },
  { value: "sonnet", label: "Sonnet" },
  { value: "opus", label: "Opus" },
];

const MODEL_NOTES: { model: string; note: string }[] = [
  { model: "Haiku", note: "fastest, fine for short notes" },
  { model: "Sonnet", note: "balanced, recommended for letters" },
  { model: "Opus", note: "most careful, slowest" },
];

const asModel = (v: string): Model => (v === "haiku" || v === "opus" ? v : "sonnet");

type AiForm = Pick<AppSettings, "models" | "concurrency" | "llm_brief" | "llm_review">;
const pick = (s: AppSettings): AiForm => ({ models: { ...s.models }, concurrency: s.concurrency, llm_brief: s.llm_brief, llm_review: s.llm_review });
const same = (a: AiForm, b: AiForm) =>
  a.concurrency === b.concurrency && a.llm_brief === b.llm_brief && a.llm_review === b.llm_review && PURPOSES.every(({ key }) => a.models[key] === b.models[key]);

/** "AI & models": which Claude model does what, how many letters at once, the daily note. */
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
        description="Ordnung uses your own Claude account. Pick which model does which job — faster models use less of your plan, more careful ones take longer."
      />
      <div className="space-y-5">
        <SettingsCard footer={<SaveBar dirty={dirty} saving={update.isPending} onSave={save} onDiscard={() => setForm(saved)} />}>
          <ul aria-label="The models" className="mb-4 flex flex-wrap gap-x-5 gap-y-1 rounded-xl bg-surface-2/60 px-3.5 py-2.5 text-[12.5px] leading-5 text-muted">
            {MODEL_NOTES.map(({ model, note }) => (
              <li key={model}>
                <strong className="font-semibold text-ink">{model}</strong> — {note}
              </li>
            ))}
          </ul>
          <ul className="divide-y divide-line">
            {PURPOSES.map(({ key, label, hint, optional }) => {
              const off = optional ? !form[optional.flag] : false;
              return (
                <li key={key} className="flex flex-col gap-2.5 py-3.5 first:pt-1 last:pb-0 sm:flex-row sm:items-center sm:gap-4">
                  <div className="min-w-0 flex-1">
                    <p className={cn("text-[14px] font-medium", off ? "text-muted" : "text-ink")}>{label}</p>
                    <p className="text-[12.5px] text-muted">{off && optional ? optional.off : hint}</p>
                  </div>
                  {/* a job that is switched off keeps its model, but can't be changed until it's on again */}
                  <fieldset disabled={off} className="m-0 min-w-0 border-0 p-0 disabled:opacity-50">
                    <SegmentedControl
                      size="sm"
                      fill="phone"
                      // only the first letter: "Model for weekly Ideas" keeps the name Ideas
                      label={`Model for ${label.charAt(0).toLowerCase()}${label.slice(1)}`}
                      value={asModel(form.models[key])}
                      onChange={(v) => setForm((f) => ({ ...f, models: { ...f.models, [key]: v } }))}
                      options={MODEL_OPTIONS}
                    />
                  </fieldset>
                </li>
              );
            })}
          </ul>

          <div className="mt-5 grid gap-5 border-t border-line pt-5">
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

        <Link to="/settings?section=region" preventScrollReset className="card flex items-center gap-3 p-4 transition-colors hover:border-line-strong sm:px-6">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
            <Languages className="size-4" aria-hidden />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[14px] font-medium text-ink">{LANGUAGE_SETTING}</span>
            <span className="block text-[12.5px] text-muted">
              {lang ? `${lang.label}${lang.label !== lang.en ? ` (${lang.en})` : ""}` : profile.language} — change it in Region & language
            </span>
          </span>
          <ChevronRight className="size-4 shrink-0 text-faint" aria-hidden />
        </Link>
      </div>
    </section>
  );
}
