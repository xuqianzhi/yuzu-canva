// Where a project stands in its workflow, worked out from its runs and
// nodes. A step is "done" once it has been run and all its nodes have an
// output; nothing here is stored.
import {
  type Node,
  type StepRun,
  type WorkflowDefinition,
  type WorkflowStep,
} from "../api/types";

export type StepState =
  /** Not run yet. */
  | "ready"
  /** Run; some nodes still have no output. */
  | "in_progress"
  /** Run, and every node has an output. */
  | "done";

/** Step 0, "Describe this video", which every project's workflow starts
    with. It isn't part of the workflow's definition: it fills the project's
    description. (No real step key can be spelled like this.) */
export const ABOUT_STEP = "@about";

/** Step 0's state: done once the video is described. */
export function aboutState(description: string): StepState {
  return description.trim() ? "done" : "ready";
}

export interface StepView {
  step: WorkflowStep;
  index: number;
  run: StepRun | undefined;
  /** The step's nodes, in run order. */
  nodes: Node[];
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
      next: workflow.steps[index + 1] ?? null,
      state,
      made,
    };
  });
}

/** The key of the step to be at: step 0 for a project with nothing described
    or made yet, else the first step that isn't done. */
export function currentStepKey(description: string, views: StepView[]): string {
  const untouched = aboutState(description) !== "done" && views.every((v) => v.state === "ready");
  if (untouched) return ABOUT_STEP;
  return (views.find((v) => v.state !== "done") ?? views[views.length - 1])?.step.key ?? ABOUT_STEP;
}

/**
 * What a run of step `key` is given by itself from earlier steps (mirrors
 * the backend's Store.carried_forward): the results with an output of each
 * earlier step that carries all. Returned as the nodes, in order.
 */
export function carriedForward(
  workflow: WorkflowDefinition,
  nodes: Record<string, Node>,
  key: string,
): Node[] {
  const index = workflow.steps.findIndex((s) => s.key === key);
  if (index < 0) return [];
  return workflow.steps
    .slice(0, index)
    .filter((step) => step.carry === "all")
    .flatMap((step) => stepNodes(nodes, step.key).filter((n) => n.selected_output_id));
}
