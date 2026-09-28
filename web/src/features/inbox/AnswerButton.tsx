/**
 * An answer to letters that wait ("Keep private", "Read these N", "Undo “Keep private”"). While its
 * request runs it shows a spinner and keeps focus: it is `aria-disabled`, not `disabled` (which would
 * drop focus to the page), so after a failed answer a keyboard or screen-reader user is still on the
 * button and can try again. `blocked` (the other answer is running) disables it outright — focus is
 * never on it then.
 */
import type { MouseEvent } from "react";
import { Button, type ButtonProps } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";

export interface AnswerButtonProps extends Omit<ButtonProps, "loading" | "disabled"> {
  /** Its request is running. */
  busy: boolean;
  /** Another answer's request is running. */
  blocked?: boolean;
}

export function AnswerButton({ busy, blocked = false, icon, onClick, children, ...rest }: AnswerButtonProps) {
  return (
    <Button
      {...rest}
      icon={busy ? undefined : icon}
      disabled={blocked && !busy}
      aria-disabled={busy || undefined}
      aria-busy={busy || undefined}
      onClick={(event: MouseEvent<HTMLButtonElement>) => {
        if (!busy) onClick?.(event);
      }}
    >
      {busy ? <Spinner className="size-4" /> : null}
      {typeof children === "string" ? <span className="min-w-0 truncate">{children}</span> : children}
    </Button>
  );
}
