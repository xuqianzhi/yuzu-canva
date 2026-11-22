import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  SelectionMode,
  useReactFlow,
  type FinalConnectionState,
  type NodeTypes,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { TERMINAL_JOB_STATUSES } from "../api/types";
import {
  useCanvas,
  type ConnectFrom,
  type GenFlowNode,
  type NodeShape,
  type RefFlowEdge,
} from "../store/canvas";
import { useShallow } from "zustand/react/shallow";
import { GenNode } from "./GenNode";
import { MATERIAL_MIME, Sidebar } from "./Sidebar";
import { useT, type Key, type T } from "../i18n";

const nodeTypes: NodeTypes = { gen: GenNode };

// Matches .gen-node (width) and .gen-node__handle (top) in styles.css, so a
// node created at a drop point lines its handle up with the cursor.
const NODE_WIDTH = 320;
const HANDLE_TOP = 120;

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
  const notice = useCanvas((s) => s.notice);
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
  const [dropTarget, setDropTarget] = useState(false);

  // Drop an asset from the Assets panel, or files from the desktop, on
  // the canvas: each becomes an uploaded node where it lands.
  const onDragOver = (event: React.DragEvent) => {
    const types = event.dataTransfer.types;
    if (!types.includes(MATERIAL_MIME) && !types.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setDropTarget(true);
  };
  const onDrop = async (event: React.DragEvent) => {
    setDropTarget(false);
    const materialId = event.dataTransfer.getData(MATERIAL_MIME);
    const files = [...event.dataTransfer.files];
    if (!materialId && !files.length) return;
    event.preventDefault();
    const at = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
    // Centre the node's card on the drop point.
    const origin = { x: at.x - NODE_WIDTH / 2, y: at.y - 100 };
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
        left: point.clientX - box.left,
        top: point.clientY - box.top,
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
    const x = from.handle === "source" ? flowX : flowX - NODE_WIDTH;
    void addConnectedNode(shape, { x, y: flowY - HANDLE_TOP }, from);
  };

  // ⌘Z / Ctrl+Z undo; ⌘⇧Z / Ctrl+Shift+Z / Ctrl+Y redo. Inside a text box
  // the browser's own text undo applies instead.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el?.closest("input, textarea, select, [contenteditable='true']")) return;
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
      const key = e.key.toLowerCase();
      if (key === "z") {
        e.preventDefault();
        void (e.shiftKey ? useCanvas.getState().redo() : useCanvas.getState().undo());
      } else if (key === "y" && e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        void useCanvas.getState().redo();
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
      if (!target.classList.contains("react-flow__pane")) return;
      const position = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
      void addNode("image", { x: position.x - 160, y: position.y - 24 });
    },
    [flow, addNode],
  );

  // Animate the references feeding a node while it generates.
  const edges = useMemo(
    () =>
      flowEdges.map((edge) => {
        const job = jobs[edge.target];
        const busy = job !== undefined && !TERMINAL_JOB_STATUSES.includes(job.status);
        return busy === Boolean(edge.animated) ? edge : { ...edge, animated: busy };
      }),
    [flowEdges, jobs],
  );

  return (
    <div
      className={`canvas${dropTarget ? " canvas--drop" : ""}`}
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
        onNodesChange={onNodesChange}
        onNodeDragStop={(_, __, nodes) => commitPositions(nodes.map((n) => n.id))}
        onEdgesChange={onEdgesChange}
        onConnect={(connection) => void connect(connection)}
        onConnectEnd={onConnectEnd}
        onPaneClick={() => setMenu(null)}
        onMoveStart={() => setMenu(null)}
        isValidConnection={canConnect}
        // Every delete (Backspace, a node's button, the selection bar) comes
        // through here: remove the nodes, every connection touching them, and
        // the selected connections, as one undo step.
        onDelete={({ nodes, edges: removed }) =>
          void deleteElements(
            nodes.map((n) => n.id),
            removed.map((e) => e.id),
          )
        }
        onMoveEnd={(_, viewport) => saveViewport(viewport)}
        onDoubleClick={onDoubleClick}
        defaultViewport={project?.viewport ?? { x: 0, y: 0, zoom: 1 }}
        zoomOnDoubleClick={false}
        // Dragging on empty canvas selects (nodes it touches, and the
        // connections between them). The view moves only through the map in
        // the bottom-right corner; the wheel and the +/- buttons still zoom.
        selectionOnDrag
        panOnDrag={false}
        panOnScroll={false}
        autoPanOnNodeDrag={false}
        autoPanOnConnect={false}
        selectionKeyCode={null}
        selectionMode={SelectionMode.Partial}
        multiSelectionKeyCode={["Meta", "Control", "Shift"]}
        deleteKeyCode={["Backspace", "Delete"]}
        minZoom={0.1}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1.2} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          className="canvas__map"
          ariaLabel={t("map_aria")}
        />
        {notice && (
          <div className={`canvas__notice canvas__notice--${notice.tone}`} role="status">
            {notice.text}
          </div>
        )}
        {(selectedNodeIds.length > 0 || selectedEdgeIds.length > 0) && (
          <div className="selection-bar" role="toolbar" aria-label={t("selection_aria")}>
            <span>{selectionLabel(selectedNodeIds.length, selectedEdgeIds.length, t)}</span>
            <button
              className="button button--danger button--small"
              onClick={() =>
                void flow.deleteElements({
                  nodes: selectedNodeIds.map((id) => ({ id })),
                  edges: selectedEdgeIds.map((id) => ({ id })),
                })
              }
            >
              {t("delete")}
            </button>
          </div>
        )}
        {flowNodes.length > 0 && selectedNodeIds.length === 0 && selectedEdgeIds.length === 0 && (
          <div className="canvas__hint">
            {t("canvas_hint")}
          </div>
        )}
        {flowNodes.length === 0 && (
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
                <span>{t(choice.label)}</span>
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
