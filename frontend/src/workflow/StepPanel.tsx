// The side panel for one workflow step: a prompt and a count, sent (with the
// project instruction and the step before's results) to make that many
// nodes; then each node's output, its versions, and, for text, a chat.
import { useReactFlow } from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { MAX_RUN_ITEMS, TERMINAL_JOB_STATUSES, type Node, type Output } from "../api/types";
import { MentionPrompt } from "../canvas/MentionPrompt";
import { useT, type Key } from "../i18n";
import { useCanvas } from "../store/canvas";
import { ChatThread } from "./ChatThread";
import { stepViews, type StepState, type StepView } from "./status";

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
        <RunForm key={view.step.key} view={view} />
        {view.nodes.length > 1 && <NodePicker view={view} current={node} />}
        {node && <NodeWork key={node.id} node={node} />}
        {view.next && view.state === "done" && (
          <div className="step-panel__continue">
            <button className="button button--primary" onClick={() => openStep(view.next!.key)}>
              {t("go_to_arrow", { step: view.next.name })}
            </button>
          </div>
        )}
      </div>
    </aside>
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

/** The step's prompt and count, and the button that runs it. */
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
  const media = view.step.kind !== "text";
  // After a one-to-one step, there is one node per result of that step.
  const fedBy = view.previous?.output === "one_to_one" ? view.previous : null;
  const sources = useCanvas(
    useShallow((s) =>
      fedBy ? Object.values(s.nodes).filter((n) => n.workflow_step === fedBy.key) : [],
    ),
  );
  const fedOutputs = useCanvas(
    useShallow((s) =>
      sources.map((n) => (n.selected_output_id ? s.outputs[n.selected_output_id]?.kind : undefined)),
    ),
  );
  // Media fed by text: each text is its node's prompt; the prompt is optional.
  const direct = Boolean(fedBy) && media && fedOutputs.length > 0 && fedOutputs.every((k) => k === "text");
  const total = fedBy ? sources.length : (count ?? 0);
  const missingCount = !fedBy && count === null;
  const ready =
    (direct || Boolean(prompt.trim())) && (!fedBy || sources.length > 0) && !missingCount;
  const example = useCanvas(
    (s) => Object.values(s.nodes).find((n) => n.name && n.workflow_step)?.name ?? "dishes_1",
  );

  const run = async () => {
    if (!ready || running) return;
    if (view.nodes.length && !window.confirm(t("run_replace", { n: view.nodes.length }))) return;
    if (view.step.kind === "video" && !window.confirm(t("generate_all_confirm", { n: total }))) {
      return;
    }
    setBusy(true);
    setError((await runStep(view.step.key, prompt.trim(), fedBy ? null : count)) ?? "");
    setBusy(false);
  };

  return (
    <section className="run" aria-label={view.step.name}>
      <label className="step-panel__label" htmlFor={`run-${view.step.key}`}>
        {direct ? t("run_direction") : t("run_prompt")}
      </label>
      <textarea
        id={`run-${view.step.key}`}
        className="run__prompt"
        rows={3}
        value={prompt}
        maxLength={4000}
        placeholder={t("run_prompt_ph")}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void run();
        }}
      />
      <div className="step-panel__actions">
        {!fedBy && (
          <label className="run__count">
            {t("run_count")}
            <input
              type="number"
              min={1}
              max={MAX_RUN_ITEMS}
              value={count ?? ""}
              aria-invalid={missingCount}
              className={missingCount ? "is-invalid" : undefined}
              onChange={(e) => {
                const raw = e.target.value.trim();
                const n = Math.floor(Number(raw));
                setCount(
                  raw === "" || !Number.isFinite(n) ? null : Math.max(1, Math.min(MAX_RUN_ITEMS, n)),
                );
              }}
            />
          </label>
        )}
        <button
          className="button button--primary"
          disabled={!ready || running}
          onClick={() => void run()}
        >
          {running
            ? t("generating")
            : missingCount
              ? t("run_go_plain")
              : view.nodes.length
                ? t("run_again", { n: total })
                : t("run_go", { n: total })}
        </button>
        {running && <span className="spinner" />}
      </div>
      <p className="step-panel__muted">
        {fedBy
          ? direct
            ? t("run_direct_note", { step: fedBy.name })
            : t("run_uses_previous", { step: fedBy.name, n: sources.length })
          : t("run_uses_instruction", { example })}
        {media && !direct ? ` ${t("run_media_note")}` : ""}
      </p>
      {missingCount && (
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
          <div className="step-panel__actions">
            {busy ? (
              <button className="button" onClick={() => void cancel(node.id)}>
                {t("cancel")}
              </button>
            ) : (
              <button
                className="button button--primary"
                disabled={!node.prompt.trim()}
                onClick={() => void generate(node.id)}
              >
                {node.selected_output_id ? t("generate_again") : t("generate")}
              </button>
            )}
            {busy && (
              <span className="step-panel__muted">
                <span className="spinner" /> {job?.status === "queued" ? t("queued") : t("generating")}
              </span>
            )}
          </div>
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
