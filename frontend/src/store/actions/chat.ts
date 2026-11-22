// A text node's chat with the model.
import { api, unwrap } from "../../api/client";
import type { CanvasState, GetState, SetState } from "../types";
import { message } from "../core";
import type { Core } from "../core";

export function chatActions(
  set: SetState,
  get: GetState,
  core: Core,
): Pick<CanvasState, "loadChat" | "sendChat" | "applyProposal"> {
  return {
  async loadChat(nodeId) {
    try {
      const messages = unwrap(
        await api.GET("/api/nodes/{node_id}/chat", { params: { path: { node_id: nodeId } } }),
      );
      set((s) => ({ chats: { ...s.chats, [nodeId]: messages } }));
    } catch (error) {
      get().showNotice(message(error));
    }
  },

  async sendChat(nodeId, text) {
    if (get().chatSending[nodeId]) return;
    set((s) => ({ chatSending: { ...s.chatSending, [nodeId]: true } }));
    try {
      const added = unwrap(
        await api.POST("/api/nodes/{node_id}/chat", {
          params: { path: { node_id: nodeId } },
          body: { text },
        }),
      );
      set((s) => ({ chats: { ...s.chats, [nodeId]: [...(s.chats[nodeId] ?? []), ...added] } }));
    } catch (error) {
      throw new Error(message(error));
    } finally {
      set((s) => ({ chatSending: { ...s.chatSending, [nodeId]: false } }));
    }
  },

  async applyProposal(nodeId, messageId) {
    try {
      const output = unwrap(
        await api.POST("/api/chat/{message_id}/apply", {
          params: { path: { message_id: messageId } },
        }),
      );
      set((s) => {
        const node = s.nodes[nodeId];
        return {
          outputs: { ...s.outputs, [output.id]: output },
          nodes: node
            ? { ...s.nodes, [nodeId]: { ...node, selected_output_id: output.id } }
            : s.nodes,
          chats: {
            ...s.chats,
            [nodeId]: (s.chats[nodeId] ?? []).map((m) =>
              m.id === messageId ? { ...m, applied_output_id: output.id } : m,
            ),
          },
        };
      });
    } catch (error) {
      get().showNotice(message(error));
    }
  },
  };
}
