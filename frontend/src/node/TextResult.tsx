// A text node's result, typed straight into: click the text (or the empty
// box) and write; clicking away saves it as a new version, so the one it came
// from stays. Esc puts it back. Shared by every view.
import { useRef, useState, type MouseEvent } from "react";
import { useT } from "../i18n";
import { useCanvas } from "../store/canvas";

export function TextResult({
  nodeId,
  text,
  busy,
  scrollable,
}: {
  nodeId: string;
  /** The chosen version's text ("": none yet). */
  text: string;
  /** Generating: nothing to type into until it's done. */
  busy: boolean;
  scrollable: boolean;
}) {
  const t = useT();
  const addTake = useCanvas((s) => s.addTake);
  const showNotice = useCanvas((s) => s.showNotice);
  const readOnly = useCanvas((s) => s.lock.status !== "editing");
  // What's being typed (null: not editing).
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState("");
  // Esc leaves without saving; the blur it causes mustn't save either.
  const cancelled = useRef(false);
  const saving = useRef(false);
  const editable = !readOnly && !busy;

  const start = () => {
    cancelled.current = false;
    setError("");
    setDraft(text);
  };

  // A click edits; Shift/⌘-click stays the canvas's "add to the selection"
  // (and a drag moves the node: it ends in no click).
  const onClick = (e: MouseEvent) => {
    if (editable && !e.shiftKey && !e.metaKey && !e.ctrlKey) start();
  };

  const save = async () => {
    // Not again while a save is on its way (a refocus and blur).
    if (draft === null || cancelled.current || saving.current) return;
    // Nothing new, or emptied: leave the version as it was.
    if (!draft.trim() || draft.trim() === text.trim()) return setDraft(null);
    saving.current = true;
    const problem = await addTake(nodeId, draft);
    saving.current = false;
    if (!problem) return setDraft(null);
    setError(problem);
    // This box is gone if another version was picked meanwhile.
    showNotice(problem);
  };

  if (draft !== null) {
    return (
      <>
        <textarea
          className="gen-node__text gen-node__editor nodrag nowheel"
          autoFocus
          // The cursor starts after what's there.
          onFocus={(e) => e.currentTarget.setSelectionRange(text.length, text.length)}
          maxLength={100_000}
          value={draft}
          aria-label={t("text_edit_aria")}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void save()}
          onKeyDown={(e) => {
            // Esc while composing (Chinese input) is the input method's own.
            if (e.nativeEvent.isComposing) return;
            if (e.key === "Escape") {
              cancelled.current = true;
              setDraft(null);
            } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.currentTarget.blur();
            }
          }}
        />
        {error && (
          <p className="gen-node__editor-error" role="alert">
            {error}
          </p>
        )}
      </>
    );
  }

  const props = editable
    ? {
        role: "button",
        tabIndex: 0,
        title: t("text_edit_title"),
        onClick,
        onKeyDown: (e: { key: string; preventDefault(): void }) => {
          if (e.key !== "Enter") return;
          e.preventDefault();
          start();
        },
      }
    : {};

  if (!text) {
    return (
      <div className={`gen-node__placeholder${editable ? " is-editable" : ""}`} {...props}>
        {!busy && <span>{t(editable ? "text_empty" : "no_output")}</span>}
      </div>
    );
  }
  return (
    <p
      className={`gen-node__text${editable ? " is-editable" : ""}${scrollable ? " nowheel" : ""}`}
      {...props}
    >
      {text}
    </p>
  );
}
