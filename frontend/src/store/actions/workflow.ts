// The workflow: which step is open, and running a step.
import { api, unwrap } from "../../api/client";
import { t } from "../../i18n";
import type { CanvasState, GetState, SetState } from "../types";
import { message, runsOf } from "../core";
import type { Core } from "../core";

export function workflowActions(
  set: SetState,
  get: GetState,
  core: Core,
): Pick<CanvasState, "openStep" | "jumpToNode" | "runStep" | "completeStep" | "generateStep"> {
  const { flushTyping, watchRuns, replaceGraph, takeGraph } = core;
  return {
  openStep(key, nodeId = null) {
    set({ activeStep: key, activeNodeId: nodeId });
  },

  jumpToNode(key, nodeId) {
    set((s) => ({ activeStep: key, activeNodeId: nodeId, jump: s.jump + 1 }));
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
      set({ runs: runsOf(graph) });
      await watchRuns(project.id);
      const run = get().runs[key];
      return run?.status === "failed" ? (run.error ?? t("run_failed")) : null;
    } catch (error) {
      return message(error);
    }
  },

  async completeStep(key, entries) {
    const project = get().project;
    if (!project) return t("node_gone");
    await flushTyping();
    try {
      const graph = unwrap(
        await api.POST("/api/projects/{project_id}/workflow/steps/{step_key}/complete", {
          params: { path: { project_id: project.id, step_key: key } },
          body: { entries },
        }),
      );
      if (get().project?.id === project.id) replaceGraph(graph);
      return null;
    } catch (error) {
      return message(error);
    }
  },

  async generateStep(key) {
    const project = get().project;
    if (!project) return t("node_gone");
    // Prompts and lengths being typed are saved first: they're what's generated.
    await flushTyping();
    try {
      const graph = unwrap(
        await api.POST("/api/projects/{project_id}/workflow/steps/{step_key}/generate", {
          params: { path: { project_id: project.id, step_key: key } },
        }),
      );
      if (get().project?.id !== project.id) return null;
      takeGraph(graph);
      return null;
    } catch (error) {
      return message(error);
    }
  },
  };
}
