// The canvas store's shape: its state and actions, and shared types.
import {
  type Connection,
  type Edge as FlowEdge,
  type EdgeChange,
  type Node as FlowNode,
  type NodeChange,
} from "@xyflow/react";
import { t, type Key } from "../i18n";
import {
  type Edge,
  type ChatMessage,
  type StepRun,
  type Job,
  type Material,
  type MediaKind,
  type Node,
  type NodeParams,
  type Output,
  type Project,
  type Viewport,
} from "../api/types";
import type { StateCreator } from "zustand";

export type GenFlowNode = FlowNode<{ nodeId: string }, "gen">;
export type RefFlowEdge = FlowEdge;

export type LoadState = { status: "loading" } | { status: "ready" } | { status: "error"; message: string };

export interface Notice {
  text: string;
  tone: "info" | "error";
}

export interface ConnectFrom {
  nodeId: string;
  /** "source": drag started at the node's output; "target": at its input. */
  handle: "source" | "target";
}

/** A connection made by connectEdge. */
export interface Made {
  edge: Edge;
  /** The target's prompt before (linking edits it). */
  promptBefore: string;
}

/** The node "shapes" the kind tabs switch between. */
export type NodeShape = MediaKind;

/** This tab and the project's lock: "editing" holds it; "viewing" means
    someone else (or your other tab) does, or it just came free. */
export type LockState =
  | { status: "checking" }
  | { status: "editing" }
  | { status: "viewing"; holderEmail: string | null; holderIsYou: boolean };

export interface CanvasState {
  load: LoadState;
  project: Project | null;
  /** API nodes by id. Positions here are the last saved ones. */
  nodes: Record<string, Node>;
  /** React Flow's copy: live positions while dragging, selection, sizes. */
  flowNodes: GenFlowNode[];
  /** References, in creation order (which is the order inputs are sent). */
  edges: Edge[];
  flowEdges: RefFlowEdge[];
  /** A short-lived message for the whole canvas (e.g. a rejected connection). */
  notice: Notice | null;
  canUndo: boolean;
  canRedo: boolean;
  outputs: Record<string, Output>;
  /** The project's uploaded images and videos, newest first. */
  materials: Material[];
  /** Files being uploaded right now. */
  uploading: number;
  /** Nodes whose prompt has typing not saved yet (their links may lag). */
  unsavedPrompts: Record<string, true>;
  /** Latest job per node id. */
  jobs: Record<string, Job>;
  /** Last error per node id, from generate or a failed save. */
  nodeErrors: Record<string, string>;
  pendingSaves: number;
  /** Whether this tab may change the project (see store/lock.ts). */
  lock: LockState;

  openProject(projectId: string): Promise<void>;
  /** Reload the project from the server, keeping what's open (view-only). */
  refreshProject(): Promise<void>;
  /** Take the lock (from your own other tab, with `takeOver`) and reload. */
  startEditing(takeOver?: boolean): Promise<void>;
  /** Save anything still pending, then forget the project. */
  closeProject(): Promise<void>;
  renameProject(name: string): void;
  /** Edit the project's instruction (saved shortly after typing stops). */
  setProjectInstruction(instruction: string): void;
  saveViewport(viewport: Viewport): void;

  onFlowNodesChange(changes: NodeChange<GenFlowNode>[]): void;
  addNode(
    kind: MediaKind,
    position: { x: number; y: number },
    name?: string | null,
  ): Promise<Node | undefined>;
  /** Add a node and connect it to `from`, on the side the drag started. */
  addConnectedNode(
    kind: MediaKind,
    position: { x: number; y: number },
    from: ConnectFrom,
  ): Promise<void>;
  commitPositions(ids: string[]): void;
  setPrompt(nodeId: string, prompt: string): void;
  /** Switch between image, video and text (undoable). */
  setShape(nodeId: string, shape: NodeShape): void;
  setParams(nodeId: string, params: NodeParams): void;
  /** Delete nodes (with every connection touching them) and connections. */
  deleteElements(nodeIds: string[], edgeIds: string[]): Promise<void>;

  onFlowEdgesChange(changes: EdgeChange<RefFlowEdge>[]): void;
  canConnect(connection: Connection | RefFlowEdge): boolean;
  connect(connection: Connection): Promise<void>;
  showNotice(message: string, tone?: Notice["tone"]): void;

  undo(): Promise<void>;
  redo(): Promise<void>;

  /** Set a node's ID (blank removes it). Resolves to an error, or null. */
  setName(nodeId: string, name: string): Promise<string | null>;
  uploadFiles(files: File[]): Promise<Material[]>;
  deleteMaterial(materialId: string): Promise<void>;
  /** Put a material on the canvas as an uploaded node. */
  placeMaterial(materialId: string, position: { x: number; y: number }): Promise<void>;

  generate(nodeId: string): Promise<void>;
  cancel(nodeId: string): Promise<void>;

  // --- workflow ---
  /** The workflow step open in the side panel, and the node shown there. */
  activeStep: string | null;
  activeNodeId: string | null;
  /** Open a step in the panel (null closes it), optionally at one of its nodes. */
  openStep(key: string | null, nodeId?: string | null): void;
  /** Each workflow step's last run, by step key. */
  runs: Record<string, StepRun>;
  /** Run a step with a prompt and a count (its nodes are replaced).
      Resolves to an error message, or null. */
  runStep(key: string, prompt: string, count: number | null): Promise<string | null>;
  /** Show another take of a node. */
  selectTake(nodeId: string, outputId: string): void;
  /** A hand-written text take. Resolves to an error message, or null. */
  addTake(nodeId: string, text: string): Promise<string | null>;
  /** Each text node's chat, once loaded. */
  chats: Record<string, ChatMessage[]>;
  chatSending: Record<string, boolean>;
  loadChat(nodeId: string): Promise<void>;
  sendChat(nodeId: string, text: string): Promise<void>;
  applyProposal(nodeId: string, messageId: string): Promise<void>;
}

/** One undoable step: it knows how to undo and redo itself through the API. */
export interface HistoryEntry {
  /** What the step is, for "Couldn't undo …" (an i18n key). */
  label: Key;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
}

/** The store's `set` and `get`, as the action modules receive them. */
export type SetState = Parameters<StateCreator<CanvasState>>[0];
export type GetState = Parameters<StateCreator<CanvasState>>[1];
