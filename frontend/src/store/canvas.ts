// Canvas state: the open project, its nodes (API data + React Flow
// positions), takes, and jobs. Every change goes through an action, which
// updates local state first and then saves to the API. The actions live in
// actions/*, built on the shared helpers in core.ts; this composes them.
import { create } from "zustand";
import { createCore } from "./core";
import { projectActions } from "./actions/project";
import { graphActions } from "./actions/graph";
import { mediaActions } from "./actions/media";
import { generationActions } from "./actions/generation";
import { workflowActions } from "./actions/workflow";
import { chatActions } from "./actions/chat";
import type { CanvasState } from "./types";

export { UNDO_KEY } from "./core";
export type { ConnectFrom, GenFlowNode, NodeShape, Notice, RefFlowEdge } from "./types";

export const useCanvas = create<CanvasState>()((set, get) => {
  const core = createCore(set, get);
  return {
    load: { status: "loading" },
    project: null,
    nodes: {},
    flowNodes: [],
    edges: [],
    flowEdges: [],
    notice: null,
    canUndo: false,
    canRedo: false,
    outputs: {},
    materials: [],
    uploading: 0,
    unsavedPrompts: {},
    jobs: {},
    nodeErrors: {},
    pendingSaves: 0,
    activeStep: null,
    activeNodeId: null,
    runs: {},
    chats: {},
    chatSending: {},

    ...projectActions(set, get, core),
    ...graphActions(set, get, core),
    ...mediaActions(set, get, core),
    ...generationActions(set, get, core),
    ...workflowActions(set, get, core),
    ...chatActions(set, get, core),
  };
});
