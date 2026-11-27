// A node's generation settings (size and quality; ratio, length, resolution
// and sound), compact, in the bottom row of its prompt card.
import type { ImageParams, NodeParams, VideoParams } from "../api/types";
import { DurationSelect, ParamSelect } from "../canvas/ParamSelect";
import { useT } from "../i18n";
import { useCanvas } from "../store/canvas";

const IMAGE_SIZES: ImageParams["size"][] = ["auto", "1024x1024", "1536x1024", "1024x1536"];
const IMAGE_QUALITIES: ImageParams["quality"][] = ["auto", "low", "medium", "high"];
const VIDEO_RATIOS: VideoParams["ratio"][] = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"];
const VIDEO_RESOLUTIONS: VideoParams["resolution"][] = ["480p", "720p", "1080p"];

export function NodeSettings({ nodeId, params }: { nodeId: string; params: NodeParams }) {
  const t = useT();
  const setParams = useCanvas((s) => s.setParams);
  if (params.kind === "text") return <span className="gen-node__hint">{t("text_output")}</span>;
  if (params.kind === "image") {
    return (
      <>
        <ParamSelect
          label={t("size")}
          value={params.size}
          options={IMAGE_SIZES}
          format={(v) => (v === "auto" ? t("size_auto") : v)}
          onChange={(size) => setParams(nodeId, { ...params, size })}
        />
        <ParamSelect
          label={t("quality")}
          value={params.quality}
          options={IMAGE_QUALITIES}
          format={(v) => (v === "auto" ? t("quality_auto") : t(`quality_${v}`))}
          onChange={(quality) => setParams(nodeId, { ...params, quality })}
        />
      </>
    );
  }
  return (
    <>
      <ParamSelect
        label={t("ratio")}
        value={params.ratio}
        options={VIDEO_RATIOS}
        onChange={(ratio) => setParams(nodeId, { ...params, ratio })}
      />
      <DurationSelect
        label={t("duration")}
        value={params.duration_s}
        onChange={(duration_s) => setParams(nodeId, { ...params, duration_s })}
      />
      <ParamSelect
        label={t("resolution")}
        value={params.resolution}
        options={VIDEO_RESOLUTIONS}
        onChange={(resolution) => setParams(nodeId, { ...params, resolution })}
      />
      <label className="toggle" title={t("audio_title")}>
        <input
          type="checkbox"
          checked={params.generate_audio}
          onChange={(e) => setParams(nodeId, { ...params, generate_audio: e.target.checked })}
        />
        {t("audio")}
      </label>
    </>
  );
}
