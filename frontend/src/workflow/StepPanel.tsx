// The side panel for one workflow step: its run form, then a selector that
// jumps to each of its nodes on the canvas (a node's prompt, versions and
// actions are on the node itself).
import { useNodesInitialized, useReactFlow } from "@xyflow/react";
import { useEffect, useRef } from "react";
import { useT } from "../i18n";
import { useCanvas } from "../store/canvas";
import { DownloadAll, NodePicker, STEP_STATE_LABELS, StepDescription, StepForms, useStepViews } from "./StepRun";

export function StepPanel() {
  const t = useT();
  const activeStep = useCanvas((s) => s.activeStep);
  const activeNodeId = useCanvas((s) => s.activeNodeId);
  const openStep = useCanvas((s) => s.openStep);
  const views = useStepViews();
  const view = views.find((v) => v.step.key === activeStep);
  const node = view?.nodes.find((n) => n.id === activeNodeId) ?? view?.nodes[0];
  useFocus(node?.id);

  if (!view) return null;
  return (
    <aside className="step-panel" aria-label={t("step_panel_aria", { step: view.step.name })}>
      <header className="step-panel__head">
        <div className="step-panel__heading">
          <small>
            {t("step_of", { n: view.index + 1, total: views.length })} · {t(`kind_${view.step.kind}`)}
          </small>
          <h2>{view.step.name}</h2>
        </div>
        <span className={`state-pill state-pill--${view.state}`}>{t(STEP_STATE_LABELS[view.state])}</span>
        <button
          className="icon-button icon-button--plain"
          onClick={() => openStep(null)}
          aria-label={t("close_panel")}
          title={t("close")}
        >
          ×
        </button>
      </header>
      <div className="step-panel__body">
        <StepDescription view={view} />
        <StepForms key={view.step.key} view={view} />
        {view.nodes.length > 0 && <NodePicker view={view} current={node?.id ?? null} />}
        {view.state === "done" && (
          <div className="step-panel__continue">
            <DownloadAll key={view.step.key} view={view} />
            {view.next && (
              <button className="button button--primary" onClick={() => openStep(view.next!.key)}>
                {t("go_to_arrow", { step: view.next.name })}
              </button>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

/** Select a node and bring it into view when the panel shows it, and again
    each time it's picked in the selector. */
function useFocus(nodeId: string | undefined) {
  const jump = useCanvas((s) => s.jump);
  const flow = useReactFlow();
  // Nodes can only be fitted once React Flow has measured them: right after
  // the canvas mounts (say, switching from the basic view), wait for that.
  const measured = useNodesInitialized();
  const focused = useRef<string | undefined>(undefined);
  useEffect(() => {
    const target = `${nodeId}:${jump}`;
    if (!nodeId || !measured || focused.current === target) return;
    focused.current = target;
    useCanvas.setState((s) => ({
      flowNodes: s.flowNodes.map((n) =>
        n.selected === (n.id === nodeId) ? n : { ...n, selected: n.id === nodeId },
      ),
    }));
    void flow.fitView({ nodes: [{ id: nodeId }], duration: 350, maxZoom: 1, padding: 0.6 });
  }, [nodeId, jump, measured, flow]);
}
