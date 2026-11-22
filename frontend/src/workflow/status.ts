// Where a project stands in its workflow, worked out from its runs and
// nodes. A step is "done" once it has been run and all its nodes have an
// output; nothing here is stored.
import type { Node, StepRun, WorkflowDefinition, WorkflowStep } from "../api/types";

export type StepState =
  /** Not run yet. */
  | "ready"
  /** Run; some nodes still have no output. */
  | "in_progress"
  /** Run, and every node has an output. */
  | "done";

export interface StepView {
  step: WorkflowStep;
  index: number;
  run: StepRun | undefined;
  /** The step's nodes, in run order. */
  nodes: Node[];
  previous: WorkflowStep | null;
  next: WorkflowStep | null;
  state: StepState;
  /** Nodes that have an output. */
  made: number;
}

export function stepNodes(nodes: Record<string, Node>, key: string): Node[] {
  return Object.values(nodes)
    .filter((n) => n.workflow_step === key)
    .sort((a, b) => (a.workflow_item ?? 0) - (b.workflow_item ?? 0));
}

export function stepViews(
  workflow: WorkflowDefinition,
  nodes: Record<string, Node>,
  runs: Record<string, StepRun>,
): StepView[] {
  return workflow.steps.map((step, index) => {
    const own = stepNodes(nodes, step.key);
    const made = own.filter((n) => n.selected_output_id).length;
    const state: StepState = !own.length
      ? "ready"
      : made === own.length
        ? "done"
        : "in_progress";
    return {
      step,
      index,
      run: runs[step.key],
      nodes: own,
      previous: workflow.steps[index - 1] ?? null,
      next: workflow.steps[index + 1] ?? null,
      state,
      made,
    };
  });
}

/** The first step that isn't done. */
export function currentStep(views: StepView[]): StepView | undefined {
  return views.find((v) => v.state !== "done") ?? views[views.length - 1];
}
