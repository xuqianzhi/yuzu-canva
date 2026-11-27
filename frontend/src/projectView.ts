// Which view a project is shown in.
import { useCanvas } from "./store/canvas";
import { useView, type ProjectView } from "./store/view";

/** Whether the project's workflow has steps (the basic view needs them). */
export function useHasSteps(): boolean {
  return useCanvas((s) => (s.project?.workflow.steps.length ?? 0) > 0);
}

/** The view actually shown: the one this viewer picked, except that a
    project without steps has only the canvas. */
export function useShownView(): ProjectView {
  const hasSteps = useHasSteps();
  const picked = useView((s) => s.projectView);
  return hasSteps ? picked : "canvas";
}
