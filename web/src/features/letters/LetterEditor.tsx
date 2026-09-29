import { useEffect, useId, useLayoutEffect, useRef, useState, type ComponentProps } from "react";
import { ChevronDown, Info, Languages, Paperclip, PenLine, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
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
  // re-fit when the width changes (layout, window, a pane shown again) or the web font arrives
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

/**
 * An editable field that reads like the letter: no box until you point at it or focus it. Its label
 * (`FIELD_ROW`) reaches 10 px past the text on both sides, so the box does too while the text lines
 * up with the headings and the labels above it (`FIELD_LABEL`).
 */
const fieldCls =
  "w-full rounded-lg border border-transparent bg-transparent px-2.5 py-1.5 text-ink transition-[border-color,background-color,box-shadow] " +
  "hover:border-line hover:bg-surface-2/40 focus-visible:border-accent/60 focus-visible:bg-surface focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-accent/15";
const FIELD_ROW = "-mx-2.5 block";
const FIELD_LABEL = "px-2.5";

/**
 * The split between "side by side" and "one pane with a toggle" is the editor card's own width
 * (a container query), not the window's: next to the sending panel the card can be narrow on a wide
 * screen. Below 760 px each pane would be under 380 px — too narrow to edit a German letter.
 */
const SPLIT_GRID = "@[47.5rem]/letter:grid-cols-2 @[47.5rem]/letter:divide-x @[47.5rem]/letter:divide-line";
/** only while the panes are side by side / only while one pane shows at a time */
const WHEN_SPLIT = "hidden @[47.5rem]/letter:grid";
const WHEN_TOGGLED = "@[47.5rem]/letter:hidden";
/** the pane the toggle doesn't show (both show side by side) */
const TOGGLED_AWAY = "@max-[47.5rem]/letter:hidden";

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

/** A sent letter's text: plain paragraphs — nothing that looks like it can still be edited. */
function ReadOnlyText({ text, className, label }: { text: string; className?: string; label: string }) {
  return (
    <div className={cn("whitespace-pre-line text-ink [overflow-wrap:anywhere]", className)} aria-label={label} role="group">
      {text}
    </div>
  );
}

function GermanPane({ value, onChange, language, enclosures, readOnly, className }: Omit<LetterEditorProps, "translation" | "translationStale" | "onRetranslate" | "retranslating"> & { className?: string }) {
  const [showBlocks, setShowBlocks] = useState(false);
  const blocksId = useId();
  const set = (k: keyof EditableFields) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value });
  const placeholders = findPlaceholders(`${value.subject}\n${value.body}`);
  const blockLabel = "text-[12px] font-medium text-muted";
  return (
    <div className={cn("@container/pane min-w-0 p-4 sm:p-6", className)} lang={language} data-pane="letter">
      <button
        type="button"
        onClick={() => setShowBlocks((s) => !s)}
        aria-expanded={showBlocks}
        aria-controls={blocksId}
        className="-mx-2 mb-3 inline-flex min-h-8 items-center gap-1.5 rounded-md px-2 text-[13px] font-medium text-muted transition-colors hover:bg-surface-2/70 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
      >
        <ChevronDown className={cn("size-3.5 transition-transform motion-reduce:transition-none", !showBlocks && "-rotate-90")} aria-hidden />
        <span lang="en">{readOnly ? "Sender, recipient & date" : "Edit sender, recipient & date"}</span>
      </button>
      {showBlocks ? (
        <div id={blocksId} className="mb-5 grid gap-4 rounded-xl bg-surface-2/50 px-4 py-3.5 @md/pane:grid-cols-2">
          {readOnly ? (
            <>
              <div>
                <p className={blockLabel} lang="en">From (you)</p>
                <ReadOnlyText text={value.sender_block} label="From (you)" className="mt-1 text-[13.5px] leading-6" />
              </div>
              <div>
                <p className={blockLabel} lang="en">To</p>
                <ReadOnlyText text={value.recipient_block} label="To" className="mt-1 text-[13.5px] leading-6" />
              </div>
              <div className="@md/pane:col-span-2">
                <p className={blockLabel} lang="en">Place &amp; date</p>
                <p className="mt-1 text-[13.5px] text-ink">{value.place_date}</p>
              </div>
            </>
          ) : (
            <>
              <label className={cn(FIELD_ROW, blockLabel)}>
                <span lang="en" className={FIELD_LABEL}>
                  From (you)
                </span>
                <AutoTextarea value={value.sender_block} onChange={set("sender_block")} minRows={3} className={cn(fieldCls, "mt-1 text-[13.5px] font-normal leading-6")} />
              </label>
              <label className={cn(FIELD_ROW, blockLabel)}>
                <span lang="en" className={FIELD_LABEL}>
                  To
                </span>
                <AutoTextarea value={value.recipient_block} onChange={set("recipient_block")} minRows={3} className={cn(fieldCls, "mt-1 text-[13.5px] font-normal leading-6")} />
              </label>
              <label className={cn(FIELD_ROW, "@md/pane:col-span-2", blockLabel)}>
                <span lang="en" className={FIELD_LABEL}>
                  Place &amp; date
                </span>
                <input value={value.place_date} onChange={set("place_date")} className={cn(fieldCls, "mt-1 block text-[13.5px] font-normal")} />
              </label>
            </>
          )}
        </div>
      ) : null}

      {readOnly ? (
        <>
          <p className="text-[15.5px] font-semibold leading-6 text-ink [overflow-wrap:anywhere]">{value.subject}</p>
          <ReadOnlyText text={value.body} label="Letter text" className="mt-4 text-[15px] leading-7" />
        </>
      ) : (
        <>
          <label className={FIELD_ROW}>
            <span className="sr-only" lang="en">
              Subject (Betreff)
            </span>
            <AutoTextarea value={value.subject} onChange={set("subject")} minRows={1} placeholder="Betreff" className={cn(fieldCls, "text-[15.5px] font-semibold leading-6")} />
          </label>
          <label className={cn(FIELD_ROW, "mt-3")}>
            <span className="sr-only" lang="en">
              Letter text (German)
            </span>
            <AutoTextarea value={value.body} onChange={set("body")} minRows={10} spellCheck className={cn(fieldCls, "text-[15px] leading-7")} />
          </label>
        </>
      )}
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
          <span>Fill in the gaps before sending: {placeholders.map((p) => `“${p}”`).join(", ")}</span>
        </p>
      ) : null}
    </div>
  );
}

function EnglishPane({
  translation,
  stale,
  onRetranslate,
  retranslating,
  className,
}: {
  translation: string;
  stale: boolean;
  onRetranslate?: () => void;
  retranslating?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0 bg-surface-2/45 p-4 sm:p-6", className)} aria-busy={retranslating || undefined} data-pane="english">
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
        <div className="whitespace-pre-line text-[15px] leading-7 text-ink/85 [overflow-wrap:anywhere]">{translation}</div>
      ) : (
        <p className="text-base text-muted">No translation for this letter.</p>
      )}
    </div>
  );
}

function PaneHeading({ icon: Icon, title, note, className }: { icon: typeof PenLine; title: string; note: string; className?: string }) {
  return (
    <div className={cn("flex items-start gap-2.5 px-4 py-3 sm:px-6", className)}>
      <Icon className={cn("mt-0.5 size-4 shrink-0", Icon === PenLine ? "text-accent" : "text-muted")} aria-hidden />
      <div className="min-w-0">
        <h2 className="text-[13.5px] font-semibold leading-5 text-ink">{title}</h2>
        <p className="text-[12px] leading-4 text-muted">{note}</p>
      </div>
    </div>
  );
}

/**
 * The letter: "Letter (German)" (editable) and "What it says (English)" (for your understanding
 * only) side by side when the card is wide enough, else one at a time with a toggle. A letter
 * without translation (written in English) is one pane with its own heading.
 */
export function LetterEditor(props: LetterEditorProps) {
  const [pane, setPane] = useState<"de" | "en">("de");
  const german = props.language === "de";
  const deLabel = german ? "Letter (German)" : "Letter";
  const deNote = props.readOnly ? "Sent — read only" : "This is what you send. You can edit it.";
  const showSplit = Boolean(props.translation) || german;

  if (!showSplit) {
    return (
      <div className="card overflow-hidden">
        <PaneHeading icon={PenLine} title={deLabel} note={deNote} className="border-b border-line" />
        {/* a readable line length, however wide the card */}
        <GermanPane {...props} className="max-w-[50rem]" />
      </div>
    );
  }

  const english = (
    <EnglishPane
      translation={props.translation}
      stale={props.translationStale}
      onRetranslate={props.onRetranslate}
      retranslating={props.retranslating}
      className={cn(pane !== "en" && TOGGLED_AWAY)}
    />
  );

  return (
    <div className="@container/letter card overflow-hidden" data-letter-editor>
      {/* one pane at a time: the toggle */}
      <div className={cn("flex flex-col gap-2 border-b border-line px-4 py-3 sm:px-6", WHEN_TOGGLED)}>
        <SegmentedControl
          label="Show the letter or its translation"
          value={pane}
          onChange={setPane}
          fill
          options={[
            { value: "de", label: deLabel, shortLabel: german ? "German" : "Letter", icon: PenLine },
            { value: "en", label: "In English", shortLabel: "English", icon: Languages },
          ]}
        />
        <p className="text-[12px] leading-4 text-muted">
          {pane === "de" ? (props.readOnly ? "Sent — read only." : "You can edit this. Send this version.") : "For your understanding only — send the German letter."}
        </p>
      </div>
      {/* side by side: a heading over each pane */}
      <div className={cn("border-b border-line", WHEN_SPLIT, SPLIT_GRID)}>
        <PaneHeading icon={PenLine} title={deLabel} note={deNote} />
        <PaneHeading icon={Languages} title="What it says (English)" note="For your understanding only" className="bg-surface-2/45" />
      </div>
      <div className={cn("grid", SPLIT_GRID)}>
        <GermanPane {...props} className={cn(pane !== "de" && TOGGLED_AWAY)} />
        {english}
      </div>
    </div>
  );
}
