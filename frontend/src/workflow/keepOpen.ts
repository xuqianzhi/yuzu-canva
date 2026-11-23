// While anything is generating, the page must stay open: the server only
// runs while someone is using the app, and shuts down a while after the last
// request. (Generations pick up again when the app is next opened, but a
// video can then take much longer.) So: a notice on the canvas, and the
// browser's "Leave site?" prompt when closing the tab.
import { useEffect } from "react";
import { TERMINAL_JOB_STATUSES } from "../api/types";
import { useCanvas } from "../store/canvas";

/** Whether anything in the open project is generating. */
export function useGenerating(): boolean {
  return useCanvas(
    (s) =>
      Object.values(s.jobs).some((job) => !TERMINAL_JOB_STATUSES.includes(job.status)) ||
      Object.values(s.runs).some((run) => run.status === "running"),
  );
}

/** Ask before closing the tab while something is generating. */
export function useKeepOpenWarning(): void {
  const generating = useGenerating();
  useEffect(() => {
    if (!generating) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Older browsers need a value; the text itself is never shown.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [generating]);
}
