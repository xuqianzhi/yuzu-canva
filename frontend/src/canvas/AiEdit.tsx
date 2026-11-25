// "Edit with AI" on one node: say what to change ("a dog, not a cat") and
// the AI rewrites the prompt with only that changed. The suggestion shows
// first (the changed words marked); Apply saves it like typing would (so
// Undo takes it back). Nothing is generated. A workflow text node has no
// prompt: its result is edited instead, and applied as a new take.
import { useState, type KeyboardEvent } from "react";
import type { AiEdit } from "../api/types";
import { useT } from "../i18n";
import { useCanvas } from "../store/canvas";

export function AiEditButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  const t = useT();
  return (
    <button
      className={`round-button round-button--ghost${open ? " is-active" : ""}`}
      onClick={onClick}
      title={t("ai_edit_title")}
      aria-label={t("ai_edit_title")}
      aria-expanded={open}
    >
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M6.5 2.5 7.6 5.4 10.5 6.5 7.6 7.6 6.5 10.5 5.4 7.6 2.5 6.5 5.4 5.4ZM11.5 9.5l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6Z" />
      </svg>
    </button>
  );
}

export function AiEditBox({ nodeId, onClose }: { nodeId: string; onClose: () => void }) {
  const t = useT();
  const node = useCanvas((s) => s.nodes[nodeId]);
  const aiEdit = useCanvas((s) => s.aiEdit);
  const setPrompt = useCanvas((s) => s.setPrompt);
  const setParams = useCanvas((s) => s.setParams);
  const addTake = useCanvas((s) => s.addTake);
  const current = useCanvas((s) => {
    const id = s.nodes[nodeId]?.selected_output_id;
    return id ? (s.outputs[id]?.text ?? "") : "";
  });
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<AiEdit | null>(null);
  if (!node) return null;
  const params = node.params;
  const before = result?.target === "text" ? current : node.prompt;
  const lengthChange =
    result?.seconds != null && params.kind === "video" && result.seconds !== params.duration_s
      ? { from: params.duration_s, to: result.seconds }
      : null;

  const ask = async () => {
    if (!instruction.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      setResult(await aiEdit(nodeId, instruction.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };

  const apply = async () => {
    if (!result) return;
    if (result.target === "text") {
      const failed = await addTake(nodeId, result.text);
      if (failed) return setError(failed);
    } else {
      setPrompt(nodeId, result.text);
      if (lengthChange && params.kind === "video") {
        setParams(nodeId, { ...params, duration_s: lengthChange.to });
      }
    }
    onClose();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void ask();
    } else if (e.key === "Escape") {
      onClose();
    }
  };

  return (
    <div className="ai-edit nodrag nowheel">
      <textarea
        className="ai-edit__input"
        rows={2}
        autoFocus
        maxLength={4000}
        value={instruction}
        placeholder={t("ai_edit_ph")}
        aria-label={t("ai_edit_title")}
        onChange={(e) => setInstruction(e.target.value)}
        onKeyDown={onKeyDown}
      />
      {busy && (
        <p className="ai-edit__note">
          <span className="spinner" /> {t("ai_edit_busy")}
        </p>
      )}
      {error && (
        <p className="ai-edit__error" role="alert">
          {error}
        </p>
      )}
      {result && !busy && (
        <>
          <p className="ai-edit__label">
            {t(result.target === "text" ? "ai_edit_new_text" : "ai_edit_new_prompt")}
          </p>
          <p className="ai-edit__result">
            {changedWords(before, result.text).map((part, i) =>
              part.changed ? <mark key={i}>{part.text}</mark> : <span key={i}>{part.text}</span>,
            )}
          </p>
          {lengthChange && (
            <p className="ai-edit__note">
              {t("ai_edit_length", { from: lengthChange.from, to: lengthChange.to })}
            </p>
          )}
        </>
      )}
      <div className="ai-edit__actions">
        {result && !busy ? (
          <>
            <button className="button button--small button--primary" onClick={() => void apply()}>
              {t("ai_edit_apply")}
            </button>
            <button className="button button--small" onClick={() => void ask()}>
              {t("ai_edit_again")}
            </button>
          </>
        ) : (
          <button
            className="button button--small button--primary"
            disabled={!instruction.trim() || busy}
            onClick={() => void ask()}
          >
            {t("ai_edit_go")}
          </button>
        )}
        <button className="button button--small" onClick={onClose}>
          {result ? t("ai_edit_discard") : t("cancel")}
        </button>
      </div>
    </div>
  );
}

// Words, or single CJK characters (unspaced scripts), or runs of spaces.
const CJK = "\\u3040-\\u30ff\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff";
const TOKEN = new RegExp(`[${CJK}]|\\s+|[^\\s${CJK}]+`, "g");
const MAX_TOKENS = 600;

/** `after` in pieces, the ones not in `before` marked as changed (a longest
    common subsequence of words). Long texts are shown unmarked. */
function changedWords(before: string, after: string): { text: string; changed: boolean }[] {
  const a = before.match(TOKEN) ?? [];
  const b = after.match(TOKEN) ?? [];
  if (a.length > MAX_TOKENS || b.length > MAX_TOKENS) return [{ text: after, changed: false }];
  // common[i][j]: the longest common run of a[i..] and b[j..].
  const common = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      common[i]![j] =
        a[i] === b[j] ? common[i + 1]![j + 1]! + 1 : Math.max(common[i + 1]![j]!, common[i]![j + 1]!);
    }
  }
  const parts: { text: string; changed: boolean }[] = [];
  const push = (text: string, changed: boolean) => {
    const last = parts[parts.length - 1];
    // Spaces join whatever they sit between, so marks don't break at each word.
    if (last && (last.changed === changed || /^\s+$/.test(text))) last.text += text;
    else parts.push({ text, changed });
  };
  let i = 0;
  for (let j = 0; j < b.length; j++) {
    while (i < a.length && a[i] !== b[j] && common[i + 1]![j]! >= common[i]![j + 1]!) i++;
    if (i < a.length && a[i] === b[j]) {
      push(b[j]!, false);
      i++;
    } else {
      push(b[j]!, true);
    }
  }
  return parts;
}
