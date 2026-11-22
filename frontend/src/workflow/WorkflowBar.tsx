// The workflow bar under the project header: every step with its state.
// The current step (the first that isn't done) is highlighted; clicking a
// step opens it in the side panel.
import { useT, type Key } from "../i18n";
import { useCanvas } from "../store/canvas";
import { useStepViews } from "./StepPanel";
import { currentStep, type StepState } from "./status";

const STATE_TITLES: Record<StepState, Key> = {
  ready: "st_ready",
  in_progress: "st_in_progress",
  done: "pill_done",
};

export function WorkflowBar() {
  const t = useT();
  const project = useCanvas((s) => s.project);
  const activeStep = useCanvas((s) => s.activeStep);
  const openStep = useCanvas((s) => s.openStep);
  const views = useStepViews();
  if (!project || !views.length) return null;
  const current = currentStep(views);

  return (
    <nav className="wf-bar" aria-label={t("wf_aria")}>
      <span className="wf-bar__title">{project.workflow.name}</span>
      <ol className="wf-bar__steps">
        {views.map((view) => {
          const { step, state } = view;
          const isCurrent = current?.step.key === step.key;
          const active = activeStep === step.key;
          const label = step.name;
          return (
            <li key={step.key} className="wf-bar__item">
              {view.index > 0 && <span className="wf-bar__line" aria-hidden="true" />}
              <button
                className={`wf-step wf-step--${state}${isCurrent ? " is-current" : ""}${
                  active ? " is-active" : ""
                }`}
                aria-current={isCurrent ? "step" : undefined}
                aria-pressed={active}
                title={`${label}: ${t(STATE_TITLES[state])}`}
                onClick={() => openStep(active ? null : step.key, view.nodes[0]?.id ?? null)}
              >
                <span className="wf-step__dot" aria-hidden="true">
                  {state === "done" ? "✓" : view.index + 1}
                </span>
                <span className="wf-step__label">{label}</span>
                {view.nodes.length > 0 && (
                  <span className="wf-step__count">
                    {view.made}/{view.nodes.length}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
