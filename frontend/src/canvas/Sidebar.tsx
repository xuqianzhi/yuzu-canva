// The menu bar on the left of the canvas: a rail of buttons, each opening a
// panel over the canvas edge.
import { useReactFlow } from "@xyflow/react";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { api, unwrap } from "../api/client";
import { useShallow } from "zustand/react/shallow";
import type { CollectionAsset, Material } from "../api/types";
import { useView } from "../store/view";
import { useCanvas } from "../store/canvas";
import { NodeNameInput } from "./NodeName";
import { MediaThumb } from "../node/MediaThumb";
import { ProjectDescription, SharedInstruction } from "../project/Instruction";
import { errorText, useT, type Key } from "../i18n";

/** dataTransfer type for dragging a material onto the canvas. */
export const MATERIAL_MIME = "application/x-seedance-material";

const ACCEPT = "image/png,image/jpeg,image/webp,video/mp4,video/quicktime";

// "Assets" in the UI; the project API calls them materials.
type Panel = "assets" | "canvas" | "instruction";

const PANEL_LABELS: Record<Panel, Key> = {
  assets: "nav_assets",
  canvas: "nav_canvas",
  instruction: "nav_instruction",
};

export function Sidebar() {
  const t = useT();
  const [open, setOpen] = useState<Panel | null>(null);
  const toggle = (panel: Panel) => setOpen((current) => (current === panel ? null : panel));

  return (
    // Drags over the menu never reach the canvas behind it: a file dropped
    // on the Assets panel is uploaded once, and an asset dropped back on
    // the menu does not land on the canvas underneath.
    <div
      className="sidebar"
      onDragOver={(e) => e.stopPropagation()}
      onDragLeave={(e) => e.stopPropagation()}
      onDrop={(e) => e.stopPropagation()}
    >
      <nav className="sidebar__rail" aria-label={t("canvas_menu")}>
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
          label={t("nav_canvas")}
          active={open === "canvas"}
          onClick={() => toggle("canvas")}
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
        <aside className="sidebar__panel" aria-label={t(PANEL_LABELS[open])}>
          {open === "assets" && <MaterialsPanel />}
          {open === "canvas" && <CanvasPanel />}
          {open === "instruction" && <InstructionPanel />}
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

function MaterialsPanel() {
  const t = useT();
  const materials = useCanvas((s) => s.materials);
  const uploading = useCanvas((s) => s.uploading);
  const uploadFiles = useCanvas((s) => s.uploadFiles);
  const input = useRef<HTMLInputElement>(null);
  const [dropping, setDropping] = useState(false);

  const onDrop = (event: DragEvent) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    setDropping(false);
    void uploadFiles([...event.dataTransfer.files]);
  };

  return (
    <div
      className={`panel${dropping ? " panel--dropping" : ""}`}
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        setDropping(true);
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
      <p className="panel__help">{t("assets_help")}</p>
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
            <MaterialItem key={m.id} material={m} />
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

function MaterialItem({ material }: { material: Material }) {
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
      className="material"
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(MATERIAL_MIME, material.id);
        e.dataTransfer.effectAllowed = "copy";
      }}
      title={t("material_title", { name: material.name })}
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

// --- Canvas: what's shown, and the nodes ------------------------------------------

function CanvasPanel() {
  const t = useT();
  const ids = useCanvas(useShallow((s) => s.flowNodes.map((n) => n.id)));
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
      <header className="panel__head panel__head--sub">
        <h3>{t("nav_nodes")}</h3>
        <span className="panel__count">{ids.length}</span>
      </header>
      <p className="panel__help">{t("nodes_help")}</p>
      {ids.length === 0 ? (
        <p className="panel__help">{t("nodes_empty")}</p>
      ) : (
        <ul className="node-list">
          {ids.map((id) => (
            <NodeRow key={id} nodeId={id} />
          ))}
        </ul>
      )}
    </div>
  );
}

function NodeRow({ nodeId }: { nodeId: string }) {
  const t = useT();
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

  const kind =
    node.source === "upload"
      ? t("kind_uploaded", { kind: t(`kind_${node.kind}`) })
      : t(`kind_${node.kind}`);
  return (
    <li className={`node-row${selected ? " is-selected" : ""}`} onClick={focus}>
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
      <p className="panel__help">{t("instruction_both_help")}</p>
      <SharedInstruction />
      <ProjectDescription className="panel__instruction" />
    </div>
  );
}
