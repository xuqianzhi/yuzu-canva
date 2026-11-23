// What the canvas store's parts share: conversions to React Flow, module-level
// timers and history, and the helpers the actions are built from.
import { MarkerType, type Connection } from "@xyflow/react";
import { api, ApiError, unwrap } from "../api/client";
import { inputKeys, labelInputs } from "../canvas/inputs";
import { errorText, t } from "../i18n";
import {
  TERMINAL_JOB_STATUSES,
  type Edge,
  type ProjectGraph,
  type Job,
  idMap,
  nameKey,
  type Node,
  type NodeUpdate,
  type Output,
  type Viewport,
} from "../api/types";
import type { GenFlowNode, GetState, HistoryEntry, Made, RefFlowEdge, SetState } from "./types";

export const toFlowEdge = (edge: Edge): RefFlowEdge => ({
  id: edge.id,
  source: edge.source_node_id,
  target: edge.target_node_id,
  markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
  // Workflow connections belong to the workflow: drawn apart, not deletable.
  ...(edge.workflow ? { className: "edge--workflow", deletable: false, selectable: false } : {}),
});

/** Would source -> target close a cycle? (Does target already reach source?) */
export function reaches(edges: Edge[], from: string, to: string): boolean {
  const stack = [from];
  const seen = new Set<string>();
  while (stack.length) {
    const node = stack.pop()!;
    if (node === to) return true;
    if (seen.has(node)) continue;
    seen.add(node);
    for (const e of edges) if (e.source_node_id === node) stack.push(e.target_node_id);
  }
  return false;
}

/** An error as the UI words it (in the current language). */
export const message = (error: unknown) => errorText(error);

export const toFlowNode = (node: Node): GenFlowNode => ({
  id: node.id,
  type: "gen",
  position: node.position,
  data: { nodeId: node.id },
  dragHandle: ".gen-node__header",
  ...(node.workflow_step ? { deletable: false } : {}),
});

// Per-node timers for debounced prompt saves and job polling. Kept outside
// the store: they are plumbing, not state anyone renders.
export const promptTimers = new Map<string, ReturnType<typeof setTimeout>>();
export const pendingPrompts = new Map<string, string>();
export const pollers = new Map<string, ReturnType<typeof setTimeout>>();
/** False while addConnectedNode records the node and its edge as one step. */

export const undoStack: HistoryEntry[] = [];
export const redoStack: HistoryEntry[] = [];
export const HISTORY_LIMIT = 200;
/** A node's prompt before the current run of typing (one undo step per run). */
export const promptBefore = new Map<string, string>();

export const PROMPT_SAVE_DELAY_MS = 400;
export const UNDO_KEY = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘Z" : "Ctrl+Z";
/** How often a running step run is checked on. */
export const RUN_POLL_MS = 1500;

export const POLL_INTERVAL_MS = 1000;

/** Module-level values that change over time (timers, what's waiting to
    be saved, the history chain), shared by the store's parts. */
export const session: {
  viewportTimer: ReturnType<typeof setTimeout> | undefined;
  pendingViewport: { projectId: string; viewport: Viewport } | undefined;
  renameTimer: ReturnType<typeof setTimeout> | undefined;
  pendingName: { projectId: string; name: string } | undefined;
  instructionTimer: ReturnType<typeof setTimeout> | undefined;
  pendingInstruction: { projectId: string; instruction: string } | undefined;
  noticeTimer: ReturnType<typeof setTimeout> | undefined;
  recordIt: boolean;
  historyChain: Promise<void>;
  /** The project whose running step runs are being polled, if any. */
  watchingRuns: string | null;
} = {
  viewportTimer: undefined,
  pendingViewport: undefined,
  renameTimer: undefined,
  pendingName: undefined,
  instructionTimer: undefined,
  pendingInstruction: undefined,
  noticeTimer: undefined,
  recordIt: true,
  historyChain: Promise.resolve(),
  watchingRuns: null,
};

/** The helpers the actions share: saving, links, polling, history, local
    graph edits. Made once per store, around its `set` and `get`. */
export function createCore(set: SetState, get: GetState) {
  /** Run a save, tracking it for the "Saving…" indicator. */
  async function saving<T>(work: () => Promise<T>, nodeId?: string): Promise<T | undefined> {
    set((s) => ({ pendingSaves: s.pendingSaves + 1 }));
    try {
      const result = await work();
      if (nodeId) clearNodeError(nodeId);
      return result;
    } catch (error) {
      if (nodeId) set((s) => ({ nodeErrors: { ...s.nodeErrors, [nodeId]: message(error) } }));
      else console.error(error);
      return undefined;
    } finally {
      set((s) => ({ pendingSaves: s.pendingSaves - 1 }));
    }
  }

  function clearNodeError(nodeId: string) {
    if (!(nodeId in get().nodeErrors)) return;
    set((s) => {
      const { [nodeId]: _, ...rest } = s.nodeErrors;
      return { nodeErrors: rest };
    });
  }

  function putNode(node: Node) {
    set((s) => ({ nodes: { ...s.nodes, [node.id]: node } }));
  }

  async function patchNode(nodeId: string, body: NodeUpdate) {
    const node = await saving(() => updateNode(nodeId, body), nodeId);
    if (node && get().nodes[nodeId]) {
      // Keep any prompt typed while this request was in flight.
      const typed = pendingPrompts.get(nodeId);
      putNode(typed === undefined ? node : { ...node, prompt: typed });
    }
    if (node && changesLinks(body)) await refreshLinks();
  }

  /** Whether a node update can change links (or other nodes' prompts). */
  function changesLinks(body: NodeUpdate): boolean {
    return ["prompt", "name", "kind"].some((key) => key in body);
  }

  /**
   * Reload links, and nodes' IDs and prompts, from the server. Links follow
   * prompts there ("@ID"), and renaming an ID rewrites other prompts, so
   * after any such change the server is the source of truth. Typing that is
   * not saved yet is kept.
   */
  async function refreshLinks() {
    const project = get().project;
    if (!project) return;
    let graph;
    try {
      graph = unwrap(
        await api.GET("/api/projects/{project_id}", {
          params: { path: { project_id: project.id } },
        }),
      );
    } catch {
      return; // a later change will refresh again
    }
    if (get().project?.id !== project.id) return;
    set((s) => {
      const nodes = { ...s.nodes };
      for (const fresh of graph.nodes) {
        const local = nodes[fresh.id];
        if (!local) continue;
        nodes[fresh.id] = {
          ...local,
          name: fresh.name,
          prompt: pendingPrompts.get(fresh.id) ?? fresh.prompt,
        };
      }
      const selected = new Set(s.flowEdges.filter((e) => e.selected).map((e) => e.id));
      return {
        nodes,
        edges: graph.edges,
        flowEdges: graph.edges.map((e) => ({ ...toFlowEdge(e), selected: selected.has(e.id) })),
      };
    });
  }

  async function flushPrompt(nodeId: string) {
    const timer = promptTimers.get(nodeId);
    if (timer) clearTimeout(timer);
    promptTimers.delete(nodeId);
    const prompt = pendingPrompts.get(nodeId);
    if (prompt === undefined) return;
    pendingPrompts.delete(nodeId);
    await patchNode(nodeId, { prompt });
    if (!pendingPrompts.has(nodeId)) {
      set((s) => {
        const { [nodeId]: _, ...rest } = s.unsavedPrompts;
        return { unsavedPrompts: rest };
      });
    }
    const before = promptBefore.get(nodeId);
    promptBefore.delete(nodeId);
    if (before !== undefined && before !== prompt) {
      record({
        label: "h_prompt",
        undo: () => applyNode(nodeId, { prompt: before }),
        redo: () => applyNode(nodeId, { prompt }),
      });
    }
  }

  /** Save all typing still waiting for its pause. */
  async function flushTyping(nodeIds?: string[]) {
    const pick = (ids: Iterable<string>) => [...ids].filter((id) => !nodeIds || nodeIds.includes(id));
    await Promise.all([
      ...pick(pendingPrompts.keys()).map((id) => flushPrompt(id)),
    ]);
  }

  function stopPolling(nodeId: string) {
    const timer = pollers.get(nodeId);
    if (timer) clearTimeout(timer);
    pollers.delete(nodeId);
  }

  function poll(nodeId: string, jobId: string) {
    stopPolling(nodeId);
    pollers.set(
      nodeId,
      setTimeout(async () => {
        let job: Job;
        try {
          job = unwrap(await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: jobId } } }));
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) return stopPolling(nodeId);
          return poll(nodeId, jobId); // network blip: keep trying
        }
        if (get().jobs[nodeId]?.id !== jobId) return; // superseded
        set((s) => ({ jobs: { ...s.jobs, [nodeId]: job } }));
        if (!TERMINAL_JOB_STATUSES.includes(job.status)) return poll(nodeId, jobId);
        pollers.delete(nodeId);
        if (job.status === "succeeded") await loadOutputs(nodeId, job.output_id ?? null);
      }, POLL_INTERVAL_MS),
    );
  }

  /** `base_1`, `base_2`... the first ID no node has. */
  function freeId(base: string): string {
    const taken = new Set(Object.keys(idMap(get().nodes)).map((id) => nameKey(id)));
    let n = 1;
    while (taken.has(nameKey(`${base}_${n}`))) n++;
    return `${base}_${n}`;
  }

  /** Errors that point at a referenced node, phrased by its input number. */
  function generateError(nodeId: string, error: unknown): string {
    if (error instanceof ApiError && error.code === "missing_ref_output") {
      const source = error.body.error.context?.node_id;
      const { edges, nodes, outputs } = get();
      const target = nodes[nodeId];
      const input = target
        ? labelInputs(inputKeys(nodeId, edges, nodes, outputs)).find(
            (i) => i.nodeId === source,
          )
        : undefined;
      if (input) return t("input_no_output", { label: input.label });
    }
    return message(error);
  }

  async function loadOutputs(nodeId: string, selected: string | null) {
    const outputs = unwrap(
      await api.GET("/api/nodes/{node_id}/outputs", { params: { path: { node_id: nodeId } } }),
    );
    set((s) => {
      const node = s.nodes[nodeId];
      if (!node) return {};
      const merged = { ...s.outputs };
      for (const output of outputs) merged[output.id] = output;
      return {
        outputs: merged,
        nodes: selected ? { ...s.nodes, [nodeId]: { ...node, selected_output_id: selected } } : s.nodes,
      };
    });
  }

  function resetProjectState() {
    for (const nodeId of pollers.keys()) stopPolling(nodeId);
    for (const timer of promptTimers.values()) clearTimeout(timer);
    promptTimers.clear();
    pendingPrompts.clear();
    clearTimeout(session.viewportTimer);
    clearTimeout(session.renameTimer);
    clearTimeout(session.instructionTimer);
    session.pendingViewport = undefined;
    session.pendingName = undefined;
    session.pendingInstruction = undefined;
  }

  async function flushViewport() {
    clearTimeout(session.viewportTimer);
    const pending = session.pendingViewport;
    session.pendingViewport = undefined;
    if (!pending) return;
    await saving(async () =>
      unwrap(
        await api.PATCH("/api/projects/{project_id}", {
          params: { path: { project_id: pending.projectId } },
          body: { viewport: pending.viewport },
        }),
      ),
    );
  }

  async function flushName() {
    clearTimeout(session.renameTimer);
    const pending = session.pendingName;
    session.pendingName = undefined;
    if (!pending) return;
    await saving(async () =>
      unwrap(
        await api.PATCH("/api/projects/{project_id}", {
          params: { path: { project_id: pending.projectId } },
          body: { name: pending.name },
        }),
      ),
    );
  }

  async function flushInstruction() {
    clearTimeout(session.instructionTimer);
    const pending = session.pendingInstruction;
    session.pendingInstruction = undefined;
    if (!pending) return;
    await saving(async () =>
      unwrap(
        await api.PATCH("/api/projects/{project_id}", {
          params: { path: { project_id: pending.projectId } },
          body: { instruction: pending.instruction },
        }),
      ),
    );
  }

  /**
   * Create an edge (after checks). Returns the new edge, or undefined (with
   * a notice) if it could not be made.
   */
  async function connectEdge(connection: Connection): Promise<Made | undefined> {
    const project = get().project;
    const { source, target } = connection;
    if (!project || !source || !target) return undefined;
    if (!get().canConnect(connection)) {
      get().showNotice(
        !get().nodes[source]?.name ? t("give_id_first") : t("loop_or_exists"),
      );
      return undefined;
    }
    const promptBefore = get().nodes[target]?.prompt ?? "";
    try {
      const edge = unwrap(
        await api.POST("/api/projects/{project_id}/edges", {
          params: { path: { project_id: project.id } },
          body: { source_node_id: source, target_node_id: target },
        }),
      );
      // The source's ID was added to the target's prompt: reload it.
      await refreshLinks();
      return { edge, promptBefore };
    } catch (error) {
      get().showNotice(message(error));
      return undefined;
    }
  }

  /**
   * Record a connection made by connectEdge. A link is really the ID it
   * added to the target's prompt, so it is undone as that prompt change.
   */
  function recordConnection(made: Made) {
    const { edge, promptBefore: before } = made;
    const after = get().nodes[edge.target_node_id]?.prompt ?? "";
    record({
      label: "h_connection",
      undo: () => applyNode(edge.target_node_id, { prompt: before ?? "" }),
      redo: () => applyNode(edge.target_node_id, { prompt: after }),
    });
  }

  // --- history ---------------------------------------------------------------

  function syncHistory() {
    set({ canUndo: undoStack.length > 0, canRedo: redoStack.length > 0 });
  }

  function record(entry: HistoryEntry) {
    undoStack.push(entry);
    if (undoStack.length > HISTORY_LIMIT) undoStack.shift();
    redoStack.length = 0;
    syncHistory();
  }

  function clearHistory() {
    undoStack.length = 0;
    redoStack.length = 0;
    promptBefore.clear();
    syncHistory();
  }

  function step(direction: "undo" | "redo"): Promise<void> {
    session.historyChain = session.historyChain.then(async () => {
      // Typing that has not been saved yet is the newest change: save it
      // (which records it) before stepping.
      await flushTyping();
      const [from, to] = direction === "undo" ? [undoStack, redoStack] : [redoStack, undoStack];
      const entry = from.pop();
      if (!entry) return;
      syncHistory();
      try {
        await entry[direction]();
        to.push(entry);
      } catch (error) {
        get().showNotice(
          t(direction === "undo" ? "undo_failed" : "redo_failed", {
            label: t(entry.label),
            error: message(error),
          }),
        );
      }
      syncHistory();
    });
    return session.historyChain;
  }

  // --- local graph edits (no API) -------------------------------------------------

  /** Remove nodes (and every edge touching them) and edges from local state. */
  function removeLocal(nodeIds: string[], edgeIds: string[]) {
    for (const id of nodeIds) {
      stopPolling(id);
      const timer = promptTimers.get(id);
      if (timer) clearTimeout(timer);
      promptTimers.delete(id);
      pendingPrompts.delete(id);
      promptBefore.delete(id);
    }
    set((s) => {
      const nodes = { ...s.nodes };
      const jobs = { ...s.jobs };
      for (const id of nodeIds) {
        delete nodes[id];
        delete jobs[id];
      }
      const gone = (e: Edge) =>
        edgeIds.includes(e.id) ||
        nodeIds.includes(e.source_node_id) ||
        nodeIds.includes(e.target_node_id);
      const edges = s.edges.filter((e) => !gone(e));
      const kept = new Set(edges.map((e) => e.id));
      return {
        nodes,
        jobs,
        edges,
        flowEdges: s.flowEdges.filter((e) => kept.has(e.id)),
        flowNodes: s.flowNodes.filter((n) => !nodeIds.includes(n.id)),
      };
    });
  }

  /** Add nodes, edges and outputs (e.g. restored ones) to local state. */
  function addLocal(nodes: Node[], edges: Edge[], outputs: Output[]) {
    set((s) => {
      const known = new Set(s.flowNodes.map((n) => n.id));
      const allEdges = [...s.edges.filter((e) => !edges.some((x) => x.id === e.id)), ...edges]
        // Creation order is the order inputs are sent, so keep it.
        .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
      return {
        nodes: { ...s.nodes, ...Object.fromEntries(nodes.map((n) => [n.id, n])) },
        flowNodes: [...s.flowNodes, ...nodes.filter((n) => !known.has(n.id)).map(toFlowNode)],
        edges: allEdges,
        flowEdges: allEdges.map(
          (e) => s.flowEdges.find((f) => f.id === e.id) ?? toFlowEdge(e),
        ),
        outputs: { ...s.outputs, ...Object.fromEntries(outputs.map((o) => [o.id, o])) },
      };
    });
  }

  async function apiDelete(nodeIds: string[], looseEdgeIds: string[]) {
    await Promise.all([
      ...nodeIds.map(async (id) =>
        unwrap(await api.DELETE("/api/nodes/{node_id}", { params: { path: { node_id: id } } })),
      ),
      ...looseEdgeIds.map(async (id) =>
        unwrap(await api.DELETE("/api/edges/{edge_id}", { params: { path: { edge_id: id } } })),
      ),
    ]);
  }

  async function apiRestore(nodeIds: string[], edgeIds: string[]) {
    const project = get().project;
    if (!project) return;
    const restored = unwrap(
      await api.POST("/api/projects/{project_id}/restore", {
        params: { path: { project_id: project.id } },
        body: { node_ids: nodeIds, edge_ids: edgeIds },
      }),
    );
    addLocal(restored.nodes, restored.edges, restored.outputs);
    await refreshLinks(); // restored IDs re-link mentions of them
    if (restored.nodes.length < new Set(nodeIds).size) {
      throw new Error(t("deleted_too_long"));
    }
  }

  /**
   * Delete locally, then on the server. Returns every edge removed: the
   * ones asked for, plus those touching the nodes (the server deletes those
   * with their node, so only the "loose" ones are sent).
   */
  async function deleteNow(
    nodeIds: string[],
    edgeIds: string[],
  ): Promise<{ all: string[]; loose: string[]; prompts: Record<string, string> }> {
    // Save typing first, so a restored node comes back with it.
    await flushTyping(nodeIds);
    const touching = get()
      .edges.filter((e) => nodeIds.includes(e.source_node_id) || nodeIds.includes(e.target_node_id))
      .map((e) => e.id);
    const loose = edgeIds.filter((id) => !touching.includes(id));
    // Deleting a main-input link removes its "@ID" from the target's prompt:
    // remember those prompts, so undo can put the mentions (and links) back.
    const prompts: Record<string, string> = {};
    for (const id of loose) {
      const edge = get().edges.find((e) => e.id === id);
      const target = edge && !edge.workflow ? get().nodes[edge.target_node_id] : undefined;
      if (target) prompts[target.id] ??= target.prompt;
    }
    removeLocal(nodeIds, edgeIds);
    await apiDelete(nodeIds, loose);
    await refreshLinks();
    return { all: [...new Set([...touching, ...loose])], loose, prompts };
  }

  /** Take the server's whole graph (after a workflow change), keeping what
      React Flow knows (live positions, selection) and unsaved typing. */
  function replaceGraph(graph: ProjectGraph) {
    set((s) => {
      const flow = new Map(s.flowNodes.map((n) => [n.id, n]));
      const nodes: Record<string, Node> = {};
      for (const fresh of graph.nodes) {
        nodes[fresh.id] = { ...fresh, prompt: pendingPrompts.get(fresh.id) ?? fresh.prompt };
      }
      const selected = new Set(s.flowEdges.filter((e) => e.selected).map((e) => e.id));
      return {
        nodes,
        flowNodes: graph.nodes.map((n) => flow.get(n.id) ?? toFlowNode(n)),
        edges: graph.edges,
        flowEdges: graph.edges.map((e) => ({ ...toFlowEdge(e), selected: selected.has(e.id) })),
        outputs: { ...s.outputs, ...Object.fromEntries(graph.outputs.map((o) => [o.id, o])) },
        runs: Object.fromEntries((graph.runs ?? []).map((r) => [r.step, r])),
      };
    });
  }

  /** Follow a project's step runs until none is running: they finish in
      the background (the text model can take a while). When one ends, the
      graph is reloaded (its new nodes) and their jobs followed. */
  async function watchRuns(projectId: string) {
    if (session.watchingRuns === projectId) return;
    session.watchingRuns = projectId;
    const running = () =>
      get().project?.id === projectId &&
      Object.values(get().runs).some((run) => run.status === "running");
    try {
      while (running()) {
        await new Promise((resolve) => setTimeout(resolve, RUN_POLL_MS));
        if (get().project?.id !== projectId) break;
        const graph = unwrap(
          await api.GET("/api/projects/{project_id}", {
            params: { path: { project_id: projectId } },
          }),
        );
        if (get().project?.id !== projectId) break;
        const runs = Object.fromEntries((graph.runs ?? []).map((r) => [r.step, r]));
        const ended = Object.values(get().runs).some(
          (run) => run.status === "running" && runs[run.step]?.status !== "running",
        );
        if (!ended) {
          set({ runs });
          continue;
        }
        replaceGraph(graph);
        const jobs = Object.fromEntries(graph.active_jobs.map((j) => [j.node_id, j]));
        set((s) => ({ jobs: { ...s.jobs, ...jobs } }));
        for (const job of Object.values(jobs)) poll(job.node_id, job.id);
      }
    } catch {
      // Lost the connection: opening the project again picks the runs up.
    } finally {
      if (session.watchingRuns === projectId) session.watchingRuns = null;
    }
  }

  /** Set node fields locally and on the server (used by undo/redo). */
  async function applyNode(nodeId: string, body: NodeUpdate) {
    const node = get().nodes[nodeId];
    if (!node) throw new Error(t("node_gone"));
    putNode({ ...node, ...(body as Partial<Node>) });
    if (body.position) {
      const position = body.position;
      set((s) => ({
        flowNodes: s.flowNodes.map((n) => (n.id === nodeId ? { ...n, position } : n)),
      }));
    }
    const updated = await updateNode(nodeId, body);
    putNode(updated);
    if (changesLinks(body)) await refreshLinks();
  }

  return {
    saving,
    clearNodeError,
    putNode,
    patchNode,
    changesLinks,
    refreshLinks,
    flushPrompt,
    flushTyping,
    stopPolling,
    poll,
    freeId,
    generateError,
    loadOutputs,
    resetProjectState,
    flushViewport,
    flushName,
    flushInstruction,
    connectEdge,
    recordConnection,
    syncHistory,
    record,
    clearHistory,
    step,
    removeLocal,
    addLocal,
    apiDelete,
    apiRestore,
    deleteNow,
    replaceGraph,
    watchRuns,
    applyNode,
  };
}

export type Core = ReturnType<typeof createCore>;

export async function updateNode(nodeId: string, body: NodeUpdate): Promise<Node> {
  return unwrap(
    await api.PATCH("/api/nodes/{node_id}", { params: { path: { node_id: nodeId } }, body }),
  );
}
