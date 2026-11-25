// The questions asked before a step does something that costs or replaces.
import type { MediaKind, Node } from "../api/types";
import { t } from "../i18n";

/** Before a run (or hand completion) replaces a step's nodes: says how many
    of them were edited since (those edits are lost too). */
export function confirmReplace(nodes: Node[]): boolean {
  if (!nodes.length) return true;
  const edited = nodes.filter((n) => n.edited).length;
  return window.confirm(
    edited
      ? t("run_replace_edited", { n: nodes.length, edited })
      : t("run_replace", { n: nodes.length }),
  );
}

/** Videos are paid per job: ask before generating `n` of them. */
export function confirmVideos(kind: MediaKind, n: number): boolean {
  return kind !== "video" || window.confirm(t("generate_all_confirm", { n }));
}
