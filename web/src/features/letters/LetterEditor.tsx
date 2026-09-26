import { useEffect, useLayoutEffect, useRef, useState, type ComponentProps } from "react";
import { ChevronDown, Info, Languages, Paperclip, PenLine, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useIsTabletUp } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { findPlaceholders, type EditableFields } from "./logic";

function fit(el: HTMLTextAreaElement) {
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight + 2}px`;
}

/** Textarea that grows with its content (no inner scrollbar). */
function AutoTextarea({ value, className, minRows = 3, ...rest }: ComponentProps<"textarea"> & { value: string; minRows?: number }) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) fit(el);
  }, [value]);
  // re-fit when the width changes (layout, window) or the web font arrives
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let width = el.clientWidth;
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => {
      if (el.clientWidth !== width) {
        width = el.clientWidth;
        fit(el);
      }
    }) : null;
    ro?.observe(el);
    void document.fonts?.ready.then(() => fit(el));
    return () => ro?.disconnect();
  }, []);
  return <textarea ref={ref} value={value} rows={minRows} className={cn("block w-full resize-none overflow-hidden", className)} {...rest} />;
}

const fieldCls =
  "rounded-lg border border-transparent bg-transparent px-2.5 py-1.5 -mx-2.5 text-ink transition-[border-color,background-color,box-shadow] " +
  "hover:border-line hover:bg-surface-2/40 focus-visible:border-accent/60 focus-visible:bg-surface focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-accent/15";

export interface LetterEditorProps {
  value: EditableFields;
  onChange: (next: EditableFields) => void;
  translation: string;
  language: string;
  enclosures: string[];
  /** the German body differs from the one the translation was made for */
  translationStale: boolean;
  /** "Re-translate": ask for a fresh translation of the letter as it stands (offered while stale) */
  onRetranslate?: () => void;
  retranslating?: boolean;
  readOnly?: boolean;
}

function GermanPane({ value, onChange, language, enclosures, readOnly }: Omit<LetterEditorProps, "translation" | "translationStale" | "onRetranslate" | "retranslating">) {
  const [showBlocks, setShowBlocks] = useState(false);
  const set = (k: keyof EditableFields) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value });
  const placeholders = findPlaceholders(`${value.subject}\n${value.body}`);
  return (
    <div className="min-w-0 p-4 sm:p-6" lang={language}>
      <button
        type="button"
        onClick={() => setShowBlocks((s) => !s)}
        aria-expanded={showBlocks}
        className="mb-4 inline-flex items-center gap-1.5 rounded-md text-[12.5px] font-medium text-muted transition-colors hover:text-ink"
      >
        <ChevronDown className={cn("size-3.5 transition-transform", !showBlocks && "-rotate-90")} aria-hidden />
        <span lang="en">Sender, recipient &amp; date</span>
      </button>
      {showBlocks ? (
        <div className="mb-5 grid gap-4 rounded-xl bg-surface-2/50 p-3.5 sm:grid-cols-2">
          <label className="block text-[12px] font-medium text-muted">
            <span lang="en">From (you)</span>
            <AutoTextarea value={value.sender_block} onChange={set("sender_block")} readOnly={readOnly} minRows={3} className={cn(fieldCls, "mx-0 mt-1 text-[13.5px] leading-6")} />
          </label>
          <label className="block text-[12px] font-medium text-muted">
            <span lang="en">To</span>
            <AutoTextarea value={value.recipient_block} onChange={set("recipient_block")} readOnly={readOnly} minRows={3} className={cn(fieldCls, "mx-0 mt-1 text-[13.5px] leading-6")} />
          </label>
          <label className="block text-[12px] font-medium text-muted sm:col-span-2">
            <span lang="en">Place &amp; date</span>
            <input value={value.place_date} onChange={set("place_date")} readOnly={readOnly} className={cn(fieldCls, "mx-0 mt-1 block w-full text-[13.5px]")} />
          </label>
        </div>
      ) : null}

      <label className="block">
        <span className="sr-only" lang="en">
          Subject (Betreff)
        </span>
        <AutoTextarea
          value={value.subject}
          onChange={set("subject")}
          readOnly={readOnly}
          minRows={1}
          placeholder="Betreff"
          className={cn(fieldCls, "text-[15.5px] font-semibold leading-6")}
        />
      </label>
      <label className="mt-3 block">
        <span className="sr-only" lang="en">
          Letter text (German)
        </span>
        <AutoTextarea
          value={value.body}
          onChange={set("body")}
          readOnly={readOnly}
          minRows={10}
          spellCheck
          className={cn(fieldCls, "text-[15px] leading-7")}
        />
      </label>
      {enclosures.length ? (
        <p className="mt-3 flex items-start gap-2 text-[13px] text-muted">
          <Paperclip className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            <span lang="en">Enclosures: </span>
            {enclosures.join(", ")}
          </span>
        </p>
      ) : null}
      {placeholders.length && !readOnly ? (
        <p className="mt-3 flex items-start gap-2 rounded-lg bg-warn-soft px-3 py-2 text-[12.5px] leading-5 text-warn-ink" lang="en">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          Fill in the gaps before sending: {placeholders.map((p) => `„${p}“`).join(", ")}
        </p>
      ) : null}
    </div>
  );
}

function EnglishPane({ translation, stale, onRetranslate, retranslating }: { translation: string; stale: boolean; onRetranslate?: () => void; retranslating?: boolean }) {
  return (
    <div className="min-w-0 bg-surface-2/45 p-4 sm:p-6" aria-busy={retranslating || undefined}>
      {stale ? (
        <div className="mb-4 rounded-lg bg-warn-soft px-3 py-2.5 text-[12.5px] leading-5 text-warn-ink" role="status">
          <p className="flex items-start gap-2">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            You've changed the German letter — this translation still shows the original draft.
          </p>
          {onRetranslate ? (
            <Button size="sm" variant="secondary" icon={RefreshCw} onClick={onRetranslate} loading={retranslating} className="ml-5.5 mt-2">
              {retranslating ? "Translating…" : "Re-translate"}
            </Button>
          ) : null}
        </div>
      ) : null}
      {translation ? (
        <div className="whitespace-pre-line text-[15px] leading-7 text-ink/85">{translation}</div>
      ) : (
        <p className="text-base text-muted">No translation for this letter.</p>
      )}
    </div>
  );
}

/**
 * The letter side by side: "Letter (German)" (editable) and "What it says (English)" (for your
 * understanding only). On phones a toggle switches between the two.
 */
export function LetterEditor(props: LetterEditorProps) {
  const wide = useIsTabletUp();
  const [pane, setPane] = useState<"de" | "en">("de");
  const german = props.language === "de";
  const deLabel = german ? "Letter (German)" : "Letter";
  const showSplit = Boolean(props.translation) || german;

  if (!showSplit) {
    return (
      <div className="card overflow-hidden">
        <GermanPane {...props} />
      </div>
    );
  }

  const header = (
    <div className="grid border-b border-line md:grid-cols-2 md:divide-x md:divide-line">
      <div className="flex items-start gap-2.5 px-4 py-3 sm:px-6">
        <PenLine className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
        <div className="min-w-0">
          <h2 className="text-[13.5px] font-semibold leading-5 text-ink">{deLabel}</h2>
          <p className="text-[12px] leading-4 text-muted">{props.readOnly ? "Sent — read only" : "This is what you send. You can edit it."}</p>
        </div>
      </div>
      <div className="hidden items-start gap-2.5 bg-surface-2/45 px-4 py-3 sm:px-6 md:flex">
        <Languages className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
        <div className="min-w-0">
          <h2 className="text-[13.5px] font-semibold leading-5 text-ink">What it says (English)</h2>
          <p className="text-[12px] leading-4 text-muted">For your understanding only</p>
        </div>
      </div>
    </div>
  );

  if (wide) {
    return (
      <div className="card overflow-hidden">
        {header}
        <div className="grid md:grid-cols-2 md:divide-x md:divide-line">
          <GermanPane {...props} />
          <EnglishPane translation={props.translation} stale={props.translationStale} onRetranslate={props.onRetranslate} retranslating={props.retranslating} />
        </div>
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-col gap-2 border-b border-line px-4 py-3">
        <SegmentedControl
          label="Show the letter or its translation"
          value={pane}
          onChange={setPane}
          fill
          options={[
            { value: "de", label: deLabel, icon: PenLine },
            { value: "en", label: "In English", icon: Languages },
          ]}
        />
        <p className="text-[12px] text-muted">{pane === "de" ? (props.readOnly ? "Sent — read only." : "You can edit this. Send this version.") : "For your understanding only — send the German letter."}</p>
      </div>
      {pane === "de" ? <GermanPane {...props} /> : <EnglishPane translation={props.translation} stale={props.translationStale} onRetranslate={props.onRetranslate} retranslating={props.retranslating} />}
    </div>
  );
}
