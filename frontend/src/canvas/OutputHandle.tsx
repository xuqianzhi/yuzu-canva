// A node's output handle. A node without an ID can't be referred to, so its
// handle is a grey, unconnectable circle that says why on hover.
import { Handle, Position } from "@xyflow/react";
import { useT } from "../i18n";

export function OutputHandle({ hasId, title }: { hasId: boolean; title: string }) {
  const t = useT();
  return (
    <Handle
      type="source"
      position={Position.Right}
      isConnectable={hasId}
      isConnectableStart={hasId}
      isConnectableEnd={hasId}
      className={`gen-node__handle${hasId ? "" : " gen-node__handle--locked"}`}
      title={hasId ? title : undefined}
      data-hint={hasId ? undefined : t("needs_id_hint")}
    />
  );
}
