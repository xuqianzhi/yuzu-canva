// The menu bar down the left of a project, in both views: a rail of buttons,
// each opening a panel over the page's edge. What needs a canvas (showing
// links, dragging an asset in) is offered only there.
import { useReactFlow } from "@xyflow/react";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { api, unwrap } from "../api/client";
import { useShallow } from "zustand/react/shallow";
import type { CollectionAsset, Material } from "../api/types";
import { useView } from "../store/view";
import { useCanvas } from "../store/canvas";
import { useShownView } from "../projectView";
import { useStepViews } from "../workflow/StepRun";
import { NodeNameInput } from "./NodeName";
import { MediaThumb } from "../node/MediaThumb";
import { AboutVideo } from "../project/Instruction";
import { errorText, useT, type Key } from "../i18n";

/** dataTransfer type for dragging a material onto the canvas. */
export const MATERIAL_MIME = "application/x-seedance-material";

const ACCEPT = "image/png,image/jpeg,image/webp,video/mp4,video/quicktime";

// "Assets" in the UI; the project API calls them materials.
type Panel = "assets" | "nodes" | "instruction";

export function Sidebar() {
  const t = useT();
  const [open, setOpen] = useState<Panel | null>(null);
  const toggle = (panel: Panel) => setOpen((current) => (current === panel ? null : panel));
  const basic = useShownView() === "basic";
  const readOnly = useCanvas((s) => s.lock.status !== "editing");
  // On the canvas, the nodes' panel also holds what's shown on it.
  const labels: Record<Panel, Key> = {
    assets: "nav_assets",
    nodes: basic ? "nav_nodes" : "nav_canvas",
    instruction: "nav_instruction",
  };

  return (
    <div className="sidebar">
      <nav className="sidebar__rail" aria-label={t("project_menu")}>
        <RailButton
          label={t("nav_assets")}
          active={open === "assets"}
          onClick={() => toggle("assets")}
          icon={
            <>
              <rect x="3" y="4" width="14" height="12" rx="2" />
              <circle cx="7.5" cy="8.5" r="1.4" />
              <path d="m3.5 14 4-4 3 3 2-2 4 4" />
            </>
          }
        />
        <RailButton
          label={t(labels.nodes)}
          active={open === "nodes"}
          onClick={() => toggle("nodes")}
          icon={
            <>
              <rect x="3" y="3.5" width="5" height="4" rx="1" />
              <rect x="3" y="12.5" width="5" height="4" rx="1" />
              <path d="M10.5 5.5H17M10.5 14.5H17" />
            </>
          }
        />
        <RailButton
          label={t("nav_instruction")}
          active={open === "instruction"}
          onClick={() => toggle("instruction")}
          icon={
            <>
              <path d="M5 2.5h7l3 3v12H5z" />
              <path d="M12 2.5v3h3M7.5 9.5h5M7.5 12.5h5M7.5 15h3" />
            </>
          }
        />
      </nav>
      {open && (
        <aside className="sidebar__panel" aria-label={t(labels[open])}>
          <fieldset className="readonly-fence" disabled={readOnly}>
            {open === "assets" && <MaterialsPanel basic={basic} />}
            {open === "nodes" && (basic ? <BasicNodesPanel /> : <CanvasPanel />)}
            {open === "instruction" && <InstructionPanel />}
          </fieldset>
        </aside>
      )}
    </div>
  );
}

function RailButton(props: {
  label: string;
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
}) {
  return (
    <button
      className={`rail-button${props.active ? " is-active" : ""}`}
      onClick={props.onClick}
      aria-pressed={props.active}
      title={props.label}
    >
      <svg viewBox="0 0 20 20" aria-hidden="true">
        {props.icon}
      </svg>
      <span>{props.label}</span>
    </button>
  );
}

// --- Assets (the project's materials) ----------------------------------------------

function MaterialsPanel({ basic }: { basic: boolean }) {
  const t = useT();
  const materials = useCanvas((s) => s.materials);
  const uploading = useCanvas((s) => s.uploading);
  const uploadFiles = useCanvas((s) => s.uploadFiles);
  const input = useRef<HTMLInputElement>(null);
  const [dropping, setDropping] = useState(false);
  // The panel's fence doesn't stop drops, so they're refused here.
  const readOnly = useCanvas((s) => s.lock.status !== "editing");

  const onDrop = (event: DragEvent) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    setDropping(false);
    if (!readOnly) void uploadFiles([...event.dataTransfer.files]);
  };

  return (
    <div
      className={`panel${dropping ? " panel--dropping" : ""}`}
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes("Files")) return;
        // Taken even when refused: else the browser would open the file.
        e.preventDefault();
        e.dataTransfer.dropEffect = readOnly ? "none" : "copy";
        setDropping(!readOnly);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as globalThis.Node | null)) {
          setDropping(false);
        }
      }}
      onDrop={onDrop}
    >
      <header className="panel__head">
        <h2>{t("nav_assets")}</h2>
        <button className="button button--primary button--small" onClick={() => input.current?.click()}>
          {t("upload")}
        </button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            void uploadFiles([...(e.target.files ?? [])]);
            e.target.value = "";
          }}
        />
      </header>
      <p className="panel__help">{t(basic ? "assets_help_basic" : "assets_help")}</p>
      {uploading > 0 && (
        <p className="panel__status">
          <span className="spinner" /> {t.n("uploading_files", uploading)}
        </p>
      )}
      {materials.length === 0 && uploading === 0 ? (
        <button className="panel__empty" onClick={() => input.current?.click()}>
          {t("assets_empty")}
        </button>
      ) : (
        <ul className="material-grid">
          {materials.map((m) => (
            <MaterialItem key={m.id} material={m} draggable={!basic} />
          ))}
        </ul>
      )}
      <CollectionAssetList />
      {dropping && <div className="panel__drop">{t("drop_to_upload")}</div>}
    </div>
  );
}

/** The collection's assets, to look at only: they're managed on the
    collection's Assets page. Fetched each time the panel opens. */
function CollectionAssetList() {
  const t = useT();
  const collectionId = useCanvas((s) => s.project?.collection_id);
  const [assets, setAssets] = useState<CollectionAsset[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!collectionId) return;
    let stale = false;
    void (async () => {
      try {
        const listed = unwrap(
          await api.GET("/api/collections/{collection_id}/assets", {
            params: { path: { collection_id: collectionId } },
          }),
        );
        if (!stale) setAssets(listed);
      } catch (e) {
        if (!stale) setError(t("ga_load_error", { error: errorText(e) }));
      }
    })();
    return () => {
      stale = true;
    };
  }, [collectionId, t]);

  if (error) return <p className="panel__status">{error}</p>;
  if (!assets.length) return null;
  return (
    <section className="panel__section" aria-label={t("collection_assets_title")}>
      <h3 className="panel__label">{t("collection_assets_title")}</h3>
      <p className="panel__help">{t("collection_assets_help")}</p>
      <ul className="material-grid">
        {assets.map((a) => (
          <li key={a.id} className="material material--view" title={a.name}>
            <div className="material__thumb">
              <MediaThumb kind={a.kind} url={a.url} />
              {a.kind === "video" && <span className="material__badge">▶</span>}
            </div>
            <span className="material__name">{a.name}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function MaterialItem({ material, draggable }: { material: Material; draggable: boolean }) {
  const t = useT();
  const deleteMaterial = useCanvas((s) => s.deleteMaterial);
  const { asset } = material;
  const details =
    asset.kind === "video" && asset.duration_s
      ? t("seconds", { n: Math.round(asset.duration_s) })
      : asset.width && asset.height
        ? `${asset.width}×${asset.height}`
        : "";

  return (
    <li
      className={`material${draggable ? "" : " material--view"}`}
      draggable={draggable}
      onDragStart={(e) => {
        e.dataTransfer.setData(MATERIAL_MIME, material.id);
        e.dataTransfer.effectAllowed = "copy";
      }}
      title={draggable ? t("material_title", { name: material.name }) : material.name}
    >
      <div className="material__thumb">
        <MediaThumb kind={asset.kind} url={asset.url} />
        {asset.kind === "video" && <span className="material__badge">▶ {details}</span>}
      </div>
      <span className="material__name">{material.name}</span>
      {asset.kind === "image" && <span className="material__meta">{details}</span>}
      <button
        className="material__delete"
        onClick={() => void deleteMaterial(material.id)}
        aria-label={t("material_remove_aria", { name: material.name })}
        title={t("material_remove_title")}
      >
        ×
      </button>
    </li>
  );
}

// --- The nodes (on the canvas, also what's shown on it) ---------------------------

/** The "Nodes" heading and its list: a row for every node, in the canvas's
    order. */
function NodeList({
  sub = false,
  help,
  empty,
  row,
}: {
  /** Under the panel's own heading. */
  sub?: boolean;
  help: string;
  empty: string;
  row: (id: string) => React.ReactNode;
}) {
  const t = useT();
  const ids = useCanvas(useShallow((s) => s.flowNodes.map((n) => n.id)));
  const Heading = sub ? "h3" : "h2";
  return (
    <>
      <header className={`panel__head${sub ? " panel__head--sub" : ""}`}>
        <Heading>{t("nav_nodes")}</Heading>
        <span className="panel__count">{ids.length}</span>
      </header>
      <p className="panel__help">{help}</p>
      {ids.length === 0 ? (
        <p className="panel__help">{empty}</p>
      ) : (
        <ul className="node-list">{ids.map(row)}</ul>
      )}
    </>
  );
}

function CanvasPanel() {
  const t = useT();
  const links = useCanvas((s) => s.flowEdges.length);
  const showLinks = useView((s) => s.showLinks);
  const setShowLinks = useView((s) => s.setShowLinks);
  return (
    <div className="panel">
      <header className="panel__head">
        <h2>{t("nav_canvas")}</h2>
      </header>
      <label className="panel__switch">
        <input
          type="checkbox"
          role="switch"
          checked={showLinks}
          onChange={(e) => setShowLinks(e.target.checked)}
        />
        <span>{t("show_links")}</span>
        <span className="panel__count">{links}</span>
      </label>
      <p className="panel__help">{t("show_links_help")}</p>
      <NodeList
        sub
        help={t("nodes_help")}
        empty={t("nodes_empty")}
        row={(id) => <CanvasNodeRow key={id} nodeId={id} />}
      />
    </div>
  );
}

function CanvasNodeRow({ nodeId }: { nodeId: string }) {
  const node = useCanvas((s) => s.nodes[nodeId]);
  const selected = useCanvas((s) => s.flowNodes.find((n) => n.id === nodeId)?.selected ?? false);
  const flow = useReactFlow();
  if (!node) return null;

  const focus = () => {
    // Select just this node and bring it to the middle of the view.
    useCanvas.setState((s) => ({
      flowNodes: s.flowNodes.map((n) => ({ ...n, selected: n.id === nodeId })),
      flowEdges: s.flowEdges.map((e) => ({ ...e, selected: false })),
    }));
    void flow.setCenter(node.position.x + 160, node.position.y + 200, {
      zoom: flow.getZoom(),
      duration: 300,
    });
  };

  return <NodeRow nodeId={nodeId} selected={selected} onClick={focus} />;
}

/** The nodes in the basic view: a row goes to its node's card. A node
    outside the workflow has none (it shows only on the canvas). */
function BasicNodesPanel() {
  const t = useT();
  const views = useStepViews();
  const activeNodeId = useCanvas((s) => s.activeNodeId);
  const jumpToNode = useCanvas((s) => s.jumpToNode);
  const stepOf = new Map(views.flatMap((v) => v.nodes.map((n) => [n.id, v.step.key] as const)));
  return (
    <div className="panel">
      <NodeList
        help={t("nodes_help_basic")}
        empty={t("nodes_empty_basic")}
        row={(id) => {
          const step = stepOf.get(id);
          return (
            <NodeRow
              key={id}
              nodeId={id}
              selected={activeNodeId === id}
              onClick={step ? () => jumpToNode(step, id) : undefined}
            />
          );
        }}
      />
    </div>
  );
}

/** One node: its kind and its ID (editable). Without `onClick` there is
    nowhere to go. */
function NodeRow({
  nodeId,
  selected,
  onClick,
}: {
  nodeId: string;
  selected: boolean;
  onClick: (() => void) | undefined;
}) {
  const t = useT();
  const node = useCanvas((s) => s.nodes[nodeId]);
  if (!node) return null;
  const kind =
    node.source === "upload"
      ? t("kind_uploaded", { kind: t(`kind_${node.kind}`) })
      : t(`kind_${node.kind}`);
  return (
    <li
      className={`node-row${selected ? " is-selected" : ""}${onClick ? "" : " node-row--elsewhere"}`}
      onClick={onClick}
      title={onClick ? undefined : t("node_only_on_canvas")}
    >
      <span className={`node-row__kind node-row__kind--${node.kind}`}>{kind}</span>
      <NodeNameInput nodeId={nodeId} className="node-row__name" />
    </li>
  );
}

/** The project's description, under its collection's instruction. */
function InstructionPanel() {
  const t = useT();
  return (
    <div className="panel panel--fill">
      <header className="panel__head">
        <h2>{t("nav_instruction")}</h2>
      </header>
      <AboutVideo className="panel__instruction" />
    </div>
  );
}
