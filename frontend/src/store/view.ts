// How this viewer likes a project shown (not saved with the project, and
// not shared): remembered in this browser.
import { create } from "zustand";

const LINKS_KEY = "yuzu.showLinks";
const SELECT_TOOL_KEY = "yuzu.selectTool";
const CANVAS_VIEW_KEY = "yuzu.canvasView";
const STRIP_COLLAPSED_KEY = "yuzu.stripCollapsed";

/** How a project is shown: one page per workflow step (basic), or every node
    on the canvas. Both show the same project; only the layout differs. */
export type ProjectView = "basic" | "canvas";

/** What dragging on empty canvas does: move the view, or draw a selection. */
export type CanvasTool = "hand" | "select";

function remembered(key: string, fallback: boolean): boolean {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : value === "1";
  } catch {
    return fallback;
  }
}

function remember(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    // Private window or blocked storage: it just isn't remembered.
  }
}

interface ViewState {
  /** Draw the links between nodes (hiding them makes a busy canvas lighter). */
  showLinks: boolean;
  setShowLinks(show: boolean): void;
  tool: CanvasTool;
  setTool(tool: CanvasTool): void;
  /** Basic unless this viewer picked the canvas. */
  projectView: ProjectView;
  setProjectView(view: ProjectView): void;
  /** The basic view's workflow bar, without the steps' result lists. */
  stripCollapsed: boolean;
  setStripCollapsed(collapsed: boolean): void;
}

export const useView = create<ViewState>()((set) => ({
  showLinks: remembered(LINKS_KEY, true),
  setShowLinks(show) {
    remember(LINKS_KEY, show);
    set({ showLinks: show });
  },
  tool: remembered(SELECT_TOOL_KEY, false) ? "select" : "hand",
  setTool(tool) {
    remember(SELECT_TOOL_KEY, tool === "select");
    set({ tool });
  },
  projectView: remembered(CANVAS_VIEW_KEY, false) ? "canvas" : "basic",
  setProjectView(projectView) {
    remember(CANVAS_VIEW_KEY, projectView === "canvas");
    set({ projectView });
  },
  stripCollapsed: remembered(STRIP_COLLAPSED_KEY, false),
  setStripCollapsed(stripCollapsed) {
    remember(STRIP_COLLAPSED_KEY, stripCollapsed);
    set({ stripCollapsed });
  },
}));
