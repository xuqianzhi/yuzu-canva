// A link between nodes. Every node's link dots sit at the same height, so a
// straight link across a row passes exactly through the dots of the nodes
// in between and looks like it starts at one of them. A link that travels
// farther than to the next column therefore bows upwards, the more the
// farther it goes; short links keep React Flow's own curve.
import { BaseEdge, getBezierPath, type EdgeProps } from "@xyflow/react";
import { memo } from "react";

// Next-column links span about 80 px (columns are 560 apart, nodes 480
// wide); anything past this crosses at least one node.
const LONG = 300;

function RefEdgeView(props: EdgeProps) {
  const { sourceX: sx, sourceY: sy, targetX: tx, targetY: ty } = props;
  const dx = tx - sx;
  let path: string;
  if (dx > LONG) {
    const bow = Math.min(240, 40 + dx * 0.06);
    const pull = Math.min(dx * 0.35, 260);
    path = `M ${sx},${sy} C ${sx + pull},${sy - bow} ${tx - pull},${ty - bow} ${tx},${ty}`;
  } else {
    [path] = getBezierPath(props);
  }
  return (
    <BaseEdge
      id={props.id}
      path={path}
      markerEnd={props.markerEnd}
      markerStart={props.markerStart}
      style={props.style}
      interactionWidth={props.interactionWidth}
    />
  );
}

export const RefEdge = memo(RefEdgeView);
