// The workflow bar under the project header: every step with its state,
// starting with step 0 ("Describe this video"). The step the project is at is
// highlighted; clicking a step opens it: in the side panel on the canvas, as
// the page in the basic view (where each step with results also lists them
// underneath).
import { StepResults } from "../basic/StepResults";
import { useT, type Key } from "../i18n";
import { useShownView } from "../projectView";
import { useCanvas } from "../store/canvas";
import { useView } from "../store/view";
import { useAboutStep, useStepViews } from "./StepRun";
import { currentStepKey, type StepState } from "./status";

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
  const about = useAboutStep();
  const collapsed = useView((s) => s.stripCollapsed);
  const setCollapsed = useView((s) => s.setStripCollapsed);
  const basic = useShownView() === "basic";
  if (!project) return null;
  const current = currentStepKey(project.description, views);
  // Step 0, then the workflow's own.
  const items = [
    { key: about.key, number: 0, label: about.name, state: about.state, view: undefined },
    ...views.map((view) => ({
      key: view.step.key,
      number: view.index + 1,
      label: view.step.name,
      state: view.state,
      view,
    })),
  ];
  const hasResults = basic && views.some((v) => v.made > 0);

  return (
    <nav className={`wf-bar${basic ? " wf-bar--basic" : ""}`} aria-label={t("wf_aria")}>
      <span className="wf-bar__title">{project.workflow.name}</span>
      <ol className="wf-bar__steps">
        {items.map(({ key, number, label, state, view }) => {
          const isCurrent = current === key;
          const active = activeStep === key;
          return (
            <li key={key} className="wf-bar__item">
              {number > 0 && <span className="wf-bar__line" aria-hidden="true" />}
              {/* The step, and under it (basic view) what it made: one
                  column, so they're as wide as each other. */}
              <div className="wf-bar__column">
                <button
                  className={`wf-step wf-step--${state}${isCurrent ? " is-current" : ""}${
                    active ? " is-active" : ""
                  }`}
                  aria-current={isCurrent ? "step" : undefined}
                  aria-pressed={active}
                  title={`${label}: ${t(STATE_TITLES[state])}`}
                  // On the canvas a second click closes the step's panel; in the
                  // basic view a step is a page, so it stays open.
                  onClick={() =>
                    // A basic page opens at its top, not scrolled to a node.
                    openStep(
                      active && !basic ? null : key,
                      basic ? null : (view?.nodes[0]?.id ?? null),
                    )
                  }
                >
                  <span className="wf-step__dot" aria-hidden="true">
                    {state === "done" ? "✓" : number}
                  </span>
                  <span className="wf-step__label">{label}</span>
                  {view && view.nodes.length > 0 && (
                    <span className="wf-step__count">
                      {view.made}/{view.nodes.length}
                    </span>
                  )}
                </button>
                {basic && !collapsed && view && <StepResults name={label} nodes={view.nodes} />}
              </div>
            </li>
          );
        })}
      </ol>
      {hasResults && (
        <button
          className="icon-button icon-button--plain wf-bar__fold"
          onClick={() => setCollapsed(!collapsed)}
          aria-expanded={!collapsed}
          title={t(collapsed ? "strip_expand" : "strip_collapse")}
          aria-label={t(collapsed ? "strip_expand" : "strip_collapse")}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d={collapsed ? "M4 6l4 4 4-4" : "M4 10l4-4 4 4"} />
          </svg>
        </button>
      )}
    </nav>
  );
}
