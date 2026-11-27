// Opening and closing a project; its name, description and viewport.
import { api, ApiError, unwrap } from "../../api/client";
import { t } from "../../i18n";
import { currentStep, stepViews } from "../../workflow/status";
import { type Job } from "../../api/types";
import type { CanvasState, GetState, SetState } from "../types";
import { toFlowEdge, message, runsOf, toFlowNode, session } from "../core";
import type { Core } from "../core";

export function projectActions(
  set: SetState,
  get: GetState,
  core: Core,
): Pick<
  CanvasState,
  | "openProject"
  | "refreshProject"
  | "startEditing"
  | "closeProject"
  | "renameProject"
  | "setProjectDescription"
  | "saveViewport"
> {
  const {
    flushTyping,
    poll,
    resetProjectState,
    flushViewport,
    flushName,
    flushDescription,
    clearHistory,
    watchRuns,
    lock,
  } = core;
  const editing = () => get().lock.status === "editing";

  async function open(projectId: string, takeOver = false) {
    lock.stop();
    resetProjectState();
    clearHistory();
    set({
      load: { status: "loading" },
      project: null,
      activeStep: null,
      activeNodeId: null,
      runs: {},
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
      const runs = runsOf(graph);
      set({ runs });
      const views = stepViews(graph.project.workflow, get().nodes, runs);
      const current = currentStep(views);
      if (current) set({ activeStep: current.step.key, activeNodeId: null });
      for (const job of Object.values(jobs)) poll(job.node_id, job.id);
      // A step may still be running (started before a reload).
      void watchRuns(graph.project.id);
      // One tab at a time may change it (see store/lock.ts).
      await lock.start(projectId, takeOver);
    } catch (error) {
      set({ load: { status: "error", message: message(error) } });
    }
  }

  return {
  openProject: (projectId) => open(projectId),

  async startEditing(takeOver = false) {
    const project = get().project;
    if (project) await open(project.id, takeOver);
  },

  async refreshProject() {
    const project = get().project;
    if (!project) return;
    let graph;
    let materials;
    try {
      graph = unwrap(
        await api.GET("/api/projects/{project_id}", {
          params: { path: { project_id: project.id } },
        }),
      );
      materials = unwrap(
        await api.GET("/api/projects/{project_id}/materials", {
          params: { path: { project_id: project.id } },
        }),
      );
    } catch (error) {
      if (get().project?.id !== project.id) return;
      if (error instanceof ApiError && error.status === 404) {
        set({ load: { status: "error", message: t("project_gone") } });
      }
      return;
    }
    if (get().project?.id !== project.id || editing()) return;
    const jobs: Record<string, Job> = {};
    for (const job of graph.active_jobs ?? []) jobs[job.node_id] = job;
    set((s) => {
      const flow = new Map(s.flowNodes.map((n) => [n.id, n]));
      return {
        project: graph.project,
        nodes: Object.fromEntries(graph.nodes.map((n) => [n.id, n])),
        // Their positions (they may have moved nodes), our selection.
        flowNodes: graph.nodes.map((n) => ({
          ...(flow.get(n.id) ?? toFlowNode(n)),
          position: n.position,
        })),
        edges: graph.edges,
        flowEdges: graph.edges.map(toFlowEdge),
        outputs: Object.fromEntries(graph.outputs.map((o) => [o.id, o])),
        materials,
        jobs,
        runs: Object.fromEntries((graph.runs ?? []).map((r) => [r.step, r])),
      };
    });
  },

  async closeProject() {
    await flushTyping();
    await Promise.all([flushViewport(), flushName(), flushDescription()]);
    await session.historyChain;
    lock.stop();
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
    if (!project || !trimmed || !editing()) return;
    set({ project: { ...project, name: trimmed } });
    session.pendingName = { projectId: project.id, name: trimmed };
    clearTimeout(session.renameTimer);
    session.renameTimer = setTimeout(() => void flushName(), 500);
  },

  setProjectDescription(description) {
    const project = get().project;
    if (!project || !editing()) return;
    set({ project: { ...project, description } });
    session.pendingDescription = { projectId: project.id, description };
    clearTimeout(session.descriptionTimer);
    session.descriptionTimer = setTimeout(() => void flushDescription(), 600);
  },

  saveViewport(viewport) {
    const project = get().project;
    if (!project || !editing()) return;
    session.pendingViewport = { projectId: project.id, viewport };
    clearTimeout(session.viewportTimer);
    session.viewportTimer = setTimeout(() => void flushViewport(), 500);
  },
  };
}
