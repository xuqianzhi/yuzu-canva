// A generated node's prompt card, the same in every view (the canvas node
// and the basic view's card wrap it): what went wrong, the inputs it uses,
// its prompt, its settings, and its actions (Edit with AI,
// Generate or Cancel). Views add only their own frame around it; a feature added here
// shows in all of them.
import { useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { AiEditBox, AiEditButton } from "../canvas/AiEdit";
import { inputKeys, labelInputs } from "../canvas/inputs";
import { MentionPrompt, useUnlinkedMentions } from "../canvas/MentionPrompt";
import { useT } from "../i18n";
import { useCanvas } from "../store/canvas";
import { MediaThumb } from "./MediaThumb";
import { useChosenOutput, useNodeGenerating } from "./NodePreview";
import { NodeSettings } from "./NodeSettings";

export function NodeBody({ nodeId }: { nodeId: string }) {
  const t = useT();
  const node = useCanvas((s) => s.nodes[nodeId]);
  const failed = useCanvas((s) => {
    const job = s.jobs[nodeId];
    return job?.status === "failed" ? job.error : undefined;
  });
  const error = useCanvas((s) => s.nodeErrors[nodeId]) ?? failed;
  // Inputs, in the order their outputs are sent to the model.
  const inputKeyList = useCanvas(
    useShallow((s) => inputKeys(nodeId, s.edges, s.nodes, s.outputs)),
  );
  const unlinked = useUnlinkedMentions(nodeId);
  const busy = useNodeGenerating(nodeId);
  const generate = useCanvas((s) => s.generate);
  const cancel = useCanvas((s) => s.cancel);
  // "Edit prompt with AI" open under the card.
  const [aiEditing, setAiEditing] = useState(false);
  if (!node) return null;
  const inputs = labelInputs(inputKeyList);
  const ready = Boolean(node.prompt.trim());

  return (
    <>
      <div className="gen-node__card">
        {error && <NodeAlert word={t("node_failed")} text={error} />}
        {!error && unlinked.length > 0 && (
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
          ariaLabel={t("prompt_aria")}
          onGenerate={() => !busy && void generate(nodeId)}
        />
        <div className="gen-node__bar nodrag">
          <NodeSettings nodeId={nodeId} params={node.params} />
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

/** One referenced node: a thumbnail of its selected take, numbered. */
function RefChip({ nodeId, label }: { nodeId: string; label: string }) {
  const t = useT();
  const output = useChosenOutput(nodeId);
  const prompt = useCanvas((s) => s.nodes[nodeId]?.prompt.trim());
  const title = prompt || t("untitled_node");
  const url = output?.asset?.url;
  return (
    <div
      className={`ref-chip${output ? "" : " ref-chip--empty"}`}
      title={output ? `${label}: ${title}` : `${label}: ${title}${t("no_output_suffix")}`}
    >
      {url && output && output.kind !== "text" && <MediaThumb kind={output.kind} url={url} />}
      {output?.kind === "text" && <span className="ref-chip__text">T</span>}
      {!url && output?.kind !== "text" && <span className="ref-chip__blank" />}
      <span className="ref-chip__label">{label}</span>
    </div>
  );
}
