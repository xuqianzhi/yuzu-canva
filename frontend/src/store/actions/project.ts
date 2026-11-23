// Opening and closing a project; its name, instruction and viewport.
import { api, unwrap } from "../../api/client";
import { currentStep, stepViews } from "../../workflow/status";
import { type Job } from "../../api/types";
import type { CanvasState, GetState, SetState } from "../types";
import { toFlowEdge, message, toFlowNode, session } from "../core";
import type { Core } from "../core";

export function projectActions(
  set: SetState,
  get: GetState,
  core: Core,
): Pick<
  CanvasState,
  | "openProject"
  | "closeProject"
  | "renameProject"
  | "setProjectInstruction"
  | "saveViewport"
> {
  const {
    flushTyping,
    poll,
    resetProjectState,
    flushViewport,
    flushName,
    flushInstruction,
    clearHistory,
    step,
    watchRuns,
  } = core;
  return {
  async openProject(projectId) {
    resetProjectState();
    clearHistory();
    set({
      load: { status: "loading" },
      project: null,
      activeStep: null,
      activeNodeId: null,
      runs: {},
      chats: {},
      chatSending: {},
    });
    try {
      const graph = unwrap(
        await api.GET("/api/projects/{project_id}", {
          params: { path: { project_id: projectId } },
        }),
      );
      const materials = unwrap(
        await api.GET("/api/projects/{project_id}/materials", {
          params: { path: { project_id: projectId } },
        }),
      );
      const jobs: Record<string, Job> = {};
      for (const job of graph.active_jobs ?? []) jobs[job.node_id] = job;
      set({
        project: graph.project,
        nodes: Object.fromEntries(graph.nodes.map((n) => [n.id, n])),
        flowNodes: graph.nodes.map(toFlowNode),
        edges: graph.edges,
        flowEdges: graph.edges.map(toFlowEdge),
        outputs: Object.fromEntries(graph.outputs.map((o) => [o.id, o])),
        materials,
        jobs,
        nodeErrors: {},
        load: { status: "ready" },
      });
      // The workflow opens at its first step not run yet.
      const runs = Object.fromEntries((graph.runs ?? []).map((r) => [r.step, r]));
      set({ runs });
      const views = stepViews(graph.project.workflow, get().nodes, runs);
      const current = currentStep(views);
      if (current) set({ activeStep: current.step.key, activeNodeId: null });
      for (const job of Object.values(jobs)) poll(job.node_id, job.id);
      // A step may still be running (started before a reload).
      void watchRuns(graph.project.id);
    } catch (error) {
      set({ load: { status: "error", message: message(error) } });
    }
  },

  async closeProject() {
    await flushTyping();
    await Promise.all([flushViewport(), flushName(), flushInstruction()]);
    await session.historyChain;
    resetProjectState();
    clearHistory();
    set({
      project: null,
      load: { status: "loading" },
      nodes: {},
      flowNodes: [],
      edges: [],
      flowEdges: [],
      outputs: {},
      materials: [],
      jobs: {},
      nodeErrors: {},
      notice: null,
    });
  },

  renameProject(name) {
    const project = get().project;
    const trimmed = name.replace(/\s+/g, " ").trim();
    if (!project || !trimmed) return;
    set({ project: { ...project, name: trimmed } });
    session.pendingName = { projectId: project.id, name: trimmed };
    clearTimeout(session.renameTimer);
    session.renameTimer = setTimeout(() => void flushName(), 500);
  },

  setProjectInstruction(instruction) {
    const project = get().project;
    if (!project) return;
    set({ project: { ...project, instruction } });
    session.pendingInstruction = { projectId: project.id, instruction };
    clearTimeout(session.instructionTimer);
    session.instructionTimer = setTimeout(() => void flushInstruction(), 600);
  },

  saveViewport(viewport) {
    const project = get().project;
    if (!project) return;
    session.pendingViewport = { projectId: project.id, viewport };
    clearTimeout(session.viewportTimer);
    session.viewportTimer = setTimeout(() => void flushViewport(), 500);
  },
  };
}
