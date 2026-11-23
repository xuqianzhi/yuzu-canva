// A collection's Instruction page: plain text that every new project in the
// collection starts with as its own instruction. Saved shortly after typing
// stops (and when leaving the page). Saving over someone else's newer
// change is refused (the collection's version): reload to see theirs.
import { useEffect, useRef, useState } from "react";
import { api, ApiError, unwrap } from "../api/client";
import { errorText, t as tr, useT } from "../i18n";
import type { CollectionView } from "./HomePage";

type Status = "loading" | "saved" | "editing" | "saving" | "error" | "conflict";

const SAVE_DELAY_MS = 600;

export function CollectionInstruction({ view }: { view: CollectionView }) {
  const t = useT();
  const { collection } = view;
  const [text, setText] = useState(collection.instruction);
  const [status, setStatus] = useState<Status>("saved");
  const [error, setError] = useState("");
  const pending = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // The version our text is based on (sent with each save).
  const version = useRef(collection.version);

  const flush = async () => {
    clearTimeout(timer.current);
    const value = pending.current;
    pending.current = null;
    if (value === null) return;
    setStatus("saving");
    try {
      const saved = unwrap(
        await api.PATCH("/api/collections/{collection_id}", {
          params: { path: { collection_id: collection.id } },
          body: { version: version.current, instruction: value },
        }),
      );
      version.current = saved.version;
      setError("");
      setStatus(pending.current === null ? "saved" : "editing");
      // So the other pages (and coming back here) show it.
      if (pending.current === null) void view.reload();
    } catch (e) {
      if (e instanceof ApiError && e.code === "edit_conflict") {
        setError(tr("conflict", { email: e.body.error.context.by ?? "?" }));
        setStatus("conflict");
        return;
      }
      setError(tr("save_error", { error: errorText(e) }));
      setStatus("error");
    }
  };

  const reload = async () => {
    await view.reload();
  };
  // A reloaded collection: take its text and version (unless typing).
  useEffect(() => {
    if (pending.current !== null) return;
    version.current = collection.version;
    setText(collection.instruction);
    setStatus("saved");
    setError("");
  }, [collection.version, collection.instruction]);

  useEffect(() => {
    // Leaving the page (opening a project) saves what was typed.
    return () => void flush();
  }, []);

  const change = (value: string) => {
    setText(value);
    setStatus("editing");
    pending.current = value;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => void flush(), SAVE_DELAY_MS);
  };

  const label =
    status === "loading"
      ? t("loading")
      : status === "saving"
        ? t("saving")
        : status === "editing"
          ? t("edited")
          : status === "saved"
            ? t("saved")
            : "";

  const failed = status === "error" || status === "conflict";
  return (
    <main className="home__page home__page--fill" aria-label={t("gi_title")}>
      <div className="home__inner home__inner--fill">
        <div className="instruction__head">
          <div>
            <h1 className="home__title">{t("gi_title")}</h1>
            <p className="home__help">{t("gi_help")}</p>
          </div>
          <span className={`instruction__status${failed ? " is-error" : ""}`} role="status">
            {failed ? error : label}
            {status === "conflict" && (
              <button className="button button--small" onClick={() => void reload()}>
                {t("reload")}
              </button>
            )}
          </span>
        </div>
        <textarea
          className="instruction-input home__instruction-input"
          aria-label={t("gi_title")}
          placeholder={t("gi_placeholder")}
          maxLength={20000}
          value={text}
          disabled={status === "loading"}
          onChange={(e) => change(e.target.value)}
          onBlur={() => void flush()}
        />
      </div>
    </main>
  );
}
