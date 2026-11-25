// Where a project stands in its workflow, worked out from its runs and
// nodes. A step is "done" once it has been run and all its nodes have an
// output; nothing here is stored.
import {
  idMap,
  mentionedIds,
  type Edge,
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

/** The first step that isn't done. */
export function currentStep(views: StepView[]): StepView | undefined {
  return views.find((v) => v.state !== "done") ?? views[views.length - 1];
}

/**
 * What a run of step `key` is given by itself from earlier steps (mirrors
 * the backend's Store.carried_forward): each earlier step's results that
 * have an output -- all of them, none, or for a step that carries only
 * what's used, those used (a link's source, or mentioned in another step's run
 * prompt). Returned as the nodes, in order.
 */
export function carriedForward(
  workflow: WorkflowDefinition,
  nodes: Record<string, Node>,
  edges: Edge[],
  runs: Record<string, StepRun>,
  key: string,
): Node[] {
  const index = workflow.steps.findIndex((s) => s.key === key);
  if (index < 0) return [];
  const ids = idMap(nodes);
  const used = new Set(edges.map((e) => e.source_node_id));
  for (const run of Object.values(runs)) {
    for (const id of mentionedIds(run.prompt, ids)) {
      if (nodes[id]?.workflow_step !== run.step) used.add(id);
    }
  }
  return workflow.steps.slice(0, index).flatMap((step) => {
    if (step.carry === "none") return [];
    return stepNodes(nodes, step.key).filter(
      (n) => n.selected_output_id && (step.carry !== "used" || used.has(n.id)),
    );
  });
}
