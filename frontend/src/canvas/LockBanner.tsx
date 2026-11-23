// Shown while this tab can only view the project (see store/lock.ts):
// who is editing it, and the button to start editing once that's possible.
import { useEffect, useRef, useState } from "react";
import { useCanvas } from "../store/canvas";
import { useT } from "../i18n";

export function LockBanner() {
  const t = useT();
  const lock = useCanvas((s) => s.lock);
  const startEditing = useCanvas((s) => s.startEditing);
  const [busy, setBusy] = useState(false);
  // Who held it last, to say they left.
  const lastHolder = useRef<string | null>(null);
  const holder = lock.status === "viewing" ? lock.holderEmail : null;
  useEffect(() => {
    if (holder) lastHolder.current = holder;
  }, [holder]);

  if (lock.status !== "viewing") return null;
  const start = async (takeOver: boolean) => {
    setBusy(true);
    try {
      await startEditing(takeOver);
    } finally {
      setBusy(false);
    }
  };

  let text: string;
  let action: { label: string; takeOver: boolean } | null = null;
  if (lock.holderIsYou) {
    text = t("lock_elsewhere");
    action = { label: t("lock_take_over"), takeOver: true };
  } else if (lock.holderEmail) {
    text = t("lock_viewing", { email: lock.holderEmail });
  } else {
    text = lastHolder.current ? t("lock_left", { email: lastHolder.current }) : t("lock_free");
    action = { label: t("lock_start"), takeOver: false };
  }
  return (
    <div className="lock-banner" role="status">
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
        <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
      </svg>
      <span>{text}</span>
      {action && (
        <button
          className="button button--primary button--small"
          disabled={busy}
          onClick={() => void start(action.takeOver)}
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
