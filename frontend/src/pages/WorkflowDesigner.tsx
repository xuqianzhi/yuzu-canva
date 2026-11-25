// A collection's Workflows page: design the steps its projects go through.
// A workflow is an ordered list of steps, each just a name and what it makes
// (text, image, video). Names are the user's text and are never translated.
// A collection has any number of workflows; every project in it runs on the
// active one, so editing or switching it changes every project.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, unwrap } from "../api/client";
import {
  MAX_RUN_ITEMS,
  parseCount,
  type CollectionWorkflow,
  type MediaKind,
  type WorkflowDefinition,
  type WorkflowStep,
} from "../api/types";
import { errorText, t as tr, useT } from "../i18n";
import type { CollectionView } from "./HomePage";

type WorkflowTemplate = CollectionWorkflow;

const KINDS: MediaKind[] = ["text", "image", "video"];

interface DragState {
  from: number;
  to: number;
  startY: number;
  dy: number;
}

/** Whether dropping now would change the order (not back into its own place). */
function moves({ from, to }: DragState): boolean {
  return to !== from && to !== from + 1;
}

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
    setDraft(next);
    setDirty(true);
  };
  // Reordering: the step being dragged (`from`), the gap it would land in
  // (`to`: 0 is above the first step), and how far it has moved.
  const [drag, setDrag] = useState<DragState | null>(null);
  const stepList = useRef<HTMLOListElement>(null);
  /** The gap nearest the pointer: before the first row whose middle is below
      it (the dragged row itself counts where it started). */
  const gapAt = (y: number, from: number): number => {
    const rows = [...(stepList.current?.children ?? [])] as HTMLElement[];
    for (let i = 0; i < rows.length; i++) {
      const box = rows[i]!.getBoundingClientRect();
      const top = i === from ? box.top - (drag?.dy ?? 0) : box.top;
      if (y < top + box.height / 2) return i;
    }
    return rows.length;
  };
  /** Move step `from` into gap `to` (an index in the list before moving). */
  const moveStep = (from: number, to: number) => {
    if (!draft || to === from || to === from + 1) return;
    const steps = [...draft.steps];
    const [moved] = steps.splice(from, 1);
    steps.splice(to > from ? to - 1 : to, 0, moved!);
    change({ ...draft, steps });
  };
  const setStep = (index: number, step: WorkflowStep) =>
    draft && change({ ...draft, steps: draft.steps.map((s, i) => (i === index ? step : s)) });
  const run = async (work: () => Promise<string | undefined>) => {
    setBusy(true);
    try {
      await load(await work());
    } catch (e) {
      setError(saveError(e, errorText(e)));
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
        <CollectionSwitches view={view} />
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
                    {
                      key: "step_1",
                      name: t("wf_new_step"),
                      kind: "text",
                      carry: "all",
                      count: null,
                      description: "",
                    },
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
              <ol className="designer__steps" ref={stepList}>
                {draft.steps.map((step, index) => (
                  <li
                    key={step.key}
                    className={[
                      "designer__step designer__step--row",
                      drag?.from === index ? "is-dragging" : "",
                      drag && moves(drag) && drag.to === index ? "is-drop-before" : "",
                      drag && moves(drag) && drag.to === index + 1 && index === draft.steps.length - 1
                        ? "is-drop-after"
                        : "",
                    ].join(" ")}
                    style={drag?.from === index ? { transform: `translateY(${drag.dy}px)` } : undefined}
                  >
                    <button
                      className="designer__grip"
                      aria-label={t("wf_drag_step", { name: step.name })}
                      title={t("wf_drag_hint")}
                      // Drag by the grip: the row follows the pointer, and a line
                      // shows the gap it lands in when released.
                      onPointerDown={(e) => {
                        if (e.button !== 0) return;
                        e.preventDefault();
                        e.currentTarget.setPointerCapture(e.pointerId);
                        setDrag({ from: index, to: index, startY: e.clientY, dy: 0 });
                      }}
                      onPointerMove={(e) => {
                        if (drag?.from !== index) return;
                        setDrag({ ...drag, to: gapAt(e.clientY, index), dy: e.clientY - drag.startY });
                      }}
                      onPointerUp={() => {
                        if (drag?.from === index) moveStep(drag.from, drag.to);
                        setDrag(null);
                      }}
                      onPointerCancel={() => setDrag(null)}
                      onKeyDown={(e) => {
                        if (e.key === "ArrowUp" && index > 0) {
                          e.preventDefault();
                          moveStep(index, index - 1);
                        } else if (e.key === "ArrowDown" && index < draft.steps.length - 1) {
                          e.preventDefault();
                          moveStep(index, index + 2);
                        }
                      }}
                    >
                      <svg viewBox="0 0 10 16" aria-hidden="true">
                        <circle cx="3" cy="3" r="1.2" />
                        <circle cx="7" cy="3" r="1.2" />
                        <circle cx="3" cy="8" r="1.2" />
                        <circle cx="7" cy="8" r="1.2" />
                        <circle cx="3" cy="13" r="1.2" />
                        <circle cx="7" cy="13" r="1.2" />
                      </svg>
                    </button>
                    <strong className="designer__n">{index + 1}</strong>
                    <label className="designer__field designer__field--grow">
                      <span>{t("wf_step_name")}</span>
                      <input
                        value={step.name}
                        maxLength={80}
                        onChange={(e) => setStep(index, { ...step, name: e.target.value })}
                      />
                    </label>
                    <label className="designer__field designer__field--kind">
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
                    <label
                      className="designer__field designer__field--wide"
                      title={t("wf_carry_help")}
                    >
                      <span>{t("wf_carry")}</span>
                      <select
                        value={step.carry}
                        disabled={index === draft.steps.length - 1}
                        onChange={(e) =>
                          setStep(index, {
                            ...step,
                            carry: e.target.value as WorkflowStep["carry"],
                          })
                        }
                      >
                        <option value="all">{t("wf_carry_all")}</option>
                        <option value="used">{t("wf_carry_used")}</option>
                        <option value="none">{t("wf_carry_none")}</option>
                      </select>
                    </label>
                    <CountField
                      step={step}
                      onChange={(count) => setStep(index, { ...step, count })}
                    />
                    <div className="designer__step-tools">
                      <button
                        className="icon-button"
                        disabled={draft.steps.length === 1}
                        onClick={() =>
                          change({ ...draft, steps: draft.steps.filter((_, i) => i !== index) })
                        }
                        aria-label={t("wf_remove_step")}
                        title={t("wf_remove_step")}
                      >
                        <svg viewBox="0 0 16 16" aria-hidden="true">
                          <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" />
                        </svg>
                      </button>
                    </div>
                    <label className="designer__field designer__field--description">
                      <span>{t("wf_description")}</span>
                      <textarea
                        rows={2}
                        maxLength={4000}
                        value={step.description}
                        placeholder={t("wf_description_ph")}
                        onChange={(e) => setStep(index, { ...step, description: e.target.value })}
                      />
                    </label>
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
                        carry: "all",
                        count: null,
                        description: "",
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

/** A save's error as text: who changed it first, for an edit conflict (409);
    otherwise `fallback`. */
function saveError(e: unknown, fallback: string): string {
  return e instanceof ApiError && e.code === "edit_conflict"
    ? tr("conflict", { email: e.body.error.context.by ?? "?" })
    : fallback;
}

/** The collection's switches: running image / video steps straight through
    (fill in the prompts and generate them, without stopping to let them be
    checked first), and, for admins only, lifting its owner's daily limits.
    Saved at once (with the collection's version). */
function CollectionSwitches({ view }: { view: CollectionView }) {
  const t = useT();
  const { collection } = view;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Admins (the allowlist, or anyone in local work) see the daily-limit switch.
  const [admin, setAdmin] = useState(false);
  useEffect(() => {
    api
      .GET("/api/me")
      .then((result) => setAdmin(result.data?.admin ?? false))
      .catch(() => setAdmin(false));
  }, []);

  const save = async (change: {
    direct_image?: boolean;
    direct_video?: boolean;
    no_daily_limit?: boolean;
  }) => {
    setBusy(true);
    setError("");
    try {
      unwrap(
        await api.PATCH("/api/collections/{collection_id}", {
          params: { path: { collection_id: collection.id } },
          body: { version: collection.version, ...change },
        }),
      );
    } catch (e) {
      setError(saveError(e, tr("save_error", { error: errorText(e) })));
    }
    await view.reload();
    setBusy(false);
  };

  return (
    <section className="direct" aria-label={t("direct_title")}>
      <h2 className="direct__title">{t("direct_title")}</h2>
      <label className="panel__switch">
        <input
          type="checkbox"
          role="switch"
          checked={collection.direct_image}
          disabled={busy}
          onChange={(e) => void save({ direct_image: e.target.checked })}
        />
        <span>{t("direct_image")}</span>
      </label>
      <label className="panel__switch">
        <input
          type="checkbox"
          role="switch"
          checked={collection.direct_video}
          disabled={busy}
          onChange={(e) => void save({ direct_video: e.target.checked })}
        />
        <span>{t("direct_video")}</span>
      </label>
      <p className="direct__help">{t("direct_help")}</p>
      {admin && (
        <>
          <h2 className="direct__title direct__title--sub">{t("limit_title")}</h2>
          <label className="panel__switch">
            <input
              type="checkbox"
              role="switch"
              checked={collection.no_daily_limit}
              disabled={busy}
              onChange={(e) => void save({ no_daily_limit: e.target.checked })}
            />
            <span>{t("no_daily_limit")}</span>
          </label>
          <p className="direct__help">{t("no_daily_limit_help")}</p>
        </>
      )}
      {error && (
        <p className="home__error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** A step's default count: how many a run makes unless the project says
    otherwise. Blank: no default. */
function CountField({
  step,
  onChange,
}: {
  step: WorkflowStep;
  onChange: (count: number | null) => void;
}) {
  const t = useT();
  return (
    <label className="designer__field designer__field--count">
      <span>{t("wf_count")}</span>
      <input
        type="number"
        min={1}
        max={MAX_RUN_ITEMS}
        step={1}
        inputMode="numeric"
        placeholder={t("wf_count_none")}
        title={t("wf_count_help")}
        value={step.count ?? ""}
        onChange={(e) => onChange(parseCount(e.target.value))}
      />
    </label>
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
