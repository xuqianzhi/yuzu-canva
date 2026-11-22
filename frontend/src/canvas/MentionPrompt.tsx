// The prompt box. Any node ID in the text links that node as an input, and
// removing it removes the link; linked IDs are highlighted in place (a copy
// of the text behind the transparent textarea carries the marks). Typing "@"
// lists the canvas's IDs; choosing one replaces "@..." with the bare ID.
import { useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useShallow } from "zustand/react/shallow";
import { findMentions, idMap, mentionedIds } from "../api/types";
import { useCanvas } from "../store/canvas";
import { useT } from "../i18n";

/** The "@partial" right before the caret, if the caret is in one. */
function activeQuery(text: string, caret: number): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const at = before.lastIndexOf("@");
  if (at === -1) return null;
  const query = before.slice(at + 1);
  if (/\s/.test(query) || query.length > 80) return null;
  return { start: at, query };
}

export function MentionPrompt({
  nodeId,
  placeholder,
  onGenerate,
  className = "",
  ariaLabel,
}: {
  nodeId: string;
  placeholder: string;
  onGenerate: () => void;
  className?: string;
  ariaLabel?: string;
}) {
  const t = useT();
  const prompt = useCanvas((s) => s.nodes[nodeId]?.prompt ?? "");
  // "start|end|linked" per ID in the text (not this node's own).
  const marks = useCanvas(
    useShallow((s) => {
      const text = s.nodes[nodeId]?.prompt ?? "";
      const ids = idMap(s.nodes);
      const linked = new Set(
        s.edges
          .filter((e) => e.target_node_id === nodeId && !e.workflow)
          .map((e) => e.source_node_id),
      );
      return findMentions(text, ids)
        .filter((m) => m.nodeId !== nodeId)
        .map((m) => `${m.start}|${m.end}|${linked.has(m.nodeId) ? 1 : 0}`);
    }),
  );
  const unsaved = useCanvas((s) => Boolean(s.unsavedPrompts[nodeId]));
  const backdrop = useRef<HTMLDivElement>(null);
  const setPrompt = useCanvas((s) => s.setPrompt);
  // "ID|kind" for every other node with an ID.
  const options = useCanvas(
    useShallow((s) =>
      Object.values(s.nodes)
        .filter((n) => n.id !== nodeId && n.name)
        .map((n) => `${n.name}|${n.kind}`),
    ),
  );
  const box = useRef<HTMLTextAreaElement>(null);
  const [picker, setPicker] = useState<{ start: number; query: string } | null>(null);
  const [active, setActive] = useState(0);

  const matches = useMemo(() => {
    if (!picker) return [];
    const q = picker.query.toLowerCase();
    return options
      .map((o) => o.split("|") as [string, string])
      .filter(([id]) => id.toLowerCase().includes(q))
      .sort(([a], [b]) => Number(!a.toLowerCase().startsWith(q)) - Number(!b.toLowerCase().startsWith(q)))
      .slice(0, 8);
  }, [picker, options]);

  const update = (text: string, caret: number) => {
    setPrompt(nodeId, text);
    setPicker(activeQuery(text, caret));
    setActive(0);
  };

  const choose = (id: string) => {
    if (!picker || !box.current) return;
    const caret = box.current.selectionStart;
    // The "@" only opens the picker: the prompt gets the bare ID.
    const text = `${prompt.slice(0, picker.start)}${id} ${prompt.slice(caret)}`;
    const nextCaret = picker.start + id.length + 1;
    setPrompt(nodeId, text);
    setPicker(null);
    requestAnimationFrame(() => {
      box.current?.focus();
      box.current?.setSelectionRange(nextCaret, nextCaret);
    });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (picker && matches.length) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const step = e.key === "ArrowDown" ? 1 : -1;
        setActive((i) => (i + step + matches.length) % matches.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        choose(matches[active]![0]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setPicker(null);
        return;
      }
    }
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      onGenerate();
    }
  };

  // The text again, with IDs marked, behind the textarea. While typing isn't
  // saved yet, a mention's link may lag: mark it as linked meanwhile.
  const highlighted = useMemo(() => {
    const parts: ReactNode[] = [];
    let last = 0;
    for (const mark of marks) {
      const [start, end, linked] = mark.split("|").map(Number) as [number, number, number];
      parts.push(prompt.slice(last, start));
      parts.push(
        <mark key={start} className={linked || unsaved ? "" : "is-unlinked"}>
          {prompt.slice(start, end)}
        </mark>,
      );
      last = end;
    }
    parts.push(prompt.slice(last), "\n");
    return parts;
  }, [marks, prompt, unsaved]);

  return (
    <div className={`mention-prompt ${className}`}>
      <div className="mention-prompt__backdrop gen-node__prompt" ref={backdrop} aria-hidden="true">
        {highlighted}
      </div>
      <textarea
        ref={box}
        className="gen-node__prompt mention-prompt__input nodrag nowheel"
        aria-label={ariaLabel}
        placeholder={placeholder}
        onScroll={(e) => {
          if (backdrop.current) backdrop.current.scrollTop = e.currentTarget.scrollTop;
        }}
        value={prompt}
        rows={3}
        onChange={(e) => update(e.target.value, e.target.selectionStart)}
        onKeyDown={onKeyDown}
        onKeyUp={(e) => {
          if (e.key.startsWith("Arrow") && !picker) return;
          if (!["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(e.key)) {
            setPicker(activeQuery(e.currentTarget.value, e.currentTarget.selectionStart));
          }
        }}
        onBlur={() => setTimeout(() => setPicker(null), 120)}
      />
      {picker && (
        <ul className="mention-picker nodrag nowheel" role="listbox" aria-label={t("node_ids_aria")}>
          {matches.length === 0 ? (
            <li className="mention-picker__empty">
              {options.length ? t("mention_none") : t("mention_no_ids")}
            </li>
          ) : (
            matches.map(([id, kind], i) => (
              <li
                key={id}
                role="option"
                aria-selected={i === active}
                className={i === active ? "is-active" : ""}
                onMouseDown={(e) => {
                  e.preventDefault(); // keep focus in the box
                  choose(id);
                }}
                onMouseEnter={() => setActive(i)}
              >
                <span>@{id}</span>
                <small>{t(`kind_${kind as "image" | "video" | "text"}`)}</small>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

/** IDs in this node's prompt that name a node but aren't linked (a link
    would make a loop). Empty while typing hasn't been saved. */
export function useUnlinkedMentions(nodeId: string): string[] {
  return useCanvas(
    useShallow((s) => {
      const node = s.nodes[nodeId];
      if (!node || s.unsavedPrompts[nodeId]) return [];
      const ids = idMap(s.nodes);
      const linked = new Set(
        s.edges
          .filter((e) => e.target_node_id === nodeId && !e.workflow)
          .map((e) => e.source_node_id),
      );
      return mentionedIds(node.prompt, ids)
        .filter((id) => id !== nodeId && !linked.has(id))
        .map((id) => s.nodes[id]?.name ?? "?");
    }),
  );
}
