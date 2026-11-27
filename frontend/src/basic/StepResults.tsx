// What a step made, listed under it in the basic view's workflow bar
// (as wide as the step): each result's thumbnail and node ID, so an ID can be
// looked up without going back. A row copies its ID; hovering it shows the
// result larger. Past a few, "+n more" opens them all.
import { useEffect, useId, useRef, useState, type MouseEvent } from "react";
import { nodeLabel, type Node, type Output } from "../api/types";
import { useT } from "../i18n";
import { MediaThumb } from "../node/MediaThumb";
import { useChosenOutput } from "../node/NodePreview";
import { useCanvas } from "../store/canvas";

/** How many results a column lists before the rest go under "+n more". */
const ROWS = 3;

export function StepResults({ name, nodes }: { name: string; nodes: Node[] }) {
  const t = useT();
  const popup = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const made = nodes.filter((n) => n.selected_output_id);
  const popupId = useId();
  if (!made.length) return null;
  const more = made.length - ROWS;

  /** Put the popup under the "+n more" button. (The button opens and closes
      it; it's in the top layer, so the bar's scrolling doesn't clip it, and a
      click outside or Esc closes it.) */
  const place = (e: MouseEvent<HTMLButtonElement>) => {
    const box = popup.current;
    if (!box) return;
    const at = e.currentTarget.getBoundingClientRect();
    box.style.top = `${at.bottom + 6}px`;
    box.style.left = `${Math.max(8, Math.min(at.left, window.innerWidth - 348))}px`;
  };

  return (
    <div className="wf-results" role="group" aria-label={t("results_of", { step: name })}>
      {made.slice(0, ROWS).map((node) => (
        <Result key={node.id} node={node} />
      ))}
      {more > 0 && (
        <>
          <button
            className="wf-results__more"
            aria-expanded={open}
            popoverTarget={popupId}
            onClick={place}
          >
            {t("results_more", { n: more })}
          </button>
          <div
            ref={popup}
            id={popupId}
            popover="auto"
            className="wf-results__all"
            onToggle={(e) => setOpen(e.newState === "open")}
          >
            <strong>{name}</strong>
            <div className="wf-results__grid">
              {open && made.map((node) => <Result key={node.id} node={node} large />)}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/** One result: a row in the column, or a tile in the popup (`large`). */
function Result({ node, large = false }: { node: Node; large?: boolean }) {
  const t = useT();
  const output = useChosenOutput(node.id);
  const showNotice = useCanvas((s) => s.showNotice);
  const [copied, setCopied] = useState(false);
  // Where the hover preview goes (null: not hovered).
  const [peek, setPeek] = useState<{ top: number; left: number } | null>(null);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const name = nodeLabel(node);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(name);
      setCopied(true);
    } catch {
      showNotice(t("strip_copy_failed", { id: name }));
    }
  };

  const show = (el: HTMLElement) => {
    const at = el.getBoundingClientRect();
    setPeek({ top: at.bottom + 4, left: Math.max(8, Math.min(at.left, window.innerWidth - 268)) });
  };

  return (
    <>
      <button
        className={large ? "wf-tile" : "wf-result"}
        onClick={() => void copy()}
        aria-label={t("strip_copy", { id: name })}
        // The popup's tiles are large already.
        onMouseEnter={(e) => !large && show(e.currentTarget)}
        onMouseLeave={() => setPeek(null)}
        onFocus={(e) => !large && show(e.currentTarget)}
        onBlur={() => setPeek(null)}
      >
        <span className="wf-result__thumb">
          <Thumb output={output} />
        </span>
        <span className="wf-result__name" aria-live="polite">
          {copied ? t("strip_copied") : name}
        </span>
      </button>
      {peek && output && (
        <div className="wf-peek" style={peek} aria-hidden="true">
          {output.kind === "text" ? <p>{output.text}</p> : <Thumb output={output} />}
        </div>
      )}
    </>
  );
}

function Thumb({ output }: { output: Output | undefined }) {
  const url = output?.asset?.url;
  if (url && output.kind !== "text") return <MediaThumb kind={output.kind} url={url} />;
  return <span className="wf-result__text">¶</span>;
}
