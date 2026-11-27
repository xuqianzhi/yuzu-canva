// What the AI is told about a project beyond each step: its collection's
// instruction (shared by the series, read-only here) and the project's own
// description. Shown by the menu's Instruction panel and by the workflow's
// step 0.
import { useId, useState } from "react";
import { useT } from "../i18n";
import { collectionHref } from "../router";
import { useCanvas } from "../store/canvas";

/** The collection's instruction: folded, shown on hover, or pinned open
    with a click. */
function SharedInstruction() {
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
function ProjectDescription({ className }: { className: string }) {
  // The menu's panel and step 0 can both be showing it.
  const id = useId();
  const t = useT();
  const description = useCanvas((s) => s.project?.description ?? "");
  const setDescription = useCanvas((s) => s.setProjectDescription);
  return (
    <>
      <label className="panel__label" htmlFor={id}>
        {t("project_description_title")}
      </label>
      <textarea
        id={id}
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

/** Both, with what they're for. The description is the project's one, so
    what's typed in one place shows in every other. */
export function AboutVideo({ className }: { className: string }) {
  const t = useT();
  const readOnly = useCanvas((s) => s.lock.status !== "editing");
  return (
    <>
      <p className="panel__help">{t("instruction_both_help")}</p>
      <SharedInstruction />
      <fieldset className="readonly-fence" disabled={readOnly}>
        <ProjectDescription className={className} />
      </fieldset>
    </>
  );
}
