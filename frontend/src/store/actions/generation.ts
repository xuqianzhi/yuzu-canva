// Generating a node, cancelling, its takes, and "Edit prompt with AI".
import { api, unwrap } from "../../api/client";
import type { CanvasState, GetState, SetState } from "../types";
import { message } from "../core";
import type { Core } from "../core";

export function generationActions(
  set: SetState,
  get: GetState,
  core: Core,
): Pick<CanvasState, "generate" | "cancel" | "selectTake" | "addTake" | "aiEdit"> {
  const {
    clearNodeError,
    putNode,
    patchNode,
    flushTyping,
    stopPolling,
    poll,
    generateError,
  } = core;
  // A new version being saved, by node: picking another waits for it, so the
  // pick is the one that stays.
  const savingTake = new Map<string, Promise<unknown>>();
  return {
  async generate(nodeId) {
    await flushTyping([nodeId]);
    clearNodeError(nodeId);
    try {
      const job = unwrap(
        await api.POST("/api/nodes/{node_id}/generate", {
          params: { path: { node_id: nodeId } },
        }),
      );
      set((s) => ({ jobs: { ...s.jobs, [nodeId]: job } }));
      poll(nodeId, job.id);
    } catch (error) {
      set((s) => ({ nodeErrors: { ...s.nodeErrors, [nodeId]: generateError(nodeId, error) } }));
    }
  },

  async cancel(nodeId) {
    const job = get().jobs[nodeId];
    if (!job) return;
    try {
      const canceled = unwrap(
        await api.POST("/api/jobs/{job_id}/cancel", { params: { path: { job_id: job.id } } }),
      );
      stopPolling(nodeId);
      set((s) => ({ jobs: { ...s.jobs, [nodeId]: canceled } }));
    } catch (error) {
      set((s) => ({ nodeErrors: { ...s.nodeErrors, [nodeId]: message(error) } }));
    }
  },
  selectTake(nodeId, outputId) {
    const saving = savingTake.get(nodeId);
    if (saving) {
      void saving.then(() => get().selectTake(nodeId, outputId));
      return;
    }
    const node = get().nodes[nodeId];
    if (!node || node.selected_output_id === outputId) return;
    putNode({ ...node, selected_output_id: outputId });
    void patchNode(nodeId, { selected_output_id: outputId });
  },

  addTake(nodeId, text) {
    const save = async () => {
      try {
        const output = unwrap(
          await api.POST("/api/nodes/{node_id}/takes", {
            params: { path: { node_id: nodeId } },
            body: { text },
          }),
        );
        set((s) => {
          const node = s.nodes[nodeId];
          return {
            outputs: { ...s.outputs, [output.id]: output },
            nodes: node
              ? {
                  ...s.nodes,
                  [nodeId]: {
                    ...node,
                    selected_output_id: output.id,
                    // The server marks a workflow node's hand-made take as an edit.
                    edited: node.edited || node.workflow_step !== null,
                  },
                }
              : s.nodes,
          };
        });
        return null;
      } catch (error) {
        return message(error);
      }
    };
    const saved = save();
    savingTake.set(nodeId, saved);
    void saved.finally(() => savingTake.delete(nodeId));
    return saved;
  },

  async aiEdit(nodeId, instruction) {
    try {
      return unwrap(
        await api.POST("/api/nodes/{node_id}/ai-edit", {
          params: { path: { node_id: nodeId } },
          body: { instruction },
        }),
      );
    } catch (error) {
      throw new Error(message(error));
    }
  },
  };
}
