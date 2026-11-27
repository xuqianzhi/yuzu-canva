// What a node has made, shown the same in every view: its chosen take (an
// image, a video or text), or a placeholder in the shape it will have, with
// progress while it generates.
import { useEffect, useState } from "react";
import { isActive, type MediaKind, type NodeParams, type Output } from "../api/types";
import { useT } from "../i18n";
import { useCanvas } from "../store/canvas";
import { TextResult } from "./TextResult";

/** A node's chosen take (undefined: none yet). */
export function useChosenOutput(nodeId: string): Output | undefined {
  return useCanvas((s) => {
    const id = s.nodes[nodeId]?.selected_output_id;
    return id ? s.outputs[id] : undefined;
  });
}

/** Whether a node is generating (its job is queued or running). */
export function useNodeGenerating(nodeId: string): boolean {
  return useCanvas((s) => isActive(s.jobs[nodeId]));
}

/** Width / height of what a node makes, from its settings (null: text,
    which fills the frame). */
export function aspect(params: NodeParams): number | null {
  if (params.kind === "video") {
    const [w, h] = params.ratio.split(":").map(Number);
    return w! / h!;
  }
  if (params.kind === "image") {
    const match = /^(\d+)x(\d+)$/.exec(params.size);
    return match ? Number(match[1]) / Number(match[2]) : 1;
  }
  return null;
}

export function NodePreview({
  nodeId,
  output,
  kind,
  ratio,
  scrollable,
}: {
  nodeId: string;
  output: Output | undefined;
  kind: MediaKind;
  /** The shape to hold before there's an output (null: fill the frame). */
  ratio: number | null;
  /** The wheel scrolls a long text. On the canvas only while the node is
      selected; otherwise the wheel zooms the canvas, as everywhere else. */
  scrollable: boolean;
}) {
  const job = useCanvas((s) => s.jobs[nodeId]);
  const busy = useNodeGenerating(nodeId);
  const t = useT();
  const box = fit(ratio);
  // The frame is exactly the output's shape (or the placeholder's), so the
  // "generating" box, drawn inside it, never spills past what's shown.
  return (
    <div className="gen-node__preview">
      <div
        className={`gen-node__frame${kind === "text" ? " gen-node__frame--fill" : ""}`}
        style={!output && kind !== "text" ? box : undefined}
      >
        {output?.asset && output.kind === "image" && (
          <img className="gen-node__output" src={output.asset.url} alt="" draggable={false} />
        )}
        {output?.asset && output.kind === "video" && (
          <video className="gen-node__output nodrag" src={output.asset.url} controls playsInline />
        )}
        {kind === "text" && (
          <TextResult
            // Another version (or node) starts from its own text.
            key={output?.id ?? nodeId}
            nodeId={nodeId}
            text={output?.text ?? ""}
            busy={busy}
            scrollable={scrollable}
          />
        )}
        {kind !== "text" && !output && (
          <div className="gen-node__placeholder">{!busy && <span>{t("no_output")}</span>}</div>
        )}
        {busy && (
          <div className="gen-node__progress">
            <span className="spinner" />
            <span>
              {job?.status === "queued" ? t("queued") : t("generating")}{" "}
              {job && <Elapsed since={job.started_at ?? job.created_at} />}
            </span>
            {kind === "video" && <small>{t("videos_take_minutes")}</small>}
          </div>
        )}
      </div>
    </div>
  );
}

/** The placeholder's size: `ratio` (width / height) fitted inside the frame
    (null: filling it). */
function fit(ratio: number | null): { width: string; height: string } {
  if (ratio === null) return { width: "100%", height: "100%" };
  if (ratio >= 1) return { width: "100%", height: `${100 / ratio}%` };
  return { width: `${100 * ratio}%`, height: "100%" };
}

/** m:ss since `since`, ticking every second. */
function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.floor((now - Date.parse(since)) / 1000));
  return (
    <span className="elapsed">
      {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
    </span>
  );
}
