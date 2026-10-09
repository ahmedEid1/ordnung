/**
 * `/dev/ui`: the design-system gallery in development, mock mode and the demos (`ordnung demo` and the online
 * one, where the end-to-end tests and the UI audit open it). The app itself has no such page: there it is
 * "Not found".
 */
import { useHealth } from "@/api/hooks";
import { shouldUseMocks } from "@/mocks/mode";
import { NotFound } from "./screens";
import UiGallery from "./UiGallery";

export default function DevUiPage() {
  const demo = Boolean(useHealth().data?.demo);
  return import.meta.env.DEV || demo || shouldUseMocks() ? <UiGallery /> : <NotFound />;
}
