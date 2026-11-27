// A node's takes (versions): step through them. Shared by every view that
// shows a node's work.
import { useMemo } from "react";
import type { Node, Output } from "../api/types";
import { useT } from "../i18n";
import { useCanvas } from "../store/canvas";

/** A node's takes, oldest first, and where its chosen one is among them. */
function useTakes(node: Node): { takes: Output[]; index: number } {
  const outputs = useCanvas((s) => s.outputs);
  // Not on every render: a node being dragged renders each frame.
  const takes = useMemo(
    () =>
      Object.values(outputs)
        .filter((o) => o.node_id === node.id)
        .sort((a, b) => a.created_at.localeCompare(b.created_at)),
    [outputs, node.id],
  );
  const index = Math.max(
    0,
    takes.findIndex((o) => o.id === node.selected_output_id),
  );
  return { takes, index };
}

/** ‹ Version n of N ›: picks the chosen take. Nothing with fewer than two. */
export function TakeSwitcher({ node }: { node: Node }) {
  const t = useT();
  const selectTake = useCanvas((s) => s.selectTake);
  const { takes, index } = useTakes(node);
  if (takes.length < 2) return null;
  return (
    <div className="take__head">
      <button
        className="icon-button icon-button--plain"
        disabled={index === 0}
        onClick={() => selectTake(node.id, takes[index - 1]!.id)}
        aria-label={t("prev_version")}
      >
        ‹
      </button>
      <span>{t("version_of", { n: index + 1, total: takes.length })}</span>
      <button
        className="icon-button icon-button--plain"
        disabled={index === takes.length - 1}
        onClick={() => selectTake(node.id, takes[index + 1]!.id)}
        aria-label={t("next_version")}
      >
        ›
      </button>
    </div>
  );
}
