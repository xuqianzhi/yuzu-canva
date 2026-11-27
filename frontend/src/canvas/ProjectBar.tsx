import { useEffect, useState } from "react";
import { collectionHref, homeHref } from "../router";
import { UNDO_KEY, useCanvas } from "../store/canvas";
import { useHasSteps, useShownView } from "../projectView";
import { useView, type ProjectView } from "../store/view";
import { useT } from "../i18n";

const REDO_KEY = UNDO_KEY === "⌘Z" ? "⌘⇧Z" : "Ctrl+Y";

/** Top of a project: back to the list, the (editable) name, the view (basic
    or canvas), and the save state. */
export function ProjectBar() {
  const t = useT();
  const project = useCanvas((s) => s.project);
  const pendingSaves = useCanvas((s) => s.pendingSaves);
  const renameProject = useCanvas((s) => s.renameProject);
  const canUndo = useCanvas((s) => s.canUndo);
  const canRedo = useCanvas((s) => s.canRedo);
  const undo = useCanvas((s) => s.undo);
  const redo = useCanvas((s) => s.redo);
  const readOnly = useCanvas((s) => s.lock.status !== "editing");
  const cleanUp = useCanvas((s) => s.cleanUp);
  const showNotice = useCanvas((s) => s.showNotice);
  const hasNodes = useCanvas((s) => s.flowNodes.length > 0);
  const [tidying, setTidying] = useState(false);
  const shown = useShownView();
  const hasSteps = useHasSteps();
  useUndoKeys();
  const tidy = async () => {
    setTidying(true);
    const moved = await cleanUp();
    setTidying(false);
    // null: it failed, and the error is already shown.
    if (moved !== null) {
      showNotice(moved ? t("clean_up_done", { n: moved }) : t("clean_up_tidy"), "info");
    }
  };
  const [name, setName] = useState(project?.name ?? "");

  const projectId = project?.id;
  const projectName = project?.name;

  // Follow the project when it loads or changes (but not while typing).
  useEffect(() => setName(useCanvas.getState().project?.name ?? ""), [projectId]);
  useEffect(() => {
    document.title = projectName ? `${projectName} · Yuzu Canva` : "Yuzu Canva";
  }, [projectName]);

  return (
    <header className="topbar">
      <a
        className="button button--ghost"
        href={project ? collectionHref(project.collection_id) : homeHref}
      >
        {t("back")}
      </a>
      {project && (
        <input
          className="topbar__name"
          value={readOnly ? project.name : name}
          readOnly={readOnly}
          maxLength={200}
          aria-label={t("project_name")}
          spellCheck={false}
          onChange={(e) => {
            setName(e.target.value);
            renameProject(e.target.value);
          }}
          onBlur={() => setName(project.name)} // never leave it blank
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === "Escape") e.currentTarget.blur();
          }}
        />
      )}
      <span className="topbar__spacer" />
      {hasSteps && <ViewSwitch />}
      {shown === "canvas" && (
        <button
          className="button button--small topbar__clean"
          onClick={() => void tidy()}
          disabled={readOnly || !hasNodes || tidying}
          title={t("clean_up_title")}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <rect x="2.5" y="2.5" width="4" height="4" rx="0.8" />
            <rect x="9.5" y="2.5" width="4" height="4" rx="0.8" />
            <rect x="2.5" y="9.5" width="4" height="4" rx="0.8" />
            <rect x="9.5" y="9.5" width="4" height="4" rx="0.8" />
          </svg>
          {t("clean_up")}
        </button>
      )}
      <div className="topbar__history">
        <button
          className="icon-button icon-button--plain"
          onClick={() => void undo()}
          disabled={!canUndo || readOnly}
          title={t("undo_title", { key: UNDO_KEY })}
          aria-label={t("undo")}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M6 4 3 7l3 3M3.5 7H10a3 3 0 0 1 0 6H8" />
          </svg>
        </button>
        <button
          className="icon-button icon-button--plain"
          onClick={() => void redo()}
          disabled={!canRedo || readOnly}
          title={t("redo_title", { key: REDO_KEY })}
          aria-label={t("redo")}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="m10 4 3 3-3 3M12.5 7H6a3 3 0 0 0 0 6h2" />
          </svg>
        </button>
      </div>
      <span className="topbar__save">
        {readOnly ? t("view_only") : pendingSaves > 0 ? t("saving") : t("saved")}
      </span>
    </header>
  );
}

const VIEWS: {
  view: ProjectView;
  label: "view_basic" | "view_canvas";
  title: "view_basic_title" | "view_canvas_title";
}[] = [
  { view: "basic", label: "view_basic", title: "view_basic_title" },
  { view: "canvas", label: "view_canvas", title: "view_canvas_title" },
];

/** ⌘Z / Ctrl+Z undo, ⌘⇧Z / Ctrl+Shift+Z / Ctrl+Y redo, in either view;
    inside text boxes the browser's own handling applies. */
function useUndoKeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target;
      if (el instanceof Element && el.closest("input, textarea, select, [contenteditable='true']"))
        return;
      const { lock, undo, redo } = useCanvas.getState();
      const command = e.metaKey || e.ctrlKey;
      if (lock.status !== "editing" || !command || e.altKey) return;
      const key = e.key.toLowerCase();
      if (key === "z") {
        e.preventDefault();
        void (e.shiftKey ? redo() : undo());
      } else if (key === "y" && e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        void redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** Basic | Canvas: how this project is shown (the same project either way). */
function ViewSwitch() {
  const t = useT();
  const projectView = useView((s) => s.projectView);
  const setProjectView = useView((s) => s.setProjectView);
  return (
    <div className="segmented topbar__views" role="group" aria-label={t("view_aria")}>
      {VIEWS.map(({ view, label, title }) => (
        <button
          key={view}
          className={projectView === view ? "is-active" : ""}
          aria-pressed={projectView === view}
          title={t(title)}
          onClick={() => setProjectView(view)}
        >
          {t(label)}
        </button>
      ))}
    </div>
  );
}
