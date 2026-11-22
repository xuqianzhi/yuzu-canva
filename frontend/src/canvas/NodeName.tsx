// A node's optional, unique ID: shown above the node on the canvas, and in
// the Nodes panel. Other nodes use it as "@ID". Click to edit; Enter or
// leaving the field saves, Escape cancels. A taken or invalid ID is refused
// with a message and the edit stays open.
import { useEffect, useRef, useState } from "react";
import { useCanvas } from "../store/canvas";
import { useT } from "../i18n";

export function NodeNameInput({
  nodeId,
  className = "",
  placeholder,
}: {
  nodeId: string;
  className?: string;
  placeholder?: string;
}) {
  const t = useT();
  const name = useCanvas((s) => s.nodes[nodeId]?.name ?? "");
  const setName = useCanvas((s) => s.setName);
  const [draft, setDraft] = useState(name);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const saving = useRef(false);

  // Follow outside changes (undo, the other place it is shown) when idle.
  useEffect(() => {
    if (!editing) setDraft(name);
  }, [name, editing]);

  const errorTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(errorTimer.current), []);

  /** Save the draft; true if it was accepted (or unchanged). */
  const save = async (): Promise<boolean> => {
    if (saving.current) return false;
    saving.current = true;
    const problem = await setName(nodeId, draft);
    saving.current = false;
    clearTimeout(errorTimer.current);
    setError(problem);
    return problem === null;
  };

  const leave = async () => {
    const ok = await save();
    if (!ok) {
      // Keep the old name; leave the reason up for a moment.
      setDraft(name);
      errorTimer.current = setTimeout(() => setError(null), 3500);
    }
    setEditing(false);
  };

  const cancel = () => {
    setDraft(name);
    setError(null);
    input.current?.blur();
  };

  return (
    <span className={`node-name nodrag ${className}`} onClick={(e) => e.stopPropagation()}>
      <input
        ref={input}
        value={draft}
        placeholder={placeholder ?? t("add_id")}
        maxLength={80}
        spellCheck={false}
        aria-label={t("node_id_aria")}
        aria-invalid={error ? true : undefined}
        className={error ? "is-invalid" : ""}
        onFocus={() => {
          clearTimeout(errorTimer.current);
          setEditing(true);
        }}
        onChange={(e) => {
          setDraft(e.target.value);
          setError(null);
        }}
        onBlur={() => void leave()}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            // Accepted: done editing. Refused: stay, with the reason shown.
            void save().then((ok) => ok && input.current?.blur());
          } else if (e.key === "Escape") {
            e.preventDefault();
            cancel();
          }
        }}
      />
      {error && (
        <span className="node-name__error" role="alert">
          {error}
        </span>
      )}
    </span>
  );
}
