// Running a workflow step, the same in every view (the canvas's step panel
// and the basic view's step page): its two forms (with AI, or by hand), the
// run's prompt and count, generating its nodes, and downloading its results.
import { useCallback, useMemo, useState } from "react";
import {
  MAX_RUN_ITEMS,
  isActive,
  nodeLabel,
  idMap,
  mentionedIds,
  parseCount,
  type ErrorResponse,
} from "../api/types";
import { ApiError, authedFetch } from "../api/client";
import { MentionBox } from "../canvas/MentionPrompt";
import { errorText, useT, type Key } from "../i18n";
import { useCanvas } from "../store/canvas";
import { confirmReplace, confirmVideos } from "./confirm";
import { ManualForm } from "./ManualForm";
import { carriedForward, stepViews, type StepState, type StepView } from "./status";

/** What a step's state pill says. */
export const STEP_STATE_LABELS: Record<StepState, Key> = {
  ready: "pill_ready",
  in_progress: "pill_in_progress",
  done: "pill_done",
};

export function useStepViews(): StepView[] {
  const project = useCanvas((s) => s.project);
  const nodes = useCanvas((s) => s.nodes);
  const runs = useCanvas((s) => s.runs);
  return useMemo(
    () => (project ? stepViews(project.workflow, nodes, runs) : []),
    [project, nodes, runs],
  );
}

/** Every result of the step (each node's chosen take) as one zip, named in
    the nodes' order: "<step>_01.png", "<step>_02.png", ... */
export function DownloadAll({ view }: { view: StepView }) {
  const t = useT();
  const projectId = useCanvas((s) => s.project?.id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const download = async () => {
    if (!projectId || busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await authedFetch(
        `/api/projects/${projectId}/workflow/steps/${encodeURIComponent(view.step.key)}/download`,
      );
      if (!response.ok) {
        throw new ApiError(response.status, (await response.json()) as ErrorResponse);
      }
      const disposition = response.headers.get("Content-Disposition") ?? "";
      const match = /filename\*=UTF-8''([^;]+)/.exec(disposition);
      const name = match ? decodeURIComponent(match[1]!) : `${view.step.key}.zip`;
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(false);
  };

  return (
    <>
      {error && (
        <p className="step-panel__error step-panel__download-error" role="alert">
          {error}
        </p>
      )}
      <button
        className="button"
        disabled={busy}
        onClick={() => void download()}
        title={t("download_all_title")}
      >
        {busy ? t("download_preparing") : t("download_all")}
      </button>
    </>
  );
}

/** What the workflow says this step is for (written on the Workflows page;
    read-only in a project). */
export function StepDescription({ view }: { view: StepView }) {
  const text = view.step.description.trim();
  return text ? <p className="step-desc">{text}</p> : null;
}

/** Two ways to complete a step: run it with AI, or give its results by
    hand. It opens the way it was last completed. */
export function StepForms({ view }: { view: StepView }) {
  const t = useT();
  const [mode, setMode] = useState<"ai" | "manual">(view.run?.manual ? "manual" : "ai");
  return (
    <>
      <div className="mode-switch" role="tablist" aria-label={t("mode_aria")}>
        {(["ai", "manual"] as const).map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={mode === m}
            className={mode === m ? "is-active" : ""}
            onClick={() => setMode(m)}
          >
            {m === "ai" ? t("mode_ai") : t("mode_manual")}
          </button>
        ))}
      </div>
      {mode === "ai" ? <RunForm view={view} /> : <ManualForm view={view} />}
    </>
  );
}

/** What the prompt box and the run's note say about the nodes it can use:
    which mentioned IDs can't be sent (no output yet), and what earlier steps
    send by themselves. Recomputed when the prompt or the graph changes, not on
    every job poll. */
function useRunMentions(prompt: string, stepKey: string) {
  const nodes = useCanvas((s) => s.nodes);
  const workflow = useCanvas((s) => s.project?.workflow);
  // Mentioned nodes are sent with the prompt: ones with an output, and not
  // this step's own (a run replaces them).
  const usable = useMemo(
    () =>
      new Set(
        Object.values(nodes)
          .filter((n) => n.selected_output_id && n.workflow_step !== stepKey)
          .map((n) => n.id),
      ),
    [nodes, stepKey],
  );
  const mentioned = useMemo(() => mentionedIds(prompt, idMap(nodes)), [prompt, nodes]);
  const hasOutput = useCallback((id: string) => usable.has(id), [usable]);
  const unused = useMemo(
    () => mentioned.filter((id) => !usable.has(id)).map((id) => nodes[id]?.name ?? "?"),
    [mentioned, usable, nodes],
  );
  // What earlier steps settled on goes along by itself (not this run's own
  // mentions: those are references anyway).
  const carried = useMemo(() => {
    if (!workflow) return [];
    const skip = new Set(mentioned);
    return carriedForward(workflow, nodes, stepKey)
      .filter((n) => !skip.has(n.id))
      .map(nodeLabel);
  }, [workflow, nodes, stepKey, mentioned]);
  return { hasOutput, unused, carried };
}

/** Stands in for the step's name in the translated count label, so the name
    can be set in italics wherever the language puts it. */
const MARK = "\u0000";

function CountLabel({ text, step }: { text: string; step: string }) {
  const [before, after = ""] = text.split(MARK);
  return (
    <span>
      {before}
      <em>{step}</em>
      {after}
    </span>
  );
}

/** The step's prompt and count, and the button that runs it. An image or
    video step goes in two parts: (1) the AI fills in each node's prompt
    (and each video's length), to check and edit; then (2) they're
    generated. */
function RunForm({ view }: { view: StepView }) {
  const t = useT();
  const runStep = useCanvas((s) => s.runStep);
  const [prompt, setPrompt] = useState(view.run?.prompt ?? "");
  // The last run's count, else the workflow's default for the step; none:
  // the field starts empty and asks for one.
  const [count, setCount] = useState<number | null>(view.run?.count ?? view.step.count ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // The run happens on the server: it may still be going after a reload.
  const running = busy || view.run?.status === "running";
  const runError = error || (view.run?.status === "failed" ? (view.run.error ?? "") : "");
  const kind = view.step.kind;
  const media = kind !== "text";
  const { hasOutput, unused, carried } = useRunMentions(prompt, view.step.key);

  const run = async () => {
    if (count === null || running) return;
    if (!confirmReplace(view.nodes)) return;
    setBusy(true);
    setError((await runStep(view.step.key, prompt.trim(), count)) ?? "");
    setBusy(false);
  };

  return (
    <section className="run" aria-label={view.step.name}>
      <label className="step-panel__label" htmlFor={`run-${view.step.key}`}>
        {t("run_instruction")}
      </label>
      <MentionBox
        id={`run-${view.step.key}`}
        className="run__box"
        inputClassName="run__prompt"
        value={prompt}
        maxLength={4000}
        placeholder=""
        onChange={setPrompt}
        isLinked={hasOutput}
        onSubmit={() => void run()}
      />
      {unused.length > 0 && (
        <p className="step-panel__muted">{t("run_mention_unused", { ids: unused.join(", ") })}</p>
      )}
      <div className="step-panel__actions">
        <label className="run__count">
          <CountLabel text={t("run_count", { step: MARK })} step={view.step.name} />
          <input
            type="number"
            min={1}
            max={MAX_RUN_ITEMS}
            value={count ?? ""}
            aria-invalid={count === null}
            className={count === null ? "is-invalid" : undefined}
            onChange={(e) => setCount(parseCount(e.target.value))}
          />
        </label>
        <button
          // A media step's run only fills in: its part 1 (part 2 generates).
          className={`button${media && view.nodes.length ? "" : " button--primary"}`}
          disabled={count === null || running}
          onClick={() => void run()}
        >
          {media && <span className="run__part">1</span>}
          {runLabel(t, { running, media, count, hasNodes: view.nodes.length > 0 })}
        </button>
        {running && <span className="spinner" />}
      </div>
      {media && <GenerateStep view={view} filling={running} />}
      {carried.length > 0 && (
        <p className="step-panel__muted run__carried">
          {t("run_carried", { names: carried.join(", ") })}
        </p>
      )}
      {count === null && (
        <p className="step-panel__error" role="alert">
          {t("run_count_missing")}
        </p>
      )}
      {runError && !running && (
        <p className="step-panel__error" role="alert">
          {runError}
        </p>
      )}
    </section>
  );
}

/** The run button's text. */
function runLabel(
  t: ReturnType<typeof useT>,
  o: { running: boolean; media: boolean; count: number | null; hasNodes: boolean },
): string {
  if (o.running) return o.media ? t("run_filling") : t("generating");
  if (o.count === null) return o.media ? t("run_fill_plain") : t("run_go_plain");
  const n = o.count;
  if (o.media) return o.hasNodes ? t("run_refill", { n }) : t("run_fill", { n });
  return o.hasNodes ? t("run_again", { n }) : t("run_go", { n });
}

/** Part 2 of a media step: generate the filled-in nodes. */
function GenerateStep({
  view,
  filling,
}: {
  view: StepView;
  filling: boolean;
}) {
  const t = useT();
  const generateStep = useCanvas((s) => s.generateStep);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const nodes = view.nodes;
  // One selector returning a number, so a poll of an unrelated job doesn't
  // re-render this.
  const generating = useCanvas((s) => nodes.filter((n) => isActive(s.jobs[n.id])).length);
  const todo = nodes.length - generating;
  const blank = nodes.filter((n) => !n.prompt.trim()).length;
  const ready = nodes.length > 0 && !filling && blank === 0 && todo > 0 && !busy;

  const go = async () => {
    if (!ready || !confirmVideos(view.step.kind, todo)) return;
    setBusy(true);
    setError((await generateStep(view.step.key)) ?? "");
    setBusy(false);
  };

  return (
    <>
      <div className="step-panel__actions">
        <button
          className={`button${nodes.length && !filling ? " button--primary" : ""}`}
          disabled={!ready}
          onClick={() => void go()}
        >
          <span className="run__part">2</span>
          {!nodes.length
            ? t("run_go_plain")
            : view.made === nodes.length
              ? t("run_again", { n: todo })
              : t("run_go", { n: todo || nodes.length })}
        </button>
        {generating > 0 && (
          <span className="step-panel__muted">
            <span className="spinner" /> {t("gen_running", { n: generating })}
          </span>
        )}
      </div>
      {!filling && (
        <p className="step-panel__muted">
          {!nodes.length ? t("gen_fill_first") : blank ? t("gen_blank", { n: blank }) : null}
        </p>
      )}
      {error && (
        <p className="step-panel__error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

/** The step's nodes by number: picking one moves the view to it. */
export function NodePicker({ view, current }: { view: StepView; current: string | null }) {
  const jumpToNode = useCanvas((s) => s.jumpToNode);
  const jobs = useCanvas((s) => s.jobs);
  return (
    <div className="items__list" role="listbox" aria-label={view.step.name}>
      {view.nodes.map((n) => {
        const busy = isActive(jobs[n.id]);
        const state = n.selected_output_id ? "done" : "draft";
        return (
          <button
            key={n.id}
            role="option"
            aria-selected={n.id === current}
            className={`item-chip item-chip--${state}${n.id === current ? " is-active" : ""}`}
            onClick={() => jumpToNode(view.step.key, n.id)}
          >
            {busy ? "… " : ""}
            {n.workflow_item}
          </button>
        );
      })}
    </div>
  );
}
