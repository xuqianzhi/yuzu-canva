import {
  Handle,
  Position,
  useReactFlow,
  useUpdateNodeInternals,
  type NodeProps,
} from "@xyflow/react";
import { memo, useEffect, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import {
  TERMINAL_JOB_STATUSES,
  type ImageParams,
  type Job,
  type MediaKind,
  type NodeParams,
  type Output,
  type VideoParams,
} from "../api/types";
import { useCanvas, type GenFlowNode, type NodeShape } from "../store/canvas";
import { AiEditBox, AiEditButton } from "./AiEdit";
import { DurationSelect, ParamSelect } from "./ParamSelect";
import { KindTabs } from "./KindTabs";
import { inputKeys, labelInputs } from "./inputs";
import { MentionPrompt, useUnlinkedMentions } from "./MentionPrompt";
import { NodeNameInput } from "./NodeName";
import { OutputHandle } from "./OutputHandle";
import { useT } from "../i18n";


const IMAGE_SIZES: ImageParams["size"][] = ["auto", "1024x1024", "1536x1024", "1024x1536"];
const IMAGE_QUALITIES: ImageParams["quality"][] = ["auto", "low", "medium", "high"];
const VIDEO_RATIOS: VideoParams["ratio"][] = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"];
const VIDEO_RESOLUTIONS: VideoParams["resolution"][] = ["480p", "720p", "1080p"];

function GenNodeView({ data, selected }: NodeProps<GenFlowNode>) {
  const { nodeId } = data;
  const node = useCanvas((s) => s.nodes[nodeId]);
  const job = useCanvas((s) => s.jobs[nodeId]);
  const error = useCanvas((s) => s.nodeErrors[nodeId]);
  const output = useCanvas((s) => {
    const id = s.nodes[nodeId]?.selected_output_id;
    return id ? s.outputs[id] : undefined;
  });
  // Inputs, in the order their outputs are sent to the model.
  const inputKeyList = useCanvas(
    useShallow((s) => inputKeys(nodeId, s.edges, s.nodes, s.outputs)),
  );
  const unlinked = useUnlinkedMentions(nodeId);
  const setShape = useCanvas((s) => s.setShape);
  const generate = useCanvas((s) => s.generate);
  const cancel = useCanvas((s) => s.cancel);
  const { deleteElements } = useReactFlow();
  // Handles appear and disappear when the shape changes: let React Flow
  // re-measure them, so connections attach in the right places.
  const updateNodeInternals = useUpdateNodeInternals();
  const steps = useCanvas((s) => s.project?.workflow.steps);
  const step = node?.workflow_step ? steps?.find((w) => w.key === node.workflow_step) : undefined;
  const t = useT();
  const openStep = useCanvas((s) => s.openStep);
  // "Edit with AI" open under the card.
  const [aiEditing, setAiEditing] = useState(false);
  const kind = node?.kind;
  useEffect(() => updateNodeInternals(nodeId), [kind, nodeId, updateNodeInternals]);

  if (!node) return null;
  if (node.source === "upload") {
    return <UploadedNode nodeId={nodeId} selected={selected} output={output} />;
  }
  const busy = job !== undefined && !TERMINAL_JOB_STATUSES.includes(job.status);
  const failed = job?.status === "failed" ? job.error : undefined;
  const params = node.params;
  const shape: NodeShape = node.kind;
  const inputs = labelInputs(inputKeyList);
  const ready = Boolean(node.prompt.trim());

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
        <Preview output={output} busy={busy} job={job} kind={node.kind} ratio={aspect(params)} />
      </div>

      {/* The prompt: its inputs, the text, and the settings it's made with.
          Wider than the output; links come in here. */}
      <div className="gen-node__card">
        {(error || failed) && <NodeAlert word={t("node_failed")} text={(error ?? failed)!} />}
        {!error && !failed && unlinked.length > 0 && (
          <NodeAlert
            warn
            word={t("node_warning")}
            text={t("loop_warning", { ids: unlinked.map((id) => `“${id}”`).join(t("list_sep")) })}
          />
        )}
        {inputs.length > 0 && (
          <div className="gen-node__refs" aria-label={t("inputs_aria")}>
            {inputs.map((input) => (
              <RefChip key={input.nodeId} nodeId={input.nodeId} label={input.label} />
            ))}
          </div>
        )}
        <MentionPrompt
          nodeId={nodeId}
          placeholder={t("ph_describe", { kind: t(`kind_${node.kind}`) })}
          onGenerate={() => !busy && void generate(nodeId)}
        />
        <div className="gen-node__bar nodrag">
          <Settings nodeId={nodeId} params={params} />
          <span className="gen-node__spacer" />
          <AiEditButton open={aiEditing} onClick={() => setAiEditing((open) => !open)} />
          {busy ? (
            <button
              className="round-button round-button--stop"
              onClick={() => void cancel(nodeId)}
              title={t("cancel")}
              aria-label={t("cancel")}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <rect x="4.5" y="4.5" width="7" height="7" rx="1.2" />
              </svg>
            </button>
          ) : (
            <button
              className="round-button"
              onClick={() => void generate(nodeId)}
              disabled={!ready}
              title={ready ? t("generate_title") : t("write_prompt_first")}
              aria-label={t("generate")}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d="M8 12.5v-9M4.5 7 8 3.5 11.5 7" />
              </svg>
            </button>
          )}
        </div>
      </div>
      {aiEditing && <AiEditBox nodeId={nodeId} onClose={() => setAiEditing(false)} />}
    </div>
  );
}

/** Width / height of what a node makes, from its settings (null: text,
    which fills the square). */
function aspect(params: NodeParams): number | null {
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

/** The node's settings, compact, in the prompt card's bottom row. */
function Settings({ nodeId, params }: { nodeId: string; params: NodeParams }) {
  const t = useT();
  const setParams = useCanvas((s) => s.setParams);
  if (params.kind === "text") return <span className="gen-node__hint">{t("text_output")}</span>;
  if (params.kind === "image") {
    return (
      <>
        <ParamSelect
          label={t("size")}
          value={params.size}
          options={IMAGE_SIZES}
          format={(v) => (v === "auto" ? t("size_auto") : v)}
          onChange={(size) => setParams(nodeId, { ...params, size })}
        />
        <ParamSelect
          label={t("quality")}
          value={params.quality}
          options={IMAGE_QUALITIES}
          format={(v) => (v === "auto" ? t("quality_auto") : t(`quality_${v}`))}
          onChange={(quality) => setParams(nodeId, { ...params, quality })}
        />
      </>
    );
  }
  return (
    <>
      <ParamSelect
        label={t("ratio")}
        value={params.ratio}
        options={VIDEO_RATIOS}
        onChange={(ratio) => setParams(nodeId, { ...params, ratio })}
      />
      <DurationSelect
        label={t("duration")}
        value={params.duration_s}
        onChange={(duration_s) => setParams(nodeId, { ...params, duration_s })}
      />
      <ParamSelect
        label={t("resolution")}
        value={params.resolution}
        options={VIDEO_RESOLUTIONS}
        onChange={(resolution) => setParams(nodeId, { ...params, resolution })}
      />
      <label className="toggle" title={t("audio_title")}>
        <input
          type="checkbox"
          checked={params.generate_audio}
          onChange={(e) => setParams(nodeId, { ...params, generate_audio: e.target.checked })}
        />
        {t("audio")}
      </label>
    </>
  );
}

/** An error (or warning): a small "! Failed" badge on the prompt card's
    top-right corner; hovering (or focusing) it shows the whole message. */
function NodeAlert({ word, text, warn = false }: { word: string; text: string; warn?: boolean }) {
  return (
    <div
      className={`node-alert nodrag nowheel${warn ? " node-alert--warn" : ""}`}
      role={warn ? "status" : "alert"}
      tabIndex={0}
      aria-label={`${word}: ${text}`}
    >
      <span className="node-alert__badge">
        <span className="node-alert__mark" aria-hidden="true">
          !
        </span>
        {word}
      </span>
      <div className="node-alert__detail">{text}</div>
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

/** One referenced node: a thumbnail of its selected take, numbered. */
function RefChip({ nodeId, label }: { nodeId: string; label: string }) {
  const t = useT();
  const output = useCanvas((s) => {
    const id = s.nodes[nodeId]?.selected_output_id;
    return id ? s.outputs[id] : undefined;
  });
  const prompt = useCanvas((s) => s.nodes[nodeId]?.prompt.trim());
  const title = prompt || t("untitled_node");
  const url = output?.asset?.url;
  return (
    <div
      className={`ref-chip${output ? "" : " ref-chip--empty"}`}
      title={output ? `${label}: ${title}` : `${label}: ${title}${t("no_output_suffix")}`}
    >
      {url && output?.kind === "image" && <img src={url} alt="" draggable={false} />}
      {url && output?.kind === "video" && (
        // #t=0.1 makes browsers paint the first frame as a thumbnail.
        <video src={`${url}#t=0.1`} muted playsInline preload="metadata" />
      )}
      {output?.kind === "text" && <span className="ref-chip__text">T</span>}
      {!url && output?.kind !== "text" && <span className="ref-chip__blank" />}
      <span className="ref-chip__label">{label}</span>
    </div>
  );
}

function Preview({
  output,
  busy,
  job,
  kind,
  ratio,
}: {
  output: Output | undefined;
  busy: boolean;
  job: Job | undefined;
  kind: MediaKind;
  /** The shape to hold before there's an output (null: fill the square). */
  ratio: number | null;
}) {
  const status = job?.status;
  const t = useT();
  const box = fit(ratio);
  // The frame is exactly the output's shape (or the placeholder's), so the
  // "generating" box, drawn inside it, never spills past what's shown.
  return (
    <div className="gen-node__preview">
      <div
        className={`gen-node__frame${output?.kind === "text" ? " gen-node__frame--fill" : ""}`}
        style={!output ? box : undefined}
      >
        {output?.asset && output.kind === "image" && (
          <img className="gen-node__output" src={output.asset.url} alt="" draggable={false} />
        )}
        {output?.asset && output.kind === "video" && (
          <video
            className="gen-node__output nodrag"
            src={output.asset.url}
            controls
            playsInline
          />
        )}
        {output?.kind === "text" && <p className="gen-node__text nowheel">{output.text}</p>}
        {!output && <div className="gen-node__placeholder">{!busy && <span>{t("no_output")}</span>}</div>}
        {busy && (
          <div className="gen-node__progress">
            <span className="spinner" />
            <span>
              {status === "queued" ? t("queued") : t("generating")}{" "}
              {job && <Elapsed since={job.started_at ?? job.created_at} />}
            </span>
            {kind === "video" && <small>{t("videos_take_minutes")}</small>}
          </div>
        )}
      </div>
    </div>
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
  const asset = output?.asset;
  const details = [
    asset?.width && asset.height ? `${asset.width}×${asset.height}` : null,
    asset?.duration_s ? t("seconds", { n: asset.duration_s.toFixed(1) }) : null,
    asset ? formatBytes(asset.bytes) : null,
  ].filter(Boolean);

  return (
    <div className={`gen-node gen-node--upload${selected ? " gen-node--selected" : ""}`}>
      <OutputHandle hasId={Boolean(node.name)} title={t("drag_file")} />
      <div className="gen-node__header" title={t("drag_to_move")}>
        <NodeNameInput nodeId={nodeId} className="gen-node__name" />
        <span className="gen-node__spacer" />
        <span className="upload-badge">{t("uploaded_kind", { kind: t(`kind_${node.kind}`) })}</span>
        <DeleteNodeButton nodeId={nodeId} />
      </div>
      <div className="gen-node__media">
        <Preview
          output={output}
          busy={false}
          job={undefined}
          kind={node.kind}
          ratio={asset?.width && asset.height ? asset.width / asset.height : 1}
        />
      </div>
      <div className="gen-node__card gen-node__upload-info">
        <span>{details.join(" · ")}</span>
        <small>
          {node.kind === "video" ? t("uploaded_hint_video") : t("uploaded_hint_image")}
        </small>
      </div>
    </div>
  );
}

/** The placeholder's size: `ratio` (width / height) fitted inside the square
    (null: filling it). */
function fit(ratio: number | null): { width: string; height: string } {
  if (ratio === null) return { width: "100%", height: "100%" };
  if (ratio >= 1) return { width: "100%", height: `${100 / ratio}%` };
  return { width: `${100 * ratio}%`, height: "100%" };
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
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

export const GenNode = memo(GenNodeView);
