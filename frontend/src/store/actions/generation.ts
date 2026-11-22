// Generating a node, cancelling, and its takes.
import { api, unwrap } from "../../api/client";
import type { CanvasState, GetState, SetState } from "../types";
import { message } from "../core";
import type { Core } from "../core";

export function generationActions(
  set: SetState,
  get: GetState,
  core: Core,
): Pick<CanvasState, "generate" | "cancel" | "selectTake" | "addTake"> {
  const {
    clearNodeError,
    putNode,
    patchNode,
    flushTyping,
    stopPolling,
    poll,
    generateError,
  } = core;
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
    const node = get().nodes[nodeId];
    if (!node || node.selected_output_id === outputId) return;
    putNode({ ...node, selected_output_id: outputId });
    void patchNode(nodeId, { selected_output_id: outputId });
  },

  async addTake(nodeId, text) {
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
            ? { ...s.nodes, [nodeId]: { ...node, selected_output_id: output.id } }
            : s.nodes,
        };
      });
      return null;
    } catch (error) {
      return message(error);
    }
  },
  };
}
