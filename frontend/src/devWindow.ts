// Local development only: the launcher's app window (opened with "?app=1")
// keeps telling the dev server where it is and how big it is, so
// `./yuzu-canva` reopens it in the same place (see vite.config.ts and
// bin/yuzu-canva). Other tabs on the dev server don't report.

const FLAG = "yuzu-app-window";
const ENDPOINT = "/__yuzu/window";

export function reportWindowPlacement(): void {
  if (!import.meta.env.DEV) return;
  try {
    // The flag outlives reloads that drop the query.
    if (new URLSearchParams(location.search).has("app")) sessionStorage.setItem(FLAG, "1");
    if (sessionStorage.getItem(FLAG) !== "1") return;
  } catch {
    return;
  }

  let last = "";
  const send = (leaving = false) => {
    const placement = {
      x: window.screenX,
      y: window.screenY,
      width: window.outerWidth,
      height: window.outerHeight,
    };
    if (placement.width < 200 || placement.height < 200) return; // minimised
    const body = JSON.stringify(placement);
    if (body === last) return;
    last = body;
    if (leaving) {
      navigator.sendBeacon(ENDPOINT, body);
      return;
    }
    fetch(ENDPOINT, { method: "POST", body, keepalive: true }).catch(() => {
      last = ""; // try again next time
    });
  };

  // Moving a window fires no event: check every second.
  window.setInterval(() => send(), 1000);
  window.addEventListener("resize", () => send());
  window.addEventListener("pagehide", () => send(true));
}
