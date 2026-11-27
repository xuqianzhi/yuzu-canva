import {
  Background,
  BackgroundVariant,
  ControlButton,
  Controls,
  MiniMap,
  ReactFlow,
  SelectionMode,
  useReactFlow,
  useStore,
  type EdgeTypes,
  type FinalConnectionState,
  type NodeTypes,
  type Viewport,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { isActive } from "../api/types";
import {
  useCanvas,
  type ConnectFrom,
  type GenFlowNode,
  type NodeShape,
  type RefFlowEdge,
} from "../store/canvas";
import { useShallow } from "zustand/react/shallow";
import { useView } from "../store/view";
import { GenNode } from "./GenNode";
import { RefEdge } from "./RefEdge";
import { MATERIAL_MIME, Sidebar } from "./Sidebar";
import { useT, type Key, type T } from "../i18n";

const nodeTypes: NodeTypes = { gen: GenNode };

/** The two drag tools, in the controls. */
const TOOLS = [
  {
    id: "hand",
    label: "tool_hand",
    path: "M5.5 8V3.8a1 1 0 0 1 2 0V7.5M7.5 7V2.8a1 1 0 0 1 2 0V7.5M9.5 7.2V3.8a1 1 0 0 1 2 0v5.4c0 2.7-1.7 4.8-4.3 4.8-1.7 0-2.6-.8-3.5-2.1L2.4 9.2a1 1 0 0 1 1.6-1.2l1.5 1.8",
  },
  {
    id: "select",
    label: "tool_select",
    path: "M3.5 2.5 12 8.2l-3.9.7 2.2 4.3-1.6.8-2.2-4.3-3 2.6z",
  },
] as const;

// Where each project's canvas was last looked at, for coming back to it
// (from the basic view); the saved one applies on a fresh load.
const lastViews = new Map<string, Viewport>();
const edgeTypes: EdgeTypes = { ref: RefEdge };

// Node geometry, matching styles.css ("nodes: an output square over a prompt
// card"): 480 wide, a 30 header, the 320 output square centred under it, then
// the card. Links come into the card's left edge and go out of its right
// edge, LINK_TOP down: a node created at a drop point lines its link up with
// the cursor.
const NODE_WIDTH = 480;
const HEADER = 30;
const LINK_TOP = 402;
// Where the output square's centre is, down from the node's top.
const SQUARE_CENTRE = HEADER + 6 + 160;

// Below this zoom a node's small print (its prompt, input thumbnails,
// settings and buttons) is too small to read: it isn't drawn (it keeps its
// space, so nodes and links don't move).
const FAR_ZOOM = 0.5;

// How long the view must be still before it's drawn sharp again.
const MOVE_SETTLE_MS = 200;

interface Choice {
  shape: NodeShape;
  label: Key;
  hint: string;
}

const MENU: Choice[] = [
  { shape: "image", label: "shape_image", hint: "OpenAI" },
  { shape: "video", label: "shape_video", hint: "Seedance" },
  { shape: "text", label: "shape_text", hint: "OpenAI" },
];

// The menu's size, roughly (see .create-menu), to keep it on screen.
const MENU_WIDTH = 240;
const MENU_HEIGHT = 150;

// One small line icon per kind, for the menu.
const MENU_ICONS: Record<NodeShape, React.ReactNode> = {
  text: <path d="M3.5 4h9M8 4v8.5M6 12.5h4" />,
  image: (
    <>
      <rect x="2.5" y="3" width="11" height="10" rx="1.8" />
      <circle cx="6" cy="6.5" r="1.1" />
      <path d="m3 11.5 3.2-3 2.3 2.1 1.6-1.4 2.9 2.6" />
    </>
  ),
  video: (
    <>
      <rect x="2" y="4" width="8.5" height="8" rx="1.8" />
      <path d="m10.5 7 3.5-2v6l-3.5-2" />
    </>
  ),
};

/** Open after a connection is dropped on empty canvas. */
interface CreateMenu {
  /** Where to draw the menu, relative to the canvas. */
  left: number;
  top: number;
  /** Where the connection was dropped, in flow coordinates. */
  flowX: number;
  flowY: number;
  from: ConnectFrom;
}

export function Canvas() {
  const t = useT();
  const flowNodes = useCanvas((s) => s.flowNodes);
  const project = useCanvas((s) => s.project);
  const onNodesChange = useCanvas((s) => s.onFlowNodesChange);
  const commitPositions = useCanvas((s) => s.commitPositions);
  const flowEdges = useCanvas((s) => s.flowEdges);
  const jobs = useCanvas((s) => s.jobs);
  const onEdgesChange = useCanvas((s) => s.onFlowEdgesChange);
  const canConnect = useCanvas((s) => s.canConnect);
  const connect = useCanvas((s) => s.connect);
  const deleteElements = useCanvas((s) => s.deleteElements);
  // Workflow nodes can't be deleted, so they don't count as a deletable selection.
  const selectedNodeIds = useCanvas(
    useShallow((s) =>
      s.flowNodes.filter((n) => n.selected && !s.nodes[n.id]?.workflow_step).map((n) => n.id),
    ),
  );
  const selectedEdgeIds = useCanvas(
    useShallow((s) => s.flowEdges.filter((e) => e.selected).map((e) => e.id)),
  );
  const saveViewport = useCanvas((s) => s.saveViewport);
  const addNode = useCanvas((s) => s.addNode);
  const addConnectedNode = useCanvas((s) => s.addConnectedNode);
  const placeMaterial = useCanvas((s) => s.placeMaterial);
  const uploadFiles = useCanvas((s) => s.uploadFiles);
  // Someone else is editing (see store/lock.ts): look, don't touch.
  const readOnly = useCanvas((s) => s.lock.status !== "editing");
  const [dropTarget, setDropTarget] = useState(false);

  // Drop an asset from the Assets panel, or files from the desktop, on
  // the canvas: each becomes an uploaded node where it lands.
  const onDragOver = (event: React.DragEvent) => {
    if (readOnly) return;
    const types = event.dataTransfer.types;
    if (!types.includes(MATERIAL_MIME) && !types.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setDropTarget(true);
  };
  const onDrop = async (event: React.DragEvent) => {
    setDropTarget(false);
    if (readOnly) return;
    const materialId = event.dataTransfer.getData(MATERIAL_MIME);
    const files = [...event.dataTransfer.files];
    if (!materialId && !files.length) return;
    event.preventDefault();
    const at = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
    // Centre the node's output square on the drop point.
    const origin = { x: at.x - NODE_WIDTH / 2, y: at.y - SQUARE_CENTRE };
    if (materialId) {
      await placeMaterial(materialId, origin);
      return;
    }
    const uploaded = await uploadFiles(files);
    for (const [i, material] of uploaded.entries()) {
      await placeMaterial(material.id, { x: origin.x + i * 40, y: origin.y + i * 40 });
    }
  };
  const flow = useReactFlow();
  const wrapper = useRef<HTMLDivElement>(null);
  const tool = useView((s) => s.tool);
  const setTool = useView((s) => s.setTool);
  // Holding Space with the select tool: dragging moves the view, as with the
  // hand tool (React Flow's own pan key still lets its selection take the
  // drag). Not while typing, or on a button reached by keyboard, where Space
  // does its own thing; a button merely clicked doesn't keep it.
  const [spaceHeld, setSpaceHeld] = useState(false);
  useEffect(() => {
    const ownSpace = (e: KeyboardEvent) =>
      e.target instanceof Element &&
      Boolean(
        e.target.closest("input, textarea, select, [contenteditable='true']") ||
          e.target.closest("button")?.matches(":focus-visible"),
      );
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || ownSpace(e)) return;
      e.preventDefault(); // not a page scroll or a button press
      setSpaceHeld(true);
    };
    const up = (e: KeyboardEvent) => e.code === "Space" && setSpaceHeld(false);
    const release = () => setSpaceHeld(false);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", release);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", release);
    };
  }, []);
  const dragSelects = tool === "select" && !spaceHeld;

  // Re-renders only when the zoom crosses FAR_ZOOM.
  const far = useStore((s) => s.transform[2] < FAR_ZOOM);
  // While the view moves, the browser scales what it has already drawn
  // instead of redrawing every node, link and picture each frame (a class
  // set directly: no re-render). It's drawn sharp again once the view has
  // been still for MOVE_SETTLE_MS (React Flow's own end comes mid-pinch).
  const settle = useRef<ReturnType<typeof setTimeout>>(undefined);
  const moved = () => {
    const box = wrapper.current;
    if (box && !box.classList.contains("canvas--moving")) box.classList.add("canvas--moving");
    clearTimeout(settle.current);
    settle.current = setTimeout(
      () => wrapper.current?.classList.remove("canvas--moving"),
      MOVE_SETTLE_MS,
    );
  };
  useEffect(() => () => clearTimeout(settle.current), []);
  const [menu, setMenu] = useState<CreateMenu | null>(null);

  // Drop a connection on empty canvas: ask what to create there.
  const onConnectEnd = useCallback(
    (event: globalThis.MouseEvent | TouchEvent, state: FinalConnectionState) => {
      // isValid is null when the drop was not over (or near) any handle.
      if (state.isValid !== null || !state.fromNode || !state.fromHandle) return;
      // Nothing can link out of a node without an ID.
      if (state.fromHandle.type === "source" && !useCanvas.getState().nodes[state.fromNode.id]?.name) {
        return;
      }
      const point = "changedTouches" in event ? event.changedTouches[0]! : event;
      const box = wrapper.current?.getBoundingClientRect();
      if (!box) return;
      const at = flow.screenToFlowPosition({ x: point.clientX, y: point.clientY });
      setMenu({
        // Kept inside the canvas (not under the step panel or off the bottom).
        left: Math.min(point.clientX - box.left, box.width - MENU_WIDTH - 16),
        top: Math.min(point.clientY - box.top, box.height - MENU_HEIGHT - 16),
        flowX: at.x,
        flowY: at.y,
        from: {
          nodeId: state.fromNode.id,
          handle: state.fromHandle.type,
        },
      });
    },
    [flow],
  );

  const createFromMenu = (shape: NodeShape) => {
    if (!menu) return;
    const { flowX, flowY, from } = menu;
    setMenu(null);
    // Put the new node's matching handle under the drop point.
    const at =
      from.handle === "source"
        ? { x: flowX, y: flowY - LINK_TOP }
        : { x: flowX - NODE_WIDTH, y: flowY - LINK_TOP };
    void addConnectedNode(shape, at, from);
  };

  // Keys, outside text boxes (where the browser's own handling applies):
  // V / H pick the select or hand tool; ⌘A / Ctrl+A selects every node and
  // Esc clears the selection. (Undo and redo: ProjectBar.)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target;
      if (el instanceof Element && el.closest("input, textarea, select, [contenteditable='true']"))
        return;
      const key = e.key.toLowerCase();
      const command = e.metaKey || e.ctrlKey;
      if (!command && !e.altKey && !e.shiftKey && (key === "v" || key === "h")) {
        useView.getState().setTool(key === "v" ? "select" : "hand");
        return;
      }
      if (key === "escape" || (command && !e.altKey && !e.shiftKey && key === "a")) {
        const select = key === "a";
        if (select) e.preventDefault();
        const { flowNodes, flowEdges, onFlowNodesChange, onFlowEdgesChange } =
          useCanvas.getState();
        onFlowNodesChange(flowNodes.map((n) => ({ id: n.id, type: "select", selected: select })));
        if (!select) {
          onFlowEdgesChange(flowEdges.map((ed) => ({ id: ed.id, type: "select", selected: false })));
        }
        return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!menu) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setMenu(null);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menu]);

  // Double-click empty canvas to add a node there.
  const onDoubleClick = useCallback(
    (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (readOnly || !target.classList.contains("react-flow__pane")) return;
      const position = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
      void addNode("image", { x: position.x - NODE_WIDTH / 2, y: position.y - HEADER / 2 });
    },
    [flow, addNode, readOnly],
  );

  // The node under the pointer, else the selected nodes: their links are
  // highlighted and the rest fade, so which link goes where is plain.
  const [hovered, setHovered] = useState<string | null>(null);
  const selectedIds = useCanvas(
    useShallow((s) => s.flowNodes.filter((n) => n.selected).map((n) => n.id)),
  );
  const focus = useMemo(
    () => new Set(hovered ? [hovered] : selectedIds),
    [hovered, selectedIds],
  );

  // Animate the references feeding a node while it generates. Hidden
  // links (the Canvas panel's switch) aren't drawn at all.
  const showLinks = useView((s) => s.showLinks);
  const edges = useMemo(
    () =>
      flowEdges.map((edge) => {
        const busy = isActive(jobs[edge.target]);
        const hidden = !showLinks;
        const base = (edge.className ?? "").replace(/\s*edge--active/g, "");
        const active = focus.has(edge.source) || focus.has(edge.target);
        const className = active ? `${base} edge--active`.trim() : base;
        return busy === Boolean(edge.animated) &&
          hidden === Boolean(edge.hidden) &&
          className === (edge.className ?? "")
          ? edge
          : { ...edge, animated: busy, hidden, className };
      }),
    [flowEdges, jobs, showLinks, focus],
  );

  return (
    <div
      className={`canvas${dropTarget ? " canvas--drop" : ""}${far ? " canvas--far" : ""}${focus.size ? " canvas--focus" : ""}`}
      ref={wrapper}
      onDragOver={onDragOver}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as globalThis.Node | null)) {
          setDropTarget(false);
        }
      }}
      onDrop={(e) => void onDrop(e)}
    >
      <Sidebar />
      <ReactFlow<GenFlowNode, RefFlowEdge>
        nodes={flowNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeMouseEnter={(_, node) => setHovered(node.id)}
        onNodeMouseLeave={() => setHovered(null)}
        onNodesChange={onNodesChange}
        onNodeDragStop={(_, __, nodes) => commitPositions(nodes.map((n) => n.id))}
        onEdgesChange={onEdgesChange}
        onConnect={(connection) => void connect(connection)}
        onConnectEnd={onConnectEnd}
        onPaneClick={() => setMenu(null)}
        onMoveStart={() => setMenu(null)}
        onMove={moved}
        isValidConnection={canConnect}
        // Every delete (Backspace, a node's button) comes through here: remove
        // the nodes, every connection touching them, and the selected
        // connections, as one undo step.
        onDelete={({ nodes, edges: removed }) =>
          void deleteElements(
            nodes.map((n) => n.id),
            removed.map((e) => e.id),
          )
        }
        onMoveEnd={(_, viewport) => {
          if (project) lastViews.set(project.id, viewport);
          saveViewport(viewport);
        }}
        onDoubleClick={onDoubleClick}
        defaultViewport={
          (project && lastViews.get(project.id)) ?? project?.viewport ?? { x: 0, y: 0, zoom: 1 }
        }
        zoomOnDoubleClick={false}
        // The hand tool: dragging on empty canvas moves the view (Shift-click
        // adds to the selection). The select tool: dragging selects; Space-drag,
        // or the middle or right button, moves the view. The wheel (and a
        // pinch) zooms, over nodes too (see the "nowheel" classes in src/node).
        panOnDrag={dragSelects ? [1, 2] : true}
        selectionOnDrag={dragSelects}
        panActivationKeyCode={null}
        panOnScroll={false}
        autoPanOnNodeDrag={false}
        autoPanOnConnect={false}
        selectionKeyCode={null}
        selectionMode={SelectionMode.Partial}
        multiSelectionKeyCode={["Meta", "Control", "Shift"]}
        deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        edgesReconnectable={!readOnly}
        minZoom={0.1}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.4} />
        <Controls showInteractive={false}>
          {TOOLS.map(({ id, label, path }) => (
            <ControlButton
              key={id}
              className={`canvas__tool${tool === id ? " is-active" : ""}`}
              onClick={() => setTool(id)}
              title={t(label)}
              aria-label={t(label)}
              aria-pressed={tool === id}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d={path} />
              </svg>
            </ControlButton>
          ))}
        </Controls>
        <MiniMap
          pannable
          zoomable
          className="canvas__map"
          ariaLabel={t("map_aria")}
        />
        {!readOnly && (selectedNodeIds.length > 0 || selectedEdgeIds.length > 0) && (
          <div className="selection-bar" role="status" aria-label={t("selection_aria")}>
            <span>{selectionLabel(selectedNodeIds.length, selectedEdgeIds.length, t)}</span>
          </div>
        )}
        {!readOnly && flowNodes.length > 0 && selectedNodeIds.length === 0 && selectedEdgeIds.length === 0 && (
          <div className="canvas__hint">
            {t(tool === "hand" ? "canvas_hint_hand" : "canvas_hint_select")}
          </div>
        )}
        {!readOnly && flowNodes.length === 0 && (
          <div className="canvas__empty">
            {t("canvas_empty")}
          </div>
        )}
      </ReactFlow>
      {menu && (
        <div
          className="create-menu"
          style={{ left: menu.left, top: menu.top }}
          role="menu"
          aria-label={t("create_menu_aria")}
        >
          <div className="create-menu__title">
            {menu.from.handle === "source" ? t("menu_from_output") : t("menu_feed_input")}
          </div>
          {MENU.map((choice, i) => (
            <div key={choice.shape} className="create-menu__row">
              <button role="menuitem" autoFocus={i === 0} onClick={() => createFromMenu(choice.shape)}>
                <span className="create-menu__icon" aria-hidden="true">
                  <svg viewBox="0 0 16 16">{MENU_ICONS[choice.shape]}</svg>
                </span>
                <span className="create-menu__label">{t(choice.label)}</span>
                <small>{choice.hint}</small>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function selectionLabel(nodes: number, edges: number, t: T): string {
  const parts = [];
  if (nodes) parts.push(t.n("count_node", nodes));
  if (edges) parts.push(t.n("count_connection", edges));
  return t("selected", { parts: parts.join(t("list_sep")) });
}
