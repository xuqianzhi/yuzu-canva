// The workflow panel: which step is open, and running a step.
import { api, unwrap } from "../../api/client";
import { t } from "../../i18n";
import type { CanvasState, GetState, SetState } from "../types";
import { message } from "../core";
import type { Core } from "../core";

export function workflowActions(
  set: SetState,
  get: GetState,
  core: Core,
): Pick<CanvasState, "openStep" | "runStep"> {
  const { flushTyping, watchRuns } = core;
  return {
  openStep(key, nodeId = null) {
    set({ activeStep: key, activeNodeId: nodeId });
  },

  async runStep(key, prompt, count) {
    const project = get().project;
    if (!project) return t("node_gone");
    await flushTyping();
    try {
      const graph = unwrap(
        await api.POST("/api/projects/{project_id}/workflow/steps/{step_key}/run", {
          params: { path: { project_id: project.id, step_key: key } },
          body: { prompt, count },
        }),
      );
      if (get().project?.id !== project.id) return null;
      // The run finishes in the background: follow it until it's done.
      set({ runs: Object.fromEntries((graph.runs ?? []).map((r) => [r.step, r])) });
      await watchRuns(project.id);
      const run = get().runs[key];
      return run?.status === "failed" ? (run.error ?? t("run_failed")) : null;
    } catch (error) {
      return message(error);
    }
  },
  };
}
