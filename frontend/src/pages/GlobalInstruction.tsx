// The landing page's Global instruction page: plain text
// that every new project starts with as its own instruction. Saved shortly
// after typing stops (and when leaving the page). Nothing uses it yet.
import { useEffect, useRef, useState } from "react";
import { api, unwrap } from "../api/client";
import { errorText, t as tr, useT } from "../i18n";

type Status = "loading" | "saved" | "editing" | "saving" | "error";

const SAVE_DELAY_MS = 600;

export function GlobalInstruction() {
  const t = useT();
  const [text, setText] = useState("");
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState("");
  const pending = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const flush = async () => {
    clearTimeout(timer.current);
    const value = pending.current;
    pending.current = null;
    if (value === null) return;
    setStatus("saving");
    try {
      unwrap(await api.PUT("/api/global-instruction", { body: { instruction: value } }));
      setError("");
      setStatus(pending.current === null ? "saved" : "editing");
    } catch (e) {
      setError(tr("save_error", { error: errorText(e) }));
      setStatus("error");
    }
  };

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const saved = unwrap(await api.GET("/api/global-instruction"));
        if (live) {
          setText(saved.instruction);
          setStatus("saved");
        }
      } catch (e) {
        if (live) {
          setError(tr("load_error", { error: errorText(e) }));
          setStatus("error");
        }
      }
    })();
    // Leaving the page (opening a project) saves what was typed.
    return () => {
      live = false;
      void flush();
    };
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

  return (
    <main className="home__page home__page--fill" aria-label={t("gi_title")}>
      <div className="home__inner home__inner--fill">
        <div className="instruction__head">
          <div>
            <h1 className="home__title">{t("gi_title")}</h1>
            <p className="home__help">{t("gi_help")}</p>
          </div>
          <span className={`instruction__status${status === "error" ? " is-error" : ""}`} role="status">
            {status === "error" ? error : label}
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
