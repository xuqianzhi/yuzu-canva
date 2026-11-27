// What the AI is told about a project beyond each step: its collection's
// instruction (shared by the series, read-only here) and the project's own
// description. Shared by the canvas's Instruction panel and the basic view.
import { useState } from "react";
import { useT } from "../i18n";
import { collectionHref } from "../router";
import { useCanvas } from "../store/canvas";

/** The collection's instruction: folded, shown on hover, or pinned open
    with a click. */
export function SharedInstruction() {
  const t = useT();
  const shared = useCanvas((s) => s.project?.collection_instruction ?? "");
  const collectionId = useCanvas((s) => s.project?.collection_id ?? "");
  const [pinned, setPinned] = useState(false);
  return (
    <div className={`shared-instruction${pinned ? " is-open" : ""}`}>
      <button
        className="shared-instruction__head"
        aria-expanded={pinned}
        onClick={() => setPinned((p) => !p)}
        title={t("shared_instruction_toggle")}
      >
        <span>{t("shared_instruction_title")}</span>
        <small>{shared.trim() ? t("shared_instruction_view_only") : t("shared_instruction_none")}</small>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4 6l4 4 4-4" />
        </svg>
      </button>
      <div className="shared-instruction__body">
        {shared.trim() ? <p>{shared}</p> : null}
        <a href={collectionHref(collectionId, "instruction")}>{t("shared_instruction_edit")}</a>
      </div>
    </div>
  );
}

/** "Describe this video": the project's description, saved as it's typed. */
export function ProjectDescription({ className = "" }: { className?: string }) {
  const t = useT();
  const description = useCanvas((s) => s.project?.description ?? "");
  const setDescription = useCanvas((s) => s.setProjectDescription);
  return (
    <>
      <label className="panel__label" htmlFor="project-description">
        {t("project_description_title")}
      </label>
      <textarea
        id="project-description"
        className={`instruction-input ${className}`}
        aria-label={t("project_description_title")}
        placeholder={t("project_description_placeholder")}
        maxLength={20000}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
    </>
  );
}
