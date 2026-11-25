// How this viewer likes the canvas shown (not saved with the project, and
// not shared): remembered in this browser.
import { create } from "zustand";

const LINKS_KEY = "yuzu.showLinks";

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
}

export const useView = create<ViewState>()((set) => ({
  showLinks: remembered(LINKS_KEY, true),
  setShowLinks(show) {
    remember(LINKS_KEY, show);
    set({ showLinks: show });
  },
}));
