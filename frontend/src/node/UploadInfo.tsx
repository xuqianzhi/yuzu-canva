// An uploaded file's node has no prompt card; it shows this instead: the
// file's size and length, and how other nodes can use it. Shared by every
// view.
import type { Node, Output } from "../api/types";
import { useT } from "../i18n";

/** Width / height of an uploaded file (1 until it's known). */
export function uploadRatio(output: Output | undefined): number {
  const asset = output?.asset;
  return asset?.width && asset.height ? asset.width / asset.height : 1;
}

export function UploadBadge({ node }: { node: Node }) {
  const t = useT();
  return <span className="upload-badge">{t("uploaded_kind", { kind: t(`kind_${node.kind}`) })}</span>;
}

export function UploadInfo({ node, output }: { node: Node; output: Output | undefined }) {
  const t = useT();
  const asset = output?.asset;
  const details = [
    asset?.width && asset.height ? `${asset.width}×${asset.height}` : null,
    asset?.duration_s ? t("seconds", { n: asset.duration_s.toFixed(1) }) : null,
    asset ? formatBytes(asset.bytes) : null,
  ].filter(Boolean);
  return (
    <div className="gen-node__card gen-node__upload-info">
      <span>{details.join(" · ")}</span>
      <small>{node.kind === "video" ? t("uploaded_hint_video") : t("uploaded_hint_image")}</small>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
