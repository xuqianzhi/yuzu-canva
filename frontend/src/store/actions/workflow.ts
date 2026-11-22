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
  const { flushTyping, poll, replaceGraph } = core;
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
      replaceGraph(graph);
      // Image and video steps start generating at once: follow those jobs.
      const jobs = Object.fromEntries((graph.active_jobs ?? []).map((j) => [j.node_id, j]));
      set((s) => ({ jobs: { ...s.jobs, ...jobs } }));
      for (const job of Object.values(jobs)) poll(job.node_id, job.id);
      return null;
    } catch (error) {
      return message(error);
    }
  },
  };
}
