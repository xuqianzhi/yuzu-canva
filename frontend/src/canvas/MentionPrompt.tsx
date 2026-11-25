// Prompt boxes that know node IDs. In a node's prompt, any node ID in the
// text links that node as an input, and removing it removes the link. IDs
// are highlighted in place (a copy of the text behind the transparent
// textarea carries the marks). Typing "@" lists the canvas's IDs; choosing
// one replaces "@..." with the bare ID.
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

/** A node's own prompt box: mentions link their nodes as inputs. */
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
  const prompt = useCanvas((s) => s.nodes[nodeId]?.prompt ?? "");
  // IDs of the nodes linked into this one by a mention.
  const linked = useCanvas(
    useShallow((s) =>
      s.edges
        .filter((e) => e.target_node_id === nodeId && !e.workflow)
        .map((e) => e.source_node_id),
    ),
  );
  const unsaved = useCanvas((s) => Boolean(s.unsavedPrompts[nodeId]));
  const setPrompt = useCanvas((s) => s.setPrompt);
  const isLinked = useMemo(() => {
    const ids = new Set(linked);
    // While typing isn't saved yet, a mention's link may lag: count it.
    return (id: string) => unsaved || ids.has(id);
  }, [linked, unsaved]);
  return (
    <MentionBox
      value={prompt}
      onChange={(text) => setPrompt(nodeId, text)}
      exclude={nodeId}
      isLinked={isLinked}
      placeholder={placeholder}
      onSubmit={onGenerate}
      className={className}
      ariaLabel={ariaLabel}
    />
  );
}

/**
 * A prompt box that knows the canvas's node IDs: they're highlighted where
 * they appear (red where `isLinked` says the mention won't be used), and
 * typing "@" lists them. The text is the caller's.
 */
export function MentionBox({
  value: prompt,
  onChange,
  exclude,
  isLinked,
  placeholder,
  onSubmit,
  className = "",
  inputClassName = "",
  ariaLabel,
  id,
  maxLength,
  rows = 3,
}: {
  value: string;
  onChange: (text: string) => void;
  /** A node not to offer or mark (the box's own). */
  exclude?: string;
  /** Whether a mention of this node is used (marked green, else red). */
  isLinked: (nodeId: string) => boolean;
  placeholder: string;
  onSubmit: () => void;
  className?: string;
  inputClassName?: string;
  ariaLabel?: string;
  id?: string;
  maxLength?: number;
  rows?: number;
}) {
  const t = useT();
  // `nodes` doesn't change while a node is dragged (the positions in flowNodes
  // do), so this isn't recomputed on every drag frame.
  const nodes = useCanvas((s) => s.nodes);
  // Every ID in the text (not the excluded node's).
  const found = useMemo(
    () => findMentions(prompt, idMap(nodes)).filter((m) => m.nodeId !== exclude),
    [prompt, nodes, exclude],
  );
  const backdrop = useRef<HTMLDivElement>(null);
  // Every other node with an ID, and its kind.
  const options = useMemo(
    () =>
      Object.values(nodes)
        .filter((n) => n.id !== exclude && n.name)
        .map((n) => [n.name!, n.kind] as const),
    [nodes, exclude],
  );
  const box = useRef<HTMLTextAreaElement>(null);
  const [picker, setPicker] = useState<{ start: number; query: string } | null>(null);
  const [active, setActive] = useState(0);

  const matches = useMemo(() => {
    if (!picker) return [];
    const q = picker.query.toLowerCase();
    return options
      .filter(([id]) => id.toLowerCase().includes(q))
      .sort(([a], [b]) => Number(!a.toLowerCase().startsWith(q)) - Number(!b.toLowerCase().startsWith(q)))
      .slice(0, 8);
  }, [picker, options]);

  const update = (text: string, caret: number) => {
    onChange(text);
    setPicker(activeQuery(text, caret));
    setActive(0);
  };

  const choose = (id: string) => {
    if (!picker || !box.current) return;
    const caret = box.current.selectionStart;
    // The "@" only opens the picker: the prompt gets the bare ID.
    const text = `${prompt.slice(0, picker.start)}${id} ${prompt.slice(caret)}`;
    if (maxLength !== undefined && text.length > maxLength) return;
    const nextCaret = picker.start + id.length + 1;
    onChange(text);
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
      onSubmit();
    }
  };

  // The text again, with IDs marked, behind the textarea.
  const highlighted = useMemo(() => {
    const parts: ReactNode[] = [];
    let last = 0;
    for (const { start, end, nodeId } of found) {
      parts.push(prompt.slice(last, start));
      parts.push(
        <mark key={start} className={isLinked(nodeId) ? "" : "is-unlinked"}>
          {prompt.slice(start, end)}
        </mark>,
      );
      last = end;
    }
    parts.push(prompt.slice(last), "\n");
    return parts;
  }, [found, prompt, isLinked]);

  return (
    <div className={`mention-prompt ${className}`}>
      <div
        className={`mention-prompt__backdrop gen-node__prompt ${inputClassName}`}
        ref={backdrop}
        aria-hidden="true"
      >
        {highlighted}
      </div>
      <textarea
        ref={box}
        id={id}
        className={`gen-node__prompt mention-prompt__input nodrag nowheel ${inputClassName}`}
        aria-label={ariaLabel}
        placeholder={placeholder}
        onScroll={(e) => {
          if (backdrop.current) backdrop.current.scrollTop = e.currentTarget.scrollTop;
        }}
        value={prompt}
        rows={rows}
        maxLength={maxLength}
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
  const nodes = useCanvas((s) => s.nodes);
  const edges = useCanvas((s) => s.edges);
  const unsaved = useCanvas((s) => s.unsavedPrompts[nodeId]);
  return useMemo(() => {
    const node = nodes[nodeId];
    if (!node || unsaved) return [];
    const linked = new Set(
      edges.filter((e) => e.target_node_id === nodeId && !e.workflow).map((e) => e.source_node_id),
    );
    return mentionedIds(node.prompt, idMap(nodes))
      .filter((id) => id !== nodeId && !linked.has(id))
      .map((id) => nodes[id]?.name ?? "?");
  }, [nodes, edges, unsaved, nodeId]);
}
