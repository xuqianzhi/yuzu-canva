// Nodes and connections: adding, moving, editing, deleting, IDs, undo/redo.
import { applyEdgeChanges, applyNodeChanges } from "@xyflow/react";
import { api, unwrap } from "../../api/client";
import { t, tn } from "../../i18n";
import {
  type Edge,
  isValidId,
  nameKey,
  normalizeName,
  type Node,
  type NodeUpdate,
} from "../../api/types";
import type { CanvasState, GetState, SetState } from "../types";
import {
  reaches,
  message,
  toFlowNode,
  promptTimers,
  pendingPrompts,
  promptBefore,
  PROMPT_SAVE_DELAY_MS,
  UNDO_KEY,
  session,
} from "../core";
import type { Core } from "../core";
import { cleanUpMoves, type Move } from "../../canvas/grid";

export function graphActions(
  set: SetState,
  get: GetState,
  core: Core,
): Pick<
  CanvasState,
  | "onFlowNodesChange"
  | "addNode"
  | "addConnectedNode"
  | "commitPositions"
  | "cleanUp"
  | "setPrompt"
  | "setShape"
  | "setParams"
  | "deleteElements"
  | "onFlowEdgesChange"
  | "canConnect"
  | "connect"
  | "showNotice"
  | "setName"
  | "undo"
  | "redo"
> {
  const {
    saving,
    putNode,
    patchNode,
    flushPrompt,
    flushTyping,
    freeId,
    connectEdge,
    recordConnection,
    record,
    step,
    apiRestore,
    deleteNow,
    applyNode,
  } = core;
  return {
  onFlowNodesChange(changes) {
    // Removals go through deleteNodes (onNodesDelete), not here.
    const kept = changes.filter((c) => c.type !== "remove");
    set((s) => ({ flowNodes: applyNodeChanges(kept, s.flowNodes) }));
  },

  async addNode(kind, position, name = null) {
    const project = get().project;
    if (!project) return;
    const node = await saving(async () =>
      unwrap(
        await api.POST("/api/projects/{project_id}/nodes", {
          params: { path: { project_id: project.id } },
          body: { kind, position, name },
        }),
      ),
    );
    if (!node) return undefined;
    set((s) => ({
      nodes: { ...s.nodes, [node.id]: node },
      flowNodes: [
        ...s.flowNodes.map((n) => ({ ...n, selected: false })),
        { ...toFlowNode(node), selected: true },
      ],
    }));
    if (session.recordIt) {
      record({
        label: "h_add",
        undo: async () => void (await deleteNow([node.id], [])),
        redo: () => apiRestore([node.id], []),
      });
    }
    return node;
  },

  async addConnectedNode(kind, position, from) {
    session.recordIt = false;
    let node: Node | undefined;
    try {
      // A node made to feed an input must have an ID to link out.
      const name = from.handle === "target" ? freeId(kind) : null;
      node = await get().addNode(kind, position, name);
    } finally {
      session.recordIt = true;
    }
    if (!node) return;
    const created = node;
    // Dragged out of an output: the new node uses it. Out of an input (a
    // character trait, or a main input): the new node feeds it.
    const made = await connectEdge(
      from.handle === "source"
        ? { source: from.nodeId, target: created.id, sourceHandle: null, targetHandle: null }
        : {
            source: created.id,
            target: from.nodeId,
            sourceHandle: null,
            targetHandle: null,
          },
    );
    const edgeIds = made ? [made.edge.id] : [];
    record({
      label: "h_add",
      undo: async () => void (await deleteNow([created.id], edgeIds)),
      redo: () => apiRestore([created.id], edgeIds),
    });
  },

  commitPositions(ids) {
    const { flowNodes, nodes } = get();
    const moves: { id: string; from: Node["position"]; to: Node["position"] }[] = [];
    for (const id of ids) {
      const flow = flowNodes.find((n) => n.id === id);
      const saved = nodes[id];
      if (!flow || !saved) continue;
      const { x, y } = flow.position;
      if (x === saved.position.x && y === saved.position.y) continue;
      moves.push({ id, from: saved.position, to: { x, y } });
      putNode({ ...saved, position: { x, y } });
      void patchNode(id, { position: { x, y } });
    }
    if (moves.length) {
      record({
        label: moves.length === 1 ? "h_move" : "h_move_many",
        undo: async () => {
          await Promise.all(moves.map((m) => applyNode(m.id, { position: m.from })));
        },
        redo: async () => {
          await Promise.all(moves.map((m) => applyNode(m.id, { position: m.to })));
        },
      });
    }
  },

  async cleanUp() {
    const project = get().project;
    if (!project) return 0;
    const moves = cleanUpMoves(Object.values(get().nodes));
    if (!moves.length) return 0;
    /** Put each node at `to` (or `from`) on screen. */
    const show = (list: Move[], where: "from" | "to") => {
      const at = new Map(list.map((m) => [m.id, m[where]]));
      set((s) => ({
        nodes: Object.fromEntries(
          Object.entries(s.nodes).map(([id, n]) => [id, at.has(id) ? { ...n, position: at.get(id)! } : n]),
        ),
        flowNodes: s.flowNodes.map((n) => (at.has(n.id) ? { ...n, position: at.get(n.id)! } : n)),
      }));
    };
    /** ...then save them all in one request (one transaction). */
    const place = async (list: Move[], where: "from" | "to") => {
      show(list, where);
      set((s) => ({ pendingSaves: s.pendingSaves + 1 }));
      try {
        unwrap(
          await api.PATCH("/api/projects/{project_id}/positions", {
            params: { path: { project_id: project.id } },
            body: { moves: list.map((m) => ({ node_id: m.id, position: m[where] })) },
          }),
        );
      } catch (error) {
        // Nothing was saved (it's all or nothing): put them back.
        show(list, where === "to" ? "from" : "to");
        throw error;
      } finally {
        set((s) => ({ pendingSaves: s.pendingSaves - 1 }));
      }
    };
    try {
      await place(moves, "to");
    } catch (error) {
      get().showNotice(message(error));
      return null;
    }
    record({
      label: "h_clean_up",
      undo: () => place(moves, "from"),
      redo: () => place(moves, "to"),
    });
    return moves.length;
  },

  setPrompt(nodeId, prompt) {
    const node = get().nodes[nodeId];
    if (!node) return;
    if (!promptBefore.has(nodeId)) promptBefore.set(nodeId, node.prompt);
    putNode({ ...node, prompt });
    if (!get().unsavedPrompts[nodeId]) {
      set((s) => ({ unsavedPrompts: { ...s.unsavedPrompts, [nodeId]: true } }));
    }
    pendingPrompts.set(nodeId, prompt);
    const timer = promptTimers.get(nodeId);
    if (timer) clearTimeout(timer);
    promptTimers.set(nodeId, setTimeout(() => void flushPrompt(nodeId), PROMPT_SAVE_DELAY_MS));
  },

  setShape(nodeId, kind) {
    const node = get().nodes[nodeId];
    if (!node || node.kind === kind) return;
    const before: NodeUpdate = {
      kind: node.kind,
      params: node.params,
      selected_output_id: node.selected_output_id,
    };
    void flushTyping([nodeId]).then(async () => {
      try {
        await applyNode(nodeId, { kind });
      } catch (error) {
        get().showNotice(message(error));
        return;
      }
      const after = get().nodes[nodeId];
      const redoBody: NodeUpdate = { kind, params: after?.params };
      record({
        label: "h_kind",
        undo: () => applyNode(nodeId, before),
        redo: () => applyNode(nodeId, redoBody),
      });
    });
  },

  setParams(nodeId, params) {
    const node = get().nodes[nodeId];
    if (!node) return;
    const before = node.params;
    putNode({ ...node, params });
    void patchNode(nodeId, { params });
    record({
      label: "h_settings",
      undo: () => applyNode(nodeId, { params: before }),
      redo: () => applyNode(nodeId, { params }),
    });
  },

  async deleteElements(nodeIds, edgeIds) {
    // Workflow nodes and connections belong to the workflow.
    const { nodes: all, edges: allEdges } = get();
    const locked = nodeIds.filter((id) => all[id]?.workflow_step);
    nodeIds = nodeIds.filter((id) => !all[id]?.workflow_step);
    edgeIds = edgeIds.filter((id) => !allEdges.find((e) => e.id === id)?.workflow);
    if (locked.length) {
      get().showNotice(
        locked.length === nodeIds.length + locked.length && !edgeIds.length
          ? t("workflow_cant_delete")
          : t("workflow_skipped"),
        "info",
      );
    }
    if (!nodeIds.length && !edgeIds.length) return;
    let removed: Awaited<ReturnType<typeof deleteNow>>;
    try {
      removed = await deleteNow(nodeIds, edgeIds);
    } catch (error) {
      get().showNotice(t("delete_failed_notice", { error: message(error) }));
      return;
    }
    record({
      label: "h_delete",
      undo: async () => {
        await apiRestore(nodeIds, removed.all);
        // Deleted main-input links come back with their "@ID" mentions.
        for (const [targetId, prompt] of Object.entries(removed.prompts)) {
          if (get().nodes[targetId]) await applyNode(targetId, { prompt });
        }
      },
      redo: async () => void (await deleteNow(nodeIds, removed.loose)),
    });
    const parts = [];
    if (nodeIds.length) parts.push(tn("count_node", nodeIds.length));
    if (removed.loose.length) parts.push(tn("count_connection", removed.loose.length));
    get().showNotice(
      t("deleted_notice", { parts: parts.join(t("join_and")), key: UNDO_KEY }),
      "info",
    );
  },

  onFlowEdgesChange(changes) {
    const kept = changes.filter((c) => c.type !== "remove");
    set((s) => ({ flowEdges: applyEdgeChanges(kept, s.flowEdges) }));
  },

  canConnect(connection) {
    const { source, target } = connection;
    if (!source || !target || source === target) return false;
    const { edges, nodes } = get();
    const targetNode = nodes[target];
    if (!nodes[source]?.name) return false; // nothing can refer to a node without an ID
    if (targetNode?.source === "upload") return false; // holds a file
    const same = (e: Edge) => e.source_node_id === source && e.target_node_id === target;
    if (edges.some(same)) return false;
    return !reaches(edges, target, source);
  },

  async connect(connection) {
    const made = await connectEdge(connection);
    if (made) recordConnection(made);
  },

  showNotice(text, tone = "error") {
    clearTimeout(session.noticeTimer);
    set({ notice: { text, tone } });
    session.noticeTimer = setTimeout(() => set({ notice: null }), 4000);
  },

  async setName(nodeId, raw) {
    const node = get().nodes[nodeId];
    if (!node) return t("node_gone");
    const name = normalizeName(raw);
    if ((name ?? null) === (node.name ?? null)) return null;
    if (name && !isValidId(name)) return t("id_rule");
    if (name) {
      const key = nameKey(name);
      const clash = Object.values(get().nodes).find(
        (n) => n.id !== nodeId && n.name && nameKey(n.name) === key,
      );
      if (clash) return t("id_clash", { id: clash.name ?? "" });
    }
    const before = node.name ?? null;
    // Without an ID nothing can refer to the node: its links out go. They
    // come back from the prompts on undo.
    try {
      await applyNode(nodeId, { name });
    } catch (error) {
      putNode(node);
      return message(error);
    }
    record({
      label: "h_id",
      undo: () => applyNode(nodeId, { name: before }),
      redo: () => applyNode(nodeId, { name }),
    });
    return null;
  },

  undo: () => step("undo"),
  redo: () => step("redo"),
  };
}
