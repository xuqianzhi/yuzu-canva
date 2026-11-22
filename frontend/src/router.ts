// Hash routes: "#/" is the project list, "#/assets" and "#/instruction" the
// defaults for new projects, "#/project/<id>" a project's canvas.
// Route changes run one at a time, so leaving a project always finishes
// saving before the next view loads.
import { useSyncExternalStore } from "react";
import { useCanvas } from "./store/canvas";

/** The landing page's sections, one per item in its left menu. */
export type HomeTab = "projects" | "assets" | "instruction" | "workflows" | "settings";

export type Route = { page: "home"; tab?: HomeTab } | { page: "project"; projectId: string };

export function parseRoute(hash: string): Route {
  const match = hash.match(/^#\/project\/([^/?#]+)$/);
  if (match) return { page: "project", projectId: decodeURIComponent(match[1]!) };
  if (hash === "#/assets") return { page: "home", tab: "assets" };
  if (hash === "#/instruction") return { page: "home", tab: "instruction" };
  if (hash === "#/workflows") return { page: "home", tab: "workflows" };
  if (hash === "#/settings") return { page: "home", tab: "settings" };
  return { page: "home", tab: "projects" };
}

export const homeHref = "#/";
export const homeTabHref = (tab: HomeTab) => (tab === "projects" ? homeHref : `#/${tab}`);
export const projectHref = (id: string) => `#/project/${encodeURIComponent(id)}`;

function subscribe(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/** The current route; re-renders on hash changes. */
export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => location.hash);
  return parseRoute(hash);
}

let chain: Promise<void> = Promise.resolve();
let openedId: string | null = null;

/** Open or close the project for `route`, in order, once per change. */
export function syncProject(route: Route): Promise<void> {
  const wanted = route.page === "project" ? route.projectId : null;
  chain = chain.then(async () => {
    if (wanted === openedId) return;
    const store = useCanvas.getState();
    if (openedId) await store.closeProject();
    openedId = wanted;
    if (wanted) await store.openProject(wanted);
  });
  return chain;
}
