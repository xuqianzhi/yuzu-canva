// The basic view of a project: one page per workflow step (the workflow bar
// above is its tabs). A page runs its step and shows its nodes as cards. It's
// the same project as the canvas -- the same store, nodes, links and actions
// -- laid out differently: every part of a page is a shared piece (StepForms,
// NodePreview, NodeBody, TakeSwitcher), so a feature changed there changes
// in both views. Nodes outside the workflow show only on the canvas.
import { memo, useEffect, useRef } from "react";
import { nodeLabel, type Node } from "../api/types";
import { useT } from "../i18n";
import { NodeBody } from "../node/NodeBody";
import { aspect, NodePreview, useChosenOutput, useNodeGenerating } from "../node/NodePreview";
import { TakeSwitcher } from "../node/Takes";
import { UploadBadge, UploadInfo, uploadRatio } from "../node/UploadInfo";
import { ProjectDescription, SharedInstruction } from "../project/Instruction";
import { useCanvas } from "../store/canvas";
import { currentStep, type StepView } from "../workflow/status";
import {
  DownloadAll,
  NodePicker,
  STEP_STATE_LABELS,
  StepDescription,
  StepForms,
  useStepViews,
} from "../workflow/StepRun";

export function BasicView() {
  const views = useStepViews();
  const activeStep = useCanvas((s) => s.activeStep);
  const openStep = useCanvas((s) => s.openStep);
  const view = views.find((v) => v.step.key === activeStep);

  // A page is always open: the step the canvas had open, else the first not
  // done yet.
  const fallback = currentStep(views)?.step.key;
  useEffect(() => {
    if (!view && fallback) openStep(fallback);
  }, [view, fallback, openStep]);

  if (!view) return null;
  return (
    <StepPage
      key={view.step.key}
      view={view}
      total={views.length}
      previous={views[view.index - 1]}
    />
  );
}

function StepPage({
  view,
  total,
  previous,
}: {
  view: StepView;
  total: number;
  previous: StepView | undefined;
}) {
  const t = useT();
  const openStep = useCanvas((s) => s.openStep);
  const activeNodeId = useCanvas((s) => s.activeNodeId);
  const readOnly = useCanvas((s) => s.lock.status !== "editing");

  return (
    <div className="basic">
      <div className="basic__page">
        <header className="basic__head">
          <div>
            <small>
              {t("step_of", { n: view.index + 1, total })} · {t(`kind_${view.step.kind}`)}
            </small>
            <h1>{view.step.name}</h1>
          </div>
          <span className={`state-pill state-pill--${view.state}`}>
            {t(STEP_STATE_LABELS[view.state])}
          </span>
        </header>
        <StepDescription view={view} />

        {/* What the video is about comes first: every step is told it. */}
        {view.index === 0 && (
          <section className="basic__card basic__about">
            <SharedInstruction />
            <fieldset className="readonly-fence" disabled={readOnly}>
              <ProjectDescription className="basic__description" />
            </fieldset>
          </section>
        )}

        <section className="basic__card" aria-label={view.step.name}>
          <fieldset className="readonly-fence" disabled={readOnly}>
            <StepForms view={view} />
          </fieldset>
          {view.nodes.length > 0 && <NodePicker view={view} current={activeNodeId} />}
        </section>

        {view.nodes.length > 0 && (
          <section className="basic__results" aria-label={t("basic_results")}>
            <h2>{t("basic_results")}</h2>
            <fieldset className="readonly-fence" disabled={readOnly}>
              <div className={`basic__grid basic__grid--${view.step.kind}`}>
                {view.nodes.map((node) => (
                  <NodeCard key={node.id} node={node} stepKey={view.step.key} />
                ))}
              </div>
            </fieldset>
          </section>
        )}

        <footer className="basic__nav">
          {previous ? (
            <button className="button" onClick={() => openStep(previous.step.key)}>
              {t("basic_prev", { step: previous.step.name })}
            </button>
          ) : (
            <span />
          )}
          <span className="basic__spacer" />
          {view.state === "done" && <DownloadAll view={view} />}
          {view.next && (
            <button
              className={`button${view.state === "done" ? " button--primary" : ""}`}
              onClick={() => openStep(view.next!.key)}
            >
              {t("go_to_arrow", { step: view.next.name })}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}

/** One node of the step as one card: its name and versions, its output (once
    there is one, or one is on the way), then its prompt card. The active card
    is marked. The shared parts are folded and restyled by CSS only
    (.basic-card), so they behave as on the canvas. */
const NodeCard = memo(function NodeCard({ node, stepKey }: { node: Node; stepKey: string }) {
  const t = useT();
  const output = useChosenOutput(node.id);
  const busy = useNodeGenerating(node.id);
  const active = useCanvas((s) => s.activeNodeId === node.id);
  const openStep = useCanvas((s) => s.openStep);
  const uploaded = node.source === "upload";
  const text = node.kind === "text";
  const ratio = uploaded ? uploadRatio(output) : aspect(node.params);
  // The output's own shape once known, so it fills the card edge to edge.
  const { width, height } = output?.asset ?? {};
  const shape = width && height ? width / height : (ratio ?? 1);
  const card = useRef<HTMLElement>(null);
  // Scrolled to when picked in the selector, and when the page opens on it;
  // not on a click in the card, which would move it under the pointer.
  const jump = useCanvas((s) => s.jump);
  useEffect(() => {
    if (useCanvas.getState().activeNodeId !== node.id) return;
    card.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [jump, node.id]);

  return (
    <article
      ref={card}
      className={`basic-card${active ? " is-active" : ""}`}
      // Working on a card makes it the step's current node (the canvas opens
      // on it too).
      onFocusCapture={() => !active && openStep(stepKey, node.id)}
      onPointerDownCapture={() => !active && openStep(stepKey, node.id)}
    >
      <header className="basic-card__head">
        {node.kind === "video" && node.workflow_item !== null && (
          <span className="basic-card__number">{node.workflow_item}</span>
        )}
        <span className="basic-card__name">{nodeLabel(node)}</span>
        {node.edited && (
          <span className="basic-card__edited" title={t("edited_title")}>
            {t("edited_mark")}
          </span>
        )}
        <span className="basic__spacer" />
        {uploaded ? <UploadBadge node={node} /> : <TakeSwitcher node={node} />}
      </header>
      {/* A text node's box is where it's typed, so it's always there. */}
      {(text || output || busy) && (
        <div
          className={`gen-node__media basic-card__media${text ? " basic-card__media--text" : ""}`}
          style={text ? undefined : { aspectRatio: shape }}
        >
          <NodePreview
            nodeId={node.id}
            output={output}
            kind={node.kind}
            ratio={ratio}
            scrollable
          />
        </div>
      )}
      {uploaded ? <UploadInfo node={node} output={output} /> : <NodeBody nodeId={node.id} />}
    </article>
  );
});
