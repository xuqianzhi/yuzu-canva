// Friendly names for the generated contract types. Do not edit schema.d.ts:
// it is regenerated from contract/openapi.json by `npm run gen:api`.
import type { components } from "./schema";

type S = components["schemas"];

export type Project = S["Project"];
export type ProjectCreate = S["ProjectCreate"];
export type ProjectUpdate = S["ProjectUpdate"];
export type ProjectGraph = S["ProjectGraph"];
export type Viewport = S["Viewport"];
export type Position = S["Position"];
export type Size = S["Size"];

export type MediaKind = S["MediaKind"];
export type Node = S["Node"];
export type NodeCreate = S["NodeCreate"];
export type NodeUpdate = S["NodeUpdate"];
export type TextParams = S["TextParams"];
export type ImageParams = S["ImageParams"];
export type VideoParams = S["VideoParams"];
export type NodeParams = TextParams | ImageParams | VideoParams;

export type Edge = S["Edge"];
export type NodeSource = S["NodeSource"];

export type Material = S["Material"];

export type WorkflowDefinition = S["WorkflowDefinition"];
export type WorkflowStep = S["WorkflowStep"];
export type ChatMessage = S["ChatMessage"];
export type StepRun = S["StepRun"];

export type Collection = S["Collection"];
export type CollectionSummary = S["CollectionSummary"];
export type CollectionWorkflow = S["CollectionWorkflow"];
export type CollectionAsset = S["CollectionAsset"];
export type Member = S["Member"];
export type Invite = S["Invite"];
export type Invitation = S["Invitation"];
export type EditorLimits = S["EditorLimits"];
export type ProjectLock = S["ProjectLock"];
export type ProjectSummary = S["ProjectSummary"];
export type Me = S["Me"];

/** The most nodes one run of a workflow step may make (contract MAX_ITEMS). */
export const MAX_RUN_ITEMS = 20;
export type EdgeCreate = S["EdgeCreate"];

export type Asset = S["Asset"];
export type Output = S["Output"];
export type Job = S["Job"];
export type JobStatus = S["JobStatus"];
export type JobInput = S["JobInput"];
export type Operation = S["Operation"];
export type Provider = S["Provider"];
export type ResolvedRef = S["ResolvedRef"];

export type ErrorCode = S["ErrorCode"];
export type ErrorResponse = S["ErrorResponse"];


export const TERMINAL_JOB_STATUSES: readonly JobStatus[] = ["succeeded", "failed", "canceled"];

/** What name uniqueness compares: case- and spacing-insensitive. */
export function nameKey(name: string): string {
  return name.split(/\s+/).filter(Boolean).join(" ").toLocaleLowerCase();
}

export function normalizeName(name: string): string | null {
  const cleaned = name.split(/\s+/).filter(Boolean).join(" ");
  return cleaned || null;
}

// --- Node IDs and mentions (mirrors backend domain/mentions.py) ----------------

/** An ID is letters (any script), digits, "_" and "-". */
const ID_RE = /^[\p{L}\p{N}_-]+$/u;
const ASCII_WORD = /[A-Za-z0-9_-]/;


export function isValidId(id: string): boolean {
  return ID_RE.test(id);
}

/** Turn any text (e.g. a file name) into a valid ID. */
export function toValidId(text: string): string {
  const cleaned = text
    .trim()
    .replace(/[^\p{L}\p{N}_-]+/gu, "_")
    .replace(/^_+|_+$/g, "");
  return cleaned || "node";
}

export interface Mention {
  start: number;
  end: number;
  nodeId: string;
}

/**
 * Every node ID in `text` (no "@" needed). At each position the longest
 * existing ID wins, ignoring case, without overlaps. An ID starting or ending
 * with a Latin letter, digit, _ or - must be a whole word on that side ("fox"
 * is not in "redfox" or "foxes"); Chinese needs no spaces. `ids` maps
 * ID -> node id.
 */
export function findMentions(text: string, ids: Record<string, string>): Mention[] {
  if (!text) return [];
  const keys = Object.entries(ids)
    .map(([id, nodeId]) => [id.toLowerCase(), nodeId] as const)
    .filter(([key]) => key)
    .sort((a, b) => b[0].length - a[0].length);
  if (!keys.length) return [];
  const lowered = text.toLowerCase();
  const found: Mention[] = [];
  let i = 0;
  while (i < text.length) {
    let match: Mention | null = null;
    for (const [key, nodeId] of keys) {
      if (!lowered.startsWith(key, i)) continue;
      const stop = i + key.length;
      if (ASCII_WORD.test(key[0]!) && i > 0 && ASCII_WORD.test(text[i - 1]!)) continue;
      if (ASCII_WORD.test(key.at(-1)!) && stop < text.length && ASCII_WORD.test(text[stop]!)) {
        continue;
      }
      match = { start: i, end: stop, nodeId };
      break;
    }
    if (match) {
      found.push(match);
      i = match.end;
    } else {
      i += 1;
    }
  }
  return found;
}

/** Node ids mentioned in `text`, in order of first mention. */
export function mentionedIds(text: string, ids: Record<string, string>): string[] {
  return [...new Set(findMentions(text, ids).map((m) => m.nodeId))];
}

/** Every live node's ID -> node id. */
export function idMap(nodes: Record<string, Node>): Record<string, string> {
  const map: Record<string, string> = {};
  for (const node of Object.values(nodes)) if (node.name) map[node.name] = node.id;
  return map;
}
