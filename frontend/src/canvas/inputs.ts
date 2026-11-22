// A node's inputs, as the canvas shows them: in the order its prompt first
// mentions their IDs, which is the order they are sent to the model.
import { idMap, mentionedIds, type Edge, type MediaKind, type Node, type Output } from "../api/types";

export interface InputRef {
  nodeId: string;
  kind: MediaKind;
  label: string;
}

/** "nodeId|kind|ID" per main input: a flat string array, cheap to compare. */
export function inputKeys(
  nodeId: string,
  edges: Edge[],
  nodes: Record<string, Node>,
  outputs: Record<string, Output>,
): string[] {
  const target = nodes[nodeId];
  const order = target ? mentionedIds(target.prompt, idMap(nodes)) : [];
  const rank = (id: string) => (order.includes(id) ? order.indexOf(id) : order.length);
  return edges
    .filter((e) => e.target_node_id === nodeId)
    .map((e) => e.source_node_id)
    .sort((a, b) => rank(a) - rank(b))
    .map((sourceId) => {
      const source = nodes[sourceId];
      const output = source?.selected_output_id ? outputs[source.selected_output_id] : undefined;
      return `${sourceId}|${output?.kind ?? source?.kind ?? "image"}|${source?.name ?? "?"}`;
    });
}

export function labelInputs(keys: string[]): InputRef[] {
  return keys.map((key) => {
    const [nodeId, kind, label] = key.split("|") as [string, MediaKind, string];
    return { nodeId, kind, label };
  });
}
