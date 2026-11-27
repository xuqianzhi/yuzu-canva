// A node on the canvas: the canvas's own frame (its handles, its header to
// drag it by, its ID, step badge or kind, and delete) around the parts every
// view shares: the output (NodePreview) and the prompt card (NodeBody).
import {
  Handle,
  Position,
  useReactFlow,
  useUpdateNodeInternals,
  type NodeProps,
} from "@xyflow/react";
import { memo, useEffect } from "react";
import type { Output } from "../api/types";
import { NodeBody } from "../node/NodeBody";
import { aspect, NodePreview, useChosenOutput, useNodeGenerating } from "../node/NodePreview";
import { TakeSwitcher } from "../node/Takes";
import { UploadBadge, UploadInfo, uploadRatio } from "../node/UploadInfo";
import { useCanvas, type GenFlowNode, type NodeShape } from "../store/canvas";
import { KindTabs } from "./KindTabs";
import { NodeNameInput } from "./NodeName";
import { OutputHandle } from "./OutputHandle";
import { useT } from "../i18n";

function GenNodeView({ data, selected }: NodeProps<GenFlowNode>) {
  const { nodeId } = data;
  const node = useCanvas((s) => s.nodes[nodeId]);
  const output = useChosenOutput(nodeId);
  const busy = useNodeGenerating(nodeId);
  const setShape = useCanvas((s) => s.setShape);
  // Handles appear and disappear when the shape changes: let React Flow
  // re-measure them, so connections attach in the right places.
  const updateNodeInternals = useUpdateNodeInternals();
  const steps = useCanvas((s) => s.project?.workflow.steps);
  const step = node?.workflow_step ? steps?.find((w) => w.key === node.workflow_step) : undefined;
  const t = useT();
  const openStep = useCanvas((s) => s.openStep);
  const kind = node?.kind;
  useEffect(() => updateNodeInternals(nodeId), [kind, nodeId, updateNodeInternals]);

  if (!node) return null;
  if (node.source === "upload") {
    return <UploadedNode nodeId={nodeId} selected={selected} output={output} />;
  }
  const shape: NodeShape = node.kind;

  return (
    <div className={`gen-node${selected ? " gen-node--selected" : ""}`}>
      <Handle
        type="target"
        position={Position.Left}
        className="gen-node__handle"
        title={t("drop_input")}
      />
      <OutputHandle hasId={Boolean(node.name)} title={t("drag_output")} />
      {/* One row: the node's ID, then its step (or kind), then delete. Like the
          rest of the node, it drags it; only the ID box and the buttons don't. */}
      <div className="gen-node__header" title={t("drag_to_move")}>
        <NodeNameInput nodeId={nodeId} className="gen-node__name" />
        <span className="gen-node__spacer" />
        <span className="nodrag">
          <TakeSwitcher node={node} />
        </span>
        {step ? (
          // A workflow node: its step sets its kind. Click to open the step;
          // dragging it moves the node (a drag doesn't count as a click).
          <button
            className="wf-badge"
            onClick={() => openStep(step.key, nodeId)}
            title={t("open_step", { step: step.name })}
          >
            {step.name} · {node.workflow_item}
            {node.edited && (
              <span className="wf-badge__edited" title={t("edited_title")}>
                {" "}
                · {t("edited_mark")}
              </span>
            )}
          </button>
        ) : (
          <KindTabs shape={shape} disabled={busy} onPick={(next) => setShape(nodeId, next)} />
        )}
        {!step && <DeleteNodeButton nodeId={nodeId} />}
      </div>

      {/* The output: a fixed square, itself invisible; what's in it keeps its
          own shape (the output's, or the settings' ratio before there is one). */}
      <div className="gen-node__media">
        <NodePreview
          nodeId={nodeId}
          output={output}
          kind={node.kind}
          ratio={aspect(node.params)}
          scrollable={selected}
        />
      </div>

      {/* The prompt card: wider than the output; links come in here. */}
      <NodeBody nodeId={nodeId} />
    </div>
  );
}

/** The header's delete button: the same path as Backspace (confirm, then
    remove the node and its connections). */
function DeleteNodeButton({ nodeId }: { nodeId: string }) {
  const t = useT();
  const { deleteElements } = useReactFlow();
  return (
    <button
      className="icon-button nodrag"
      onClick={() => void deleteElements({ nodes: [{ id: nodeId }] })}
      title={t("delete_node")}
      aria-label={t("delete_node")}
    >
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" />
      </svg>
    </button>
  );
}

/** A node holding an uploaded file: no prompt, no inputs, no generating. Same
    size as a generating node; its output feeds other nodes like any take. */
function UploadedNode({
  nodeId,
  selected,
  output,
}: {
  nodeId: string;
  selected: boolean;
  output: Output | undefined;
}) {
  const node = useCanvas((s) => s.nodes[nodeId]);
  const t = useT();
  if (!node) return null;
  return (
    <div className={`gen-node gen-node--upload${selected ? " gen-node--selected" : ""}`}>
      <OutputHandle hasId={Boolean(node.name)} title={t("drag_file")} />
      <div className="gen-node__header" title={t("drag_to_move")}>
        <NodeNameInput nodeId={nodeId} className="gen-node__name" />
        <span className="gen-node__spacer" />
        <UploadBadge node={node} />
        <DeleteNodeButton nodeId={nodeId} />
      </div>
      <div className="gen-node__media">
        <NodePreview
          nodeId={nodeId}
          output={output}
          kind={node.kind}
          ratio={uploadRatio(output)}
          scrollable={selected}
        />
      </div>
      <UploadInfo node={node} output={output} />
    </div>
  );
}

export const GenNode = memo(GenNodeView);
