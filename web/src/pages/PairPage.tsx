/**
 * `/pair` — a phone pairs with Ordnung on the computer (outside the app shell, which needs a paired phone).
 *
 * The QR code in Settings → Phone opens `https://<address>:<port>/pair#<CODE>`: the code is in the fragment, which
 * never travels in a request, and the page takes it out of the address at once (so it isn't left in the history).
 * Without a link the code is typed. "Pair this phone" sends it with the phone's name (`POST /api/phone/pair`, the
 * one request the phone listener answers before pairing); the answer sets the phone's sign-in cookie and names two
 * words the computer shows too — the person compares them before opening Ordnung (a full page load, signed in).
 *
 * Health first: a phone that is paired already goes on to Today; the computer's own tab is told pairing is for
 * phones. `?removed=…` says why it is here again — `1` (the computer removed this phone), `token_reuse` (its sign-in
 * was used from two places), `code_reused` (another device used its pairing code) or `unused` (not used for 30 days)
 * — as the phone listener said it (its redirect, or the `removed` of its 401 that `leaveIfUnpaired` follows).
 *
 * The typed code keeps at most {@link CODE_LENGTH} characters: an extra one typed at the end is dropped, so the field
 * never shows a right code that the form then refuses.
 */
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, KeyRound, RotateCw, Smartphone } from "lucide-react";
import { ApiError } from "@/api/client";
import { api } from "@/api/endpoints";
import { qk, usePairPhone } from "@/api/hooks";
import type { PairResult } from "@/api/types";
import { Logo } from "@/components/shell/Logo";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Field, Input } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import { PHONE_CHECKS } from "@/app/screens";
import { setClientKind } from "@/features/phone/client";
import { PHONE_UNREACHABLE } from "@/features/phone/copy";
import { guessDeviceName, pageLoad, servedToPhone } from "@/features/phone/platform";
import { NB_HYPHEN } from "@/lib/glue";

/** Characters in a pairing code (Crockford's base 32: no I, L, O or U). */
export const CODE_LENGTH = 10;
/** The most characters of a phone's name (the API's limit). */
export const NAME_MAX = 40;

/** The heading of the form. */
export const PAIR_TITLE = "Pair this phone with Ordnung";
/** What pairing is, under the heading. */
export const PAIR_INTRO = "Ordnung runs on your computer. Pairing lets this phone open it over your home Wi‑Fi; your letters stay on the computer.";
/** `?removed=1`: the computer removed this phone (or phone access started over). */
export const REMOVED_NOTE = "This phone was removed on your computer. Pair it again to keep using Ordnung here.";
/** `?removed=token_reuse`: the computer signed it out because its sign-in turned up in two places. */
export const TOKEN_REUSE_NOTE =
  "This phone was signed out because its sign-in was used from two places. If that wasn't you, someone may have copied it: pair again, and check the phones listed on your computer.";
/** `?removed=code_reused`: another device used the code this phone paired with, so neither stays paired. */
export const CODE_REUSED_NOTE =
  "This phone was signed out because another device used the same pairing code. Someone may have seen the code: make a new one on your computer, pair again, and check the phones listed there.";
/** `?removed=unused`: the computer forgot a phone unused for 30 days. */
export const UNUSED_NOTE = "This phone wasn't used with Ordnung for 30 days, so your computer forgot it. Pair it again to keep using Ordnung here.";
/** The computer's own tab on `/pair`. */
export const COMPUTER_NOTE = "Pairing is for phones. On this computer, open Settings → Phone and scan the code there with your phone's camera.";

/**
 * A code as the API compares it, without what only makes it readable: upper case, no spaces or dashes (the API also
 * reads O as 0 and I or L as 1).
 */
export function compactCode(raw: string): string {
  return raw.toUpperCase().replace(/[^0-9A-Z]/g, "");
}

/** "K7QM2XD9PA" → "K7QM2‑XD9PA" (a non-breaking hyphen: the code never splits at the end of a line). */
export function formatCode(raw: string): string {
  const code = compactCode(raw).slice(0, CODE_LENGTH);
  return code.length > 5 ? `${code.slice(0, 5)}${NB_HYPHEN}${code.slice(5)}` : code;
}

/** The code a QR link carries in its fragment (`#K7QM2XD9PA`), or null for any other fragment. */
export function codeFromHash(hash: string): string | null {
  let raw = hash.replace(/^#/, "");
  try {
    raw = decodeURIComponent(raw);
  } catch {
    return null;
  }
  const code = compactCode(raw);
  return code.length === CODE_LENGTH && /^[0-9A-Za-z\s\-‑]+$/.test(raw) ? code : null;
}

/** Why this phone is here again (`?removed=…`), if it says: a copied sign-in or a code two devices used in the danger tone. */
export function removedNote(params: URLSearchParams): { tone: "warn" | "danger"; text: string } | null {
  const removed = params.get("removed");
  if (!removed) return null;
  if (removed === "token_reuse") return { tone: "danger", text: TOKEN_REUSE_NOTE };
  if (removed === "code_reused") return { tone: "danger", text: CODE_REUSED_NOTE };
  if (removed === "unused") return { tone: "warn", text: UNUSED_NOTE };
  return { tone: "warn", text: REMOVED_NOTE };
}

/** The phone's answer to "who am I": paired (Health), not paired (the form), or an error to show. */
function useWhoAmI() {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["pair", "health"],
    queryFn: async ({ signal }) => {
      try {
        const health = await api.health(signal);
        setClientKind(health.client);
        // the app takes it from here (a paired phone goes on to Today)
        qc.setQueryData(qk.health, health);
        return health;
      } catch (err) {
        // only the phone listener says this: the form is for this phone
        if (err instanceof ApiError && err.code === "phone_not_paired") setClientKind("phone");
        throw err;
      }
    },
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });
}

export default function PairPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const params = new URLSearchParams(location.search);
  const who = useWhoAmI();
  // the phone listener refuses a phone it doesn't know with `phone_not_paired`: the form is for this phone (a 401
  // on the computer's own listener is its signed-out tab, which pairing can't help)
  const refusal = who.error instanceof ApiError ? who.error : null;
  const notPaired = Boolean(refusal && (refusal.code === "phone_not_paired" || ((refusal.status === 401 || refusal.status === 403) && servedToPhone())));

  // the code from the QR link: kept here, and out of the address bar at once (a later link replaces it)
  const incoming = codeFromHash(location.hash);
  const [linkCode, setLinkCode] = useState<string | null>(incoming);
  if (incoming && incoming !== linkCode) setLinkCode(incoming);
  useEffect(() => {
    if (!location.hash) return;
    navigate({ pathname: "/pair", search: location.search, hash: "" }, { replace: true });
  }, [location.hash, location.search, navigate]);

  // a paired phone has nothing to pair: on to Today
  const pairedAlready = who.data?.client === "phone";
  useEffect(() => {
    if (pairedAlready) navigate("/", { replace: true });
  }, [pairedAlready, navigate]);

  const [paired, setPaired] = useState<PairResult | null>(null);
  useEffect(() => {
    document.title = paired ? "Paired · Ordnung" : "Pair this phone · Ordnung";
  }, [paired]);

  let body: ReactNode;
  if (paired) body = <Paired result={paired} />;
  else if (who.isPending || pairedAlready) body = <Checking />;
  else if (who.data) body = <ComputerHere />;
  else if (notPaired) body = <PairForm linkCode={linkCode} onForgetLinkCode={() => setLinkCode(null)} note={removedNote(params)} onPaired={setPaired} />;
  else body = <NoAnswer error={who.error} retrying={who.isFetching} onRetry={() => void who.refetch()} />;

  return (
    <div className="relative flex min-h-dvh flex-col overflow-x-hidden bg-canvas">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[320px] bg-[radial-gradient(60%_100%_at_50%_0%,var(--color-accent-soft),transparent)] opacity-80 dark:opacity-50"
      />
      <header className="relative mx-auto flex w-full max-w-lg items-center px-4 pb-4 pt-6 sm:px-6">
        <Logo />
      </header>
      <main className="relative mx-auto flex w-full max-w-lg flex-1 flex-col px-4 pb-[max(2rem,env(safe-area-inset-bottom))] sm:px-6">
        <div className="card p-5 sm:my-auto sm:p-8">{body}</div>
      </main>
    </div>
  );
}

/** The page's h1, focused when the card changes (form → paired), so a screen reader hears where it is. */
function Title({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (document.activeElement === document.body || !document.activeElement) ref.current?.focus({ preventScroll: true });
  }, []);
  return (
    <h1 ref={ref} tabIndex={-1} className="display text-balance text-[26px] font-semibold leading-tight text-ink outline-none">
      {children}
    </h1>
  );
}

function Checking() {
  return (
    <div aria-busy="true" className="flex flex-col items-center py-6 text-center">
      <Spinner className="size-5 text-muted" />
      <p role="status" className="mt-3 text-base text-muted">
        Checking this phone…
      </p>
    </div>
  );
}

/** The computer's own tab opened `/pair`: pairing happens on the phone. */
function ComputerHere() {
  return (
    <>
      <Title>Pairing is for phones</Title>
      <p className="mt-2 text-pretty text-base leading-relaxed text-muted">{COMPUTER_NOTE}</p>
      <Link to="/settings?section=phone" className={buttonVariants({ variant: "primary", className: "mt-6" })}>
        <Smartphone aria-hidden />
        Open Settings → Phone
      </Link>
    </>
  );
}

/** The computer didn't answer (or answered with an error): what to check, and "Try again". */
function NoAnswer({ error, retrying, onRetry }: { error: unknown; retrying: boolean; onRetry: () => void }) {
  const refused = error instanceof ApiError && error.status !== 0 ? error : null;
  const unreachable = !refused;
  return (
    <>
      <Title>{unreachable ? "Can't reach your computer" : "Pairing can't start"}</Title>
      {unreachable ? (
        <>
          <p className="mt-2 text-pretty text-base leading-relaxed text-muted">This phone pairs with Ordnung on your computer over your home Wi‑Fi, and the computer didn't answer.</p>
          <ul className="mt-4 space-y-2 text-[15px] leading-6 text-ink/85">
            {PHONE_CHECKS.map((line) => (
              <li key={line} className="flex gap-2.5">
                <Check className="mt-1 size-4 shrink-0 text-muted" aria-hidden />
                {line}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p role="alert" className="mt-2 text-pretty text-base leading-relaxed text-danger-ink">
          {refused?.message}
        </p>
      )}
      <Button variant="primary" icon={RotateCw} className="mt-6" loading={retrying} onClick={onRetry}>
        Try again
      </Button>
    </>
  );
}

/** What a refusal of `POST /api/phone/pair` says, in the API's own words (a network error in the phone's). */
function refusal(err: unknown): string {
  if (err instanceof ApiError) return err.status === 0 ? PHONE_UNREACHABLE : err.message;
  return err instanceof Error ? err.message : "Pairing didn't work. Please try again.";
}

function PairForm({
  linkCode,
  onForgetLinkCode,
  note,
  onPaired,
}: {
  linkCode: string | null;
  onForgetLinkCode: () => void;
  note: { tone: "warn" | "danger"; text: string } | null;
  onPaired: (result: PairResult) => void;
}) {
  const ids = useId();
  const pair = usePairPhone();
  const [typed, setTyped] = useState("");
  const [name, setName] = useState(() => guessDeviceName());
  const [tried, setTried] = useState(false);
  const codeRef = useRef<HTMLInputElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const code = linkCode ?? compactCode(typed);
  const codeProblem = code.length === CODE_LENGTH ? null : code.length ? `The code has ${CODE_LENGTH} characters — check the ones on your computer.` : "Type the code shown on your computer.";
  const nameProblem = name.trim() ? null : "Give this phone a name — your computer lists it by this name.";
  const failed = pair.error ? refusal(pair.error) : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (pair.isPending) return;
    setTried(true);
    if (codeProblem && !linkCode) {
      codeRef.current?.focus();
      return;
    }
    if (nameProblem) {
      nameRef.current?.focus();
      return;
    }
    pair.mutate({ code, name: name.trim().slice(0, NAME_MAX) }, { onSuccess: onPaired });
  };

  return (
    <form onSubmit={submit} noValidate aria-labelledby={`${ids}-title`}>
      <div id={`${ids}-title`}>
        <Title>{PAIR_TITLE}</Title>
      </div>
      <p className="mt-2 text-pretty text-base leading-relaxed text-muted">{PAIR_INTRO}</p>
      {note ? (
        <Callout tone={note.tone} className="mt-4">
          {note.text}
        </Callout>
      ) : null}

      <div className="mt-6 flex flex-col gap-5">
        {linkCode ? (
          <div>
            <p className="text-sm font-medium text-ink" id={`${ids}-code`}>
              Code from your computer
            </p>
            <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span
                aria-labelledby={`${ids}-code`}
                className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-1.5 font-ident text-[19px] font-semibold tracking-[0.06em] text-ink"
              >
                <KeyRound className="size-4 text-muted" aria-hidden />
                {formatCode(linkCode)}
              </span>
              <Button
                variant="link"
                size="sm"
                onClick={() => {
                  onForgetLinkCode();
                  pair.reset();
                  requestAnimationFrame(() => codeRef.current?.focus());
                }}
              >
                Type a code instead
              </Button>
            </p>
            <p className="mt-1.5 text-sm leading-5 text-muted">From the QR code you scanned.</p>
          </div>
        ) : (
          <Field
            label="Code from your computer"
            hint={`The ${CODE_LENGTH} characters under the QR code in Settings → Phone on your computer.`}
            error={tried ? codeProblem : null}
          >
            <Input
              ref={codeRef}
              value={formatCode(typed)}
              // at most the code's characters: an 11th one typed at the end is dropped, never shown and refused
              onChange={(e) => setTyped(compactCode(e.target.value).slice(0, CODE_LENGTH))}
              autoCapitalize="characters"
              autoComplete="one-time-code"
              autoCorrect="off"
              spellCheck={false}
              enterKeyHint="next"
              placeholder={`XXXXX${NB_HYPHEN}XXXXX`}
              className="h-11 font-ident text-[17px] tracking-[0.06em]"
            />
          </Field>
        )}
        <Field label="This phone's name" hint="Your computer lists this phone by this name." error={tried ? nameProblem : null}>
          <Input
            ref={nameRef}
            value={name}
            maxLength={NAME_MAX}
            onChange={(e) => setName(e.target.value)}
            autoComplete="off"
            enterKeyHint="go"
            className="h-11 text-[16px]"
          />
        </Field>
      </div>

      {failed ? (
        <p role="alert" className="mt-5 rounded-xl border border-danger/25 bg-danger-soft px-4 py-3 text-[15px] leading-relaxed text-danger-ink">
          {failed}
        </p>
      ) : null}

      <Button type="submit" variant="primary" size="lg" iconRight={ArrowRight} loading={pair.isPending} className="mt-6 w-full">
        Pair this phone
      </Button>
    </form>
  );
}

/**
 * Paired: the two words this phone got, which the computer's pairing dialog shows too. Matching words say this
 * phone — not someone who saw the code — paired; then Ordnung opens, signed in (a full page load).
 */
function Paired({ result }: { result: PairResult }) {
  return (
    <>
      <Title>Paired</Title>
      <p className="mt-2 text-pretty text-base leading-relaxed text-muted">
        This phone is paired as <span className="font-medium text-ink">{result.name}</span>. Check that your computer shows the same two words:
      </p>
      <p data-check-words="" className="display mt-5 text-center text-[30px] font-semibold leading-tight text-ink">
        {result.check_words}
      </p>
      <p className="mt-5 text-pretty text-sm leading-relaxed text-muted">
        Other words on your computer mean another device used the code: choose Remove there, and pair this phone again.
      </p>
      <Button variant="primary" size="lg" iconRight={ArrowRight} className="mt-6 w-full" onClick={() => pageLoad.replace("/")}>
        Open Ordnung
      </Button>
    </>
  );
}
