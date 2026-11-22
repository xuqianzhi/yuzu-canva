// The kind switch at the top of a node: Image, Video, Text.
import type { NodeShape } from "../store/canvas";
import { useT } from "../i18n";

const SHAPES: NodeShape[] = ["image", "video", "text"];

export function KindTabs({
  shape,
  disabled,
  onPick,
}: {
  shape: NodeShape;
  disabled: boolean;
  onPick: (shape: NodeShape) => void;
}) {
  const t = useT();
  return (
    <div className="segmented nodrag" role="group" aria-label={t("node_kind")}>
      {SHAPES.map((option) => (
        <button
          key={option}
          className={shape === option ? "is-active" : ""}
          disabled={disabled}
          aria-pressed={shape === option}
          onClick={() => onPick(option)}
        >
          {t(`shape_${option}`)}
        </button>
      ))}
    </div>
  );
}
