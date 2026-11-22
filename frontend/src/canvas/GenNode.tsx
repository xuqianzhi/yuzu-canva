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
  type Output,
  type VideoParams,
} from "../api/types";
import { useCanvas, type GenFlowNode, type NodeShape } from "../store/canvas";
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
  const setParams = useCanvas((s) => s.setParams);
  const generate = useCanvas((s) => s.generate);
  const cancel = useCanvas((s) => s.cancel);
  const { deleteElements } = useReactFlow();
  // Handles appear and disappear when the shape changes: let React Flow
  // re-measure them, so connections attach in the right places.
  const updateNodeInternals = useUpdateNodeInternals();
  const step = useCanvas((s) =>
    node?.workflow_step ? s.project?.workflow.steps.find((w) => w.key === node.workflow_step) : undefined,
  );
  const t = useT();
  const openStep = useCanvas((s) => s.openStep);
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
    <div
      className={`gen-node${selected ? " gen-node--selected" : ""}`}
    >
      {/* A one-to-one step's nodes have no ID: only the next step uses them. */}
      {step?.output !== "one_to_one" && <NodeNameInput nodeId={nodeId} className="gen-node__name" />}
      <Handle
        type="target"
        position={Position.Left}
        className="gen-node__handle"
        title={t("drop_input")}
      />
      <OutputHandle hasId={Boolean(node.name)} title={t("drag_output")} />
      <div className="gen-node__header" title={t("drag_to_move")}>
        {step ? (
          // A workflow node: its step sets its kind. Click to open the step.
          <>
            <button
              className="wf-badge nodrag"
              onClick={() => openStep(step.key, nodeId)}
              title={t("open_step", { step: step.name })}
            >
              {step.name} · {node.workflow_item}
            </button>
          </>
        ) : (
          <KindTabs shape={shape} disabled={busy} onPick={(next) => setShape(nodeId, next)} />
        )}
      </div>

      {/* Fixed-size media box. Inputs and errors float over it, so every node
          is the same size whatever it holds. */}
      <div className="gen-node__media">
        <Preview
          output={output}
          busy={busy}
          job={job}
          kind={node.kind}
        />
        {inputs.length > 0 && (
          <div className="gen-node__refs" aria-label={t("inputs_aria")}>
            {inputs.map((input) => (
              <RefChip key={input.nodeId} nodeId={input.nodeId} label={input.label} />
            ))}
          </div>
        )}
        {(error || failed) && (
          <div className="gen-node__error" role="alert">
            {error ?? failed}
          </div>
        )}
        {!error && !failed && unlinked.length > 0 && (
          <div className="gen-node__error gen-node__error--warn" role="status">
            {t("loop_warning", { ids: unlinked.map((id) => `“${id}”`).join(t("list_sep")) })}
          </div>
        )}
      </div>

      <MentionPrompt
        nodeId={nodeId}
        placeholder={t("ph_describe", { kind: t(`kind_${node.kind}`) })}
        onGenerate={() => !busy && void generate(nodeId)}
      />

      <div className="gen-node__params nodrag">
        {params.kind === "image" && (
          <>
            <select
              aria-label={t("size")}
              value={params.size}
              onChange={(e) =>
                setParams(nodeId, { ...params, size: e.target.value as ImageParams["size"] })
              }
            >
              {IMAGE_SIZES.map((v) => (
                <option key={v} value={v}>
                  {v === "auto" ? t("size_auto") : v}
                </option>
              ))}
            </select>
            <select
              aria-label={t("quality")}
              value={params.quality}
              onChange={(e) =>
                setParams(nodeId, {
                  ...params,
                  quality: e.target.value as ImageParams["quality"],
                })
              }
            >
              {IMAGE_QUALITIES.map((v) => (
                <option key={v} value={v}>
                  {v === "auto" ? t("quality_auto") : t(`quality_${v}`)}
                </option>
              ))}
            </select>
          </>
        )}
        {params.kind === "video" && (
          <>
            <select
              aria-label={t("ratio")}
              value={params.ratio}
              onChange={(e) =>
                setParams(nodeId, { ...params, ratio: e.target.value as VideoParams["ratio"] })
              }
            >
              {VIDEO_RATIOS.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
            <select
              aria-label={t("duration")}
              value={params.duration_s}
              onChange={(e) => setParams(nodeId, { ...params, duration_s: Number(e.target.value) })}
            >
              {Array.from({ length: 12 }, (_, i) => i + 4).map((s) => (
                <option key={s} value={s}>
                  {t("seconds", { n: s })}
                </option>
              ))}
            </select>
            <select
              aria-label={t("resolution")}
              value={params.resolution}
              onChange={(e) =>
                setParams(nodeId, {
                  ...params,
                  resolution: e.target.value as VideoParams["resolution"],
                })
              }
            >
              {VIDEO_RESOLUTIONS.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
            <label className="toggle" title={t("audio_title")}>
              <input
                type="checkbox"
                checked={params.generate_audio}
                onChange={(e) => setParams(nodeId, { ...params, generate_audio: e.target.checked })}
              />
              {t("audio")}
            </label>
          </>
        )}
        {params.kind === "text" && <span className="gen-node__hint">{t("text_output")}</span>}
      </div>

      <div className="gen-node__footer nodrag">
        {!step && (
          <button
            className="icon-button"
            // Same path as Backspace: confirm, then remove it and its connections.
            onClick={() => void deleteElements({ nodes: [{ id: nodeId }] })}
            title={t("delete_node")}
            aria-label={t("delete_node")}
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" />
            </svg>
          </button>
        )}
        <span className="gen-node__spacer" />
        {busy ? (
          <button className="button button--small" onClick={() => void cancel(nodeId)}>
            {t("cancel")}
          </button>
        ) : (
          <button
            className="button button--primary button--small"
            onClick={() => void generate(nodeId)}
            disabled={!ready}
            title={ready ? t("generate_title") : t("write_prompt_first")}
          >
            {t("generate")}
          </button>
        )}
      </div>
    </div>
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
}: {
  output: Output | undefined;
  busy: boolean;
  job: Job | undefined;
  kind: MediaKind;
}) {
  const status = job?.status;
  const t = useT();
  return (
    <div className={`gen-node__preview${output ? "" : " gen-node__preview--empty"}`}>
      {output?.asset && output.kind === "image" && (
        <img src={output.asset.url} alt="" draggable={false} />
      )}
      {output?.asset && output.kind === "video" && (
        <video src={output.asset.url} controls playsInline className="nodrag" />
      )}
      {output?.kind === "text" &&
        <p className="gen-node__text nowheel">{output.text}</p>}
      {!output && !busy && <span>{t("no_output")}</span>}
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
  const { deleteElements } = useReactFlow();
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
      <NodeNameInput nodeId={nodeId} className="gen-node__name" />
      <OutputHandle hasId={Boolean(node.name)} title={t("drag_file")} />
      <div className="gen-node__header">
        <span className="upload-badge">{t("uploaded_kind", { kind: t(`kind_${node.kind}`) })}</span>
      </div>
      <div className="gen-node__media">
        <Preview output={output} busy={false} job={undefined} kind={node.kind} />
      </div>
      <div className="gen-node__upload-info nodrag">
        <span>{details.join(" · ")}</span>
        <small>
          {node.kind === "video" ? t("uploaded_hint_video") : t("uploaded_hint_image")}
        </small>
      </div>
      <div className="gen-node__footer nodrag">
        <button
          className="icon-button"
          onClick={() => void deleteElements({ nodes: [{ id: nodeId }] })}
          title={t("delete_node")}
          aria-label={t("delete_node")}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" />
          </svg>
        </button>
      </div>
    </div>
  );
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
