import type { ReactNode, Ref } from "react";
import { Check, Copy, Eye, EyeOff, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { useClipboard } from "@/features/today/clipboard";
import type { PassphraseProblem } from "./backup";

export interface PassphraseFieldsProps {
  /** Ids: `<idPrefix>-passphrase` and `<idPrefix>-repeat` (where a problem's focus goes). */
  idPrefix: string;
  passphrase: string;
  onPassphraseChange: (value: string) => void;
  /** The second field ("Repeat the passphrase"); left out when the passphrase is typed once (joining). */
  repeat?: string;
  onRepeatChange?: (value: string) => void;
  problem: PassphraseProblem | null;
  visible: boolean;
  onVisibleChange: (visible: boolean) => void;
  /** Offer "Suggest a strong one" (a new passphrase only). */
  onSuggest?: () => void;
  /** The passphrase shown is the suggested one: "Copy passphrase" is offered, and `suggestedHint` replaces `hint`. */
  suggested?: boolean;
  hint?: ReactNode;
  suggestedHint?: ReactNode;
  /** Said under the hint while typing (the strength of a new sync passphrase). */
  status?: ReactNode;
  busy?: boolean;
  label?: string;
  firstRef?: Ref<HTMLInputElement>;
}

/**
 * A passphrase typed twice (or once), with Show, "Suggest a strong one" and — once suggested, since a password
 * manager won't offer to save text it shows — "Copy passphrase". Shared by the encrypted backup's dialog and hand-off
 * sync's setup; each says itself where the passphrase lives (`hint`).
 */
export function PassphraseFields({
  idPrefix,
  passphrase,
  onPassphraseChange,
  repeat,
  onRepeatChange,
  problem,
  visible,
  onVisibleChange,
  onSuggest,
  suggested = false,
  hint,
  suggestedHint,
  status,
  busy = false,
  label = "Passphrase",
  firstRef,
}: PassphraseFieldsProps) {
  const { copy, copied } = useClipboard();
  const type = visible ? "text" : "password";
  const twice = repeat !== undefined;
  return (
    <>
      <div>
        <Field id={`${idPrefix}-passphrase`} label={label} hint={suggested ? (suggestedHint ?? hint) : hint} error={problem?.field === "passphrase" ? problem.message : undefined}>
          <Input
            ref={firstRef}
            type={type}
            value={passphrase}
            onChange={(e) => onPassphraseChange(e.target.value)}
            autoComplete={twice ? "new-password" : "current-password"}
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            readOnly={busy}
            className={visible ? "font-mono" : undefined}
          />
        </Field>
        {status && problem?.field !== "passphrase" ? <div className="mt-1.5">{status}</div> : null}
      </div>
      {twice ? (
        <Field id={`${idPrefix}-repeat`} label="Repeat the passphrase" error={problem?.field === "repeat" ? problem.message : undefined}>
          <Input
            type={type}
            value={repeat}
            onChange={(e) => onRepeatChange?.(e.target.value)}
            autoComplete="new-password"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            readOnly={busy}
            className={visible ? "font-mono" : undefined}
          />
        </Field>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="ghost" icon={visible ? EyeOff : Eye} onClick={() => onVisibleChange(!visible)} aria-pressed={visible} disabled={busy}>
          {visible ? "Hide passphrase" : "Show passphrase"}
        </Button>
        {onSuggest ? (
          <Button size="sm" variant="ghost" icon={Sparkles} onClick={onSuggest} disabled={busy}>
            Suggest a strong one
          </Button>
        ) : null}
        {suggested ? (
          // shown as text, a password manager won't offer to save it: copying it is the way there
          <Button size="sm" variant="ghost" icon={copied === passphrase ? Check : Copy} onClick={() => void copy(passphrase)} disabled={busy}>
            {copied === passphrase ? "Copied" : "Copy passphrase"}
          </Button>
        ) : null}
        <span className="sr-only" aria-live="polite">
          {suggested && copied === passphrase ? "Passphrase copied to the clipboard" : ""}
        </span>
      </div>
    </>
  );
}
