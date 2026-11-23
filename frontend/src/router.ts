// Hash routes:
// - "#/" your collections (and invitations), "#/settings" settings;
// - "#/c/<id>" a collection's projects, "#/c/<id>/<section>" its assets,
//   instruction, workflows or sharing;
// - "#/project/<id>" a project's canvas.
// Route changes run one at a time, so leaving a project always finishes
// saving before the next view loads.
import { useSyncExternalStore } from "react";
import { useCanvas } from "./store/canvas";

/** A collection's sections, one per item in its left menu. */
export type CollectionTab = "projects" | "assets" | "instruction" | "workflows" | "share";

export type Route =
  | { page: "home" }
  | { page: "settings" }
  | { page: "collection"; collectionId: string; tab: CollectionTab }
  | { page: "project"; projectId: string };

const TABS: CollectionTab[] = ["projects", "assets", "instruction", "workflows", "share"];

export function parseRoute(hash: string): Route {
  const project = hash.match(/^#\/project\/([^/?#]+)$/);
  if (project) return { page: "project", projectId: decodeURIComponent(project[1]!) };
  const collection = hash.match(/^#\/c\/([^/?#]+)(?:\/([a-z]+))?$/);
  if (collection) {
    const tab = TABS.find((t) => t === collection[2]) ?? "projects";
    return { page: "collection", collectionId: decodeURIComponent(collection[1]!), tab };
  }
  if (hash === "#/settings") return { page: "settings" };
  return { page: "home" };
}

export const homeHref = "#/";
export const settingsHref = "#/settings";
export const collectionHref = (id: string, tab: CollectionTab = "projects") =>
  `#/c/${encodeURIComponent(id)}${tab === "projects" ? "" : `/${tab}`}`;
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
