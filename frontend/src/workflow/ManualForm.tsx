// Completing a step by hand: the user's own texts (a text step) or files (an
// image or video step) become its nodes, in order. Files are uploaded as
// soon as they're picked (into the project's assets); "Complete step" then
// replaces the step's nodes with them. Nothing is generated. Results can be
// added, removed and moved.
import { useRef, useState, type DragEvent } from "react";
import type { Material, StepEntry } from "../api/types";
import { useT } from "../i18n";
import { useCanvas } from "../store/canvas";
import { confirmReplace } from "./confirm";
import type { StepView } from "./status";

interface Entry {
  key: number;
  /** The node's ID (blank: <step>_<n>). */
  id: string;
  text: string;
  material: Material | null;
  /** The file being uploaded, by name. */
  uploading: string | null;
}

let nextKey = 1;
const blank = (): Entry => ({ key: nextKey++, id: "", text: "", material: null, uploading: null });

export function ManualForm({ view }: { view: StepView }) {
  const t = useT();
  const { step } = view;
  const media = step.kind !== "text";
  const completeStep = useCanvas((s) => s.completeStep);
  const uploadFiles = useCanvas((s) => s.uploadFiles);
  const [entries, setEntries] = useState<Entry[]>(() => (media ? [] : [blank()]));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const update = (index: number, change: Partial<Entry>) =>
    setEntries((current) => {
      const next = [...current];
      next[index] = { ...next[index]!, ...change };
      return next;
    });

  const move = (index: number, by: number) =>
    setEntries((current) => {
      const next = [...current];
      const [item] = next.splice(index, 1);
      next.splice(index + by, 0, item!);
      return next;
    });

  /** Upload one file into a row (replacing what it held). */
  const uploadInto = async (rowKey: number, file: File) => {
    const set = (change: Partial<Entry>) =>
      setEntries((current) => current.map((e) => (e.key === rowKey ? { ...e, ...change } : e)));
    set({ uploading: file.name, material: null });
    const [material] = await uploadFiles([file]);
    set({ uploading: null, material: material ?? null });
  };

  /** New entries for picked or dropped files, uploaded in order. */
  const addFiles = (files: File[]) => {
    const wanted = files.filter((f) => f.type.startsWith(`${step.kind}/`) || !f.type);
    if (wanted.length < files.length)
      setError(t("manual_wrong_kind", { kind: t(`kind_${step.kind}`) }));
    const added = wanted.map(() => blank());
    setEntries((current) => [...current, ...added]);
    added.forEach((row, i) => void uploadInto(row.key, wanted[i]!));
  };

  const ready =
    entries.length > 0 &&
    entries.every((r) => (media ? r.material !== null && !r.uploading : r.text.trim() !== ""));

  const submit = async () => {
    if (!ready || busy) return;
    if (!confirmReplace(view.nodes)) return;
    setBusy(true);
    const body: StepEntry[] = entries.map((r) => ({
      id: r.id.trim() || null,
      ...(media ? { material_id: r.material!.id } : { text: r.text.trim() }),
    }));
    const failed = await completeStep(step.key, body);
    setBusy(false);
    setError(failed ?? "");
    if (!failed) setEntries(media ? [] : [blank()]);
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    addFiles([...event.dataTransfer.files]);
  };

  return (
    <section className="manual" aria-label={t("manual_title")}>
      {view.run?.manual && view.nodes.length > 0 && (
        <p className="step-panel__muted">{t("manual_done", { n: view.nodes.length })}</p>
      )}
      <ol className="manual__list">
        {entries.map((row, index) => (
          <li key={row.key} className="manual__row">
            <div className="manual__head">
              <span className="manual__number">#{index + 1}</span>
              <input
                className="manual__id"
                value={row.id}
                maxLength={80}
                placeholder={`${step.key}_${index + 1}`}
                aria-label={t("manual_id_aria", { n: index + 1 })}
                onChange={(e) => update(index, { id: e.target.value })}
              />
              <span className="manual__tools">
                <button
                  className="icon-button"
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                  aria-label={t("manual_up")}
                  title={t("manual_up")}
                >
                  <svg viewBox="0 0 16 16" aria-hidden="true">
                    <path d="M8 12.5v-9M4 7l4-3.5L12 7" />
                  </svg>
                </button>
                <button
                  className="icon-button"
                  disabled={index === entries.length - 1}
                  onClick={() => move(index, 1)}
                  aria-label={t("manual_down")}
                  title={t("manual_down")}
                >
                  <svg viewBox="0 0 16 16" aria-hidden="true">
                    <path d="M8 3.5v9M4 9l4 3.5L12 9" />
                  </svg>
                </button>
                <button
                  className="icon-button"
                  disabled={!media && entries.length === 1}
                  onClick={() => setEntries((current) => current.filter((_, i) => i !== index))}
                  aria-label={t("manual_remove")}
                  title={t("manual_remove")}
                >
                  <svg viewBox="0 0 16 16" aria-hidden="true">
                    <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" />
                  </svg>
                </button>
              </span>
            </div>
            {media ? (
              <MediaSlot
                row={row}
                kind={step.kind as "image" | "video"}
                onFile={(file) => void uploadInto(row.key, file)}
              />
            ) : (
              <textarea
                className="run__prompt manual__text"
                rows={3}
                value={row.text}
                maxLength={100_000}
                placeholder={t("manual_text_ph")}
                aria-label={t("manual_text_aria", { n: index + 1 })}
                onChange={(e) => update(index, { text: e.target.value })}
              />
            )}
          </li>
        ))}
      </ol>

      {media ? (
        <div
          className={`manual__drop${dragging ? " is-dragging" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <button className="button" onClick={() => picker.current?.click()}>
            {t(step.kind === "image" ? "manual_add_images" : "manual_add_videos")}
          </button>
          <span className="step-panel__muted">{t("manual_drop")}</span>
          <input
            ref={picker}
            type="file"
            hidden
            multiple
            accept={
              step.kind === "image"
                ? "image/png,image/jpeg,image/webp"
                : "video/mp4,video/quicktime"
            }
            onChange={(e) => {
              addFiles([...(e.target.files ?? [])]);
              e.target.value = "";
            }}
          />
        </div>
      ) : (
        <button className="button button--small" onClick={() => setEntries((c) => [...c, blank()])}>
          {t("manual_add_text")}
        </button>
      )}

      {entries.length > 0 && (
        <div className="step-panel__actions">
          <button
            className="button button--primary"
            disabled={!ready || busy}
            onClick={() => void submit()}
          >
            {busy ? t("manual_saving") : t("manual_complete", { n: entries.length })}
          </button>
        </div>
      )}
      <p className="step-panel__muted">{t("manual_note")}</p>
      {error && (
        <p className="step-panel__error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function MediaSlot({
  row,
  kind,
  onFile,
}: {
  row: Entry;
  kind: "image" | "video";
  onFile: (file: File) => void;
}) {
  const t = useT();
  const input = useRef<HTMLInputElement>(null);
  const url = row.material?.asset.url;
  return (
    <div className="manual__media">
      {row.uploading ? (
        <span className="manual__placeholder">
          <span className="spinner" /> {row.uploading}
        </span>
      ) : url ? (
        kind === "image" ? (
          <img src={url} alt={row.material?.name ?? ""} />
        ) : (
          <video src={url} muted playsInline controls preload="metadata" />
        )
      ) : (
        <span className="manual__placeholder">{t("manual_no_file")}</span>
      )}
      <button className="button button--small" onClick={() => input.current?.click()}>
        {url ? t("manual_replace_file") : t("manual_choose_file")}
      </button>
      <input
        ref={input}
        type="file"
        hidden
        accept={kind === "image" ? "image/png,image/jpeg,image/webp" : "video/mp4,video/quicktime"}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}
