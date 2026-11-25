// The side panel for one workflow step: a prompt and a count, sent (with the
// instructions and what earlier steps settled on) to make that many nodes;
// then each node's output, its versions, and, for text, a chat.
import { useReactFlow } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import {
  MAX_RUN_ITEMS,
  TERMINAL_JOB_STATUSES,
  idMap,
  mentionedIds,
  parseCount,
  type ErrorResponse,
  type MediaKind,
  type Node,
  type Output,
} from "../api/types";
import { ApiError, authedFetch } from "../api/client";
import { DurationSelect } from "../canvas/ParamSelect";
import { MentionBox, MentionPrompt } from "../canvas/MentionPrompt";
import { errorText, useT, type Key } from "../i18n";
import { useCanvas } from "../store/canvas";
import { ChatThread } from "./ChatThread";
import { confirmReplace, confirmVideos } from "./confirm";
import { ManualForm } from "./ManualForm";
import { carriedForward, stepViews, type StepState, type StepView } from "./status";

const STATE_LABELS: Record<StepState, Key> = {
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
        <span className={`state-pill state-pill--${view.state}`}>{t(STATE_LABELS[view.state])}</span>
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
        <StepForms key={view.step.key} view={view} />
        {view.nodes.length > 1 && <NodePicker view={view} current={node} />}
        {node && <NodeWork key={node.id} node={node} />}
        {view.state === "done" && (
          <div className="step-panel__continue">
            <DownloadAll view={view} />
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

/** Every result of the step (each node's chosen take) as one zip, named in
    the nodes' order: "<step>_01.png", "<step>_02.png", ... */
function DownloadAll({ view }: { view: StepView }) {
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

/** Select a node and bring it into view when the panel shows it. */
function useFocus(nodeId: string | undefined) {
  const flow = useReactFlow();
  useEffect(() => {
    if (!nodeId) return;
    useCanvas.setState((s) => ({
      flowNodes: s.flowNodes.map((n) =>
        n.selected === (n.id === nodeId) ? n : { ...n, selected: n.id === nodeId },
      ),
    }));
    void flow.fitView({ nodes: [{ id: nodeId }], duration: 350, maxZoom: 1, padding: 0.6 });
  }, [nodeId, flow]);
}

/** Two ways to complete a step: run it with AI, or give its results by
    hand. It opens the way it was last completed. */
function StepForms({ view }: { view: StepView }) {
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
  const edges = useCanvas((s) => s.edges);
  const runs = useCanvas((s) => s.runs);
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
    return carriedForward(workflow, nodes, edges, runs, stepKey)
      .filter((n) => !skip.has(n.id))
      .map((n) => n.name ?? `#${n.workflow_item ?? ""}`);
  }, [workflow, nodes, edges, runs, stepKey, mentioned]);
  return { hasOutput, unused, carried };
}

// What the note under a media step's form says: the run only fills in the
// prompts (to check; then generate), or generates them right away (the
// collection's "generate directly").
const MEDIA_NOTES = {
  fill: { image: "run_media_note", video: "run_media_note_video" },
  direct: { image: "run_direct_note", video: "run_direct_note_video" },
} as const;

/** The step's prompt and count, and the button that runs it. An image or
    video step goes in two parts: (1) the AI fills in each node's prompt
    (and each video's length), to check and edit; then (2) they're
    generated -- unless the collection generates that kind directly, when
    one click does both. */
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
  const direct = useCanvas((s) =>
    kind === "image" ? !!s.project?.direct_image : kind === "video" && !!s.project?.direct_video,
  );
  // Filling in only: the media steps' part 1 (part 2 generates).
  const fillOnly = media && !direct;
  const { hasOutput, unused, carried } = useRunMentions(prompt, view.step.key);
  const example = useCanvas(
    (s) => Object.values(s.nodes).find((n) => n.name && n.workflow_step)?.name ?? "dishes_1",
  );

  const run = async () => {
    if (count === null || running) return;
    if (!confirmReplace(view.nodes)) return;
    // Generating videos directly pays for them: ask, as Generate does.
    if (direct && !confirmVideos(kind, count)) return;
    setBusy(true);
    setError((await runStep(view.step.key, prompt.trim(), count)) ?? "");
    setBusy(false);
  };

  return (
    <section className="run" aria-label={view.step.name}>
      <label className="step-panel__label" htmlFor={`run-${view.step.key}`}>
        {t("run_prompt_optional")}
      </label>
      <MentionBox
        id={`run-${view.step.key}`}
        className="run__box"
        inputClassName="run__prompt"
        value={prompt}
        maxLength={4000}
        placeholder={t("run_prompt_ph")}
        onChange={setPrompt}
        isLinked={hasOutput}
        onSubmit={() => void run()}
      />
      {unused.length > 0 && (
        <p className="step-panel__muted">{t("run_mention_unused", { ids: unused.join(", ") })}</p>
      )}
      <div className="step-panel__actions">
        <label className="run__count">
          {t("run_count")}
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
          className={`button${fillOnly && view.nodes.length ? "" : " button--primary"}`}
          disabled={count === null || running}
          onClick={() => void run()}
        >
          {fillOnly && <span className="run__part">1</span>}
          {runLabel(t, { running, fillOnly, count, hasNodes: view.nodes.length > 0 })}
        </button>
        {running && <span className="spinner" />}
      </div>
      {media && <GenerateStep view={view} filling={running} direct={direct} />}
      {carried.length > 0 && (
        <p className="step-panel__muted run__carried">
          {t("run_carried", { names: carried.join(", ") })}
        </p>
      )}
      <p className="step-panel__muted">
        {t("run_uses_instruction", { example })}
        {media ? ` ${t(MEDIA_NOTES[direct ? "direct" : "fill"][kind as Exclude<MediaKind, "text">])}` : ""}
      </p>
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
  o: { running: boolean; fillOnly: boolean; count: number | null; hasNodes: boolean },
): string {
  if (o.running) return o.fillOnly ? t("run_filling") : t("generating");
  if (o.count === null) return o.fillOnly ? t("run_fill_plain") : t("run_go_plain");
  const n = o.count;
  if (o.fillOnly) return o.hasNodes ? t("run_refill", { n }) : t("run_fill", { n });
  return o.hasNodes ? t("run_again", { n }) : t("run_go", { n });
}

/** Part 2 of a media step: generate the filled-in nodes. When the
    collection generates directly (the run does it), only what's left over
    shows: nodes generating, and a button for any neither made nor
    generating (say, a run that hit a daily limit). */
function GenerateStep({
  view,
  filling,
  direct,
}: {
  view: StepView;
  filling: boolean;
  direct: boolean;
}) {
  const t = useT();
  const generateStep = useCanvas((s) => s.generateStep);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const nodes = view.nodes;
  // How many are generating, and how many have no output and aren't: one
  // selector, so a poll of an unrelated job doesn't re-render this.
  const { generating, leftOver } = useCanvas(
    useShallow((s) => {
      let generating = 0;
      let leftOver = 0;
      for (const n of nodes) {
        const job = s.jobs[n.id];
        if (job !== undefined && !TERMINAL_JOB_STATUSES.includes(job.status)) generating += 1;
        else if (!n.selected_output_id) leftOver += 1;
      }
      return { generating, leftOver };
    }),
  );
  const todo = nodes.length - generating;
  const blank = nodes.filter((n) => !n.prompt.trim()).length;
  const made = nodes.filter((n) => n.selected_output_id).length;
  const ready = nodes.length > 0 && !filling && blank === 0 && todo > 0 && !busy;

  const go = async () => {
    if (!ready || !confirmVideos(view.step.kind, todo)) return;
    setBusy(true);
    setError((await generateStep(view.step.key)) ?? "");
    setBusy(false);
  };

  if (direct && !filling && leftOver === 0 && generating === 0 && !error) return null;

  return (
    <>
      <div className="step-panel__actions">
        {(!direct || (!filling && leftOver > 0)) && (
          <button
            className={`button${nodes.length && !filling ? " button--primary" : ""}`}
            disabled={!ready}
            onClick={() => void go()}
          >
            {!direct && <span className="run__part">2</span>}
            {!nodes.length
              ? t("run_go_plain")
              : made === nodes.length
                ? t("run_again", { n: todo })
                : t("run_go", { n: todo || nodes.length })}
          </button>
        )}
        {generating > 0 && (
          <span className="step-panel__muted">
            <span className="spinner" /> {t("gen_running", { n: generating })}
          </span>
        )}
      </div>
      {!filling && !direct && (
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

function NodePicker({ view, current }: { view: StepView; current: Node | undefined }) {
  const openStep = useCanvas((s) => s.openStep);
  const jobs = useCanvas((s) => s.jobs);
  return (
    <div className="items__list" role="listbox" aria-label={view.step.name}>
      {view.nodes.map((n) => {
        const job = jobs[n.id];
        const busy = job !== undefined && !TERMINAL_JOB_STATUSES.includes(job.status);
        const state = n.selected_output_id ? "approved" : "draft";
        return (
          <button
            key={n.id}
            role="option"
            aria-selected={n.id === current?.id}
            className={`item-chip item-chip--${state}${n.id === current?.id ? " is-active" : ""}`}
            onClick={() => openStep(view.step.key, n.id)}
          >
            {busy ? "… " : ""}
            {n.workflow_item}
          </button>
        );
      })}
    </div>
  );
}

function NodeWork({ node }: { node: Node }) {
  const t = useT();
  const job = useCanvas((s) => s.jobs[node.id]);
  const nodeError = useCanvas((s) => s.nodeErrors[node.id]);
  const generate = useCanvas((s) => s.generate);
  const cancel = useCanvas((s) => s.cancel);
  const busy = job !== undefined && !TERMINAL_JOB_STATUSES.includes(job.status);
  const failed = job?.status === "failed" ? job.error : undefined;
  const isText = node.kind === "text";

  return (
    <div className="node-work">
      <h3 className="step-panel__subhead">
        #{node.workflow_item}
        <span className="step-panel__id">{node.name}</span>
      </h3>
      {!isText && (
        <>
          <label className="step-panel__label">{t("label_prompt")}</label>
          <MentionPrompt
            nodeId={node.id}
            className="step-panel__prompt"
            ariaLabel={t("label_prompt")}
            placeholder={t("ph_shot")}
            onGenerate={() => !busy && void generate(node.id)}
          />
          {node.params.kind === "video" && <VideoLength node={node} />}
          {/* One node is made again from the canvas (its own Generate); the
              panel only shows progress and can cancel. */}
          {busy && (
            <div className="step-panel__actions">
              <button className="button" onClick={() => void cancel(node.id)}>
                {t("cancel")}
              </button>
              <span className="step-panel__muted">
                <span className="spinner" /> {job?.status === "queued" ? t("queued") : t("generating")}
              </span>
            </div>
          )}
        </>
      )}
      {(nodeError || failed) && (
        <p className="step-panel__error" role="alert">
          {nodeError ?? failed}
        </p>
      )}
      <Takes node={node} />
      {isText && <ChatThread nodeId={node.id} />}
    </div>
  );
}

/** A video node's length, as the AI filled it in (editable). */
function VideoLength({ node }: { node: Node }) {
  const t = useT();
  const setParams = useCanvas((s) => s.setParams);
  const params = node.params;
  if (params.kind !== "video") return null;
  return (
    <label className="step-panel__inline">
      {t("label_length")}
      <DurationSelect
        label={t("label_length")}
        value={params.duration_s}
        onChange={(duration_s) => setParams(node.id, { ...params, duration_s })}
      />
    </label>
  );
}

function Takes({ node }: { node: Node }) {
  const t = useT();
  const outputs = useCanvas((s) => s.outputs);
  const selectTake = useCanvas((s) => s.selectTake);
  const addTake = useCanvas((s) => s.addTake);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState("");
  const takes: Output[] = Object.values(outputs)
    .filter((o) => o.node_id === node.id)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  if (!takes.length) return null;
  const index = Math.max(
    0,
    takes.findIndex((o) => o.id === node.selected_output_id),
  );
  const take = takes[index]!;

  return (
    <section className="take" aria-label={t("versions_aria")}>
      <div className="take__head">
        <button
          className="icon-button icon-button--plain"
          disabled={index === 0}
          onClick={() => selectTake(node.id, takes[index - 1]!.id)}
          aria-label={t("prev_version")}
        >
          ‹
        </button>
        <span>{t("version_of", { n: index + 1, total: takes.length })}</span>
        <button
          className="icon-button icon-button--plain"
          disabled={index === takes.length - 1}
          onClick={() => selectTake(node.id, takes[index + 1]!.id)}
          aria-label={t("next_version")}
        >
          ›
        </button>
      </div>
      {editing !== null ? (
        <div className="take__edit">
          <textarea
            className="take__editor"
            value={editing}
            onChange={(e) => setEditing(e.target.value)}
            aria-label={t("edit_version_aria")}
          />
          {error && (
            <p className="step-panel__error" role="alert">
              {error}
            </p>
          )}
          <div className="step-panel__actions">
            <button
              className="button button--primary"
              disabled={!editing.trim() || editing === take.text}
              onClick={async () => {
                const problem = await addTake(node.id, editing);
                if (problem) setError(problem);
                else {
                  setEditing(null);
                  setError("");
                }
              }}
            >
              {t("save_new_version")}
            </button>
            <button className="button" onClick={() => (setEditing(null), setError(""))}>
              {t("cancel")}
            </button>
          </div>
        </div>
      ) : (
        <div className="take__body">
          {take.kind === "text" && <p className="take__text">{take.text}</p>}
          {take.kind === "video" && take.asset && (
            <video src={take.asset.url} controls playsInline className="take__media" />
          )}
          {take.kind === "image" && take.asset && (
            <img src={take.asset.url} alt="" className="take__media" />
          )}
        </div>
      )}
      {editing === null && take.kind === "text" && (
        <div className="step-panel__actions">
          <button className="button" onClick={() => setEditing(take.text ?? "")}>
            {t("edit")}
          </button>
        </div>
      )}
    </section>
  );
}
