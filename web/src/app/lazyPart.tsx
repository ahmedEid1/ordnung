/**
 * A part of the shell that loads its code only when it is first shown (the demo's tour, the People & organisations
 * drawer), so every page's first load doesn't carry it. A part whose code can't load (Ordnung restarted under an
 * open tab, or upgraded) leaves the shell as it is: it shows nothing, the app reloads for a new build as it does for
 * a page (`reloadIfServing`), and the next time the part is asked for (`retry` changes) it tries again. When the app
 * did not reload, `failed` says so (the drawer's toast), so a click is never left without an answer.
 */
import { Component, lazy, Suspense, type ComponentType, type ReactNode } from "react";
import { reloadIfServing } from "./staleChunks";

class Quiet extends Component<{ retry: unknown; children: ReactNode }, { failed: boolean; retry: unknown }> {
  state = { failed: false, retry: this.props.retry };

  static getDerivedStateFromError(): Partial<{ failed: boolean }> {
    return { failed: true };
  }

  static getDerivedStateFromProps(props: { retry: unknown }, state: { failed: boolean; retry: unknown }) {
    // asked for again: try again
    return props.retry === state.retry ? null : { failed: false, retry: props.retry };
  }

  render(): ReactNode {
    return this.state.failed ? null : this.props.children;
  }
}

/**
 * `load`'s component, loaded on its first render. A failed load is not kept: the next render after `retry` changes
 * loads it again. `failed` runs when a load failed and the app was not reloaded for it.
 */
export function lazyPart<P extends object>(
  load: () => Promise<ComponentType<P>>,
  { failed }: { failed?: () => void } = {},
): ComponentType<P & { retry?: unknown }> {
  /** The `retry` the part was asked with when its code failed to load: a load tried again only for another one. */
  const state: { asking: unknown; failedFor: { retry: unknown } | null } = { asking: undefined, failedFor: null };
  const make = () =>
    lazy(() =>
      load().then(
        (component) => ({ default: component }),
        (err: unknown) => {
          state.failedFor = { retry: state.asking };
          let reloading = false;
          void reloadIfServing(() => {
            reloading = true;
            window.location.reload();
          }).then(() => {
            if (!reloading) failed?.();
          });
          throw err;
        },
      ),
    );
  const loader = { current: make() };
  function Part({ retry, ...props }: P & { retry?: unknown }) {
    state.asking = retry;
    if (state.failedFor && state.failedFor.retry !== retry) {
      state.failedFor = null;
      loader.current = make();
    }
    const Loaded = loader.current;
    return (
      <Quiet retry={retry}>
        <Suspense fallback={null}>
          <Loaded {...(props as P)} />
        </Suspense>
      </Quiet>
    );
  }
  return Part;
}
