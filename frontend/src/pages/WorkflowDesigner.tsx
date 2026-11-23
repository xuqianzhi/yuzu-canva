// A collection's Workflows page: design the steps its projects go through.
// A workflow is an ordered list of steps, each just a name and what it makes
// (text, image, video). Names are the user's text and are never translated.
// A collection has any number of workflows; every project in it runs on the
// active one, so editing or switching it changes every project.
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, unwrap } from "../api/client";
import type {
  CollectionWorkflow,
  MediaKind,
  WorkflowDefinition,
  WorkflowStep,
} from "../api/types";
import { errorText, t as tr, useT } from "../i18n";
import type { CollectionView } from "./HomePage";

type WorkflowTemplate = CollectionWorkflow;

const KINDS: MediaKind[] = ["text", "image", "video"];

/** A key no step has yet (node IDs are "<key>_<n>"). */
function freeKey(steps: WorkflowStep[]): string {
  const taken = new Set(steps.map((s) => s.key));
  let n = steps.length + 1;
  while (taken.has(`step_${n}`)) n++;
  return `step_${n}`;
}

export function WorkflowDesigner({ view }: { view: CollectionView }) {
  const t = useT();
  const collectionId = view.collection.id;
  const [templates, setTemplates] = useState<WorkflowTemplate[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<WorkflowDefinition | null>(null);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (select?: string) => {
    try {
      const list = unwrap(
        await api.GET("/api/collections/{collection_id}/workflows", {
          params: { path: { collection_id: collectionId } },
        }),
      );
      setTemplates(list);
      const chosen = list.find((w) => w.id === select) ?? list.find((w) => w.active) ?? list[0];
      setSelected(chosen?.id ?? null);
      setDraft(chosen ? structuredClone(chosen.definition) : null);
      setDirty(false);
      setError("");
    } catch (e) {
      setError(errorText(e));
    }
  }, [collectionId]);

  useEffect(() => void load(), [load]);

  const current = templates?.find((w) => w.id === selected);
  const pickTemplate = (template: WorkflowTemplate) => {
    if (dirty && !window.confirm(`${tr("wf_unsaved")}?`)) return;
    setSelected(template.id);
    setDraft(structuredClone(template.definition));
    setDirty(false);
    setError("");
  };
  const change = (next: WorkflowDefinition) => {
    // The last step has no next step to feed: its results are independent.
    const last = next.steps.length - 1;
    const steps = next.steps.map((s, i) =>
      i === last && s.output === "one_to_one" ? { ...s, output: "independent" as const } : s,
    );
    setDraft({ ...next, steps });
    setDirty(true);
  };
  const setStep = (index: number, step: WorkflowStep) =>
    draft && change({ ...draft, steps: draft.steps.map((s, i) => (i === index ? step : s)) });
  const run = async (work: () => Promise<string | undefined>) => {
    setBusy(true);
    try {
      await load(await work());
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === "edit_conflict"
          ? tr("conflict", { email: e.body.error.context.by ?? "?" })
          : errorText(e),
      );
    } finally {
      setBusy(false);
    }
  };
  const create = (definition: WorkflowDefinition) =>
    run(
      async () =>
        unwrap(
          await api.POST("/api/collections/{collection_id}/workflows", {
            params: { path: { collection_id: collectionId } },
            body: { definition },
          }),
        ).id,
    );

  return (
    <main className="home__page">
      <div className="home__inner">
        <h1 className="home__title">{t("wf_title")}</h1>
        <p className="home__help">{t("wf_help")}</p>
        {error && (
          <p className="home__error" role="alert">
            {error}
          </p>
        )}
        <div className="designer">
          <nav className="designer__list" aria-label={t("wf_title")}>
            {templates?.map((w) => (
              <button
                key={w.id}
                className={`designer__item${w.id === selected ? " is-active" : ""}`}
                onClick={() => pickTemplate(w)}
              >
                <span>{w.definition.name}</span>
                {w.active && <small className="state-pill">{t("wf_active")}</small>}
              </button>
            ))}
            <button
              className="button"
              disabled={busy}
              onClick={() =>
                void create({
                  id: "new",
                  version: 1,
                  name: t("wf_new_name"),
                  steps: [
                    { key: "step_1", name: t("wf_new_step"), kind: "text", output: "independent" },
                  ],
                })
              }
            >
              + {t("wf_new")}
            </button>
            <CopyFrom collectionId={collectionId} disabled={busy} onPick={(d) => void create(d)} />
          </nav>
          {draft && current ? (
            <section className="designer__editor">
              <div className="designer__head">
                <label className="designer__field designer__field--grow">
                  <span>{t("wf_name")}</span>
                  <input
                    value={draft.name}
                    maxLength={80}
                    placeholder={t("wf_name_ph")}
                    onChange={(e) => change({ ...draft, name: e.target.value })}
                  />
                </label>
                <small className="step-panel__muted">
                  {t("wf_version", { n: current.definition.version })}
                </small>
              </div>
              <div className="step-panel__actions">
                <button
                  className="button button--primary"
                  disabled={!dirty || busy || !draft.name.trim() || draft.steps.some((s) => !s.name.trim())}
                  onClick={() =>
                    void run(async () => {
                      unwrap(
                        await api.PUT("/api/workflows/{workflow_id}", {
                          params: { path: { workflow_id: current.id } },
                          body: { definition: draft, base_version: current.definition.version },
                        }),
                      );
                      return current.id;
                    })
                  }
                >
                  {t("wf_save")}
                </button>
                {dirty && <span className="step-panel__muted">{t("wf_unsaved")}</span>}
                <span className="take__spacer" />
                <button
                  className="button"
                  disabled={busy}
                  onClick={() =>
                    void create({ ...structuredClone(draft), name: t("wf_copy", { name: draft.name }) })
                  }
                >
                  {t("wf_duplicate")}
                </button>
                {!current.active && (
                  <>
                    <button
                      className="button"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          unwrap(
                            await api.POST("/api/workflows/{workflow_id}/activate", {
                              params: { path: { workflow_id: current.id } },
                            }),
                          );
                          return current.id;
                        })
                      }
                    >
                      {t("wf_make_active")}
                    </button>
                    <button
                      className="button"
                      disabled={busy}
                      onClick={() => {
                        if (!window.confirm(t("wf_confirm_delete", { name: current.definition.name }))) {
                          return;
                        }
                        void run(async () => {
                          unwrap(
                            await api.DELETE("/api/workflows/{workflow_id}", {
                              params: { path: { workflow_id: current.id } },
                            }),
                          );
                          return undefined;
                        });
                      }}
                    >
                      {t("delete")}
                    </button>
                  </>
                )}
              </div>
              <ol className="designer__steps">
                {draft.steps.map((step, index) => (
                  <li key={step.key} className="designer__step designer__step--row">
                    <strong className="designer__n">{index + 1}</strong>
                    <label className="designer__field designer__field--grow">
                      <span>{t("wf_step_name")}</span>
                      <input
                        value={step.name}
                        maxLength={80}
                        onChange={(e) => setStep(index, { ...step, name: e.target.value })}
                      />
                    </label>
                    <label className="designer__field">
                      <span>{t("wf_kind")}</span>
                      <select
                        value={step.kind}
                        onChange={(e) => setStep(index, { ...step, kind: e.target.value as MediaKind })}
                      >
                        {KINDS.map((kind) => (
                          <option key={kind} value={kind}>
                            {t(`shape_${kind}`)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="designer__field">
                      <span>{t("wf_output")}</span>
                      <select
                        value={step.output}
                        disabled={index === draft.steps.length - 1}
                        title={index === draft.steps.length - 1 ? t("wf_output_last") : undefined}
                        onChange={(e) =>
                          setStep(index, {
                            ...step,
                            output: e.target.value as WorkflowStep["output"],
                          })
                        }
                      >
                        <option value="independent">{t("wf_output_independent")}</option>
                        <option value="one_to_one">{t("wf_output_one_to_one")}</option>
                      </select>
                    </label>
                    <div className="designer__step-tools">
                      <button
                        className="icon-button icon-button--plain"
                        disabled={index === 0}
                        onClick={() => {
                          const steps = [...draft.steps];
                          [steps[index - 1], steps[index]] = [steps[index]!, steps[index - 1]!];
                          change({ ...draft, steps });
                        }}
                        aria-label={t("wf_move_up")}
                        title={t("wf_move_up")}
                      >
                        ↑
                      </button>
                      <button
                        className="icon-button icon-button--plain"
                        disabled={index === draft.steps.length - 1}
                        onClick={() => {
                          const steps = [...draft.steps];
                          [steps[index + 1], steps[index]] = [steps[index]!, steps[index + 1]!];
                          change({ ...draft, steps });
                        }}
                        aria-label={t("wf_move_down")}
                        title={t("wf_move_down")}
                      >
                        ↓
                      </button>
                      <button
                        className="icon-button"
                        disabled={draft.steps.length === 1}
                        onClick={() =>
                          change({ ...draft, steps: draft.steps.filter((_, i) => i !== index) })
                        }
                        aria-label={t("wf_remove_step")}
                        title={t("wf_remove_step")}
                      >
                        ×
                      </button>
                    </div>
                  </li>
                ))}
              </ol>
              <button
                className="button"
                onClick={() =>
                  change({
                    ...draft,
                    steps: [
                      ...draft.steps,
                      {
                        key: freeKey(draft.steps),
                        name: t("wf_new_step"),
                        kind: "text",
                        output: "independent",
                      },
                    ],
                  })
                }
              >
                + {t("wf_add_step")}
              </button>
            </section>
          ) : (
            <p className="step-panel__muted">{templates === null ? t("loading") : t("wf_empty")}</p>
          )}
        </div>
      </div>
    </main>
  );
}

/** "Copy from…": a workflow from another collection you're in. */
function CopyFrom({
  collectionId,
  disabled,
  onPick,
}: {
  collectionId: string;
  disabled: boolean;
  onPick: (definition: WorkflowDefinition) => void;
}) {
  const t = useT();
  const [options, setOptions] = useState<{ label: string; workflow: CollectionWorkflow }[] | null>(
    null,
  );
  const load = async () => {
    if (options) return;
    try {
      const collections = unwrap(await api.GET("/api/collections")).filter(
        (c) => c.id !== collectionId,
      );
      const lists = await Promise.all(
        collections.map(async (c) => ({
          name: c.name,
          workflows: unwrap(
            await api.GET("/api/collections/{collection_id}/workflows", {
              params: { path: { collection_id: c.id } },
            }),
          ),
        })),
      );
      setOptions(
        lists.flatMap(({ name, workflows }) =>
          workflows.map((w) => ({ label: `${name} · ${w.definition.name}`, workflow: w })),
        ),
      );
    } catch {
      setOptions([]);
    }
  };
  return (
    <select
      className="designer__copy"
      aria-label={t("wf_copy_from")}
      value=""
      disabled={disabled}
      onFocus={() => void load()}
      onPointerDown={() => void load()}
      onChange={(e) => {
        const picked = options?.[Number(e.target.value)];
        if (picked) onPick(structuredClone(picked.workflow.definition));
      }}
    >
      <option value="">{t("wf_copy_from")}</option>
      {options === null && <option disabled>{t("loading")}</option>}
      {options?.length === 0 && <option disabled>{t("wf_copy_none")}</option>}
      {options?.map((option, i) => (
        <option key={option.workflow.id} value={i}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
